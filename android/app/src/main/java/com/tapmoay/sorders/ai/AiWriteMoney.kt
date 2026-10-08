package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.OrderStatusModel
import com.tapmoay.sorders.ui.order.DISCOUNT_KIND_AMOUNT
import com.tapmoay.sorders.ui.order.DISCOUNT_KIND_PERCENT
import com.tapmoay.sorders.ui.order.canDiscount
import com.tapmoay.sorders.ui.order.discountKindLabel
import com.tapmoay.sorders.ui.order.discountSummary
import com.tapmoay.sorders.ui.order.discountValueError
import com.tapmoay.sorders.ui.order.discountValueToSend
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put

/**
 * 钱相关四条（CHG-0087 / 台账 L-56，2026-10-08）：给一单**定价**、**让价**、**取消让价**、设挂账**额度**。
 *
 * ### 为什么这四条当初被写在「本轮不开放」里，现在又能做了
 * 四条被挡住的原因**不是**能力缺口，是**一次问一件事**：
 * - 定价原来要同时定「多少钱 + 哪个分类 + 要不要顺手沉淀成价目」；
 * - 让价原来要同时定「方式 + 值 + 范围 + 理由」；
 * - 额度是「这个单位还能赊多少」，一次改动直接决定挂账收不收得住。
 * 四五个决定挤在一张卡上，用户读完已经不知道该看哪一行。现在每一条都**只问一件事**：
 * 多少钱（分类可留空、沉淀不做）／让多少（范围可以整单）／取消（只有单号）／额度（一个数）。
 * 被砍掉的那几件（顺手沉淀价目、让价的其它花样）**写在卡片和说明书里**，不做哑巴砍。
 *
 * ### 这四条各自最容易搞混的一处（卡片上逐条写明，别让用户猜）
 * 1. **定价 ≠ 改司机运费**：`orders.freight`（改司机运费）走普通改单 `PATCH /orders/{id}`、只改一个数；
 *    这一条走 `POST /orders/{id}/price-freight`，**连运费分类一起定**，而且已送达 / 已退货的单只要
 *    定过价就锁死（后端原话：事后改运费不会动司机账单，只会在两个页面上显示两个数）。
 * 2. **让价是整单替换，不是叠加**（`services/order_discount.py::apply_discount` 是幂等替换）：
 *    再让一次＝按新值重算；每一行的金额由**服务端**算，客户端一个乘法都不做。
 * 3. **取消让价是按快照精确还原**（`clear_discount` 用的是当时记下的 `before`），
 *    不是拿单价 × 数量重算 —— 老数据没有逐行快照时后端按整单处理。
 * 4. **额度「不限额」≠「额度 0 元」**：前者这个单位还能赊，后者一分钱都不许赊。
 *    后端正是这么分的（`ArrearsUnitEditRequest.credit_limit` 用**非空** `JsonElement`，
 *    `null` 是合法取值＝清空），所以这里的 payload 也用 `JsonNull` 表达"不限额"。
 *
 * ### 撤回：两条有按钮、两条没有（理由写在 `AiRevert` 的"撤不回来"表里）
 * - `orders.discount_clear` / `arrears_unit.set_credit_limit` **有**撤回：
 *   取消让价按快照把上一套让价整份打回去（`AiInverse` 成对动作）；额度按快照写回旧值
 *   （`AiResource.nullableWritable` 让"原来是不限额"也能写回 `JsonNull`）。
 * - `orders.price_freight` / `orders.discount` **没有**撤回按钮，而且是**刻意的**：
 *   这两条写下去之前不确定该撤到哪一套 —— 定价的常态是给**从没定过价**的单定价（旧运费是空，
 *   而 `AiRevert.patchPlan` 写不回去的键会**从撤回 payload 里消失**，剩下的键又缺必填项），
 *   让价则可能是"第一次让价"也可能是"替换上一套"。真给按钮的话，卡片最后一行会承诺一个
 *   常常不出现的按钮 —— 与其骗一次点击，不如如实写「要改就说一句…」。
 *
 * ### 键名纪律
 * payload 的键名**就是撤回快照的键名**（`AiResources.kt` 的文件头第 2 条）：撤回是把旧值塞回
 * 同一条写路径，那条路读的是 payload 键。所以：
 * - 定价：`order_id` / `freight_fee` / `freight_category_id`（缺席＝清空分类，与后端一致）；
 * - 让价：`order_id` / `discount_kind` / `discount_value` / `discount_line_ids` / `discount_reason`；
 * - 取消让价：只有 `order_id`；额度：`unit_id` / `credit_limit`。
 *
 * ### 这一条由谁钉住
 * - 判据：`_tools/qa/_check_ai_money.py`（反向验证：`_tools/qa/_reverse_verify_ai_money.py`）。
 */
