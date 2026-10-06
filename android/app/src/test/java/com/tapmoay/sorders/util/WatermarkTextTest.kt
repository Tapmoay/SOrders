package com.tapmoay.sorders.util

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * `WatermarkText.lines`：**照片水印上到底画哪几行**（2026-10-06，台账 L-22）。
 *
 * ## 为什么这个文件必须存在
 * 用户要的是「补上去的照片要看得出来是补过的」—— 落地形态就是水印**多一行字**。
 * 而真正画水印的 `Watermark.drawWatermark` 要真 Bitmap、真 Canvas，在 JVM 单测里跑不了；
 * 所以「画哪几行」被抽成纯函数放在这里，测试钉住它 —— 否则这件事就只剩肉眼验收。
 *
 * ⚠️ 两个方向都会出事故，两边都要钉：
 * - 少一行 ⇒ 补拍的照片冒充当场拍的（**留痕失真**，比难看严重）；
 * - 多一行 ⇒ **当场拍的送达照也带上「补拍」字样**，等于把每一单都标成补录的。
 */
class WatermarkTextTest {

    @Test
    fun `当场拍的只有两行_时间加地点`() {
        // 「拍照送达」那条链路的行为：与加这个功能之前**逐字一致**
        assertEquals(
            listOf("2026-10-06 12:30:00", "杭州市余杭区仓前街道 1 号"),
            WatermarkText.lines("2026-10-06 12:30:00", "杭州市余杭区仓前街道 1 号")
        )
    }

    @Test
    fun `补拍那张多第三行_补拍标识`() {
        val ls = WatermarkText.lines("2026-10-06 12:30:00", "杭州市余杭区仓前街道 1 号", WatermarkText.MAKEUP_TAG)
        assertEquals(3, ls.size)
        assertEquals(WatermarkText.MAKEUP_TAG, ls[2])
    }

    @Test
    fun `补拍标识的文案钉在这里_改字要改这条判据`() {
        // 用户只说了「就是说补过的照片就可以了」，具体用词是我们自决的 —— 钉住它，
        // 免得哪天被顺手改成别的字样，界面上与文档里又对不上。
        assertEquals("补拍 · 事后补录", WatermarkText.MAKEUP_TAG)
    }

    @Test
    fun `地点取不到时兜底送达地点`() {
        assertEquals(listOf("2026-10-06 12:30:00", "送达地点"), WatermarkText.lines("2026-10-06 12:30:00", ""))
        // 全空白也算取不到（后端给过全空格的地址）
        assertEquals(listOf("2026-10-06 12:30:00", "送达地点"), WatermarkText.lines("2026-10-06 12:30:00", "   "))
        // 补拍那张的第三行不受兜底影响
        assertEquals(
            listOf("2026-10-06 12:30:00", "送达地点", WatermarkText.MAKEUP_TAG),
            WatermarkText.lines("2026-10-06 12:30:00", "", WatermarkText.MAKEUP_TAG)
        )
    }

    @Test
    fun `地点太长截断到六十个字`() {
        val long = "长".repeat(100)
        val ls = WatermarkText.lines("2026-10-06 12:30:00", long)
        assertEquals(60, ls[1].length)
        assertEquals("长".repeat(60), ls[1])
    }

    @Test
    fun `标识传空串等于没传_不会被误标成补拍`() {
        assertEquals(2, WatermarkText.lines("2026-10-06 12:30:00", "某地", "").size)
        assertEquals(2, WatermarkText.lines("2026-10-06 12:30:00", "某地", "   ").size)
        assertEquals(2, WatermarkText.lines("2026-10-06 12:30:00", "某地", null).size)
    }

    @Test
    fun `补拍标识永远在最后一行`() {
        // 地点是个超长串时也不许把标识挤到中间（绘制顺序就是列表顺序）
        val ls = WatermarkText.lines("2026-10-06 12:30:00", "长".repeat(200), WatermarkText.MAKEUP_TAG)
        assertEquals(WatermarkText.MAKEUP_TAG, ls.last())
        assertEquals(3, ls.size)
    }
}
