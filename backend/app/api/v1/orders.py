import json
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
from app.deps import CurrentUser, parse_date_range, require_permission
from app.models import ArrearsUnit, Order, User
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.schemas.order import (
    BatchAssignResultItem,
    DeliveryPhotoUploadOut,
    DriverNoteBody,
    OrderAssignBody,
    OrderFreightBody,
    OrderSplitBody,
    OrderBatchAssignBody,
    OrderBatchAssignOut,
    OrderChargeBody,
    OrderCompleteBody,
    OrderCreate,
    OrderExceptionBody,
    OrderOut,
    OrderRecallBody,
    OrderUpdate,
)
from app.schemas.place import OrderNavigationBody
from app.schemas.product_visibility import product_visible_to
from app.services.auth_service import new_order_no
from app.services.operation_log_service import write_log
from app.services.order_flow import split_order
from app.services.data_retention import delete_orders_by_ids
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
    push_new_order_to_dispatchers,
    push_dispatcher_pending_pool_changed,
    push_driver_ack_shipper,
    push_driver_ack_to_dispatchers,
    push_order_delivered_to_dispatchers,
    push_order_cancelled_to_dispatchers,
    push_ledger_updated,
    push_order_freight_updated,
    push_order_assigned,
    push_order_cancelled,
    push_order_delivered,
    push_order_revoked,
    push_order_to_shipper,
    push_navigation_filled,
)
from app.services.shipper_contact_service import upsert_boss_contact
from app.services import place_service

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
    # 软删除（隔离区）订单：仅派单员可见可操作；普通用户视为不存在
    if order.deleted_at is not None and role != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    if role == UserRole.SHIPPER.value and (
        order.shipper_id is None or order.shipper_id != current.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    if role == UserRole.DRIVER.value and order.driver_id != current.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    return order


async def _bg_push_assigned(driver_id: int, order_id: int) -> None:
    await push_order_assigned(driver_id, order_id)


async def _bg_freight_updated(order_id: int) -> None:
    await push_order_freight_updated(order_id)


async def _bg_push_revoked(driver_id: int, order_id: int, reason: str) -> None:
    await push_order_revoked(driver_id, order_id, reason)


async def _bg_push_shipper_recalled(shipper_id: int, order_id: int) -> None:
    await push_order_to_shipper(shipper_id, order_id, "order.recalled")


async def _bg_notify_delivered(order_id: int) -> None:
    await push_order_delivered(order_id)
    await push_order_delivered_to_dispatchers(order_id)


async def _bg_notify_cancel(shipper_id: int, order_id: int) -> None:
    await push_order_cancelled([shipper_id], order_id)
    await push_order_cancelled_to_dispatchers(order_id)


async def _bg_notify_driver_ack(shipper_id: int, order_id: int) -> None:
    await push_driver_ack_shipper(shipper_id, order_id)
    await push_driver_ack_to_dispatchers(order_id)


async def _bg_notify_navigation_filled(shipper_id: int, order_id: int, place_name: str) -> None:
    await push_navigation_filled(shipper_id, order_id, place_name)


async def _bg_dispatcher_pending_pool() -> None:
    await push_dispatcher_pending_pool_changed()


async def _bg_notify_new_order(order_id: int) -> None:
    await push_new_order_to_dispatchers(order_id)


@router.get("", response_model=list[OrderOut])
def list_orders(
    current: CurrentUser,
    db: Session = Depends(get_db),
    status_filter: OrderStatus | None = Query(None, alias="status"),
    search_q: str | None = Query(None, alias="q"),
    shipper_id_filter: int | None = Query(None, alias="shipper_id"),
    temp_shipper_name_filter: str | None = Query(None, alias="temp_shipper_name"),
    date_from: str | None = Query(None, alias="date_from", description="YYYY-MM-DD（含当天）"),
    date_to: str | None = Query(None, alias="date_to", description="YYYY-MM-DD（含当天）"),
    limit: int | None = Query(None, ge=1, le=5000, description="返回条数上限（待派池缺省=300，其余缺省=全量）"),
    include_deleted: bool = Query(False, description="含软删除(隔离区)订单——仅派单员"),
    deleted_only: bool = Query(False, description="仅软删除(回收站)订单——仅派单员"),
) -> list[OrderOut]:
    role = user_role_key(current)
    if (include_deleted or deleted_only) and role != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看隔离数据")
    effective_limit = limit
    if effective_limit is None and role == UserRole.DISPATCHER.value and status_filter == OrderStatus.PENDING_DISPATCH:
        effective_limit = 300  # 待派池防护：万级积压时只取最新300单，防接口十几秒/内存暴涨
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
        if date_from or date_to:
            df, dt = parse_date_range(date_from, date_to)
            if df is not None:
                stmt = stmt.where(Order.created_at >= df)
            if dt is not None:
                stmt = stmt.where(Order.created_at <= dt)
        if status_filter is not None:
            stmt = stmt.where(Order.status == status_filter)
        if temp_shipper_name_filter is not None and temp_shipper_name_filter.strip():
            stmt = stmt.where(Order.shipper_id.is_(None)).where(
                Order.temp_shipper_name == temp_shipper_name_filter.strip()
            )
        elif shipper_id_filter is not None:
            stmt = stmt.where(Order.shipper_id == shipper_id_filter)
        if deleted_only:
            stmt = stmt.where(Order.deleted_at.isnot(None))
        elif not include_deleted:
            stmt = stmt.where(Order.deleted_at.is_(None))
        if effective_limit is not None:
            stmt = stmt.limit(effective_limit)
        orders = list(db.scalars(stmt).unique().all())
        return [enrich_order_out(o, db, current) for o in orders]

    q = select(Order).options(selectinload(Order.order_products)).order_by(Order.id.desc())
    if deleted_only:
        q = q.where(Order.deleted_at.isnot(None))
    elif not include_deleted:
        q = q.where(Order.deleted_at.is_(None))

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
    if date_from or date_to:
        df, dt = parse_date_range(date_from, date_to)
        if df is not None:
            q = q.where(Order.created_at >= df)
        if dt is not None:
            q = q.where(Order.created_at <= dt)

    if effective_limit is not None:
        q = q.limit(effective_limit)
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
    q = select(func.count()).select_from(Order).where(
        Order.status == OrderStatus.PENDING_DISPATCH,
        Order.deleted_at.is_(None),
    )
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
            if body.collect_cash is not None:
                order.collect_cash = body.collect_cash
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
    """软删除订单 → 进入隔离区 30 天（用户不可见；派单员可恢复；到期物理清理）。
    货主：本人 已送达/已撤销/异常 订单；派单员：任意状态（含待派单）。"""
    order = _get_order_scoped(order_id, current, db)
    role = user_role_key(current)
    if role not in (UserRole.SHIPPER.value, UserRole.DISPATCHER.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作")
    if role == UserRole.SHIPPER.value:
        if not role_has_permission(role, Permission.ORDER_DELETE_CANCELLED):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作")
        if order.status not in (OrderStatus.CANCELLED, OrderStatus.DELIVERED) and not bool(order.is_exception):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="仅已送达/已撤销/异常订单可删除（进行中的订单请走撤销或撤回）",
            )
    if order.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="订单已在隔离区，如需恢复请联系派单员")
    order.deleted_at = datetime.now(timezone.utc)
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_DELETE,
        change_payload={"order_no": order.order_no},
    )
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="代理下单请选择货主或填写临时货主姓名",
            )
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前角色不能创建订单")

    # 白名单（v3.43）：货主自己下单时，**不许**把看不到的商品塞进单里。
    # 为什么必须在这一层挡：选品页把商品藏起来只是"看不到"，
    # 接口照收就等于**看起来限制了、其实没有**（这种洞在界面上完全看不出来）。
    # 派单员代下单不受这条限制：他不是被限制的那个人，而且他看得到全部商品。
    bad = [
        (i + 1, ln.product_id)
        for i, ln in enumerate(body.lines)
        if not product_visible_to(db, current, ln.product_id)
    ]
    if bad:
        idx = "、".join(f"第 {i} 行" for i, _ in bad)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{idx}的商品不在你的可选范围内。请重新从商品目录里选一个。",
        )

    # 行金额/商品编号的判据在 build_order_products 里（**唯一一处**）：
    # 行金额由服务端按"单价×数量"算，商品编号必须在库里且没被删——被拒时要说清是第几行。
    try:
        lines = build_order_products(db, body.lines)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
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
    background_tasks.add_task(_bg_notify_new_order, order.id)
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


