from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission, role_has_permission, user_role_key
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import Ledger, LedgerExportJob, Order, User
from app.models.enums import LedgerSource, OperationAction, UserRole
from app.models.export_job import ExportFormat, ExportJobStatus
from app.schemas.export_job import LedgerExportJobCreate, LedgerExportJobOut
from app.schemas.ledger import (
    LedgerCreate,
    LedgerOut,
    LedgerSyncFromOrdersBody,
    LedgerUpdate,
)
from app.services.ledger_export_worker import run_ledger_export_job_task
from app.services.ledger_response import ledger_to_out
from app.services.ledger_sync import (
    sync_delivered_orders_to_ledger,
    sync_order_product_from_ledger,
)
from app.services.operation_log_service import write_log
from app.services.push_events import push_ledger_updated

router = APIRouter(prefix="/ledger", tags=["ledger"])


async def _bg_push_ledger_shipper(shipper_id: int) -> None:
    await push_ledger_updated(shipper_id)


@router.get("/entries", response_model=list[LedgerOut])
def list_entries(
    current: CurrentUser,
    db: Session = Depends(get_db),
    shipper_id: int | None = Query(None),
    temp_shipper_name: str | None = Query(None, description="临时货主名称（与 shipper_id 二选一）"),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
) -> list[LedgerOut]:
    from datetime import date as date_type

    role = user_role_key(current)
    q = select(Ledger).order_by(Ledger.entry_date.desc(), Ledger.id.desc())
    tsn = (temp_shipper_name or "").strip()
    if role == UserRole.SHIPPER.value:
        q = q.where(Ledger.shipper_id == current.id)
    elif role == UserRole.DISPATCHER.value:
        if shipper_id is not None and tsn:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请只指定 shipper_id 或 temp_shipper_name 之一",
            )
        if shipper_id is not None:
            q = q.where(Ledger.shipper_id == shipper_id)
        elif tsn:
            q = q.where(Ledger.shipper_id.is_(None)).where(Ledger.temp_shipper_name == tsn)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="派单员查询账本时请指定货主（shipper_id）或临时货主名称（temp_shipper_name）",
            )
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")

    if date_from:
        try:
            df = date_type.fromisoformat(date_from[:10])
            q = q.where(Ledger.entry_date >= df)
        except ValueError:
            raise HTTPException(status_code=400, detail="开始日期格式无效") from None
    if date_to:
        try:
            dt = date_type.fromisoformat(date_to[:10])
            q = q.where(Ledger.entry_date <= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="结束日期格式无效") from None

    rows = list(db.scalars(q).all())
    return [ledger_to_out(r, db) for r in rows]


