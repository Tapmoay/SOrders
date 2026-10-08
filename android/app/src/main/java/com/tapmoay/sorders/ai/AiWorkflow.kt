package com.tapmoay.sorders.ai

/**
 * **业务工作流**：用户说一句业务目标（「这个月帮我对一下账」「把这几个商品给批发商降 5%」），
 * AI 自己认出该走哪条流程、按固定步骤跑完，最后把**结论**交回来 —— 用户少说几句。
 *
 * ### 用户口径（2026-10-09 本会话拍板）
 * - 先做哪条：「**两条一起做**」—— 对账 + 批量调价同一单交。
 * - 跑到要改数据那一步怎么办：「**先给结论，再问一句要不要发卡**」——
 *   先把明细和金额摆出来让他看，他点头才生成确认卡。
 * - goal ② 原文（`goal-9c29e859-ec5e-444e-9e78-6e330bf0aa07`）：「业务工作流 —— 内置多步流程
 *   （对账、批量调价这类），AI 认出来后自己按步骤跑完整件事，用户少说几句。」
 * - 本单：**CHG-0096**（业务多步工作流的第一批：对账 ＋ 批量调价 —— 读能力有 36 条，
 *   够格"多步 ＋ 每步结果要对上"的只有这两条）。
 *
 * ### 为什么是「代码里的编排器」，不是提示词里的步骤清单
 * 计划文档 §15.6（`docs/AI_ASSISTANT_PLAN_V3.md:622-630`）早就定了：工作流 ≈ agent 循环**之上的一层编排**，
 * 「而不是把步骤塞进 system prompt 让模型自己记」。理由很具体：对账必须把
 * 「这段时间已送达的单」和「账本里这段时间的流水」**用同一个窗口**各查一次再按订单号对差集；
 * 步骤落在提示词里 = 每轮重发一遍、每次还可能漏一步或换个窗口 —— 而窗口一错，
 * 结论就是「这个月少记了三万块」这种**看着最像真的**的假账。
 *
 * ### 它一步都不写
 * 工作流只**查**：跑完给 `conclusion`（结论）+ `next`（该发哪张卡、参数是什么、要问用户哪一句）。
 * 发卡仍然只走 `preview_write` 那一条路 —— 「写能力只有一条路径」这条红线不动，
 * 而用户拍板的「先给结论，再问一句要不要发卡」正好落在同一个形状上。
 *
 * ### 判据
 * `AiWorkflowTest` 直接读这一份（提示词拼它、单测查它，同一份，与 [AiAnswerSkills] 同一规矩）。
 */
internal data class AiWorkflowStep(
    /** 这一步在读什么。**回话与痕迹里那一行就是它**，⛔ 不许在 runner 里另写一遍文案（会漂移）。 */
    val title: String,
    /** 读目录里的 action（`AiReadCatalog` / `AiLocalReads` 里真实存在的 key）。 */
    val action: String,
)

/**
 * 一条登记在案的工作流。
 *
 * [nextAction] 是**写动作的 id**（`AiWrites` 里的那一个）：工作流自己**不执行**它，
 * 只把它连同参数交给模型，让模型问过用户之后走 `preview_write` 发卡。
 */
internal data class AiWorkflow(
    val id: String,
    val cn: String,
    /** 用户说哪些话时就该选它（写进提示词，让模型**自己认出来**，不是等用户点名）。 */
    val whenToUse: String,
    /** 除 `from` / `to` 两个通用参数外，还要模型给什么。 */
    val paramsCn: String,
    val steps: List<AiWorkflowStep>,
    val nextAction: String,
    /** 结论给完之后要问用户的那一句（这里写好，模型照说）。 */
    val ask: String,
    /** 谁能用。两条都是派单员专属 —— 它们要发的写动作本身就不在货主的白名单里。 */
    val roles: Set<AiRole> = setOf(AiRole.DISPATCHER),
)

internal object AiWorkflows {

    const val LEDGER_RECONCILE = "ledger.reconcile"
    const val PRICE_BATCH = "price.batch"

    /**
     * **对账**：这段时间「已送达的单」↔「账本里的流水」。
     *
     * 为什么它不是"查一次"能问出来的：要两张表按同一个窗口各查一次、再按订单号对差集。
     * 而"哪张单该记账"这条规则**只有后端有**
     * （`backend/app/services/ledger_sync.py:14`：已送达 **且**有归属才记；没有归属的单**永远**不会自动记），
     * 所以结论里必须把「无归属」单独说清楚 —— 否则用户会以为那几张单也该自动进账，白等。
     */
    val RECONCILE = AiWorkflow(
        id = LEDGER_RECONCILE,
        cn = "对账",
        whenToUse = "用户说「这个月对一下账」「哪些单还没进账本」「账对不上」「有没有漏记的」这类",
        paramsCn = "shipper：只看这一位货主（可选，传名字，不要传编号）",
        steps = listOf(
            AiWorkflowStep("查这段时间已送达的订单", "orders.list_orders"),
            AiWorkflowStep("查这段时间的账本流水", "ledger.list_entries"),
        ),
        nextAction = AiWrites.LEDGER_SYNC_DELIVERED,
        ask = "要不要我发一张「补进账本」的确认卡？点确认之后系统会把该补的补上（重复跑不会重复入账）。",
    )

