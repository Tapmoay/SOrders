package com.tapmoay.sorders.ai

import java.time.LocalDate
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 工作流执行器（[AiWorkflowRunner]，CHG-0096）—— **它只读，一个字都不写**。
 *
 * 这里用假的 `read` 喂手写的 JSON（形状与真读接口一致：`items` / `truncated` / `error`），
 * 钉的是几件"错了就是假账"的事：
 * - 订单那边必须走 `extra` 的 `delivered_from/delivered_to`（筛**送达日**），⛔ 不是 `from/to`（那是下单日）；
 * - 手工记的账（来源 = manual）**不算**这张单已经进账本（算进来会**漏报**）；
 * - 没有归属的单**不算漏记**，但要单独说清楚（否则用户白等）；
 * - 没查全（truncated）就**不给任何数字结论**；
 * - 调价**一条价都不算**（涨降算法只有确认卡上那一份实现）；
 * - 账本那一侧的**逐行明细**（各来源几笔多少钱、退货红冲逐行、哪些是整单退）是**代码算的**，
 *   没查全时一个字都不说 —— 台账 TB-04：模型自己按单拼明细时，会报出一个"库里数不出来"的笔数差。
 */
class AiWorkflowRunnerTest {

    private val today = LocalDate.parse("2026-10-09")

    /** 假的读：按 action 给一段 JSON，顺手把每次调用的参数记下来（判据要查参数本身）。 */
    private class FakeRead(private val replies: Map<String, String>) {
        val calls = mutableListOf<Pair<String, JsonObject>>()
        suspend fun read(action: String, args: JsonObject): String {
            calls += action to args
            return replies[action] ?: """{"error":"测试没给这个 action 准备返回"}"""
        }
        fun argsOf(action: String): JsonObject = calls.first { it.first == action }.second
    }

    private fun runner(fake: FakeRead) = AiWorkflowRunner(read = fake::read, today = { today })

    private fun obj(raw: String): JsonObject =
        AiJson.parseObjectLenient(raw) ?: throw AssertionError("返回的不是合法 JSON：" + raw)

    private fun JsonObject.str(key: String): String = (this[key] as JsonPrimitive).content
    private fun JsonObject.num(key: String): Int = str(key).toInt()
    private fun JsonObject.obj(key: String): JsonObject = this[key] as JsonObject
    private fun JsonObject.arr(key: String): List<JsonObject> = (this[key] as JsonArray).map { it as JsonObject }

    private fun args(vararg kv: Pair<String, String>): JsonObject = buildJsonObject {
        for ((k, v) in kv) put(k, v)
    }

    private val orders2 = """{"items":[
        {"订单号":"A001","货主":"张三","送达时间":"2026-10-03 10:00","货款":"12.50","status":"DELIVERED"},
        {"订单号":"A002","货主":"李四","送达时间":"2026-10-04 11:00","货款":"30.00","status":"DELIVERED"}
    ],"truncated":false}"""

    private val ledger1 = """{"items":[
        {"订单号":"A001","来源":"order","货主":"张三","金额":"12.50","entry_date":"2026-10-03"}
    ],"truncated":false}"""

    private val empty = """{"items":[],"truncated":false}"""

    // ------------------------------------------------------------------ 对账

    @Test
    fun `漏记的单被列出来_金额合计是查出来的`() = runBlocking {
        val fake = FakeRead(mapOf("orders.list_orders" to orders2, "ledger.list_entries" to ledger1))
        val root = obj(runner(fake).run(AiWorkflows.LEDGER_RECONCILE, args()))
        assertEquals(2, root.num("delivered_count"))
        assertEquals(1, root.num("booked_count"))
        assertEquals(1, root.num("missing_count"))
        assertEquals("30", root.str("missing_amount"))
        assertEquals("A002", root.arr("missing")[0].str("订单号"))
        assertTrue("结论要把「几张没进账本」说出来：" + root.str("conclusion"), root.str("conclusion").contains("1 张**没进账本**"))
        assertEquals(AiWrites.LEDGER_SYNC_DELIVERED, root.obj("next").str("action"))
        assertEquals(
            "交棒的动作要有人话名字：" + root.obj("next").toString(),
            AiWrites.titleOf(AiWrites.LEDGER_SYNC_DELIVERED),
            root.obj("next").str("action_cn"),
        )
        assertTrue("要问用户的那一句在 next 里：" + root.obj("next").toString(), root.obj("next").str("ask").contains("确认卡"))
    }

