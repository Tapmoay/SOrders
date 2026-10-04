"""采购单的入参与出参（FEAT-0013）。形状由 `app/models/purchase.py` 的三条不变量决定。

两条给客户端的硬规矩：

1. **金额一律字符串两位小数**（与 `api/v1/suppliers.py::_money` 同一写法）：浮点数进了
   JSON 就会在客户端被四舍五入成另一个数，而这是要拿去对账的钱。
2. **合计与每行金额都是服务端算的**（`services/purchase_service.py::line_amount` /
   `total_of` 是全项目唯一那两处乘法与加法）：⛔ 客户端不许自己乘了再加。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.money import MoneyInput


class PurchaseItemIn(MoneyInput):
    """一行明细。`id` 只在**改单**时给：指向这张单已有的那一行。"""

    id: int | None = Field(None, description="改单时指向已有明细行；新加的行不给")
    product_id: int
    #: ⛔ 0 与负数在服务层被拦成中文 400（不是 422 的结构体）：数量为 0 的行
    #  「看着像一行货，其实什么都没进」，那正是最容易被忽略的一类错录。
    quantity: int = Field(..., ge=0, le=1_000_000, description="数量（整数，与库存同一单位）")
    #: 进货价必须 > 0：0 元进货会让 `cost_basis` 的「算得出成本」判据（cost > 0）失效，
    #  那一行的收入就永远进不了毛利。赠品 / 盘盈走库存调整（那条路本来就不记成本价）。
    unit_cost: Decimal = Field(..., description="进货价（元/单位）；上界由 MoneyInput 管")


class PurchaseOrderCreate(MoneyInput):
    """建单：一次提交写库存 + 成本 + 应付（三件事同一个事务）。"""

    supplier_id: int
    doc_date: date
    remark: str = Field("", max_length=256)
    items: list[PurchaseItemIn] = Field(..., min_length=1, description="至少一行；同一商品只允许一行")


class PurchaseOrderUpdate(MoneyInput):
    """改单。`items` 是**整单替换**：没出现在里面的行 = 撤掉（那一行仍在单子上，标记 `is_void`）。

    ⛔ `items=None`（请求里干脆不带这个键）= 只改单头（供应商 / 日期 / 备注），一行都不动。
    这两件事必须分得开：客户端漏传一个空数组，不应该把整张单的明细全撤掉。
    """

    supplier_id: int | None = None
    doc_date: date | None = None
    remark: str | None = Field(None, max_length=256)
    items: list[PurchaseItemIn] | None = None


class PurchaseItemOut(BaseModel):
    """一行明细（含已撤的行：`is_void=true`，`amount` 计 0）。"""

    id: int
    product_id: int
    product_name: str = ""
    unit: str = ""
    quantity: int = 0
    unit_cost: str = "0.00"
    #: = 数量 × 单价（服务端算）；已撤的行恒为 "0.00"（撤掉的行不进合计）
    amount: str = "0.00"
    is_void: bool = False
    movement_id: int | None = None


class PurchaseOrderBrief(BaseModel):
    """列表里的一张单（⛔ 不带明细：明细去详情端点拿）。"""

    id: int
    supplier_id: int
    supplier_name: str = ""
    doc_date: date
    remark: str = ""
    #: 还活着的行数（已撤的行不算）
    item_count: int = 0
    #: 单头合计 = Σ(活着的行的 数量 × 单价)；服务端算
    total: str = "0.00"
    payable_id: int | None = None
    #: 这张单生成的应付单已经付掉多少、还差多少（都由服务端算，⛔ 客户端不许自己减）
    payable_paid: str = "0.00"
    payable_unpaid: str = "0.00"
    is_deleted: bool = False
    created_at: datetime | None = None


class PurchaseOrderOut(PurchaseOrderBrief):
    """详情：单头 + 全部明细（含已撤的行）。"""

    operator_id: int | None = None
    updated_at: datetime | None = None
    items: list[PurchaseItemOut] = []
