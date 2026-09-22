package com.tapmoay.sorders.ai

/**
 * 供应商 / 厂商档案 + 应付款的写动作（2026-09-22 用户要求，账本管理「支出」那一块）。
 *
 * ## 用户原话
 * > 「支出主要是**给某个供应商或者说是厂商支付尾款**……**购买一个装备或者说是设备**……
 * > 比如说类似**邮费**啊」；拍板口径：**跟客户一个量级的档案**（**可挂账、可查还欠多少、可分次付款**）。
 *
 * ## 十一个动作，三条线
 * | 线 | 动作 | 怎么实现 |
 * |---|---|---|
 * | 档案 | `create` / `update` / `delete` | 声明式（`CrudSpec`） |
 * | 应付单 | `create` / `update` / `delete` | 声明式 |
 * | 付款 | `pay` | **手写**（[SupplierPaymentWriteHandler]）：卡片要写清"还差多少 → 付完还差多少" |
 * | 付款 | `cancel` | 声明式（撤销＝软删那一行流水） |
 * | 三条线各自的 `restore` | —— | [restoreAction]（`undoOnly`，只有撤回入口拿着编号调） |
 *
 * ## ⛔ 为什么 `pay` 必须手写
 * 它是**唯一一个真正把钱写出去**的动作。声明式那层的卡片只写得出"字段：值"，
 * 而用户核对一笔付款时真正要看的是**这张单还差多少、付完还差多少** ——
 * 那两个数要先把这张应付单读回来才算得出来（还要顺带拦住"付得比还差多"）。
 * 卡片上不写这两个数，用户就只能凭记忆判断"这 800 是不是付多了"。
 *
 * ## ⛔ 付款**不是新表**
 * 它就是 `cash_flows` 的一行（`biz_type=PAYMENT_SUPPLIER`），所以账本「收支」页自动有它；
 * 撤销＝软删那一行流水（可恢复）。在这一层再造一个"付款单"就是把同一笔钱记两遍。
 */
internal object AiWriteSuppliers {

    // ⚠️ 动作 id **只在 `AiWrites` 里定义一处**（撤回表、红线、设置页都从那儿读）。
    // ⛔ 下面 `id =` 必须写全 `AiWrites.XXX`：`_tools/ai/_show_undo_status.py` 是按源码里的
    //    `id = AiWrites.X` 解析"到底注册了哪些动作"的 —— 写本地别名它会报「挂了不存在的动作」。
    const val SUPPLIER_CREATE = AiWrites.SUPPLIER_CREATE
    const val SUPPLIER_UPDATE = AiWrites.SUPPLIER_UPDATE
    const val PAYABLE_CREATE = AiWrites.SUPPLIER_PAYABLE_CREATE
    const val PAYABLE_UPDATE = AiWrites.SUPPLIER_PAYABLE_UPDATE
    const val PAY_CREATE = AiWrites.SUPPLIER_PAYMENT_PAY

    /** 应付款的用途分类**建议值**（后端 `schemas/supplier.py::SUPPLIER_PAYABLE_CATEGORIES` 同一份）。 */
    val CATEGORIES: List<String> = listOf("货款", "设备采购", "运费", "尾款", "其他")

    // 声明式三个动作的参数表：⚠️ 两个局部量得就叫 `targets` / `fields`
    // （`_check_ai_write_params.py` 按 `params = crudParams(targets, fields)` 这一行**字面**数）。
    // ⚠️ 至少有一对局部量得**就叫** `targets` / `fields`：判据 `_check_ai_write_params.py` 是按
    //    `params = crudParams(targets, fields)` 这一行**字面**数它出现几次的（每个处理器文件恰好
    //    一次）。手拼一份 `AiWriteParam(...)` 会让"给模型看的参数说明"与规格走散 —— 而那种走散
    //    不报错，只是模型按一处写、另一处不认。所以撤销付款那一对用规范名，另两对用更贴切的名字。
    private val targets = listOf(targetSupplierPayment(required = true))
    private val fields: List<AiFieldSpec> = emptyList()

    private val supplierTargets = listOf(targetSupplier(required = true))
    private val supplierNoFields: List<AiFieldSpec> = emptyList()

