"""发票台账端点（FEAT-0014 税账）：登记 → 开具 → 作废·冲红，销项与进项共用一条线。

## 为什么要有这条线

老板要知道「这个月要交多少税」。要回答它只需要三个事实：开了多少票（销项）、收到多少票（进项）、
每张票里有多少税。这三件事以前**一处都没有** —— `shipper_receipts.invoiced` 是个布尔、没有任何落点，
利润表那一格恒为 0，全库连一个 `tax_rate` 都没有。本文件把发票变成一个可登记的事实。

## 状态机（三个状态，只往前、可回到登记）

`~text
REGISTERED（登记） --发出--> ISSUED（已开具） --作废--> VOIDED（已作废）
     ^                          ^
     +--- 只有 REGISTERED 能改 --+（要改已开具/已作废的票：作废重开一张）
`~

## 鉴权（⛔ 不新建权限点，见 docs/changes/FEAT-0014.md 的 Authorization）

`~text
写（登记 / 改 / 开具 / 作废 / 删 / 恢复）  Permission.LEDGER_EDIT —— 发票是钱的凭据，与账本编辑同一档。
读（列表 / 详情）                          Permission.ORDER_DISPATCH —— 与报表中心其余端点同一档。
`~

## 金额出参一律两位小数的字符串（`_money`）

浮点数进 JSON 就会在客户端被四舍五入成另一个数，而这是要拿去报税的钱。
⛔ 格式化只有端点层这一处（与采购单端点同一写法：`str(q2(...))`，不写格式串）。

## ⛔ 本文件一个数都不算

「这张票算不算进税汇」只有一处判据（`services/tax_service.py::counts_in_tax`）、
「税额怎么算」也只有一处（`tax_of_amount`）—— 端点只做参数搬运与形状转换。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.date_window import date_window
from app.core.pagination import finish_page
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import User
from app.schemas.invoice import InvoiceBrief, InvoiceCreate, InvoiceUpdate
from app.services import tax_service as tsvc
from app.services.order_money import q2

router = APIRouter(prefix="/invoices", tags=["invoices"])

#: 写端点：发票是钱的凭据，与账本编辑同一档（⛔ 不新建权限点）。
Writer = Depends(require_permission(Permission.LEDGER_EDIT))
#: 读端点：与报表中心其余端点同一档。
Reader = Depends(require_permission(Permission.ORDER_DISPATCH))


def _money(v: Decimal | None) -> str:
    """金额出参：两位小数的字符串（客户端直接显示，⛔ 不许拿去做算术）。"""
    # `q2` 已经把值量化到两位（services/order_money.py），`str` 出来就是两位小数字符串。
    # ⛔ 这里不写那个格式串：`_tools/qa/_check_money_display.py` 只放行 api/v1/suppliers.py 那一处。
    return str(q2(Decimal(v or 0)))


def _write(fn, db: Session, **kwargs):
    """写端点的统一保护：服务层中途抛中文 400/409 时，把这一事务里已经改过的行回滚掉。

    为什么必须显式回滚：`get_db` 的 `db.close()` 在生产里本来也会回滚（一次请求一个会话），
    但测试与 AI 复用同一个会话时不会 —— 半成品改动留在会话里，会被下一次别的请求的 commit
    带进库（一次 400 之后账上悄悄多出一张票）。
    """
    try:
        return fn(db, **kwargs)
    except HTTPException:
        db.rollback()
        raise


def _out(row: dict[str, Any]) -> InvoiceBrief:
    """服务层那份值 → 接口形状（金额在这里格式化）。"""
    return InvoiceBrief(
        id=row["id"],
        direction=row["direction"],
        invoice_no=row["invoice_no"],
        invoice_date=row["invoice_date"],
        amount=Decimal(str(row["amount"] or 0)),
        tax_rate=row["tax_rate"],
        tax_amount=row["tax_amount"],
        status=row["status"],
        supplier_id=row["supplier_id"],
        supplier_name=row["supplier_name"],
        customer_id=row["customer_id"],
        customer_name=row["customer_name"],
        note=row["note"],
        counts_in_tax=row["counts_in_tax"],
        purchase_order_ids=row["purchase_order_ids"],
        ledger_ids=row["ledger_ids"],
        is_deleted=row["is_deleted"],
        created_at=row["created_at"],
    )


def _out_one(db: Session, invoice) -> InvoiceBrief:
    sups, cus = tsvc.party_names(db, [invoice])
    return _out(tsvc.brief(invoice, sups=sups, cus=cus))


def _out_many(db: Session, invoices) -> list[InvoiceBrief]:
    """一批票：供应商 / 客户名各查一次（⛔ 不按张查，N+1 会拖垮列表）。"""
    sups, cus = tsvc.party_names(db, invoices)
    return [_out(tsvc.brief(inv, sups=sups, cus=cus)) for inv in invoices]


@router.get("", response_model=list[InvoiceBrief])
def list_invoices(
    db: Session = Depends(get_db),
    _: User = Reader,
    direction: str | None = Query(None, pattern="^(OUTPUT|INPUT)$", description="销项 / 进项"),
    status_: str | None = Query(None, alias="status", pattern="^(REGISTERED|ISSUED|VOIDED)$"),
    date_from: str | None = Query(None, description="开票日期起（含），YYYY-MM-DD"),
    date_to: str | None = Query(None, description="开票日期止（含），YYYY-MM-DD"),
    supplier_id: int | None = Query(None, description="只看某个供应商开的票（进项）"),
    customer_id: int | None = Query(None, description="只看开给某个客户的票（销项）"),
    keyword: str | None = Query(None, description="票号模糊找"),
    include_deleted: bool = Query(False, description="连回收站一起看"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    response: Response = None,  # type: ignore[assignment]
) -> list[InvoiceBrief]:
    """发票台账列表（默认不含回收站，按开票日期倒序）。

    ⚠️ `invoice_date` 是**业务当地的日期列**（同 `expenses.exp_date`），所以直接按日期比，
       不套 `business_range_utc` —— 那个是给 `created_at` 这类 UTC naive 时间列用的。

    ⚠️ 校验走 `core.date_window.date_window`（收**字符串**、返回 `date`），⛔ 不是 `deps.parse_date_range`：
       后者返回 `datetime`，拿它去比 `Date` 列就是 `ledger.py:78` 记下的那个坑（当天头 8 小时查不到），
       而且它自己也拦反序 —— 两个闸门叠在一起时「日期反了」这句 400 出自谁就说不清了。
    """
    df, dt = date_window(date_from, date_to)
    stmt = tsvc.invoice_query(
        direction=direction,
        status=status_,
        date_from=df,
        date_to=dt,
        supplier_id=supplier_id,
        customer_id=customer_id,
        include_deleted=include_deleted,
        keyword=keyword,
    )
    # ⚠️ 多取一行交给 `finish_page` 判截断（同 `api/v1/purchase_orders.py:185`）：
    #    只取 limit 行时，永远算不出「后面还有没有」，客户端也就永远看不到截断位。
    rows = list(db.scalars(stmt.limit(limit + 1).offset(offset)).all())
    return _out_many(db, finish_page(rows, limit, response))


@router.get("/{invoice_id}", response_model=InvoiceBrief)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: User = Reader,
) -> InvoiceBrief:
    """一张票（回收站里的也照给：列表能点进来看，详情就得打得开）。"""
    return _out_one(db, tsvc.get_invoice_or_404(db, invoice_id))


@router.post("", response_model=InvoiceBrief, status_code=status.HTTP_201_CREATED)
def create_invoice(
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    user: User = Writer,
) -> InvoiceBrief:
    """登记一张票（进项 / 销项共用）。

    ⚠️ **进项票必须挂 ≥1 张采购单**（发票抵的就是那几车货，供应商必须一致）；
       销项票挂账本条目（0..N 张，挂了的客户必须一致）。挂单规矩在 `tax_service._check_links`。
    """
    invoice = _write(
        tsvc.create_invoice,
        db,
        direction=payload.direction,
        invoice_no=payload.invoice_no,
        invoice_date=payload.invoice_date,
        amount=payload.amount,
        tax_rate=payload.tax_rate,
        tax_amount=payload.tax_amount,
        supplier_id=payload.supplier_id,
        customer_id=payload.customer_id,
        purchase_order_ids=payload.purchase_order_ids,
        ledger_ids=payload.ledger_ids,
        note=payload.note,
        operator_id=user.id,
    )
    return _out_one(db, invoice)


@router.patch("/{invoice_id}", response_model=InvoiceBrief)
def update_invoice(
    invoice_id: int,
    payload: InvoiceUpdate,
    db: Session = Depends(get_db),
    user: User = Writer,
) -> InvoiceBrief:
    """改一张**已登记**的票（已开具 / 已作废的票一个字都不动）。

    ⚠️ `exclude_unset` 是必须的：只有**真的传了**的字段才算「要改」，没传的字段一个字不动 ——
       税额重算规则靠它区分「没提税率」与「显式清空税率」（见 `tax_service.update_invoice`）。
    """
    invoice = tsvc.get_invoice_or_404(db, invoice_id)
    changes = payload.model_dump(exclude_unset=True)
    invoice = _write(tsvc.update_invoice, db, invoice=invoice, changes=changes, operator_id=user.id)
    return _out_one(db, invoice)


@router.post("/{invoice_id}/issue", response_model=InvoiceBrief)
def issue_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    user: User = Writer,
) -> InvoiceBrief:
    """把票从「已登记」推到「已开具」（票真的开出去了）。重复推进会被拦下。"""
    invoice = tsvc.get_invoice_or_404(db, invoice_id)
    invoice = _write(tsvc.issue_invoice, db, invoice=invoice, operator_id=user.id)
    return _out_one(db, invoice)


@router.post("/{invoice_id}/void", response_model=InvoiceBrief)
def void_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    user: User = Writer,
) -> InvoiceBrief:
    """作废 / 冲红：票从「已开具」或「已登记」进「已作废」。

    ⛔ 作废的票**不算数**（不进税汇），但它仍留在台账里（灰着摆出来）—— 税是记过的事，不能抹掉。
    """
    invoice = tsvc.get_invoice_or_404(db, invoice_id)
    invoice = _write(tsvc.void_invoice, db, invoice=invoice, operator_id=user.id)
    return _out_one(db, invoice)


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    user: User = Writer,
) -> None:
    """把票放进回收站（软删，可原样恢复）。"""
    invoice = tsvc.get_invoice_or_404(db, invoice_id)
    _write(tsvc.soft_delete_invoice, db, invoice=invoice, operator_id=user.id)


@router.post("/{invoice_id}/restore", response_model=InvoiceBrief)
def restore_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    user: User = Writer,
) -> InvoiceBrief:
    """从回收站恢复一张票。

    ⚠️ 票号在这期间被别人登记走了 ⇒ 如实报 **409**（⛔ 不悄悄改号：改号等于改一张票的身份）。
    """
    invoice = tsvc.get_invoice_or_404(db, invoice_id)
    invoice = _write(tsvc.restore_invoice, db, invoice=invoice, operator_id=user.id)
    return _out_one(db, invoice)
