package dev.llmbridge.client.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.PlayArrow
import dev.llmbridge.client.Card
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.llmbridge.client.ChatInfo
import dev.llmbridge.client.ChatViewModel
import dev.llmbridge.client.Conn
import dev.llmbridge.client.ConnState
import dev.llmbridge.client.Msg
import dev.llmbridge.client.Pairing
import dev.llmbridge.client.ServerStatus
import kotlinx.coroutines.launch

private val LINK_PERMISSION: String =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) Manifest.permission.NEARBY_WIFI_DEVICES
    else Manifest.permission.ACCESS_FINE_LOCATION

private val ALL_PERMISSIONS: Array<String> =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
        arrayOf(LINK_PERMISSION, Manifest.permission.POST_NOTIFICATIONS)
    else arrayOf(LINK_PERMISSION)

/** Правка сообщения: на месте или с повторной отправкой (новая ветка). */
private data class EditRequest(val msg: Msg, val resend: Boolean)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(vm: ChatViewModel, pairing: Pairing) {
    val ctx = LocalContext.current
    val conn by vm.conn.collectAsStateWithLifecycle()
    val status by vm.status.collectAsStateWithLifecycle()
    val chats by vm.chats.collectAsStateWithLifecycle()
    val currentId by vm.currentChatId.collectAsStateWithLifecycle()
    val messages by vm.messages.collectAsStateWithLifecycle()
    val defaultPrompt by vm.defaultPrompt.collectAsStateWithLifecycle()
    val defaultSettings by vm.defaultSettings.collectAsStateWithLifecycle()
    val recommended by vm.recommended.collectAsStateWithLifecycle()
    val memory by vm.memory.collectAsStateWithLifecycle()

    var permissionDenied by remember { mutableStateOf(false) }
    val permLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { _ ->
        // результат содержит только запрошенные сейчас разрешения — проверяем фактическое состояние
        val ok = ContextCompat.checkSelfPermission(ctx, LINK_PERMISSION) == PackageManager.PERMISSION_GRANTED
        permissionDenied = !ok
        if (ok) vm.connect()
    }

    fun connectWithPermissions() {
        val missing = ALL_PERMISSIONS.filter {
            ContextCompat.checkSelfPermission(ctx, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isEmpty()) vm.connect() else permLauncher.launch(missing.toTypedArray())
    }

    // при каждом открытии экрана: служба запущена, сессия идёт
    LaunchedEffect(pairing) { connectWithPermissions() }

    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) {
        vm.events.collect { snackbar.showSnackbar(it) }
    }

    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()

    val currentChat = chats.firstOrNull { it.id == currentId }
    val generating = messages.any { it.generating }
    val ready = conn.conn == Conn.ONLINE && status.canChat
    val profiles by vm.profiles.collectAsStateWithLifecycle()
    var drawRequest by remember { mutableStateOf<DrawRequest?>(null) }

