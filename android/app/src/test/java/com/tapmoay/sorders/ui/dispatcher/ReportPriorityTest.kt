package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.ExceptionOrderDto
import com.tapmoay.sorders.data.remote.dto.OperationLogDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

/**
 * 「异常与审计」分级排序的测试。
 *
 * 用户的原话是「上百条翻不到，就该按危险层级/紧急层级做分类和优先级排序」，
 * 所以这里钉的不是"函数能跑"，是**那几条最该先看的确实浮到最前面**：
 * 赔钱的排在没赔钱的上面、拖得久的排在刚发生的上面、改钱的排在改备注的上面。
 */
class ReportPriorityTest {

    private fun ex(
        id: Long,
        reason: String,
        orderDate: String = LocalDate.now().toString() + "T09:00:00",
        resolvedAt: String? = null,
        due: String? = null,
        deliveredAt: String? = null,
    ) = ExceptionOrderDto(
        id = id,
        orderNo = "SO$id",
        orderDate = orderDate,
        status = "DISPATCHED",
        exceptionReason = reason,
        exceptionResolvedAt = resolvedAt,
        expectedDeliverBefore = due,
        deliveredAt = deliveredAt,
    )

    private fun log(id: Long, action: String, at: String = "2026-09-16T10:00:00") =
        OperationLogDto(id = id, action = action, createdAt = at)

    // ---------------------------------------------------------------- 异常：危险层级

    @Test
    fun `钱货风险按原因文字分级（后端异常单没有金额字段，不猜金额）`() {
        assertEquals(RiskLevel.MONEY, exceptionRisk(ex(1, "司机反馈货损 2 件")))
        assertEquals(RiskLevel.MONEY, exceptionRisk(ex(2, "客户拒收")))
        assertEquals(RiskLevel.STUCK, exceptionRisk(ex(3, "超时未送（超过预计送达时间）")))
        assertEquals(RiskLevel.STUCK, exceptionRisk(ex(4, "待派超时（超过4小时未派单）")))
        assertEquals(RiskLevel.OTHER, exceptionRisk(ex(5, "随手记一笔")))
    }

    @Test
    fun `已经过去的事不再占用「要处理」（真机 275 条里 119 条是这个）`() {
        // 真实数据：110 条「逾期送达」（货已经到客户手里了，只是迟到过）+ 9 条「已撤销/撤回订单」
        val late = ex(10, "逾期送达（超过预计送达时间）")
        val cancelled = ex(11, "已撤销/撤回订单")
        assertEquals(RiskLevel.PAST, exceptionRisk(late))
        assertEquals(RiskLevel.PAST, exceptionRisk(cancelled))
        assertFalse("已送达的迟到单不该让人去处理", exceptionNeedsAction(late))
        assertFalse("已撤销的单是终态，没有可做的事", exceptionNeedsAction(cancelled))
        assertTrue("超时未送是真要处理的", exceptionNeedsAction(ex(12, "超时未送（超过预计送达时间）")))
        // 「要处理」和「已过去」两个数字必须加起来对得上，不能有单子凭空消失
        val all = listOf(late, cancelled, ex(12, "超时未送（超过预计送达时间）"))
        assertEquals(all.size, pendingExceptions(all).size + pastExceptions(all).size)
    }

    @Test
    fun `已解决的不再参与待处理排序`() {
        val e = ex(5, "货损 1 件", resolvedAt = "2026-09-16T12:00:00")
        assertEquals(RiskLevel.DONE, exceptionRisk(e))
        assertTrue("已解决的不该出现在待处理列表里", pendingExceptions(listOf(e)).isEmpty())
    }

    @Test
    fun `承诺送达时间已过且没送到，即使原因没写也算履约卡住`() {
        val overdue = ex(6, "说不清楚", due = LocalDate.now().minusDays(1).toString() + "T18:00:00")
        assertEquals(RiskLevel.STUCK, exceptionRisk(overdue))
        // 送到了就不算（避免"迟到过"被永远当成卡住）
        val done = ex(7, "说不清楚", due = LocalDate.now().minusDays(1).toString() + "T18:00:00", deliveredAt = "2026-09-16T08:00:00")
        assertEquals(RiskLevel.OTHER, exceptionRisk(done))
    }

    // ---------------------------------------------------------------- 异常：排序

