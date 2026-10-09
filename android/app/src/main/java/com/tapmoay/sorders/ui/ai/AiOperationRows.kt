package com.tapmoay.sorders.ui.ai

import com.tapmoay.sorders.ai.AiReadCatalog
import com.tapmoay.sorders.ai.AiTools
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
     * 动作名：三张表依次认，认得出就写「中文名（动作 id）」，三张都认不出就**只写 id**。
     *
     * 为什么要认三张（2026-10-09，台账 L-58 / BUG-0020）：流水的 `action` 有**三种来源**，
     * 分别落在三张表里，谁也不是谁的子集 ——
     * 1. 写动作 → `AiWrites`（「恢复发票（invoices.restore）」这类本来就有中文名）；
     * 2. 读动作 → `AiReadCatalog` 的 `cn`（CHG-0089 起读动作也带头，形如 `invoices.list_invoices`）；
     * 3. 工具本身 → `AiTools` 的短名表（形如 `inventory_alerts`）。
     * 前两类都认不出时页面上只有一行英文 id，用户读不出它到底干了什么 —— 这就是 L-58 记的那件事。
     *
     * 没有动作名的（`action == null`）**不是异常数据**：2026-10-09（CHG-0089）之前
     * 读动作不带头，那些老行在这本账里只有端点。如实写「未标动作（只读查询）」，
     * 而不是拿端点去猜一个动作名 —— 猜错的动作名比没有动作名危险得多。
     */
    fun actionLabel(row: AiOperationDto): String {
        val id = row.action?.takeIf { it.isNotBlank() } ?: return "未标动作（只读查询）"
        val title = knownTitle(id)
        return if (title == id) id else title + "（" + id + "）"
    }

    /**
     * 三张表依次认（写动作 → 读目录 → 工具短名），**都认不出就把 id 原样返回**
     * （调用方靠"返回值等于入参"判断没认出来，⛔ 不许在这里编一个中文名兜底）。
     *
     * 读目录那张表给的是**一整句话说明**（"某商品某段时间的卖法…"），直接印在流水列上会挤成一片，
     * 所以只取它开头的表名（见 [readTitle]）。顺序不许调换：写动作的表最具体，先认。
     */
    private fun knownTitle(id: String): String {
        val write = AiWrites.titleOf(id)
        if (write != id) return write
        AiReadCatalog.find(id)?.let { return readTitle(it.cn) }
        return AiTools.titleOf(id)
    }

    /**
     * 读目录那条说明的**短名**：第一个「（」之前的表名（"商品（某段时间的卖法…）" → "商品"）。
     *
     * ⛔ 不许改读目录本身 —— `AiReadCatalog.kt` 是 `_tools/ai/_gen_ai_read_catalog.py`
     * 机器生成的（手改会被 `--check` 抓）；短名在这里现场推导，产物一个字节都不用动。
     * 说明整句没有括号时原样用整句；万一剥出来是空的，也退回整句 —— ⛔ 这一列不许变空白。
     */
    internal fun readTitle(cn: String): String {
        val short = cn.substringBefore("（").substringBefore("(").trim()
        return short.ifEmpty { cn.trim() }
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
