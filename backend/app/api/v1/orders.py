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
    Response,
    UploadFile,
    status,
)
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, aliased, selectinload

from app.core.business_time import business_range_utc, utc_now_naive
from app.core.pagination import finish_page
from app.core.rbac import Permission, role_has_permission, user_role_key
from app.database import get_db
from app.deps import CurrentUser, parse_date_range, require_permission
from app.models import ArrearsUnit, Order, User
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.models import (
    DriverBillingRuleTemplate,
    FreightCategory,
    FreightTemplate,
    FreightTemplateCategory,
    ShipperAddress,
)
from app.schemas.order import (
    OrderFreightPriceBody,
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
    OrderReturnBody,
    OrderReturnOut,
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
from app.services.order_money import money_map
from app.services.order_response import enrich_order_out, load_order_for_response
from app.services.order_return import OrderReturnError, ReturnItem, return_order
from app.services import order_return_request as return_request_svc
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
    push_return_request_closed,
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
    # ⚠️ 认不出的角色**一律拒绝**（2026-09-19 审计 R12-L5）：
    #    原来是 if/if 两个分支，role 是第三种值（将来新增角色、或库里出现枚举外的值）时
    #    **两个分支都不进 → 直接放行**，那个角色能读全库订单详情；
    #    而同一个文件的列表接口对这种情况是 403（`list_orders` 的 else 分支）——
    #    同一份判据两处不一致，改一处就会留下一个口子。fail-closed 才对。
    if role not in (UserRole.SHIPPER.value, UserRole.DRIVER.value, UserRole.DISPATCHER.value):
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


async def _bg_notify_return_request_closed(request_id: int, amount: str, note: str) -> None:
    """直连退货把那张申请自动关掉之后，告诉货主（2026-09-21 用户拍板的那条规则）。"""
    await push_return_request_closed(request_id, returned_amount=amount, note=note)


async def _bg_notify_new_order(order_id: int) -> None:
    await push_new_order_to_dispatchers(order_id)


def _orders_response(
    db: Session, current: User, rows: list[Order], limit: int, response: Response
) -> list[OrderOut]:
    """列表接口的公共出口：把"截断了没有"如实写进响应头。

    ⚠️ 为什么要让客户端知道（2026-09-19 审计）：`GET /orders` 以前除"派单员+待派单"外**没有上限**，
    现在统一给了 300 —— 但**界面必须知道自己在看一页还是一切**：派单员在「全部订单」里以为看到了
    全部、其实只是最近 300 条，比"慢"更糟（他会据此判断"这单不存在"）。
    响应体是 `list[OrderOut]`（裸数组，加不了元数据，改形状会破坏所有老客户端），所以走响应头：
    `X-Result-Limit`（本次上限）、`X-Truncated: 1`（还有更多）。

    ⚠️ 这里还顺手把**一页的钱**一次算完（`money_map`：4 条分组查询，与订单条数无关）再逐单装配。
       留给 `enrich_order_out` 逐单算就是 4×N 条 SQL（一页 300 条 = 1200 条）。
    """
    page = finish_page(rows, limit, response)
    money = money_map(db, page)
    return [enrich_order_out(o, db, current, money.get(o.id)) for o in page]


def _apply_delivered_window(stmt, delivered_from: str | None, delivered_to: str | None):
    """按**送达日**（业务当地日）筛一批订单 —— 只给账本用，口径与账本行的 `entry_date` 对齐。

    ## 为什么必须有这一对参数（2026-09-20，账本管理改成"按订单的账"）
    账本页现在是"选货主 → 选时间 → 这个人的账（**按订单**）"：KPI 与商品统计都来自
    这些订单的 `应收 / 已收 / 欠款`。如果订单列表按 `created_at` 筛（也就是 `date_from/date_to`
    的语义），而账本流水按 `entry_date`（= **送达**那天）筛，那么
    「8 月 31 日下单、9 月 1 日送达」的单会出现在 9 月的账本流水里、却不在 9 月的订单列表里 ——
    同一屏两个集合，谁都不报错，用户只会以为"这个月少算了一单"。

    所以窗口按 `delivered_at` 取，并且**换算成业务当地日**（`business_range_utc`）：
    直接拿当地日期去比 UTC 列，会让当地 00:00~08:00 送达的单掉出窗口
    （`core/business_time.py` 的模块注释记着这个坑踩过多少次）。

    ⚠️ 「全部」那一档不传这两个参数 = 不加条件（与 `date_from/date_to` 同一条约定）。
    """
    if not delivered_from and not delivered_to:
        return stmt
    # ✅ 这一处**过了换算**（`business_range_utc`）—— 它就是"正确形状"的样板：
    #    `parse_date_range` 给的是当地日，必须换算成库里那种 UTC naive 再比。
    df, dt = parse_date_range(delivered_from, delivered_to)
    if df is None or dt is None:
        return stmt
    lo, hi = business_range_utc(df.date(), dt.date())
    return stmt.where(Order.delivered_at.isnot(None)).where(Order.delivered_at >= lo).where(Order.delivered_at < hi)


@router.get("", response_model=list[OrderOut])
def list_orders(
    current: CurrentUser,
    response: Response,
    db: Session = Depends(get_db),
    status_filter: OrderStatus | None = Query(None, alias="status"),
    search_q: str | None = Query(None, alias="q"),
    shipper_id_filter: int | None = Query(None, alias="shipper_id"),
    temp_shipper_name_filter: str | None = Query(None, alias="temp_shipper_name"),
    #: **待定价**（2026-09-21）：已派出去、但还没有运费的单 —— 派单员要手动给它们定价。
    #: 用户口径：「没有匹配到就没有计费、没有定价……这个订单就得派单员手动去给他定价」。
    #: ⚠️ 它**不改异常标记**（`is_exception` 是人工标的业务异常，两件事混在一列就都看不清了）。
    unpriced: bool = Query(False, description="只看运费待定价的单（已派单但没有运费）"),
    date_from: str | None = Query(None, alias="date_from", description="YYYY-MM-DD（含当天，按**下单时间**）"),
    date_to: str | None = Query(None, alias="date_to", description="YYYY-MM-DD（含当天，按**下单时间**）"),
    delivered_from: str | None = Query(
        None, alias="delivered_from", description="YYYY-MM-DD（含当天，按**送达日**的当地日；账本用）"
    ),
    delivered_to: str | None = Query(
        None, alias="delivered_to", description="YYYY-MM-DD（含当天，按**送达日**的当地日；账本用）"
    ),
    limit: int | None = Query(None, ge=1, le=5000, description="返回条数上限（缺省=300，最多 5000）"),
    include_deleted: bool = Query(False, description="含软删除(隔离区)订单——仅派单员"),
    deleted_only: bool = Query(False, description="仅软删除(回收站)订单——仅派单员"),
) -> list[OrderOut]:
    role = user_role_key(current)
    if (include_deleted or deleted_only) and role != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看隔离数据")
    # ⚠️ **所有**查询都有缺省上限（2026-09-19 审计）。原来只有"派单员 + 待派单"这一条路径有 300 的
    #    防护，其余（派单员「全部」页签、货主「全部」、司机「已完成」）都是**全量**：
    #    数据保留 3 年，一年后就是几万单、十几 MB 一次性下发，客户端全解析成 DTO 再交给列表 ——
    #    这是"随时间必然发生"的功能不可用，而它落在最常用的入口上。
    #    上限取 300 与待派池一致；客户端要知道"是不是被截断了"，看响应头 `X-Truncated`（见下）。
    DEFAULT_LIST_LIMIT = 300
    effective_limit = limit or DEFAULT_LIST_LIMIT
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
                    # 收货人 / 下单人的名字与电话（2026-09-20）：派单员搜索走的是这一支，
                    # 少了这两行就会出现"卡片上看得见名字、搜这个名字却搜不到"
                    Order.contact_dongjia_name.like(term),
                    Order.contact_boss_name.like(term),
                    Order.contact_dongjia_phone.like(term),
                    Order.contact_boss_phone.like(term),
                )
            )
            .order_by(Order.created_at.desc())
        )
        if date_from or date_to:
            # ⚠️ **必须过 `business_range_utc`**（与 `_apply_delivered_window` 同形）：
            #    `date_from/date_to` 是**业务当地日**，而 `orders.created_at` 存的是 **UTC naive**。
            #    第一版直接拿 `parse_date_range` 的当地零点去比 → 「查 9-21」实际取到的是
            #    北京 9-21 08:00 ~ 9-22 08:00（当天头 8 小时的单查不到、次日头 8 小时的多进来），
            #    界面上只是"少了几单"，看不出是时区错（与审计 R12-M11 同族）。
            #    ⚠️ 这个端点有**两条互不相干的查询构造路径**（这条是"派单员 + 搜索词"用的 `stmt`，
            #    下面还有一条给其余角色的 `q`）—— 两边的日期窗口**都要**换算，别只改一处。
            df, dt = parse_date_range(date_from, date_to)
            lo, hi = business_range_utc((df or dt).date(), (dt or df).date())
            if df is not None:
                stmt = stmt.where(Order.created_at >= lo)
            if dt is not None:
                stmt = stmt.where(Order.created_at < hi)
        if status_filter is not None:
            stmt = stmt.where(Order.status == status_filter)
        if unpriced:
            # 待定价 = **已经派出去了**（有司机）但运费还是空的，而且单还活着
            stmt = stmt.where(
                Order.driver_id.isnot(None),
                Order.freight_fee.is_(None),
                Order.status.notin_([OrderStatus.PENDING_DISPATCH, OrderStatus.CANCELLED]),
            )
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
        stmt = _apply_delivered_window(stmt, delivered_from, delivered_to)
        # 多取一行：拿到 limit+1 行就说明"还有更多"，据此写 X-Truncated
        stmt = stmt.limit(effective_limit + 1)
        orders = list(db.scalars(stmt).unique().all())
        return _orders_response(db, current, orders, effective_limit, response)

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
    # ⚠️⚠️ `unpriced` 必须**两条路径都加**（2026-09-21 真机抓到）：这个端点有两条互不相干的查询
    #    构造路径（上面"派单员 + 搜索词"那条用 `stmt`，这条用 `q`），过滤条件要各写一遍。
    #    只加在上面那条的后果：**待定价页（不带 q）静默返回全部订单**——它显示的是"所有单"，
    #    而页面上写着"这些单已经派出去了、但还没有运费"，用户照着这句话去核对就全错了。
    #    静态检查（`_check_freight_pricing.py`）当时只断言了"参数存在"，抓不到这种"文本对、行为错"。
    if unpriced:
        q = q.where(
            Order.driver_id.isnot(None),
            Order.freight_fee.is_(None),
            Order.status.notin_([OrderStatus.PENDING_DISPATCH, OrderStatus.CANCELLED]),
        )
    # ⚠️ `q` 对**所有角色**都要生效（2026-09-19 审计）。原来这个模糊搜索只在派单员分支里处理，
    #    货主/司机带 `q` 时后端**静默忽略**、照样返回他自己的一整页订单。而 AI 的读工具会把它
    #    写进 `filters_used`（`AiReadService` 原样回报生效条件）→ 模型以为筛过了 →
    #    用户问「SO202609186557849472 这单送到哪了」，答的是**另一张单**的地址与金额。
    #    作用域不变（货主只在自己的单里搜、司机只在自己的任务里搜），所以放开是安全的。
    if qtrim and role != UserRole.DISPATCHER.value:
        term = f"%{qtrim}%"
        q = q.where(
            or_(
                Order.order_no.like(term),
                Order.address_detail.like(term),
                Order.delivery_description.like(term),
                Order.contact_boss_phone.like(term),
                Order.contact_dongjia_phone.like(term),
                # 收货人/下单人的**名字**也一起搜（2026-09-20 加的那两列）：
                # 卡片与详情上都写着这两个名字，搜不到就是"看得见却搜不着"
                Order.contact_dongjia_name.like(term),
                Order.contact_boss_name.like(term),
            )
        )
    if date_from or date_to:
        # ⚠️ **必须过 `business_range_utc`** —— 与上面那条 `stmt` 路径同一件事、同一套换算
        #    （这个端点两条路径各写一遍过滤条件，漏一条就是"某个角色查某天少几单"）。
        #    窗口边界是**业务当地日**，而 `Order.created_at` 是 UTC naive，直接比会差 8 小时。
        df, dt = parse_date_range(date_from, date_to)
        lo, hi = business_range_utc((df or dt).date(), (dt or df).date())
        if df is not None:
            q = q.where(Order.created_at >= lo)
        if dt is not None:
            q = q.where(Order.created_at < hi)
    q = _apply_delivered_window(q, delivered_from, delivered_to)

    q = q.limit(effective_limit + 1)
    orders = list(db.scalars(q).unique().all())
    return _orders_response(db, current, orders, effective_limit, response)


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
        # ⛔ 「异常」**不是**删除通行证（2026-09-19 审计）。原来这里是
        #    `if 状态不在(已撤销, 已送达) and not is_exception:` —— 那个 `and` 让"是异常单"
        #    成了万能钥匙，而括号里那句"进行中的订单请走撤销或撤回"正是它要防的情况：
        #    派单员给一张**已接单在途**的单标了异常（客户催单是日常操作）→ 货主那一页出现
        #    「删除订单」→ 一删，单子进回收站 → 司机端列表里它直接消失（`GET /orders` 对司机
        #    过滤 `deleted_at`）→ **司机拿着打不开的单跑车，到现场发现单子没了、也拿不到钱**。
        #    现在：异常单必须**先撤销/撤回**（把状态变成终态）才能删。
        if order.status not in (OrderStatus.CANCELLED, OrderStatus.DELIVERED):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "仅已送达/已撤销订单可删除。这是一张进行中的订单"
                    + ("（已标异常）" if bool(order.is_exception) else "")
                    + "，请先走撤销或撤回，再删除。"
                ),
            )
    if order.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="订单已在隔离区，如需恢复请联系派单员")
    # 软删除时间统一用 **UTC naive**（`business_time.utc_now_naive`）：保留任务按 UTC 比
    # `deleted_at < cutoff`，而原来这里是 tz-aware UTC、其它六张表是本地时间 —— 三种基准混用，
    # 30 天隔离期在同一套判据下有的早 8 小时、有的同秒比较还会受字符串形状影响（R14-9 同族）。
    order.deleted_at = utc_now_naive()
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
        contact_dongjia_name=body.contact_dongjia_name.strip(),
        contact_boss_name=body.contact_boss_name.strip(),
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
    # 下单时把这一单的收货地址收进「我的地点」（用户 2026-09-20：「只要用户下单他会选择地点，
    # 这个时候，我们就自动地把它添加到地点库当中」）。
    # 代理下单**两边都记**（下单人 + 这单的货主）：地点库按登录人隔离，只记一边的话，
    # 另一边的人下次还得重新找这个地址。判据与去重全在 `place_service.remember_order_address`。
    saved = place_service.remember_order_address(
        db,
        owner_ids=[current.id, target_shipper_id],
        name=body.address_detail,
        detail_address=body.address_detail,
        lat=float(body.address_lat) if body.address_lat is not None else None,
        lng=float(body.address_lng) if body.address_lng is not None else None,
    )
    # 真的**新建**了才留痕：并进已有那条时什么都没变，多写一行日志只会让审计页变吵。
    # 写的是 PLACE_AUTO_ADDED（与"常用共享地点自动进我的地点"同一个动作码），
    # 这样"我的地点库里怎么多出一条"在操作日志里**只有一个地方**要查。
    for owner_id in saved["created_for"]:
        write_log(
            db,
            operator_id=current.id,
            order_id=order.id,
            action=OperationAction.PLACE_AUTO_ADDED,
            change_payload={
                "place_name": (body.address_detail or "").strip(),
                "owner_id": owner_id,
                "has_coords": body.address_lat is not None and body.address_lng is not None,
                "note": "下单时把收货地址自动加进「我的地点」（判据见 place_service.remember_order_address）",
            },
        )
    if target_shipper_id is not None and body.contact_boss_phone.strip():
        # 名字一起带上：这位下单人会在货主的联系人里出现，只有号码没有名字的话
        # 货主下次看到的就是一条"来源不明的联系人"（`upsert_boss_contact` 只在原本没名字时补）。
        upsert_boss_contact(db, target_shipper_id, body.contact_boss_phone.strip(),
                            body.contact_boss_name.strip())
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
    if order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED):
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
    if body.contact_dongjia_name is not None:
        order.contact_dongjia_name = body.contact_dongjia_name
    if body.contact_boss_name is not None:
        order.contact_boss_name = body.contact_boss_name
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
    # ⚠️ 重新登记异常时必须**清掉上一次的解决时间**（2026-09-19 审计）：
    #    `exception_resolved_at` 一直只有"解决"那条路径写，这里从来不清。
    #    于是"用户重新登记一条异常 → 接口 200、提示"异常已登记"，但列表里它带着旧的解决时间
    #    → 报表的「要处理」按 resolved 过滤 → **它永远不出现在待处理里**（典型的"操作成功但事情没做"），
    #    而且自动异常判定（`stats_service`）看到 resolved_at 非空也不再判它。
    if body.is_exception:
        order.exception_resolved_at = None
        order.exception_resolution = ""
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
    """上传收货地址参考图（定位不清时辅助找路）。

    **谁能传**（2026-09-20 扩容）：派单员 / 这单的货主 / **这单的司机**。
    司机加进来是用户点名要的：「司机他也可以去上交补交照片，如果他到了地方没有照片的话，
    他也可以补」—— 到了现场的人正是唯一拍得出"这个门口长什么样"的人。
    （原来只放行前两个角色，司机在订单详情页连入口都没有，只能打电话问路。）

    **照片会同时进「我的地点」**（`place_service.attach_order_photo`）：用户要的是
    「照片跟地点是一样自动保存在库里的」—— 下次下单选到这个位置，图就在库里，
    不用再让每个货主各拍一次。
    """
    order = _order_not_deleted_or_404(db.get(Order, order_id))
    rk = user_role_key(current)
    if (
        rk != UserRole.DISPATCHER.value
        and current.id != order.shipper_id
        and current.id != order.driver_id
    ):
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
    # 照片跟着**同一条判据、同一批人**进「我的地点」（用户 2026-09-20：
    # 「照片跟地点是一样是自动保存在库里的」）。代理下单时两边都记 —— 与
    # `remember_order_address` 完全同一批 owner，判据也只有 `place_service` 那一处。
    # 司机传的图也进**货主**的库（司机自己没有"我的地点"这个概念）。
    photo_owners = place_service.attach_order_photo(
        db,
        owner_ids=[current.id, order.shipper_id],
        name=order.address_detail or "",
        detail_address=order.address_detail or "",
        url=url,
        lat=float(order.address_lat) if order.address_lat is not None else None,
        lng=float(order.address_lng) if order.address_lng is not None else None,
    )
    if photo_owners:
        write_log(
            db,
            operator_id=current.id,
            order_id=order.id,
            action=OperationAction.PLACE_AUTO_ADDED,
            change_payload={
                "photo": url,
                "owner_ids": photo_owners,
                "note": "位置照片存进「我的地点」（判据见 place_service.attach_order_photo）",
            },
        )
    db.commit()
    db.refresh(order)
    return order


