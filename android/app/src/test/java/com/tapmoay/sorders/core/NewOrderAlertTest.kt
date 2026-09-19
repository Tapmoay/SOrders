package com.tapmoay.sorders.core

import com.tapmoay.sorders.ui.nav.Role
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「来单了」判定逻辑的单测。
 *
 * 这些断言存在的理由只有一个：**司机端最不能出的错是"这次没响"**，
 * 而它在界面上没有任何表现（不会报错、不会变红，就是安静）。
 * 所以每一条规则都要有测试钉着，而不是靠"看起来写了"。
 */
class NewOrderAlertTest {

    // ---- 认不认得出"这是一条要播的事件" ----

    @Test
    fun `新单能认出来并带上单号`() {
        val ev = NewOrderAlert.eventOf("order.assigned", 404L, "新派单")
        assertNotNull(ev)
        assertEquals(AlertKind.NEW_ORDER, ev!!.kind)
        assertEquals(404L, ev.orderId)
        assertEquals("assigned:404", ev.dedupeKey)
    }

    @Test
    fun `撤回与取消都认，且同一单共用一个去重键`() {
        val a = NewOrderAlert.eventOf("order.revoked", 9L)
        val b = NewOrderAlert.eventOf("order.cancelled", 9L)
        assertEquals(AlertKind.REVOKED, a!!.kind)
        assertEquals(AlertKind.REVOKED, b!!.kind)
        // 同一单先撤回后取消（或反过来）不该喊两遍
        assertEquals(a.dedupeKey, b.dedupeKey)
    }

    @Test
    fun `无关事件不播报`() {
        // 送达/运费更新/账本都不是"该司机动手"的事，播了就是噪音
        listOf("order.delivered", "order.freight.updated", "order.dispatched", "ledger.updated", "")
            .forEach { assertNull("不该播：" + it, NewOrderAlert.eventOf(it, 1L)) }
    }

    @Test
    fun `没有单号时也要能播（否则漏一次真单）`() {
        // payload 缺 order_id 时后端仍然发了站内信，这时宁可响、不可哑
        val ev = NewOrderAlert.eventOf("order.assigned", null, "新派单")
        assertNotNull(ev)
        assertEquals("assigned:-1", ev!!.dedupeKey)
    }

    // ---- 谁该听见 ----

    @Test
    fun `只有司机播语音`() {
        assertTrue(NewOrderAlert.isSpoken(Role.DRIVER))
        assertFalse(NewOrderAlert.isSpoken(Role.DISPATCHER))
        assertFalse(NewOrderAlert.isSpoken(Role.SHIPPER))
        // 认不出角色 → 不播（少播一次，好过给错的人放"来单了"）
        assertFalse(NewOrderAlert.isSpoken(null))
    }

    // ---- 响几次 ----

    @Test
    fun `设置的档位照做`() {
        assertEquals(3, NewOrderAlert.plan(3).repeats)
        assertEquals(1, NewOrderAlert.plan(1).repeats)
        assertEquals(2, NewOrderAlert.plan(2).repeats)
        assertTrue(NewOrderAlert.plan(NewOrderAlert.FOREVER).forever)
    }

    @Test
    fun `坏值回落到默认档而不是变成永远不响`() {
        // 存进去一个越界值（旧版本残留、手改偏好）时，绝不能变成 repeats=0 之外的意外行为。
        // 注意 5 现在是越界值：一段素材 ≈5 秒，5 次就是 25 秒（旧版本存过 5，升级后要能安全回落）
        listOf(-1, 4, 5, 99).forEach {
            assertEquals("值 $it 应回落", NewOrderAlert.DEFAULT_REPEAT, NewOrderAlert.plan(it).repeats)
        }
    }

    @Test
    fun `撤回只说一遍，哪怕用户设了三遍或一直响`() {
        // 连喊三遍"有任务被撤回"，司机会以为撤了三单
        assertEquals(1, NewOrderAlert.planFor(AlertKind.REVOKED, 3).repeats)
        assertEquals(1, NewOrderAlert.planFor(AlertKind.REVOKED, NewOrderAlert.FOREVER).repeats)
        assertFalse(NewOrderAlert.planFor(AlertKind.REVOKED, 3).forever)
    }

    @Test
    fun `新单按用户设置走`() {
        assertEquals(3, NewOrderAlert.planFor(AlertKind.NEW_ORDER, 3).repeats)
        assertEquals(2, NewOrderAlert.planFor(AlertKind.NEW_ORDER, 2).repeats)
        assertTrue(NewOrderAlert.planFor(AlertKind.NEW_ORDER, NewOrderAlert.FOREVER).forever)
    }

    @Test
    fun `总时长算得对（一段约 5 秒：号角+一整句话）`() {
        assertEquals(NewOrderAlert.CLIP_MS, NewOrderAlert.totalMs(NewOrderAlert.plan(1)))
        assertEquals(
            3 * NewOrderAlert.CLIP_MS + 2 * NewOrderAlert.GAP_MS,
            NewOrderAlert.totalMs(NewOrderAlert.plan(3)),
        )
        // 一直响没有确定时长——界面不能显示一个假的总时长
        assertNull(NewOrderAlert.totalMs(NewOrderAlert.plan(NewOrderAlert.FOREVER)))
    }

