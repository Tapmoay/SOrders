package com.tapmoay.sorders.ui.theme

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.math.pow

/**
 * AI 聊天页那个「像微信的绿」（台账 L-66 / CHG-0104）的判据。
 *
 * 用户口径（ref `m04856`，逐字）：
 * 「你别帮我那个 a i 对话框改的颜色改其他颜色了，它的主颜色还是绿色……它就像微信一样。
 *  为什么要绿色呢？因为我希望让使用……跟微信一样亲切啊，因为我们微信是大家经常用的」。
 *
 * 为什么这几条必须有机器的判据（都是"坏了不报错"的那一类）：
 * 1. **白字读不清**这件事不会崩、不会报错，界面照样能点 —— 只是老年用户看不清。
 *    而绿在 sRGB 里亮度权重最高（0.7152），**稍微调亮一点白字就掉到 4.5 以下**，
 *    改色的人肉眼看不出来。所以要真的算一遍对比度。
 * 2. **`AiAccent` 被写回 `Color(ThemeGreen)`** 也不会报错 ——
 *    这正是本单的病根：CHG-0091 把 AI 页收敛到 `ThemeGreen`，
 *    CHG-0101 换主色时它**跟着全 App 主操作色一起变成了红棕**，用户才来说这一句。
 * 3. **两档被合并成一个**（有人嫌麻烦）也不会报错，但那就必然有一处要么白字读不清、
 *    要么强调色当图标用太淡。第 ④ 条就是钉住"合并之后必然出事"这件事的。
 *
 * ⚠️ 与 `_tools/qa/_check_ai_chat_green.py` 的分工：那边守**绑定关系**
 *    （哪个文件读哪个 token、旧引用有没有残留、主操作色有没有被误伤），
 *    这边守**取色本身**（值对不对、压白字够不够、是不是个绿）。两边都要看。
 */
class AiChatGreenTest {

    // ------------------------------------------------------------ 工具（与 _check_ai_chat_green.py 同一套公式）

    private fun ch(c: Long, sh: Int): Double {
        val v = ((c shr sh) and 0xFF) / 255.0
        return if (v <= 0.04045) v / 12.92 else ((v + 0.055) / 1.055).pow(2.4)
    }

    /** WCAG 相对亮度。 */
    private fun lum(c: Long): Double = 0.2126 * ch(c, 16) + 0.7152 * ch(c, 8) + 0.0722 * ch(c, 0)

    /** 对比度（1~21）。 */
    private fun ratio(a: Long, b: Long): Double {
        val la = lum(a)
        val lb = lum(b)
        return (maxOf(la, lb) + 0.05) / (minOf(la, lb) + 0.05)
    }

