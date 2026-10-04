"""发票台账（FEAT-0014 税账，2026-10-04 五期计划第四期）：一张票 = 一笔进项或销项的税。

## 为什么要有这张表

在这之前，"税"在全库里**一个数据源都没有**：利润表第七级 `tax_total` 恒为 0
（`services/reports/profit_query.py`，notes 里如实写着"税没有数据源"），
而全库唯一带 `invoice` 字样的列是 `shipper_receipts.invoiced`（一个布尔，没有落点）。
于是"这个月要交多少税、哪批货有票、哪批没票"只能靠翻纸质票。

这张表把一张发票变成事实：**方向**（销项/进项）+ **票号** + **日期** +
**价税合计** + **税率** + **税额**，以及它挂在**哪些业务单据**上。

## 三条口径（本文件定形状，服务层守值）

1. **价税合计与税率是输入，税额是算出来的**：`amount` 是票面上的合计数，
   `tax_rate` 是这张票适用的税率（小规模默认 3.00%，本期不做多档税率表），
   `tax_amount = amount − amount / (1 + tax_rate)`（四舍五入到分，ROUND_HALF_UP）。
   ⛔ 不许在别处重算：税额的**唯一**写入点是 `services/tax_service.py::tax_of_amount`，
   允许人手覆盖（票面税额与算出来的差一分钱的现实存在）—— 覆盖后不再重算。
2. **未税票与零税率票是两回事**：`tax_rate IS NULL` = 未税（这一张不进税汇，
   例如收据、内部单据），`tax_rate = 0.00` = 零税率（**进**税汇，税额恒 0）。
   于是"参加税汇的票"有唯一判据：`tax_rate IS NOT NULL`。
3. **票号可以为空，但空号不算重复**：票还没拿到（月结代开）就先登记，
   `invoice_no = ''`，拿到再补（改票只允许在 REGISTERED 状态做）。
   同一方向 + 同一票号**唯一** —— 靠 `no_key` 列编码（见下），⛔ 不用
   `sqlite_where` 那种"部分唯一索引"：MySQL 会**静默忽略**它，生产上就变成整表唯一，
   而本机 SQLite 一切正常（`models/customer.py:12-29` 记着这个教训）。

## 两张连线表：一张票可以挂在多张单据上

| 方向 | 挂什么 | 为什么 |
| --- | --- | --- |
| 进项 INPUT | `invoice_purchase_orders` → 采购单（≥1 张） | 一张进项票常常对多张进货单（月结合并开票）。**必须挂**：要回答"这批货到底有没有票" |
| 销项 OUTPUT | `invoice_ledgers` → 账本条目（可 0 张） | 公司的应收记在 `ledgers` 上（`customer_id` + 金额）。⛔ 不挂 `shipper_settlements`：那是批发商**自己那本**向下游收钱的账，一个字节都不进公司账（见 `models/shipper_settlement.py:9-18`）。挂了的票，客户必须与发票客户一致 |

## 两种"不算数"

`status = VOIDED`（作废·冲红，**保留行占位**）与 `is_deleted`（回收站）都会让这张票
退出税汇，而且都保留原样可查：作废的票留在列表里、颜色变灰；要从回收站回来走
`POST /invoices/{id}/restore`（逐字段原样放回）。判据 `_tools/qa/_check_tax_invoices.py`
与 `backend/tests/test_tax_invoices.py` 两边都钉这条：**税汇里只出现"活着且没作废"的票**。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class Invoice(Base, TimestampMixin, SoftDeleteMixin):
    """一张发票。**税额与价税合计的关系不在别处重算**（见文件头第 1 条）。"""

    __tablename__ = "invoices"
    __table_args__ = (
        #: 同一方向 + 同一票号唯一；空票号（`no_key IS NULL`）不参与唯一 ——
        #  "唯一索引里的多个 NULL 不算冲突"两种数据库语义一致（`models/customer.py:20-24`）。
        Index("uq_invoices_direction_no", "direction", "no_key", unique=True),
        Index("ix_invoices_direction_date", "direction", "invoice_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: 方向（`InvoiceDirection`）：OUTPUT 销项 / INPUT 进项。存字符串值而不是 Enum 列 ——
    #  跟随 `purchase_orders` 的做法（`String` + 服务层校验）：新加方向时不必改库里的 CHECK。
    direction: Mapped[str] = mapped_column(String(10), index=True)
    #: 票号。空串 = 还没拿到（允许改）。非空时同一方向内唯一。
    invoice_no: Mapped[str] = mapped_column(String(64), default="")
    #: 票号的唯一键：非空票号 = 票号本身，空票号 = NULL（见 `__table_args__`）。
    #  ⚠️ 与 `customers.tmp_phone_key` 同一个道理：把"谁参与唯一"编码进列值，
    #     而不是靠方言专属的 partial index。唯一写入点是 `tax_service._no_key`。
    no_key: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    #: 开票日期（**业务当地日期**，同 `expenses.exp_date` / `purchase_orders.doc_date`）。
    #  税期按这一列算，⛔ 不按 created_at（今天补录上个月的票，要落在上个月）。
    invoice_date: Mapped[date] = mapped_column(Date, index=True)
    #: 价税合计（元）。> 0。
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    #: 税率（百分数，如 3.00 = 3%）。NULL = 未税（不进税汇）；0.00 = 零税率（进税汇，税额 0）。
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True, default=None)
    #: 税额。`tax_rate IS NULL` ⇒ 本列也必须是 NULL（两列要么都有、要么都没有）。
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True, default=None)
    #: 进项票的供应商（INPUT 必填）；销项票的客户（OUTPUT 必填）。两者互斥，服务层校验。
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("suppliers.id"), nullable=True, default=None, index=True
    )
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True, default=None, index=True
    )
    #: 状态（`InvoiceStatus`）：REGISTERED / ISSUED / VOIDED。
    status: Mapped[str] = mapped_column(String(12), default="REGISTERED", index=True)
    note: Mapped[str] = mapped_column(String(256), default="")
    operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, default=None
    )

    purchase_orders: Mapped[list["InvoicePurchaseOrder"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    ledgers: Mapped[list["InvoiceLedger"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class InvoicePurchaseOrder(Base, TimestampMixin):
    """进项票 ↔ 采购单（多对多）。**这张票抵的是这几车货的进项**。"""

    __tablename__ = "invoice_purchase_orders"
    __table_args__ = (
        UniqueConstraint("invoice_id", "purchase_order_id", name="uq_invoice_po"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)

    invoice: Mapped["Invoice"] = relationship(back_populates="purchase_orders")


class InvoiceLedger(Base, TimestampMixin):
    """销项票 ↔ 账本条目（多对多）。**这张票开的是这几笔应收**。"""

    __tablename__ = "invoice_ledgers"
    __table_args__ = (UniqueConstraint("invoice_id", "ledger_id", name="uq_invoice_ledger"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    ledger_id: Mapped[int] = mapped_column(ForeignKey("ledgers.id"), index=True)

    invoice: Mapped["Invoice"] = relationship(back_populates="ledgers")
