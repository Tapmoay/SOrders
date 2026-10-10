"""030_user_category_parent：`user_categories` 加一列 `parent_id`（两级分类，2026-10-11 CHG-0112）。

### 为什么加它（用户 2026-10-11 原话）

> 「假如我的货主和批发商做了分类的话，然后我这个账户管理就会显示 2 级分类，
>  也就会显示他们里面的子分类。这就方便我们去查角色嘛……假如他没有多少分类吗？
>  一堆的话到时候查起来非常麻烦。」

账户管理页左栏要「大类 + 缩进的子类」，点大类筛出它下面**所有**子类的账号。
而这张表原来是**平表**（只有 `name + sort_order`）——「大类」这件事无处可存。

### 为什么走迁移而不是 schema_bootstrap

`migrations/README.md` 的分工：**正式变更**走本目录、**运行时自愈**走
`core/schema_bootstrap.py`。本事项加的是**一列新列**（列定义本身），
与 `014_user_categories`（同一张表的另一列）逐条同形。

### 为什么不是「名字里带分隔」（方案 A）

方案 A 把父子关系编码进名字（`货主 / 食堂`），后端零迁移，但：
1. **大类本身不是一行** —— 左栏得靠前缀**造**出一个父格，
   「有哪些大类、什么顺序」就没有出处了（名册的全部意义就是那个顺序）；
2. **改大类名要重写所有子类名 ＋ 所有账号的 `category`**（前缀级联），
   而现在的改名级联是**整名相等**（`update_category` 里那句 `User.category == old_name`）——
   前缀重写正好打在本事项明令不许破坏的那段语义上；
3. 分隔符会跟用户自己起的名字打架（他真起一个「货主 / 食堂」呢？）。

### 三条设计选择（与 014 同形）

1. **`NULL` = 大类本身**（不是 0、不是空串）：没有父就是没有父。
   `0` 会变成一个"不存在的分类编号"哨兵，两库的表现还不一样。
2. **⛔ 不回填**。老库一行都没有父子信息 —— 谁是谁的子类**没人能证明**，
   一律落进 `NULL`＝大类，与 014「不回填」同一条纪律。
3. **索引由本迁移建**：`create_all(checkfirst=True)` 不给已存在的表加索引
   （`core/schema_bootstrap.py` 开头记着这条同族缺陷 D4）。
   ⚠️ 名字与模型 `index=True` 的默认名一致（`ix_user_categories_parent_id`）——
   两处建的是**同一张**索引，别建两条。
   ⛔ 不要写 `CREATE INDEX IF NOT EXISTS`：MySQL 没有这个语法，生产会停在那一句
   （2026-10-06 发版 0.2.6 栽过，见 `_check_migrations.py` 第 7 组）。

### 「只两级」在这一列上保证吗

不。这一列只管「有没有父」；「父必须自己也是大类」由**写入路径**保证
（`api/v1/user_categories.py::_parent_or_400`），所以结构里不会出现第三层。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 30
NAME = "user_category_parent"
DESCRIPTION = "user_categories 加 parent_id（两级分类：NULL=大类）。⛔ 不回填老数据"

TABLE = "user_categories"
COLUMN = "parent_id"
DDL = "parent_id INTEGER NULL"
INDEX_NAME = "ix_user_categories_parent_id"


def _columns(engine: Engine) -> set[str] | None:
    """`user_categories` 现有的列名；None = 表还不存在（全新库，没什么可做的）。"""
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
