package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.ExceptionOrderDto
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import com.tapmoay.sorders.data.remote.dto.OperationLogDto
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeParseException

/**
 * 「异常与审计」页的**分级与排序**（纯函数，有单测）。
 *
 * ### 为什么要有它（用户原话）
 * 「如果是因为上百条审计也翻不到到时候，我们就应该主动去做一个分类——按照危险层级、
 * 或者说按照紧急层级做一个排序分类优先级。」
 *
 * 把审计块提到前面（v3.26）只解决了"能不能找到入口"，解决不了"里面 300 条从哪看起"：
 * 一屏只能看 3~4 条，用户需要的是**最该先看的那几条自己浮上来**。
 *
 * ### 两个维度分开，不揉成一个分
 * - **危险层级**＝"这事放任下去会损失什么"：钱货风险 > 履约卡住 > 其它。
 *   它由**内容**决定（异常原因、动作性质），和什么时候发生的无关。
 * - **紧急层级**＝"拖了多久"：由时间决定。
 *
 * 揉成一个分数的问题是：用户没法核对（"为什么这条排前面？"），
 * 而分开之后排序规则可以一句话说清：**先按危险，同级按拖得久的**。
 */
enum class RiskLevel(val label: String) {
    /** 已经在赔钱／可能丢货：货损、拒收、短少。 */
    MONEY("钱货风险"),

    /** 单卡住了但还没赔钱：超期未送达、地址/联系不上、超时未派。 */
    STUCK("履约卡住"),

    /** 其它异常。 */
    OTHER("一般"),

    /**
     * **已经过去了的事**：不用处理，只是留档。
     *
     * 这一档是看了真实数据才加的——本机 275 条"异常"里有 119 条是这个：
     * 110 条「逾期送达」（**已经送到客户手里了**，只是迟到过）、9 条「已撤销/撤回订单」（终态）。
     * 它们把"待解决异常 274 单"这个数字撑到荒唐，真要看的那 9 条「超时未送」
     * 和 5 条人工标记（货损/地址找不到）就淹在里面了——
     * 用户说的"上百条翻不到"，根子在这里，不在排序。
     */
    PAST("已过去"),

    /** 已解决——不进"待处理"的排序。 */
    DONE("已解决"),
}

/** 审计动作的性质。用途是**分类筛选**（"我只想看改钱的"）。 */
enum class AuditKind(val label: String) {
    MONEY("改钱"),
    DELETE("删数据"),
    AUTH("账号权限"),
    STATE("改状态"),
    OTHER("其它"),
}

/**
 * 一条审计的"该不该先看"。
 *
 * 判据只有一条：**这个动作能不能让钱或数据悄悄变样**。
 * - 删数据（订单进回收站、删流水、删商品行）：**最先看**——改钱还能再改一次，
 *   删掉的那条可能就找不回来了（判据顺序上"删"优先于"钱"，单测钉着
 *   `LEDGER_DELETE` 必须归到删数据而不是改钱）
 * - 改钱（价格/运费/账本/收款）：错一个数字月底才发现 → 次高
 * - 账号权限（建号/改号/换角色/停用）：改错了是"别人能登进来"
 * - 改状态（派单/撤回/撤销/异常标记）：影响的是流程，看得见
 *
 * ⚠️ 光看动作名不够：**「改商品」既能改名字也能改单价**，而后者才是要盯的。
 *    后端的 `change_content` 里就是字段级 diff（`{"field":"default_unit_price",…}`），
 *    所以金额判定要**连内容一起看**——否则"我改了 12 次价"会被归到「其它」里沉底，
 *    而用户提这件事的起因正是"价格改动的审计翻不到"。
 */
fun auditKind(action: String, changeContent: String? = null): AuditKind = when {
    // ⚠️ 顺序有意义：`LEDGER_DELETE` 两个条件都命中，先判删除。
    action.contains("DELETE") || action.contains("REMOVE") -> AuditKind.DELETE

    action.contains("PRICE") || action.contains("FREIGHT") || action.contains("LEDGER") ||
        action.contains("PAY") || action.contains("CHARGE") || action.contains("RECEIPT") -> AuditKind.MONEY

    touchesMoney(changeContent) -> AuditKind.MONEY

    action.contains("USER") || action.contains("ROLE") || action.contains("PASSWORD") ||
        action.contains("ACTIVE") -> AuditKind.AUTH
    action.contains("DISPATCH") || action.contains("RECALL") || action.contains("CANCEL") ||
        action.contains("EXCEPTION") || action.contains("COMPLETE") || action.contains("RESTORE") -> AuditKind.STATE
    else -> AuditKind.OTHER
}

