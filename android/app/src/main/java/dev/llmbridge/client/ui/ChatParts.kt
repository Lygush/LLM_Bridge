package dev.llmbridge.client.ui

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.DragInteraction
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.OutlinedButton
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SmallFloatingActionButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import dev.llmbridge.client.ImageInfo
import dev.llmbridge.client.Attachment
import dev.llmbridge.client.ImageUtil
import dev.llmbridge.client.Msg
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import kotlin.math.max
import kotlin.math.min

const val MAX_ATTACHMENTS = 4

// ============================================================ плавный вывод

/**
 * Буфер вывода: текст приходит рывками, а показывается равномерно.
 * Отставание догоняется примерно за треть секунды, но не медленнее 40 символов в секунду,
 * поэтому и медленная, и быстрая генерация выглядят плавно.
 */
@Composable
fun rememberSmoothText(id: Long, target: String, generating: Boolean): String {
    // история показывается сразу; анимируется только то, что генерируется на глазах
    var shown by remember(id) { mutableIntStateOf(if (generating) 0 else target.length) }
    val targetState = rememberUpdatedState(target)
    val generatingState = rememberUpdatedState(generating)
    val active = generating || shown < target.length
    LaunchedEffect(id, active) {
        if (!active) return@LaunchedEffect
        var last = 0L
        var acc = 0.0
        while (true) {
            val done = withFrameNanos { now ->
                val t = targetState.value
                if (shown > t.length) shown = t.length          // текст заменили (правка, перечитывание)
                val backlog = t.length - shown
                if (backlog > 0) {
                    val dt = if (last == 0L) 0.016 else (now - last) / 1e9
                    acc += max(40.0, backlog / 0.33) * min(dt, 0.1)
                    val step = acc.toInt()
                    if (step > 0) {
                        var n = min(t.length, shown + step)
                        if (n < t.length && n > 0 && t[n - 1].isHighSurrogate()) n++   // не резать эмодзи
                        shown = n
                        acc -= step
                    }
                }
                last = now
                backlog <= 0
            }
            if (done && !generatingState.value) break
        }
    }
    val t = targetState.value
    return if (shown >= t.length) t else t.substring(0, shown)
}

/** Три пульсирующие точки — модель думает. */
@Composable
fun TypingDots(color: Color = MaterialTheme.colorScheme.onSurfaceVariant) {
    val tr = rememberInfiniteTransition(label = "dots")
    Row(horizontalArrangement = Arrangement.spacedBy(5.dp), modifier = Modifier.padding(vertical = 6.dp)) {
        for (i in 0 until 3) {
            val a by tr.animateFloat(
                initialValue = 0.25f, targetValue = 1f,
                animationSpec = infiniteRepeatable(tween(500, delayMillis = i * 160), RepeatMode.Reverse),
                label = "dot$i",
            )
            Box(Modifier.size(7.dp).alpha(a).background(color, CircleShape))
        }
    }
}

// ================================================================ список

