package dev.llmbridge.client

import android.content.Context
import android.graphics.Bitmap
import android.graphics.ImageDecoder
import android.net.Uri
import java.io.ByteArrayOutputStream
import kotlin.math.roundToInt

/** Подготовленное к отправке фото: JPEG и миниатюра для превью. */
class Attachment(val jpeg: ByteArray, val preview: Bitmap)

object ImageUtil {
    /** Длинная сторона после сжатия: модели больше не нужно, а передача быстрее. */
    const val MAX_SIDE = 1280

    /**
     * Фото из галереи или камеры → JPEG не больше MAX_SIDE по длинной стороне.
     * ImageDecoder сам учитывает поворот из EXIF. Вызывать не в главном потоке.
     */
    fun prepare(context: Context, uri: Uri): Attachment? = try {
        val src = ImageDecoder.createSource(context.contentResolver, uri)
        val bmp = ImageDecoder.decodeBitmap(src) { decoder, info, _ ->
            val w = info.size.width
            val h = info.size.height
            val scale = minOf(1.0, MAX_SIDE.toDouble() / maxOf(w, h))
            decoder.setTargetSize(maxOf(1, (w * scale).roundToInt()), maxOf(1, (h * scale).roundToInt()))
            decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE   // нужно для compress()
        }
        val out = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, 85, out)
        val k = 256.0 / maxOf(bmp.width, bmp.height)
        val preview = if (k < 1) Bitmap.createScaledBitmap(
            bmp, maxOf(1, (bmp.width * k).roundToInt()), maxOf(1, (bmp.height * k).roundToInt()), true
        ) else bmp
        Attachment(out.toByteArray(), preview)
    } catch (e: Exception) {
        null
    }
}
