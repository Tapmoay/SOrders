package com.tapmoay.sorders.ai

import java.math.BigDecimal

/**
 * **货主自己那一本账**的动作清单（批发商给下游货主核销，2026-09-20 用户要求）。
 *
 * 用户原话：「他也可以撤掉核销。**同时，他的 AI 也要具备这些功能**：具备帮他核销、
 * 帮他管理账本、还有帮他撤回核销……不过我们的操作都是走软删，这个你要注意一下」。
 *
 * ## ⛔ 这三个动作碰的是他自己那一本，不是公司账
 * | 动作 | 后端 | 写什么 |
 * | --- | --- | --- |
 * | [AiWrites.MY_LEDGER_SETTLE] | `POST /shipper-ledger/settlements` | 只写 `shipper_settlements` |
 * | [AiWrites.MY_LEDGER_REVOKE] | `DELETE /shipper-ledger/settlements/{id}` | 只把那一条**软删** |
 * | [AiWrites.MY_LEDGER_RESTORE] | `POST …/{id}/restore` | 把那一条放回来 |
 *
 * 它们**不写** `orders.paid` / `cash_flows` / `ledgers`——那三处是派单员那一本账
 * （见 `backend/app/models/shipper_settlement.py` 开头那张表）。所以卡片上必须把这句话
 * 写出来：用户最怕的是"我在这儿点一下，公司的账跟着变了"。
 *
 * ## 只有**批发商货主**有这本账（`memberOnly = true`）
 * 三个动作都标了 [AiWriteAction.memberOnly]：**普通货主的 AI 清单里根本没有它们**
 * （用户 2026-09-20：「AI 也会分成 2 个：一个是普通货主、一个是批发商货主的 AI……
 * 普通货主**手机做不到的事情，AI 也做不到**」——普通货主那本账上没有「核销」这一段）。
 * 处理器里那句 `isMemberShipper()` 仍然留着：清单是第一道门，**执行是最后一道**，
 * 两道都要，因为"认不出角色/member 没问出来"时清单会退化成普通货主，而执行侧不能跟着退化。
 */
object AiWriteShipperLedger {

    /** 收款方式：与后端 `schemas/shipper_settlement.py::SETTLE_METHODS` 同一套词。 */
    val METHODS: List<String> = listOf("cash", "wechat", "transfer", "arrears_settle")

    val ACTIONS: List<AiWriteAction> = listOf(
        AiWriteAction(
            id = AiWrites.MY_LEDGER_SETTLE,
            title = "给我的货主核销",
            // MEDIUM：它记的是"我收到了谁的钱"。写错了要改——但这条路**能退**
            // （说一句"撤销那一笔"就走 MY_LEDGER_REVOKE，撤销本身还能恢复）。
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_MY_LEDGER,
            blurb = "在我的账本上记一笔核销：某个货主（联系人）把某张订单的钱给我了。" +
                "可以不点名商品 = 整单核销，也可以只核其中几样商品（按商品核销）。" +
                "**只记我自己这一本账，公司那边的账一分都不动**。",
            params = listOf(
                AiWriteParam(
                    "order_no",
                    "订单号",
                    required = true,
                    hint = "必填。**要写全**（如 SO202609201234567890），只写后几位我找不到；只能是自己的单",
                ),
                AiWriteParam(
                    "customer",
                    "货主（收货人）",
                    hint = "可选。**只传姓名**，用来核对这一单是不是他的；对不上我会拒绝，不会硬记",
                ),
                AiWriteParam(
                    "products",
                    "只核这几样商品",
                    hint = "可选。逗号分隔的商品名，如「白菜,萝卜」= 按商品核销；" +
                        "**留空 = 整单核销**（这一单还欠多少就核多少）",
                ),
                AiWriteParam(
                    "method",
                    "收款方式",
                    kind = AiWriteParamKind.ENUM,
                    hint = "可选，默认 cash",
                    enumValues = METHODS,
                ),
                AiWriteParam("note", "备注", hint = "可选，一句话（如「微信收款」）"),
            ),
            memberOnly = true,
        ),
        AiWriteAction(
            id = AiWrites.MY_LEDGER_REVOKE,
            title = "撤销我的核销",
            // MEDIUM：撤销**是软删**（记录还在，随时能恢复）。
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_MY_LEDGER,
            blurb = "把我在自己账本上记的一笔核销**撤掉**（后台是伪删除：记录留着，随时能恢复）。" +
                "撤掉之后那一单又变成「还欠我钱」。" +
                "公司那边的账不受影响。",
            params = listOf(
                AiWriteParam(
                    "order_no",
                    "订单号",
                    required = true,
                    hint = "必填，要写全。这一单记过的核销会被列出来让你挑",
                ),
                AiWriteParam("amount", "金额（元）", hint = "可选。同一单记过多笔时用它区分是哪一笔"),
            ),
            memberOnly = true,
        ),
        // 恢复：撤回专用（`undoOnly`），模型看不到它 —— 被撤掉的那一笔已经从列表里消失，
        // 按名字/单号根本找不到，而撤回路径拿着**确定的编号**。
        restoreAction(
            cn = "核销记录",
            id = AiWrites.MY_LEDGER_RESTORE,
            group = AiWrites.G_MY_LEDGER,
            memberOnly = true,
            call = { ds, id -> ds.restoreMySettlement(id) },
        ),
    )
}

/**
 * 我账本上的一行商品：**还可核销多少**。
 *
 * ⚠️ `remaining` 由数据源用 `ui/shipper/ShipperLedgerGrouping.kt::lineRemainingCents` 算好
 * （与界面、与后端 `services/shipper_settle.py::line_remaining` 同一个式子）——
 * **这里不另算一份**：算错的表现是"AI 说能核 80、点下去后端说只能核 60"。
 */
data class AiSettleLine(
    val id: Long,
    val name: String,
    /** 这一行原本该收多少（已扣退货）。 */
    val receivable: BigDecimal,
    /** 这一行已经核销过多少。 */
    val settled: BigDecimal,
) {
    val remaining: BigDecimal = (receivable - settled).max(BigDecimal.ZERO)
}

/** 我账本上的一张单：单号 + 归属货主 + 逐行"还可核销"。 */
data class AiSettleOrder(
    val id: Long,
    val orderNo: String,
    val customer: String,
    val customerPhone: String,
    val status: String,
    val lines: List<AiSettleLine>,
) {
    fun statusCn(): String = AiOrderRef.statusLabel(status)
}

/** 我记下的一笔核销（撤销要用它认人）。 */
data class AiMySettlementRef(
    val id: Long,
    val orderId: Long,
    val orderNo: String,
    val customer: String,
    val amount: String,
    val method: String,
    val settledAt: String,
    val isDeleted: Boolean,
    private val products: List<String>,
) {
    /** 卡片/候选名单上的一行字（**没有内部编号**）。 */
    fun label(): String = buildString {
        append(amount).append(" 元")
        if (methodCn.isNotBlank()) append(" · ").append(methodCn)
        if (settledAt.isNotBlank()) append(" · ").append(settledAt)
    }

    fun productNames(): String = products.joinToString("、")

    private val methodCn: String
        get() = when (method) {
            "cash" -> "现金"
            "wechat" -> "微信"
            "transfer" -> "转账"
            "arrears_settle" -> "结清欠款"
            else -> method
        }
}
