package com.tapmoay.sorders.util

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Rect
import android.media.ExifInterface
import java.io.File
import java.io.FileOutputStream

/**
 * # 位图流水线（全库唯一一份）：读 → 按 EXIF 摆正 → 缩到长边 ≤ [MAX_EDGE] →（可选）裁 → 输出 JPEG
 *
 * 2026-10-07（CHG-0072 / 台账 L-33）：商品照片要能**自由框选裁切**，而"先摆正、再裁"这条顺序
 * 与缩放 / 输出这两个参数，必须和送达照那条路（[Watermark]）**一模一样** —— 所以把原来只住在
 * [Watermark] 里的那几步提到这里，[Watermark] 改成调它。
 * ⛔ 谁都不许再复制第二份旋转或缩放：复制出来的那一份，JPEG 质量与最大边长迟早和这边走散，
 * 而且"竖拍照片裁出来是横的"这种坑要再踩一遍。
 *
 * ## 顺序要紧
 * **先按 EXIF 摆正、再裁**。直接拿解码出来的原始位图去裁，竖拍照片（EXIF ROTATE_90 / 270）
 * 裁出来是横的：用户在框里选的是一个方向，存下来的却是另一个方向。
 *
 * ## 谁在回收
 * 每个返回 Bitmap 的函数都把返回件交给调用方回收；**自己造的中间件自己回收**，
 * 调用方传进来的位图一律不回收（[crop]、[saveJpeg] 都不动入参）。
 */
object ImageOps {

    /** 长边上限：超过就等比缩下来（送达照与商品照共用这一条）。 */
    const val MAX_EDGE = 2560

    /** 输出 JPEG 的质量（同上，只有这一处）。 */
    const val JPEG_QUALITY = 85

    /**
     * 读一张磁盘上的图并按 EXIF 摆正（**不缩放**）。返回件归调用方回收。
     *
     * 要"整张图原样"时用它（商品图的裁切框就是按它换算像素的）；只要能用的位图就用 [loadOriented]。
     */
    fun decodeOriented(path: String): Bitmap {
        val raw = BitmapFactory.decodeFile(path) ?: throw IllegalStateException("图片读取失败")
        val rotated = rotateByExif(raw, path)
        if (rotated !== raw) raw.recycle()
        return rotated
    }

    /** 读 + 摆正 + 缩到长边 ≤ [maxEdge]（默认 [MAX_EDGE]）。返回件归调用方回收。 */
    fun loadOriented(path: String, maxEdge: Int = MAX_EDGE): Bitmap {
        val oriented = decodeOriented(path)
        val scaled = scaleDown(oriented, maxEdge)
        if (scaled !== oriented) oriented.recycle()
        return scaled
    }

    /**
     * 按 EXIF 方向摆正。读不到 EXIF、或本来就是正的（ORIENTATION_NORMAL）时**原样返回入参**
     * （同一个对象，调用方按"是不是同一个"决定要不要回收）。
     */
    fun rotateByExif(bmp: Bitmap, path: String): Bitmap {
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

    /** 等比缩到长边 ≤ [maxEdge]；本来就够小则**原样返回入参**（同上，不回收）。 */
    fun scaleDown(bmp: Bitmap, maxEdge: Int): Bitmap {
        val max = maxOf(bmp.width, bmp.height)
        if (max <= maxEdge) return bmp
        val ratio = maxEdge.toFloat() / max
        return Bitmap.createScaledBitmap(bmp, (bmp.width * ratio).toInt(), (bmp.height * ratio).toInt(), true)
    }

    /**
     * 裁一块：[rect] 以 [bmp] 的像素为单位，越界自动夹回图内、整图则返回入参
     * （同一个对象；调用方按"是不是同一个"决定要不要回收）。⛔ 不回收 [bmp]。
     */
    fun crop(bmp: Bitmap, rect: Rect): Bitmap {
        val left = rect.left.coerceIn(0, bmp.width - 1)
        val top = rect.top.coerceIn(0, bmp.height - 1)
        val right = rect.right.coerceIn(left + 1, bmp.width)
        val bottom = rect.bottom.coerceIn(top + 1, bmp.height)
        if (left == 0 && top == 0 && right == bmp.width && bottom == bmp.height) return bmp
        return Bitmap.createBitmap(bmp, left, top, right - left, bottom - top)
    }

    /** 把位图写成 JPEG（质量默认 [JPEG_QUALITY]，唯一的那一处）。⛔ 不回收 [bmp]。 */
    fun saveJpeg(bmp: Bitmap, outFile: File, quality: Int = JPEG_QUALITY): File {
        outFile.parentFile?.mkdirs()
        FileOutputStream(outFile).use { fos ->
            bmp.compress(Bitmap.CompressFormat.JPEG, quality, fos)
        }
        return outFile
    }

    /**
     * 商品照那条路的一步到位：读 [srcPath] → 摆正 → 缩到长边 ≤ [MAX_EDGE] → 裁 [rect]
     * （传 null = 不裁，只摆正 + 压缩）→ 写 [outFile]。返回 [outFile]。
     *
     * 用户口径（m01347）：「可以加一个上传前的**摆正**；压缩就不需要了 —— 压缩是我们**自动**给它压缩的」
     * ⇒ 就算用户选"不裁切"，摆正与压缩也一样要做。
     */
    fun cropToFile(srcPath: String, rect: Rect?, outFile: File): File {
        val scaled = loadOriented(srcPath)
        val cropped = if (rect == null) scaled else crop(scaled, rect)
        if (cropped !== scaled) scaled.recycle()
        saveJpeg(cropped, outFile)
        cropped.recycle()
        return outFile
    }
}
