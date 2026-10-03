"""车辆分类名册（派单员维护；车辆管理页左侧那一列）。

用户 2026-10-05：「还有我们的账户管理司机管理货主管理批发商管理。车辆管理……
在这个位置也加个分类，默认是显示，全部，同样也是左边侧边栏，
然后左边侧边栏同样也是可以新增分类的」。

与账号分类名册（`api/v1/user_categories.py`）同一套三条：改名要级联改
`vehicles.category`、建车时带了名册里没有的分类名就自动补进名册、删除时还有车挂着就拒绝。

⚠️ 与 `vehicles.vehicle_type`（车型：小货车 / 大货车 / 挂车 —— **计费口径**）和
`vehicles.body_type`（车身型式）是**三件不同的事**：那两列是运输属性，会影响计费与匹配；
分类只是"派单员怎么把车队分组看"。⛔ 分类**不许**参与任何计费 / 匹配 / 权限判断，
否则会出现"改个分组名把运费改了"这种事。

⚠️ 「在用」含**停用**的车（`is_active=False`）：车不软删，停用的车照样挂着分类，
删分类就会把它变成未分类。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import User, Vehicle, VehicleCategory
from app.models.enums import OperationAction
from app.schemas.vehicle_category import (
    VehicleCategoryCreate,
    VehicleCategoryOut,
    VehicleCategoryReorder,
    VehicleCategoryUpdate,
)
from app.services.category_order import ordered_ids
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/vehicle-categories", tags=["vehicle-categories"])

MAX_CATEGORIES = 200


def _counts(db: Session) -> dict[str, int]:
    """分类名 → 在用车辆数（**一次查完**，不要每个分类查一遍）。"""
    rows = db.execute(
        select(Vehicle.category, func.count(Vehicle.id))
        .where(Vehicle.category != "")
        .group_by(Vehicle.category)
    ).all()
    return {(name or "").strip(): n for name, n in rows if (name or "").strip()}


def _out(row: VehicleCategory, counts: dict[str, int]) -> VehicleCategoryOut:
    o = VehicleCategoryOut.model_validate(row)
    o.vehicle_count = counts.get(row.name, 0)
    return o


def _next_sort(db: Session) -> int:
    top = db.scalar(select(func.max(VehicleCategory.sort_order)))
    return (top or 0) + 1


def ensure_vehicle_category(db: Session, name: str) -> VehicleCategory | None:
    """确保这个分类名在名册里（不在就补到最后）。给车辆的新建/修改复用。"""
    clean = (name or "").strip()[:32]
    if not clean:
        return None
    exists = db.scalars(select(VehicleCategory).where(VehicleCategory.name == clean)).first()
    if exists is not None:
        return None
    row = VehicleCategory(name=clean, sort_order=_next_sort(db))
    db.add(row)
    db.flush()
    return row


@router.get("", response_model=list[VehicleCategoryOut])
def list_categories(current: CurrentUser, db: Session = Depends(get_db)) -> list[VehicleCategoryOut]:
    """分类名册（按显示顺序）。全店一份 —— 车队是全局主数据。"""
    rows = db.scalars(
        select(VehicleCategory).order_by(VehicleCategory.sort_order, VehicleCategory.id)
    ).all()
    counts = _counts(db)
    return [_out(r, counts) for r in rows]


@router.post("", response_model=VehicleCategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: VehicleCategoryCreate,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> VehicleCategoryOut:
    exists = db.scalars(select(VehicleCategory).where(VehicleCategory.name == body.name)).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
    total = db.scalar(select(func.count(VehicleCategory.id))) or 0
    if total >= MAX_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"分类最多 {MAX_CATEGORIES} 个，请先清理一些")
    row = VehicleCategory(
        name=body.name,
        sort_order=body.sort_order if body.sort_order is not None else _next_sort(db),
    )
    db.add(row)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.VEHICLE_CATEGORY_UPSERT,
        change_payload={"category_id": row.id, "name": row.name, "sort_order": row.sort_order, "op": "create"},
    )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db))


@router.patch("/{category_id}", response_model=VehicleCategoryOut)
def update_category(
    category_id: int,
    body: VehicleCategoryUpdate,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> VehicleCategoryOut:
    """改名 / 改顺序。**改名会级联改掉挂在这一类下的车**（同一事务）。"""
    row = db.get(VehicleCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    changes: list[dict] = []
    if body.name is not None and body.name != row.name:
        clash = db.scalars(
            select(VehicleCategory).where(
                VehicleCategory.name == body.name, VehicleCategory.id != row.id
            )
        ).first()
        if clash is not None:
            raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
        old_name = row.name
        moved = db.execute(
            Vehicle.__table__.update().where(Vehicle.category == old_name).values(category=body.name)
        ).rowcount
        row.name = body.name
        changes.append({"field": "name", "from": old_name, "to": body.name, "vehicles_moved": moved})
    if body.sort_order is not None and body.sort_order != row.sort_order:
        changes.append({"field": "sort_order", "from": row.sort_order, "to": body.sort_order})
        row.sort_order = body.sort_order
    if changes:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.VEHICLE_CATEGORY_UPSERT,
            change_payload={"category_id": row.id, "op": "update", "changes": changes},
        )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db))


@router.post("/reorder", response_model=list[VehicleCategoryOut])
def reorder_categories(
    body: VehicleCategoryReorder,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> list[VehicleCategoryOut]:
    """整份顺序一次提交：`ids[0]` 排最前（必须覆盖全部现存分类）。"""
    rows = db.scalars(select(VehicleCategory)).all()
    by_id = {r.id: r for r in rows}
    ids = ordered_ids(by_id, body.ids)
    for idx, cid in enumerate(ids):
        by_id[cid].sort_order = idx
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.VEHICLE_CATEGORY_REORDER,
        change_payload={"order": [{"id": i, "name": by_id[i].name} for i in ids]},
    )
    db.commit()
    counts = _counts(db)
    return [_out(by_id[i], counts) for i in ids]


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    current: User = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    """删除分类名册里的一行。**还有车挂着时拒绝**（告诉有几辆）。"""
    row = db.get(VehicleCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    used = db.scalar(select(func.count(Vehicle.id)).where(Vehicle.category == row.name)) or 0
    if used:
        raise HTTPException(
            status_code=400,
            detail=f"还有 {used} 辆车挂在这个分类下，先把它们改成别的分类（或改个名）再删",
        )
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.VEHICLE_CATEGORY_DELETE,
        change_payload={"category_id": row.id, "name": row.name},
    )
    db.delete(row)
    db.commit()
