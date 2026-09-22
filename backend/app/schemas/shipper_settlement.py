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


class ShipperLedgerSummaryOut(BaseModel):
    """「我的账本」顶上那段**收支统计**（2026-09-22 用户要求：账本的统计对货主与批发商也做）。

    ## 两个方向，别混
    | 字段 | 方向 | 口径 |
    | --- | --- | --- |
    | [payable] / [paid] / [unpaid] | **支出：我该付的**（我 ↔ 公司/总分销商） | `services/order_money.py`（**一张单的钱只有那一处实现**） |
    | [receivable] / [received] / [unreceived] | **收入：我该收的**（我 ↔ 我的下游货主） | `services/shipper_settle.py` + `order_money.line_receivable` |

    ⛔ **两个方向绝不互相写**：下面那三个数是**批发商自己记的核销**，
    一个字节都不写 `orders.paid` / `cash_flows` / `ledgers` —— 所以"我该收的"变了，
    "我该付的"**一分钱都不会跟着变**。

    ⚠️ **为什么这三个数必须由服务端算**：这一页的订单列表是**带 limit 的一页**，
    客户端把这一页加起来在**列表被截断时就会偏小**（期① 审计里那个"客户端求和少算 62%"
    是同一个形状）。所以出参里的每个数都是 SQL 侧算完的，`orders` 也是**窗口内的全量单数**
    （不是取到的那一页）。普通货主的 [receivable]/[received]/[unreceived] 恒为 0
    —— 他是给自己下单，系统里没有他的进账（[is_member] 让客户端知道该不该画那一边）。
    """

    #: 这一段（同一窗口、同一个可选的下游货主）一共几单
    orders: int = 0
    #: 其中已经结清的（欠款 ≤ 0）
    cleared_orders: int = 0
    #: 支出侧：应付合计 = **货款**（订单金额 − 已退）。
    #: ⚠️ **不含运费** —— `orders.freight_fee` 是**公司付给司机**的钱，不进他与公司之间的账。
    #:    顺手加上运费的话，这个数就和订单详情里的"还欠"对不上了（同一个概念两个答案）。
    payable: Decimal = Decimal("0")
    #: 支出侧：已经付掉的（净已收 = 已收 − 已退现金）
    paid: Decimal = Decimal("0")
    #: 支出侧：还欠（< 0 = 预收，与订单出参的 `arrears_amount` 同一个符号约定）
    unpaid: Decimal = Decimal("0")
    #: 收入侧：我该向下游收的货款（已退的那部分扣掉）
    receivable: Decimal = Decimal("0")
    #: 收入侧：我已经收到的（他自己记的核销，未撤销的那些）
    received: Decimal = Decimal("0")
    #: 收入侧：还没收到的
    unreceived: Decimal = Decimal("0")
    #: 这一段记了几笔核销
    settlements: int = 0
    #: 是不是批发商货主（决定界面上画不画"收入"那一边）
    is_member: bool = False

