package dev.llmbridge.client

import android.annotation.SuppressLint
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.wifi.p2p.WifiP2pConfig
import android.net.wifi.p2p.WifiP2pInfo
import android.net.wifi.p2p.WifiP2pManager
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class LinkPhase { IDLE, CONNECTING, CONNECTED, FAILED }

data class LinkState(val phase: LinkPhase, val message: String = "")

/**
 * Подключение к группе Wi-Fi Direct, которую держит ПК (он — Group Owner).
 * С Android 10 можно войти в существующую группу по имени сети и паролю,
 * без согласования ролей и без подтверждения на стороне ПК.
 */
class P2pConnector(context: Context) {
    private val ctx = context.applicationContext
    private val manager: WifiP2pManager? = ctx.getSystemService(WifiP2pManager::class.java)
    private var channel: WifiP2pManager.Channel? = null
    private val handler = Handler(Looper.getMainLooper())
    private var p2pEnabled = true

    private val _state = MutableStateFlow(LinkState(LinkPhase.IDLE))
    val state: StateFlow<LinkState> = _state.asStateFlow()

    private val timeout = Runnable {
        if (_state.value.phase == LinkPhase.CONNECTING) {
            fail("ПК не найден за 30 с. Проверьте, что канал на ПК включён")
        }
    }

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, intent: Intent) {
            when (intent.action) {
                WifiP2pManager.WIFI_P2P_STATE_CHANGED_ACTION -> {
                    val st = intent.getIntExtra(WifiP2pManager.EXTRA_WIFI_STATE, -1)
                    p2pEnabled = st == WifiP2pManager.WIFI_P2P_STATE_ENABLED
                    if (!p2pEnabled && _state.value.phase != LinkPhase.IDLE) {
                        fail("Wi-Fi выключен")
                    }
                }
                WifiP2pManager.WIFI_P2P_CONNECTION_CHANGED_ACTION -> refreshConnectionInfo()
            }
        }
    }

    init {
        val filter = IntentFilter().apply {
            addAction(WifiP2pManager.WIFI_P2P_STATE_CHANGED_ACTION)
            addAction(WifiP2pManager.WIFI_P2P_CONNECTION_CHANGED_ACTION)
        }
        ContextCompat.registerReceiver(ctx, receiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
    }

    private fun ch(): WifiP2pManager.Channel? {
        val m = manager ?: return null
        return channel ?: m.initialize(ctx, Looper.getMainLooper()) { channel = null }
            .also { channel = it }
    }

    private fun fail(msg: String) {
        handler.removeCallbacks(timeout)
        _state.value = LinkState(LinkPhase.FAILED, msg)
    }

    @SuppressLint("MissingPermission")
    private fun refreshConnectionInfo() {
        val m = manager ?: return
        val c = ch() ?: return
        m.requestConnectionInfo(c) { info: WifiP2pInfo? ->
            val formed = info?.groupFormed == true
            when {
                formed && !info!!.isGroupOwner -> {
                    handler.removeCallbacks(timeout)
                    _state.value = LinkState(LinkPhase.CONNECTED)
                }
                !formed && _state.value.phase == LinkPhase.CONNECTED ->
                    fail("Соединение Wi-Fi Direct разорвано")
            }
        }
    }

    /** Требует разрешений NEARBY_WIFI_DEVICES (Android 13+) или ACCESS_FINE_LOCATION (10–12). */
    @SuppressLint("MissingPermission")
    fun connect(p: Pairing) {
        val m = manager
        val c = ch()
        if (m == null || c == null) {
            fail("Телефон не поддерживает Wi-Fi Direct")
            return
        }
        if (!p2pEnabled) {
            fail("Включите Wi-Fi")
            return
        }
        val config = try {
            WifiP2pConfig.Builder()
                .setNetworkName(p.ssid)
                .setPassphrase(p.psk)
                .enablePersistentMode(false)
                .setGroupOperatingBand(WifiP2pConfig.GROUP_OWNER_BAND_AUTO)
                .build()
        } catch (e: IllegalArgumentException) {
            fail("Некорректные данные сети: ${e.message}")
            return
        }
        _state.value = LinkState(LinkPhase.CONNECTING, "Подключение к ${p.ssid}…")
        handler.removeCallbacks(timeout)
        handler.postDelayed(timeout, 30_000)

        m.requestConnectionInfo(c) { info ->
            val formed = info?.groupFormed == true
            val isOwner = info?.isGroupOwner == true
            val owner = info?.groupOwnerAddress?.hostAddress
            if (formed && !isOwner && owner == p.host) {
                // уже в группе нашего ПК — переподключаться не нужно
                handler.removeCallbacks(timeout)
                _state.value = LinkState(LinkPhase.CONNECTED)
            } else if (formed) {
                // телефон в какой-то другой группе Wi-Fi Direct — выходим из неё
                m.removeGroup(c, object : WifiP2pManager.ActionListener {
                    override fun onSuccess() = doConnect(m, c, config)
                    override fun onFailure(reason: Int) = doConnect(m, c, config)
                })
            } else {
                doConnect(m, c, config)
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun doConnect(m: WifiP2pManager, c: WifiP2pManager.Channel, config: WifiP2pConfig) {
        try {
            m.connect(c, config, object : WifiP2pManager.ActionListener {
                override fun onSuccess() {
                    // запрос принят, результат придёт через WIFI_P2P_CONNECTION_CHANGED_ACTION
                }

                override fun onFailure(reason: Int) {
                    fail("Wi-Fi Direct: " + when (reason) {
                        WifiP2pManager.P2P_UNSUPPORTED -> "не поддерживается"
                        WifiP2pManager.BUSY -> "модуль занят, повторите"
                        else -> "ошибка $reason"
                    })
                }
            })
        } catch (e: SecurityException) {
            fail("Нет разрешения на Wi-Fi Direct")
        }
    }

    fun disconnect() {
        handler.removeCallbacks(timeout)
        val m = manager
        val c = ch()
        if (m != null && c != null) m.removeGroup(c, null)
        _state.value = LinkState(LinkPhase.IDLE)
    }

    fun release() {
        handler.removeCallbacks(timeout)
        runCatching { ctx.unregisterReceiver(receiver) }
    }
}