@Composable
fun MessageList(
    messages: List<Msg>,
    modifier: Modifier,
    loadImage: suspend (String) -> Bitmap?,
    onSelectVariant: (Long) -> Unit,
    onRegenerate: (Long) -> Unit,
    onEdit: (Msg, Boolean) -> Unit,
    onDelete: (Long) -> Unit,
    onContinue: (Long) -> Unit,
    onPin: (Long, Boolean) -> Unit,
    actionsEnabled: Boolean,
    onRedraw: (Msg) -> Unit = {},
    onSimilar: (ImageInfo) -> Unit = {},
    onSaveImage: (String) -> Unit = {},
    onRewrite: (Msg) -> Unit = {},
    header: @Composable (Msg) -> Unit = {},
    splitAnswers: Boolean = false,
) {
    // Следование за ответом: пока пользователь внизу, список прокручивается вслед за
    // растущим текстом. Касание пальцем отключает следование — текст стоит на месте и
    // его можно читать. Включается снова у самого низа или кнопкой «вниз».
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val last = messages.lastOrNull()
    var viewer by remember { mutableStateOf<Pair<String, Long>?>(null) }   // картинка и её сообщение
    var follow by remember { mutableStateOf(true) }

    LaunchedEffect(listState) {
        listState.interactionSource.interactions.collect { i ->
            when (i) {
                is DragInteraction.Start -> follow = false
                is DragInteraction.Stop, is DragInteraction.Cancel ->
                    if (!listState.canScrollForward) follow = true
            }
        }
    }
    LaunchedEffect(listState) {
        // после инерционной прокрутки до самого низа — снова следовать
        snapshotFlow { listState.isScrollInProgress to listState.canScrollForward }
            .collect { (moving, canForward) -> if (!moving && !canForward) follow = true }
    }
    LaunchedEffect(listState) {
        // текст вырос ниже края экрана — догнать, если следуем
        snapshotFlow { follow && listState.canScrollForward }
            .collect { need -> if (need) listState.scrollBy(1_000_000f) }
    }
    // новое сообщение (своё или ответ) — к низу и снова следовать
    LaunchedEffect(last?.id) {
        if (messages.isNotEmpty()) {
            follow = true
            listState.scrollToItem(messages.lastIndex)
            listState.scrollBy(1_000_000f)
        }
    }
    val showDown by remember { derivedStateOf { !follow && listState.canScrollForward } }

    if (messages.isEmpty()) {
        Box(modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            Text("Напишите сообщение", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        return
    }
    Box(modifier.fillMaxWidth()) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            state = listState,
            contentPadding = PaddingValues(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp, Alignment.Bottom),
        ) {
            items(messages, key = { it.id }) { m ->
                if (m.hidden) return@items
                if (m.directive && m.role == "user") {
                    DirectiveRow(m)
                    return@items
                }
                header(m)
                MessageBubble(
                    m = m,
                    isLast = m.id == last?.id,
                    actionsEnabled = actionsEnabled,
                    loadImage = loadImage,
                    onOpenImage = { viewer = it to m.id },
                    onRedraw = onRedraw,
                    onSelectVariant = onSelectVariant,
                    onRegenerate = onRegenerate,
                    onEdit = onEdit,
                    onDelete = onDelete,
                    onContinue = onContinue,
                    onPin = onPin,
                    onRewrite = onRewrite,
                    split = splitAnswers,
                )
            }
        }
        AnimatedVisibility(
            visible = showDown,
            enter = fadeIn(), exit = fadeOut(),
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(12.dp),
        ) {
            SmallFloatingActionButton(onClick = {
                follow = true
                scope.launch {
                    listState.animateScrollToItem(messages.lastIndex)
                    listState.scrollBy(1_000_000f)
                }
            }) {
                Icon(Icons.Filled.KeyboardArrowDown, contentDescription = "Вниз")
            }
        }
    }
    viewer?.let { (name, mid) ->
        val m = messages.firstOrNull { it.id == mid }
        ImageViewer(
            name = name, load = loadImage, msg = m, actionsEnabled = actionsEnabled,
            onRedraw = { m?.let { viewer = null; onRedraw(it) } },
            onSimilar = { m?.art?.let { viewer = null; onSimilar(it) } },
            onSave = { onSaveImage(name) },
            onClose = { viewer = null },
        )
    }
}

