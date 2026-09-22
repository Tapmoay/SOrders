package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * 「给供应商付款」——**唯一一个真正把钱写出去**的动作，所以是手写处理器。
 *
 * ## 为什么不能走声明式（`CrudSpec`）
 * 声明式那层的卡片只写得出"字段：值"。而用户核对一笔付款时真正要看的是：
 *
 *     这张单应付 1,200.50 / 已经付了 500.00 / **还差 700.00** → 这次付 700.00 → **付清**
 *
 * 这三个数要把这张应付单先读回来才算得出来，声明式的卡片拿不到它们。
 * 卡片上不写，用户就只能凭记忆判断"这 700 是不是付多了" —— 而**钱付出去撤不回来**
 * （撤销要走撤回，是补救不是预防）。
 *
 * ## 两条"宁可拒绝也不猜"（都在 [prepare] 里，**发卡之前**）
 * 1. **付清了的不许再付**：让模型去"再付一点"是不可能的，直接说清"这张单已经付清了"。
 * 2. **不许超过还差**：超了就是预付款，而预付款在这套账里没有位置（欠款会变成负数，
 *    界面上没人读得对）。后端也会拒绝，但**在卡片之前拦住**才不会让用户点了确认才吃一个错。
 *
 * ## 钱的数字**全部来自后端**
 * `unpaid` / `amount` 都是后端算好的字符串（口径只有一处：`services/supplier_service.py`）。
 * ⛔ 这里不做"应付 − 已付"的减法 —— 那会变成第二个口径。
 * 卡片上那句"付完还差 X"是**减法**，但它只是展示（且与后端算的 `unpaid` 同源），
 * 真正写进去的只有这次付的金额。
 */
