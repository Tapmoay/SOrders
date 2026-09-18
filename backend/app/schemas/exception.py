from pydantic import BaseModel, Field

from app.schemas.text import MAX_TEXT


class ExceptionResolveBody(BaseModel):
    # 解除异常时写进 orders.exception_resolution（TEXT 列）
    note: str | None = Field(None, max_length=MAX_TEXT)