    private val payableTargets = listOf(targetSupplierPayable(required = true))
    private val payableNoFields: List<AiFieldSpec> = emptyList()

    /** 档案的普通字段（新建与改名共用一套：`name` 在新建时必填、在改时可选）。 */
    private fun supplierFields(nameRequired: Boolean): List<AiFieldSpec> = listOf(
        AiFieldSpec(
            "name", "供应商名称", AiFieldType.TEXT,
            "对方的名字（如「永盛食品有限公司」）。名字在系统里是唯一的：同名会被拒绝，直接用那一个",
            required = nameRequired, maxChars = 64,
        ),
        textField("contact_name", "联系人", "对方的联系人姓名，可选", maxChars = 32),
        textField("phone", "电话", "可选。只能是 7~12 位数字（座机写成 07521234567，不带横杠）", maxChars = 32),
        textField("address", "地址", "可选，对方的地址", maxChars = 128),
        textField("remark", "备注", "可选，一句话", maxChars = 256),
    )

    // 应付单的普通字段（新建全给；改的时候金额也允许改 —— 后端会拦住"改成比已付还小"）
    private fun payableFields(titleRequired: Boolean, amountRequired: Boolean): List<AiFieldSpec> = listOf(
        AiFieldSpec(
            "title", "这笔账是什么", AiFieldType.TEXT,
            "对方认得出的说法，如「9 月货款」「采购叉车」——对账全靠它",
            required = titleRequired, maxChars = 64,
        ),
        AiFieldSpec(
            "amount", "应付金额（元）", AiFieldType.MONEY,
            "这笔欠他的总额（不是这次付的）。只传数字，不要带「元」字",
            required = amountRequired,
        ),
        AiFieldSpec(
            "category", "用途分类", AiFieldType.ENUM,
            "填不动就写「货款」。只能是：${CATEGORIES.joinToString("、")}",
            enumValues = CATEGORIES,
        ),
        AiFieldSpec("doc_date", "单据日期", AiFieldType.DATE, "这笔欠款从哪天算；不填默认今天"),
        textField("remark", "备注", "可选，一句话", maxChars = 256),
    )

