package com.tapmoay.sorders.ui.messages

import com.tapmoay.sorders.ui.nav.Role
import com.tapmoay.sorders.ui.nav.Routes
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/**
 * 消息卡片的**分级**：类型 → 颜色、severity → 风险档、payload 里被点名的重点词、
 * 以及「点这张卡该去哪一页 + 链接文案」（FEAT-0019，2026-10-11 用户口径）。
 *
 * 用户的验收口径（逐字要点）：
 * - 「按消息类型做颜色区别，而且**只有未读**才有这个样式，**已读所有消息一个样**」；
 * - 卡片最左边一条 **6px 方角竖条**（颜色 = 该消息类型对应**工作台那一格**的颜色）+ 同色小标签；
 * - 后来**否掉「整条正文上色」**：「你的文字不能全部用颜色给他去搞出来……我们的真正的重心是
 *   这几个字：第一**库存不足**、以及现在还剩多少库存的那个个数……其他的文字你用正常的黑色
 *   就可以了。因为只有这些信息才是重点。你要记住一点：**全是重点就是没有重点**。」
 *   ⇒ 只有 `payload["emphasis"]` 里**被业务点名**的词与数字上色（客户端**不猜**哪个词重要）；
 * - 已读：竖条、彩标、**高亮一并去掉**，整条灰调。
 *
 * ⛔ 这个文件是「type → 色 / 风险色 / 重点词 / 该去哪一页」的**唯一一处**实现
 *    （`_tools/qa/_check_message_card_grading.py` 钉着「只有这一处」）。界面代码只管画，
 *    ⛔ 不许在界面里再写一遍这几个映射。
 * ⛔ 退货申请那条线不在这里重写：先调 [noticeReturnRoute]（`ui/messages/NoticeRouting.kt`），
 *    它认不出来才由本文件兜后面的类型 —— 「申请单号 → 去派单端还是货主端」的规则只有那一处。
 */
// ---------------------------------------------------------------------------
// 1) 类型 → 颜色（**工作台那一格的色**）
// ---------------------------------------------------------------------------
//
// ⚠️ 这里写的是**字面量**，不是 `ui/theme/Color.kt` 的语义色 token：CHG-0091 / CHG-0101 整体
//    换色之后那几个 token 的值已经与用户过目的样本对不上（例：`InfoBlue` 现在 = ThemeGreen、
//    `ProgressYellow` 现在 = 0xFF91871D）。用户是照样本里这 11 个色点头的（样式表
//    `_tmp/palette_demo/messages_all.html`），所以样本值就是本单的权威 —— 两边的分叉在这里
//    留一句，别再各改各的（工作台要跟着换色时，这里与样本一起重新对一遍）。
//
// ⛔ 一个族一个色，不许在别处再写第二个色表（颜色写两处 = 同一种消息两种颜色）。

/** 订单类（工作台「订单管理」那一格）：待接单 / 已接单 / 改价 / 退货申请 … */
const val MSG_COLOR_ORDER = 0xFF1E6FFFL

/**
 * 已送达（订单走完）：**语义绿**，与 `ui/common/SegmentedStatusTabs.kt` 的「已送达 · 绿」同一支
 * （`ui/driver/DriverOrdersScreen.kt` 注释里点名的 `0xFF00AC6E`）。
 *
 * ⚠️ 样本 `_tmp/palette_demo/messages.html` 画的是老绿 `#00B578`：那个值已被 CHG-0091/0101/0105 换掉，
 * 而且 `_tools/qa/_check_low_sat_palette.py` 的 `NEW_MUST_GONE` 明令**一处都不许留** ⇒ 这里取现行值，
 * 与「已送达」状态页签的颜色**同源**（用户要的「工作台那一格的色」在换色后就是这个）。
 */
const val MSG_COLOR_DONE = 0xFF00AC6EL

/** 撤销 / 删单（工作台「我的订单」那一格）：order.revoked / order.cancelled* / order.deleted。 */
const val MSG_COLOR_VOID = 0xFF917A16L

/** 库存（工作台「库存管理」那一格）：不足 / 偏低。 */
const val MSG_COLOR_STOCK = 0xFF008EABL

