package dev.llmbridge.client

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.llmbridge.client.ui.BridgeTheme
import dev.llmbridge.client.ui.ChatScreen
import dev.llmbridge.client.ui.PairScreen

class MainActivity : ComponentActivity() {
    private val vm: ChatViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            AppTheme {
                val pairing by vm.pairing.collectAsStateWithLifecycle()
                val p = pairing
                if (p == null) {
                    PairScreen(onPaired = vm::pair)
                } else {
                    ChatScreen(vm = vm, pairing = p)
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        vm.repo.onForeground()
    }
}

/** Тема приложения — см. ui/Ui.kt (свои цвета, тёмная и светлая по системе). */
@Composable
fun AppTheme(content: @Composable () -> Unit) = BridgeTheme(content)
