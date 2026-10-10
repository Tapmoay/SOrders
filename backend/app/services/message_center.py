"""消息中心：持久化通知 + Socket.IO 推送。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Notification, Order, OrderReturnRequest, User
from app.models.enums import UserRole
from app.schemas.notification import NotificationOut
from app.services.money_contract import has_per_order_pay
from app.services.message_push import emit_to_user
from app.services.money_text import money_text
from app.models.notification import SEVERITY_DANGER, SEVERITY_INFO, SEVERITY_WARN


# ══════════════════════════════════════════════════════════════════════════════
# 消息分级（FEAT-0019）：这张卡有多危险 · 哪几个字是重点
# ══════════════════════════════════════════════════════════════════════════════
#
# 用户口径（2026-10-11，逐字）：
#   ·「消息（底部 Tab）……要按消息类型做颜色区别，而且**只有未读状态才有这个样式**」；
#   ·「文字也要按风险程度着色……按风险程度分红 / 橙 / …（重要程度不同 → 文字颜色不同）」；
#   · 追加修正（同日晚，原话）：「你的文字不能全部用颜色给他去搞出来……真正的重心是这几个字
#     ……全是重点就是没有重点」。
#
# 落地成两个**互相独立**的事实，都由"发消息这一侧"（本模块）给出，客户端一个都不猜：
#   ① `severity`：这张卡有多危险。**判定只有一处** = 下面的 `severity_for()`。
#      客户端拿它决定被点名的词用什么颜色（danger 红 / warn 橙 / info 不上色）；
#      而"只有未读才上样式"是客户端的事（已读整条灰调，连高亮一起去掉）。
#   ② `payload["emphasis"]`：这条消息里**哪几个字 / 哪个数字是重点**。
#      `emphasis_for()` 按 type 取这一类固定的"新闻词"，再加上发消息的人手上那几个具体值
#      （单号 / 金额 / 人名），最后**只保留真的出现在标题或正文里的词**（找不到就一个都不标）。
#      ⛔ 客户端不许自己猜重点词，也不许整行上色。
#
# ⚠️ 为什么死守"只有一处"：这两种事实一旦散到下面 20 多个调用点，同一条消息在不同路径上就会
#    得到不同的档 —— 那是本项目在"权限判定散落各处"上已经栽过一次的形状。

#: —— type → 严重度：**本表就是唯一的那一处判定** ——
#: 表里查不到的 type 一律 `info`（`severity_for` 的兜底）。加新消息类型时**必须**在这里补一行：
#: 漏了不会报错（安静地落到 info），但 `_tools/qa/_check_notification_severity.py` 会红 ——
#: 它把代码里出现的每个通知 `type` 字面量都拿回来对这张表。
#:
#: 档位口径（对齐用户过目的那张 17 类样式表）：
#:   · `danger`：**已经在亏 / 已经出事**（库存低于报警阈值、应收超额度、应付已逾期、异地新设备登录）
#:   · `warn`  ：**不好但还没到最坏 / 需要人去看一眼**（撤销·删单·退货一族、库存偏低、应付临期、年检）
#:   · `info`  ：正常流转（派单·接单·送达·收款到账·开票·价格调整·系统公告）
SEVERITY_BY_TYPE: dict[str, str] = {
    # ── 订单：正常流转 ───────────────────────────────────────────────────────
    "order.assigned": SEVERITY_INFO,
    "order.dispatched": SEVERITY_INFO,
    "order.created": SEVERITY_INFO,
    "order.driver_ack": SEVERITY_INFO,
    "order.delivered": SEVERITY_INFO,
    "order.delivered_driver": SEVERITY_INFO,
    "order.delivered_dispatcher": SEVERITY_INFO,
    "order.driver_ack_dispatcher": SEVERITY_INFO,
    "order.restored": SEVERITY_INFO,
    "order.navigation.filled": SEVERITY_INFO,
    "order.edited": SEVERITY_INFO,
    "order.freight.updated": SEVERITY_INFO,
    # ── 订单：不好但还没到最坏（有人得去看一眼）──────────────────────────────
    "order.revoked": SEVERITY_WARN,
    "order.recalled": SEVERITY_WARN,
    "order.cancelled": SEVERITY_WARN,
    "order.cancelled_dispatcher": SEVERITY_WARN,
    "order.deleted": SEVERITY_WARN,
    "order.return_request": SEVERITY_WARN,
    "order.return_request.rejected": SEVERITY_WARN,
    "order.return_request.done": SEVERITY_WARN,
    "order.return_request.closed": SEVERITY_WARN,
    "order.returned": SEVERITY_WARN,
    # ── 系统 / 维护：要派单员动手（订单被保留策略挡住、司机应付明细作废）──────
    "order_purge_blocked": SEVERITY_WARN,
    "driver_bill_cancelled": SEVERITY_WARN,
    # ── 价格 / 导出 / 公告：通知性质 ─────────────────────────────────────────
    "price_change": SEVERITY_INFO,
    "ledger_export": SEVERITY_INFO,
    "system": SEVERITY_INFO,
    "system.notice": SEVERITY_INFO,
    # ── 下面这些**今天还没有生产者**（库存预警、应付到期、发票、车辆年检、账号安全）──
    #    先把名字与档位定下来：样式表（`_tmp/palette_demo/messages_all.html`，用户已过目）
    #    里那 17 类，App 那一侧照着 `type` 上色、后端这边照着 `type` 定档，两边用同一套名字。
    #    ⛔ 接生产者时**用这些名字**（别另起一个近义名），否则档位会安静地掉回 info。
    "stock.low": SEVERITY_DANGER,             # 库存 ≤ 报警阈值（用户原话「库存不足……很危险」）
    "stock.near_low": SEVERITY_WARN,          # 库存低于建议水位（今天只有 low_stock_alert 一个阈值）
    "arrears.over_limit": SEVERITY_DANGER,    # 客户欠款超过额度
    "payable.due_soon": SEVERITY_WARN,        # 应付临期（≤7 天）
    "payable.overdue": SEVERITY_DANGER,       # 应付已逾期
    "invoice.issued": SEVERITY_INFO,          # 发票已开具
    "vehicle.inspection_due": SEVERITY_WARN,  # 车辆年检临期
    "account.new_device_login": SEVERITY_DANGER,  # 异地 / 新设备登录
    "account.device_unfrozen": SEVERITY_INFO,     # 账号已解冻
}

#: —— type → 这类消息里"该被点名"的**固定说法**（新闻词）——
#: 只写确实会出现在标题或正文里的那几个字。数字 / 人名这类每条都不同的东西，由调用方通过
#: `create_message(..., emphasis=(...))` 传进来；单号由 `payload["order_no"]` 自动进表。
#: info 类只点"关键金额 / 单号"（用户口径），所以这里基本只有 warn / danger 类有行。
EMPHASIS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "order.revoked": ("已被撤回",),
    "order.recalled": ("已由派单员撤回",),
    "order.cancelled": ("已取消",),
    "order.cancelled_dispatcher": ("已撤销",),
    "order.deleted": ("已被派单员删除",),
    "order.edited": ("有改动",),
    "order.delivered_dispatcher": ("已完成送达",),
    "order.return_request": ("申请退货",),
    "order.return_request.rejected": ("被驳回",),
    "order.return_request.done": ("已办理",),
    "order.return_request.closed": ("已自动关闭",),
    "order.returned": ("退货了",),
    "order_purge_blocked": ("没有被清理",),
    "driver_bill_cancelled": ("作废",),
    "price_change": ("价格调整",),
    # 还没有生产者的那几类：写的是**将来那条文案里必须出现的字**，
    # 对不上时过滤会把它丢掉（宁可不标，也不标错）。
    "stock.low": ("库存不足",),
    "stock.near_low": ("库存偏低",),
    "arrears.over_limit": ("已超额度",),
    "payable.due_soon": ("将到期",),
    "payable.overdue": ("已逾期",),
    "invoice.issued": ("已开具",),
    "vehicle.inspection_due": ("年检",),
    "account.new_device_login": ("新设备登录",),
    "account.device_unfrozen": ("已解冻",),
    "system.notice": ("系统公告",),
}

#: 一条消息最多点几处、单个重点词最长几个字。
#: 用户口径「全是重点就是没有重点」—— 上限就是这条口径的机器化：宁可少标，不许标满。
MAX_EMPHASIS = 4
MAX_EMPHASIS_CHARS = 24


def severity_for(message_type: str | None) -> str:
    """**唯一一处严重度判定**：通知 type → `info` / `warn` / `danger`（FEAT-0019）。

    ⛔ 只有这一处。别在调用点按标题 / 正文现猜，也别拿 `speech_important` 顶替
    （那是"要不要念出来"）。表里查不到就返回 `info` —— 新消息类型忘了登记时的表现是
    "普通消息"，而不是"假装很危险"。
    """
    return SEVERITY_BY_TYPE.get(str(message_type or "").strip(), SEVERITY_INFO)


def emphasis_for(
    message_type: str | None,
    title: str | None,
    content: str | None,
    extra: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """这条消息里该被点名的片段（有序、去重、**必须真的出现在标题或正文里**）。

    顺序：先这一类固定的"新闻词"，再调用方给的具体值（金额 / 人名），单号由
    `emphasis_payload` 从 payload 里补在最后。

    ⛔ 三条不许（`_tools/qa/_check_notification_severity.py` 钉着）：
      · 标题/正文里**找不到**的词不许标 —— 宁可一个都不标，也不许标错；
      · 整条标题或整段正文本身不许当重点词（那就是用户否掉的"整行上色"）；
      · 最多 `MAX_EMPHASIS` 处、单个词不超过 `MAX_EMPHASIS_CHARS` 字（一句话不是重点词）。
    """
    text = f"{title or ''}\n{content or ''}"
    out: list[str] = []
    for raw in list(EMPHASIS_BY_TYPE.get(str(message_type or "").strip(), ())) + list(extra or ()):
        word = str(raw or "").strip()
        if not word or word in out:
            continue
        if word not in text:
            continue
        if len(word) > MAX_EMPHASIS_CHARS:
            continue
        if word == (title or "").strip() or word == (content or "").strip():
            continue
        out.append(word)
    return out[:MAX_EMPHASIS]


def emphasis_payload(
    payload: dict[str, Any] | None,
    message_type: str | None,
    title: str | None,
    content: str | None,
    extra: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any] | None:
    """把重点词写进 `payload["emphasis"]` —— 发消息这一侧的**唯一入口**。

    · 有重点词 → 一定写进 payload（payload 为空就地建一个）；
    · payload 本来就有、但没有重点词 → 写成 `[]`（**明确说"没有重点"**，
      免得客户端把"后端忘了填"与"这条消息本来就没重点"混成一种）；
    · payload 本来就是 None、也没有重点词 → 保持 None：⛔ 别凭空造一个 `{}` ——
      「没有 payload 就只读」是客户端的既有口径（FEAT-0019 契约第 3 条），塞个空对象会改掉它。

    ⚠️ 只是在 payload 上**追加**一个键：老字段（`order_id` / `old_price` / `new_price` …）
      一个都不动 —— 旧 H5 的 `ShipperPriceNoticeBar.vue` 与 App 都在读它们。
    """
    order_no = ""
    if isinstance(payload, dict):
        order_no = str(payload.get("order_no") or "")
    words = emphasis_for(
        message_type,
        title,
        content,
        tuple(extra or ()) + ((order_no,) if order_no else ()),
    )
    if not words and payload is None:
        return None
    out: dict[str, Any] = dict(payload) if payload else {}
    out["emphasis"] = words
    return out


def count_unread(db: Session, recipient_id: int) -> int:
    q = select(func.count()).select_from(Notification).where(
        Notification.recipient_id == recipient_id,
        Notification.read_at.is_(None),
    )
    return int(db.scalar(q) or 0)


def idem_key_for(idem_key: str | None, recipient_id: int) -> str | None:
    """幂等键的**最终形态**（事实键 ＋ 收件人）。``idem_key`` 的拼法只有这一处。

    为什么键里要带收件人：同一条业务事实发给司机和派单员两个人，那是两条**该发**的消息。
    为什么截到 140 字：列是 ``String(160)``，'"'#'"' ＋ 收件人编号还要占十来位 ——
    在**唯一一处**截断，胜过让每个调用点自己猜上限（截断后撞键 = 少发一条，比超长报错更隐蔽）。

    FEAT-0021：生产者（``message_producers``）也要用同一个键去问"这条是不是已经有了"，
    所以把它提出来当公共口径 —— ⛔ 生产者不许自己拼一遍键（拼法分叉 = 去重静默失效）。
    """
    if not idem_key or not idem_key.strip():
        return None
    return idem_key.strip()[:140] + "#" + str(recipient_id)


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
    idem_key: str | None = None,
    emphasis: tuple[str, ...] | list[str] | None = None,
) -> Notification:
    """建一条站内信。

    ### FEAT-0019：严重度与重点词都**从这里出去**（调用点只给数据，不给档）
    - `severity`：本函数按 `type` **现算**（`severity_for`）。调用点**没有**这个参数 ——
      ⛔ 不许哪个调用点自己判危险程度（那正是"同一件事两套判定"的开头）。
    - `emphasis`：这条消息里"该被点名的具体值"（金额 / 人名），只有发消息的人手上才有。
      这一类固定的新闻词由 `EMPHASIS_BY_TYPE` 按 type 给，单号从 payload 自动补，
      最后一起过滤（正文里找不到的词一个都不标）写进 `payload["emphasis"]`。
      颜色由 `severity` 决定，客户端不猜。

    ### 第二轮 R2-04：`idem_key` 是**幂等键**
    「同一条业务事实被投递两次」在本系统里是**设计内的正常情况**：发件箱的口径是至少一次
    （失败退避重试、快速通道与 worker 两条路都在跑）。没有幂等键时，重投一次就多一条站内信，
    **而且没有任何地方会报错**。

    - 传了 `idem_key`：同一收件人已经有过这个键的那条 → **返回已有的那条**，不再新建；
    - 不传（默认）：行为与以前**一字不差** —— 直接调用创建的消息（用户在界面上点的、
      后台补发的）本来就该每次都是一条新的。
    - 键里由本函数拼上收件人：同一条事实发给司机和派单员两个人，那是两条**该发**的消息。
    - ⛔ 唯一性由**数据库**保证（`uq_notifications_idem_key`），不是「先查再插」——
      后者挡不住两个 worker 同时投同一条事件（本项目在 lost update 上栽过同一个形状）。
    """
    key = idem_key_for(idem_key, recipient_id)
    if key is not None:
        existing = db.scalars(select(Notification).where(Notification.idem_key == key)).first()
        if existing is not None:
            return existing
    n = Notification(
        recipient_id=recipient_id,
        category=category,
        type=type,
        title=title,
        content=content,
        # 重点词写进 payload（只是**追加**一个键，老字段一个都不动）
        payload=emphasis_payload(payload, type, title, content, emphasis),
        # 严重度现算：唯一判定在 `severity_for`；模型的列默认值还会给绕过本工厂的
        # 构造路径（data_retention / ledger_export_worker / notifications 两个端点）兜一次。
        severity=severity_for(type),
        speech_important=speech_important,
        idem_key=key,
    )
    try:
        # SAVEPOINT：并发的两个 worker 同时插同一个键时，只有一边会撞唯一索引，
        # 而 **SAVEPOINT 回滚不会带走外层事务**（裸 db.rollback() 会 —— 那是把业务写一起丢掉）。
        with db.begin_nested():
            db.add(n)
            db.flush()
    except IntegrityError:
        if key is None:
            raise
        existing = db.scalars(select(Notification).where(Notification.idem_key == key)).first()
        if existing is None:
            raise
        return existing
    return n


async def emit_notification(n: Notification) -> None:
    data = NotificationOut.model_validate(n).model_dump(mode="json")
    await emit_to_user(n.recipient_id, "notification", {"notification": data})
    await emit_unread_count(n.recipient_id)


async def emit_notification_by_id(notification_id: int) -> None:
    """按编号重新取那一条再推（事务发件箱的处理器入口）。

    ⚠️ 为什么不让事件把整条消息带着走：负载里塞一份**快照**就等于两处状态
    （发件箱里那份与消息中心里那份），改了消息之后推出去的还是旧的；只带编号则永远推的是当前值。
    行已经不在（被删/保留期清理）就静默跳过 —— 那说明这条事件没有意义了，不是故障。
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        n = db.get(Notification, notification_id)
        if n is None:
            return
        await emit_notification(n)
    finally:
        db.close()


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
            idem_key="order.assigned" + ":" + str(order_id),
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
                idem_key="order.dispatched" + ":" + str(order_id),
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
    """运费更新提醒：只发给「有按单应付」的单（`driver_pay.has_per_order_pay`，与账单同源）。"""
    order = db.get(Order, order_id)
    if order is None or order.driver_id is None:
        return
    # 收件人必须存在（`create_message` 要写 recipient_id）
    if db.get(User, order.driver_id) is None:
        return
    # ⚠️ 模式只从**订单**读。原来这里按司机**当前**的车型/计费再算一遍 ——
    #    同一张老单（快照为空）会"账单按单给他结，运费改了却不提醒他"。
    if not has_per_order_pay(order):
        return
    ono = order.order_no
    fee = order.freight_fee
    # 正文给人看 → `money_text` 去尾零（`100.00 元` → `100 元`）；payload 里的结构化金额不动。
    content = (
        f"订单 {ono} 运费已更新：{money_text(fee)} 元。"
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
        # 钱变了就是这张卡的重点（用户口径：数字属于"重心"那几个字）
        emphasis=((money_text(fee),) if fee is not None else ()),
        payload={"order_id": order_id, "order_no": ono},
        speech_important=False,
        idem_key=f"order.freight.updated" + ":" + str(order_id),
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
        # 撤回**原因**是司机唯一能拿到的答复（没填就一个都不标 —— 过滤在 emphasis_for 里）
        emphasis=(reason,),
        payload={"order_id": order_id, "order_no": ono, "reason": reason},
        speech_important=True,
        idem_key=f"order.revoked" + ":" + str(order_id),
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(driver_id, {"type": "order.revoked", "order_id": order_id, "reason": reason})


async def publish_order_edited_driver(
    db: Session, driver_id: int, order_id: int, *, event_id: int = 0
) -> None:
    """派单员改了这一单 → **经手那张单的司机**收站内信（2026-10-05 CHG-0040）。

    用户原话：「在这个阶段可以对订单进行更改，不管是货主、商品，全部都可以更改」
    「**如果更改的话，对应的司机是会收到消息的**说他这个信息已经更改了」。
    ⛔ 货主端一个字都不提醒（与 CHG-0039「静默退回派单池」同一口径）：改单是派单员的
       内部修正，货主看得到的金额与件数本来就会跟着变，但没有一条「你的单被改了」的消息
       要发给他。

    ⚠️ 这条消息**刻意不说改了哪一处**：发件箱负载里只有 driver_id + order_id
      （`orders.edited` 的聚合根就是订单，见 `core/outbox.py` 的 `AGGREGATE_KEY`），
      而「改了什么」的唯一权威是订单本身 —— 所以正文说的是「去看一眼详情」，
      ⛔ 绝不在这里按订单重算或猜哪几个字段变了（说错一处比不说更坏）。
    ⚠️ 幂等键必须带**发件箱那一行的编号**：同一张单会被改很多次，只用 order_id 的话，
      第二次以后的改动会被 `create_message` 当成重复吞掉。
    ⚠️ 2026-10-06 CHG-0057：**货主 / 批发商自己也能补联系信息了**
      （`PATCH /orders/{order_id}/contact`，门是新的权限点），所以正文不再写死"被某某修改了"
      —— 写死角色就是对他说的假话。谁改的看操作日志（这条消息里一个字都不提）。
    """
    order = db.get(Order, order_id)
    if order is None:
        return
    # 收件人必须存在（`create_message` 要写 recipient_id）：与 `publish_order_returned_to_driver` 同一道闸
    if db.get(User, driver_id) is None:
        return
    ono = order.order_no
    n = create_message(
        db,
        recipient_id=driver_id,
        category="order",
        type="order.edited",
        title="订单信息有修改",
        content=f"订单 {ono} 的收货信息或货物明细有改动，出车前请打开订单详情核对一遍。",
        payload={"order_id": order_id, "order_no": ono},
        # 改单会改「送到哪、送给谁、送几件」——司机正在跑这一单，值得念出来
        speech_important=True,
        idem_key=f"order.edited" + ":" + str(order_id) + ":" + str(driver_id) + ":" + str(event_id),
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(driver_id, {"type": "order.updated", "order_id": order_id})

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
        idem_key=f"order.recalled" + ":" + str(order_id),
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
        idem_key=f"order.navigation.filled" + ":" + str(order_id),
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
                idem_key="order.delivered" + ":" + str(order_id),
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
                idem_key="order.delivered_driver" + ":" + str(order_id),
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
        emphasis=(driver_name,),
        payload={"order_id": order_id, "order_no": ono},
        speech_important=False,
        idem_key=f"order.driver_ack" + ":" + str(order_id),
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
                idem_key="order.cancelled" + ":" + str(order_id),
            )
        )
    db.commit()
    for n in ns:
        db.refresh(n)
        await emit_notification(n)
    for uid in user_ids:
        await emit_realtime(uid, {"type": "order.cancelled", "order_id": order_id})