@router.get("/temp-shipper-names", response_model=list[str])
def list_temp_shipper_names(
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> list[str]:
    """派单员：曾出现过的临时货主称呼（账本或订单），用于快捷筛选；订单送达时已自动入账，无需「创建账本」。"""
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    names: set[str] = set()
    for raw in db.scalars(
        select(Ledger.temp_shipper_name).where(
            Ledger.shipper_id.is_(None),
            Ledger.temp_shipper_name.isnot(None),
        )
    ).all():
        t = (raw or "").strip()
        if t:
            names.add(t)
    for raw in db.scalars(
        select(Order.temp_shipper_name).where(
            Order.shipper_id.is_(None),
            Order.temp_shipper_name.isnot(None),
        )
    ).all():
        t = (raw or "").strip()
        if t:
            names.add(t)
    return sorted(names)


@router.post("/sync-from-delivered-orders")
def sync_ledger_from_delivered_orders(
    body: LedgerSyncFromOrdersBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> dict:
    """按历史已送达订单补全/刷新账本（幂等）。仅派单员。"""
    n, shipper_ids = sync_delivered_orders_to_ledger(db, body.shipper_id, body.temp_shipper_name)
    db.commit()
    for sid in shipper_ids:
        background_tasks.add_task(_bg_push_ledger_shipper, sid)
    return {"orders_synced": n, "shippers_notified": len(shipper_ids)}


@router.post("/entries", response_model=LedgerOut, status_code=status.HTTP_201_CREATED)
def create_entry(
    body: LedgerCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> LedgerOut:
    total = body.total
    if total is None or total == Decimal("0"):
        total = body.unit_price * body.quantity
    sid = body.shipper_id
    tname = body.temp_shipper_name if sid is None else None
    row = Ledger(
        shipper_id=sid,
        temp_shipper_name=tname,
        entry_date=body.entry_date,
        product_name=body.product_name,
        quantity=body.quantity,
        unit_price=body.unit_price,
        total=total,
        order_id=body.order_id,
        order_product_id=body.order_product_id,
        product_id=body.product_id,
        source=body.source,
        note=body.note,
    )
    db.add(row)
    db.flush()
    sync_order_product_from_ledger(db, row)
    write_log(
        db,
        operator_id=current.id,
        order_id=body.order_id,
        action=OperationAction.LEDGER_CREATE,
        change_payload={"ledger_id": row.id},
    )
    db.commit()
    db.refresh(row)
    if row.shipper_id is not None:
        background_tasks.add_task(_bg_push_ledger_shipper, row.shipper_id)
    return ledger_to_out(row, db)


@router.get("/entries/{entry_id}", response_model=LedgerOut)
def get_entry(
    entry_id: int,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> LedgerOut:
    row = db.get(Ledger, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    role = user_role_key(current)
    if role == UserRole.SHIPPER.value and (
        row.shipper_id is None or row.shipper_id != current.id
    ):
        raise HTTPException(status_code=403, detail="无权访问")
    if role not in (UserRole.SHIPPER.value, UserRole.DISPATCHER.value):
        raise HTTPException(status_code=403, detail="无权访问")
    return ledger_to_out(row, db)


@router.patch("/entries/{entry_id}", response_model=LedgerOut)
def update_entry(
    entry_id: int,
    body: LedgerUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> LedgerOut:
    """派单员：订单自动同步行与手动行均可改明细；修改订单来源行时会尝试回写对应订单明细。"""
    row = db.get(Ledger, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    shipper_id = row.shipper_id
    detail_editable = row.source in (LedgerSource.MANUAL, LedgerSource.ORDER)
    detail_keys = (
        "entry_date",
        "product_name",
        "quantity",
        "unit_price",
        "total",
        "order_id",
        "product_id",
    )
    raw = body.model_dump(exclude_unset=True)
    wants_detail = any(k in raw for k in detail_keys)
    if wants_detail and not detail_editable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无法修改该行商品与金额",
        )
    if detail_editable:
        if "entry_date" in raw and raw["entry_date"] is not None:
            row.entry_date = raw["entry_date"]
        if "product_name" in raw and raw["product_name"] is not None:
            row.product_name = raw["product_name"].strip()
        if "unit_price" in raw and raw["unit_price"] is not None:
            row.unit_price = raw["unit_price"]
        if "quantity" in raw and raw["quantity"] is not None:
            row.quantity = raw["quantity"]
        if "order_id" in raw:
            row.order_id = raw["order_id"]
        if "product_id" in raw:
            row.product_id = raw["product_id"]
        if "total" in raw and raw["total"] is not None:
            row.total = raw["total"]
        elif "unit_price" in raw or "quantity" in raw:
            row.total = row.unit_price * row.quantity
    if body.note is not None:
        row.note = body.note
    db.flush()
    sync_order_product_from_ledger(db, row)
    write_log(
        db,
        operator_id=current.id,
        order_id=row.order_id,
        action=OperationAction.LEDGER_UPDATE,
        change_payload={"ledger_id": row.id},
    )
    db.commit()
    db.refresh(row)
    if shipper_id is not None:
        background_tasks.add_task(_bg_push_ledger_shipper, shipper_id)
    return ledger_to_out(row, db)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(
    entry_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> None:
    row = db.get(Ledger, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    shipper_id = row.shipper_id
    oid = row.order_id
    write_log(
        db,
        operator_id=current.id,
        order_id=oid,
        action=OperationAction.LEDGER_DELETE,
        change_payload={"ledger_id": entry_id},
    )
    db.delete(row)
    db.commit()
    if shipper_id is not None:
        background_tasks.add_task(_bg_push_ledger_shipper, shipper_id)


@router.post(
    "/export-jobs",
    response_model=LedgerExportJobOut,
    status_code=status.HTTP_201_CREATED,
)
def create_export_job(
    body: LedgerExportJobCreate,
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> LedgerExportJob:
    role = user_role_key(current)
    if role == UserRole.SHIPPER.value:
        if body.shipper_id != current.id:
            raise HTTPException(status_code=403, detail="仅能导出自己的账本")
    elif role == UserRole.DISPATCHER.value:
        if not role_has_permission(role, Permission.LEDGER_EDIT):
            raise HTTPException(status_code=403, detail="无权访问")
    else:
        raise HTTPException(status_code=403, detail="无权访问")
    if body.date_from > body.date_to:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
    job = LedgerExportJob(
        created_by_id=current.id,
        shipper_id=body.shipper_id,
        file_format=body.export_format,
        date_from=body.date_from,
        date_to=body.date_to,
        status=ExportJobStatus.PENDING,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(run_ledger_export_job_task, job.id)
    return job


@router.get("/export-jobs/{job_id}", response_model=LedgerExportJobOut)
def get_export_job(
    job_id: int,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> LedgerExportJob:
    job = db.get(LedgerExportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    role = user_role_key(current)
    if role == UserRole.SHIPPER.value:
        if job.created_by_id != current.id or job.shipper_id != current.id:
            raise HTTPException(status_code=403, detail="无权访问")
    elif role == UserRole.DISPATCHER.value:
        if job.created_by_id != current.id:
            raise HTTPException(status_code=403, detail="无权访问")
    else:
        raise HTTPException(status_code=403, detail="无权访问")
    return job