def _order_not_deleted_or_404(order: Order | None) -> Order:
    """取到单之后**统一挡掉隔离区（已进回收站）的单**（2026-09-19 审计 R13-D1）。

    ### 为什么需要它
    读侧对所有非派单员是「订单不存在」（`_get_order_scoped`），而司机端的**写路径**
    （送达 / 上传凭证 / 追加备注 / 派单）原来一个都不看 `deleted_at`：
    派单员把一张在途单删进回收站之后（客户催单 → 标记异常 → 删单，是日常操作，
    而且这条删除**没有任何推送**告诉司机），司机手上那一页还停在旧数据，点「送达」返回 **200**：
    库存实扣、账本入账、**司机应付账单生成**，而这张单在司机/货主/派单员的普通查询里都不存在。
    30 天后它被物理清理，那笔 OPEN 应付随之作废——司机白跑一趟，全程无提示。

    ⚠️ 用 404 而不是 403：与读侧同一种答复（"这张单对你来说不存在"），
    否则司机能从状态码差异反推出"有一张我看不到的已删除单"。
    """
    if order is None or order.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    return order


@router.post("/{order_id}/delivery-photos", response_model=DeliveryPhotoUploadOut)
async def upload_delivery_photos(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_UPLOAD_DELIVERY)),
    files: list[UploadFile] = File(...),
) -> DeliveryPhotoUploadOut:
    order = _order_not_deleted_or_404(
        db.scalars(select(Order).where(Order.id == order_id)).first()
    )
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


