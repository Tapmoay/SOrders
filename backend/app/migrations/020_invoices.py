"""020 发票台账（FEAT-0014 税账）：三张新表 —— invoices 与两张连线表。

### 为什么要这三张表
税在全库**一个数据源都没有**（利润表 `tax_total` 恒 0，全库唯一带 invoice 字样的列
`shipper_receipts.invoiced` 是一个没有落点的布尔）。一张发票要挂到它抵税的那几张
业务单据上：进项挂采购单（`invoice_purchase_orders`）、销项挂账本条目（`invoice_ledgers`）。
为什么、以及三条口径，见 `backend/app/models/invoice.py` 的文件头。

### 两条设计选择（与 002_outbox_events / 019_purchase_orders 同一套理由）
1. **表结构直接取自模型**（`__table__.create`）：模型与迁移**不可能写成两样**；
2. `checkfirst=True` → 可以重跑（全新库与单测里 `create_all` 已经建过这三张表，这里必然跳过）。

### 本迁移只建表、不回填
历史上没有"发票"这回事。⛔ **不拿 `expenses` / `cash_flows` 里带"税"字的行反推发票**：
那些行没记票号、没记税率，猜出来的税额进税汇比没有更糟（用户会拿它去申报）。
缺的那一段如实留在「历史数据影响」里。
"""

from __future__ import annotations

from sqlalchemy.engine import Engine

VERSION = 20
NAME = "invoices"
DESCRIPTION = "新增 invoices + invoice_purchase_orders + invoice_ledgers：发票台账（销项/进项、价税合计与税额、挂业务单据）"


def upgrade(engine: Engine) -> None:
    from app.models.invoice import Invoice, InvoiceLedger, InvoicePurchaseOrder

    Invoice.__table__.create(bind=engine, checkfirst=True)
    InvoicePurchaseOrder.__table__.create(bind=engine, checkfirst=True)
    InvoiceLedger.__table__.create(bind=engine, checkfirst=True)
