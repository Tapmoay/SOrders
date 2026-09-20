"""批发商自记账核销的入参/出参。

⚠️ 这两个模型的名字前缀是 `ShipperSettlement`，**与派单员的 `ShipperReceipt`
（`schemas/accounting_v2.py`）是两件事**，别混：
`ShipperReceipt` = 公司收到货主的钱（写 `cash_flows` + 翻 `orders.paid`）；
`ShipperSettlement` = 批发商收到他下游货主的钱（**谁都不写，只记他自己那一本**）。
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.money import MoneyInput

#: 一次核销最多覆盖多少行（订单本身最多 10 行，这里给足余量）
MAX_SETTLE_LINES = 50

#: 收款方式：与 `shipper_receipts.method` 同一套词，免得多出第二套说法
SETTLE_METHODS = ("cash", "transfer", "wechat", "arrears_settle")


class ShipperSettlementLineIn(MoneyInput):
    order_product_id: int
    amount: Decimal = Field(
        ...,
        gt=0,
        description="这一行核销多少钱（不得超过这一行的「还可核销」）",
    )


class ShipperSettlementCreate(MoneyInput):
    """核销一笔：整单（`lines` 留空）或按商品（给出要核的那几行）。"""

    order_id: int
    lines: list[ShipperSettlementLineIn] = Field(
        default_factory=list,
        max_length=MAX_SETTLE_LINES,
        description="留空 = 整单核销（每一行按「还可核销」全额收）；给了就是**按商品核销**",
    )
    method: str = Field("cash", pattern="^(" + "|".join(SETTLE_METHODS) + ")$")
    note: str = Field("", max_length=256)
    #: 这笔核销是谁发起的（人工点 = app，AI 助手确认卡 = ai）。只用于审计与列表上的标记。
    source: str = Field("app", pattern="^(app|ai)$")


class ShipperSettlementLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_product_id: int
    #: 商品名**快照**：订单商品行是物理增删的，行没了这笔钱仍要能说清"核的是哪样货"
    product_name: str
    amount: Decimal


class ShipperSettlementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    #: 单号（由 API 装配；AI 与界面都靠它认单，不给内部编号）
    order_no: str | None = None
    #: 归属货主（下这一单是替谁下的 = 订单上的收货人）
    customer_name: str = ""
    customer_phone: str = ""
    amount: Decimal
    method: str = "cash"
    note: str = ""
    settled_at: datetime
    source: str = "app"
    #: 是不是已撤销（进了回收站）。列表默认只回未删的，`include_deleted=true` 时才可能为真
    is_deleted: bool = False
    created_at: datetime
    lines: list[ShipperSettlementLineOut] = []
