"""018_vehicle_depreciation：`vehicles` 加四列（购置价 / 购置日期 / 使用年限 / 残值率）。

### 为什么加它们（FEAT-0012 第二期，需求方 2026-10-04 拍板）

> 折旧怎么算 → 「录「购置价 ＋ 购置日期 ＋ 使用年限 ＋ 残值率」，系统**按月直线法**自动计提」
> 折旧放哪里 → 「**并入「期间费用」那一层**（与开销同一层，多一行「− 车辆折旧」）」
> 历史车怎么办 → 「**不回溯**：缺购置价的车不算折旧，利润表里单列「未覆盖折旧」并说明」

第一期（FEAT-0011）那张经营利润表的口径说明第 2 条原文就是：
「折旧没有算进去：车辆台账里没有购置价与折旧字段，也没有月度计提。所以这张表的营业利润偏高
（少了折旧那一块），第二期补车辆台账时接进来。」—— 这四列就是那一步的**输入**。

### 为什么要走迁移而不是 schema_bootstrap

`migrations/README.md` 的分工：**正式变更**走本目录、**运行时自愈**走 `core/schema_bootstrap.py`。
本事项加的是**四列新列**（列定义本身），与 `010_vehicle_attrs` / `012_contact_categories` /
`013_route_categories` / `014_user_categories` / `015_vehicle_categories` / `016_session_end_reason`
`017_settlement_bill_ids` 同一条理由。`schema_bootstrap` 里那份是同一句 DDL 的自愈副本，
给「迁移没跑过就直接起服务」的库兜底。

### 三条设计选择

1. **四列全部可空、不回填**。老车没有这份台账 —— 编一个购置价出来等于替用户记错账
   （与 009～017 同一条纪律：宁可空着）。NULL 的含义是「**没录**」，⛔ 不是 0：
   购置价 NULL ≠ 0 元的车、年限 NULL ≠ "当年就提完了"。
2. **折旧额不进库**（这一条不是 SQL，是本事项立场的落点）：这四列只是**输入**，
   折旧是**派生量** —— 每次按窗口现算（`services/vehicle_depreciation.py`），
   于是改口径不需要改历史行、也不需要回填任何一个月。
3. **没有索引**：这四列只随车辆行按主键读出（车辆的读法只有「列表 + 单行」），
   没有任何按它们筛的查询；建索引只会拖慢写入。

### 可重跑

逐列判存在性、逐列执行（MySQL 的 DDL 隐式提交：一条迁移可能改了一半才失败，
下次重跑必须能接着往下走 —— README 硬要求）。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 18
NAME = "vehicle_depreciation"
DESCRIPTION = (
    "vehicles 加四列（purchase_price / purchase_date / useful_life_years / residual_rate）："
    "车辆台账第一次记得住「这车多少钱买的、什么时候买的、用几年、最后剩多少」，"
    "折旧按月直线法现算（⛔ 不落库）。四列全部可空、NULL = 没录、⛔ 不回填老车"
)

TABLE = "vehicles"

COLUMNS: dict[str, str] = {
    "purchase_price": "purchase_price DECIMAL(12,2) NULL",
    "purchase_date": "purchase_date DATE NULL",
    "useful_life_years": "useful_life_years DECIMAL(4,1) NULL",
    "residual_rate": "residual_rate DECIMAL(5,4) NULL",
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
        # 全新库：模型里已经有这四列，create_all 建出来的表就是全的。
        return
    for name, ddl in COLUMNS.items():
        if name in have:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN " + ddl))
