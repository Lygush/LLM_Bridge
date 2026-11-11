package dev.llmbridge.client.ui

import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.vector.ImageVector
import android.graphics.Bitmap
import androidx.activity.compose.BackHandler
import androidx.compose.animation.Crossfade
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.IconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.llmbridge.client.Card
import dev.llmbridge.client.ChatViewModel
import dev.llmbridge.client.Msg

/** Страница новеллы: фон (место), кто говорит и с какой эмоцией, текст. */
private data class Page(
    val placeKey: String,
    val placeName: String,
    val speaker: Card?,
    val name: String,
    val emotion: String,
    val text: String,
    val msgId: Long,
)

private const val PAGE_CHARS = 260

/** Длинный абзац — на несколько страниц по предложениям. */
private fun paginate(text: String): List<String> {
    if (text.length <= PAGE_CHARS) return listOf(text)
    val out = mutableListOf<String>()
    val cur = StringBuilder()
    Regex("[^.!?…]+[.!?…]*\\s*").findAll(text).forEach { m ->
        if (cur.length + m.value.length > PAGE_CHARS && cur.isNotEmpty()) {
            out += cur.toString().trim(); cur.clear()
        }
        cur.append(m.value)
    }
    if (cur.isNotBlank()) out += cur.toString().trim()
    return out
}

private fun buildPages(messages: List<Msg>, cast: List<Card>): List<Page> {
    var key = ""
    var place = ""
    val pages = mutableListOf<Page>()
    messages.filter { it.role == "assistant" && !it.generating && it.beats.isNotEmpty() }.forEach { m ->
        m.beats.forEach { b ->
            when (b.type) {
                "place" -> { key = b.key; place = b.name }
                "line" -> {
                    val who = cast.firstOrNull { it.id == b.characterId }
                        ?: cast.firstOrNull { it.name.equals(b.name, ignoreCase = true) }
                    paginate(b.text).forEach { pages += Page(key, place, who, b.name, b.emotion, it, m.id) }
                }
                else -> paginate(b.text).forEach { pages += Page(key, place, null, "", "calm", it, m.id) }
            }
        }
    }
    return pages
}

/**
 * Экран визуальной новеллы для режима «История»: фон места, спрайт говорящего с эмоцией,
 * текст листается смахиванием влево-вправо или стрелками. В конце — ваш ход.
 */
