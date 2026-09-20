package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put
import java.math.BigDecimal
import java.math.RoundingMode

/**
 * 批量调价。
 *
 * ### 用户要的三种用法（原话整理）
 * 1. 「这个商品要降价，所有商户或者说指定商户全部统一降价」
 * 2. 「一个批发商他的所有商品统一降价，或者说抬升百分之多少」
 * 3. 「指定某个商品单独抬升/下降百分之多少」
 * 4. 「用户做了一个表格，直接让 AI 全部调好」
 *
 * 前三种是同一个形状：**(若干批发商) × (若干商品) × 一套价格规则**，
 * 所以是一个动作（[AiWrites.PRICE_RULES_BATCH]），用"留空 = 全部"来表达范围。
 * 第四种每行价格都可能不同，后端一次调用套不了多套规则，所以是另一个动作
 * （[AiWrites.PRICE_RULES_APPLY_TABLE]），逐行执行、如实报告。
 *
 * ### 为什么这一个动作是手写而不是声明式
 * 它有两件声明式表达不了的事：
 * ① 目标参数是**一组名字**（"城东水果批发、明辉食品行"，留空 = 全部），不是单个名字；
 * ② 卡片上的 before→after 要在**预览时**就算出来——那需要把「批发商的专属价」和
 *    「商品的默认价」join 起来自己算一遍。这是全 App 唯一一个"我要先把结果算给你看"的动作，
 *    而它恰恰是最需要算的那个：**用户核对的就是那串数字**。
 */
class BatchPriceHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.PRICE_RULES_BATCH

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        // ---- 1. 范围：批发商 × 商品，都允许留空表示"全部" ----
        val allMembers = ds.members()
        val allProducts = ds.productPrices()

        val shipperNames = splitNames(AiWriteArgs.str(params, "shipper"))
        val productNames = splitNames(AiWriteArgs.str(params, "product"))
        if (shipperNames.isEmpty() && productNames.isEmpty()) {
            throw AiWriteArgException(
                "范围太大了：批发商和商品都没指定，这会把**所有批发商的所有商品**都改一遍。" +
                    "请让用户至少说清楚是哪一类（比如「所有批发商的红富士苹果」或「城东水果批发的所有商品」）。",
            )
        }

        val members = if (shipperNames.isEmpty()) {
            allMembers
        } else {
            shipperNames.map { name ->
                AiWriteArgs.strict(name, allMembers, "批发商")
                    ?: throw AiWriteArgException("「$name」不是批发商（可能是个普通货主）。")
            }
        }
        val products = if (productNames.isEmpty()) {
            allProducts
        } else {
            productNames.map { name ->
                val hit = AiWriteArgs.strict(name, allProducts.map { AiName(it.id, it.name) }, "商品")
                    ?: throw AiWriteArgException("找不到商品「$name」。")
                allProducts.first { it.id == hit.id }
            }
        }
        if (members.isEmpty()) throw AiWriteArgException("系统里还没有批发商（没有 is_member 的账号）。")
        if (products.isEmpty()) throw AiWriteArgException("没有可调价的商品。")

        // ---- 2. 幅度：涨/降百分比，或者直接设一个统一单价 ----
        val adjustRaw = AiWriteArgs.str(params, "adjust")
        val fixedRaw = AiWriteArgs.str(params, "price")
        if (adjustRaw == null && fixedRaw == null) {
            throw AiWriteArgException("缺少 adjust 或 price：这次是涨/降百分之多少，还是直接定一个统一单价？")
        }
        if (adjustRaw != null && fixedRaw != null) {
            throw AiWriteArgException("adjust（按百分比调）和 price（直接定单价）只能给一个。")
        }
        val adjust: BigDecimal? = adjustRaw?.let { parsePercent(it) }
        val fixed: BigDecimal? = fixedRaw?.let { AiWriteArgs.parseMoney(it, "price", mustPositive = false) }

        // ---- 3. 把 before → after 算出来（这是卡片的全部价值） ----
        val rules: Map<Pair<Long, Long>, String> = ds.priceRuleRows().associate { (it.shipperId to it.productId) to it.price }
        val changes = ArrayList<PriceChange>(members.size * products.size)
        for (m in members) {
            for (p in products) {
                val existing = rules[m.id to p.id]
                val before = existing ?: p.defaultPrice
                val after = when {
                    fixed != null -> fixed
                    else -> BigDecimal(before)
                        .multiply(BigDecimal(100).add(adjust))
                        .divide(BigDecimal(100), 2, RoundingMode.HALF_UP)
                }
                if (after.signum() < 0) {
                    throw AiWriteArgException(
                        "「${m.label} × ${p.name}」按这个幅度算出来是负数（${before} → ${after}）。" +
                            "请让用户确认幅度——降幅超过 100% 是没有意义的。",
                    )
                }
                changes += PriceChange(m.label, p.name, BigDecimal(before).setScale(2, RoundingMode.HALF_UP), after, existing != null)
            }
        }

        val direction = when {
            fixed != null -> "统一设为 ${AiWriteArgs.money(fixed)} 元"
            // adjust 与 fixed 二选一，这里 adjust 一定非空；用 requireNotNull 而不是 !! 是为了
            // 万一将来有人改坏了这个约束，错误信息能说清楚是哪里坏的。
            else -> {
                val pct = requireNotNull(adjust) { "adjust 与 fixed 必须恰好给一个" }
                when {
                    pct.signum() < 0 -> "降 ${pct.abs().stripTrailingZeros().toPlainString()}%"
                    pct.signum() > 0 -> "涨 ${pct.stripTrailingZeros().toPlainString()}%"
                    else -> "不变（幅度是 0）"
                }
            }
        }

        val details = ArrayList<String>(MAX_LISTED + 6)
        // ⚠️ 这一行会渲染在确认卡上（普通 Text，不解析 Markdown），别写 `**加粗**`。
        details += "范围：${members.size} 个批发商 × ${products.size} 个商品 ＝ ${changes.size} 条价格"
        details += "幅度：$direction"
        details += "———— 逐条改动 ————"
        changes.take(MAX_LISTED).forEach { c ->
            details += "· ${c.shipper} ${c.product}：${AiWriteArgs.money(c.before)} → ${AiWriteArgs.money(c.after)}" +
                if (c.hadRule) "" else "（原来按通用价）"
        }
        if (changes.size > MAX_LISTED) details += "…… 还有 ${changes.size - MAX_LISTED} 条，未逐条列出"
        details += "⚠️ 这会覆盖这些批发商已有的专属价（没有专属价的会新建一条）"

        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = "批量调价：${changes.size} 条 · $direction",
                detailLines = details,
                payload = buildJsonObject {
                    put("shipper_ids", JsonArray(members.map { JsonPrimitive(it.id) }))
                    put("product_ids", JsonArray(products.map { JsonPrimitive(it.id) }))
                    if (fixed != null) {
                        put("mode", "fixed")
                        put("value", fixed.toPlainString())
                    } else {
                        put("mode", "adjust")
                        put("adjust_percent", adjust!!.stripTrailingZeros().toPlainString())
                    }
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.batchPriceRules(
            shipperIds = payload.longList("shipper_ids"),
            productIds = payload.longList("product_ids"),
            mode = payload.str("mode").orEmpty(),
            value = payload.str("value"),
            adjustPercent = payload.str("adjust_percent"),
        )
    }

    /** 卡片上逐条列出时最多列几条（再多就只是噪音，用户不会一条条看）。 */
    private companion object {
        const val MAX_LISTED = 12
    }

    private data class PriceChange(
        val shipper: String,
        val product: String,
        val before: BigDecimal,
        val after: BigDecimal,
        /** true = 之前已经有专属价（false = 按通用价买）。 */
        val hadRule: Boolean,
    )

    /**
     * 百分比解析：收 `-15`、`-15%`、`降15%`、`涨10`。
     *
     * 为什么单独一个解析器而不是复用金额的：金额有"上限 100 万"那条防多打零的规则，
     * 而百分比的上限是另一个数量级（±100 / +1000），套用金额的规则会把合法的 15 也拦掉。
     */
    private fun parsePercent(raw: String): BigDecimal {
        var s = raw.trim().removeSuffix("%").removeSuffix("％").trim()
        var sign = 1
        if (s.startsWith("降") || s.startsWith("下调") || s.startsWith("-")) sign = -1
        if (s.startsWith("涨") || s.startsWith("上调") || s.startsWith("+")) sign = 1
        s = s.removePrefix("降").removePrefix("下调").removePrefix("涨").removePrefix("上调")
            .removePrefix("-").removePrefix("+").removeSuffix("%").trim()
        val v = s.toBigDecimalOrNull()
            ?: throw AiWriteArgException(
                "adjust「$raw」看不懂。请只给一个百分比数字：涨填 10（或 +10），降填 -10。",
            )
        val signed = v.multiply(BigDecimal(sign))
        if (signed < BigDecimal(-100) || signed > BigDecimal(1000)) {
            throw AiWriteArgException("adjust 是 ${signed.toPlainString()}%，超出允许范围（-100% ~ +1000%），请先核对。")
        }
        return signed
    }
}

