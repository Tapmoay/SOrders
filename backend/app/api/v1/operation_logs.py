from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import OperationLog, User
from app.schemas.operation_log import OperationLogOut

router = APIRouter(prefix="/operation-logs", tags=["operation-logs"])


@router.get("", response_model=list[OperationLogOut])
def list_operation_logs(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.OPERATION_LOG_READ)),
    order_id: int | None = Query(None),
    operator_id: int | None = Query(None),
    skip: int = 0,
    limit: int = Query(200, le=1000),
) -> list[OperationLog]:
    q = select(OperationLog).order_by(OperationLog.id.desc()).offset(skip).limit(limit)
    if order_id is not None:
        q = q.where(OperationLog.order_id == order_id)
    if operator_id is not None:
        q = q.where(OperationLog.operator_id == operator_id)
    return list(db.scalars(q).all())


@router.get("/{log_id}", response_model=OperationLogOut)
def get_operation_log(
    log_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.OPERATION_LOG_READ)),
) -> OperationLog:
    row = db.get(OperationLog, log_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到对应记录")
    return row
