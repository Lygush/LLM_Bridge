package dev.llmbridge.client.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import dev.llmbridge.client.GenSettings
import dev.llmbridge.client.Recommended
import java.util.Locale
import kotlin.math.roundToInt

private val ILLUSTRATE = listOf(
    Triple("off", "Выкл", "модель не рисует сама — только кнопка «Нарисовать…»"),
    Triple("on_request", "По просьбе", "рисует, когда попросите в сообщении: «нарисуй…», «покажи…»"),
    Triple("auto", "Ключевые моменты", "ещё и сама иллюстрирует новые сцены и персонажей"),
)

private data class Preset(val name: String, val hint: String, val apply: (GenSettings) -> GenSettings)

private val PRESETS = listOf(
    Preset("Рекомендуемые", "сбалансированно, по совету авторов Qwen") { s ->
        GenSettings(thinking = s.thinking, maxTokens = s.maxTokens,
            imageProfile = s.imageProfile, illustrate = s.illustrate, likeness = s.likeness)
    },
    Preset("Точный", "факты, код, расчёты") { s ->
        s.copy(temperature = 0.3, topP = 0.8, topK = 20, minP = 0.0, presencePenalty = 0.5, repeatPenalty = null)
    },
    Preset("Творческий", "истории, ролевые игры") { s ->
        s.copy(temperature = 1.0, topP = 0.95, topK = 40, minP = 0.05, presencePenalty = 1.2, repeatPenalty = null)
    },
)

/** Параметры генерации чата: тумблер размышлений, пресеты, ползунки. */
@Composable
fun SettingsDialog(
    initial: GenSettings,
    recommended: Recommended,
    forChat: Boolean,
    onSave: (GenSettings, Boolean) -> Unit,
    onDismiss: () -> Unit,
) {
    var s by remember { mutableStateOf(initial) }
    var makeDefault by remember { mutableStateOf(false) }
    val rec = recommended.forMode(s.thinking)

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Параметры генерации") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clickable { s = s.copy(thinking = !s.thinking) },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text("Размышления", style = MaterialTheme.typography.titleSmall)
                        Text(
                            "Модель сначала рассуждает: точнее на сложных задачах, но заметно дольше.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Switch(checked = s.thinking, onCheckedChange = { s = s.copy(thinking = it) })
                }
                Spacer(Modifier.height(12.dp))
                Text("Иллюстрации", style = MaterialTheme.typography.titleSmall)
                val ill = s.illustrate ?: "on_request"
                Row(
                    Modifier.horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    ILLUSTRATE.forEach { (id, name, _) ->
                        FilterChip(
                            selected = ill == id,
                            onClick = { s = s.copy(illustrate = id) },
                            label = { Text(name, style = MaterialTheme.typography.labelSmall) },
                        )
                    }
                }
                Text(
                    ILLUSTRATE.first { it.first == ill }.third,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Похожие лица", style = MaterialTheme.typography.bodyMedium)
                        Text("персонажи рисуются по своим портретам (нужен Qwen-Image с зрением; медленнее)",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Switch(checked = s.likeness != false, onCheckedChange = { s = s.copy(likeness = it) })
                }
                Spacer(Modifier.height(12.dp))
                Text("Пресет", style = MaterialTheme.typography.titleSmall)
                Row(
                    Modifier.horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    PRESETS.forEach { p ->
                        FilterChip(
                            selected = p.apply(s) == s,
                            onClick = { s = p.apply(s) },
                            label = { Text(p.name, style = MaterialTheme.typography.labelSmall) },
                        )
                    }
                }
                Text(
                    PRESETS.firstOrNull { it.apply(s) == s }?.hint ?: "свои значения",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                HorizontalDivider(Modifier.padding(vertical = 8.dp))

                ParamSlider("Длина ответа, токенов", s.maxTokens?.toDouble(), rec.maxTokens?.toDouble() ?: 1536.0,
                    256f..8192f, 30, { "%.0f".format(Locale.US, it) },
                    "Предел длины. Если ответ оборвался — «Продолжить» в меню сообщения.") {
                    s = s.copy(maxTokens = it?.roundToInt())
                }
                ParamSlider("Температура", s.temperature, rec.temperature ?: 0.7, 0f..2f, 39,
                    { "%.2f".format(Locale.US, it) }, "Выше — разнообразнее и смелее, ниже — предсказуемее.") {
                    s = s.copy(temperature = it)
                }
                ParamSlider("Штраф за повторы (presence)", s.presencePenalty, rec.presencePenalty ?: 1.0,
                    0f..2f, 19, { "%.1f".format(Locale.US, it) },
                    "Против зацикливания. 1–1.5 помогает квантованным моделям.") {
                    s = s.copy(presencePenalty = it)
                }
                ParamSlider("Top-p", s.topP, rec.topP ?: 0.8, 0.5f..1f, 9, { "%.2f".format(Locale.US, it) },
                    null) { s = s.copy(topP = it) }
                ParamSlider("Top-k", s.topK?.toDouble(), rec.topK?.toDouble() ?: 20.0, 0f..100f, 19,
                    { "%.0f".format(Locale.US, it) }, "0 — без ограничения.") {
                    s = s.copy(topK = it?.roundToInt())
                }
                ParamSlider("Min-p", s.minP, rec.minP ?: 0.0, 0f..0.3f, 29, { "%.2f".format(Locale.US, it) },
                    null) { s = s.copy(minP = it) }
                ParamSlider("Штраф за повтор токенов (repeat)", s.repeatPenalty, 1.0, 1f..1.5f, 9,
                    { "%.2f".format(Locale.US, it) }, null) { s = s.copy(repeatPenalty = it) }

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
        confirmButton = { TextButton(onClick = { onSave(s, makeDefault) }) { Text("Сохранить") } },
        dismissButton = {
            Row {
                TextButton(onClick = { s = GenSettings(thinking = s.thinking) }) { Text("Сброс") }
                TextButton(onClick = onDismiss) { Text("Отмена") }
            }
        },
    )
}

/** Ползунок параметра. value == null — используется рекомендуемое значение («авто»). */
@Composable
private fun ParamSlider(
    label: String,
    value: Double?,
    recommended: Double,
    range: ClosedFloatingPointRange<Float>,
    steps: Int,
    format: (Double) -> String,
    hint: String?,
    onChange: (Double?) -> Unit,
) {
    val shown = value ?: recommended
    Column(Modifier.padding(vertical = 4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            Text(
                format(shown) + if (value == null) " · авто" else "",
                style = MaterialTheme.typography.labelMedium,
                color = if (value == null) MaterialTheme.colorScheme.onSurfaceVariant
                else MaterialTheme.colorScheme.primary,
                modifier = Modifier.clickable { onChange(null) },   // нажатие на значение — вернуть «авто»
            )
        }
        Slider(
            value = shown.toFloat().coerceIn(range.start, range.endInclusive),
            onValueChange = { onChange(it.toDouble()) },
            valueRange = range,
            steps = steps,
        )
        if (hint != null) {
            Text(hint, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
