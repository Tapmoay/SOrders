from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.text import MAX_TEXT


class NotificationCreate(BaseModel):
    recipient_id: int
    category: str = Field(default="system", max_length=32, description="system | order | reminder")
    type: str = Field(default="system", max_length=64)
    title: str = Field(default="", max_length=256)
    content: str = Field("", max_length=MAX_TEXT)
    payload: dict[str, Any] | None = None
    speech_important: bool = False


class NotificationUpdate(BaseModel):
    title: str | None = Field(None, max_length=256)
    content: str | None = Field(None, max_length=MAX_TEXT)
    payload: dict[str, Any] | None = None


class NotificationBatchDeleteBody(BaseModel):
    """批量删除消息：ids 指定列表，或 all=true 清空（二选一）。"""

    ids: list[int] = Field(default_factory=list, description="要删除的消息ID列表")
    all: bool = Field(default=False, description="true=清空该账户全部消息")
    recipient_id: int | None = Field(default=None, description="仅派单员可指定其他用户；缺省=本人")


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recipient_id: int
    category: str
    type: str
    speech_important: bool
    title: str
    content: str
    payload: dict[str, Any] | None
    read_at: datetime | None
    created_at: datetime
