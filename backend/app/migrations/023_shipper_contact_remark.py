"""023_shipper_contact_remark：`shipper_contacts` 加一列 `remark`（联系人备注，L-10）。

### 为什么加它（用户 2026-10-06 原话）

> 「还有我们那个叫什么联系人，他也是要**有备注**的哈，我们联系人可以备注的；
>  以及我们那个**地点**的时候，如果选择对应的联系人，**对应的备注也会写上去**的，
>  当然，**这个备注是可以改的**……而此备注**只有自己才能看见**」

### 为什么走迁移而不是 schema_bootstrap

`migrations/README.md` 的分工：**正式变更**走本目录、**运行时自愈**（缺表补表 / 缺列补列 /
枚举补值 / 列宽放宽）走 `core/schema_bootstrap.py`。本事项加的是**一列新列**（列定义本身），
与 `012_contact_categories`（同一张表加 category）、`010_vehicle_attrs`、
`011_contact_phone_optional` 同一条理由。⛔ 不两边都写：「这一列从哪来」只能有一个来源 ——
`schema_bootstrap.py` 里只给 `shipper_locations` 补列（image_url / image_urls /
contact_name / contact_phone），**没有**给 `shipper_contacts` 补列的自愈，本次也不新开一条。

### 三条设计选择

1. **`NOT NULL DEFAULT ''`**（空串 = 没写备注）—— 与 `shipper_locations.remark` **逐字同形**
   （同样是 `String(256)`、同样 `default=""`）：这一行备注会被客户端**带进地点备注栏**，
   两边长度不一样就会出现「带过去就被截断」这种没人能解释的现象。
2. **⛔ 不回填**。老联系人的备注**一个都不猜**：没人能证明某个联系人在用户心里叫什么，
   与 009「千万不要猜着补快照」、010「不回填老车属性」、011「不回填空串」、012「不回填分类」
   同一条纪律。全员落进空串＝没写备注。
3. **⛔ 不建索引**：这一列只跟着联系人行一起读写（列表端点取全量、按常用度排序），
   没有任何按 remark 过滤 / 排序的查询 —— 与 `shipper_locations.remark` 一样不建索引
   （012 建索引是因为**分类要分栏**，备注不分栏）。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 23
NAME = "shipper_contact_remark"
DESCRIPTION = "shipper_contacts 加 remark（联系人备注，空串=没写）。⛔ 不回填老数据、⛔ 不建索引"

TABLE = "shipper_contacts"
COLUMN = "remark"
DDL = "remark VARCHAR(256) NOT NULL DEFAULT ''"


def _columns(engine: Engine) -> set[str] | None:
    """这一张表现有的列名；None = 表还不存在（全新库，没什么可做的）。"""
    insp = inspect(engine)
    if TABLE not in insp.get_table_names():
        return None
    return {c["name"] for c in insp.get_columns(TABLE)}


def upgrade(engine: Engine) -> None:
    have = _columns(engine)
    if have is None:
        # 全新库由 create_all 按模型建表（模型里已经有这一列），这里没什么可做的。
        return
    if COLUMN not in have:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {DDL}"))
