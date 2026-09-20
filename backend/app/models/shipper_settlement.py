"""批发商（高级货主）**自己那一本**的核销记录：他向下游货主收钱的账。

## 用户口径（2026-09-20 口述，照这个做）
「他可以对**单个订单**进行核销，也可以对单个订单的**某些商品**进行部分商品核销，
 或者**全部商品**的核销，他也可以**撤掉核销**」
「这个核销只对他来说……不会对总分销商（派单员）进行核销，也就是说他这个核销是他另外的、
 独立的，他自己管自己的」。

## ⛔ 这张表**不写任何一处派单员的账**（这是它存在的全部理由）

| 不写 | 为什么不写 |
| --- | --- |
| `orders.paid` / 收款流水 | 那是**派单员向他收钱**的标记。同一张单在两边是**两个事实**：他欠公司多少、他的客户欠他多少 |
| `cash_flows` | 全系统资金流水（营业额、报表、现金日记账都读它）。他向下游收的钱**没有经过公司账**，写进去就是凭空多一笔"已收" |
| `ledgers` | 派单员开的账。写它会让「这个货主还欠公司多少」当场变少，而钱公司一分没收到 |

写进去的后果不是"多一条记录"，而是**营业额与欠款口径被污染**，而且两边都不报错
（这正是本项目最贵的一类错）。

## 删除
走 `SoftDeleteMixin`（用户：「我们的操作都是走软删除这个你要注意一下」）：
`DELETE` 只打标记，`POST /{id}/restore` 逐字段原样放回来。
**明细行（[ShipperSettlementLine]）自己不设标记** —— 它们跟着**父记录**的标记走
（父被删 = 这一笔核销整体不存在），所以"已核销多少"永远只有一个判据，不会出现
"父还在、某几行却被单独删掉"的中间态（那种态下金额会莫名其妙少几行）。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class ShipperSettlement(Base, TimestampMixin, SoftDeleteMixin):
    """一笔核销：某张订单上的若干商品行，他（批发商）向下游货主收了多少钱。"""

    __tablename__ = "shipper_settlements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: 收钱的人 = 登录的批发商本人，也就是 `orders.shipper_id`（他既是货主、又是收款人）
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    #: 归属货主（订单上的**收货人名称**快照）。
    #: ⚠️ 存快照而不是外键到 `shipper_contacts`：他改联系人名字/删掉联系人的时候，
    #:    历史这笔钱仍然要能说清"当时是向谁收的"（与 `orders.contact_dongjia_name`
    #:    同一个道理：这几列记的都是**当时那个人**）。
    customer_name: Mapped[str] = mapped_column(String(128), default="", index=True)
    customer_phone: Mapped[str] = mapped_column(String(32), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    #: 收款方式：与 `shipper_receipts.method` 同一套词（cash/transfer/wechat/arrears_settle）
    method: Mapped[str] = mapped_column(String(16), default="cash")
    note: Mapped[str] = mapped_column(String(256), default="")
    #: **他什么时候收到这笔钱的**（业务时间，UTC 由 Python 写，与全库口径一致）。
    #: ⚠️ 账本页的窗口按**订单的送达日**筛，不按这一列 —— 否则"上个月送的单、今天收到钱"
    #:    会从本月账面上消失，那一单看起来又变成"没核销"（钱和状态两边打架）。
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    #: 留痕：这笔核销是从哪个端进来的（app=人工点、ai=AI 助手确认卡）
    source: Mapped[str] = mapped_column(String(16), default="app")


class ShipperSettlementLine(Base, TimestampMixin):
    """这笔核销覆盖了哪几行商品、每行多少钱（"按商品核销"就落在这一层）。

    `product_name` 存快照：订单商品行**没有软删**（改单是物理增删），
    所以订单行可能真的消失；而这一笔钱的事后复核（"当时核的是哪几样货"）不能因此断掉。
    """

    __tablename__ = "shipper_settlement_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    settlement_id: Mapped[int] = mapped_column(
        ForeignKey("shipper_settlements.id"), index=True
    )
    #: 冗余一份 order_id：按订单汇总"已核销多少"时少一次 join（这是最热的那个查询）
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    order_product_id: Mapped[int] = mapped_column(ForeignKey("order_products.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(256), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
