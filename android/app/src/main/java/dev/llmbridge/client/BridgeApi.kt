package dev.llmbridge.client

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

class ApiException(message: String, val code: Int = 0) : IOException(message)

/** REST и WebSocket моста на ПК (api 2). */
class BridgeClient(private val p: Pairing) {

    private val http = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .pingInterval(15, TimeUnit.SECONDS)   // обрыв WebSocket заметим за ~15 с
        .build()

    private val quick = http.newBuilder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .readTimeout(3, TimeUnit.SECONDS)
        .build()

    // запросы, где ПК может сначала вернуть текстовую модель в видеопамять (до нескольких минут)
    private val slow = http.newBuilder()
        .readTimeout(6, TimeUnit.MINUTES)
        .callTimeout(6, TimeUnit.MINUTES)
        .build()

    private val jsonType = "application/json; charset=utf-8".toMediaType()

    private fun req(path: String) = Request.Builder()
        .url(p.baseUrl + path)
        .header("Authorization", "Bearer ${p.token}")

    private suspend fun call(b: Request.Builder, c: OkHttpClient = http): JSONObject = withContext(Dispatchers.IO) {
        c.newCall(b.build()).execute().use { r ->
            val text = r.body?.string().orEmpty()
            val obj = runCatching { JSONObject(text) }.getOrNull()
            if (!r.isSuccessful) {
                val msg = when (r.code) {
                    401 -> "Неверный токен — сопрягите телефон заново"
                    else -> obj?.strOrNull("error") ?: "Ошибка ${r.code}"
                }
                throw ApiException(msg, r.code)
            }
            obj ?: JSONObject()
        }
    }

    private fun body(o: JSONObject) = o.toString().toRequestBody(jsonType)

    suspend fun get(path: String) = call(req(path).get())
    suspend fun post(path: String, o: JSONObject = JSONObject()) = call(req(path).post(body(o)))
    suspend fun postSlow(path: String, o: JSONObject) = call(req(path).post(body(o)), slow)
    suspend fun put(path: String, o: JSONObject) = call(req(path).put(body(o)))
    suspend fun patch(path: String, o: JSONObject) = call(req(path).patch(body(o)))
    suspend fun delete(path: String) = call(req(path).delete())

    /** Версия API моста или null, если ПК не отвечает. */
    suspend fun ping(): Int? = withContext(Dispatchers.IO) {
        try {
            quick.newCall(Request.Builder().url(p.baseUrl + "/api/ping").build()).execute().use { r ->
                if (!r.isSuccessful) null
                else JSONObject(r.body?.string().orEmpty()).optInt("api", 1)
            }
        } catch (e: IOException) {
            null
        } catch (e: org.json.JSONException) {
            null
        }
    }

    /** Двоичные данные (картинки). */
    suspend fun bytes(path: String): ByteArray = withContext(Dispatchers.IO) {
        http.newCall(req(path).get().build()).execute().use { r ->
            if (!r.isSuccessful) throw ApiException("Ошибка ${r.code}", r.code)
            r.body?.bytes() ?: ByteArray(0)
        }
    }

    fun openSocket(listener: WebSocketListener): WebSocket =
        http.newWebSocket(req("/api/ws").build(), listener)
}
