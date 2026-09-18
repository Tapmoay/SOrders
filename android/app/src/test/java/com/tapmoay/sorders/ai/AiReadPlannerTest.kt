package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

/**
 * 「读所有列表」的纯逻辑测试：**不联网、不依赖 Android、不依赖 Retrofit**。
 *
 * 这里守的是三件事，每一件出错用户都会得到**看起来正常的错答案**：
 * 1. **参数映射**（`from` 要落到这个接口真正声明的那个日期参数上）——映射错 → 后端 422 或悄悄不筛，
 *    用户拿到的是"全部数据"却以为筛过了；
 * 2. **必填补齐要说出来**（`assumed_filters`）——不补就是 422，补了不说就等于偷偷缩小范围；
 * 3. **编号只按名字解析**（模型永远拿不到、也不需要编号）——这是"回答里不出现内部编号"的第一道闸。
 */
class AiReadPlannerTest {

    private val today = LocalDate.of(2026, 9, 15)

    private fun args(vararg kv: Pair<String, String>): JsonObject = buildJsonObject {
        kv.forEach { (k, v) -> put(k, v) }
    }

    private fun ok(action: String, a: JsonObject): AiReadPlanner.Plan {
        val r = AiReadPlanner.plan(action, a, today)
        assertTrue("期望 Ok，实际：$r", r is AiReadPlanner.Result.Ok)
        return (r as AiReadPlanner.Result.Ok).plan
    }

    private fun bad(action: String, a: JsonObject): String {
        val r = AiReadPlanner.plan(action, a, today)
        assertTrue("期望 Bad，实际：$r", r is AiReadPlanner.Result.Bad)
        return (r as AiReadPlanner.Result.Bad).message
    }

    // ------------------------------------------------------------ 目录本身

    @Test
    fun statusAndOtherEnumFiltersSurviveIntoTheCatalog() {
        // ⚠️ 这条是**实测漏掉过的**：`status_filter: OrderStatus | None = Query(None, alias="status")`
        // 的注解是**枚举类型**，生成脚本一开始按"类型不在白名单就跳过"处理，
        // 结果 `status` 从目录里消失——真机上模型想按已送达筛，只能如实回答
        // 「订单列表接口不支持按状态筛选」，而接口其实支持。
        val orders = AiReadCatalog.find("orders.list_orders")
        assertTrue("订单列表必须支持 status 筛选", orders!!.params.any { it.name == "status" })
        val status = orders.params.first { it.name == "status" }
        assertTrue("status 的取值要带上（模型不知道该填什么就等于没有这个条件）", status.enum.isNotEmpty())
        assertTrue(status.enum.contains("DELIVERED"))
        // 说明里也要写清这张表能按什么筛，否则模型只能猜参数名
        assertTrue("filterHint 不能为空", orders.filterHint.isNotBlank())
        assertTrue(orders.filterHint.contains("status"))
        // 另一个枚举参数（用户角色）
        val users = AiReadCatalog.find("users.list_users")!!
        assertEquals(listOf("shipper", "driver", "dispatcher"), users.params.first { it.name == "role" }.enum)
    }

    @Test
    fun catalogHasNoPathParamsAndNoDuplicateActions() {
        // 目录是生成的，但"生成得对不对"要有人守。三条都踩过或差点踩到：
        // ① 带 {} 的端点=按 id 查详情，AI 看不到 id，不该在里面；
        // ② **路径必须是完整路径**（`/api/v1/...`）——生成脚本一开始拿的是 FastAPI **相对路由前缀**
        //    的路径（大量是空串），于是真机上请求打到 `/api/v1/` 上吃了 404，模型如实回报
        //    「read_data 暂不可用」。断言"不以 /api/v1/ 开头就失败"才能拦住它；
        // ③ 动作名重复会让 find() 静默返回其中一个。
        assertTrue("目录不该为空", AiReadCatalog.ACTIONS.size >= 30)
        AiReadCatalog.ACTIONS.forEach { a ->
            assertTrue("${a.action} 的路径必须是完整路径，实际「${a.path}」", a.path.startsWith("/api/v1/"))
            assertFalse("${a.action} 的路径不该带路径参数", a.path.contains("{"))
            assertTrue("${a.action} 的中文说明不能为空", a.cn.isNotBlank())
        }
        val dup = AiReadCatalog.ACTIONS.groupBy { it.action }.filterValues { it.size > 1 }
        assertEquals("动作名必须唯一", emptyMap<String, List<ReadAction>>(), dup)
    }

