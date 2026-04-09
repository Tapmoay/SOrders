"""Socket.IO 长连接（与 FastAPI 组合为 ASGI）。业务侧通过 emit_to_user 推送。"""

from __future__ import annotations

from typing import Any

import socketio
from jose import JWTError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.database import SessionLocal
from app.models import Notification, User
from app.models.enums import UserRole
from app.schemas.notification import NotificationOut

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)


def _room(user_id: int) -> str:
    return f"user_{user_id}"


async def emit_to_user(user_id: int, event: str, data: dict[str, Any]) -> None:
    await sio.emit(event, data, room=_room(user_id))


def _count_unread(db: Session, recipient_id: int) -> int:
    q = select(func.count()).select_from(Notification).where(
        Notification.recipient_id == recipient_id,
        Notification.read_at.is_(None),
    )
    return int(db.scalar(q) or 0)


@sio.event
async def connect(sid, environ, auth=None) -> bool:  # type: ignore[no-untyped-def]
    if auth is None or not isinstance(auth, dict):
        return False
    token = auth.get("token")
    if not token or not isinstance(token, str):
        return False
    try:
        payload = decode_token(token)
        sub = payload.get("sub")
        if sub is None:
            return False
        user_id = int(sub)
        token_role = payload.get("role")
    except (JWTError, ValueError, TypeError):
        return False

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            return False
        ur = user.role.value if isinstance(user.role, UserRole) else str(user.role)
        if token_role is not None and token_role != ur:
            return False
    finally:
        db.close()

    await sio.enter_room(sid, _room(user_id))
    last_id = 0
    try:
        last_id = int(auth.get("lastNotificationId") or 0)
    except (TypeError, ValueError):
        last_id = 0

    db = SessionLocal()
    try:
        unread = _count_unread(db, user_id)
        rows = list(
            db.scalars(
                select(Notification)
                .where(
                    Notification.recipient_id == user_id,
                    Notification.id > last_id,
                )
                .order_by(Notification.id.asc())
                .limit(200)
            ).all()
        )
        sync_list = [
            NotificationOut.model_validate(n).model_dump(mode="json") for n in rows
        ]
    finally:
        db.close()

    await sio.emit(
        "sync",
        {"notifications": sync_list, "unread_count": unread},
        room=sid,
    )
    return True


@sio.event
async def disconnect(sid) -> None:  # type: ignore[no-untyped-def]
    pass