    @Test
    fun `待解决列表先按危险层级、再按拖得久（这就是优先级的含义）`() {
        val today = LocalDate.now()
        val list = listOf(
            ex(1, "随手记一笔", orderDate = today.minusDays(30).toString() + "T09:00:00"), // 最久，但只是一般
            ex(2, "司机反馈货损 1 件", orderDate = today.minusDays(1).toString() + "T09:00:00"), // 钱货风险，才 1 天
            ex(3, "超时未送（超过预计送达时间）", orderDate = today.minusDays(5).toString() + "T09:00:00"),
            ex(4, "客户拒收", orderDate = today.minusDays(2).toString() + "T09:00:00"),
        )
        val order = pendingExceptions(list).map { it.id }
        // 钱货风险两条在最前，其中拖得久的（拒收 2 天 > 货损 1 天）再靠前
        assertEquals(listOf(4L, 2L, 3L, 1L), order)
    }

    @Test
    fun `拖了几天按订单日期算，解析不出来就是 0 而不是崩`() {
        assertEquals(3, stuckDays(ex(8, "x", orderDate = LocalDate.now().minusDays(3).toString() + "T09:00:00")))
        assertEquals(0, stuckDays(ex(9, "x", orderDate = "看不懂的日期")))
    }

    // ---------------------------------------------------------------- 审计：分类与危险

    @Test
    fun `审计按改动性质分类（用户要的是「我只想看改钱的」）`() {
        assertEquals(AuditKind.MONEY, auditKind("PRICE_RULE_UPSERT"))
        assertEquals(AuditKind.MONEY, auditKind("ORDER_FREIGHT"))
        assertEquals(AuditKind.MONEY, auditKind("LEDGER_UPDATE"))
        assertEquals(AuditKind.DELETE, auditKind("ORDER_DELETE"))
        // 删除优先于改钱：删掉的东西要先看见（钱改错了还能再改一次）
        assertEquals(AuditKind.DELETE, auditKind("LEDGER_DELETE"))
        assertEquals(AuditKind.AUTH, auditKind("USER_UPDATE"))
        assertEquals(AuditKind.STATE, auditKind("ORDER_DISPATCH"))
        assertEquals(AuditKind.STATE, auditKind("ORDER_EXCEPTION"))
        assertEquals(AuditKind.OTHER, auditKind("ORDER_CREATE"))
    }

    @Test
    fun `改商品既可能只改名字也可能改了单价，按改动内容判（真机日志就是这个形状）`() {
        // 库里真实的一行：{"product_id":3,"name":"红富士苹果","changes":[{"field":"default_unit_price",…}]}
        val price = """{"product_id": 3, "name": "红富士苹果", "changes": [{"field": "default_unit_price", "from": "12.0000", "to": "20.0000"}]}"""
        assertEquals(AuditKind.MONEY, auditKind("PRODUCT_UPDATE", price))
        val rename = """{"product_id": 3, "name": "红富士苹果", "changes": [{"field": "name", "from": "苹果", "to": "红富士苹果"}]}"""
        assertEquals(AuditKind.OTHER, auditKind("PRODUCT_UPDATE", rename))
        // 数量变动里有数字，但动的不是钱——别把"2 件改成 3 件"也算改钱
        val qty = """{"changes": [{"field": "quantity", "from": "2", "to": "3"}]}"""
        assertEquals(AuditKind.OTHER, auditKind("ORDER_LINE_UPDATE", qty))
        // 金额字段名出现（运费/单价/总额）就要归到改钱
        assertEquals(AuditKind.MONEY, auditKind("ORDER_LINE_UPDATE", """{"changes":[{"field":"line_total"}]}"""))
    }

    @Test
    fun `能悄悄改坏东西的排在最前，同级按时间倒序`() {
        val list = listOf(
            log(1, "ORDER_CREATE", "2026-09-16T12:00:00"), // 其它
            log(2, "USER_UPDATE", "2026-09-16T09:00:00"), // 账号权限（高危）
            log(3, "ORDER_DISPATCH", "2026-09-16T11:00:00"), // 改状态（中）
            log(4, "PRICE_RULE_UPSERT", "2026-09-16T10:00:00"), // 改钱（高危，比 2 新）
        )
        assertEquals(listOf(4L, 2L, 3L, 1L), sortedAudits(list).map { it.id })
    }

    @Test
    fun `分类筛选之后条数与筛选条上显示的一致`() {
        val list = listOf(log(1, "PRICE_RULE_UPSERT"), log(2, "ORDER_FREIGHT"), log(3, "ORDER_DELETE"), log(4, "ORDER_CREATE"))
        val counts = auditCounts(list)
        assertEquals(2, counts[AuditKind.MONEY])
        assertEquals(1, counts[AuditKind.DELETE])
        assertEquals(2, sortedAudits(list, AuditKind.MONEY).size)
        assertEquals(2, sortedAudits(list, AuditKind.MONEY).size)
        assertTrue("筛出来的每一条都必须是这一类", sortedAudits(list, AuditKind.DELETE).all { auditKind(it.action) == AuditKind.DELETE })
        // 不筛的时候一条都不许少：筛选只能是"过滤"，不能是"顺手丢掉"
        assertEquals(list.size, sortedAudits(list).size)
    }