/** 钱进来（工作台「客户收款」那一格）：收款到账、欠款超限提醒。 */
const val MSG_COLOR_RECEIPT = 0xFF9C88E0L

/** 钱出去（工作台「供应商」那一格）：应付将到期 / 已逾期。 */
const val MSG_COLOR_PAYABLE = 0xFFE05288L

/** 发票台账那一格。 */
const val MSG_COLOR_INVOICE = 0xFFE08034L

/** 下游定价那一格：商品价格调整。 */
const val MSG_COLOR_PRICE = 0xFFB65DC4L

/** 车辆管理那一格：年检提醒。 */
const val MSG_COLOR_VEHICLE = 0xFF00AAAEL

/** 账户管理那一格：新设备登录 / 解冻。 */
const val MSG_COLOR_ACCOUNT = 0xFFAC7217L

/** 消息中心那一格（兜底色）：系统公告与认不出来的 type。 */
const val MSG_COLOR_SYSTEM = 0xFFE07B80L

/**
 * 消息族 = 「同一种颜色 + 同一套去向」的那一组类型。
 *
 * [label] 是卡片上那个小标签的**缺省**文案；发消息那边可以在 `payload["label"]` 里给更具体的
 * （例：「库存预警」下面再细分「临期预警」），给了就用它的。
 */
enum class MessageFamily(val label: String, val color: Long) {
    ORDER("订单", MSG_COLOR_ORDER),
    ORDER_DONE("已送达", MSG_COLOR_DONE),
    ORDER_VOID("订单撤销", MSG_COLOR_VOID),
    STOCK("库存预警", MSG_COLOR_STOCK),
    RECEIPT("客户收款", MSG_COLOR_RECEIPT),
    ARREARS("欠款提醒", MSG_COLOR_RECEIPT),
    PAYABLE("应付账款", MSG_COLOR_PAYABLE),
    INVOICE("发票", MSG_COLOR_INVOICE),
    PRICE("价格调整", MSG_COLOR_PRICE),
    VEHICLE("车辆提醒", MSG_COLOR_VEHICLE),
    ACCOUNT("账号安全", MSG_COLOR_ACCOUNT),
    SYSTEM("系统公告", MSG_COLOR_SYSTEM),
}

/** 已送达：`backend/app/services/message_center.py` 的三个 order.delivered* 类型。 */
private val ORDER_DONE_TYPES = setOf("order.delivered", "order.delivered_driver", "order.delivered_dispatcher")

/** 撤销 / 删单：被撤销、被取消、被删除。 */
private val ORDER_VOID_TYPES = setOf("order.revoked", "order.cancelled", "order.cancelled_dispatcher", "order.deleted")

/**
 * 库存：不足（`stock.low`，danger）/ 偏低（`stock.near_low`，warn）。
 *
 * 后端 FEAT-0019 定名（2026-10-11 后端会话对齐）：`stock.low` = 低于**报警阈值**、
 * `stock.near_low` = 低于**建议水位**；`stock.shortage` 是早先的名字，留着不删（老消息还认得出）。
 */
private val STOCK_TYPES = setOf("stock.low", "stock.near_low", "stock.shortage")

/** 收款：到账 / 撤销。 */
private val RECEIPT_TYPES = setOf("receipt.received", "receipt.undone")

/** 欠款：超额度提醒。 */
private val ARREARS_TYPES = setOf("arrears.over_limit")

/** 应付：将到期 / 已逾期 / 已付。 */
private val PAYABLE_TYPES = setOf("payable.due_soon", "payable.overdue", "payable.paid")

/** 发票：开具 / 作废。 */
private val INVOICE_TYPES = setOf("invoice.issued", "invoice.voided")

/** 价格：后端既有的 price_change（`backend/app/api/v1/notifications.py`）。 */
private val PRICE_TYPES = setOf("price_change", "price.changed")

/**
 * 车辆：年检提醒（FEAT-0022）。
 *
 * `vehicle.inspection_due` = 距到期 ≤30 天（后端给 severity=warn）；
 * `vehicle.inspection_overdue` = **已经过期**（severity=danger，2026-10-11 新增的那一条）。
 * 两条都归车辆族（竖条 `MSG_COLOR_VEHICLE` #00AAAE）；⛔ 认新类型只改这一行 ——
 * 上色档走 [riskOf] / [emphasisColor]，渲染逻辑一个字都不用动。
 */
