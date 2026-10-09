package com.tapmoay.sorders.ui.ai

import com.tapmoay.sorders.ai.AiReadCatalog
import com.tapmoay.sorders.ai.AiTools
import com.tapmoay.sorders.ai.AiWrites
import com.tapmoay.sorders.data.remote.dto.AiOperationDto
import com.tapmoay.sorders.util.formatDateTime
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import java.time.ZoneId

/**
 * 「AI 操作流水」那一行字怎么念（台账 L-52 / CHG-0082）。
 *
 * ## 为什么一个"格式化"值得 14 个用例
 * 这一页是**审计页**：用户读它不是为了好看，是为了回答"AI 到底动过什么"。
 * 三句话写错就等于**答错**：
 * - 认不出的动作名 → 编一个中文名（用户会以为 AI 干了别的事）；
 * - `user_name` 缺失 → 留空（那一行看起来"没人做过"）；
 * - 失败但没有原因 → 留空（403 越权 / 400 参数错 / 500 后端炸了被糊成一片空白）。
 * 所以这里逐条钉死，包括三种兜底。
 *
 * ⚠️ 动作名认不出**不等于**可以只写英文 id（台账 L-58 / BUG-0020）：流水的 `action` 有三种
 * 来源，写动作在 `AiWrites`、读动作在 `AiReadCatalog`、工具本身在 `AiTools` 的短名表里。
 * 三张表都查过还是认不出，才轮到"如实写 id"。所以下面每一条来源各有用例，
 * 且中文名一律**从表里取**（⛔ 不许在用例里抄一个中文名 —— 抄了就变成钉住抄错的那份）。
 *
 * ⚠️ 时间那一条**不许写死"几点"**：`formatDateTime` 是设备时区相关的
 * （见 `util/TimeFmt.kt` 顶部那段"所有时间早 8 小时"的教训）。这里改成
 * ①与 `formatDateTime` 同源 ②形状正确 ③**只要设备不在 UTC 就绝不能等于 naive 截断**
 * —— 第三条正是当年那个缺陷的形状，且在 UTC 机器上会正确地跳过（否则本机跑绿、换台机器就红）。
 */
class AiOperationRowsTest {

    private fun row(
        id: Long = 1,
        userId: Long? = null,
        action: String? = null,
        method: String = "POST",
        path: String = "/api/v1/orders",
        statusCode: Int = 200,
        ok: Boolean = true,
        error: String? = null,
        requestId: String? = null,
        durationMs: Int = 12,
        createdAt: String = "2026-10-08T01:30:00",
        userName: String? = null,
    ) = AiOperationDto(
        id = id,
        userId = userId,
        action = action,
        method = method,
        path = path,
        statusCode = statusCode,
        ok = ok,
        error = error,
        requestId = requestId,
        durationMs = durationMs,
        createdAt = createdAt,
        userName = userName,
    )

    @Test
    fun `成没成_失败时必须带上状态码`() {
        assertEquals("成功", AiOperationRows.resultLabel(row(ok = true, statusCode = 200)))
        // 排障第一步就是状态码：只写"失败"等于把 403/400/500 三件事糊成一件
        assertEquals("失败 · 403", AiOperationRows.resultLabel(row(ok = false, statusCode = 403)))
        // 超时/断网的记录可能是 0：照原样写，别美化成"-"
        assertEquals("失败 · 0", AiOperationRows.resultLabel(row(ok = false, statusCode = 0)))
    }

    @Test
    fun `认得出的动作写中文名_括号里带动作 id`() {
        val known = AiWrites.ALL.first { it.title != it.id }
        assertEquals(known.title + "（" + known.id + "）", AiOperationRows.actionLabel(row(action = known.id)))
    }

    @Test
    fun `读动作认得出_写读目录那张表的中文名`() {
        // 2026-10-09（CHG-0089）起读动作也带头：`invoices.list_invoices` 这种规范名
        // 不在写动作表里，靠读目录的 cn 认（台账 L-58 记的就是它只有 id 的那一版）
        val read = AiReadCatalog.ACTIONS.first { it.cn.contains("（") }
        assertEquals(AiOperationRows.readTitle(read.cn) + "（" + read.action + "）", AiOperationRows.actionLabel(row(action = read.action)))
    }

    @Test
    fun `读动作说明没有括号时_整句当表名`() {
        val read = AiReadCatalog.ACTIONS.first { !it.cn.contains("（") && !it.cn.contains("(") }
        assertEquals(read.cn + "（" + read.action + "）", AiOperationRows.actionLabel(row(action = read.action)))
    }

    @Test
    fun `工具驱动的动作认得出_写设置页那张短名表`() {
        // 工具 id（`inventory_alerts` 这类）既不在写动作表、也不是读目录规范名，靠 AiTools 认
        val tool = AiTools.ALL.first { AiTools.titleOf(it) != it }
        assertEquals(AiTools.titleOf(tool) + "（" + tool + "）", AiOperationRows.actionLabel(row(action = tool)))
    }

