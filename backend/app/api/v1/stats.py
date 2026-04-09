from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import User
from app.schemas.stats import (
    DriverPerformanceOut,
    DriverPerformanceRow,
    DrilldownOrderItem,
    ExceptionOrderItem,
    ShipperActivityOut,
    ShipperProductChartOut,
    StatsExportBody,
)
from app.services import stats_service
from app.services.stats_export import build_stats_export_bytes

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/shipper-product-chart", response_model=ShipperProductChartOut)
def get_shipper_product_chart(
    date_from: date = Query(..., description="含起"),
    date_to: date = Query(..., description="含止"),
    granularity: Literal["month", "year"] = Query("month"),
    metric: Literal["quantity", "amount"] = Query("quantity"),
    _: User = Depends(require_permission(Permission.STATS_READ)),
    db: Session = Depends(get_db),
) -> ShipperProductChartOut:
    cats, series = stats_service.shipper_product_chart(
        db, date_from, date_to, granularity, metric
    )
    return ShipperProductChartOut(
        granularity=granularity,
        metric=metric,
        categories=cats,
        series=series,
    )


@router.get("/shipper-activity", response_model=ShipperActivityOut)
def get_shipper_activity(
    shipper_id: int = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    _: User = Depends(require_permission(Permission.STATS_READ)),
    db: Session = Depends(get_db),
) -> ShipperActivityOut:
    data = stats_service.shipper_activity(db, shipper_id, date_from, date_to)
    return ShipperActivityOut.model_validate(data)


@router.get("/product-drilldown", response_model=list[DrilldownOrderItem])
def get_product_drilldown(
    product_name: str = Query(..., min_length=1),
    date_from: date = Query(...),
    date_to: date = Query(...),
    _: User = Depends(require_permission(Permission.STATS_READ)),
    db: Session = Depends(get_db),
) -> list[DrilldownOrderItem]:
    rows = stats_service.product_drilldown(db, product_name, date_from, date_to)
    return [DrilldownOrderItem.model_validate(r) for r in rows]


@router.get("/driver-performance", response_model=DriverPerformanceOut)
def get_driver_performance(
    date_from: date = Query(...),
    date_to: date = Query(...),
    _: User = Depends(require_permission(Permission.STATS_READ)),
    db: Session = Depends(get_db),
) -> DriverPerformanceOut:
    rows = stats_service.driver_performance(db, date_from, date_to)
    label = f"{date_from.isoformat()} ~ {date_to.isoformat()}"
    return DriverPerformanceOut(
        period_label=label,
        drivers=[DriverPerformanceRow.model_validate(r) for r in rows],
    )


@router.get("/exception-orders", response_model=list[ExceptionOrderItem])
def get_exception_orders(
    date_from: date = Query(...),
    date_to: date = Query(...),
    _: User = Depends(require_permission(Permission.STATS_READ)),
    db: Session = Depends(get_db),
) -> list[ExceptionOrderItem]:
    rows = stats_service.exception_orders(db, date_from, date_to)
    return [ExceptionOrderItem.model_validate(r) for r in rows]


@router.post("/export")
def post_stats_export(
    body: StatsExportBody,
    _: User = Depends(require_permission(Permission.STATS_READ)),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    raw = build_stats_export_bytes(db, body)
    fn = f"stats-{body.date_from.isoformat()}-{body.date_to.isoformat()}.xlsx"
    return StreamingResponse(
        iter([raw]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fn}"'},
    )
