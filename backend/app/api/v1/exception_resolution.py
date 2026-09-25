"""异常订单的**解决**端点（订单域的写动作，URL 挂在 `/stats` 下）。

## 为什么单独一个文件，而不是留在 `stats.py` 里
第二轮 R2-05 摸底时抓到一处真违规：这个端点住在**报表模块**里，做的却是
**写业务状态**（`orders.is_exception` / `exception_reason` /
`exception_resolution` / `exception_resolved_at`），而且开的是**自己的**
`SessionLocal()` —— 那次写不在请求的事务里，报表层的任何只读判据都看不见它。
方向指南 §八 的原话是：「报表是**事实消费者，而不是事实生产者**」。

## 为什么不干脆把它挪到 `/orders/…` 下面
⛔ **URL 是客户端契约**：App 的「报表中心 → 异常与审计」那个按钮打的就是这个地址。
搬 URL 等于把线上客户端打死（本项目把「URL / 入参 / 出参 / 权限一字未改」当作搬迁的硬要求）。
所以做法是**把实现搬出报表层、URL 留在原地**：

| | 之前 | 现在 |
|---|---|---|
| 文件 | `api/v1/stats.py`（报表层） | **本文件**（订单域的写端点） |
| 写逻辑 | 写在路由体里 | `app.commands.order.resolve_exception`（订单域命令层） |
| 会话 | 自己 `SessionLocal()` | 请求的 `db`（同一个事务） |
| URL / 入参 / 出参 / 权限 | — | **一字未改** |

⚠️ 本文件**不在**报表层的只读清单里（`_check_report_boundary.py` 的 `REPORT_FILES`）——
它是订单域的写端点，只是恰好挂在 `/stats` 前缀下。判据会同时核对：
报表层**没有**任何写动词，而**这个**写端点确实存在（不然功能就悄悄没了）。
"""

from fastapi import APIRouter, Depends, HTTPException

from app.commands import order as order_commands
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import User
from app.schemas.exception import ExceptionResolveBody

from sqlalchemy.orm import Session

router = APIRouter(prefix="/stats", tags=["stats"])


@router.post("/exception-orders/{order_id}/resolve", response_model=dict)
def resolve_exception_order(
    order_id: int,
    body: "ExceptionResolveBody",
    current: User = Depends(require_permission(Permission.STATS_READ)),
    db: Session = Depends(get_db),
) -> dict:
    """派单员解决异常：填写解决说明，订单标记已解决。"""
    note = (body.note or "").strip()
    try:
        order_commands.resolve_exception(db, actor=current, order_id=order_id, note=note)
    except order_commands.CommandError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from None
    return {"ok": True, "order_id": order_id}
