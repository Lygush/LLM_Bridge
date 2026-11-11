package dev.llmbridge.client

import org.json.JSONArray
import org.json.JSONObject

/** Состояние модели на ПК (/api/status, события status/busy). */
data class ServerStatus(
    val llama: String = "down",   // ready / loading / down / error
    val model: String = "",
    val vision: Boolean = false,
    val nCtx: Int = 0,
    val busy: Boolean = false,
    val images: Boolean = false,     // на ПК настроена генерация изображений
    val bg: String = "down",         // фоновая маленькая модель: ready / loading / down
) {
    /** Можно писать: модель готова или выгружена на время рисования (вернётся сама). */
    val canChat: Boolean get() = llama == "ready" || llama == "swapped"

    companion object {
        fun from(o: JSONObject?): ServerStatus = if (o == null) ServerStatus() else ServerStatus(
            llama = o.optString("llama", "down"),
            model = o.optString("model", ""),
            vision = o.optBoolean("vision", false),
            nCtx = o.optInt("n_ctx", 0),
            busy = o.optBoolean("busy", false),
            images = o.optBoolean("images", false),
            bg = o.optString("bg", "down"),
        )
    }
}

/** Параметры генерации чата. null — значение llama-server по умолчанию. */
data class GenSettings(
    val thinking: Boolean = false,
    val temperature: Double? = null,
    val topP: Double? = null,
    val minP: Double? = null,
    val topK: Int? = null,
    val repeatPenalty: Double? = null,
    val presencePenalty: Double? = null,
    val maxTokens: Int? = null,
    val imageProfile: String? = null,   // профиль рисования чата (не параметр текста)
    val illustrate: String? = null,     // off | on_request | auto — когда модель рисует сама
    val likeness: Boolean? = null,      // рисовать персонажей по образцам портретов (null — да)
) {
    /** Значение параметра: своё, иначе рекомендуемое. */
    fun or(r: GenSettings) = GenSettings(
        thinking = thinking,
        temperature = temperature ?: r.temperature,
        topP = topP ?: r.topP,
        minP = minP ?: r.minP,
        topK = topK ?: r.topK,
        repeatPenalty = repeatPenalty ?: r.repeatPenalty,
        presencePenalty = presencePenalty ?: r.presencePenalty,
        maxTokens = maxTokens ?: r.maxTokens,
    )

    fun toJson(): JSONObject = JSONObject().apply {
        put("thinking", thinking)
        temperature?.let { put("temperature", it) }
        topP?.let { put("top_p", it) }
        minP?.let { put("min_p", it) }
        topK?.let { put("top_k", it) }
        repeatPenalty?.let { put("repeat_penalty", it) }
        presencePenalty?.let { put("presence_penalty", it) }
        maxTokens?.let { put("max_tokens", it) }
        imageProfile?.let { put("image_profile", it) }
        illustrate?.let { put("illustrate", it) }
        likeness?.let { put("likeness", it) }
    }

    companion object {
        fun from(o: JSONObject?): GenSettings = if (o == null) GenSettings() else GenSettings(
            thinking = o.optBoolean("thinking", false),
            temperature = o.doubleOrNull("temperature"),
            topP = o.doubleOrNull("top_p"),
            minP = o.doubleOrNull("min_p"),
            topK = o.intOrNull("top_k"),
            repeatPenalty = o.doubleOrNull("repeat_penalty"),
            presencePenalty = o.doubleOrNull("presence_penalty"),
            maxTokens = o.intOrNull("max_tokens"),
            imageProfile = o.strOrNull("image_profile"),
            illustrate = o.strOrNull("illustrate"),
            likeness = if (o.has("likeness")) o.optBoolean("likeness") else null,
        )
    }
}

/** Профиль генерации изображений на ПК. */
data class ImageProfile(
    val id: String,
    val name: String,
    val width: Int,
    val height: Int,
    val steps: Int,
    val ready: Boolean,
    val missing: List<String>,
    val about: String = "",          // чем хороша: «быстрая», «рисует по образцу»…
    val fast: Boolean = false,       // турбо-модель: шаги фиксированы
) {
    companion object {
        fun from(o: JSONObject): ImageProfile {
            val m = o.optJSONArray("missing")
            return ImageProfile(
                about = o.optString("about"), fast = o.optBoolean("fast", false),
                id = o.optString("id"), name = o.optString("name", o.optString("id")),
                width = o.optInt("width", 1024), height = o.optInt("height", 1024),
                steps = o.optInt("steps", 20), ready = o.optBoolean("ready", false),
                missing = if (m == null) emptyList() else (0 until m.length()).map { m.optString(it) },
            )
        }
    }
}

