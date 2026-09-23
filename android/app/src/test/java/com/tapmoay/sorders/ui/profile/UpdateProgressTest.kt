package com.tapmoay.sorders.ui.profile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「检查更新」下载文案的纯逻辑测试。
 *
 * 为什么值得测：这些数字是用户判断"要不要继续等"的唯一依据。
 * 显示 0 KB/s、负数剩余时间、或者把 40MB 写成 "41943040"，都会让用户以为程序坏了。
 */
class UpdateProgressTest {

    @Test
    fun humanSizeAlwaysCarriesUnit() {
        assertEquals("512 B", UpdateProgress.humanSize(512))
        assertEquals("1 KB", UpdateProgress.humanSize(1024))
        assertEquals("860 KB", UpdateProgress.humanSize(880_640))
        assertEquals("1.0 MB", UpdateProgress.humanSize(1_048_576))
        assertEquals("51.2 MB", UpdateProgress.humanSize(53_687_091))
        assertEquals("1.00 GB", UpdateProgress.humanSize(1_073_741_824))
        // 任何情况下都不允许出现裸数字（用户没法判断单位）
        assertTrue(UpdateProgress.humanSize(12_345_678).contains("MB"))
    }

    @Test
    fun speedIsHiddenWhenUnknownInsteadOfShowingZero() {
        assertEquals("", UpdateProgress.speedText(0.0))
        assertEquals("", UpdateProgress.speedText(-1.0))
        assertEquals("860 KB/s", UpdateProgress.speedText(880_640.0))
        assertEquals("1.2 MB/s", UpdateProgress.speedText(1_258_291.0))
    }

    @Test
    fun etaUsesReadableUnits() {
        assertEquals("", UpdateProgress.etaText(1000, 0.0))      // 速度未知 → 不猜
        assertEquals("", UpdateProgress.etaText(0, 1024.0))       // 已下完 → 不显示
        assertEquals("还剩不到 1 秒", UpdateProgress.etaText(100, 1024.0))
        assertEquals("还剩 28 秒", UpdateProgress.etaText(28 * 1024, 1024.0))
        assertEquals("还剩 2 分 0 秒", UpdateProgress.etaText(120 * 1024, 1024.0))
        assertEquals("还剩 1 小时 5 分", UpdateProgress.etaText(3900 * 1024, 1024.0))
    }

    @Test
    fun detailLineShowsSpeedBytesAndEta() {
        val line = UpdateProgress.detailLine(
            done = 19_293_798,          // 18.4 MB
            total = 53_687_091,         // 51.2 MB
            bytesPerSec = 1_258_291.0,  // 1.2 MB/s
        )
        assertTrue(line, line.contains("1.2 MB/s"))
        assertTrue(line, line.contains("已下 18.4 MB / 51.2 MB"))
        assertTrue(line, line.contains("还剩"))
        // 三段之间用 · 分隔，横着读就是一句话
        assertEquals(3, line.split(" · ").size)
    }

    @Test
    fun detailLineWithoutContentLengthStillSaysHowMuchDownloaded() {
        val line = UpdateProgress.detailLine(done = 5_242_880, total = -1, bytesPerSec = 0.0)
        assertEquals("已下 5.0 MB", line)
    }

    @Test
    fun stalledHintOnlyAfterRealSilence() {
        assertNull(UpdateProgress.stalledHint(0))
        assertNull(UpdateProgress.stalledHint(29))
        assertEquals("已 45 秒没有新数据，网络可能断了", UpdateProgress.stalledHint(45))
    }

    /**
     * 版本号显示口径（2026-09-23 用户报障）。
     *
     * 用户原话：「他一直显示啊？**重安装当前版本**，但是你已经推送回新版本了，可**版本号的问题**嘛，
     * **0.2.3 版本号并没有发生改变**啊，因为上个版本号也是这样子的」。
     *
     * ⚠️ 关键那条是「**同一天打的两个包**」：产品版本都是 `0.2.3`，只有构建号不同 ——
     * 这正是原来两行看着一模一样、被读成"重装当前版本"的场景。
     */
    @Test
    fun versionLabelCarriesTheBuildNumber() {
        assertEquals("0.2.4 · 2026092302", UpdateProgress.versionLabel("0.2.4", 2026092302))
        // ⚠️ 同一个产品版本的两个包：**只有构建号不同**，不显示它就分不出来
        assertEquals("0.2.3 · 2026092302", UpdateProgress.versionLabel("0.2.3", 2026092302))
        assertEquals("0.2.3 · 2026092204", UpdateProgress.versionLabel("0.2.3", 2026092204))
    }

    @Test
    fun versionLabelNeverInventsAVersionOrAZeroBuild() {
        // 服务端没写 version（老后端/半截 version.json）→ 兜一句人话，⛔ 不是拼出半个 "v"
        assertEquals("未知版本", UpdateProgress.versionLabel(null, 0))
        assertEquals("未知版本", UpdateProgress.versionLabel("   ", null))
        // 老后端没有 versionCode → **不拼 0**（"新版本是第 0 号"比不显示更糟）
        assertEquals("0.2.4", UpdateProgress.versionLabel("0.2.4", null))
        assertEquals("0.2.4", UpdateProgress.versionLabel("0.2.4", 0))
        assertEquals("0.2.4", UpdateProgress.versionLabel("0.2.4", -1))
        // 两端空白归一，别显示成 "0.2.4  · 2026092302"
        assertEquals("0.2.4 · 2026092302", UpdateProgress.versionLabel(" 0.2.4 ", 2026092302))
    }
}