    @Test
    fun `默认窗口是本月 1 号到今天_订单按送达日筛`() = runBlocking {
        val fake = FakeRead(mapOf("orders.list_orders" to empty, "ledger.list_entries" to empty))
        val root = obj(runner(fake).run(AiWorkflows.LEDGER_RECONCILE, args()))
        assertEquals("2026-10-01", root.obj("window").str("from"))
        assertEquals("2026-10-09", root.obj("window").str("to"))
        val oa = fake.argsOf("orders.list_orders")
        assertEquals("DELIVERED", oa.str("status"))
        assertEquals(AiTools.MAX_ROWS, oa.num("limit"))
        assertTrue("订单必须走 extra 的 delivered_from：" + oa, oa.str("extra").contains("delivered_from"))
        assertTrue("订单必须走 extra 的 delivered_to：" + oa, oa.str("extra").contains("delivered_to"))
        assertTrue("⛔ 订单上不许传 from（那筛的是下单日）：" + oa, oa["from"] == null && oa["to"] == null)
        val la = fake.argsOf("ledger.list_entries")
        assertEquals("2026-10-01", la.str("from"))
        assertEquals("2026-10-09", la.str("to"))
    }

    @Test
    fun `指定的货主两张表都要带上`() = runBlocking {
        val fake = FakeRead(mapOf("orders.list_orders" to empty, "ledger.list_entries" to empty))
        val root = obj(runner(fake).run(AiWorkflows.LEDGER_RECONCILE, args("shipper" to "张三")))
        assertEquals("张三", fake.argsOf("orders.list_orders").str("name"))
        assertEquals("张三", fake.argsOf("ledger.list_entries").str("name"))
        assertEquals("只看 张三", root.str("scope"))
        assertEquals("张三", root.obj("next").obj("params").str("shipper"))
    }

    @Test
    fun `手工记的账不算这张单已经进账本`() = runBlocking {
        val fake = FakeRead(
            mapOf(
                "orders.list_orders" to """{"items":[{"订单号":"A001","货主":"张三","货款":"12.50"}],"truncated":false}""",
                "ledger.list_entries" to """{"items":[{"订单号":"A001","来源":"manual","金额":"12.50"}],"truncated":false}""",
            ),
        )
        val root = obj(runner(fake).run(AiWorkflows.LEDGER_RECONCILE, args()))
        assertEquals("手工那一笔不算这张单自动记过账", 0, root.num("booked_count"))
        assertEquals(1, root.num("missing_count"))
    }

    @Test
    fun `没有归属的单不算漏记_但要单独说清楚`() = runBlocking {
        val fake = FakeRead(
            mapOf(
                "orders.list_orders" to """{"items":[{"订单号":"A003","货款":"9.00"}],"truncated":false}""",
                "ledger.list_entries" to empty,
            ),
        )
        val root = obj(runner(fake).run(AiWorkflows.LEDGER_RECONCILE, args()))
        assertEquals(0, root.num("missing_count"))
        assertEquals(1, root.num("unowned_count"))
        assertTrue("要说清「系统不会自动记、不算漏记」：" + root.str("conclusion"), root.str("conclusion").contains("没有归属"))
    }

    @Test
    fun `账上有订单里没有的_单列出来建议逐张看`() = runBlocking {
        val fake = FakeRead(
            mapOf(
                "orders.list_orders" to empty,
                "ledger.list_entries" to """{"items":[{"订单号":"A009","来源":"order","金额":"5.00"}],"truncated":false}""",
            ),
        )
        val root = obj(runner(fake).run(AiWorkflows.LEDGER_RECONCILE, args()))
        assertEquals(0, root.num("missing_count"))
        assertEquals(1, root.num("ledger_only_count"))
        assertTrue("要说「账上有、这批订单里没有」：" + root.str("conclusion"), root.str("conclusion").contains("账上有"))
    }

    @Test
    fun `行里没有订单号的不算进对账`() = runBlocking {
        val fake = FakeRead(
            mapOf(
                "orders.list_orders" to """{"items":[{"货主":"张三","货款":"7.00"}],"truncated":false}""",
                "ledger.list_entries" to empty,
            ),
        )
        val root = obj(runner(fake).run(AiWorkflows.LEDGER_RECONCILE, args()))
        assertEquals(0, root.num("missing_count"))
        assertTrue("要说明有几行没有订单号、没算进对账：" + root.str("conclusion"), root.str("conclusion").contains("没有订单号"))
    }

