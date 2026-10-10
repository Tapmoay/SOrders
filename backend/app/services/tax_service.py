"""发票台账与税汇（FEAT-0014 税账，2026-10-04 五期计划第四期）。

## 这个文件是「税」的唯一落点

在这之前全库没有一个「税」的数据源：利润表的 `tax_total` 恒为 0
（`services/reports/profit_query.py` 里原来的 `tax_total = _ZERO`），
而唯一带 invoice 字样的列是 `shipper_receipts.invoiced`（一个布尔，没有落点）。
本文件 + `models/invoice.py` 把一张票变成事实：方向 / 票号 / 日期 / 价税合计 / 税率 / 税额，
以及它挂在哪些业务单据上。

## 三条口径（判据 `_tools/qa/_check_tax_invoices.py` 与 `backend/tests/test_tax_invoices.py` 两边都钉）

1. **税额只有一个算法**：`tax_of_amount(amount, rate) = amount − amount / (1 + rate/100)`，
   四舍五入到分（ROUND_HALF_UP）。⛔ 别处不许再写一遍这个除法（判据在源码里钉唯一实现）。
   人手填了 `tax_amount` 就按人手填的算（票面税额与算出来的差一分钱的现实存在）。
2. **参加税汇的判据只有一处**：`counts_in_tax()` = 活着（没进回收站）+ 没作废 +
   `tax_rate IS NOT NULL`。`tax_rate = 0.00`（零税率）**进**税汇但税额恒 0；
   `tax_rate IS NULL`（未税，如收据）不进税汇，单列在 `untaxed_*` 里。
3. **钱一律到分**：入参已经在 schema 层被 `MoneyInput` 管住上界，这里只做
   `yuan()` 到分与税额的减法 —— ⛔ 不用 float，⛔ 不四舍五入两次（先算到分再减）。

## 两种「不算数」

`status = VOIDED`（作废·冲红）与 `is_deleted`（回收站）都退出税汇，但**都保留原样**：
作废的票留在列表里（界面变灰）、回收站里的票走 `POST /invoices/{id}/restore` 原样放回。
恢复时如果票号已经被别人用了，**如实报冲突**（`409`），⛔ 不悄悄改号。
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Sequence

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.models.customer import Customer
from app.models.enums import InvoiceDirection, InvoiceStatus, OperationAction
from app.models.invoice import Invoice, InvoiceLedger, InvoicePurchaseOrder
from app.models.ledger import Ledger
from app.models.purchase import PurchaseOrder
from app.models.supplier import Supplier
from app.services.operation_log_service import write_log
from app.services.soft_delete import ensure_alive

#: 默认税率：小规模纳税人一档 3.00%（一票一改）。
#  ⛔ 本期**不做**多档税率表 / 配置页（全库没有配置表，见 FEAT-0014 的 Known Limitations）：
#     要改默认值就是改这一行。现行 1% 减征在单张发票上改税率即可。
DEFAULT_TAX_RATE = Decimal("3.00")

#: 方向与状态的字符串值（库里存字符串，⛔ 不存 Enum 列，跟随 purchase_orders 的做法）
OUTPUT = InvoiceDirection.OUTPUT.value
INPUT = InvoiceDirection.INPUT.value
REGISTERED = InvoiceStatus.REGISTERED.value
ISSUED = InvoiceStatus.ISSUED.value
VOIDED = InvoiceStatus.VOIDED.value

_CENT = Decimal("0.01")
_NO_WIDTH = 64
_NOTE_WIDTH = 256


def yuan(value: Any) -> Decimal:
    """到分（ROUND_HALF_UP）。金额列是 `Numeric(12,2)`，⛔ 不把多余的小数位带进库。"""
    try:
        num = Decimal(str(value if value is not None else 0))
    except Exception:  # pragma: no cover - Decimal(str()) 对数字不会失败
        num = Decimal(0)
    return num.quantize(_CENT, rounding=ROUND_HALF_UP)


def tax_of_amount(amount: Any, rate: Any | None) -> Decimal | None:
    """由**价税合计**与税率算税额：`amount − amount/(1+rate/100)`，到分。

    `rate is None`（未税票）⇒ 返回 `None`（税额与税率同生同灭）。
    这是全库**唯一**的税额算法：别的文件要税额就调它，⛔ 不许重写这个除法。
    """
    if rate is None:
        return None
    total = yuan(amount)
    r = Decimal(str(rate)) / Decimal(100)
    net = total / (Decimal(1) + r)
    return yuan(total - net)


def net_of(amount: Any, tax_amount: Any | None) -> Decimal:
    """不含税金额 = 价税合计 − 税额（税额可能是人手覆盖的，⛔ 不拿税率反推）。"""
    return yuan(yuan(amount) - yuan(tax_amount or 0))


def _no_key(no: str | None) -> str | None:
    """票号的唯一键：非空 = 票号本身，空 = `None`（唯一索引里的多个 NULL 不算冲突）。"""
    text = str(no or "").strip()
    return text or None


def counts_in_tax(invoice: Invoice) -> bool:
    """这一张票算不算进税汇 —— **税汇口径的唯一判据**。"""
    if getattr(invoice, "is_deleted", False):
        return False
    if str(invoice.status or "") == VOIDED:
        return False
    return invoice.tax_rate is not None


def direction_name(direction: str | None) -> str:
    """给界面 / 报错用的中文方向名。"""
    return "销项" if str(direction or "") == OUTPUT else "进项"


# ---------------------------------------------------------------- 读


def get_invoice_or_404(db: Session, invoice_id: int) -> Invoice:
    row = db.get(Invoice, invoice_id)
    if row is None:
        raise HTTPException(status_code=404, detail="这张发票不存在（可能已经被彻底删除了）。")
    return row


def party_names(db: Session, invoices: Sequence[Invoice]) -> tuple[dict[int, str], dict[int, str]]:
    """一次把供应商名与客户名查出来（列表每行都要显示是谁开的票 / 开给谁）。"""
    sup_ids = {i.supplier_id for i in invoices if i.supplier_id}
    cus_ids = {i.customer_id for i in invoices if i.customer_id}
    sups = (
        {row.id: (row.name or "") for row in db.scalars(select(Supplier).where(Supplier.id.in_(sup_ids)))}
        if sup_ids
        else {}
    )
    cus = (
        {row.id: (row.name or "") for row in db.scalars(select(Customer).where(Customer.id.in_(cus_ids)))}
        if cus_ids
        else {}
    )
    return sups, cus


def brief(
    invoice: Invoice,
    *,
    sups: dict[int, str] | None = None,
    cus: dict[int, str] | None = None,
) -> dict[str, Any]:
    """列表 / 详情共用的一份值（金额格式化在端点层做，这里给 Decimal）。"""
    return {
        "id": invoice.id,
        "direction": invoice.direction,
        "invoice_no": invoice.invoice_no or "",
        "invoice_date": invoice.invoice_date,
        "amount": yuan(invoice.amount),
        "tax_rate": invoice.tax_rate,
        "tax_amount": invoice.tax_amount,
        "status": invoice.status,
        "supplier_id": invoice.supplier_id,
        "supplier_name": (sups or {}).get(invoice.supplier_id, "") or "",
        "customer_id": invoice.customer_id,
        "customer_name": (cus or {}).get(invoice.customer_id, "") or "",
        "note": invoice.note or "",
        "counts_in_tax": counts_in_tax(invoice),
        "purchase_order_ids": [row.purchase_order_id for row in invoice.purchase_orders],
        "ledger_ids": [row.ledger_id for row in invoice.ledgers],
        "is_deleted": bool(invoice.is_deleted),
        "created_at": invoice.created_at.strftime("%Y-%m-%d %H:%M") if invoice.created_at else "",
    }


def invoice_query(
    *,
    direction: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    supplier_id: int | None = None,
    customer_id: int | None = None,
    include_deleted: bool = False,
    keyword: str | None = None,
):
    """列表的**筛选与排序**（默认只给活着的票；回收站要看就显式要），新的在前面。

    ⚠️ 这里**不带 limit / offset**：分页那一步（含「多取一行」）由调用方在最外层做 ——
       API 层写 `.limit(limit + 1)`（判据 `_tools/qa/_check_pagination_wiring.py` 要看见那一行），
       而 `list_invoices()` 是给服务内部（税汇、探针）用的便捷包装。
    """
    stmt = select(Invoice)
    if not include_deleted:
        stmt = stmt.where(Invoice.is_deleted.is_(False))
    if direction:
        stmt = stmt.where(Invoice.direction == direction)
    if status:
        stmt = stmt.where(Invoice.status == status)
    if date_from is not None:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    if supplier_id is not None:
        stmt = stmt.where(Invoice.supplier_id == supplier_id)
    if customer_id is not None:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    text = str(keyword or "").strip()
    if text:
        stmt = stmt.where(Invoice.invoice_no.like(f"%{text}%"))
    return stmt.order_by(Invoice.invoice_date.desc(), Invoice.id.desc())


def list_invoices(
    db: Session,
    *,
    direction: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    supplier_id: int | None = None,
    customer_id: int | None = None,
    include_deleted: bool = False,
    keyword: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Invoice]:
    """列表（筛 + 排序 + 可选分页）。分页规矩见 `invoice_query` 的说明。"""
    stmt = invoice_query(
        direction=direction,
        status=status,
        date_from=date_from,
        date_to=date_to,
        supplier_id=supplier_id,
        customer_id=customer_id,
        include_deleted=include_deleted,
        keyword=keyword,
    )
    if offset:
        stmt = stmt.offset(int(offset))
    if limit is not None:
        stmt = stmt.limit(int(limit))
    return list(db.scalars(stmt).all())


def _snapshot(invoice: Invoice) -> dict[str, Any]:
    """写进操作日志的「这一刻这张票长什么样」。"""
    return {
        "id": invoice.id,
        "direction": invoice.direction,
        "invoice_no": invoice.invoice_no or "",
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "amount": str(yuan(invoice.amount)),
        "tax_rate": str(invoice.tax_rate) if invoice.tax_rate is not None else None,
        "tax_amount": str(yuan(invoice.tax_amount)) if invoice.tax_amount is not None else None,
        "status": invoice.status,
        "supplier_id": invoice.supplier_id,
        "customer_id": invoice.customer_id,
        "note": invoice.note or "",
        "purchase_order_ids": [row.purchase_order_id for row in invoice.purchase_orders],
        "ledger_ids": [row.ledger_id for row in invoice.ledgers],
        "is_deleted": bool(invoice.is_deleted),
    }


# ---------------------------------------------------------------- 校验


def _clean_ids(ids: Iterable[Any] | None) -> list[int]:
    """去重保序（同一个 id 给两遍不该变成两条连线 —— 库里有唯一约束，这里先挡一次）。"""
    out: list[int] = []
    for raw in ids or []:
        try:
            num = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(400, detail=f"单据编号要是数字，收到的不是数字：{raw!r}。")
        if num not in out:
            out.append(num)
    return out


def _check_no_duplicate(
    db: Session, *, direction: str, no_key: str | None, exclude_id: int | None = None
) -> None:
    """同一方向 + 同一票号只能有一张票（空票号不算 —— 月结代开时先登记、后补号）。

    ⚠️ **回收站里的票仍然占着号**：唯一索引就是 `(direction, no_key)` 两列（空号走 `no_key IS NULL`
    不进唯一），软删不清号。所以这里 ⛔ 不筛 `is_deleted` —— 筛了它，「删一张票之后再登记同一个号」
    就会一头撞上数据库的 IntegrityError（500 而不是一句人话），而那种情况本来就是同一张票登记了两遍。
    """
    if no_key is None:
        return
    stmt = select(Invoice.id, Invoice.is_deleted).where(
        Invoice.direction == direction,
        Invoice.no_key == no_key,
    )
    if exclude_id is not None:
        stmt = stmt.where(Invoice.id != exclude_id)
    hit = db.execute(stmt).first()
    if hit is None:
        return
    extra = (
        "（那张票现在在回收站里 —— 先把它恢复出来，而不是把同一张票再登记一遍。）"
        if hit[1]
        else ""
    )
    raise HTTPException(
        status_code=409,
        detail=(
            f"{direction_name(direction)}票号「{no_key}」已经登记过一张票了。"
            f"同一个票号只能登记一次；号写错了请改成正确的票号。{extra}"
        ),
    )


def _load_purchase_orders(db: Session, ids: list[int]) -> list[PurchaseOrder]:
    if not ids:
        return []
    rows = {row.id: row for row in db.scalars(select(PurchaseOrder).where(PurchaseOrder.id.in_(ids)))}
    missing = [i for i in ids if i not in rows]
    if missing:
        raise HTTPException(400, detail=f"这些采购单不存在：{missing}（编号对不对？）")
    for row in rows.values():
        ensure_alive(row, "采购单", f"先去采购单回收站把 #{row.id} 恢复出来，再挂到这张票上。")
    return [rows[i] for i in ids]


def _load_ledgers(db: Session, ids: list[int]) -> list[Ledger]:
    if not ids:
        return []
    rows = {row.id: row for row in db.scalars(select(Ledger).where(Ledger.id.in_(ids)))}
    missing = [i for i in ids if i not in rows]
    if missing:
        raise HTTPException(400, detail=f"这些账本条目不存在：{missing}（编号对不对？）")
    for row in rows.values():
        if row.customer_id is None:
            raise HTTPException(
                400,
                detail=(
                    f"账本第 #{row.id} 行没有客户档案（历史行按名称兜底），挂不到销项票上。"
                    "先在账本里给它补上客户，再回来开票。"
                ),
            )
    return [rows[i] for i in ids]


def _check_links(
    db: Session,
    *,
    direction: str,
    supplier_id: int | None,
    customer_id: int | None,
    po_ids: list[int],
    ledger_ids: list[int],
) -> tuple[list[PurchaseOrder], list[Ledger]]:
    """进项 / 销项各自的挂单规矩（行为契约里那几条失败路径就落在这里）。"""
    if direction == INPUT:
        if not supplier_id:
            raise HTTPException(400, detail="进项票要写清是哪个供应商开的（supplier_id）。")
        if not po_ids:
            raise HTTPException(
                400,
                detail=(
                    "进项票必须挂至少一张采购单 —— 不然答不出「这批货有没有票」。"
                    "先在采购单里建这张进货单，再回来登记票。"
                ),
            )
        if customer_id:
            raise HTTPException(400, detail="进项票是供应商开给我们的，不该填客户。")
        if ledger_ids:
            raise HTTPException(400, detail="进项票挂的是采购单，不该挂账本条目。")
        orders = _load_purchase_orders(db, po_ids)
        for row in orders:
            if row.supplier_id != int(supplier_id):
                raise HTTPException(
                    400,
                    detail=(
                        f"第 #{row.id} 张采购单的供应商与这张票的供应商不是同一家 —— "
                        "一张进项票只能抵同一家供应商的货。"
                    ),
                )
        return orders, []
    if direction == OUTPUT:
        if not customer_id:
            raise HTTPException(400, detail="销项票要写清开给哪个客户（customer_id）。")
        if supplier_id:
            raise HTTPException(400, detail="销项票是我们开给客户的，不该填供应商。")
        if po_ids:
            raise HTTPException(400, detail="销项票挂的是客户应收（账本条目），不该挂采购单。")
        ledgers = _load_ledgers(db, ledger_ids)
        for row in ledgers:
            if row.customer_id != int(customer_id):
                raise HTTPException(
                    400,
                    detail=(
                        f"账本第 #{row.id} 行的客户与这张票的客户不是同一个 —— "
                        "一张销项票只能开给同一个客户。"
                    ),
                )
        return [], ledgers
    raise HTTPException(400, detail="发票方向只能是销项（OUTPUT）或进项（INPUT）。")


def _tax_pair(
    amount: Any, tax_rate: Any | None, tax_amount: Any | None
) -> tuple[Decimal | None, Decimal | None]:
    """把（价税合计, 税率, 税额）收成一对自洽的值（税率与税额同生同灭）。"""
    if tax_rate is None:
        if tax_amount is not None:
            raise HTTPException(
                400,
                detail="没填税率的票不该有税额 —— 要么把税率填上，要么把税额清空（未税票不进税汇）。",
            )
        return None, None
    rate = Decimal(str(tax_rate)).quantize(_CENT, rounding=ROUND_HALF_UP)
    if rate < 0 or rate > 100:
        raise HTTPException(400, detail="税率是百分数（3.00 = 3%），只能在 0 到 100 之间。")
    if tax_amount is None:
        return rate, tax_of_amount(amount, rate)
    tax = yuan(tax_amount)
    if tax > yuan(amount):
        raise HTTPException(400, detail="税额不能大于价税合计 —— 这两个数是不是填反了？")
    return rate, tax


def _sync_links(
    db: Session,
    invoice: Invoice,
    *,
    orders: list[PurchaseOrder] | None,
    ledgers: list[Ledger] | None,
) -> None:
    """把这张票挂的单据摆成给定的样子（`None` = 这一边不动）。"""
    if orders is not None:
        want = [row.id for row in orders]
        for link in list(invoice.purchase_orders):
            if link.purchase_order_id not in want:
                db.delete(link)
        db.flush()
        have = {link.purchase_order_id for link in invoice.purchase_orders}
        for pid in want:
            if pid not in have:
                invoice.purchase_orders.append(InvoicePurchaseOrder(purchase_order_id=pid))
    if ledgers is not None:
        want_l = [row.id for row in ledgers]
        for link in list(invoice.ledgers):
            if link.ledger_id not in want_l:
                db.delete(link)
        db.flush()
        have_l = {link.ledger_id for link in invoice.ledgers}
        for lid in want_l:
            if lid not in have_l:
                invoice.ledgers.append(InvoiceLedger(ledger_id=lid))


# ---------------------------------------------------------------- 写


def create_invoice(
    db: Session,
    *,
    direction: str,
    invoice_no: str | None,
    invoice_date: date,
    amount: Any,
    tax_rate: Any | None,
    tax_amount: Any | None,
    supplier_id: int | None,
    customer_id: int | None,
    purchase_order_ids: Iterable[Any] | None,
    ledger_ids: Iterable[Any] | None,
    note: str | None,
    operator_id: int | None,
) -> Invoice:
    """登记一张票（状态 REGISTERED）。挂单规矩见 `_check_links`。"""
    dir_value = str(direction or "").strip().upper()
    if dir_value not in (OUTPUT, INPUT):
        raise HTTPException(400, detail="发票方向只能是销项（OUTPUT）或进项（INPUT）。")
    no = str(invoice_no or "").strip()[:_NO_WIDTH]
    key = _no_key(no)
    _check_no_duplicate(db, direction=dir_value, no_key=key)
    orders, ledgers = _check_links(
        db,
        direction=dir_value,
        supplier_id=supplier_id,
        customer_id=customer_id,
        po_ids=_clean_ids(purchase_order_ids),
        ledger_ids=_clean_ids(ledger_ids),
    )
    rate, tax = _tax_pair(amount, tax_rate, tax_amount)
    invoice = Invoice(
        direction=dir_value,
        invoice_no=no,
        no_key=key,
        invoice_date=invoice_date,
        amount=yuan(amount),
        tax_rate=rate,
        tax_amount=tax,
        supplier_id=int(supplier_id) if supplier_id else None,
        customer_id=int(customer_id) if customer_id else None,
        status=REGISTERED,
        note=str(note or "").strip()[:_NOTE_WIDTH],
        operator_id=operator_id,
    )
    db.add(invoice)
    db.flush()
    _sync_links(db, invoice, orders=orders, ledgers=ledgers)
    write_log(
        db,
        operator_id=operator_id,
        order_id=None,
        action=OperationAction.TAX_INVOICE_CREATE,
        change_payload=_snapshot(invoice),
    )
    db.commit()
    db.refresh(invoice)
    return invoice


def update_invoice(
    db: Session,
    invoice: Invoice,
    *,
    changes: dict[str, Any],
    operator_id: int | None,
) -> Invoice:
    """改一张票：只有 **REGISTERED** 状态能改（已开具 / 已作废的票一个字都不动）。"""
    ensure_alive(invoice, "发票", f"POST /invoices/{invoice.id}/restore")
    if str(invoice.status or "") != REGISTERED:
        raise HTTPException(
            400,
            detail=(
                f"这张票已经是「{'已作废' if invoice.status == VOIDED else '已开具'}」了，改不动。"
                "只有「已登记」状态的票能改；要改就作废重开一张。"
            ),
        )
    before = _snapshot(invoice)
    data = dict(changes or {})
    if "invoice_no" in data:
        no = str(data.get("invoice_no") or "").strip()[:_NO_WIDTH]
        key = _no_key(no)
        _check_no_duplicate(db, direction=invoice.direction, no_key=key, exclude_id=invoice.id)
        invoice.invoice_no = no
        invoice.no_key = key
    if data.get("invoice_date") is not None:
        invoice.invoice_date = data["invoice_date"]
    if "note" in data:
        invoice.note = str(data.get("note") or "").strip()[:_NOTE_WIDTH]
    amount = yuan(data["amount"]) if data.get("amount") is not None else yuan(invoice.amount)
    rate = data["tax_rate"] if "tax_rate" in data else invoice.tax_rate
    if "tax_rate" in data and data["tax_rate"] is None and "tax_amount" not in data:
        tax_in = None                      # 改成未税票：税额跟着清掉
    elif "tax_amount" in data:
        tax_in = data["tax_amount"]
    elif "amount" in data and data.get("amount") is not None and rate is not None:
        tax_in = None                      # 只改了合计：税额按税率重算
    else:
        tax_in = invoice.tax_amount
    supplier_id = data.get("supplier_id", invoice.supplier_id)
    customer_id = data.get("customer_id", invoice.customer_id)
    po_ids = _clean_ids(data["purchase_order_ids"]) if "purchase_order_ids" in data else None
    ledger_ids = _clean_ids(data["ledger_ids"]) if "ledger_ids" in data else None
    orders, ledgers = _check_links(
        db,
        direction=invoice.direction,
        supplier_id=supplier_id,
        customer_id=customer_id,
        po_ids=po_ids if po_ids is not None else [link.purchase_order_id for link in invoice.purchase_orders],
        ledger_ids=ledger_ids if ledger_ids is not None else [link.ledger_id for link in invoice.ledgers],
    )
    rate, tax = _tax_pair(amount, rate, tax_in)
    invoice.amount = amount
    invoice.tax_rate = rate
    invoice.tax_amount = tax
    if supplier_id is not None:
        invoice.supplier_id = int(supplier_id)
    if customer_id is not None:
        invoice.customer_id = int(customer_id)
    _sync_links(db, invoice, orders=orders, ledgers=ledgers)
    write_log(
        db,
        operator_id=operator_id,
        order_id=None,
        action=OperationAction.TAX_INVOICE_UPDATE,
        change_payload={"before": before, "after": _snapshot(invoice)},
    )
    db.commit()
    db.refresh(invoice)
    return invoice


def issue_invoice(db: Session, invoice: Invoice, *, operator_id: int | None) -> Invoice:
    """开具：REGISTERED → ISSUED。开具之后改不动（要改就作废重开）。"""
    ensure_alive(invoice, "发票", f"POST /invoices/{invoice.id}/restore")
    if str(invoice.status or "") == ISSUED:
        raise HTTPException(400, detail="这张票已经开具过了。")
    if str(invoice.status or "") == VOIDED:
        raise HTTPException(400, detail="这张票已经作废了，作废的票不能再开具；要重开就新登记一张。")
    invoice.status = ISSUED
    write_log(
        db,
        operator_id=operator_id,
        order_id=None,
        action=OperationAction.TAX_INVOICE_ISSUE,
        change_payload=_snapshot(invoice),
    )
    # FEAT-0021：开票成功 → 给派单端一条 info（同一张票只一条；与状态改动同一个事务）。
    from app.services import message_producers

    message_producers.notify_invoice_issued(db, invoice=invoice, operator_id=operator_id)
    db.commit()
    db.refresh(invoice)
    return invoice


def void_invoice(db: Session, invoice: Invoice, *, operator_id: int | None) -> Invoice:
    """作废·冲红：REGISTERED / ISSUED → VOIDED。**行留着**（票号不释放，历史查得到）。"""
    ensure_alive(invoice, "发票", f"POST /invoices/{invoice.id}/restore")
    if str(invoice.status or "") == VOIDED:
        raise HTTPException(400, detail="这张票已经作废过了。")
    before = str(invoice.status or "")
    invoice.status = VOIDED
    write_log(
        db,
        operator_id=operator_id,
        order_id=None,
        action=OperationAction.TAX_INVOICE_VOID,
        change_payload={"status_before": before, "after": _snapshot(invoice)},
    )
    db.commit()
    db.refresh(invoice)
    return invoice


def soft_delete_invoice(db: Session, invoice: Invoice, *, operator_id: int | None) -> None:
    """进回收站：票从税汇里退出（`counts_in_tax` 立刻为假），但原样留着可恢复。"""
    ensure_alive(invoice, "发票", f"POST /invoices/{invoice.id}/restore")
    before = _snapshot(invoice)
    invoice.is_deleted = True
    invoice.deleted_at = utc_now_naive()
    write_log(
        db,
        operator_id=operator_id,
        order_id=None,
        action=OperationAction.TAX_INVOICE_DELETE,
        change_payload={"before": before, "after": _snapshot(invoice)},
    )
    db.commit()


def restore_invoice(db: Session, invoice: Invoice, *, operator_id: int | None) -> Invoice:
    """从回收站恢复。

    ⚠️ 恢复**不会**与别人撞号：票号唯一性是数据库级的 `(direction, no_key)` 唯一索引，回收站里的
    行也占着号 —— 那个号一直是这一行的。下面这道查重是一层**防御**：真撞上了说明索引不再成立
    （有人绕过服务层改了号），那时如实报 409 也比悄悄替用户改号好。
    """
    if not invoice.is_deleted:
        raise HTTPException(400, detail="这张票不在回收站里，不需要恢复。")
    _check_no_duplicate(db, direction=invoice.direction, no_key=invoice.no_key, exclude_id=invoice.id)
    invoice.is_deleted = False
    invoice.deleted_at = None
    write_log(
        db,
        operator_id=operator_id,
        order_id=None,
        action=OperationAction.TAX_INVOICE_RESTORE,
        change_payload=_snapshot(invoice),
    )
    db.commit()
    db.refresh(invoice)
    return invoice


# ---------------------------------------------------------------- 税汇


def _empty_side() -> dict[str, Any]:
    return {
        "count": 0,
        "amount": Decimal("0.00"),
        "net_amount": Decimal("0.00"),
        "tax_amount": Decimal("0.00"),
        "untaxed_count": 0,
        "untaxed_amount": Decimal("0.00"),
    }


def sum_taxes(db: Session, start: date, end: date) -> dict[str, Any]:
    """一段窗口的销项 / 进项（**税汇口径的唯一实现**，报表与利润表都走它）。

    - 窗口按 `invoice_date`（**开票日期**），⛔ 不按 created_at：今天补录上个月的票要落在上个月。
    - `VOIDED` 与回收站里的票不算数，但**计数**（`voided_count`）如实给出来。
    - `tax_rate IS NULL` 的票进 `untaxed_*`（不进 `tax_amount`），一眼看得出「还有票没税率」。
    """
    rows = list(
        db.scalars(
            select(Invoice).where(
                Invoice.invoice_date >= start,
                Invoice.invoice_date <= end,
                Invoice.is_deleted.is_(False),
            )
        ).all()
    )
    sides = {OUTPUT: _empty_side(), INPUT: _empty_side()}
    # 按税率分的小格（销项 / 进项各自看）：回答「13% 那批开了多少」这种问题。
    buckets: dict[tuple[str, Decimal], dict[str, Any]] = {}
    voided = 0
    for invoice in rows:
        side = sides.get(str(invoice.direction or ""))
        if side is None:
            continue
        if str(invoice.status or "") == VOIDED:
            voided += 1
            continue
        amount = yuan(invoice.amount)
        if invoice.tax_rate is None:
            side["untaxed_count"] += 1
            side["untaxed_amount"] += amount
            continue
        tax = yuan(invoice.tax_amount or 0)
        side["count"] += 1
        side["amount"] += amount
        side["tax_amount"] += tax
        side["net_amount"] += amount - tax
        key = (str(invoice.direction), yuan(invoice.tax_rate))
        bucket = buckets.setdefault(
            key,
            {
                "direction": key[0],
                "tax_rate": key[1],
                "count": 0,
                "amount": Decimal("0.00"),
                "net_amount": Decimal("0.00"),
                "tax_amount": Decimal("0.00"),
            },
        )
        bucket["count"] += 1
        bucket["amount"] += amount
        bucket["tax_amount"] += tax
        bucket["net_amount"] += amount - tax
    return {
        "output": sides[OUTPUT],
        "input": sides[INPUT],
        "vat_payable": sides[OUTPUT]["tax_amount"] - sides[INPUT]["tax_amount"],
        "voided_count": voided,
        # 税率从高到低（13% → 9% → 3%），销项在前 —— 与界面上「销项一栏、进项一栏」同序。
        "by_rate": [buckets[k] for k in sorted(buckets, key=lambda k: (k[0] != OUTPUT, -k[1]))],
    }
