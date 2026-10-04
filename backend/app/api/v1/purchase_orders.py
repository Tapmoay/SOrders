"""采购单端点（FEAT-0013）：一次进货，把**库存、成本价、供应商应付**三件事一起写。

## 为什么要有这条线（原来只有「逐个商品手工入库」）

```text
POST /inventory/movements  一次只写一个商品、供应商不提、单据不留痕
    → 「这批货总共多少钱、欠谁多少」只能事后拿计算器拼
```

采购单把**一次采购**变成一个事实：单头（供应商 + 单据日期）+ 多行明细（商品 / 数量 / 进货价），
保存时在同一个事务里写完三件事。改单是**改写**那一行绑定的人库流水（理由见 `services/purchase_service.py`）。

## 鉴权（⛔ 不新建权限点，见 docs/changes/FEAT-0013.md 的 Authorization）

```text
写（建 / 改 / 删 / 恢复）  Permission.PRODUCT_MANAGE —— 进货第一件事是入库，与
                          POST /inventory/movements 同一个权限点：
                          能改库存的人才建得了采购单。
读（列表 / 详情）          Permission.ORDER_DISPATCH —— 与报表中心其余端点同一档
                          （进货价与欠款是经营数据）。
```

## 金额出参一律**字符串两位小数**（`_money`）

浮点数进 JSON 就会在客户端被四舍五入成另一个数，而这是要拿去对账的钱。
⛔ 欠款不在这里算：「还差多少」走 `supplier_service.unpaid_of`（全项目唯一那处减法）。
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.date_window import date_window
from app.core.pagination import finish_page
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import Product, PurchaseOrder, Supplier, SupplierPayable, User
from app.schemas.purchase import (
    PurchaseItemOut,
    PurchaseOrderBrief,
    PurchaseOrderCreate,
    PurchaseOrderOut,
    PurchaseOrderUpdate,
)
from app.services import purchase_service as psvc
from app.services import supplier_service as svc
from app.services.order_money import q2

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])

#: 写端点：与 POST /inventory/movements 同一个权限点（进货第一件事是入库）。
Writer = Depends(require_permission(Permission.PRODUCT_MANAGE))
#: 读端点：与报表中心其余端点同一档（进货价与欠款是经营数据，不是名册）。
Reader = Depends(require_permission(Permission.ORDER_DISPATCH))

_ZERO = Decimal("0")


def _money(v: Decimal | None) -> str:
    """金额出参：两位小数的字符串（客户端直接显示，⛔ 不许拿去做算术）。"""
    # `q2` 已经把值量化到两位（services/order_money.py），`str` 出来就是两位小数字符串 ——
    # 与「两位小数的格式串」逐字相同。⛔ 这里不写那个格式串：`_tools/qa/_check_money_display.py` 只放行
    # api/v1/suppliers.py 那一处（全仓唯一的接口出参格式化点），别处再写会被判「格式化越界」。
    return str(q2(Decimal(v or 0)))


def _write(fn, db: Session, **kwargs):
    """写端点的统一保护：服务层中途抛中文 400/409 时，**把这一事务里已经改过的行回滚掉**。

    为什么必须显式回滚：`get_db` 的 `db.close()` 在生产里本来也会回滚（一次请求一个会话），
    但测试与 AI 复用同一个会话时不会 —— 半成品改动留在会话里，会被**下一次别的请求**的
    commit 带进库（一次 400 之后账上悄悄多出一段库存）。2026-10-04 实测抓到：
    「已经付过钱的单删不掉」这条用例里，删单返回 400、库存却已经退回去了。
    """
    try:
        return fn(db, **kwargs)
    except HTTPException:
        db.rollback()
        raise


def _payable_amounts(db: Session, order: PurchaseOrder) -> tuple[Decimal, Decimal]:
    """这张单生成的应付：已付 / 还差。

    ⛔ 减法只在 `supplier_service.unpaid_of` 一处 —— 这里不写 `amount - paid`。
    """
    if order.payable_id is None:
        return _ZERO, _ZERO
    payable = db.get(SupplierPayable, order.payable_id)
    if payable is None:
        return _ZERO, _ZERO
    paid = svc.payable_paid(db, payable.id)
    return paid, svc.unpaid_of(payable, paid)


def _brief_out(db: Session, order: PurchaseOrder) -> PurchaseOrderBrief:
    """列表里的一行：单头 + 行数 + 合计 + 应付摘要（明细不带）。"""
    supplier = db.get(Supplier, order.supplier_id)
    paid, unpaid = _payable_amounts(db, order)
    return PurchaseOrderBrief(
        id=order.id,
        supplier_id=order.supplier_id,
        supplier_name=supplier.name if supplier is not None else "",
        doc_date=order.doc_date,
        remark=order.remark or "",
        item_count=len(psvc.active_items(order)),
        # 合计 = Σ 明细金额（现算，⛔ 单头不存这个数）
        total=_money(psvc.total_of(order.items)),
        payable_id=order.payable_id,
        payable_paid=_money(paid),
        payable_unpaid=_money(unpaid),
        is_deleted=bool(order.is_deleted),
        created_at=order.created_at,
    )


def _items_out(db: Session, order: PurchaseOrder) -> list[PurchaseItemOut]:
    ids = [it.product_id for it in order.items]
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids)))} if ids else {}
    out: list[PurchaseItemOut] = []
    for it in order.items:
        p = products.get(it.product_id)
        out.append(PurchaseItemOut(
            id=it.id,
            product_id=it.product_id,
            product_name=p.name if p is not None else "",
            unit=(p.unit or "") if p is not None else "",
            quantity=int(it.quantity or 0),
            unit_cost=_money(it.unit_cost),
            # 撤行恒 0（`line_amount` 是那一处口径）
            amount=_money(psvc.line_amount(it)),
            is_void=bool(it.is_void),
            movement_id=it.movement_id,
        ))
    return out


def _detail_out(db: Session, order: PurchaseOrder) -> PurchaseOrderOut:
    brief = _brief_out(db, order)
    return PurchaseOrderOut(
        **brief.model_dump(),
        operator_id=order.operator_id,
        updated_at=order.updated_at,
        items=_items_out(db, order),
    )


@router.get("", response_model=list[PurchaseOrderBrief])
def list_purchase_orders(
    db: Session = Depends(get_db),
    _: User = Reader,
    supplier_id: int | None = Query(None, description="只看某个供应商的"),
    date_from: str | None = Query(None, description="单据日期起（含），YYYY-MM-DD"),
    date_to: str | None = Query(None, description="单据日期止（含），YYYY-MM-DD"),
    include_deleted: bool = Query(False, description="连回收站一起看"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    response: Response = None,  # type: ignore[assignment]
) -> list[PurchaseOrderBrief]:
    """采购单列表（默认不含回收站，按单据日期倒序 —— 这是「看记录」）。

    ⚠️ `doc_date` 是**业务当地的日期列**（同 `expenses.exp_date`），所以直接按日期比，
       不套 `business_range_utc` —— 那个是给 `created_at` 这类 UTC naive 时间列用的。

    ⚠️ 校验走 `core.date_window.date_window`（收**字符串**、返回 `date`），⛔ 不是 `deps.parse_date_range`：
       后者返回 `datetime`，拿它去比 `Date` 列就是 `ledger.py:78` 记下的那个坑（当天头 8 小时查不到）。
       而且它自己也拦反序 —— 两个闸门叠在一起时，"日期反了"这句 400 到底出自谁就说不清了，
       `tests/test_date_order_guard.py::test_the_400_comes_from_the_shared_guard` 会因此变红。
    """
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.doc_date.desc(), PurchaseOrder.id.desc())
    if supplier_id is not None:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    df, dt = date_window(date_from, date_to)
    if df is not None:
        stmt = stmt.where(PurchaseOrder.doc_date >= df)
    if dt is not None:
        stmt = stmt.where(PurchaseOrder.doc_date <= dt)
    if not include_deleted:
        stmt = stmt.where(PurchaseOrder.is_deleted.is_(False))
    rows = list(db.scalars(stmt.limit(limit + 1).offset(offset)))
    return [_brief_out(db, o) for o in finish_page(rows, limit, response)]


@router.get("/{order_id}", response_model=PurchaseOrderOut)
def get_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Reader,
) -> PurchaseOrderOut:
    """一张采购单的明细（回收站里的也照给：列表能点进来看，详情就得打得开）。"""
    order = psvc.get_order_or_404(db, order_id)
    return _detail_out(db, order)


@router.post("", response_model=PurchaseOrderOut, status_code=status.HTTP_201_CREATED)
def create_purchase_order(
    body: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    operator: User = Writer,
) -> PurchaseOrderOut:
    """建一张采购单：库存 + 成本价（加权均价）+ 供应商应付，一个事务里一次写完。

    校验都在 `purchase_service` 里（中文 400）：数量/单价的区间、同单同商品只许一行、
    供应商必须存在 —— 端点这一层不重复实现规则。
    """
    order = _write(
        psvc.create_order,
        db,
        supplier_id=body.supplier_id,
        doc_date=body.doc_date,
        remark=body.remark,
        items=body.items,
        operator_id=operator.id,
    )
    return _detail_out(db, order)


@router.patch("/{order_id}", response_model=PurchaseOrderOut)
def update_purchase_order(
    order_id: int,
    body: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
    operator: User = Writer,
) -> PurchaseOrderOut:
    """改单：改数量/单价就**改写那一行绑定的人库流水**（不是再记一笔冲销），撤行走 `is_void`。

    `items=None` 表示只改单头（供应商/日期/备注），⛔ 与「传一个空数组」不是一回事
    （空数组 = 把所有行都撤掉，而一张一行都不剩的采购单没有意义 —— 那条路是 DELETE）。
    """
    order = psvc.get_order_or_404(db, order_id)
    order = _write(
        psvc.update_order,
        db,
        order=order,
        supplier_id=body.supplier_id,
        doc_date=body.doc_date,
        remark=body.remark,
        items=body.items,
        operator_id=operator.id,
    )
    return _detail_out(db, order)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    operator: User = Writer,
) -> None:
    """撤销整张采购单（软删）：逐行把库存冲回去 + 删掉它生成的那张应付单。

    ⛔ 已经付过钱的应付单删不掉（`supplier_service.soft_delete_payable` 会如实拒绝），
       这时候用户该做的是先撤销那些付款 —— 端点把这句原话透出去。
    """
    order = psvc.get_order_or_404(db, order_id)
    _write(psvc.soft_delete_order, db, order=order, operator_id=operator.id)


@router.post("/{order_id}/restore", response_model=PurchaseOrderOut)
def restore_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    operator: User = Writer,
) -> PurchaseOrderOut:
    """把回收站里的采购单恢复回来：重新入库 + 恢复它生成的那张应付单。

    库存不够（这段时间货已经被卖掉/出库了）时如实报错，⛔ 不把库存改成负数。
    """
    order = psvc.get_order_or_404(db, order_id)
    order = _write(psvc.restore_order, db, order=order, operator_id=operator.id)
    return _detail_out(db, order)
