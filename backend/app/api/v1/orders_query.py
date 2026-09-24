"""orders 的**查询组**：列表 / 待派计数 / 详情（阶段 4 第一步，纯搬迁）。

⚠️ 注册顺序有讲究：`/orders/pending-dispatch-count` 这类**静态路径**必须排在同方法的
`/orders/{order_id}` **前面** —— 否则它先命中动态路由（参数是 int 时表现为 422）。
本模块内三条的顺序就是按这个来的：list（`""`）→ pending-dispatch-count → {order_id}。
搬迁前后的「静态路径被动态路径遮蔽」关系由 `_tools/qa/_api_contract_snapshot.py` 机器比对，
实测两边都是 0 对。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload
from app.core.business_time import business_range_utc
from app.core.pagination import finish_page
from app.core.query_text import LIKE_ESCAPE, like_pattern
from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser, parse_date_range
from app.models import Order, User
from app.models.enums import OrderStatus, UserRole
from app.schemas.order import OrderOut
from app.services.order_money import money_map
from app.services.order_response import enrich_order_out
from app.api.v1.orders_common import _get_order_scoped

router = APIRouter(prefix="/orders", tags=["orders"])


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
        # ⚠️ pattern 必须过 `like_pattern()`（2026-09-24 第 19 轮）：直接 `f"%{qtrim}%"` 的话
        #    用户打一个 `%` 就是"不加条件"—— 实测 `GET /orders?q=%25&limit=5000` 返回**全部 426 张单**。
        term = like_pattern(qtrim)
        assert term is not None          # 上面已判过 qtrim 非空
        stmt = (
            select(Order)
            .outerjoin(shipper_u, Order.shipper_id == shipper_u.id)
            .outerjoin(driver_u, Order.driver_id == driver_u.id)
            .options(selectinload(Order.order_products))
            .where(
                or_(
                    Order.order_no.like(term, escape=LIKE_ESCAPE),
                    shipper_u.full_name.like(term, escape=LIKE_ESCAPE),
                    shipper_u.phone.like(term, escape=LIKE_ESCAPE),
                    Order.temp_shipper_name.like(term, escape=LIKE_ESCAPE),
                    Order.address_detail.like(term, escape=LIKE_ESCAPE),
                    driver_u.full_name.like(term, escape=LIKE_ESCAPE),
                    driver_u.phone.like(term, escape=LIKE_ESCAPE),
                    # 收货人 / 下单人的名字与电话（2026-09-20）：派单员搜索走的是这一支，
                    # 少了这两行就会出现"卡片上看得见名字、搜这个名字却搜不到"
                    Order.contact_dongjia_name.like(term, escape=LIKE_ESCAPE),
                    Order.contact_boss_name.like(term, escape=LIKE_ESCAPE),
                    Order.contact_dongjia_phone.like(term, escape=LIKE_ESCAPE),
                    Order.contact_boss_phone.like(term, escape=LIKE_ESCAPE),
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
        # ⚠️ pattern 必须过 `like_pattern()`（2026-09-24 第 19 轮）：直接 `f"%{qtrim}%"` 的话
        #    用户打一个 `%` 就是"不加条件"—— 实测 `GET /orders?q=%25&limit=5000` 返回**全部 426 张单**。
        term = like_pattern(qtrim)
        assert term is not None          # 上面已判过 qtrim 非空
        q = q.where(
            or_(
                Order.order_no.like(term, escape=LIKE_ESCAPE),
                Order.address_detail.like(term, escape=LIKE_ESCAPE),
                Order.delivery_description.like(term, escape=LIKE_ESCAPE),
                Order.contact_boss_phone.like(term, escape=LIKE_ESCAPE),
                Order.contact_dongjia_phone.like(term, escape=LIKE_ESCAPE),
                # 收货人/下单人的**名字**也一起搜（2026-09-20 加的那两列）：
                # 卡片与详情上都写着这两个名字，搜不到就是"看得见却搜不着"
                Order.contact_dongjia_name.like(term, escape=LIKE_ESCAPE),
                Order.contact_boss_name.like(term, escape=LIKE_ESCAPE),
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


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, current: CurrentUser, db: Session = Depends(get_db)) -> OrderOut:
    order = _get_order_scoped(order_id, current, db)
    return enrich_order_out(order, db, current)