// ============================================================== 按表格调价

/**
 * 用户**贴一张表格**批量调价（用户原话里的第四种用法）。
 *
 * ### 它和 [BatchPriceHandler] 的关系
 * 那个动作是「(若干批发商) × (若干商品) × **一套**规则」——后端一次原子调用就能做完。
 * 这一个每行的规则都不一样（`红富士 → 城东 -10%`、`皇冠梨 → 明辉 新价 3.80`），
 * 后端一次调用**套不了多套规则**，所以只能**逐行执行**。
 *
 * ### 为什么是"一张卡 + 逐行提交"，而不是"每行一张卡"
 * `AiWritePreviewStore.MAX_PENDING = 4`：一张 20 行的表会弹 20 张卡，
 * 前面那些会被挤掉，而用户根本来不及看清。更要紧的是**语义**：
 * 用户贴的是一张表，他要核对的也是**整张表**（"这就是我做的那张表吗"），
 * 而不是 20 次"这一行对吗"。所以一张卡列全部行，点一次确认，逐行发出去。
 *
 * ### 逐行执行就会**部分成功**
 * 这是这个动作唯一"不干净"的地方：第 3 行因为别人同时改了商品名而失败时，
 * 第 4~20 行**已经写进去了**。所以：
 * - 发卡**之前**把每一行都校验一遍（名字、幅度、算出来的价），**有一行不合法就整张卡不发**——
 *   把"部分成功"压到"只在并发这种真意外时才发生"；
 * - 提交时逐行 `try/catch`，**不因为一行失败就中断**（中断会留下"后面的行没做、而用户以为没做"的
 *   更难解释的状态）；
 * - 执行完**如实汇报**（[commitNote]）：全成功就说全成功，有失败就把**第几行、为什么**列出来。
 *   绝不会只显示一句"已完成"——那等于把失败的几行藏起来。
 */
class ApplyPriceTableHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId = AiWrites.PRICE_RULES_APPLY_TABLE

    /**
     * 执行完之后要补的那句话（一次性：取走即清空）。
     *
     * 为什么需要它：`AiWriteService.execute` 给用户的反馈是"已完成：<卡片摘要>"，
     * 而这张摘要是在**预览时**写好的——那时还不知道哪几行会失败。
     * 批量动作如果只能回那一句，用户就会以为 20 行全成了（**这正是最坏的结果**）。
     */
    private var pendingNote: String? = null

    override fun commitNote(): String? = pendingNote.also { pendingNote = null }

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        val text = AiWriteArgs.required(
            params,
            "rows",
            "把用户贴的那张表格**原样**放进 rows（一行一条）。如果用户没贴表格，就别用这个动作。",
        )
        val forced = when (AiWriteArgs.str(params, "mode")?.trim()?.lowercase()) {
            null, "" -> null
            "adjust", "percent", "百分比" -> AiPriceTable.Mode.ADJUST
            "fixed", "price", "新价", "固定价" -> AiPriceTable.Mode.FIXED
            else -> throw AiWriteArgException(
                "mode 只能是 adjust（涨跌百分比）或 fixed（绝对新价）。",
            )
        }

        val allMembers = ds.members()
        val allProducts = ds.productPrices()
        val rows = AiPriceTable.parse(
            text = text,
            products = allProducts.map { AiName(it.id, it.name) },
            members = allMembers,
            forcedMode = forced,
        )
        if (allMembers.isEmpty()) {
            throw AiWriteArgException("系统里还没有批发商（没有 is_member 的账号），没法设专属价。")
        }

        // ---- 算 before → after（这是卡片存在的理由：用户核对的就是这串数字）----
        val rules = ds.priceRuleRows().associate { (it.shipperId to it.productId) to it.price }
        val productById = allProducts.associateBy { it.id }
        val planned = rows.map { r ->
            val p = productById.getValue(r.product.id)
            // 这一行覆盖的批发商：点名的一个，或者全部
            val targets = if (r.shipper != null) listOf(r.shipper) else allMembers
            val changes = targets.map { m ->
                val before = rules[m.id to p.id] ?: p.defaultPrice
                val after = when (r.mode) {
                    AiPriceTable.Mode.FIXED -> r.value
                    AiPriceTable.Mode.ADJUST -> BigDecimal(before)
                        .multiply(BigDecimal(100).add(r.value))
                        .divide(BigDecimal(100), 2, RoundingMode.HALF_UP)
                }
                if (after.signum() < 0) {
                    throw AiWriteArgException(
                        "表格第 ${r.lineNo} 行：${m.label} 的 ${p.name} 按这个幅度算出来是负数" +
                            "（$before → $after）。请让用户确认这一行的幅度。",
                    )
                }
                Planned(r.lineNo, m.id, m.label, p.id, p.name, BigDecimal(before).setScale(2, RoundingMode.HALF_UP), after, r.mode, r.value)
            }
            changes
        }.flatten()

        if (planned.isEmpty()) throw AiWriteArgException("这张表读出来是空的，没有可执行的调价。")

        val pctCount = planned.count { it.mode == AiPriceTable.Mode.ADJUST }
        val fixedCount = planned.size - pctCount
        val valueCaveat = when {
            forced != null -> null
            pctCount > 0 && fixedCount == 0 -> "表格里没写「元/新价」，这一列按**百分比**读的"
            fixedCount > 0 && pctCount == 0 -> "表格里带「元/新价」或表头写的是价格，这一列按**绝对新价**读的"
            else -> "这张表里两种都有：带 % 的按百分比、带「元/新价」的按绝对价格"
        }

        val details = ArrayList<String>(AiPriceTable.MAX_ROWS + 8)
        details += "表格：${rows.size} 行 → 覆盖 ${planned.size} 条价格（${planned.map { it.shipperLabel }.distinct().size} 个批发商 × ${rows.map { it.product.id }.distinct().size} 个商品）"
        if (valueCaveat != null) details += "读法：$valueCaveat"
        details += "———— 逐行改动 ————"
        planned.take(MAX_LISTED).forEach { c ->
            details += "· 第 ${c.lineNo} 行 ${c.shipperLabel} ${c.productName}：${AiWriteArgs.money(c.before)} → ${AiWriteArgs.money(c.after)}" +
                if (c.mode == AiPriceTable.Mode.ADJUST) {
                    "（${if (c.value.signum() < 0) "降" else "涨"} ${c.value.abs().stripTrailingZeros().toPlainString()}%）"
                } else {
                    "（新价）"
                }
        }
        if (planned.size > MAX_LISTED) details += "…… 还有 ${planned.size - MAX_LISTED} 条，未逐条列出"
        details += "⚠️ 会覆盖这些批发商已有的专属价（没有专属价的会新建一条）"
        // ⚠️ 这句必须写：逐行执行＝可能部分成功，用户点确认前有权知道失败时会怎样。
        // 真机实测时卡片上出现过字面的 `**`，所以这里一律不用 Markdown 记号。
        details += "⚠️ 这是一行一行发出去的：万一中间某行被后端拒绝，其余行仍然会执行，我会把失败的那几行列给你"

        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = "按表格调价：${rows.size} 行 · ${planned.size} 条价格",
                detailLines = details,
                payload = buildJsonObject {
                    put(
                        "rows",
                        JsonArray(
                            rows.map { r ->
                                buildJsonObject {
                                    put("product_id", r.product.id.toString())
                                    put("mode", if (r.mode == AiPriceTable.Mode.FIXED) "fixed" else "adjust")
                                    // 用 money() 保留两位：卡片上写的是 3.80，发出去的也得是 3.80
                                    // （"卡片上写的 == 真正发出去的"是这套框架的不变量；
                                    //   stripTrailingZeros 会把它变成 3.8，值一样但字面不一致）。
                                    put("value", AiWriteArgs.money(r.value))
                                    // ⚠️ 空列表就**不放这个键**（payload 约定：空字符串 = 没给）：
                                    // 不放 = 全部批发商，后端语义就是这样。
                                    if (r.shipper != null) put("shipper_ids", JsonArray(listOf(JsonPrimitive(r.shipper.id))))
                                    put("line", r.lineNo.toString())
                                }
                            },
                        ),
                    )
                },
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val rows = (payload["rows"] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
        if (rows.isEmpty()) {
            // 走到这里说明 payload 坏了（App 内部错误），如实说，不要假装成功。
            pendingNote = "这次没有要执行的表格行（内部错误），什么都没写。"
            return
        }
        val ok = ArrayList<Int>()
        val failed = ArrayList<String>()
        rows.forEachIndexed { idx, r ->
            val line = r.str("line")?.toIntOrNull() ?: (idx + 1)
            val productId = r.str("product_id")?.toLongOrNull()
            val shipperIds = (r["shipper_ids"] as? JsonArray)
                ?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.toLongOrNull() }
                .orEmpty()
            if (productId == null) {
                failed += "第 $line 行（内部错误：商品编号丢了）"
                return@forEachIndexed
            }
            try {
                val isFixed = r.str("mode") == "fixed"
                ds.batchPriceRules(
                    shipperIds = shipperIds,
                    productIds = listOf(productId),
                    // 后端的两种模式共用同一个端点：fixed 用 value（新价），adjust 用 adjust_percent（涨跌幅）
                    mode = if (isFixed) "fixed" else "adjust",
                    value = if (isFixed) r.str("value") else null,
                    adjustPercent = if (isFixed) null else r.str("value"),
                )
                ok += line
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                failed += "第 $line 行（${e.message ?: e.javaClass.simpleName}）"
            }
        }
        pendingNote = buildString {
            append("表格逐行结果：成功 ${ok.size} 行")
            if (failed.isEmpty()) {
                append("，全部写完")
            } else {
                append("、失败 ${failed.size} 行 —— ")
                append(failed.joinToString("；"))
                if (ok.isNotEmpty()) append("。（失败的行没写进去，成功的已经生效）")
            }
        }
    }

    private data class Planned(
        val lineNo: Int,
        val shipperId: Long,
        val shipperLabel: String,
        val productId: Long,
        val productName: String,
        val before: BigDecimal,
        val after: BigDecimal,
        val mode: AiPriceTable.Mode,
        val value: BigDecimal,
    )

    private companion object {
        /** 卡片上逐条列出时最多列几条。**和 [BatchPriceHandler] 用同一个数**：都是"看一眼就够"的量。 */
        const val MAX_LISTED = 12
    }
}