private val VEHICLE_TYPES = setOf("vehicle.inspection_due", "vehicle.inspection_overdue")

/**
 * 账号：新设备登录（`account.new_device_login`，danger）/ 设备解冻（`account.device_unfrozen`，info）/ 冻结。
 *
 * 后端 FEAT-0019 定名（2026-10-11 对齐）；`account.new_device` / `account.unfrozen` 是早先的短名，
 * 留着不删（老消息还认得出）。
 */
private val ACCOUNT_TYPES = setOf(
    "account.new_device_login", "account.device_unfrozen", "account.new_device", "account.unfrozen", "account.frozen",
)

/** 系统：公告，以及后端既有的 ledger_export / order_purge_blocked / driver_bill_cancelled。 */
private val SYSTEM_TYPES = setOf(
    "system", "announcement", "ledger_export", "order_purge_blocked", "driver_bill_cancelled",
)

/** 后端 type 字符串 → 族。认不出来 = [MessageFamily.SYSTEM]（兜底色 + 不跳）。 */
fun familyOf(type: String): MessageFamily {
    val t = type.trim().lowercase()
    return when {
        t in ORDER_DONE_TYPES -> MessageFamily.ORDER_DONE
        t in ORDER_VOID_TYPES -> MessageFamily.ORDER_VOID
        t in STOCK_TYPES -> MessageFamily.STOCK
        t in RECEIPT_TYPES -> MessageFamily.RECEIPT
        t in ARREARS_TYPES -> MessageFamily.ARREARS
        t in PAYABLE_TYPES -> MessageFamily.PAYABLE
        t in INVOICE_TYPES -> MessageFamily.INVOICE
        t in PRICE_TYPES -> MessageFamily.PRICE
        t in VEHICLE_TYPES -> MessageFamily.VEHICLE
        t in ACCOUNT_TYPES -> MessageFamily.ACCOUNT
        t in SYSTEM_TYPES -> MessageFamily.SYSTEM
        // 后端订单域的类型都是 order.*（含 order.return_request* 那一族）——
        // 以后新增一个 order.xxx 不用回来改这张表，也不会掉进「认不出来」的兜底里。
        t.startsWith("order.") -> MessageFamily.ORDER
        else -> MessageFamily.SYSTEM
    }
}

/** 卡片小标签：`payload["label"]` 优先（发消息那边点名），没有就退回 [MessageFamily.label]。 */
fun messageLabel(type: String, payload: Map<String, JsonElement>?): String {
    val custom = (payload?.get(KEY_LABEL) as? JsonPrimitive)?.contentOrNull?.trim()
    return if (custom.isNullOrEmpty()) familyOf(type).label else custom
}

// ---------------------------------------------------------------------------
// 2) severity → 风险档（**只**决定被点名片段用什么色）
// ---------------------------------------------------------------------------

/** 风险档。后端 `NotificationOut.severity` 是 info | warn | danger。 */
enum class MessageRisk { INFO, WARN, DANGER }

/** 危险：样本里的红。 */
const val MSG_TEXT_DANGER = 0xFFD93025L

/** 警告：样本里的橙。 */
const val MSG_TEXT_WARN = 0xFFE07B00L

/** 后端 `severity` 字符串 → 风险档；认不出来 / 缺字段（旧响应）= [MessageRisk.INFO]。 */
fun riskOf(severity: String?): MessageRisk = when (severity?.trim()?.lowercase()) {
    "danger" -> MessageRisk.DANGER
    "warn", "warning" -> MessageRisk.WARN
    else -> MessageRisk.INFO
}

/**
 * 被点名片段该上的色。
 *
 * null = **不上风险色**（info 档：常规深色 + 加粗，样本里「收款 320.00 元」就是这样）。
 * ⛔ 这张表是「风险 → 颜色」的唯一一处：界面里再写一遍 `0xFFD93025` 就是第二处。
 */
fun emphasisColor(risk: MessageRisk): Long? = when (risk) {
    MessageRisk.DANGER -> MSG_TEXT_DANGER
    MessageRisk.WARN -> MSG_TEXT_WARN
    MessageRisk.INFO -> null
}

