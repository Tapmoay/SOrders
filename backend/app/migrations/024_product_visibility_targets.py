"""024_product_visibility_targets：`user_product_visibility` 加两列（分类维 + 允许/排除），
并把唯一性从"一个用户一个商品一行"扩成"一个用户一个分类一个模式一行"（CHG-0062 / 台账 L-23）。

### 为什么加它（用户 2026-10-06 原话）

> 「假如以后有其他商品增加到这个分类，**它自动是显示的**」
> 「**这个分类是要全部显示的，但是某个商品我们不让它显示**，就把它直接关闭……
>   以后其他新商品增加到这个分类，**他也会正常显示**」

⇒ 可见范围从"只认单品"扩成"分类 + 单品、授权 + 排除"。这两列就是承载它的全部结构：
`category_name` 为空 = 单品行（老行全是这样）；非空 = 分类行（**空串 = 「未分类」那一类**，
与 `products.category` 同一套写法）；`mode` 分 allow / deny。

### 为什么走迁移而不是 schema_bootstrap

`migrations/README.md` 的分工：**正式变更**走本目录、**运行时自愈**（缺表补表 / 缺列补列 /
枚举补值 / 列宽放宽）走 `core/schema_bootstrap.py`。本次加的是**两列新列 + 一条唯一索引**，
外加**一列的可空性**（列定义本身），与 `011_contact_phone_optional`、`012_contact_categories`、
`014_user_categories`、`022_shipper_status_hold` 同一条理由。
⛔ 不两边都写：「这两列从哪来」「这一列可不可空」都只能有一个来源 —— `schema_bootstrap.py` 里
**没有**给 `user_product_visibility` 补列 / 改可空性的自愈，本次也不新开一条。

### 五条设计选择

1. **老行靠列默认值天然变成"单品授权项"，⛔ 一条数据都不搬家。**
   `mode VARCHAR(8) NOT NULL DEFAULT 'allow'` 一加上去，现存每一行就是
   `product_id=有值 / category_name=NULL / mode=allow` —— 这正是旧语义（单品白名单）的逐字翻译。
   ⛔ 绝不把任何老行解释成分类行：那会把"只给他看这 3 个商品"悄悄变成"给他看这 3 个商品所在的分类"，
   范围一下子放大到用户没同意的程度（同 009「千万不要猜着补快照」、012「不回填分类」的纪律）。
2. **唯一索引带上 `mode`**（`uq_upv_category(user_id, category_name, mode)`）：
   allow 与 deny 是两行、各自唯一。⛔ 不写成 `(user_id, category_name)` —— 那样
   "这一类给他看"与"这一类不给他看"会互相顶掉，写第二行直接报唯一冲突。
   旧约束 `uq_user_product_visibility(user_id, product_id)` **原样保留**：
   SQLite/MySQL 里 NULL 互不相等，分类行（product_id 为 NULL）不受它管。
3. **⛔ 不给 `category_name` 建普通索引**：这张表只按 `user_id` 取整份（端点是"读这个人的整份配置"），
   没有任何按分类名反查的查询 —— 唯一索引里已经带了这一列，够用（同 023 不建索引那条理由）。
4. **模型里的 `CheckConstraint`（一条明细只指一个目标）在纯 ALTER 的老库上补不上**：
   SQLite 的 `ALTER TABLE` 加不了 CHECK。这类库靠**写入端归一**兜住
   （`replace_visibility` 永远是"先清后写"，只会写出一种目标）——
   ⚠️ 走下面第 5 条**整表重建**的老库是例外：重建按模型建表，CHECK 会一起落下去。
5. **⚠️ `product_id` 的可空性也必须在迁移里补上（否则分类行写不进去，接口 500）。**
   024 之前建出来的库里这一列是 `NOT NULL`（模型里 `product_id: Mapped[int | None]` 只对
   `create_all` 建的新库生效）；而分类行恰恰要求 `product_id IS NULL` ——
   只加两列不补可空性的话，"按分类授权"这个功能在半数以上的真实库上**一写就报
   `NOT NULL constraint failed: user_product_visibility.product_id`**，而单测全绿
   （测试库都是 `create_all` 建的新形状，2026-10-06 真库探针才撞出来）。
   手法照 `011_contact_phone_optional`：SQLite 不支持 `MODIFY COLUMN` ⇒ **中转表 + DROP + 按模型重建**；
   其它方言一句 `MODIFY COLUMN product_id INT NULL`。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 24
NAME = "product_visibility_targets"
DESCRIPTION = (
    "user_product_visibility 加 category_name（空串=未分类）与 mode（allow/deny），"
    "并加唯一索引 (user_id, category_name, mode)。⛔ 老行不搬家、⛔ 不建普通索引"
)

TABLE = "user_product_visibility"
COLUMNS: tuple[tuple[str, str], ...] = (
    ("category_name", "category_name VARCHAR(32)"),
    ("mode", "mode VARCHAR(8) NOT NULL DEFAULT 'allow'"),
)
INDEX = "uq_upv_category"
INDEX_DDL = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX} ON {TABLE} (user_id, category_name, mode)"
)
#: 分类行的 product_id 是 NULL，所以这一列必须可空（见 docstring 第 5 条）。
COLUMN_PRODUCT_ID = "product_id"
#: SQLite 中转表名。带事项号，避免和别的表撞名（同 011 的写法）。
STAGING = f"{TABLE}_chg0062_stage"


def _columns(engine: Engine) -> set[str] | None:
    """这一张表现有的列名；None = 表还不存在（全新库，没什么可做的）。"""
    insp = inspect(engine)
    if TABLE not in insp.get_table_names():
        return None
    return {c["name"] for c in insp.get_columns(TABLE)}


def _product_id_nullable(engine: Engine) -> bool | None:
    """True/False = 这一列现在可不可空；None = 表或列不存在（全新库，没什么可做的）。"""
    insp = inspect(engine)
    if TABLE not in insp.get_table_names():
        return None
    for col in insp.get_columns(TABLE):
        if col["name"] == COLUMN_PRODUCT_ID:
            return bool(col["nullable"])
    return None


def _sqlite_rebuild(engine: Engine) -> None:
    """SQLite：把数据搬进中转表 → 整张删掉旧表 → 按模型重建 → 搬回来（同 011 的手法）。

    ⚠️ 用**中转表 + DROP**、不用 `RENAME TO`：SQLite 的 RENAME 会把 `index=True`
    建出来的具名索引留在旧表名下，新表再建同名索引直接撞名；整表 DROP 则连索引一起走。
    """
    from app.models.product_visibility import UserProductVisibility

    table = UserProductVisibility.__table__
    new_cols = [c.name for c in table.columns]
    cols_sql = ",".join(f'"{c}"' for c in new_cols)

    with engine.begin() as conn:
        old_cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({TABLE})")).fetchall()}
        sel_sql = ",".join(f'"{c}"' if c in old_cols else "NULL" for c in new_cols)
        conn.execute(text(f'DROP TABLE IF EXISTS "{STAGING}"'))
        conn.execute(text(f'CREATE TABLE "{STAGING}" AS SELECT {sel_sql} FROM "{TABLE}"'))
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE "{TABLE}"'))
    table.create(bind=engine, checkfirst=True)
    with engine.begin() as conn:
        # 位置对应（中转表是按 new_cols 的顺序 select 出来的），所以这里不逐个点名列。
        conn.execute(text(f'INSERT INTO "{TABLE}" ({cols_sql}) SELECT * FROM "{STAGING}"'))
        conn.execute(text(f'DROP TABLE "{STAGING}"'))
        # 重建把上面那条具名唯一索引一起带走了（模型里是内联 UNIQUE 约束，SQLite 给它起的是
        # sqlite_autoindex_* 这种名字），所以这里补回同一句 DDL，让"重建过的老库"与
        # "只走 ALTER 的老库"落到同一个形状上。
        conn.execute(text(INDEX_DDL))


def upgrade(engine: Engine) -> None:
    have = _columns(engine)
    if have is None:
        # 全新库由 create_all 按模型建表（模型里已经有这两列、两条唯一约束、一条 CHECK，
        # 且 product_id 本来就可空），这里没什么可做的。
        return
    with engine.begin() as conn:
        for name, ddl in COLUMNS:
            if name not in have:
                conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {ddl}"))
        conn.execute(text(INDEX_DDL))
    # ⚠️ 顺序：先补完上面两列，再重建 —— 重建是按模型列名搬数据的，`mode` 得先在表里
    #    （老库上它由列默认值 `'allow'` 填出来）。
    nullable = _product_id_nullable(engine)
    if nullable is False:
        if engine.dialect.name == "sqlite":
            _sqlite_rebuild(engine)
            return
        # MySQL / 其它方言：一句 MODIFY 就够。唯一约束是**独立对象**，改列不会把它带走。
        with engine.begin() as conn:
            conn.execute(
                text(f"ALTER TABLE {TABLE} MODIFY COLUMN {COLUMN_PRODUCT_ID} INT NULL")
            )
