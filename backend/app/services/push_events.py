"""异步推送入口：落库消息中心 + Socket.IO。"""

from __future__ import annotations

from app.database import SessionLocal
from app.services import message_center
from app.core.socket_io import emit_to_dispatchers


async def push_order_assigned(driver_id: int, order_id: int) -> None:
    db = SessionLocal()
    try:
        await message_center.publish_order_assigned(db, order_id)
    finally:
        db.close()


async def push_order_freight_updated(order_id: int) -> None:
    db = SessionLocal()
    try:
        await message_center.publish_order_freight_updated(db, order_id)
    finally:
        db.close()


async def push_order_revoked(driver_id: int, order_id: int, reason: str = "") -> None:
    db = SessionLocal()
    try:
        await message_center.publish_order_revoked(db, driver_id, order_id, reason)
    finally:
        db.close()


async def push_order_cancelled(target_user_ids: list[int], order_id: int) -> None:
    db = SessionLocal()
    try:
        await message_center.publish_order_cancelled_multi(db, target_user_ids, order_id)
    finally:
        db.close()


async def push_order_delivered(order_id: int) -> None:
    db = SessionLocal()
    try:
        await message_center.publish_order_delivered(db, order_id)
    finally:
        db.close()


async def push_driver_ack_shipper(shipper_id: int, order_id: int) -> None:
    db = SessionLocal()
    try:
        await message_center.publish_driver_ack_shipper(db, shipper_id, order_id)
    finally:
        db.close()


async def push_ledger_updated(shipper_id: int) -> None:
    await message_center.publish_ledger_updated_event(shipper_id)


async def push_order_delivered_to_dispatchers(order_id: int) -> None:
    db = SessionLocal()
    try:
        await message_center.broadcast_order_delivered_to_dispatchers(db, order_id)
    finally:
        db.close()


async def push_driver_ack_to_dispatchers(order_id: int) -> None:
    db = SessionLocal()
    try:
        await message_center.broadcast_driver_ack_to_dispatchers(db, order_id)
    finally:
        db.close()


async def push_order_cancelled_to_dispatchers(order_id: int) -> None:
    db = SessionLocal()
    try:
        await message_center.broadcast_order_cancelled_to_dispatchers(db, order_id)
    finally:
        db.close()


async def push_new_order_to_dispatchers(order_id: int) -> None:
    """新单通知派单员（站内信 + 实时推送）。

    ⚠️ 这里原来是一行 `await message_center.publish_new_order_to_dispatchers(SessionLocal(), order_id)`
    —— **没有 close**（2026-09-23 全项目复核抓到）。同一个文件里另外 12 个函数都是
    `try/finally: db.close()`，只有这一处漏了，而它恰恰是**每次下单都会走**的那条路：
    每建一张单就泄漏一个连接，生产 `pool_size=64 / max_overflow=32`，泄漏到上限之后
    新请求只能等 `pool_timeout` 再报错 —— 表现是"跑了一阵之后下单开始 500"，
    而那一刻离真正的成因（这里少一个 close）已经很远。
    """
    db = SessionLocal()
    try:
        await message_center.publish_new_order_to_dispatchers(db, order_id)
    finally:
        db.close()


async def push_dispatcher_pending_pool_changed() -> None:
    """待派单池数量变化时通知所有在线派单员刷新角标。"""
    await emit_to_dispatchers("realtime", {"type": "dispatcher.pending_pool"})


async def push_navigation_filled(shipper_id: int, order_id: int, place_name: str) -> None:
    """司机补完导航信息 → 落站内信 + 实时推给货主。"""
    db = SessionLocal()
    try:
        await message_center.publish_navigation_filled(db, shipper_id, order_id, place_name)
    finally:
        db.close()


async def push_order_to_shipper(shipper_id: int, order_id: int, event_type: str) -> None:
    """撤回：落库+推送；派单已由 publish_order_assigned 覆盖货主。"""
    if event_type == "order.recalled":
        db = SessionLocal()
        try:
            await message_center.publish_order_recalled_shipper(db, shipper_id, order_id)
        finally:
            db.close()
        return
    if event_type == "order.dispatched":
        return
    await message_center.emit_realtime(shipper_id, {"type": event_type, "order_id": order_id})


# ---------------------------------------------------------------- 退货申请（2026-09-21）


async def push_return_request_to_dispatchers(request_id: int) -> None:
    """货主提交退货申请 → 全体派单员收站内信（见 `message_center` 里那段注释）。"""
    db = SessionLocal()
    try:
        await message_center.publish_return_request_to_dispatchers(db, request_id)
    finally:
        db.close()


async def push_return_request_rejected(request_id: int) -> None:
    """派单员驳回 → 货主收站内信（带理由）。"""
    db = SessionLocal()
    try:
        await message_center.publish_return_request_rejected(db, request_id)
    finally:
        db.close()


async def push_return_request_done(
    request_id: int,
    *,
    returned_amount: str,
    refund_amount: str,
    fully_returned: bool,
) -> None:
    """派单员办完 → 货主收站内信（金额由办理那一刻的回参带过来，不在这里重算）。"""
    db = SessionLocal()
    try:
        await message_center.publish_return_request_done(
            db,
            request_id,
            returned_amount=returned_amount,
            refund_amount=refund_amount,
            fully_returned=fully_returned,
        )
    finally:
        db.close()


async def push_return_request_closed(request_id: int, *, returned_amount: str, note: str) -> None:
    """派单员**直连退货**把申请自动关掉 → 货主收站内信（含"申请了什么 / 实退什么"的对照）。

    用户 2026-09-21 拍板这条规则时的原话：「把规则改成派单员退货之后，自动取消申请，
    然后它对应的数据发生改变，状态变成已退货多少多少」—— 所以这条消息必须把
    「退了多少」说出来（金额由 `return_order` 的回参带过来，⛔ 不在这里重算）。
    """
    db = SessionLocal()
    try:
        await message_center.publish_return_request_closed(
            db, request_id, returned_amount=returned_amount, note=note
        )
    finally:
        db.close()