    @Test
    fun `默认播报不短于 5 秒也不长于 20 秒`() {
        // 用户的要求是「2 到 3 遍」：太短听不清、太长会烦。
        // 这条断言拦的是"素材换了时长但档位没跟着调"——那会让默认值悄悄变成半分钟。
        val total = NewOrderAlert.totalMs(NewOrderAlert.plan(NewOrderAlert.DEFAULT_REPEAT))!!
        assertTrue("默认 $total ms 太短，可能只播了半句", total >= 5_000)
        assertTrue("默认 $total ms 太长，已经算吵了", total <= 20_000)
    }

    @Test
    fun `一直响也有止损上限`() {
        // 没人接的单不能响一整夜：上限必须存在且不超过几分钟
        assertTrue(NewOrderAlert.FOREVER_MAX_MS in 10_000..300_000)
    }

    // ---- 什么时候闭嘴 ----

    @Test
    fun `司机动手和活没了都要立刻闭嘴`() {
        listOf(
            "order.driver_ack",       // 司机接单（本机 ack 与后端事件两条路）
            "order.delivered_driver", // 已送达
            "order.revoked",          // 撤回
            "order.cancelled",        // 取消
        ).forEach { assertTrue("$it 应该停止播报", NewOrderAlert.shouldStop(it)) }
    }

    @Test
    fun `新单本身不是停止信号`() {
        // 写完 shouldStop 最容易犯的错是把 order.assigned 也塞进去——那样一单都不会响
        assertFalse(NewOrderAlert.shouldStop("order.assigned"))
        assertFalse(NewOrderAlert.shouldStop("order.freight.updated"))
    }

    // ---- 去重（后端两条链路各推一次） ----

    @Test
    fun `同一单两条链路只响一次`() {
        val seen = mutableMapOf<String, Long>()
        val key = NewOrderAlert.eventOf("order.assigned", 7L)!!.dedupeKey
        assertFalse("第一次不该算重复", NewOrderAlert.isDuplicate(seen, key, 1_000L))
        seen[key] = 1_000L
        // notification 与 realtime 之间通常只差几百毫秒
        assertTrue("紧接着的第二次要算重复", NewOrderAlert.isDuplicate(seen, key, 1_400L))
        // 过了窗口（比如司机把同一单又派了一次）应该能再响
        assertFalse(
            "超过窗口应重新播报",
            NewOrderAlert.isDuplicate(seen, key, 1_000L + NewOrderAlert.DEDUPE_MS + 1),
        )
    }

    @Test
    fun `不同单互不影响`() {
        val seen = mutableMapOf<String, Long>()
        val a = NewOrderAlert.eventOf("order.assigned", 1L)!!.dedupeKey
        val b = NewOrderAlert.eventOf("order.assigned", 2L)!!.dedupeKey
        seen[a] = 1_000L
        assertFalse(NewOrderAlert.isDuplicate(seen, b, 1_100L))
    }

    @Test
    fun `去重表不会无限长大`() {
        val seen = mutableMapOf<String, Long>()
        repeat(200) { i -> seen["k$i"] = 0L }
        NewOrderAlert.isDuplicate(seen, "kNew", 10 * NewOrderAlert.DEDUPE_MS)
        assertTrue("过期的键要被清掉，否则跟着进程活成一条慢泄漏", seen.size <= 64)
    }

    // ---- 撤回后重派必须重新响（R14-14，2026-09-19 审计） ----

    @Test
    fun `撤回后 60 秒内重派给同一个司机也要响`() {
        // 真机场景：派单员派给司机 A（响）→ 撤回 → 立刻改派给同一个司机。
        // 不去作废去重键的话，第二声会被 60 秒窗口吞掉 —— 司机刚被告知"撤回了"，
        // 重派却没有提示音（列表会刷新，但人在车上不会盯屏幕）。
        val seen = mutableMapOf<String, Long>()
        val key = NewOrderAlert.eventOf("order.assigned", 42L)!!.dedupeKey
        seen[key] = 1_000L
        // 同一批派单的第二条链路：应当算重复
        assertTrue(NewOrderAlert.isDuplicate(seen, key, 1_200L))

        // 撤回到达 → 该单的新单去重键作废
        NewOrderAlert.forgetOnStop(seen, "order.revoked", 42L)
        assertFalse(
            "撤回之后再派给同一个司机，必须在窗口内也能响",
            NewOrderAlert.isDuplicate(seen, key, 1_300L),
        )
    }

    @Test
    fun `取消、接单、撤回、召回都会作废该单的新单去重键`() {
        listOf("order.cancelled", "order.driver_ack", "order.revoked", "order.recalled").forEach { t ->
            val seen = mutableMapOf("assigned:5" to 1_000L)
            NewOrderAlert.forgetOnStop(seen, t, 5L)
            assertFalse("$t 之后该单的新单键应当作废", seen.containsKey("assigned:5"))
        }
    }

