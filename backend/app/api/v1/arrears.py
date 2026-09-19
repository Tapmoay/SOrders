"""挂账单位管理（派单员）：订单可选择挂账到单位名下。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.services.operation_log_service import write_log
from app.services.soft_delete import del_suffix, ensure_alive
from app.models import ArrearsUnit, Order, User
from app.models.enums import OperationAction
from app.schemas.arrears import ArrearsUnitCreate, ArrearsUnitOut, ArrearsUnitUpdate
from datetime import datetime

router = APIRouter(prefix="/arrears-units", tags=["arrears-units"])


@router.get("", response_model=list[ArrearsUnitOut])
def list_units(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> list[ArrearsUnit]:
    rows = db.scalars(
        select(ArrearsUnit).where(ArrearsUnit.is_deleted.is_(False)).order_by(ArrearsUnit.id.desc())
    )
    return list(rows)


@router.post("", response_model=ArrearsUnitOut, status_code=status.HTTP_201_CREATED)
def create_unit(
    body: ArrearsUnitCreate,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> ArrearsUnit:
    name = body.name.strip()
    if db.scalars(
        select(ArrearsUnit).where(ArrearsUnit.name == name, ArrearsUnit.is_deleted.is_(False))
    ).first():
        raise HTTPException(status_code=400, detail="挂账单位名称已存在")
    u = ArrearsUnit(name=name, phone=body.phone.strip(), remark=body.remark.strip())
    db.add(u)
    db.flush()
    # ⚠️ 挂账单位是**钱挂在谁名下**这件事（2026-09-19 审计 R14-1）：原来四个写端点
    #    **一条日志都不写** —— 真机用 AI 建了一个单位，库里多了一行、审计页上什么都没有。
    #    单位改名之后历史欠款按 `arrears_unit_name` 快照分组，谁也说不清名字是谁改的。
    write_log(
        db,
        operator_id=operator.id,
        order_id=None,
        action=OperationAction.ARREARS_UNIT_UPSERT,
        change_payload={"unit_id": u.id, "name": u.name, "phone": u.phone, "scope": "create"},
    )
    db.commit()
    db.refresh(u)
    return u


@router.patch("/{unit_id}", response_model=ArrearsUnitOut)
def update_unit(
    unit_id: int,
    body: ArrearsUnitUpdate,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> ArrearsUnit:
    u = db.get(ArrearsUnit, unit_id)
    if u is None:
        raise HTTPException(status_code=404, detail="挂账单位不存在")
    # ⚠️ 软删的挂账单位**改不了**（R11-F4）：列表里看不见它，改它只会得到一句「已完成」，
    #    而它名下的旧欠款还挂在账上——用户以为改的是"现在用的那一个"。
    ensure_alive(u, "挂账单位", "POST /arrears-units/{id}/restore")
    before = {"name": u.name, "phone": u.phone, "remark": u.remark}
    if body.name is not None:
        name = body.name.strip()
        dup = db.scalars(
            select(ArrearsUnit).where(
            ArrearsUnit.name == name, ArrearsUnit.id != unit_id, ArrearsUnit.is_deleted.is_(False)
        )
        ).first()
        if dup:
            raise HTTPException(status_code=400, detail="挂账单位名称已存在")
        u.name = name
    if body.phone is not None:
        u.phone = body.phone.strip()
    if body.remark is not None:
        u.remark = body.remark.strip()
    write_log(
        db,
        operator_id=operator.id,
        order_id=None,
        action=OperationAction.ARREARS_UNIT_UPSERT,
        change_payload={
            "unit_id": u.id,
            "scope": "update",
            "before": before,
            "after": {"name": u.name, "phone": u.phone, "remark": u.remark},
        },
    )
    db.commit()
    db.refresh(u)
    return u


@router.delete("/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> None:
    u = db.get(ArrearsUnit, unit_id)
    if u is None:
        raise HTTPException(status_code=404, detail="挂账单位不存在")
    # ⚠️ 引用的**每一处**都要数（2026-09-19 审计）：原来只数订单，于是删掉一个单位之后，
    #    `customers.arrears_unit_id` 与 `shipper_receipts.arrears_unit_id` 会留下**指向已删单位的孤儿**。
    #    两列都是裸 Integer（没有外键），数据库不会拦、界面上也看不出来。
    used = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.arrears_unit_id == unit_id)
    )
    if used:
        raise HTTPException(status_code=400, detail=f"该单位名下已有 {used} 笔挂账订单，无法删除")
    from app.models import Customer, ShipperReceipt

    cust_used = db.scalar(
        select(func.count()).select_from(Customer).where(Customer.arrears_unit_id == unit_id)
    )
    if cust_used:
        raise HTTPException(status_code=400, detail=f"有 {cust_used} 个客户档案挂在这个单位上，先改掉再删")
    receipt_used = db.scalar(
        select(func.count()).select_from(ShipperReceipt).where(ShipperReceipt.arrears_unit_id == unit_id)
    )
    if receipt_used:
        raise HTTPException(
            status_code=400,
            detail=f"有 {receipt_used} 张收款单记在这个单位名下，删了会让收款记录指向不存在的单位",
        )
    # 伪装删除：行留着，恢复时逐字段照搬。**名字要释放出来**——
    # 这张表 name 是唯一的，不释放的话删掉再建同名单位会直接 500。
    original_name = u.name
    u.is_deleted = True
    u.deleted_at = utc_now_naive()
    u.name = del_suffix(u.name, u.id, 128)   # arrears_units.name 是 String(128)
    write_log(
        db,
        operator_id=operator.id,
        order_id=None,
        action=OperationAction.ARREARS_UNIT_DELETE,
        change_payload={"unit_id": u.id, "name": original_name, "note": "伪装删除，可 restore 恢复"},
    )
    db.commit()


@router.post("/{unit_id}/restore", response_model=ArrearsUnitOut)
def restore_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> ArrearsUnit:
    """把删掉的挂账单位恢复回来（DELETE /{id} 的逆操作）。

    名字冲突时**保留现在的名字**（硬抢回来会把另一个单位顶掉）；冲突情况写在返回里，
    让用户自己决定要不要改名。
    """
    u = db.get(ArrearsUnit, unit_id)
    if u is None:
        raise HTTPException(status_code=404, detail="挂账单位不存在")
    if not u.is_deleted:
        raise HTTPException(status_code=400, detail="这个单位没有被删除，不需要恢复")
    suffix = f"_del{u.id}"
    if u.name.endswith(suffix):
        want = u.name[: -len(suffix)]
        taken = db.scalars(
            select(ArrearsUnit).where(ArrearsUnit.name == want, ArrearsUnit.id != u.id)
        ).first()
        if taken is None:
            u.name = want
    u.is_deleted = False
    u.deleted_at = None
    write_log(
        db,
        operator_id=operator.id,
        order_id=None,
        action=OperationAction.ARREARS_UNIT_RESTORE,
        change_payload={"unit_id": u.id, "name": u.name},
    )
    db.commit()
    db.refresh(u)
    return u
