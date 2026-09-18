"""账本 V2 统一账务钩子（单源事实）：送达→两支明细+货损；收款→逐单核销；结算单状态机；开销→资金流水。

约定（REV5 定稿）：
- 客户欠款 = Σledgers(含负向红冲) − Σcash_flows(IN, customer) + Σcash_flows(OUT, REFUND_CUSTOMER, customer)
- 司机未结 = Σdriver_bills(未作废) − Σcash_flows(OUT, driver) + Σcash_flows(IN, REFUND_DRIVER, driver)
- 货损（公司自担）：EXPENSE_LOSS（成本口径）+ ledgers 专用红冲行（amount=0、负成本快照冲回 COGS），客户/营业额零影响。
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
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
from app.services.driver_pay import (
    has_per_order_pay,
    pay_for_order,
    rule_from_snapshot,
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


# ---------- ① 送达：司机应付明细（幂等生成） ----------
def generate_piece_bill(db: Session, order: Order, operator_id: int | None = None) -> DriverBill | None:
    """订单送达且有"按单应付" → 生成/复用明细。幂等：order_id+bill_type 唯一。

    ### v3.36：金额不再等于运费
    以前这里是 `amount = order.freight_fee`（计件=全额运费）。现在司机可能挂着计费规则
    （每单固定 / 运费提成 / 商品金额提成 / 固定工资+提成），金额由 `driver_pay.pay_for_order`
    按**订单上的规则快照**算——一处实现，四处（这里、补单、结算页、司机绩效）共用。
    `rule=None`（没挂规则的存量司机）时它仍然返回全额运费，行为一字不变。

    ### 判据也从"用户表里的 billing_mode"换成了"订单快照"
    换成 `driver_pay.has_per_order_pay(order)` 之后，和结算页/补单用的口径**完全一致**：
    快照为空的老单按"有运费就算有应付"处理（以前这里对快照为空的单**不生成**账单，
    而结算页会把同一张单列进待结运费——同一张单两个页面说法不同）。
    """
    if order.status.value != "DELIVERED":
        return None
    if not has_per_order_pay(order):
        return None
    rule = rule_from_snapshot(getattr(order, "driver_rule_snapshot", None))
    pay = pay_for_order(order)
    if pay.total <= 0:
        return None
    existing = db.scalars(
        select(DriverBill).where(
            DriverBill.order_id == order.id,
            DriverBill.bill_type == DriverBillType.PIECE,
        )
    ).first()
    if existing is not None:
        return existing
    # 账单要能**独立**说清"当时按什么算的"：规则名 + 两件金额 + 文字明细都落库。
    # 只留一个裸金额的话，月底对账时没人能复核这个数是怎么来的（改造前的既有缺陷）。
    detail = f"规则「{rule.name}」：" if rule is not None else ""
    bill = DriverBill(
        driver_id=order.driver_id or 0,
        bill_type=DriverBillType.PIECE,
        order_id=order.id,
        month=_month_of(order.delivered_at),
        amount=pay.total,
        status=DriverBillStatus.OPEN,
        note=(detail + _pay_note(pay, rule))[:250] if rule is not None else "订单送达自动生成（运费全额）",
        rule_id=rule.rule_id if rule is not None else None,
        rule_name=rule.name if rule is not None else "",
        piece_amount=pay.piece if rule is not None else None,
        commission_amount=pay.commission if rule is not None else None,
    )
    db.add(bill)
    return bill


def _pay_note(pay, rule) -> str:
    """账单上那行"怎么算出来的"（例：`每单 300.00 + 运费 1000.00 的 8% = 80.00`）。

    ⚠️ 比例必须用 `pay.rate_used`（**这一次实际用的**），不能用 `rule.commission_rate`：
    派单员可以对这一单单独定比例，用规则里的默认值会印出一句**算术上不成立**的话
    （真机 E2E 抓到过：运费 1000 的 5.00% = 80.00，而 5% 其实是 50）——
    账单是钱，说明里出现算不通的数字，等于这张账单没法复核。
    """
    parts: list[str] = []
    if pay.piece > 0:
        cn = "每件" if getattr(rule, "piece_unit", "order") == "item" else "每单"
        mark = "（这一单单独定的）" if getattr(pay, "piece_overridden", False) else ""
        parts.append(f"{cn} {pay.piece}{mark}")
    if pay.commission > 0:
        base_cn = {"freight": "运费", "goods": "商品金额"}.get(getattr(rule, "commission_base", ""), "基数")
        rate = getattr(pay, "rate_used", None) or getattr(rule, "commission_rate", 0)
        mark = "（这一单单独定的）" if getattr(pay, "rate_overridden", False) else ""
        parts.append(f"{base_cn} {pay.basis} 的 {rate}%{mark} = {pay.commission}")
    parts.append(f"合计 {pay.total}")
    return " + ".join(parts)


# ---------- ② 送达：货损（公司自担）记账 ----------
def apply_damage_accounting(db: Session, order: Order, operator_id: int | None = None) -> list[str]:
    """商品行级货损 → ①EXPENSE_LOSS(成本×数量) ②ledgers 专用红冲行(amount=0, 负成本快照)。
    货损成本=该行 cost_price_snapshot×damage_quantity；客户欠款/营业额零影响（客户全额付款）。

    ### 返回值 = 必须让人看到的"没记成"清单（不要把司机报的货损抹掉）
    以前没有成本快照时这里会把 `damage_quantity` **置回 0**（注释写"提示在接口层"，
    而接口层从来没有提示）——后果是司机在送达界面填的货损**凭空消失**：
    接口返回成功、订单上货损变成 0、也没有任何地方提示过。
    现在：**保留司机填的数量**，只是"这笔成本没进账"，并把这个事实作为返回值的
    一句话交出去（调用方写进操作日志，报表中心的「异常与审计」看得到）。
    """
    warnings: list[str] = []
    for op in order.order_products:
        qty = op.damage_quantity or 0
        if qty <= 0:
            continue
        cost = op.cost_price_snapshot or Decimal("0")
        cost_amt = (cost * Decimal(qty)).quantize(Decimal("0.01"))
        if cost_amt <= 0:
            # 数量**留着**（那是司机报的事实），只是没有成本价就算不出损失金额
            warnings.append(
                f"{order.order_no} 的「{op.product_name_snapshot}」报了货损 {qty} 件，"
                f"但这个商品没有成本价快照，损失金额按 0 计、没有进开销账。"
                f"要按成本计损失，请在「商品管理」里补上成本价（只对之后新下的单生效）。"
            )
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
    return warnings


# ---------- ③ 送达：总钩子（先 bill 后货损） ----------
def post_delivery_accounting(db: Session, order: Order, operator_id: int | None = None) -> list[str]:
    """送达之后的两件事，返回**"没记成"清单**（见 [apply_damage_accounting]）。"""
    generate_piece_bill(db, order, operator_id)
    return apply_damage_accounting(db, order, operator_id)


# ---------- ④ 客户收款单：逐单核销 ----------
def create_receipt(db: Session, body: ShipperReceiptCreate, operator_id: int | None) -> ShipperReceipt:
    cust = db.get(Customer, body.customer_id)
    if cust is None:
        raise ValueError("客户档案不存在")
    per_order: dict[int, Decimal] = {}
    if body.settle_mode == ReceiptSettleMode.ITEMIZED:
        if not body.order_ids:
            raise ValueError("逐单核销需绑定订单")
        total = Decimal("0")
        # ⚠️ 逐单核销是"读 paid → 判断 → 写"，中间没有锁：两个请求同时核销同一张单会**都读到
        #    paid=False**，于是两条收款记录、两条现金流水（钱多记一笔）。
        #    `with_for_update()` = MySQL 上的行锁（第二个请求等第一个提交后再读，就读到 paid=True 了）；
        #    SQLite **不支持行锁**（SQLAlchemy 直接忽略）——2026-09-18 探针在本机实测复现了
        #    「两个请求都 200、同一张单两条收款记录」（`_tools/qa/_probe_core_flows.py` 的并发组）。
        #    所以下面还有一道**条件 UPDATE 占位**（作业同 `order_flow` 的状态跃迁）：
        #    把 paid=false → true 这一步变成"改到行的人才能继续"，两种数据库上都原子。
        ids = sorted({int(x) for x in body.order_ids})
        locked = {
            o.id: o
            for o in db.scalars(select(Order).where(Order.id.in_(ids)).with_for_update())
        }
        for oid in ids:
            o = locked.get(oid)
            if o is None:
                raise ValueError(f"订单 {oid} 不存在")
            if o.shipper_id is None:
                raise ValueError(f"订单 {oid} 无客户归属（临时货主收款需先关联客户档案）")
            if o.shipper_id != cust.user_id:
                raise ValueError(f"订单 {oid} 不属于该客户")
            # ⚠️ 已经收过款的单不能再逐单核销一次（v3.39 探针实测：原来可以，
            #    于是同一张单出现两条收款记录、两条现金流水——账上多出一笔没收到的钱）。
            #    "逐单核销"的语义就是"这张单的钱收齐了"（下面那句 amount 必须等于合计），
            #    所以第二次必然是多记。补差额请改用「滚动收款」（绑定不了单的那种）。
            if o.paid:
                how = {
                    "cash": "司机送达时收的现金",
                    "arrears": "已挂账结清",
                }.get((o.payment_method or "").lower(), "之前已经核销过")
                raise ValueError(
                    f"订单 {o.order_no} 已经收过款了（{how}），逐单核销不能重复收款。"
                    "如果是补差额，请改用「滚动收款」。"
                )
            line_total = sum((op.line_total or Decimal("0")) for op in o.order_products)
            per_order[oid] = line_total
            total += line_total
        if Decimal(body.amount) != total:
            raise ValueError(f"收款金额 {body.amount} 与所选订单合计 {total} 不一致（逐单核销需全额）")
        # 原子占位：只有把 paid 从 false 改成 true 的那个请求能继续（另一个 rowcount 会少）
        claimed = db.execute(
            update(Order)
            .where(Order.id.in_(ids), Order.paid.is_(False))
            .values(
                paid=True,
                payment_method="cash" if body.method in ("cash", "transfer", "wechat") else "arrears",
            )
        )
        if claimed.rowcount != len(ids):
            db.rollback()
            raise ValueError("这些订单里有刚刚被别的收款记录核销掉的，请刷新订单后重试")
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
            # ⚠️ `paid` 已经在上面**用条件 UPDATE 占位**写过了（那是原子性的来源）。
            #    这里只兜**滚动收款**那条路（它不绑单、没有占位），逐单核销时
            #    这一句是幂等的重复赋值（值一样），不会覆盖上面的判定。
            if body.settle_mode != ReceiptSettleMode.ITEMIZED:
                o.paid = True
                o.payment_method = "cash" if body.method in ("cash", "transfer", "wechat") else "arrears"
        db.add(
            CashFlow(
                flow_date=body.received_at,
                direction=CashFlowDirection.IN,
                # ⚠️ 这里**必须**逐单写金额，不能写 None。
                #
                # `cash_flows.amount` 是 NOT NULL（`models/cash_flow.py`：`Mapped[Decimal]`），
                # 以前多张单的逐单核销写的是 `None`，于是**收款直接 500**
                # （IntegrityError），钱一分都没落库——而界面上只说"收款失败"。
                #
                # 拆成"每张单各自那部分"也是**语义上对的**：逐单核销本来就是
                # "这笔钱分摊到这几张单上"，每条流水写自己那一份，
                # 合计等于收款总额（`reports.py` 的资金收支就是按流水逐条求和的）。
                amount=per_order.get(oid) if per_order else body.amount,
                party_type="customer",
                party_id=cust.id,
                party_name=cust.name,
                channel="wechat" if body.method == "wechat" else ("bank" if body.method == "transfer" else "cash"),
                biz_type=biz,
                order_id=oid,
                doc_id=receipt.id,
                note=f"客户收款（逐单核销，收款单 #{receipt.id}）",
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
    # ⚠️ 付款前**再看一眼明细还在不在**（2026-09-18 补，缺陷挖掘的产物）。
    #
    # 确认时已经查过一次，为什么付款还要查：确认与付款是**两次点击**，中间可能隔很久，
    # 而明细行本身可以被别的路径删掉（订单硬删、清理脚本、以后的数据保留策略）。
    # 明细一旦没了，这张单就变成"付出去一笔钱、账上没有任何对应的应付款"——
    # 月底没人能复核这笔钱付的是什么。库里真的出现过这种单：
    # 1 张 352 元的已付结算单、0 条明细（探针见 `_tools/qa/_probe_settlement_orphan.py`）。
    # 钱付出去就撤不回来，所以这道检查必须紧贴付款那一刻，而不是只在确认时查。
    live = list(db.scalars(select(DriverBill).where(DriverBill.settled_doc_id == s.id)))
    if not live:
        raise ValueError("这张结算单已经没有任何明细（明细被删除或解绑），不能付款；请作废后重新结算")
    if any(b.status != DriverBillStatus.SETTLED or b.driver_id != s.driver_id for b in live):
        raise ValueError("这张结算单的明细状态与司机对不上（被别的操作改过），不能付款；请作废后重新结算")
    live_total = sum((b.amount for b in live), Decimal("0"))
    if Decimal(s.amount) != live_total:
        raise ValueError(
            f"结算单金额 {s.amount} 与现存明细合计 {live_total} 不一致，不能付款；请作废后重新结算"
        )
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
