package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.math.BigDecimal
import java.math.RoundingMode

/**
 * 司机账单与结算（月末收口）。**AI 写能力的最后一批后端接口。**
 *
 * ### 这一批为什么排在最后
 * 它管的不是「一单」，而是**一个月的收口**：生成账单 → 生成结算单 → 确认 → 付款。
 * 每一步的输入都是「哪个月、哪个司机」，输出却是**一批**记录（一个月几十张账单）。
 * 也就是说它的错误形状和批量调价是同一类：**范围错比幅度错严重得多**——
 * 幅度错了用户一眼能看出来，范围错了（比如月份点错一位）是「某个司机的账多了一笔、
 * 另一个少了一笔」，而这两个人自己都不会知道。
 *
 * ### 三条真机/读源码确认过的硬约束（卡片必须照实写）
 * 1. **司机账单没有删除接口**（`driver_bills.py` 只有 `GET` 与 `POST /generate`）。
 *    生成错了 App 里没有任何入口能撤——这是本批唯一「彻底撤不回来」的动作，
 *    所以 [GenerateDriverBillsHandler] 的卡片是 HIGH 且专门写了一行警告。
 * 2. **确认结算单之后不能作废**：`confirm_settlement` 只允许草稿确认，
 *    `cancel_settlement` 只允许草稿作废。确认 = 把所属账单锁成 `settled`，**没有回头路**。
 * 3. **付款会写一条资金流水（支出）**，且没有「反付款」接口。
 *
 * ### 为什么「找到那一张结算单」要靠三个条件
 * 结算单没有名字（和账本流水一样）：它由「司机 + 月份 + 计费方式」唯一确定。
 * 所以定位 = 这三个条件 + **动作要求的状态**（确认/作废只能找草稿，付款只能找已确认）。
 * 收窄后仍不唯一 → 拒绝并列候选，绝不挑一张像的：它连着钱和账单锁定。
 */
abstract class SettlementWriteHandler(
    protected val ds: AiWriteDataSource,
    protected val store: AiWritePreviewStore,
) : AiWriteHandler {

    /** 造卡只有一处实现（`AiWritePreviewStore.card`）：这里只把本处理器的 [actionId] 递进去。 */
    protected fun card(summary: String, details: List<String>, payload: JsonObject): AiWriteOutcome =
        AiWriteOutcome.NeedConfirm(
            store.card(actionId, summary = summary, detailLines = details, payload = payload),
        )

    /**
     * 结算方式：收 `piece` / `salary`，也收「运费/工资/计件/月薪」这些说法。
     *
     * 为什么不给默认值：默认错了就是**给一个人建了另一种账单**。
     * 运费单和工资单长得像、金额却完全不同，而账单**建完删不掉**。
     */
    protected fun parseBillType(raw: String?, required: Boolean): String? {
        val s = raw?.trim()?.lowercase()?.takeIf { it.isNotEmpty() } ?: run {
            if (required) {
                throw AiWriteArgException(
                    "缺少 type：这次是**按单计费的运费账单**（piece）还是**固定工资的月薪单**（salary）？" +
                        "两者不能混，不确定就问用户，不要猜。",
                )
            }
            return null
        }
        return when (s) {
            "piece", "运费", "运费单", "计件", "按单", "按单计费", "里程" -> "piece"
            "salary", "工资", "工资单", "月薪", "固定工资", "月薪单" -> "salary"
            else -> throw AiWriteArgException(
                "type「$raw」不认。只能填 piece（按单计费的运费账单）或 salary（固定工资的月薪单）。",
            )
        }
    }

    protected fun typeLabel(code: String): String = if (code == "salary") "工资单" else "运费单"

    /**
     * 找司机：给了名字就严格解析（对不上/对上多个一律抛），没给就返回 null。
     *
     * ### 为什么"工资单"要在**全部司机**里找、而不是只在工资制司机里找
     * 只在工资制名单里找的话，用户说"给李强建工资单"（李强其实是按单计费的司机）会得到
     * 「系统里没有匹配李强的司机」——**这句是假的**，李强明明在系统里。
     * 假的错误信息会把模型推到更坏的路上（它可能改去建运费单，或者干脆说系统里没这个人）。
     * 所以先在全量名册里确认"这个人存在"，再单独判"他是不是工资制"。
     */
    protected suspend fun resolveDriver(name: String?): AiName? {
        if (name.isNullOrBlank()) return null
        return AiWriteArgs.strict(name, ds.drivers(), "司机")
            ?: throw AiWriteArgException("没找到司机「$name」。请让用户确认名字，不要自己挑一个。")
    }

    companion object {
        /** 卡片上逐条列出时最多列几条（再多就是噪音）。 */
        const val MAX_LISTED = 12
    }
}