internal object AiWriteMoney {

    val ACTIONS: List<AiWriteAction> = listOf(
        AiWriteAction(
            id = AiWrites.ORDERS_PRICE_FREIGHT,
            title = "给这一单定司机运费",
            // MEDIUM：与「改司机运费」同一个档位 —— 改的是这一单给司机多少钱，写错了还能再改一次。
            // ⛔ 不取 LOW：它动的是钱（司机账单）。也不取 HIGH：它不是"撤不回来"的那一类，
            //    送达之前随时能再定一次价。
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ORDER,
            blurb = "定这一单给司机多少钱（派单员当场判断的那个数），可以连「运费分类」一起定。" +
                "⚠️ 它和「改司机运费」不是同一条路：那一条是普通改单（只改一个数、不动分类），" +
                "这一条是定价 —— 已送达 / 已退货的单只要定过价就锁死了" +
                "（事后改运费不会动司机账单，只会在两个页面上显示两个数），要动得走司机结算那边。" +
                "这一步**不顺手沉淀价目**（要沉淀请到运费定价页勾一下）。",
            params = listOf(
                AiWriteParam(
                    name = "order",
                    cn = "订单号",
                    required = true,
                    hint = "完整订单号（形如 SOTEST2026091100230）",
                ),
                AiWriteParam(
                    name = "freight",
                    cn = "司机运费（元）",
                    required = true,
                    kind = AiWriteParamKind.NUMBER,
                    hint = "元。可以填 0（＝这一单不收运费）",
                ),
                AiWriteParam(
                    name = "category",
                    cn = "运费分类",
                    hint = "分类名（如「市内」）。说「不适用」＝不套分类；不说＝沿用现在的分类",
                ),
            ),
        ),
        AiWriteAction(
            id = AiWrites.ORDERS_DISCOUNT,
            title = "给这一单让价",
            // HIGH：它改写**每一行**的金额（退货也按折后实付退），而且这一步没有撤回按钮。
            // 与押金 / 收款同一档：动钱、且要用户看清"影响谁"。
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_ORDER,
            blurb = "给这单让价：抹零（减一个金额）或减百分比（减几个点）；可以只让某几个商品，" +
                "不说就是整单。⚠️ 一张单只有一套让价：再让一次是**整单替换**、不是叠加。" +
                "每一行的金额由后台重算（这里不预演：抹零会被「最后一行没那么多钱」改小）。" +
                "退货按折后实付退。",
            params = listOf(
                AiWriteParam(name = "order", cn = "订单号", required = true, hint = "完整订单号"),
                AiWriteParam(
                    name = "kind",
                    cn = "让价方式",
                    required = true,
                    kind = AiWriteParamKind.ENUM,
                    enumValues = listOf("抹零", "减百分比"),
                    hint = "抹零 = 减掉一个金额；减百分比 = 减几个点",
                ),
                AiWriteParam(
                    name = "value",
                    cn = "让多少",
                    required = true,
                    kind = AiWriteParamKind.NUMBER,
                    hint = "抹零：减掉的元数（如 3.5）；减百分比：减掉的点数（如 10 表示减 10%）",
                ),
                AiWriteParam(
                    name = "lines",
                    cn = "只让哪几个商品",
                    hint = "商品名，一个或多个，用「、」分开，例如 红富士苹果、香蕉。不说 = 整单",
                ),
                AiWriteParam(name = "reason", cn = "理由", hint = "可选，一句话（会写进操作日志）"),
            ),
        ),
        AiWriteAction(
            id = AiWrites.ORDERS_DISCOUNT_CLEAR,
            title = "取消这一单的让价",
            // HIGH：动钱（把客户该付的金额还原成原价），与上面那一条是同一张卡的两面。
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_ORDER,
            blurb = "把这一单的让价取消掉：每一行的金额还原成打折前的值（按当时记下的快照精确还原，" +
                "不是拿单价 × 数量重算）。本来就没有让价的单会被拒。取消之后这一单就是原价。",
            params = listOf(
                AiWriteParam(name = "order", cn = "订单号", required = true, hint = "完整订单号"),
            ),
        ),
        AiWriteAction(
            id = AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT,
            title = "设挂账单位的额度",
            // HIGH：额度＝这个单位还能赊多少，直接决定挂账收不收得住（后端每次改动都写一条流水）。
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_LEDGER,
            blurb = "设这个挂账单位「还能赊多少」。说「不限额」＝把额度清空（还能赊）；" +
                "⚠️ 它和「额度 0 元」（一分钱都不许赊）是两件事。每次改动都会在后台留一条流水" +
                "（谁改的、改前改后各是多少）。",
            params = listOf(
                AiWriteParam(
                    name = "unit",
                    cn = "挂账单位",
                    required = true,
                    hint = "单位名（挂账单位名册里的名字）",
                ),
                AiWriteParam(
                    name = "limit",
                    cn = "额度（元）",
                    required = true,
                    kind = AiWriteParamKind.NUMBER,
                    hint = "元，0 表示一分钱都不许赊；说「不限额」＝清空额度",
                ),
            ),
        ),
    )
}

