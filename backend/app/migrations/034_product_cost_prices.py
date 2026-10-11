"""034_product_cost_prices：建一张「商品附加成本价」表（FEAT-0025，用户 2026-10-11 要求）。

### 为什么需要一张新表
用户要的是"一个商品可以有多个成本价"，而且**要能命名**（"返点后成本" / "补贴后成本"）、
能列好几个、能改能删能撤回。这几条在 `products` 那一行上都存不下（一格只能放一个数）。
⚠️ 加固定列（`cost_price_2`）也不行：名字与个数都写死在表结构里，第三个口径又要迁移一次。
⛔ 而**默认那个口径依旧是 `products.cost_price`（真实成本价）**，订单与毛利照旧只按它算 ——
这张表只装"附加口径"，一个字节都不参与金额计算（见 `app/models/product.py` 的说明）。

### 为什么走迁移而不是 schema_bootstrap
与 `019_purchase_orders` / `020_invoices` / `027_shipper_prices` / `029_ai_operation_log` /
`031_account_devices` 同一条：建表是**正式变更**（老库要建表、新库由 `create_all` 按模型建）。
⛔ `core/schema_bootstrap.py` 里**没有**这张表，本次也不新开
（`_tools/qa/_check_silent_release.py` 第 5 条钉着这条纪律）。

### 为什么用模型建表
`ProductCostPrice.__table__.create` 让两种方言（本机 SQLite / 生产 MySQL）落到**同一个形状**上：
`product_id` 索引与 `(product_id, name)` 唯一约束都跟着模型走 ——
不会出现「迁移建的表少一条唯一约束」这种只在生产才发作的偏差
（那条约束正是"同名成本价不许重复"的**最后一道**保障，见 models/product.py）。

### 回滚
revert 代码即可：多出来的这张表对旧代码完全无害（旧代码一个字节都不读它）。
"""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

VERSION = 34
NAME = "product_cost_prices"
DESCRIPTION = (
    "product_cost_prices：商品的附加成本口径（一个商品可多条，可命名、可排序、可软删/恢复）。"
    "⛔ 订单与毛利的成本口径仍是 products.cost_price（真实成本价），本表不参与任何金额计算"
)

TABLE = "product_cost_prices"


def upgrade(engine: Engine) -> None:
    """建这张表；已经在了就什么都不做（⛔ 必须能重跑）。"""
    if TABLE in set(inspect(engine).get_table_names()):
        return
    from app.models.product import ProductCostPrice

    ProductCostPrice.__table__.create(bind=engine, checkfirst=True)
