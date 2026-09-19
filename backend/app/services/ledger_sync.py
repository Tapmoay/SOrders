"""账本与订单明细一致性：关联订单的账本行变更时同步 OrderProduct；送达时由订单明细生成账本。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.business_time import business_date
from app.models import Ledger, Order, OrderProduct
from app.models.enums import LedgerSource, OrderStatus


def sync_ledger_from_delivered_order(db: Session, order: Order) -> None:
    """订单变为已送达且存在归属（系统货主或临时货主名）时，按订单明细自动写入/更新账本（来源 order，按 order_product_id 幂等）。"""
    if order.status != OrderStatus.DELIVERED:
        return
    has_user_shipper = order.shipper_id is not None
    temp_name = (order.temp_shipper_name or "").strip()
    has_temp = bool(temp_name)
    if not has_user_shipper and not has_temp:
        return
    entry_date: date
    # ⚠️ 账本行的日期用**业务当地日**（2026-09-19 审计 R12-M11）：`delivered_at` 是 UTC，
    #    直接取 `.date()` 会让东八区凌晨送达的单记成"前一天的那笔账"
    #    —— 账本按日期筛/对账时就会跟订单的送达日对不上。
    entry_date = business_date(order.delivered_at) or order.order_date
    shipper_id = order.shipper_id
    temp_shipper_name = temp_name if not has_user_shipper else None
    for op in order.order_products:
        lt = op.line_total if op.line_total is not None else (op.unit_price * Decimal(op.quantity))
        existing = db.scalars(
            select(Ledger).where(
                Ledger.order_product_id == op.id,
                Ledger.source == LedgerSource.ORDER,
            )
        ).first()
        if existing is not None:
            existing.shipper_id = shipper_id
            existing.temp_shipper_name = temp_shipper_name
            existing.entry_date = entry_date
            existing.product_name = op.product_name_snapshot
            existing.quantity = op.quantity
            existing.unit_price = op.unit_price
            existing.total = lt
            existing.order_id = order.id
            existing.product_id = op.product_id
            existing.cost_price_snapshot = op.cost_price_snapshot or Decimal("0")
            if not (existing.note or "").strip():
                existing.note = "订单送达自动记账"
            continue
        db.add(
            Ledger(
                shipper_id=shipper_id,
                temp_shipper_name=temp_shipper_name,
                entry_date=entry_date,
                product_name=op.product_name_snapshot,
                quantity=op.quantity,
                unit_price=op.unit_price,
                total=lt,
                order_id=order.id,
                order_product_id=op.id,
                product_id=op.product_id,
                source=LedgerSource.ORDER,
                note="订单送达自动记账",
                cost_price_snapshot=op.cost_price_snapshot or Decimal("0"),
            )
        )


def sync_order_product_from_ledger(db: Session, ledger: Ledger) -> None:
    """把账本行的数量/单价/金额**写回订单商品行**。

    ⛔ **只有 `source=ORDER` 的行才允许回写**（2026-09-19 审计 F2，高）。
    原来只排除了 `MANUAL`，于是 `REFUND`（货损红冲）那类行也走回写，而它们的
    `quantity/unit_price/total` 记的是**被冲掉的那一部分**（本机实例：ledgers.id=17 是
    `REFUND` 行，quantity=2 / unit_price=0 / total=0，指向 order_products.id=26，
    而那一行真实值是 qty=10 / 单价 23.5 / 金额 235）。

    于是"改一下那条红冲的备注"就会把订单行**静默清零**：数量→2、单价→0、金额→0，
    营业额 235→0、挂账未收与商品经营全线掉数，而司机账单（按送达时冻结）与那条
    ORDER 账本行仍然是 235 —— **一张单三个数**，且操作日志里因为"明细本身没变"
    记的是"什么都没改"。

    回写的语义只在"这一行账本就是订单行的那份账"时成立，那就是 `source=ORDER`。
    """
    if ledger.source != LedgerSource.ORDER:
        return
    if ledger.order_id is None:
        return
    op: OrderProduct | None = None
    if ledger.order_product_id is not None:
        cand = db.get(OrderProduct, ledger.order_product_id)
        if cand is not None and cand.order_id == ledger.order_id:
            op = cand
    if op is None and ledger.product_id is not None:
        op = db.scalars(
            select(OrderProduct).where(
                OrderProduct.order_id == ledger.order_id,
                OrderProduct.product_id == ledger.product_id,
            )
        ).first()
    if op is None:
        name = (ledger.product_name or "").strip()
        op = db.scalars(
            select(OrderProduct).where(
                OrderProduct.order_id == ledger.order_id,
                OrderProduct.product_name_snapshot == name,
            )
        ).first()
    if op is None:
        return
    op.quantity = ledger.quantity
    op.unit_price = ledger.unit_price
    op.line_total = ledger.total
    if ledger.product_name and op.product_name_snapshot != ledger.product_name:
        op.product_name_snapshot = ledger.product_name


def sync_delivered_orders_to_ledger(
    db: Session,
    shipper_id: int | None = None,
    temp_shipper_name: str | None = None,
) -> tuple[int, set[int]]:
    """对已送达订单批量执行账本同步（与送达时逻辑相同，用于历史补全）。返回 (订单数, 涉及系统货主 id 集合，用于消息推送)。"""
    stmt = (
        select(Order)
        .where(Order.status == OrderStatus.DELIVERED)
        .where(or_(Order.shipper_id.isnot(None), Order.temp_shipper_name.isnot(None)))
        .options(selectinload(Order.order_products))
    )
    if shipper_id is not None:
        stmt = stmt.where(Order.shipper_id == shipper_id)
    elif temp_shipper_name is not None and temp_shipper_name.strip():
        stmt = stmt.where(Order.shipper_id.is_(None)).where(Order.temp_shipper_name == temp_shipper_name.strip())
    orders = list(db.scalars(stmt).unique().all())
    affected_shippers: set[int] = set()
    for order in orders:
        sync_ledger_from_delivered_order(db, order)
        if order.shipper_id is not None:
            affected_shippers.add(order.shipper_id)
    return len(orders), affected_shippers