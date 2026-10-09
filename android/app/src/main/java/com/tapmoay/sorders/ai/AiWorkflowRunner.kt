package com.tapmoay.sorders.ai

import com.tapmoay.sorders.core.ledgerSourceLabel
import java.math.BigDecimal
import java.time.LocalDate
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonObject
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

    // ------------------------------------------------------------------ 零件

    /** [AiWorkflows] 那条"该发哪张卡"的交棒。⛔ 这里只是**告诉**模型发哪张卡，它自己一步都不写。 */
    private fun nextJson(wf: AiWorkflow, params: JsonObject): JsonObject = buildJsonObject {
        put("action", wf.nextAction)
        put("action_cn", AiWrites.titleOf(wf.nextAction))
        put("params", params)
        put("ask", wf.ask)
        put("how", "用户点头之后再调 preview_write：action 用上面的值，params 原样传（键名一个都别改）。")
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
        return ReadResult(rows, text(root, "truncated") == "true", null)
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

    private class ReadResult(val rows: List<JsonObject>, val truncated: Boolean, val error: String?)

    private companion object {
        val DATE = Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}")
        val ALL_WORDS = setOf("全部", "所有", "全部商品", "所有商品", "全部批发商", "所有批发商", "全部商户", "all", "*")
        const val STATUS_DELIVERED = "DELIVERED"
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
