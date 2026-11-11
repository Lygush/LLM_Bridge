package dev.llmbridge.client

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import android.util.LruCache
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException

enum class Conn { STOPPED, LINKING, CONNECTING, ONLINE, OFFLINE }

data class ConnState(val conn: Conn = Conn.STOPPED, val message: String = "")

/**
 * Связь с мостом и состояние чатов. Один экземпляр на приложение (App.repo).
 *
 * Источник истины — ПК: здесь только отражение. Соединение держит цикл сессии:
 * Wi-Fi Direct → проверка моста → WebSocket событий; при обрыве — повтор с паузой.
 * Все изменения состояния выполняются в главном потоке.
 */
class BridgeRepository(context: Context) {
    private val app = context.applicationContext
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    val p2p = P2pConnector(app)

    private val _pairing = MutableStateFlow(Pairing.load(app))
    val pairing: StateFlow<Pairing?> = _pairing.asStateFlow()

    private val _conn = MutableStateFlow(ConnState())
    val conn: StateFlow<ConnState> = _conn.asStateFlow()

    private val _status = MutableStateFlow(ServerStatus())
    val status: StateFlow<ServerStatus> = _status.asStateFlow()

    private val _chats = MutableStateFlow<List<ChatInfo>>(emptyList())
    val chats: StateFlow<List<ChatInfo>> = _chats.asStateFlow()

    private val _currentChatId = MutableStateFlow<Long?>(null)
    val currentChatId: StateFlow<Long?> = _currentChatId.asStateFlow()

    private val _messages = MutableStateFlow<List<Msg>>(emptyList())
    val messages: StateFlow<List<Msg>> = _messages.asStateFlow()

    private val _defaultPrompt = MutableStateFlow("")
    val defaultPrompt: StateFlow<String> = _defaultPrompt.asStateFlow()

    private val _defaultSettings = MutableStateFlow(GenSettings())
    val defaultSettings: StateFlow<GenSettings> = _defaultSettings.asStateFlow()

    private val _profiles = MutableStateFlow<List<ImageProfile>>(emptyList())
    val profiles: StateFlow<List<ImageProfile>> = _profiles.asStateFlow()
    private val _imageRoutes = MutableStateFlow<List<ImageRoute>>(emptyList())
    val imageRoutes: StateFlow<List<ImageRoute>> = _imageRoutes.asStateFlow()
    private val _imageQuality = MutableStateFlow("normal")
    val imageQuality: StateFlow<String> = _imageQuality.asStateFlow()

    private val _recommended = MutableStateFlow(Recommended())
    val recommended: StateFlow<Recommended> = _recommended.asStateFlow()

    /** Память открытого чата (загружается, когда открыта панель памяти). */
    private val _memory = MutableStateFlow<MemoryInfo?>(null)
    val memory: StateFlow<MemoryInfo?> = _memory.asStateFlow()

    /** Карточки персонажей и персон, описание их полей, ход рисования портретов. */
    private val _cards = MutableStateFlow<List<Card>>(emptyList())
    val cards: StateFlow<List<Card>> = _cards.asStateFlow()
    private val _cardFields = MutableStateFlow<Map<String, List<CardField>>>(emptyMap())
    val cardFields: StateFlow<Map<String, List<CardField>>> = _cardFields.asStateFlow()
    private val _cardStages = MutableStateFlow<Map<Long, CardStage>>(emptyMap())
    val cardStages: StateFlow<Map<Long, CardStage>> = _cardStages.asStateFlow()

    /** Отношения персонажей открытого чата и монеты персоны. */
    private val _relations = MutableStateFlow<List<Relation>>(emptyList())
    val relations: StateFlow<List<Relation>> = _relations.asStateFlow()
    private val _coins = MutableStateFlow<Int?>(null)
    val coins: StateFlow<Int?> = _coins.asStateFlow()
    private var walletPersona = 0L

    /** Показывать ли отношения числами (настройка телефона); иначе — только подсказки. */
    private val prefs = app.getSharedPreferences("settings", Context.MODE_PRIVATE)
    private val _showRelations = MutableStateFlow(prefs.getString("show_relations", "1") == "1")
    val showRelations: StateFlow<Boolean> = _showRelations.asStateFlow()

    fun setShowRelations(v: Boolean) {
        _showRelations.value = v
        prefs.edit().putString("show_relations", if (v) "1" else "0").apply()
    }

    /** Фоны мест открытой истории: ключ места → картинка; и какие ещё рисуются. */
    private val _vnBackgrounds = MutableStateFlow<Map<String, String>>(emptyMap())
    val vnBackgrounds: StateFlow<Map<String, String>> = _vnBackgrounds.asStateFlow()
    private val _vnPending = MutableStateFlow<Set<String>>(emptySet())
    val vnPending: StateFlow<Set<String>> = _vnPending.asStateFlow()

    /** Предложения модели обновить карточки («персонаж меняется»). */
    private val _proposals = MutableStateFlow<List<Proposal>>(emptyList())
    val proposals: StateFlow<List<Proposal>> = _proposals.asStateFlow()

    /** Сообщения для пользователя (ошибки действий). */
    private val _events = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val events: SharedFlow<String> = _events.asSharedFlow()

    private var client: BridgeClient? = _pairing.value?.let { BridgeClient(it) }
    private var session: Job? = null
    private var socket: WebSocket? = null
    private var reloadJob: Job? = null
    private val wake = Channel<Unit>(Channel.CONFLATED)
    private var autoOpen = true   // при первом подключении открыть последний чат

    // Чаты, удалённые на телефоне без связи: исчезают сразу, на ПК удаляются при подключении.
    private val cache = app.getSharedPreferences("cache", Context.MODE_PRIVATE)
    private val pendingDeletes = mutableSetOf<Long>().apply {
        cache.getString("delete_chats", "")!!.split(',').mapNotNullTo(this) { it.toLongOrNull() }
    }