/** Задача рисования и какая модель её выполняет ("" — «Авто», тогда рисует auto). */
data class ImageRoute(
    val id: String,
    val title: String,
    val hint: String,
    val choice: String,
    val auto: String,
    val options: List<Pair<String, String>>,   // id → название
) {
    companion object {
        fun from(o: JSONObject): ImageRoute {
            val a = o.optJSONArray("options")
            return ImageRoute(
                id = o.optString("id"), title = o.optString("title"), hint = o.optString("hint"),
                choice = o.optString("choice"), auto = o.optString("auto"),
                options = (0 until (a?.length() ?: 0)).mapNotNull { i ->
                    a?.optJSONObject(i)?.let { it.optString("id") to it.optString("name") }
                },
            )
        }
    }
}

/** Что ПК подставляет, если параметр не задан (обычный режим и с размышлениями). */
data class Recommended(
    val plain: GenSettings = GenSettings(temperature = 0.7, topP = 0.8, topK = 20, minP = 0.0,
        presencePenalty = 1.0, maxTokens = 1536),
    val thinking: GenSettings = GenSettings(thinking = true, temperature = 0.6, topP = 0.95, topK = 20,
        minP = 0.0, presencePenalty = 1.0, maxTokens = 4096),
) {
    fun forMode(thinkingOn: Boolean) = if (thinkingOn) thinking else plain

    companion object {
        fun from(o: JSONObject?): Recommended {
            if (o == null) return Recommended()
            val d = Recommended()
            return Recommended(
                plain = o.optJSONObject("plain")?.let { GenSettings.from(it) } ?: d.plain,
                thinking = o.optJSONObject("thinking")?.let { GenSettings.from(it).copy(thinking = true) }
                    ?: d.thinking,
            )
        }
    }
}

/** Раскладка контекста последнего ответа по слоям (в токенах). */
data class ContextStats(
    val nCtx: Int,
    val reserve: Int,
    val system: Int,
    val memory: Int,
    val chronicle: Int,
    val pinned: Int,
    val history: Int,
    val messages: Int,
    val dropped: Int,
) {
    val total: Int get() = system + memory + chronicle + pinned + history

    companion object {
        fun from(o: JSONObject?): ContextStats? = if (o == null) null else ContextStats(
            nCtx = o.optInt("n_ctx"), reserve = o.optInt("reserve"),
            system = o.optInt("system"), memory = o.optInt("memory"),
            chronicle = o.optInt("chronicle"), pinned = o.optInt("pinned"),
            history = o.optInt("history"), messages = o.optInt("messages"),
            dropped = o.optInt("dropped"),
        )
    }
}

data class Fact(val id: Long, val text: String, val pinned: Boolean, val auto: Boolean) {
    companion object {
        fun from(o: JSONObject) = Fact(
            id = o.getLong("id"), text = o.strOrNull("text") ?: "",
            pinned = o.optBoolean("pinned", false), auto = o.optBoolean("auto", false),
        )
    }
}

/** Память чата: факты, хроника текущей ветки и раскладка контекста. */
data class MemoryInfo(
    val chatId: Long,
    val facts: List<Fact>,
    val chronicle: String,
    val ctx: ContextStats?,
) {
    companion object {
        fun from(o: JSONObject): MemoryInfo {
            val a = o.optJSONArray("facts")
            return MemoryInfo(
                chatId = o.optLong("chat_id"),
                facts = if (a == null) emptyList()
                        else (0 until a.length()).mapNotNull { i -> a.optJSONObject(i)?.let { Fact.from(it) } },
                chronicle = o.optJSONObject("chronicle")?.strOrNull("text") ?: "",
                ctx = ContextStats.from(o.optJSONObject("ctx")),
            )
        }
    }
}