    @Test
    fun `读目录短名_只取第一个括号之前_剥不空`() {
        assertEquals("商品", AiOperationRows.readTitle("商品（某段时间的卖法、单价、卖出多少）"))
        // 半角括号同样要剥（生成器只保证「（」，但别把半角漏成整句）
        assertEquals("库存", AiOperationRows.readTitle("库存(只读)"))
        // 本来就没括号的（那批一句话表名）原样用整句
        assertEquals("客户列表", AiOperationRows.readTitle("客户列表"))
        // ⛔ 兜底：剥出来是空的就退回整句 —— 这一列绝不许空白
        assertEquals("（全括号）", AiOperationRows.readTitle("（全括号）"))
        assertEquals("", AiOperationRows.readTitle(""))
    }

    @Test
    fun `认不出的动作原样写 id_不许编中文名`() {
        assertEquals("no.such.action", AiOperationRows.actionLabel(row(action = "no.such.action")))
    }

    @Test
    fun `只读查询没有动作名_如实写未标动作`() {
        // 读工具没有"动作"可写 ⇒ action=null 是**正常**数据，不是脏数据；
        // 拿端点去猜一个动作名，猜错比不猜危险得多。
        assertEquals("未标动作（只读查询）", AiOperationRows.actionLabel(row(action = null)))
        assertEquals("未标动作（只读查询）", AiOperationRows.actionLabel(row(action = "   ")))
    }

    @Test
    fun `谁_昵称优先_再退回用户编号_最后是未登录`() {
        assertEquals("张三", AiOperationRows.whoLabel(row(userName = "张三", userId = 7)))
        // 后端给了个空白串（等于没给）⇒ 退回编号，⛔ 不许留空
        assertEquals("用户 #7", AiOperationRows.whoLabel(row(userName = "  ", userId = 7)))
        assertEquals("用户 #7", AiOperationRows.whoLabel(row(userName = null, userId = 7)))
        // 401 的请求认不出人：仍然要有一句话，否则那一行看起来"没人做过"
        assertEquals("未登录请求", AiOperationRows.whoLabel(row(userName = null, userId = null)))
    }

    @Test
    fun `端点三档兜底`() {
        assertEquals("POST /api/v1/orders", AiOperationRows.endpointLabel(row(method = "POST", path = "/api/v1/orders")))
        assertEquals("? /api/v1/orders", AiOperationRows.endpointLabel(row(method = "", path = "/api/v1/orders")))
        assertEquals("GET （没记端点）", AiOperationRows.endpointLabel(row(method = "GET", path = "")))
    }

    @Test
    fun `耗时_一秒以下写毫秒_以上写秒`() {
        assertEquals("0 ms", AiOperationRows.durationLabel(0))
        assertEquals("999 ms", AiOperationRows.durationLabel(999))
        assertEquals("1.0 s", AiOperationRows.durationLabel(1000))
        // ⛔ 用 Locale.US：跟着机器区域变的话，某些区域会把小数点写成逗号
        assertEquals("12.3 s", AiOperationRows.durationLabel(12345))
    }

    @Test
    fun `失败原因_后端给什么写什么_没有就说没有`() {
        assertEquals("你没有权限执行这个操作", AiOperationRows.errorLabel(row(ok = false, error = "你没有权限执行这个操作")))
        assertEquals("后端没有留下原因（看状态码）", AiOperationRows.errorLabel(row(ok = false, error = null)))
        assertEquals("后端没有留下原因（看状态码）", AiOperationRows.errorLabel(row(ok = false, error = "  ")))
    }

    @Test
    fun `时刻_与全站同一把尺子_且绝不是 UTC 原样印`() {
        val sample = "2026-10-08T01:30:00"
        val label = AiOperationRows.whenLabel(row(createdAt = sample))
        // ① 与 `formatDateTime` 同源（这一页没有自己的时间格式）
        assertEquals(formatDateTime(sample), label)
        // ② 形状正确
        assertTrue("时刻形状不对：$label", label.matches(Regex("\\d{2}-\\d{2} \\d{2}:\\d{2}")))
        // ③ 设备不在 UTC 时，绝不能等于 naive 截断（"所有时间早 8 小时"那个缺陷的形状）
        val offset = ZoneId.systemDefault().rules.getOffset(Instant.now())
        if (offset.totalSeconds != 0) {
            assertNotEquals(sample.take(16).replace('T', ' '), label)
        }
    }

    @Test
    fun `时刻为空时不编一个时间出来`() {
        assertEquals("", AiOperationRows.whenLabel(row(createdAt = "")))
    }
}
