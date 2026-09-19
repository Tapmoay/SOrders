"""Socket.IO 长连接（与 FastAPI 组合为 ASGI）。业务侧通过 emit_to_user 推送。"""

from __future__ import annotations

from typing import Any

import socketio
from jose import JWTError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.core.security import decode_token
from app.database import SessionLocal
from app.models import Notification, User
from app.models.enums import UserRole
from app.schemas.notification import NotificationOut

DISPATCHERS_ROOM = "role_dispatchers"

#: 断线回补一次最多下发多少条（R14-13）。要**最新**的这么多条，不是最旧的。
SYNC_LIMIT = 200

from app.config import get_settings

# 多 worker 部署时用 Redis 适配器共享连接状态（否则 403/400 重连循环）；单进程留空用内存
_socket_redis_url = get_settings().socket_redis_url
_client_manager = socketio.AsyncRedisManager(_socket_redis_url) if _socket_redis_url else None

if not _socket_redis_url:
    # ⚠️ 空值必须**说出来**（2026-09-19 审计 R12-A6）：各 worker 各持一份内存连接表时，
    #    连在 worker B 上的司机收不到 worker A 发出的推送 —— 表现是"约一半推送静默丢失"
    #    （司机端只是没动静，没有报错，运维也无从发现）。生产是 `--workers 2`，
    #    所以这一行日志在多进程部署里是很要紧的信号；单进程本机开发忽略即可。
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "SOCKET_REDIS_URL 未配置：Socket.IO 走**进程内**内存模式。"
        "单进程（本机开发）没问题；多 worker 部署下跨进程推送会丢失一半，请配置该变量。"
    )

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
    client_manager=_client_manager,
)


def _room(user_id: int) -> str:
    return f"user_{user_id}"


async def emit_to_user(user_id: int, event: str, data: dict[str, Any]) -> None:
    await sio.emit(event, data, room=_room(user_id))


async def emit_to_dispatchers(event: str, data: dict[str, Any]) -> None:
    """向所有在线派单员广播（连接时已加入 DISPATCHERS_ROOM）。"""
    await sio.emit(event, data, room=DISPATCHERS_ROOM)


def _count_unread(db: Session, recipient_id: int) -> int:
    q = select(func.count()).select_from(Notification).where(
        Notification.recipient_id == recipient_id,
        Notification.read_at.is_(None),
    )
    return int(db.scalar(q) or 0)


def _load_user(user_id: int):
    """按 id 取账号（连接里要用它的角色决定进哪个房间）。"""
    db = SessionLocal()
    try:
        return db.get(User, user_id)
    finally:
        db.close()


def authenticate_socket_token(token: object) -> int | None:
    """长连接握手的**唯一鉴权判据**：返回 user_id，或 None（拒绝）。

    ### 为什么单独抽出来（2026-09-19 审计 R12-H2）
    判据原来散在 `connect` 里，而 `connect` 一被调用就会 `enter_room` —— 单测里直接调它
    只会得到 `ValueError: sid is not connected to requested namespace`，
    于是"握手的鉴权"这件事**根本没有办法被测试钉住**，两处判据（HTTP / socket）走散了也没人知道。

    ### 三条判据（与 HTTP 侧同源，缺一条就是一个洞）
    1. 令牌能解出 `sub`；
    2. 账号存在且 `is_active`；
    3. **`tv` 与 `users.token_version` 一致** —— 登出/改密码会 `bump_token_version`，
       少了这一条，"我已经登出了"的旧令牌打 HTTP 全 401，却仍能建起 socket 长连接、
       进 `user_{id}` 甚至 `role_dispatchers` 房间，继续收新派单/运费/送达/撤销/账本推送。
       丢手机、共用手机的场景里，这正是"登出止损"最要紧的地方。
    """
    if not token or not isinstance(token, str):
        return None
    try:
        payload = decode_token(token)
        sub = payload.get("sub")
        if sub is None:
            return None
        user_id = int(sub)
    except (JWTError, ValueError, TypeError):
        return None

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            return None
        if int(payload.get("tv", 0) or 0) != int(getattr(user, "token_version", 0) or 0):
            return None
        return user_id
    finally:
        db.close()


@sio.event
async def connect(sid, environ, auth=None) -> bool:  # type: ignore[no-untyped-def]
    if auth is None or not isinstance(auth, dict):
        return False
    user_id = authenticate_socket_token(auth.get("token"))
    if user_id is None:
        return False
    user = _load_user(user_id)
    if user is None:
        return False

    await sio.enter_room(sid, _room(user_id))
    if user_role_key(user) == UserRole.DISPATCHER.value:
        await sio.enter_room(sid, DISPATCHERS_ROOM)
    last_id = 0
    try:
        last_id = int(auth.get("lastNotificationId") or 0)
    except (TypeError, ValueError):
        last_id = 0

    await sio.emit("sync", sync_payload_for(user_id, last_id), room=sid)
    return True


def sync_payload_for(user_id: int, last_id: int) -> dict[str, Any]:
    """断线回补的负载：`{"notifications": [...], "unread_count": N}`。

    抽成独立函数是为了**能单测"补的是最新的还是最旧的"** —— 原来这段逻辑埋在
    socket 事件处理里，`test_socket_io.py` 只能断言"负载里有这两个键"，
    于是这一条缺陷（R14-13）从来没有被任何检查碰到过。

    ⛔ 这里原来是 `order_by(id.asc()).limit(200)` —— 冷启动（游标=0，进程重启后游标归零）
       时回补的是**最旧的** 200 条（2026-09-19 审计 R14-13）。对一个有 2336 条消息的账号，
       客户端拿到的是它最早那批消息，而它只把游标推到第 200 条的 id、**列表本身整个丢掉**
       → 「断线期间产生的站内信」永远补不到：司机错过新单的三层提醒在"进程重启"这条路径上是空的。
       改法：取**最新**的 200 条（desc + limit），再反转回升序 ——
       客户端靠 `lastOrNull()` 推游标，所以下发的顺序必须仍是升序。
    """
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
                .order_by(Notification.id.desc())
                .limit(SYNC_LIMIT)
            ).all()
        )
        rows.reverse()
        return {
            "notifications": [
                NotificationOut.model_validate(n).model_dump(mode="json") for n in rows
            ],
            "unread_count": unread,
        }
    finally:
        db.close()


@sio.event
async def disconnect(sid) -> None:  # type: ignore[no-untyped-def]
    pass