    init {
        // последний известный список чатов — чтобы видеть и удалять их без связи с ПК
        if (_pairing.value != null) {
            runCatching { JSONArray(cache.getString("chats", "[]") ?: "[]") }.getOrNull()?.let { a ->
                _chats.value = ChatInfo.list(a).filter { it.id !in pendingDeletes }
            }
        }
    }

    private fun setChats(list: List<ChatInfo>) {
        _chats.value = list.filter { it.id !in pendingDeletes }
        cache.edit().putString("chats", JSONArray().apply { _chats.value.forEach { put(it.toJson()) } }
            .toString()).apply()
    }

    private fun savePending() {
        cache.edit().putString("delete_chats", pendingDeletes.joinToString(",")).apply()
    }

    /** Отправить на ПК удаления, сделанные без связи. */
    private suspend fun flushDeletes() {
        val c = client ?: return
        for (id in pendingDeletes.toList()) {
            try {
                c.delete("/api/chats/$id")
            } catch (e: ApiException) {
                if (e.code != 404) continue   // 404 — на ПК его уже нет
            } catch (e: IOException) {
                return
            }
            pendingDeletes.remove(id)
            savePending()
        }
    }

    // ============================================================ сопряжение

    fun pair(p: Pairing) {
        stopSession(disconnectLink = true)
        p.save(app)
        client = BridgeClient(p)
        _pairing.value = p
        clearData()
        // сессию запустит LinkService, который стартует экран после проверки разрешений
    }

    fun forget() {
        stopSession(disconnectLink = true)
        Pairing.clear(app)
        client = null
        _pairing.value = null
        clearData()
    }

    private fun clearData() {
        setChats(emptyList())
        pendingDeletes.clear()
        savePending()
        _messages.value = emptyList()
        _currentChatId.value = null
        _status.value = ServerStatus()
        _memory.value = null
        autoOpen = true
    }

    // =============================================================== сессия

    fun startSession() {
        if (session?.isActive == true) {
            wake.trySend(Unit)
            return
        }
        if (_pairing.value == null) return
        session = scope.launch { runLoop() }
    }

    fun stopSession(disconnectLink: Boolean) {
        session?.cancel()
        session = null
        closeSocket()
        if (disconnectLink) p2p.disconnect()
        _conn.value = ConnState(Conn.STOPPED)
    }

    /** Разорвать текущее соединение и сразу подключиться заново. */
    fun reconnectNow() {
        if (session?.isActive != true) {
            startSession()
            return
        }
        closeSocket()
        wake.trySend(Unit)
    }

    /** Приложение снова на экране: если связи нет — не ждать паузу между попытками. */
    fun onForeground() {
        if (session?.isActive != true) {
            if (_pairing.value != null && _conn.value.conn != Conn.STOPPED) startSession()
            return
        }
        if (_conn.value.conn != Conn.ONLINE) wake.trySend(Unit)
    }

    private fun closeSocket() {
        socket?.cancel()
        socket = null
    }

    private fun offline(msg: String) {
        _conn.value = ConnState(Conn.OFFLINE, msg)
    }

    private suspend fun waitWake(ms: Long) {
        withTimeoutOrNull(ms) { wake.receive() }
    }

    private suspend fun runLoop() {
        var backoff = 1_000L
        while (currentCoroutineContext().isActive) {
            val p = _pairing.value ?: break
            val c = client ?: break

            var api: Int? = c.ping()
            if (api == null) {
                // моста не видно — входим в группу Wi-Fi Direct (если ещё не в ней)
                if (p2p.state.value.phase != LinkPhase.CONNECTED) {
                    _conn.value = ConnState(Conn.LINKING, "Подключение к ${p.ssid}…")
                    try {
                        p2p.connect(p)
                    } catch (e: SecurityException) {
                        offline("Нет разрешения на Wi-Fi Direct")
                        waitWake(10_000)
                        continue
                    }
                    withTimeoutOrNull(35_000) {
                        p2p.state.first { it.phase == LinkPhase.CONNECTED || it.phase == LinkPhase.FAILED }
                    }
                }
                // адрес по DHCP приходит не сразу
                for (i in 0 until 5) {
                    api = c.ping()
                    if (api != null) break
                    delay(1_000)
                }
            }
            val version = api
            if (version == null) {
                val ls = p2p.state.value
                offline(if (ls.phase == LinkPhase.FAILED && ls.message.isNotEmpty()) ls.message
                        else "ПК не отвечает")
                waitWake(backoff)
                backoff = (backoff * 2).coerceAtMost(15_000)
                continue
            }
            if (version < 2) {
                offline("Обновите LLM Bridge на ПК")
                waitWake(15_000)
                continue
            }

            _conn.value = ConnState(Conn.CONNECTING, "Синхронизация…")
            val hello = CompletableDeferred<Unit>()
            val closed = CompletableDeferred<String>()
            val ws = c.openSocket(listener(hello, closed))
            socket = ws
            if (withTimeoutOrNull(6_000) { hello.await() } == null) {
                ws.cancel()
                if (socket === ws) socket = null
                offline(if (closed.isCompleted) closed.await() else "Мост не отвечает")
                waitWake(backoff)
                backoff = (backoff * 2).coerceAtMost(15_000)
                continue
            }
            backoff = 1_000L
            _conn.value = ConnState(Conn.ONLINE)
            val reason = closed.await()
            if (socket === ws) socket = null
            offline(reason)
            waitWake(1_000)
        }
    }