// ============================================================ 定价（`POST /orders/{id}/price-freight`）

/** 已送达 / 已退货：这两个状态**只**在"从来没定过价"时才还能定价（后端留的口子）。 */
private val LOCKED_AFTER_DELIVERY = setOf("DELIVERED", "RETURNED")

private const val STATUS_CANCELLED = "CANCELLED"

/**
 * 用户说「不适用」时，要的是**不套分类**（而不是"没说"）。
 *
 * ⚠️ 这两个在定价端点上结果不同：后台的判据是 `category_id` —— **给了就用它、没给就清空**
 * （`orders_assignment.py:165` 原话：「分类：给了就用它（并把名字快照写下来），没给就清空」；
 * `OrderFreightPriceBody.category_id` 的默认值就是 `None`，所以"键不在请求体里"与"发一个 null"
 * 在后端是**同一个结果：清空分类**）。所以「没说」绝不能翻成"发一个 null" —— 必须把**当前分类的编号**
 * 原样发回去（见下面的 `categoryOf`）。
 */
private val NO_CATEGORY_WORDS = setOf(
    "不适用", "不用", "无", "没有", "去掉", "清空", "不套分类", "不挂分类", "不属于任何分类", "none",
)

/**
 * 定价这一条在弹卡之前先判的三件事（**AI 侧不许弹一张注定失败的卡**）。
 *
 * 三条话术都来自后端 `api/v1/orders_assignment.py::price_freight` 的**原话**，不是我们编的：
 * 1. 已撤销 ⇒ 400「这一单已经撤销了，不用再定价」；
 * 2. 已送达 / 已退货 **且已经定过价** ⇒ 400「…事后改运费不会动司机账单，只会在两个页面上显示两个数」；
 * 3. 已送达 / 已退货但**从来没定过价**是**合法**的（后端留的口子：补定价之后那张还没结算的应付明细
 *    会跟着改）—— 别一律拒，那是后端故意留的。
 */
private fun requirePriceable(order: AiOrderRef) {
    val status = order.status.uppercase()
    if (status == STATUS_CANCELLED) {
        throw AiWriteArgException("这一单已经撤销了，不用再定价。请如实告诉用户，不要换一张单去操作。")
    }
    if (status in LOCKED_AFTER_DELIVERY && !order.freightFee.isNullOrBlank()) {
        throw AiWriteArgException(
            "这一单已经" + order.statusCn + "、而且已经定过运费了 —— 已送达的单运费是锁定的" +
                "（事后改运费不会动司机账单，只会在两个页面上显示两个数）。" +
                "要改请让用户去司机结算那边处理。",
        )
    }
    if (status !in OrderStatusModel.FREIGHT_EDITABLE && status !in LOCKED_AFTER_DELIVERY) {
        throw AiWriteArgException(
            "这一单现在是「" + order.statusCn + "」，这个状态定不了运费。请如实告诉用户。",
        )
    }
}

