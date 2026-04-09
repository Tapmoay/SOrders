from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OperationLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    operator_id: int
    order_id: int | None
    action: str
    change_content: str | None
    created_at: datetime