@Composable
fun NovelScreen(vm: ChatViewModel, cast: List<Card>, onClose: () -> Unit) {
    val messages by vm.messages.collectAsStateWithLifecycle()
    val backgrounds by vm.vnBackgrounds.collectAsStateWithLifecycle()
    val pending by vm.vnPending.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.loadVn() }
    val pages = remember(messages, cast) { buildPages(messages, cast) }
    val generating = messages.any { it.generating }
    // открываем с начала последнего ответа
    val lastMsg = pages.lastOrNull()?.msgId
    var index by rememberSaveable { mutableStateOf(pages.indexOfFirst { it.msgId == lastMsg }.coerceAtLeast(0)) }
    // пришёл новый ответ, а мы стояли в конце — листаем к его началу
    var seen by rememberSaveable { mutableStateOf(pages.size) }
    LaunchedEffect(pages.size) {
        if (pages.size > seen && index >= seen - 1) index = seen.coerceAtMost(pages.lastIndex)
        seen = pages.size
    }
    val page = pages.getOrNull(index)
    val atEnd = index >= pages.lastIndex
    var input by rememberSaveable { mutableStateOf("") }

    fun next() { if (index < pages.lastIndex) index++ }
    fun prev() { if (index > 0) index-- }

    // Экран живёт в окне приложения (не в диалоге): так системные панели учитываются надёжно.
    BackHandler(onBack = onClose)
    Box(
        Modifier
            .fillMaxSize()
            .background(Color(0xFF101014))
            // листание: смахнуть влево — дальше, вправо — назад
            .pointerInput(pages.size) {
                var total = 0f
                detectHorizontalDragGestures(
                    onDragStart = { total = 0f },
                    onDragEnd = { if (total < -70f) next() else if (total > 70f) prev() },
                ) { _, drag -> total += drag }
            },
    ) {
        // фон места — во весь экран, под системными панелями
        val bgName = page?.let { backgrounds[it.placeKey] }
        Crossfade(bgName, label = "bg") { name ->
            if (name != null) FitImage(name, { vm.image(it) }, ContentScale.Crop, Modifier.fillMaxSize())
        }
        // спрайт: на странице с репликой — говорящий; на авторском тексте остаётся тот, кто
        // говорил последним в этой же сцене (чуть приглушённый), чтобы герой не «мигал»
        val holder = page?.speaker ?: pages.take(index).lastOrNull { it.speaker != null }
            ?.takeIf { it.msgId == page?.msgId && it.placeKey == page.placeKey }?.speaker
        val emotion = if (page?.speaker != null) page.emotion
            else pages.take(index).lastOrNull { it.speaker != null }?.emotion ?: "calm"
        val sprite = holder?.let { it.sprites[emotion] ?: it.sprites["calm"] ?: it.portrait }
        val spriteAlpha = if (page?.speaker != null) 1f else 0.72f

        val topBar: @Composable () -> Unit = {
            Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                NovelButton("Текстом", AppIcons.TextView, onClick = onClose)
                Spacer(Modifier.weight(1f))
                val place = page?.placeName.orEmpty()
                val drawing = page?.placeKey?.let { it in pending } == true
                val pageKey = page?.placeKey.orEmpty()
                if (place.isNotBlank() && !drawing && pageKey !in backgrounds) {
                    NovelButton("Фон", AppIcons.Background) { vm.drawBackground(place) }
                    Spacer(Modifier.width(6.dp))
                }
                if (place.isNotBlank()) {
                    IconLabel(AppIcons.Place, place + if (drawing) " · рисую фон…" else "", color = Color.White,
                        style = MaterialTheme.typography.labelMedium,
                        modifier = Modifier.widthIn(max = 240.dp)
                            .background(Color.Black.copy(alpha = 0.45f), RoundedCornerShape(10.dp))
                            .padding(horizontal = 10.dp, vertical = 6.dp))
                }
            }
        }
        val spriteBox: @Composable (Modifier) -> Unit = { m ->
            Box(m, contentAlignment = Alignment.BottomCenter) {
                Crossfade(sprite, label = "sprite") { name ->
                    if (name != null) FitImage(name, { vm.image(it) }, ContentScale.Fit,
                        Modifier.fillMaxSize().alpha(spriteAlpha))
                }
            }
        }
        val textCard: @Composable () -> Unit = {
            if (page != null) {
                Surface(color = Color.Black.copy(alpha = 0.76f), shape = RoundedCornerShape(18.dp),
                    modifier = Modifier.fillMaxWidth().heightIn(min = 120.dp)) {
                    Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 2.dp)) {
                        if (page.name.isNotBlank()) {
                            Text(page.name, color = Color(0xFFFFD27A), fontWeight = FontWeight.Bold,
                                style = MaterialTheme.typography.titleSmall)
                            Spacer(Modifier.height(4.dp))
                        }
                        Box(Modifier.heightIn(max = 220.dp).verticalScroll(rememberScrollState())) {
                            MarkdownText(page.text, color = Color.White,
                                style = if (page.name.isBlank()) MaterialTheme.typography.bodyLarge.copy(fontStyle = FontStyle.Italic)
                                else MaterialTheme.typography.bodyLarge)
                        }
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            IconButton(onClick = { prev() }, enabled = index > 0) {
                                Icon(AppIcons.Prev, contentDescription = "Назад",
                                    tint = Color.White.copy(alpha = if (index > 0) 1f else 0.3f))
                            }
                            Text(
                                when {
                                    !atEnd -> "${index + 1} / ${pages.size} · листайте в стороны"
                                    generating -> "пишется продолжение…"
                                    else -> "${index + 1} / ${pages.size} · ваш ход"
                                },
                                color = Color.White.copy(alpha = 0.6f), style = MaterialTheme.typography.labelSmall,
                                textAlign = TextAlign.Center, modifier = Modifier.weight(1f))
                            IconButton(onClick = { next() }, enabled = !atEnd) {
                                Icon(AppIcons.Next, contentDescription = "Дальше",
                                    tint = Color.White.copy(alpha = if (!atEnd) 1f else 0.3f))
                            }
                        }
                    }
                }
            } else {
                Text(if (generating) "Пишется начало истории…" else "Здесь появятся сцены истории",
                    color = Color.White, modifier = Modifier.padding(16.dp))
            }
        }
        // ваш ход: развилка, команды, свой текст
        val controls: @Composable () -> Unit = {
            if (atEnd && !generating) {
                Spacer(Modifier.height(6.dp))
                messages.lastOrNull { it.role == "assistant" }?.choices?.forEach { c ->
                    Row(Modifier.fillMaxWidth().padding(bottom = 4.dp)) {
                        NovelButton(c, AppIcons.Next) { vm.send(c, emptyList(), choice = true) {} }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    NovelButton("Продолжи") { vm.send("[Продолжи]", emptyList(), directive = true) {} }
                    NovelButton("Поворот") { vm.send("[Добавь неожиданный поворот сюжета]", emptyList(), directive = true) {} }
                }
                Spacer(Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = input,
                        onValueChange = { input = it },
                        placeholder = { Text("Что дальше: «она открывает дверь…»", color = Color.White.copy(alpha = 0.5f)) },
                        maxLines = 4,
                        shape = RoundedCornerShape(18.dp),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedTextColor = Color.White, unfocusedTextColor = Color.White,
                            focusedContainerColor = Color.Black.copy(alpha = 0.6f),
                            unfocusedContainerColor = Color.Black.copy(alpha = 0.6f),
                        ),
                        modifier = Modifier.weight(1f),
                    )
                    IconButton(onClick = {
                        val t = input.trim()
                        if (t.isNotEmpty()) vm.send(t, emptyList()) { ok -> if (ok) input = "" }
                    }) { Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Отправить", tint = Color.White) }
                }
            }
        }

        val frame = Modifier.fillMaxSize().safeDrawingPadding().imePadding().padding(horizontal = 10.dp)
        if (isLandscapePhone() || isWideScreen()) {
            // широкий или низкий экран: герой слева, текст и управление — колонкой справа
            Column(frame) {
                topBar()
                Row(Modifier.fillMaxWidth().weight(1f), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    spriteBox(Modifier.weight(0.42f).fillMaxHeight())
                    Column(Modifier.weight(0.58f).fillMaxHeight().verticalScroll(rememberScrollState()),
                        verticalArrangement = Arrangement.Bottom) {
                        textCard()
                        controls()
                        Spacer(Modifier.height(6.dp))
                    }
                }
            }
        } else {
            Column(frame, horizontalAlignment = Alignment.CenterHorizontally) {
                topBar()
                spriteBox(Modifier.fillMaxWidth().weight(1f))
                Column(Modifier.widthIn(max = ReadableWidth)) {
                    textCard()
                    controls()
                }
                Spacer(Modifier.height(6.dp))
            }
        }
    }
}

@Composable
private fun NovelButton(text: String, icon: ImageVector? = null, onClick: () -> Unit) {
    TextButton(onClick = onClick,
        modifier = Modifier.background(Color.Black.copy(alpha = 0.55f), RoundedCornerShape(12.dp))) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = Color.White, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
        }
        Text(text, color = Color.White)
    }
}

@Composable
private fun FitImage(name: String, load: suspend (String) -> Bitmap?, scale: ContentScale, modifier: Modifier) {
    val bmp by produceState<Bitmap?>(null, name) { value = load(name) }
    val b = bmp ?: return
    Image(b.asImageBitmap(), contentDescription = null, contentScale = scale, modifier = modifier)
}