async def publish_order_deleted(db: Session, user_ids: list[int], order_id: int) -> None:
    """软删一张单 → **当事人**各收一条站内信 + 一条实时信号（BUG-0027 / 测试台账 TA-05）。

    ### 为什么必须有（这是本单的病根）
    撤回（publish_order_revoked）、取消（publish_order_cancelled_multi）、送达都有推送，
    唯独「派单员把单删进回收站」一条都没有：司机端「进行中」列表在推送前毫无变化、
    手动刷新后那张卡**静默消失**，全程没有一句话（恢复则相反，静默回归）。
    司机拿着打不开的单跑车，到现场才发现单子没了 —— 这是**可见**级缺陷，不是体验问题。

    ⚠️ 站内信是「回过头还能查到」的那一份（消息中心留痕），实时信号是让司机端列表**当场**
    重拉的那一份（order.deleted → RealtimeHub 的 _refreshOrders）；两个渠道都要，
    少一个就退化成「要么当时没提示、要么过后查不到」。
    """
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
                type="order.deleted",
                title="订单已被删除",
                # ⚠️ 与 orders_common.DELETED_ORDER_NOTICES[1] 是同一句话：详情页 404 与这条
                #    站内信说的是同一件事，两处文案不一致会让司机以为是两回事。
                content=f"订单 {ono} 已被派单员删除，如需找回请联系派单员从回收站恢复。",
                payload={"order_id": order_id, "order_no": ono},
                speech_important=True,
                idem_key="order.deleted" + ":" + str(order_id),
            )
        )
    db.commit()
    for n in ns:
        db.refresh(n)
        await emit_notification(n)
    for uid in user_ids:
        await emit_realtime(uid, {"type": "order.deleted", "order_id": order_id, "order_no": ono})


