package com.tapmoay.sorders.ai

/**
 * **业务工作流**：用户说一句业务目标（「这个月帮我对一下账」「给城东水果批发送 3 件红富士苹果」），
 * AI 自己认出该走哪条流程、按固定步骤跑完，最后把**结论**交回来 —— 用户少说几句。
 *
 * ### 用户口径（2026-10-09 拍板 ＋ 2026-10-11 FEAT-0020）
 * - 先做哪条：「**两条一起做**」—— 对账 + 批量调价同一单交（CHG-0096）。
 * - 跑到要改数据那一步怎么办：「**先给结论，再问一句要不要发卡**」——
 *   先把明细和金额摆出来让他看，他点头才生成确认卡。
 * - goal ② 原文（`goal-9c29e859-ec5e-444e-9e78-6e330bf0aa07`）：「业务工作流 —— 内置多步流程
 *   （对账、批量调价这类），AI 认出来后自己按步骤跑完整件事，用户少说几句。」
 * - **FEAT-0020（用户原话）**：「为什么我们的货主或者批发商他的 AI 没有对应的技能和工作流呢，
 *   也是要具备的哦」—— 上面那两条是**派单员专属**，货主 / 批发商一条都没有。
 *   本单把工作流补给他们：货主 5 条（下单 / 查单 / 账本小结 / 退货申请 / 改联系信息），
 *   批发商货主再多 1 条（改自己那一本下游价）。
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
 * ### 只读工作流（FEAT-0020）：查完直接给结论，**不发卡**
 * 「我这单到哪了」「本月账本小结」这类**没有下一步要改的东西**：查完把结论说清楚就结束了。
 * 所以 [AiWorkflow.nextAction] / [AiWorkflow.ask] 都是可空的，两条都为空 = 只读
 * （[AiWorkflow.readOnly]）。执行器那边**明确不给** `next` / `ask` 两个键，
 * 工具说明与第 13 条也分两种口气写 —— ⛔ 别让模型以为只读的那些也会发卡
 * （它会去问「要不要我发一张确认卡」，然后**没有卡可发**）。
 *
 * ### 判据
 * `AiWorkflowTest` 直接读这一份（提示词拼它、单测查它，同一份，与 [AiAnswerSkills] 同一规矩）；
 * 跨文件的那几条（步骤 action 在读目录里、每条 nextAction 在**对应角色的写白名单**里、
 * 谁的角色能跑哪几条）由 `_tools/qa/_check_shipper_ai_workflows.py` 钉。
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
 * **只读工作流两个都传 null**（见文件头那段）。
 */
internal data class AiWorkflow(
    val id: String,
    val cn: String,
    /** 用户说哪些话时就该选它（写进提示词，让模型**自己认出来**，不是等用户点名）。 */
    val whenToUse: String,
    /** 除 `from` / `to` 两个通用参数外，还要模型给什么。 */
    val paramsCn: String,
    val steps: List<AiWorkflowStep>,
    /**
     * 交棒的写动作 id；**只读工作流传 null**（查完直接给结论，没有下一步要改的东西）。
     *
     * ⚠️ 它与 [ask] **必须同生同灭**：有动作没话问、有话问没动作，两种都是登记写坏了
     * （单测与判据各钉一次）。
     */
    val nextAction: String?,
    /** 结论给完之后要问用户的那一句（这里写好，模型照说）；**只读工作流传 null**。 */
    val ask: String?,
    /** 谁能用。默认派单员专属 —— 要发的写动作本身不在货主白名单里的那些就该留在这个默认值上。 */
    val roles: Set<AiRole> = setOf(AiRole.DISPATCHER),
    /**
     * 只有**批发商货主**（`users.is_member=1`）能用。
     *
     * 与 `AiWriteAction.memberOnly` 同一条：普通货主手机上根本没有「我的下游价」那一段，
     * 给他的 AI 列出来只会让它去解释一件他做不了的事（「能看见但一定失败」是本仓最坏一类 bug）。
     */
    val memberOnly: Boolean = false,
) {
    /** 只读工作流：跑完给结论，**不发卡**（执行器的返回里没有 `next` / `ask`）。 */
    val readOnly: Boolean get() = nextAction == null
}