    @Test
    fun `没查全就不给数字结论_让用户缩小范围`() = runBlocking {
        val fake = FakeRead(
            mapOf(
                "orders.list_orders" to """{"items":[{"订单号":"A001","货主":"张三","货款":"12.50"}],"truncated":true}""",
                "ledger.list_entries" to empty,
            ),
        )
        val root = obj(runner(fake).run(AiWorkflows.LEDGER_RECONCILE, args()))
        assertEquals("true", root.str("incomplete"))
        assertNull("没查全时不许给金额（那会被当成完整的账）", root["missing_amount"])
        assertTrue("要明说没查全、缩小范围重跑：" + root.str("conclusion"), root.str("conclusion").contains("没查全"))
        assertTrue("痕迹里也要标出来：" + root.str("trace"), root.str("trace").contains("没查全"))
    }

    @Test
    fun `窗口反了直接报错_一个读都不发`() = runBlocking {
        val fake = FakeRead(mapOf("orders.list_orders" to empty, "ledger.list_entries" to empty))
        val root = obj(
            runner(fake).run(AiWorkflows.LEDGER_RECONCILE, args("from" to "2026-10-09", "to" to "2026-10-01")),
        )
        assertTrue("要说清时间范围反了：" + root.toString(), root.str("error").contains("时间范围反了"))
        assertTrue("不许拿一个倒着的窗口去查（查回来是空的，结论会变成「账全对」）", fake.calls.isEmpty())
    }

    @Test
    fun `读接口出错就停下来_不拿半份数据下结论`() = runBlocking {
        val fake = FakeRead(
            mapOf(
                "orders.list_orders" to """{"error":"后端 500"}""",
                "ledger.list_entries" to ledger1,
            ),
        )
        val root = obj(runner(fake).run(AiWorkflows.LEDGER_RECONCILE, args()))
        assertTrue("要说清是第几步没查成：" + root.toString(), root.str("error").contains("第 1 步"))
        assertEquals("出错就只调了那一步", 1, fake.calls.size)
    }

    @Test
    fun `认不出的工作流要报错并列出能跑的`() = runBlocking {
        val fake = FakeRead(emptyMap())
        val root = obj(runner(fake).run("ledger.reconcile2", args()))
        assertTrue("要认出是「认不出」：" + root.toString(), root.str("error").contains("认不出"))
        assertTrue("要列出登记在案的：" + root.toString(), root.str("error").contains(AiWorkflows.LEDGER_RECONCILE))
    }

    @Test
    fun `传进来的时间必须是 YYYY-MM-DD_否则当没给`() = runBlocking {
        val fake = FakeRead(mapOf("orders.list_orders" to empty, "ledger.list_entries" to empty))
        val root = obj(runner(fake).run(AiWorkflows.LEDGER_RECONCILE, args("from" to "上个月")))
        assertEquals("认不出来的日期就退回默认窗口", "2026-10-01", root.obj("window").str("from"))
    }

    // -------------------------------------------------- 账本明细（TB-04 / BUG-0019）

    /** 四种来源混在一起：自动记账 + 退货红冲（部分退 A001 / 整单退 A009）+ 手工记账。 */
    private val ledgerMixed = """{"items":[
        {"订单号":"A001","来源":"order","货主":"张三","合计":"12.50","entry_date":"2026-10-03"},
        {"订单号":"A001","来源":"return","货主":"张三","商品":"菜籽油","合计":"-2.50","entry_date":"2026-10-05"},
        {"订单号":"A009","来源":"return","货主":"李四","商品":"大米","合计":"-7.10","entry_date":"2026-10-06"},
        {"订单号":"","来源":"manual","货主":"张三","合计":"12.50","entry_date":"2026-10-03"}
    ],"truncated":false}"""

    private fun mixedFake() = FakeRead(mapOf("orders.list_orders" to orders2, "ledger.list_entries" to ledgerMixed))

