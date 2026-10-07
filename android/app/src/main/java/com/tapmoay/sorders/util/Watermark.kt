package com.tapmoay.sorders.util

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import java.io.File
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/**
 * 图片处理：读取（或接一张内存里的位图）→ 按 EXIF 旋转 / 缩放 → 绘制时间/地点水印 → 输出 JPEG。
 * 返回处理后的文件路径。
 *
 * 水印**画哪几行**不在这里定：文案与行数出自 [WatermarkText]（纯函数、可单测）。
 * 两个入口的差别只是「照片从哪来」：
 * - [process]：磁盘上的文件（送达照链路，按 EXIF 摆正）；
 * - [markBitmap]：已经在内存里的位图（详情页「位置图片」的系统相机那条路）。
 *
 * ⚠️ 2026-10-07（CHG-0072 / 台账 L-33）：位图流水线那几步（按 EXIF 摆正 / 缩到长边 ≤
 * [ImageOps.MAX_EDGE] / 输出 JPEG [ImageOps.JPEG_QUALITY]）已经提成公共件 [ImageOps]，
 * 商品照片的裁切也走它 —— 这里只留"水印怎么画"（画图是全库只许在两处出现的东西之一）。
 * ⛔ 不许在本文件里再写一份旋转或缩放。
 *
 * @param tag 补拍标识（台账 L-22）：传 [WatermarkText.MAKEUP_TAG] = 这张是事后补的，多画一行；
 *            留空 = 当场拍的（两行，与既有送达照逐字一致）。
 */
object Watermark {

    /** 长边上限 —— 与商品照共用同一个值，出处只有 [ImageOps.MAX_EDGE]。 */
    private const val MAX_EDGE = ImageOps.MAX_EDGE

    fun process(
        srcFile: File,
        outFile: File,
        locationText: String,
        tag: String? = null,
    ): File {
        // 读 + 按 EXIF 摆正 + 缩到长边上限：三步都在 ImageOps 里，全库只有那一份实现。
        val scaled = ImageOps.loadOriented(srcFile.absolutePath, MAX_EDGE)
        val marked = drawWatermark(scaled, locationText, tag)
        if (marked !== scaled) scaled.recycle()

        ImageOps.saveJpeg(marked, outFile)
        marked.recycle()
        return outFile
    }

    /**
     * 已经在内存里的位图（系统相机 TakePicturePreview 那条路）—— 不必先落盘再读回来。
     *
     * ⛔ 不回收 [src]：那是调用方的位图（相机回调给的），本函数只回收自己造的中间件。
     */
    fun markBitmap(
        src: Bitmap,
        outFile: File,
        locationText: String,
        tag: String? = null,
    ): File {
        val scaled = ImageOps.scaleDown(src, MAX_EDGE)
        val marked = drawWatermark(scaled, locationText, tag)
        if (scaled !== src) scaled.recycle()

        ImageOps.saveJpeg(marked, outFile)
        marked.recycle()
        return outFile
    }

    private fun drawWatermark(src: Bitmap, locationText: String, tag: String? = null): Bitmap {
        val out = src.copy(Bitmap.Config.ARGB_8888, true)
        val canvas = Canvas(out)
        // 大号水印：约屏宽 5%，最小 40px，保证醒目
        val textSize = (out.width / 20f).coerceAtLeast(40f)
        val time = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
        // 画哪几行**只有一个出处**（时间 + 地点 + 可选的补拍标识），见 WatermarkText
        val lines = WatermarkText.lines(time, locationText, tag)

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