async def publish_order_restored(db: Session, user_ids: list[int], order_id: int) -> None:
    """从回收站恢复 → 当事人的清单里**多了一张单**，必须说明它的来历（否则是静默回归）。

    speech_important=False：恢复是「好事」，不需要像撤回那样打断语音；实时信号照发，
    列表要当场把它挪回「进行中」。
    """
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
                type="order.restored",
                title="订单已恢复",
                content=f"订单 {ono} 已由派单员从回收站恢复。",
                payload={"order_id": order_id, "order_no": ono},
                speech_important=False,
                idem_key="order.restored" + ":" + str(order_id),
            )
        )
    db.commit()
    for n in ns:
        db.refresh(n)
        await emit_notification(n)
    for uid in user_ids:
        await emit_realtime(uid, {"type": "order.restored", "order_id": order_id, "order_no": ono})


def active_dispatchers(db: Session) -> list[User]:
    """**在用**的派单员（能收站内信的那群人）。

    FEAT-0021：从前这条判据只写在 ``_broadcast_to_dispatchers`` 里（外加
    ``publish_new_order_to_dispatchers`` 又抄了一份）。生产者要给"库存低的商品 / 该付的款 /
    开了的票"发消息，收件人必须与"新订单通知谁"**完全同一群人** ——
    在这里再写一遍 where 就是第二个口径：哪天"停用的派单员不收消息"改了，
    库存预警还照发，而两边都不报错。所以提成这一处，谁要发给派单员都走它。
    """
    return list(
        db.scalars(
            select(User).where(
                User.role == UserRole.DISPATCHER,
                User.is_active.is_(True),
            )
        ).all()
    )


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
    for d in active_dispatchers(db):
        n = create_message(
            db,
            recipient_id=d.id,
            category="order",
            type=type_,
            # 第二轮 R2-04：键里带 business fact（type_ 由调用方给），事件重投不会再发一条。
            idem_key=str(type_) + ":" + str(order_id),
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
    for d in active_dispatchers(db):
        n = create_message(
            db,
            recipient_id=d.id,
            category="order",
            type="order.created",
            title="新订单待派单",
            content=f"订单 {ono} 已提交，请及时派单。",
            payload={"order_id": order.id, "order_no": ono},
            speech_important=True,
            idem_key="order.created" + ":" + str(order_id),
        )
        db.commit()
        db.refresh(n)
        # 同上：`emit_notification` 已经含 `unread_count`，不许再补一次。
        await emit_notification(n)


async def publish_ledger_updated_event(
    shipper_id: int | None = None,
    *,
    driver_id: int | None = None,
    dispatchers: bool = False,
) -> None:
    """仅实时刷新账本列表（不额外落库，避免每条编辑一条消息）。

    ## 为什么收件人不只是货主（2026-09-24 第 20 轮并行渗透 C12-2）
    这个事件原来**只发给货主**（`emit_realtime(shipper_id, …)`），而客户端那边
    **三个角色**都在订阅 `ledger.updated` → `refreshLedger`：
      · 货主「我的账本」（`ShipperLedgerViewModel`）；
      · **司机「我的运费」**（`DriverFreightViewModel.kt:85`）—— 送达/改运费之后那一页的
        金额不变，且界面上没有任何提示；
      · **派单员「账本管理」**（`DispatcherLedgerViewModel.kt:444`）—— 记账/核销之后
        他自己那一页也停在旧数字。
    也就是说"信号发出去了但没人收、收的人等的是另一个信号"—— 两边都不报错。

    ⛔ 不许改成"给所有人广播"：账本是**按人**的东西，收件人必须是
    「这本账的主人 + 这一单的司机 + 派单员」这三类。
    """
    targets: set[int] = set()
    if shipper_id:
        targets.add(int(shipper_id))
    if driver_id:
        targets.add(int(driver_id))
    if dispatchers:
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            targets.update(
                int(u)
                for u in db.scalars(
                    select(User.id).where(
                        User.role == UserRole.DISPATCHER.value, User.is_active.is_(True)
                    )
                )
            )
        finally:
            db.close()
    for uid in sorted(targets):
        await emit_realtime(uid, {"type": "ledger.updated"})


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
            f"退货金额 ¥{money_text(returned_amount)}。{note}"
        ),
        emphasis=(f"¥{money_text(returned_amount)}",),
        payload=payload,
        speech_important=False,
        idem_key=f"order.return_request.closed" + ":" + str(request_id),
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
            emphasis=(who,),
            payload=_return_request_payload(req, ono),
            speech_important=False,
            idem_key="order.return_request" + ":" + str(request_id),
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
        emphasis=(req.reject_reason or "",),
        payload=payload,
        speech_important=False,
        idem_key=f"order.return_request.rejected" + ":" + str(request_id),
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
            refund_note = f"，已退款 ¥{money_text(refund_amount)}"
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
            f"退货金额 ¥{money_text(returned_amount)}{refund_note}。{tail}"
        ),
        emphasis=(f"¥{money_text(returned_amount)}",),
        payload=payload,
        speech_important=False,
        idem_key=f"order.return_request.done" + ":" + str(request_id),
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(
        req.shipper_id,
        {"type": "order.return_request.done", "order_id": req.order_id, "request_id": req.id},
    )


