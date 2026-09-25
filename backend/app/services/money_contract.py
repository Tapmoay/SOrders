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

## 接口：消费方依赖契约，不依赖实现（第 ② 步，2026-09-25 第 23 轮）

报告要的是「**所有消费方依赖接口**」，所以第 ② 步把消费方的 import 指到这一页：见下面的 `REEXPORTS`。
从此「钱只有一处实现」是**一条 import 语句**就能看出来的事，而不是靠一份清单 + 文件冻结。
⛔ 顺序是**先判据、再改 import**（判据的第 ⑥ 条钉着）：没有判据就改 import，等于把「哪一处是唯一实现」从代码搬回记忆。
⚠️ 还有两个消费方**暂时没改**（`api/v1/reports.py`、`services/reports_service.py`）：它们正在被另一个会话
下沉成 service、**尚未提交**，改过去只会把两个会话的改动搅在一起。判据里那两条例外写在 `PENDING` 表里、
写明理由，并且**等它落地后必须删掉**（例外不再命中就报红，防化石）。

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
            # 第二轮 R2-05：报表聚合搬进了 `services/reports/`。
            "services/reports/turnover_query.py",
            "services/reports/product_query.py",
            "services/reports/arrears_query.py",
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
            # ⛔ driver_pay 这条**只列 turnover_query**（多列两份会被判「假消费方」）。
            "services/reports/turnover_query.py",
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

# ---------------------------------------------------------------- 接口（转出）
#: 契约**转出**的钱符号：`符号 -> (实现模块, 该模块里的名字)`。
#: 消费方一律 `from app.services.money_contract import …` —— 转出的是**同一个对象**（判据核对它的 `__module__`），
#: ⛔ 不是在这里再包一层、更不是抄一份实现。
#: ⚠️ **为什么用惰性转出（PEP 562 的模块级 `__getattr__`）而不是文件顶端一句 import**：
#:    `order_return.py` 反过来 import `order_flow.mark_returned`，而 `order_flow` 自己就是消费方 ——
#:    顶端 eager import 当场成环（order_flow → money_contract → order_return → order_flow）。
#:    惰性转出把「取符号」推迟到真正用它的那一刻，环就不成立，而 `from … import 符号` 照常可用。
#: ⚠️ `accounting_service` 的两个实现符号（`generate_piece_bill` / `post_delivery_accounting`）**不转出**：
#:    它反过来 import `order_flow`，转出会成环；它们仍然按上面的 `impls` 声明当"实现站点"核对。
REEXPORTS: dict[str, tuple[str, str]] = {
    # order_money：一张单的四个钱（应收 / 已收 / 已退现 / 欠款）
    "money_of": ("app.services.order_money", "money_of"),
    "money_map": ("app.services.order_money", "money_map"),
    "line_receivable": ("app.services.order_money", "line_receivable"),
    # driver_pay：司机应得（每单 / 工资 / 提成）
    "order_pay": ("app.services.driver_pay", "order_pay"),
    "pay_for_order": ("app.services.driver_pay", "pay_for_order"),
    "per_order_pay_filter": ("app.services.driver_pay", "per_order_pay_filter"),
    "has_per_order_pay": ("app.services.driver_pay", "has_per_order_pay"),
    "pay_summary_for": ("app.services.driver_pay", "pay_summary_for"),
    "rule_of_user": ("app.services.driver_pay", "rule_of_user"),
    # shipper_settle：货主核销的上限与剩余
    "line_remaining": ("app.services.shipper_settle", "line_remaining"),
    "remaining_of_lines": ("app.services.shipper_settle", "remaining_of_lines"),
    "over_settled_lines": ("app.services.shipper_settle", "over_settled_lines"),
    "settle_blocker": ("app.services.shipper_settle", "settle_blocker"),
    # order_return：退货红冲与退现
    "return_order": ("app.services.order_return", "return_order"),
    "max_returnable": ("app.services.order_return", "max_returnable"),
}


def __getattr__(name: str):
    """模块级惰性转出（PEP 562）—— 理由见 `REEXPORTS` 上面那段。"""
    try:
        module, symbol = REEXPORTS[name]
    except KeyError:
        raise AttributeError("module " + repr(__name__) + " has no attribute " + repr(name)) from None
    from importlib import import_module

    value = getattr(import_module(module), symbol)
    globals()[name] = value  # 取到就放进模块字典，后面几次不再走这里
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(REEXPORTS))


#: 实现区 = 所有声明过的实现站点所在文件。判据用它当「允许出现钱算式」的集合。
IMPLEMENTATION_FILES: frozenset[str] = frozenset(
    impl.split("::")[0] for fig in FIGURES for impl in fig.impls
    # 成本口径（`cost_basis.py`）也属于钱，但它自己的判据在 `_check_cost_basis.py`，
    # 本轮没有为它写 forbid 模式 —— 先把它划进实现区，免得将来写模式时误报。
).union({"services/cost_basis.py"})
