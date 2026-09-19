package com.tapmoay.sorders.ui.profile

import java.util.Locale

/**
 * 「检查更新」下载过程中的文案与进度计算——**纯函数，不碰任何 Android API**，所以能进 JVM 单测。
 *
 * 为什么单独拎出来：这段逻辑以前揉在下载循环里，循环每读 64KB 就
 * `withContext(Dispatchers.Main)` 往主线程跑一趟（40MB 的包 = 600 多次往返，
 * 主线程还在同时重组进度条），既拖慢下载又完全没法测。
 * 现在循环只负责读字节并调用这里生成文案。
 *
 * 设计取向：**拿不到的数字就不显示**。速度未知时宁可只写「已下 18.4 MB」，
 * 也不要显示「-- KB/s」或一个瞎猜的剩余时间——用户看到假数字会以为程序坏了。
 */
object UpdateProgress {

    /** 带单位的人话体积：1.2 MB / 860 KB。绝不出现裸数字（没人知道是字节还是 KB）。 */
    fun humanSize(bytes: Long): String = when {
        bytes >= 1024L * 1024L * 1024L -> String.format(Locale.US, "%.2f GB", bytes / 1073741824.0)
        bytes >= 1024L * 1024L -> String.format(Locale.US, "%.1f MB", bytes / 1048576.0)
        bytes >= 1024L -> String.format(Locale.US, "%.0f KB", bytes / 1024.0)
        else -> "$bytes B"
    }

    /** 速度：1.2 MB/s / 860 KB/s。非正值返回空串（= 不显示这一项）。 */
    fun speedText(bytesPerSec: Double): String = when {
        bytesPerSec <= 0.0 -> ""
        bytesPerSec >= 1024.0 * 1024.0 -> String.format(Locale.US, "%.1f MB/s", bytesPerSec / 1048576.0)
        bytesPerSec >= 1024.0 -> String.format(Locale.US, "%.0f KB/s", bytesPerSec / 1024.0)
        else -> String.format(Locale.US, "%.0f B/s", bytesPerSec)
    }

    /** 剩余时间：还剩 28 秒 / 还剩 1 分 20 秒 / 还剩 1 小时 5 分。速度未知时返回空串。 */
    fun etaText(remainBytes: Long, bytesPerSec: Double): String {
        if (bytesPerSec <= 0.0 || remainBytes <= 0) return ""
        val sec = (remainBytes / bytesPerSec).toLong()
        return when {
            sec < 1 -> "还剩不到 1 秒"
            sec < 60 -> "还剩 $sec 秒"
            sec < 3600 -> "还剩 ${sec / 60} 分 ${sec % 60} 秒"
            else -> "还剩 ${sec / 3600} 小时 ${(sec % 3600) / 60} 分"
        }
    }

    /**
     * 下载中那一行字：`1.2 MB/s · 已下 18.4 MB / 51.2 MB · 还剩 28 秒`。
     * 服务器没给 Content-Length（total <= 0）时就只说已下多少，不显示百分比也不显示剩余时间。
     */
    fun detailLine(done: Long, total: Long, bytesPerSec: Double): String {
        val parts = ArrayList<String>(3)
        val sp = speedText(bytesPerSec)
        if (sp.isNotEmpty()) parts += sp
        parts += if (total > 0) "已下 ${humanSize(done)} / ${humanSize(total)}" else "已下 ${humanSize(done)}"
        val eta = etaText(total - done, bytesPerSec)
        if (eta.isNotEmpty()) parts += eta
        return parts.joinToString(" · ")
    }

    /** 卡住了就说卡住了：进度条停在 87% 一动不动时，给一句解释而不是让用户干等。 */
    fun stalledHint(secondsSinceProgress: Long): String? =
        if (secondsSinceProgress >= 30) "已 $secondsSinceProgress 秒没有新数据，网络可能断了" else null
}