    val ACTIONS: List<AiWriteAction> = listOf(
        // ---------------- 档案 ----------------
        AiWriteAction(
            id = AiWrites.SUPPLIER_CREATE,
            title = "新增供应商/厂商",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_SUPPLIER,
            blurb = "建一个供应商（或厂商）档案 —— 以后给它的付款、欠它的钱都挂在这个档案下面。" +
                "⛔ 建档这一步不动钱：要记「欠他多少」请用「挂一笔应付款」。",
            params = crudParams(supplierTargets.drop(1), supplierFields(nameRequired = true)),
            crud = CrudSpec(
                targets = emptyList(),
                fields = supplierFields(nameRequired = true),
                headline = { c -> "新增供应商：${c.str("name").orEmpty()}" },
                details = { c ->
                    listOf(
                        "建档不动钱：这个动作只是把对方记进名册",
                        "建完之后要给它的付款挂账：用动作「挂一笔应付款」＋「给供应商付款」",
                    ) + listOfNotNull(
                        c.line("contact_name", "联系人"),
                        c.line("phone", "电话"),
                        c.line("address", "地址"),
                        c.line("remark", "备注"),
                    )
                },
                commit = { ds, p -> ds.createSupplier(p) },
            ),
        ),
        AiWriteAction(
            id = AiWrites.SUPPLIER_UPDATE,
            title = "改供应商/厂商资料",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_SUPPLIER,
            blurb = "改一个已有供应商的资料（只改你说了的那几项，没提到的原样不动）。" +
                "⚠️ 名称在系统里唯一：改成别人已经用着的名字会被拒绝。",
            params = crudParams(supplierTargets, supplierFields(nameRequired = false)),
            crud = CrudSpec(
                targets = supplierTargets,
                fields = supplierFields(nameRequired = false),
                headline = { c -> "改供应商：${c.ref("supplier")?.label ?: "（没对上）"}" },
                details = { c ->
                    listOf("改的是：${c.ref("supplier")?.label ?: "（没对上）"}（只改下面列出的那几项）") +
                        listOfNotNull(
                            c.line("name", "改成"),
                            c.line("contact_name", "联系人"),
                            c.line("phone", "电话"),
                            c.line("address", "地址"),
                            c.line("remark", "备注"),
                        )
                },
                commit = { ds, p -> ds.updateSupplier(p.reqLong("supplier_id"), p) },
            ),
        ),
        AiWriteAction(
            id = AiWrites.SUPPLIER_DELETE,
            title = "删除供应商/厂商",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_SUPPLIER,
            blurb = "把一个供应商删掉（伪装删除：行还在库里，按钮上有「撤回」能放回来）。" +
                "⛔ 名下还有应付单时后端会拒绝 —— 欠款不能挂在一个看不见的供应商上。",
            params = crudParams(supplierTargets, supplierNoFields),
            crud = CrudSpec(
                targets = supplierTargets,
                fields = supplierNoFields,
                headline = { c -> "删除供应商：${c.ref("supplier")?.label ?: "（没对上）"}" },
                details = {
                    listOf(
                        "删掉之后名册里看不到它（后台是伪装删除，行还在）",
                        "这次删除有「撤回」：点一下原样放回来（名称、联系人、电话、地址都是删之前那份）",
                        "⚠️ 名下还有应付单的话会被拒绝（先把那些单处理掉）",
                    )
                },
                commit = { ds, p -> ds.deleteSupplier(p.reqLong("supplier_id")) },
            ),
        ),
        restoreAction("供应商", AiWrites.SUPPLIER_RESTORE, AiWrites.G_SUPPLIER) { ds, id -> ds.restoreSupplier(id) },

        // ---------------- 应付单 ----------------
        AiWriteAction(
            id = AiWrites.SUPPLIER_PAYABLE_CREATE,
            title = "挂一笔应付款",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_SUPPLIER,
            blurb = "记下「我们还欠这个供应商一笔钱」（货款 / 采购设备 / 运费 / 尾款…）。" +
                "⛔ 这一步不动钱：欠款只是账面上的数，真正付出去要用「给供应商付款」。",
            params = crudParams(payableTargets, payableFields(titleRequired = true, amountRequired = true)),
            crud = CrudSpec(
                targets = payableTargets,
                fields = payableFields(titleRequired = true, amountRequired = true),
                headline = { c ->
                    "挂应付款：${c.ref("supplier")?.label ?: "（没对上）"} · " +
                        "${AiWriteArgs.moneyText(c.str("amount"))} 元"
                },
                details = { c ->
                    listOf(
                        "供应商：${c.ref("supplier")?.label ?: "（没对上）"}",
                        "事由：${c.str("title").orEmpty()}",
                        "应付总额：${AiWriteArgs.moneyText(c.str("amount"))} 元",
                        "用途分类：${c.str("category") ?: "货款"}",
                        "单据日期：${c.str("doc_date") ?: "（今天）"}",
                        c.line("remark", "备注"),
                        "⛔ 挂账不动钱：这一步只是把「欠他多少」记上，钱还在我们这边",
                        "要真的付出去：用动作「给供应商付款」（一张单可以分很多次付）",
                    ).filterNotNull()
                },
                commit = { ds, p -> ds.createSupplierPayable(p) },
            ),
        ),
        AiWriteAction(
            id = AiWrites.SUPPLIER_PAYABLE_UPDATE,
            title = "改应付款",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_SUPPLIER,
            blurb = "改一张应付单（只改你说了的那几项）。⚠️ 金额不许改到比已经付过的还小" +
                "（那等于把付出去的钱说成没付）；要改小请先撤销多付的那一笔。",
            params = crudParams(payableTargets, payableFields(titleRequired = false, amountRequired = false)),
            crud = CrudSpec(
                targets = payableTargets,
                fields = payableFields(titleRequired = false, amountRequired = false),
                headline = { c -> "改应付款：${c.ref("payable")?.label ?: "（没对上）"}" },
                details = { c ->
                    listOf("改的是：${c.ref("payable")?.label ?: "（没对上）"}（只改下面列出的那几项）") +
                        listOfNotNull(
                            c.line("title", "事由"),
                            c.line("amount", "应付总额"),
                            c.line("category", "用途分类"),
                            c.line("doc_date", "单据日期"),
                            c.line("remark", "备注"),
                        ) + listOf("⚠️ 金额不许改到比已付的小；改错的部分要靠撤销付款来退")
                },
                commit = { ds, p -> ds.updateSupplierPayable(p.reqLong("payable_id"), p) },
            ),
        ),
        AiWriteAction(
            id = AiWrites.SUPPLIER_PAYABLE_DELETE,
            title = "删除应付款",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_SUPPLIER,
            blurb = "把一张应付单删掉（伪装删除，可「撤回」放回来）。" +
                "⛔ 还有没撤销的付款时后端会拒绝（那些钱会对不上单据）。",
            params = crudParams(payableTargets, payableNoFields),
            crud = CrudSpec(
                targets = payableTargets,
                fields = payableNoFields,
                headline = { c -> "删除应付款：${c.ref("payable")?.label ?: "（没对上）"}" },
                details = {
                    listOf(
                        "删掉之后这一笔欠款不再算进「还欠他多少」（后台是伪装删除，行还在）",
                        "这次删除有「撤回」：点一下原样放回来（事由、金额、日期都是删之前那份）",
                        "⚠️ 还有没撤销的付款时会被拒绝：先把那些付款撤销掉",
                    )
                },
                commit = { ds, p -> ds.deleteSupplierPayable(p.reqLong("payable_id")) },
            ),
        ),
        restoreAction("应付款", AiWrites.SUPPLIER_PAYABLE_RESTORE, AiWrites.G_SUPPLIER) { ds, id ->
            ds.restoreSupplierPayable(id)
        },

        // ---------------- 付款 ----------------
        AiWriteAction(
            id = AiWrites.SUPPLIER_PAYMENT_PAY,
            title = "给供应商付款",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_SUPPLIER,
            blurb = "给某张应付单付一笔钱（钱真的出去了：会写一行资金流水，账本「收支」里立刻看得到）。" +
                "一张单可以分很多次付；⚠️ 金额不许超过这张单还差的数。",
            params = listOf(
                AiWriteParam("supplier", "供应商/厂商", required = true, hint = "付给谁（写对方的名字）"),
                AiWriteParam("payable", "这笔账是什么", required = true, hint = "付的是哪一笔（写应付单上那个事由，如「9 月货款」）"),
                AiWriteParam(
                    "amount", "付款金额（元）", required = true, kind = AiWriteParamKind.NUMBER,
                    hint = "这次付多少。只传数字，不要带「元」字；不许超过这张单还差的数",
                ),
                AiWriteParam("pay_date", "付款日期", kind = AiWriteParamKind.DATE, hint = "YYYY-MM-DD；不填默认今天"),
                AiWriteParam(
                    "channel", "付款方式", kind = AiWriteParamKind.ENUM,
                    enumValues = listOf("cash", "transfer", "wechat", "bank"),
                    hint = "不填默认现金（cash）；转账 transfer / 微信 wechat / 银行 bank",
                ),
                AiWriteParam("remark", "备注", hint = "可选，一句话（如「顺丰到付」）"),
            ),
        ),
        AiWriteAction(
            id = AiWrites.SUPPLIER_PAYMENT_CANCEL,
            title = "撤销一笔付款",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_SUPPLIER,
            blurb = "把付错的一笔钱撤回来（伪装删除：那一行流水还在库里，只是不再算数；可「撤回」放回来）。" +
                "⛔ 撤销之后「还欠他多少」会立刻变回去，账本「收支」里也不再算这一笔。",
            params = crudParams(targets, fields),
            crud = CrudSpec(
                targets = targets,
                fields = fields,
                headline = { c -> "撤销付款：${c.ref("payment")?.label ?: "（没对上）"}" },
                details = {
                    listOf(
                        "撤销之后这一笔不再算「已付」（还欠他的钱会变回去）",
                        "账本「收支」里也不再算这一笔（两边一起变，不会一个说付了一个说没付）",
                        "这次撤销有「撤回」：点一下原样放回来",
                    )
                },
                commit = { ds, p -> ds.cancelSupplierPayment(p.reqLong("payment_id")) },
            ),
        ),
        restoreAction("付款记录", AiWrites.SUPPLIER_PAYMENT_RESTORE, AiWrites.G_SUPPLIER) { ds, id ->
            ds.restoreSupplierPayment(id)
        },
    )
}
