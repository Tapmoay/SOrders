import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.core.rbac import Permission, role_has_permission, user_role_key
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import Order, User
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.schemas.order import (
    BatchAssignResultItem,
    DeliveryPhotoUploadOut,
    DriverNoteBody,
    OrderAssignBody,
    OrderBatchAssignBody,
    OrderBatchAssignOut,
    OrderCompleteBody,
    OrderCreate,
    OrderExceptionBody,
    OrderOut,
    OrderRecallBody,
    OrderUpdate,
)
from app.services.auth_service import new_order_no
from app.services.operation_log_service import write_log
from app.services.cancelled_order_retention import delete_orders_by_ids
from app.services.order_flow import (
    assign_driver,
    build_order_products,
    cancel_pending,
    complete_delivery,
    ensure_order_date,
    recall_dispatch,
)
from app.services.order_response import enrich_order_out, load_order_for_response
from app.services.push_events import (
    push_dispatcher_pending_pool_changed,
    push_driver_ack_shipper,
    push_ledger_updated,
    push_order_assigned,
    push_order_cancelled,
    push_order_delivered,
    push_order_revoked,
    push_order_to_shipper,
)
from app.services.shipper_contact_service import upsert_boss_contact

router = APIRouter(prefix="/orders", tags=["orders"])


async def _bg_ledger_updated_shipper(shipper_id: int) -> None:
    await push_ledger_updated(shipper_id)


UPLOAD_DIR = Path("uploads") / "delivery"
ALLOWED_IMAGE_CT = frozenset({"image/jpeg", "image/png", "image/webp", "image/jpg", "image/pjpeg"})


async def _save_delivery_uploads(order_id: int, files: list[UploadFile]) -> list[str]:
    sub = UPLOAD_DIR / str(order_id)
    sub.mkdir(parents=True, exist_ok=True)
    urls: list[str] = []
    for f in files[:20]:
        ct = (f.content_type or "").split(";")[0].strip().lower()
        if ct not in ALLOWED_IMAGE_CT:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型：{ct}")
        raw = await f.read()
        if len(raw) > 8 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="文件过大")
        ext = Path(f.filename or "").suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            ext = ".jpg"
        name = f"{uuid.uuid4().hex}{ext}"
        path = sub / name
        path.write_bytes(raw)
        urls.append(f"/static/uploads/delivery/{order_id}/{name}")
    return urls