@router.post("/{order_id}/price-freight", response_model=OrderOut)
def price_freight(
    order_id: int,
    body: OrderFreightPriceBody,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> OrderOut:
    """派单员**手动定价**：没匹配到价目的单，由人给一个数。

    用户 2026-09-21：「这个定价完之后，同理，他会**新增对应的地点/路线和对应的运费模板**，
    并且放到那个分类当中去，就是绑定那个分类」——所以带上 `save_template` 时，
    这一次定价会**沉淀**成：①（必要时）一条线路；② 一条绑了这个分类的价目。

    ⛔ 沉淀**只新建/更新价目**，绝不动别的单：改价目只影响"以后派的单"
    （已经派出去的单记的是当时的运费，不是引用）。
    """
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="这一单已经撤销了，不用再定价")

    before = {
        "freight_fee": str(order.freight_fee) if order.freight_fee is not None else None,
        "freight_category_id": order.freight_category_id,
        "freight_category": order.freight_category or "",
    }
    # 分类：给了就用它（并把名字快照写下来），没给就清空（"这一类不适用"）
    cat_name = ""
    if body.category_id is not None:
        cat = db.get(FreightCategory, body.category_id)
        if cat is None:
            raise HTTPException(status_code=400, detail="这个运费分类不存在")
        cat_name = cat.name
    order.freight_fee = body.freight_fee
    order.freight_category_id = body.category_id
    order.freight_category = cat_name

    saved: dict = {}
    if body.save_template:
        # ① 路线：优先用现成的一条（同一终点、且是当前派单员的），没有就建一条
        route = None
        if body.save_template:
            route = db.scalars(
                select(ShipperAddress).where(
                    ShipperAddress.shipper_id == current.id,
                    ShipperAddress.detail_address == (order.address_detail or "").strip(),
                    ShipperAddress.is_deleted.is_(False),
                )
            ).first()
        if route is None:
            route = ShipperAddress(
                shipper_id=current.id,
                receiver_name=(order.contact_dongjia_name or "").strip()[:64],
                phone=(order.contact_dongjia_phone or "").strip()[:32],
                detail_address=(order.address_detail or "").strip()[:512],
                remark="由手动定价自动沉淀",
            )
            db.add(route)
            db.flush()
            saved["route_created"] = route.id
        # ② 价目：这条路线上"同一套分类"已经有一条就改价，否则新建
        want_cats = {body.category_id} if body.category_id is not None else set()
        existing = None
        for t in db.scalars(
            select(FreightTemplate).where(
                FreightTemplate.route_id == route.id,
                FreightTemplate.is_deleted.is_(False),
            )
        ).all():
            mine = set(_template_category_ids(db, t.id))
            if mine == want_cats:
                existing = t
                break
        if existing is not None:
            existing.fee = body.freight_fee
            if body.price_name.strip():
                existing.price_name = body.price_name.strip()[:32]
            saved["template_updated"] = existing.id
            tmpl = existing
        else:
            tmpl = FreightTemplate(
                name=(body.template_name.strip() or (route.detail_address or "手动定价")[:120]),
                route_id=route.id,
                from_place=(route.origin_address or "").strip()[:128],
                to_place=(route.detail_address or "").strip()[:128],
                price_name=body.price_name.strip()[:32],
                fee=body.freight_fee,
                remark="由手动定价自动沉淀",
                created_by=current.id,
            )
            db.add(tmpl)
            db.flush()
            saved["template_created"] = tmpl.id
        if body.category_id is not None:
            db.add(FreightTemplateCategory(template_id=tmpl.id, category_id=body.category_id))
        # ⛔ 价目**不绑司机**（2026-09-21 用户：「运费模板不会去匹配车型也不会匹配司机……
        #    这一目录就归这个计费规则」）。所以"下次自动带价"要落到**规则**上：
        #    这一单的司机有规则 → 把新价目**勾进他的规则**（没有就如实说，不偷偷造规则）。
        driver = db.get(User, order.driver_id) if order.driver_id is not None else None
        rule_id = getattr(driver, "driver_rule_id", None) if driver is not None else None
        if rule_id is not None:
            linked = db.scalars(
                select(DriverBillingRuleTemplate).where(
                    DriverBillingRuleTemplate.rule_id == int(rule_id),
                    DriverBillingRuleTemplate.template_id == tmpl.id,
                )
            ).first()
            if linked is None:
                db.add(DriverBillingRuleTemplate(rule_id=int(rule_id), template_id=tmpl.id))
                saved["rule_linked"] = int(rule_id)
        else:
            saved["rule_not_linked"] = "这一单的司机还没挂计费规则，价目已存好但要有人在他的规则里勾上才会自动带价"
        db.flush()

    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_FREIGHT_PRICE,
        change_payload={
            "before": before,
            "after": {
                "freight_fee": str(order.freight_fee),
                "freight_category_id": order.freight_category_id,
                "freight_category": order.freight_category or "",
            },
            "saved": saved,
        },
    )
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
    # ⛔ **没传运费 ≠ 把运费清空**（2026-09-19 审计 H3，高）：
    #    这里原来是无条件 `order.freight_fee = body.freight_fee`，而 `OrderAssignBody.freight_fee`
    #    的缺省是 `None` —— 于是"派单时没填运费"会把订单上**原有的运费清成 NULL**：
    #      · 司机计费规则为空时，司机应得 = `freight_fee`（`driver_pay` 的 PIECE 分支）→ **¥0.00**；
    #      · 而 `post_delivery_accounting` 里 `if pay.total <= 0: return None` →
    #        **连账单都不生成、不报错、不留痕** —— 司机这一趟白跑，账面上查不到任何异常。
    #    老 H5 的单条派单弹层没有运费输入框（批量派单那条路径不碰 freight_fee）→ 同一屏两个按钮
    #    两个结果：单条派单 = 司机拿 0 元，批量派单 = 运费还在。本机旁证：132 张 `freight_fee`
    #    为 NULL 的已送达单，`driver_bills` **0 条**。
    #    口径与紧邻的 `collect_cash` 一致（它有 `is not None` 守卫）：**没传就是不改**。
    #    要真的清掉运费得显式传一个值（现在不允许传 null —— 清运费属于改单，走订单编辑）。
    if body.freight_fee is not None:
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
    """派单员补录/修改司机运费（送达/撤销/退货后锁定；传 null 清空回待定）。"""
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # 已退货也算"这单结束了"：司机账单在送达那一刻就按当时的规则快照生成好了，
    # 事后改运费不会动账单（改了个寂寞），而界面上会显示一个与账单不一致的数。
    if order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED):
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


