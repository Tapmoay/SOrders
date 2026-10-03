"""013_route_categories：`shipper_addresses` 加一列 `category`（线路分类，2026-10-04）。

### 为什么加它（用户 2026-10-04 原话）

> 「**干脆给线路联系人以及地点，这3个的界面玩个框了框的位置加一个分类显示**，它目前，
>  全部的话，就显示，全部如果是其他分类就显示，其他分类点击这个按钮的时候，它就会弹出一个
>  在左侧来，它这个左侧抽屉左侧抽屉就是我们的那个分类显示，可以去参考账本管理的那些代码」

三档页签（路线 / 联系人 / 地点）要长得一样，而**线路这一档当时根本没有分类**：
`shipper_contacts.category`（迁移 012）与 `shipper_locations.category` 都在，只有
`shipper_addresses` 少了这一格 —— 界面上就没有"分类显示"可点。

### 为什么走迁移而不是 schema_bootstrap

`migrations/README.md` 的分工：**正式变更**走本目录、**运行时自愈**（缺表补表 / 缺列补列 /
枚举补值 / 列宽放宽）走 `core/schema_bootstrap.py`。本事项加的是**一列新列**（列定义本身），
与 `009_freight_rule_snapshot`、`010_vehicle_attrs`、`011_contact_phone_optional`、
`012_contact_categories` 同一条理由。
⛔ 不两边都写："这一列从哪来"只能有一个来源。

### 四条设计选择（与 012 逐条同形）

1. **`NOT NULL DEFAULT ''`**（空串 = 未分类）—— 与 `shipper_contacts.category` /
   `shipper_locations.category` **逐字同形**（同样是 `String(32)`、同样 `index=True`）：
   三处的"分类"是同一件事，读侧不该出现第三套写法。
2. **⛔ 不回填**。老线路的分类**一个都不猜**：这一条到底是"常送"还是"应急"**没人能证明**，
   与 009「千万不要猜着补快照」、010「不回填老车属性」、011「不回填空串」、
   012「老联系人一律未分类」同一条纪律。全员落进空串＝未分类，谁属于哪一类由用户自己分。
3. **索引由本迁移建**：`create_all(checkfirst=True)` **不给已存在的表加索引**
   （`core/schema_bootstrap.py` 开头记着这条同族缺陷 D4），所以老库上必须在这里补。
   ⚠️ 名字 `ix_shipper_addresses_category` 与 `index=True` 的默认名一致 —— 两处建的是
   **同一张**索引，别建两条（先例：`007_outbox_aggregate_id.py` 同一句注释）。
4. **`route_categories` 表不在这里建**：新表由 `create_all` 建（先例：`place_categories` /
   `contact_categories` / `product_categories` / `expense_categories` 都是这么来的，
   见 `core/schema_bootstrap.py` 里那几条「表由 create_all 建，这里只做存量回填」）。
   本事项**没有存量回填**（老数据一律未分类）。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 13
NAME = "route_categories"
DESCRIPTION = "shipper_addresses 加 category（线路分类，空串=未分类）+ 索引。⛔ 不回填老数据"

TABLE = "shipper_addresses"
COLUMN = "category"
DDL = "category VARCHAR(32) NOT NULL DEFAULT ''"
#: 与模型里 `index=True` 生成的默认名一致（两处建的是同一张索引，见模块头第 3 条）。
INDEX_NAME = "ix_shipper_addresses_category"


def _columns(engine: Engine) -> set[str] | None:
    """这一张表现有的列名；None = 表还不存在（全新库，没什么可做的）。"""
    insp = inspect(engine)
    if TABLE not in insp.get_table_names():
        return None
    return {c["name"] for c in insp.get_columns(TABLE)}


def _indexes(engine: Engine) -> set[str]:
    return {ix["name"] for ix in inspect(engine).get_indexes(TABLE)}


def upgrade(engine: Engine) -> None:
    have = _columns(engine)
    if have is None:
        # 全新库由 create_all 按模型建表（模型里已经有这一列与这张索引），这里没什么可做的。
        return
    # ⛔ 加列与建索引**分开判、分开执行**：MySQL 的 DDL 隐式提交，一条迁移可能改了一半才失败；
    #    下次重跑必须能接着往下走（README 硬要求「必须能重跑」）。
    if COLUMN not in have:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {DDL}"))
    if INDEX_NAME not in _indexes(engine):
        with engine.begin() as conn:
            conn.execute(text(f"CREATE INDEX {INDEX_NAME} ON {TABLE} ({COLUMN})"))
