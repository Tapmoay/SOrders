from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission, user_role_key
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import Notification, User
from app.models.enums import UserRole
from app.schemas.notification import NotificationCreate, NotificationOut, NotificationUpdate
from app.schemas.price_notify import PriceChangeNotifyBody
from app.services.message_center import emit_notification, emit_unread_count

router = APIRouter(prefix="/notifications", tags=["notifications"])


async def _bg_emit_unread(user_id: int) -> None:
    await emit_unread_count(user_id)


@router.get("/unread-count")
def unread_count(current: CurrentUser, db: Session = Depends(get_db)) -> dict[str, int]:
    from app.services.message_center import count_unread

    n = count_unread(db, current.id)
    return {"count": n}


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    current: CurrentUser,
    db: Session = Depends(get_db),
    unread_only: bool = False,
    recipient_id: int | None = None,
    category: str | None = Query(None, description="system | order | reminder"),
) -> list[Notification]:
    q = select(Notification).order_by(Notification.id.desc())
    if user_role_key(current) == UserRole.DISPATCHER.value:
        if recipient_id is not None:
            q = q.where(Notification.recipient_id == recipient_id)
    else:
        q = q.where(Notification.recipient_id == current.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    if category:
        q = q.where(Notification.category == category)
    q = q.limit(200)
    return list(db.scalars(q).all())


@router.post("/price-notify", response_model=list[NotificationOut], status_code=status.HTTP_201_CREATED)
def notify_price_change(
    body: PriceChangeNotifyBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.NOTIFICATION_MANAGE)),
) -> list[Notification]:
    """派单员：价格变更后向选定货主发送站内通知并推送 Socket。"""
    out: list[Notification] = []
    type_label = "默认价" if body.price_type == "default" else "特殊价"
    old_s = str(body.old_price) if body.old_price is not None else "—"
    title = f"商品价格调整：{body.product_name}"
    content = (
        f"商品「{body.product_name}」的{type_label}已更新：{old_s} → {body.new_price}。"
        f"如有疑问请联系派单员。"
    )
    for sid in body.shipper_ids:
        n = Notification(
            recipient_id=sid,
            category="reminder",
            type="price_change",
            title=title,
            content=content,
            speech_important=False,
            payload={
                "product_id": body.product_id,
                "product_name": body.product_name,
                "price_type": body.price_type,
                "old_price": old_s,
                "new_price": str(body.new_price),
                "product_image_url": body.product_image_url,
            },
        )
        db.add(n)
        out.append(n)
    db.commit()
    for n in out:
        db.refresh(n)
        background_tasks.add_task(emit_notification, n)
    return out


@router.post("", response_model=NotificationOut, status_code=status.HTTP_201_CREATED)
def create_notification(
    body: NotificationCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.NOTIFICATION_MANAGE)),
) -> Notification:
    n = Notification(
        recipient_id=body.recipient_id,
        category=body.category,
        type=body.type,
        title=body.title,
        content=body.content,
        payload=body.payload,
        speech_important=body.speech_important,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    background_tasks.add_task(emit_notification, n)
    return n


@router.post("/read-all", response_model=dict)
def mark_all_read(
    current: CurrentUser,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    q = select(Notification).where(
        Notification.recipient_id == current.id,
        Notification.read_at.is_(None),
    )
    rows = list(db.scalars(q).all())
    now = datetime.now(timezone.utc)
    for n in rows:
        n.read_at = now
    db.commit()
    background_tasks.add_task(_bg_emit_unread, current.id)
    return {"updated": len(rows)}


@router.get("/{notification_id}", response_model=NotificationOut)
def get_notification(notification_id: int, current: CurrentUser, db: Session = Depends(get_db)) -> Notification:
    n = db.get(Notification, notification_id)
    if n is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if n.recipient_id != current.id and user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="无权访问")
    return n


@router.patch("/{notification_id}", response_model=NotificationOut)
def update_notification(
    notification_id: int,
    body: NotificationUpdate,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> Notification:
    n = db.get(Notification, notification_id)
    if n is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if n.recipient_id != current.id and user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="无权访问")
    if body.title is not None:
        n.title = body.title
    if body.content is not None:
        n.content = body.content
    if body.payload is not None:
        n.payload = body.payload
    db.commit()
    db.refresh(n)
    return n


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(
    notification_id: int,
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    n = db.get(Notification, notification_id)
    if n is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if n.recipient_id != current.id and user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="无权访问")
    rid = n.recipient_id
    db.delete(n)
    db.commit()
    background_tasks.add_task(_bg_emit_unread, rid)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> Notification:
    n = db.get(Notification, notification_id)
    if n is None or n.recipient_id != current.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到对应记录")
    n.read_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(n)
    background_tasks.add_task(_bg_emit_unread, current.id)
    return n
