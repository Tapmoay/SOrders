"""010_vehicle_attrs：给 vehicles 加**车身型式 + 9 项属性**（车辆台账的固有属性）。

### 为什么加它（用户 2026-09-27 拍板，属性清单已逐条批准）

> 「可以给一辆车**固定一个属性**……在**创建车辆的时候就需要填相应的属性**。
>  **不同的车型会需要填的属性是不同的**……别说有可能是个**平板车**、有可能是一个**自卸车**。」
> 「（车辆属性）**是要算钱的**……主要的是**吨和方**这种即便（计量）单位。」

车型 / 车牌 / 司机这三样原来的表里已经有了，缺的是**这辆车本身长什么样**：
容积（一车装多少方）、载重（一车拉多少吨）、车厢 / 台面 / 车斗的尺寸、轴数。
没有它们，「一车 = 多少方」只能是一条**全库通用**的换算（`unit_conversions` 现在就是这样）。

### 为什么走迁移而不是 schema_bootstrap

`migrations/README.md` 的分工：**正式变更**走本目录、**运行时自愈**走 bootstrap。
加列是正式变更（老库要 ALTER、新库由 create_all 按模型建），所以是一条迁移 ——
与 `009_freight_rule_snapshot` 同一条理由。
⚠️ 尤其不能两边都写：那会让"这一列从哪来的"有两个来源，而"同一个事实写两遍"
正是本项目头号忌讳（009 的注释里也写着同一句）。

### 五条设计选择

1. **十列全部可空**（`body_type` 除外，它 `NOT NULL DEFAULT ''`）。
   ⛔ **不回填老数据**：老车这一批属性**本来就没人量过**，
   替它们猜一个"大货车都是 8 方"就是**伪造台账事实**（与 009 那条「千万不要猜着补快照」同一条纪律）。
   NULL 的含义是明确的「这一项没量过」，不是"忘了填"。
2. **`body_type` 与 `vehicle_type` 是两件事**，所以另起一列而不是扩 `vehicle_type` 的取值：
   `vehicle_type`（小货车 / 大货车 / 挂车）是**计费口径**，被五处共用，
   其中 `models/user.py::resolve_billing_mode` 的 `trailer → 按单计费，其余 → 固定工资` **是钱**。
   往它里面塞 `box` / `flat` / `dump`，等于让"箱式车按什么算钱"变成一个没人回答过的问题，
   而且答错了不会报错（规范 §三十三 第④条：同一个业务事实出现两个 Owner 时停下来重设计）。
3. **一列一个事实**：车厢 / 台面 / 车斗的"长 / 宽 / 高"是**同一个事实的不同叫法**
   （载货区的长 / 宽 / 高），所以是 `cargo_length_m` 三列，不是九列。
   拆成九列之后，"这辆车载货区多长"会有三个 Owner，改一处漏两处。
   界面上按型式显示不同叫法（车厢长 / 台面长 / 车斗长），**叫法**由
   `services/vehicle_attrs.py` 一处给出。
4. **`axle_count` 存 INTEGER**，其余存 `NUMERIC(…,3)`。
   ⛔ 不用 FLOAT：这几个数将来要参与「一车 = 多少方 / 多少吨」的换算，
   浮点会让 8 变成 7.999999999999999（与 `unit_conversions.factor` 用 `Numeric(14,4)` 同一条理由）。
5. **不加索引**：属性只在看**单辆车**时被读（车辆详情 / 以后的换算），从来不用来筛选。
   ⛔ 也**不加 CHECK 约束**：老库那些 NULL 行本来就合法，
   加了 CHECK 会把它们一起判成非法，启动直接崩 —— 而它们**本来就是这样的**。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 10
NAME = "vehicle_attrs"
DESCRIPTION = "vehicles 加 body_type（车身型式）+ 9 项属性（车高/车宽/净重/载重/容积/货厢三围/轴数）。⛔ 不回填老数据"

TABLE = "vehicles"

#: 列名 → DDL 片段。**顺序就是加列顺序**，与模型里声明的顺序一致（便于对读）。
#: ⚠️ 数值列一律 `NUMERIC`（不用 FLOAT，见模块头第 4 条）；
#: `body_type` 用 `NOT NULL DEFAULT ''`（空串 = 「未设置」，是**正式取值**，不是"没填"）。
COLUMNS: tuple[tuple[str, str], ...] = (
    ("body_type", "body_type VARCHAR(16) NOT NULL DEFAULT ''"),
    ("height_m", "height_m NUMERIC(8, 3) NULL"),
    ("width_m", "width_m NUMERIC(8, 3) NULL"),
    ("curb_weight_t", "curb_weight_t NUMERIC(12, 3) NULL"),
    ("load_tons", "load_tons NUMERIC(12, 3) NULL"),
    ("volume_cubic", "volume_cubic NUMERIC(12, 3) NULL"),
    ("cargo_length_m", "cargo_length_m NUMERIC(8, 3) NULL"),
    ("cargo_width_m", "cargo_width_m NUMERIC(8, 3) NULL"),
    ("cargo_height_m", "cargo_height_m NUMERIC(8, 3) NULL"),
    ("axle_count", "axle_count INTEGER NULL"),
)


def upgrade(engine: Engine) -> None:
    insp = inspect(engine)
    if TABLE not in insp.get_table_names():
        # 全新库由 create_all 按模型建表（模型里已经有这些列），这里没什么可做的。
        return
    have = {c["name"] for c in insp.get_columns(TABLE)}
    for name, ddl in COLUMNS:
        if name in have:
            continue
        # ⛔ 逐列判断、逐列 ALTER：MySQL 的 DDL 隐式提交，一条迁移可能改了一半才失败；
        #    下次重跑必须能接着往下走（README 硬要求「必须能重跑」）。
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {ddl}"))