    /**
     * **批量调价**：先查清「要调的是哪几个商品、现有专属价有几条」，再让用户确认。
     *
     * ⛔ 它**一条价都不算**：涨降的算法（在当前价基础上按百分比、`HALF_UP` 到分）
     * 唯一一份实现在 `AiWritePricing.kt` 的 `BatchPriceHandler` 里，
     * 卡片上那串「改前 → 改后」就是权威。这里再算一遍 = 两份实现，迟早对不上
     * （本仓的规矩：同一个数只有一处算）。
     * 它解决的是**另一件事**：用户说「菜籽油降 5%」时，名字里带「菜籽油」的到底有几个商品、
     * 有几位批发商已经定了专属价会被覆盖 —— 这正是确认卡发出**之前**该看一眼的。
     */
    val PRICE_ADJUST = AiWorkflow(
        id = PRICE_BATCH,
        cn = "批量调价",
        whenToUse = "用户说「把这几个商品降/涨价」「所有批发商的某商品统一调价」这类",
        paramsCn = "product：商品名，多个用「、」隔开（留空＝全部商品）；" +
            "shipper：批发商名，多个用「、」隔开（留空＝全部批发商）；" +
            "adjust：在当前价基础上涨降百分比（降 15 填 -15）；price：统一单价（与 adjust 二选一）",
        steps = listOf(
            AiWorkflowStep("查商品与通用价", "products.list_products"),
            AiWorkflowStep("查现有的批发商专属价", "price_rules.list_price_rules"),
        ),
        nextAction = AiWrites.PRICE_RULES_BATCH,
        ask = "要不要我发一张调价确认卡？卡上会逐条列出改前 → 改后，你核对完再点确认。",
    )

    /** 登记表。加一条工作流 = 在这里加一项 **+ 在 [AiWorkflowRunner] 里接上同名的执行分支**。 */
    val ALL: List<AiWorkflow> = listOf(RECONCILE, PRICE_ADJUST)

    /** 工具 schema 里的 `enum`（从登记表算，加一条就自动出现，不会漏）。 */
    val IDS: List<String> = ALL.map { it.id }

    fun byId(id: String): AiWorkflow? = ALL.firstOrNull { it.id == id }

    /** 这个角色能跑的工作流。**认不出角色 = 一条都不给**（与工具白名单同一条 fail-closed）。 */
    fun forRole(role: AiRole?): List<AiWorkflow> =
        if (role == null) emptyList() else ALL.filter { role in it.roles }

    /**
     * `run_workflow` 的工具说明 —— **从登记表拼**。
     *
     * 为什么不手写：手写的清单在加工作流时一定会漏（设置页那句"可申请：…"就踩过这个坑，
     * 见 `AiTools.previewWriteHint`）。这里少写一条的症状是「模型根本不知道有这条工作流」，
     * 静默失效，没有报错。
     */
    val TOOL_DESCRIPTION: String = buildString {
        appendLine("跑一条登记在案的多步工作流：一次调用把整件事查完 —— 比你自己一步一步查更快、也不会漏步骤。")
        appendLine("现在能跑这些：")
        ALL.forEach { w ->
            appendLine("- " + w.id + "（" + w.cn + "）：" + w.whenToUse + "。")
            appendLine("  · 参数：" + w.paramsCn + "。")
            appendLine("  · 它会做这几步：" + w.steps.joinToString("；") { it.title } + "。")
            appendLine("  · 跑完给你结论（" + w.cn + "），并告诉你要不要发确认卡 —— **它自己一步都不写**。")
        }
        appendLine("⛔ 时间范围：用户没说就用**本月 1 号到今天**，并在回答里写明你用的是哪一段。")
        appendLine("⛔ 跑完先给结论，再问 `next.ask` 那一句；用户没点头**不许**调 preview_write。")
    }

    /**
     * 提示词里的「工作流目录 + 纪律」（[AiAgentLoop.systemPrompt] 接在 [AiAnswerSkills.RULES] 之后）。
     *
     * ⛔ 这里只写**目录与纪律**，⛔ 不写步骤 —— 步骤在代码里跑（见文件头那段「为什么不是步骤清单」）。
     * 编号 13 接在 [AiAnswerSkills] 的第 12 条之后；⛔ 不要动前面第 1~12 条的编号
     * （`_tools/qa/_check_order_contact_required.py` 与它的反验都钉着那些字面量）。
     */
    val RULES: String = buildString {
        appendLine("13. **认出「多步的活」，别一步一步等用户催**（下面这些是登记在案的工作流，用 `run_workflow` 一次跑完）：")
        ALL.forEach { w ->
            appendLine("   - " + w.cn + "（`" + w.id + "`）：" + w.whenToUse + "。")
        }
        appendLine("   - 跑之前先把时间范围定下来：用户没说就用**本月 1 号到今天**，并在回话里写明你用的是哪一段。")
        appendLine("   - 它给的 `conclusion` 是**查出来的**：照原话说。⛔ 不要自己再算一遍、不要四舍五入、不要补它没查的数。")
        appendLine("     它给的 `steps` 是每一步实际取到多少条 —— 用户问「你查了什么」时按它说，⛔ 不要编中间的查询。")
        appendLine("   - `next` 里是「该发哪张卡 + 参数 + 要问用户的那一句」：**先把结论给用户，再问那一句**；")
        appendLine("     用户没点头之前⛔ **不许**调 preview_write。工作流自己一步都不会写。")
        appendLine("   - 它标了 `incomplete=true` 时（一次取不完）：⛔ 不许把那些数字当完整的账报给用户，照它说的让用户缩小范围重跑。")
        appendLine("   - 这两条都不适用时，才退回你自己用 read_data 一步一步查。")
    }
}
