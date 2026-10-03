"""014_user_categories：`users` 加一列 `category`（账号分类，2026-10-05）。

### 为什么加它（用户 2026-10-05 原话）

> 「还有我们的账户管理司机管理货主管理批发商管理。车辆管理……在这个位置也加个分类，
>  默认是显示，全部，同样也是左边侧边栏，然后左边侧边栏同样也是可以新增分类的，
>  那个左边侧分栏的底下，凡是跟地点是同样的」

账户 / 司机 / 货主 / 批发商这四个名册页顶栏要能像「地址与联系人」那样按分类筛，
而**账号当时根本没有分类这一格** —— 界面上就没有"分类"可点。

### 为什么走迁移而不是 schema_bootstrap

`migrations/README.md` 的分工：**正式变更**走本目录、**运行时自愈**走
`core/schema_bootstrap.py`。本事项加的是**一列新列**（列定义本身），与
`012_contact_categories`、`013_route_categories` 同一条理由。
⛔ 不两边都写："这一列从哪来"只能有一个来源。（`schema_bootstrap` 里那份是同一句 DDL 的
自愈副本，给"迁移没跑过就直接起服务"的库兜底，照 `products.category` / `shipper_locations.category` 的先例。）

### 四条设计选择（与 013 逐条同形）

1. **`NOT NULL DEFAULT ''`**（空串 = 未分类）—— 与 `products.category` /
   `shipper_contacts.category` / `shipper_locations.category` / `shipper_addresses.category`
   **逐字同形**（同样 `String(32)`、同样 `index=True`）：五处的"分类"是同一件事，
   读侧不该出现另一套写法。
2. **⛔ 不回填**。老账号属于哪一类**没人能证明**（"这个司机是外请的还是自有的"不是
   从任何一个已有列能推出来的），与 009～013 同一条纪律：一律落进空串＝未分类，
   谁属于哪一类由用户自己分。
3. **索引由本迁移建**：`create_all(checkfirst=True)` **不给已存在的表加索引**
   （`core/schema_bootstrap.py` 开头记着这条同族缺陷 D4），所以老库上必须在这里补。
   ⚠️ 名字与 `index=True` 的默认名一致 —— 两处建的是**同一张**索引，别建两条。
4. **`user_categories` 表不在这里建**：新表由 `create_all` 建
   （先例：`product_categories` / `place_categories` / `contact_categories` /
   `route_categories` 都是这么来的）。本事项**没有存量回填**（老数据一律未分类）。

### 为什么和 015 分成两份（「一事一迁移」）

账号分类与车辆分类是**两张名册、两套端点、两个页面**：`users.category` 喂四个名册页，
`vehicles.category` 只喂车辆管理页。做成一条迁移的话，将来只回滚其中一半（比如车辆那半边
出问题）就得动一条已经上过生产、按 README 规定**永不修改**的迁移。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 14
NAME = "user_categories"
DESCRIPTION = "users 加 category（账号分类，空串=未分类）+ 索引。⛔ 不回填老数据"

TABLE = "users"
COLUMN = "category"
DDL = "category VARCHAR(32) NOT NULL DEFAULT ''"
INDEX_NAME = "ix_users_category"


def _columns(engine: Engine) -> set[str] | None:
    """`users` 现有的列名；None = 表还不存在（全新库，没什么可做的）。"""
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
