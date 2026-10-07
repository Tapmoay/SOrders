package com.tapmoay.sorders.util

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.media.MediaScannerConnection
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import java.io.File
import java.io.FileOutputStream

/** 下载目录下的子目录（全 App 一处定义：AI 在聊天里下的报表与报表中心下的，落在一起）。 */
private const val EXPORT_SUBDIR = "SOrders报表"

/** xlsx 的 MIME（一处定义、三个用户：存 Downloads、分享时告诉对方这是什么、单测断言）。 */
private const val MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

/**
 * 一次落盘的结果：能给人看的路径 + 能给别的 App 的 Uri。
 *
 * 为什么要把 Uri 带出来（v3.34，CHG-0078）：[saveExportFile] 从 v3.6 起就把 Uri **扔掉**了，
 * 而分享（微信/QQ）**只能**靠它 —— 拿到路径没有用，`file://` 从 Android 7 起会直接抛
 * `FileUriExposedException`。所以保存这一步顺手把它留给调用方。
 *
 * [uri] 为 null = **这台手机上分享不了**：Android 10 以下的落盘走的是外部存储的普通文件，
 * 没有 MediaStore 给的 `content://`。这是系统的事，不是可以绕过去的（口径 m01865：分享只对 10+ 开）。
 */
data class ExportedFile(val path: String, val uri: Uri?, val fileName: String) {
    /** 这台机器上能不能分享（分享按钮据此显示或换成一句中文说明）。 */
    val shareable: Boolean get() = uri != null
}

/** 把导出的字节流保存到系统下载目录，返回展示路径（失败返回 null）。 */
fun saveExportFile(context: Context, bytes: ByteArray, fileName: String): String? =
    saveExportFileWithUri(context, bytes, fileName)?.path

/**
 * 同 [saveExportFile]，但把 Uri 一起带回来（聊天页的「下载」与报表页的「分享」都要它）。
 *
 * Q+ 走 MediaStore：`IS_PENDING` 那两步是"写完才让别人看见"，否则文件管理器/分享目标
 * 可能抓到一份还没写完的 xlsx。Q 以下（minSdk 26 ⇒ 26–28）直接写外部存储，
 * 靠清单里已有的 `WRITE_EXTERNAL_STORAGE maxSdkVersion="28"`。
 */
fun saveExportFileWithUri(context: Context, bytes: ByteArray, fileName: String): ExportedFile? {
    return try {
        val displayDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).absolutePath
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, fileName)
                put(MediaStore.Downloads.MIME_TYPE, MIME_XLSX)
                put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/" + EXPORT_SUBDIR)
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val resolver = context.contentResolver
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: return null
            resolver.openOutputStream(uri)?.use { it.write(bytes) } ?: return null
            values.clear()
            values.put(MediaStore.Downloads.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
            ExportedFile(displayDir + "/" + EXPORT_SUBDIR + "/" + fileName, uri, fileName)
        } else {
            val dir = File(displayDir, EXPORT_SUBDIR).apply { if (!exists()) mkdirs() }
            val file = File(dir, fileName).apply { FileOutputStream(this).use { it.write(bytes) } }
            ExportedFile(file.absolutePath, null, fileName)
        }
    } catch (e: Exception) {
        null
    }
}

/**
 * 把一份导出的文件**交给别的 App**（微信、QQ、邮件…）。
 *
 * 为什么是 `ACTION_SEND` + `createChooser` 而不是直接点名微信：点名的话没装微信就崩，
 * 而且用户想发到 QQ/邮箱时还得再改一次代码。
 *
 * 两处细节：
 * - `FLAG_GRANT_READ_URI_PERMISSION` 必须加 —— 目标 App 没有我们的存储权限，
 *   这一句才是"临时允许它读这一个 Uri"；少了它微信会收到一个打不开的附件。
 * - `FLAG_ACTIVITY_NEW_TASK` 也必须加 —— 这里是 applicationContext 起的 Activity。
 *
 * 返回 false = 没能起分享面板（系统里连一个能收 xlsx 的 App 都没有），调用方如实说一句。
 */
fun shareExportFile(context: Context, file: ExportedFile): Boolean {
    val uri = file.uri ?: return false
    return try {
        val send = Intent(Intent.ACTION_SEND).apply {
            type = MIME_XLSX
            putExtra(Intent.EXTRA_STREAM, uri)
            putExtra(Intent.EXTRA_SUBJECT, file.fileName)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        val chooser = Intent.createChooser(send, "分享到").apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(chooser)
        true
    } catch (e: Exception) {
        false
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