/** 这次要写进去的分类：[id] 为 null = 清空；[kept] = 沿用原来那个（卡片上要写明"沿用"）。 */
private class CategoryChoice(val id: Long?, val label: String, val kept: Boolean)

internal class PriceFreightHandler(ds: AiWriteDataSource, store: AiWritePreviewStore) :
    OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_PRICE_FREIGHT

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        val freight = AiWriteArgs.parseMoney(
            AiWriteArgs.str(params, "freight"),
            "freight",
            mustPositive = false,
        )
        requirePriceable(order)
        val category = categoryOf(params, order)
        val details = buildList {
            addAll(orderLines(order))
            add("———— 改成 ————")
            add(
                "司机运费：" + AiWriteArgs.moneyText(freight) + " 元" +
                    if (freight.signum() == 0) "（不收运费）" else "",
            )
            add("运费分类：" + category.label + if (category.kept) "（沿用现在的分类）" else "")
            if (order.status.uppercase() in LOCKED_AFTER_DELIVERY) {
                add(
                    "这一单已经「" + order.statusCn + "」、原先没定过运费 —— 这是补定：" +
                        "那张还没结算的司机应付明细会跟着改。",
                )
            }
            add("这一步不顺手沉淀价目 —— 要沉淀请到运费定价页勾一下。")
        }
        return card(
            "给 " + order.orderNo + " 定运费：" + AiWriteArgs.moneyText(freight) + " 元",
            details,
            payload = buildJsonObject {
                put("order_id", order.id)
                put("freight_fee", AiWriteArgs.money(freight))
                put("freight_category_id", category.id?.let { JsonPrimitive(it) } ?: JsonNull)
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.priceFreight(
            payload.reqLong("order_id"),
            payload.req("freight_fee"),
            payload.optLong("freight_category_id"),
        )
    }

    /**
     * 「运费分类」这次写什么：**没说 ≠ 清空**。
     *
     * - 用户没说 ⇒ 把**当前分类原样发回去**（沿用）。定价端点不认"省略＝不动"：
     *   键不在请求体里就是清空分类，所以"沿用"必须显式把现在的编号写进 payload；
     * - 用户说「不适用」⇒ 显式写 null（= 清空）；
     * - 用户给了名字 ⇒ 在分类名册里严格解析（撞上多个 / 一个都没有都如实报错，不挑最像的）。
     */
    private suspend fun categoryOf(params: JsonObject, order: AiOrderRef): CategoryChoice {
        val raw = AiWriteArgs.str(params, "category")
            ?: return CategoryChoice(
                order.freightCategoryId,
                order.freightCategory.ifBlank { "（现在没有分类）" },
                kept = true,
            )
        if (AiWriteArgs.norm(raw) in NO_CATEGORY_WORDS) return CategoryChoice(null, "不套分类", kept = false)
        val hit = AiWriteArgs.strict(raw, ds.freightCategories(), "运费分类")
            ?: throw AiWriteArgException("没读到运费分类名册，请稍后再试。")
        return CategoryChoice(hit.id, hit.label, kept = false)
    }
}

// ============================================================ 让价（`POST|DELETE /orders/{id}/discount`）

/** 让价范围在 payload 里写成"全部"或行号表（`12,15`）—— 撤回那份快照用的是同一种写法。 */
private const val DISCOUNT_ALL_LINES = "全部"

/** 一次最多勾多少行：纯可读性上限，真到 200 行也该换个做法了。 */
private const val MAX_DISCOUNT_LINES = 200

/**
 * 用户嘴里的两种说法 → 后端 `order_discount.py` 的两个 code。
 *
 * ⛔ 只认这两种，第三种一律问清楚（不猜）：`discountKindLabel` 把"不是 amount 的都算百分数"，
 * 而"打个折"这种说法两种解释都成立 —— 猜错的后果是给客户少收钱或者多收钱。
 */
private fun discountKindOf(raw: String): String = when (AiWriteArgs.norm(raw)) {
    "抹零", "抹零头", "抹掉零头", "抹个零", "金额", "按金额", "减金额", "让金额", "amount" ->
        DISCOUNT_KIND_AMOUNT
    "减百分比", "按百分比", "百分比", "减百分数", "让百分比", "percent" -> DISCOUNT_KIND_PERCENT
    else -> throw AiWriteArgException(
        "让价方式只认两种：抹零（减一个金额）或减百分比（减几个点），收到「" + raw + "」。" +
            "请让用户明确说要哪一种。",
    )
}

