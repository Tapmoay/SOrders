"""送达与司机（完成 / 完成带图 / 司机接单 / 司机备注 / 补导航 / 撤销）（orders_delivery）—— 2026-09-24 整改阶段 4 **纯搬迁**的产物。

从 `api/v1/orders.py` 原样搬来的 7 个函数（_parse_damage_items,complete_order_with_upload,driver_ack_view,driver_append_internal_note,fill_order_navigation,complete_order,cancel_order）。
除代码组织外**一个字没改** —— URL / 入参 / 出参 / 权限 / 状态机 / 数据库全不变；
证据：`_tools/qa/_api_contract_snapshot.py --diff <搬之前> <搬之后>` 契约零差异。

⚠️ 本模块**自己声明** `router`：按文件解析的 AST 工具（端点索引 / AI 能力表）靠这一行算 URL 前缀。
"""

import json
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload
from app.core.business_time import local_stamp
from app.core.rbac import Permission, role_has_permission, user_role_key
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import Order, User
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.schemas.order import DriverNoteBody, OrderCompleteBody, OrderOut
from app.schemas.place import OrderNavigationBody
from app.services.operation_log_service import write_log
from app.services.order_flow import assign_driver, cancel_pending, complete_delivery, lock_order_row
from app.services.order_response import enrich_order_out, load_order_for_response
from app.services import place_service
from app.api.v1.orders_payment import _apply_complete_payment_logged, _reject_if_already_collected
from app.api.v1.orders_common import (
    _bg_dispatcher_pending_pool,
    _bg_ledger_updated_shipper,
    _bg_notify_cancel,
    _bg_notify_delivered,
    _bg_notify_driver_ack,
    _bg_notify_navigation_filled,
    _get_order_scoped,
    _order_not_deleted_or_404,
    _save_delivery_uploads,
)
from app.api.v1.orders_common import (_bg_ledger_updated_shipper, _save_delivery_uploads, _get_order_scoped, _bg_notify_delivered, _bg_notify_cancel, _bg_notify_driver_ack, _bg_notify_navigation_filled, _bg_dispatcher_pending_pool, _order_not_deleted_or_404)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/{order_id}/complete-with-upload", response_model=OrderOut)
async def complete_order_with_upload(
    order_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_COMPLETE_DRIVER)),
    files: list[UploadFile] = File(...),
    driver_remark: str = Form(""),
    payment: str = Form(""),
    damage_items: str = Form("[]"),
    damage_note: str = Form(""),
) -> OrderOut:
    # ⛔ **归属与状态必须在落盘之前判完**（2026-09-19 全项目报告 P1-11，中）：
    #    本端点原来取到单就直接 `_save_delivery_uploads`，把"是不是你的单 / 状态对不对"
    #    留给后面的 `complete_delivery` —— 后果有两条，都不是理论：
    #      · **任意司机的令牌可以对任意 `order_id` 写文件**到匿名可读的公开静态目录
    #        （`/static/uploads/delivery/<order_id>/…`）：拒绝发生在文件已经落盘之后；
    #      · `order_id` 不存在时 `order` 是 None → `complete_delivery(db, None, …)` 抛
    #        `AttributeError`（**不是** ValueError，下面的 `except ValueError` 接不住）→ **500**。
    #    三道门照抄同文件 `upload_delivery_photos`（同一条链上它是做对的那一个：先判后写）。
    order = _order_not_deleted_or_404(
        db.scalars(
            select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
        ).first()
    )
    if user_role_key(current) != UserRole.DRIVER.value or order.driver_id != current.id:
        raise HTTPException(status_code=403, detail="无权操作")
    if order.status != OrderStatus.ACCEPTED:
        raise HTTPException(status_code=400, detail="仅「已接单」订单可上传凭证")
    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")
    urls = await _save_delivery_uploads(order_id, files)
    try:
        items = _parse_damage_items(damage_items)
        complete_delivery(db, order, current, urls, driver_remark, items, damage_note.strip())
        # 收款方式也放进同一个 try：明确要现金而派单没勾选时要**整单回滚**（不能只送达到一半）
        _apply_complete_payment_logged(db, order, payment.strip() or None, current.id)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    background_tasks.add_task(_bg_notify_delivered, order.id)
    if order.shipper_id is not None:
        background_tasks.add_task(_bg_ledger_updated_shipper, order.shipper_id)
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/driver-ack", response_model=OrderOut)
def driver_ack_view(
    order_id: int,
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> OrderOut:
    if user_role_key(current) != UserRole.DRIVER.value:
        raise HTTPException(status_code=403, detail="无权操作")
    order = _get_order_scoped(order_id, current, db)
    if order.status != OrderStatus.DISPATCHED:
        raise HTTPException(status_code=400, detail="仅「已派单」订单可确认接单")
    # ⚠️ 条件 UPDATE 占位（2026-09-19 审计）：这是**司机手滑点两下**最容易撞上的一处
    #    （派单员同一时刻可能在撤销/撤回）。原来是无条件赋值，与撤销并发时能把已经撤销的单
    #    覆盖回 ACCEPTED —— 而撤销那一步已经把预占释放了，于是单子复活但**库存永远不扣**
    #    （送达时 `auto_stock_commit` 找不到 RESERVED 行）。作业同 assign/complete。
    claimed = db.execute(
        update(Order)
        .where(
            Order.id == order.id,
            Order.status == OrderStatus.DISPATCHED,
            Order.driver_id == current.id,   # 只有被派的那个人能接（_get_order_scoped 已挡，这里再钉一次）
            Order.deleted_at.is_(None),
        )
        .values(status=OrderStatus.ACCEPTED, driver_acknowledged_at=datetime.now(timezone.utc))
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="这张单刚刚被改过（可能已被撤销/撤回/别人接过），请刷新后看看当前状态",
        )
    db.refresh(order)
    sid = order.shipper_id
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    if sid is not None:
        background_tasks.add_task(_bg_notify_driver_ack, sid, order.id)
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/driver-note", response_model=OrderOut)
def driver_append_internal_note(
    order_id: int,
    body: DriverNoteBody,
    current: User = Depends(require_permission(Permission.ORDER_INTERNAL_NOTE)),
    db: Session = Depends(get_db),
) -> OrderOut:
    role = user_role_key(current)
    if role not in (UserRole.DRIVER.value, UserRole.DISPATCHER.value):
        raise HTTPException(status_code=403, detail="无权操作")
    order = _order_not_deleted_or_404(db.scalars(select(Order).where(Order.id == order_id)).first())
    # ⚠️ **先取锁再改这一段文本**（2026-09-23 第 8 轮）：这一行是"读出来 → 拼一段 → 写回去"
    #    （`internal_notes` 是**累计文本**，不是单值字段）。两个并发追加（司机与派单员各写一条，
    #    或同一个人两个设备）会各自读到同一份旧文本、各自拼一段再写回 → **后写的那一段把前一段
    #    整条吃掉**，而两边都收到 200。这条红线（`_check_status_gate_locking.py` 的"多写入点必须同源"）
    #    把 `internal_notes` 盘出来时才看见：另一个写入点 `assign_driver` 早就锁了，这里漏了。
    order = lock_order_row(db, order)
    if role == UserRole.DRIVER.value:
        if order.driver_id != current.id:
            raise HTTPException(status_code=403, detail="无权操作")
        # ⛔ 时间戳按**业务当地时刻**印（`local_stamp` 的唯一实现）：
        #    这里原来是 `datetime.now(timezone.utc).strftime(...)` —— 当地 09-21 07:10 写的备注
        #    在单子上印成 `[司机 09-20 23:10]`（连日期都跨），而这段文本一旦写进
        #    `internal_notes` 就**再也改不了**（累计文本、历史不可追溯）——
        #    用户拿它跟司机对时间时，两边说的不是同一天（2026-09-23 第 18 轮并行渗透 A2-3）。
        prefix = f"[司机 {local_stamp()}] "
    else:
        prefix = f"[派单 {local_stamp()}] "
    order.internal_notes = (order.internal_notes or "").strip()
    if order.internal_notes:
        order.internal_notes += "\n"
    order.internal_notes += prefix + body.note.strip()
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/navigation", response_model=OrderOut)
def fill_order_navigation(
    order_id: int,
    body: OrderNavigationBody,
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> OrderOut:
    """**司机到场后给这单补上导航信息**（订单原本没有坐标时才能补）。

    ## 为什么会需要这个接口
    下单时收货地址常常只有一行文字（"XX 路口进来第三家"），没有坐标；而**知道坐标的人
    恰恰是到过现场的司机**。以前这个坐标没有任何地方可以放：订单的经纬度只有
    `PATCH /orders/{id}` 一个入口（不带独立按钮），司机的 App 里更没有入口 ——
    于是同一个地方被问一百遍。这个接口把司机的那一次现场定位变成**三个人受益**：

    1. **这一单**：`orders.address_lat/lng` 补上，`nav_source='driver'`（货主端能看到
       "司机已帮你补上导航信息"，这句话必须是真的，所以来源要落库）；
    2. **这个货主**：写进他自己的地点库（`shipper_locations`），下次下单直接可选；
    3. **所有人**：写进**全局共享地点库**（`places`），同一个位置的下一单直接拉过来。

    ## 三条硬约束
    - **只补不改**：订单已经有坐标时一律 400。司机到的地方不一定就是收货点
      （卸货口、隔壁仓），让他覆盖掉一个货主确认过的坐标，是把"有坐标"变成"有错坐标"，
      而错坐标的危害比没有坐标更大（导航会把人带错，且看不出来）。
    - **只有这单的司机或派单员**能补（`_get_order_scoped` 已经按角色卡过）。
    - **合并半径 1 米**（`place_service.MERGE_METERS`）：相近坐标并入同一条而不是新建。
      "这次到底是新建还是并入"记在 `operation_logs.change_payload` 里（`merged_into_existing_place`）
      —— 出参保持 `OrderOut`（和其它订单动作一致，客户端拿到后整单刷新），
      所以**不在这里编造一个界面上的字段**；用户看到的结论两种情况下是同一句：
      "这个位置的坐标已经进库，下次能直接选"。
    """
    role = user_role_key(current)
    if role not in (UserRole.DRIVER.value, UserRole.DISPATCHER.value):
        raise HTTPException(status_code=403, detail="仅司机或派单员可以补导航信息")
    order = _get_order_scoped(order_id, current, db)
    # ⚠️ **先取锁再判"要不要补"**（2026-09-23 第 8 轮）：下面那道门是"还没有坐标才让补"，
    #    而它读的是手边这份对象；`PATCH /orders/{id}`（改地址，已取锁）与它写的是**同一组字段**
    #    （`address_detail` / `address_lat` / `address_lng`）。不同源时口径宽的那一个就是漏洞：
    #    派单员刚把地址改对、司机这一下补录又把它盖回他现场选的那个点。
    order = lock_order_row(db, order)
    if order.deleted_at is not None:
        raise HTTPException(status_code=400, detail="这张订单在回收站里，不能补导航信息")
    if order.address_lat is not None and order.address_lng is not None:
        raise HTTPException(
            status_code=400,
            detail="这张订单已经有导航信息了，不需要补录（避免把正确的坐标改成错的）",
        )
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="已撤销的订单不需要补导航信息")

    lat = float(body.address_lat)
    lng = float(body.address_lng)
    # 地点名：优先用司机填的，其次用订单原有的文字地址（避免库里一排空白名字）
    place_name = (body.name or "").strip() or (order.address_detail or "").strip()
    detail = (body.detail_address or "").strip() or (order.address_detail or "").strip()
    # ⚠️ 名字与地址**不能都是空**：这张单会往**全库共享**的地点库里写一条，
    #    而共享库是全库共用的一张表 —— 一条无名无址的记录在每个人的「共享地点」
    #    列表里都显示成「未命名地点」+ 空地址，谁也认不出是哪儿。
    #    （2026-09-19 起删除改成了软删、只有派单员能删，所以现在"清得掉"了；
    #    但入口挡掉仍然更好：进来一条就是**所有人**都看见了一条。）
    #    这里挡在入口，并给一句能照着做的中文（"起个名字"比"参数不合法"有用得多）。
    if not place_name and not detail:
        raise HTTPException(
            status_code=400,
            detail="请给这个位置起个名字（或填一下地址）再提交 —— "
            "共享库里只有坐标的话，别人下次认不出是哪儿，而且这条记录删不掉",
        )

    place, merged = place_service.upsert_place(
        db,
        lat=lat,
        lng=lng,
        name=place_name,
        detail_address=detail,
        source="driver" if role == UserRole.DRIVER.value else "dispatcher",
        created_by=current.id,
        order_id=order.id,
    )

    order.address_lat = body.address_lat
    order.address_lng = body.address_lng
    order.nav_source = "driver" if role == UserRole.DRIVER.value else "dispatcher"
    if detail:
        order.address_detail = detail

    shipper_location_created = False
    if order.shipper_id is not None:
        _, shipper_location_created = place_service.ensure_shipper_location(
            db,
            shipper_id=order.shipper_id,
            name=place_name,
            detail_address=detail,
            lat=lat,
            lng=lng,
        )

    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_NAVIGATION_FILL,
        change_payload={
            "order_no": order.order_no,
            "address_lat": str(body.address_lat),
            "address_lng": str(body.address_lng),
            "place_id": place.id,
            "place_name": place.name,
            # 这两个布尔量是"到底发生了什么"的原始记录：
            # 并入已有坐标 vs 新建、货主地点库有没有真的多一条。
            "merged_into_existing_place": merged,
            "shipper_location_created": shipper_location_created,
            "shipper_id": order.shipper_id,
        },
    )
    db.commit()

    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    if order.shipper_id is not None:
        background_tasks.add_task(
            _bg_notify_navigation_filled, order.shipper_id, order.id, place_name
        )
    return enrich_order_out(full, db, current)


