package dev.llmbridge.client

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch

/**
 * Служба переднего плана: держит соединение с ПК, пока приложение свёрнуто
 * или экран выключен. Уведомление показывает состояние и даёт отключиться.
 */
class LinkService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var started = false
    // Wi-Fi не уходит в энергосбережение, пока служба работает; процессор не спит, пока ПК
    // генерирует или идёт подключение (иначе телефон с погасшим экраном перестаёт отвечать
    // мосту, и тот через 15 с рвёт соединение)
    private var wifiLock: WifiManager.WifiLock? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            repo.stopSession(disconnectLink = true)
            releaseLocks()
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
            stopSelf()
            return START_NOT_STICKY
        }
        if (repo.pairing.value == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (!started) {
            started = true
            createChannel()
            val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE else 0
            ServiceCompat.startForeground(this, NOTIF_ID, build("Подключение…"), type)
            acquireLocks()
            scope.launch {
                combine(repo.conn, repo.status) { c, s ->
                    (c.conn == Conn.ONLINE && s.busy) || c.conn == Conn.LINKING || c.conn == Conn.CONNECTING
                }.distinctUntilChanged().collect { keepAwake(it) }
            }
            scope.launch {
                combine(repo.conn, repo.status) { c, s -> text(c, s) }
                    .distinctUntilChanged()
                    .collect { update(it) }
            }
        }
        repo.startSession()
        return START_NOT_STICKY
    }

    private fun acquireLocks() {
        runCatching {
            val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            @Suppress("DEPRECATION")
            wifiLock = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "llmbridge:wifi").apply {
                setReferenceCounted(false)
                acquire()
            }
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "llmbridge:busy").apply {
                setReferenceCounted(false)
            }
        }
    }

    private fun keepAwake(on: Boolean) {
        val wl = wakeLock ?: return
        runCatching {
            if (on) wl.acquire(20 * 60 * 1000L)   // с запасом: сам отпустится, если что-то зависло
            else if (wl.isHeld) wl.release()
        }
    }

    private fun releaseLocks() {
        runCatching { wakeLock?.let { if (it.isHeld) it.release() } }
        runCatching { wifiLock?.let { if (it.isHeld) it.release() } }
        wakeLock = null
        wifiLock = null
    }

    override fun onDestroy() {
        releaseLocks()
        scope.cancel()
        repo.stopSession(disconnectLink = false)
        super.onDestroy()
    }

    private fun text(c: ConnState, s: ServerStatus): String {
        val name = repo.pairing.value?.name ?: "ПК"
        return when (c.conn) {
            Conn.ONLINE -> when {
                s.busy -> "$name · генерация ответа…"
                s.llama == "ready" -> "$name · на связи"
                s.llama == "loading" -> "$name · модель загружается"
                else -> "$name · модель не запущена"
            }
            Conn.LINKING, Conn.CONNECTING -> c.message.ifEmpty { "Подключение…" }
            Conn.OFFLINE -> "Нет связи: ${c.message}"
            Conn.STOPPED -> "Отключено"
        }
    }

    private fun update(text: String) {
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(NOTIF_ID, build(text))
    }

    private fun build(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val stop = PendingIntent.getService(
            this, 1, Intent(this, LinkService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_link)
            .setContentTitle("LLM Bridge")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .addAction(0, "Отключить", stop)
            .build()
    }

    private fun createChannel() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, "Связь с ПК", NotificationManager.IMPORTANCE_LOW)
                .apply { description = "Состояние соединения с моделью на компьютере" })
    }

    companion object {
        private const val CHANNEL = "link"
        private const val NOTIF_ID = 1
        private const val ACTION_STOP = "dev.llmbridge.client.STOP"

        fun start(context: Context) {
            ContextCompat.startForegroundService(context, Intent(context, LinkService::class.java))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, LinkService::class.java))
        }
    }
}