    @Test
    fun everyDeclaredIdParamIsMarkedAsId() {
        // is_id 标错 = 编号会被当成普通参数透给模型，或者"按名字筛"会失效
        AiReadCatalog.ACTIONS.forEach { a ->
            a.params.filter { it.name == "id" || it.name.endsWith("_id") }.forEach { p ->
                assertTrue("${a.action}.${p.name} 应该标成编号类参数", p.isId)
            }
        }
    }

    // ------------------------------------------------------------ 参数映射

    @Test
    fun fromAndToLandOnTheDateParameterThisEndpointActuallyDeclares() {
        // 三种命名风格（date_from/date_to、from/to、month）都要能对上
        val a1 = ok("orders.list_orders", args("from" to "2026-09-01", "to" to "2026-09-15"))
        assertEquals("2026-09-01", a1.query["date_from"])
        assertEquals("2026-09-15", a1.query["date_to"])

        val a2 = ok("freight_settlement.freight_settlement", args("from" to "2026-09-01", "to" to "2026-09-15"))
        assertEquals("2026-09-01", a2.query["from"])
        assertEquals("2026-09-15", a2.query["to"])

        // 只认到月的端点：给了具体日期要自动截成 YYYY-MM，否则后端 422
        val a3 = ok("driver_bills.list_driver_bills", args("from" to "2026-09-01"))
        assertEquals("2026-09", a3.query["month"])
        assertNull("month 类端点不该收到 date_to", a3.query["date_to"])
    }

    @Test
    fun unsupportedFiltersAreReportedInsteadOfSilentlyDropped() {
        // 悄悄丢掉筛选条件 = 用户拿到"看起来是他要的、其实范围完全不同"的数据
        val p = ok("products.list_products", args("status" to "ACTIVE", "q" to "酱油"))
        assertTrue("不支持的筛选要进 ignored", p.ignored.any { it.startsWith("status") })
        assertFalse("支持的筛选要生效", p.query.containsKey("status"))
        // products 没有 q 参数 → 也要如实报告
        assertTrue(p.ignored.contains("q"))

        val p2 = ok("users.list_users", args("q" to "王"))
        assertEquals("王", p2.query["q"])
        assertTrue(p2.ignored.isEmpty())
    }

    @Test
    fun limitIsCappedAndDefaultsAreApplied() {
        assertEquals(AiTools.DEFAULT_ROWS, ok("orders.list_orders", args()).limit)
        assertEquals(AiTools.MAX_ROWS, ok("orders.list_orders", args("limit" to "9999")).limit)
        assertEquals(1, ok("orders.list_orders", args("limit" to "0")).limit)
    }

    @Test
    fun requiredParamsAreFilledAndReported() {
        // 报表类接口的锚点日期是必填（`Query(..., alias="date")`）：不补 → 后端 422，
        // 用户只看到一句"参数不正确"。补了则**必须说出来**，否则他以为统计的是他说的那天。
        val p = ok("reports.turnover_report", args())
        assertEquals("2026-09-15", p.query["date"])
        assertEquals("2026-09-15", p.assumed["date"])

        // 司机跑货统计的区间也是必填
        val p2 = ok("stats.get_driver_performance", args())
        assertEquals("2026-09-01", p2.query["date_from"])
        assertEquals("2026-09-15", p2.query["date_to"])
        assertTrue(p2.assumed.containsKey("date_from"))
    }

    @Test
    fun optionalDatesAreNotFilledIn() {
        // ⚠️ 反向要求：可选参数**绝不**替用户补。
        // 给「所有订单」补上本月区间，用户拿到的就不是他要的全部了——比报错更糟。
        // （这条测试真的抓到过一个 bug：生成脚本只读 Query 的关键字参数，把 `Query(None, alias=...)`
        //   判成了必填，于是每个可选日期都被补上"本月"。）
        val p = ok("orders.list_orders", args("status" to "DELIVERED"))
        assertFalse(p.query.containsKey("date_from"))
        assertTrue("可选项不该出现在 assumed 里", p.assumed.isEmpty())
    }

