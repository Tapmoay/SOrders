package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.OrderStatusModel
import com.tapmoay.sorders.core.ledgerSourceLabel
import java.math.BigDecimal
import java.time.LocalDate
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonObjectBuilder
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject

/**
 * 工作流的**执行器**（CHG-0096）：按登记表（[AiWorkflows]）把一条工作流在**一次调用里跑完**，返回一段 JSON 给模型。
 *
 * ### 它只读，一个字都不写
 * 对账 = 两张表各查一次 + 按订单号对差集；调价 = 查清商品范围与现有专属价。
 * 要改数据时它只**交棒**：把该发的动作、参数、要问用户的那一句放进 `next`，
 * 由模型问过用户之后走 `preview_write` 发卡。**写能力仍然只有那一条路径**。
 *
 * ### 账本那一侧的明细由它算（TB-04 / BUG-0019）
 * 对账结果里 `ledger_detail` / `returns` 的笔数与金额、`whole_order_returns`、`scope_note` 的口径
 * 全是**代码算的**：模型只照着说。原来让它自己按单拼明细，它会报出一个"库里数不出来"的笔数差
 * （差的那些挂在已进回收站的单上）—— 于是看起来像漏账。
 *
 * ### 为什么它是代码而不是提示词里的步骤清单
 * 见 [AiWorkflow] 的文件头：窗口一错，结论就是"这个月少记了三万块"这种**看着最像真的**的假账。
 * 步骤写死在代码里，判据才能钉住"两边用同一个窗口"。
 *
 * @param read 调一个只读动作（就是 `read_data` 走的那条路）：返回那段 JSON 字符串。**不抛异常**（出错走 `error` 字段）。
 * @param today 今天（测的时候注入一个固定日期，判据才能钉住"默认窗口 = 本月 1 号到今天"）。
 */
