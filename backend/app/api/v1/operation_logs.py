from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.pagination import finish_page
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import OperationLog, User
from app.schemas.operation_log import OperationLogOut

router = APIRouter(prefix="/operation-logs", tags=["operation-logs"])


def _out(row: OperationLog) -> OperationLogOut:
    """把 ORM 行转成出参，并**补上两个"用户看得懂"的字段**。

    为什么不在 schema 里用 relationship 自动带：`operator_name` 是"姓名优先、没有就用手机号"
    的取值规则，写在端点里只有一处；`order_no` 来自订单表，也要 join。
    这两个字段是审计页的刚需（谁改的 / 哪一单），只给 `operator_id`/`order_id` 用户看不懂。
    """
    item = OperationLogOut.model_validate(row)
    op = row.operator
    item.operator_name = (op.full_name or op.phone) if op is not None else None
    item.order_no = row.order.order_no if row.order is not None else None
    return item


@router.get("", response_model=list[OperationLogOut])
def list_operation_logs(
    response: Response,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.OPERATION_LOG_READ)),
    order_id: int | None = Query(None),
    operator_id: int | None = Query(None),
    # ⚠️ `ge` 不是装饰（2026-09-24 第 19 轮实测）：`?limit=-5` 在 SQLite 上是**不限量**
    #    （实测返回全表 986 行减 5），生产 MySQL 直接 500；`skip=-3` 同理。
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> list[OperationLogOut]:
    q = (
        select(OperationLog)
        .options(joinedload(OperationLog.operator), joinedload(OperationLog.order))
        .order_by(OperationLog.id.desc())
        .offset(skip)
        # 多取一行判截断（2026-09-19 外部完整检查 §9.1）：审计页拿不到"还有更早的"，
        # 用户会据此判断"这条改动没被记录"——而审计的全部价值就在"能翻到"。
        .limit(limit + 1)
    )
    if order_id is not None:
        q = q.where(OperationLog.order_id == order_id)
    if operator_id is not None:
        q = q.where(OperationLog.operator_id == operator_id)
    rows = [_out(r) for r in db.scalars(q).unique().all()]
    return finish_page(rows, limit, response)


@router.get("/{log_id}", response_model=OperationLogOut)
def get_operation_log(
    log_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.OPERATION_LOG_READ)),
) -> OperationLogOut:
    row = db.get(OperationLog, log_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到对应记录")
    return _out(row)
