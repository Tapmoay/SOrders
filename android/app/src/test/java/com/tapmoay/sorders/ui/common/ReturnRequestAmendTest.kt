package com.tapmoay.sorders.ui.common

import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import com.tapmoay.sorders.ui.messages.TYPE_AMENDED
import com.tapmoay.sorders.ui.messages.noticeReturnRoute
import com.tapmoay.sorders.ui.nav.Role
import com.tapmoay.sorders.ui.nav.Routes
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import com.tapmoay.sorders.data.remote.dto.ReturnRequestDto
import com.tapmoay.sorders.data.remote.dto.ReturnRequestLineDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「改退货申请的明细」的**判据与文案**（2026-10-15 CHG-0130）。
 *
 * 为什么值得单独测（这一段是**规则**，不是样式）：
 *  · **哪些状态能改**这个判据同时管三处 —— 派单端待办里露不露「改明细」、货主端我的申请里
 *    露不露「改明细」、以及后端放不放行。三处只要有一处写岔，用户看到的就是
 *    "能点但点了被拒"或者"明明还能改却没有入口"，而且不会报任何错。
 *  · **改动只发一条通知**是用户口径里点名的（「只不过我们会发个通知」「只会重新发个信息」），
 *    通知发给谁（派单员改 → 货主/批发商；货主或批发商改 → 派单员）在文案里就得说清。
 *  · **可退上限**必须与后端、与另外三处消费点用**同一条规则**；这里钉住"改明细用的是同一份"。
 */
class ReturnRequestAmendTest {

    private fun req(status: String) = ReturnRequestDto(
        id = 9,
        orderId = 100,
        orderNo = "SO-100",
        status = status,
        statusLabel = "（后端给的中文）",
        lines = listOf(ReturnRequestLineDto(orderProductId = 1, productName = "苹果", quantity = 2)),
    )

    private fun line(
        id: Long,
        name: String,
        quantity: Int,
        damage: Int = 0,
        returned: Int = 0,
    ) = OrderProductDto(
        id = id,
        orderId = 100,
        productNameSnapshot = name,
        quantity = quantity,
        damageQuantity = damage,
        returnedQuantity = returned,
    )

    @Test
    fun `只有待处理能改_已办理_已驳回_已撤回_已自动关闭都改不了`() {
        assertTrue(canAmendReturnRequest(req("pending")))
        // 终态就是终态：这四种再点必然被后端拒，所以界面上也不该露出入口
        assertEquals(false, canAmendReturnRequest(req("done")))
        assertEquals(false, canAmendReturnRequest(req("rejected")))
        assertEquals(false, canAmendReturnRequest(req("withdrawn")))
        assertEquals(false, canAmendReturnRequest(req("closed")))
    }

    @Test
    fun `派单员改了就通知货主和批发商_而且只发一条`() {
        val line = amendNoticeLine(AMEND_ACTOR_DISPATCHER)
        assertTrue(line.contains("货主"))
        assertTrue(line.contains("批发商"))
        assertTrue("必须明说只发一条（用户口径）", line.contains("只发一条"))

        val done = amendDoneMessage(AMEND_ACTOR_DISPATCHER, "苹果×3")
        assertTrue("提示里要有改完之后的样子", done.contains("苹果×3"))
        assertTrue(done.contains("货主和批发商"))
        assertEquals(false, done.contains("操作成功"))
    }

    @Test
    fun `货主或批发商改了只通知派单员_并且说成这单发生了改动`() {
        val line = amendNoticeLine(AMEND_ACTOR_SHIPPER)
        assertTrue(line.contains("派单员"))
        assertTrue(line.contains("只发一条"))
        assertTrue("用户口径就是这句话", line.contains("此退货订单发生了改动"))

        val done = amendDoneMessage(AMEND_ACTOR_SHIPPER, "苹果×1")
        assertTrue(done.contains("派单员"))
        assertEquals(false, done.contains("货主和批发商"))
    }