    @Test
    fun `时间解析不出来也不会把它排到最后丢掉（宁可靠后也不丢）`() {
        val list = listOf(log(1, "PRICE_RULE_UPSERT", "坏时间"), log(2, "PRICE_RULE_UPSERT", "2026-09-16T10:00:00"))
        assertEquals(2, sortedAudits(list).size)
        assertEquals(2L, sortedAudits(list).first().id)
    }

    @Test
    fun `审计内容翻成人话（真机上是直接把 JSON 摆给用户看的）`() {
        // 库里真实的两行
        val price = """{"product_id": 3, "name": "红富士苹果", "changes": [{"field": "default_unit_price", "from": "12.0000", "to": "20.0000"}]}"""
        assertEquals("默认单价 12.0000 → 20.0000", auditChangeText(price))
        val freight = """{"freight_fee": {"before": "50.00", "after": "45.00"}}"""
        assertEquals("司机运费 50.00 → 45.00", auditChangeText(freight))
        val name = """{"user_id": 162, "changes": [{"field": "full_name", "from": "撤回测试账号", "to": "撤回测试账号改"}]}"""
        assertEquals("姓名 撤回测试账号 → 撤回测试账号改", auditChangeText(name))
        // ⚠️ 认不出来的形状**也不许把 JSON 摆出去**（v3.29 改的口径）：
        //    上一版是"原样返回"，于是真机上三种没覆盖到的形状就那样躺在审计页上。
        //    现在宁可写「没有可读的明细」——用户看一眼就知道这条日志没细节，
        //    而不是对着一串 `{"whatever": 1}` 猜。
        assertEquals("（这条日志没有可读的明细）", auditChangeText("""{"whatever": 1}"""))
        assertEquals("", auditChangeText(null))
        assertEquals("", auditChangeText("   "))
    }

    @Test
    fun `审计里其余的 JSON 形状也要说人话（这一条是第二遍真机才抓全的）`() {
        // ⚠️ 下面这些是**库里真实存在**的六种形状（`select action, change_content from operation_logs`）。
        //    第一版只认 changes/before-after 两种，其余原样返回 JSON——真机上就那样躺在审计页上。
        //    ① 建账号
        val create = """{"user_id": 162, "username": "13700008888", "full_name": "撤回测试账号", "phone": "13700008888", "role": "shipper", "is_member": false}"""
        val c1 = auditChangeText(create)
        assertFalse("不许出现内部编号：$c1", c1.contains("162"))
        assertFalse("不许出现 JSON 括号：$c1", c1.contains("{") || c1.contains("}") || c1.contains("\""))
        assertTrue("要说清是谁、什么角色：$c1", c1.contains("撤回测试账号") && c1.contains("货主"))
        assertTrue("布尔值要说人话：$c1", c1.contains("批发商 否"))
        // ② 删账号（说明里带接口路径，要清掉"代码话"）
        val del = """{"user_id": 162, "username": "13700008888", "phone": "13700008888", "note": "软删除（可 POST /users/{id}/restore 恢复），手机号已释放"}"""
        val c2 = auditChangeText(del)
        assertFalse("不许出现接口路径：$c2", c2.contains("/users/") || c2.contains("POST"))
        assertTrue("要保留「可恢复」这个信息：$c2", c2.contains("可恢复"))
        assertTrue("要说清电话已释放：$c2", c2.contains("手机号已释放"))
        // ③ 恢复账号（数组 + 空数组）
        val restore = """{"user_id": 162, "username": "13700008888", "phone": "13700008888", "restored": ["手机号", "用户名"], "conflicts": []}"""
        val c3 = auditChangeText(restore)
        assertTrue("数组要念出来：$c3", c3.contains("手机号、用户名"))
        assertTrue("账号读作「账号」而不是「电话」（它俩是同一个值）：$c3", c3.contains("账号 13700008888"))
        assertFalse("同一个值不许念两遍：$c3", c3.contains("电话"))
        assertFalse("空数组没有信息，不要念：$c3", c3.contains("冲突") || c3.contains("[]"))
        // ④ 批量调价的形状（顶层 before/after + 商品 + 批发商）
        val batch = """{"scope": "batch", "mode": "adjust", "shipper": "测试货主003", "product": "红富士苹果", "before": null, "after": "4.75"}"""
        val c4 = auditChangeText(batch)
        assertTrue("要说清哪个商品、成了多少：$c4", c4.contains("红富士苹果") && c4.contains("4.75"))
        assertTrue("要说清是给谁的：$c4", c4.contains("测试货主003"))
        assertFalse("别把内部选择器念出来：$c4", c4.contains("batch") || c4.contains("adjust"))
        // ⑤ 只有单号的动作（删单/恢复）
        assertEquals("订单 SOTEST2026091400227-2", auditChangeText("""{"order_no": "SOTEST2026091400227-2"}"""))
        // ⑥ 只有一个行编号的（什么都念不了，也不能把编号摆出来）
        val line = auditChangeText("""{"line_id": 580}""")
        assertFalse("行编号是内部编号，不许出现：$line", line.contains("580"))
        // ⑦ 删商品：名称 + 库存 + 说明
        val pdel = """{"product_id": 1, "name": "ttt", "stock": 100, "note": "软删除（可恢复）；库存流水/订单/账本/专属价均未改动"}"""
        val c7 = auditChangeText(pdel)
        assertTrue("要说清删的是哪个：$c7", c7.contains("ttt"))
        assertTrue("要说清库存没动：$c7", c7.contains("库存流水"))
    }

