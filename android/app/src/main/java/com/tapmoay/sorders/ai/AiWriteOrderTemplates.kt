package com.tapmoay.sorders.ai

/**
 * 预订单（订单模板）的写动作（2026-09-22 用户要求）。
 *
 * ## 用户原话
 * > 「支持 AI 去**预选**……可以让 AI 去**直接创建对应的商品和对应的数量**，方便直接下单；
 * > **甚至可以让 AI 直接去创建预定单** —— 就是**预设好的订单**，这个参数没有变，直接下单就可以了。」
 *
 * ## 四个动作分别是什么
 * · `create` / `update` —— **手写处理器**（[OrderTemplateWriteHandler]）：因为它们要收 `lines`
 *   （一组"商品 + 数量"），而声明式那层的字段类型里**没有数组**（`AiFieldType` 只有文本/金额/
 *   整数/日期/是-否/枚举）。这与 `orders.create` 是同一个处境、同一个解法（那边也是手写 + `lines`）。
 * · `delete` —— 声明式（一个目标 + 空字段表），与全项目其余软删资源同形。
 * · `restore` —— 走 [restoreAction]（`undoOnly`，模型看不见它，只有撤回入口拿着编号调它）。
 *
 * ## ⛔ 它**不生成订单**
 * 「一键下单」是界面上的动作（读这张预设单 → 走已有的 `POST /orders`）。
 * AI 要下单就用**已有的** `orders.create` 动作 —— 那一头的状态核对、库存、账本口径都是现成的。
 * 在这里再开一个"从预设单下单"的动作，等于把下单这条路抄第二遍。
 */
internal object AiWriteOrderTemplates {

    // ⚠️ 动作 id **只在 `AiWrites` 里定义一处**（撤回表、红线、设置页都从那儿读）：
    //    这两个短名字只给 [OrderTemplateWriteHandler] 比对用。
    // ⛔ 下面四个动作的 `id =` **必须写全 `AiWrites.XXX`**：`_tools/ai/_show_undo_status.py`
    //    是按源码里的 `id = AiWrites.X` 解析"到底注册了哪些动作"的 —— 写成 `id = CREATE`
    //    （本文件的别名）它认不出来，会报「资源挂了不存在的动作」（实测踩过一次）。
    const val CREATE = AiWrites.ORDER_TEMPLATE_CREATE
    const val UPDATE = AiWrites.ORDER_TEMPLATE_UPDATE

    /**
     * 一张预设单最多几行货 —— **与后端 `schemas/order_template.py::MAX_LINES` 逐值一致**。
     * 两边不一致的后果：模型填 30 行，卡片上写着"30 行都在"，后端却砍掉 5 行。
     */
    const val MAX_LINES = 30

    /**
     * 「删预设单」的参数表 —— **必须走 `crudParams(targets, fields)`**（全项目唯一一份推导）。
     *
     * ⚠️ 两个局部量的名字得就叫 `targets` / `fields`：判据 `_check_ai_write_params.py` 是按
     *    `params = crudParams(targets, fields)` 这一行**字面**数它出现几次的（声明式工厂各一次）。
     *    手拼一份 `AiWriteParam(...)` 会让"给模型看的参数说明"与规格走散。
     */
    private val targets = listOf(targetOrderTemplate(required = true))
    private val fields: List<AiFieldSpec> = emptyList()