internal object AiWorkflows {

    const val LEDGER_RECONCILE = "ledger.reconcile"
    const val PRICE_BATCH = "price.batch"

    // ---- 货主那 5 条（FEAT-0020）----
    const val ORDER_PLACE = "order.place"
    const val ORDER_TRACK = "order.track"
    const val LEDGER_MONTHLY = "ledger.monthly"
    const val ORDER_RETURN_REQUEST = "order.return_request"
    const val ORDER_CONTACT = "order.contact"

    /** 批发商货主（`is_member`）多出来的那一条（FEAT-0020）。 */
    const val PRICE_MINE = "price.mine"

    /** 货主那一组（普通货主与批发商货主都是这个角色，两条的分野在 [AiWorkflow.memberOnly]）。 */
    private val SHIPPER_ROLES = setOf(AiRole.SHIPPER)

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

    // ============================================================ 货主那 5 条（FEAT-0020）

    /**
     * **一句话下单**（货主）：用户说「给城东水果批发送 3 件红富士苹果到××地址」。
     *
     * ⛔ 它**不填单价**：单价按**这个货主自己的价**算（`CreateOrderHandler` 里
     * `shipperId = ds.currentUserId()` 那一条路）—— 模型自己编一个价，
     * 用户就会在卡上看到两个数（"批发商谈好 10 元，AI 建出来的单按 20 元"）。
     * 所以这一步只**核对**：商品在不在、数量是多少、联系人/地址对不对，然后把
     * 「商品 + 数量 + 联系人 + 地址」交给确认卡。
     */
    val PLACE_ORDER = AiWorkflow(
        id = ORDER_PLACE,
        cn = "一句话下单",
        whenToUse = "用户说「给城东水果批发送 3 件红富士苹果到××地址」「帮我下这一单」「再来一单和上次一样的」这类" +
            "（他自己要发货 —— 下单是他真能干的事，派单是派单员的活）",
        paramsCn = "product：商品名，多个用「、」隔开；quantity：数量（只传数字）；" +
            "contact：收货人（他名册里的联系人，可选）；address：送货地址（用户说了才填，没说就留空，让他事后在页面上补）",
        steps = listOf(
            AiWorkflowStep("查商品与单价", "products.list_products"),
            AiWorkflowStep("查我的收货联系人", "shipper.list_contacts"),
            AiWorkflowStep("查我的送货地址", "shipper.list_addresses"),
        ),
        nextAction = AiWrites.ORDERS_CREATE,
        ask = "要不要我发一张「创建订单」的确认卡？卡上会逐行列出商品、数量、单价与合计，你核对完再点确认。",
        roles = SHIPPER_ROLES,
    )

    /**
     * **查单到哪了**（货主，**只读**）：查完直接给结论，**没有卡**。
     *
     * 为什么它必须是只读的：用户问「我那单到哪了」，他知道的答案就是"在谁手上、到没到"，
     * 这里**没有任何一件要改的事**。给它配一张卡，模型就会去问「要不要发一张确认卡」——
     * 而那张卡该写什么、点了会改什么，谁都答不上来。
     */
    val TRACK_ORDER = AiWorkflow(
        id = ORDER_TRACK,
        cn = "查单到哪了",
        whenToUse = "用户说「我那单到哪了」「今天有几单在送」「××单送到了吗」「是谁在送」这类（**只读**：查完直接给结论，不发卡）",
        paramsCn = "order：订单号（可选 —— 只问某一张单时给；不给就按时间范围汇总）；" +
            "status：只看某一档状态（可选，取值照订单自己的枚举）",
        steps = listOf(
            AiWorkflowStep("查我的订单（状态 / 司机 / 到货时间）", "orders.list_orders"),
        ),
        nextAction = null,
        ask = null,
        roles = SHIPPER_ROLES,
    )

