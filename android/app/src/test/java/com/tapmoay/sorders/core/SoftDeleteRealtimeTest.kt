package com.tapmoay.sorders.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 软删 / 恢复的**实时信号**（测试台账 TA-05 → BUG-0027）。
 *
 * 后端 2026-10-10 起在「派单员把一张单删进回收站」与「从回收站恢复」时各发一条实时事件
 * （`order.deleted` / `order.restored`）。这两条在安卓侧必须**被认出来** —— 认不出就等于
 * 「后端发了没人认」（CHG-0040 的 order.updated 栽过一次）：站内信照进（那是另一条链路），
 * 但司机端「进行中」列表不会当场刷新，仍然要手动下拉才看得到那张卡消失/回来 ——
 * 那正是 TA-05 的原样。
 *
 * 这里钉住的三件事都在纯函数层（跑 JVM 单测就能验，不需要模拟器）：
 * 1. `PushTrust` 认得这两个类型（`isOrderEvent`）：不认就降级成普通消息（不再走「派单与新单」渠道）；
 * 2. `NewOrderAlert` 认 `order.deleted` 是「任务被撤回」那一类，且与 revoked/cancelled
 *    **同族去重键**（同一单先撤回后删除不该喊两遍 —— 现有单测就是这条规矩）；
 * 3. 它是「该闭嘴」的类型：司机接了单/活没了要立刻打断播报，并作废那单的新单去重键
 *    （否则那单被删之后，回补的一条旧通知还会再喊一次「来订单了」）。
 */
class SoftDeleteRealtimeTest {

    // ---- ① 类型白名单 ----

    @Test
    fun `软删与恢复都算订单事件`() {
        // 白名单的语义是「这条消息属于订单渠道」（高优先级横幅 + 点开直达某一单），
        // 不是「这条消息是坏消息」。少一个的后果：那条站内信降级成普通消息。
        assertTrue("order.deleted 应当被认成订单事件", PushTrust.isOrderEvent("order.deleted"))
        assertTrue("order.restored 应当被认成订单事件", PushTrust.isOrderEvent("order.restored"))
    }

    // ---- ② 播报判定 ----

    @Test
    fun `被删的单说成任务被撤回`() {
        val ev = NewOrderAlert.eventOf("order.deleted", 9L)
        assertNotNull("order.deleted 必须能翻成一条播报事件，否则司机端一句话都没有", ev)
        assertEquals(AlertKind.REVOKED, ev!!.kind)
        assertEquals(9L, ev.orderId)
    }

    @Test
    fun `撤回取消与被删同一单共用一个去重键`() {
        // 同一张单可能先被撤回、后被删除（或反过来）。三个类型说的是同一件事：
        // 「那单没了」—— 喊两遍只会让司机以为有两笔单出了事。
        val revoked = NewOrderAlert.eventOf("order.revoked", 9L)!!
        val cancelled = NewOrderAlert.eventOf("order.cancelled", 9L)!!
        val deleted = NewOrderAlert.eventOf("order.deleted", 9L)!!
        assertEquals(revoked.dedupeKey, deleted.dedupeKey)
        assertEquals(cancelled.dedupeKey, deleted.dedupeKey)
    }

    @Test
    fun `缺单号时也能认出来但不冒充某一张单`() {
        val ev = NewOrderAlert.eventOf("order.deleted", null)
        assertNotNull("缺单号只该丢掉去重键里的编号，不该整条丢掉", ev)
        // 单号缺失时 orderId 保持 null（"不知道是哪一单"，与 assigned / pending 两个分支同一约定），
        // 只有去重键里的编号退化成哨兵 -1 —— 别把哨兵写进 orderId，那会冒充成"第 -1 单"。
        assertNull("缺单号时不冒充某一张单", ev!!.orderId)
        assertEquals("revoked:-1", ev.dedupeKey)
        assertFalse(ev.dedupeKey == NewOrderAlert.eventOf("order.deleted", 9L)!!.dedupeKey)
    }

    @Test
    fun `活没了要立刻闭嘴`() {
        assertTrue("被删的单不该继续响「来订单了」", NewOrderAlert.shouldStop("order.deleted"))
    }

    @Test
    fun `被删之后那单的新单去重键作废`() {
        // 去重键不清的后果：司机端断线回补（sync）时，一条**删除之前**的旧通知
        // 会被当成"没响过的新单"再喊一次 —— 单子早没了，还在喊来订单了。
        val seen = mutableMapOf("assigned:9" to 1L, "assigned:8" to 1L)
        NewOrderAlert.forgetOnStop(seen, "order.deleted", 9L)
        assertFalse("被删那单的去重键要清掉", seen.containsKey("assigned:9"))
        assertTrue("别的单不许受影响", seen.containsKey("assigned:8"))
    }

    @Test
    fun `恢复不打断也不冒充新单`() {
        // 恢复是"好事"：不该像撤回那样抢话（真机上会打断正在播的语音）。
        assertFalse(NewOrderAlert.shouldStop("order.restored"))
    }
}