    /** sRGB -> CIE L*a*b*（D65）。 */
    private fun lab(c: Long): Triple<Double, Double, Double> {
        val r = ch(c, 16)
        val g = ch(c, 8)
        val b = ch(c, 0)
        val x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
        val y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) / 1.00000
        val z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883
        fun f(t: Double) = if (t > 216.0 / 24389.0) t.pow(1.0 / 3.0) else (841.0 / 108.0) * t + 4.0 / 29.0
        val fx = f(x)
        val fy = f(y)
        val fz = f(z)
        return Triple(116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))
    }

    /** (L*, C*, h°)。 */
    private fun lch(c: Long): Triple<Double, Double, Double> {
        val (l, a, b) = lab(c)
        return Triple(l, hypot(a, b), (Math.toDegrees(atan2(b, a)) + 360.0) % 360.0)
    }

    private fun hueDelta(h1: Double, h2: Double): Double {
        val d = abs(h1 - h2) % 360.0
        return minOf(d, 360.0 - d)
    }

    private fun hex(c: Long) = "#" + (c and 0xFFFFFF).toString(16).uppercase().padStart(6, '0')

    /**
     * `Color` -> 裸 ARGB（`Long`）。
     *
     * ⚠️ 不走 `Color.toArgb()`：那是 `androidx.compose.ui.graphics` 的**平台实现**，
     *    在纯 JVM 单测里有踩到 `android.graphics` 的风险。这里只用 `red/green/blue`
     *    三个 float 自己拼 —— 本仓库的语义色 token 本来就都是裸 ARGB，
     *    这个函数只是把 `SurfaceLight` 那种 `Color` 拉回同一个口径。
     */
    private fun argb(c: androidx.compose.ui.graphics.Color): Long {
        fun q(v: Float) = (v.coerceIn(0f, 1f) * 255f + 0.5f).toLong()
        return (0xFFL shl 24) or (q(c.red) shl 16) or (q(c.green) shl 8) or q(c.blue)
    }

    /** 微信品牌绿 —— 用户点名的那一家。⚠️ 只用来比**色相**，⛔ 不用来比值（它自己没过 AA）。 */
    private val WeChatGreen = 0xFF00C939L

    private val White = 0xFFFFFFFFL

    // ------------------------------------------------------------ 判据

    @Test
    fun `强调色就是定稿那个绿 4B8C5E，不许被谁调亮调暗`() {
        // 定稿依据：h=149.9°（微信是 148.8°，几乎同色相）、L*=53.0、当图标压在页面底上 3.73:1。
        assertEquals("AI 页强调色变了（定稿是 #4B8C5E）", 0xFF4B8C5EL, AiChatGreen)
    }

    @Test
    fun `实心档就是定稿那个深绿 3D734D`() {
        // 白字 5.59:1 —— 这一档存在的**全部**理由就是这句话。
        assertEquals("AI 页实心档变了（定稿是 #3D734D）", 0xFF3D734DL, AiChatGreenDeep)
    }

    @Test
    fun `白字压实心档过 AA 的 4_5`() {
        val r = ratio(White, AiChatGreenDeep)
        assertTrue(
            "白字压在 ${hex(AiChatGreenDeep)} 上只有 %.2f:1，读不清（要 >=4.5）".format(r),
            r >= 4.5,
        )
    }

    @Test
    fun `白字压强调档过不了 AA —— 所以两档不能合并成一个`() {
        val r = ratio(White, AiChatGreen)
        assertTrue(
            "白字压在 ${hex(AiChatGreen)} 上是 %.2f:1，居然过了 AA —— ".format(r) +
                "那两档可以合并，Color.kt 里那段「为什么是两个」要重写",
            r < 4.5,
        )
        // 反过来也钉一下：它当"图形"用是够的（否则这个强调色本身就不合格）
        assertTrue(
            "白字压在 ${hex(AiChatGreen)} 上只有 %.2f:1，连图形都够呛".format(r),
            r >= 3.0,
        )
    }

    @Test
    fun `强调档当图标用，压在白卡与页面底上都过 3_1`() {
        // 白卡 = SurfaceLight，页面底 = BackgroundLight。这两个是 AI 页里最常被压的两层。
        for ((name, bg) in listOf("白卡" to argb(SurfaceLight), "页面底" to argb(BackgroundLight))) {
            val r = ratio(AiChatGreen, bg)
            assertTrue(
                "强调色 ${hex(AiChatGreen)} 压在$name ${hex(bg)} 上只有 %.2f:1（图形要 >=3.0）".format(r),
                r >= 3.0,
            )
        }
    }

    @Test
    fun `强调档是个绿，而且跟微信品牌绿同一个色相家族`() {
        val (l, c, h) = lch(AiChatGreen)
        val (_, _, hw) = lch(WeChatGreen)
        assertTrue(
            "强调色 ${hex(AiChatGreen)} 的色相是 %.1f°，不是个绿".format(h),
            h in 100.0..180.0,
        )
        assertTrue(
            "强调色色相 %.1f° 与微信品牌绿 %.1f° 差了 %.1f°（要 <=12）".format(h, hw, hueDelta(h, hw)),
            hueDelta(h, hw) <= 12.0,
        )
        // 顺便钉住那条论证：微信绿自己没过 AA，所以本单**不能照抄它的值**。
        val wechat = ratio(White, WeChatGreen)
        assertTrue(
            "微信品牌绿白字居然有 %.2f:1 —— Color.kt 里那段论证要重写".format(wechat),
            wechat < 4.5,
        )
        assertTrue("强调色的明度算出来是 %.1f，不对劲".format(l), l in 40.0..60.0)
        assertTrue("强调色的彩度算出来是 %.1f，不对劲".format(c), c in 25.0..50.0)
    }

    @Test
    fun `两档的明度差在 5 到 16 之间（既分得开、又不像是两个色）`() {
        val d = abs(lab(AiChatGreenDeep).first - lab(AiChatGreen).first)
        assertTrue(
            "两档明度只差 %.1f —— 界面上看不出主次（「三颗图标是入口、发送键是主行动」就没了）".format(d),
            d >= 5.0,
        )
        assertTrue(
            "两档明度差到 %.1f —— 看着像两个不相关的颜色，不像同一个绿的两个档".format(d),
            d <= 16.0,
        )
        // Deep 必须是更暗的那一档
        assertTrue("实心档比强调档还亮 —— 「深一档」写反了", lum(AiChatGreenDeep) < lum(AiChatGreen))
    }
}
