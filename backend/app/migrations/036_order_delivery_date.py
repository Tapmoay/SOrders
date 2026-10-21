"""036_order_delivery_date：给 orders 加一列 delivery_date（期望送达日，FEAT-0028）。

### 为什么加它（用户 2026-10-21 原话）

> 「这个功能就是货主和批发商以及派单员，他们在下单的时候……**可以选择送到的日期**，
>   然后我们还要加一个警示……告诉他们**订单必须提前一天下达**，当天下的单不一定能准时送达。」

今天一张单上只有 `order_date`（**哪天下的单**）：它既当报表分桶的键，又当账本归属日的兜底。
「这单哪天送到」在**送达之前根本不存在**（送达那一刻才有 `delivered_at`），所以下单时
选的那个日子没有任何落点 —— 只能写进备注，谁也搜不出来、也画不到卡片上。

### 为什么是一列新的，而不是复用现成那两个

| 候选 | 为什么不行 |
|---|---|
| `order_date` | 那是"哪天下的单"。与送达日合并成一列之后，"提前一天"就永远成立了（每天看起来都合规），而报表按它分的桶会跟着错位 |
| `expected_deliver_before` | 那是**截止时刻**：准时率的分母（`services/stats_service.py:35`）与自动异常（`:388` 到点未送达即登记）都按它判。拿"选了个日期"写它 = 替用户登记了一个截止时刻，到点这单**自己变成异常单** |

### 为什么走迁移而不是 schema_bootstrap

migrations/README.md 的分工：**正式变更**走本目录、**运行时自愈**走 bootstrap。
加列是正式变更（老库要 ALTER，新库由 `create_all` 按模型建），与 `009_freight_rule_snapshot`、
`025_order_discount` 同一条理由。⛔ 两边都写 = 同一件事两个来源，本次不新开 bootstrap。

### 三条设计选择

1. **可空、⛔ 无默认值、⛔ 不回填**：NULL = 这一单**没选过**送达日期（老客户端 / AI 下单 /
   存量单）。拿今天去猜"老单本来想哪天送"就是伪造历史事实（同 009 那句"千万不要猜着补快照"）。
2. **不建索引**：这一列只在**看单张订单**（详情 / 出参 / 卡片）时被读，本轮不参与任何筛选或排序；
   等真出现"按送达日筛"的查询再加（索引的作用是查询，不是"看起来完整"）。
3. **日期列按 `Date` 存**（不是 DATETIME）：用户选的是**哪一天**，时分秒是业务不需要的精度 ——
   存成时刻就得回答"那是当地几点"，而多一个时分秒只会让"这单算不算当天"多一种解释。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 36
NAME = "order_delivery_date"
DESCRIPTION = "orders 加 delivery_date（期望送达日）。⛔ 可空、无默认值、不回填老数据、不建索引"


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    if "orders" not in insp.get_table_names():
        # 全新库：表由 `create_all` 按模型建好，这一列已经在里面了（没什么可做的）。
        return
    cols = {c["name"] for c in insp.get_columns("orders")}
    if "delivery_date" in cols:
        # ⛔ 必须能重跑：MySQL 的 DDL 是隐式提交的，失败可能留半截（README 硬要求 2）。
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_date DATE"))