internal class SupplierPaymentWriteHandler(
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    /**
     * ⚠️ 这一行的形状**一个字都不能改**：类体里一行 `override` + `val actionId = AiWrites.XXX`，
     *    不写类型标注、不做成构造参数。
     *    · 判据 `_check_role_parity.py` 按这个字面形状把"处理器"与"动作"关联起来 ——
     *      写成构造参数时它认不出，这个动作会被报成"手机上能做的端点没有 AI 动作"；
     *    · 判据 `_check_ai_guardrails.py` 按那一串字面量**数动作个数**，所以连注释里都别写全
     *      （写了会被一起数进去，三份数就对不上）—— 实测踩过。
     */
    override val actionId = AiWrites.SUPPLIER_PAYMENT_PAY

    /**
     * 付款方式：后端 `pattern="^(cash|transfer|wechat|bank)$"`。
     * 键是**用户/模型可能说出来的说法**（中英都收），值是后端要的 code。
     * 为什么中英都收：用户说「现金付的」，模型很自然地会传「现金」两个字 ——
     * 只认英文等于逼它猜，而它猜错时用户看到的是一句看不懂的报错。
     */
    private val channelCodes = linkedMapOf(
        "cash" to "cash", "现金" to "cash", "现钱" to "cash",
        "transfer" to "transfer", "转账" to "transfer", "银行转账" to "transfer",
        "wechat" to "wechat", "微信" to "wechat",
        "bank" to "bank", "银行" to "bank",
    )

    /** code → 卡片上写的中文（卡片给用户看，⛔ 不出现 `transfer` 这种字）。 */
    private fun channelCn(code: String): String = when (code) {
        "cash" -> "现金"
        "transfer" -> "转账"
        "wechat" -> "微信"
        else -> "银行"
    }

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        // ---- 1. 付给谁 ----
        val supplierRaw = AiWriteArgs.required(params, "supplier", "付给哪个供应商/厂商？把对方的名字告诉我。")
        val supplier = AiWriteArgs.strict(supplierRaw, ds.suppliers(), "供应商")
            ?: throw AiWriteArgException(
                "系统里没有叫「$supplierRaw」的供应商。请先让用户确认名字" +
                    "（可以在账本管理 → 供应商/厂商页看到全部档案）；还没有档案就用动作「新增供应商」。",
            )

        // ---- 2. 付的是哪一笔（**在这一个供应商名下**找，不跨供应商）----
        val payableRaw = AiWriteArgs.required(params, "payable", "付的是哪一笔？把应付单上那个事由告诉我。")
        val payables = ds.supplierPayables(supplier.id)
        val payName = AiWriteArgs.strict(
            query = payableRaw,
            pool = payables.map { AiName(it.id, it.title, note = "应付 ${it.amount}，还差 ${it.unpaid}") },
            kind = "应付款",
        ) ?: throw AiWriteArgException(
            "「${supplier.label}」名下没有叫「$payableRaw」的应付款。请让用户确认事由" +
                "（在供应商详情页能看到他名下全部应付单）；还没有这张单就用动作「挂一笔应付款」。",
        )
        val payable = payables.first { it.id == payName.id }

        // ---- 3. 付多少 ----
        val amountRaw = AiWriteArgs.required(params, "amount", "这次付多少钱？")
        // 两个形状都要：`amountValue` 用来比大小/算差，`amount` 是进 payload 的两位小数
        // （⛔ 不要拿字符串去比大小 —— 那是"10 > 9"那种谁都不会发现的错）。
        val amountValue = AiWriteArgs.parseMoney(amountRaw, "付款金额", mustPositive = true)
        val amount = AiWriteArgs.money(amountValue)
        val unpaid = payable.unpaid.toBigDecimalOrNull()
            ?: throw AiWriteArgException(
                "这张应付单的「还差多少」读不出来（后端返回的是「${payable.unpaid}」），请刷新后重试。",
            )
        if (unpaid.signum() <= 0) {
            throw AiWriteArgException(
                "「${payable.title}」已经付清了（应付 ${payable.amount}，已付 ${payable.paid}），不用再付。" +
                    "如果确实还要给对方钱，请先挂一张新的应付款。",
            )
        }
        if (amountValue > unpaid) {
            throw AiWriteArgException(
                "付款金额 $amount 超过了这张单还差的 $unpaid" +
                    "（应付 ${payable.amount}，已付 ${payable.paid}）。" +
                    "要付这么多就另建一张应付单（预付款在这套账里没有位置）。",
            )
        }

        // ---- 4. 日期 / 方式 / 备注 ----
        val payDate = AiWriteArgs.parseDate(AiWriteArgs.str(params, "pay_date"), "付款日期")?.toString()
            ?: java.time.LocalDate.now().toString()
        val channelRaw = (AiWriteArgs.str(params, "channel") ?: "cash").trim()
        val channel = channelCodes[channelRaw.lowercase()]
            ?: throw AiWriteArgException(
                "付款方式「$channelRaw」不认识。只能是：现金 / 转账 / 微信 / 银行。",
            )
        val remark = AiWriteArgs.text(AiWriteArgs.str(params, "remark"), "备注")

        val payload = buildJsonObject {
            put("payable_id", payable.id)
            put("amount", amount)
            put("pay_date", payDate)
            put("channel", channel)
            if (remark.isNotBlank()) put("remark", remark)
        }
        val after = (unpaid - amountValue).setScale(2, java.math.RoundingMode.HALF_UP).toPlainString()

        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = "付款：给「${supplier.label}」付 ${AiWriteArgs.moneyText(amount)} 元（${payable.title}）",
                detailLines = listOf(
                    "付给：${supplier.label}",
                    "这笔账：${payable.title}",
                    "应付总额：${AiWriteArgs.moneyText(payable.amount)} 元",
                    "已经付过：${AiWriteArgs.moneyText(payable.paid)} 元（含这次之前 ${payable.paymentCount} 笔）",
                    "现在还差：${AiWriteArgs.moneyText(payable.unpaid)} 元",
                    "这次付：${AiWriteArgs.moneyText(amount)} 元",
                    "付完之后：还差 ${AiWriteArgs.moneyText(after)} 元" + if (after == "0.00") "（这一笔付清了）" else "",
                    "付款日期：$payDate",
                    "付款方式：${channelCn(channel)}",
                    "⛔ 钱真的出去了：会写一行资金流水，账本「收支」里立刻看得到",
                    "付错了有「撤回」：撤销之后欠款变回去、收支里也不再算这一笔",
                ) + listOfNotNull(remark.takeIf { it.isNotBlank() }?.let { "备注：$it" }),
                payload = payload,
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        ds.paySupplierPayable(payload)
    }
}
