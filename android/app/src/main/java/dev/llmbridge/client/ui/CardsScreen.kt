package dev.llmbridge.client.ui

import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.layout.width
import android.graphics.Bitmap
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.llmbridge.client.Card
import dev.llmbridge.client.CardField
import dev.llmbridge.client.CardStage
import dev.llmbridge.client.ChatViewModel
import dev.llmbridge.client.LoreEntry

private val KIND_TABS = listOf("character" to "Персонажи", "persona" to "Я", "world" to "Миры")

/**
 * Персонажи и персоны. Карточку можно не заполнять руками: описать своими словами,
 * и модель на ПК разложит описание по полям; любое поле можно переписать моделью.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CardsScreen(vm: ChatViewModel, online: Boolean, onClose: () -> Unit, onNewScene: (worldId: Long?) -> Unit) {
    val cards by vm.cards.collectAsStateWithLifecycle()
    val fields by vm.cardFields.collectAsStateWithLifecycle()
    val stages by vm.cardStages.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableStateOf(0) }
    var editId by rememberSaveable { mutableStateOf<Long?>(null) }
    var create by remember { mutableStateOf(false) }
    LaunchedEffect(online) { if (online) vm.loadCards() }

    Dialog(
        onDismissRequest = { if (editId != null) editId = null else onClose() },
        // окно на весь экран, отступы под системные панели расставляет Scaffold
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Surface(Modifier.fillMaxSize()) {
            val editing = cards.firstOrNull { it.id == editId }
            if (editing != null) {
                CardEditor(
                    vm = vm,
                    card = editing,
                    fields = fields[editing.kind].orEmpty(),
                    stage = stages[editing.id],
                    personas = cards.filter { it.kind == "persona" },
                    online = online,
                    onBack = { editId = null },
                    onChatStarted = { editId = null; onClose() },
                    onNewScene = { editId = null; onNewScene(it) },
                )
                return@Surface
            }
            val kind = KIND_TABS[tab].first
            Scaffold(
                topBar = {
                    TopAppBar(
                        navigationIcon = {
                            IconButton(onClick = onClose) {
                                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад")
                            }
                        },
                        title = { Text("Карточки") },
                        actions = {
                            IconButton(onClick = { create = true }, enabled = online) {
                                Icon(Icons.Filled.Add, contentDescription = "Создать")
                            }
                        },
                    )
                },
            ) { pad ->
                Column(Modifier.padding(pad).fillMaxSize()) {
                    TabRow(selectedTabIndex = tab) {
                        KIND_TABS.forEachIndexed { i, (_, name) ->
                            Tab(selected = tab == i, onClick = { tab = i }, text = { Text(name) })
                        }
                    }
                    val list = cards.filter { it.kind == kind }
                    if (list.isEmpty()) {
                        Text(
                            if (!online) "Нет связи с ПК" else when (kind) {
                                "character" -> "Персонажей пока нет. Нажмите «+» и опишите персонажа своими " +
                                    "словами — модель заполнит карточку сама."
                                "persona" -> "Персона — это вы в ролевых чатах: имя, внешность, кто вы. " +
                                    "Нажмите «+», чтобы создать."
                                else -> "Мир — место действия для квестов и историй: описание, тон и лорбук " +
                                    "(места, фракции, обычаи). Нажмите «+» и опишите мир как угодно."
                            },
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(24.dp),
                        )
                    }
                    // сетка сама решает, сколько колонок: одна на телефоне, две-три на широком экране
                    LazyVerticalGrid(columns = GridCells.Adaptive(300.dp), modifier = Modifier.weight(1f),
                        contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 12.dp, bottom = 24.dp),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        items(list, key = { it.id }) { c ->
                            CardRow(c, stages[c.id], { vm.image(it) }) { editId = c.id }
                        }
                    }
                }
            }
            if (create) {
                CreateCardDialog(
                    kind = kind,
                    onCreate = { text, done ->
                        vm.createCard(kind, text) { card ->
                            done()
                            if (card != null) {
                                create = false
                                editId = card.id
                            }
                        }
                    },
                    onDismiss = { create = false },
                )
            }
        }
    }
}

@Composable
private fun CardRow(c: Card, stage: CardStage?, load: suspend (String) -> Bitmap?, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(MaterialTheme.shapes.medium)
            .background(MaterialTheme.colorScheme.surfaceContainer)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Avatar(c, load, 64)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(c.name.ifBlank { "Без имени" }, style = MaterialTheme.typography.titleMedium,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            val sub = if (stage != null) "рисую портрет…" else c.short
            if (sub.isNotBlank()) {
                Text(sub, style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2,
                    overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@Composable
internal fun Avatar(c: Card, load: suspend (String) -> Bitmap?, sizeDp: Int) {
    val p = c.portrait
    if (p != null) {
        RemoteImage(p, load, Modifier.size(sizeDp.dp).clip(CircleShape))
    } else {
        Box(
            Modifier.size(sizeDp.dp).clip(CircleShape).background(MaterialTheme.colorScheme.secondaryContainer),
            contentAlignment = Alignment.Center,
        ) {
            Text(c.name.take(1).ifBlank { "?" }.uppercase(), style = MaterialTheme.typography.titleLarge,
                color = MaterialTheme.colorScheme.onSecondaryContainer)
        }
    }
}

@Composable
private fun CreateCardDialog(kind: String, onCreate: (String, () -> Unit) -> Unit, onDismiss: () -> Unit) {
    var text by rememberSaveable { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text(when (kind) { "character" -> "Новый персонаж"; "persona" -> "Новая персона"; else -> "Новый мир" }) },
        text = {
            Column {
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    enabled = !busy,
                    minLines = 5,
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = {
                        Text(when (kind) {
                            "character" -> "Как угодно: «Лиса-оборотень, хитрая, работает барменом в портовом " +
                                "городе, рыжие волосы, шрам на щеке…»"
                            "persona" -> "«Меня зовут Иван, инженер, высокий, тёмные волосы…»"
                            else -> "«Портовый город в мире низкой магии, контрабандисты, гильдии, туманы…»"
                        })
                    },
                )
                Spacer(Modifier.height(8.dp))
                if (busy) {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                    Spacer(Modifier.height(4.dp))
                    Text("Модель заполняет карточку — это может занять минуту…",
                        style = MaterialTheme.typography.bodySmall)
                } else {
                    Text("Модель разложит описание по полям и додумает остальное. Потом всё можно поправить.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { busy = true; onCreate(text.trim()) { busy = false } },
                enabled = text.isNotBlank() && !busy) { Text("Заполнить моделью") }
        },
        dismissButton = {
            TextButton(onClick = { busy = true; onCreate("") { busy = false } }, enabled = !busy) {
                Text("Пустая")
            }
        },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CardEditor(
    vm: ChatViewModel,
    card: Card,
    fields: List<CardField>,
    stage: CardStage?,
    personas: List<Card>,
    online: Boolean,
    onBack: () -> Unit,
    onChatStarted: () -> Unit,
    onNewScene: (Long?) -> Unit,
) {
    val values = remember(card.id) { mutableStateMapOf<String, String>().apply { putAll(card.data) } }
    val rewriting = remember(card.id) { mutableStateMapOf<String, Boolean>() }
    var wishFor by remember { mutableStateOf<CardField?>(null) }
    var confirmDelete by remember { mutableStateOf(false) }
    var pickPersona by remember { mutableStateOf(false) }
    val changed = fields.any { (values[it.key] ?: "") != (card.data[it.key] ?: "") }
    val current = { fields.associate { it.key to (values[it.key] ?: "") } }

    fun startChat(personaId: Long?) {
        val go = { vm.startCharacterChat(card.id, personaId) { ok -> if (ok) onChatStarted() } }
        if (changed) vm.saveCard(card.id, current()) { if (it != null) go() } else go()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                navigationIcon = {
                    IconButton(onClick = { if (changed) vm.saveCard(card.id, current()); onBack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад")
                    }
                },
                title = { Text(values["name"].orEmpty().ifBlank { "Карточка" }, maxLines = 1) },
                actions = {
                    TextButton(onClick = { vm.saveCard(card.id, current()) }, enabled = changed && online) {
                        Text("Сохранить")
                    }
                    IconButton(onClick = { confirmDelete = true }, enabled = online) {
                        Icon(Icons.Filled.Delete, contentDescription = "Удалить карточку")
                    }
                },
            )
        },
    ) { pad ->
        Column(
            Modifier
                .padding(pad)
                .fillMaxSize()
                .imePadding()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = sidePadding(), vertical = 16.dp),
        ) {
            // портрет (у мира его нет — у мира стиль картинок)
            if (card.kind != "world") Row(verticalAlignment = Alignment.CenterVertically) {
                val p = card.portrait
                if (p != null) {
                    RemoteImage(p, { vm.image(it) },
                        Modifier.size(width = 120.dp, height = 176.dp).clip(RoundedCornerShape(14.dp)))
                } else {
                    Avatar(card, { vm.image(it) }, 96)
                }
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    if (stage != null) {
                        Text(portraitStageText(stage), style = MaterialTheme.typography.bodySmall)
                        Spacer(Modifier.height(6.dp))
                        if (stage.total > 0) {
                            LinearProgressIndicator(
                                progress = { stage.done.toFloat() / stage.total },
                                modifier = Modifier.fillMaxWidth(),
                            )
                        } else {
                            LinearProgressIndicator(Modifier.fillMaxWidth())
                        }
                    } else {
                        OutlinedButton(
                            onClick = {
                                if (changed) vm.saveCard(card.id, current()) { if (it != null) vm.drawPortrait(card.id) }
                                else vm.drawPortrait(card.id)
                            },
                            enabled = online,
                        ) { Text(if (card.portrait == null) "Нарисовать портрет" else "Перерисовать портрет") }
                        if (card.kind == "character" && card.portrait != null) {
                            OutlinedButton(onClick = { vm.drawSprites(card.id) }, enabled = online) {
                                Text(if (card.sprites.isEmpty()) "Эмоции для новеллы" else "Эмоции: ${card.sprites.size}/6 — заново")
                            }
                        }
                        Text("По тегам внешности. Портрет увидит и модель в чате.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            Spacer(Modifier.height(16.dp))
            if (card.kind == "world") {
                Button(onClick = {
                    if (changed) vm.saveCard(card.id, current()) { if (it != null) onNewScene(card.id) }
                    else onNewScene(card.id)
                }, enabled = online, modifier = Modifier.fillMaxWidth()) { Text("Начать квест или историю") }
                Spacer(Modifier.height(12.dp))
            }
            if (card.kind == "character") {
                Button(
                    onClick = { if (personas.isEmpty()) startChat(null) else pickPersona = true },
                    enabled = online,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Начать чат") }
                Spacer(Modifier.height(12.dp))
            }

            fields.forEach { f ->
                val busy = rewriting[f.key] == true
                OutlinedTextField(
                    value = values[f.key] ?: "",
                    onValueChange = { values[f.key] = it },
                    label = { Text(f.label) },
                    enabled = !busy,
                    singleLine = !f.multiline,
                    minLines = if (f.multiline) 2 else 1,
                    modifier = Modifier.fillMaxWidth(),
                    trailingIcon = {
                        if (busy) {
                            CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                        } else {
                            IconButton(onClick = { wishFor = f }, enabled = online) {
                                Icon(AppIcons.Magic, contentDescription = "Переписать моделью",
                                    tint = MaterialTheme.colorScheme.primary)
                            }
                        }
                    },
                )
                Spacer(Modifier.height(8.dp))
            }
            if (card.kind == "world") LoreSection(vm, card.id, online)
            Spacer(Modifier.height(24.dp))
        }
    }

    wishFor?.let { f ->
        TextDialog(
            title = "Переписать: ${f.label}",
            initial = "",
            label = "Пожелание (можно пусто): «короче», «добавь шрам», «сделай мрачнее»…",
            confirm = "Переписать",
            allowEmpty = true,
            onConfirm = { wish ->
                wishFor = null
                rewriting[f.key] = true
                vm.rewriteField(card.id, f.key, wish, current()) { value ->
                    rewriting.remove(f.key)
                    if (value != null) values[f.key] = value
                }
            },
            onDismiss = { wishFor = null },
        )
    }
    if (pickPersona) {
        AlertDialog(
            onDismissRequest = { pickPersona = false },
            title = { Text("От чьего лица?") },
            text = {
                Column {
                    (listOf<Card?>(null) + personas).forEach { p ->
                        Text(
                            p?.name?.ifBlank { "Без имени" } ?: "Без персоны",
                            style = MaterialTheme.typography.bodyLarge,
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { pickPersona = false; startChat(p?.id) }
                                .padding(vertical = 12.dp),
                        )
                    }
                }
            },
            confirmButton = {},
            dismissButton = { TextButton(onClick = { pickPersona = false }) { Text("Отмена") } },
        )
    }
    if (confirmDelete) {
        ConfirmDialog(
            title = "Удалить карточку?",
            text = "Чаты останутся, но без этого описания.",
            confirm = "Удалить",
            onConfirm = { confirmDelete = false; vm.deleteCard(card.id); onBack() },
            onDismiss = { confirmDelete = false },
        )
    }
}

private fun portraitStageText(s: CardStage) = when (s.stage) {
    "sprites" -> "Рисую эмоции: ${s.done + 1} из ${s.total}"
    "queued", "starting" -> "Портрет в очереди…"
    "unloading_llm" -> "Выгружаю текстовую модель…"
    "loading_image_model" -> "Загружаю модель изображений…"
    "image" -> if (s.total > 0) "Рисую портрет: шаг ${s.done} из ${s.total}" else "Рисую портрет…"
    else -> "Рисую портрет…"
}

// ================================================================ лорбук

@Composable
private fun LoreSection(vm: ChatViewModel, worldId: Long, online: Boolean) {
    val lore by vm.lore.collectAsStateWithLifecycle()
    LaunchedEffect(worldId) { vm.loadLore(worldId) }
    val entries = lore?.takeIf { it.first == worldId }?.second.orEmpty()
    var edit by remember { mutableStateOf<LoreEntry?>(null) }
    var ask by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }

    HorizontalDivider(Modifier.padding(vertical = 8.dp))
    Text("Лорбук", style = MaterialTheme.typography.titleMedium)
    Text("Места, фракции, обычаи. Запись попадает в разговор, когда в нём встречаются её ключи " +
        "(основы слов: «гильди, вор»), или всегда, если она закреплена.",
        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    Spacer(Modifier.height(6.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = { edit = LoreEntry(0, "", "", "", false) }, enabled = online) { Text("+ Запись") }
        OutlinedButton(onClick = { ask = true }, enabled = online && !busy) {
            Icon(AppIcons.Magic, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Text("Дополнить моделью")
        }
    }
    if (busy) {
        Spacer(Modifier.height(6.dp))
        LinearProgressIndicator(Modifier.fillMaxWidth())
    }
    entries.forEach { e ->
        Column(
            Modifier
                .fillMaxWidth()
                .clickable { edit = e }
                .padding(vertical = 8.dp),
        ) {
            if (e.always) IconLabel(AppIcons.Pin, e.title.ifBlank { "Без названия" },
                style = MaterialTheme.typography.titleSmall)
            else Text(e.title.ifBlank { "Без названия" }, style = MaterialTheme.typography.titleSmall)
            if (e.keys.isNotBlank()) {
                Text("ключи: ${e.keys}", style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text(e.content, style = MaterialTheme.typography.bodySmall, maxLines = 3, overflow = TextOverflow.Ellipsis)
        }
        HorizontalDivider()
    }

    edit?.let { e ->
        LoreDialog(
            entry = e,
            onSave = { vm.saveLore(worldId, it); edit = null },
            onDelete = if (e.id != 0L) ({ vm.deleteLore(worldId, e.id); edit = null }) else null,
            onDismiss = { edit = null },
        )
    }
    if (ask) {
        TextDialog(
            title = "Дополнить лорбук",
            initial = "",
            label = "Что добавить: «гильдия воров и её глава», «три таверны в порту», «местная религия»…",
            confirm = "Добавить",
            onConfirm = { text ->
                ask = false
                busy = true
                vm.generateLore(worldId, text) { busy = false }
            },
            onDismiss = { ask = false },
        )
    }
}

@Composable
private fun LoreDialog(entry: LoreEntry, onSave: (LoreEntry) -> Unit, onDelete: (() -> Unit)?, onDismiss: () -> Unit) {
    var title by rememberSaveable { mutableStateOf(entry.title) }
    var keys by rememberSaveable { mutableStateOf(entry.keys) }
    var content by rememberSaveable { mutableStateOf(entry.content) }
    var always by rememberSaveable { mutableStateOf(entry.always) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (entry.id == 0L) "Новая запись" else "Запись лорбука") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                OutlinedTextField(title, { title = it }, label = { Text("Название") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth())
                OutlinedTextField(keys, { keys = it }, label = { Text("Ключи через запятую") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth())
                OutlinedTextField(content, { content = it }, label = { Text("Текст") }, minLines = 4,
                    modifier = Modifier.fillMaxWidth())
                Row(verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.clickable { always = !always }) {
                    Checkbox(checked = always, onCheckedChange = { always = it })
                    Text("Всегда в контексте")
                }
                if (onDelete != null) {
                    TextButton(onClick = onDelete) { Text("Удалить запись", color = MaterialTheme.colorScheme.error) }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(entry.copy(title = title.trim(), keys = keys.trim(),
                content = content.trim(), always = always)) }, enabled = content.isNotBlank()) { Text("Сохранить") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Отмена") } },
    )
}
