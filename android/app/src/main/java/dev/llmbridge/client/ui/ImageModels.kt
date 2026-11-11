package dev.llmbridge.client.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.llmbridge.client.ChatViewModel
import dev.llmbridge.client.ImageRoute

/**
 * «Модели картинок»: какая модель рисует какую задачу и с каким качеством.
 * «Авто» — ПК выбирает сам; если выбранная модель не загрузилась, рисует следующая подходящая.
 */
@Composable
fun ImageModelsDialog(vm: ChatViewModel, online: Boolean, onDismiss: () -> Unit) {
    val routes by vm.imageRoutes.collectAsStateWithLifecycle()
    val quality by vm.imageQuality.collectAsStateWithLifecycle()
    val profiles by vm.profiles.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.loadProfiles() }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Модели картинок") },
        text = {
            Column(Modifier.heightIn(max = 560.dp).verticalScroll(rememberScrollState())) {
                if (!online) {
                    Text("Нет связи с ПК — показаны последние известные настройки.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                    Spacer(Modifier.height(8.dp))
                }
                Text("Качество", style = MaterialTheme.typography.titleSmall)
                Row(Modifier.horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("fast" to "Быстрее", "normal" to "Обычное", "high" to "Выше").forEach { (id, name) ->
                        FilterChip(selected = quality == id, enabled = online,
                            onClick = { vm.setImageQuality(id) }, label = { Text(name) })
                    }
                }
                Text(
                    when (quality) {
                        "fast" -> "Меньше шагов — быстрее, деталей чуть меньше."
                        "high" -> "Больше шагов и картинка крупнее на четверть — заметно дольше."
                        else -> "Шаги и размер, рекомендованные для каждой модели."
                    } + " У быстрых (turbo) моделей число шагов не меняется.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(12.dp))
                Text("Что чем рисовать", style = MaterialTheme.typography.titleSmall)
                if (routes.isEmpty()) {
                    Text("Список задач не получен — обновите мост на ПК.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                routes.forEach { r ->
                    RouteRow(r, online) { vm.setImageRoute(r.id, it) }
                    HorizontalDivider()
                }
                val missing = profiles.filter { !it.ready }
                if (missing.isNotEmpty()) {
                    Spacer(Modifier.height(10.dp))
                    Text("Не скачаны", style = MaterialTheme.typography.titleSmall)
                    missing.forEach { p ->
                        Text("${p.name}: нет файлов ${p.missing.joinToString()}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Готово") } },
    )
}

@Composable
private fun RouteRow(r: ImageRoute, enabled: Boolean, onPick: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    val name = { id: String -> r.options.firstOrNull { it.first == id }?.second ?: id }
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(r.title, style = MaterialTheme.typography.bodyLarge)
            Text(r.hint, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Box {
            Surface(
                color = MaterialTheme.colorScheme.surfaceContainerHighest,
                shape = MaterialTheme.shapes.small,
                modifier = Modifier.clickable(enabled = enabled && r.options.isNotEmpty()) { open = true },
            ) {
                Row(Modifier.padding(start = 12.dp, end = 6.dp, top = 8.dp, bottom = 8.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        when {
                            r.options.isEmpty() -> "нет модели"
                            r.choice.isBlank() -> "Авто · " + name(r.auto)
                            else -> name(r.choice)
                        },
                        style = MaterialTheme.typography.labelLarge, maxLines = 1,
                    )
                    Icon(AppIcons.More, contentDescription = null)
                }
            }
            DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                DropdownMenuItem(text = { Text("Авто · " + name(r.auto)) }, onClick = { open = false; onPick("") })
                r.options.forEach { (id, title) ->
                    DropdownMenuItem(text = { Text(title) }, onClick = { open = false; onPick(id) })
                }
            }
        }
    }
}