def _parse_damage_items(raw: str) -> list:
    """解析 multipart Form 的 damage_items JSON（[{order_product_id, quantity}]）。"""
    import json as _json

    if not raw or not raw.strip():
        return []
    try:
        data = _json.loads(raw)
    except Exception:
        raise ValueError("货损数据格式错误")
    if not isinstance(data, list):
        raise ValueError("货损数据格式错误")
    out = []
    for it in data:
        out.append(type("DmgItem", (), {"order_product_id": int(it.get("order_product_id")), "quantity": int(it.get("quantity", 0))})())
    return out


@router.post("/{order_id}/complete", response_model=OrderOut)
def complete_order(
    order_id: int,
    body: OrderCompleteBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_COMPLETE_DRIVER)),
) -> OrderOut:
    order = _order_not_deleted_or_404(
        db.scalars(select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)).first()
    )
    try:
        complete_delivery(db, order, current, body.delivery_photo_urls, body.driver_remark, body.damage_items, body.damage_note)
        # 收款方式也放进同一个 try：明确要现金而派单没勾选时要**整单回滚**（不能只送达到一半）
        _apply_complete_payment_logged(db, order, body.payment, current.id)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    background_tasks.add_task(_bg_notify_delivered, order.id)
    if order.shipper_id is not None:
        background_tasks.add_task(_bg_ledger_updated_shipper, order.shipper_id)
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: int,
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> OrderOut:
    # ⛔ 隔离区（回收站）里的单**不许撤销**（2026-09-24 第 24 轮并行渗透 03-F1）：
    #    这是第 5 条写路径，而 R13-D1 当年只补了送达/上传凭证/追加备注/派单四条。
    #    漏掉它的后果是**两个角色两种答案**：货主 `GET /orders/{id}` 是 404、
    #    `?deleted_only=true` 是 403（他在界面上根本看不到这张单），
    #    可是同一个 id 发 `POST /cancel` 却会成功 —— 一张他看不见的单被改成「已撤销」，
    #    还会推一条「已撤销」通知给他（点进去 404）。本机库内实测有 22 行
    #    `deleted_at IS NOT NULL AND shipper_id=2 AND status IN (待派单, 已派单)` 满足这个前提。
    #    用 `_order_not_deleted_or_404` 与那四条写路径同一个判据、同一句答复。
    order = _order_not_deleted_or_404(
        db.scalars(select(Order).where(Order.id == order_id)).first()
    )
    role = user_role_key(current)
    if role == UserRole.SHIPPER.value:
        if order.shipper_id is None or order.shipper_id != current.id:
            raise HTTPException(status_code=403, detail="无权操作")
    elif role == UserRole.DISPATCHER.value:
        _reject_if_already_collected(db, order, "改回挂账")
    else:
        raise HTTPException(status_code=403, detail="无权操作")

    if order.status not in (OrderStatus.PENDING_DISPATCH, OrderStatus.DISPATCHED):
        raise HTTPException(status_code=400, detail="仅「待派单/已派单（司机未接单）」订单可撤销")

    if role == UserRole.SHIPPER.value:
        if not role_has_permission(role, Permission.ORDER_CANCEL_SHIPPER):
            raise HTTPException(status_code=403, detail="无权操作")
    else:
        if not role_has_permission(role, Permission.ORDER_CANCEL_DISPATCHER):
            raise HTTPException(status_code=403, detail="无权操作")

    try:
        cancel_pending(db, order, current)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    sid = order.shipper_id
    oid = order.id
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    if sid is not None:
        background_tasks.add_task(_bg_notify_cancel, sid, oid)
    if order.driver_id is not None:
        background_tasks.add_task(_bg_notify_cancel, order.driver_id, oid)
    background_tasks.add_task(_bg_dispatcher_pending_pool)
    return enrich_order_out(full, db, current)
