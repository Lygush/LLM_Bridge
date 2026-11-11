package dev.llmbridge.client.ui

import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.material3.Icon
import androidx.compose.foundation.layout.size
import android.graphics.Bitmap
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dev.llmbridge.client.Card
import dev.llmbridge.client.Msg
import dev.llmbridge.client.QuestState

private val MODES = listOf(
    Triple("chat", "Чат", "разговор с одним или несколькими персонажами"),
    Triple("quest", "Квест", "модель — ведущий игры; состояние и варианты действий"),
    Triple("story", "История", "пишете историю вместе: «продолжи», «поворот», «перепиши»"),
    Triple("gm", "Я ведущий", "вы — мастер игры, модель играет героев; есть помощник ведущего"),
)

/** Новая сцена: режим, персонажи, персона, мир и завязка своими словами. */
@Composable
fun SceneDialog(
    cards: List<Card>,
    initialMode: String = "chat",
    initialWorld: Long? = null,
    initialChars: List<Long> = emptyList(),
    onCreate: (mode: String, chars: List<Long>, persona: Long?, world: Long?, setup: String, style: String,
               done: (Boolean) -> Unit) -> Unit,
    onDismiss: () -> Unit,
) {
    var mode by rememberSaveable { mutableStateOf(initialMode) }
    val chars = remember { mutableStateListOf<Long>().apply { addAll(initialChars) } }
    var persona by rememberSaveable { mutableStateOf<Long?>(null) }
    var world by rememberSaveable { mutableStateOf(initialWorld) }
    var setup by rememberSaveable { mutableStateOf("") }
    var style by rememberSaveable { mutableStateOf("messenger") }
    var busy by remember { mutableStateOf(false) }
    val characters = cards.filter { it.kind == "character" }
    val personas = cards.filter { it.kind == "persona" }
    val worlds = cards.filter { it.kind == "world" }
    val canCreate = !busy && (mode != "chat" || chars.isNotEmpty())

    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text("Новая сцена") },
        text = {
            Column(Modifier.heightIn(max = 560.dp).verticalScroll(rememberScrollState())) {
                ChipRow {
                    MODES.forEach { (id, name, _) ->
                        FilterChip(selected = mode == id, onClick = { mode = id }, label = { Text(name) })
                    }
                }
                Text(MODES.first { it.first == mode }.third, style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (mode == "chat") {
                    Section("Как общаетесь")
                    ChipRow {
                        FilterChip(selected = style == "messenger", onClick = { style = "messenger" },
                            label = { Text("Переписка") })
                        FilterChip(selected = style == "roleplay", onClick = { style = "roleplay" },
                            label = { Text("Рядом, с действиями") })
                    }
                }
                Section(when (mode) {
                    "chat" -> "Персонажи (можно несколько)"
                    "gm" -> "Герои, за которых играет модель"
                    else -> "Персонажи (необязательно)"
                })
                if (characters.isEmpty()) Hint("Создайте персонажей в «Персонажи и персоны».")
                ChipRow {
                    characters.forEach { c ->
                        FilterChip(selected = c.id in chars,
                            onClick = { if (c.id in chars) chars.remove(c.id) else chars.add(c.id) },
                            label = { Text(c.name.ifBlank { "?" }) })
                    }
                }
                if (personas.isNotEmpty()) {
                    Section(if (mode == "quest") "Кем играете" else "Вы — персона")
                    ChipRow {
                        FilterChip(selected = persona == null, onClick = { persona = null }, label = { Text("без") })
                        personas.forEach { p ->
                            FilterChip(selected = persona == p.id, onClick = { persona = p.id },
                                label = { Text(p.name.ifBlank { "?" }) })
                        }
                    }
                }
                Section("Мир")
                ChipRow {
                    FilterChip(selected = world == null, onClick = { world = null }, label = { Text("без") })
                    worlds.forEach { w ->
                        FilterChip(selected = world == w.id, onClick = { world = w.id },
                            label = { Text(w.name.ifBlank { "?" }) })
                    }
                }
                Section(if (mode == "chat") "Завязка (необязательно)" else "Завязка")
                OutlinedTextField(
                    value = setup,
                    onValueChange = { setup = it },
                    enabled = !busy,
                    minLines = 3,
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = {
                        Text(when (mode) {
                            "quest" -> "Кто вы и чего хотите, можно коротко: «я наёмник, ищу пропавший караван»"
                            "story" -> "О чём история, с чего начать, в каком стиле"
                            else -> "Ситуация, с которой начать; пусто — персонаж поздоровается сам"
                        })
                    },
                )
                if (busy) {
                    Spacer(Modifier.height(8.dp))
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    busy = true
                    onCreate(mode, chars.toList(), persona, world, setup.trim(), style) { ok -> busy = false; if (ok) onDismiss() }
                },
                enabled = canCreate,
            ) { Text("Начать") }
        },
        dismissButton = { TextButton(onClick = onDismiss, enabled = !busy) { Text("Отмена") } },
    )
}

