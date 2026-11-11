package dev.llmbridge.client

import android.content.Context
import android.net.Uri

/** Данные сопряжения из QR-кода ПК: llmbridge://pair?v=1&ssid=..&psk=..&host=..&port=..&token=..&name=.. */
data class Pairing(
    val ssid: String,
    val psk: String,
    val host: String,
    val port: Int,
    val token: String,
    val name: String,
) {
    val baseUrl: String get() = "http://$host:$port"

    fun save(context: Context) {
        prefs(context).edit()
            .putString("ssid", ssid)
            .putString("psk", psk)
            .putString("host", host)
            .putInt("port", port)
            .putString("token", token)
            .putString("name", name)
            .apply()
    }

    companion object {
        private fun prefs(context: Context) =
            context.getSharedPreferences("pairing", Context.MODE_PRIVATE)

        fun parse(text: String): Pairing? {
            val uri = runCatching { Uri.parse(text.trim()) }.getOrNull() ?: return null
            if (uri.scheme != "llmbridge" || uri.host != "pair") return null
            val ssid = uri.getQueryParameter("ssid")?.takeIf { it.isNotBlank() } ?: return null
            val psk = uri.getQueryParameter("psk")?.takeIf { it.length >= 8 } ?: return null
            val host = uri.getQueryParameter("host")?.takeIf { it.isNotBlank() } ?: return null
            val token = uri.getQueryParameter("token")?.takeIf { it.isNotBlank() } ?: return null
            val port = uri.getQueryParameter("port")?.toIntOrNull() ?: 8765
            val name = uri.getQueryParameter("name")?.takeIf { it.isNotBlank() } ?: "ПК"
            return Pairing(ssid, psk, host, port, token, name)
        }

        fun load(context: Context): Pairing? {
            val p = prefs(context)
            val ssid = p.getString("ssid", null) ?: return null
            return Pairing(
                ssid = ssid,
                psk = p.getString("psk", "") ?: "",
                host = p.getString("host", "") ?: "",
                port = p.getInt("port", 8765),
                token = p.getString("token", "") ?: "",
                name = p.getString("name", "ПК") ?: "ПК",
            )
        }

        fun clear(context: Context) {
            prefs(context).edit().clear().apply()
        }
    }
}
