from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.rbac import Permission, user_role_key
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import Notification, User
from app.models.enums import UserRole
from app.schemas.notification import (
    NotificationBatchDeleteBody,
    NotificationCreate,
    NotificationOut,
    NotificationUpdate,
)
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
    days: int = Query(30, ge=1, le=365, description="仅返回最近 N 天消息，并顺带物理清理超过 N 天的消息（默认30）"),
) -> list[Notification]:
    """消息列表。

    ### 默认只看**自己的**（v3.32 修正了一个"清空之后消息会复活"的 bug）
    这里原来是 `if 派单员: if recipient_id: … else: 按自己` ——那个 `else` 挂在**内层** if 上，
    于是派单员**不带 recipient_id** 时一个收件人过滤都不加，返回**所有人的消息**。
    后果不是"多看到一个列表"，而是三处口径互相打架：

    1. **清空清不掉**：界面上的「清空」走 `batch-delete`，而它按
       `target = recipient_id if (派单员 and 指定了) else current.id`——**只删自己的**。
       列表却还显示着别人的消息，客户端又把"删完"当成 `messages = emptyList()` 乐观置空，
       于是界面上看着清空了、**重启后重新拉取又全回来**。
    2. **点了没反应**：`POST /{id}/read` 与 `DELETE /{id}` 只认自己的（别人的 404/403），
       列表里那些别人的消息点了标记已读会静默失败（客户端吞掉异常）。
    3. **角标对不上**：`unread-count` 数的从来都是自己的，与列表条数永远不一致。

    现在与 `batch-delete` 使用**同一套口径**：默认自己；派单员可以显式带 `recipient_id`
    查看某个账户的消息（消息中心全局视图要保留时，必须由调用方**显式**指定看谁的）。
    """
    is_dispatcher = user_role_key(current) == UserRole.DISPATCHER.value
    target = recipient_id if (is_dispatcher and recipient_id is not None) else current.id

    # 消息保留期：由请求路径惰性清理实现，无任何服务器后台定时任务
    # （客户端未来做本地缓存/离线查看时，联网任一请求即触发过期清理，不影响离线快照）
    #
    # ⚠️ 惰性清理只清**这次看得到的那个账户**的过期消息：读一个人的列表，
    #    不该顺手把别人的行删掉（全局保留期由 data_retention.purge_expired_notifications 每日负责）。
    cutoff = datetime.now() - timedelta(days=days)
    purge = delete(Notification).where(
        Notification.recipient_id == target, Notification.created_at < cutoff
    )
    try:
        db.execute(purge)
        db.commit()
    except Exception:
        db.rollback()  # 清理失败不影响查询；查询仍然按保留期过滤
    q = (
        select(Notification)
        .where(Notification.recipient_id == target, Notification.created_at >= cutoff)
        .order_by(Notification.id.desc())
    )
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


@router.post("/batch-delete", response_model=dict)
def batch_delete_notifications(
    body: NotificationBatchDeleteBody,
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """批量删除消息：ids 指定列表，或 all=true 清空该账户全部消息（二选一）。
    默认仅本人消息；派单员可带 recipient_id 指定其他用户。"""
    if body.ids and body.all:
        raise HTTPException(status_code=400, detail="ids 与 all 不能同时使用")
    is_disp = user_role_key(current) == UserRole.DISPATCHER.value
    if body.recipient_id is not None and not is_disp:
        raise HTTPException(status_code=403, detail="无权删除他人消息")
    target = body.recipient_id if (is_disp and body.recipient_id is not None) else current.id
    if body.ids:
        dq = delete(Notification).where(
            Notification.recipient_id == target, Notification.id.in_(body.ids)
        )
    else:
        dq = delete(Notification).where(Notification.recipient_id == target)
    result = db.execute(dq)
    db.commit()
    background_tasks.add_task(_bg_emit_unread, target)
    return {"deleted": result.rowcount}


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