    var menu by remember { mutableStateOf(false) }
    var promptDialog by remember { mutableStateOf(false) }
    var renameDialog by remember { mutableStateOf(false) }
    var deleteTarget by remember { mutableStateOf<ChatInfo?>(null) }   // какой чат удалить
    var cardsOpen by rememberSaveable { mutableStateOf(false) }
    var sceneRequest by remember { mutableStateOf<SceneRequest?>(null) }
    var replyAs by remember(currentId) { mutableStateOf<Long?>(null) }   // кто из персонажей ответит
    var rewriteFor by remember { mutableStateOf<Msg?>(null) }
    var stateEdit by remember { mutableStateOf<Msg?>(null) }
    val cards by vm.cards.collectAsStateWithLifecycle()
    val mode = currentChat?.mode ?: "chat"
    val castCards = currentChat?.cast.orEmpty().mapNotNull { id -> cards.firstOrNull { it.id == id } }
    val lastAnswer = messages.lastOrNull { it.role == "assistant" }
    val stateMsg = messages.lastOrNull { it.state != null }
    val relations by vm.relations.collectAsStateWithLifecycle()
    val coins by vm.coins.collectAsStateWithLifecycle()
    val showRelations by vm.showRelations.collectAsStateWithLifecycle()
    val charChat = mode == "chat" && castCards.isNotEmpty()
    var giftOpen by remember { mutableStateOf(false) }
    // история открывается сразу новеллой; «Текстом» — запомнить для этого чата
    var novelClosedFor by rememberSaveable { mutableStateOf<Long?>(null) }
    var chatOptions by remember { mutableStateOf(false) }
    var imageModels by remember { mutableStateOf(false) }
    var borrowOpen by remember { mutableStateOf(false) }
    var dateOpen by remember { mutableStateOf(false) }
    var recapText by remember { mutableStateOf<String?>(null) }
    val proposals by vm.proposals.collectAsStateWithLifecycle()
    val cardFields by vm.cardFields.collectAsStateWithLifecycle()
    var galleryItems by remember { mutableStateOf<List<dev.llmbridge.client.GalleryItem>?>(null) }
    var forksList by remember { mutableStateOf<List<dev.llmbridge.client.Fork>?>(null) }
    var frameOpen by remember { mutableStateOf(false) }
    val isDate = currentChat?.dateOf != null
    val target = castCards.firstOrNull { it.id == replyAs } ?: castCards.firstOrNull()
    val debt = relations.firstOrNull { it.characterId == target?.id }?.debt ?: 0
    var gmAssist by remember { mutableStateOf(false) }
    // вернулись в приложение — персонаж может написать первым (решает ПК, не чаще раза за паузу)
    val lifecycle = androidx.lifecycle.compose.LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val obs = androidx.lifecycle.LifecycleEventObserver { _, e ->
            if (e == androidx.lifecycle.Lifecycle.Event.ON_RESUME) vm.nudge()
        }
        lifecycle.addObserver(obs)
        onDispose { lifecycle.removeObserver(obs) }
    }
    var forgetDialog by remember { mutableStateOf(false) }
    var editRequest by remember { mutableStateOf<EditRequest?>(null) }
    var settingsDialog by remember { mutableStateOf(false) }
    var memoryTab by remember { mutableStateOf(-1) }   // -1 — панель памяти закрыта

    // режим «История» сразу открывается новеллой — во всё окно, вместо экрана чата
    if (mode == "story" && currentChat != null && novelClosedFor != currentId) {
        NovelScreen(vm, castCards, onClose = { novelClosedFor = currentId })
        return
    }

    // широкий экран (планшет, телефон на боку): список чатов всегда слева, без выдвижной панели
    val wide = isWideScreen()
    val chatList: @Composable () -> Unit = {
                ChatList(
                    chats = chats,
                    currentId = currentId,
                    onNew = {
                        vm.newChat()
                        scope.launch { drawer.close() }
                    },
                    onOpen = {
                        vm.openChat(it)
                        scope.launch { drawer.close() }
                    },
                    onDelete = { deleteTarget = it },
                    onCards = {
                        cardsOpen = true
                        scope.launch { drawer.close() }
                    },
                    onScene = {
                        sceneRequest = SceneRequest()
                        scope.launch { drawer.close() }
                    },
                    cards = cards,
                    loadImage = { vm.image(it) },
                )
    }
    val body: @Composable () -> Unit = {
        Scaffold(
            snackbarHost = { SnackbarHost(snackbar) },
            topBar = {
                Column {
                    TopAppBar(
                        navigationIcon = {
                            if (!wide) IconButton(onClick = { scope.launch { drawer.open() } }) {
                                Icon(Icons.Filled.Menu, contentDescription = "Чаты")
                            }
                        },
                        title = {
                            Column {
                                Text(
                                    currentChat?.title?.ifBlank { null } ?: "Новый чат",
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Text(
                                    statusLine(conn, status, permissionDenied),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = if (ready) MaterialTheme.colorScheme.primary
                                    else MaterialTheme.colorScheme.onSurfaceVariant,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                        },
                        actions = {
                            IconButton(onClick = { menu = true }) {
                                Icon(Icons.Filled.MoreVert, contentDescription = "Меню")
                            }
                            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                                DropdownMenuItem(text = { Text("Системный промпт") }, onClick = {
                                    menu = false; promptDialog = true
                                })
                                DropdownMenuItem(text = { Text("Параметры генерации") }, onClick = {
                                    menu = false; settingsDialog = true
                                })
                                DropdownMenuItem(text = { Text("Модели картинок") },
                                    leadingIcon = { Icon(AppIcons.Draw, contentDescription = null) },
                                    onClick = { menu = false; imageModels = true })
                                if (currentChat != null) {
                                    DropdownMenuItem(text = { Text("Память чата") }, onClick = {
                                        menu = false; memoryTab = 0
                                    })
                                    DropdownMenuItem(text = { Text("Переименовать чат") }, onClick = {
                                        menu = false; renameDialog = true
                                    })
                                    DropdownMenuItem(text = { Text("Галерея") }, onClick = {
                                        menu = false; vm.gallery { galleryItems = it }
                                    })
                                    if (mode == "story") {
                                        DropdownMenuItem(
                                            text = { Text(if (currentChat.vnBg == "manual") "Фоны новеллы: рисовать самим"
                                                else "Фоны новеллы: рисовать по кнопке") },
                                            onClick = {
                                                menu = false
                                                vm.setChatOption("vn_bg", if (currentChat.vnBg == "manual") "auto" else "manual")
                                            })
                                    }
                                    DropdownMenuItem(text = { Text("Удалить чат") }, onClick = {
                                        menu = false; deleteTarget = currentChat
                                    })
                                    if (charChat) {
                                        DropdownMenuItem(text = { Text("Настройки общения…") },
                                            leadingIcon = { Icon(AppIcons.Tune, contentDescription = null) }, onClick = {
                                            menu = false; chatOptions = true
                                        })
                                    }
                                }
                                HorizontalDivider()
                                DropdownMenuItem(text = { Text("Переподключиться") }, onClick = {
                                    menu = false
                                    if (permissionDenied) connectWithPermissions() else vm.reconnect()
                                })
                                DropdownMenuItem(text = { Text("Забыть ПК") }, onClick = {
                                    menu = false; forgetDialog = true
                                })
                            }
                        },
                    )
                    ContextBar(messages, status, onClick = { if (currentChat != null) memoryTab = 2 })
                    if (charChat) RelationBar(relations, coins, showRelations,
                        currentChat?.chatStyle == "messenger") { chatOptions = true }
                }
            },
        ) { inner ->
            Column(
                Modifier
                    .padding(inner)
                    .fillMaxSize()
                    .imePadding(),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                // «персонаж меняется»: предложение обновить карточку героя этого чата
                proposals.firstOrNull { p -> castCards.any { it.id == p.cardId } }?.let { p ->
                    val label = cardFields["character"]?.firstOrNull { it.key == p.field }?.label ?: p.field
                    ProposalBanner(p, label) { yes -> vm.answerProposal(p.id, yes) }
                }
                if ((mode == "quest" || mode == "gm") && stateMsg?.state != null) {
                    QuestPanel(stateMsg.state, coins) { stateEdit = stateMsg }
                }
                MessageList(
                    messages = messages,
                    modifier = Modifier.weight(1f).widthIn(max = ReadableWidth),
                    loadImage = { vm.image(it) },
                    onSelectVariant = { vm.selectVariant(it) },
                    onRegenerate = { vm.regenerate(it) },
                    onEdit = { m, resend -> editRequest = EditRequest(m, resend) },
                    onDelete = { vm.deleteMessage(it) },
                    onContinue = { vm.continueMessage(it) },
                    onPin = { id, pin -> vm.setPinned(id, pin) },
                    onRedraw = { m -> if (m.kind == "image") vm.regenerate(m.id) else vm.redraw(m.id) },
                    onSimilar = { art ->
                        drawRequest = DrawRequest(art.prompt, width = art.width, height = art.height,
                            enhance = false, profile = art.profile.ifBlank { null })
                    },
                    onSaveImage = { vm.saveImage(it) },
                    onRewrite = { rewriteFor = it },
                    header = { m -> SpeakerHeader(m, castCards, { vm.image(it) }) },
                    splitAnswers = charChat && currentChat?.chatStyle == "messenger",
                    actionsEnabled = conn.conn == Conn.ONLINE && !generating,
                )
                val canAct = ready && !generating
                Column(Modifier.widthIn(max = ReadableWidth)) {
                when {
                    mode == "quest" && lastAnswer != null && !lastAnswer.generating ->
                        ActionChips(lastAnswer.choices.map { c -> ChipAction(c, AppIcons.Next) { vm.send(c, emptyList()) {} } }, canAct)
                    mode == "story" && lastAnswer != null -> ActionChips(
                        (if (lastAnswer.generating) emptyList() else lastAnswer.choices.map { c ->
                            ChipAction(c, AppIcons.Next) { vm.send(c, emptyList(), choice = true) {} }
                        }) + listOfNotNull(
                        ChipAction("Новелла", AppIcons.Novel) { novelClosedFor = null },
                        ChipAction("Кадр", AppIcons.Frame) { frameOpen = true },
                        ChipAction("Выборы", AppIcons.Forks) { vm.forks { forksList = it } },
                        if (isDate) ChipAction("Завершить вечер", AppIcons.Finish) { vm.finishDate() } else null,
                        ChipAction("Что было", AppIcons.Recap) { vm.recap { recapText = it ?: "" } },
                        ChipAction("Продолжи") { vm.send("[Продолжи]", emptyList(), directive = true) {} },
                        ChipAction("Поворот") { vm.send("[Добавь неожиданный поворот сюжета]", emptyList(), directive = true) {} },
                        ChipAction("Перепиши") { vm.regenerate(lastAnswer.id) },
                        ChipAction("Подробнее") { vm.regenerate(lastAnswer.id, "подробнее: больше деталей, ощущений и диалогов") },
                        ChipAction("Короче") { vm.regenerate(lastAnswer.id, "короче и динамичнее") },
                    ), canAct)
                    mode == "gm" -> ActionChips(listOf(
                        ChipAction("Помощник ведущего", AppIcons.Assistant) { gmAssist = true },
                    ), canAct)
                    charChat -> Column {
                        ActionChips(listOfNotNull(
                            ChipAction("Подарить", AppIcons.Gift) { giftOpen = true },
                            ChipAction("Занять", AppIcons.Borrow) { borrowOpen = true },
                            if (debt > 0) ChipAction("Вернуть $debt", AppIcons.Repay) { vm.money("repay", debt, target?.id) } else null,
                            ChipAction("Свидание", AppIcons.Date) { dateOpen = true },
                        ), canAct)
                        if (castCards.size > 1) CastBar(castCards, replyAs, { vm.image(it) }) { replyAs = it }
                    }
                }
                InputBar(
                    enabled = ready,
                    vision = status.vision,
                    images = status.images,
                    generating = generating,
                    onSend = { text, images, restore ->
                        vm.send(text, images, replyAs) { ok -> if (!ok) restore() else replyAs = null }
                    },
                    onDraw = { text, sent -> drawRequest = DrawRequest(text, sent) },
                    onStop = { vm.stop() },
                    onError = { scope.launch { snackbar.showSnackbar(it) } },
                )
                }
            }
        }
    }
    if (wide) {
        Row(Modifier.fillMaxSize()) {
            Surface(color = MaterialTheme.colorScheme.surfaceContainerLow,
                modifier = Modifier.width(320.dp).fillMaxHeight()) {
                Box(Modifier.safeDrawingPadding()) { chatList() }
            }
            Box(Modifier.weight(1f)) { body() }
        }
    } else {
        ModalNavigationDrawer(
            drawerState = drawer,
            drawerContent = { ModalDrawerSheet(Modifier.widthIn(max = 320.dp)) { chatList() } },
        ) { body() }
    }

    // ---------------------------------------------------------------- диалоги
    drawRequest?.let { r ->
        LaunchedEffect(Unit) { vm.loadProfiles() }
        DrawDialog(
            initialPrompt = r.prompt,
            profiles = profiles,
            selected = r.profile,
            initialWidth = r.width,
            initialHeight = r.height,
            initialEnhance = r.enhance,
            onDraw = { prompt, profile, w, h, steps, seed, enhance, likeness ->
                drawRequest = null
                vm.draw(prompt, profile, w, h, steps, seed, enhance, likeness) { ok -> if (ok) r.sent(r.prompt) }
            },
            onEnhance = { text, done -> vm.enhancePrompt(text) { res -> done(res?.first) } },
            onDismiss = { drawRequest = null },
        )
    }

    if (imageModels) {
        ImageModelsDialog(vm, online = conn.conn == Conn.ONLINE) { imageModels = false }
    }

    if (settingsDialog) {
        val base = currentChat?.settings ?: defaultSettings
        SettingsDialog(
            initial = base,
            recommended = recommended,
            forChat = currentChat != null,
            onSave = { st, makeDefault ->
                vm.setSettings(st.copy(imageProfile = base.imageProfile), makeDefault)
                settingsDialog = false
            },
            onDismiss = { settingsDialog = false },
        )
    }

    if (memoryTab >= 0 && currentChat != null) {
        LaunchedEffect(currentChat.id) { vm.openMemory() }
        MemorySheet(
            memory = memory,
            lastCtx = messages.lastOrNull { it.ctx != null }?.ctx,
            initialTab = memoryTab,
            onDismiss = {
                memoryTab = -1
                vm.closeMemory()
            },
            onAddFact = { vm.addFact(it) },
            onEditFact = { id, t -> vm.editFact(id, t) },
            onPinFact = { id, p -> vm.pinFact(id, p) },
            onDeleteFact = { vm.deleteFact(it) },
            onSaveChronicle = { vm.saveChronicle(it) },
            onRefresh = { vm.refreshMemory() },
        )
    }

    if (permissionDenied) {
        AlertDialog(
            onDismissRequest = { permissionDenied = false },
            title = { Text("Нужен доступ к Wi-Fi Direct") },
            text = {
                Text("Без разрешения «Устройства поблизости» приложение не может подключиться к ПК. " +
                    "Если запрос больше не появляется, включите разрешение в настройках приложения.")
            },
            confirmButton = {
                TextButton(onClick = {
                    permissionDenied = false
                    ctx.startActivity(
                        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            Uri.fromParts("package", ctx.packageName, null))
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }) { Text("Настройки") }
            },
            dismissButton = {
                TextButton(onClick = { connectWithPermissions() }) { Text("Повторить") }
            },
        )
    }

    if (promptDialog) {
        SystemPromptDialog(
            initial = currentChat?.systemPrompt ?: defaultPrompt,
            forChat = currentChat != null,
            onSave = { text, makeDefault ->
                vm.setSystemPrompt(text, makeDefault)
                promptDialog = false
            },
            onDismiss = { promptDialog = false },
        )
    }

    if (renameDialog && currentChat != null) {
        TextDialog(
            title = "Название чата",
            initial = currentChat.title,
            confirm = "Сохранить",
            singleLine = true,
            onConfirm = {
                vm.renameChat(currentChat.id, it)
                renameDialog = false
            },
            onDismiss = { renameDialog = false },
        )
    }

    deleteTarget?.let { target ->
        ConfirmDialog(
            title = "Удалить чат?",
            text = "«${target.title.ifBlank { "Без названия" }}» удалится вместе со всеми ветками." +
                if (conn.conn != Conn.ONLINE) "\nСейчас нет связи: с телефона чат пропадёт сразу, " +
                    "а на ПК удалится при подключении." else "",
            confirm = "Удалить",
            onConfirm = {
                vm.deleteChat(target.id)
                deleteTarget = null
            },
            onDismiss = { deleteTarget = null },
        )
    }
    if (cardsOpen) {
        CardsScreen(vm, online = ready || conn.conn == Conn.ONLINE, onClose = { cardsOpen = false },
            onNewScene = { w -> cardsOpen = false; sceneRequest = SceneRequest(world = w, mode = "quest") })
    }
    sceneRequest?.let { r ->
        LaunchedEffect(Unit) { vm.loadCards() }
        SceneDialog(
            cards = cards,
            initialMode = r.mode,
            initialWorld = r.world,
            onCreate = { m, chars, persona, world, setup, style, done ->
                vm.createScene(m, chars, persona, world, setup, style) { ok -> done(ok); if (ok) sceneRequest = null }
            },
            onDismiss = { sceneRequest = null },
        )
    }
    rewriteFor?.let { m ->
        TextDialog(
            title = "Переписать ответ",
            initial = "",
            label = "Как переписать: «короче», «злее», «без пафоса», «пусть она откажет»…",
            confirm = "Переписать",
            onConfirm = { wish -> rewriteFor = null; vm.regenerate(m.id, wish) },
            onDismiss = { rewriteFor = null },
        )
    }
    galleryItems?.let { g ->
        GalleryDialog(g, { vm.image(it) }, onSave = { vm.saveImage(it) }, onDismiss = { galleryItems = null })
    }
    forksList?.let { f -> ForksDialog(f) { forksList = null } }
    if (frameOpen) {
        TextDialog(
            title = "Кадр",
            initial = "",
            label = "Одной строкой: «она стоит у окна, дождь, грустит» — модель развернёт в сцену",
            confirm = "Снять",
            onConfirm = { t -> frameOpen = false; vm.send("[Кадр: ${t.trim()}]", emptyList(), directive = true) {} },
            onDismiss = { frameOpen = false },
        )
    }
    if (borrowOpen) {
        TextDialog(
            title = "Занять" + (target?.let { " у: ${it.name}" } ?: ""),
            initial = "50",
            label = "Сколько монет — даст или нет, решит персонаж",
            confirm = "Попросить",
            singleLine = true,
            onConfirm = { t ->
                borrowOpen = false
                t.trim().toIntOrNull()?.let { vm.money("borrow", it, target?.id) }
            },
            onDismiss = { borrowOpen = false },
        )
    }
    if (dateOpen) {
        TextDialog(
            title = "Свидание" + (target?.let { ": ${it.name}" } ?: ""),
            initial = "",
            label = "Куда и как: «ужин в маленьком кафе у моря», «ночная прогулка по городу»… Можно пусто",
            confirm = "Начать",
            allowEmpty = true,
            onConfirm = { t -> dateOpen = false; vm.startDate(t.trim(), target?.id) },
            onDismiss = { dateOpen = false },
        )
    }
    recapText?.let { t ->
        AlertDialog(
            onDismissRequest = { recapText = null },
            title = { Text("В предыдущих сериях") },
            text = { Text(t.ifBlank { "Пересказ не получился" }) },
            confirmButton = { TextButton(onClick = { recapText = null }) { Text("Понятно") } },
        )
    }
    if (chatOptions && currentChat != null) {
        ChatOptionsDialog(
            messenger = currentChat.chatStyle == "messenger",
            initiative = currentChat.initiative,
            showRelations = showRelations,
            relations = relations,
            onStyle = { vm.setChatOption("chat_style", if (it) "messenger" else "roleplay") },
            onInitiative = { vm.setChatOption("initiative", it) },
            onShowRelations = { vm.setShowRelations(it) },
            onReset = { vm.resetRelations() },
            onDismiss = { chatOptions = false },
        )
    }
    if (giftOpen) {
        TextDialog(
            title = "Подарок" + (castCards.firstOrNull { it.id == replyAs }?.let { " для ${it.name}" } ?: ""),
            initial = "",
            label = "Что подарить: «букет ромашек», «книгу стихов», «билеты в кино»… Цену назначит ПК" +
                (coins?.let { ", у вас $it монет" } ?: ""),
            confirm = "Подарить",
            onConfirm = { t -> giftOpen = false; vm.gift(t.trim(), replyAs) { if (it) replyAs = null } },
            onDismiss = { giftOpen = false },
        )
    }
    if (gmAssist) {
        TextDialog(
            title = "Помощник ведущего",
            initial = "",
            label = "Что нужно: «опиши таверну», «реплика стражника», «какое осложнение добавить», «награда за квест»…",
            confirm = "Спросить",
            onConfirm = { t -> gmAssist = false; vm.send("[Помощник ведущего] ${t.trim()}", emptyList(), directive = true) {} },
            onDismiss = { gmAssist = false },
        )
    }
    stateEdit?.let { m ->
        StateDialog(
            initial = m.state ?: dev.llmbridge.client.QuestState(),
            onSave = { st -> vm.saveState(m.id, st); stateEdit = null },
            onDismiss = { stateEdit = null },
        )
    }

    if (forgetDialog) {
        ConfirmDialog(
            title = "Забыть ПК?",
            text = "Для подключения понадобится снова отсканировать QR-код. Чаты останутся на ПК.",
            confirm = "Забыть",
            onConfirm = {
                forgetDialog = false
                vm.forget()
            },
            onDismiss = { forgetDialog = false },
        )
    }

    editRequest?.let { req ->
        TextDialog(
            title = if (req.resend) "Изменить и отправить заново" else "Изменить сообщение",
            initial = req.msg.content,
            confirm = if (req.resend) "Отправить" else "Сохранить",
            singleLine = false,
            onConfirm = { text ->
                if (req.resend) vm.resend(req.msg.id, text) else vm.edit(req.msg.id, text)
                editRequest = null
            },
            onDismiss = { editRequest = null },
        )
    }
}

private fun statusLine(c: ConnState, s: ServerStatus, permissionDenied: Boolean): String = when {
    permissionDenied -> "Нет разрешения на Wi-Fi Direct"
    c.conn == Conn.ONLINE -> when (s.llama) {
        "ready" -> if (s.busy) "Генерация…" else "Готов · ${s.model.removeSuffix(".gguf")}"
        "swapped" -> if (s.busy) "Рисую…" else "Готов · модель выгружена на время рисования"
        "loading" -> "Модель загружается…"
        "down" -> "Модель на ПК не запущена"
        else -> "Ошибка модели на ПК"
    }
    c.conn == Conn.STOPPED -> "Отключено"
    else -> c.message.ifEmpty { "Подключение…" }
}

// ================================================================ список чатов

@Composable
private fun ChatList(
    chats: List<ChatInfo>,
    currentId: Long?,
    onNew: () -> Unit,
    onOpen: (Long) -> Unit,
    onDelete: (ChatInfo) -> Unit,
    onCards: () -> Unit,
    onScene: () -> Unit,
    cards: List<Card>,
    loadImage: suspend (String) -> android.graphics.Bitmap?,
) {
    Column(Modifier.fillMaxSize()) {
        Text(
            "Чаты",
            style = MaterialTheme.typography.titleLarge,
            modifier = Modifier.padding(start = 24.dp, top = 24.dp, bottom = 12.dp),
        )
        NavigationDrawerItem(
            label = { Text("Новый чат") },
            icon = { Icon(Icons.Filled.Add, contentDescription = null) },
            selected = currentId == null,
            onClick = onNew,
            modifier = Modifier.padding(horizontal = 12.dp),
        )
        NavigationDrawerItem(
            label = { Text("Новая сцена: квест, история…") },
            icon = { Icon(Icons.Filled.PlayArrow, contentDescription = null) },
            selected = false,
            onClick = onScene,
            modifier = Modifier.padding(horizontal = 12.dp),
        )
        NavigationDrawerItem(
            label = { Text("Персонажи, персоны, миры") },
            icon = { Icon(Icons.Filled.Person, contentDescription = null) },
            selected = false,
            onClick = onCards,
            modifier = Modifier.padding(horizontal = 12.dp),
        )
        HorizontalDivider(Modifier.padding(vertical = 8.dp))
        LazyColumn(Modifier.weight(1f)) {
            items(chats, key = { it.id }) { c ->
                val card = cards.firstOrNull { it.id == c.characterId }
                NavigationDrawerItem(
                    label = {
                        Column {
                            Text(c.title.ifBlank { "Без названия" }, maxLines = 1,
                                overflow = TextOverflow.Ellipsis)
                            if (c.preview.isNotBlank()) {
                                Text(
                                    c.preview.replace('\n', ' '),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                        }
                    },
                    selected = c.id == currentId,
                    onClick = { onOpen(c.id) },
                    icon = if (card == null) null else {
                        { Avatar(card, loadImage, 32) }
                    },
                    badge = {
                        IconButton(onClick = { onDelete(c) }) {
                            Icon(Icons.Filled.Delete, contentDescription = "Удалить",
                                tint = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    },
                    modifier = Modifier.padding(horizontal = 12.dp),
                )
            }
        }
    }
}

// ================================================================ отношения

/** Под заголовком чата с персонажем: отношения (если показ включён) и монеты. */
@Composable
private fun RelationBar(relations: List<dev.llmbridge.client.Relation>, coins: Int?, show: Boolean,
                        messenger: Boolean, onClick: () -> Unit) {
    val color = MaterialTheme.colorScheme.onSurfaceVariant
    val style = MaterialTheme.typography.labelMedium
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(start = 16.dp, end = 8.dp, top = 4.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(Modifier.weight(1f).horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(14.dp), verticalAlignment = Alignment.CenterVertically) {
            IconLabel(if (messenger) AppIcons.Messenger else AppIcons.Roleplay,
                if (messenger) "переписка" else "рядом", style = style, color = color)
            if (show) relations.forEach { r ->
                val face = when {
                    r.sympathy <= -20 -> AppIcons.MoodBad
                    r.sympathy < 15 -> AppIcons.MoodNeutral
                    r.sympathy < 50 -> AppIcons.MoodGood
                    else -> AppIcons.Love
                }
                IconLabel(face, (if (relations.size > 1) "${r.name}: " else "") + r.status +
                    " · симпатия ${r.sympathy} · доверие ${r.trust}" +
                    (if (r.mood.isNotBlank() && r.mood != "обычное") " · ${r.mood}" else ""),
                    style = style, color = if (r.sympathy >= 50) MaterialTheme.colorScheme.tertiary else color)
            }
            if (coins != null) IconLabel(AppIcons.Coins, coins.toString(), style = style, color = color)
        }
        Icon(AppIcons.Tune, contentDescription = "Настройки общения", tint = color, modifier = Modifier.size(18.dp))
    }
}

// ================================================================ контекст

@Composable
private fun ContextBar(messages: List<Msg>, status: ServerStatus, onClick: () -> Unit) {
    if (status.nCtx <= 0) return
    // последний ответ, для которого модель сообщила расход токенов
    val last = messages.lastOrNull { it.promptTokens != null }
    val used = if (last == null) 0 else (last.promptTokens ?: 0) + (last.completionTokens ?: 0)
    if (used == 0 && messages.isEmpty()) return
    val frac = (used.toFloat() / status.nCtx).coerceIn(0f, 1f)
    val color = when {
        frac >= 0.9f -> MaterialTheme.colorScheme.error
        frac >= 0.75f -> MaterialTheme.colorScheme.tertiary
        else -> MaterialTheme.colorScheme.primary
    }
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        LinearProgressIndicator(
            progress = { frac },
            modifier = Modifier.weight(1f),
            color = color,
        )
        Spacer(Modifier.width(8.dp))
        Text(
            "Контекст ${kTok(used)} / ${kTok(status.nCtx)}",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

private fun kTok(n: Int): String =
    if (n < 1000) n.toString() else String.format(java.util.Locale.US, "%.1fk", n / 1000f)

// ================================================================= диалоги

@Composable
private fun SystemPromptDialog(
    initial: String,
    forChat: Boolean,
    onSave: (String, Boolean) -> Unit,
    onDismiss: () -> Unit,
) {
    var text by rememberSaveable { mutableStateOf(initial) }
    var makeDefault by rememberSaveable { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Системный промпт") },
        text = {
            Column {
                Text(
                    if (forChat) "Инструкция модели для этого чата: роль, стиль, язык ответов."
                    else "Промпт для новых чатов.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 120.dp, max = 320.dp),
                    placeholder = { Text("Например: Отвечай кратко и по-русски.") },
                )
                if (forChat) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.clickable { makeDefault = !makeDefault },
                    ) {
                        Checkbox(checked = makeDefault, onCheckedChange = { makeDefault = it })
                        Text("Использовать и для новых чатов", style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = { onSave(text, makeDefault) }) { Text("Сохранить") } },
        dismissButton = {
            Row {
                if (text.isNotEmpty()) {
                    TextButton(onClick = { text = "" }) { Text("Очистить") }
                }
                TextButton(onClick = onDismiss) { Text("Отмена") }
            }
        },
    )
}

@Composable
internal fun TextDialog(
    title: String,
    initial: String,
    confirm: String,
    singleLine: Boolean = false,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
    label: String? = null,
    allowEmpty: Boolean = false,
) {
    var text by rememberSaveable { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                singleLine = singleLine,
                placeholder = label?.let { { Text(it) } },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 360.dp),
            )
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(text) }, enabled = allowEmpty || text.isNotBlank()) { Text(confirm) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Отмена") } },
    )
}

@Composable
internal fun ConfirmDialog(
    title: String,
    text: String,
    confirm: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(text) },
        confirmButton = { TextButton(onClick = onConfirm) { Text(confirm) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Отмена") } },
    )
}

/** Открыть диалог рисования: с текстом из поля ввода или «похожую» на готовую картинку. */
private data class DrawRequest(
    val prompt: String,
    val sent: (String) -> Unit = {},
    val width: Int = 0,
    val height: Int = 0,
    val enhance: Boolean = true,
    val profile: String? = null,
)

/** Открыть диалог новой сцены (из меню или из карточки мира). */
private data class SceneRequest(val world: Long? = null, val mode: String = "chat")
