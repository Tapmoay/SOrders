package com.tapmoay.sorders.ui.order

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 旧卡片点开之后的「说人话」判据（测试台账 TA-06 → BUG-0027）。
 *
 * 病灶：派单员把在途单删进回收站之后，司机端那张**旧卡片**还留在列表里、还能点开；
 * 点开走的是 GET /orders/{id}，后端回 404「订单不存在」（为了不让人从状态码反推有这张单，
 * 404 本身是对的），于是司机看到的就是一句「订单不存在」+ 一个「重试」按钮 ——
 * 单子明明刚才还在，重试一百次也回不来，而且没人告诉他是谁把它弄没了。
 *
 * 后端从 2026-10-10 起把这个 404 的 detail 换成了两句人话（只有当事人看得见，见
 * backend/app/api/v1/orders_common.py 的 DELETED_ORDER_NOTICES），这里钉住客户端侧的一半：
 * **认得出这两句**（据它换成「已被派单员删除」的面板 + 返回），**且不把别的错误认成它**
 * （把网络故障说成「订单被删了」比不说还坏 —— 司机会以为活没了）。
 */
class OrderDeletedTest {

    @Test
    fun `后端那两句删除说明都认`() {
        assertEquals("后端只发这两句，客户端多认一句就是自己编的", 2, OrderDeleted.HINTS.size)
        OrderDeleted.HINTS.forEach {
            assertTrue("$it 必须自己能认出自己", OrderDeleted.isDeletedNotice(it))
            assertTrue("$it 要给出路：告诉司机去哪找回来", it.contains("回收站"))
        }
    }

    @Test
    fun `后端原句一字不改也认`() {
        // 抄的是 backend/app/api/v1/orders_common.py 里 DELETED_ORDER_NOTICES 的字面量。
        // 后端哪天改文案，这条会红 —— 那是好事：客户端面板是按这句话认人的。
        assertTrue(
            OrderDeleted.isDeletedNotice("订单已被删除，如需找回请联系派单员从回收站恢复。")
        )
        assertTrue(
            OrderDeleted.isDeletedNotice("订单已被派单员删除，如需找回请联系派单员从回收站恢复。")
        )
    }

    @Test
    fun `夹在别的字里的删除说明也认`() {
        // 真机上是 OkHttp 那句「读取失败：」拼上去的，客户端不该因为多了一个前缀就翻脸。
        assertTrue(
            OrderDeleted.isDeletedNotice(
                "读取失败：订单已被派单员删除，如需找回请联系派单员从回收站恢复。"
            )
        )
    }

    @Test
    fun `普通的订单不存在不算删除说明`() {
        // 后端对「不是当事人」仍然只回这句（不许从文案反推那张单的存在）。
        // 客户端也就不该拿这句去渲染「已被派单员删除」—— 那是替后端撒谎。
        assertFalse(OrderDeleted.isDeletedNotice("订单不存在"))
    }

    @Test
    fun `别的报错不会被误判成删除`() {
        listOf(
            "网络连接失败，请检查网络后重试",
            "登录已过期，请重新登录",
            "读取失败：订单不存在",
            "",
            null,
        ).forEach { assertFalse("$it 不该被当成「订单被删了」", OrderDeleted.isDeletedNotice(it)) }
    }
}
