package dev.llmbridge.client.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import dev.llmbridge.client.ImageProfile
import kotlin.math.roundToInt

private data class SizePreset(val name: String, val w: Int, val h: Int)

private val SIZES = listOf(
    SizePreset("Квадрат", 1024, 1024),
    SizePreset("Портрет", 832, 1216),
    SizePreset("Пейзаж", 1216, 832),
    SizePreset("Быстро", 768, 768),
)

/** Рисование: запрос, профиль (модель), размер, шаги, сид.
 *  Запрос можно писать по-русски и коротко — текстовая модель доработает его в английский промпт. */
@Composable
fun DrawDialog(
    initialPrompt: String,
    profiles: List<ImageProfile>,
    selected: String?,
    onDraw: (prompt: String, profile: String?, width: Int, height: Int, steps: Int?, seed: Long?,
             enhance: Boolean, likeness: Boolean) -> Unit,
    onDismiss: () -> Unit,
    onEnhance: ((String, (String?) -> Unit) -> Unit)? = null,
    initialWidth: Int = 0,
    initialHeight: Int = 0,
    initialEnhance: Boolean = true,
) {
    var prompt by rememberSaveable { mutableStateOf(initialPrompt) }
    var profileId by rememberSaveable { mutableStateOf(selected) }
    var size by rememberSaveable {
        mutableStateOf(SIZES.indexOfFirst { it.w == initialWidth && it.h == initialHeight }.coerceAtLeast(0))
    }
    var enhance by rememberSaveable { mutableStateOf(initialEnhance && onEnhance != null) }
    var enhancing by remember { mutableStateOf(false) }
    var likeness by rememberSaveable { mutableStateOf(true) }
    var steps by remember { mutableStateOf<Int?>(null) }
    var seed by rememberSaveable { mutableStateOf("") }

    // null — «Авто»: ПК сам берёт модель под задачу (см. «Модели картинок» в меню)
    val profile = profiles.firstOrNull { it.id == profileId && it.ready }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Нарисовать") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                OutlinedTextField(
                    value = prompt,
                    onValueChange = { prompt = it },
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 96.dp, max = 220.dp),
                    enabled = !enhancing,
                    placeholder = { Text("Что нарисовать: сюжет, стиль, свет, детали…") },
                )
                if (onEnhance != null) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth().clickable { enhance = !enhance },
                    ) {
                        Checkbox(checked = enhance, onCheckedChange = { enhance = it })
                        Text("Модель доработает запрос", style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.weight(1f))
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        OutlinedButton(
                            onClick = {
                                enhancing = true
                                onEnhance(prompt.trim()) { better ->
                                    enhancing = false
                                    if (better != null) {
                                        prompt = better
                                        enhance = false   // уже доработан — рисуем как есть
                                    }
                                }
                            },
                            enabled = prompt.isNotBlank() && !enhancing,
                        ) { Text("Улучшить сейчас") }
                        if (enhancing) {
                            Spacer(Modifier.width(10.dp))
                            CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                            Spacer(Modifier.width(8.dp))
                            Text("модель пишет промпт…", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth().clickable { likeness = !likeness },
                ) {
                    Checkbox(checked = likeness, onCheckedChange = { likeness = it })
                    Text("Персонажи — по их портретам", style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.weight(1f))
                }
                Text(
                    if (enhance) "Пишите как удобно, по-русски: модель на ПК превратит запрос в подробный " +
                        "английский промпт с учётом чата (внешность персонажей, сцена)."
                    else "Модели изображений лучше понимают английский. Модель на ПК во время рисования " +
                        "выгружается и вернётся при следующем сообщении.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))

                Text("Модель", style = MaterialTheme.typography.titleSmall)
                if (profiles.isEmpty()) {
                    Text("Профили не загружены или не настроены на ПК",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                }
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth().clickable { profileId = null; steps = null },
                ) {
                    RadioButton(selected = profile == null, onClick = { profileId = null; steps = null })
                    Column {
                        Text("Авто", style = MaterialTheme.typography.bodyMedium)
                        Text("модель под задачу: с лицом персонажа — одна, без — другая",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                profiles.forEach { p ->
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable(enabled = p.ready) { profileId = p.id; steps = null },
                    ) {
                        RadioButton(selected = profile?.id == p.id, enabled = p.ready,
                            onClick = { profileId = p.id; steps = null })
                        Column {
                            Text(p.name, style = MaterialTheme.typography.bodyMedium)
                            if (p.ready && p.about.isNotBlank()) {
                                Text(p.about, style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            if (!p.ready) {
                                Text("нет файлов: " + p.missing.joinToString(),
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.error)
                            }
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))

                Text("Размер", style = MaterialTheme.typography.titleSmall)
                Row(
                    Modifier.horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    SIZES.forEachIndexed { i, s ->
                        FilterChip(
                            selected = size == i,
                            onClick = { size = i },
                            label = { Text("${s.name} ${s.w}×${s.h}", style = MaterialTheme.typography.labelSmall) },
                        )
                    }
                }
                Spacer(Modifier.height(8.dp))

                val profileSteps = profile?.steps ?: 20
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Шаги", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                    Text(
                        if (steps == null) (if (profile == null) "как у модели" else "$profileSteps · по профилю")
                        else "$steps",
                        style = MaterialTheme.typography.labelMedium,
                        modifier = Modifier.clickable { steps = null },
                    )
                }
                Slider(
                    value = (steps ?: profileSteps).toFloat(),
                    onValueChange = { steps = it.roundToInt() },
                    valueRange = 1f..60f,
                    steps = 58,
                )
                Text("Больше шагов — детальнее, но дольше. Turbo-моделям хватает 6–10.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(8.dp))

                OutlinedTextField(
                    value = seed,
                    onValueChange = { v -> seed = v.filter { it.isDigit() }.take(10) },
                    label = { Text("Сид (пусто — случайный)") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    val s = SIZES[size]
                    onDraw(prompt.trim(), profile?.id, s.w, s.h, steps, seed.toLongOrNull(), enhance, likeness)
                },
                enabled = prompt.isNotBlank() && profiles.any { it.ready } && !enhancing,
            ) { Text("Нарисовать") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Отмена") } },
    )
}
