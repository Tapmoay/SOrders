"""客户收款单：逐单核销（默认 itemized），绑定 orders 并标记 paid。

## 为什么会带软删（2026-10-10，BUG-0029 / 台账 TB-09）
在这之前收款是**只增不撤**的：`POST /ledger/receipts` 一次写四个落点（本表一行 ＋
`cash_flows` 若干行 ＋ `orders.paid=True` ＋ 由前两者算出来的 `turnover.collected/arrears`
与 `customer-balances`），而**撤销入口一个都没有** —— 系统自己的报错文案还写着
「请联系管理员在账上冲正」，可管理员也没有这个入口（`app/api/v1/orders_payment.py:199`）。
用户定的硬规矩是「**所有删除一律软删（伪装删除）＋ 必须有恢复路径**」，所以这里跟
`cash_flows` / `products` 一样加 `is_deleted` / `deleted_at`：撤销 = 打标记（行还在、
历史一行不丢），`POST /ledger/receipts/{id}/restore` 原样放回来。

⚠️ **查询侧必须一起改**（不然等于没撤）：凡是从本表取数的地方都要带
`.where(ShipperReceipt.is_deleted.is_(False))`；要看得见回收站就得显式要
（`GET /ledger/receipts?include_deleted=true`）。
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.enums import ReceiptSettleMode


class ShipperReceipt(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "shipper_receipts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(16))  # cash/transfer/wechat/arrears_settle
    received_at: Mapped[date] = mapped_column(Date, index=True)
    order_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)  # 逐单核销绑定
    settle_mode: Mapped[ReceiptSettleMode] = mapped_column(String(12), default=ReceiptSettleMode.ITEMIZED)
    arrears_unit_id: Mapped[int | None] = mapped_column(nullable=True)
    invoiced: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(256), default="")
    operator_id: Mapped[int | None] = mapped_column(nullable=True)
