from pydantic import BaseModel, Field


class UsageResetOut(BaseModel):
    """重置常用计数的结果。

    `deleted` = 这次清掉了几行 —— 界面要**如实说数量**：只说"重置成功"的话，
    用户分不清"真的清了 20 条"和"本来就没有、什么都没发生"（后者更可能是他点错了地方）。
    """

    deleted: int = Field(0, ge=0, description="清掉的计数行数（0 = 本来就没有）")
