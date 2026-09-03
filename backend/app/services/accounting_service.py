"""账本 V2 统一账务钩子（单源事实）：送达→两支明细+货损；收款→逐单核销；结算单状态机；开销→资金流水。

约定（REV5 定稿）：
- 客户欠款 = Σledgers(含负向红冲) − Σcash_flows(IN, customer) + Σcash_flows(OUT, REFUND_CUSTOMER, customer)
- 司机未结 = Σdriver_bills(未作废) − Σcash_flows(OUT, driver) + Σcash_flows(IN, REFUND_DRIVER, driver)
- 货损（公司自担）：EXPENSE_LOSS（成本口径）+ ledgers 专用红冲行（amount=0、负成本快照冲回 COGS），客户/营业额零影响。
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    CashFlow,
    Customer,
    DriverBill,
    DriverSettlement,
    Expense,
    Ledger,
    Order,
    OrderProduct,
    ShipperReceipt,
    User,
)
from app.models.enums import (
    CashFlowBizType,
    CashFlowDirection,
    DriverBillStatus,
    DriverBillType,
    ExpenseCategory,
    LedgerSource,
    ReceiptSettleMode,
    SettlementStatus,
)
from app.schemas.accounting_v2 import (
    DriverSettlementCreate,
    ExpenseCreate,
    ShipperReceiptCreate,
)


# ---------- 工具 ----------
def _month_of(dt: datetime | None) -> str:
    d = dt or datetime.now(timezone.utc)
    return d.strftime("%Y-%m")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def customer_display_name(db: Session, customer_id: int | None, customer: Customer | None = None) -> str:
    c = customer or (db.get(Customer, customer_id) if customer_id else None)
    return c.name if c else ""

def resolve_customer_for_order(db: Session, order: Order) -> Customer | None:
    """订单归属客户：registered→按 user_id；temp→按名称（尽力匹配）。"""
    if order.shipper_id is not None:
        return db.scalars(select(Customer).where(Customer.user_id == order.shipper_id)).first()
    name = (order.temp_shipper_name or "").strip()
    if not name:
        return None
    return db.scalars(select(Customer).where(Customer.name == name)).first()


# ---------- ① 送达：司机应付明细（PIECE 幂等生成） ----------
def generate_piece_bill(db: Session, order: Order, operator_id: int | None = None) -> DriverBill | None:
    """订单送达且为按单计费司机且运费非空 → 生成/复用 PIECE 明细。幂等：order_id+bill_type 唯一。"""
    if order.status.value != "DELIVERED":
        return None
    mode = (order.driver_billing_mode_snapshot or "").upper()
    if mode != "PIECE":
        return None
    fee = order.freight_fee
    if fee is None or Decimal(fee) <= 0:
        return None
    existing = db.scalars(
        select(DriverBill).where(
            DriverBill.order_id == order.id,
            DriverBill.bill_type == DriverBillType.PIECE,
        )
    ).first()
    if existing is not None:
        return existing
    bill = DriverBill(
        driver_id=order.driver_id or 0,
        bill_type=DriverBillType.PIECE,
        order_id=order.id,
        month=_month_of(order.delivered_at),
        amount=Decimal(fee),
        status=DriverBillStatus.OPEN,
        note="订单送达自动生成",
    )
    db.add(bill)
    return bill


# ---------- ② 送达：货损（公司自担）记账 ----------
def apply_damage_accounting(db: Session, order: Order, operator_id: int | None = None) -> None:
    """商品行级货损 → ①EXPENSE_LOSS(成本×数量) ②ledgers 专用红冲行(amount=0, 负成本快照)。
    货损成本=该行 cost_price_snapshot×damage_quantity；客户欠款/营业额零影响（客户全额付款）。"""
    for op in order.order_products:
        qty = op.damage_quantity or 0
        if qty <= 0:
            continue
        cost = op.cost_price_snapshot or Decimal("0")
        cost_amt = (cost * Decimal(qty)).quantize(Decimal("0.01"))
        if cost_amt <= 0:
            op.damage_quantity = 0  # 无成本快照时货损金额为 0，置回不计（提示在接口层）
            continue
        dod = order.delivered_at.date() if order.delivered_at else order.order_date
        exp = Expense(
            exp_date=dod,
            category=ExpenseCategory.LOSS,
            amount=cost_amt,
            driver_id=order.driver_id,
            order_id=order.id,
            note=f"送达货损 {qty} 件 × 成本 {cost}（{order.order_no}）",
            operator_id=operator_id,
        )
        db.add(exp)
        db.flush()
        db.add(
            CashFlow(
                flow_date=dod,
                direction=CashFlowDirection.OUT,
                amount=cost_amt,
                party_type="expense",
                party_id=exp.id,
                party_name="货损",
                channel="cash",
                biz_type=CashFlowBizType.EXPENSE_LOSS,
                order_id=order.id,
                doc_id=exp.id,
                note=exp.note,
                operator_id=operator_id,
            )
        )
        # ledgers 专用红冲行：amount=0，负成本快照冲回 COGS（不影响营业额/欠款）
        cust = resolve_customer_for_order(db, order)
        db.add(
            Ledger(
                shipper_id=order.shipper_id,
                temp_shipper_name=order.temp_shipper_name if order.shipper_id is None else None,
                customer_id=cust.id if cust else None,
                entry_date=dod,
                product_name=op.product_name_snapshot,
                quantity=qty,
                unit_price=Decimal("0"),
                total=Decimal("0"),
                order_id=order.id,
                order_product_id=op.id,
                product_id=op.product_id,
                source=LedgerSource.REFUND,
                note=f"送达货损成本冲回（自动）{qty} 件",
                cost_price_snapshot=-(cost * Decimal(qty)).quantize(Decimal("0.0001")),
            )
        )


# ---------- ③ 送达：总钩子（先 bill 后货损） ----------
def post_delivery_accounting(db: Session, order: Order, operator_id: int | None = None) -> None:
    generate_piece_bill(db, order, operator_id)
    apply_damage_accounting(db, order, operator_id)


# ---------- ④ 客户收款单：逐单核销 ----------
def create_receipt(db: Session, body: ShipperReceiptCreate, operator_id: int | None) -> ShipperReceipt:
    cust = db.get(Customer, body.customer_id)
    if cust is None:
        raise ValueError("客户档案不存在")
    if body.settle_mode == ReceiptSettleMode.ITEMIZED:
        if not body.order_ids:
            raise ValueError("逐单核销需绑定订单")
        total = Decimal("0")
        for oid in body.order_ids:
            o = db.get(Order, oid)
            if o is None:
                raise ValueError(f"订单 {oid} 不存在")
            if o.shipper_id is None:
                raise ValueError(f"订单 {oid} 无客户归属（临时货主收款需先关联客户档案）")
            if o.shipper_id != cust.user_id:
                raise ValueError(f"订单 {oid} 不属于该客户")
            total += sum((op.line_total or Decimal("0")) for op in o.order_products)
        if Decimal(body.amount) != total:
            raise ValueError(f"收款金额 {body.amount} 与所选订单合计 {total} 不一致（逐单核销需全额）")
    receipt = ShipperReceipt(
        customer_id=body.customer_id,
        amount=body.amount,
        method=body.method,
        received_at=body.received_at,
        order_ids=body.order_ids,
        settle_mode=body.settle_mode,
        arrears_unit_id=body.arrears_unit_id,
        note=body.note,
        operator_id=operator_id,
    )
    db.add(receipt)
    db.flush()
    biz = CashFlowBizType.RECEIPT_CASH
    if body.method == "transfer":
        biz = CashFlowBizType.RECEIPT_TRANSFER
    elif body.method == "wechat":
        biz = CashFlowBizType.RECEIPT_TRANSFER
    elif body.method == "arrears_settle":
        biz = CashFlowBizType.RECEIPT_ARREARS
    for oid in (body.order_ids or []):
        o = db.get(Order, oid)
        if o is not None:
            o.paid = True
            o.payment_method = "cash" if body.method in ("cash", "transfer", "wechat") else "arrears"
        db.add(
            CashFlow(
                flow_date=body.received_at,
                direction=CashFlowDirection.IN,
                amount=body.amount if len(body.order_ids or []) == 1 else None,
                party_type="customer",
                party_id=cust.id,
                party_name=cust.name,
                channel="wechat" if body.method == "wechat" else ("bank" if body.method == "transfer" else "cash"),
                biz_type=biz,
                order_id=oid,
                doc_id=receipt.id,
                note=f"客户收款（逐单核销）",
                operator_id=operator_id,
            )
        )
    return receipt


# ---------- ⑤ 司机结算单状态机 ----------
def create_settlement(db: Session, body: DriverSettlementCreate, operator_id: int | None) -> DriverSettlement:
    driver = db.get(User, body.driver_id)
    if driver is None:
        raise ValueError("司机不存在")
    if body.settle_type == DriverBillType.PIECE:
        bills = list(
            db.scalars(
                select(DriverBill).where(
                    DriverBill.driver_id == body.driver_id,
                    DriverBill.bill_type == DriverBillType.PIECE,
                    DriverBill.month == body.month,
                    DriverBill.status == DriverBillStatus.OPEN,
                )
            )
        )
        order_ids = [b.order_id for b in bills if b.order_id]
        amount = sum((b.amount for b in bills), Decimal("0"))
        period_from = date(int(body.month[:4]), int(body.month[5:7]), 1)
        period_to = period_from
    else:
        bills = list(
            db.scalars(
                select(DriverBill).where(
                    DriverBill.driver_id == body.driver_id,
                    DriverBill.bill_type == DriverBillType.SALARY,
                    DriverBill.month == body.month,
                    DriverBill.status == DriverBillStatus.OPEN,
                )
            )
        )
        order_ids = []
        amount = sum((b.amount for b in bills), Decimal("0"))
        period_from = None
        period_to = None
    if not bills:
        raise ValueError(f"{body.month} 无待结算明细（请先生成账单）")
    if body.amount is not None and Decimal(body.amount) != amount:
        amount = Decimal(body.amount)  # 允许手工调整（注记差异）
    s = DriverSettlement(
        driver_id=body.driver_id,
        settle_type=body.settle_type,
        month=body.month,
        period_from=period_from,
        period_to=period_to,
        amount=amount,
        status=SettlementStatus.DRAFT,
        order_ids=order_ids,
        operator_id=operator_id,
        note=body.note,
    )
    db.add(s)
    return s


def confirm_settlement(db: Session, s: DriverSettlement, operator_id: int | None) -> DriverSettlement:
    if s.status != SettlementStatus.DRAFT:
        raise ValueError("仅草稿可确认")
    # 原子锁定：仍 OPEN 的所属 bills → SETTLED
    if s.settle_type == DriverBillType.PIECE and s.order_ids:
        bills = list(
            db.scalars(
                select(DriverBill).where(
                    DriverBill.id.in_(
                        select(DriverBill.id).where(
                            DriverBill.order_id.in_(s.order_ids),
                            DriverBill.driver_id == s.driver_id,
                            DriverBill.bill_type == DriverBillType.PIECE,
                            DriverBill.status == DriverBillStatus.OPEN,
                        )
                    )
                )
            )
        )
    else:
        bills = list(
            db.scalars(
                select(DriverBill).where(
                    DriverBill.driver_id == s.driver_id,
                    DriverBill.bill_type == s.settle_type,
                    DriverBill.month == s.month,
                    DriverBill.status == DriverBillStatus.OPEN,
                )
            )
        )
    if not bills:
        raise ValueError("账单已被其他结算单占用或不存在")
    locked_total = sum((b.amount for b in bills), Decimal("0"))
    if Decimal(s.amount) != locked_total:
        raise ValueError(f"结算单金额 {s.amount} 与明细合计 {locked_total} 不一致，请核对")
    for b in bills:
        b.status = DriverBillStatus.SETTLED
        b.settled_doc_id = s.id
    s.status = SettlementStatus.CONFIRMED
    return s


def pay_settlement(db: Session, s: DriverSettlement, method: str, operator_id: int | None) -> DriverSettlement:
    if s.status != SettlementStatus.CONFIRMED:
        raise ValueError("仅已确认结算单可付款")
    s.status = SettlementStatus.PAID
    s.paid_at = _now()
    s.method = method
    db.add(
        CashFlow(
            flow_date=(s.paid_at).date(),
            direction=CashFlowDirection.OUT,
            amount=s.amount,
            party_type="driver",
            party_id=s.driver_id,
            party_name="",
            channel=method,
            biz_type=CashFlowBizType.PAYMENT_DRIVER if s.settle_type == DriverBillType.PIECE else CashFlowBizType.PAYMENT_SALARY,
            doc_id=s.id,
            note=f"司机结算单 #{s.id}（{s.month}）",
            operator_id=operator_id,
        )
    )
    return s


def cancel_settlement(db: Session, s: DriverSettlement, operator_id: int | None) -> DriverSettlement:
    if s.status != SettlementStatus.DRAFT:
        raise ValueError("仅草稿可取消")
    s.status = SettlementStatus.CANCELLED
    if s.settle_type == DriverBillType.PIECE and s.order_ids:
        bills = list(
            db.scalars(
                select(DriverBill).where(
                    DriverBill.settled_doc_id == s.id,
                    DriverBill.status == DriverBillStatus.SETTLED,
                )
            )
        )
        for b in bills:
            b.status = DriverBillStatus.OPEN
            b.settled_doc_id = None
    return s


# ---------- ⑥ 开销单 ----------
def create_expense(db: Session, body: ExpenseCreate, operator_id: int | None) -> Expense:
    e = Expense(
        exp_date=body.exp_date,
        category=body.category,
        amount=body.amount,
        driver_id=body.driver_id,
        vehicle_id=body.vehicle_id,
        order_id=body.order_id,
        note=body.note,
        operator_id=operator_id,
    )
    db.add(e)
    db.flush()
    biz_map = {
        "fuel": CashFlowBizType.EXPENSE_FUEL,
        "repair": CashFlowBizType.EXPENSE_REPAIR,
        "toll": CashFlowBizType.EXPENSE_TOLL,
        "parking": CashFlowBizType.EXPENSE_PARKING,
        "fine": CashFlowBizType.EXPENSE_FINE,
        "insurance": CashFlowBizType.EXPENSE_INSURANCE,
        "loss": CashFlowBizType.EXPENSE_LOSS,
        "other": CashFlowBizType.EXPENSE_OTHER,
    }
    db.add(
        CashFlow(
            flow_date=body.exp_date,
            direction=CashFlowDirection.OUT,
            amount=body.amount,
            party_type="expense",
            party_id=e.id,
            party_name=body.category.value,
            channel="cash",
            biz_type=biz_map.get(body.category.value, CashFlowBizType.EXPENSE_OTHER),
            order_id=body.order_id,
            doc_id=e.id,
            note=body.note,
            operator_id=operator_id,
        )
    )
    return e
