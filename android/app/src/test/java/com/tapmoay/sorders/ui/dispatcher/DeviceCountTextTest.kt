package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.DeviceBindingDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

/**
 * 「已绑 N/3 台」这套文案（FEAT-0018）。
 *
 * 这一单为什么值得测：名额是派单员判断"这个账号还能不能在新手机上登录"的**唯一线索**，
 * 而它有两种坏法都**不会报错**：① 把"还没拉到"画成 0 台（看着像名额空着，其实是被 403 拦掉的）；
 * ② 把已失效的历史行也算进名额（解冻完还显示 3/3，用户以为解冻没生效、会反复点）。
 * 两句文案的差别就是这两种坏法，所以逐字钉住。
 */
class DeviceCountTextTest {

    private fun binding(
        id: Long = 1,
        deviceId: String = "0123456789abcdef",
        boundAt: String? = null,
        lastSeenAt: String? = null,
        source: String? = null,
        active: Boolean = true,
    ) = DeviceBindingDto(
        id = id,
        deviceId = deviceId,
        boundAt = boundAt,
        lastSeenAt = lastSeenAt,
        source = source,
        active = active,
    )

    @Test
    fun `还没拉到时不许画成 0 台`() {
        val text = deviceCountText(UNKNOWN_DEVICE_COUNT)
        assertEquals("已绑 --/3 台", text)
        assertFalse("画成 0 台会被读成名额空着：$text", text.contains("0/3"))
        assertFalse("也不许说满了：$text", text.contains("已满"))
    }

    @Test
    fun `没满就报台数`() {
        assertEquals("已绑 0/3 台", deviceCountText(0))
        assertEquals("已绑 1/3 台", deviceCountText(1))
        assertEquals("已绑 2/3 台", deviceCountText(2))
    }

    @Test
    fun `满了要把后果一起说清（第 4 台等最旧那台失效）`() {
        val text = deviceCountText(MAX_DEVICES)
        assertTrue("要报出台数：$text", text.contains("3/3"))
        assertTrue("要说出第 4 台怎么办：$text", text.contains("第 4 台"))
        assertTrue("要说清是等最旧那台失效：$text", text.contains("失效"))
    }

    @Test
    fun `超过上限时照实报数（后端放宽也不许把台数藏起来）`() {
        // 客户端这一份 MAX_DEVICES 只用来**画文案**（不拿它拦请求），所以后端真放宽到 4 台时，
        // 这里必须照实画"4/3 + 已满"——把台数截成 3 会让派单员看到的数字与后端对不上。
        val text = deviceCountText(MAX_DEVICES + 1)
        assertTrue("$text", text.contains("已满"))
        assertTrue("台数不许被截成 3：$text", text.contains("4/3"))
    }

    @Test
    fun `名额只算在用的（历史行不占名额）`() {
        val rows = listOf(
            binding(id = 1, active = true),
            binding(id = 2, active = true),
            binding(id = 3, active = false),
            binding(id = 4, active = false),
        )
        assertEquals(2, activeDeviceCount(rows))
        assertEquals("已绑 2/3 台", deviceCountText(activeDeviceCount(rows)))
    }

    @Test
    fun `没拉过与拉到空是两件事`() {
        assertEquals(UNKNOWN_DEVICE_COUNT, activeDeviceCount(null))
        assertEquals("已绑 --/3 台", deviceCountText(activeDeviceCount(null)))
        assertEquals("拉到空 = 真的 0 台", 0, activeDeviceCount(emptyList()))
        assertEquals("已绑 0/3 台", deviceCountText(activeDeviceCount(emptyList())))
    }

    @Test
    fun `解冻完那一台不再占名额（台数会自己降下来）`() {
        val before = listOf(binding(id = 1), binding(id = 2), binding(id = 3))
        assertEquals("已绑 3/3 台（已满，第 4 台要等最旧那台失效）", deviceCountText(activeDeviceCount(before)))
        val after = listOf(binding(id = 1), binding(id = 2), binding(id = 3, active = false))
        assertEquals("已绑 2/3 台", deviceCountText(activeDeviceCount(after)))
    }

    @Test
    fun `设备短号取尾 6 位（同一账号下足够对上号）`() {
        assertEquals("abcdef", deviceShortId(binding(deviceId = "0123456789abcdef")))
        assertEquals("不够 6 位就整串给出来", "123456", deviceShortId(binding(deviceId = "123456", id = 9)))
    }

    @Test
    fun `设备号是空串时回落成井号加内部 id（不许画成空白的设备）`() {
        assertEquals("#7", deviceShortId(binding(id = 7, deviceId = "")))
    }

    @Test
    fun `设备标题带来源，且来源原样显示不翻译`() {
        assertEquals("设备 …abcdef（login）", deviceTitle(binding(source = "login")))
        assertEquals("设备 …abcdef", deviceTitle(binding(source = null)))
        assertEquals("空来源等于没有来源", "设备 …abcdef", deviceTitle(binding(source = "  ")))
    }

    @Test
    fun `绑定时间与最后活跃按传入时区换算（naive UTC 不小 8 小时）`() {
        val b = binding(boundAt = "2026-10-11T01:30:00", lastSeenAt = "2026-10-11T02:00:00")
        assertEquals(
            "绑定 2026-10-11 09:30 · 最近 2026-10-11 10:00",
            deviceMeta(b, ZoneId.of("Asia/Shanghai")),
        )
        assertEquals(
            "绑定 2026-10-11 01:30 · 最近 2026-10-11 02:00",
            deviceMeta(b, ZoneId.of("UTC")),
        )
    }

    @Test
    fun `从没活跃过的设备写从未（不是留空）`() {
        val b = binding(boundAt = "2026-10-11T01:30:00", lastSeenAt = null)
        assertEquals("绑定 2026-10-11 09:30 · 最近 从未", deviceMeta(b, ZoneId.of("Asia/Shanghai")))
    }

    @Test
    fun `连绑定时间都没给时画破折号，不崩也不留空`() {
        val b = binding(boundAt = null, lastSeenAt = null)
        assertEquals("绑定 — · 最近 从未", deviceMeta(b, ZoneId.of("Asia/Shanghai")))
    }
}