@router.post("/{order_id}/restore", response_model=OrderOut)
def restore_order(
    order_id: int,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> OrderOut:
    """派单员：从隔离区恢复订单（软删除后 30 天内可恢复）。"""
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅派单员可恢复")
    order = db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
    if order is None or order.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不在隔离区")
    order.deleted_at = None
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_RESTORE,
        change_payload={"order_no": order.order_no},
    )
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/address-image", response_model=OrderOut)
async def upload_order_address_image(
    order_id: int,
    current: CurrentUser,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
) -> Order:
    """上传收货地址参考图（定位不清时辅助找路）。"""
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    rk = user_role_key(current)
    if rk != UserRole.DISPATCHER.value and current.id != order.shipper_id:
        raise HTTPException(status_code=403, detail="无权操作")
    from app.api.v1.products import ALLOWED_IMAGE_CT, _sniff_image_mime

    ct = (file.content_type or "").split(";")[0].strip().lower()
    raw = await file.read()
    if ct not in ALLOWED_IMAGE_CT or ct in ("", "application/octet-stream"):
        sniffed = _sniff_image_mime(raw[:32])
        if sniffed:
            ct = sniffed
    if ct not in ALLOWED_IMAGE_CT:
        raise HTTPException(status_code=400, detail="不支持的图片类型（请使用 JPG/PNG/WebP）")
    if len(raw) > 4 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片过大（最大 4MB）")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        ext = ".jpg"
    sub = UPLOAD_DIR / str(order_id)
    name = f"{uuid.uuid4().hex}{ext}"
    path = sub / name
    try:
        sub.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="图片保存失败：服务器无法写入 uploads 目录",
        ) from e
    url = f"/static/uploads/delivery/{order_id}/{name}"
    # 多图：拼进 image_urls（JSON 数组），address_image_url 始终指向首图（兼容旧客户端）
    try:
        urls = json.loads(order.image_urls or "[]")
    except Exception:
        urls = []
    if url not in urls:
        urls.append(url)
    order.image_urls = json.dumps(urls, ensure_ascii=False)
    order.address_image_url = urls[0] if urls else url
    db.commit()
    db.refresh(order)
    return order


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
    payment: str = Form(""),
    damage_items: str = Form("[]"),
    damage_note: str = Form(""),
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
        items = _parse_damage_items(damage_items)
        complete_delivery(db, order, current, urls, driver_remark, items, damage_note.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _apply_complete_payment(order, payment.strip() or None)
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
    order.status = OrderStatus.ACCEPTED
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
    #    而共享库**没有删除接口** —— 一条无名无址的记录是永久的，
    #    在每个人的「共享地点」列表里都显示成「未命名地点」+ 空地址。
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
        # 逐单覆盖值（派单员对这一单单独定的金额/比例）跟着一起进 assign_driver——
        # 它与模式快照、规则快照是**同一件事的三个字段**，分开写会出现半截状态。
        assign_driver(
            db,
            order,
            driver,
            current,
            body.internal_note,
            piece_override=body.driver_piece_amount,
            rate_override=body.driver_commission_rate,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    order.freight_fee = body.freight_fee
    if body.collect_cash is not None:
        order.collect_cash = body.collect_cash
    db.commit()
    background_tasks.add_task(_bg_push_assigned, body.driver_id, order.id)
    background_tasks.add_task(_bg_dispatcher_pending_pool)
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/split", response_model=list[OrderOut])
def split_order_endpoint(
    order_id: int,
    body: OrderSplitBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> list[OrderOut]:
    """把待派单拆分为 N 个子单（按比例拆分件数），分别派单。"""
    order = db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    try:
        created = split_order(db, order, body.parts, current)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.commit()
    for c in created:
        background_tasks.add_task(_bg_notify_new_order, c.id)
    background_tasks.add_task(_bg_dispatcher_pending_pool)
    return [enrich_order_out(c, db, current) for c in created]


@router.post("/{order_id}/freight", response_model=OrderOut)
def update_order_freight(
    order_id: int,
    body: OrderFreightBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> OrderOut:
    """派单员补录/修改司机运费（送达/撤销后锁定；传 null 清空回待定）。"""
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED):
        raise HTTPException(status_code=400, detail="已送达或已撤销的订单不可修改运费")
    old = order.freight_fee
    order.freight_fee = body.freight_fee
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_FREIGHT,
        change_payload={
            "freight_fee": {
                "before": str(old) if old is not None else None,
                "after": str(body.freight_fee) if body.freight_fee is not None else None,
            }
        },
    )
    db.commit()
    background_tasks.add_task(_bg_freight_updated, order.id)
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
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


def _apply_complete_payment(order, payment: str | None) -> None:
    """司机完成订单时的收款处理：
    - 派单勾选「收取现金」：司机明确选 cash=现场收现金 / arrears=挂账（未选择按挂账兜底）；
    - 未勾选「收取现金」：账单自动挂账（不出现收款按钮）。"""
    if order.collect_cash:
        if payment == "cash":
            order.payment_method = "cash"
            order.paid = True
        else:
            order.payment_method = "arrears"
            order.paid = False
    else:
        order.payment_method = "arrears"
        order.paid = False


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
        complete_delivery(db, order, current, body.delivery_photo_urls, body.driver_remark, body.damage_items, body.damage_note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _apply_complete_payment(order, body.payment)
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


def _payment_scoped_order(order_id: int, db: Session) -> Order:
    order = db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="已撤销订单不可收款/挂账")
    return order


@router.post("/{order_id}/pay", response_model=OrderOut)
def pay_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderOut:
    """派单员：现场收款确认（货到付款）。仅派单员界面可用。"""
    order = _payment_scoped_order(order_id, db)
    order.payment_method = "cash"
    order.paid = True
    order.arrears_unit_id = None
    order.arrears_unit_name = ""
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action="ORDER_PAY",
        change_payload="现场收款确认",
    )
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/charge", response_model=OrderOut)
def charge_order(
    order_id: int,
    body: OrderChargeBody,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderOut:
    """派单员：订单挂账到挂账单位名下。仅派单员界面可用。"""
    order = _payment_scoped_order(order_id, db)
    unit = db.get(ArrearsUnit, body.arrears_unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="挂账单位不存在")
    order.payment_method = "arrears"
    order.paid = False
    order.arrears_unit_id = unit.id
    order.arrears_unit_name = unit.name
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action="ORDER_CHARGE",
        change_payload="挂账到 " + unit.name,
    )
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
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