from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AiOperationLogOut(BaseModel):
    """AI 操作流水的一行（管理端「AI 操作记录」那一页）。

    ⚠️ 与 `OperationLogOut` 不是一回事：那一张记的是"业务写成功了"（一次业务写入一行、
    挂在订单上），这一张记的是"AI 发起了一次请求"（**失败也有一行**，且不依赖业务成功）。
    两张表各自回答一个问题，别互相替代（理由见 `models/ai_operation_log.py` 的文件头）。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    # 谁让 AI 干的（未登录 / 鉴权失败时为 NULL —— 那本身也是要看得见的事实）。
    user_id: int | None
    # AI 动作名（App 的 `AiWriteAction.id`，如 `orders.create`）；认不出时为 NULL。
    action: str | None
    method: str
    path: str
    status_code: int
    ok: bool
    # 失败时后端给用户的那句话（截断 500 字）；成功时为 NULL。
    error: str | None
    request_id: str | None
    duration_ms: int
    created_at: datetime
    # 只给 user_id 等于没给（用户看不懂编号）：名字由端点从 users 表带出来
    # （`full_name` 优先，没有就用手机号 —— 与审计页同一套取值规则）。
    user_name: str | None = None
