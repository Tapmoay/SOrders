"""司机运费结算（派单员/司机）：按送达月份聚合已送达且计价的订单。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.rbac import Permission, user_role_key
from app.database import get_db
from app.deps import get_current_user, require_permission
from app.models import Order, User
from app.models.enums import OrderStatus, UserRole
from app.services.order_response import apply_driver_view_gating
from app.services.order_response import enrich_order_out as _enrich  # noqa: F401

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
            Order.freight_fee.isnot(None),
            Order.delivered_at.isnot(None),
            Order.delivered_at >= start,
            Order.delivered_at < end,
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
        fee = float(o.freight_fee or 0)
        g["count"] += 1
        g["total"] = round(g["total"] + fee, 2)
        g["orders"].append(
            {
                "order_id": o.id,
                "order_no": o.order_no,
                "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
                "freight_fee": str(o.freight_fee),
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