/** 勾中的商品：行号与名字（卡片上要写清"让的是哪几样"，而不是一串行号）。 */
private class LinePick(val ids: List<Long>, val names: List<String>) {
    val text: String get() = if (ids.isEmpty()) DISCOUNT_ALL_LINES else ids.joinToString(",")
}

/**
 * 商品名 → 行号。
 *
 * 三条判据：
 * - 名字对不上 ⇒ **拒绝并列出这一单的商品名**（不挑一个最像的：挑错了就是给错的商品打折）；
 * - 同一个商品名在这一单里有多行 ⇒ **全都要**（名字就是身份：用户说"红富士苹果不让价"说的就是这几行，
 *    这不是猜）；
 * - 一个也没勾 ⇒ 整单（后端 `line_ids` 空 = 整单）。
 *
 * ⚠️ 商品名里的空格是名字的一部分（如「红富士 苹果」），所以分隔符只认标点，**不认空格**。
 */
private suspend fun discountLinesOf(ds: AiWriteDataSource, orderId: Long, raw: String): LinePick {
    if (raw.isBlank()) return LinePick(emptyList(), emptyList())
    val lines = ds.orderLines(orderId)
    if (lines.isEmpty()) throw AiWriteArgException("这一单现在一条商品行都没有，没法按行让价。")
    val byName = lines.groupBy { AiWriteArgs.norm(it.product) }
    val ids = LinkedHashSet<Long>()
    val names = mutableListOf<String>()
    raw.split("、", "，", ",", ";", "；", "/").map { it.trim() }.filter { it.isNotEmpty() }.forEach { q ->
        val hits = byName[AiWriteArgs.norm(q)]
            ?: throw AiWriteArgException(
                "这一单里没有叫「" + q + "」的商品。这一单的商品是：" +
                    lines.map { it.product }.distinct().joinToString("、") + "。请让用户从里面挑。",
            )
        hits.forEach { ids += it.id }
        hits.first().product.let { if (!names.contains(it)) names += it }
    }
    if (ids.size > MAX_DISCOUNT_LINES) {
        throw AiWriteArgException("一次最多只勾 " + MAX_DISCOUNT_LINES + " 行，收到 " + ids.size + " 行。")
    }
    return LinePick(ids.toList(), names)
}

/**
 * 这一单能不能动钱 —— 复用界面那一份判据（`ui/order/OrderDiscount.kt::canDiscount`）。
 *
 * ⛔ 不另写一份状态集合：后端的 `LINE_EDITABLE_STATUSES`、界面的 `DISCOUNT_STATUSES`、这里的判断
 * 必须是同一组值，判据脚本会核对它们一致（改一处忘一处就红）。
 */
private fun requireDiscountable(order: AiOrderRef) {
    if (!canDiscount(order.status)) {
        throw AiWriteArgException(
            "这一单现在是「" + order.statusCn + "」，动不了钱（只有待派单 / 派单中 / 已接单的单能让价）。" +
                "请如实告诉用户，不要换一张单去操作。",
        )
    }
}