/** 这次改动是不是动了钱：看字段名，不看数字（"数量 2→3"也是数字，但不是钱）。 */
private fun touchesMoney(changeContent: String?): Boolean {
    val c = changeContent ?: return false
    val moneyFields = listOf("price", "freight", "amount", "fee", "total", "cost", "收款", "运费", "单价", "金额")
    return moneyFields.any { c.contains(it) }
}

/** 分类 → 危险层级：前两类是"能悄悄改坏东西"的，先看。 */
fun auditRisk(kind: AuditKind): RiskLevel = when (kind) {
    AuditKind.MONEY, AuditKind.DELETE, AuditKind.AUTH -> RiskLevel.MONEY
    AuditKind.STATE -> RiskLevel.STUCK
    AuditKind.OTHER -> RiskLevel.OTHER
}

/**
 * 异常单的危险层级。**按原因文字判**，因为后端异常单出参里没有金额字段——
 * 与其猜一个金额，不如用它真正给了的东西（原因 + 状态 + 日期）。
 *
 * ⚠️ 后端这个列表是**规则自动生成**的（`stats_service.auto_exception_reason`），
 * 不是只有人工标记的异常单。真机实测 275 条的构成：
 * 142 待派超时 / 110 逾期送达 / 9 已撤销 / 9 超时未送 / 5 人工标记（货损、地址找不到…）。
 * 所以"是不是还要做点什么"必须先判出来，否则列表里 4 成是**已经送到客户手里**的单。
 */
fun exceptionRisk(e: ExceptionOrderDto): RiskLevel {
    if (e.exceptionResolvedAt != null) return RiskLevel.DONE
    val r = e.exceptionReason
    // ① 已经过去的事：送到了（只是迟到）、或者单子已经撤销/撤回（终态）
    if (r.contains("逾期送达") || r.contains("已撤销") || r.contains("已撤回")) return RiskLevel.PAST
    // ② 已经在赔的（货损/拒收/短少/丢失）
    val money = listOf("货损", "破损", "损坏", "拒收", "短少", "丢失", "少了", "赔")
    if (money.any { r.contains(it) }) return RiskLevel.MONEY
    // ③ 卡住了：超时未送、超时未派、地址/联系不上
    val stuck = listOf("超时", "未送达", "没送到", "地址", "联系不上", "找不到", "延误", "逾期", "司机")
    if (stuck.any { r.contains(it) }) return RiskLevel.STUCK
    if (isOverdue(e)) return RiskLevel.STUCK
    return RiskLevel.OTHER
}

/**
 * 这一条还需要人做点什么吗？
 *
 * `false` 的不进"要处理"的列表，单独归到「已过去（留档）」——
 * 数字要分开报：把它们混在一起报成"待解决异常 274 单"，用户没法判断自己该干什么。
 */
fun exceptionNeedsAction(e: ExceptionOrderDto): Boolean = exceptionRisk(e) !in setOf(RiskLevel.PAST, RiskLevel.DONE)

/** 承诺送达时间已过、而且没送到。 */
private fun isOverdue(e: ExceptionOrderDto): Boolean {
    val due = parseDate(e.expectedDeliverBefore) ?: return false
    if (e.deliveredAt != null) return false
    return due.isBefore(LocalDate.now())
}

/**
 * 「拖了几天」：从下单日期算起（异常单出参里有 `order_date`）。
 * 解析不出来就是 0——**不猜**，也不因此崩。
 */
fun stuckDays(e: ExceptionOrderDto): Long {
    val start = parseDate(e.orderDate) ?: return 0
    val end = if (e.exceptionResolvedAt != null) parseDate(e.exceptionResolvedAt) else LocalDate.now()
    val d = java.time.temporal.ChronoUnit.DAYS.between(start, end ?: LocalDate.now())
    return if (d < 0) 0 else d
}

private fun parseDate(s: String?): LocalDate? {
    if (s.isNullOrBlank()) return null
    return try {
        LocalDate.parse(s.take(10))
    } catch (_: DateTimeParseException) {
        null
    }
}

internal fun parseDateTime(s: String?): LocalDateTime? {
    if (s.isNullOrBlank()) return null
    return try {
        LocalDateTime.parse(s.take(19))
    } catch (_: DateTimeParseException) {
        null
    }
}

/** 要处理的：危险层级 → 拖得久的 → 新的在前。 */
fun pendingExceptions(list: List<ExceptionOrderDto>): List<ExceptionOrderDto> =
    list.filter { exceptionNeedsAction(it) }
        .sortedWith(
            compareBy<ExceptionOrderDto> { exceptionRisk(it).ordinal }
                .thenByDescending { stuckDays(it) }
                .thenByDescending { it.orderDate }
                .thenByDescending { it.orderNo },
        )

