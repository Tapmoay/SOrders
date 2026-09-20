"""批发商**自己那一本账**的金额口径 —— 只有这一份实现。

## 口径（改这里就是改全局）

对**每一行商品**（`order_products`）：

    行应收     = `order_money.line_receivable(op)`      ← 复用已有那一份，**不另算一套**
    行已核销   = Σ 未删核销记录里这一行的金额（`shipper_settlement_lines`）
    行还可核销 = 行应收 − 行已核销            （≤ 0 = 这一行收齐了）

对**每一张订单**：

    单已核销   = Σ 各行已核销
    单还可核销 = Σ 各行还可核销

## 为什么必须只有一份
界面上"这一单还能核销 ¥X"是拿这份算的，提交时后端也拿它校验上限。
两边各写一遍必然走散（本项目栽过：界面让填 3、后端只认 2），
而走散的表现是**用户按界面上的数点了核销、后端报一句看不懂的错**。

## ⛔ 这份钱与派单员的钱是两笔
`order_money`（应收/已收/欠款）是**公司 ↔ 货主**的账；
本模块是**批发商 ↔ 他的下游货主**的账。两者**共用一张订单**，但一个字段都不交叉：
本模块只**读**订单行金额（那是我卖给他的货值），一个字节都不写回订单、账本或资金流水。
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, OrderProduct
from app.models.enums import OrderStatus
from app.models.shipper_settlement import ShipperSettlement, ShipperSettlementLine
from app.services.order_money import line_receivable, q2

ZERO = Decimal("0")

#: 一次核销最多覆盖多少行（真正的上限来自订单本身：`OrderCreate.lines` 最多 10 行）
MAX_SETTLE_LINES = 50


def _alive_settlement_ids(db: Session) -> object:
    """没进回收站的核销记录（父记录的标记是唯一判据，见模型注释）。"""
    return select(ShipperSettlement.id).where(ShipperSettlement.is_deleted.is_(False))


def settled_line_map(db: Session, order_product_ids: list[int]) -> dict[int, Decimal]:
    """这几行**各自已经核销了多少**（一次查询，与行数无关）。"""
    ids = [int(i) for i in order_product_ids if i]
    if not ids:
        return {}
    rows = db.execute(
        select(
            ShipperSettlementLine.order_product_id,
            ShipperSettlementLine.amount,
        )
        .where(ShipperSettlementLine.order_product_id.in_(ids))
        .where(ShipperSettlementLine.settlement_id.in_(_alive_settlement_ids(db)))
    ).all()
    out: dict[int, Decimal] = {}
    for opid, amount in rows:
        key = int(opid)
        out[key] = q2(out.get(key, ZERO) + Decimal(amount or 0))
    return out


def settled_order_map(db: Session, order_ids: list[int]) -> dict[int, Decimal]:
    """这几张单**各自已经核销了多少**（批发商向他的货主收的钱）。"""
    ids = [int(i) for i in order_ids if i]
    if not ids:
        return {}
    rows = db.execute(
        select(ShipperSettlementLine.order_id, ShipperSettlementLine.amount)
        .where(ShipperSettlementLine.order_id.in_(ids))
        .where(ShipperSettlementLine.settlement_id.in_(_alive_settlement_ids(db)))
    ).all()
    out: dict[int, Decimal] = {}
    for oid, amount in rows:
        key = int(oid)
        out[key] = q2(out.get(key, ZERO) + Decimal(amount or 0))
    return out


def line_remaining(op: OrderProduct, settled: Decimal) -> Decimal:
    """这一行**现在还能核销多少**（= 行应收 − 已核销；不会小于 0）。"""
    left = q2(line_receivable(op) - Decimal(settled or 0))
    return left if left > ZERO else ZERO


def remaining_of_lines(order: Order, settled_lines: dict[int, Decimal]) -> list[tuple[OrderProduct, Decimal]]:
    """订单的每一行 + 它还可核销多少（顺序与 `order.order_products` 一致）。"""
    out: list[tuple[OrderProduct, Decimal]] = []
    for op in order.order_products:
        out.append((op, line_remaining(op, settled_lines.get(op.id, ZERO))))
    return out


def lines_of_order(db: Session, order: Order) -> list[tuple[OrderProduct, Decimal]]:
    """订单各行 + 各行还可核销多少（**界面与提交共用这一份**）。"""
    settled = settled_line_map(db, [op.id for op in order.order_products])
    return remaining_of_lines(order, settled)


def order_settle_state(db: Session, order: Order) -> tuple[Decimal, Decimal]:
    """(单已核销, 单还可核销)。"""
    pairs = lines_of_order(db, order)
    settled_total = ZERO
    left_total = ZERO
    for op, left in pairs:
        left_total += left
        settled_total += line_receivable(op) - left
    return q2(settled_total), q2(left_total)


def settle_blocker(order: Order) -> str | None:
    """**现在能不能核销这一单**；不能就返回一句能照着做的中文（能则 None）。

    三道门，都是"这笔钱现在还不该存在"的情形：
    · 单子还没送达 / 已撤销：货没到客户手上，他还没向客户收钱；
    · 单子已整单退货：应收被红冲冲平了（`line_receivable` = 0），没得收；
    · 单子已软删（在回收站里）：它连自己的列表都进不去，别在它上面记账。
    """
    if order.deleted_at is not None:
        return "这张单在回收站里（已删除），先恢复它再核销"
    if order.status in (OrderStatus.PENDING_DISPATCH, OrderStatus.DISPATCHED, OrderStatus.ACCEPTED):
        return "这张单还没送达，先别核销（送达之后才有这笔应收）"
    if order.status == OrderStatus.CANCELLED:
        return "这张单已撤销，没有应收可核销"
    if order.status == OrderStatus.RETURNED:
        return "这张单已整单退货，货款已经冲平，没有可核销的金额"
    return None
