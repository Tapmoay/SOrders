"""线路分类名册（**按人分区**）：线路列表左侧那一列叫哪些名字、按什么顺序。

与 `api/v1/contact_categories.py` / `api/v1/place_categories.py` 是**同一个做法**（名册管顺序、
字符串管归属、改名级联、整份顺序提交幂等、还有东西挂着时不许删），差在**归属那一格挂在谁身上**：

| | 地点分类 | 线路分类 |
|---|---|---|
| 归属那一格 | `shipper_locations.category` | `shipper_addresses.category` |
| 谁在用 | 货主 / 派单员（司机没有地点库） | 货主 / 派单员（司机也没有线路库） |
| 删除时挡谁 | 还有地点挂着 → 400 | 还有线路挂着 → 400 |

⚠️ **谁能改**：与 `api/v1/shipper.py` 的线路端点**同一个角色门**
（`ShipperOrDispatcher`：货主 + 派单员）。批发商在本仓库就是**货主**（见
`models/shipper_settlement.py` 开头），没有独立角色，所以这一个门就是用户说的三种身份。
司机没有线路库，进来会被挡住。

⚠️ 删除分类**还有线路挂着时拒绝**（与地点/商品分类同一条纪律）：不"顺手把那些线路改成未分类"
—— 用户点的是"删掉这个分类"，不是"把 12 条线路的分类清掉"，而且清完在界面上看不出来。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_roles
from app.models import RouteCategory, OperationAction, ShipperAddress, User
from app.models.enums import UserRole
from app.schemas.route_category import (
    RouteCategoryCreate,
    RouteCategoryOut,
    RouteCategoryReorder,
    RouteCategoryUpdate,
)
from app.services.category_order import ordered_ids
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/route-categories", tags=["route-categories"])

#: 谁能管线路分类：**货主（含批发商）和派单员**（司机没有线路库）。
#: 与 `api/v1/shipper.py` 的 `ShipperOrDispatcher` 是同一个角色集合 —— 线路库就是同一批人在用。
RouteOwner = Annotated[User, Depends(require_roles(UserRole.SHIPPER, UserRole.DISPATCHER))]

#: 一个人最多几个分类（与地点/商品分类同一个上限）。超了先让他清理，而不是随便长。
MAX_CATEGORIES = 200


def _counts(db: Session, owner_id: int) -> dict[str, int]:
    """分类名 → 在用线路数（**一次查完**，不要每个分类查一遍）。"""
    rows = db.execute(
        select(ShipperAddress.category, func.count(ShipperAddress.id))
        .where(
            ShipperAddress.shipper_id == owner_id,
            ShipperAddress.is_deleted.is_(False),
        )
        .group_by(ShipperAddress.category)
    ).all()
    return {(name or "").strip(): n for name, n in rows if (name or "").strip()}


def _out(row: RouteCategory, counts: dict[str, int]) -> RouteCategoryOut:
    o = RouteCategoryOut.model_validate(row)
    o.address_count = counts.get(row.name, 0)
    return o


def _next_sort(db: Session, owner_id: int) -> int:
    top = db.scalar(
        select(func.max(RouteCategory.sort_order)).where(RouteCategory.shipper_id == owner_id)
    )
    return (top or 0) + 1


def ensure_route_category(db: Session, owner_id: int, name: str) -> RouteCategory | None:
    """确保这个分类名在该用户的名册里（不在就补到最后）。

    给线路创建/修改复用（用户在编辑线路时直接敲一个新分类名 = 顺手建了它）。
    返回被新建的名册行；已经在名册里则返回 None。
    """
    clean = (name or "").strip()[:32]
    if not clean:
        return None
    exists = db.scalars(
        select(RouteCategory).where(
            RouteCategory.shipper_id == owner_id, RouteCategory.name == clean
        )
    ).first()
    if exists is not None:
        return None
    row = RouteCategory(shipper_id=owner_id, name=clean, sort_order=_next_sort(db, owner_id))
    db.add(row)
    db.flush()
    return row


@router.get("", response_model=list[RouteCategoryOut])
def list_categories(current: RouteOwner, db: Session = Depends(get_db)) -> list[RouteCategoryOut]:
    """**自己那一份**分类名册（按显示顺序）。司机没有线路库，拿不到。"""
    rows = db.scalars(
        select(RouteCategory)
        .where(RouteCategory.shipper_id == current.id)
        .order_by(RouteCategory.sort_order, RouteCategory.id)
    ).all()
    counts = _counts(db, current.id)
    return [_out(r, counts) for r in rows]


@router.post("", response_model=RouteCategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: RouteCategoryCreate,
    current: RouteOwner,
    db: Session = Depends(get_db),
) -> RouteCategoryOut:
    exists = db.scalars(
        select(RouteCategory).where(
            RouteCategory.shipper_id == current.id, RouteCategory.name == body.name
        )
    ).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
    total = db.scalar(
        select(func.count(RouteCategory.id)).where(RouteCategory.shipper_id == current.id)
    ) or 0
    if total >= MAX_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"分类最多 {MAX_CATEGORIES} 个，请先清理一些")
    row = RouteCategory(
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
        action=OperationAction.ROUTE_CATEGORY_UPSERT,
        change_payload={"category_id": row.id, "name": row.name, "sort_order": row.sort_order, "op": "create"},
    )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db, current.id))


@router.patch("/{category_id}", response_model=RouteCategoryOut)
def update_category(
    category_id: int,
    body: RouteCategoryUpdate,
    current: RouteOwner,
    db: Session = Depends(get_db),
) -> RouteCategoryOut:
    """改名 / 改顺序。**改名会级联改掉挂在这一类下的线路**（同一事务）。"""
    row = db.get(RouteCategory, category_id)
    if row is None or row.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    changes: list[dict] = []
    if body.name is not None and body.name != row.name:
        clash = db.scalars(
            select(RouteCategory).where(
                RouteCategory.shipper_id == current.id,
                RouteCategory.name == body.name,
                RouteCategory.id != row.id,
            )
        ).first()
        if clash is not None:
            raise HTTPException(status_code=409, detail=f"分类「{body.name}」已经存在了")
        old_name = row.name
        # ⚠️ **软删的线路也要一起改名**：那是"伪装删除"（行还在库里、回收站里能恢复），
        #    不跟着改的话，恢复出来的那条会挂着一个已经不存在的分类名（左侧多出一格）。
        moved = db.execute(
            ShipperAddress.__table__.update()
            .where(ShipperAddress.shipper_id == current.id, ShipperAddress.category == old_name)
            .values(category=body.name)
        ).rowcount
        row.name = body.name
        changes.append({"field": "name", "from": old_name, "to": body.name, "addresses_moved": moved})
    if body.sort_order is not None and body.sort_order != row.sort_order:
        changes.append({"field": "sort_order", "from": row.sort_order, "to": body.sort_order})
        row.sort_order = body.sort_order
    if changes:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.ROUTE_CATEGORY_UPSERT,
            change_payload={"category_id": row.id, "op": "update", "changes": changes},
        )
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db, current.id))


@router.post("/reorder", response_model=list[RouteCategoryOut])
def reorder_categories(
    body: RouteCategoryReorder,
    current: RouteOwner,
    db: Session = Depends(get_db),
) -> list[RouteCategoryOut]:
    """整份顺序一次提交：`ids[0]` 排最前。**必须覆盖自己全部现存分类**（理由同地点分类：
    只传一部分的话"没提到的那些该排哪儿"没有答案）。"""
    rows = db.scalars(select(RouteCategory).where(RouteCategory.shipper_id == current.id)).all()
    by_id = {r.id: r for r in rows}
    # 整份顺序的校验五个名册共用一份（**不区分"编号不存在"与"不是你的"**，
    # 免得把"这个编号存不存在"变成一条可以探测的信息 —— 理由见 services/category_order.py）
    ids = ordered_ids(by_id, body.ids)
    for idx, cid in enumerate(ids):
        by_id[cid].sort_order = idx
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.ROUTE_CATEGORY_REORDER,
        change_payload={"order": [{"id": i, "name": by_id[i].name} for i in ids]},
    )
    db.commit()
    counts = _counts(db, current.id)
    return [_out(by_id[i], counts) for i in ids]


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    current: RouteOwner,
    db: Session = Depends(get_db),
) -> None:
    """删掉自己名册里的一行。**还有线路挂着时拒绝**（告诉有几条）。"""
    row = db.get(RouteCategory, category_id)
    if row is None or row.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    used = db.scalar(
        select(func.count(ShipperAddress.id)).where(
            ShipperAddress.shipper_id == current.id,
            ShipperAddress.category == row.name,
            ShipperAddress.is_deleted.is_(False),
        )
    ) or 0
    if used:
        raise HTTPException(
            status_code=400,
            detail=f"还有 {used} 条线路挂在这个分类下，先把它们改成别的分类（或改个名）再删",
        )
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.ROUTE_CATEGORY_DELETE,
        change_payload={"category_id": row.id, "name": row.name},
    )
    db.execute(sa_delete(RouteCategory).where(RouteCategory.id == row.id))
    db.commit()
