package dev.llmbridge.client.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.Star
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import dev.llmbridge.client.ContextStats
import dev.llmbridge.client.Fact
import dev.llmbridge.client.MemoryInfo

/** Панель памяти чата: факты, хроника, раскладка контекста. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MemorySheet(
    memory: MemoryInfo?,
    lastCtx: ContextStats?,
    initialTab: Int,
    onDismiss: () -> Unit,
    onAddFact: (String) -> Unit,
    onEditFact: (Long, String) -> Unit,
    onPinFact: (Long, Boolean) -> Unit,
    onDeleteFact: (Long) -> Unit,
    onSaveChronicle: (String) -> Unit,
    onRefresh: () -> Unit,
) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var tab by rememberSaveable { mutableIntStateOf(initialTab) }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet) {
        Column(
            Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .heightIn(min = 360.dp)
        ) {
            TabRow(selectedTabIndex = tab) {
                listOf("Факты", "Хроника", "Контекст").forEachIndexed { i, t ->
                    Tab(selected = tab == i, onClick = { tab = i }, text = { Text(t) })
                }
            }
            if (memory == null) {
                Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
                return@Column
            }
            when (tab) {
                0 -> FactsTab(memory.facts, onAddFact, onEditFact, onPinFact, onDeleteFact, onRefresh)
                1 -> ChronicleTab(memory.chronicle, onSaveChronicle)
                else -> ContextTab(memory.ctx ?: lastCtx)
            }
        }
    }
}

@Composable
private fun FactsTab(
    facts: List<Fact>,
    onAdd: (String) -> Unit,
    onEdit: (Long, String) -> Unit,
    onPin: (Long, Boolean) -> Unit,
    onDelete: (Long) -> Unit,
    onRefresh: () -> Unit,
) {
    var newText by rememberSaveable { mutableStateOf("") }
    var editing by remember { mutableStateOf<Fact?>(null) }
    Column(Modifier.padding(16.dp)) {
        Text(
            "Важное, что модель помнит всегда. Пополняется само по ходу диалога; " +
                "звезда — закрепить (модель не изменит), нажатие — изменить.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
        if (facts.isEmpty()) {
            Text("Пока пусто", modifier = Modifier.padding(vertical = 16.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        LazyColumn(Modifier.heightIn(max = 380.dp)) {
            items(facts, key = { it.id }) { f ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(
                        Modifier
                            .weight(1f)
                            .clickable { editing = f }
                            .padding(vertical = 6.dp)
                    ) {
                        Text(f.text, style = MaterialTheme.typography.bodyMedium)
                        Text(if (f.auto) "авто" else "вручную", style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    IconButton(onClick = { onPin(f.id, !f.pinned) }) {
                        Icon(
                            if (f.pinned) Icons.Filled.Star else Icons.Outlined.Star,
                            contentDescription = if (f.pinned) "Открепить" else "Закрепить",
                            tint = if (f.pinned) MaterialTheme.colorScheme.primary
                            else MaterialTheme.colorScheme.outline,
                        )
                    }
                    IconButton(onClick = { onDelete(f.id) }) {
                        Icon(Icons.Filled.Delete, contentDescription = "Удалить",
                            tint = MaterialTheme.colorScheme.outline)
                    }
                }
                HorizontalDivider()
            }
        }
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = newText,
                onValueChange = { newText = it },
                modifier = Modifier.weight(1f),
                placeholder = { Text("Новый факт") },
                maxLines = 3,
            )
            Spacer(Modifier.width(8.dp))
            Button(onClick = { onAdd(newText); newText = "" }, enabled = newText.isNotBlank()) {
                Text("Добавить")
            }
        }
        TextButton(onClick = onRefresh) {
            Icon(Icons.Filled.Refresh, contentDescription = null)
            Spacer(Modifier.width(6.dp))
            Text("Обновить из диалога сейчас")
        }
    }
    editing?.let { f ->
        TextDialog(
            title = "Факт",
            initial = f.text,
            confirm = "Сохранить",
            singleLine = false,
            onConfirm = { onEdit(f.id, it); editing = null },
            onDismiss = { editing = null },
        )
    }
}

@Composable
private fun ChronicleTab(chronicle: String, onSave: (String) -> Unit) {
    var text by remember(chronicle) { mutableStateOf(chronicle) }
    Column(Modifier.padding(16.dp)) {
        Text(
            "Краткое содержание старой части диалога, которая уже не помещается в контекст дословно. " +
                "Дописывается автоматически; можно поправить.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = text,
            onValueChange = { text = it },
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 160.dp, max = 420.dp),
            placeholder = { Text("Пока пусто — диалог помещается в контекст целиком") },
        )
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onSave(text) }, enabled = text != chronicle) { Text("Сохранить") }
            OutlinedButton(onClick = { text = chronicle }, enabled = text != chronicle) { Text("Отменить") }
        }
    }
}

@Composable
private fun ContextTab(ctx: ContextStats?) {
    Column(Modifier.padding(16.dp)) {
        if (ctx == null || ctx.nCtx <= 0) {
            Text("Данные появятся после первого ответа модели.",
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            return@Column
        }
        Text("Раскладка контекста последнего ответа", style = MaterialTheme.typography.titleSmall)
        Spacer(Modifier.height(8.dp))
        LinearProgressIndicator(
            progress = { ((ctx.total + ctx.reserve).toFloat() / ctx.nCtx).coerceIn(0f, 1f) },
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))
        CtxRow("Системный промпт", ctx.system)
        CtxRow("Память (факты)", ctx.memory)
        CtxRow("Хроника", ctx.chronicle)
        CtxRow("Закреплённые сообщения", ctx.pinned)
        CtxRow("История дословно (${ctx.messages} сообщ.)", ctx.history)
        CtxRow("Резерв на ответ", ctx.reserve)
        HorizontalDivider(Modifier.padding(vertical = 6.dp))
        CtxRow("Всего из ${ctx.nCtx}", ctx.total + ctx.reserve)
        if (ctx.dropped > 0) {
            Spacer(Modifier.height(6.dp))
            Text(
                "Старых сообщений вне окна: ${ctx.dropped} — их содержание в хронике.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun CtxRow(label: String, tokens: Int) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Text("$tokens", style = MaterialTheme.typography.bodyMedium)
    }
}