def _get_order_scoped(order_id: int, current: User, db: Session) -> Order:
    order = db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    role = user_role_key(current)
    if role == UserRole.SHIPPER.value and (
        order.shipper_id is None or order.shipper_id != current.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    if role == UserRole.DRIVER.value and order.driver_id != current.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    return order


async def _bg_push_assigned(driver_id: int, order_id: int) -> None:
    await push_order_assigned(driver_id, order_id)


async def _bg_push_revoked(driver_id: int, order_id: int, reason: str) -> None:
    await push_order_revoked(driver_id, order_id, reason)


async def _bg_push_shipper_recalled(shipper_id: int, order_id: int) -> None:
    await push_order_to_shipper(shipper_id, order_id, "order.recalled")


async def _bg_notify_delivered(order_id: int) -> None:
    await push_order_delivered(order_id)


async def _bg_notify_cancel(shipper_id: int, order_id: int) -> None:
    await push_order_cancelled([shipper_id], order_id)


async def _bg_notify_driver_ack(shipper_id: int, order_id: int) -> None:
    await push_driver_ack_shipper(shipper_id, order_id)


async def _bg_dispatcher_pending_pool() -> None:
    await push_dispatcher_pending_pool_changed()


@router.get("", response_model=list[OrderOut])
def list_orders(
    current: CurrentUser,
    db: Session = Depends(get_db),
    status_filter: OrderStatus | None = Query(None, alias="status"),
    search_q: str | None = Query(None, alias="q"),
    shipper_id_filter: int | None = Query(None, alias="shipper_id"),
    temp_shipper_name_filter: str | None = Query(None, alias="temp_shipper_name"),
) -> list[OrderOut]:
    role = user_role_key(current)
    qtrim = (search_q or "").strip() or None

    if role == UserRole.DISPATCHER.value and qtrim:
        shipper_u = aliased(User)
        driver_u = aliased(User)
        term = f"%{qtrim}%"
        stmt = (
            select(Order)
            .outerjoin(shipper_u, Order.shipper_id == shipper_u.id)
            .outerjoin(driver_u, Order.driver_id == driver_u.id)
            .options(selectinload(Order.order_products))
            .where(
                or_(
                    Order.order_no.like(term),
                    shipper_u.full_name.like(term),
                    shipper_u.phone.like(term),
                    Order.temp_shipper_name.like(term),
                    Order.address_detail.like(term),
                    driver_u.full_name.like(term),
                    driver_u.phone.like(term),
                )
            )
            .order_by(Order.created_at.desc())
        )
        if status_filter is not None:
            stmt = stmt.where(Order.status == status_filter)
        if temp_shipper_name_filter is not None and temp_shipper_name_filter.strip():
            stmt = stmt.where(Order.shipper_id.is_(None)).where(
                Order.temp_shipper_name == temp_shipper_name_filter.strip()
            )
        elif shipper_id_filter is not None:
            stmt = stmt.where(Order.shipper_id == shipper_id_filter)
        orders = list(db.scalars(stmt).unique().all())
        return [enrich_order_out(o, db, current) for o in orders]

    q = select(Order).options(selectinload(Order.order_products)).order_by(Order.id.desc())

    if role == UserRole.SHIPPER.value:
        q = q.where(Order.shipper_id == current.id)
    elif role == UserRole.DRIVER.value:
        q = q.where(Order.driver_id == current.id)
    elif role == UserRole.DISPATCHER.value:
        if temp_shipper_name_filter is not None and temp_shipper_name_filter.strip():
            q = q.where(Order.shipper_id.is_(None)).where(
                Order.temp_shipper_name == temp_shipper_name_filter.strip()
            )
        elif shipper_id_filter is not None:
            q = q.where(Order.shipper_id == shipper_id_filter)
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无法识别当前用户角色")

    if status_filter is not None:
        q = q.where(Order.status == status_filter)

    orders = list(db.scalars(q).unique().all())
    return [enrich_order_out(o, db, current) for o in orders]


@router.get("/pending-dispatch-count")
def pending_dispatch_count(
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """派单工作台：当前「派单中」订单数量，用于底部 Tab / 铃铛角标。"""
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅派单员可查询")
    q = select(func.count()).select_from(Order).where(Order.status == OrderStatus.PENDING_DISPATCH)
    n = db.scalar(q)
    return {"count": int(n or 0)}


@router.post("/batch-assign", response_model=OrderBatchAssignOut)
def batch_assign_orders(
    body: OrderBatchAssignBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> OrderBatchAssignOut:
    driver = db.get(User, body.driver_id)
    if driver is None:
        raise HTTPException(status_code=400, detail="未找到该司机")
    if user_role_key(driver) != UserRole.DRIVER.value:
        raise HTTPException(status_code=400, detail="派单目标须为司机账号")
    results: list[BatchAssignResultItem] = []
    seen: set[int] = set()
    for oid in body.order_ids:
        if oid in seen:
            continue
        seen.add(oid)
        try:
            order = db.scalars(
                select(Order).options(selectinload(Order.order_products)).where(Order.id == oid)
            ).first()
            if order is None:
                results.append(BatchAssignResultItem(order_id=oid, success=False, detail="未找到订单"))
                continue
            assign_driver(db, order, driver, current, body.internal_note)
            db.commit()
            results.append(BatchAssignResultItem(order_id=oid, success=True, detail=None))
            background_tasks.add_task(_bg_push_assigned, body.driver_id, oid)
        except ValueError as e:
            db.rollback()
            results.append(BatchAssignResultItem(order_id=oid, success=False, detail=str(e)))
    if any(r.success for r in results):
        background_tasks.add_task(_bg_dispatcher_pending_pool)
    return OrderBatchAssignOut(results=results)


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, current: CurrentUser, db: Session = Depends(get_db)) -> OrderOut:
    order = _get_order_scoped(order_id, current, db)
    return enrich_order_out(order, db, current)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cancelled_order(
    order_id: int,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    """仅删除「已撤销」状态的订单（货主删自己的单；派单员可删含临时货主单）。"""
    order = _get_order_scoped(order_id, current, db)
    role = user_role_key(current)
    if role not in (UserRole.SHIPPER.value, UserRole.DISPATCHER.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作")
    if not role_has_permission(role, Permission.ORDER_DELETE_CANCELLED):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作")
    if order.status != OrderStatus.CANCELLED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅已撤销的订单可删除")
    delete_orders_by_ids(db, [order_id])
    db.commit()


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    body: OrderCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_CREATE)),
) -> OrderOut:
    """创建订单，初始状态为派单中（PENDING_DISPATCH）。

    客户端本地「未提交草稿」与已落库订单无关；创建成功后应以响应中的
    ``created_at`` 为准清除草稿状态，避免与派单中订单混淆。
    """
    role = user_role_key(current)
    target_shipper_id: int | None
    order_temp_shipper_name: str | None = None
    if role == UserRole.SHIPPER.value:
        if body.shipper_id is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="货主下单无需指定货主")
        target_shipper_id = current.id
    elif role == UserRole.DISPATCHER.value:
        if body.shipper_id is not None:
            su = db.get(User, body.shipper_id)
            if su is None or user_role_key(su) != UserRole.SHIPPER.value:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的货主")
            target_shipper_id = body.shipper_id
        elif body.temp_shipper_name:
            target_shipper_id = None
            order_temp_shipper_name = body.temp_shipper_name
        else:
            target_shipper_id = None
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前角色不能创建订单")

    lines = build_order_products(body.lines)
    od = ensure_order_date(body.order_date)
    order = Order(
        order_no=new_order_no(),
        status=OrderStatus.PENDING_DISPATCH,
        shipper_id=target_shipper_id,
        temp_shipper_name=order_temp_shipper_name,
        order_date=od,
        delivery_description=body.delivery_description,
        address_detail=body.address_detail,
        address_lat=body.address_lat,
        address_lng=body.address_lng,
        contact_dongjia_phone=body.contact_dongjia_phone,
        contact_boss_phone=body.contact_boss_phone,
        remark=body.remark,
        order_products=lines,
    )
    db.add(order)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_CREATE,
        change_payload={"order_no": order.order_no},
    )
    if target_shipper_id is not None and body.contact_boss_phone.strip():
        upsert_boss_contact(db, target_shipper_id, body.contact_boss_phone.strip())
    db.commit()
    background_tasks.add_task(_bg_dispatcher_pending_pool)
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单保存失败")
    return enrich_order_out(full, db, current)


