package com.tapmoay.sorders.util

import android.content.ContentValues
import android.content.Context
import android.media.MediaScannerConnection
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import java.io.File
import java.io.FileOutputStream

/** 把导出的字节流保存到系统下载目录，返回展示路径（失败返回 null）。 */
fun saveExportFile(context: Context, bytes: ByteArray, fileName: String): String? {
    return try {
        val displayDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).absolutePath
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, fileName)
                put(MediaStore.Downloads.MIME_TYPE, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/SOrders报表")
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val resolver = context.contentResolver
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: return null
            resolver.openOutputStream(uri)?.use { it.write(bytes) } ?: return null
            values.clear()
            values.put(MediaStore.Downloads.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
            displayDir + "/SOrders报表/" + fileName
        } else {
            val dir = File(displayDir, "SOrders报表").apply { if (!exists()) mkdirs() }
            File(dir, fileName).apply { FileOutputStream(this).use { it.write(bytes) } }.absolutePath
        }
    } catch (e: Exception) {
        null
    }
}

/**
 * 把一张图片保存到系统相册（`Pictures/SOrders`），返回展示路径（失败返回 null）。
 *
 * ## 为什么不复用上面那个函数
 * 两者是同一条路子的**两个落点**：报表落 `Downloads/SOrders报表` + xlsx 的 MIME，
 * 图片落 `Pictures/SOrders` + `image/jpeg`。上面那个函数的目录与 MIME 都是写死的，
 * 为了复用去把它参数化，只会让两个调用点都变得更难读（同一个函数里两个 if 各认一套常量）。
 *
 * ## 权限（这条决定了为什么可以直接写）
 * - Q+ 走 MediaStore：**不需要任何权限**，`IS_PENDING` 那两步是"写完才让别人看见"，
 *   否则相册会在文件还没写完时先抓到一个半张图。
 * - Q 以下（本 App minSdk 26 ⇒ 26–28 这一段）直接写外部存储，靠清单里已有的
 *   `WRITE_EXTERNAL_STORAGE maxSdkVersion="28"`；写完再喊一次媒体扫描，
 *   否则相册要等到下次开机才看得见这张图（用户嘴里就是"保存了但相册里没有"）。
 */
fun saveImageToGallery(context: Context, bytes: ByteArray, fileName: String): String? {
    return try {
        val displayDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES).absolutePath
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.Images.Media.DISPLAY_NAME, fileName)
                put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
                put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/SOrders")
                put(MediaStore.Images.Media.IS_PENDING, 1)
            }
            val resolver = context.contentResolver
            val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values) ?: return null
            resolver.openOutputStream(uri)?.use { it.write(bytes) } ?: return null
            values.clear()
            values.put(MediaStore.Images.Media.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
            displayDir + "/SOrders/" + fileName
        } else {
            val dir = File(displayDir, "SOrders").apply { if (!exists()) mkdirs() }
            val file = File(dir, fileName)
            FileOutputStream(file).use { it.write(bytes) }
            MediaScannerConnection.scanFile(context, arrayOf(file.absolutePath), arrayOf("image/jpeg"), null)
            file.absolutePath
        }
    } catch (e: Exception) {
        null
    }
}
