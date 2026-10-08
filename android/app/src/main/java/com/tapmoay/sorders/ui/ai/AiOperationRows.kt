package com.tapmoay.sorders.ui.ai

import com.tapmoay.sorders.ai.AiWrites
import com.tapmoay.sorders.data.remote.dto.AiOperationDto
import com.tapmoay.sorders.util.formatDateTime
import java.util.Locale

/**
 * 一条 AI 流水在界面上要说清的四件事：**谁、什么时候、动了什么、成没成**（台账 L-52 / CHG-0082）。
 *
 * ## 为什么这些是纯函数
 * 这一页是**审计页**：一句话写错的后果不是"不好看"，而是用户据此判断"AI 没干过这件事"
 * （或者反过来，以为成功其实失败了）。所以每一句都由单测钉住（`AiOperationRowsTest`），
 * 尤其是三条最容易被写坏的边界：
 * - 动作名认不出来（老记录 / 后端换了 id）→ **如实写 id**，⛔ 不许编一个中文名；
 * - `user_name` 缺失（401 的请求、账号已注销）→ 写 `用户 #id` 或「未登录请求」，⛔ 不许留空
 *   （空白行会让人以为"没人做过"）；
 * - 失败但没有 `error` → 写「后端没有留下原因」，⛔ 不许显示成空白。
 */
object AiOperationRows {

    /** 「成功」/「失败 · 403」—— 失败时把状态码带上：排障第一步就是它。 */
    fun resultLabel(row: AiOperationDto): String =
        if (row.ok) "成功" else "失败 · " + row.statusCode

    /**
     * 动作名：动作表里认得出就写「中文名（动作 id）」，认不出就**只写 id**。
     *
     * 没有动作名的（`action == null`）**不是异常数据**：2026-10-09（CHG-0089）之前
     * 读动作不带头，那些老行在这本账里只有端点。如实写「未标动作（只读查询）」，
     * 而不是拿端点去猜一个动作名 —— 猜错的动作名比没有动作名危险得多。
     *
     * ⚠️ 2026-10-09 起读动作**也带头了**（CHG-0089）：读目录里的动作用**规范名**
     * （`invoices.list_invoices`），工具驱动的那批用**工具 id**（`inventory_alerts`）。
     * 两条都还没进 `AiWrites` 的动作表 ⇒ 页面上会**只显示 id**（这是"认不出就只写 id"
     * 那条规矩的正常结果，已记进台账 **L-58**：要不要给它们补中文名，另立新单）。
     */
    fun actionLabel(row: AiOperationDto): String {
        val id = row.action?.takeIf { it.isNotBlank() } ?: return "未标动作（只读查询）"
        val title = AiWrites.titleOf(id)
        return if (title == id) id else title + "（" + id + "）"
    }

    /** 端点：`POST /api/v1/orders`。这一列回答"它到底碰了哪个接口"。 */
    fun endpointLabel(row: AiOperationDto): String =
        (row.method.ifBlank { "?" }) + " " + row.path.ifBlank { "（没记端点）" }

    /** 谁：昵称优先 → `用户 #id` → 未登录。⛔ 不许出现空字符串（第一眼要看的就是"谁"）。 */
    fun whoLabel(row: AiOperationDto): String {
        val name = row.userName?.takeIf { it.isNotBlank() }
        if (name != null) return name
        val id = row.userId
        return if (id != null) "用户 #" + id else "未登录请求"
    }

    /** 耗时：不到 1 秒写毫秒，1 秒以上写秒（一位小数；⛔ 用 `Locale.US`，别跟着机器区域变小数点）。 */
    fun durationLabel(ms: Int): String =
        if (ms < 1000) "" + ms + " ms" else String.format(Locale.US, "%.1f s", ms / 1000.0)

    /** 失败原因：后端已经从响应体 `detail` 里摘好了一句人话；没有就如实说没有。 */
    fun errorLabel(row: AiOperationDto): String =
        row.error?.takeIf { it.isNotBlank() } ?: "后端没有留下原因（看状态码）"

    /** 时刻：naive UTC → 设备时区（直接印会早 8 小时，见 `util/TimeFmt.kt` 的注释）。 */
    fun whenLabel(row: AiOperationDto): String = formatDateTime(row.createdAt)
}
