from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NotificationCreate(BaseModel):
    recipient_id: int
    category: str = Field(default="system", max_length=32, description="system | order | reminder")
    type: str = Field(default="system", max_length=64)
    title: str = Field(default="", max_length=256)
    content: str = ""
    payload: dict[str, Any] | None = None
    speech_important: bool = False


class NotificationUpdate(BaseModel):
    title: str | None = Field(None, max_length=256)
    content: str | None = None
    payload: dict[str, Any] | None = None


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
