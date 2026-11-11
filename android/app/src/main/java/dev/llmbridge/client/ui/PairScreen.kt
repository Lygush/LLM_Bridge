package dev.llmbridge.client.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.activity.compose.rememberLauncherForActivityResult
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import dev.llmbridge.client.Pairing

@Composable
fun PairScreen(onPaired: (Pairing) -> Unit) {
    var error by remember { mutableStateOf<String?>(null) }
    val clipboard = LocalClipboardManager.current

    fun accept(text: String?) {
        if (text.isNullOrBlank()) return
        val p = Pairing.parse(text)
        if (p == null) {
            error = if (text.startsWith("WIFI:"))
                "Это QR для настроек Wi-Fi. На ПК выберите «Для приложения»"
            else
                "Это не QR-код LLM Bridge"
        } else {
            error = null
            onPaired(p)
        }
    }

    val scanner = rememberLauncherForActivityResult(ScanContract()) { result ->
        accept(result.contents)
    }

    Surface(Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .safeDrawingPadding()
                .padding(24.dp)
                .fillMaxSize(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("LLM Bridge", style = MaterialTheme.typography.headlineMedium)
            Spacer(Modifier.height(12.dp))
            Text(
                "На ПК включите канал в приложении LLM Bridge и отсканируйте QR-код «Для приложения».",
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.bodyLarge,
            )
            Spacer(Modifier.height(32.dp))
            Button(
                onClick = {
                    scanner.launch(
                        ScanOptions()
                            .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                            .setPrompt("Наведите камеру на QR-код на экране ПК")
                            .setBeepEnabled(false)
                            .setOrientationLocked(false)
                    )
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Сканировать QR") }
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = { accept(clipboard.getText()?.text) },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Вставить ссылку из буфера") }
            error?.let {
                Spacer(Modifier.height(16.dp))
                Text(it, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center)
            }
        }
    }
}
