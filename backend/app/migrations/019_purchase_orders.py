"""019 采购单（FEAT-0013）：两张新表 —— purchase_orders 与 purchase_order_items。

### 为什么要这两张表
一次进货要同时改写三样东西：库存（inventory_movements）、成本价（成本价区间表）、
供应商应付（supplier_payables）。在它们之上需要一个**单据**把这三件事绑成一个事务 ——
为什么、以及三条不变量，见 `backend/app/models/purchase.py` 的文件头。

### 两条设计选择（与 002_outbox_events 同一套理由）
1. **表结构直接取自模型**（`__table__.create`）：模型与迁移**不可能写成两样**，
   而「两边不一致」正是这类表最贵的缺陷（列名差一个字 → 上线当天才发现）；
2. `checkfirst=True` → 可以重跑（MySQL 的 DDL 隐式提交，一条迁移可能改了一半就失败）。
   全新库与单测里 `create_all` 已经建过这两张表，这里必然跳过。

### 本迁移只建表、不回填
历史上没有「采购单」这回事。⛔ **不拿旧的 `inventory_movements`（source="MANUAL"）
反推出采购单** —— 那些流水没记供应商，也分不清哪几笔属于同一次进货，猜出来的单据
比没有单据更糟（用户会拿它去对账）。缺的那一段如实留在「历史数据影响」里。
"""

from __future__ import annotations

from sqlalchemy.engine import Engine

VERSION = 19
NAME = "purchase_orders"
DESCRIPTION = "新增 purchase_orders + purchase_order_items：一次进货同时写库存、成本价与供应商应付"


def upgrade(engine: Engine) -> None:
    from app.models.purchase import PurchaseOrder, PurchaseOrderItem

    PurchaseOrder.__table__.create(bind=engine, checkfirst=True)
    PurchaseOrderItem.__table__.create(bind=engine, checkfirst=True)
