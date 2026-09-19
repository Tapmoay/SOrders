from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MovementCreate(BaseModel):
    product_id: int
    # 正数入库 / 负数出库，不得为 0
    change: int = Field(..., ge=-1_000_000, le=1_000_000)
    note: str = Field(default="", max_length=256)
    """
    **这次进货的成本价**（选填，只在入库时有意义）。

    为什么要有这个字段（用户 2026-09-19）：「成本价也是可以进行调整的，包括进货的时候
    也要输入成本价，因为可能这个时间的进货和那个时间进货的成本价是不一样的」。

    口径（**刻意只做到这一步**）：填了就把商品的 `cost_price` 更新成这个价
    —— 商品的成本价 = **最近一次进货价**，订单的 `cost_price_snapshot` 在下单时定格，
    于是毛利反映的是"卖的时候那批货的进货价"。历史进货价留在操作日志里可回查。
    ⚠️ 这是**近似**，不是分批成本（FIFO / 加权平均）：100 件 ¥10 与 100 件 ¥12 之后，
    商品成本是 ¥12，卖旧货那几单的毛利会偏低。要精确到批次是另一件事（要改毛利口径），
    用户没有要求，这里不做，但**别把它说成"分批成本"**。
    """
    unit_cost: Decimal | None = Field(None, ge=0, description="本次进货价（选填，仅入库）")


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
