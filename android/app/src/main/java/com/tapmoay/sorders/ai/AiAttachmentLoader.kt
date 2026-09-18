package com.tapmoay.sorders.ai

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns

/**
 * 从手机里把用户选的文件读出来，准备上传给后端解析。
 *
 * ### 为什么先读成一个 byte 数组
 * 用户选的是一个 `content://` URI（SAF），它不一定是文件路径——可能是云盘、
 * 可能是别的 App 的 provider。能拿到的只有字节流，所以统一读成字节再上传。
 *
 * ### 为什么本地就要拦一道
 * 后端的 `files/parse-sheet` 也会拦（8MB、扩展名白名单），但那是**传完一遍之后**才知道被拒。
 * 一个 200MB 的视频选中后先传 30 秒再报"不支持这种文件"，用户会以为 App 卡死了。
 * 能在这里一眼看出来的（扩展名不对、文件太大、读不到），就在这里说清楚。
 */
object AiAttachmentLoader {

    /** 与后端 `sheet_parser.MAX_BYTES` 保持一致（8MB）。两边不一致时以更小的那个为准。 */
    const val MAX_BYTES = 8 * 1024 * 1024

    /** 能读的扩展名（小写含点）。与后端白名单**必须一致**，改一边就要改另一边。 */
    val ALLOWED_EXT = setOf(".xlsx", ".xlsm", ".csv", ".tsv", ".txt")

    /** 旧版 Excel（二进制 .xls）——读不了，但要给一句"怎么办"，而不是"不支持"。 */
    private val LEGACY_EXT = setOf(".xls")

    class AttachmentException(message: String) : Exception(message)

    /** 读出来的一个待上传文件。 */
    data class Picked(val filename: String, val mime: String, val bytes: ByteArray) {
        // ByteArray 让它变成一个"按内容比较"的普通数据类（自动生成的 equals 比的是引用）
        override fun equals(other: Any?): Boolean =
            this === other || (other is Picked && filename == other.filename && bytes.contentEquals(other.bytes))

        override fun hashCode(): Int = 31 * filename.hashCode() + bytes.contentHashCode()
    }

    /**
     * 读一个用户选中的 URI。
     *
     * @throws AttachmentException 读不了 / 不支持 / 太大（message 直接展示给用户）
     */
    fun read(context: Context, uri: Uri): Picked {
        val resolver = context.contentResolver
        var name = ""
        var size = -1L
        try {
            resolver.query(uri, null, null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    val ni = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (ni >= 0 && !c.isNull(ni)) name = c.getString(ni).orEmpty()
                    val si = c.getColumnIndex(OpenableColumns.SIZE)
                    if (si >= 0 && !c.isNull(si)) size = c.getLong(si)
                }
            }
        } catch (e: Exception) {
            // provider 不认 DISPLAY_NAME 也没关系，下面还有扩展名和兜底名
        }
        val safeName = name.trim().ifBlank { uri.lastPathSegment?.substringAfterLast('/').orEmpty() }

        val ext = ("." + safeName.substringAfterLast('.', "").lowercase()).takeIf { safeName.contains('.') } ?: ""
        if (ext in LEGACY_EXT) {
            throw AttachmentException(
                "这是旧版 Excel（.xls）格式，读不了。请在 Excel/WPS 里「另存为」成 .xlsx 或 .csv 再传。",
            )
        }
        if (!safeName.isBlank() && ext !in ALLOWED_EXT) {
            throw AttachmentException(
                "只能传 Excel（.xlsx）或文本表格（.csv / .tsv / .txt），这个是「${ext.ifBlank { "无扩展名" }}」。",
            )
        }
        if (size > MAX_BYTES) {
            throw AttachmentException("这个文件有 ${size / 1024 / 1024}MB，超过 ${MAX_BYTES / 1024 / 1024}MB 的上限。请先删掉用不到的列/行，或拆成几个文件。")
        }

        val bytes = try {
            resolver.openInputStream(uri)?.use { it.readBytes() }
        } catch (e: Exception) {
            null
        } ?: throw AttachmentException("读不到这个文件（可能是云盘文件还没下载好，或者没有读取权限）。")

        if (bytes.isEmpty()) throw AttachmentException("这个文件是空的。")
        if (bytes.size > MAX_BYTES) {
            throw AttachmentException("这个文件超过 ${MAX_BYTES / 1024 / 1024}MB，传不了。请先拆小。")
        }