    @Test
    fun nameFillsNameLikeRequiredParams() {
        // 商品下钻的必填参数是 product_name（不是编号），名字要能落到它上面
        val p = ok("stats.get_product_drilldown", args("name" to "金龙鱼调和油"))
        assertEquals("金龙鱼调和油", p.query["product_name"])
        assertNull(p.nameNeed)
    }

    // ------------------------------------------------------------ 名字 → 编号

    @Test
    fun nameIsTurnedIntoAnIdLookupNotPassedToTheModel() {
        val p = ok("ledger.list_entries", args("name" to "城东水果批发"))
        val need = p.nameNeed
        assertTrue("必须识别出需要按名字解析编号", need != null)
        assertEquals("shipper_id", need!!.param)
        assertEquals(AiReadPlanner.IdKind.SHIPPER, need.kind)
        assertEquals("城东水果批发", need.name)
        // 关键：计划里**还没有**编号（编号是执行期在 App 内解析的，模型全程看不到）
        assertFalse("模型给的参数里绝不能出现编号", p.query.containsKey("shipper_id"))
    }

    @Test
    fun idParamsInExtraAreRejectedWithAnActionableHint() {
        // 硬错误而不是"忽略"：忽略的话查询会**不带这个筛选条件**照样跑，
        // 模型很容易把"全部流水"当成"这个商品的流水"报给用户——最坏的一类错答案。
        val msg = bad("inventory.list_movements", args("extra" to """{"product_id": 12}"""))
        assertTrue("要告诉模型改用 name，而不是只说错了", msg.contains(AiReadPlanner.A_NAME))
    }

    @Test
    fun severalIdParamsRefuseToGuess() {
        // operation_logs 同时有 order_id / operator_id：只凭一个名字猜不出来，必须问清楚
        val msg = bad("operation_logs.list_operation_logs", args("name" to "张三"))
        assertTrue(msg.contains("order_id"))
        assertTrue(msg.contains("operator_id"))
    }

    @Test
    fun endpointsWithoutAnyIdParamUseNameAsKeyword() {
        // users 列表没有编号类条件 → 名字当关键词用，别浪费
        val p = ok("users.list_users", args("name" to "城东水果批发"))
        assertEquals("城东水果批发", p.query["q"])
        assertNull(p.nameNeed)
    }

    @Test
    fun unknownActionIsRejectedWithGuidance() {
        val msg = bad("users.delete_user", args())
        assertTrue("要引导模型去看 action 清单", msg.contains("action"))
    }

    @Test
    fun extraJsonAcceptsOnlyDeclaredNonIdParams() {
        val p = ok("users.list_users", args("extra" to """{"is_member": true}"""))
        assertEquals("true", p.query["is_member"])
        val p2 = ok("customers.list_customers", args("extra" to """{"kind":"member","who":"x"}"""))
        assertEquals("member", p2.query["kind"])
        assertTrue("不认识的键要报告", p2.ignored.contains("who"))
    }

    @Test
    fun brokenExtraJsonIsReportedNotCrashed() {
        val p = ok("users.list_users", args("extra" to "{这不是 JSON"))
        assertTrue(p.ignored.any { it.startsWith(AiReadPlanner.A_EXTRA) })
    }

    @Test
    fun kindMappingCoversTheMeasuredCatalog() {
        assertEquals(AiReadPlanner.IdKind.DRIVER, AiReadPlanner.kindOf("driver_id"))
        assertEquals(AiReadPlanner.IdKind.CUSTOMER, AiReadPlanner.kindOf("customer_id"))
        assertEquals(AiReadPlanner.IdKind.PRODUCT, AiReadPlanner.kindOf("product_id"))
        assertEquals(AiReadPlanner.IdKind.ORDER, AiReadPlanner.kindOf("order_id"))
        assertEquals(AiReadPlanner.IdKind.UNKNOWN, AiReadPlanner.kindOf("mystery_id"))
    }

    @Test
    fun dateParsingRejectsNaturalLanguage() {
        assertEquals(LocalDate.of(2026, 9, 1), AiReadPlanner.parseDateOrNull("2026-09-01"))
        assertNull(AiReadPlanner.parseDateOrNull("上周"))
        assertNull(AiReadPlanner.parseDateOrNull(null))
    }
}
