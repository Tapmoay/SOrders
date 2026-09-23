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
from app.services import usage_service
from datetime import datetime

router = APIRouter(prefix="/arrears-units", tags=["arrears-units"])


@router.get("", response_model=list[ArrearsUnitOut])
def list_units(
    db: Session = Depends(get_db),
    # ⚠️ 参数名必须是 `current`：下面 `with_popularity(..., current)` 要用它
    # （原来这里写的是 `_` —— 依赖只用来做鉴权、值没人用）。2026-09-22 改成常用度排序时
    # 加了这个实参，`_` 与 `current` 对不上 → 每次调这个端点都 500（`NameError`），
    # 而**编译期看不出来**（真打到端点才炸）。
    current: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> list[ArrearsUnit]:
    rows = db.scalars(
        # 2026-09-22 统一规则：常用度 → 先创建的在前
        usage_service.with_popularity(
            select(ArrearsUnit).where(ArrearsUnit.is_deleted.is_(False)),
            ArrearsUnit, usage_service.KIND_ARREARS_UNIT, current,
        )
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
    u = _insert_unit(db, name, body.phone, body.remark, operator)
    db.commit()
    db.refresh(u)
    return u


def _insert_unit(db: Session, name: str, phone: str, remark: str, operator: User) -> ArrearsUnit:
    """新建一行挂账单位 + 写审计（**建单位的唯一实现**，见 [find_or_create_unit]）。"""
    u = ArrearsUnit(name=name, phone=phone.strip(), remark=remark.strip())
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
    return u


def find_or_create_unit(db: Session, raw_name: str, operator: User) -> ArrearsUnit:
    """按名字**找或建**一个挂账单位 —— 「挂账时自动添加」的唯一实现（2026-09-22）。

    用户原话：「我们这个挂账有个联动：假如有个订单，他没有结账，**直接点击挂账**，
    这个**挂账单位是自动添加的**」。
    所以挂账那条路不再要求"先建好单位再回来挂"，名字对得上就复用、对不上就地建一个。

    ⚠️ **软删过的不许再插一行**：`arrears_units.name` 上有唯一索引，而删除是软删
    （用户定的硬规矩）—— 直接 INSERT 会撞唯一索引（500），表现是"这个名字永远用不了"。
    所以这里先按名字（**连软删的一起**）找：活着就复用、躺回收站里就**放回来**（这也正是
    "删除一律软删 + 要有恢复路径"该有的样子）。
    """
    name = raw_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="挂账单位名不能为空")
    existing = db.scalars(select(ArrearsUnit).where(ArrearsUnit.name == name)).first()
    if existing is not None:
        if existing.is_deleted:
            existing.is_deleted = False
            existing.deleted_at = None
            write_log(
                db,
                operator_id=operator.id,
                order_id=None,
                action=OperationAction.ARREARS_UNIT_UPSERT,
                change_payload={"unit_id": existing.id, "name": existing.name, "scope": "restore"},
            )
        return existing
    return _insert_unit(db, name, "", "", operator)


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
    #
    # ⚠️ 2026-09-23 第 7 轮：订单那一份**只看"还没收到钱"的**（`paid=False`）。
    #    原来不分已收/未收，于是「派单员先点挂账 → 司机按收取现金送达」留下的那根陈旧指向
    #    （送达那条路当时没清 `arrears_unit_id`，见 `orders._apply_complete_payment`）
    #    会让这个单位**永远删不掉**，而那句「该单位名下已有 N 笔挂账订单」说的其实是一笔
    #    早就收了现金的单 —— 界面上又没有"改挂账单位"的入口，用户照这句话去处理也解不开。
    #    判据回到它本来的意思：**还挂着账（没收回钱）的订单才拦**。
    used = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.arrears_unit_id == unit_id, Order.paid.is_(False))
    )
    if used:
        raise HTTPException(status_code=400, detail=f"该单位名下已有 {used} 笔挂账订单，无法删除")
    # 只是"历史指向"（钱已经收到了）的那些：不拦，但要如实记一笔，别让人以为一个引用都没有。
    stale = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.arrears_unit_id == unit_id)
    ) or 0
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
        change_payload={
            "unit_id": u.id,
            "name": original_name,
            "note": "伪装删除，可 restore 恢复",
            # 查日志时能回答"这一单为什么允许删"：这些订单只是**历史指向**（钱已经收到了）
            **({"collected_orders_still_pointing": stale} if stale else {}),
        },
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