// ---------------------------------------------------------------------------
// 3) `payload["emphasis"]` → 该上色的片段
// ---------------------------------------------------------------------------

/** 发消息那边点名的重点词列表（例如 `["库存不足","8"]`；没有重点词就给空列表）。 */
const val KEY_EMPHASIS = "emphasis"

/** 可选：这张卡小标签的文案（不给就用族名）。 */
const val KEY_LABEL = "label"

/**
 * 取出被点名的重点词。
 *
 * 兼容三种写法：JSON 数组（权威写法，后端就是它）、单个字符串、逗号分隔的字符串 ——
 * 后两种只是为了让手写 / AI 发的消息不至于一个字都不上色。**顺序保留**、去空白、去重。
 * ⛔ 这里**不判断这个词在不在正文里**：找不到 = 那一段自然不上色（见 [splitByEmphasis]），
 *    绝不因为「找不到」就退化成整行上色。
 */
fun emphasisWords(payload: Map<String, JsonElement>?): List<String> {
    val raw = payload?.get(KEY_EMPHASIS) ?: return emptyList()
    val items: List<String> = when (raw) {
        is JsonArray -> raw.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
        is JsonPrimitive -> raw.contentOrNull?.split(",").orEmpty()
        else -> emptyList()
    }
    return items.map { it.trim() }.filter { it.isNotEmpty() }.distinct()
}

/** 正文切出来的一段。[emphasized] = 这一段是被点名的重点（要加粗 + 上风险色）。 */
data class MessageTextSpan(val text: String, val emphasized: Boolean)

/**
 * 把正文按重点词切成若干段 —— 界面据此只给**被点名的片段**上色，其余原样。
 *
 * 规则：
 * - 从前往后扫，命中就切一段出来；重叠时**先匹配长的**（点了 `["库存不足","不足"]` 时
 *   「库存不足」整段算重点，而不是把「不足」单拎出来）；
 * - 同一个词在正文里出现几次就标几次；**词不在正文里 = 不标**（不报错、不整行标）；
 * - 重点词为空 = 整段正文一段，一个字都不上色。
 */
fun splitByEmphasis(text: String, words: List<String>): List<MessageTextSpan> {
    if (text.isEmpty()) return emptyList()
    val needles = words.map { it.trim() }.filter { it.isNotEmpty() }.distinct().sortedByDescending { it.length }
    if (needles.isEmpty()) return listOf(MessageTextSpan(text, false))
    val spans = mutableListOf<MessageTextSpan>()
    val plain = StringBuilder()
    var i = 0
    while (i < text.length) {
        val hit = needles.firstOrNull { text.startsWith(it, i) }
        if (hit == null) {
            plain.append(text[i])
            i++
        } else {
            if (plain.isNotEmpty()) {
                spans += MessageTextSpan(plain.toString(), false)
                plain.clear()
            }
            spans += MessageTextSpan(hit, true)
            i += hit.length
        }
    }
    if (plain.isNotEmpty()) spans += MessageTextSpan(plain.toString(), false)
    return spans
}

// ---------------------------------------------------------------------------
// 4) 这张卡该去哪一页 + 链接文案
// ---------------------------------------------------------------------------

/**
 * 点这张卡去哪儿 —— 传的是**整条路由**（`?focus=` 已经拼好）。
 *
 * ⛔ 认不出来就返回 null（**不跳**）。老的那条兜底（2026-09-21 起就有：payload 里带 `order_id`
 *    就开订单详情）只留给**认不出的 type**（见下面 `SYSTEM` 那一支）：缺键 / 值不是正整数 = 不跳，
 *    绝不瞎跳（跳错页比不跳更难查：用户看到的是 403 或一张空列表）。
 * ⛔ 角色用**登录缓存原文 key**（[Role.DISPATCHER.key]）比较，不经过 `Role.fromKey`：
 *    那个函数对空串会回落成货主，「会话还没恢复」的一瞬间就会被当成货主。
 */
