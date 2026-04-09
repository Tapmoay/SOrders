import json
from typing import Any

from sqlalchemy.orm import Session

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
    row = OperationLog(operator_id=operator_id, order_id=order_id, action=act, change_content=content)
    db.add(row)
    return row
