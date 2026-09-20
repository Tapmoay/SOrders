"""一张订单的**钱**只有这一份算法：应收 / 已收 / 已退 / 欠款。

## 为什么必须只有一处实现（2026-09-20）

在这之前，"这张单还欠多少"是靠 `orders.paid` 一个布尔 + 现场把 `order_products.line_total`
加起来**在四个地方各算一遍**（营业纵览、挂账单位报表、订单出参、账本页）。那时它是安全的 ——
因为核销只有一种形态：**整单核销**，`paid` 一翻就是"全收"或"全没收"，四处算出来的数必然一致。

本轮加进来的两件事把这个前提打破了：

1. **按商品核销**（用户：「点击订单点击核销……也可以按商品进行核销」）——
   一张单可以只收一部分钱，`paid` 仍然是 False，而"欠多少"已经不是整单金额了；
2. **退货红冲**（用户：「可以整单退货，也可以只退其中的某几个商品」）——
   应收会被 `ledgers` 上的负金额红冲行**减掉**，而 `order_products.line_total` 不会变
   （那是"当时卖了多少"，不是"现在该收多少"）。

两者叠加之后，四处各算一遍必然出现"同一个客户，报表说欠 700、账本页说欠 1000"，
而且**两边都不报错**。所以这里把口径钉成一处，四个消费点全部改成调它：

## 口径（唯一一份，改这里就是改全局）

    total       = Σ 商品行 line_total          （当时卖了多少，不随退货变）
    returned    = Σ |ledgers.source=RETURN 的 total|（已退金额，正数）
    receivable  = total − returned             （**应收**：营业额看的也是这个数）
    settled     = 已收：Σ(cash_flows IN, 本单) ；现场收现金（`paid` 且没有流水）按 total 计
    refunded    = Σ(cash_flows OUT 且 biz_type=REFUND_CUSTOMER, 本单)（已退给客户的现金）
    arrears     = receivable − settled + refunded   （**欠款**；< 0 = 预收）

两边恒等式（验算见 `tests/test_order_return.py`）：
`receivable == (settled − refunded) + arrears`，也就是「应收 = 净已收 + 欠款」。

## 两个必须记住的坑

· **现场收现金没有现金流水**（`orders.py::_apply_complete_payment` 只翻 `paid`），
  所以 `settled` 不能只看流水 —— 只看流水会把"司机现场收的现金"当成没收到，
  这张单会永远留在催收名单里，而且收款人手里明明有钱。
· **`cash_flows` 里挂在本单上的 OUT 不都是退款**：货损成本（`EXPENSE_LOSS`）也带 `order_id`。
  退款的判据只有 `biz_type == REFUND_CUSTOMER` 一条，用"所有 OUT"会把货损当成退给客户的钱。
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CashFlow, Ledger, Order, OrderProduct
from app.models.enums import CashFlowBizType, LedgerSource

ZERO = Decimal("0")


def q2(v: Decimal) -> Decimal:
    """全项目统一两位小数（与 `driver_pay.money()` 同一个进位方式，见那里的注释）。"""
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class OrderMoney:
    """一张订单的钱。所有字段都已经是"可以直接显示"的两位小数。"""

    total: Decimal
    returned: Decimal
    receivable: Decimal
    settled: Decimal
    refunded: Decimal
    arrears: Decimal
    fully_returned: bool

    @property
    def net_collected(self) -> Decimal:
        """净已收 = 已收 − 已退现。与 [arrears] 相加必然等于 [receivable]。"""
        return q2(self.settled - self.refunded)


def _group_sum(db: Session, key_col, value_col, *where) -> dict[int, Decimal]:
    """按 `order_id` 分组求和（一次查询解决一张列表，避免逐单发 SQL）。

    ⚠️ `value_col` 传**列对象**、不传 `func.sum(...)`：传聚合表达式进来会变成
       `sum(sum(x))`，SQLite 直接报 `misuse of aggregate function sum()`
       （第一版就是这么写的，跑测试当场红）。
    """
    stmt = select(key_col, func.sum(value_col)).where(key_col.isnot(None), *where).group_by(key_col)
    return {int(k): Decimal(v or 0) for k, v in db.execute(stmt).all()}


def _is_inflow(direction: object) -> bool:
    """是不是"钱进来"。`direction` 两种库里都存小写（`in`/`out`），老数据可能带大写。"""
    return str(getattr(direction, "value", direction) or "").lower() == "in"


def _is_customer_refund(direction: object, biz: object) -> bool:
    """是不是"退给客户的现金"。**只看 `REFUND_CUSTOMER`** —— 货损成本流水也挂 `order_id`。"""
    if str(getattr(direction, "value", direction) or "").lower() != "out":
        return False
    return str(getattr(biz, "value", biz) or "") == CashFlowBizType.REFUND_CUSTOMER.value


def line_receivable(op: OrderProduct) -> Decimal:
    """**这一行现在还能收多少** = 行金额 − 单价 × 已退数量。

    这是"按商品核销"的金额来源，也是整单核销的金额来源（整单 = 所有行的和）：
    两者必须是同一个算法，否则会出现"整单核销要 700、按商品加起来要 1000"
    —— 而两个数都印在同一张核销弹层上。

    为什么不用 `quantity − returned_quantity` 直接乘单价：`line_total` 在生产库里有
    历史折扣（不等于 `单价×数量`），按行存下来的 `line_total` 才是当时真正卖的价。
    """
    total = op.line_total if op.line_total is not None else (op.unit_price or ZERO) * Decimal(op.quantity or 0)
    returned = (op.unit_price or ZERO) * Decimal(int(op.returned_quantity or 0))
    return q2(Decimal(total) - returned)


def money_map(db: Session, orders: list[Order], *, lock: bool = False) -> dict[int, OrderMoney]:
    """一批订单的钱（**4 条分组查询，与订单条数无关**）。

    ⚠️ 不许改成"逐单 `money_of`"：订单列表一页 300 条就是 1200 条 SQL，
       而 `enrich_order_out` 本来就已经在逐单 `db.get` 了（`ledger_response` 那条注释
       记着同类问题的实测代价：85,474 行 → 27.75 秒）。

    `lock=True` = **收款的防重算**要用的那一档（`accounting_service.create_receipt`）：
    现金流水改成**加锁读**（`SELECT … FOR UPDATE`）并在 Python 里用同一套判据汇总。
    为什么非这样不可：MySQL 的 REPEATABLE READ 下，普通 SELECT 读的是事务**开始时**的快照 ——
    两个并发核销各自读到"还欠 1000"，就都能通过"这次核销不许超过欠款"的校验，
    结果收了两倍的钱（**而这正是本项目最贵的一类错**）。加锁读永远读到最新已提交值，
    且后到的那个请求会一直等到前一个提交后才继续 —— 于是它看到的是"还欠 300"。
    """
    ids = [o.id for o in orders]
    if not ids:
        return {}

    totals = _group_sum(
        db, OrderProduct.order_id, OrderProduct.line_total, OrderProduct.order_id.in_(ids)
    )
    # 退货红冲行存的是**负数**（红冲），取负号变回"已退金额"这个正数口径
    returned = _group_sum(
        db,
        Ledger.order_id,
        Ledger.total,
        Ledger.order_id.in_(ids),
        Ledger.source == LedgerSource.RETURN,
    )
    if lock:
        inflow: dict[int, Decimal] = {}
        refund: dict[int, Decimal] = {}
        flow_rows = db.execute(
            select(CashFlow.order_id, CashFlow.direction, CashFlow.biz_type, CashFlow.amount)
            .where(CashFlow.order_id.in_(ids))
            .with_for_update()
        ).all()
        for oid, direction, biz, amount in flow_rows:
            if _is_inflow(direction):
                inflow[oid] = inflow.get(oid, ZERO) + Decimal(amount or 0)
            elif _is_customer_refund(direction, biz):
                refund[oid] = refund.get(oid, ZERO) + Decimal(amount or 0)
    else:
        inflow = _group_sum(
            db,
            CashFlow.order_id,
            CashFlow.amount,
            CashFlow.order_id.in_(ids),
            func.lower(CashFlow.direction) == "in",
        )
        refund = _group_sum(
            db,
            CashFlow.order_id,
            CashFlow.amount,
            CashFlow.order_id.in_(ids),
            func.lower(CashFlow.direction) == "out",
            CashFlow.biz_type == CashFlowBizType.REFUND_CUSTOMER,
        )

    out: dict[int, OrderMoney] = {}
    for o in orders:
        total = q2(totals.get(o.id, ZERO))
        ret = q2(-returned.get(o.id, ZERO))
        receivable = q2(total - ret)
        got = inflow.get(o.id, ZERO)
        # 现场收现金：`paid=True` 却**一条流水都没有**（见模块头注释）。
        # ⚠️ 判据必须是"有没有流水"，不能写成 `max(got, total if paid else 0)`：
        #    退过货的单的应收比 `total` 小，收款是按应收收的（流水 60 < total 100），
        #    取 max 会把已收算成 100 → 欠款变 −40（"预收 40"），而钱其实一分不差。
        settled = q2(got if got > ZERO else (total if o.paid else ZERO))
        refunded = q2(refund.get(o.id, ZERO))
        out[o.id] = OrderMoney(
            total=total,
            returned=ret,
            receivable=receivable,
            settled=settled,
            refunded=refunded,
            arrears=q2(receivable - settled + refunded),
            # 整单退完的判据：退掉的金额已经把应收冲平（而不是"退过一次"）
            fully_returned=bool(ret > 0 and ret >= total),
        )
    return out


def money_of(db: Session, order: Order, *, lock: bool = False) -> OrderMoney:
    """单张订单的钱（**列表请用 [money_map]**，别在循环里调它）。"""
    return money_map(db, [order], lock=lock)[order.id]