    @Test
    fun `无关事件与缺单号不会误清去重键`() {
        // 不能因为一条无关事件就把别人的"正在响"状态清掉（否则同一单会被播两遍）
        val seen = mutableMapOf("assigned:6" to 1_000L)
        NewOrderAlert.forgetOnStop(seen, "order.delivered", 6L) // 送达是停止信号：允许清
        assertFalse(seen.containsKey("assigned:6"))
        val again = mutableMapOf("assigned:6" to 1_000L)
        NewOrderAlert.forgetOnStop(again, "ledger.updated", 6L)
        assertTrue("无关事件不许去动去重表", again.containsKey("assigned:6"))
        NewOrderAlert.forgetOnStop(again, "order.revoked", null)
        assertTrue("没有单号时无从清起", again.containsKey("assigned:6"))
    }

    // ---- 音量 ----

    @Test
    fun `音量低才抬，并且抬到八成`() {
        // 用户明确要求「调到手机的 80% 播放」（第一版是 70%，他反馈"声音比较小"）。
        // 15 档里的八成 = 12（四舍五入差一档无所谓，写死一个数只会让测试变脆）
        val raised = NewOrderAlert.boostTarget(15, 3)
        assertNotNull(raised)
        assertTrue("要抬到八成左右，实际 " + raised, raised!! in 11..12)
        // 已经够响就不动——"什么都没变还去写一次音量"会被用户察觉成音量自己乱跳
        assertNull(NewOrderAlert.boostTarget(15, 12))
        assertNull(NewOrderAlert.boostTarget(15, 15))
        // 拿不到音量上限（个别机型/被策略挡）时不做任何事，也不要除零
        assertNull(NewOrderAlert.boostTarget(0, 0))
    }

    @Test
    fun `抬音量的比例就是八成`() {
        // 钉住这个数：它是用户听出来的结论，不是随手取的参数
        assertEquals(0.8f, NewOrderAlert.BOOST_RATIO, 0.0001f)
    }

    // ---- 后台常驻的缺省 ----

    @Test
    fun `司机默认后台常驻，其他角色默认关`() {
        assertTrue(NewOrderAlert.defaultBackground(Role.DRIVER))
        assertFalse(NewOrderAlert.defaultBackground(Role.DISPATCHER))
        assertFalse(NewOrderAlert.defaultBackground(Role.SHIPPER))
    }

    // ---- 文案 ----

    @Test
    fun `档位文案是用户能懂的`() {
        assertEquals("1 次", NewOrderAlert.repeatLabel(1))
        assertEquals("5 次", NewOrderAlert.repeatLabel(5))
        assertEquals("一直响到我接单", NewOrderAlert.repeatLabel(NewOrderAlert.FOREVER))
        // 「0 次」这种从常量直接漏到界面上的写法要拦住
        NewOrderAlert.REPEAT_CHOICES.forEach {
            assertFalse("档位 $it 的文案不能出现 0", NewOrderAlert.repeatLabel(it).contains("0"))
        }
    }

    // ---- 「我的」那一行的状态摘要（用户判断"会不会响"的唯一入口） ----

    @Test
    fun `权限没开时所有角色都说权限没开`() {
        // 权限没开比"语音关了"更根本：先说自己收不到，再说别的
        listOf(Role.DRIVER, Role.DISPATCHER, Role.SHIPPER).forEach { r ->
            assertEquals(
                "通知权限未开",
                NewOrderAlert.summary(r, notificationsAllowed = false, voiceEnabled = true, repeat = 3, background = true),
            )
        }
    }

    @Test
    fun `货主和派单员不会被告知有语音`() {
        // 语音只有司机有；给他们写「语音 3 次」就是一句假话，他们会等一个永远不会响的东西
        listOf(Role.DISPATCHER, Role.SHIPPER, null).forEach { r ->
            val s = NewOrderAlert.summary(r, true, voiceEnabled = true, repeat = 3, background = true)
            assertFalse("非司机不该出现「语音」：$s", s.contains("语音"))
            assertEquals("后台接收中", s)
            assertEquals(
                "仅前台接收",
                NewOrderAlert.summary(r, true, voiceEnabled = true, repeat = 3, background = false),
            )
        }
    }

    @Test
    fun `司机的摘要要说清语音和后台两件事`() {
        assertEquals(
            "语音 3 次·后台接收",
            NewOrderAlert.summary(Role.DRIVER, true, voiceEnabled = true, repeat = 3, background = true),
        )
        assertEquals(
            "语音 1 次",
            NewOrderAlert.summary(Role.DRIVER, true, voiceEnabled = true, repeat = 1, background = false),
        )
        assertEquals(
            "语音已关",
            NewOrderAlert.summary(Role.DRIVER, true, voiceEnabled = false, repeat = 3, background = true),
        )
        assertEquals(
            "语音 一直响到我接单·后台接收",
            NewOrderAlert.summary(Role.DRIVER, true, voiceEnabled = true, repeat = NewOrderAlert.FOREVER, background = true),
        )
    }
}
