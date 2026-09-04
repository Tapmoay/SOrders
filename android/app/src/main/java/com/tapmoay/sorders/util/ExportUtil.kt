package com.tapmoay.sorders.util

import android.content.ContentValues
import android.content.Context
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
