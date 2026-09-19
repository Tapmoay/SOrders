"""司机运费结算（派单员/司机）：按送达月份聚合已送达且计价的订单。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.rbac import Permission, user_role_key
from app.database import get_db
from app.deps import get_current_user, require_permission
from app.models import Order, User
from app.models.enums import OrderStatus, UserRole
from app.services.order_response import apply_driver_view_gating
from app.services.order_response import enrich_order_out as _enrich  # noqa: F401
from app.services.driver_pay import pay_for_order

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
    elif month:
        start, end = await _month_range(month)
    else:
        raise HTTPException(status_code=400, detail="需提供 month 或 from/to 范围")
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
            # 计件(PIECE)司机全部列出（未定价=待定价可后补）；仅兼容旧单（快照空但有价）
            #
            # ⚠️ 用 `func.upper(...)` 比，不要写 `== "PIECE"`：
            # 历史数据里这个快照列两种写法都出现过（AI 写小写、页面写大写），
            # 精确比较会让"库里是小写 piece 的司机"**在结算页整批消失**——
            # 而司机账单那边本来就用的是 upper()，于是同一批单在账单里算得出来、
            # 在这里看不到，两张表对不上却谁都不报错。
            # 写入侧已经归一（`models/user.py::normalize_billing_mode`），
            # 这里放宽是为了让**存量数据**也显示正确。
            or_(
                func.upper(Order.driver_billing_mode_snapshot) == "PIECE",
                and_(Order.driver_billing_mode_snapshot.is_(None), Order.freight_fee.isnot(None)),
            ),
        )
        .order_by(Order.delivered_at.desc())
    )
    orders = list(db.scalars(q))
    groups: dict[int, dict] = {}
    for o in orders:
        driver_id = o.driver_id or 0
        g = groups.setdefault(
            driver_id,
            {"driver_id": driver_id, "driver_name": "", "count": 0, "total": 0.0, "orders": []},
        )
        driver = db.get(User, driver_id) if driver_id else None
        if driver is not None:
            g["driver_name"] = driver.full_name or driver.phone or ""
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