    /**
     * **本月账本小结**（货主，**只读**）：已付 / 还欠 / 哪几单还没结。
     *
     * 「我该付的」那三个数是**服务端算的**（`/shipper-ledger/summary`，不设 limit、
     * 按送达日窗口），⛔ 不许在客户端把一页列表加起来当合计 —— 那一页带 limit，
     * 截断时求和会**偏小**（后端那句注释里记着"客户端求和少算 62%"）。
     * 逐单「还没结清」的那一栏走订单列表，取不到就如实说取不到（⛔ 不猜 0）。
     */
    val MONTHLY_LEDGER = AiWorkflow(
        id = LEDGER_MONTHLY,
        cn = "本月账本小结",
        whenToUse = "用户说「这个月我付了多少、还欠多少」「本月账本给我小结一下」「哪几单还没结清」这类" +
            "（**只读**：查完直接给结论，不发卡）",
        paramsCn = "customer：只看这一位下游客户 / 收货人（可选；普通货主没有下游那一本账，用不上）",
        steps = listOf(
            AiWorkflowStep("查这一段我该付 / 已付 / 还欠（服务端算好的）", "shipper_ledger.ledger_summary"),
            AiWorkflowStep("查这一段已送达的订单（逐单看哪几张还没结清）", "orders.list_orders"),
        ),
        nextAction = null,
        ask = null,
        roles = SHIPPER_ROLES,
    )

    /**
     * **申请退货**（货主）：核对那一单 / 那几件，再出**退货申请卡**。
     *
     * ⛔ 「申请」与「真的退」是两件事、两个人（见 `AiWriteReturnRequest.kt` 的头注）：
     * 这条链发出去的那张卡**只写一张申请单**，库存、账本、订单状态一个都不动；
     * 派单员收到通知并实际办理之后才生效。所以结论里必须把这句话说出来 ——
     * 用户以为"点了就退了"，会一直等货被拉走。
     */
    val APPLY_RETURN = AiWorkflow(
        id = ORDER_RETURN_REQUEST,
        cn = "申请退货",
        whenToUse = "用户说「那两件苹果要退」「××单我要退货」这类（他自己提出退货申请）",
        paramsCn = "order：订单号（必填，只能是他自己**已送达**的单）；" +
            "product：退哪个商品（可选，留空＝整单申请）；quantity：退几件（只传数字）；note：一句话说明（可选）",
        steps = listOf(
            AiWorkflowStep("查我要退的那张单（核对商品与数量）", "orders.list_orders"),
            AiWorkflowStep("查这张单有没有已经提过的退货申请", "return_requests.list_my_return_requests"),
        ),
        nextAction = AiWrites.RETURN_REQUEST_APPLY,
        ask = "要不要我发一张「申请退货」的确认卡？⚠️ 这只是**申请**：库存和账本现在都不动，" +
            "派单员实际办理之后才生效。",
        roles = SHIPPER_ROLES,
    )

    /**
     * **改收货联系信息**（货主）：找到那一单，**只改用户点名的那几个字段**。
     *
     * ### PATCH 语义：没点名的一个字都不许带
     * 货主白名单里能改的只有 `orders.update_contact` 的**四个联系字段**
     * （收货人 / 下单人的名称与电话）。用户说「把电话改成 138…」，那么卡上只该出现电话那一栏；
     * 顺手把另外三栏按"现在查到的那样"再写一遍，等于**拿查到的值去覆盖**——
     * 查回来的是**上一轮**的值，两次改单之间被人改过的那一栏就被悄悄写回去了。
     *
     * ### ⛔ 送货地址**不在这一扇门里**
     * 用户口径里这条叫「改地址 / 联系人」，而白名单里**没有**改送货地址的写动作：
     * 订单上的地址要派单员才能改（`orders.update_contact` 的 blurb 原话：
     * 「只能补联系信息：配送说明、送货地址、备注那些要派单员才能改」）。
     * 结论里必须把这条边界说清楚 —— 答应了却发不出卡，是本仓最坏的一类体验。
     * （他要改**自己地址库里**那条时走的是 `address.update`，那是另一个动作，
     * 不在这条工作流里，模型自己用 `preview_write` 发那张卡就行。）
     */
    val FIX_CONTACT = AiWorkflow(
        id = ORDER_CONTACT,
        cn = "改收货联系信息",
        whenToUse = "用户说「这张单的收货人 / 电话写错了，改成××」「联系不上他，换成××」这类" +
            "（⚠️ 只改联系信息；**送货地址不在这扇门里**，那是派单员才能改的）",
        paramsCn = "order：订单号（必填）；**只给用户点名的那几个字段**：" +
            "dongjia_name（收货人名称）、dongjia_phone（收货人电话）、boss_name（下单人名称）、" +
            "boss_phone（下单人电话）—— 他没提的一律**别填**（不填＝那一栏不动，见这条的 KDoc）",
        steps = listOf(
            AiWorkflowStep("查那一张单现在的联系信息", "orders.list_orders"),
            AiWorkflowStep("查我名册里的联系人（核对要改成谁）", "shipper.list_contacts"),
        ),
        nextAction = AiWrites.ORDERS_UPDATE_CONTACT,
        ask = "要不要我发一张「补联系信息」的确认卡？卡上只列你要改的那几栏（改前 → 改后），你核对完再点确认。",
        roles = SHIPPER_ROLES,
    )

