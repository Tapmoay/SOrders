"""009_freight_rule_snapshot：给 orders 加 freight_rule_snapshot（承运运费的**来源凭据**）。

### 为什么加它（用户 2026-09-27 拍板 §6）

R4-09 的计价事实审计查出来的缺口：`orders.freight_fee` 有金额、有分类，
**没记是哪一条价目产生的**，全库也没有任何一处记「按哪一版计价契约算的」——
于是半年后没人能回答「这 120.00 当时凭什么」。
用户判据原话：「**能重新计算 ≠ 能证明历史为什么是这个金额。**」

### 为什么走迁移而不是 schema_bootstrap

migrations/README.md 的分工：**正式变更**走本目录、**运行时自愈**走 bootstrap。
加一列是正式变更（老库要 ALTER、新库由 create_all 按模型建），所以是一条迁移 ——
与 `004_operation_log_origin` 同一条理由。
⚠️ 第一版**曾经只加在 bootstrap 里**（R4-11 当天就改过来了）：那会让 Bootstrap 自愈
与迁移成为**同一件事的两个来源**，而"同一个事实写两遍"正是本项目头号忌讳。

### 三条设计选择

1. **可空、无默认值**：⛔ **不回填老数据**。用户原话：「**千万不要猜着补快照**」——
   拿今天的价目表倒推历史 = **伪造历史事实**。老单这一列留 NULL，
   含义是明确的「这一段历史没有记来源」，不是"忘了填"。
2. **不加索引**：它只在看**单张订单**时被读（订单详情 / 复核），从来不用来筛选。
3. **不写 CHECK 约束**：与 `freight_fee` 的"同生共死"不变量由**写入侧**保证
   （唯一写入口 `services/order_money.record_freight_decision`，判据扫全仓的赋值）——
   加 CHECK 会把老数据（金额在、凭据 NULL）一起判成非法，而老数据**本来就是这样**。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 9
NAME = "freight_rule_snapshot"
DESCRIPTION = "orders 加 freight_rule_snapshot：承运运费的来源凭据（价目 / 计价方式 / 契约版本）。⛔ 不回填老数据"

TABLE = "orders"
COLUMN = "freight_rule_snapshot"


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    if TABLE not in insp.get_table_names():
        # 全新库由 create_all 按模型建表（模型里已经有这一列），这里没什么可做的。
        return
    cols = {c["name"] for c in insp.get_columns(TABLE)}
    if COLUMN in cols:
        return
    with engine.begin() as conn:
        # ⛔ 必须能重跑（README 硬要求：MySQL 的 DDL 隐式提交，一条迁移可能改了一半才失败）。
        # ⛔ **不加 DEFAULT、不回填**：老行留 NULL 才是事实（见模块头第 1 条）。
        conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} TEXT"))