    @Test
    fun `可退上限与全仓唯一那份规则同源_下单减货损减已退且不为负`() {
        assertEquals(5, amendMaxReturnable(line(1, "苹果", quantity = 10, damage = 2, returned = 3)))
        assertEquals(10, amendMaxReturnable(line(2, "梨", quantity = 10)))
        // 已经退完的行：0（不是负数 —— 负数会让"−"按钮和越界判据一起错）
        assertEquals(0, amendMaxReturnable(line(3, "桃", quantity = 4, returned = 4)))
        assertEquals(0, amendMaxReturnable(line(4, "枣", quantity = 1, damage = 3)))
    }

    @Test
    fun `填 0 等于这一行不要了_只有大于 0 的行才交上去`() {
        val lines = listOf(line(1, "苹果", 10), line(2, "梨", 10), line(3, "桃", 10))
        val qty = mapOf(1L to 3, 2L to 0, 3L to 1)
        // 顺序跟着订单行走（与后端 `lines_summary`、与申请单上的摘要同一个形状）
        assertEquals(listOf(1L, 3L), amendPickedIds(lines, qty))
        assertEquals("苹果×3、桃×1", amendPickedSummary(lines, qty))
        // 全清零 = 一行都没留（这条要被拦下来，见下一条用例）
        assertEquals(emptyList<Long>(), amendPickedIds(lines, lines.associate { it.id to 0 }))
        assertEquals("", amendPickedSummary(lines, lines.associate { it.id to 0 }))
    }

    @Test
    fun `空明细不给提交_并且把用户引到「撤回申请」而不是让他干瞪眼`() {
        val lines = listOf(line(1, "苹果", 10))
        val err = amendSubmitError(lines, mapOf(1L to 0))
        assertTrue(err != null)
        assertTrue("要给出下一步", err!!.contains("撤回申请"))
        // ⛔ 后端也会拒（`items` 的 min_length=1），这里只是不让用户白跑一次网络
        assertTrue(amendSubmitError(lines, mapOf(1L to 1)) == null)
    }

    @Test
    fun `一次最多改 20 行_超了在本地就说清`() {
        val many = (1L..21L).map { line(it, "商品" + it, 10) }
        val err = amendSubmitError(many, many.associate { it.id to 1 })
        assertTrue(err != null)
        assertTrue(err!!.contains("20"))
        // 正好 20 行是允许的（后端 `max_length=20`）
        val twenty = many.take(20)
        assertNull(amendSubmitError(twenty, twenty.associate { it.id to 1 }))
    }

    // ------------------------------------------------------------------
    // 改动通知的去向（`ui/messages/NoticeRouting.kt` —— 退货那一族的**唯一**路由处）
    // ------------------------------------------------------------------

    private fun amendPayload(id: Long): Map<String, JsonElement> =
        mapOf("request_id" to JsonPrimitive(id))

    @Test
    fun `有人改了这张申请_消息点得进去而且各回各那一页`() {
        // 派单员改的 → 货主（批发商同属这一侧）收到 → 货主端「我的退货申请」并定位那一条
        assertEquals(
            Routes.shipperReturnRequests(31),
            noticeReturnRoute(Role.SHIPPER.key, TYPE_AMENDED, amendPayload(31)),
        )
        // 货主 / 批发商改的 → 派单员收到 → 派单端「退货申请」待办页（唯一能真的办理的那一页）
        assertEquals(
            Routes.dispatcherReturnRequests(31),
            noticeReturnRoute(Role.DISPATCHER.key, TYPE_AMENDED, amendPayload(31)),
        )
    }

    @Test
    fun `改动通知缺申请单号就不跳_不把人扔到列表顶上`() {
        assertNull(
            noticeReturnRoute(
                Role.SHIPPER.key, TYPE_AMENDED,
                mapOf("order_no" to JsonPrimitive("SO-100")),
            ),
        )
        assertNull(noticeReturnRoute(Role.SHIPPER.key, TYPE_AMENDED, null))
    }

    @Test
    fun `改动通知的 type 名与后端一字不差_角色对不上就不跳`() {
        assertEquals("order.return_request.amended", TYPE_AMENDED)
        // 司机不是这三方 —— 与既有四条退货 type 同一套规则：认不出就退回老行为
        assertNull(noticeReturnRoute("driver", TYPE_AMENDED, amendPayload(31)))
    }
}
