"""033_vehicle_inspection：`vehicles` 加两列（上牌日期 / 上次年检日期）。

### 为什么加它们（FEAT-0022，需求方 2026-10-11 口述）

> 「关于这个车辆年检提醒啊，到我给那个车子建档案的时候会填一下就是这车的**上牌日期**。
>   或者说是**上一个年检日期**啊方便我们去做一个提醒」

也就是说：用户**不打算**在系统里维护一个"下次年检到哪天"的字段 —— 他只愿意录一次已经发生过的
事实（这车哪天上的牌 / 上一次什么时候检的），"下次该检了"由系统**算**出来。
所以这两列是**输入**，下次年检日期是**派生量**（见 `services/inspection_due.py`）。

FEAT-0021 把 `vehicle.inspection_due` 登记了档位却没有生产者，理由原文就是
「年检 / 保险日期字段**全库不存在**」—— 这两列就是那一句话的解法。

### 为什么要走迁移而不是 schema_bootstrap

`migrations/README.md` 的分工：**正式变更**走本目录、**运行时自愈**走 `core/schema_bootstrap.py`。
本事项加的是**两列新列**（列定义本身），与 `010_vehicle_attrs` / `012_contact_categories` /
`015_vehicle_categories` / `018_vehicle_depreciation` 同一条理由。
`schema_bootstrap` 里那份是同一句 DDL 的自愈副本，给「迁移没跑过就直接起服务」的库兜底。

### 三条设计选择

1. **两列全部可空、不回填**。老车没有这份记录 —— 给一台没录过的车编一个上牌日期，
   后果是"系统会自己造一条假的年检提醒出来"（比不提醒更坏）。NULL 的含义是「**没录**」，
   ⛔ 不是"没上牌"、也不是"从来没检过"。
2. **没有索引**：这两列只随车辆行按主键读出（车辆的读法只有「列表 + 单行」），
   每日扫描是**全表按这两列非空**扫一遍小车队（几百行量级），建索引只会拖慢写入。
3. **⛔ 不加"下次年检日期"列**：它是派生量，落库就意味着"改了上次年检日期之后，
   那个算出来的旧值还留在库里"。计算只有一处（`services/inspection_due.py`）。

### 可重跑

逐列判存在性、逐列执行（MySQL 的 DDL 隐式提交：一条迁移可能改了一半才失败，
下次重跑必须能接着往下走 —— README 硬要求）。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 33
NAME = "vehicle_inspection"
DESCRIPTION = (
    "vehicles 加两列（registration_date 上牌日期 / last_inspection_date 上次年检日期）："
    "用户只录已经发生过的事实，下次年检日期由系统按「(上次年检 or 上牌) + 1 年」现算"
    "（⛔ 不落库）。两列全部可空、NULL = 没录、⛔ 不回填老车"
)

TABLE = "vehicles"

COLUMNS: dict[str, str] = {
    "registration_date": "registration_date DATE NULL",
    "last_inspection_date": "last_inspection_date DATE NULL",
}


def _columns(engine: Engine) -> set[str] | None:
    """`vehicles` 现有的列名；None = 表还不存在（全新库由 `create_all` 按模型建全）。"""
    insp = inspect(engine)
    if TABLE not in insp.get_table_names():
        return None
    return {c["name"] for c in insp.get_columns(TABLE)}


def upgrade(engine: Engine) -> None:
    have = _columns(engine)
    if have is None:
        # 全新库：模型里已经有这两列，create_all 建出来的表就是全的。
        return
    for name, ddl in COLUMNS.items():
        if name in have:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN " + ddl))