def _already_collected(db: Session, order: Order) -> bool:
    """这张单**已经收过款**了吗？（判据与 [_reject_if_already_collected] 同一套）

    两条：`order.paid` 是标记，而**指向这张单的 inbound 流水**是"钱真的进来过"的物证
    （标记可能被别的路径改过，物证不会）。
    """
    if order.paid:
        return True
    from app.models import CashFlow

    return (
        db.scalars(
            select(CashFlow).where(
                CashFlow.order_id == order.id,
                func.lower(CashFlow.direction) == "in",
            )
        ).first()
        is not None
    )


def _apply_complete_payment(db, order, payment: str | None) -> str | None:
    """司机完成订单时的收款处理：
    - 派单勾选「收取现金」：司机明确选 cash=现场收现金 / arrears=挂账（未选择按挂账兜底）；
    - 未勾选「收取现金」：账单自动挂账（界面上不出现收款按钮）。

    ⚠️ **明确要现金、但派单没勾选**时必须报错，不许悄悄改成挂账（2026-09-19 真机 E2E 抓到）：
    实测里司机侧传 `payment=cash`、而这一单派单时没勾「收取现金」，结果订单落成
    `payment_method=arrears / paid=False`、接口 200 —— 两边对同一件事的理解**相反**：
    司机以为自己收了现金，系统记的是"还没收"，于是这块账会出现在催收名单里。
    App 侧不会这么发（按钮只在勾选后才出现），但"接口照收却按另一个意思记"正是
    这个项目反复在治的那一类（后端没有的语义要如实拒绝，不许悄悄换掉）。

    ⛔ **已经收过款的单，送达不许把 `paid` 改回 False**（2026-09-19 审计 F1，高）：
    下面原来是无条件赋值，于是这条链一路静默 ——
    ① 先收了一笔钱（预收 / 派单员代收：`POST /ledger/receipts` → `paid=True` + 收款单 + 现金流水）；
    ② 单子照常派送、送达时 `collect_cash` 是默认的 False → 落到 `else` 分支 →
       **`paid` 被抹回 False**，而收款单与流水都还在，审计日志里也**没有任何翻 `paid` 的痕迹**；
    ③ 派单员打开「客户收款」，这张单又出现在"已送达未收"列表里 → 再核销一次 →
       **第二张收款单 + 第二条现金流水**：资金流入 = 2×，营业额 = 1×，客户被重复催收。

    所以现在的口径：**钱只认一次**。
      · 已经收过款 + 司机说收了现金 → 直接拒绝（再收一次就是重复收款）；
      · 已经收过款 + 没说要现金 → **保留**原来的收款方式与 `paid=True`（送达只记送达）。
    返回一句"要不要留痕"的说明（改了收款状态时非 None，调用方写进审计日志）。
    """
    if payment == "cash" and not order.collect_cash:
        raise ValueError(
            "这一单在派单时没有勾选「收取现金」，不能按现金收款。"
            "请让派单员先勾选（或改派），再按现金提交；否则只能按挂账提交。"
        )
    if _already_collected(db, order):
        if payment == "cash":
            raise ValueError(
                "这一单已经收过款了，司机再收一次现金就是重复收款。"
                "请让派单员核对「客户收款」里这张单的记录；确认钱确实没收到的，"
                "先处理掉那笔收款再送达。"
            )
        # 保留原来的收款方式（不许因为"派单没勾现金"就把一笔已收的钱改回未收）
        return f"送达时发现这一单已有收款记录，保留原收款方式（{order.payment_method or '—'} / paid=True）"
    before = (order.paid, order.payment_method)
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
    if (order.paid, order.payment_method) == before:
        return None
    return f"送达收款处理：paid {before[0]} → {order.paid}，方式 {before[1] or '—'} → {order.payment_method or '—'}"