data class ChatInfo(
    val id: Long,
    val title: String,
    val systemPrompt: String,
    val updated: Double,
    val preview: String,
    val settings: GenSettings = GenSettings(),
    val characterId: Long? = null,   // чат с персонажем (карточка)
    val personaId: Long? = null,
    val characterIds: List<Long> = emptyList(),   // персонажи сцены
    val worldId: Long? = null,
    val mode: String = "chat",       // chat | quest | story | gm
    val chatStyle: String = "roleplay",   // messenger — переписка, roleplay — рядом, с действиями
    val initiative: Boolean = true,  // персонаж может написать первым
    val dateOf: Long? = null,        // свидание: из какого чата начато
    val vnBg: String = "auto",       // фоны новеллы: auto — сами при смене места, manual — по кнопке
) {
    /** Все персонажи чата: и старый одиночный, и список сцены. */
    val cast: List<Long> get() = characterIds.ifEmpty { listOfNotNull(characterId) }

    /** Для кэша на телефоне: список чатов виден и без связи с ПК. */
    fun toJson(): JSONObject = JSONObject()
        .put("id", id).put("title", title).put("system_prompt", systemPrompt)
        .put("updated", updated).put("preview", preview)
        .put("settings", settings.toJson().apply {
            characterId?.let { put("character_id", it) }
            personaId?.let { put("persona_id", it) }
            worldId?.let { put("world_id", it) }
            put("character_ids", JSONArray().apply { characterIds.forEach { put(it) } })
            put("mode", mode)
            put("chat_style", chatStyle)
            put("initiative", initiative)
            dateOf?.let { put("date_of", it) }
            put("vn_bg", vnBg)
        })

    companion object {
        fun from(o: JSONObject) = ChatInfo(
            id = o.getLong("id"),
            title = o.strOrNull("title") ?: "",
            systemPrompt = o.strOrNull("system_prompt") ?: "",
            updated = o.optDouble("updated", 0.0).let { if (it.isNaN()) 0.0 else it },
            preview = o.strOrNull("preview") ?: "",
            settings = GenSettings.from(o.optJSONObject("settings")),
            characterId = o.optJSONObject("settings")?.longOrNull("character_id"),
            personaId = o.optJSONObject("settings")?.longOrNull("persona_id"),
            characterIds = o.optJSONObject("settings")?.optJSONArray("character_ids")?.let { a ->
                (0 until a.length()).map { a.optLong(it) }
            } ?: emptyList(),
            worldId = o.optJSONObject("settings")?.longOrNull("world_id"),
            mode = o.optJSONObject("settings")?.strOrNull("mode") ?: "chat",
            chatStyle = o.optJSONObject("settings")?.strOrNull("chat_style") ?: "roleplay",
            initiative = o.optJSONObject("settings")?.optBoolean("initiative", true) ?: true,
            dateOf = o.optJSONObject("settings")?.longOrNull("date_of"),
            vnBg = o.optJSONObject("settings")?.strOrNull("vn_bg") ?: "auto",
        )

        fun list(a: JSONArray?): List<ChatInfo> {
            if (a == null) return emptyList()
            return (0 until a.length()).mapNotNull { i -> a.optJSONObject(i)?.let { from(it) } }
                .sortedByDescending { it.updated }
        }
    }
}

/** Сведения о нарисованной картинке: для подписи, значка и карточки «что это». */
data class ImageInfo(
    val source: String,       // user — нарисовано по запросу человека, model — модель решила сама
    val prompt: String,       // английский промпт, ушедший в модель изображений
    val request: String = "", // исходный запрос человека (если промпт доработала модель)
    val caption: String = "",
    val negative: String = "",
    val profile: String = "",
    val seed: Long? = null,
    val width: Int = 0,
    val height: Int = 0,
    val steps: Int = 0,
    val seen: String = "",    // что видит на картинке текстовая модель
    val error: String = "",   // рисование не удалось (текст ответа при этом цел)
    val refs: List<String> = emptyList(),   // по каким образцам рисовалось: персонажи, фото позы
) {
    companion object {
        fun from(meta: JSONObject?): ImageInfo? {
            if (meta == null) return null
            val d = meta.optJSONObject("drawn")
            val o = d ?: if (meta.optString("kind") == "image") meta else return null
            return ImageInfo(
                source = if (d != null) "model" else "user",
                prompt = o.strOrNull("prompt") ?: "",
                request = o.strOrNull("request") ?: "",
                caption = o.strOrNull("caption") ?: "",
                negative = o.strOrNull("negative") ?: "",
                profile = o.strOrNull("profile") ?: "",
                seed = o.longOrNull("seed"),
                width = o.optInt("width", 0),
                height = o.optInt("height", 0),
                steps = o.optInt("steps", 0),
                seen = o.strOrNull("seen") ?: "",
                error = meta.strOrNull("draw_error") ?: "",
                refs = o.optJSONArray("refs")?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: emptyList(),
            )
        }
    }
}

