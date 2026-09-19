package com.tapmoay.sorders.util

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.media.ExifInterface
import java.io.File
import java.io.FileOutputStream
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/**
 * 送达照处理：读取 → 按 EXIF 旋转 → 缩放 → 绘制时间/地点水印 → 输出 JPEG。
 * 返回处理后的文件路径。
 */
object Watermark {

    private const val MAX_EDGE = 2560

    fun process(
        srcFile: File,
        outFile: File,
        locationText: String,
    ): File {
        val raw = BitmapFactory.decodeFile(srcFile.absolutePath) ?: throw IllegalStateException("图片读取失败")
        val rotated = rotateByExif(raw, srcFile.absolutePath)
        val scaled = scaleDown(rotated, MAX_EDGE)
        if (scaled !== rotated) rotated.recycle()
        val marked = drawWatermark(scaled, locationText)
        if (marked !== scaled) scaled.recycle()

        FileOutputStream(outFile).use { fos ->
            marked.compress(Bitmap.CompressFormat.JPEG, 85, fos)
        }
        marked.recycle()
        return outFile
    }

    private fun rotateByExif(bmp: Bitmap, path: String): Bitmap {
        val rotation = runCatching {
            when (ExifInterface(path).getAttributeInt(
                ExifInterface.TAG_ORIENTATION,
                ExifInterface.ORIENTATION_NORMAL
            )) {
                ExifInterface.ORIENTATION_ROTATE_90 -> 90f
                ExifInterface.ORIENTATION_ROTATE_180 -> 180f
                ExifInterface.ORIENTATION_ROTATE_270 -> 270f
                else -> 0f
            }
        }.getOrDefault(0f)
        if (rotation == 0f) return bmp
        val matrix = android.graphics.Matrix().apply { postRotate(rotation) }
        return Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, matrix, true)
    }

    private fun scaleDown(bmp: Bitmap, maxEdge: Int): Bitmap {
        val max = maxOf(bmp.width, bmp.height)
        if (max <= maxEdge) return bmp
        val ratio = maxEdge.toFloat() / max
        return Bitmap.createScaledBitmap(bmp, (bmp.width * ratio).toInt(), (bmp.height * ratio).toInt(), true)
    }

    private fun drawWatermark(src: Bitmap, locationText: String): Bitmap {
        val out = src.copy(Bitmap.Config.ARGB_8888, true)
        val canvas = Canvas(out)
        // 大号水印：约屏宽 5%，最小 40px，保证醒目
        val textSize = (out.width / 20f).coerceAtLeast(40f)
        val time = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
        val lines = listOf(time, locationText.take(60).ifBlank { "送达地点" })

        val bg = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.argb(110, 0, 0, 0)
        }
        val text = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            this.textSize = textSize
        }
        val lineH = textSize * 1.4f
        val pad = textSize * 0.6f
        val totalH = lineH * lines.size + pad * 2
        val top = out.height - totalH - textSize * 0.8f

        canvas.drawRect(0f, top - pad / 2, out.width.toFloat(), out.height.toFloat(), bg)
        lines.forEachIndexed { i, line ->
            canvas.drawText(line, pad, top + i * lineH + textSize, text)
        }
        return out
    }
}
