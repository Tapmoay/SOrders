"""027_shipper_prices：建一张「批发商给下游客户定的价」表（CHG-0077 / 台账 L-38）。

### 为什么需要一张新表（而不是复用 price_rules）

用户 2026-10-07 原话（ref m01547）：「他同样可以给他**自己的商品进行定价**，但这个定价
**只走他自己的账**……**别人欠他的就按照他自己定的价**来……同理，他也可以**给不同的人
不同的价格**」。这是**第三层价**：

- 第一层：平台 / 派单员的商品价（`products.unit_price`）；
- 第二层：派单员给这个批发商的专属价（`price_rules.special_unit_price`）；
  ⚠️ 它的 `shipper_id` 语义逐字是「**被给价的那个批发商**」（被定价的人），
  ⛔ 不是「定价的人」；
- 第三层：**批发商给下游客户定的价** —— 今天无表可存。

硬塞进 `price_rules` 会与 `uq_price_rule_shipper_product` 撞唯一键，
并且会让「公司给他的价」被他自己的价**覆盖**（那是数据事故，不是边界问题）。

### 为什么走迁移而不是 schema_bootstrap

README 的分工：**正式变更**走本目录、**运行时自愈**走 `core/schema_bootstrap.py`。
建表是正式变更（老库要建表、新库由 create_all 按模型建），所以是一条迁移 ——
与 `005_ai_call_daily` / `019_purchase_orders` / `020_invoices` 同一条理由。
⛔ 不两边都写：`core/schema_bootstrap.py` 里**没有**这张表，本次也不新开
（`_tools/qa/_check_silent_release.py` 第 5 条钉着这条纪律）。

### 为什么用模型建表

`ShipperPrice.__table__.create` 让两种方言（本机 SQLite / 生产 MySQL）落到**同一个形状**上
（唯一约束 `uq_shipper_price_scope` 与两个索引都跟着模型走），
不会出现「迁移建的表少一条索引」这种只在生产才发作的偏差 —— 同 `024` 的 `table.create` 手法。
"""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

VERSION = 27
NAME = "shipper_prices"
DESCRIPTION = (
    "shipper_prices：批发商自己给下游客户定的价（第三层价；contact_id 为 NULL = 默认价）。"
    "只影响他自己那本账，公司那本账与订单行金额一个字节不动"
)

TABLE = "shipper_prices"


def upgrade(engine: Engine) -> None:
    """建这张表；已经在了就什么都不做（⛔ 必须能重跑）。"""
    if TABLE in set(inspect(engine).get_table_names()):
        return
    from app.models.shipper_price import ShipperPrice

    ShipperPrice.__table__.create(bind=engine, checkfirst=True)