def _apply_complete_payment_logged(db, order, payment: str | None, operator_id: int) -> None:
    """送达时的收款处理 + **留痕**（两个送达端点共用这一处，别各写一遍）。

    ⚠️ 为什么要有这个封装（2026-09-19 全项目 bug 报告 P1-10，实测 500）：
    两个送达端点原先各写了一遍收款调用，其中 `/{order_id}/complete-with-upload`（拍照送达，
    司机端的主力路径）**漏传了第一个位置参数** → `TypeError`（不是 `ValueError`，下面的
    `except ValueError` 接不住）→ **恒 500**，而 `complete_delivery` 已经跑完（改状态、扣库存、
    入账、生成司机账单），只有最后的 `db.commit()` 没执行 → 整笔回滚，**照片却已落盘**。
    另一条路径（`/{order_id}/complete`）虽然调对了，但它的留痕块写在端点里，
    所以拍照送达这一侧连"钱的收款状态变过"这件事都不会进审计。

    收口成一个函数之后，两条路径**在同一个地方**保证「调用参数 + 留痕」两件事都做到：
    留痕是 F1（2026-09-19 审计，高）的要求——送达只写 `ORDER_COMPLETE{photos:N}` 时，
    `paid` 被翻动在审计页上完全看不见，而"钱的状态变过"正是最需要能回查的那一类事实。
    """
    note = _apply_complete_payment(db, order, payment)
    if note:
        write_log(
            db,
            operator_id=operator_id,
            order_id=order.id,
            action=OperationAction.ORDER_COMPLETE,
            change_payload={"payment_change": note},
        )


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