    @Test
    fun `账本明细是按来源算出来的_退货红冲逐行都在`() = runBlocking {
        val root = obj(runner(mixedFake()).run(AiWorkflows.LEDGER_RECONCILE, args()))

        val detail = root.arr("ledger_detail")
        assertEquals("三个来源各一行（manual / order / return）：" + detail, 3, detail.size)
        val manual = detail.first { it.str("来源") == "manual" }
        assertEquals("来源说明走全 App 唯一那份中文表", "手工记账", manual.str("来源说明"))
        assertEquals(1, manual.num("笔数"))
        assertEquals("12.5", manual.str("金额"))
        assertEquals("订单入账", detail.first { it.str("来源") == "order" }.str("来源说明"))
        assertEquals("退货红冲", detail.first { it.str("来源") == "return" }.str("来源说明"))

        assertEquals(2, root.num("returns_count"))
        assertEquals("-9.6", root.str("returns_amount"))
        val returns = root.arr("returns")
        assertEquals(2, returns.size)
        assertEquals("A001", returns[0].str("订单号"))
        assertEquals("2026-10-05", returns[0].str("日期"))
        assertEquals("-2.5", returns[0].str("金额"))
        assertEquals("菜籽油", returns[0].str("商品"))
        assertTrue(
            "结论要说清退货红冲几笔、多少钱（数都是代码算的）：" + root.str("conclusion"),
            root.str("conclusion").contains("退货红冲有 2 笔（合计 -9.6 元）"),
        )
        assertTrue(
            "⛔ 结论里不许自己拼明细，要指向 ledger_detail：" + root.str("conclusion"),
            root.str("conclusion").contains("不要自己按单拼明细"),
        )
    }

    @Test
    fun `整单退货还是部分退_是代码判的不许猜`() = runBlocking {
        val root = obj(runner(mixedFake()).run(AiWorkflows.LEDGER_RECONCILE, args()))
        assertEquals("A009 不在本次已送达清单里 ⇒ 那一笔是整单退", 1, root.num("whole_order_returns"))
        val returns = root.arr("returns")
        assertTrue("A001 还在已送达清单里 ⇒ 部分退：" + returns[0], returns[0].str("整单退货").startsWith("否"))
        assertTrue("A009 不在 ⇒ 整单退：" + returns[1], returns[1].str("整单退货").startsWith("是"))
        assertTrue(
            "结论要点出有几笔挂在整单退货的单上：" + root.str("conclusion"),
            root.str("conclusion").contains("1 笔挂在**整单退货**的单上"),
        )
    }

    @Test
    fun `口径那句话只有一份_讲清回收站的单两边都不计`() = runBlocking {
        val root = obj(runner(mixedFake()).run(AiWorkflows.LEDGER_RECONCILE, args()))
        val note = root.str("scope_note")
        assertTrue("要说清只算没进回收站的：" + note, note.contains("没进回收站"))
        assertTrue("要说清成对存在、净额 0：" + note, note.contains("成对存在、净额 0"))
        assertTrue("要说明对不上不是漏账：" + note, note.contains("那不是漏账"))
        assertTrue("结论末尾要带上这条口径：" + root.str("conclusion"), root.str("conclusion").contains(note))
    }

    @Test
    fun `没查全时一个字都不说账本明细`() = runBlocking {
        val fake = FakeRead(
            mapOf(
                "orders.list_orders" to """{"items":[{"订单号":"A001","货主":"张三","货款":"12.50"}],"truncated":true}""",
                "ledger.list_entries" to ledgerMixed,
            ),
        )
        val root = obj(runner(fake).run(AiWorkflows.LEDGER_RECONCILE, args()))
        assertEquals("true", root.str("incomplete"))
        assertTrue(
            "没查全时结论里不许出现退货红冲的数（那是拿半份数据当账）：" + root.str("conclusion"),
            !root.str("conclusion").contains("退货红冲"),
        )
    }

    // -------------------------------------------------------------- 批量调价

    private val products = """{"items":[
        {"名称":"金龙鱼菜籽油","default_unit_price":"40.00","库存":"10"},
        {"名称":"东北大米","default_unit_price":"5.00","库存":"20"}
    ],"truncated":false}"""

    private val rules2 = """{"items":[
        {"商品":"金龙鱼菜籽油","货主":"甲批发","special_unit_price":"38.00"},
        {"商品":"金龙鱼菜籽油","货主":"乙批发","special_unit_price":"39.00"},
        {"商品":"东北大米","货主":"甲批发","special_unit_price":"4.50"}
    ],"truncated":false}"""