internal class DiscountOrderHandler(ds: AiWriteDataSource, store: AiWritePreviewStore) :
    OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_DISCOUNT

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        requireDiscountable(order)
        val kind = discountKindOf(
            AiWriteArgs.required(params, "kind", "要让价的方式：抹零（减一个金额）还是减百分比（减几个点）？"),
        )
        val rawValue = AiWriteArgs.required(
            params,
            "value",
            "要让多少？（抹零＝减掉的元数；减百分比＝减掉的点数）",
        )
        // 复用界面那份"值填得对不对"的判据：拦在这里的都是**一定发不出去**的数，
        // 业务规则（抹零比整单还多、勾到了「不参与打折」的行）留在后端 —— 那些要看这一单现在有多少钱。
        discountValueError(kind, rawValue)?.let {
            throw AiWriteArgException("让价的数值不对：" + it + "。请如实告诉用户，不要改去动别的单。")
        }
        val value = discountValueToSend(rawValue)
        val picked = discountLinesOf(ds, order.id, AiWriteArgs.text(AiWriteArgs.str(params, "lines"), "lines"))
        val reason = AiWriteArgs.text(AiWriteArgs.str(params, "reason"), "reason").ifBlank { null }
        val details = buildList {
            addAll(orderLines(order))
            add("———— 这次让价 ————")
            add("方式：" + discountKindLabel(kind))
            add("让价：" + discountSummary(kind, value))
            add(
                "范围：" + if (picked.ids.isEmpty()) {
                    "整单（每一行都按比例让）"
                } else {
                    picked.names.joinToString("、") + "（共 " + picked.ids.size + " 行）"
                },
            )
            add(
                "这一单现在" + (
                    order.discountTrace?.let { "已经有一套让价：" + it + " —— 这次会把它整份替换掉，不是叠加。" }
                        ?: "没有让价。"
                    ),
            )
            add(
                "每一行的金额由后台重算（这里不预演：抹零会被「最后一行没那么多钱」改小，" +
                    "预演出来的数和账上不一样）。",
            )
            add("选中的商品如果在档案上勾了「不参与打折」，后台会拒绝这一单 —— 那是规则，不是出错。")
        }
        return card(
            "给 " + order.orderNo + " 让价：" + discountSummary(kind, value),
            details,
            payload = buildJsonObject {
                put("order_id", order.id)
                put("discount_kind", kind)
                put("discount_value", value)
                put("discount_line_ids", picked.text)
                reason?.let { put("discount_reason", it) }
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.applyOrderDiscount(
            payload.reqLong("order_id"),
            payload.reqOrExplain("discount_kind", "让价方式"),
            payload.reqOrExplain("discount_value", "让价数值"),
            discountLineIdsOf(payload),
            payload.str("discount_reason"),
        )
    }
}

internal class DiscountClearHandler(ds: AiWriteDataSource, store: AiWritePreviewStore) :
    OrderWriteHandler(ds, store) {

    override val actionId = AiWrites.ORDERS_DISCOUNT_CLEAR

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val order = resolveOrder(params)
        requireDiscountable(order)
        if (order.discountKind.isNullOrBlank()) {
            // 后端对"本来就没折扣"是 400（不是"无事发生"）：审计上要能看出有人试过。
            throw AiWriteArgException(
                "这一单本来就没有让价（后台的原话：「这一单本来就没有折扣。」）。请如实告诉用户。",
            )
        }
        val details = buildList {
            addAll(orderLines(order))
            add("———— 取消掉 ————")
            add("现在这套让价：" + (order.discountTrace ?: discountKindLabel(order.discountKind)))
            add("每一行的金额还原成打折前的值（按当时记下的快照精确还原，不是拿单价 × 数量重算）。")
            add(
                "取消之后这一单就是原价；要重新打折得重新说条件" +
                    "（这张卡上的「撤回」能把刚取消的这套让价整份打回去）。",
            )
        }
        return card(
            "取消 " + order.orderNo + " 的让价",
            details,
            payload = buildJsonObject { put("order_id", order.id) },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.clearOrderDiscount(payload.reqLong("order_id"))
    }
}

/**
 * 撤回时的让价范围：**缺席要拒绝，不能默默当成"整单"**。
 *
 * 默认成整单会把撤回范围悄悄放大（本来只想退掉那两行的折扣，结果整单都退了）——
 * 宁可让用户重新说一遍。
 */
private fun discountLineIdsOf(payload: JsonObject): List<Long> {
    val raw = payload.str("discount_line_ids")
        ?: throw AiWriteArgException(
            "这次写操作没有带上让价范围（payload 缺 discount_line_ids）—— 请重新说一遍要按哪几行让价。",
        )
    if (raw == DISCOUNT_ALL_LINES) return emptyList()
    return raw.split(",").map { p ->
        p.trim().toLongOrNull()
            ?: throw AiWriteArgException(
                "让价范围里的「" + p + "」不是行号 —— 这次撤回的 payload 坏了，请重新说一遍要按哪几行让价。",
            )
    }
}

// ============================================================ 挂账额度（`PATCH /arrears-units/{id}` 的额度那一面）

/** 「不限额」的说法。⚠️ 「清空」在这里是**不限额**，不是"额度 0"。 */
private val NO_LIMIT_WORDS = setOf(
    "不限额", "不限", "不设限", "不限额度", "不设额度", "没有上限", "无上限", "不设上限",
    "取消上限", "没有额度", "清空",
)

