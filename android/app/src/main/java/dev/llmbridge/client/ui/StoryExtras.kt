package dev.llmbridge.client.ui

import android.graphics.Bitmap
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import dev.llmbridge.client.Fork
import dev.llmbridge.client.GalleryItem
import dev.llmbridge.client.Proposal

/** «Персонаж меняется»: модель предлагает обновить карточку, решает человек. */
@Composable
fun ProposalBanner(p: Proposal, fieldLabel: String, onAnswer: (Boolean) -> Unit) {
    var show by remember { mutableStateOf(false) }
    Surface(color = MaterialTheme.colorScheme.tertiaryContainer, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(horizontal = 14.dp, vertical = 6.dp)) {
            IconLabel(AppIcons.Edit, "${p.name}: ${p.reason.ifBlank { "изменения" }}",
                style = MaterialTheme.typography.labelLarge, maxLines = 2)
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(onClick = { show = true }) { Text("Что изменится") }
                TextButton(onClick = { onAnswer(true) }) { Text("Обновить карточку") }
                TextButton(onClick = { onAnswer(false) }) { Text("Нет") }
            }
        }
    }
    if (show) {
        AlertDialog(
            onDismissRequest = { show = false },
            title = { Text("${p.name} — $fieldLabel") },
            text = {
                Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState())) {
                    Text(p.reason, style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(8.dp))
                    Text("Станет так:", style = MaterialTheme.typography.labelMedium)
                    Text(p.value)
                }
            },
            confirmButton = { TextButton(onClick = { show = false; onAnswer(true) }) { Text("Обновить") } },
            dismissButton = { TextButton(onClick = { show = false }) { Text("Закрыть") } },
        )
    }
}

/** Карта выборов истории. */
@Composable
fun ForksDialog(forks: List<Fork>, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Карта выборов") },
        text = {
            Column(Modifier.heightIn(max = 480.dp).verticalScroll(rememberScrollState())) {
                if (forks.isEmpty()) Text("Развилок пока не было.")
                forks.forEachIndexed { i, f ->
                    Text("Развилка ${i + 1}", style = MaterialTheme.typography.titleSmall)
                    f.options.forEach { o ->
                        val mark = when {
                            o == f.taken -> AppIcons.Check
                            o in f.tried -> AppIcons.Retry
                            else -> AppIcons.Empty
                        }
                        IconLabel(mark, o, style = MaterialTheme.typography.bodyMedium, maxLines = 3,
                            color = if (o == f.taken) MaterialTheme.colorScheme.primary
                            else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    val own = (listOfNotNull(f.taken) + f.tried).filter { it !in f.options }
                    own.forEach { IconLabel(AppIcons.Edit, it, style = MaterialTheme.typography.bodyMedium, maxLines = 3) }
                    Spacer(Modifier.height(10.dp))
                }
                val dim = MaterialTheme.colorScheme.onSurfaceVariant
                val small = MaterialTheme.typography.labelSmall
                IconLabel(AppIcons.Check, "выбрано", style = small, color = dim, iconSize = 14.dp)
                IconLabel(AppIcons.Retry, "пробовали в другой ветке", style = small, color = dim, iconSize = 14.dp)
                IconLabel(AppIcons.Empty, "не выбирали", style = small, color = dim, iconSize = 14.dp)
                IconLabel(AppIcons.Edit, "свой вариант", style = small, color = dim, iconSize = 14.dp)
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Закрыть") } },
    )
}

/** Галерея чата: все картинки, фоны, портреты и эмоции — сеткой; нажатие открывает крупно. */
@Composable
fun GalleryDialog(pics: List<GalleryItem>, load: suspend (String) -> Bitmap?, onSave: (String) -> Unit,
                  onDismiss: () -> Unit) {
    var open by remember { mutableStateOf<GalleryItem?>(null) }
    Dialog(onDismissRequest = { if (open != null) open = null else onDismiss() },
        properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.padding(top = 36.dp, bottom = 36.dp)) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp)) {
                    Text("Галерея · ${pics.size}", style = MaterialTheme.typography.titleLarge,
                        modifier = Modifier.weight(1f).padding(top = 8.dp))
                    TextButton(onClick = onDismiss) { Text("Закрыть") }
                }
                val cur = open
                if (cur != null) {
                    Column(Modifier.fillMaxSize().clickable { open = null }.padding(8.dp)) {
                        RemoteImage(cur.name, load, Modifier.fillMaxWidth().weight(1f).clip(RoundedCornerShape(10.dp)))
                        Text(cur.caption, style = MaterialTheme.typography.bodyMedium, maxLines = 3,
                            overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
                        TextButton(onClick = { onSave(cur.name) }) { Text("Сохранить в галерею телефона") }
                    }
                } else if (pics.isEmpty()) {
                    Text("Картинок пока нет.", modifier = Modifier.padding(24.dp))
                } else {
                    LazyVerticalGrid(columns = GridCells.Adaptive(110.dp), modifier = Modifier.fillMaxSize().padding(6.dp),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(pics, key = { it.name }) { it ->
                            Box(Modifier.aspectRatio(1f).clip(RoundedCornerShape(8.dp)).clickable { open = it }) {
                                RemoteImage(it.name, load, Modifier.fillMaxSize())
                            }
                        }
                    }
                }
            }
        }
    }
}
