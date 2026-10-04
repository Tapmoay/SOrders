"""采购单：一次进货 = 一张单（库存 + 成本价 + 供应商应付，三件事一次写完）。

## 为什么要有这张单（2026-10-04 五期计划第三期，FEAT-0013）

在这之前，「进货」只有一条路：`POST /inventory/movements` 一个一个商品手工入库。
那条路能让账上的货变多，却记不下「这一车是从谁那儿进的、这一批花了多少钱」：
供应商与应付单在另一套表里（`suppliers` / `supplier_payables`），和进货**没有连线** ——
录一次采购要在两个页面各录一遍，录漏一处也没人发现。

这张单把三件事绑在**一次提交**里：

```text
一张采购单（供应商 + 日期 + 多行：商品 / 数量 / 单价）
  ├─ 库存：每一行往里加一次货（一条 inventory_movements，source="PURCHASE"）
  ├─ 成本：同一行带进货价 → services/cost_history.record_cost（商品成本价 + 成本价区间表）
  └─ 应付：单头合计 = Σ(数量 × 单价) → 自动生成一张 supplier_payables（category="货款"）
```

三件事**要么都有、要么都没有**（同一个事务，见 `services/purchase_service.py`）。

## 三条不变量（本文件定形状，服务层守值）

1. **单头不存合计、明细不存金额**：合计 = Σ(数量 × 单价)，现算。
   同一个数落两处，早晚会有一处忘了改（本项目最贵的一类缺陷）。
2. **每一行明细绑定它写下的那一条入库流水**（`movement_id`）：一行 = 一条流水。
   ⛔ 不是「一张单 = 一堆流水里猜出来的」—— 猜出来的对应关系，改单时就找不到该改哪一条。
3. **改单是改写那条流水，不是再记一笔冲销**：`services/cost_basis.py::_weighted_avg`
   的分母只认 `change > 0 AND unit_cost IS NOT NULL`，冲销行天然进不了分母 ——
   再记一笔会让**旧价永远留在加权均价里**（分子分母都不减），两批货串成一个价。
   改写则让「这条流水就是这批货」永远成立，同时保住
   `Σ(inventory_movements.change) == products.stock`（流水是库存的唯一账本）。

## 两种「不算数」，一个判据

`item.is_void`（这一行被撤了）与 `order.is_deleted`（整张单进了回收站）都会让那一行
**不算数**，而且都表现为「那条流水脱离」：

```text
流水脱离（detached）  ⟺  item.is_void or order.is_deleted
```

脱离时流水被摆成「没发生过」：`change = 0`、`unit_cost = NULL`、`status = "VOID"`，
库存同时按数量扣回去（扣不动就如实报「库存不足」，绝不悄悄把库存压成 0）。
恢复时按明细行上的 `quantity` / `unit_cost` 原样写回。所以单子活着且行没撤时恒有：

```text
movement.change == item.quantity   且   movement.unit_cost == item.unit_cost
```

判据 `_tools/qa/_check_purchase_orders.py` 与 `backend/tests/test_purchase_orders.py`
两边都钉这条恒等式 —— 它是「明细是意图、流水是账」这句话的可执行版本。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class PurchaseOrder(Base, TimestampMixin, SoftDeleteMixin):
    """一张采购单的单头。**合计不在这里**（= Σ 明细，现算，见文件头第 1 条）。"""

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    #: 单据日期（**业务当地日期**，同 expenses.exp_date / ledgers.entry_date）。
    #  ⛔ 不是 UTC 时间列：列表筛选直接比日期，不要套 business_range_utc（那是给 created_at 用的）。
    doc_date: Mapped[date] = mapped_column(Date, index=True)
    remark: Mapped[str] = mapped_column(String(256), default="")
    #: 这张单自动生成的那张应付单（supplier_payables.id）。
    #  金额同步的唯一写入点是 `services/purchase_service.py::_sync_payable`；
    #  反向保护在 `api/v1/suppliers.py`：来自采购单的应付单不许在供应商页改/删。
    payable_id: Mapped[int | None] = mapped_column(
        ForeignKey("supplier_payables.id"), nullable=True, default=None, index=True
    )
    operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, default=None
    )

    items: Mapped[list[PurchaseOrderItem]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderItem.id",
    )


class PurchaseOrderItem(Base, TimestampMixin):
    """明细行：**这张单要什么**（数量 + 单价）。它对库存与成本的**作用**在流水上。

    ⛔ 没有金额列（= 数量 × 单价，现算）；⛔ 没有合计列（那个在服务层 Σ）。
    """

    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    #: 数量（整数）。与 products.stock / inventory_movements.change 同一单位 ——
    #  单位换算不在这条链上（换算率是下单时的概念，见 unit_conversions）。
    quantity: Mapped[int] = mapped_column(Integer)
    #: 进货价（元/单位），精度同 products.cost_price（Numeric(14,4)）。必须 > 0。
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    #: 这一行写下的那条入库流水。撤行/恢复都改这一条，不见新流水（见文件头第 2、3 条）。
    movement_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_movements.id"), nullable=True, default=None, index=True
    )
    #: 这一行被撤掉了（改单时没出现在明细里，或用户显式删掉这一行）。
    #  ⛔ 撤行**不删这一行**：撤掉的量与原价要留在单子上（否则「我明明进过这批货」无从对证）。
    is_void: Mapped[bool] = mapped_column(Boolean, default=False)

    order: Mapped[PurchaseOrder] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship("Product")
    movement: Mapped["InventoryMovement"] = relationship("InventoryMovement")