// ============================================================== сообщение

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MessageBubble(
    m: Msg,
    isLast: Boolean,
    actionsEnabled: Boolean,
    loadImage: suspend (String) -> Bitmap?,
    onOpenImage: (String) -> Unit,
    onSelectVariant: (Long) -> Unit,
    onRegenerate: (Long) -> Unit,
    onEdit: (Msg, Boolean) -> Unit,
    onDelete: (Long) -> Unit,
    onContinue: (Long) -> Unit,
    onPin: (Long, Boolean) -> Unit,
    onRedraw: (Msg) -> Unit,
    onRewrite: (Msg) -> Unit,
    split: Boolean = false,
) {
    val mine = m.role == "user"
    val clipboard = LocalClipboardManager.current
    var showReasoning by rememberSaveable(m.id) { mutableStateOf(false) }
    var menu by remember { mutableStateOf(false) }
    val isImage = m.kind == "image"
    val art = m.art
    // модель рисует к своему ответу: картинка под текстом, а не над ним
    val below = !isImage && !mine && (m.drawnByModel || (m.generating && m.stage in DRAW_STAGES))
    val shownContent = when {
        isImage -> (art?.request?.ifBlank { null } ?: m.prompt).let { p ->
            if (p.isNotBlank()) "_${p.replace("_", "\\_")}_" else ""
        }
        m.kind == "image_request" -> m.content.trimStart()
        else -> m.content.trimStart()
    }
    val smooth = rememberSmoothText(m.id, shownContent, m.generating && !isImage)
    // переписка: ответ из нескольких сообщений (через пустую строку) — отдельными пузырями
    val chunks = if (split && !mine && !isImage && !m.generating)
        smooth.split(Regex("\n\\s*\n")).map { it.trim() }.filter { it.isNotEmpty() } else emptyList()
    val text = if (chunks.size > 1) chunks.last() else smooth

    Column(
        Modifier.fillMaxWidth(),
        horizontalAlignment = if (mine) Alignment.End else Alignment.Start,
    ) {
        if (m.images.isNotEmpty() && !below) {
            ImagesRow(m, loadImage, onOpenImage)
            if (isImage && art != null) ArtBadge(art)
            if (m.content.isNotBlank()) Spacer(Modifier.height(4.dp))
        }
        chunks.dropLast(1).forEach { part ->
            Surface(
                shape = RoundedCornerShape(18.dp, 18.dp, 18.dp, 4.dp),
                color = MaterialTheme.colorScheme.surfaceContainerHigh,
                modifier = Modifier.widthIn(max = 360.dp),
            ) {
                MarkdownText(part, style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp))
            }
            Spacer(Modifier.height(4.dp))
        }
        if (shownContent.isNotBlank() || !mine) Box {
            Surface(
                shape = RoundedCornerShape(
                    topStart = 18.dp, topEnd = 18.dp,
                    bottomStart = if (mine) 18.dp else 4.dp, bottomEnd = if (mine) 4.dp else 18.dp,
                ),
                color = if (mine) MaterialTheme.colorScheme.primaryContainer
                else MaterialTheme.colorScheme.surfaceContainerHigh,
                modifier = Modifier
                    .widthIn(max = bubbleWidth(mine))
                    .combinedClickable(onClick = {}, onLongClick = { menu = true }),
            ) {
                Column(Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                    if (m.pinned) {
                        IconLabel(AppIcons.Pin, "закреплено", style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant, iconSize = 14.dp)
                    }
                    if (isImage || m.kind == "image_request") {
                        IconLabel(AppIcons.Draw, if (isImage) "Рисунок" else "Просьба нарисовать",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant, iconSize = 14.dp)
                    }
                    if (m.reasoning.isNotEmpty()) {
                        IconLabel(
                            if (showReasoning) AppIcons.Less else AppIcons.More,
                            if (m.generating && m.content.isEmpty()) "Размышляет…" else "Размышления",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.clickable { showReasoning = !showReasoning },
                        )
                        if (showReasoning) {
                            Text(
                                m.reasoning.trim(),
                                style = MaterialTheme.typography.bodySmall,
                                fontStyle = FontStyle.Italic,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        if (m.content.isNotEmpty()) Spacer(Modifier.height(6.dp))
                    }
                    if (isImage && m.generating) {
                        ImageProgress(m)
                        Spacer(Modifier.height(6.dp))
                    } else if (!isImage && m.generating && m.content.isEmpty() && m.stage in STAGE_TEXT &&
                        m.stage !in DRAW_STAGES) {
                        Text(STAGE_TEXT.getValue(m.stage), fontStyle = FontStyle.Italic,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    when {
                        text.isNotEmpty() && !(isImage && m.generating) -> MarkdownText(text,
                            style = if (isImage) MaterialTheme.typography.bodyMedium else MaterialTheme.typography.bodyLarge)
                        isImage -> {}
                        m.generating && m.stage in STAGE_TEXT -> {}
                        m.generating && m.stage in DRAW_STAGES -> {}
                        m.generating && m.stage == "summarizing" ->
                            Text("Сжимаю старую часть диалога в хронику…", fontStyle = FontStyle.Italic,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        m.generating && m.reasoning.isEmpty() -> TypingDots()
                    }
                    if (!isImage && m.generating && m.stage in DRAW_STAGES) {
                        if (text.isNotEmpty()) Spacer(Modifier.height(8.dp))
                        ImageProgress(m)
                    }
                    if (art != null && art.error.isNotBlank() && !m.generating) {
                        Text("Картинка не получилась: ${art.error}", color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodySmall)
                    }
                    if (m.truncated && !m.generating) {
                        Text("Оборвано по пределу длины — «Продолжить» в меню",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    when (m.status) {
                        "error" -> Text(m.error ?: "Ошибка", color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodySmall)
                        "cancelled" -> Text("Остановлено", style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            MessageMenu(m, menu, isLast, actionsEnabled, { menu = false },
                onCopy = { clipboard.setText(AnnotatedString(m.content)) },
                onEdit = onEdit, onRegenerate = onRegenerate, onContinue = onContinue,
                onPin = onPin, onDelete = onDelete, onRedraw = onRedraw, onRewrite = onRewrite)
        }
        if (m.images.isNotEmpty() && below) {
            Spacer(Modifier.height(4.dp))
            ImagesRow(m, loadImage, onOpenImage)
            if (art != null) ArtBadge(art)
        }
        // как ход повлиял на отношения: «Мире понравилось…»
        m.hints.forEach { h ->
            IconLabel(AppIcons.Thought, h, style = MaterialTheme.typography.labelSmall, italic = true,
                color = MaterialTheme.colorScheme.tertiary, iconSize = 14.dp, maxLines = 3,
                modifier = Modifier.padding(start = 6.dp, top = 2.dp))
        }
        if (m.coins != 0) {
            IconLabel(AppIcons.Coins, (if (m.coins > 0) "+" else "") + m.coins,
                style = MaterialTheme.typography.labelSmall, iconSize = 14.dp,
                color = MaterialTheme.colorScheme.tertiary, modifier = Modifier.padding(start = 6.dp, top = 2.dp))
        }
        // варианты ответа / версии сообщения и скорость генерации
        if (m.variants > 1 || (!mine && m.tokensPerSec != null && !m.generating)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (m.variants > 1) {
                    val idx = m.variantIds.indexOf(m.id)
                    IconButton(
                        onClick = { onSelectVariant(m.variantIds[idx - 1]) },
                        enabled = actionsEnabled && idx > 0,
                        modifier = Modifier.size(32.dp),
                    ) { Icon(Icons.AutoMirrored.Filled.KeyboardArrowLeft, contentDescription = "Предыдущий") }
                    Text("${m.variant} / ${m.variants}", style = MaterialTheme.typography.labelSmall)
                    IconButton(
                        onClick = { onSelectVariant(m.variantIds[idx + 1]) },
                        enabled = actionsEnabled && idx >= 0 && idx < m.variantIds.lastIndex,
                        modifier = Modifier.size(32.dp),
                    ) { Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = "Следующий") }
                }
                if (!mine && m.tokensPerSec != null && !m.generating) {
                    Text(
                        String.format(java.util.Locale.US, "  %.1f ток/с", m.tokensPerSec),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@Composable
private fun MessageMenu(
    m: Msg,
    expanded: Boolean,
    isLast: Boolean,
    actionsEnabled: Boolean,
    onDismiss: () -> Unit,
    onCopy: () -> Unit,
    onEdit: (Msg, Boolean) -> Unit,
    onRegenerate: (Long) -> Unit,
    onContinue: (Long) -> Unit,
    onPin: (Long, Boolean) -> Unit,
    onDelete: (Long) -> Unit,
    onRedraw: (Msg) -> Unit,
    onRewrite: (Msg) -> Unit,
) {
    val mine = m.role == "user"
    DropdownMenu(expanded = expanded, onDismissRequest = onDismiss) {
        DropdownMenuItem(text = { Text("Копировать") }, onClick = { onDismiss(); onCopy() })
        if (actionsEnabled && !m.generating) {
            DropdownMenuItem(text = { Text("Изменить") }, onClick = { onDismiss(); onEdit(m, false) })
            if (mine) {
                DropdownMenuItem(text = { Text("Изменить и отправить заново") },
                    onClick = { onDismiss(); onEdit(m, true) })
            } else {
                DropdownMenuItem(text = { Text("Перегенерировать") }, onClick = { onDismiss(); onRegenerate(m.id) })
                if (m.kind != "image") {
                    DropdownMenuItem(text = { Text("Переписать с пожеланием…") }, onClick = { onDismiss(); onRewrite(m) })
                }
                if (m.drawnByModel) {
                    DropdownMenuItem(text = { Text("Перерисовать картинку") }, onClick = { onDismiss(); onRedraw(m) })
                }
                if (isLast && m.content.isNotBlank()) {
                    DropdownMenuItem(text = { Text("Продолжить") }, onClick = { onDismiss(); onContinue(m.id) })
                }
            }
            DropdownMenuItem(
                text = { Text(if (m.pinned) "Открепить" else "Закрепить (всегда в контексте)") },
                onClick = { onDismiss(); onPin(m.id, !m.pinned) },
            )
            DropdownMenuItem(text = { Text("Удалить (с продолжением)") }, onClick = { onDismiss(); onDelete(m.id) })
        }
    }
}

// =============================================================== этапы

/** Подписи этапов, пока на ПК идёт подготовка (до появления текста). */
private val STAGE_TEXT = mapOf(
    "loading_llm" to "Загружаю языковую модель…",
    "unloading_llm" to "Освобождаю видеопамять…",
    "loading_image_model" to "Загружаю модель изображений…",
    "drawing" to "Модель решила нарисовать…",
    "enhancing" to "Модель пишет промпт для рисунка…",
)

/** Этапы рисования, которое модель запускает сама после текста ответа. */
private val DRAW_STAGES = setOf("drawing", "unloading_llm", "loading_image_model", "image")

@Composable
private fun ImageProgress(m: Msg) {
    Column(Modifier.widthIn(min = 220.dp)) {
        val label = when {
            m.stage == "image" && m.progressTotal > 0 -> "Рисую… шаг ${m.progressDone} из ${m.progressTotal}"
            m.stage == "image" -> "Рисую…"
            else -> STAGE_TEXT[m.stage] ?: "Готовлюсь…"
        }
        Text(label, style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(6.dp))
        if (m.stage == "image" && m.progressTotal > 0) {
            LinearProgressIndicator(
                progress = { (m.progressDone.toFloat() / m.progressTotal).coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth(),
            )
        } else {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
    }
}

// =============================================================== картинки

@Composable
internal fun RemoteImage(name: String, load: suspend (String) -> Bitmap?, modifier: Modifier) {
    val bmp by produceState<Bitmap?>(null, name) { value = load(name) }
    Box(modifier.background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
        val b = bmp
        if (b != null) {
            Image(b.asImageBitmap(), contentDescription = null, contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize())
        } else {
            TypingDots()
        }
    }
}

@Composable
private fun ImagesRow(m: Msg, load: suspend (String) -> Bitmap?, onOpen: (String) -> Unit) {
    Row(
        Modifier
            .widthIn(max = 340.dp)
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        m.images.forEach { name ->
            RemoteImage(
                name = name,
                load = load,
                modifier = Modifier
                    .size(if (m.images.size == 1) 220.dp else 130.dp)
                    .clip(RoundedCornerShape(14.dp))
                    .clickable { onOpen(name) },
            )
        }
    }
}

/** Служебная команда («Продолжи», завязка сцены) — мелкой строкой, а не пузырём. */
@Composable
private fun DirectiveRow(m: Msg) {
    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
        IconLabel(
            AppIcons.Reply, m.content.trim(),
            style = MaterialTheme.typography.labelMedium,
            italic = true,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 4,
            modifier = Modifier.widthIn(max = 300.dp).padding(horizontal = 4.dp),
        )
    }
}

/** Откуда картинка: нарисована по просьбе человека или модель решила сама. */
@Composable
private fun ArtBadge(art: ImageInfo) {
    val text = if (art.source == "model") "нарисовала модель" + (if (art.caption.isNotBlank()) " · ${art.caption}" else "")
    else "по вашему запросу"
    IconLabel(
        if (art.source == "model") AppIcons.Magic else AppIcons.Brush,
        text,
        style = MaterialTheme.typography.labelSmall,
        italic = true, iconSize = 14.dp, maxLines = 2,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.widthIn(max = 340.dp).padding(top = 2.dp, start = 4.dp),
    )
}

@Composable
private fun ImageViewer(
    name: String,
    load: suspend (String) -> Bitmap?,
    msg: Msg?,
    actionsEnabled: Boolean,
    onRedraw: () -> Unit,
    onSimilar: () -> Unit,
    onSave: () -> Unit,
    onClose: () -> Unit,
) {
    val bmp by produceState<Bitmap?>(null, name) { value = load(name) }
    val art = msg?.art
    var info by remember { mutableStateOf(false) }
    // окно диалога на весь экран (иначе на части телефонов низ окна обрезается),
    // а кнопки — сверху, под строкой состояния: там их ничто не перекроет
    Dialog(
        onDismissRequest = onClose,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Box(
            Modifier
                .fillMaxSize()
                .background(Color.Black)
                .clickable { if (info) info = false else onClose() },
            contentAlignment = Alignment.Center,
        ) {
            val b = bmp
            if (b != null) {
                Image(b.asImageBitmap(), contentDescription = null, contentScale = ContentScale.Fit,
                    modifier = Modifier.fillMaxSize())
            } else {
                TypingDots(Color.White)
            }
            Column(
                Modifier
                    .align(Alignment.TopCenter)
                    .fillMaxWidth()
                    .background(Color.Black.copy(alpha = 0.72f))
                    .statusBarsPadding()
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                val border = BorderStroke(1.dp, Color.White.copy(alpha = 0.6f))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.horizontalScroll(rememberScrollState())) {
                    OutlinedButton(onClick = onClose, border = border) {
                        Icon(AppIcons.Close, contentDescription = "Закрыть", tint = Color.White)
                    }
                    if (art != null) {
                        OutlinedButton(onClick = { info = !info }, border = border) {
                            Text(if (info) "Скрыть" else "Что это", color = Color.White)
                        }
                        OutlinedButton(onClick = onRedraw, enabled = actionsEnabled, border = border) {
                            Text("Перерисовать", color = Color.White)
                        }
                        OutlinedButton(onClick = onSimilar, enabled = actionsEnabled, border = border) {
                            Text("Похожую", color = Color.White)
                        }
                    }
                    OutlinedButton(onClick = onSave, border = border) { Text("Сохранить", color = Color.White) }
                }
                if (info && art != null) {
                    Spacer(Modifier.height(8.dp))
                    ArtInfo(art)
                }
            }
        }
    }
}

@Composable
private fun ArtInfo(art: ImageInfo) {
    val dim = Color.White.copy(alpha = 0.7f)
    Column(
        Modifier
            .fillMaxWidth()
            .heightIn(max = 320.dp)
            .verticalScroll(rememberScrollState())
            .padding(bottom = 10.dp),
    ) {
        IconLabel(if (art.source == "model") AppIcons.Magic else AppIcons.Brush,
            if (art.source == "model") "Нарисовала модель сама" else "Нарисовано по вашему запросу",
            color = Color.White, style = MaterialTheme.typography.titleSmall, iconSize = 18.dp)
        if (art.caption.isNotBlank()) Text(art.caption, color = Color.White, style = MaterialTheme.typography.bodyMedium)
        if (art.request.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            Text("Запрос", color = dim, style = MaterialTheme.typography.labelSmall)
            Text(art.request, color = Color.White, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.height(6.dp))
        Text("Промпт (долгое нажатие — выделить)", color = dim, style = MaterialTheme.typography.labelSmall)
        SelectionContainer { Text(art.prompt, color = Color.White, style = MaterialTheme.typography.bodySmall) }
        if (art.refs.isNotEmpty()) {
            Text("По образцам: ${art.refs.joinToString(", ")}", color = dim, style = MaterialTheme.typography.bodySmall)
        }
        if (art.negative.isNotBlank()) {
            Text("Негатив: ${art.negative}", color = dim, style = MaterialTheme.typography.bodySmall)
        }
        if (art.seen.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            Text("Модель видит на картинке", color = dim, style = MaterialTheme.typography.labelSmall)
            Text(art.seen, color = Color.White, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.height(6.dp))
        val parts = listOfNotNull(
            art.profile.ifBlank { null },
            if (art.width > 0) "${art.width}×${art.height}" else null,
            if (art.steps > 0) "${art.steps} шагов" else null,
            art.seed?.let { "seed $it" },
        )
        SelectionContainer { Text(parts.joinToString(" · "), color = dim, style = MaterialTheme.typography.labelSmall) }
    }
}

// ================================================================== ввод

@Composable
fun InputBar(
    enabled: Boolean,
    vision: Boolean,
    images: Boolean,
    generating: Boolean,
    onSend: (String, List<ByteArray>, () -> Unit) -> Unit,
    onDraw: (String, (String) -> Unit) -> Unit,
    onStop: () -> Unit,
    onError: (String) -> Unit,
) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val keyboard = LocalSoftwareKeyboardController.current
    val focus = LocalFocusManager.current
    var text by rememberSaveable { mutableStateOf("") }
    val attachments = remember { mutableStateListOf<Attachment>() }
    var attachMenu by remember { mutableStateOf(false) }
    var cameraUri by remember { mutableStateOf<Uri?>(null) }

    fun addUris(uris: List<Uri>) {
        scope.launch {
            for (u in uris) {
                if (attachments.size >= MAX_ATTACHMENTS) break
                val a = withContext(Dispatchers.IO) { ImageUtil.prepare(ctx, u) }
                if (a != null) attachments.add(a) else onError("Не удалось открыть картинку")
            }
        }
    }

    val gallery = rememberLauncherForActivityResult(
        ActivityResultContracts.PickMultipleVisualMedia(MAX_ATTACHMENTS)
    ) { uris -> addUris(uris) }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        val u = cameraUri
        if (ok && u != null) addUris(listOf(u))
    }
    fun launchCamera() {
        val dir = File(ctx.cacheDir, "camera").apply { mkdirs() }
        val f = File(dir, "photo_${System.currentTimeMillis()}.jpg")
        val u = FileProvider.getUriForFile(ctx, ctx.packageName + ".files", f)
        cameraUri = u
        camera.launch(u)
    }
    val cameraPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) launchCamera() else onError("Нет доступа к камере")
    }

    Column(
        Modifier
            .fillMaxWidth()
            .navigationBarsPadding()
    ) {
        if (attachments.isNotEmpty()) {
            Row(
                Modifier
                    .horizontalScroll(rememberScrollState())
                    .padding(start = 12.dp, end = 12.dp, top = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                attachments.forEachIndexed { i, a ->
                    Box {
                        Image(
                            a.preview.asImageBitmap(), contentDescription = null,
                            contentScale = ContentScale.Crop,
                            modifier = Modifier.size(64.dp).clip(RoundedCornerShape(10.dp)),
                        )
                        Box(
                            Modifier
                                .align(Alignment.TopEnd)
                                .padding(2.dp)
                                .size(20.dp)
                                .background(Color.Black.copy(alpha = 0.6f), CircleShape)
                                .clickable { attachments.removeAt(i) },
                            contentAlignment = Alignment.Center,
                        ) {
                            Icon(Icons.Filled.Close, contentDescription = "Убрать", tint = Color.White,
                                modifier = Modifier.size(14.dp))
                        }
                    }
                }
            }
        }
        Row(
            Modifier
                .fillMaxWidth()
                .padding(8.dp),
            verticalAlignment = Alignment.Bottom,
        ) {
            Box {
                IconButton(
                    onClick = { attachMenu = true },
                    enabled = enabled && !generating,
                ) { Icon(Icons.Filled.Add, contentDescription = "Фото и рисование") }
                DropdownMenu(expanded = attachMenu, onDismissRequest = { attachMenu = false }) {
                    DropdownMenuItem(
                        text = { Text(if (images) "Нарисовать…" else "Нарисовать… (не настроено на ПК)") },
                        enabled = images,
                        onClick = {
                            attachMenu = false
                            // текст из поля — заготовка запроса; после отправки поле очищается
                            onDraw(text) { sent -> if (text == sent) text = "" }
                        },
                    )
                    if (!vision) {
                        DropdownMenuItem(text = { Text("Фото (модель на ПК без mmproj)") },
                            enabled = false, onClick = {})
                    }
                    if (vision && attachments.size < MAX_ATTACHMENTS) DropdownMenuItem(text = { Text("Фото из галереи") }, onClick = {
                        attachMenu = false
                        gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                    })
                    if (vision && attachments.size < MAX_ATTACHMENTS) DropdownMenuItem(text = { Text("Снять камерой") }, onClick = {
                        attachMenu = false
                        if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.CAMERA) ==
                            PackageManager.PERMISSION_GRANTED) launchCamera()
                        else cameraPermission.launch(Manifest.permission.CAMERA)
                    })
                }
            }
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                modifier = Modifier.weight(1f),
                placeholder = {
                    Text(when {
                        !enabled -> "Нет связи с моделью"
                        attachments.isNotEmpty() -> "Вопрос о фото"
                        else -> "Сообщение"
                    })
                },
                shape = RoundedCornerShape(24.dp),
                maxLines = 6,
            )
            Spacer(Modifier.width(8.dp))
            if (generating) {
                FilledIconButton(onClick = onStop) {
                    Icon(Icons.Filled.Close, contentDescription = "Остановить")
                }
            } else {
                FilledIconButton(
                    onClick = {
                        val t = text
                        val imgs = attachments.toList()
                        text = ""
                        attachments.clear()
                        keyboard?.hide()
                        focus.clearFocus()
                        onSend(t, imgs.map { it.jpeg }) {
                            // не ушло — вернуть набранное
                            if (text.isEmpty()) text = t
                            if (attachments.isEmpty()) attachments.addAll(imgs)
                        }
                    },
                    enabled = enabled && (text.isNotBlank() || attachments.isNotEmpty()),
                ) {
                    Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Отправить")
                }
            }
        }
    }
}