    val ACTIONS: List<AiWriteAction> = listOf(
        AiWriteAction(
            id = AiWrites.ORDER_TEMPLATE_CREATE,
            title = "建一张预设单",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ORDER,
            blurb = "把「以后还要照这样再下一遍」的那一单**存成预设单**（货主/地址/收货人/运费/商品与数量）。" +
                "⛔ 它**不生成订单**、不占订单号、不动库存与账本 —— 真下单是另一件事（动作「创建订单」）。",
            params = listOf(
                AiWriteParam("name", "预设单名", required = true, hint = "必填。一个用户认得出的名字，如「永盛食品每周单」"),
                AiWriteParam(
                    "lines", "商品明细", required = true, kind = AiWriteParamKind.TEXT,
                    hint = "必填，**数组**：[{\"product\":\"红富士苹果\",\"quantity\":6}, …]（最多 $MAX_LINES 行）。" +
                        "product 传商品名（系统按名字找商品），quantity 只传数字。" +
                        "⛔ **不要传单价**：预设单只记「哪几样、各多少」，钱在下单那一刻按商品价算",
                ),
                AiWriteParam("shipper", "货主名", hint = "可选。不写＝下单时再选（有些预设单是「按商品备货」）"),
                AiWriteParam("address", "送货地址", hint = "可选，送货到的地址"),
                AiWriteParam("receiver_name", "收货人", hint = "可选，到现场接货的人"),
                AiWriteParam("receiver_phone", "收货人电话", hint = "可选"),
                AiWriteParam(
                    "freight_fee", "预设运费", kind = AiWriteParamKind.NUMBER,
                    hint = "可选，单位元。**不填＝不预设**（下单时按运费规则算）；填 0 才是「免运费」——两个意思不一样",
                ),
                AiWriteParam("remark", "备注", hint = "可选，一句话"),
            ),
        ),
        AiWriteAction(
            id = AiWrites.ORDER_TEMPLATE_UPDATE,
            title = "改预设单",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ORDER,
            blurb = "改一张已有预设单的某几项（只改你说了的那几项，没提到的原样不动）。" +
                "⚠️ **换货主可以，清空货主不行**（AI 这条路上发不出「空值」）—— 要清空请让用户在预设单页面上改。",
            params = listOf(
                AiWriteParam("template", "预设单名", required = true, hint = "必填。要改哪一张（写预设单的名字）"),
                AiWriteParam("name", "改成什么名", hint = "可选。要给这张预设单换个名字时才填"),
                AiWriteParam(
                    "lines", "商品明细", kind = AiWriteParamKind.TEXT,
                    hint = "可选。**填了就整份换掉**（不是追加）：[{\"product\":\"…\",\"quantity\":3}, …]" +
                        "（最多 $MAX_LINES 行）。⛔ 不要传单价",
                ),
                AiWriteParam("shipper", "货主名", hint = "可选。换货主；⛔ 清空货主请让用户在页面上改"),
                AiWriteParam("address", "送货地址", hint = "可选"),
                AiWriteParam("receiver_name", "收货人", hint = "可选"),
                AiWriteParam("receiver_phone", "收货人电话", hint = "可选"),
                AiWriteParam(
                    "freight_fee", "预设运费", kind = AiWriteParamKind.NUMBER,
                    hint = "可选，单位元。填 0 = 免运费；⛔ **改回「不预设」请让用户在页面上改**",
                ),
                AiWriteParam("remark", "备注", hint = "可选"),
            ),
        ),
        AiWriteAction(
            id = AiWrites.ORDER_TEMPLATE_DELETE,
            title = "删预设单",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ORDER,
            blurb = "把一张预设单删掉（**伪装删除**：行还在库里，按钮上有「撤回」能放回来）。",
            params = crudParams(targets, fields),
            crud = CrudSpec(
                targets = targets,
                fields = fields,
                headline = { c -> "删预设单：${c.ref("template")?.label ?: "（没对上）"}" },
                details = {
                    listOf(
                        "删掉之后列表里看不到它（后台是伪装删除，行还在）",
                        "这次删除有「撤回」：点一下原样放回来（名字、货主、地址、商品行都是删之前那份）",
                    )
                },
                commit = { ds, p -> ds.deleteOrderTemplate(p.reqLong("template_id")) },
            ),
        ),
        restoreAction("预设单", AiWrites.ORDER_TEMPLATE_RESTORE, AiWrites.G_ORDER) { ds, id -> ds.restoreOrderTemplate(id) },
    )
}