/** 已过去（留档）：新的在前——它只是给对账/复盘看，没有处理顺序可言。 */
fun pastExceptions(list: List<ExceptionOrderDto>): List<ExceptionOrderDto> =
    list.filter { exceptionRisk(it) == RiskLevel.PAST }
        .sortedWith(compareByDescending<ExceptionOrderDto> { it.orderDate }.thenByDescending { it.orderNo })

/** 审计排序：危险层级 → 时间倒序（新的在前）。 */
fun sortedAudits(list: List<OperationLogDto>, kind: AuditKind? = null): List<OperationLogDto> =
    list.filter { kind == null || auditKind(it.action, it.changeContent) == kind }
        .sortedWith(
            compareBy<OperationLogDto> { auditRisk(auditKind(it.action, it.changeContent)).ordinal }
                .thenByDescending { parseDateTime(it.createdAt) ?: LocalDateTime.MIN },
        )

/** 分类筛选后每类的条数（给筛选条显示"改钱 12"用）。 */
fun auditCounts(list: List<OperationLogDto>): Map<AuditKind, Int> =
    AuditKind.entries.associateWith { k -> list.count { auditKind(it.action, it.changeContent) == k } }

/**
 * 把审计的 `change_content`（后端存的是 JSON）翻成人话。
 *
 * ### 为什么要重写一遍（v3.29 真机）
 * 第一版只认两种形状（`changes:[{field,from,to}]` 和嵌套的 `{before,after}`），
 * 其余**原样返回 JSON**——于是真机审计页上躺着这些：
 * ```
 * {"user_id": 162, "username": "13700008888", "phone": "13700008888",
 *  "restored": ["手机号", "用户名"], "conflicts": []}
 * {"user_id": 162, "username": "13700008888", "note": "软删除（可 POST /users/{id}/restore 恢复），手机号已释放"}
 * {"user_id": 162, "username": "13700008888", "full_name": "撤回测试账号", "role": "shipper", "is_member": false}
 * ```
 * 三宗罪：① 用户看不懂 JSON；② **内部编号 `user_id: 162` 直接露在屏幕上**（提示词里
 * 早写了"绝不允许出现内部编号"，页面却自己印）；③ `role: "shipper"`、`is_member: false`
 * 这种英文枚举没人看得懂。
 *
 * 现在**解析后按结构渲染**，并且保证输出里不出现 `{`/`}`/`"` 和 `*_id`。
 * 真解析不出来（不是 JSON）才当普通文本返回——那种情况它本来就是人话。
 */
fun auditChangeText(changeContent: String?): String {
    val c = changeContent?.trim().orEmpty()
    if (c.isEmpty()) return ""
    val obj = runCatching { Json.parseToJsonElement(c) as? JsonObject }.getOrNull()
        ?: return stripApiSpeak(c) // 不是 JSON：本来就是人话（只清掉 API 说法）
    val parts = mutableListOf<String>()

    // ① 逐字段改动：`changes: [{field, from, to}]`
    changesOf(obj).forEach { (field, from, to) ->
        val label = FIELD_CN[field] ?: field
        parts += when {
            from.isEmpty() && to.isEmpty() -> label
            from.isEmpty() -> "$label 设为 $to"
            to.isEmpty() -> "$label 清空（原 $from）"
            from == to -> "$label 仍是 $from"
            else -> "$label $from → $to"
        }
    }
    // ② 嵌套的 `{字段: {before, after}}`（改运费的形状）
    if (parts.isEmpty()) {
        obj.forEach { (k, v) ->
            val inner = v as? JsonObject ?: return@forEach
            val before = inner["before"]?.textOrNull() ?: return@forEach
            val after = inner["after"]?.textOrNull() ?: return@forEach
            parts += "${FIELD_CN[k] ?: k} $before → $after"
        }
    }
    // ③ 顶层 before/after（批量调价、专属价的形状）
    if (parts.isEmpty()) {
        val before = obj["before"]?.textOrNull()
        val after = obj["after"]?.textOrNull()
        if (after != null || before != null) {
            val who = obj["product"]?.textOrNull() ?: obj["name"]?.textOrNull()
            val target = obj["shipper"]?.textOrNull()
            val head = listOfNotNull(who, target?.let { "批发商：$it" }).joinToString(" ")
            val tail = when {
                before == null || before == "null" -> "设为 $after"
                after == null || after == "null" -> "清空（原 $before）"
                before == after -> "仍是 $before"
                else -> "$before → $after"
            }
            parts += listOf(head, tail).filter { it.isNotBlank() }.joinToString(" ")
        }
    }
    // ④ 兜底：**按已知标签逐个键值念**（绝不把 JSON 摆出去）
    if (parts.isEmpty()) {
        val account = obj["username"]?.textOrNull()
        GENERIC_KEYS.forEach { k ->
            if (k !in obj) return@forEach
            // 账号和电话是同一个值时只说一次（真机上就是 `username`=`phone`）——
            // 留「账号」而不是「电话」：用户想确认的是"动的是哪个账号"。
            if (k == "phone" && account != null && account == obj[k]?.textOrNull()) return@forEach
            val text = valueText(obj[k]) ?: return@forEach
            parts += "${FIELD_CN[k] ?: k} $text"
        }
    }
    return if (parts.isEmpty()) "（这条日志没有可读的明细）" else parts.joinToString("；")
}