        val mime = resolver.getType(uri)?.takeIf { it.isNotBlank() } ?: guessMime(ext)
        return Picked(filename = safeName.ifBlank { "附件$ext" }, mime = mime, bytes = bytes)
    }

    /** provider 不给 MIME 时按扩展名兜一个（后端只按扩展名分派，MIME 只影响 multipart 头）。 */
    private fun guessMime(ext: String): String = when (ext) {
        ".xlsx", ".xlsm" -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ".csv" -> "text/csv"
        ".tsv" -> "text/tab-separated-values"
        ".txt" -> "text/plain"
        ".jpg", ".jpeg" -> "image/jpeg"
        ".png" -> "image/png"
        ".webp" -> "image/webp"
        else -> "application/octet-stream"
    }

    // ------------------------------------------------------------------ 图片

    /** 图片长边压到这个像素数再上传。 */
    private const val IMAGE_MAX_SIDE = 1280

    /** JPEG 质量。80 是"文字照片还能看清"和"体积能接受"的折中。 */
    private const val IMAGE_QUALITY = 80

    /** 压完之后的字节上限（base64 会再涨 1/3，所以这里不能放太宽）。 */
    private const val IMAGE_MAX_BYTES = 900 * 1024

    fun isImageMime(mime: String?): Boolean = mime?.trim()?.lowercase()?.startsWith("image/") == true

    /**
     * 从 URI 的末段猜它是不是图片。
     *
     * 为什么需要：不少 provider（尤其是"最近文件"和第三方网盘）返回的 MIME 是
     * `application/octet-stream` 甚至 null，只看 MIME 会把一张照片当成表格去传，
     * 然后后端回一句"读不了这种文件"——用户明明选的是照片。
     */
    fun looksLikeImage(pathOrName: String?): Boolean {
        val n = pathOrName?.trim()?.lowercase().orEmpty()
        return IMAGE_EXT.any { n.endsWith(it) }
    }

    private val IMAGE_EXT = setOf(".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif", ".gif")

    /** 用户看到的文件名（挑不到就给空串，调用方自己兜底命名）。 */
    fun displayName(context: Context, uri: Uri): String {
        val resolver = context.contentResolver
        return try {
            resolver.query(uri, null, null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    val ni = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (ni >= 0 && !c.isNull(ni)) c.getString(ni).orEmpty().trim() else ""
                } else {
                    ""
                }
            } ?: ""
        } catch (e: Exception) {
            ""
        }
    }

    /**
     * 读一张**图片**并压缩到适合发给模型的尺寸，返回 data URL。
     *
     * ### 为什么要压（三个理由，缺一个都不行）
     * 1. **钱**：多模态是按像素算 token 的，原图 4000×3000 一张就是上千 token，
     *    而且工具循环的**每一轮**都会重发一次；
     * 2. **快**：几 MB 的 base64 走一次工具循环要传好几遍，用户会以为卡死；
     * 3. **够用**：模型看的是"图里有什么"，1280 长边对单据/表格/商品照片都足够。
     *
     * 压缩走 `inSampleSize` 两遍解码（第一遍只读尺寸），比先整张读进内存再缩放省得多——
     * 一张 4000×3000 的图整张解码是 48MB 位图，低端机直接 OOM。
     *
     * @throws AttachmentException 读不了 / 解不出来（message 直接展示给用户）
     */
    fun readImage(context: Context, uri: Uri): String {
        val resolver = context.contentResolver
        val bounds = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
        try {
            resolver.openInputStream(uri)?.use { android.graphics.BitmapFactory.decodeStream(it, null, bounds) }
        } catch (e: Exception) {
            throw AttachmentException("读不到这张图片（可能是云盘文件还没下载好，或者没有读取权限）。")
        }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
            throw AttachmentException("这个文件不是能打开的图片。")
        }
        val opts = android.graphics.BitmapFactory.Options().apply {
            inSampleSize = sampleSize(bounds.outWidth, bounds.outHeight, IMAGE_MAX_SIDE)
            inPreferredConfig = android.graphics.Bitmap.Config.ARGB_8888
        }
        val decoded = try {
            resolver.openInputStream(uri)?.use { android.graphics.BitmapFactory.decodeStream(it, null, opts) }
        } catch (e: Exception) {
            null
        } ?: throw AttachmentException("这张图片打不开（可能已损坏）。")

        val scaled = scaleDown(decoded, IMAGE_MAX_SIDE)
        val bytes = java.io.ByteArrayOutputStream()
        scaled.compress(android.graphics.Bitmap.CompressFormat.JPEG, IMAGE_QUALITY, bytes)
        if (scaled !== decoded) scaled.recycle()
        decoded.recycle()
        var raw = bytes.toByteArray()
        // 极端情况下（大图 + 复杂纹理）质量 80 仍可能超过上限 → 再降一档质量重压一次
        if (raw.size > IMAGE_MAX_BYTES) {
            val again = java.io.ByteArrayOutputStream()
            val bmp = android.graphics.BitmapFactory.decodeByteArray(raw, 0, raw.size)
            bmp?.compress(android.graphics.Bitmap.CompressFormat.JPEG, 60, again)
            bmp?.recycle()
            if (again.size() in 1 until raw.size) raw = again.toByteArray()
        }
        if (raw.size > IMAGE_MAX_BYTES * 2) {
            throw AttachmentException("这张图片压完还是太大，换一张小一点的，或者先裁剪一下。")
        }
        val b64 = android.util.Base64.encodeToString(raw, android.util.Base64.NO_WRAP)
        return "data:image/jpeg;base64,$b64"
    }

    /** 计算 [inSampleSize]：2 的幂，保证压完长边不小于 [target]。 */
    private fun sampleSize(w: Int, h: Int, target: Int): Int {
        var sample = 1
        var longSide = maxOf(w, h)
        while (longSide / 2 >= target) {
            longSide /= 2
            sample *= 2
        }
        return sample
    }

    private fun scaleDown(src: android.graphics.Bitmap, target: Int): android.graphics.Bitmap {
        val long = maxOf(src.width, src.height)
        if (long <= target) return src
        val ratio = target.toFloat() / long
        return android.graphics.Bitmap.createScaledBitmap(
            src,
            (src.width * ratio).toInt().coerceAtLeast(1),
            (src.height * ratio).toInt().coerceAtLeast(1),
            true,
        )
    }
}