/**
 * 批量调价的动作定义（行为在 [BatchPriceHandler] 与 [ApplyPriceTableHandler]）。
 *
 * ### 为什么档位是 HIGH
 * 一次动**成百上千条**价格，而卡片只能列出前 12 条。用户核对不完，
 * 所以真正拦住错误的地方是**范围**那一行（"3 个批发商 × 5 个商品 = 15 条"）和**幅度**那一行
 * ——他要能一眼看出"这不是我要的那个范围"。范围写错比幅度写错严重得多：
 * 幅度写错是全面的偏差（一眼能看出来），范围写错是**一部分人价格变了、另一部分没变**，
 * 而这两拨人自己不会知道。
 *
 * 所以这里强制了一条：**批发商和商品不能同时留空**。
 * 「所有批发商的所有商品一起涨价」是一个真实存在但极少见的操作，
 * 而它一旦是误触，影响面是整张价格表。
 */
internal object AiWritePricing {

    val ACTIONS: List<AiWriteAction> = listOf(
        AiWriteAction(
            id = AiWrites.PRICE_RULES_BATCH,
            title = "批量调价",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_PRICE,
            blurb = "给一批批发商的一批商品统一调价。**涨/降按百分比是在当前价基础上算的**" +
                "（不是按商品默认价），也可以直接设一个统一单价。",
            params = listOf(
                AiWriteParam(
                    "shipper", "批发商", required = false, kind = AiWriteParamKind.TEXT,
                    hint = "要调哪几个批发商。多个用「、」隔开；**留空 = 全部批发商**。" +
                        "但 shipper 和 product **不能同时留空**（那就是全表调价）",
                ),
                AiWriteParam(
                    "product", "商品", required = false, kind = AiWriteParamKind.TEXT,
                    hint = "要调哪几个商品。多个用「、」隔开；**留空 = 全部商品**",
                ),
                AiWriteParam(
                    "adjust", "涨降百分比", required = false, kind = AiWriteParamKind.NUMBER,
                    hint = "在**当前价**基础上涨/降百分之多少：降 15% 填 -15，涨 10% 填 10。" +
                        "与 price 二选一",
                ),
                AiWriteParam(
                    "price", "统一单价（元）", required = false, kind = AiWriteParamKind.NUMBER,
                    hint = "把范围内所有价格直接设成这个数（只传数字）。与 adjust 二选一",
                ),
            ),
        ),
        AiWriteAction(
            id = AiWrites.PRICE_RULES_APPLY_TABLE,
            title = "按表格调价",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_PRICE,
            blurb = "用户**贴了一张表格**、每行一套调价规则时用它（几行到几十行，行与行的价格可以不同）。" +
                "把表格**原样**放进 rows，**不要改写、不要重排、不要只挑几行**——" +
                "系统会自己读那张表，并把「读到的每一行」列在确认卡上让用户逐行核对。",
            params = listOf(
                AiWriteParam(
                    "rows", "表格原文", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填。把用户贴的那张表**逐行原样**放进来（保留换行）。" +
                        "列之间用空格/Tab/逗号/竖线都行。" +
                        "**不要**自己加解释、不要只挑几行、不要改写成 JSON、" +
                        "**不要算好新价再填**（把用户写的数字原样留着）",
                ),
                AiWriteParam(
                    "mode", "那列数字是什么", kind = AiWriteParamKind.ENUM,
                    hint = "可选。表格里的数字**既没写 % 也没有表头**时才填：" +
                        "adjust=涨跌百分比、fixed=绝对新价；拿不准就留空" +
                        "（留空按百分比读，卡片会把这一点写出来）",
                    enumValues = listOf("adjust", "fixed"),
                ),
            ),
        ),
    )
}

/** 把「A、B，C」拆成一组名字（空/null → 空列表 = 全部）。 */
private fun splitNames(raw: String?): List<String> {
    if (raw.isNullOrBlank()) return emptyList()
    val all = raw.trim().lowercase()
    // 「全部」「所有」这类词等同于留空。用户和模型都会这么写。
    if (all in setOf("全部", "所有", "全部批发商", "所有批发商", "全部商品", "所有商品", "all", "*", "全部商户")) {
        return emptyList()
    }
    return raw.split('、', '，', ',', ';', '；')
        .map { it.trim() }
        .filter { it.isNotEmpty() }
}

private fun JsonObject.longList(key: String): List<Long> =
    (this[key] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.toLongOrNull() } ?: emptyList()