    // ============================================================ 批发商货主那 1 条（FEAT-0020）

    /**
     * **改我的下游价**（批发商货主 (`is_member`），FEAT-0020）。
     *
     * ### 它动的是「我卖给下游该收多少钱」，⛔ 不是派单员那条批发商专属价
     * 两条价长得像、后果完全不同：
     * - 这条 = `shipper_price.*`（表 `shipper_prices`）：**他自己**给下游定的价，
     *   只有他这本账，后端连 `shipper_id` 入参都没有（写的永远是 `current.id`）；
     * - 派单员那条 = `price_rules.*`（批发商专属价）：公司给他的价，只有派单员能改。
     * 混起来的后果是**钱**：货主点了确认却改了公司给他的价，或者反过来永远改不动自己那一本。
     *
     * ### ⛔ 它一个价都不算
     * 「改后」那个数由**确认卡**那一份实现说了算（`SetMyPriceHandler` 会印出
     * 「原来：X 元 → 现在：Y 元」，还会说"这一档已经有一条价了，这次是改不是新建"）。
     * 所以这条工作流的参数是**一个确定的单价**：用户说「降 5%」时，先问清具体是多少钱 ——
     * 百分比换算在这条链上没有第二份实现，硬算一个数出来就是把两份实现的分歧写进价目表。
     */
    val MY_PRICES = AiWorkflow(
        id = PRICE_MINE,
        cn = "改我的下游价",
        whenToUse = "用户说「我给下游的价改成××」「给张三的苹果价调成 9 块」这类" +
            "（批发商货主改**自己那一本**下游价目表；⛔ 不是派单员那条批发商专属价）",
        paramsCn = "product：商品名，多个用「、」隔开（只能是他能定价的商品）；" +
            "contact：下游联系人（可选，不写＝对所有下游的默认价）；" +
            "price：要改成的新单价（元，必填；⛔ **不认百分比** —— 用户说「降 5%」时先问清具体是多少钱）",
        steps = listOf(
            AiWorkflowStep("查我现有的下游价（有哪几条、各是多少）", "shipper_prices.list_shipper_prices"),
            AiWorkflowStep("查我能定价的商品（上游给我的价 / 我的默认价）", "shipper_prices.list_priceable_products"),
        ),
        nextAction = AiWrites.SHIPPER_PRICE_SET,
        ask = "要不要我发一张调价确认卡？卡上逐条列出改前 → 改后（有几个商品就几张卡，一张一张来），" +
            "你核对完再点确认。⛔ 它只动你自己那一本下游账，公司那边的账一分钱都不变。",
        roles = SHIPPER_ROLES,
        memberOnly = true,
    )

    /** 登记表。加一条工作流 = 在这里加一项 **+ 在 [AiWorkflowRunner] 里接上同名的执行分支**。 */
    val ALL: List<AiWorkflow> = listOf(
        RECONCILE,
        PRICE_ADJUST,
        PLACE_ORDER,
        TRACK_ORDER,
        MONTHLY_LEDGER,
        APPLY_RETURN,
        FIX_CONTACT,
        MY_PRICES,
    )

    /** 工具 schema 里的 `enum`（从登记表算，加一条就自动出现，不会漏）。 */
    val IDS: List<String> = ALL.map { it.id }

    fun byId(id: String): AiWorkflow? = ALL.firstOrNull { it.id == id }

