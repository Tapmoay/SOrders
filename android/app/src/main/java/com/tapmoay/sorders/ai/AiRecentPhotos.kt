package com.tapmoay.sorders.ai

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import androidx.core.content.ContextCompat

/**
 * 最近拍的照片（**只读**，用来把"刚拍的那张单子"直接摆在输入框上方）。
 *
 * ### 为什么要有它（用户口径 2026-09-17）
 * 用户拿别的 App 的输入区做参照：「中间那些图片全是相册的图片已经列出来了，然后在下面再是下面 3 个」。
 * 也就是**先看见、再选**——而不是先点「相册」、等系统选择器弹出来、再在一堆图里找。
 * 对"刚拍完一张送货单，想让 AI 看一眼"这个最高频的场景，少两步。
 *
 * ### 和系统照片选择器的关系（不是替代，是并排）
 * 系统选择器（`PickVisualMedia`）**不需要任何权限**，隐私上最干净，所以「相册」那个按钮保留。
 * 这里读 MediaStore 只是为了"把最近的几张摆出来"，因此：
 * - **拿不到权限就返回空表**，面板照样显示「拍照 / 相册 / 文件」三个入口，功能一个都不少；
 * - 只读 `_ID` 一列、只取最近 [LIMIT] 张，不碰其它字段，也不写任何东西；
 * - Android 14+ 用户只给"部分照片"时，系统本来也只把选中的那些放进查询结果——
 *   那不是我们的 bug，是系统给的视图，照实显示即可。
 */
internal object AiRecentPhotos {

    /** 面板里最多摆几张。够"看见刚才那张"就行，摆满一屏反而要滑半天。 */
    const val LIMIT = 18

    /**
     * 该申请的权限名。
     *
     * Android 13（TIRAMISU）起读图片走 `READ_MEDIA_IMAGES`；更低版本仍是 `READ_EXTERNAL_STORAGE`
     * （清单里那条带 `maxSdkVersion="32"` 的就是给它用的）。
     */
    fun permission(): String =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            Manifest.permission.READ_MEDIA_IMAGES
        } else {
            Manifest.permission.READ_EXTERNAL_STORAGE
        }

    /** 现在有没有权限。**没有就什么都不做**——不要在这里弹框，弹框是界面的事。 */
    fun granted(context: Context): Boolean = try {
        ContextCompat.checkSelfPermission(context, permission()) == PackageManager.PERMISSION_GRANTED
    } catch (e: Exception) {
        false
    }

    /**
     * 最近的照片，新的在前。
     *
     * 全程不抛异常：相册读不到**不是致命错误**（面板里还有三个入口能干活），
     * 让它把整个输入区搞崩才是最糟的结果。
     */
    fun recent(context: Context, limit: Int = LIMIT): List<Uri> {
        if (!granted(context)) return emptyList()
        val out = ArrayList<Uri>(limit)
        try {
            // 排序交给系统（DATE_ADDED DESC），我们取够 limit 条就停——
            // Cursor 是惰性的，不会真的把几万张都读出来。
            context.contentResolver.query(
                MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                arrayOf(MediaStore.Images.Media._ID),
                null,
                null,
                "${MediaStore.Images.Media.DATE_ADDED} DESC",
            )?.use { c ->
                val idCol = c.getColumnIndexOrThrow(MediaStore.Images.Media._ID)
                while (out.size < limit && c.moveToNext()) {
                    out += Uri.withAppendedPath(
                        MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                        c.getLong(idCol).toString(),
                    )
                }
            }
        } catch (e: Exception) {
            return emptyList()
        }
        return out
    }
}
