"""司机运费结算（派单员/司机）：按送达月份聚合已送达且计价的订单。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.business_time import to_utc_naive
from app.core.rbac import Permission, user_role_key
from app.database import get_db
from app.deps import get_current_user, require_permission
from app.models import Order, User
from app.models.enums import OrderStatus, UserRole
from app.services.order_response import enrich_order_out as _enrich  # noqa: F401
from app.services.driver_pay import pay_for_order, per_order_pay_filter
from app.services.soft_delete import dialable_phone

router = APIRouter(prefix="/freight-settlement", tags=["freight-settlement"])


async def _month_range(month: str) -> tuple:
    """YYYY-MM → (start, end) datetime（含起，不含止）。"""
    from datetime import datetime

    try:
        y, m = month.split("-")
        y, m = int(y), int(m)
        if not (1 <= m <= 12):
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="月份格式须为 YYYY-MM")
    start = datetime(y, m, 1)
    end = datetime(y + (m == 12 and 1 or 0), m % 12 + 1, 1) if m != 12 else datetime(y + 1, 1, 1)
    return start, end


@router.get("")
async def freight_settlement(
    month: str | None = Query(None, description="YYYY-MM"),
    from_: str | None = Query(None, alias="from", description="送达时间范围起（ISO，含）"),
    to: str | None = Query(None, description="送达时间范围止（ISO，不含）"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    from datetime import datetime

    if from_ and to:
        try:
            start = datetime.fromisoformat(from_)
            end = datetime.fromisoformat(to)
        except ValueError:
            raise HTTPException(status_code=400, detail="from/to 须为 ISO 时间格式")
        # ⚠️ 顺序反了要**当场拒绝**（2026-09-24 第 22 轮 F8-1）：`from>to` 时 SQL 恒不命中，
        #    于是这一页显示"这段时间没有应付"—— 而结算页是"该给司机多少钱"的页面，
        #    空列表会被读成"确实不用付"。同族的 `/reports/turnover` 等端点回 400。
        if start > end:
            raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
    elif month:
        start, end = await _month_range(month)
    else:
        raise HTTPException(status_code=400, detail="需提供 month 或 from/to 范围")
    # ⚠️ 客户端传的是**当地墙上时间**（`2026-09-19T00:00:00`），而 `delivered_at` 存的是 UTC：
    #    直接拿去比，东八区当地 00:00~08:00 送达的单会被整段漏掉——报表里算得出来的应付，
    #    在结算页里看不见（2026-09-19 审计 R12-M11）。统一换算到 UTC 再比。
    start = to_utc_naive(start)
    end = to_utc_naive(end)
    q = (
        select(Order)
        .options(selectinload(Order.order_products))
        .where(
            Order.status == OrderStatus.DELIVERED,
            Order.delivered_at.isnot(None),
            Order.delivered_at >= start,
            Order.delivered_at < end,
            # 隔离区（软删）的单**不进结算**：用户删掉一张错单之后，
            # 谁都不该再为它付运费——而删除是"伪装删除"，行还在库里。
            Order.deleted_at.is_(None),
            # 计件(PIECE)司机全部列出（未定价 = 待定价可后补），旧单（快照空但有价）也算 ——
            # 判据只有一处：`driver_pay.per_order_pay_filter`（大小写/空串的坑都记在那儿）
            per_order_pay_filter(),
        )
        .order_by(Order.delivered_at.desc())
    )
    orders = list(db.scalars(q))
    # 司机名册**一次取全**（`IN`）：原来是循环里 `db.get(User, driver_id)`，
    # 首次命中的确会真发一条 SQL —— 结算页动辄几十个司机、上千单，那是几十条本可以合并的查询。
    driver_ids = {o.driver_id for o in orders if o.driver_id}
    driver_by_id: dict[int, User] = (
        {u.id: u for u in db.scalars(select(User).where(User.id.in_(driver_ids)))} if driver_ids else {}
    )
    groups: dict[int, dict] = {}
    for o in orders:
        driver_id = o.driver_id or 0
        g = groups.setdefault(
            driver_id,
            {
                "driver_id": driver_id,
                "driver_name": "",
                # 手机号 + 能不能登录：与货主/批发商账**同一套**（用户 2026-09-19 要的
                # 搜索键是「名称 / 电话 / 电话后 4 位」，只下发名字等于那条需求只做了一半）。
                "driver_phone": None,
                "driver_active": False,
                "count": 0,
                "total": 0.0,
                "orders": [],
            },
        )
        driver = driver_by_id.get(driver_id) if driver_id else None
        if driver is not None and not g["driver_phone"]:
            # 可拨号码的唯一口径（活账号带 `_del` 后缀 = 号码已被别人抢走 → 不给号码）
            g["driver_phone"] = dialable_phone(driver)
        if driver is not None and not g["driver_name"]:
            g["driver_name"] = driver.full_name or driver.phone or ""
            g["driver_active"] = bool(getattr(driver, "is_active", True))
        # ⚠️ v3.36：这里原来把 `freight_fee` 当成"司机该拿的钱"（因为当时计件=全额运费）。
        #    现在司机可能挂着计费规则（每单固定 / 运费提成 / 商品提成），
        #    "该拿多少"必须走和账单**同一个**函数，否则这一页和司机账单页会各说一个数。
        #    运费仍然照原样显示（它是货主那头的价，也是提成的基数），只是不再等于司机应得。
        pay = pay_for_order(o)
        g["count"] += 1
        g["total"] = round(g["total"] + float(pay.total), 2)
        g["orders"].append(
            {
                "order_id": o.id,
                "order_no": o.order_no,
                "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
                "freight_fee": str(o.freight_fee) if o.freight_fee is not None else None,
                # 应得 + 拆件：结算页要把账摆开（只给一个总数，司机问"怎么算的"就答不上来）
                "pay_total": str(pay.total),
                "pay_piece": str(pay.piece),
                "pay_commission": str(pay.commission),
                "delivery_description": o.delivery_description,
                "address_detail": o.address_detail,
            }
        )
    result = sorted(groups.values(), key=lambda x: -x["total"])
    role = user_role_key(current)
    if role == UserRole.DRIVER.value:
        # 司机只能看自己当月运费
        result = [g for g in result if g["driver_id"] == current.id]
    elif role != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员或司机可查看")
    return {"month": month, "groups": result}