// ============================================================== 生成司机账单

/**
 * 生成司机账单（`POST /driver-bills/generate`，幂等）。
 *
 * ### 为什么是 HIGH，而且是本批唯一「撤不回来」的动作
 * - 它**批量**建记录：不指定司机时，工资单 = 所有工资制司机，运费单 = 该月所有该补的单；
 * - 建出来的账单**没有删除接口**（App 里翻不到任何「删账单」，司机账单页只有列表）；
 * - 而且它**影响别人**：账单是司机的应付凭据，司机端能看见自己的账单。
 *
 * ### 卡片上必须出现的两类数（否则用户没法核对）
 * - **工资单**：能算准。后端按 `users.salary` 建，所以卡片直接列出「哪几个人、各多少、合计」，
 *   并减掉该月**已有**的（幂等跳过的那些）。
 * - **运费单**：算得出**金额**、算不出**张数**。金额 = 「该月应结运费」（按订单聚合）
 *   减去「该月已生成的账单」——这个差额就是这次会补进去的钱，一分不差。
 *   张数只能给上界（该月未定价的单不会补），所以卡片写「至多 N 张」。
 *   ——不写清楚这一点，用户就会拿「张数」来对账，然后发现对不上。
 */
class GenerateDriverBillsHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : SettlementWriteHandler(ds, store) {

    override val actionId = AiWrites.SETTLEMENTS_GENERATE_BILLS

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val month = AiWriteArgs.parseMonth(AiWriteArgs.str(params, "month"), "month")
        val type = requireNotNull(parseBillType(AiWriteArgs.str(params, "type"), required = true)) {
            "required=true 时 parseBillType 必抛"
        }
        val driverName = AiWriteArgs.str(params, "driver")

