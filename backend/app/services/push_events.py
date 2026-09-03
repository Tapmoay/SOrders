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
    await message_center.publish_new_order_to_dispatchers(SessionLocal(), order_id)


async def push_dispatcher_pending_pool_changed() -> None:
    """待派单池数量变化时通知所有在线派单员刷新角标。"""
    await emit_to_dispatchers("realtime", {"type": "dispatcher.pending_pool"})


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