    private fun listener(hello: CompletableDeferred<Unit>, closed: CompletableDeferred<String>) =
        object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                scope.launch {
                    if (socket === webSocket) handleEvent(text, hello)
                }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                closed.complete("Соединение закрыто")
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                closed.complete(if (response?.code == 401) "Неверный токен — сопрягите заново"
                                else "Связь с ПК потеряна")
            }
        }

    // ============================================================== события

    private fun handleEvent(text: String, hello: CompletableDeferred<Unit>) {
        val o = runCatching { JSONObject(text) }.getOrNull() ?: return
        val current = _currentChatId.value
        when (o.optString("type")) {
            "hello" -> {
                _status.value = ServerStatus.from(o.optJSONObject("status"))
                setChats(ChatInfo.list(o.optJSONArray("chats")))
                hello.complete(Unit)
                onHello()
            }
            "status" -> _status.value = ServerStatus.from(o.optJSONObject("status"))
            "busy" -> _status.value = _status.value.copy(busy = o.optBoolean("busy"))
            "chat.updated" -> o.optJSONObject("chat")?.let { upsertChat(ChatInfo.from(it)) }
            "chat.deleted" -> removeChat(o.optLong("id"))
            "chat.changed" -> if (o.optLong("chat_id") == current) scheduleReload()
            "message.added" -> if (o.optLong("chat_id") == current) {
                o.optJSONObject("message")?.let { addMessage(Msg.from(it)) }
            }
            "message.delta" -> if (o.optLong("chat_id") == current) applyDelta(o)
            "message.done", "message.updated" -> if (o.optLong("chat_id") == current) {
                o.optJSONObject("message")?.let { replaceMessage(Msg.from(it)) }
            }
            "message.stage" -> if (o.optLong("chat_id") == current) {
                setStage(o.optLong("id"), o.optString("stage"), o.optInt("done", -1), o.optInt("total", -1))
            }
            "card.updated" -> o.optJSONObject("card")?.let { upsertCard(Card.from(it)) }
            "relation.updated" -> if (o.optLong("chat_id") == current) {
                scope.launch { loadRelations() }
            }
            "card.proposal" -> o.optJSONObject("proposal")?.let {
                val p = Proposal.from(it)
                _proposals.value = _proposals.value.filter { x -> x.id != p.id } + p
            }
            "card.proposal.closed" -> _proposals.value = _proposals.value.filter { it.id != o.optLong("id") }
            "vn.background" -> if (o.optLong("chat_id") == current) {
                val key = o.optString("key")
                when (o.optString("state")) {
                    "queued" -> _vnPending.value = _vnPending.value + key
                    "ready" -> {
                        _vnPending.value = _vnPending.value - key
                        o.optJSONObject("image")?.strOrNull("name")?.let { _vnBackgrounds.value = _vnBackgrounds.value + (key to it) }
                    }
                    else -> _vnPending.value = _vnPending.value - key
                }
            }
            "wallet" -> if (o.optLong("persona_id") == walletPersona) _coins.value = o.optInt("coins")
            "image.routes" -> applyImageInfo(o)
            "lore.updated" -> {
                val id = o.optLong("card_id")
                if (_lore.value?.first == id) scope.launch { loadLore(id) }
            }
            "card.deleted" -> _cards.value = _cards.value.filter { it.id != o.optLong("id") }
            "card.stage" -> {
                val id = o.optLong("id")
                when (val st = o.optString("stage")) {
                    "done" -> _cardStages.value = _cardStages.value - id
                    "error" -> _events.tryEmit("Портрет не нарисован: ${o.optString("error")}")
                    else -> _cardStages.value = _cardStages.value +
                        (id to CardStage(st, o.optInt("done", 0), o.optInt("total", 0)))
                }
            }
            "memory.updated" -> {
                val cid = o.optLong("chat_id")
                if (cid == current && _memory.value?.chatId == cid) scope.launch { loadMemory() }
            }
        }
    }

    private fun onHello() {
        scope.launch {
            flushDeletes()
            loadCards()   // аватарки персонажей в списке чатов
            loadProposals()
            guard {
                val s = client?.get("/api/settings") ?: return@guard
                _defaultPrompt.value = s.strOrNull("default_system_prompt") ?: ""
                _defaultSettings.value = GenSettings.from(s.optJSONObject("default_settings"))
                _recommended.value = Recommended.from(s.optJSONObject("recommended"))
                migrateLocalPrompt()
            }
        }
        val cur = _currentChatId.value
        when {
            cur != null && _chats.value.any { it.id == cur } -> {
                scheduleReload(0)
                scope.launch { delay(400); loadRelations(); nudge() }
            }
            cur != null -> {   // чат удалили, пока не было связи
                _currentChatId.value = null
                _messages.value = emptyList()
            }
            autoOpen && _chats.value.isNotEmpty() -> {
                autoOpen = false
                openChat(_chats.value.first().id)
            }
        }
    }

    /** Системный промпт из прошлой версии приложения хранился на телефоне. */
    private suspend fun migrateLocalPrompt() {
        val prefs = app.getSharedPreferences("settings", Context.MODE_PRIVATE)
        val old = prefs.getString("system_prompt", "").orEmpty()
        if (old.isNotBlank() && _defaultPrompt.value.isBlank()) {
            client?.put("/api/settings", JSONObject().put("default_system_prompt", old))
            _defaultPrompt.value = old
        }
        if (old.isNotEmpty()) prefs.edit().remove("system_prompt").apply()
    }

    private fun upsertChat(c: ChatInfo) {
        setChats((_chats.value.filter { it.id != c.id } + c).sortedByDescending { it.updated })
    }

    private fun removeChat(id: Long) {
        setChats(_chats.value.filter { it.id != id })
        if (_currentChatId.value == id) {
            _currentChatId.value = null
            _messages.value = emptyList()
        }
    }

    private fun addMessage(m: Msg) {
        val list = _messages.value
        if (list.any { it.id == m.id }) return
        if (m.parentId == list.lastOrNull()?.id) _messages.value = list + m else scheduleReload()
    }

    private fun replaceMessage(m: Msg) {
        val list = _messages.value
        val i = list.indexOfFirst { it.id == m.id }
        if (i < 0) {
            scheduleReload()
            return
        }
        _messages.value = list.toMutableList().also { it[i] = m }
    }

    private fun setStage(id: Long, stage: String, done: Int = -1, total: Int = -1) {
        val list = _messages.value
        val i = list.indexOfFirst { it.id == id }
        if (i < 0) return
        _messages.value = list.toMutableList().also {
            val m = it[i]
            it[i] = if (total > 0) m.copy(stage = stage, progressDone = done.coerceAtLeast(0), progressTotal = total)
                    else m.copy(stage = stage)
        }
    }

    private fun applyDelta(o: JSONObject) {
        val id = o.optLong("id")
        val list = _messages.value
        val i = list.indexOfFirst { it.id == id }
        if (i < 0) {
            scheduleReload()
            return
        }
        val m = list[i]
        val c = merge(m.content, o.optInt("offset"), o.optString("content"))
        val r = merge(m.reasoning, o.optInt("r_offset"), o.optString("reasoning"))
        if (c == null || r == null) {   // пропущен кусок — перечитать с ПК
            scheduleReload()
            return
        }
        _messages.value = list.toMutableList().also {
            it[i] = m.copy(content = c, reasoning = r, status = "generating", stage = "generating")
        }
    }

    /** Смещения — в единицах UTF-16, как String.length. null — разрыв. */
    private fun merge(cur: String, offset: Int, piece: String): String? = when {
        piece.isEmpty() -> cur
        offset == cur.length -> cur + piece
        offset < cur.length ->
            if (offset + piece.length > cur.length) cur + piece.substring(cur.length - offset) else cur
        else -> null
    }

    private fun scheduleReload(delayMs: Long = 150) {
        if (reloadJob?.isActive == true) return
        reloadJob = scope.launch {
            delay(delayMs)
            _currentChatId.value?.let { loadChat(it) }
        }
    }

    private suspend fun loadChat(id: Long) {
        val c = client ?: return
        try {
            val o = c.get("/api/chats/$id")
            applyChatResponse(o)
        } catch (e: ApiException) {
            if (e.code == 404) removeChat(id) else _events.tryEmit(e.message ?: "Ошибка")
        } catch (e: IOException) {
            // связь восстановит цикл сессии, после hello чат перечитается
        }
    }

    private fun applyChatResponse(o: JSONObject) {
        val chat = o.optJSONObject("chat")?.let { ChatInfo.from(it) } ?: return
        upsertChat(chat)
        if (chat.id == _currentChatId.value) {
            _messages.value = Msg.list(o.optJSONArray("messages"))
        }
    }

    // ============================================================= действия

    private suspend fun <T> guard(block: suspend () -> T): T? = try {
        block()
    } catch (e: ApiException) {
        _events.tryEmit(e.message ?: "Ошибка")
        null
    } catch (e: IOException) {
        _events.tryEmit("Нет связи с ПК")
        null
    }

    fun openChat(id: Long) {
        autoOpen = false
        if (_currentChatId.value != id) {
            _currentChatId.value = id
            _messages.value = emptyList()
            _memory.value = null
            _relations.value = emptyList()
            _vnBackgrounds.value = emptyMap()
            _vnPending.value = emptySet()
        }
        scope.launch {
            loadChat(id)
            loadRelations()
            nudge()
        }
    }

    /** Пустой экран нового чата; сам чат создаётся на ПК при первом сообщении. */
    fun newChat() {
        autoOpen = false
        _relations.value = emptyList()
        _coins.value = null
        _currentChatId.value = null
        _messages.value = emptyList()
        _memory.value = null
    }

    // ============================================================ картинки

    private val imageCache = object : LruCache<String, Bitmap>(48 * 1024 * 1024) {
        override fun sizeOf(key: String, value: Bitmap) = value.byteCount
    }

    /** Картинка с ПК, уменьшенная до ~800 px по длинной стороне (для показа в чате). */
    suspend fun image(name: String): Bitmap? {
        imageCache.get(name)?.let { return it }
        val c = client ?: return null
        val data = try {
            c.bytes("/api/images/$name")
        } catch (e: IOException) {
            return null
        }
        val bmp = kotlinx.coroutines.withContext(Dispatchers.Default) {
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeByteArray(data, 0, data.size, bounds)
            var sample = 1
            while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= 800) sample *= 2
            BitmapFactory.decodeByteArray(data, 0, data.size,
                BitmapFactory.Options().apply { inSampleSize = sample })
        } ?: return null
        imageCache.put(name, bmp)
        return bmp
    }

    suspend fun send(text: String, images: List<ByteArray> = emptyList(), replyAs: Long? = null,
                     directive: Boolean = false, choice: Boolean = false): Boolean {
        val c = client ?: return false
        return guard {
            var cid = _currentChatId.value
            if (cid == null) {
                val chat = ChatInfo.from(c.post("/api/chats").getJSONObject("chat"))
                upsertChat(chat)
                cid = chat.id
                _currentChatId.value = cid
                _messages.value = emptyList()
            }
            val body = JSONObject().put("content", text)
            replyAs?.let { body.put("reply_as", it) }
            if (directive) body.put("directive", true)
            if (choice) body.put("choice", true)
            if (images.isNotEmpty()) {
                val arr = org.json.JSONArray()
                images.forEach { arr.put(Base64.encodeToString(it, Base64.NO_WRAP)) }
                body.put("images", arr)
            }
            val o = c.post("/api/chats/$cid/messages", body)
            o.optJSONObject("chat")?.let { upsertChat(ChatInfo.from(it)) }
            Msg.list(o.optJSONArray("messages")).forEach { addMessage(it) }
            true
        } ?: false
    }

    suspend fun cancel() {
        val cid = _currentChatId.value ?: return
        guard { client?.post("/api/chats/$cid/cancel") }
    }

    /** Новый вариант ответа; wish — переписать с пожеланием («короче», «подробнее»). */
    suspend fun regenerate(msgId: Long, wish: String = "") {
        guard {
            val body = JSONObject()
            if (wish.isNotBlank()) body.put("wish", wish)
            client?.post("/api/messages/$msgId/regenerate", body)?.let { applyChatResponse(it) }
        }
    }

    // ============================================================ лорбук и сцены

    private val _lore = MutableStateFlow<Pair<Long, List<LoreEntry>>?>(null)   // мир → записи
    val lore: StateFlow<Pair<Long, List<LoreEntry>>?> = _lore.asStateFlow()

    suspend fun loadLore(worldId: Long) {
        guard {
            val o = client?.get("/api/cards/$worldId/lore") ?: return@guard
            _lore.value = worldId to LoreEntry.list(o.optJSONArray("lore"))
        }
    }

    suspend fun saveLore(worldId: Long, e: LoreEntry) {
        guard {
            val body = JSONObject().put("title", e.title).put("keys", e.keys)
                .put("content", e.content).put("always", e.always)
            if (e.id == 0L) client?.post("/api/cards/$worldId/lore", body)
            else client?.patch("/api/lore/${e.id}", body)
        }
        loadLore(worldId)
    }

    suspend fun deleteLore(worldId: Long, id: Long) {
        guard { client?.delete("/api/lore/$id") }
        loadLore(worldId)
    }

    /** Модель дописывает лорбук по просьбе своими словами. */
    suspend fun generateLore(worldId: Long, text: String): Boolean = guard {
        val o = client?.postSlow("/api/cards/$worldId/lore/generate", JSONObject().put("text", text))
            ?: return@guard false
        _lore.value = worldId to LoreEntry.list(o.optJSONArray("lore"))
        true
    } ?: false

    /** Новая сцена: чат с несколькими персонажами, квест или история. Сразу открывается. */
    suspend fun createScene(mode: String, characterIds: List<Long>, personaId: Long?, worldId: Long?,
                            setup: String, style: String = "messenger"): Boolean {
        val c = client ?: return false
        return guard {
            val body = JSONObject().put("mode", mode).put("setup", setup).put("chat_style", style)
                .put("character_ids", JSONArray().apply { characterIds.forEach { put(it) } })
            personaId?.let { body.put("persona_id", it) }
            worldId?.let { body.put("world_id", it) }
            val chat = ChatInfo.from(c.post("/api/scenes", body).getJSONObject("chat"))
            upsertChat(chat)
            openChat(chat.id)
            true
        } ?: false
    }

    // ============================================== отношения, инициатива, подарки

    suspend fun loadRelations() {
        val cid = _currentChatId.value ?: run { _relations.value = emptyList(); _coins.value = null; return }
        try {   // тихо: это дополнение к чату, ошибка связи уже показана при его открытии
            val o = client?.get("/api/chats/$cid/relations") ?: return
            val a = o.optJSONArray("relations")
            _relations.value = (0 until (a?.length() ?: 0)).mapNotNull { i -> a?.optJSONObject(i)?.let { Relation.from(it) } }
            walletPersona = o.optLong("persona_id")
            _coins.value = o.optInt("coins")
        } catch (e: IOException) {
            // ApiException — тоже IOException
        }
    }

    suspend fun resetRelations() {
        val cid = _currentChatId.value ?: return
        guard { client?.delete("/api/chats/$cid/relations") }
        loadRelations()
    }

    /** Открыли чат: персонаж может написать первым, если давно не общались (решает ПК). */
    suspend fun nudge() {
        val cid = _currentChatId.value ?: return
        val c = client ?: return
        if (_conn.value.conn != Conn.ONLINE) return
        val chat = _chats.value.firstOrNull { it.id == cid } ?: return
        if (chat.mode != "chat" || chat.cast.isEmpty() || !chat.initiative) return
        try {
            val o = c.post("/api/chats/$cid/nudge")
            if (o.optBoolean("started")) Msg.list(o.optJSONArray("messages")).forEach { addMessage(it) }
        } catch (e: IOException) {
            // не вышло — не страшно, это необязательно
        }
    }

    /** Подарок за монеты; цену назначает модель на ПК. */
    suspend fun gift(text: String, to: Long?): Boolean {
        val cid = _currentChatId.value ?: return false
        return guard {
            val body = JSONObject().put("text", text)
            to?.let { body.put("to", it) }
            val o = client?.post("/api/chats/$cid/gift", body) ?: return@guard false
            Msg.list(o.optJSONArray("messages")).forEach { addMessage(it) }
            _coins.value = o.optInt("coins")
            _events.tryEmit("Подарок стоил ${o.optInt("price")} монет, осталось ${o.optInt("coins")}")
            true
        } ?: false
    }

    /** Занять у персонажа (решает он сам) или вернуть долг. */
    suspend fun money(action: String, amount: Int, to: Long?): Boolean {
        val cid = _currentChatId.value ?: return false
        return guard {
            val body = JSONObject().put("action", action).put("amount", amount)
            to?.let { body.put("to", it) }
            val o = client?.post("/api/chats/$cid/money", body) ?: return@guard false
            Msg.list(o.optJSONArray("messages")).forEach { addMessage(it) }
            if (o.has("coins")) _coins.value = o.optInt("coins")
            true
        } ?: false
    }

    /** Свидание: отдельная история-новелла с персонажем; сразу открывается. */
    suspend fun startDate(setup: String, to: Long?): Boolean {
        val cid = _currentChatId.value ?: return false
        return guard {
            val body = JSONObject().put("setup", setup)
            to?.let { body.put("to", it) }
            val chat = ChatInfo.from(client?.post("/api/chats/$cid/date", body)?.getJSONObject("chat")
                ?: return@guard false)
            upsertChat(chat)
            openChat(chat.id)
            true
        } ?: false
    }

    /** Завершить вечер: итог уходит в отношения, возвращаемся в исходный чат. */
    suspend fun finishDate() {
        val cid = _currentChatId.value ?: return
        guard {
            val o = client?.post("/api/chats/$cid/date/finish") ?: return@guard
            o.strOrNull("summary")?.let { _events.tryEmit("Итог вечера: $it") }
            val back = o.optLong("chat_id")
            if (back > 0) openChat(back)
        }
    }

    /** «В предыдущих сериях» — краткий пересказ истории. */
    suspend fun recap(): String? = guard {
        val cid = _currentChatId.value ?: return@guard null
        client?.get("/api/chats/$cid/recap")?.strOrNull("recap")
    }

    /** Изменить одну настройку чата, не трогая остальные (стиль, инициатива). */
    suspend fun setChatOption(key: String, value: Any?) {
        val cid = _currentChatId.value ?: return
        guard {
            client?.patch("/api/chats/$cid", JSONObject().put("set", JSONObject().put(key, value ?: JSONObject.NULL)))
                ?.optJSONObject("chat")?.let { upsertChat(ChatInfo.from(it)) }
        }
    }

    suspend fun loadProposals() {
        guard {
            val a = client?.get("/api/proposals")?.optJSONArray("proposals") ?: return@guard
            _proposals.value = (0 until a.length()).mapNotNull { i -> a.optJSONObject(i)?.let { Proposal.from(it) } }
        }
    }

    suspend fun answerProposal(id: Long, accept: Boolean) {
        _proposals.value = _proposals.value.filter { it.id != id }
        guard { client?.post("/api/proposals/$id", JSONObject().put("accept", accept)) }
    }

    suspend fun gallery(): List<GalleryItem> = guard {
        val cid = _currentChatId.value ?: return@guard emptyList()
        val a = client?.get("/api/chats/$cid/gallery")?.optJSONArray("items") ?: return@guard emptyList()
        (0 until a.length()).mapNotNull { i ->
            a.optJSONObject(i)?.let { GalleryItem(it.optString("name"), it.strOrNull("caption") ?: "", it.optString("kind")) }
        }
    } ?: emptyList()

    suspend fun forks(): List<Fork> = guard {
        val cid = _currentChatId.value ?: return@guard emptyList()
        val a = client?.get("/api/chats/$cid/choices")?.optJSONArray("forks") ?: return@guard emptyList()
        fun strs(x: JSONArray?) = if (x == null) emptyList() else (0 until x.length()).map { x.optString(it) }
        (0 until a.length()).mapNotNull { i ->
            a.optJSONObject(i)?.let { Fork(strs(it.optJSONArray("options")), it.strOrNull("taken"), strs(it.optJSONArray("tried"))) }
        }
    } ?: emptyList()

    /** Нарисовать фон места по кнопке. */
    suspend fun drawBackground(name: String) {
        val cid = _currentChatId.value ?: return
        guard { client?.post("/api/chats/$cid/vn/background", JSONObject().put("name", name)) }
    }

    suspend fun loadVn() {
        val cid = _currentChatId.value ?: return
        guard {
            val o = client?.get("/api/chats/$cid/vn") ?: return@guard
            val bg = o.optJSONObject("backgrounds")
            _vnBackgrounds.value = buildMap<String, String> {
                bg?.keys()?.forEach { k -> bg.optJSONObject(k)?.strOrNull("name")?.let { put(k, it) } }
            }
            val p = o.optJSONArray("pending")
            _vnPending.value = (0 until (p?.length() ?: 0)).map { p!!.optString(it) }.toSet()
        }
    }

    /** Нарисовать набор эмоций персонажа (для новеллы). */
    suspend fun drawSprites(cardId: Long) {
        _cardStages.value = _cardStages.value + (cardId to CardStage("queued"))
        if (guard { client?.post("/api/cards/$cardId/sprites") } == null) {
            _cardStages.value = _cardStages.value - cardId
        }
    }

    suspend fun saveState(msgId: Long, state: QuestState) {
        guard {
            client?.patch("/api/messages/$msgId/state", JSONObject().put("state", state.toJson()))
                ?.optJSONObject("message")?.let { replaceMessage(Msg.from(it)) }
        }
    }

    suspend fun selectVariant(msgId: Long) {
        guard { client?.post("/api/messages/$msgId/select")?.let { applyChatResponse(it) } }
    }

    suspend fun editMessage(msgId: Long, text: String) {
        guard {
            client?.patch("/api/messages/$msgId", JSONObject().put("content", text))
                ?.optJSONObject("message")?.let { replaceMessage(Msg.from(it)) }
        }
    }

    /** Правка своего сообщения с повторной отправкой: новая ветка и новый ответ. */
    suspend fun resend(userMsgId: Long, text: String) {
        val cid = _currentChatId.value ?: return
        guard {
            client?.post("/api/chats/$cid/messages",
                JSONObject().put("content", text).put("replace_id", userMsgId))
            loadChat(cid)
        }
    }

    suspend fun deleteMessage(msgId: Long) {
        guard { client?.delete("/api/messages/$msgId")?.let { applyChatResponse(it) } }
    }

    suspend fun renameChat(id: Long, title: String) {
        guard {
            client?.patch("/api/chats/$id", JSONObject().put("title", title))
                ?.optJSONObject("chat")?.let { upsertChat(ChatInfo.from(it)) }
        }
    }

    /** Удаление работает и без связи: чат пропадает сразу, на ПК — при подключении. */
    suspend fun deleteChat(id: Long) {
        pendingDeletes.add(id)
        savePending()
        removeChat(id)
        if (_conn.value.conn == Conn.ONLINE) {
            flushDeletes()
        }
        if (id in pendingDeletes) _events.tryEmit("Чат удалён на телефоне; на ПК удалится при подключении")
    }

    /** Промпт текущего чата; без открытого чата — промпт по умолчанию для новых. */
    suspend fun setSystemPrompt(text: String, makeDefault: Boolean) {
        val c = client ?: return
        val cid = _currentChatId.value
        guard {
            if (cid == null) {
                c.put("/api/settings", JSONObject().put("default_system_prompt", text))
                _defaultPrompt.value = text.trim()
            } else {
                val o = c.patch("/api/chats/$cid",
                    JSONObject().put("system_prompt", text).put("make_default", makeDefault))
                o.optJSONObject("chat")?.let { upsertChat(ChatInfo.from(it)) }
                if (makeDefault) _defaultPrompt.value = text.trim()
            }
        }
    }

    // ============================================================ рисование

    suspend fun loadProfiles() {
        guard {
            val o = client?.get("/api/image/profiles") ?: return@guard
            applyImageInfo(o)
        }
    }

    private fun applyImageInfo(o: JSONObject) {
        o.optJSONArray("profiles")?.let { a ->
            _profiles.value = (0 until a.length()).mapNotNull { i -> a.optJSONObject(i)?.let { ImageProfile.from(it) } }
        }
        o.optJSONArray("routes")?.let { a ->
            _imageRoutes.value = (0 until a.length()).mapNotNull { i -> a.optJSONObject(i)?.let { ImageRoute.from(it) } }
        }
        if (o.has("quality")) _imageQuality.value = o.optString("quality", "normal")
    }

    /** Закрепить модель за задачей рисования ("" — «Авто»). */
    suspend fun setImageRoute(task: String, profile: String) {
        guard {
            client?.put("/api/image/routes", JSONObject().put("routes", JSONObject().put(task, profile)))
                ?.let { applyImageInfo(it) }
        }
    }

    suspend fun setImageQuality(q: String) {
        guard { client?.put("/api/image/routes", JSONObject().put("quality", q))?.let { applyImageInfo(it) } }
    }

    /** Нарисовать в текущем чате (или в новом). Ответом модели станет картинка. */
    suspend fun draw(prompt: String, profile: String?, width: Int, height: Int, steps: Int?, seed: Long?,
                     enhance: Boolean = false, likeness: Boolean = true): Boolean {
        val c = client ?: return false
        return guard {
            var cid = _currentChatId.value
            if (cid == null) {
                val chat = ChatInfo.from(c.post("/api/chats").getJSONObject("chat"))
                upsertChat(chat)
                cid = chat.id
                _currentChatId.value = cid
                _messages.value = emptyList()
            }
            val body = JSONObject().put("prompt", prompt).put("width", width).put("height", height)
            profile?.let { body.put("profile", it) }
            steps?.let { body.put("steps", it) }
            seed?.let { body.put("seed", it) }
            if (enhance) body.put("enhance", true)
            if (!likeness) body.put("likeness", false)
            val o = c.post("/api/chats/$cid/images", body)
            o.optJSONObject("chat")?.let { upsertChat(ChatInfo.from(it)) }
            Msg.list(o.optJSONArray("messages")).forEach { addMessage(it) }
            true
        } ?: false
    }

    /** Короткий запрос → подробный английский промпт текстовой моделью (с учётом чата). */
    suspend fun enhancePrompt(text: String): Pair<String, String>? {
        val c = client ?: return null
        return guard {
            val body = JSONObject().put("text", text)
            _currentChatId.value?.let { body.put("chat_id", it) }
            val o = c.postSlow("/api/image/enhance", body)
            (o.strOrNull("prompt") ?: "") to (o.strOrNull("negative") ?: "")
        }?.takeIf { it.first.isNotBlank() }
    }

    /** Перерисовать картинку сообщения на месте (новый seed, текст ответа не меняется). */
    suspend fun redraw(msgId: Long) {
        guard {
            val o = client?.post("/api/messages/$msgId/redraw") ?: return@guard
            o.optJSONObject("message")?.let { replaceMessage(Msg.from(it)) }
        }
    }

    /** Сохранить картинку в полном размере в галерею (Pictures/LLM Bridge). */
    suspend fun saveImage(name: String): Boolean {
        val c = client ?: return false
        val data = guard { c.bytes("/api/images/$name") } ?: return false
        return kotlinx.coroutines.withContext(Dispatchers.IO) {
            val png = name.endsWith(".png", ignoreCase = true)
            val values = android.content.ContentValues().apply {
                put(android.provider.MediaStore.Images.Media.DISPLAY_NAME, name)
                put(android.provider.MediaStore.Images.Media.MIME_TYPE, if (png) "image/png" else "image/jpeg")
                put(android.provider.MediaStore.Images.Media.RELATIVE_PATH, "Pictures/LLM Bridge")
            }
            val resolver = app.contentResolver
            val uri = resolver.insert(android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                ?: return@withContext false
            try {
                resolver.openOutputStream(uri)?.use { it.write(data) } ?: return@withContext false
                true
            } catch (e: IOException) {
                resolver.delete(uri, null, null)
                false
            }
        }.also { ok -> _events.tryEmit(if (ok) "Сохранено в «Галерея → LLM Bridge»" else "Не удалось сохранить") }
    }

    // =============================================================== карточки

    private fun upsertCard(c: Card) {
        _cards.value = listOf(c) + _cards.value.filter { it.id != c.id }
    }

    suspend fun loadCards() {
        guard {
            val o = client?.get("/api/cards") ?: return@guard
            val a = o.optJSONArray("cards")
            _cards.value = (0 until (a?.length() ?: 0)).mapNotNull { i -> a?.optJSONObject(i)?.let { Card.from(it) } }
            _cardFields.value = Card.fields(o.optJSONObject("fields"))
            val drawing = o.optJSONArray("drawing")
            _cardStages.value = (0 until (drawing?.length() ?: 0)).associate { i ->
                drawing!!.optLong(i) to (_cardStages.value[drawing.optLong(i)] ?: CardStage("queued"))
            }
        }
    }

    /** Новая карточка: по описанию своими словами (заполнит модель) или пустая. */
    suspend fun createCard(kind: String, text: String): Card? {
        val c = client ?: return null
        return guard {
            val o = if (text.isBlank()) {
                c.post("/api/cards", JSONObject().put("kind", kind)
                    .put("data", JSONObject().put("name", if (kind == "persona") "Я" else "Новый персонаж")))
            } else {
                c.postSlow("/api/cards/generate", JSONObject().put("kind", kind).put("text", text))
            }
            Card.from(o.getJSONObject("card")).also { upsertCard(it) }
        }
    }

    suspend fun saveCard(id: Long, data: Map<String, String>): Card? = guard {
        val o = client?.patch("/api/cards/$id", JSONObject().put("data", JSONObject(data))) ?: return@guard null
        Card.from(o.getJSONObject("card")).also { upsertCard(it) }
    }

    suspend fun deleteCard(id: Long) {
        guard {
            client?.delete("/api/cards/$id")
            _cards.value = _cards.value.filter { it.id != id }
        }
    }

    /** Переписать одно поле моделью; значение возвращается в редактор, не сохраняется. */
    suspend fun rewriteField(id: Long, field: String, wish: String, data: Map<String, String>): String? = guard {
        val o = client?.postSlow("/api/cards/$id/rewrite", JSONObject().put("field", field)
            .put("wish", wish).put("data", JSONObject(data))) ?: return@guard null
        o.strOrNull("value")
    }

    suspend fun drawPortrait(id: Long) {
        _cardStages.value = _cardStages.value + (id to CardStage("queued"))
        if (guard { client?.post("/api/cards/$id/portrait") } == null) {
            _cardStages.value = _cardStages.value - id
        }
    }

    /** Новый чат с персонажем (и, если выбрана, от лица персоны) — сразу открывается. */
    suspend fun startCharacterChat(id: Long, personaId: Long?): Boolean {
        val c = client ?: return false
        return guard {
            val body = JSONObject()
            personaId?.let { body.put("persona_id", it) }
            val chat = ChatInfo.from(c.post("/api/cards/$id/chat", body).getJSONObject("chat"))
            upsertChat(chat)
            openChat(chat.id)
            true
        } ?: false
    }

    suspend fun continueMessage(msgId: Long) {
        guard { client?.post("/api/messages/$msgId/continue")?.let { applyChatResponse(it) } }
    }

    suspend fun setPinned(msgId: Long, pinned: Boolean) {
        guard {
            client?.patch("/api/messages/$msgId", JSONObject().put("pinned", pinned))
                ?.optJSONObject("message")?.let { replaceMessage(Msg.from(it)) }
        }
    }

    /** Параметры генерации текущего чата; без открытого чата — для новых чатов. */
    suspend fun setSettings(settings: GenSettings, makeDefault: Boolean) {
        val c = client ?: return
        val cid = _currentChatId.value
        guard {
            if (cid == null) {
                c.put("/api/settings", JSONObject().put("default_settings", settings.toJson()))
                _defaultSettings.value = settings
            } else {
                val o = c.patch("/api/chats/$cid",
                    JSONObject().put("settings", settings.toJson()).put("make_default", makeDefault))
                o.optJSONObject("chat")?.let { upsertChat(ChatInfo.from(it)) }
                if (makeDefault) _defaultSettings.value = settings
            }
        }
    }

    // ------------------------------------------------------------- память

    suspend fun loadMemory() {
        val cid = _currentChatId.value ?: run { _memory.value = null; return }
        guard { client?.get("/api/chats/$cid/memory")?.let { applyMemory(it) } }
    }

    fun closeMemory() {
        _memory.value = null
    }

    private fun applyMemory(o: JSONObject) {
        val m = MemoryInfo.from(o)
        if (m.chatId == _currentChatId.value) _memory.value = m
    }

    suspend fun addFact(text: String) {
        val cid = _currentChatId.value ?: return
        guard { client?.post("/api/chats/$cid/facts", JSONObject().put("text", text))?.let { applyMemory(it) } }
    }

    suspend fun editFact(id: Long, text: String) {
        guard { client?.patch("/api/facts/$id", JSONObject().put("text", text))?.let { applyMemory(it) } }
    }

    suspend fun pinFact(id: Long, pinned: Boolean) {
        guard { client?.patch("/api/facts/$id", JSONObject().put("pinned", pinned))?.let { applyMemory(it) } }
    }

    suspend fun deleteFact(id: Long) {
        guard { client?.delete("/api/facts/$id")?.let { applyMemory(it) } }
    }

    suspend fun saveChronicle(text: String) {
        val cid = _currentChatId.value ?: return
        guard { client?.put("/api/chats/$cid/chronicle", JSONObject().put("text", text))?.let { applyMemory(it) } }
    }

    suspend fun refreshMemory() {
        val cid = _currentChatId.value ?: return
        guard {
            client?.post("/api/chats/$cid/memory/refresh")
            _events.tryEmit("Память обновится, когда модель освободится")
        }
    }
}