async def publish_order_returned_to_driver(
    db: Session,
    order_id: int,
    *,
    event_id: int,
    returned_amount: str,
    refund_amount: str,
    fully_returned: bool,
    items: str,
) -> None:
    """一次退货办完 → **经手那张单的司机**收站内信（2026-10-03，E2E 走查 P27）。

    走查原文：「货主端与派单员端都收到了「退货已办理」消息；**司机端一条都没有**。」
    司机把货送到就走了，货被退掉、这一单进了「已退货」，而他没有任何信号 ——
    这条消息就是补上这个信号。

    ⚠️ 金额与件数都是**退货那一刻的既成事实**（`return_order` 的回参与它算好的那一串），
       ⛔ 不在这里按订单重算：钱的口径只有 `services/order_money.py` / `order_return.py` 一处。
    ⚠️ 正文那句「账单不会被退货改动」是**成文口径**，不是安慰话：`order_return.py` 模块
       docstring「三条刻意不做的」第 1 条写着「不复原司机账单」，`driver_pay.pay_for_order`
       的输入里也没有退货数量。⚠️ 但⛔ 不许写成「这一单的运费照结」——整单退货的单在
       「运费结算页」是**看不到的**（`api/v1/driver_bills.py:66-67` 把这件事挂在待拍板上），
       那是另一个产品决策，不由这条消息替它下结论。
    """
    order = db.get(Order, order_id)
    if order is None or order.driver_id is None:
        return
    # 收件人必须存在（`create_message` 要写 recipient_id）：与 `publish_order_freight_updated` 同一道闸
    if db.get(User, order.driver_id) is None:
        return
    ono = order.order_no
    tail = "这一单已经整单退完。" if fully_returned else "这是部分退货，订单仍然是「已送达」。"
    refund_note = ""
    try:
        if float(refund_amount or 0) > 0:
            refund_note = f"，已退款 ¥{money_text(refund_amount)}"
    except (TypeError, ValueError):  # pragma: no cover - 出参异常时不要因此不通知司机
        refund_note = ""
    what = items or "（明细见订单详情）"
    n = create_message(
        db,
        recipient_id=order.driver_id,
        category="order",
        type="order.returned",
        title="订单被退货了",
        content=(
            f"订单 {ono} 退货了：{what}，退货金额 ¥{money_text(returned_amount)}{refund_note}。"
            f"{tail}这一趟你已经跑完，账单不会被退货改动（有疑问看「我的账单」里这一笔）。"
        ),
        emphasis=(f"¥{money_text(returned_amount)}",),
        payload={
            "order_id": order_id,
            "order_no": ono,
            "returned_amount": returned_amount,
            "refund_amount": refund_amount,
            "fully_returned": fully_returned,
        },
        speech_important=False,
        # ⚠️ 幂等键必须带**发件箱那一行的编号**：同一张单可以退好几次（部分退货累加），
        #    只用 order_id 的话第二次以后的消息会被 `create_message` 当成重复吞掉。
        idem_key=f"order.returned" + ":" + str(order_id) + ":" + str(event_id),
    )
    db.commit()
    db.refresh(n)
    await emit_notification(n)
    await emit_realtime(order.driver_id, {"type": "order.returned", "order_id": order_id})
