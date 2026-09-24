"""钱与账的**领域契约**（整改报告 §7「阶段 5：把领域真相从文件冻结升级为代码边界」）。

报告的原话是：

```text
以前：谁想用就 import 文件 → 靠 freeze 保证
以后：Domain Contract → 接口 → 唯一实现 → 所有消费方依赖接口
```

并点名了三个契约：`OrderMoneyCalculator` / `DriverPayCalculator` / `SettlementService`。

## 这一页是什么

一张**机器可核**的表：每个「钱数」＝ 口径一句话 + 唯一实现站点（`文件::符号`）+ 消费方清单 +
「别人不许这么算」的写法。判据在 `_tools/qa/_check_money_contract.py`（进 `_check_all.py` 必跑组），它逐条核对：

1. 实现站点还在，且**真的定义了**那个符号（AST，不是「我记得有」）；
2. 声明过的消费方**真的在用它**（AST 找 import —— 声明与事实不符就红）；
3. **除实现区之外**没有任何文件命中「自己又算了一遍」的写法（每条模式都写清为什么它是重复实现）；
4. 本模块自己**一行算术都没有** —— 接口里不许藏实现（否则「契约」会变成第二个实现点）。

## 为什么这一轮不直接把 import 全改到这一页

改 import 是「行为零变化」的活，但它要动 20 多个消费文件 —— 其中 `api/v1/reports.py`、
`services/reports_service.py`（两个都是钱的重度消费方）**正在被另一个会话改造成 service**。
所以分两步：① 先立契约 + 判据（本轮，不碰消费方一个字节）；② 等那些文件空下来再逐个把 import 指过来。
⛔ 顺序不能反：先改 import 而没有判据，等于把「哪一处是唯一实现」从代码搬回记忆里。

## 允许的例外

「实现区之外不许算」这条有例外（例如报表层按商品聚合营业额），例外**写在判据脚本的 `ALLOWED` 表里**，
每条都必须写清「为什么它不是第二个实现」，并且那条例外一旦不再命中就报红（防化石）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Figure:
    """一个「钱数」的契约条目。字段全部是**声明**，判据负责把它与源码对上。"""

    key: str
    name: str
    meaning: str
    impls: tuple[str, ...]
    consumers: tuple[str, ...]
    #: (稳定键, 正则, 为什么它是「自己又算了一遍」)。键给判据的允许表用 —— 正则改字不会让豁免失效，
    #: 而**键改了就会让豁免变成化石**（判据会报出来），这正是我们要的。
    forbid: tuple[tuple[str, str, str], ...]


#: ⚠️ `impls` / `consumers` 的路径都相对 `backend/app`，符号用 `::` 分隔 —— 判据按这两个字段去源码里核对。
FIGURES: tuple[Figure, ...] = (
    Figure(
        key="order_money",
        name="一张单的四个钱（应收 / 已收 / 已退现 / 欠款）",
        meaning=(
            "应收 = Σ行金额 − 退货红冲；欠款 = 应收 − 净已收（现场收现金没有流水，按 total 计）；"
            "恒等式 应收 = 净已收 + 欠款"
        ),
        impls=(
            "services/order_money.py::money_of",
            "services/order_money.py::money_map",
            "services/order_money.py::line_receivable",
        ),
        consumers=(
            "services/order_response.py",
            "api/v1/orders_query.py",
            "api/v1/orders_payment.py",
            "api/v1/reports.py",
            "services/reports_service.py",
            "api/v1/shipper_ledger.py",
        ),
        forbid=((
            "line_total_arith",
            r"\bline_total\b\s*[-+*/]|[-+*/]=\s*[\w.]{0,24}\bline_total\b",
            "行金额被拿去加减乘除 —— 应收只有 order_money.line_receivable 一处算",
        ), (
            "cashflow_sum",
            r"func\.sum\(\s*(CashFlow\.amount|Ledger\.total)",
            "自己聚合现金流/账本 —— 已收与红冲只有 order_money 一处算",
        )),
    ),
    Figure(
        key="driver_pay",
        name="司机应得（每单 / 工资 / 提成）与送达那一刻生成的应付",
        meaning="规则 = 工资 + 计件 + 提成三件可任意组合；派单时把规则快照进订单，送达按快照生成账单",
        impls=(
            "services/driver_pay.py::order_pay",
            "services/driver_pay.py::pay_for_order",
            "services/driver_pay.py::per_order_pay_filter",
            "services/driver_pay.py::has_per_order_pay",
            "services/driver_pay.py::pay_summary_for",
            "services/driver_pay.py::rule_of_user",
            "services/accounting_service.py::generate_piece_bill",
            "services/accounting_service.py::post_delivery_accounting",
        ),
        consumers=(
            "services/order_flow.py",
            "services/order_response.py",
            "services/stats_service.py",
            "services/reports_service.py",
            "api/v1/freight_settlement.py",
            "api/v1/driver_bills.py",
            "api/v1/users.py",
        ),
        forbid=((
            "freight_fee_arith",
            r"\bfreight_fee\b\s*[-+*/]|[-+*/]=\s*[\w.]{0,24}\bfreight_fee\b",
            "拿订单运费自己乘除 —— 「这个司机这单拿多少」只有 driver_pay 一处（少改一处就是账单 120、结算页 500）",
        ), (
            "commission_rate_arith",
            r"\bcommission_rate\b\s*[-+*/]|[-+*/]=\s*[\w.]{0,24}\bcommission_rate\b",
            "拿提成率自己乘 —— 提成只有 driver_pay 一处算",
        ), (
            "piece_amount_arith",
            r"\bpiece_amount\b\s*[-+*/]|[-+*/]=\s*[\w.]{0,24}\bpiece_amount\b",
            "拿计件额自己乘 —— 计件只有 driver_pay 一处算",
        )),
    ),
    Figure(
        key="shipper_settle",
        name="货主核销的上限与剩余（按商品核销）",
        meaning="每一行「还能收多少」= 行金额 − 该行已核销；上限由服务端算，客户端只填数量",
        impls=(
            "services/shipper_settle.py::line_remaining",
            "services/shipper_settle.py::remaining_of_lines",
            "services/shipper_settle.py::over_settled_lines",
            "services/shipper_settle.py::settle_blocker",
        ),
        consumers=("api/v1/shipper_ledger.py",),
        forbid=((
            "line_total_minus",
            r"\bline_total\b\s*-\s*",
            "自己用行金额减已核销 —— 剩余只有 shipper_settle 一处算",
        ),),
    ),
    Figure(
        key="order_return",
        name="退货红冲与退现（退多少、退给客户多少现金）",
        meaning="按行退数量、按行金额红冲账本、封顶不超过真正收过的钱；整单退完才进 RETURNED",
        impls=(
            "services/order_return.py::return_order",
            "services/order_return.py::max_returnable",
        ),
        consumers=(
            # ⚠️ `api/v1/return_requests.py` **不在**这里：它消费的是 `order_return_request`（申请单那条链），
            #    只 import 了 `OrderReturnError` / `ReturnItem` 两个类型 —— 声明它当消费方就是「假消费方」。
            "api/v1/orders_return.py",
            "services/order_return_request.py",
        ),
        forbid=((
            "refund_customer_flow",
            r"CashFlowBizType\.REFUND_CUSTOMER",
            "退给客户的现金流水只有 order_return 一处写（货损成本也挂 order_id，凭 biz_type 区分）",
        ),),
    ),
    Figure(
        key="supplier_payables",
        name="供应商应付款（欠了多少 / 付了多少）",
        meaning="应付款的已付 = 挂在它上面的资金流水合计；欠款 = 应付 − 已付",
        impls=(
            "services/supplier_service.py::supplier_totals",
            "services/supplier_service.py::payable_paid",
            "services/supplier_service.py::unpaid_of",
            "services/supplier_service.py::balance_of",
        ),
        consumers=("api/v1/suppliers.py",),
        forbid=((
            "supplier_cashflow_sum",
            r"func\.sum\(\s*CashFlow\.amount",
            "自己聚合资金流水当已付 —— 只有 supplier_service 一处算（与订单的钱不是同一个数）",
        ),),
    ),
)

#: 实现区 = 所有声明过的实现站点所在文件。判据用它当「允许出现钱算式」的集合。
IMPLEMENTATION_FILES: frozenset[str] = frozenset(
    impl.split("::")[0] for fig in FIGURES for impl in fig.impls
    # 成本口径（`cost_basis.py`）也属于钱，但它自己的判据在 `_check_cost_basis.py`，
    # 本轮没有为它写 forbid 模式 —— 先把它划进实现区，免得将来写模式时误报。
).union({"services/cost_basis.py"})
