"""028_order_product_shipper_price：给订单行加一格「下单当时的下游单价」（CHG-0077 / 台账 L-38）。

### 为什么加它

用户口径（m13365 第五问）：**改价之后老单一律按下单当时的快照，老单不追改**。
今天下游那本账是按订单行**实时**算的（`services/shipper_settle.py`）——
不把当时的价定格在行上，批发商改一次价就会把**历史账单**一起改掉。

### 为什么是一列可空、且老行留 NULL

- 老单当时根本没有「批发商自己定的价」这一层事实 ⇒ 一律 `NULL`，
  读侧回落订单行 `unit_price`，账本数字与今天**逐格相同**。
  ⛔ **不许**按今天的价目表倒推回填：那是伪造历史事实（与 `009_freight_rule_snapshot`
  那条「不倒推历史」同一条纪律）。
- 没有默认值：默认值会让"当时没有价"与"当时价格是 0"分不开。

### 为什么走迁移而不是 schema_bootstrap

与 026 / 027 同一条理由：加列是**正式变更**（老库要 ALTER、新库由 create_all 按模型建）。
⛔ `core/schema_bootstrap.py` 里没有这一列，本次也不新开。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 28
NAME = "order_product_shipper_price"
DESCRIPTION = (
    "order_products 加 shipper_unit_price（下单当时批发商自己定的下游单价）。"
    "可空、无默认：老行一律 NULL = 当时没有这一层价，读侧回落 unit_price"
)

TABLE = "order_products"
COLUMN = "shipper_unit_price"


def upgrade(engine: Engine) -> None:
    """给已有库补这一列；全新库由 `create_all` 按模型建，这里什么都不做。"""
    insp = inspect(engine)
    if TABLE not in set(insp.get_table_names()):
        return
    # 可重跑：先判列在不在（MySQL 的 DDL 隐式提交，一条迁移可能改了一半才失败）
    if COLUMN in {c["name"] for c in insp.get_columns(TABLE)}:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} NUMERIC(14, 4) NULL"))
