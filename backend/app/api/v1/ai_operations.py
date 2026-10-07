"""AI 操作流水（2026-10-08 CHG-0082 / 台账 L-52）—— **管理端单独一页要看的那个列表**。

它与 `api/v1/operation_logs.py`（异常与审计页）的分工：

| | operation_logs | ai_operation_logs（本文件） |
|---|---|---|
| 记什么 | 业务写入**成功**之后的一行 | AI **发起**的一次请求（成功、4xx、5xx 都记） |
| 一行 = | 一次业务改动 | 一次 AI 动作 |
| 回答 | "谁把这一单改成这样了" | "AI 替我干过什么、成没成、为什么不成" |

⛔ 权限沿用 `OPERATION_LOG_READ`（**不新开权限点**）：能看审计页的人就是能看 AI 流水的人 ——
新开一个权限点意味着 `core/capabilities.py`、`rbac.ROLE_PERMISSIONS`、"能看哪些页"三处都要跟着改，
而这一页没有任何"多出来的人"要看（口径与用户 2026-10-08 的勾选一致：管理端可查）。
"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.pagination import finish_page
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import AiOperationLog, User
from app.schemas.ai_operation_log import AiOperationLogOut

router = APIRouter(prefix="/ai", tags=["ai"])


def _out(row: AiOperationLog) -> AiOperationLogOut:
    """把 ORM 行转成出参，并补上"用户看得懂"的那个字段（谁）。

    为什么不在 schema 里用 relationship 自动带：`user_name` 是"姓名优先、没有就用手机号"
    的取值规则，写在端点里只有一处（与审计页 `operation_logs._out` 同一套写法）。
    """
    item = AiOperationLogOut.model_validate(row)
    u = row.user
    item.user_name = (u.full_name or u.phone) if u is not None else None
    return item


@router.get("/operations", response_model=list[AiOperationLogOut])
def list_ai_operations(
    response: Response,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.OPERATION_LOG_READ)),
    # 三把筛子就是这一页要回答的三个问题：只看失败的 / 只看某一类动作 / 只看某个人。
    ok: bool | None = Query(None),
    action: str | None = Query(None),
    user_id: int | None = Query(None),
    # ⚠️ `ge` 不是装饰（2026-09-24 第 19 轮实测）：`?limit=-5` 在 SQLite 上是**不限量**，
    #    生产 MySQL 直接 500；`skip=-3` 同理。
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> list[AiOperationLogOut]:
    q = (
        select(AiOperationLog)
        .options(joinedload(AiOperationLog.user))
        .order_by(AiOperationLog.id.desc())
        .offset(skip)
        # 多取一行判截断：这一页最容易骗人的地方就是"只看到最近 200 条以为就这些"，
        # 而"AI 到底干过什么"正是它存在的理由（响应头 X-Truncated 见 core/pagination.py）。
        .limit(limit + 1)
    )
    if ok is not None:
        q = q.where(AiOperationLog.ok == ok)
    if action is not None:
        q = q.where(AiOperationLog.action == action)
    if user_id is not None:
        q = q.where(AiOperationLog.user_id == user_id)
    rows = [_out(r) for r in db.scalars(q).unique().all()]
    return finish_page(rows, limit, response)
