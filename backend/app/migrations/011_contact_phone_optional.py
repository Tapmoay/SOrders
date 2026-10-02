"""011_contact_phone_optional：`shipper_contacts.phone` 由 NOT NULL 改成可空（联系人手机号选填）。

### 为什么加它（用户 2026-10-03 拍板，原话）

> 「新建联系人的时候**不需要必填手机号**」
> 「我说的是新建货主的时候**没必要强迫填手机号**……在下单的时候用户或者说是货主批发商以及派单员
>  是可以不这个手机号的，**一旦补上去了，他就自动的做一份保存**」

"没填"必须有**一个**表示法：这张表上有 `(shipper_id, phone)` 唯一约束（`uq_shipper_contact_phone`），
而**空串是真值** —— 两条"没填号"的联系人在 MySQL 与 SQLite 上都会撞唯一键，
只有 NULL 才允许多行共存。所以列必须真的可空，不能靠"存个空串"糊过去。

### 为什么走迁移而不是 schema_bootstrap

`migrations/README.md` 的分工：**正式变更**走本目录、**运行时自愈**（缺表补表 / 缺列补列 /
枚举补值 / **列宽放宽**）走 `core/schema_bootstrap.py`。本事项改的是**列的可空性**（列定义本身），
是一次性结构变更 —— 与 `009_freight_rule_snapshot`、`010_vehicle_attrs` 同一条理由。
⛔ 不两边都写："这一列从哪来"只能有一个来源。

### 三条设计选择

1. **唯一约束原样保留**，只改可空性。`uq_shipper_contact_phone` 允许多个 NULL（MySQL InnoDB 与
   SQLite 都允许），于是"多条没填号"合法，而"两条同一个号码"仍然被挡住。
   ⚠️ 这条约束是**删除时要加 `_del{id}` 后缀**那套的由来（见 `DELETETE /contacts/{id}`）；
   拆掉它等于打开"同号两份档案"，不在本事项范围内。
2. **⛔ 不回填**。历史行里 `phone` 是空串 `''` 的**原样不动**（`validate_contact_phone('')` 一直是放行的，
   所以生产库里可能真有）。把 `''` 改成 NULL 是一次数据搬迁，而"这一条到底是没填、还是填了个空"
   **没人能证明** —— 与 009「千万不要猜着补快照」、010「不回填老车属性」同一条纪律。
   读侧 `ContactOut` 已经把 None 归一成空串，两种老值在界面上一模一样。
3. **SQLite 走整表重建**：SQLite 的 `ALTER TABLE` **不支持** `MODIFY COLUMN`。
   既有先例是 `core/schema_bootstrap.py::_sqlite_rebuild_table_for_nullable_shipper_id`
   （那是给 `orders/ledgers.shipper_id` 用的，列名写死）。这里复用同一手法但**不抽公共函数**：
   迁移是"跑过就不许再改"的冻结文件，把运行时自愈和一条历史迁移绑在一起，
   等于以后动 bootstrap 就等于动历史。
   ⚠️ 手法上有一处**刻意的不同**：那里用 `RENAME TO` 改名旧表，这里用**中转表 + DROP**。
   原因：SQLite 的 `RENAME` 会把 `index=True` 建出来的**具名索引留在旧表名下**，
   新表再建同名索引直接撞名；整表 DROP 则连索引一起走。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 11
NAME = "contact_phone_optional"
DESCRIPTION = "shipper_contacts.phone 由 NOT NULL 改成可空（联系人手机号选填）。⛔ 不回填空串、⛔ 不动唯一约束"

TABLE = "shipper_contacts"
COLUMN = "phone"
#: SQLite 中转表名。带事项号，避免和别的表撞名。
STAGING = f"{TABLE}_chg0010_stage"


def _phone_nullable(engine: Engine) -> bool | None:
    """True/False = 这一列现在可不可空；None = 表或列不存在（全新库，没什么可做的）。"""
    insp = inspect(engine)
    if TABLE not in insp.get_table_names():
        return None
    for col in insp.get_columns(TABLE):
        if col["name"] == COLUMN:
            return bool(col["nullable"])
    return None


def _sqlite_rebuild(engine: Engine) -> None:
    """SQLite：把数据搬进中转表 → 整张删掉旧表 → 按模型重建 → 搬回来。"""
    from app.models.shipper import ShipperContact

    table = ShipperContact.__table__
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


def upgrade(engine: Engine) -> None:
    nullable = _phone_nullable(engine)
    if nullable is None:
        # 全新库由 create_all 按模型建表（模型里 phone 本来就可空），这里没什么可做的。
        return
    if nullable:
        # 已经改过了 —— 重跑必须安静通过（README 硬要求「必须能重跑」）。
        return
    if engine.dialect.name == "sqlite":
        _sqlite_rebuild(engine)
        return
    # MySQL / 其它方言：一句 MODIFY 就够。唯一约束是**独立对象**，改列不会把它带走。
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {TABLE} MODIFY COLUMN {COLUMN} VARCHAR(32) NULL"))