data class Msg(
    val id: Long,
    val chatId: Long,
    val parentId: Long?,
    val role: String,             // user | assistant
    val content: String,
    val reasoning: String,
    val status: String,           // done | generating | cancelled | error
    val error: String?,
    val promptTokens: Int?,
    val completionTokens: Int?,
    val tokensPerSec: Double?,
    val variant: Int,
    val variants: Int,
    val variantIds: List<Long>,
    val pinned: Boolean = false,
    val ctx: ContextStats? = null,
    val stage: String = "",        // summarizing — ПК сжимает историю перед ответом
    val truncated: Boolean = false, // ответ упёрся в предел длины
    val images: List<String> = emptyList(),   // имена картинок на ПК (/api/images/<имя>)
    val kind: String = "",          // image — нарисованная картинка, image_request — запрос на рисование
    val prompt: String = "",
    val progressDone: Int = 0,      // шаги рисования
    val progressTotal: Int = 0,
    val art: ImageInfo? = null,     // откуда картинка и с какими параметрами нарисована
    val speakers: List<Long> = emptyList(),   // кто из персонажей говорит в ответе
    val state: QuestState? = null,            // состояние квеста после этого хода
    val choices: List<String> = emptyList(),  // варианты действий игрока
    val hints: List<String> = emptyList(),    // «Мире понравилось…» — как ход повлиял на отношения
    val coins: Int = 0,                       // монеты, полученные/потраченные за ход квеста
    val beats: List<Beat> = emptyList(),      // кадры визуальной новеллы (режим «История»)
) {
    /** Служебный толчок «персонаж пишет первым» — пользователю не показывается. */
    val hidden: Boolean get() = kind == "nudge"
    /** Служебная команда истории («продолжи», «поворот») или завязка сцены. */
    val directive: Boolean get() = kind == "directive"
    val generating: Boolean get() = status == "generating"
    /** Картинку нарисовала сама модель (инструментом) — к тексту ответа. */
    val drawnByModel: Boolean get() = art?.source == "model"

    companion object {
        fun from(o: JSONObject): Msg {
            val ids = o.optJSONArray("variant_ids")
            val tps = o.optJSONObject("meta")?.optJSONObject("timings")
                ?.optDouble("predicted_per_second", Double.NaN)
            return Msg(
                id = o.getLong("id"),
                chatId = o.getLong("chat_id"),
                parentId = o.longOrNull("parent_id"),
                role = o.optString("role", "assistant"),
                content = o.strOrNull("content") ?: "",
                reasoning = o.strOrNull("reasoning") ?: "",
                status = o.optString("status", "done"),
                error = o.strOrNull("error"),
                promptTokens = o.intOrNull("prompt_tokens"),
                completionTokens = o.intOrNull("completion_tokens"),
                tokensPerSec = tps?.takeIf { !it.isNaN() },
                variant = o.optInt("variant", 1),
                variants = o.optInt("variants", 1),
                variantIds = if (ids == null) emptyList() else (0 until ids.length()).map { ids.getLong(it) },
                pinned = o.optBoolean("pinned", false),
                ctx = ContextStats.from(o.optJSONObject("meta")?.optJSONObject("ctx")),
                truncated = o.optJSONObject("meta")?.optBoolean("truncated", false) ?: false,
                kind = o.optJSONObject("meta")?.strOrNull("kind") ?: "",
                prompt = o.optJSONObject("meta")?.strOrNull("prompt") ?: "",
                art = ImageInfo.from(o.optJSONObject("meta")),
                speakers = o.optJSONObject("meta")?.optJSONArray("speakers")?.let { a ->
                    (0 until a.length()).map { a.optLong(it) }
                } ?: emptyList(),
                state = o.optJSONObject("meta")?.optJSONObject("state")?.let { QuestState.from(it) },
                hints = o.optJSONObject("meta")?.optJSONArray("events")?.let { a ->
                    (0 until a.length()).mapNotNull { a.optJSONObject(it)?.strOrNull("text") }
                } ?: emptyList(),
                coins = o.optJSONObject("meta")?.optInt("coins", 0) ?: 0,
                beats = Beat.list(o.optJSONObject("meta")?.optJSONArray("beats")),
                choices = o.optJSONObject("meta")?.optJSONArray("choices")?.let { a ->
                    (0 until a.length()).map { a.optString(it) }.filter { it.isNotBlank() }
                } ?: emptyList(),
                images = o.optJSONObject("meta")?.optJSONArray("images")?.let { a ->
                    (0 until a.length()).mapNotNull { a.optJSONObject(it)?.strOrNull("name") }
                } ?: emptyList(),
            )
        }

        fun list(a: JSONArray?): List<Msg> {
            if (a == null) return emptyList()
            return (0 until a.length()).mapNotNull { i -> a.optJSONObject(i)?.let { from(it) } }
        }
    }
}

