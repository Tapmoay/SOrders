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
    # 审计页要回答的第一个问题是「**谁**改的」——只给 operator_id 等于没给（用户看不懂编号）。
    # 名字由端点从 users 表带出来（`full_name` 优先，没有就用手机号）。
    operator_name: str | None = None
    # 「涉及哪一单」同理：`order_id` 是内部编号，用户认的是单号。
    order_no: str | None = None