        return if (type == "salary") {
            prepareSalary(month, driverName)
        } else {
            preparePiece(month, driverName)
        }
    }

    // ------------------------------------------------------------ 工资单
    private suspend fun prepareSalary(month: String, driverName: String?): AiWriteOutcome {
        val all = ds.salaryDrivers()
        if (all.isEmpty()) {
            throw AiWriteArgException(
                "系统里没有**工资制**司机（没有谁的计费方式是「固定工资」且月薪大于 0）。" +
                    "请如实告诉用户，不要改去建运费单。",
            )
        }
        val named = resolveDriver(driverName)
        if (driverName != null && named != null && all.none { it.id == named.id }) {
            throw AiWriteArgException(
                "「${named.label}」不是**工资制**司机（他现在的计费方式是按单计费），没有月薪可以建单。" +
                    "如果他其实是要结运费，请改用运费账单（type=piece）。请如实告诉用户，不要换个人建。",
            )
        }
        val targets = if (named == null) all else all.filter { it.id == named.id }

        // 幂等：该月已有的工资单会被后端跳过，卡片上要说清「跳过几个」。
        // ⚠️ 按 **编号** 对齐（见 [AiDriverBill.driverId]）：按姓名对齐会漏掉重名的司机。
        val existing = ds.driverBills(null, month, "salary")
        val existingDriverIds = existing.map { it.driverId }.toSet()

        val pending = targets.filter { it.id !in existingDriverIds }
        if (pending.isEmpty()) {
            throw AiWriteArgException(
                "$month 的工资单**已经全部生成过了**（后端是幂等的，再跑一次不会重复建）。" +
                    (if (existing.isNotEmpty()) "现有的：\n" + existing.take(MAX_LISTED)
                        .joinToString("\n") { "· " + it.driverLabel + "｜" + it.label() } else ""),
            )
        }
        val skipped = targets.size - pending.size
        val total = pending.fold(BigDecimal.ZERO) { a, d ->
            a.add(d.salary.toBigDecimalOrNull() ?: BigDecimal.ZERO)
        }.setScale(2, RoundingMode.HALF_UP)

        return card(
            summary = "生成工资单：$month · ${pending.size} 人 · 合计 ${AiWriteArgs.money(total)} 元",
            details = buildList {
                add("月份：$month")
                add("类型：月薪单（固定工资司机）")
                add("做法：按每位司机的月薪各建一张账单；该月已有的会被跳过（幂等）")
                add("———— 将新建 ${pending.size} 张 ————")
                pending.take(MAX_LISTED).forEach { add("· ${it.label}：${it.salary} 元") }
                if (pending.size > MAX_LISTED) add("…… 还有 ${pending.size - MAX_LISTED} 人，未逐条列出")
                if (skipped > 0) add("该月已有工资单的 $skipped 人会被跳过")
                // ⚠️ 这一行是拿源码读出来的事实，不是推测（driver_bills.py 只有 GET 与 POST /generate）：
                add("⚠️ 司机账单生成后没有删除入口（App 里翻不到「删账单」），月份请再核对一遍")
                add("司机端能看到自己的这笔账单")
            },
            payload = buildJsonObject {
                put("month", month)
                put("bill_type", "salary")
                // 指定了司机才发 driver_id：留空 = 全部工资制司机（后端语义）。
                if (named != null) put("driver_id", named.id.toString())
            },
        )
    }

    // ------------------------------------------------------------ 运费单
    private suspend fun preparePiece(month: String, driverName: String?): AiWriteOutcome {
        val named = resolveDriver(driverName)

        // 应结（按订单聚合，含未定价的单：未定价按 0 计）
        val freight = ds.monthlyFreight(month)
            .filter { named == null || it.driverId == named.id }
        if (freight.isEmpty()) {
            throw AiWriteArgException(
                "$month 没有**已送达且计价**的订单" + (named?.let { "（司机 ${it.label}）" } ?: "") + "。" +
                    "没有可结的运费，这张账单不该生成——请如实告诉用户，不要换个范围硬试。",
            )
        }

        // 已生成的（幂等会跳过）。⚠️ 按 **司机编号** 分组，不按姓名（见 [AiDriverBill.driverId]）。
        val existing = ds.driverBills(named?.id, month, "piece")
        val existingByDriver = existing.groupBy { it.driverId }
            .mapValues { (_, rows) ->
                rows.fold(BigDecimal.ZERO) { a, b ->
                    a.add(b.amount.toBigDecimalOrNull() ?: BigDecimal.ZERO)
                }.setScale(2, RoundingMode.HALF_UP)
            }

        val rows = freight.map { f ->
            val owed = f.total.toBigDecimalOrNull() ?: BigDecimal.ZERO
            val billed = existingByDriver[f.driverId] ?: BigDecimal.ZERO
            PieceRow(f, owed, billed, owed.subtract(billed).setScale(2, RoundingMode.HALF_UP), f.count)
        }
        val todo = rows.filter { it.delta.signum() > 0 }
        if (todo.isEmpty()) {
            throw AiWriteArgException(
                "$month 的运费账单**已经生成齐了**（应结与已生成一致，后端是幂等的）。" +
                    "现有账单：${existing.size} 张。请如实告诉用户，不要重复跑。",
            )
        }
        val deltaTotal = todo.fold(BigDecimal.ZERO) { a, r -> a.add(r.delta) }

        return card(
            summary = "生成运费账单：$month · " +
                (if (named != null) named.label else "${todo.size} 位司机") +
                " · 补 ${AiWriteArgs.money(deltaTotal)} 元",
            details = buildList {
                add("月份：$month")
                add("类型：运费单（按单计费：一张已送达的单 -> 一张账单）")
                if (named != null) add("司机：${named.label}")
                add("做法：把已送达、已计价、但还没生成账单的单补成账单（幂等）")
                add("———— 会补多少 ————")
                todo.take(MAX_LISTED).forEach { r ->
                    add(
                        "· ${r.f.driverLabel}：应结 ${AiWriteArgs.money(r.owed)} 元（${r.f.count} 张单），" +
                            "已生成 ${AiWriteArgs.money(r.billed)} 元 → 补 ${AiWriteArgs.money(r.delta)} 元（至多 ${r.candidates} 张）",
                    )
                }
                if (todo.size > MAX_LISTED) add("…… 还有 ${todo.size - MAX_LISTED} 位司机，未逐条列出")
                add("本次共补：${AiWriteArgs.money(deltaTotal)} 元")
                add("张数写「至多」是因为该月未定价的单不会补（它们没有金额可入账）")
                add("⚠️ 司机账单生成后没有删除入口（App 里翻不到「删账单」），月份请再核对一遍")
                add("司机端能看到自己的这些账单")
            },
            payload = buildJsonObject {
                put("month", month)
                put("bill_type", "piece")
                if (named != null) put("driver_id", named.id.toString())
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.generateDriverBills(
            driverId = payload.str("driver_id")?.toLongOrNull(),
            month = payload.req("month"),
            billType = payload.req("bill_type"),
        )
    }

    /** 一位司机的补单情况。 */
    private data class PieceRow(
        val f: AiDriverFreight,
        val owed: BigDecimal,
        val billed: BigDecimal,
        val delta: BigDecimal,
        /** 未定价的单也在 `count` 里，所以补单张数只能给上界。 */
        val candidates: Int,
    )
}

// ============================================================== 生成结算单

/**
 * 生成司机结算单（草稿）。
 *
 * ### 为什么是 MEDIUM
 * 它**产生一条真记录**（司机的结算单，司机端可见），但它是**草稿**：
 * 草稿可以作废（[CancelSettlementHandler]），而且**不会锁任何账单**
 * （锁定发生在确认那一步）。所以它需要确认，但不需要恐吓。
 *
 * ### 金额一律不给（不给用户「手改总额」的口子）
 * 后端允许 `amount` 手工指定，但确认时要求「结算单金额 == 明细合计」——
 * 手改过的单**永远确认不了**，只能作废重来。把它暴露给模型等于给它一个
 * 「造一张废单」的能力，所以这里**根本不传 amount**，金额由后端按待结算明细汇总。
 */
class CreateSettlementHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : SettlementWriteHandler(ds, store) {

    override val actionId = AiWrites.SETTLEMENTS_CREATE

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val driverName = AiWriteArgs.required(
            params,
            "driver",
            "给哪个司机做结算？把司机姓名告诉我（只传姓名，编号由系统自己找）。",
        )
        val month = AiWriteArgs.parseMonth(AiWriteArgs.str(params, "month"), "month")
        val type = parseBillType(AiWriteArgs.str(params, "type"), required = false) ?: "piece"
        val driver = resolveDriver(driverName)
            ?: throw AiWriteArgException("没找到司机「$driverName」。")

        val open = ds.driverBills(driver.id, month, type).filter { it.status.equals("open", true) }
        if (open.isEmpty()) {
            val any = ds.driverBills(driver.id, month, null)
            throw AiWriteArgException(
                "${driver.label} 在 $month 没有**待结算**的${typeLabel(type)}。" +
                    if (any.isEmpty()) {
                        "这个月该司机还没有账单——要先「生成司机账单」吗？（要用 settlements.generate_bills）"
                    } else {
                        "该月的账单状态是：" + any.take(MAX_LISTED)
                            .joinToString("、") { it.typeLabel() + "·" + it.statusLabel() } +
                            "。已结算的不会被再结一次。"
                    },
            )
        }
        val total = open.fold(BigDecimal.ZERO) { a, b ->
            a.add(b.amount.toBigDecimalOrNull() ?: BigDecimal.ZERO)
        }.setScale(2, RoundingMode.HALF_UP)

        return card(
            summary = "生成结算单：${driver.label} $month ${typeLabel(type)} ${AiWriteArgs.money(total)} 元",
            details = buildList {
                add("司机：${driver.label}")
                add("月份：$month")
                add("类型：${typeLabel(type)}")
                add("———— 汇总这些待结算账单（${open.size} 张）————")
                open.take(MAX_LISTED).forEach { add("· " + it.label()) }
                if (open.size > MAX_LISTED) add("…… 还有 ${open.size - MAX_LISTED} 张，未逐条列出")
                add("合计：${AiWriteArgs.money(total)} 元（金额由后端按上面这些账单汇总，不能手改）")
                add("———— 生成之后 ————")
                add("这是一张草稿：还没有锁住任何账单，可以作废")
                add("要真正结掉，后面还有两步：确认（锁账单）→ 付款（写资金流水）")
            },
            payload = buildJsonObject {
                put("driver_id", driver.id.toString())
                put("settle_type", type)
                put("month", month)
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.createSettlement(
            driverId = payload.reqLong("driver_id"),
            settleType = payload.req("settle_type"),
            month = payload.req("month"),
            note = null,
        )
    }
}

// ============================================================== 结算单动作（确认 / 付款 / 作废）

/**
 * 结算单动作的公共部分：**用「司机 + 月份 + 类型 + 动作要求的状态」定位唯一一张**。
 *
 * 结算单没有名字也没有单号，用户嘴上是「老王九月的结算单」。所以：
 * 1. 先按司机+月份（+类型）拉出来；
 * 2. 再按**动作要求的状态**收窄（确认/作废 → 草稿；付款 → 已确认）；
 * 3. 收窄后：
 *    - 1 张 → 就是它；
 *    - 0 张 → 把「实际存在的状态」还给模型（「这张现在是已付款，不能再确认」比「没找到」有用得多）；
 *    - 多张 → 拒绝并列候选（真出现两张草稿时，用户必须自己去页面上处理）。
 */
abstract class SettlementActionHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : SettlementWriteHandler(ds, store) {

    /** 这个动作只对哪种状态生效（与后端状态机一致）。 */
    protected abstract val requiredStatus: String

    /** 卡片上「状态会怎么变」那一行。 */
    protected abstract val transition: String

    protected suspend fun resolveSettlement(params: JsonObject): AiSettlementRef {
        val driverName = AiWriteArgs.required(
            params,
            "driver",
            "是哪位司机的结算单？把司机姓名告诉我。",
        )
        val month = AiWriteArgs.parseMonth(AiWriteArgs.str(params, "month"), "month")
        val type = parseBillType(AiWriteArgs.str(params, "type"), required = false) ?: "piece"
        val driver = resolveDriver(driverName)
            ?: throw AiWriteArgException("没找到司机「$driverName」。")

        val all = ds.driverSettlements(driver.id, month, null).filter {
            it.settleType.equals(type, ignoreCase = true)
        }
        if (all.isEmpty()) {
            throw AiWriteArgException(
                "${driver.label} 在 $month 没有${typeLabel(type)}的结算单。" +
                    "结算单要先「生成结算单」（settlements.create）——请如实告诉用户这一步还没有做。",
            )
        }
        val pool = all.filter { it.status.equals(requiredStatus, ignoreCase = true) }
        return when {
            pool.size == 1 -> pool.first()

            pool.isEmpty() -> throw AiWriteArgException(
                "${driver.label} $month 的${typeLabel(type)}结算单现在不能做这个动作：" +
                    "它当前状态是「${all.first().statusLabel()}」，而这个动作只对「" +
                    (if (requiredStatus == "draft") "草稿" else "已确认") + "」生效。" +
                    "现有结算单：\n" + all.take(MAX_LISTED).joinToString("\n") { "· " + it.label() },
            )

            else -> throw AiWriteArgException(
                "对上了 ${pool.size} 张结算单（同一司机同一月有多张同状态的单），改错一张会锁错账单。" +
                    "请让用户到「司机运费结算」页面上指定是哪一张：\n" +
                    pool.take(MAX_LISTED).joinToString("\n") { "· " + it.label() },
                candidates = pool.take(MAX_LISTED).map { it.label() },
            )
        }
    }
}

/**
 * 确认结算单：把所属账单**锁成已结算**。
 *
 * ### 为什么是 HIGH
 * - 它**撤不回来**：后端只允许草稿作废，确认之后连作废都做不了；
 * - 它**锁住账单**：那些账单不会再出现在「待结算」里，司机那边看到的是「已结算」；
 * - 它**影响别人**：金额是司机要拿的钱。
 *
 * 卡片必须让用户看清两件事：**金额**和**这张单要锁掉的账单张数**。
 */
class ConfirmSettlementHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : SettlementActionHandler(ds, store) {

    override val actionId = AiWrites.SETTLEMENTS_CONFIRM
    override val requiredStatus = "draft"
    override val transition = "草稿 → 已确认"

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val s = resolveSettlement(params)
        val bills = ds.driverBills(null, s.month, s.settleType)
            .filter { it.status.equals("open", true) && it.driverId == s.driverId }

        return card(
            summary = "确认结算单：${s.driverLabel} ${s.month} ${s.typeLabel()} ${s.amount} 元",
            details = buildList {
                add("司机：${s.driverLabel}")
                add("月份：${s.month}　类型：${s.typeLabel()}")
                add("金额：${s.amount} 元")
                add("状态：${s.statusLabel()} → 已确认")
                add("———— 会锁住的账单（${bills.size} 张）————")
                if (bills.isEmpty()) {
                    add("· （没有查到待结算的账单明细，后端会自己再核一遍合计）")
                } else {
                    bills.take(MAX_LISTED).forEach { add("· " + it.label()) }
                    if (bills.size > MAX_LISTED) add("…… 还有 ${bills.size - MAX_LISTED} 张，未逐条列出")
                }
                add("⚠️ 确认后不能作废（后端只允许草稿作废），这一步撤不回来")
                add("付款是下一步：确认之后还要再点一次「付款」，钱才会出账")
                add("这些账单会从「待结算」变成「已结算」，司机端同步可见")
            },
            payload = buildJsonObject { put("settlement_id", s.id.toString()) },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.settlementAction(payload.reqLong("settlement_id"), "confirm", "cash")
    }
}

/**
 * 给结算单付款：**动钱**——写一条资金流水（支出），状态变已付款。
 *
 * ### 为什么是 HIGH
 * 它真的把钱记出去了，而且**没有「反付款」接口**：付错了要在账上再记一笔冲回来
 * （那是一次新的、需要人判断的操作，不该由这个动作偷偷做）。
 *
 * ### 为什么付款方式要显示在卡片上
 * 付款方式会写进资金流水的 `channel`（现金/转账/微信/银行），对账时按它分账。
 * 用户没说时按后端默认 `cash`，但**必须在卡片上写出来**——他点确认前有义务看到。
 */
class PaySettlementHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : SettlementActionHandler(ds, store) {

    override val actionId = AiWrites.SETTLEMENTS_PAY
    override val requiredStatus = "confirmed"
    override val transition = "已确认 → 已付款"

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val s = resolveSettlement(params)
        if (s.orderCount < 0) throw AiWriteArgException("结算单数据异常。")

        val raw = AiWriteArgs.str(params, "method")?.trim()?.lowercase()
        val method = when (raw) {
            null, "", "cash", "现金" -> "cash"
            "transfer", "转账", "银行", "bank" -> if (raw == "bank" || raw == "银行") "bank" else "transfer"
            "wechat", "微信" -> "wechat"
            else -> throw AiWriteArgException(
                "付款方式「$raw」不认。只能填 cash（现金）/ transfer（转账）/ wechat（微信）/ bank（银行）。",
            )
        }

        return card(
            summary = "结算单付款：${s.driverLabel} ${s.month} ${s.typeLabel()} ${s.amount} 元（${methodLabel(method)}）",
            details = buildList {
                add("司机：${s.driverLabel}")
                add("月份：${s.month}　类型：${s.typeLabel()}")
                add("付款金额：${s.amount} 元")
                add("付款方式：${methodLabel(method)}" + if (raw == null || raw.isEmpty()) "（用户没说，按默认现金）" else "")
                if (s.orderCount > 0) add("对应的运费单：${s.orderCount} 张")
                add("状态：${s.statusLabel()} → 已付款")
                add("———— 会写进去的东西 ————")
                add("一条资金流水（支出）：${s.amount} 元，付款方式记在流水上")
                add("⚠️ 付款撤不回来（没有反付款接口）：付错了只能在账上另记一笔冲回")
            },
            payload = buildJsonObject {
                put("settlement_id", s.id.toString())
                put("method", method)
            },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.settlementAction(payload.reqLong("settlement_id"), "pay", payload.req("method"))
    }

    private fun methodLabel(code: String): String = when (code) {
        "cash" -> "现金"
        "transfer" -> "转账"
        "wechat" -> "微信"
        "bank" -> "银行"
        else -> code
    }
}

/**
 * 作废结算单（草稿 → 已作废）。
 *
 * ### 为什么是 MEDIUM（而确认/付款是 HIGH）
 * 它只动一张**草稿**：草稿没有锁住任何账单（锁定发生在确认那一步），
 * 所以作废**不会解开任何已结算的账单**，也不会动钱。它产生一条真记录
 * （一张作废的结算单会留在列表里），所以不适合放进 LOW 自动执行。
 *
 * ⚠️ 后端 `cancel_settlement` 的解锁逻辑只在 `settle_type == PIECE and order_ids 非空`
 * 时才会把账单从 `settled` 放回 `open`——而**草稿的账单本来就是 open**，
 * 所以这里如实写「不会解锁任何账单」，不写「会把账单放回去」。
 */
class CancelSettlementHandler(
    ds: AiWriteDataSource,
    store: AiWritePreviewStore,
) : SettlementActionHandler(ds, store) {

    override val actionId = AiWrites.SETTLEMENTS_CANCEL
    override val requiredStatus = "draft"
    override val transition = "草稿 → 已作废"

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val s = resolveSettlement(params)
        return card(
            summary = "作废结算单：${s.driverLabel} ${s.month} ${s.typeLabel()} ${s.amount} 元",
            details = buildList {
                add("司机：${s.driverLabel}")
                add("月份：${s.month}　类型：${s.typeLabel()}")
                add("金额：${s.amount} 元")
                add("状态：${s.statusLabel()} → 已作废")
                add("———— 作废之后 ————")
                add("这张草稿作废，列表里会留下一条「已作废」的记录")
                add("不会解锁任何账单（它本来就没锁过：账单是在确认那一步才锁的）")
                add("不会动钱（付款是另一步）")
                add("如果还要结这个月，得重新生成一张结算单")
            },
            payload = buildJsonObject { put("settlement_id", s.id.toString()) },
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.settlementAction(payload.reqLong("settlement_id"), "cancel", "cash")
    }
}

// ============================================================== 动作声明

/**
 * 司机账单与结算的动作声明（行为在 [GenerateDriverBillsHandler] 等）。
 *
 * ### 为什么「确认/付款/作废」是三个动作而不是一个带 `action` 参数的动作
 * 后端是**一个端点**（`PATCH /driver-settlements/{id}`）靠 `action` 区分，但 AI 这边
 * 拆成三个，原因是**风险档位是挂在动作上的**：确认和付款撤不回来（HIGH），
 * 作废只动一张草稿（MEDIUM）。合成一个动作就只能取最高的那一档，
 * 于是「作废一张草稿」也会顶着「影响别人或撤不回来」的红牌——那会让用户
 * 学会无视红牌（见 [AiWriteRisk] 的第一条理由）。
 *
 * 拆开还有个好处：每个动作的参数表都只留自己真正要的那几个（付款才需要 method），
 * 模型没有机会把 `action=pay` 填进一个本来只是「确认」的请求里。
 */
internal object AiWriteSettlements {

    /** 司机 + 月份 + 类型：三个动作共用同一套定位参数。 */
    /** 月份参数的说明。**用户给了就照他说的填**——见下面那行注释里的真机实测。 */
    private const val MONTH_HINT =
        "必填 YYYY-MM（如 2026-09）。**用户说了月份就照他说的填**；" +
            "**他没说**时才不要默认成「这个月」（月末和月初的人要的不是同一个月），那时才要问清楚"

    private fun locateParams(extra: List<AiWriteParam> = emptyList()): List<AiWriteParam> =
        listOf(
            AiWriteParam(
                "driver", "司机", required = true,
                hint = "必填。**只传姓名**，编号由系统自己找；找不到就让用户确认，不要猜",
            ),
            AiWriteParam("month", "月份", required = true, hint = MONTH_HINT),
            AiWriteParam(
                "type", "类型", kind = AiWriteParamKind.ENUM,
                hint = "可选，默认 piece。piece=按单计费的运费单；salary=固定工资的月薪单",
                enumValues = listOf("piece", "salary"),
            ),
        ) + extra

    val ACTIONS: List<AiWriteAction> = listOf(
        AiWriteAction(
            id = AiWrites.SETTLEMENTS_GENERATE_BILLS,
            title = "生成司机账单",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_LEDGER,
            blurb = "月末收口第一步：把该月的司机应付账单补齐（幂等，已有的不会重复建）。" +
                "工资单按每位司机的月薪建；运费单按该月已送达已计价的单建。" +
                "⚠️ **账单生成后 App 里没有删除入口**，所以月份和司机必须核对准。",
            params = listOf(
                AiWriteParam(
                    "month", "月份", required = true,
                    // 2026-09-16 真机实测：这句原来只写了「不要默认成"这个月"，先问清楚」，
                    // 于是用户**已经说了**「2026-10」，模型还是又问了一遍确认月份（白跑一轮）。
                    // 把"他给了就照他说的填"写进同一句——省掉的是每张卡一轮对话。
                    hint = MONTH_HINT,
                ),
                AiWriteParam(
                    "type", "账单类型", required = true, kind = AiWriteParamKind.ENUM,
                    hint = "必填。piece=按单计费的运费账单；salary=固定工资的月薪单。" +
                        "**不确定就问用户，不要猜**（两者金额完全不同）",
                    enumValues = listOf("piece", "salary"),
                ),
                AiWriteParam(
                    "driver", "只给这个司机生成", kind = AiWriteParamKind.TEXT,
                    hint = "可选。不填 = 该范围内全部（工资单=全部工资制司机；运费单=该月所有该补单的司机）",
                ),
            ),
        ),
        AiWriteAction(
            id = AiWrites.SETTLEMENTS_CREATE,
            title = "生成结算单",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_LEDGER,
            blurb = "月末收口第二步：把某司机某月的**待结算**账单汇总成一张结算单（草稿）。" +
                "金额由后端按账单汇总，不能手改。草稿还没锁账单，可以作废。",
            params = locateParams(),
        ),
        AiWriteAction(
            id = AiWrites.SETTLEMENTS_CONFIRM,
            title = "确认结算单",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_LEDGER,
            blurb = "月末收口第三步：确认一张**草稿**结算单，把所属账单锁成「已结算」。" +
                "⚠️ 确认后**不能作废**（撤不回来）；付款是再下一步。",
            params = locateParams(),
        ),
        AiWriteAction(
            id = AiWrites.SETTLEMENTS_PAY,
            title = "结算单付款",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_LEDGER,
            blurb = "月末收口第四步：给一张**已确认**的结算单付款，会写一条**资金流水（支出）**。" +
                "⚠️ 没有反付款接口，付错了只能在账上另记一笔冲回。",
            params = locateParams(
                listOf(
                    AiWriteParam(
                        "method", "付款方式", kind = AiWriteParamKind.ENUM,
                        hint = "可选，默认 cash。会记在资金流水上，对账按它分账",
                        enumValues = listOf("cash", "transfer", "wechat", "bank"),
                    ),
                ),
            ),
        ),
        AiWriteAction(
            id = AiWrites.SETTLEMENTS_CANCEL,
            title = "作废结算单",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_LEDGER,
            blurb = "作废一张**草稿**结算单（只对草稿生效）。不会解锁任何账单（它本来就没锁过），" +
                "也不会动钱。要再结这个月得重新生成一张。",
            params = locateParams(),
        ),
    )
}
