"""消息中心：持久化通知 + Socket.IO 推送。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Notification, Order, User
from app.schemas.notification import NotificationOut
from app.services.message_push import emit_to_user


def count_unread(db: Session, recipient_id: int) -> int:
    q = select(func.count()).select_from(Notification).where(
        Notification.recipient_id == recipient_id,
        Notification.read_at.is_(None),
    )
    return int(db.scalar(q) or 0)


def create_message(
    db: Session,
    *,
    recipient_id: int,
    category: str,
    type: str,
    title: str,
    content: str,
    payload: dict[str, Any] | None = None,
    speech_important: bool = False,
) -> Notification:
    n = Notification(
        recipient_id=recipient_id,
        category=category,
        type=type,
        title=title,
        content=content,
        payload=payload,
        speech_important=speech_important,
    )
    db.add(n)
    db.flush()
    return n


async def emit_notification(n: Notification) -> None:
    data = NotificationOut.model_validate(n).model_dump(mode="json")
    await emit_to_user(n.recipient_id, "notification", {"notification": data})
    await emit_unread_count(n.recipient_id)


async def emit_unread_count(recipient_id: int) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        c = count_unread(db, recipient_id)
    finally:
        db.close()
    await emit_to_user(recipient_id, "unread_count", {"count": c})


async def emit_realtime(user_id: int, payload: dict[str, Any]) -> None:
    await emit_to_user(user_id, "realtime", payload)


def _user_label(db: Session, uid: int | None) -> str:
    if not uid:
        return ""
    u = db.get(User, uid)
    if not u:
        return ""
    return (u.full_name or u.phone or str(uid)).strip()


async def publish_order_assigned(db: Session, order_id: int) -> None:
    order = db.get(Order, order_id)
    if order is None:
        return
    ono = order.order_no
    driver_id = order.driver_id
    if not driver_id:
        return
    shipper_id = order.shipper_id
    ns: list[Notification] = []
    ns.append(
        create_message(
            db,
            recipient_id=driver_id,
            category="order",
            type="order.assigned",
            title="新派单",
            content=f"您有新的派单：{ono}，请及时处理。",
            payload={"order_id": order_id, "order_no": ono},
            speech_important=True,
        )
    )
    if shipper_id is not None:
        ns.append(
            create_message(
                db,
                recipient_id=shipper_id,
                category="order",
                type="order.dispatched",
                title="订单已派单",
                content=f"订单 {ono} 已指派司机。",
                payload={"order_id": order_id, "order_no": ono},
                speech_important=False,
            )
        )
    db.commit()
    for n in ns:
        db.refresh(n)
        await emit_notification(n)
    await emit_realtime(driver_id, {"type": "order.assigned", "order_id": order_id})
    if shipper_id is not None:
        await emit_realtime(shipper_id, {"type": "order.dispatched", "order_id": order_id})


async def publish_order_revoked(db: Session, driver_id: int, order_id: int, reason: str) -> None:
    order = db.get(Order, order_id)
    ono = order.order_no if order else str(order_id)
    n = create_message(
        db,
        recipient_id=driver_id,
        category="order",
        type="order.revoked",
        title="订单已撤回",
        content=f"订单 {ono} 已被撤回" + (f"：{reason}" if reason.strip() else "。"),
        payload={"order_id": order_id, "order_no": ono, "reason": reason},
        speech_important=True,
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(driver_id, {"type": "order.revoked", "order_id": order_id, "reason": reason})


async def publish_order_recalled_shipper(db: Session, shipper_id: int, order_id: int) -> None:
    order = db.get(Order, order_id)
    ono = order.order_no if order else str(order_id)
    n = create_message(
        db,
        recipient_id=shipper_id,
        category="order",
        type="order.recalled",
        title="派单已撤回",
        content=f"订单 {ono} 的派单已由派单员撤回。",
        payload={"order_id": order_id, "order_no": ono},
        speech_important=False,
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(shipper_id, {"type": "order.recalled", "order_id": order_id})


async def publish_order_delivered(db: Session, shipper_id: int, order_id: int) -> None:
    order = db.get(Order, order_id)
    ono = order.order_no if order else str(order_id)
    n = create_message(
        db,
        recipient_id=shipper_id,
        category="order",
        type="order.delivered",
        title="订单已送达",
        content=f"订单 {ono} 已完成送达。",
        payload={"order_id": order_id, "order_no": ono},
        speech_important=False,
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(shipper_id, {"type": "order.delivered", "order_id": order_id})


async def publish_order_cancelled(db: Session, shipper_id: int, order_id: int) -> None:
    order = db.get(Order, order_id)
    ono = order.order_no if order else str(order_id)
    n = create_message(
        db,
        recipient_id=shipper_id,
        category="order",
        type="order.cancelled",
        title="订单已取消",
        content=f"订单 {ono} 已取消。",
        payload={"order_id": order_id, "order_no": ono},
        speech_important=True,
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(shipper_id, {"type": "order.cancelled", "order_id": order_id})


async def publish_driver_ack_shipper(db: Session, shipper_id: int, order_id: int) -> None:
    order = db.get(Order, order_id)
    ono = order.order_no if order else str(order_id)
    driver_name = _user_label(db, order.driver_id if order else None)
    n = create_message(
        db,
        recipient_id=shipper_id,
        category="order",
        type="order.driver_ack",
        title="司机已接单",
        content=f"订单 {ono} 已由司机{driver_name or ''}确认。",
        payload={"order_id": order_id, "order_no": ono},
        speech_important=False,
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(shipper_id, {"type": "order.driver_ack", "order_id": order_id})


async def publish_order_cancelled_multi(db: Session, user_ids: list[int], order_id: int) -> None:
    if not user_ids:
        return
    order = db.get(Order, order_id)
    ono = order.order_no if order else str(order_id)
    ns: list[Notification] = []
    for uid in user_ids:
        ns.append(
            create_message(
                db,
                recipient_id=uid,
                category="order",
                type="order.cancelled",
                title="订单已取消",
                content=f"订单 {ono} 已取消。",
                payload={"order_id": order_id, "order_no": ono},
                speech_important=True,
            )
        )
    db.commit()
    for n in ns:
        db.refresh(n)
        await emit_notification(n)
    for uid in user_ids:
        await emit_realtime(uid, {"type": "order.cancelled", "order_id": order_id})


async def publish_ledger_updated_event(shipper_id: int) -> None:
    """仅实时刷新账本列表（不额外落库，避免每条编辑一条消息）。"""
    await emit_realtime(shipper_id, {"type": "ledger.updated"})