    @Test
    fun `不是 JSON 的那种也照样清掉代码话（后端偶尔存纯文本）`() {
        // ⚠️ 这条是反向验证逼出来的：把「不是 JSON 时也清 API 说法」那一步退回 `return c`
        //    之后，上面那些测试**全绿**——因为它们喂的全是合法 JSON，根本没走到这一支。
        val plain = "软删除（可 POST /users/{id}/restore 恢复），手机号已释放"
        val out = auditChangeText(plain)
        assertFalse("纯文本也要清掉接口路径：$out", out.contains("/users/") || out.contains("POST"))
        assertTrue("该留的信息不能丢：$out", out.contains("可恢复") && out.contains("手机号已释放"))
    }

    @Test
    fun `审计卡片要写清「谁、什么时候」（审计的第一个问题就是谁改的）`() {
        val today = java.time.LocalDate.now()
        // 今天：只写「今天 时:分」
        val t1 = auditWhoWhen("Dispatcher", today.toString() + "T10:21:50")
        assertEquals("Dispatcher · 今天 10:21", t1)
        // 昨天
        val t2 = auditWhoWhen("Dispatcher", today.minusDays(1).toString() + "T23:53:20")
        assertEquals("Dispatcher · 昨天 23:53", t2)
        // 更早：写月-日
        val d = today.minusDays(9)
        val t3 = auditWhoWhen("Dispatcher", d.toString() + "T08:05:00")
        assertEquals("Dispatcher · %02d-%02d 08:05".format(d.monthValue, d.dayOfMonth), t3)
        // 操作人缺失：说"未知"，不编一个名字；时间坏掉：只写人，不编时间
        assertEquals("操作人未知", auditWhoWhen(null, "坏时间"))
        assertEquals("操作人未知 · 今天 10:21", auditWhoWhen("  ", today.toString() + "T10:21:00"))
    }

    @Test
    fun `审计文本里任何形状都不许把 JSON 或内部编号摆出去`() {
        // 兜底断言：把上面所有真实形状都过一遍，输出里不许有 `{`/`}`/`"`/`*_id`
        val payloads = listOf(
            """{"product_id": 3, "name": "红富士苹果", "changes": [{"field": "default_unit_price", "from": "12.0000", "to": "20.0000"}]}""",
            """{"freight_fee": {"before": "50.00", "after": "45.00"}}""",
            """{"user_id": 162, "username": "13700008888", "full_name": "撤回测试账号", "phone": "13700008888", "role": "shipper", "is_member": false}""",
            """{"user_id": 162, "username": "13700008888", "restored": ["手机号", "用户名"], "conflicts": []}""",
            """{"scope": "batch", "mode": "adjust", "shipper": "测试货主003", "product": "红富士苹果", "before": null, "after": "4.75"}""",
            """{"order_no": "SO20260904975061"}""",
            """{"line_id": 580}""",
            """{"product_id": 1, "name": "ttt", "stock": 100, "note": "软删除（可恢复）"}""",
            """{"scope": "single", "shipper": "城东水果批发", "product": "红富士苹果", "before": "4.7500", "after": "4.80"}""",
        )
        for (p in payloads) {
            val out = auditChangeText(p)
            assertTrue("空输出等于把这条日志吞了：$p", out.isNotBlank())
            assertFalse("不许出现 JSON 花括号：$p → $out", out.contains("{") || out.contains("}"))
            assertFalse("不许出现 JSON 引号：$p → $out", out.contains("\""))
            for (bad in listOf("_id", "user_id", "product_id", "line_id", "order_id")) {
                assertFalse("不许出现内部字段名 $bad：$p → $out", out.contains(bad))
            }
        }
    }
}
