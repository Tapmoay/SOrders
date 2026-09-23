"""供应商 / 厂商档案 + 应付单 + 付款（2026-09-22 用户要求，账本管理「支出」那一块）。

用户原话：「支出主要是**给某个供应商或者说是厂商支付尾款**……**购买一个装备或者说是设备**……
比如说类似**邮费**啊」；拍板口径：**跟客户一个量级的档案**（**可挂账、可查还欠多少、可分次付款**）。

## 这一组端点回答的三个问题
| 端点 | 回答 |
|---|---|
| `GET /suppliers` | 我有哪些供应商、**各自还欠多少** |
| `GET /suppliers/{id}` | 他的账：几笔应付、每笔付了多少、每笔付款是什么时候付的 |
| `POST /supplier-payables/{id}/payments` | **付一笔**（分次付款：一张单可以付很多次） |

## 权限
**全部 `LEDGER_EDIT`（只有派单员）** —— 与开销管理/客户收款同一档：
这些端点能动钱（付款会写 `cash_flows`），货主/司机不该碰。

## 一条贯穿全组的纪律
**欠款只由 `services/supplier_service.py` 算**，端点一个 SUM 都不写（理由见那个模块的文件头）。
端点在这里只做三件事：鉴权、把 ORM 行翻译成出参、写审计。
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.date_window import ensure_date_order
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import CashFlow, Supplier, SupplierPayable, User
from app.models.enums import OperationAction
from app.schemas.supplier import (
    SupplierCreate,
    SupplierOut,
    SupplierPayableCreate,
    SupplierPayableOut,
    SupplierPayableUpdate,
    SupplierPaymentCreate,
    SupplierPaymentOut,
    SupplierUpdate,
)
from app.services import supplier_service as svc
from app.services import usage_service
from app.services.operation_log_service import write_log
from app.services.order_money import q2

router = APIRouter(tags=["suppliers"])

Dispatcher = Depends(require_permission(Permission.LEDGER_EDIT))


def _money(v: Decimal | None) -> str:
    """金额出参一律两位小数字符串（与全项目同一套写法，客户端不再做进位）。"""
    return f"{q2(Decimal(v or 0)):.2f}"


def _supplier_out(db: Session, s: Supplier) -> SupplierOut:
    due, paid = svc.supplier_totals(db, s.id)
    open_n = db.scalar(
        select(func.count())
        .select_from(SupplierPayable)
        .where(SupplierPayable.supplier_id == s.id, SupplierPayable.is_deleted.is_(False))
    )
    return SupplierOut(
        id=s.id, name=s.name, contact_name=s.contact_name, phone=s.phone,
        address=s.address, remark=s.remark,
        payable_total=_money(due), paid_total=_money(paid),
        # ⚠️ 减法走 `svc.balance_of`（唯一那一处），**不在端点里做这个算术**：
        #    端点里出现"应付减已付"就等于开出第二个口径（判据会拦）。
        unpaid_total=_money(svc.balance_of(due, paid)),
        open_payables=int(open_n or 0), created_at=s.created_at,
    )


def _payable_out(db: Session, p: SupplierPayable) -> SupplierPayableOut:
    paid = svc.payable_paid(db, p.id)
    sup = db.get(Supplier, p.supplier_id)
    return SupplierPayableOut(
        id=p.id, supplier_id=p.supplier_id,
        supplier_name=(sup.name if sup else ""),
        title=p.title, category=p.category, amount=_money(p.amount),
        doc_date=p.doc_date, remark=p.remark,
        paid=_money(paid), unpaid=_money(svc.unpaid_of(p, paid)),
        payment_count=svc.payable_payment_count(db, p.id),
        created_at=p.created_at,
    )


def _payment_out(db: Session, f: CashFlow, sup_name: str = "", title: str = "") -> SupplierPaymentOut:
    """一行付款流水 → 出参。

    ⚠️ `remark` 是从流水的 `note` 里**取回来的**：付款时把备注拼进了 note
       （`note = "标题（第 N 次付款）· 备注"`），这里只取 `·` 之后那一段。
       为什么不在流水上单开一列存备注：`cash_flows.note` 就是这个作用，
       为了一句备注动钱的总账表不值得。
    """
    note = f.note or ""
    remark = note.split("·", 1)[1].strip() if "·" in note else ""
    if not sup_name:
        s = db.get(Supplier, f.party_id)
        sup_name = s.name if s else ""
    if not title and f.doc_id:
        p = db.get(SupplierPayable, f.doc_id)
        title = p.title if p else ""
    return SupplierPaymentOut(
        id=f.id, supplier_id=int(f.party_id or 0), supplier_name=sup_name,
        payable_id=int(f.doc_id or 0), payable_title=title,
        amount=_money(f.amount), pay_date=f.flow_date,
        channel=f.channel or "cash", remark=remark, created_at=f.created_at,
    )


def _touch(db: Session, me: User, supplier_id: int) -> None:
    """记一次「这个人用了这个供应商」（常用度排序；规则见 `services/usage_service.py`）。"""
    usage_service.record_usage(db, user=me, kind=usage_service.KIND_SUPPLIER, target_id=supplier_id)


def _check_name_free(db: Session, name: str, exclude_id: int | None = None) -> None:
    """名字不能被别人占着（**连回收站里的一起看**）。

    ⚠️ 回收站里的行名字带 `_del{id}` 后缀，所以正常不会撞上；但"软删时释放名字"
       这条规则一旦哪天被改坏，这里能给出人话而不是 500。
    """
    stmt = select(Supplier).where(Supplier.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Supplier.id != exclude_id)
    if db.scalars(stmt).first():
        raise HTTPException(status_code=400, detail=f"已经有一个供应商叫「{name}」了，换个名字或者直接用那一个")


# ---------------- 供应商档案 ----------------
@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    db: Session = Depends(get_db),
    current: User = Dispatcher,
    include_deleted: bool = Query(False),
) -> list[SupplierOut]:
    """供应商列表（默认不含回收站）。

    排序走统一规则（常用度 → 先创建的在前）：供应商是"挑一个来记账"的**名册**，
    不是"看记录"的列表，所以不按最新在前排。
    """
    stmt = select(Supplier)
    if not include_deleted:
        stmt = stmt.where(Supplier.is_deleted.is_(False))
    rows = list(db.scalars(usage_service.with_popularity(stmt, Supplier, usage_service.KIND_SUPPLIER, current)))
    if include_deleted:
        # 回收站是"看记录"，按删得最晚的在前；常用度排序对它们没有意义
        rows.sort(key=lambda s: (not s.is_deleted, s.id))
    return [_supplier_out(db, s) for s in rows]


@router.post("/suppliers", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def create_supplier(
    body: SupplierCreate,
    db: Session = Depends(get_db),
    operator: User = Dispatcher,
) -> SupplierOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="供应商名称不能为空")
    _check_name_free(db, name)
    s = Supplier(
        name=name, contact_name=body.contact_name.strip(), phone=(body.phone or "").strip(),
        address=body.address.strip(), remark=body.remark.strip(), operator_id=operator.id,
    )
    db.add(s)
    db.flush()
    write_log(
        db, operator_id=operator.id, order_id=None, action=OperationAction.SUPPLIER_UPSERT,
        change_payload={"supplier_id": s.id, "name": s.name, "scope": "create"},
    )
    _touch(db, operator, s.id)
    db.commit()
    db.refresh(s)
    return _supplier_out(db, s)


@router.get("/suppliers/{supplier_id}", response_model=SupplierOut)
def get_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    current: User = Dispatcher,
) -> SupplierOut:
    s = svc.get_supplier_or_404(db, supplier_id, need_alive=False)
    _touch(db, current, s.id)
    db.commit()
    return _supplier_out(db, s)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: int,
    body: SupplierUpdate,
    db: Session = Depends(get_db),
    operator: User = Dispatcher,
) -> SupplierOut:
    s = svc.get_supplier_or_404(db, supplier_id)
    before = {"name": s.name, "contact_name": s.contact_name, "phone": s.phone,
              "address": s.address, "remark": s.remark}
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="供应商名称不能为空")
        if name != s.name:
            _check_name_free(db, name, exclude_id=s.id)
        s.name = name
    if body.contact_name is not None:
        s.contact_name = body.contact_name.strip()
    if body.phone is not None:
        s.phone = (body.phone or "").strip()
    if body.address is not None:
        s.address = body.address.strip()
    if body.remark is not None:
        s.remark = body.remark.strip()
    write_log(
        db, operator_id=operator.id, order_id=None, action=OperationAction.SUPPLIER_UPSERT,
        change_payload={
            "supplier_id": s.id, "scope": "update", "before": before,
            "after": {"name": s.name, "contact_name": s.contact_name, "phone": s.phone,
                      "address": s.address, "remark": s.remark},
        },
    )
    db.commit()
    db.refresh(s)
    return _supplier_out(db, s)


@router.delete("/suppliers/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    operator: User = Dispatcher,
) -> None:
    s = svc.get_supplier_or_404(db, supplier_id)
    name = s.name
    svc.soft_delete_supplier(db, s)
    write_log(
        db, operator_id=operator.id, order_id=None, action=OperationAction.SUPPLIER_DELETE,
        change_payload={"supplier_id": s.id, "name": name, "note": "伪装删除，可 restore 恢复"},
    )
    db.commit()


@router.post("/suppliers/{supplier_id}/restore", response_model=SupplierOut)
def restore_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    operator: User = Dispatcher,
) -> SupplierOut:
    s = svc.get_supplier_or_404(db, supplier_id, need_alive=False)
    svc.restore_supplier(db, s)
    write_log(
        db, operator_id=operator.id, order_id=None, action=OperationAction.SUPPLIER_RESTORE,
        change_payload={"supplier_id": s.id, "name": s.name},
    )
    db.commit()
    db.refresh(s)
    return _supplier_out(db, s)


# ---------------- 应付单 ----------------
@router.get("/supplier-payables", response_model=list[SupplierPayableOut])
def list_payables(
    db: Session = Depends(get_db),
    current: User = Dispatcher,
    supplier_id: int | None = Query(None),
    include_deleted: bool = Query(False),
    only_open: bool = Query(False, description="只看还没结清的"),
) -> list[SupplierPayableOut]:
    """应付单列表（按单据日期倒序 —— 这是"看记录"，不是挑名册）。"""
    stmt = select(SupplierPayable).order_by(SupplierPayable.doc_date.desc(), SupplierPayable.id.desc())
    if supplier_id is not None:
        stmt = stmt.where(SupplierPayable.supplier_id == supplier_id)
    if not include_deleted:
        stmt = stmt.where(SupplierPayable.is_deleted.is_(False))
    rows = [_payable_out(db, p) for p in db.scalars(stmt)]
    if only_open:
        rows = [r for r in rows if Decimal(r.unpaid) > 0]
    return rows


@router.post("/suppliers/{supplier_id}/payables", response_model=SupplierPayableOut, status_code=status.HTTP_201_CREATED)
def create_payable(
    supplier_id: int,
    body: SupplierPayableCreate,
    db: Session = Depends(get_db),
    operator: User = Dispatcher,
) -> SupplierPayableOut:
    """给某个供应商挂一笔应付（欠他的钱）。**这一步不动钱** —— 付的时候才动。"""
    s = svc.get_supplier_or_404(db, supplier_id)
    if body.supplier_id != supplier_id:
        raise HTTPException(status_code=400, detail="路径里的供应商与请求体里的对不上，别把账挂到别人头上")
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="这笔应付是什么（事由）不能为空")
    p = SupplierPayable(
        supplier_id=s.id, title=title, category=(body.category or "货款").strip() or "货款",
        amount=q2(Decimal(body.amount)), doc_date=body.doc_date,
        remark=body.remark.strip(), operator_id=operator.id,
    )
    db.add(p)
    db.flush()
    write_log(
        db, operator_id=operator.id, order_id=None, action=OperationAction.SUPPLIER_PAYABLE_UPSERT,
        change_payload={"payable_id": p.id, "supplier_id": s.id, "supplier_name": s.name,
                        "title": p.title, "amount": str(p.amount), "scope": "create"},
    )
    _touch(db, operator, s.id)
    db.commit()
    db.refresh(p)
    return _payable_out(db, p)


@router.patch("/supplier-payables/{payable_id}", response_model=SupplierPayableOut)
def update_payable(
    payable_id: int,
    body: SupplierPayableUpdate,
    db: Session = Depends(get_db),
    operator: User = Dispatcher,
) -> SupplierPayableOut:
    p = svc.get_payable_or_404(db, payable_id)
    before = {"title": p.title, "category": p.category, "amount": str(p.amount),
              "doc_date": str(p.doc_date), "remark": p.remark}
    if body.amount is not None:
        # ⛔ 金额不许改到小于已付：那等于把**已经付出去的钱**说成没付（欠款会变成负数，
        #    而界面上没人读得对）。要改小就先撤销多付的那一笔。
        paid = svc.payable_paid(db, p.id)
        if q2(Decimal(body.amount)) < paid:
            raise HTTPException(
                status_code=400,
                detail=f"这张单已经付了 {paid}，金额不能改成比它小（{q2(Decimal(body.amount))}）；先撤销多付的那一笔",
            )
        p.amount = q2(Decimal(body.amount))
    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="这笔应付是什么（事由）不能为空")
        p.title = title
    if body.category is not None:
        p.category = body.category.strip() or "货款"
    if body.doc_date is not None:
        p.doc_date = body.doc_date
    if body.remark is not None:
        p.remark = body.remark.strip()
    write_log(
        db, operator_id=operator.id, order_id=None, action=OperationAction.SUPPLIER_PAYABLE_UPSERT,
        change_payload={
            "payable_id": p.id, "supplier_id": p.supplier_id, "title": p.title,
            "scope": "update", "before": before,
            "after": {"title": p.title, "category": p.category, "amount": str(p.amount),
                      "doc_date": str(p.doc_date), "remark": p.remark},
        },
    )
    db.commit()
    db.refresh(p)
    return _payable_out(db, p)


@router.delete("/supplier-payables/{payable_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payable(
    payable_id: int,
    db: Session = Depends(get_db),
    operator: User = Dispatcher,
) -> None:
    p = svc.get_payable_or_404(db, payable_id)
    title = p.title
    svc.soft_delete_payable(db, p)
    write_log(
        db, operator_id=operator.id, order_id=None, action=OperationAction.SUPPLIER_PAYABLE_DELETE,
        change_payload={"payable_id": p.id, "supplier_id": p.supplier_id, "title": title,
                        "note": "伪装删除，可 restore 恢复"},
    )
    db.commit()


@router.post("/supplier-payables/{payable_id}/restore", response_model=SupplierPayableOut)
def restore_payable(
    payable_id: int,
    db: Session = Depends(get_db),
    operator: User = Dispatcher,
) -> SupplierPayableOut:
    p = svc.get_payable_or_404(db, payable_id, need_alive=False)
    svc.restore_payable(db, p)
    write_log(
        db, operator_id=operator.id, order_id=None, action=OperationAction.SUPPLIER_PAYABLE_RESTORE,
        change_payload={"payable_id": p.id, "supplier_id": p.supplier_id, "title": p.title},
    )
    db.commit()
    db.refresh(p)
    return _payable_out(db, p)


# ---------------- 付款 ----------------
@router.get("/supplier-payments", response_model=list[SupplierPaymentOut])
def list_payments(
    db: Session = Depends(get_db),
    current: User = Dispatcher,
    supplier_id: int | None = Query(None),
    payable_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    include_deleted: bool = Query(False, description="含已撤销的（回收站）"),
) -> list[SupplierPaymentOut]:
    """付款记录列表（默认只看**没被撤销**的）。

    ⚠️ 付款记录**就是** `cash_flows` 里 `biz_type=PAYMENT_SUPPLIER` 的那些行 ——
       账本「收支」页看的也是同一批行（同一笔钱不可能有两个来源）。
    """
    ensure_date_order(date_from, date_to)
    stmt = (
        select(CashFlow)
        .where(
            CashFlow.party_type == svc.PARTY_SUPPLIER,
            CashFlow.biz_type == "PAYMENT_SUPPLIER",
        )
        .order_by(CashFlow.flow_date.desc(), CashFlow.id.desc())
    )
    if not include_deleted:
        stmt = stmt.where(CashFlow.is_deleted.is_(False))
    if supplier_id is not None:
        stmt = stmt.where(CashFlow.party_id == supplier_id)
    if payable_id is not None:
        stmt = stmt.where(CashFlow.doc_id == payable_id)
    if date_from:
        stmt = stmt.where(CashFlow.flow_date >= date_from)
    if date_to:
        stmt = stmt.where(CashFlow.flow_date <= date_to)
    return [_payment_out(db, f) for f in db.scalars(stmt)]


@router.post("/supplier-payables/{payable_id}/payments", response_model=SupplierPaymentOut, status_code=status.HTTP_201_CREATED)
def pay_payable(
    payable_id: int,
    body: SupplierPaymentCreate,
    db: Session = Depends(get_db),
    operator: User = Dispatcher,
) -> SupplierPaymentOut:
    """**付一笔款**（分次付款：同一张单可以付很多次，每次一行资金流水）。"""
    p = svc.get_payable_or_404(db, payable_id)
    flow = svc.pay_supplier(
        db, p, amount=body.amount, pay_date=body.pay_date, channel=body.channel,
        remark=body.remark, operator_id=operator.id,
    )
    write_log(
        db, operator_id=operator.id, order_id=None, action=OperationAction.SUPPLIER_PAYMENT_CREATE,
        change_payload={"flow_id": flow.id, "payable_id": p.id, "supplier_id": p.supplier_id,
                        "amount": str(flow.amount), "pay_date": str(flow.flow_date),
                        "channel": flow.channel},
    )
    _touch(db, operator, p.supplier_id)
    db.commit()
    db.refresh(flow)
    return _payment_out(db, flow)


@router.delete("/supplier-payments/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_payment(
    flow_id: int,
    db: Session = Depends(get_db),
    operator: User = Dispatcher,
) -> None:
    """**撤销一笔付款**（软删那一行资金流水）。

    用户定的硬规矩：「所有删除一律软删 + 必须有恢复路径」。这里的"删除"必须软删而不是
    再写一笔反向的钱 —— 反向的钱会在账上留下一对谁也不敢删的行，而且"这笔到底算不算"
    以后只能靠人去读备注。
    """
    f = _get_payment_or_404(db, flow_id)
    if f.is_deleted:
        raise HTTPException(status_code=400, detail="这笔付款已经撤销过了")
    f.is_deleted = True
    f.deleted_at = utc_now_naive()
    write_log(
        db, operator_id=operator.id, order_id=None, action=OperationAction.SUPPLIER_PAYMENT_CANCEL,
        change_payload={"flow_id": f.id, "payable_id": f.doc_id, "supplier_id": f.party_id,
                        "amount": str(f.amount), "note": "撤销付款（伪装删除），可 restore 恢复"},
    )
    db.commit()


@router.post("/supplier-payments/{flow_id}/restore", response_model=SupplierPaymentOut)
def restore_payment(
    flow_id: int,
    db: Session = Depends(get_db),
    operator: User = Dispatcher,
) -> SupplierPaymentOut:
    """把撤销掉的付款放回来。

    ⛔ 三道门（少一道就会出现"钱回来了、却对不上任何单据"）：
       ① 它得真的在回收站里；② 它对应的**应付单必须还活着**；③ 它对应的**供应商也必须还活着**。
    """
    f = _get_payment_or_404(db, flow_id)
    if not f.is_deleted:
        raise HTTPException(status_code=400, detail="这笔付款没有被撤销，不需要恢复")
    p = db.get(SupplierPayable, f.doc_id) if f.doc_id else None
    if p is None:
        raise HTTPException(status_code=400, detail="它对应的应付单已经不存在了，恢复不了")
    if p.is_deleted:
        raise HTTPException(
            status_code=400,
            detail="它对应的应付单还在回收站里，先把那张单恢复回来（POST /supplier-payables/{id}/restore）",
        )
    s = db.get(Supplier, f.party_id) if f.party_id else None
    if s is None or s.is_deleted:
        raise HTTPException(
            status_code=400,
            detail="它对应的供应商还在回收站里（或已不存在），先把供应商恢复回来（POST /suppliers/{id}/restore）",
        )
    f.is_deleted = False
    f.deleted_at = None
    write_log(
        db, operator_id=operator.id, order_id=None, action=OperationAction.SUPPLIER_PAYMENT_RESTORE,
        change_payload={"flow_id": f.id, "payable_id": f.doc_id, "supplier_id": f.party_id,
                        "amount": str(f.amount)},
    )
    db.commit()
    db.refresh(f)
    return _payment_out(db, f)


def _get_payment_or_404(db: Session, flow_id: int) -> CashFlow:
    """按编号取一行**付款流水**（不是随便一行 cash_flow）。

    ⚠️ 判据必须带上 `party_type` + `biz_type`：`cash_flows` 是所有收付的总账，
       光按 id 取会取到一笔司机结算或开销，然后被"撤销"掉。
    """
    f = db.get(CashFlow, flow_id)
    if f is None or f.party_type != svc.PARTY_SUPPLIER or str(f.biz_type) != "PAYMENT_SUPPLIER":
        raise HTTPException(status_code=404, detail="这笔付款记录不存在")
    return f
