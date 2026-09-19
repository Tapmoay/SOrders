"""共享地点库（导航信息）接口。

## 谁能看、谁能写
- **看**：三种角色都可以。这不是疏忽——用户 2026-09-18 明确要求
  "所有导航信息我们都有共同的库，方便下次有人比如说他也是相同的位置，那直接拉过来，
  省的每个人都要手动上传一次"。所以这张表**刻意不按人分区**。
  （代价要说清楚：货主 A 能看到货主 B 录入过的地点名与地址。这是需求本身要的效果，
  不是漏配权限；反过来，如果按人分区，"相同位置直接拉过来"就不成立了。）
- **写**：`POST /places` 三种角色都可以（自己录一个点）；
  给**订单**补导航是 `POST /orders/{id}/navigation`，只允许该单司机或派单员（见那边）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.pagination import finish_page
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser, require_roles
from app.models import Place, User
from app.models.enums import UserRole
from app.core.rbac import user_role_key
from app.models.enums import OperationAction, UserRole
from app.schemas.place import PlaceCreate, PlaceDemoteOut, PlaceOut, PlaceUpdate, PlaceUseOut
from app.services import place_service
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/places", tags=["places"])

#: 列表最多回多少条。共享库会一直长，不设上限的话货主换个地址要滚几百屏。
MAX_LIST = 200


@router.get("", response_model=list[PlaceOut])
def list_places(
    current: CurrentUser,
    response: Response,
    db: Session = Depends(get_db),
    q: str | None = Query(None, description="按地点名/地址模糊匹配（不传=常用在前）"),
    limit: int = Query(100, ge=1, le=MAX_LIST),
) -> list[Place]:
    stmt = select(Place)
    keyword = (q or "").strip()
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Place.name.like(like), Place.detail_address.like(like)))
    # 常用在前（use_count 是"有多少人沿用/录过这个点"），同频次按新近
    # 多取一行判截断（2026-09-19 外部完整检查 §9.1）：共享库会一直长，
    # 不说"还有更多"的话用户会以为"这个点大家都没录过"。
    stmt = stmt.order_by(Place.use_count.desc(), Place.id.desc()).limit(limit + 1)
    return finish_page(list(db.scalars(stmt).all()), limit, response)


@router.post("", response_model=PlaceOut, status_code=status.HTTP_201_CREATED)
def create_place(
    body: PlaceCreate,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> PlaceOut:
    """往共享地点库加一个点；**坐标 ≤1 米内已有点时并入那一条**（不新建重复行）。

    返回体的 `merged` 字段说明这次是新建还是并入 —— 客户端要如实告诉用户，
    否则用户以为"多录了一个点"，而列表上什么都没变。
    """
    role = user_role_key(current)
    source = "shipper" if role == UserRole.SHIPPER.value else (
        "dispatcher" if role == UserRole.DISPATCHER.value else "driver"
    )
    place, merged = place_service.upsert_place(
        db,
        lat=float(body.address_lat),
        lng=float(body.address_lng),
        name=body.name,
        detail_address=body.detail_address,
        source=source,
        created_by=current.id,
    )
    db.commit()
    db.refresh(place)
    out = PlaceOut.model_validate(place)
    out.merged = merged
    return out


@router.post("/{place_id}/use", response_model=PlaceUseOut)
def use_place(place_id: int, current: CurrentUser, db: Session = Depends(get_db)) -> PlaceUseOut:
    """记一次"我用了这个共享地点"；**同一个人用到第 2 次就自动收进他自己的地点库**。

    用户 2026-09-18：
    > 常点的那个共享地点，有人经常点了，它就会自动移到他自己的地点库当中。

    判据与阈值都在 `place_service`（`AUTO_ADD_AFTER`）。这里只负责把结果**如实回报**：
    `auto_added=True` 时界面必须说一句"已加进「我的地点」"——静默帮用户改了他自己的库，
    他下次看到多出一条来源不明的记录只能猜。
    """
    place = db.get(Place, place_id)
    if place is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    count, added = place_service.note_place_use(db, user=current, place=place)
    if added:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.PLACE_AUTO_ADDED,
            change_payload={
                "place_id": place.id,
                "place_name": place.name,
                "use_count": count,
                "threshold": place_service.AUTO_ADD_AFTER,
                "note": "常用共享地点自动加入「我的地点」（判据见 place_service.AUTO_ADD_AFTER）",
            },
        )
    db.commit()
    return PlaceUseOut(use_count=count, auto_added=added, place_id=place.id)


@router.get("/{place_id}", response_model=PlaceOut)
def get_place(place_id: int, current: CurrentUser, db: Session = Depends(get_db)) -> Place:
    row = db.get(Place, place_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return row


# ===========================================================================
# 共享库的**管理**（2026-09-19 用户要求）：只有派单员能改 / 撤销 / 删除。
#
# 用户原话：
# > 这个地址是可以编辑的。如果是来到了共享库的话，共享地址的编辑**只有派单员**可以编辑，
# > 其他人都编辑不了。派单员可以改名称，也可以把一些地点给**设置为共享地址**，
# > 也可以**撤销**某些共享地址，把它**降为普通的地址**，或者直接**删掉**。
#
# 为什么权限只给派单员（而 `POST /places` 三种角色都能写）：`POST /places` 是"**记录一个点**"
# —— 司机在现场、货主在门口，谁有坐标谁就能补（用户 2026-09-18 要的就是这个）。
# 而改/撤销/删除动的是**别人也在用的那条记录**（这张表全库共用），所以要一个人负责。
# 三个动作各自的完整理由见 `services/place_service.py` 那几个函数。
# ===========================================================================

#: 谁能管共享库：**只有派单员**。
DispatcherOnly = Annotated[User, Depends(require_roles(UserRole.DISPATCHER))]


def _alive_place(db: Session, place_id: int) -> Place:
    row = db.get(Place, place_id)
    if row is None:
        raise HTTPException(status_code=404, detail="这个共享地点不存在（可能刚被别人删掉了）")
    return row


@router.patch("/{place_id}", response_model=PlaceOut)
def update_place(
    place_id: int,
    body: PlaceUpdate,
    current: DispatcherOnly,
    db: Session = Depends(get_db),
) -> Place:
    """改共享地址的名称 / 地址（**只有派单员**）。

    ⛔ 坐标**不给改**：这张表的每一条都是"某个坐标是哪儿"的事实，
    改坐标等于把一条别人核对过的导航信息指到另一个地方（司机照着走就是错的）；
    位置不对就删掉重新补一个点。
    """
    place = _alive_place(db, place_id)
    if body.name is None and body.detail_address is None:
        raise HTTPException(status_code=400, detail="没有要改的内容（名称和地址都没传）")
    try:
        before, after = place_service.apply_place_update(
            db, place, name=body.name, detail_address=body.detail_address
        )
    except ValueError as exc:
        # 判据来自 `place_service.identify_error`，那句话本来就是给用户看的
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if before != after:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.PLACE_UPDATE,
            change_payload={
                "place_id": place.id,
                "before": before,
                "after": after,
                "note": "共享地点库（全库共用）：改的是所有人都看得到的那一条",
            },
        )
    db.commit()
    db.refresh(place)
    return place


@router.post("/{place_id}/demote", response_model=PlaceDemoteOut)
def demote_place(
    place_id: int,
    current: DispatcherOnly,
    db: Session = Depends(get_db),
) -> PlaceDemoteOut:
    """**撤销**一个共享地址 → 降为**操作人自己**的普通地点（叫「我的地点」）。

    两件事同一个事务：① 按同一条合并判据（`place_service`）写进**他**的地点库；
    ② 把共享库那条删掉（"其他的不会显示"）。返回落在他库里的那一条 + 是否新建。
    """
    place = _alive_place(db, place_id)
    snapshot = {
        "place_id": place.id,
        "name": place.name,
        "detail_address": place.detail_address,
        "address_lat": str(place.lat),
        "address_lng": str(place.lng),
        "source": place.source,
    }
    loc, created = place_service.demote_place(db, place=place, operator_id=current.id)
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PLACE_DEMOTE,
        change_payload={
            **snapshot,
            "location_id": loc.id,
            "created": created,
            "note": "共享地址撤销 → 存进操作人自己的「我的地点」；共享库里这一条已删除",
        },
    )
    db.commit()
    # commit 之后 `place` 已经是删除态、`loc` 还在 session 里，id 要先取出来
    return PlaceDemoteOut(place_id=place_id, location_id=loc.id, created=created)


@router.delete("/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_place(place_id: int, current: DispatcherOnly, db: Session = Depends(get_db)) -> Response:
    """从共享库**删掉**一个地点（只有派单员）。

    ⚠️ 这是**物理删除**（与主数据那套软删不同，理由见 `place_service.delete_place`），
    所以删除前先把整行写进审计日志 —— 事后要能回答"删的是哪一条、谁删的"。
    """
    place = _alive_place(db, place_id)
    snapshot = {
        "place_id": place.id,
        "name": place.name,
        "detail_address": place.detail_address,
        "address_lat": str(place.lat),
        "address_lng": str(place.lng),
        "source": place.source,
        "use_count": place.use_count,
    }
    place_service.delete_place(db, place)
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PLACE_DELETE,
        change_payload={**snapshot, "note": "共享地点库里的这一条被删除（物理删除，内容见本行）"},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
