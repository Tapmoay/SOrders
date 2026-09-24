from datetime import datetime, timedelta, timezone

from typing import Annotated
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.pagination import finish_page
from app.core.rbac import Permission, user_role_key
from app.database import get_db
from app.deps import require_any_permission, CurrentUser, require_permission
from app.models import Notification, User
from app.models.enums import OperationAction, UserRole
from app.schemas.notification import (
    NotificationBatchDeleteBody,
    NotificationCreate,
    NotificationOut,
    NotificationUpdate,
)
from app.schemas.price_notify import PriceChangeNotifyBody
from app.core import outbox
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/notifications", tags=["notifications"])

#: ⚠️ 这个文件里原来的 `_bg_emit_unread` 助手与 `emit_notification` 后台任务都**搬进事务发件箱**了
#: （整改报告 §10）：事件只带编号，处理器按编号重新取那一条再推 —— 见 `main.py::_outbox_deliver`。


@router.get("/unread-count")
def unread_count(current: Annotated[User, Depends(require_any_permission(Permission.NOTIFICATION_READ))], db: Session = Depends(get_db)) -> dict[str, int]:
    from app.services.message_center import count_unread

    n = count_unread(db, current.id)
    return {"count": n}


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    response: Response,
    current: Annotated[User, Depends(require_any_permission(Permission.NOTIFICATION_READ))],
    db: Session = Depends(get_db),
    unread_only: bool = False,
    recipient_id: int | None = None,
    category: str | None = Query(None, description="system | order | reminder"),
    days: int = Query(30, ge=1, le=365, description="仅返回最近 N 天消息（只过滤，不删除任何数据；保留期由每日保留任务负责）"),
    limit: int = Query(200, ge=1, le=5000, description="本次最多返回多少条（缺省 200；上限 5000 与 /orders 一致）"),
    before_id: int | None = Query(
        None, ge=1, description="游标：只返回 id **小于**它的消息（「加载更多」往下翻页用；按 id 倒序即时间倒序）"
    ),
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

    ### 硬上限 200 与「还有更多」（R14-8，2026-09-19 审计）
    这里一直有一个硬 `limit(200)`：**没有分页、没有游标、也不回报截断**。实测（派单员账号
    2336 条消息、未读 1134）：无论 `?limit=5` 还是 `?limit=1000`，一律返回 200 条，
    响应头里什么都没有；而 `GET /orders` 早就有 `X-Truncated` 了。
    真实后果是第 201 条以前的旧消息在 App 里**一个入口都没有**（其中包含「账本导出完成」
    这种 payload 里带唯一下载链接的通知），用户点「全部已读」把 1134 条标掉，却只看过 200 条。

    现在：`limit` 真的生效（缺省 200、上限 5000，与 `GET /orders` 同一档）、
    `before_id` 游标可以往下翻页、响应头如实回报"还有更多"
    （`X-Truncated: 1/0` + `X-Result-Limit`，与订单列表**同一个形状**，客户端不用学第二套）。

    ⚠️ 上限放开到 5000 而不是钉死在 200，是为了让 AI 的**截断探针**能用：
    `AiReadService` 判断"是否还有更多"的唯一办法是**多要一行**（传 `limit + 1`），
    上限钉在 200 就会让"要 200 条"变成 201 → 422。`GET /orders` 早就是这个上限。
    """
    is_dispatcher = user_role_key(current) == UserRole.DISPATCHER.value
    target = recipient_id if (is_dispatcher and recipient_id is not None) else current.id

    # 消息保留期：**只过滤，不删除**（2026-09-19 审计修正）。
    #
    # ⛔ 这里原来还顺手 `DELETE ... WHERE recipient_id=target AND created_at < cutoff`。
    #    后果不是"清理得早了一点"，而是**一个 GET 会永久删数据**，而且删的是"最近 N 天之外"——
    #    触发它的方式又极其自然：AI 的 `read_data` 工具把 `days` 声明成可筛参数并渲染进工具说明
    #    （`AiReadCatalog.kt` / `AiReads.kt`），读工具**不经确认卡直接执行**。
    #    于是用户问一句「最近三天的消息」，模型填 `days=1`，一天前的站内信就被物理删掉了，
    #    全程没有提示、没有 operation_logs、也没法恢复；派单员带上别人的 recipient_id 还能清掉**别人**的消息。
    #    保留期该由"谁负责"来做：`data_retention.purge_expired_notifications`（每日随保留任务跑，
    #    main.py 的 lifespan 里 `run_daily_retention` 调它）——那是**有意为之的删除**，看得见、可审计。
    #
    # ⛔ cutoff 用 `datetime.now()`（**进程本地时间**）是错的（R14-9）：`created_at` 按本项目的
    #    口径存的是 **UTC**，两者相减就是固定时区偏差 —— 本机实测 `days=1` 少给 8 小时 / 1508 条，
    #    同一列在 SQLite（CURRENT_TIMESTAMP=UTC）与 MySQL（NOW()=会话时区）上基准还不一样。
    #    统一走 `business_time.utc_now_naive()`（与每日保留任务同一个"现在"）。
    cutoff = utc_now_naive() - timedelta(days=days)
    q = (
        select(Notification)
        .where(Notification.recipient_id == target, Notification.created_at >= cutoff)
        .order_by(Notification.id.desc())
    )
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    if category:
        q = q.where(Notification.category == category)
    if before_id is not None:
        q = q.where(Notification.id < before_id)
    # 多要一行：拿到第 limit+1 行就说明"还有更多"，与 `GET /orders` 的 X-Truncated 同源。
    rows = list(db.scalars(q.limit(limit + 1)).all())
    return finish_page(rows, limit, response)


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
    # 正文是**给人看的一句话** → 金额过 `money_text` 去尾零（`4.0500 → 4.05`、`5.00 → 5`）。
    # ⚠️ 下面 payload 里那几个结构化价格**原样不动**：客户端要拿它们做展示与对比
    #    （`ShipperPriceNoticeBar.vue` 读的就是 payload 的 old_price/new_price）。
    old_s = money_text(body.old_price) if body.old_price is not None else "—"
    new_s = money_text(body.new_price)
    title = f"商品价格调整：{body.product_name}"
    content = (
        f"商品「{body.product_name}」的{type_label}已更新：{old_s} → {new_s}。"
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
    db.flush()   # 先拿 id：事件只带编号，处理器按编号重取那一条
    for n in out:
        outbox.enqueue(db, "notifications.created", {"notification_id": n.id})
    db.commit()
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
    db.flush()
    outbox.enqueue(db, "notifications.created", {"notification_id": n.id})
    db.commit()
    db.refresh(n)
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
    outbox.enqueue(db, "notifications.unread_changed", {"user_id": current.id})
    db.commit()
    return {"updated": len(rows)}


@router.post("/batch-delete", response_model=dict)
def batch_delete_notifications(
    body: NotificationBatchDeleteBody,
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """批量删除消息：ids 指定列表，或 all=true 清空该账户全部消息（二选一）。
    默认仅本人消息；派单员可带 recipient_id 指定其他用户。

    ⛔ `{"ids": [], "all": false}` 必须拒绝（R14-8/A8，2026-09-19 审计复核）。
    这里的判据原来是"`ids` 非空就按 ids 删，否则删光"——`all` **根本没参与**这个判断
    （它只在上面做了一次互斥校验）。于是空 ids 会落到 else 分支，**把该账号的消息全删**。
    客户端的默认形状恰好就是空表（Android `NotificationBatchDeleteRequest` 的
    `ids = emptyList()`；AI 侧键缺失时也会得到空表），当前三个调用点都自己带了守卫，
    所以**现状不可达**——但"参数为空 = 删光"这种兜底不该留在服务端：
    它把任何一个新调用方的一次疏忽变成"用户消息全没了"，而且没有二次确认、不可恢复。
    """
    if body.ids and body.all:
        raise HTTPException(status_code=400, detail="ids 与 all 不能同时使用")
    if not body.ids and not body.all:
        raise HTTPException(status_code=400, detail="请指定要删除的消息（ids），或显式传 all=true 清空")
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
    # ⚠️ **派单员动别人的消息必须留痕**（2026-09-23 复核 A8）：这个端点允许派单员带
    #    `recipient_id` 清掉**任何账号**的消息（产品口径如此：消息中心是全局视图），
    #    但在这之前它**一条审计都不写** —— 一次 `{"recipient_id": X, "all": true}` 就能
    #    永久清空 X 的全部站内信，事后在审计页上查不到任何痕迹（"谁删的、删了多少"都不知道）。
    #    动自己的消息仍然不记（那是状态不是业务事实，逐条记会把审计页淹掉，见 REASONS 那条口径）。
    if target != current.id:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.NOTIFICATION_MODERATE,
            change_payload={
                "act": "batch_delete",
                "recipient_id": target,
                "deleted": result.rowcount,
                "scope": "all" if not body.ids else "ids",
                "ids": list(body.ids or [])[:50],
                "note": "派单员删除了**别人的**站内信（该账号自己的消息中心不再有这些条）",
            },
        )
    outbox.enqueue(db, "notifications.unread_changed", {"user_id": target})
    db.commit()
    return {"deleted": result.rowcount}


@router.get("/{notification_id}", response_model=NotificationOut)
def get_notification(notification_id: int, current: Annotated[User, Depends(require_any_permission(Permission.NOTIFICATION_READ))], db: Session = Depends(get_db)) -> Notification:
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
    # 改**别人的**消息要留痕（同 batch-delete 那条理由）：正文被改过之后，
    # 收件人看到的内容与后端当初发的那条已经不是一回事了，事后必须查得到是谁改的。
    if n.recipient_id != current.id:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.NOTIFICATION_MODERATE,
            change_payload={
                "act": "update",
                "notification_id": n.id,
                "recipient_id": n.recipient_id,
                "fields": [k for k, v in (("title", body.title), ("content", body.content),
                                          ("payload", body.payload)) if v is not None],
                "note": "派单员改了**别人的**站内信正文",
            },
        )
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
    # 删**别人的**消息要留痕（同上）。注意顺序：先把日志写进同一个事务，再删除那一行——
    # 日志记的是"我删了谁的那条消息"，所以里面的字段要在 `db.delete(n)` **之前**取。
    if rid != current.id:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.NOTIFICATION_MODERATE,
            change_payload={
                "act": "delete",
                "notification_id": n.id,
                "recipient_id": rid,
                "title": (n.title or "")[:64],
                "type": n.type,
                "note": "派单员删除了**别人的**一条站内信（不可恢复）",
            },
        )
    db.delete(n)
    outbox.enqueue(db, "notifications.unread_changed", {"user_id": rid})
    db.commit()


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
    outbox.enqueue(db, "notifications.unread_changed", {"user_id": current.id})
    db.commit()
    db.refresh(n)
    return n