    /**
     * 这个角色（＋ 他是不是批发商货主）能跑的工作流。
     *
     * **认不出角色 = 一条都不给**（与工具白名单同一条 fail-closed）；
     * [AiWorkflow.memberOnly] 的那些只给**批发商货主**（派单员与普通货主都拿不到 ——
     * 派单员拿不到是因为那本账后端只认货主角色）。
     */
    fun forActor(actor: AiActor?): List<AiWorkflow> {
        val role = actor?.role ?: return emptyList()
        val member = actor.memberShipper
        return ALL.filter { role in it.roles && (!it.memberOnly || member) }
    }

    /** 这个角色能不能跑这一条（执行前的门与工具 enum 同一份判据）。 */
    fun allows(actor: AiActor?, id: String): Boolean = forActor(actor).any { it.id == id }

    /**
     * `run_workflow` 的工具说明 —— **从登记表拼**。
     *
     * 为什么不手写：手写的清单在加工作流时一定会漏（设置页那句"可申请：…"就踩过这个坑，
     * 见 `AiTools.previewWriteHint`）。这里少写一条的症状是「模型根本不知道有这条工作流」，
     * 静默失效，没有报错。
     *
     * ⚠️ 只读的那几条要**分开写**：不写清楚，模型会照着"跑完问你一句要不要发卡"去问，
     * 而那条链**没有卡**（见文件头那段）。
     */
    val TOOL_DESCRIPTION: String = buildString {
        appendLine("跑一条登记在案的多步工作流：一次调用把整件事查完 —— 比你自己一步一步查更快、也不会漏步骤。")
        appendLine("现在能跑这些：")
        ALL.forEach { w ->
            appendLine("- " + w.id + "（" + w.cn + "）：" + w.whenToUse + "。")
            appendLine("  · 参数：" + w.paramsCn + "。")
            appendLine("  · 它会做这几步：" + w.steps.joinToString("；") { it.title } + "。")
            if (w.readOnly) {
                appendLine("  · **只读**：跑完给你结论（" + w.cn + "），⛔ 没有确认卡、也没有要问用户的那一句 —— 它一个字都不写。")
            } else {
                appendLine("  · 跑完给你结论（" + w.cn + "），并告诉你要不要发确认卡 —— **它自己一步都不写**。")
            }
        }
        appendLine("⛔ 时间范围：用户没说就用**本月 1 号到今天**，并在回答里写明你用的是哪一段。")
        appendLine("⛔ 跑完先给结论；结果里有 `next` 的（要发卡的那些）再问 `next.ask` 那一句 —— 用户没点头**不许**调 preview_write。")
        appendLine("⛔ 标了**只读**的那几条：跑完只有结论，⛔ **不要**问「要不要发一张确认卡」——它们没有卡可发。")
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
        appendLine("   - 它给的 `ledger_detail` / `returns` 是**账本那一侧的逐行明细**（各来源几笔多少钱、退货红冲逐行）：")
        appendLine("     笔数金额都是**它算好的**，照它说 —— ⛔ 不许自己按单去拼明细、不许自己加总。")
        appendLine("     有人拿库里的原始数据核对笔数时，先把 `scope_note` 那条口径讲清楚（进了回收站的单两边都不计）。")
        appendLine("   - `next` 里是「该发哪张卡 + 参数 + 要问用户的那一句」：**先把结论给用户，再问那一句**；")
        appendLine("     用户没点头之前⛔ **不许**调 preview_write。工作流自己一步都不会写。")
        appendLine("     给了 `nexts`（多于一张卡，比如一次改几个商品的下游价）时：**一张一张来**，每张都先问那一句。")
        appendLine("   - 标了 `read_only=true` 的那几条（查单到哪了 / 本月账本小结）：跑完**只有结论**，")
        appendLine("     ⛔ 没有 `next`、也没有要问的那一句 —— 别去问「要不要发卡」，它们一个字都不会写。")
        appendLine("   - 它标了 `incomplete=true` 时（一次取不完）：⛔ 不许把那些数字当完整的账报给用户，照它说的让用户缩小范围重跑。")
        appendLine("   - 这两条都不适用时，才退回你自己用 read_data 一步一步查。")
    }
}