// optString/optLong превращают JSON null в "null"/0 — поэтому свои функции
internal fun JSONObject.strOrNull(key: String): String? =
    if (has(key) && !isNull(key)) getString(key) else null

internal fun JSONObject.longOrNull(key: String): Long? =
    if (has(key) && !isNull(key)) getLong(key) else null

internal fun JSONObject.intOrNull(key: String): Int? =
    if (has(key) && !isNull(key)) getInt(key) else null

internal fun JSONObject.doubleOrNull(key: String): Double? =
    if (has(key) && !isNull(key)) getDouble(key) else null

// ================================================================ карточки

/** Поле карточки — описание приходит с ПК, редактор строится по нему. */
data class CardField(val key: String, val label: String, val multiline: Boolean)

/** Персонаж (character) или персона пользователя (persona). */
data class Card(
    val id: Long,
    val kind: String,
    val name: String,
    val data: Map<String, String>,
    val portrait: String?,   // имя картинки на ПК
    val sprites: Map<String, String> = emptyMap(),   // эмоция (calm, joy…) → картинка для новеллы
) {
    val short: String get() = data["short"].orEmpty()

    companion object {
        fun from(o: JSONObject): Card {
            val d = o.optJSONObject("data")
            val map = buildMap<String, String> { d?.keys()?.forEach { k -> put(k, d.optString(k)) } }
            return Card(
                id = o.getLong("id"),
                kind = o.optString("kind"),
                name = o.strOrNull("name") ?: "",
                data = map,
                portrait = o.optJSONObject("portrait")?.strOrNull("name"),
                sprites = o.optJSONObject("sprites")?.let { sp ->
                    buildMap<String, String> { sp.keys().forEach { k -> sp.optJSONObject(k)?.strOrNull("name")?.let { put(k, it) } } }
                } ?: emptyMap(),
            )
        }

        fun fields(o: JSONObject?): Map<String, List<CardField>> {
            if (o == null) return emptyMap()
            return buildMap {
                o.keys().forEach { kind ->
                    val a = o.optJSONArray(kind) ?: return@forEach
                    put(kind, (0 until a.length()).mapNotNull { i ->
                        a.optJSONObject(i)?.let {
                            CardField(it.optString("key"), it.optString("label"), it.optBoolean("multiline"))
                        }
                    })
                }
            }
        }
    }
}

/** Ход рисования портрета карточки. */
data class CardStage(val stage: String, val done: Int = 0, val total: Int = 0)

/** Запись лорбука мира: попадает в контекст, когда в разговоре встречаются её ключи. */
data class LoreEntry(val id: Long, val title: String, val keys: String, val content: String, val always: Boolean) {
    companion object {
        fun from(o: JSONObject) = LoreEntry(
            o.getLong("id"), o.strOrNull("title") ?: "", o.strOrNull("keys") ?: "",
            o.strOrNull("content") ?: "", o.optBoolean("always"),
        )
        fun list(a: JSONArray?): List<LoreEntry> =
            if (a == null) emptyList() else (0 until a.length()).mapNotNull { i -> a.optJSONObject(i)?.let { from(it) } }
    }
}