internal class AiWorkflowRunner(
    private val read: suspend (String, JsonObject) -> String,
    private val today: () -> LocalDate = { LocalDate.now() },
) {

    /** 跑一条工作流。返回**给模型看的 JSON 字符串**；认不出/跑不完都走 `{"error": …}`。 */
    suspend fun run(id: String, args: JsonObject): String {
        val wf = AiWorkflows.byId(id)
            ?: return err("认不出这条工作流：" + id + "。登记在案的是：" + AiWorkflows.IDS.joinToString("、") + "。")
        val t = today()
        val win = window(args, t)
            ?: return err("时间范围反了：开始比结束晚。给一个正常的区间，或者干脆不传 —— 不传就是本月 1 号到今天。")
        return when (wf.id) {
            AiWorkflows.LEDGER_RECONCILE -> reconcile(wf, args, t, win.first, win.second)
            AiWorkflows.PRICE_BATCH -> priceBatch(wf, args, t)
            AiWorkflows.ORDER_PLACE -> placeOrder(wf, args, t)
            AiWorkflows.ORDER_TRACK -> trackOrder(wf, args, t, win.first, win.second)
            AiWorkflows.LEDGER_MONTHLY -> monthlyLedger(wf, args, t, win.first, win.second)
            AiWorkflows.ORDER_RETURN_REQUEST -> applyReturn(wf, args, t)
            AiWorkflows.ORDER_CONTACT -> fixContact(wf, args, t)
            AiWorkflows.PRICE_MINE -> myPrices(wf, args, t)
            else -> err("工作流「" + wf.cn + "」登记在案，但执行器里没接上它的分支（代码少了一条）。")
        }
    }

    // ------------------------------------------------------------------ 对账

    private suspend fun reconcile(
        wf: AiWorkflow,
        args: JsonObject,
        t: LocalDate,
        from: String,
        to: String,
    ): String {
        val shipper = text(args, "shipper")
        val orderStep = wf.steps[0]
        val ledgerStep = wf.steps[1]

        val orders = readStep(
            orderStep.action,
            buildJsonObject {
                put("status", STATUS_DELIVERED)
                put("limit", AiTools.MAX_ROWS)
                if (shipper != null) put("name", shipper)
                // ⚠️ 订单这边必须走 extra 的 delivered_from / delivered_to（筛的是**送达日**）。
                //    ⛔ 别图省事传 from/to —— 那两个在 orders 上筛的是**下单日**，
                //    拿两种口径的窗口对账，差出来的全是窗口的差、不是账的差。
                put("extra", buildJsonObject {
                    put("delivered_from", from)
                    put("delivered_to", to)
                }.toString())
            },
        )
        orders.error?.let { return err("对账没跑完：第 1 步「" + orderStep.title + "」没查成 —— " + it) }

        val ledger = readStep(
            ledgerStep.action,
            buildJsonObject {
                put("from", from)
                put("to", to)
                put("limit", AiTools.MAX_ROWS)
                if (shipper != null) put("name", shipper)
            },
        )
        ledger.error?.let { return err("对账没跑完：第 2 步「" + ledgerStep.title + "」没查成 —— " + it) }

        // ---- 对账（全是"查"）----
        // 账上有的单号**只认「订单送达自动记账」那些行**（来源 = order）。
        // ⛔ 手工记的账（来源 = manual）不算"这张单已经进账本"：手工那一笔可能压根不是这张单的，
        //    把它算进来会**漏报**（明明没自动记，看着像记过了）。
        val booked = ledger.rows
            .filter { field(it, *SOURCE)?.lowercase() == SOURCE_ORDER }
            .mapNotNull { field(it, *ORDER_NO) }
            .toSet()
        val withNo = orders.rows.filter { field(it, *ORDER_NO) != null }
        val noNo = orders.rows.size - withNo.size
        val owned = withNo.filter { hasOwner(it) }
        val unowned = withNo.filterNot { hasOwner(it) }
        val missing = owned.filter { field(it, *ORDER_NO) !in booked }
        val seen = withNo.mapNotNull { field(it, *ORDER_NO) }.toSet()
        val ledgerOnly = booked.filterNot { it in seen }
        val missingAmount = missing.mapNotNull { money(it, *GOODS) }
            .fold(BigDecimal.ZERO) { a, b -> a.add(b) }
        val amountUnknown = missing.count { money(it, *GOODS) == null }
        val incomplete = orders.truncated || ledger.truncated
        val scopeCn = if (shipper != null) "只看 " + shipper else "全部货主"
        val clean = missing.isEmpty() && unowned.isEmpty() && ledgerOnly.isEmpty() && noNo == 0

        val baseConclusion = if (incomplete) {
            "这次**没查全**（订单或流水超过一次能取的上限 " + AiTools.MAX_ROWS + " 条），" +
                "所以下面的数字不能当完整的账用。把时间范围缩小一点（比如按周）再跑一次。"
        } else if (clean) {
            "对完了，" + scopeCn + "、" + from + " ~ " + to + "：已送达 " + orders.rows.size +
                " 张单，**全部在账上**（账本里这段时间有 " + booked.size + " 张单的流水），没有缺的。"
        } else {
            buildString {
                append("对完了，" + scopeCn + "、" + from + " ~ " + to + "：已送达 " + orders.rows.size + " 张单")
                append("，其中 " + missing.size + " 张**没进账本**")
                if (missing.isNotEmpty()) append("（货款合计 " + AiWriteArgs.moneyText(missingAmount) + " 元）")
                append("。")
                if (unowned.isNotEmpty()) {
                    append("另有 " + unowned.size + " 张单**没有归属**（既没注册货主、也没临时货主）：" +
                        "系统不会自动给这种单记账，要人工处理 —— 它不算「漏记」。")
                }
                if (ledgerOnly.isNotEmpty()) {
                    append("还有 " + ledgerOnly.size + " 张单**账上有、这批订单里没有**（可能是窗口差了一天，" +
                        "也可能这单后来被撤了），建议逐张看一眼。")
                }
                if (noNo > 0) {
                    append("另有 " + noNo + " 张单读回来的行里没有订单号，没算进上面的对账" +
                        "（读接口那边可能少下发了字段）。")
                }
                if (amountUnknown > 0) {
                    append("没进账本的那批里有 " + amountUnknown + " 张的货款没读回来，上面的合计偏小。")
                }
            }
        }

        // ---- 账本那一侧的逐行明细（笔数/金额**全是代码算的**，⛔ 不让模型自己按单拼）----
        // TB-04（BUG-0019）：模型原来自己按单拼明细，报「退货红冲 8 笔 −431.50」，
        // 而库里同一窗口有 10 笔 −570.70 —— 差的 2 笔挂在**已进回收站**的单上，
        // 账本口径两边都不计。数没错，错的是**口径没说 + 明细让模型自己拼**。
        // 所以这里按来源把明细算好交给它，并把口径写成一句固定的话（[SCOPE_NOTE]）。
        val bySource = ledger.rows.groupBy { field(it, *SOURCE)?.lowercase() ?: "" }
        val sourceDetail = bySource.entries.sortedBy { it.key }.map { (src, rows) ->
            buildJsonObject {
                put("来源", src)
                put("来源说明", ledgerSourceLabel(src))
                put("笔数", rows.size)
                put("金额", AiWriteArgs.moneyText(sumMoney(rows, *MONEY)))
            }
        }
        val returns = bySource[SOURCE_RETURN].orEmpty()
        val returnsAmount = sumMoney(returns, *MONEY)
        val wholeReturns = returns.count { isWholeOrderReturn(it, seen) }
        val returnsBrief = returns.take(BRIEF_ROWS).map { row ->
            buildJsonObject {
                put("订单号", field(row, *ORDER_NO) ?: "（行里没有订单号）")
                put("日期", field(row, *ENTRY_DATE) ?: "")
                put("金额", money(row, *MONEY)?.let { AiWriteArgs.moneyText(it) } ?: "（没读到）")
                put("商品", field(row, *R_PRODUCT) ?: "")
                put("货主", field(row, *SHIPPER, *TEMP_SHIPPER) ?: "")
                put("整单退货", wholeReturnCn(row, seen))
            }
        }
        val returnsCn = if (returns.isEmpty()) {
            "账本这段窗口里**没有退货红冲**（来源 = return）的行。"
        } else {
            "账本这段窗口里的退货红冲有 " + returns.size + " 笔（合计 " +
                AiWriteArgs.moneyText(returnsAmount) + " 元）" +
                (if (wholeReturns > 0) "，其中 " + wholeReturns + " 笔挂在**整单退货**的单上" else "") +
                "。逐行明细在 `ledger_detail` / `returns` 里（**代码算的**，明细最多摆 " + BRIEF_ROWS +
                " 条、笔数与金额是全量）：照它说，⛔ 不要自己按单拼明细、不要自己加总；" +
                "有人拿库里的原始数据核对时，先把 `scope_note` 那条口径讲清楚。"
        }

        // 账本那一段只在**查全**时才说：没查全时账本自己都不完整（见上面那句"不能当完整的账用"）。
        val conclusion = if (incomplete) baseConclusion else baseConclusion + returnsCn + SCOPE_NOTE

        val brief = missing.take(BRIEF_ROWS).map { row ->
            buildJsonObject {
                // 键名沿用读接口那套中文标签（AiFieldLabels），⛔ 不另起一套 —— 模型看到的是一份词表。
                put("订单号", field(row, *ORDER_NO) ?: "")
                put("货主", field(row, *SHIPPER, *TEMP_SHIPPER) ?: "（没有归属）")
                put("送达时间", field(row, *DELIVERED_AT) ?: "")
                put("货款", money(row, *GOODS)?.let { AiWriteArgs.moneyText(it) } ?: "（没读到）")
            }
        }

        val trace = buildString {
            append(wf.cn + " · " + from + "~" + to)
            if (incomplete) {
                append(" · 没查全")
            } else {
                append(" · 已送达 " + orders.rows.size + " 张 · 缺 " + missing.size + " 张")
                if (missing.isNotEmpty()) append("（" + AiWriteArgs.moneyText(missingAmount) + " 元）")
            }
        }

        return buildJsonObject {
            put("workflow", wf.id)
            put("workflow_cn", wf.cn)
            put("as_of", t.toString())
            putJsonObject("window") {
                put("from", from)
                put("to", to)
            }
            put("scope", scopeCn)
            put("conclusion", conclusion)
            put("incomplete", incomplete)
            putJsonArray("steps") {
                add(stepJson(orderStep.title, orders.rows.size, orders.truncated))
                add(stepJson(ledgerStep.title, ledger.rows.size, ledger.truncated))
            }
            put("delivered_count", orders.rows.size)
            put("booked_count", booked.size)
            put("missing_count", missing.size)
            if (!incomplete) put("missing_amount", AiWriteArgs.moneyText(missingAmount))
            put("unowned_count", unowned.size)
            put("ledger_only_count", ledgerOnly.size)
            putJsonArray("ledger_detail") { sourceDetail.forEach { add(it) } }
            put("returns_count", returns.size)
            put("returns_amount", AiWriteArgs.moneyText(returnsAmount))
            put("whole_order_returns", wholeReturns)
            putJsonArray("returns") { returnsBrief.forEach { add(it) } }
            put("scope_note", SCOPE_NOTE)
            putJsonArray("missing") { brief.forEach { add(it) } }
            put("next", nextJson(wf, buildJsonObject { if (shipper != null) put("shipper", shipper) }))
            put("trace", trace)
        }.toString()
    }

    // -------------------------------------------------------------- 批量调价

    private suspend fun priceBatch(wf: AiWorkflow, args: JsonObject, t: LocalDate): String {
        val adjust = text(args, "adjust")
        val price = text(args, "price")
        if ((adjust == null) == (price == null)) {
            return err(
                "批量调价要**恰好**给一个：adjust（在当前价基础上涨降百分比，降 15 就填 -15）" +
                    "或者 price（统一单价）。两个都给、或都不给，都没法跑。",
            )
        }
        val wantProducts = splitNames(text(args, "product"))
        val wantShippers = splitNames(text(args, "shipper"))

        // 两张表都**没有可用的筛参**（目录里 price_rules 一个参数都没有、products 只有 include_inactive），
        // 所以整体取回来、在本地按名字匹配。这也是它们**读**的份内事：只查，不改。
        val productStep = wf.steps[0]
        val ruleStep = wf.steps[1]
        val products = readStep(productStep.action, buildJsonObject { put("limit", AiTools.MAX_ROWS) })
        products.error?.let { return err("批量调价没跑完：第 1 步「" + productStep.title + "」没查成 —— " + it) }
        val rules = readStep(ruleStep.action, buildJsonObject { put("limit", AiTools.MAX_ROWS) })
        rules.error?.let { return err("批量调价没跑完：第 2 步「" + ruleStep.title + "」没查成 —— " + it) }

        val all = products.rows
        val matched = if (wantProducts.isEmpty()) {
            all
        } else {
            all.filter { row -> wantProducts.any { w -> matchName(field(row, *P_NAME), w) } }
        }
        val missed = if (wantProducts.isEmpty()) {
            emptyList()
        } else {
            wantProducts.filter { w -> all.none { matchName(field(it, *P_NAME), w) } }
        }
        val matchedNames = matched.mapNotNull { field(it, *P_NAME) }.toSet()
        val covered = rules.rows.filter { row ->
            (wantProducts.isEmpty() || field(row, *R_PRODUCT) in matchedNames) &&
                (wantShippers.isEmpty() || wantShippers.any { w -> matchName(field(row, *R_SHIPPER), w) })
        }
        val coveredShippers = covered.mapNotNull { field(it, *R_SHIPPER) }.distinct()
        val incomplete = products.truncated || rules.truncated
        val howCn = if (adjust != null) {
            "在**当前价**基础上 " + adjust + "%（不是按通用价算）"
        } else {
            "统一设成 " + price + " 元"
        }
        val productCn = if (wantProducts.isEmpty()) {
            "全部商品（这份列表里 " + all.size + " 个）"
        } else {
            val names = matchedNames.toList()
            "「" + wantProducts.joinToString("、") + "」匹配到 " + matched.size + " 个商品" +
                (if (names.isEmpty()) "" else "：" + names.take(5).joinToString("、") +
                    (if (names.size > 5) " 等 " + names.size + " 个" else ""))
        }
        val shipperCn = if (wantShippers.isEmpty()) "全部批发商" else "「" + wantShippers.joinToString("、") + "」"

        val conclusion = buildString {
            if (incomplete) {
                append("这次**没查全**（商品或专属价超过一次能取的上限 " + AiTools.MAX_ROWS + " 条），" +
                    "下面这些数只能当参考，确认卡发出前请把范围缩小再跑一次。")
            } else {
                append("查清了：")
            }
            append("要调的是 " + productCn + "，范围是 " + shipperCn + "，改法：" + howCn + "。")
            append("现有专属价里会**被这张卡覆盖**的有 " + covered.size + " 条")
            if (coveredShippers.isNotEmpty()) {
                append("（涉及 " + coveredShippers.size + " 位批发商：" +
                    coveredShippers.take(5).joinToString("、") +
                    (if (coveredShippers.size > 5) " 等" else "") + "）")
            }
            append("；其余是**新建**一条专属价。")
            if (missed.isNotEmpty()) {
                append("⚠️ 没找到叫「" + missed.joinToString("、") + "」的商品 —— 名字对不上就没法调，" +
                    "先跟用户核一下写法（差一个字就是另一个商品）。")
            }
            if (matched.isNotEmpty()) {
                append("商品表里它们的通用价：" + matched.take(5).joinToString("、") { row ->
                    (field(row, *P_NAME) ?: "?") + " " +
                        (money(row, *P_PRICE)?.let { AiWriteArgs.moneyText(it) } ?: "?") + " 元"
                } + (if (matched.size > 5) " 等" else "") + "。")
            }
            append("⛔ 具体每一条改前 → 改后不在这里算：那是确认卡上的事（同一个算法只有那一份实现）。")
        }

        val brief = matched.take(BRIEF_ROWS).map { row ->
            buildJsonObject {
                put("名称", field(row, *P_NAME) ?: "")
                put("通用价", money(row, *P_PRICE)?.let { AiWriteArgs.moneyText(it) } ?: "（没读到）")
                put("已有专属价条数", rules.rows.count { field(it, *R_PRODUCT) == field(row, *P_NAME) })
            }
        }

        val trace = buildString {
            append(wf.cn + " · " + matched.size + " 个商品 · 覆盖 " + covered.size + " 条专属价")
            if (incomplete) append(" · 没查全")
        }

        return buildJsonObject {
            put("workflow", wf.id)
            put("workflow_cn", wf.cn)
            put("as_of", t.toString())
            put("scope", productCn + " × " + shipperCn)
            put("conclusion", conclusion)
            put("incomplete", incomplete)
            putJsonArray("steps") {
                add(stepJson(productStep.title, all.size, products.truncated))
                add(stepJson(ruleStep.title, rules.rows.size, rules.truncated))
            }
            put("matched_products", matched.size)
            put("covered_rules", covered.size)
            putJsonArray("products") { brief.forEach { add(it) } }
            if (missed.isNotEmpty()) put("not_found", missed.joinToString("、"))
            put(
                "next",
                nextJson(
                    wf,
                    buildJsonObject {
                        if (wantShippers.isNotEmpty()) put("shipper", text(args, "shipper") ?: "")
                        if (wantProducts.isNotEmpty()) put("product", text(args, "product") ?: "")
                        if (adjust != null) put("adjust", adjust) else if (price != null) put("price", price)
                    },
                ),
            )
            put("trace", trace)
        }.toString()
    }

    // ==================================================== 货主那 6 条（FEAT-0020）
    //
    // 这六条只做两件事：**把该查的查回来**、**把要发的那张卡要什么参数拼好**。
    // ⛔ 它们一个字都不写（写仍然只有 preview_write 一条路），也一个字都不算钱
    // （「改后价」「合计」这类数各自只有一处实现：确认卡与后端）。

    /**
     * **一句话下单**（货主）：核对商品 / 数量 / 联系人 / 地址 → 交出建单卡。
     *
     * ⛔ 不填单价：单价由确认卡按**这个货主自己的价**算（`CreateOrderHandler` 的 selfOrder 分支）。
     * 工作流这里自己编一个价，用户就会在卡上看到两个数（"谈好 10 元，AI 建出来的单按 20 元"）。
     */
    private suspend fun placeOrder(wf: AiWorkflow, args: JsonObject, t: LocalDate): String {
        val wantProducts = splitNames(text(args, "product"))
        if (wantProducts.isEmpty()) {
            return err("一句话下单还差一样：**要下什么商品**。让用户说商品名（我按名字在商品表里找），别让他报编号。")
        }
        val qty = text(args, "quantity")?.let { parseQty(it) }
            ?: return err("一句话下单还差一样：**每种商品要几件**（只传数字，例如 3）。")
        val wantContact = text(args, "contact")
        val address = text(args, "address")

        val productStep = wf.steps[0]
        val contactStep = wf.steps[1]
        val addressStep = wf.steps[2]
        val products = readStep(productStep.action, buildJsonObject { put("limit", AiTools.MAX_ROWS) })
        products.error?.let { return err("下单没跑完：第 1 步「" + productStep.title + "」没查成 —— " + it) }
        val contacts = readStep(contactStep.action, buildJsonObject { put("limit", AiTools.MAX_ROWS) })
        contacts.error?.let { return err("下单没跑完：第 2 步「" + contactStep.title + "」没查成 —— " + it) }
        val addresses = readStep(addressStep.action, buildJsonObject { put("limit", AiTools.MAX_ROWS) })
        addresses.error?.let { return err("下单没跑完：第 3 步「" + addressStep.title + "」没查成 —— " + it) }

        val matched = products.rows.filter { row -> wantProducts.any { matchName(field(row, *P_NAME), it) } }
        val missed = wantProducts.filter { w -> products.rows.none { matchName(field(it, *P_NAME), w) } }
        val hit = wantContact?.let { want ->
            contacts.rows.firstOrNull { row ->
                matchName(field(row, *P_NAME), want) || field(row, *PHONE) == want
            }
        }
        val addrHit = address?.let { want ->
            addresses.rows.firstOrNull { row ->
                val a = field(row, *ADDRESS)
                a != null && (a.contains(want) || want.contains(a))
            }
        }
        val incomplete = products.truncated || contacts.truncated || addresses.truncated
        if (matched.isEmpty()) {
            // 商品一个都没匹配上：**不发卡**（空明细的卡点了必然报错，用户白核对一次）。
            return refused(
                wf,
                t,
                "商品没匹配上：商品表里没有叫「" + wantProducts.joinToString("、") + "」的" +
                    (if (missed.size < wantProducts.size) "" else "") +
                    "。名字差一个字就是另一个商品，先跟用户核一下写法再下单。" +
                    (if (incomplete) "⚠️ 而且这次**没查全**（商品超过一次能取的上限 " + AiTools.MAX_ROWS + " 条），也要考虑这个原因。" else ""),
                wf.cn + " · 商品没匹配上",
            )
        }
        val priceCn = matched.take(3).joinToString("、") { row ->
            (field(row, *P_NAME) ?: "?") + " " +
                (money(row, *P_PRICE)?.let { AiWriteArgs.moneyText(it) } ?: "（没读到通用价）") + " 元/件"
        }
        val conclusion = buildString {
            if (incomplete) {
                append("⚠️ 这次**没查全**（商品 / 联系人 / 地址有一边超过一次能取的上限 " + AiTools.MAX_ROWS +
                    " 条），下面按取回来的那部分核对 —— 名字没匹配上时先别下结论。")
            }
            append("这一单要下的：" + matched.joinToString("、") { (field(it, *P_NAME) ?: "?") + " × " + qty + " 件" })
            if (missed.isNotEmpty()) {
                append("；⚠️ 商品表里没有叫「" + missed.joinToString("、") + "」的 —— 名字差一个字就是另一个商品，" +
                    "先跟用户核一下写法")
            }
            append("。商品表里的通用价（**只作参考**）：" + priceCn + "。")
            append("收货人：")
            if (wantContact == null) {
                append("用户没说 —— 卡上留空，让他自己在卡上 / 页面上补（⛔ 别自己编一个名字或号码）。")
            } else if (hit == null) {
                append("⚠️ 他名册里没有叫「" + wantContact + "」的联系人 —— 卡上照样按他说的这个名字记，" +
                    "但先跟他核一下是不是同一个人（同名不同电话在系统里是两个人）。")
            } else {
                append("「" + (field(hit, *P_NAME) ?: wantContact) + "」，电话 " +
                    (field(hit, *PHONE) ?: "（没读到）") + "（在他自己的名册里）。")
            }
            append("送货地址：")
            if (address == null) {
                append("用户没说 —— 留空（他能在页面上补）。")
            } else {
                val tail = if (addrHit != null) {
                    "（地址库里有对得上的一条）"
                } else {
                    "（⚠️ 地址库里没有对得上的那条 —— 照用户说的原样填，⛔ 不要自己改地址、也不要自己去新增地址）"
                }
                append(address + tail + "。")
            }
            append("单价：确认卡按**他自己的价**算（有专属价用专属价、否则商品默认价）—— ⛔ 你别自己填 unit_price；")
            append("填了但与他实际的价不一样，卡上会把两个数并排写出来让你回去核对。")
        }
        val trace = buildString {
            append(wf.cn + " · " + matched.size + " 个商品 × " + qty + " 件")
            if (incomplete) append(" · 没查全")
        }
        return buildJsonObject {
            put("workflow", wf.id)
            put("workflow_cn", wf.cn)
            put("as_of", t.toString())
            put("read_only", false)
            put("scope", "他自己下的单（货主给自己下单，不用指定货主）")
            put("conclusion", conclusion)
            put("incomplete", incomplete)
            putJsonArray("steps") {
                add(stepJson(productStep.title, products.rows.size, products.truncated))
                add(stepJson(contactStep.title, contacts.rows.size, contacts.truncated))
                add(stepJson(addressStep.title, addresses.rows.size, addresses.truncated))
            }
            put("matched_products", matched.size)
            if (missed.isNotEmpty()) put("not_found", missed.joinToString("、"))
            put(
                "next",
                nextJson(
                    wf,
                    buildJsonObject {
                        putJsonArray("lines") {
                            matched.forEach { row ->
                                add(buildJsonObject {
                                    put("product", field(row, *P_NAME) ?: "")
                                    put("quantity", qty)
                                })
                            }
                        }
                        if (address != null) put("address", address)
                        if (hit != null) {
                            field(hit, *P_NAME)?.let { put("name_dongjia", it) }
                            field(hit, *PHONE)?.let { put("phone_dongjia", it) }
                        }
                    },
                ),
            )
            put("trace", trace)
        }.toString()
    }

    /**
     * **查单到哪了**（货主，**只读**）：查完直接给结论，**没有卡**。
     *
     * 走 [readOnlyOut] 那个出口 —— 返回里**没有** `next` / `ask`。
     * 单号给了就查那一张，没给就按时间范围汇总（默认窗口与其他工作流同一条：本月 1 号 → 今天）。
     */
    private suspend fun trackOrder(
        wf: AiWorkflow,
        args: JsonObject,
        t: LocalDate,
        from: String,
        to: String,
    ): String {
        val step = wf.steps[0]
        val one = text(args, "order")
        val wantStatus = text(args, "status")
        val query = buildJsonObject {
            put("limit", AiTools.MAX_ROWS)
            if (one != null) put("q", one)
            if (wantStatus != null) put("status", wantStatus.uppercase())
            if (one == null) {
                put("date_from", from)
                put("date_to", to)
            }
        }
        val res = readStep(step.action, query)
        res.error?.let { return err("查单没跑完：第 1 步「" + step.title + "」没查成 —— " + it) }

        val rows = res.rows
        val onRoad = rows.count { field(it, *STATUS) in ON_ROAD }
        val today = t.toString()
        val arrivedToday = rows.count { field(it, *DELIVERED_AT)?.startsWith(today) == true }
        val parts = OrderStatusModel.ALL.mapNotNull { s ->
            val n = rows.count { field(it, *STATUS) == s }
            if (n > 0) cnStatus(s) + " " + n + " 张" else null
        }
        val unknown = rows.count { row -> field(row, *STATUS)?.let { it in OrderStatusModel.ALL } != true }

        val conclusion = if (one != null) {
            val hit = rows.firstOrNull { field(it, *ORDER_NO) == one } ?: rows.firstOrNull()
            if (hit == null) {
                "没查到他名下有单号「" + one + "」的单 —— 单号看错一位就查不到，先跟用户核一下单号" +
                    "（也可能这一张不是他自己的单）。⛔ 不要猜一张相近的报给他。"
            } else {
                buildString {
                    append("「" + (field(hit, *ORDER_NO) ?: one) + "」现在是「" + cnStatus(field(hit, *STATUS)) + "」")
                    val driver = field(hit, *DRIVER)
                    if (driver != null) append("，司机：" + driver)
                    field(hit, *DELIVERED_AT)?.let { append("，送达时间：" + it) }
                    field(hit, *CREATED_AT)?.let { append("，下单时间：" + it) }
                    append("。")
                    if (driver == null && field(hit, *STATUS) in ON_ROAD) {
                        append("⚠️ 司机这一栏这次没读到（AI 侧对司机姓名与电话有专门的限制，" +
                            "只读工具不喂它）—— 想让他看是谁在送，让他去「我的订单」那一页看。")
                    }
                }
            }
        } else {
            buildString {
                if (res.truncated) {
                    append("⚠️ 这次**没查全**（订单超过一次能取的上限 " + AiTools.MAX_ROWS +
                        " 条），下面的数只覆盖取回来的那部分 —— 要把范围缩小一点再问一次。")
                }
                append("他名下（" + from + " ~ " + to + "）一共 " + rows.size + " 张单")
                if (parts.isEmpty()) {
                    append("：一张都没有。")
                } else {
                    append("：" + parts.joinToString("、") + "。")
                }
                if (unknown > 0) append("（另有 " + unknown + " 张状态没认出来，没算进上面几档。）")
                append("其中**在送** " + onRoad + " 张")
                if (arrivedToday > 0) append("、今天到货 " + arrivedToday + " 张")
                append("。想看某一张具体到哪了，把单号给我。")
            }
        }
        val trace = buildString {
            append(wf.cn + " · " + rows.size + " 张单 · 在送 " + onRoad + " 张")
            if (res.truncated) append(" · 没查全")
        }
        return readOnlyOut(wf, t, conclusion, trace) {
            put("matched_orders", rows.size)
            put("on_road", onRoad)
            if (arrivedToday > 0) put("arrived_today", arrivedToday)
            putJsonArray("orders") {
                rows.take(BRIEF_ROWS).forEach { row ->
                    add(buildJsonObject {
                        put("订单号", field(row, *ORDER_NO) ?: "")
                        put("状态", cnStatus(field(row, *STATUS)))
                        field(row, *DELIVERED_AT)?.let { put("送达时间", it) }
                    })
                }
            }
        }
    }

    /**
     * **本月账本小结**（货主，**只读**）：已付 / 还欠 / 哪几单还没结。
     *
     * ⚠️ 「我该付的」那三个数是**服务端算的**（/shipper-ledger/summary：窗口按送达日、**不设 limit**）——
     * 客户端把一页列表加起来，列表一被截断就**偏小**（后端那句注释里记着"客户端求和少算 62%"）。
     * 所以这里只**取**那一份统计，⛔ 不自己按订单行加总。
     *
     * ⚠️ 逐单「还欠多少」是**另一条**读（订单列表）来的：取不到那一栏时**如实说取不到**，
     * ⛔ 不许把「没读到」当成 0（那会让用户以为全结清了）。
     */
    private suspend fun monthlyLedger(
        wf: AiWorkflow,
        args: JsonObject,
        t: LocalDate,
        from: String,
        to: String,
    ): String {
        val customer = text(args, "customer")
        val sumStep = wf.steps[0]
        val orderStep = wf.steps[1]
        val sum = readStep(
            sumStep.action,
            buildJsonObject {
                put("delivered_from", from)
                put("delivered_to", to)
                if (customer != null) put("customer_name", customer)
            },
        )
        sum.error?.let { return err("账本小结没跑完：第 1 步「" + sumStep.title + "」没查成 —— " + it) }
        val orders = readStep(
            orderStep.action,
            buildJsonObject {
                put("status", STATUS_DELIVERED)
                put("limit", AiTools.MAX_ROWS)
                // 与账本同一套窗口口径：订单这边筛的是**送达日**（⛔ 不是下单日）。
                put("extra", buildJsonObject {
                    put("delivered_from", from)
                    put("delivered_to", to)
                }.toString())
            },
        )
        orders.error?.let { return err("账本小结没跑完：第 2 步「" + orderStep.title + "」没查成 —— " + it) }

        // 那段统计**不是列表**：AiReadService 把它抹平后放在 value 里（键名保持英文，没过标签表），
        // 所以两种写法都认一下。
        val v = sum.value
        val payable = v?.let { money(it, "payable", "应付") }
        val paid = v?.let { money(it, "paid", "已付") }
        val unpaid = v?.let { money(it, "unpaid", "未付", "欠款") }
        val cnt = v?.let { field(it, "orders", "单数")?.toIntOrNull() }
        val cleared = v?.let { field(it, "cleared_orders", "已结清")?.toIntOrNull() }
        val receivable = v?.let { money(it, "receivable", "应收") }
        val received = v?.let { money(it, "received", "已收") }
        val unreceived = v?.let { money(it, "unreceived", "待收", "未收") }

        val arrears = orders.rows.mapNotNull { row ->
            money(row, "arrears_amount", "欠款", "arrears", "unpaid", "未付")?.let { row to it }
        }
        val owed = arrears.filter { it.second > BigDecimal.ZERO }
        val total = cnt ?: orders.rows.size

        val conclusion = buildString {
            if (sum.truncated || orders.truncated) {
                append("⚠️ 这次**没查全**（订单超过一次能取的上限 " + AiTools.MAX_ROWS +
                    " 条），下面的数只覆盖取回来的那部分。")
            }
            append("这一段（" + from + " ~ " + to + "，按**送达日**算）")
            if (payable == null && unpaid == null && paid == null) {
                append("的服务端统计这次没取到 —— 第 1 步没返回可用的汇总（接口这次给的不是那段统计）。")
            } else {
                append("他一共 " + total + " 张单：")
                payable?.let { append("货款合计 " + AiWriteArgs.moneyText(it) + " 元，") }
                paid?.let { append("已付 " + AiWriteArgs.moneyText(it) + " 元，") }
                unpaid?.let { append("**还欠 " + AiWriteArgs.moneyText(it) + " 元**") }
                append("。")
                if (cleared != null) {
                    append("其中 " + cleared + " 张已经结清、" + (total - cleared).coerceAtLeast(0) + " 张还没结清。")
                }
            }
            if (owed.isNotEmpty()) {
                append("还没结清的单：" + owed.take(BRIEF_ROWS).joinToString("、") { (row, amt) ->
                    (field(row, *ORDER_NO) ?: "（没读到单号）") + "（还欠 " + AiWriteArgs.moneyText(amt) + " 元）"
                })
                if (owed.size > BRIEF_ROWS) append(" 等 " + owed.size + " 张")
                append("。")
            } else if (orders.rows.isNotEmpty() && arrears.isEmpty()) {
                append("⚠️ 逐单的「还欠多少」这一栏这次没取到（订单列表里没有这个字段），" +
                    "所以只能给上面的合计；要逐单核，让他去「我的账本」那一页看。")
            }
            if (receivable != null && (receivable > BigDecimal.ZERO || (received ?: BigDecimal.ZERO) > BigDecimal.ZERO)) {
                append("下游那一侧（只有批发商货主有这本账）：应收 " + AiWriteArgs.moneyText(receivable) + " 元、已收 " +
                    AiWriteArgs.moneyText(received ?: BigDecimal.ZERO) + " 元、待收 " +
                    AiWriteArgs.moneyText(unreceived ?: BigDecimal.ZERO) + " 元 —— 那是他自己记的核销，" +
                    "与上面的「我该付的」是**两本账**，⛔ 别混着说。")
            }
            append("这几个数是**服务端**按送达日窗口算的（不是把一页列表加起来），口径与他「我的账本」那一页一致。")
        }
        val trace = buildString {
            append(wf.cn + " · " + total + " 张单 · 未结清 " + owed.size + " 张")
            if (sum.truncated || orders.truncated) append(" · 没查全")
        }
        return readOnlyOut(wf, t, conclusion, trace) {
            put("orders_count", total)
            put("unpaid_count", owed.size)
            payable?.let { put("payable", AiWriteArgs.moneyText(it)) }
            paid?.let { put("paid", AiWriteArgs.moneyText(it)) }
            unpaid?.let { put("unpaid", AiWriteArgs.moneyText(it)) }
            if (arrears.isEmpty() && orders.rows.isNotEmpty()) put("per_order_arrears_missing", true)
        }
    }

    /**
     * **申请退货**（货主）：核对那一单 → 交出退货申请卡。
     *
     * ⛔ 「申请」不是「退」：这张卡只写一张申请单，库存 / 账本 / 订单状态一个都不动，
     * 派单员实际办理之后才生效（见 AiWriteReturnRequest.kt 头注）。结论里必须说出来。
     * ⛔ 不是「已送达」的单**不发卡**（后端与处理器都会拒），走 refused 如实说清楚。
     */
    private suspend fun applyReturn(wf: AiWorkflow, args: JsonObject, t: LocalDate): String {
        val orderNo = text(args, "order")
            ?: return err("申请退货要先知道**是哪一张单**：让用户给订单号（他名下的单）。")
        val wantProducts = splitNames(text(args, "product"))
        val qtyRaw = text(args, "quantity")
        val qty = qtyRaw?.let { parseQty(it) }
        if (qtyRaw != null && qty == null) {
            return err("退货数量只认正整数（这次收到「" + qtyRaw + "」）。让用户说清楚退几件。")
        }
        if (wantProducts.isNotEmpty() && qty == null) {
            return err("要退某几件时，要一起说清**退几件**（只传数字）。整单退货就别给商品名。")
        }
        val note = text(args, "note")

        val orderStep = wf.steps[0]
        val reqStep = wf.steps[1]
        val orders = readStep(orderStep.action, buildJsonObject {
            put("q", orderNo)
            put("limit", AiTools.MAX_ROWS)
        })
        orders.error?.let { return err("申请退货没跑完：第 1 步「" + orderStep.title + "」没查成 —— " + it) }
        val mine = readStep(reqStep.action, buildJsonObject { put("limit", AiTools.MAX_ROWS) })
        mine.error?.let { return err("申请退货没跑完：第 2 步「" + reqStep.title + "」没查成 —— " + it) }

        val hit = orders.rows.firstOrNull { field(it, *ORDER_NO) == orderNo } ?: orders.rows.firstOrNull()
        if (hit == null) {
            return refused(
                wf,
                t,
                "没查到他名下有单号「" + orderNo + "」的单 —— 单号看错一位就查不到，先跟用户核一下单号" +
                    "（也可能这一张不是他自己的单）。⛔ 不要拿一张相近的单去申请。",
                wf.cn + " · 没找到那张单",
            )
        }
        val realNo = field(hit, *ORDER_NO) ?: orderNo
        val status = field(hit, *STATUS)
        if (status != null && status != STATUS_DELIVERED) {
            return refused(
                wf,
                t,
                "「" + realNo + "」现在是「" + cnStatus(status) + "」，**退不了**：" +
                    "退货申请只能对**已送达**的单提（货还没送到就要作废这一单，那是「撤销」，不是退货）。",
                wf.cn + " · 状态 " + status,
            )
        }
        val existing = mine.rows.filter { field(it, *ORDER_NO) == realNo }
        val params = buildJsonObject {
            put("order", realNo)
            if (wantProducts.isNotEmpty()) {
                putJsonArray("lines") {
                    wantProducts.forEach { w ->
                        add(buildJsonObject {
                            put("product", w)
                            put("quantity", qty ?: 1)
                        })
                    }
                }
            }
            if (note != null) put("note", note)
        }
        val conclusion = buildString {
            append("要申请退货的是「" + realNo + "」（现在是「" + cnStatus(status) + "」）：")
            if (wantProducts.isEmpty()) {
                append("**整单申请**（卡上会逐行列出这一单的商品，用户核对完再确认）。")
            } else {
                append("只退 " + wantProducts.joinToString("、") { it + " × " + (qty ?: 1) + " 件" } +
                    "（这几样要能在**这一单的可退行**里认出来；认不出卡上会当场报错 —— " +
                    "⛔ 别自己编商品名，也别自己改数量）。")
            }
            if (existing.isNotEmpty()) {
                append("⚠️ 这一单上**已经有一条退货申请**了（" +
                    existing.take(3).joinToString("、") { cnStatus(field(it, *STATUS)) } +
                    "）—— 先跟用户核一下：是要**改数量**（那要先撤回再重提），还是重复提了。")
            }
            append("⚠️ 记住这只是**申请**：库存、账本、订单状态现在都不动，" +
                "派单员收到通知并**实际办理**之后才生效。")
        }
        val trace = wf.cn + " · " + realNo +
            (if (wantProducts.isEmpty()) " · 整单" else " · " + wantProducts.size + " 种商品")
        return buildJsonObject {
            put("workflow", wf.id)
            put("workflow_cn", wf.cn)
            put("as_of", t.toString())
            put("read_only", false)
            put("scope", "他自己那一张单（" + realNo + "）")
            put("conclusion", conclusion)
            put("incomplete", orders.truncated || mine.truncated)
            putJsonArray("steps") {
                add(stepJson(orderStep.title, orders.rows.size, orders.truncated))
                add(stepJson(reqStep.title, mine.rows.size, mine.truncated))
            }
            put("existing_requests", existing.size)
            put("next", nextJson(wf, params))
            put("trace", trace)
        }.toString()
    }

    /**
     * **改收货联系信息**（货主）：找到那一单 → 交出修改卡。
     *
     * ⛔ **PATCH 语义**：没点名的字段**一个都不带**。把查到的另外几栏原样写回去，等于用
     * 「上一轮读到的值」覆盖掉这中间别人改过的内容（而用户只说了改电话）。
     * ⛔ 送货地址不在这一扇门里（白名单里没有改地址的写动作）：结论里如实说，别答应。
     */
    private suspend fun fixContact(wf: AiWorkflow, args: JsonObject, t: LocalDate): String {
        val orderNo = text(args, "order")
            ?: return err("改联系信息要先知道**是哪一张单**：让用户给订单号。")
        val want = CONTACT_FIELDS.mapNotNull { (key, cn) -> text(args, key)?.let { Triple(key, cn, it) } }
        if (want.isEmpty()) {
            return err(
                "改联系信息要至少说清**改哪一栏**：收货人名称 / 收货人电话 / 下单人名称 / 下单人电话。" +
                    "他没提的那几栏**一个字都别填**（不填＝那一栏不动）。",
            )
        }
        want.forEach { (key, cn, value) ->
            if (key.endsWith("phone") && value.count { it.isDigit() } < 5) {
                return err(
                    "「" + cn + "」看着不像一个电话（这次收到「" + value + "」）—— " +
                        "让用户把号码说全（至少 5 位数字），⛔ 别自己补全。",
                )
            }
        }

        val orderStep = wf.steps[0]
        val contactStep = wf.steps[1]
        val orders = readStep(orderStep.action, buildJsonObject {
            put("q", orderNo)
            put("limit", AiTools.MAX_ROWS)
        })
        orders.error?.let { return err("改联系信息没跑完：第 1 步「" + orderStep.title + "」没查成 —— " + it) }
        val contacts = readStep(contactStep.action, buildJsonObject { put("limit", AiTools.MAX_ROWS) })
        contacts.error?.let { return err("改联系信息没跑完：第 2 步「" + contactStep.title + "」没查成 —— " + it) }

        val hit = orders.rows.firstOrNull { field(it, *ORDER_NO) == orderNo } ?: orders.rows.firstOrNull()
        if (hit == null) {
            return refused(
                wf,
                t,
                "没查到他名下有单号「" + orderNo + "」的单 —— 单号看错一位就查不到，" +
                    "先跟用户核一下单号。⛔ 不要改一张相近的单。",
                wf.cn + " · 没找到那张单",
            )
        }
        val realNo = field(hit, *ORDER_NO) ?: orderNo
        // 名册里有没有这个人：只用来提醒（订单上的人不一定先存进名册），⛔ 不用来拦。
        val rosterHit = want.firstNotNullOfOrNull { (key, _, value) ->
            if (key == "dongjia_name" || key == "boss_name") {
                contacts.rows.firstOrNull { matchName(field(it, *P_NAME), value) }
            } else {
                null
            }
        }

        val conclusion = buildString {
            append("要改「" + realNo + "」（现在是「" + cnStatus(field(hit, *STATUS)) + "」）的这几栏：" +
                want.joinToString("、") { (_, cn, value) -> cn + " → " + value } + "。")
            append("**只改这几栏**，别的字段一个字都不动（没点名的栏不会出现在卡上）。")
            append("⚠️ 这一扇门只改**收货人 / 下单人的名字与电话**：送货地址、配送说明、备注要**请派单员**改 —— " +
                "用户要是想改送货地址，如实告诉他这一步得找派单员（他自己改不了）。")
            val now = listOf(
                "收货人" to field(hit, "收货人", "customer_name", "dongjia_name"),
                "电话" to field(hit, *PHONE),
                "地址" to field(hit, *ADDRESS),
            ).mapNotNull { (cn, v) -> v?.let { cn + "：" + it } }
            if (now.isEmpty()) {
                append("⚠️ 这一单现在的联系信息这次没读到（订单列表里没有那几栏）—— 卡上照样按用户说的改，" +
                    "改动前的值以确认卡上印的为准。")
            } else {
                append("现在这一单上的：" + now.joinToString("；") + "。")
            }
            if (rosterHit != null) {
                append("（他联系人名册里也有「" + (field(rosterHit, *P_NAME) ?: "") + "」这个人。）")
            } else if (want.any { it.first == "dongjia_name" || it.first == "boss_name" }) {
                append("⚠️ 他联系人名册里没有这个名字 —— 卡上照样按他说的改，" +
                    "但先核一下是不是同一个人（同名不同电话在系统里是两个人）。")
            }
        }
        val trace = wf.cn + " · " + realNo + " · 改 " + want.size + " 栏"
        return buildJsonObject {
            put("workflow", wf.id)
            put("workflow_cn", wf.cn)
            put("as_of", t.toString())
            put("read_only", false)
            put("scope", "他自己那一张单（" + realNo + "）")
            put("conclusion", conclusion)
            put("incomplete", orders.truncated || contacts.truncated)
            putJsonArray("steps") {
                add(stepJson(orderStep.title, orders.rows.size, orders.truncated))
                add(stepJson(contactStep.title, contacts.rows.size, contacts.truncated))
            }
            put("patch_fields", want.size)
            put(
                "next",
                nextJson(
                    wf,
                    buildJsonObject {
                        put("order", realNo)
                        // ⛔ 只放点名的那几栏（PATCH 语义，见 KDoc）。
                        want.forEach { (key, _, value) -> put(key, value) }
                    },
                ),
            )
            put("trace", trace)
        }.toString()
    }

    /**
     * **改我的下游价**（批发商货主）：查现有的下游价 → 逐条交出调价卡（一个商品一张）。
     *
     * ⛔ 它**一个价都不算**：改后价就是用户给的那个数，卡片会印「原来：X 元 → 现在：Y 元」。
     * 用户说「降 5%」时这条链**不折算**（折算就是第二份算价实现），让他先说清多少钱。
     * ⛔ 只动 shipper_price.*（他自己那一本下游账），**不碰** price_rules.*（派单员那条批发商专属价）。
     */
    private suspend fun myPrices(wf: AiWorkflow, args: JsonObject, t: LocalDate): String {
        val wantProducts = splitNames(text(args, "product"))
        if (wantProducts.isEmpty()) {
            return err("改下游价要先知道**改哪个商品**：让用户说商品名（我按名字在他能定价的商品里找）。")
        }
        val priceRaw = text(args, "price")
            ?: return err(
                "改下游价要一个**确定的单价**（元）。用户说的是百分比（例如「降 5%」）时，先问他" +
                    "「具体改成多少钱」—— 这条链不折算百分比（改后价只有确认卡那一份实现）。",
            )
        val price = parseMoney(priceRaw)?.takeIf { it > BigDecimal.ZERO }
            ?: return err("「" + priceRaw + "」不像一个单价（元）。让用户说一个大于 0 的数，例如 8.5。")
        val contact = text(args, "contact")

        val priceStep = wf.steps[0]
        val productStep = wf.steps[1]
        val prices = readStep(priceStep.action, buildJsonObject { put("limit", AiTools.MAX_ROWS) })
        prices.error?.let { return err("改下游价没跑完：第 1 步「" + priceStep.title + "」没查成 —— " + it) }
        val priceable = readStep(productStep.action, buildJsonObject { put("limit", AiTools.MAX_ROWS) })
        priceable.error?.let { return err("改下游价没跑完：第 2 步「" + productStep.title + "」没查成 —— " + it) }

        val matched = priceable.rows.filter { row -> wantProducts.any { matchName(field(row, *P_NAME), it) } }
        val missed = wantProducts.filter { w -> priceable.rows.none { matchName(field(it, *P_NAME), w) } }
        if (matched.isEmpty()) {
            return refused(
                wf,
                t,
                "他能定价的商品里没有叫「" + wantProducts.joinToString("、") + "」的 —— " +
                    "可定价的只有「他自己下过单的、或派单员给他设过专属价的」商品。先跟用户核一下商品名。",
                wf.cn + " · 没匹配到商品",
            )
        }
        val cards = matched.take(MAX_CARDS)
        val existing = cards.map { row ->
            val name = field(row, *P_NAME) ?: ""
            name to prices.rows.filter { field(it, *PRICE_PRODUCT) == name }
        }
        val conclusion = buildString {
            if (prices.truncated || priceable.truncated) {
                append("⚠️ 这次**没查全**（价目表或可定价商品超过一次能取的上限 " + AiTools.MAX_ROWS +
                    " 条），下面按取回来的那部分核对。")
            }
            append("要把这几个商品的下游价改成 " + AiWriteArgs.moneyText(price) + " 元" +
                (if (contact != null) "（只给「" + contact + "」这一个下游）" else "（对所有下游的默认价）") + "：")
            existing.forEach { (name, rows) ->
                append("· " + name + "：")
                if (rows.isEmpty()) {
                    append("这一档现在还没有价（这次是新建一条）")
                } else {
                    append("现在有 " + rows.size + " 条价 —— " + rows.take(4).joinToString("、") { row ->
                        val who = field(row, *PRICE_CONTACT) ?: "所有下游（默认价）"
                        who + " " + (money(row, *PRICE_UNIT)?.let { AiWriteArgs.moneyText(it) } ?: "（没读到价）") + " 元"
                    } + (if (rows.size > 4) " 等" else "") + " → 改成 " + AiWriteArgs.moneyText(price) + " 元")
                }
                append("；")
            }
            append("。卡上会逐条印「原来：X 元 → 现在：Y 元」（有几个商品就几张卡，一张一张来）。")
            if (missed.isNotEmpty()) {
                append("⚠️ 他能定价的商品里没有叫「" + missed.joinToString("、") + "」的 —— 先跟用户核一下商品名。")
            }
            if (matched.size > cards.size) {
                append("⚠️ 一次最多发 " + MAX_CARDS + " 张卡，这次还有 " + (matched.size - cards.size) +
                    " 个商品没进卡 —— 先说清这次改了哪几个，剩下的让他再说一次。")
            }
            append("⛔ 只动他自己那一本下游账（公司那边的账一分钱都不变）；")
            append("也只影响**以后新下的单**：已经下过的单按当时的价定格，一个字节都不动。")
        }
        val trace = buildString {
            append(wf.cn + " · " + cards.size + " 个商品 → " + AiWriteArgs.moneyText(price) + " 元")
            if (prices.truncated || priceable.truncated) append(" · 没查全")
        }
        val cardParams = cards.map { row ->
            buildJsonObject {
                put("product", field(row, *P_NAME) ?: "")
                put("price", price)
                if (contact != null) put("contact", contact)
            }
        }
        return buildJsonObject {
            put("workflow", wf.id)
            put("workflow_cn", wf.cn)
            put("as_of", t.toString())
            put("read_only", false)
            put("scope", "他自己那一本下游价（shipper_prices），不是派单员那条批发商专属价")
            put("conclusion", conclusion)
            put("incomplete", prices.truncated || priceable.truncated)
            putJsonArray("steps") {
                add(stepJson(priceStep.title, prices.rows.size, prices.truncated))
                add(stepJson(productStep.title, priceable.rows.size, priceable.truncated))
            }
            put("matched_products", matched.size)
            put("cards", cardParams.size)
            if (missed.isNotEmpty()) put("not_found", missed.joinToString("、"))
            // 一张卡一个商品（shipper_price.set 就是单商品的动作）：一张时给 next，
            // 多于一张时给 nexts（第 13 条写明「一张一张来」）。
            if (cardParams.size == 1) {
                put("next", nextJson(wf, cardParams.first()))
            } else {
                putJsonArray("nexts") { cardParams.forEach { add(nextJson(wf, it)) } }
            }
            put("trace", trace)
        }.toString()
    }

    // ------------------------------------------------------------------ 零件

    /**
     * [AiWorkflows] 那条"该发哪张卡"的交棒。⛔ 这里只是**告诉**模型发哪张卡，它自己一步都不写。
     *
     * ⚠️ **只读工作流永远不走这里**（[AiWorkflow.readOnly] 没有交棒动作、也没有要问的那一句）：
     * 调用它就是登记表与执行分支接错了。编译期看不出来（`nextAction` 只是可空），
     * 所以这里**当场抛**，单测与判据各再钉一次。
     */
    private fun nextJson(wf: AiWorkflow, params: JsonObject): JsonObject {
        val action = wf.nextAction
            ?: error("只读工作流没有交棒动作，不该走 nextJson：" + wf.id)
        return buildJsonObject {
            put("action", action)
            put("action_cn", AiWrites.titleOf(action))
            put("params", params)
            put("ask", wf.ask ?: "")
            put("how", "用户点头之后再调 preview_write：action 用上面的值，params 原样传（键名一个都别改）。")
        }
    }

    private fun stepJson(title: String, count: Int, truncated: Boolean): JsonObject = buildJsonObject {
        put("title", title)
        put("count", count)
        put("truncated", truncated)
    }

    /**
     * 时间窗口：模型给了 `from` / `to` 就用（只认 `YYYY-MM-DD`），没给就**本月 1 号 → 今天**。
     * 两头颠倒了返回 null（**不能装看不见**：倒着的窗口查回来是空的，结论会变成"账全对"—— 最坏的那种假账）。
     */
    private fun window(args: JsonObject, t: LocalDate): Pair<String, String>? {
        val from = date(args, "from") ?: t.withDayOfMonth(1).toString()
        val to = date(args, "to") ?: t.toString()
        return if (from > to) null else from to to
    }

    private fun date(args: JsonObject, key: String): String? = text(args, key)?.takeIf { DATE.matches(it) }

    /** 取一个标量参数。数字也收（模型给 `adjust: -15` 是数字，只收字符串就会当成"没给"）。 */
    private fun text(o: JsonObject, key: String): String? {
        val p = o[key] as? JsonPrimitive ?: return null
        if (p.content == "null") return null
        return p.content.trim().takeIf { it.isNotEmpty() }
    }

    /**
     * 行里的一个字段。
     *
     * ⚠️ 键名是**抹平 + 换中文标签之后**的（`AiRowShaper.shape` → `AiFieldLabels`）：
     * 「订单号 / 货主 / 送达时间 / 货款 / 来源 / 名称 / 商品」这些才是真的键名；
     * 表里没有的（`default_unit_price` 这种）保持英文原样，所以英文键名放在后面兜底。
     * ⛔ 都没有就返回 null —— **不许猜一个相近的字段**（猜错比查不到更糟）。
     */
    private fun field(row: JsonObject, vararg keys: String): String? {
        for (k in keys) {
            val p = row[k] as? JsonPrimitive ?: continue
            val v = p.content.trim()
            if (v.isNotEmpty() && v != "null") return v
        }
        return null
    }

    /** 金额：字符串/数字都按十进制解析；⛔ 解析不了返回 null（**不要当成 0** —— 那会把缺账算成不缺）。 */
    private fun money(row: JsonObject, vararg keys: String): BigDecimal? =
        field(row, *keys)?.replace(",", "")?.let { raw -> runCatching { BigDecimal(raw) }.getOrNull() }

    /** 这张单有归属吗（注册货主或临时货主）。后端的自动记账规则要的就是这个（`ledger_sync.py:14`）。 */
    private fun hasOwner(row: JsonObject): Boolean =
        field(row, *SHIPPER) != null || field(row, *TEMP_SHIPPER) != null

    /** 名字对得上吗：全等优先，其次是包含（用户说「菜籽油」，商品叫「金龙鱼菜籽油」）。 */
    private fun matchName(name: String?, want: String): Boolean {
        if (name == null || want.isBlank()) return false
        return name.equals(want, ignoreCase = true) || name.contains(want, ignoreCase = true)
    }

    /** 把「A、B，C」拆成一组名字。空/「全部」这类词 → 空列表 = 全部。⛔ 与写侧的 `splitNames` 各算各的（那份是 private，且那边还管"留空=全部"的写语义）。 */
    private fun splitNames(raw: String?): List<String> {
        if (raw.isNullOrBlank()) return emptyList()
        val all = raw.trim().lowercase()
        if (all in ALL_WORDS) return emptyList()
        return raw.split('、', '，', ',', ';', '；').map { it.trim() }.filter { it.isNotEmpty() }
    }

    private suspend fun readStep(action: String, args: JsonObject): ReadResult {
        val raw = try {
            read(action, args)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            return ReadResult(emptyList(), false, "调读接口时出错：" + (e.message ?: e.javaClass.simpleName))
        }
        val root = AiJson.parseObjectLenient(raw)
            ?: return ReadResult(emptyList(), false, "读接口返回的不是合法 JSON")
        text(root, "error")?.let { return ReadResult(emptyList(), false, it) }
        val rows = (root["items"] as? kotlinx.serialization.json.JsonArray)
            ?.mapNotNull { it as? JsonObject }
            .orEmpty()
        // ⚠️ 还有一类接口**根本不是列表**（「我的账本」那段统计就是）：AiReadService 把它抹平后
        //    放在 `value` 里，而不是 `items`。只认 items 的话，那条工作流会拿到 0 行
        //    却**不报错**（结论变成"这一段一张单都没有"）—— 最坏的那种错答案。
        val value = root["value"] as? JsonObject
        return ReadResult(rows, text(root, "truncated") == "true", null, value)
    }

    /** 一批行按某个金额键求和：**认不出来的行按 0 算**（与 [money] 同一条规矩 —— ⛔ 不猜）。 */
    private fun sumMoney(rows: List<JsonObject>, vararg keys: String): BigDecimal =
        rows.fold(BigDecimal.ZERO) { acc, row -> money(row, *keys)?.let { acc.add(it) } ?: acc }

    /**
     * 这一行红冲是不是**整单退货**留下的：看它的订单号还在不在本次"已送达"清单里（[seen]）。
     *
     * 整单退掉的单已经不在已送达档里；部分退货的单还在。这是**代码判的**，
     * ⛔ 不让模型自己看金额猜（猜错就会把一张还在的单说成"已整单退"）。
     */
    private fun isWholeOrderReturn(row: JsonObject, seen: Set<String>): Boolean {
        val no = field(row, *ORDER_NO) ?: return false
        return no !in seen
    }

    private fun wholeReturnCn(row: JsonObject, seen: Set<String>): String {
        val no = field(row, *ORDER_NO) ?: return "（行里没有订单号，认不出是哪张单）"
        return if (no in seen) "否（部分退：这张单还在已送达清单里）" else "是（整单退：这张单不在本次已送达清单里）"
    }

    private fun err(message: String): String = buildJsonObject { put("error", message) }.toString()

    /**
     * **只读工作流的唯一出口**（[AiWorkflow.readOnly]）：结论 ＋ 明细，**没有 `next`、也没有 `ask`**。
     *
     * 为什么单独一个出口，而不是在别处"少 put 两个键"：只读那两条的返回里**必须**没有交棒那一段。
     * 少一个键不会有任何报错，而模型会照着别的结果的样子去问"要不要发卡"，然后**没有卡可发**
     * ——用户点了空。所以出口只有这一个，它连 `read_only=true` 一起给出去（提示词第 13 条照它说）。
     */
    private fun readOnlyOut(
        wf: AiWorkflow,
        t: LocalDate,
        conclusion: String,
        trace: String,
        extra: JsonObjectBuilder.() -> Unit = {},
    ): String = buildJsonObject {
        put("workflow", wf.id)
        put("workflow_cn", wf.cn)
        put("as_of", t.toString())
        put("read_only", true)
        put("conclusion", conclusion)
        extra()
        put("trace", trace)
    }.toString()

    /**
     * 「这件事**现在做不了**」的出口：给结论 ＋ `refused` 原因，**不发卡**。
     *
     * 它和 [err] 不是一回事：`err` 是"这次没跑成，改个参数再来"（模型自己修），
     * 而这里是"查清了，但这件事本身做不了"（单号对不上 / 这单不是已送达 / 商品名字对不上）——
     * 用户要的是一个**结论**，不是让模型换个写法再试一次。⛔ 所以这里明确不发卡：
     * 一条注定被后端拒掉的卡，用户白核对一遍。
     */
    private fun refused(wf: AiWorkflow, t: LocalDate, why: String, trace: String): String = buildJsonObject {
        put("workflow", wf.id)
        put("workflow_cn", wf.cn)
        put("as_of", t.toString())
        put("read_only", false)
        put("conclusion", why)
        put("refused", why)
        put("trace", trace)
    }.toString()

    /** 数量：只认正整数（「3」「3件」都收）。⛔ 认不出返回 null —— 不猜 1。 */
    private fun parseQty(raw: String): Int? {
        val t = raw.trim().removeSuffix("件").removeSuffix("个").removeSuffix("箱").removeSuffix("斤").trim()
        val n = t.toIntOrNull() ?: return null
        return if (n > 0) n else null
    }

    /** 金额：认不出返回 null（⛔ 不猜 0 —— 与 [money] 同一条规矩）。 */
    private fun parseMoney(raw: String): BigDecimal? =
        runCatching { BigDecimal(raw.replace(",", "").removePrefix("¥").trim()) }.getOrNull()

    /** 状态码 → 中文：**唯一那一份在 [AiOrderRef.statusLabel]**（⛔ 这里不许再抄一张表）。 */
    private fun cnStatus(raw: String?): String {
        val s = AiOrderRef.statusLabel(raw)
        return if (s.isBlank()) "状态没读到" else s
    }

    private class ReadResult(
        val rows: List<JsonObject>,
        val truncated: Boolean,
        val error: String?,
        /** 这个接口**不是列表**时那份抹平后的对象（`AiReadService` 的 `value`）；是列表时为 null。 */
        val value: JsonObject? = null,
    )

    private companion object {
        val DATE = Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}")
        val ALL_WORDS = setOf("全部", "所有", "全部商品", "所有商品", "全部批发商", "所有批发商", "全部商户", "all", "*")
        const val STATUS_DELIVERED = "DELIVERED"

        /** 状态那一栏（行里叫「状态」）。 */
        val STATUS = arrayOf("状态", "status")

        /** 电话那一栏（联系人行与订单行都可能是它）。 */
        val PHONE = arrayOf("电话", "phone")

        /** 地址那一栏。 */
        val ADDRESS = arrayOf("地址", "address")

        /**
         * 司机那一栏。
         *
         * ⚠️ `driver_name` 会被 [AiRowShaper] 摘掉（台账 L-30：AI 侧不喂司机姓名与电话），
         * 所以 `full_name` 也认一下 —— 后端有时把司机嵌成对象再被抹平，那一支还在。
         */
        val DRIVER = arrayOf("司机", "driver_name", "full_name")

        /** 下单时间那一栏。 */
        val CREATED_AT = arrayOf("创建时间", "created_at")

        /**
         * 「在送」＝ 派单中 ＋ 已接单（货在路上）。
         *
         * ⚠️ 这是**汇总口径**（回答"今天有几单在送"用的），⛔ 不是某个动作的状态门 ——
         * 状态门各自在 [com.tapmoay.sorders.core.OrderStatusModel] 里，别拿这个当判据。
         */
        val ON_ROAD = setOf("DISPATCHED", "ACCEPTED")

        /** 下游价目表（`shipper_prices`）那三栏。 */
        val PRICE_PRODUCT = arrayOf("商品", "product_name")
        val PRICE_CONTACT = arrayOf("下游", "contact_name", "客户", "customer_name")
        val PRICE_UNIT = arrayOf("单价", "unit_price", "price")

        /** 一次最多发几张下游价确认卡（一个商品一张卡）：多了就先说清这次改哪几个。 */
        const val MAX_CARDS = 6

        /** 订单上那四个联系字段（`orders.update_contact` 的入参）：键 → 中文名。 */
        val CONTACT_FIELDS = listOf(
            "dongjia_name" to "收货人名称",
            "dongjia_phone" to "收货人电话",
            "boss_name" to "下单人名称",
            "boss_phone" to "下单人电话",
        )
        const val SOURCE_ORDER = "order"

        /** 账本里的**退货红冲**行（`LedgerSource.RETURN`）：营收与成本一起冲回头（BUG-0019 / 台账 TB-04）。 */
        const val SOURCE_RETURN = "return"

        /**
         * 账本口径那一句话 —— 模型被人拿"库里的原始数据"核对笔数时，照它解释（BUG-0019 / 台账 TB-04）。
         *
         * ⚠️ 这是**口径**不是客套话：`backend/app/services/ledger_scope.py` 的 `visible_ledger_clause()`
         * 把进了回收站（软删）的单整条排除在外；那种单的自动行与退货红冲行在库里**成对存在、净额 0**，
         * 所以拿原始数据数笔数会多出成对的那几行 —— **不是漏账**。
         */
        const val SCOPE_NOTE = "账本这一侧的口径：只算**没进回收站**的单的账。进了回收站（已删除）的单，" +
            "它的自动行与退货红冲行在库里成对存在、净额 0，账本与营业额**两边都不计** —— " +
            "拿库里的原始数据核对时笔数会对不上，那不是漏账，是这一条口径。"
        /** 明细里最多摆几条订单（剩下的让模型自己说"还有 N 张"）。 */
        const val BRIEF_ROWS = 20

        val ORDER_NO = arrayOf("订单号", "order_no")
        val SHIPPER = arrayOf("货主", "shipper_name")
        val TEMP_SHIPPER = arrayOf("临时货主", "temp_shipper_name")
        val GOODS = arrayOf("货款", "goods_amount")
        val DELIVERED_AT = arrayOf("送达时间", "delivered_at")
        val SOURCE = arrayOf("来源", "source")

        /** 金额那两个名字：订单侧是「合计 / total」，账本侧是「金额 / amount」—— 两边的行都认（BUG-0019）。 */
        val MONEY = arrayOf("合计", "total", "金额", "amount")

        /** 账本流水的记账日（`entry_date`）：`AiFieldLabels` 认不出它，明细里自己认（BUG-0019）。 */
        val ENTRY_DATE = arrayOf("entry_date", "日期")
        val P_NAME = arrayOf("名称", "name")
        val P_PRICE = arrayOf("default_unit_price")
        val R_PRODUCT = arrayOf("商品", "product_name")
        val R_SHIPPER = arrayOf("货主", "shipper_name")
    }
}