@router.patch("/{order_id}", response_model=OrderOut)
def update_order(
    order_id: int,
    body: OrderUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderOut:
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED):
        raise HTTPException(status_code=400, detail="订单已结束，不可再编辑")
    before = {
        "delivery_description": order.delivery_description,
        "address_detail": order.address_detail,
        "remark": order.remark,
    }
    if body.delivery_description is not None:
        order.delivery_description = body.delivery_description
    if body.address_detail is not None:
        order.address_detail = body.address_detail
    if body.address_lat is not None:
        order.address_lat = body.address_lat
    if body.address_lng is not None:
        order.address_lng = body.address_lng
    if body.contact_dongjia_phone is not None:
        order.contact_dongjia_phone = body.contact_dongjia_phone
    if body.contact_boss_phone is not None:
        order.contact_boss_phone = body.contact_boss_phone
    if body.remark is not None:
        order.remark = body.remark
    if body.internal_notes is not None:
        order.internal_notes = body.internal_notes
    after = {
        "delivery_description": order.delivery_description,
        "address_detail": order.address_detail,
        "remark": order.remark,
    }
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_UPDATE,
        change_payload={"before": before, "after": after},
    )
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.patch("/{order_id}/exception", response_model=OrderOut)
def patch_order_exception(
    order_id: int,
    body: OrderExceptionBody,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderOut:
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    order.is_exception = body.is_exception
    order.exception_reason = body.exception_reason or ""
    order.exception_resolution = body.exception_resolution or ""
    if body.expected_deliver_before is not None:
        order.expected_deliver_before = body.expected_deliver_before
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_EXCEPTION,
        change_payload={
            "is_exception": body.is_exception,
            "exception_reason": body.exception_reason,
            "exception_resolution": body.exception_resolution,
        },
    )
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> None:
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if order.status != OrderStatus.PENDING_DISPATCH:
        raise HTTPException(status_code=400, detail="仅「待派单」订单可删除")
    db.delete(order)
    db.commit()