    private fun priceFake() = FakeRead(
        mapOf("products.list_products" to products, "price_rules.list_price_rules" to rules2),
    )

    @Test
    fun `调价的改法必须恰好给一个`() = runBlocking {
        val none = obj(runner(priceFake()).run(AiWorkflows.PRICE_BATCH, args()))
        assertTrue("两个都不给要报错：" + none.toString(), none.str("error").contains("恰好"))
        val both = obj(runner(priceFake()).run(AiWorkflows.PRICE_BATCH, args("adjust" to "-5", "price" to "9")))
        assertTrue("两个都给也要报错：" + both.toString(), both.str("error").contains("恰好"))
    }

    @Test
    fun `名字能对上时统计会被这张卡覆盖的专属价`() = runBlocking {
        val fake = priceFake()
        val root = obj(runner(fake).run(AiWorkflows.PRICE_BATCH, args("product" to "菜籽油", "adjust" to "-5")))
        assertEquals(1, root.num("matched_products"))
        assertEquals(2, root.num("covered_rules"))
        assertTrue("结论要说清覆盖几条：" + root.str("conclusion"), root.str("conclusion").contains("2 条"))
        val next = root.obj("next")
        assertEquals(AiWrites.PRICE_RULES_BATCH, next.str("action"))
        assertEquals("-5", next.obj("params").str("adjust"))
        assertEquals("菜籽油", next.obj("params").str("product"))
    }

    @Test
    fun `全部这两个字等于不过滤`() = runBlocking {
        val root = obj(
            runner(priceFake()).run(AiWorkflows.PRICE_BATCH, args("product" to "全部", "shipper" to "所有批发商", "price" to "9")),
        )
        assertEquals(2, root.num("matched_products"))
        assertEquals(3, root.num("covered_rules"))
        val params = root.obj("next").obj("params")
        assertEquals("9", params.str("price"))
        assertTrue("说了「全部」就不要把它当成一个商品名传下去：" + params.toString(), params["product"] == null)
        assertTrue("同理不要传 shipper：" + params.toString(), params["shipper"] == null)
    }

    @Test
    fun `名字对不上要单独说_不许自己猜一个商品`() = runBlocking {
        val root = obj(runner(priceFake()).run(AiWorkflows.PRICE_BATCH, args("product" to "不存在的商品", "adjust" to "5")))
        assertEquals(0, root.num("matched_products"))
        assertEquals("不存在的商品", root.str("not_found"))
        assertTrue("要提醒用户核一下写法：" + root.str("conclusion"), root.str("conclusion").contains("没找到叫"))
    }

    @Test
    fun `调价一条价都不算_改前改后是确认卡上的事`() = runBlocking {
        val root = obj(runner(priceFake()).run(AiWorkflows.PRICE_BATCH, args("product" to "菜籽油", "adjust" to "-5")))
        assertTrue(
            "要写明不在这里算价：" + root.str("conclusion"),
            root.str("conclusion").contains("不在这里算"),
        )
        assertNull("⛔ 不许自己算一个「改后」出来（那是确认卡上唯一那份实现的事）", root["after"])
    }

    @Test
    fun `调价也怕没查全`() = runBlocking {
        val fake = FakeRead(
            mapOf(
                "products.list_products" to """{"items":[{"名称":"金龙鱼菜籽油","default_unit_price":"40.00"}],"truncated":true}""",
                "price_rules.list_price_rules" to rules2,
            ),
        )
        val root = obj(runner(fake).run(AiWorkflows.PRICE_BATCH, args("product" to "菜籽油", "adjust" to "-5")))
        assertEquals("true", root.str("incomplete"))
        assertTrue("要提醒缩小范围再跑：" + root.str("conclusion"), root.str("conclusion").contains("没查全"))
    }

    @Test
    fun `调价的读出错就停下`() = runBlocking {
        val fake = FakeRead(
            mapOf(
                "products.list_products" to """{"error":"超时"}""",
                "price_rules.list_price_rules" to rules2,
            ),
        )
        val root = obj(runner(fake).run(AiWorkflows.PRICE_BATCH, args("product" to "菜籽油", "adjust" to "-5")))
        assertTrue("要说清第几步没查成：" + root.toString(), root.str("error").contains("第 1 步"))
        assertEquals(1, fake.calls.size)
    }
}
