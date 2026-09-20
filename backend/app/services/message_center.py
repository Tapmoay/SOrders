"""消息中心：持久化通知 + Socket.IO 推送。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Notification, Order, OrderReturnRequest, User
from app.models.enums import UserRole
from app.models.user import resolve_billing_mode
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


async def publish_order_freight_updated(db: Session, order_id: int) -> None:
    """运费更新提醒：仅按单计费（PIECE）司机可见金额，固定工资司机不打扰。"""
    order = db.get(Order, order_id)
    if order is None or order.driver_id is None:
        return
    driver = db.get(User, order.driver_id)
    if driver is None:
        return
    mode = order.driver_billing_mode_snapshot or resolve_billing_mode(
        driver.vehicle_type, driver.billing_mode
    )
    if mode != "PIECE":
        return
    ono = order.order_no
    fee = order.freight_fee
    content = (
        f"订单 {ono} 运费已更新：{fee} 元。"
        if fee is not None
        else f"订单 {ono} 运费已清空（待定）。"
    )
    n = create_message(
        db,
        recipient_id=order.driver_id,
        category="order",
        type="order.freight.updated",
        title="运费更新",
        content=content,
        payload={"order_id": order_id, "order_no": ono},
        speech_important=False,
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(order.driver_id, {"type": "order.freight.updated", "order_id": order_id})


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


async def publish_navigation_filled(
    db: Session, shipper_id: int, order_id: int, place_name: str
) -> None:
    """司机给这单补上导航信息后，告诉货主（2026-09-18）。

    为什么值得单独发一条站内信：货主这边的实际变化是**他自己看不到的两件事**——
    地址库里多了一个地点、这单从此能导航了。不发消息的话，货主下次下单时
    突然发现地址库多了一条来源不明的记录，只能猜。
    `speech_important=False`：这不是要司机接单那种必须立刻响的事，响铃会变成噪音。
    """
    order = db.get(Order, order_id)
    ono = order.order_no if order else str(order_id)
    where = place_name.strip() or "本单收货地址"
    n = create_message(
        db,
        recipient_id=shipper_id,
        category="order",
        type="order.navigation.filled",
        title="导航信息已补上",
        content=f"订单 {ono} 的司机到场后补上了导航位置「{where}」，已存入你的地点库，下次下单可直接选。",
        payload={"order_id": order_id, "order_no": ono, "place_name": where},
        speech_important=False,
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(shipper_id, {"type": "order.navigation.filled", "order_id": order_id})


async def publish_order_delivered(db: Session, order_id: int) -> None:
    """货主收到 order.delivered；司机收到 order.delivered_driver（无货主时仅司机）。"""
    order = db.get(Order, order_id)
    ono = order.order_no if order else str(order_id)
    shipper_id = order.shipper_id if order else None
    driver_id = order.driver_id if order else None
    ns: list[Notification] = []
    if shipper_id is not None:
        ns.append(
            create_message(
                db,
                recipient_id=shipper_id,
                category="order",
                type="order.delivered",
                title="订单已送达",
                content=f"订单 {ono} 已完成送达。",
                payload={"order_id": order_id, "order_no": ono},
                speech_important=False,
            )
        )
    if driver_id is not None:
        ns.append(
            create_message(
                db,
                recipient_id=driver_id,
                category="order",
                type="order.delivered_driver",
                title="送达已确认",
                content=f"订单 {ono} 已完成送达，可在「已完成」中查看。",
                payload={"order_id": order_id, "order_no": ono},
                speech_important=False,
            )
        )
    if not ns:
        return
    db.commit()
    for n in ns:
        db.refresh(n)
        await emit_notification(n)
    if shipper_id is not None:
        await emit_realtime(shipper_id, {"type": "order.delivered", "order_id": order_id})
    if driver_id is not None:
        await emit_realtime(driver_id, {"type": "order.delivered_driver", "order_id": order_id})


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


async def _broadcast_to_dispatchers(
    db: Session,
    order_id: int,
    type_: str,
    title: str,
    content_tpl: str,
) -> None:
    """广播给所有派单员：消息落库 + 实时推送 + 未读角标（三端同步）。"""
    order = db.get(Order, order_id)
    if order is None:
        return
    content = content_tpl.format(ono=order.order_no)
    dispatchers = db.scalars(
        select(User).where(
            User.role == UserRole.DISPATCHER,
            User.is_active.is_(True),
        )
    ).all()
    for d in dispatchers:
        n = create_message(
            db,
            recipient_id=d.id,
            category="order",
            type=type_,
            title=title,
            content=content,
            payload={"order_id": order_id, "order_no": order.order_no},
            speech_important=False,
        )
        db.commit()
        db.refresh(n)
        # ⛔ 不要再补一次 `emit_unread_count(d.id)`（R14-16）：`emit_notification` 内部
        #    已经发过 `unread_count` 了。重复那次是"每张新单每个派单员多一条事件 +
        #    多一次 count 查询"，数值一致所以看不出来，只是噪音 —— 但这条链路上是常态
        #    （N 个派单员 × 每张单 = 2N 条事件、2N 次 count）。
        await emit_notification(n)


async def broadcast_order_delivered_to_dispatchers(db: Session, order_id: int) -> None:
    await _broadcast_to_dispatchers(db, order_id, "order.delivered_dispatcher", "订单已送达", "订单 {ono} 已完成送达，请知悉。")


async def broadcast_driver_ack_to_dispatchers(db: Session, order_id: int) -> None:
    await _broadcast_to_dispatchers(db, order_id, "order.driver_ack_dispatcher", "司机已接单", "订单 {ono} 司机已确认接单。")


async def broadcast_order_cancelled_to_dispatchers(db: Session, order_id: int) -> None:
    await _broadcast_to_dispatchers(db, order_id, "order.cancelled_dispatcher", "订单已撤销", "订单 {ono} 已撤销，请知悉。")


async def publish_new_order_to_dispatchers(db: Session, order_id: int) -> None:
    """新订单提交：通知所有派单员（消息落库 + 实时推送 + 未读角标）。"""
    order = db.get(Order, order_id)
    if order is None:
        return
    ono = order.order_no
    dispatchers = db.scalars(
        select(User).where(
            User.role == UserRole.DISPATCHER,
            User.is_active.is_(True),
        )
    ).all()
    for d in dispatchers:
        n = create_message(
            db,
            recipient_id=d.id,
            category="order",
            type="order.created",
            title="新订单待派单",
            content=f"订单 {ono} 已提交，请及时派单。",
            payload={"order_id": order.id, "order_no": ono},
            speech_important=True,
        )
        db.commit()
        db.refresh(n)
        # 同上：`emit_notification` 已经含 `unread_count`，不许再补一次。
        await emit_notification(n)


async def publish_ledger_updated_event(shipper_id: int) -> None:
    """仅实时刷新账本列表（不额外落库，避免每条编辑一条消息）。"""
    await emit_realtime(shipper_id, {"type": "ledger.updated"})


async def publish_return_request_closed(
    db: Session, request_id: int, *, returned_amount: str, note: str
) -> None:
    """派单员**直连退货**（订单管理那条老路）→ 那张申请自动关闭 → 告诉货主（2026-09-21）。

    这条消息是"我的申请为什么没被办理就结束了"的**唯一答复**，所以两件事都要写出来：
    · 退了多少（`returned_amount`，由 `return_order` 的回参带过来，⛔ 不在这里重算）；
    · `note` 那句"申请了什么 / 实退什么"的对照 —— 两边不一致时必须一眼看见
      （⛔ 不许把一个真实的差异悄悄盖成"已办理"，那正是本仓库最贵的一类错）。
    """
    req = db.get(OrderReturnRequest, request_id)
    if req is None:
        return
    order = db.get(Order, req.order_id)
    ono = order.order_no if order else str(req.order_id)
    payload = _return_request_payload(req, ono)
    payload["returned_amount"] = returned_amount
    payload["closed_note"] = note
    n = create_message(
        db,
        recipient_id=req.shipper_id,
        category="order",
        type="order.return_request.closed",
        title="退货申请已关闭（派单员直接退了货）",
        content=(
            f"订单 {ono} 的退货申请已自动关闭：派单员在订单管理里直接办了退货，"
            f"退货金额 ¥{returned_amount}。{note}"
        ),
        payload=payload,
        speech_important=False,
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(
        req.shipper_id,
        {"type": "order.return_request.closed", "order_id": req.order_id, "request_id": req.id},
    )


# ------------------------------------------------------------------ 退货申请（2026-09-21）
#
# 用户原话：「批发商……他可以直接在订单上作退货。然后我们的那个派单员，他会接到一个通知，
# 这个时候派单员就会去帮他进行一个退货的操作」。所以这里是一对消息：
# **货主提交 → 全体派单员**；**派单员办完/驳回 → 那一个货主**。
#
# ⚠️ 三个 `type` 都是**给客户端做路由用的**（点了通知要跳到哪一页）：
#    `order.return_request`（去申请详情/待办）、`…rejected`、`…done`。
#    payload 里一定带 `request_id` —— 没有它，派单员点开消息只能看到一句"有人申请退货"，
#    还得自己去列表里找是哪一张。


def _return_request_parts(req: OrderReturnRequest) -> str:
    parts = "、".join(f"{ln.product_name}×{ln.quantity}" for ln in req.lines)
    return parts or "（未填明细）"


def _return_request_payload(req: OrderReturnRequest, ono: str) -> dict[str, Any]:
    return {
        "request_id": req.id,
        "order_id": req.order_id,
        "order_no": ono,
        "items": [{"product_name": ln.product_name, "quantity": ln.quantity} for ln in req.lines],
    }


async def publish_return_request_to_dispatchers(db: Session, request_id: int) -> None:
    """货主提交退货申请 → 通知**所有**派单员（消息落库 + 实时推送 + 未读角标）。

    为什么广播给全体而不是指定某一个：派单员是**一个班次一个角色**，谁在线谁办
    （与"新订单待派单"完全同一条口径）。指定人反而会出现"他今天休息，这张申请没人看"。
    `speech_important=False`：货已经在客户手里放着了，晚一小时处理没有任何后果 ——
    让它响铃的代价是下次真正该响的（新订单）被无视。
    """
    req = db.get(OrderReturnRequest, request_id)
    if req is None:
        return
    order = db.get(Order, req.order_id)
    ono = order.order_no if order else str(req.order_id)
    who = _user_label(db, req.shipper_id) or "货主"
    dispatchers = db.scalars(
        select(User).where(
            User.role == UserRole.DISPATCHER,
            User.is_active.is_(True),
        )
    ).all()
    for d in dispatchers:
        n = create_message(
            db,
            recipient_id=d.id,
            category="order",
            type="order.return_request",
            title="退货申请待处理",
            content=f"{who} 对订单 {ono} 申请退货：{_return_request_parts(req)}。核对后请办理或驳回。",
            payload=_return_request_payload(req, ono),
            speech_important=False,
        )
        db.commit()
        db.refresh(n)
        # 与 `_broadcast_to_dispatchers` 同一条：`emit_notification` 内部已发 `unread_count`，
        # 不许再补一次（重复那次是纯噪音：N 个派单员 × 每条消息多一次 count 查询）。
        await emit_notification(n)


async def publish_return_request_rejected(db: Session, request_id: int) -> None:
    """派单员驳回 → 告诉货主（**带上理由**：这是他唯一能拿到的答复）。"""
    req = db.get(OrderReturnRequest, request_id)
    if req is None:
        return
    order = db.get(Order, req.order_id)
    ono = order.order_no if order else str(req.order_id)
    payload = _return_request_payload(req, ono)
    payload["reason"] = req.reject_reason or ""
    n = create_message(
        db,
        recipient_id=req.shipper_id,
        category="order",
        type="order.return_request.rejected",
        title="退货申请被驳回",
        content=f"订单 {ono} 的退货申请被驳回：{req.reject_reason or '（未填原因）'}",
        payload=payload,
        speech_important=False,
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(
        req.shipper_id,
        {"type": "order.return_request.rejected", "order_id": req.order_id, "request_id": req.id},
    )


async def publish_return_request_done(
    db: Session,
    request_id: int,
    *,
    returned_amount: str,
    refund_amount: str,
    fully_returned: bool,
) -> None:
    """派单员**办完了**（真的退了货）→ 告诉货主：退了多少、退了多少钱、这单结没结。

    ⚠️ 金额是**办理那一刻算出来的值**（由调用方从 `return_order` 的回参传进来），
       ⛔ 不在这里按订单重算：钱的口径只有 `services/order_money.py` / `order_return.py` 一处，
       消息中心再算一遍就是第二处（两边一旦不一致，货主看到的数字和账本上的对不上，
       而他只会相信消息里的那个）。
    """
    req = db.get(OrderReturnRequest, request_id)
    if req is None:
        return
    order = db.get(Order, req.order_id)
    ono = order.order_no if order else str(req.order_id)
    tail = "这一单已经整单退完。" if fully_returned else "这是部分退货，订单仍然是「已送达」。"
    refund_note = ""
    try:
        if float(refund_amount or 0) > 0:
            refund_note = f"，已退款 ¥{refund_amount}"
    except (TypeError, ValueError):  # pragma: no cover - 出参异常时不要因此不发货主
        refund_note = ""
    payload = _return_request_payload(req, ono)
    payload["returned_amount"] = returned_amount
    payload["refund_amount"] = refund_amount
    payload["fully_returned"] = fully_returned
    n = create_message(
        db,
        recipient_id=req.shipper_id,
        category="order",
        type="order.return_request.done",
        title="退货已办理",
        content=(
            f"订单 {ono} 的退货申请已办理：{_return_request_parts(req)}，"
            f"退货金额 ¥{returned_amount}{refund_note}。{tail}"
        ),
        payload=payload,
        speech_important=False,
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(
        req.shipper_id,
        {"type": "order.return_request.done", "order_id": req.order_id, "request_id": req.id},
    )