@router.post("/{order_id}/delivery-photos", response_model=DeliveryPhotoUploadOut)
async def upload_delivery_photos(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_UPLOAD_DELIVERY)),
    files: list[UploadFile] = File(...),
) -> DeliveryPhotoUploadOut:
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if user_role_key(current) != UserRole.DRIVER.value or order.driver_id != current.id:
        raise HTTPException(status_code=403, detail="无权操作")
    if order.status != OrderStatus.ACCEPTED:
        raise HTTPException(status_code=400, detail="仅「已接单」订单可上传凭证")
    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")

    urls = await _save_delivery_uploads(order_id, files)
    return DeliveryPhotoUploadOut(urls=urls)


@router.post("/{order_id}/complete-with-upload", response_model=OrderOut)
async def complete_order_with_upload(
    order_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_COMPLETE_DRIVER)),
    files: list[UploadFile] = File(...),
    driver_remark: str = Form(""),
) -> OrderOut:
    order = db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")
    urls = await _save_delivery_uploads(order_id, files)
    try:
        complete_delivery(db, order, current, urls, driver_remark)
    except ValueError as e:
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
    order.driver_acknowledged_at = datetime.now(timezone.utc)
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
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if role == UserRole.DRIVER.value:
        if order.driver_id != current.id:
            raise HTTPException(status_code=403, detail="无权操作")
        prefix = f"[司机 {datetime.now(timezone.utc).strftime('%m-%d %H:%M')}] "
    else:
        prefix = f"[派单 {datetime.now(timezone.utc).strftime('%m-%d %H:%M')}] "
    order.internal_notes = (order.internal_notes or "").strip()
    if order.internal_notes:
        order.internal_notes += "\n"
    order.internal_notes += prefix + body.note.strip()
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/assign", response_model=OrderOut)
def assign_order(
    order_id: int,
    body: OrderAssignBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> OrderOut:
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    driver = db.get(User, body.driver_id)
    if driver is None:
        raise HTTPException(status_code=400, detail="未找到该司机")
    try:
        assign_driver(db, order, driver, current, body.internal_note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.commit()
    background_tasks.add_task(_bg_push_assigned, body.driver_id, order.id)
    background_tasks.add_task(_bg_dispatcher_pending_pool)
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/complete", response_model=OrderOut)
def complete_order(
    order_id: int,
    body: OrderCompleteBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_COMPLETE_DRIVER)),
) -> OrderOut:
    order = db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    try:
        complete_delivery(db, order, current, body.delivery_photo_urls, body.driver_remark)
    except ValueError as e:
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
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    role = user_role_key(current)
    if role == UserRole.SHIPPER.value:
        if order.shipper_id is None or order.shipper_id != current.id:
            raise HTTPException(status_code=403, detail="无权操作")
    elif role == UserRole.DISPATCHER.value:
        pass
    else:
        raise HTTPException(status_code=403, detail="无权操作")

    if order.status != OrderStatus.PENDING_DISPATCH:
        raise HTTPException(status_code=400, detail="仅「待派单」订单可撤销")

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
    background_tasks.add_task(_bg_dispatcher_pending_pool)
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/recall", response_model=OrderOut)
def recall_order(
    order_id: int,
    body: OrderRecallBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_RECALL)),
) -> OrderOut:
    order = db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    shipper_id = order.shipper_id
    old_driver_id = order.driver_id
    try:
        recall_dispatch(db, order, current, body.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.commit()
    if old_driver_id:
        background_tasks.add_task(_bg_push_revoked, old_driver_id, order_id, body.reason)
    if shipper_id is not None:
        background_tasks.add_task(_bg_push_shipper_recalled, shipper_id, order_id)
    background_tasks.add_task(_bg_dispatcher_pending_pool)
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)
