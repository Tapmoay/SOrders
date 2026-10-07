from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.money import MoneyInput


class MovementCreate(MoneyInput):
    product_id: int
    # 正数入库 / 负数出库，不得为 0
    change: int = Field(..., ge=-1_000_000, le=1_000_000)
    note: str = Field(default="", max_length=256)
    """
    **这次进货的成本价**（选填，只在入库时有意义）。

    为什么要有这个字段（用户 2026-09-19）：「成本价也是可以进行调整的，包括进货的时候
    也要输入成本价，因为可能这个时间的进货和那个时间进货的成本价是不一样的」。

    两件事同时发生（**同一个事务**，不会出现"货进了、成本没改"）：
    ① 这一个价**记在流水上**（`inventory_movements.unit_cost`）—— 它是"这批货多少钱"的
       一手数据，毛利的加权平均进货价就是从它算的（`services/cost_basis.py`）；
    ② 商品的 `cost_price` 也更新成它（商品卡与编辑页显示的就是"最近一次进货价"）。

    ⚠️ 只填 ② 不填 ① 就等于把成本信息丢了 —— 这正是这一列存在的原因。
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
    #: 这一批的进货单价（只有手工入库且填了才有值）；出参带出来是为了让"成本从哪来"看得见
    unit_cost: Decimal | None = None
    #: **这一行属于哪张采购单**（2026-10-07 CHG-0073）。
    #:
    #: ⛔ 它是**只读派生**字段、不是 `inventory_movements` 的列：归属的唯一真相仍然是
    #: `purchase_order_items.movement_id`（一行明细绑定它写下的那一条流水），这里只是那次
    #: 绑定在流水视角下的投影，列表查询时现算（`api/v1/inventory.py::_attach_purchase_orders`）。
    #:
    #: null = 不属于任何**还在的**采购单 —— 手工调整（source=MANUAL）、订单自动出库
    #: （source=ORDER）、以及明细已作废 / 单子已软删的那些。⛔ 历史行**一个字节都不回填**
    #: （FEAT-0013 与 migrations/019_purchase_orders.py:15-16 的 ⛔ 照旧）。
    purchase_order_id: int | None = None
