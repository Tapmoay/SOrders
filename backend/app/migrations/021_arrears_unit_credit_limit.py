"""021_arrears_unit_credit_limit：给 arrears_units 加 credit_limit（赊账客户的信用额度）。

### 为什么加它（FEAT-0015 第五期）

第五期要回答的两个问题里，第二个是「**这家还能赊多少**」。在此之前全库没有一处记得住
「最多允许欠多少」—— 客户欠了多少能算（`order_money.arrears`），但只要没有一个上限，
报表就只能把数字摆出来、说不出「已经超了」。

### 为什么额度长在「挂账单位」上，不长在「客户档案」上

订单上挂的是 `arrears_unit_id`（+ 名字快照），订单与 `customers` 之间隔着
`customers.arrears_unit_id` 这条**可空、非唯一**的映射 —— 一个单位可能对多条客户档案、
一条客户档案也可能没有单位。额度要能算「已用 / 剩余」，就必须与报表行 1:1；
报表行的身份是**债务人**（挂账单位 → 货主 → 临时货主），其中只有挂账单位这张表是「赊账主体」
自己的名册（模型 docstring 原文：「赊账客户（临时货主/单位）」）。

### 三条设计选择

1. **可空、无默认值、不回填**：NULL = **不限额**。⛔ 不回填、⛔ 不当 0
   —— 0 的含义是「一分钱都不许赊」，与"没设过额度"是**两件相反的事**，
   猜着补一个数就是伪造风控事实（与 009～018 同一条纪律：宁可空着）。
2. **不加索引**：额度只随挂账单位行按主键读出（读法只有「名册列表 + 报表行」），
   没有任何按它筛选的查询。
3. **额度不落任何派生值**：已用/剩余/超限全是**现算**（`services/reports/balance_query.py`），
   于是改口径不需要回填、也不需要改历史行。

### 可重跑

`migrations/README.md` 硬要求：MySQL 的 DDL 隐式提交，一条迁移可能改了一半才失败。
这里先判表在不在、再判列在不在，重复跑是空操作。
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 21
NAME = "arrears_unit_credit_limit"
DESCRIPTION = (
    "arrears_units 加 credit_limit（信用额度，DECIMAL(14,2) 可空）："
    "第一次记得住「这家最多能赊多少」。NULL = 不限额、⛔ 不回填老数据、⛔ 不当 0"
)

TABLE = "arrears_units"
COLUMN = "credit_limit"
DDL = "credit_limit DECIMAL(14,2) NULL"


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    if TABLE not in insp.get_table_names():
        # 全新库由 create_all 按模型建表（模型里已经有这一列），这里没什么可做的。
        return
    if COLUMN in {c["name"] for c in insp.get_columns(TABLE)}:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN " + DDL))