@router.post("/{order_id}/return", response_model=OrderReturnOut)
def return_order_endpoint(
    order_id: int,
    body: OrderReturnBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_RETURN)),
) -> OrderReturnOut:
    """**订单退货**（2026-09-20 用户要求）。

    一次调用动五样东西（行级已退数量 / 账本红冲 / 库存回补 / 可能退现 / 订单状态），
    全部在 `services/order_return.py` 一处，本端点只做"取单 → 调服务 → 提交 → 回参"。

    ⚠️ **整单退货不是另一个端点**：客户端把每一行的数量都填满，走同一套行级校验。
       多一条"整单"的路径就多一条能绕过"货损那几件不能退"的路。
    ⚠️ 失败要**整单回滚**（所有变更在一个事务里）：红冲写了一半而库存没回补，
       是最难查的一类账（账上说退了、仓库里货没回来）。
    ⚠️ 取单时就**锁住这一行**（与收款同一条理由）：两个退货请求同时进来会各自通过
       "还能退几件"的校验（`max_returnable` 读的是各自快照里的 `returned_quantity`），
       退出去的量就会超过下单量。加锁之后后到的请求要等前一个提交，算出来的是真实余量。
    """
    order = db.scalars(
        select(Order)
        .options(selectinload(Order.order_products))
        .where(Order.id == order_id)
        .with_for_update()
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # 这一单若挂着一张**待处理的退货申请**：直连退货**照旧允许**，退完把它**自动关掉**
    # （2026-09-21 用户拍板：「把规则改成派单员退货之后，自动取消申请，然后它对应的数据发生改变」）。
    #
    # ⚠️ 这条规则换过一次方向，两次都记在这里，免得下一个人再翻回去：
    #   ① 最初（同日早些时候）我这里是 **400 fail-closed**：申请还挂着时不许直连退货。
    #      理由是真实的 —— 货主申请退 2 件（共 5 件）→ 派单员手工退了 2 件 → 申请仍是待处理 →
    #      他（或另一个派单员）再点「办理」时余量 3 ≥ 2、**校验全部通过** → 同一批货退第二遍。
    #   ② 用户拍板改成"**允许直连 + 自动关闭申请**"。← **现在跑的是这一条**。
    #      所以"同一批货退两遍"那个洞由**关闭申请**来堵：申请一旦不是 pending，
    #      `fulfill` 会被 `_check_pending` 拒（"已经由派单员直接退了货（自动关闭）"）。
    # ⛔ 因此下面这一次 `close_by_direct_return` 调用**不是可选的美化**：删掉它，
    #    ①里的双重退货就会原样复活（红线 `_check_return_request.py` 与它的反向验证钉着）。
    pending_req = return_request_svc.pending_for_order(db, order.id)
    try:
        result = return_order(
            db,
            order,
            [ReturnItem(order_product_id=i.order_product_id, quantity=i.quantity) for i in body.items],
            note=body.note,
            operator_id=current.id,
        )
        closed = None
        closed_note = ""
        if pending_req is not None:
            closed = return_request_svc.close_by_direct_return(
                db,
                order,
                dispatcher_id=current.id,
                items=[ReturnItem(order_product_id=i.order_product_id, quantity=i.quantity) for i in body.items],
            )
            if closed is not None:
                closed_note = closed[1]
                closed = closed[0]
    except OrderReturnError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    sid = order.shipper_id
    oid = order.id
    closed_id = closed.id if closed is not None else None
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    if sid is not None:
        background_tasks.add_task(_bg_ledger_updated_shipper, sid)
    if closed_id is not None:
        # 告诉货主"你那张申请被直接办掉了、实退多少"（差异也在这里如实写出来）
        background_tasks.add_task(
            _bg_notify_return_request_closed,
            closed_id,
            str(result.returned_amount),
            closed_note,
        )
    return OrderReturnOut(
        order_no=result.order_no,
        returned_amount=result.returned_amount,
        refund_amount=result.refund_amount,
        fully_returned=result.fully_returned,
        restocked_lines=result.restocked_lines,
        warnings=result.warnings,
        order=enrich_order_out(full, db, current),
    )


def _payment_scoped_order(order_id: int, db: Session) -> Order:
    order = db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # 已撤销 / 已退货的单都不能再收款或挂账（2026-09-20 合并成一条）：
    # 撤销 = 这单没发生过；退货 = 货款已经红冲掉了 —— 两种情况下再记一次收款/挂账，
    # 都是把一笔不存在的应收重新变成"收过钱"或"欠着钱"。
    if order.status in (OrderStatus.CANCELLED, OrderStatus.RETURNED):
        raise HTTPException(status_code=400, detail="已撤销/已退货订单不可收款、挂账")
    return order


def _reject_if_already_collected(db: Session, order: Order, what: str) -> None:
    """这张单**已经收过款**了 → 不许再把它改回「未收」（2026-09-19 审计 R14-2）。

    ### 缺口长什么样（真机可复现的三步，派单员一个人就能做完）
    1. 送货 → `POST /ledger/receipts`（逐单核销）→ 订单 `paid=True` + 一张收款单 + 一条现金流水；
    2. App 上这张已送达单的「挂账」按钮**一直是可点的**（`OrderDetailScreen` 只判 `!acting`）→
       `POST /orders/{id}/charge` → 本函数原来的写法是**无条件** `paid=False, payment_method=arrears`；
    3. 再核销一次 → 收款侧唯一的防重判据就是 `paid`（`accounting_service` 的 `if o.paid` 与
       条件 UPDATE 的 `Order.paid.is_(False)` 都只看它）→ **第二张收款单 + 第二条现金流水**。

    后果是"钱多记一笔"：资金收支流入 = 2×订单金额，而营业额 = 1×（按 `paid` 二选一），
    两个口径永久分叉；客户还会重新出现在「挂账未收」名单里被再催一次。

    ### 判据为什么是两条
    - `order.paid`：正常核销/现场收款的标记；
    - **指向这张单的收款流水**：`paid` 可能被别的路径改过（本轮修的就是"能改回去"这件事），
      而 `cash_flows(order_id=…, direction=in)` 是"钱真的进来过"的物证——它比标记可信。
    """
    # ⛔ 判据**只算一处**（2026-09-21 精简轮收口）：上面 `_already_collected`。
    #    这段原来在这里内联抄了一遍，而 `_already_collected` 的 docstring 一直写着
    #    "判据与 [_reject_if_already_collected] 同一套" —— 注释在承诺一件代码没保证的事：
    #    谁哪天改了 `paid` 与 inbound 流水的取舍，另一边不会跟着动，而**两边都不报错**。
    if not _already_collected(db, order):
        return
    raise HTTPException(
        status_code=400,
        detail=(
            f"这张单已经收过款了，不能{what}。"
            # ⛔ 这句原来写的是"请先在账本里把那笔收款处理掉"——而**系统里根本做不到**
            #    （2026-09-19 审计 F5：`ledger.py` 只有 `POST/GET /ledger/receipts`，
            #    没有 DELETE/PATCH，也没有反向分录）。让用户去做一件做不到的事，
            #    比直接说"做不到"更糟：他会反复找、以为是自己没找到入口。
            "系统目前**没有撤销收款的入口**，所以这一笔只能这样处理："
            "先确认钱是不是真的收到了——如果这笔收款记错了，请联系管理员在账上冲正；"
            "如果钱确实收到了，那这张单不用再收，保持现状即可。"
        ),
    )


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
    # ⚠️ 已收款的单**不许改回挂账**（2026-09-19 审计 R14-2）：收款侧唯一的防重判据就是 `paid`，
    #    把 paid 改回 False 等于给这张单**重新开了一次收款窗口**（收款单与现金流水都还在）。
    _reject_if_already_collected(db, order, "改回挂账")
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


def _template_category_ids(db: Session, template_id: int) -> list[int]:
    """一条价目挂的分类编号（沉淀时用来判断"这条路线上是不是已经有一条同类的价目"）。"""
    return list(
        db.scalars(
            select(FreightTemplateCategory.category_id).where(
                FreightTemplateCategory.template_id == template_id
            )
        ).all()
    )