@Composable
private fun ChipRow(content: @Composable () -> Unit) {
    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        content()
    }
}

@Composable
private fun Section(text: String) {
    Spacer(Modifier.height(10.dp))
    Text(text, style = MaterialTheme.typography.titleSmall)
}

@Composable
private fun Hint(text: String) {
    Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

// ================================================================ квест

/** Панель состояния квеста над чатом: кратко в одну строку, по нажатию — подробно. */
@Composable
fun QuestPanel(state: QuestState, coins: Int?, onEdit: () -> Unit) {
    var open by rememberSaveable { mutableStateOf(false) }
    Surface(
        color = MaterialTheme.colorScheme.secondaryContainer,
        modifier = Modifier.fillMaxWidth().clickable { open = !open },
    ) {
        Column(Modifier.padding(horizontal = 14.dp, vertical = 8.dp)) {
            val tint = MaterialTheme.colorScheme.onSecondaryContainer
            Row(verticalAlignment = Alignment.CenterVertically) {
                Row(Modifier.weight(1f).horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(14.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    val style = MaterialTheme.typography.labelLarge
                    if (state.location.isNotBlank()) IconLabel(AppIcons.Place, state.location, style = style, color = tint)
                    if (state.time.isNotBlank()) IconLabel(AppIcons.Time, state.time, style = style, color = tint)
                    if (state.health.isNotBlank()) IconLabel(AppIcons.Health, state.health, style = style, color = tint)
                    if (coins != null) IconLabel(AppIcons.Coins, coins.toString(), style = style, color = tint)
                    if (state.location.isBlank() && state.time.isBlank() && state.health.isBlank())
                        Text("Состояние игры", style = style)
                }
                Icon(if (open) AppIcons.Less else AppIcons.More, contentDescription = null, tint = tint)
            }
            AnimatedVisibility(open) {
                Column(Modifier.padding(top = 6.dp)) {
                    StateList(AppIcons.Inventory, "Инвентарь", state.inventory)
                    StateList(AppIcons.Goals, "Цели", state.goals)
                    StateList(AppIcons.People, "Отношения", state.relations)
                    if (state.notes.isNotBlank()) {
                        IconLabel(AppIcons.Notes, "Заметки", style = MaterialTheme.typography.labelMedium)
                        Text(state.notes, style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.padding(start = 8.dp, bottom = 4.dp))
                    }
                    TextButton(onClick = onEdit) { Text("Изменить") }
                }
            }
        }
    }
}

@Composable
private fun StateList(icon: ImageVector, title: String, items: List<String>) {
    if (items.isEmpty()) return
    IconLabel(icon, title, style = MaterialTheme.typography.labelMedium)
    Text(items.joinToString("\n") { "• $it" }, style = MaterialTheme.typography.bodySmall,
        modifier = Modifier.padding(start = 8.dp, bottom = 4.dp))
}

/** Правка состояния вручную: списки — по одному пункту в строке. */
@Composable
fun StateDialog(initial: QuestState, onSave: (QuestState) -> Unit, onDismiss: () -> Unit) {
    var location by rememberSaveable { mutableStateOf(initial.location) }
    var time by rememberSaveable { mutableStateOf(initial.time) }
    var health by rememberSaveable { mutableStateOf(initial.health) }
    var inventory by rememberSaveable { mutableStateOf(initial.inventory.joinToString("\n")) }
    var goals by rememberSaveable { mutableStateOf(initial.goals.joinToString("\n")) }
    var relations by rememberSaveable { mutableStateOf(initial.relations.joinToString("\n")) }
    var notes by rememberSaveable { mutableStateOf(initial.notes) }
    fun lines(s: String) = s.lines().map { it.trim() }.filter { it.isNotEmpty() }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Состояние игры") },
        text = {
            Column(Modifier.heightIn(max = 520.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(location, { location = it }, label = { Text("Где") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(time, { time = it }, label = { Text("Время") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(health, { health = it }, label = { Text("Состояние") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(inventory, { inventory = it }, label = { Text("Инвентарь (по строке)") },
                    minLines = 2, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(goals, { goals = it }, label = { Text("Цели (по строке)") },
                    minLines = 2, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(relations, { relations = it }, label = { Text("Отношения (по строке)") },
                    minLines = 2, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(notes, { notes = it }, label = { Text("Заметки") }, minLines = 2,
                    modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = {
            TextButton(onClick = {
                onSave(QuestState(location.trim(), time.trim(), health.trim(), lines(inventory), lines(goals),
                    lines(relations), notes.trim()))
            }) { Text("Сохранить") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Отмена") } },
    )
}

/** Кнопка-действие над полем ввода: подпись, значок и что сделать. */
class ChipAction(val label: String, val icon: ImageVector? = null, val onClick: () -> Unit)

/** Кнопки над полем ввода: варианты действий (квест), команды истории, кто отвечает. */
@Composable
fun ActionChips(items: List<ChipAction>, enabled: Boolean) {
    if (items.isEmpty()) return
    Row(
        Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .padding(horizontal = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        items.forEach { a ->
            AssistChip(onClick = a.onClick, enabled = enabled,
                leadingIcon = a.icon?.let { ic -> { Icon(ic, contentDescription = null, modifier = Modifier.size(18.dp)) } },
                label = { Text(a.label, maxLines = 2, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.widthIn(max = 260.dp)) })
        }
    }
}

/** Выбор, кто из персонажей ответит на следующее сообщение. */
@Composable
fun CastBar(cast: List<Card>, selected: Long?, load: suspend (String) -> Bitmap?, onSelect: (Long?) -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .padding(horizontal = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("Ответит:", style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        FilterChip(selected = selected == null, onClick = { onSelect(null) }, label = { Text("все") })
        cast.forEach { c ->
            FilterChip(
                selected = selected == c.id,
                onClick = { onSelect(if (selected == c.id) null else c.id) },
                leadingIcon = { Avatar(c, load, 20) },
                label = { Text(c.name.ifBlank { "?" }) },
            )
        }
    }
}

/** Над ответом модели — кто говорит (аватары и имена персонажей). */
@Composable
fun SpeakerHeader(m: Msg, cast: List<Card>, load: suspend (String) -> Bitmap?) {
    if (m.role != "assistant" || m.speakers.isEmpty()) return
    val who = m.speakers.mapNotNull { id -> cast.firstOrNull { it.id == id } }
    if (who.isEmpty()) return
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 2.dp)) {
        who.forEach { c ->
            Avatar(c, load, 24)
            Spacer(Modifier.width(4.dp))
            Text(c.name, style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.width(10.dp))
        }
    }
}

/** Настройки общения с персонажем — всё в одном понятном месте. */
@Composable
fun ChatOptionsDialog(
    messenger: Boolean,
    initiative: Boolean,
    showRelations: Boolean,
    relations: List<dev.llmbridge.client.Relation>,
    onStyle: (messenger: Boolean) -> Unit,
    onInitiative: (Boolean) -> Unit,
    onShowRelations: (Boolean) -> Unit,
    onReset: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Настройки общения") },
        text = {
            Column(Modifier.heightIn(max = 520.dp).verticalScroll(rememberScrollState())) {
                Text("Как общаетесь", style = MaterialTheme.typography.titleSmall)
                StyleRow(AppIcons.Messenger, "Переписка", "как в мессенджере: короткие сообщения, без описаний действий",
                    messenger) { onStyle(true) }
                StyleRow(AppIcons.Roleplay, "Рядом", "вы вместе: речь и действия персонажа, как в ролевой игре",
                    !messenger) { onStyle(false) }
                Spacer(Modifier.height(10.dp))
                SwitchRow("Может написать первым", "когда вы заходите после паузы", initiative, onInitiative)
                SwitchRow("Показывать отношения", "числа под заголовком; иначе — только подсказки под ответами",
                    showRelations, onShowRelations)
                if (relations.isNotEmpty()) {
                    Spacer(Modifier.height(10.dp))
                    Text("Отношения", style = MaterialTheme.typography.titleSmall)
                    relations.forEach { r ->
                        Text("${r.name}: ${r.status} · симпатия ${r.sympathy} · доверие ${r.trust}" +
                            (if (r.mood.isNotBlank()) " · ${r.mood}" else "") +
                            (if (r.debt > 0) " · ваш долг ${r.debt} монет" else ""),
                            style = MaterialTheme.typography.bodySmall)
                        r.promises.forEach { p ->
                            Text("   обещали: $p", style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    TextButton(onClick = onReset) {
                        Text("Сбросить отношения", color = MaterialTheme.colorScheme.error)
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Готово") } },
    )
}

@Composable
private fun StyleRow(icon: ImageVector, title: String, hint: String, selected: Boolean, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically) {
        androidx.compose.material3.RadioButton(selected = selected, onClick = onClick)
        Column(Modifier.weight(1f)) {
            IconLabel(icon, title, style = MaterialTheme.typography.bodyLarge, iconSize = 20.dp)
            Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun SwitchRow(title: String, hint: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        androidx.compose.material3.Switch(checked = checked, onCheckedChange = onChange)
    }
}