/** Состояние квеста: где игрок, что у него есть, цели. Правится вручную и моделью. */
data class QuestState(
    val location: String = "",
    val time: String = "",
    val health: String = "",
    val inventory: List<String> = emptyList(),
    val goals: List<String> = emptyList(),
    val relations: List<String> = emptyList(),
    val notes: String = "",
) {
    fun toJson(): JSONObject = JSONObject()
        .put("location", location).put("time", time).put("health", health)
        .put("inventory", JSONArray().apply { inventory.forEach { put(it) } })
        .put("goals", JSONArray().apply { goals.forEach { put(it) } })
        .put("relations", JSONArray().apply { relations.forEach { put(it) } })
        .put("notes", notes)

    companion object {
        private fun strs(o: JSONObject, k: String): List<String> = o.optJSONArray(k)?.let { a ->
            (0 until a.length()).map { a.optString(it) }.filter { it.isNotBlank() }
        } ?: emptyList()

        fun from(o: JSONObject) = QuestState(
            location = o.strOrNull("location") ?: "", time = o.strOrNull("time") ?: "",
            health = o.strOrNull("health") ?: "", inventory = strs(o, "inventory"),
            goals = strs(o, "goals"), relations = strs(o, "relations"), notes = o.strOrNull("notes") ?: "",
        )
    }
}

/** Отношения персонажа с вами (персоной): общие для всех ваших чатов с ним. */
data class Relation(
    val characterId: Long,
    val name: String,
    val sympathy: Int,
    val trust: Int,
    val status: String,
    val mood: String,
    val promises: List<String>,
    val debt: Int = 0,           // сколько монет вы ему должны
) {
    companion object {
        fun from(o: JSONObject): Relation {
            val r = o.optJSONObject("relation") ?: JSONObject()
            val pr = r.optJSONArray("promises")
            return Relation(
                characterId = o.optLong("character_id"),
                name = o.strOrNull("name") ?: "",
                sympathy = r.optInt("sympathy", 0),
                trust = r.optInt("trust", 0),
                status = r.strOrNull("status") ?: "",
                mood = r.strOrNull("mood") ?: "",
                promises = if (pr == null) emptyList() else (0 until pr.length()).map { pr.optString(it) },
                debt = r.optInt("debt", 0),
            )
        }
    }
}

/** Кадр новеллы: смена места, повествование или реплика персонажа с эмоцией. */
data class Beat(
    val type: String,            // place | narration | line
    val text: String = "",
    val name: String = "",
    val key: String = "",        // ключ места (для фона)
    val characterId: Long? = null,
    val emotion: String = "calm",
) {
    companion object {
        fun list(a: JSONArray?): List<Beat> {
            if (a == null) return emptyList()
            return (0 until a.length()).mapNotNull { i ->
                a.optJSONObject(i)?.let { o ->
                    Beat(
                        type = o.optString("type"), text = o.strOrNull("text") ?: "",
                        name = o.strOrNull("name") ?: "", key = o.strOrNull("key") ?: "",
                        characterId = o.longOrNull("character_id"), emotion = o.strOrNull("emotion") ?: "calm",
                    )
                }
            }
        }
    }
}

/** Предложение модели изменить карточку: «персонаж меняется». */
data class Proposal(val id: Long, val cardId: Long, val name: String, val field: String,
                    val value: String, val reason: String, val chatId: Long) {
    companion object {
        fun from(o: JSONObject) = Proposal(
            o.getLong("id"), o.optLong("card_id"), o.strOrNull("name") ?: "", o.optString("field"),
            o.strOrNull("value") ?: "", o.strOrNull("reason") ?: "", o.optLong("chat_id"),
        )
    }
}

/** Картинка в галерее чата. */
data class GalleryItem(val name: String, val caption: String, val kind: String)

/** Развилка истории: варианты, что выбрано на этом пути, что пробовали в других ветках. */
data class Fork(val options: List<String>, val taken: String?, val tried: List<String>)
