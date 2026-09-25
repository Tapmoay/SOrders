import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.client_origin import get_origin
from app.core.command_id import get_command_id
from app.core.request_id import get_request_id
from app.models import OperationLog
from app.models.enums import OperationAction


def write_log(
    db: Session,
    *,
    operator_id: int,
    order_id: int | None,
    action: OperationAction | str,
    change_payload: Any | None = None,
) -> OperationLog:
    if change_payload is None:
        content: str | None = None
    elif isinstance(change_payload, str):
        content = change_payload
    else:
        content = json.dumps(change_payload, ensure_ascii=False)
    act = action.value if isinstance(action, OperationAction) else str(action)
    # 整改报告 §15 ① 的最后一跳：把这一行接回产生它的那次 HTTP 请求。
    # ⚠️ 只在这一处填（本函数是全库**唯一**构造 OperationLog 的地方）—— 谁要是绕过它自己
    #    构造，那一行就永远没有 request_id，而「缺一个字段」不会报错，只会让报障时接不上。
    rid = get_request_id() or None   # 请求外（后台任务/脚本/保留期治理）→ NULL，不是空串
    row = OperationLog(
        operator_id=operator_id,
        order_id=order_id,
        action=act,
        change_content=content,
        request_id=rid,
        # R3-04-A：同一次命令里的所有审计行带同一个 command_id（命令层开的作用域，见 core/command_id.py）。
        command_id=get_command_id() or None,
        # 报告 §15 ②：**同一处填**（与 request_id 并排的理由一样：本函数是全库唯一构造点），
        # 后台任务 / 脚本里没有请求上下文 → `get_origin()` 返回 human，那正是事实。
        origin=get_origin(),
    )
    db.add(row)
    return row