/** `changes` 数组 → (字段, 改动前, 改动后)。 */
private fun changesOf(obj: JsonObject): List<Triple<String, String, String>> {
    val arr = obj["changes"] as? JsonArray ?: return emptyList()
    return arr.mapNotNull { it as? JsonObject }.mapNotNull { c ->
        val f = c["field"]?.textOrNull() ?: return@mapNotNull null
        Triple(f, c["from"]?.textOrNull().orEmpty().ifEmpty { "" }, c["to"]?.textOrNull().orEmpty().ifEmpty { "" })
    }
}

/** 逐个键值念的顺序（先念"这是谁"，再念"改了什么"）。 */
private val GENERIC_KEYS = listOf(
    "order_no", "name", "product", "shipper", "full_name", "username", "phone",
    "role", "is_member", "stock", "restored", "note",
)

/**
 * 值 → 人话。**空数组/空对象/编号一律不显示**：
 * `conflicts: []` 没有任何信息，`user_id: 162` 是内部编号（用户看不懂也做不了事）。
 */
private fun valueText(el: JsonElement?): String? {
    val s = el?.textOrNull() ?: run {
        val arr = el as? JsonArray ?: return null
        if (arr.isEmpty()) return null
        return arr.mapNotNull { it.textOrNull() }.joinToString("、").ifBlank { null }
    }
    if (s.isBlank() || s == "null") return null
    return when (s) {
        "true" -> "是"
        "false" -> "否"
        "shipper" -> "货主"
        "dispatcher" -> "派单员"
        "driver" -> "司机"
        else -> stripApiSpeak(s)
    }
}

private fun JsonElement.textOrNull(): String? = (this as? JsonPrimitive)?.content

/**
 * 清掉"代码话"：后端的说明里会带接口路径，例如
 * `软删除（可 POST /users/{id}/restore 恢复），手机号已释放` ——
 * 用户只需要知道"可恢复"，不需要知道是哪个接口。
 */
internal fun stripApiSpeak(s: String): String =
    Regex("（可\\s*(?:GET|POST|PATCH|DELETE|PUT)\\s+[^）]*?恢复）").replace(s, "（可恢复）")

// ---------------------------------------------------------------- 审计内容说人话

/** 字段名 → 中文。审计页上写 `default_unit_price: 20 → 5` 等于没写。 */
private val FIELD_CN = mapOf(
    "default_unit_price" to "默认单价", "special_unit_price" to "专属单价", "unit_price" to "单价",
    "cost_price" to "成本价", "price" to "价格", "freight_fee" to "司机运费", "line_total" to "行金额",
    "total_amount" to "总额", "amount" to "金额", "fee" to "费用", "quantity" to "数量",
    "stock" to "库存", "low_stock_alert" to "缺货提醒", "unit" to "单位", "name" to "名称",
    "full_name" to "姓名", "phone" to "电话", "detail_address" to "地址", "address_detail" to "送达地址",
    "origin_address" to "起点地址", "remark" to "备注", "internal_notes" to "内部备注",
    "is_active" to "上下架", "is_member" to "批发商", "delivery_description" to "送货说明",
    "driver_id" to "司机", "shipper_id" to "货主", "product_id" to "商品", "user_id" to "账号",
    "before" to "原值", "after" to "新值", "restored" to "恢复了", "note" to "说明",
    // 下面这几个是**第二遍真机**补上的：不然审计页上会出现 `order_no SOTEST…`、`role shipper`
    "order_no" to "订单", "username" to "账号", "role" to "角色",
    "shipper" to "批发商", "product" to "商品",
)

