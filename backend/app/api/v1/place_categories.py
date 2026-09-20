"""地点分类名册（**按人分区**）：地址库左侧那一列叫哪些名字、按什么顺序。

与 `api/v1/product_categories.py` 是**同一个做法**（名册管顺序、字符串管归属、
改名级联、整份顺序提交幂等），差在两处：

1. **按人分区**：商品分类是全店一份；地点库是每个人自己那一份
   （`shipper_locations.shipper_id` 就是"这个人自己的库"），
   所以每个端点都只碰 `current.id` 那一行 —— 否则货主 A 建的分类会出现在货主 B 的库里。
2. **谁能改**：商品分类要 `PRODUCT_MANAGE`（派单员）；地点库是**货主和派单员都有的功能**
   （`ShipperOrDispatcher`），所以这里也放给这两种角色 —— 用户 2026-09-19 原话
   「地点库的分类**包括货主和派单员**，他们都可以自行的添加分类也可以进行分类的管理」。
   司机没有地点库，进来会被 `ShipperOrDispatcher` 挡掉。

⚠️ 删除分类**还有地点挂着时拒绝**（与商品分类同一条纪律）：不"顺手把那些地点改成未分类"
—— 用户点的是"删掉这个分类"，不是"把 12 个地点的分类清掉"，而且清完在界面上看不出来。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_roles
from app.models import OperationAction, PlaceCategory, ShipperLocation, User
from app.models.enums import UserRole
from app.schemas.place_category import (
    PlaceCategoryCreate,
    PlaceCategoryOut,
    PlaceCategoryReorder,
    PlaceCategoryUpdate,
)
from app.services.category_order import ordered_ids
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/place-categories", tags=["place-categories"])

#: 谁能管地点分类：**货主和派单员**（司机没有地点库）。
#: 与 `api/v1/shipper.py` 的 `ShipperOrDispatcher` 是同一个角色集合 —— 因为地点库就是同一批人在用。
PlaceOwner = Annotated[User, Depends(require_roles(UserRole.SHIPPER, UserRole.DISPATCHER))]

#: 一个人最多几个分类（与商品分类同一个上限）。超了先让他清理，而不是随便长。
MAX_CATEGORIES = 200


def _counts(db: Session, owner_id: int) -> dict[str, int]:
    """分类名 → 在用地点数（**一次查完**，不要每个分类查一遍）。"""
    rows = db.execute(
        select(ShipperLocation.category, func.count(ShipperLocation.id))
        .where(
            ShipperLocation.shipper_id == owner_id,
            ShipperLocation.is_deleted.is_(False),
        )
        .group_by(ShipperLocation.category)
    ).all()
    return {(name or "").strip(): n for name, n in rows if (name or "").strip()}


def _out(row: PlaceCategory, counts: dict[str, int]) -> PlaceCategoryOut:
    o = PlaceCategoryOut.model_validate(row)
    o.location_count = counts.get(row.name, 0)
    return o


def _next_sort(db: Session, owner_id: int) -> int:
    top = db.scalar(
        select(func.max(PlaceCategory.sort_order)).where(PlaceCategory.shipper_id == owner_id)
    )
    return (top or 0) + 1


def ensure_place_category(db: Session, owner_id: int, name: str) -> PlaceCategory | None:
    """确保这个分类名在该用户的名册里（不在就补到最后）。

    给地点创建/修改复用（用户在编辑地点时直接敲一个新分类名 = 顺手建了它）。
    返回被新建的名册行；已经在名册里则返回 None。
    """
    clean = (name or "").strip()[:32]
    if not clean:
        return None
    exists = db.scalars(
        select(PlaceCategory).where(
            PlaceCategory.shipper_id == owner_id, PlaceCategory.name == clean
        )
    ).first()
    if exists is not None:
        return None
    row = PlaceCategory(shipper_id=owner_id, name=clean, sort_order=_next_sort(db, owner_id))
    db.add(row)
    db.flush()
    return row


@router.get("", response_model=list[PlaceCategoryOut])
def list_categories(current: PlaceOwner, db: Session = Depends(get_db)) -> list[PlaceCategoryOut]:
    """**自己那一份**分类名册（按显示顺序）。司机没有地点库，拿不到。"""
    rows = db.scalars(
        select(PlaceCategory)
        .where(PlaceCategory.shipper_id == current.id)
        .order_by(PlaceCategory.sort_order, PlaceCategory.id)
    ).all()
    counts = _counts(db, current.id)
    return [_out(r, counts) for r in rows]


@router.post("", response_model=PlaceCategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: PlaceCategoryCreate,
    current: PlaceOwner,
    db: Session = Depends(get_db),
) -> PlaceCategoryOut:
    exists = db.scalars(
        select(PlaceCategory).where(
            PlaceCategory.shipper_id == current.id, PlaceCategory.name == body.name
        )
    ).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
    total = db.scalar(
        select(func.count(PlaceCategory.id)).where(PlaceCategory.shipper_id == current.id)
    ) or 0
    if total >= MAX_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"分类最多 {MAX_CATEGORIES} 个，请先清理一些")
    row = PlaceCategory(
        shipper_id=current.id,
        name=body.name,
        sort_order=body.sort_order if body.sort_order is not None else _next_sort(db, current.id),
    )
    db.add(row)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PLACE_CATEGORY_UPSERT,
        change_payload={"category_id": row.id, "name": row.name, "sort_order": row.sort_order, "op": "create"},
    )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db, current.id))


@router.patch("/{category_id}", response_model=PlaceCategoryOut)
def update_category(
    category_id: int,
    body: PlaceCategoryUpdate,
    current: PlaceOwner,
    db: Session = Depends(get_db),
) -> PlaceCategoryOut:
    """改名 / 改顺序。**改名会级联改掉挂在这一类下的地点**（同一事务）。"""
    row = db.get(PlaceCategory, category_id)
    if row is None or row.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    changes: list[dict] = []
    if body.name is not None and body.name != row.name:
        clash = db.scalars(
            select(PlaceCategory).where(
                PlaceCategory.shipper_id == current.id,
                PlaceCategory.name == body.name,
                PlaceCategory.id != row.id,
            )
        ).first()
        if clash is not None:
            raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
        old_name = row.name
        # ⚠️ **软删的地点也要一起改名**：那是"伪装删除"（行还在库里、回收站里能恢复），
        #    不跟着改的话，恢复出来的那条会挂着一个已经不存在的分类名（左侧多出一格）。
        moved = db.execute(
            ShipperLocation.__table__.update()
            .where(ShipperLocation.shipper_id == current.id, ShipperLocation.category == old_name)
            .values(category=body.name)
        ).rowcount
        row.name = body.name
        changes.append({"field": "name", "from": old_name, "to": body.name, "locations_moved": moved})
    if body.sort_order is not None and body.sort_order != row.sort_order:
        changes.append({"field": "sort_order", "from": row.sort_order, "to": body.sort_order})
        row.sort_order = body.sort_order
    if changes:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.PLACE_CATEGORY_UPSERT,
            change_payload={"category_id": row.id, "op": "update", "changes": changes},
        )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db, current.id))


@router.post("/reorder", response_model=list[PlaceCategoryOut])
def reorder_categories(
    body: PlaceCategoryReorder,
    current: PlaceOwner,
    db: Session = Depends(get_db),
) -> list[PlaceCategoryOut]:
    """整份顺序一次提交：`ids[0]` 排最前。**必须覆盖自己全部现存分类**（理由同商品分类：
    只传一部分的话"没提到的那些该排哪儿"没有答案）。"""
    rows = db.scalars(select(PlaceCategory).where(PlaceCategory.shipper_id == current.id)).all()
    by_id = {r.id: r for r in rows}
    # 整份顺序的校验四个名册共用一份（**不区分"编号不存在"与"不是你的"**，
    # 免得把"这个编号存不存在"变成一条可以探测的信息 —— 理由见 services/category_order.py）
    ids = ordered_ids(by_id, body.ids)
    for idx, cid in enumerate(ids):
        by_id[cid].sort_order = idx
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PLACE_CATEGORY_REORDER,
        change_payload={"order": [{"id": i, "name": by_id[i].name} for i in ids]},
    )
    db.commit()
    counts = _counts(db, current.id)
    return [_out(by_id[i], counts) for i in ids]


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    current: PlaceOwner,
    db: Session = Depends(get_db),
) -> None:
    """删掉自己名册里的一行。**还有地点挂着时拒绝**（告诉有几条）。"""
    row = db.get(PlaceCategory, category_id)
    if row is None or row.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    used = db.scalar(
        select(func.count(ShipperLocation.id)).where(
            ShipperLocation.shipper_id == current.id,
            ShipperLocation.category == row.name,
            ShipperLocation.is_deleted.is_(False),
        )
    ) or 0
    if used:
        raise HTTPException(
            status_code=400,
            detail=f"还有 {used} 个地点挂在这个分类下，先把它们改成别的分类（或改个名）再删",
        )
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PLACE_CATEGORY_DELETE,
        change_payload={"category_id": row.id, "name": row.name},
    )
    db.execute(sa_delete(PlaceCategory).where(PlaceCategory.id == row.id))
    db.commit()
