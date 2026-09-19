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

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser
from app.models import Place
from app.models.enums import UserRole
from app.core.rbac import user_role_key
from app.models.enums import OperationAction, UserRole
from app.schemas.place import PlaceCreate, PlaceOut, PlaceUseOut
from app.services import place_service
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/places", tags=["places"])

#: 列表最多回多少条。共享库会一直长，不设上限的话货主换个地址要滚几百屏。
MAX_LIST = 200


@router.get("", response_model=list[PlaceOut])
def list_places(
    current: CurrentUser,
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
    stmt = stmt.order_by(Place.use_count.desc(), Place.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


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