fun noticeRoute(roleKey: String?, type: String, payload: Map<String, JsonElement>?): String? {
    // 退货申请（4 个 type）仍由 NoticeRouting 一处算 —— 那里还带着「该去派单端还是货主端」的规则。
    noticeReturnRoute(roleKey, type, payload)?.let { return it }
    return when (familyOf(type)) {
        // 订单类：那张订单的详情页（货主 / 派单员 / 司机都能开）。
        MessageFamily.ORDER -> longAt(payload, "order_id")?.let { Routes.orderDetail(it) }
        // 已送达：派单员看账本（样本的链接文案就是「查看账本 ›」），货主看自己的账本。
        MessageFamily.ORDER_DONE -> when {
            isDispatcher(roleKey) -> Routes.LEDGER_HOME
            isShipper(roleKey) -> Routes.SHIPPER_LEDGER
            else -> longAt(payload, "order_id")?.let { Routes.orderDetail(it) }
        }
        MessageFamily.ORDER_VOID -> longAt(payload, "order_id")?.let { Routes.orderDetail(it) }
        // 库存：直达库存管理页并**定位到那个商品**（`?focus=`，见 [Routes.inventory]）。
        MessageFamily.STOCK -> longAt(payload, "product_id")?.let { Routes.inventory(it) }
        MessageFamily.RECEIPT -> if (isDispatcher(roleKey)) Routes.DISPATCH_RECEIPTS else null
        MessageFamily.ARREARS -> when {
            isDispatcher(roleKey) -> Routes.REPORT_CUSTOMER_BALANCES
            isShipper(roleKey) -> Routes.SHIPPER_LEDGER
            else -> null
        }
        MessageFamily.PAYABLE -> if (isDispatcher(roleKey)) Routes.DISPATCH_SUPPLIERS else null
        MessageFamily.INVOICE -> if (isDispatcher(roleKey)) Routes.INVOICES else null
        // 价格：货主看的是「卖给他的价」（下游定价页），派单员看的是那个商品的定价。
        MessageFamily.PRICE -> when {
            isShipper(roleKey) -> Routes.SHIPPER_PRICES
            isDispatcher(roleKey) -> longAt(payload, "product_id")?.let { Routes.priceByProduct(it) }
            else -> null
        }
        // 车辆年检 / 系统公告：样本里就没有链接 —— 不跳。
        MessageFamily.VEHICLE -> null
        MessageFamily.ACCOUNT -> if (isDispatcher(roleKey)) Routes.ACCOUNTS else null
        // 认不出的 type：走**老兜底**（2026-09-21 就有）—— payload 里带了订单号就开那张订单，
        // 免得 AI 发的自定义消息、以后新增的类型「点了没反应」。
        // ⛔ 前提是 payload 里**真有** order_id：没有就是 null = 不跳（缺键绝不瞎跳）。
        MessageFamily.SYSTEM -> longAt(payload, "order_id")?.let { Routes.orderDetail(it) }
    }
}

/** 链接文案（样本：「查看库存 ›」「去付款 ›」…）；null = 这类消息不画链接。 */
fun noticeActionLabel(type: String): String? = when (familyOf(type)) {
    MessageFamily.ORDER -> "查看订单"
    MessageFamily.ORDER_DONE -> "查看账本"
    MessageFamily.ORDER_VOID -> if (type.trim().lowercase().endsWith("deleted")) "查看详情" else "查看订单"
    MessageFamily.STOCK -> "查看库存"
    MessageFamily.RECEIPT -> "查看收款"
    MessageFamily.ARREARS -> "查看欠款"
    MessageFamily.PAYABLE -> "去付款"
    MessageFamily.INVOICE -> "查看发票"
    MessageFamily.PRICE -> "查看价格"
    MessageFamily.VEHICLE -> null
    MessageFamily.ACCOUNT -> "查看设备"
    MessageFamily.SYSTEM -> null
}

private fun isDispatcher(roleKey: String?): Boolean = roleKey == Role.DISPATCHER.key

private fun isShipper(roleKey: String?): Boolean = roleKey == Role.SHIPPER.key

/** payload 里的正整数（id）。缺键 / 不是数 / <= 0 一律 null ⇒ 调用方不跳。 */
private fun longAt(payload: Map<String, JsonElement>?, key: String): Long? =
    (payload?.get(key) as? JsonPrimitive)?.contentOrNull?.trim()?.toLongOrNull()?.takeIf { it > 0L }
