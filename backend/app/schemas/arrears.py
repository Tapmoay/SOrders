from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ArrearsUnitCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    phone: str = Field(default="", max_length=32)
    remark: str = Field(default="", max_length=256)


class ArrearsUnitUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    phone: str | None = Field(None, max_length=32)
    remark: str | None = Field(None, max_length=256)


class ArrearsUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    remark: str
    created_at: datetime
