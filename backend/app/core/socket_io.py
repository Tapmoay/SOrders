"""Socket.IO 长连接（与 FastAPI 组合为 ASGI）。业务侧通过 emit_to_user 推送。

### 投递边界的一条硬契约（2026-09-26 R3-06 生产 Drill C 逼出来的）

    sio.emit  →  本地投递（_handle_emit）  →  redis.publish（_publish，跨实例那一半）

上游 AsyncRedisManager._publish 在两次发布都失败之后**只打一条日志就 return**（异常被吞掉），
于是 sio.emit **永远成功返回** —— 发件箱因此把「跨实例那条推送根本没发出去」记成 sent，
重试 / 退避 / failed + last_error 一条都不触发。那正是 outbox 模块开头点名要治的病。

所以本模块把这一层**翻成会抛**（见 _StrictRedisManager）：
**只有 redis.publish 真的返回之后，emit 才算成功**；失败必须让调用方看得见。
⛔ 这不是「发之前先探一次 Redis 可达」—— 那是 TOCTOU：探完到发之间它照样能挂，
   而且它只能降低概率，证明不了 publish 成功。
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

DISPATCHERS_ROOM = "role_dispatchers"

#: 断线回补一次最多下发多少条（R14-13）。要**最新**的这么多条，不是最旧的。
SYNC_LIMIT = 200

from app.config import get_settings

class _StrictRedisManager(socketio.AsyncRedisManager):
    """Redis 适配器：**publish 失败必须抛**，不许记一条日志就当成功。

    ### 它治的是什么病（2026-09-26 R3-06 生产 Drill C 实测）
    停掉 Redis 之后，一条真实业务写入产生的发件箱事件被记成了 sent / attempts=0，
    而同一时刻日志里是 16 条 ERROR [socketio.server] Cannot publish to redis... giving up ——
    事件在发件箱眼里「已经发出去了」，实际上**跨实例那半根本没发出去，而且没有任何地方记着**。

    ### 契约（这一层存在的**全部**理由）
    _publish **只有在 redis.publish 真的返回之后才返回**；失败一律抛出去，
    由调用方按它自己的语义处理 —— 发件箱那边的语义是「留在 pending，退避重试，用满次数才 failed」。

    ### ⛔ 它刻意**不**做的事
    · 不重写发布逻辑：仍然调 super()._publish()，只把它的「失败返回值」翻成异常；
    · 不做「发之前先探一次 Redis 可达」—— 检查与使用之间有竞态，证明不了 publish 成功。
    """

    async def _publish(self, data):  # type: ignore[no-untyped-def]
        sent = await super()._publish(data)
        # 上游成功时返回 redis.publish 的订阅者数（**0 也算成功**）；两次都失败时 return None。
        if sent is None:
            raise RuntimeError(
                "Socket.IO 跨实例投递失败：redis.publish 没有成功返回"
                "（上游 AsyncRedisManager 把失败吞成了一条日志）—— "
                "发件箱必须按**投递失败**处理，⛔ 不许当成已发送。"
            )
        return sent


# 多 worker 部署时用 Redis 适配器共享连接状态（否则 403/400 重连循环）；单进程留空用内存
_socket_redis_url = get_settings().socket_redis_url
_client_manager = _StrictRedisManager(_socket_redis_url) if _socket_redis_url else None

if not _socket_redis_url:
    # ⚠️ 空值必须**说出来**（2026-09-19 审计 R12-A6）：各 worker 各持一份内存连接表时，
    #    连在 worker B 上的司机收不到 worker A 发出的推送 —— 表现是"约一半推送静默丢失"
    #    （司机端只是没动静，没有报错，运维也无从发现）。生产是 `--workers 2`，
    #    所以这一行日志在多进程部署里是很要紧的信号；单进程本机开发忽略即可。
    logger.warning(
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

    # ⚠️ sync 是发给**这条连接自己**的（room=sid）：emit 会先本地投递，再往 Redis 广播一次
    #    （别的进程收到也会忽略 —— 那个 sid 不在它们那儿）。Redis 不可用时严格适配器会从
    #    **广播那一步**抛出来，可那一刻 payload **已经就位投递完了** ⇒ 这一处必须容忍：
    #    ⛔ 别把它变成「Redis 一抖，新连接就建不起来」。
    #    ⛔ 与发件箱那条路**故意不一样**：那边一失败就必须让事件留在 pending（见 _StrictRedisManager）。
    try:
        await sio.emit("sync", sync_payload_for(user_id, last_id), room=sid)
    except Exception:  # noqa: BLE001 - 跨实例广播失败不影响这条连接拿它自己的 payload
        logger.warning(
            "sync 的跨实例广播失败（本连接的 payload 已就地投递）user_id=%s", user_id, exc_info=True
        )
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


async def _participants(room: str):
    """本进程里这个房间的连接（sid, eio_sid）。

    ⚠️ 命名空间管理器的 `get_participants` 有两种形状：`AsyncManager` 是**异步生成器**，
    `AsyncRedisManager` 是普通生成器（它只返回**本机**的参与者，跨 worker 的看不到）。
    两种都要能吃，所以这里做一层适配，而不是赌其中一种。
    """
    got = sio.manager.get_participants("/", room)
    if hasattr(got, "__aiter__"):
        async for item in got:          # type: ignore[union-attr]
            yield item
    else:
        for item in got:
            yield item


async def revoke_user_sockets(user_id: int, reason: str = "") -> None:
    """撤销这个账号的长连接：先推 `session_revoked`，再断开**本进程**里它的连接。

    ### 为什么必须有（2026-09-19 外部完整检查 C-3）
    `authenticate_socket_token` 只在**握手**时校验一次 `tv`（令牌版本）；`connect` 之后
    这个连接就一直躺在 `user_{id}` 房间里收推送，而 `disconnect` 是空实现、
    全后端也只有 `connect`/`disconnect` 两个 socket 事件。于是"登出/改密/停用"之后：
    旧令牌打 HTTP 全 401，**但那条已经建起来的连接继续收**（站内信正文、单号、账本变动）。
    丢手机、共用手机的场景里，这正是"登出止损"最要紧的地方。

    ### 两半各管一段（跨 worker 的账要算清）
    - `emit` 经 Redis 适配器**广播到所有 worker**，每个 worker 再发给本机这个房间里的连接
      → 客户端收到 `session_revoked` 后自己走"登录已失效"那条链（App 侧已实现）；
    - `disconnect(sid)` 只对本进程的连接有效（管理器拿不到别的 worker 的参与者列表）。
      它的作用是**兜住还没升级的旧客户端** —— 它们不认识那个事件，只能由服务端断开。

    ⚠️ 残留（已记进台账）：旧客户端如果恰好连在**另一个** worker 上，要等它下次重连
    （握手时会被 `tv` 判据拒掉）才会真正断开。要做到"任意 worker 上的旧连接立刻断"，
    得自己维护一份跨进程的 sid 名册 —— 那是另一条改动链，本轮不做。
    """
    try:
        await sio.emit("session_revoked", {"reason": reason}, room=_room(user_id))
    except Exception:  # noqa: BLE001 - 推不出去也要继续断本地连接
        logger.warning("推送 session_revoked 失败 user_id=%s", user_id, exc_info=True)
    try:
        async for sid, _eio_sid in _participants(_room(user_id)):
            try:
                await sio.disconnect(sid)
            except Exception:  # noqa: BLE001
                logger.warning("断开已撤销的 socket 失败 sid=%s user_id=%s", sid, user_id, exc_info=True)
    except Exception:  # noqa: BLE001
        logger.warning("枚举 user_id=%s 的连接失败", user_id, exc_info=True)


@sio.event
async def disconnect(sid) -> None:  # type: ignore[no-untyped-def]
    pass
