from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MovementCreate(BaseModel):
    product_id: int
    # 正数入库 / 负数出库，不得为 0
    change: int = Field(..., ge=-1_000_000, le=1_000_000)
    note: str = Field(default="", max_length=256)


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    change: int
    note: str
    operator_id: int
    created_at: datetime
    source: str = "MANUAL"
    order_id: int | None = None
    order_no: str | None = None
    status: str = "COMMITTED"


class InventorySummaryOut(BaseModel):
    product_id: int
    product_name: str
    stock: int
    unit: str = "件"
    low_stock_alert: int = 0
    is_active: bool
