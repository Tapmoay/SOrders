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


async def push_order_deleted(target_user_ids: list[int], order_id: int) -> None:
    """软删一张单 → 当事人收到「这单已被派单员删除」（BUG-0027 / 测试台账 TA-05）。"""
    db = SessionLocal()
    try:
        await message_center.publish_order_deleted(db, target_user_ids, order_id)
    finally:
        db.close()


async def push_order_restored(target_user_ids: list[int], order_id: int) -> None:
    """从回收站恢复 → 当事人收到「这单又回来了」（同上；否则是静默回归）。"""
    db = SessionLocal()
    try:
        await message_center.publish_order_restored(db, target_user_ids, order_id)
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


async def push_order_edited_to_driver(driver_id: int, order_id: int, *, event_id: int = 0) -> None:
    """改单（地址 / 联系人 / 配送说明 / 商品行）→ 司机收**站内信** + 那一页自己重拉。

    2026-10-05 CHG-0040：这里原来只有一句 `emit_realtime(…"order.updated"…)`，而 Android
    那边 `RealtimeHub.kt` 的 `when (e.type)` 里**根本没有 `"order.updated"` 这一支**
    ⇒ 改单对司机**完全无感**：列表不刷新、不响、消息中心也没有一条。
    ⇒ 现在两件事一起做：落一条站内信（`message_center.publish_order_edited_driver`）
      + 实时信号（客户端据此重拉权威数据）。

    ⚠️ `event_id` 是发件箱那一行的编号：同一张单可以改很多次，只用 order_id 当幂等键的话，
    第二次以后的消息会被 `create_message` 当成重复吞掉。
    ⛔ 事件**不带负载**：客户端一律重拉服务端权威数据（`RealtimeHub.kt` 的既定做法），
    所以不存在「推送里的地址是旧的」这种可能。
    """
    db = SessionLocal()
    try:
        await message_center.publish_order_edited_driver(db, driver_id, order_id, event_id=event_id)
    finally:
        db.close()


async def push_ledger_updated(
    shipper_id: int | None = None,
    *,
    driver_id: int | None = None,
    dispatchers: bool = False,
) -> None:
    """账本/钱变动 → 让**相关的人**的账本页自己刷新（见 `publish_ledger_updated_event` 的说明）。

    ⚠️ 2026-09-24 第 20 轮并行渗透 C12-2：原来只有 `shipper_id` 一个收件人，
    而客户端有**三个角色**在订阅这个信号（货主账本 / 司机运费 / 派单员账本管理）——
    司机与派单员那两个页面**永远收不到**，界面停在旧数字且不报错。
    """
    await message_center.publish_ledger_updated_event(
        shipper_id, driver_id=driver_id, dispatchers=dispatchers
    )


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


async def push_order_returned_to_driver(
    order_id: int,
    *,
    event_id: int,
    returned_amount: str,
    refund_amount: str,
    fully_returned: bool,
    items: str,
) -> None:
    """一次退货办完 → **经手那张单的司机**收站内信（2026-10-03，E2E 走查 P27）。

    走查原文：「货主端与派单员端都收到了「退货已办理」消息；**司机端一条都没有**。
    司机端订单详情仍是 已送达，流转记录里没有退货/红冲一行。」

    ⚠️ `event_id` 是发件箱那一行的编号：同一张单可以退好几次（部分退货累加），
    只用 order_id 当幂等键的话，第二次以后的消息会被 `create_message` 当成重复吞掉。
    """
    db = SessionLocal()
    try:
        await message_center.publish_order_returned_to_driver(
            db,
            order_id,
            event_id=event_id,
            returned_amount=returned_amount,
            refund_amount=refund_amount,
            fully_returned=fully_returned,
            items=items,
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