internal class CreditLimitWriteHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val rawUnit = AiWriteArgs.required(params, "unit", "要给哪个挂账单位定额度？把单位名告诉我。")
        val hit = AiWriteArgs.strict(rawUnit, ds.arrearsUnits(), "挂账单位")
            ?: throw AiWriteArgException("没读到挂账单位名册，请稍后再试。")
        // 卡片要写「原额度 → 新额度」，所以这里**必须**再读一次这一行（名册列表里没有额度）。
        val before = ds.arrearsUnit(hit.id)
            ?: throw AiWriteArgException(
                "没读到挂账单位「" + hit.label + "」现在的额度（它可能刚被删掉）。" +
                    "请如实告诉用户，不要改去设别的单位。",
            )
        val rawLimit = AiWriteArgs.required(
            params,
            "limit",
            "额度设成多少？（元；说「不限额」＝清空额度）",
        )
        val noLimit = AiWriteArgs.norm(rawLimit) in NO_LIMIT_WORDS
        val limit = if (noLimit) {
            null
        } else {
            AiWriteArgs.parseMoney(rawLimit, "limit", mustPositive = false)
        }
        val nowText = before.creditLimit?.let { AiWriteArgs.moneyText(it) + " 元" } ?: "不限额";
        val newText = limit?.let { AiWriteArgs.moneyText(it) + " 元" } ?: "不限额（清空额度）";
        // 已经是这个数：如实说，别弹一张什么都没动的卡（后端也只在真的变了时才写流水）。
        val same = if (limit == null) {
            before.creditLimit == null
        } else {
            before.creditLimit?.toBigDecimalOrNull()?.compareTo(limit) == 0
        }
        if (same) {
            throw AiWriteArgException(
                "「" + before.name + "」现在的额度就是 " + newText + "，不用改。请告诉用户已经是这个数了。",
            )
        }
        val details = listOf(
            "单位：" + before.name + if (before.phone.isNotBlank()) "（电话 " + before.phone + "）" else "",
            "———— 改成 ————",
            "额度上限：" + nowText + " → " + newText,
            "「不限额」和「额度 0 元」是两件事：前者这个单位还能赊，后者一分钱都不许赊。",
            "额度决定这个单位的挂账收不收得住；这次改动会在后台留一条流水（谁改的、改前改后各是多少）。",
        )
        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = "把挂账单位「" + before.name + "」的额度改成 " + newText,
                detailLines = details,
                payload = buildJsonObject {
                    put("unit_id", before.id)
                    if (limit == null) {
                        // 「不限额」＝把额度清空：这一槽必须是 JsonNull（写成 0 就是另一件事了）。
                        put("credit_limit", JsonNull)
                    } else {
                        // 值口径：两位小数发回后端（去零的 moneyText( 是卡片那一侧的事）。
                        put("credit_limit", AiWriteArgs.money(limit))
                    }
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val creditLimit: JsonElement = payload["credit_limit"]
            ?: throw AiWriteArgException(
                "这次撤回没有带上额度 —— 请重新说一遍要把额度改成多少（或者说「不限额」）。",
            )
        ds.setArrearsUnitCreditLimit(payload.reqLong("unit_id"), creditLimit)
    }
}

// ============================================================ payload 取值

/** payload 里的可空编号：缺席与 JsonNull 都读成 null（编号没有"空值"这一说，只有"没有"）。 */
private fun JsonObject.optLong(key: String): Long? {
    val e = this[key] ?: return null
    if (e is JsonNull) return null
    return (e as? JsonPrimitive)?.contentOrNull?.toLongOrNull()
}

/**
 * commit 期必须存在的键：缺席说明这张卡（或这次撤回）的 payload 坏了。
 *
 * 为什么不直接用 `req`：那一句是 `error(...)`（内部错误），用户会看到一句"App 内部错误，不该发生"；
 * 这里如实说清楚缺了什么、下一步该说什么。
 */
private fun JsonObject.reqOrExplain(key: String, cn: String): String =
    str(key) ?: throw AiWriteArgException(
        "这次写操作没有带上「" + cn + "」（payload 缺 " + key + "）—— 请重新说一遍。",
    )

