"""017_settlement_bill_ids：`driver_settlements` 加两列（覆盖哪几行明细 / 手工改额差额）。

### 为什么加它们（2026-10-03 三端真机 E2E 走查后的用户拍板）

> 「你说结账单的数字和明细对不上，这是非常大的问题啊…金钱对不上账会出现问题的，
>  这个必须要修的，必须查明原因，看是不是代码写错了，还是哪个逻辑链路出现了问题」

根因是**两套取数口径**（`backend/app/services/accounting_service.py`）：
`create_settlement` 按「司机 + 月 + 类型 + OPEN + 订单未软删」取明细（其中
`or_(DriverBill.order_id.is_(None), ...)` 让 `order_id` 为空的历史孤儿账单**也算进金额**），
`confirm_settlement` 却按 `order_ids` 重取 —— 孤儿没有单号，永远取不回来 ⇒
`amount` 比明细合计多出孤儿那几笔，确认接口必然 400（全量套件里那 3 条长期红：
「结算单金额 970.00 与明细合计 940.00 不一致，请核对」），真机上的表现是
**那张结算单永远确认不了、司机这笔钱结不掉**（只能改库）。

处置（BUG-0007）：把「这一单覆盖哪几行」在建单当刻**定死**，确认 / 付款 / 作废全按它走；
手工改额不再是把金额硬改掉，而是记下差额。

### 为什么要走迁移而不是 schema_bootstrap

`migrations/README.md` 的分工：**正式变更**走本目录、**运行时自愈**走
`core/schema_bootstrap.py`。本事项加的是**两列新列**（列定义本身），与
`012_contact_categories` / `013_route_categories` / `014_user_categories` /
`015_vehicle_categories` / `016_session_end_reason` 同一条理由。
`schema_bootstrap` 里那份是同一句 DDL 的自愈副本，给「迁移没跑过就直接起服务」的库兜底。

### 三条设计选择

1. **`bill_ids` 可空、不回填**。老单没有这份清单 —— 编一份出来等于替用户记错账
   （与 009～016 同一条纪律：宁可空着）。读侧按「空 = 老单，走老路」处理
   （`confirm_settlement` 里保留下来的那两条老分支）。
2. **`adjustment` 是 `DECIMAL(12,2) NOT NULL DEFAULT 0`**：恒等式
   `amount == 明细合计 + adjustment`（手工改额记差额，而不是把金额硬改掉）。
   老单 / 没改过 = 0，所以补列不改变任何既有单的判断。
3. **没有索引**：这两列只随行按主键读出（`driver_settlements` 的读法只有「列表 + 单行」），
   没有任何按它们筛的查询；建索引只会拖慢写入。

### 可重跑

逐列判存在性、逐列执行（MySQL 的 DDL 隐式提交：一条迁移可能改了一半才失败，
下次重跑必须能接着往下走 —— README 硬要求）。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 17
NAME = "settlement_bill_ids"
DESCRIPTION = (
    "driver_settlements 加两列（bill_ids 覆盖哪几行明细 / adjustment 手工改额差额）："
    "金额与明细同源，孤儿明细不再让结算单永远确认不了。⛔ 不回填老数据"
)

TABLE = "driver_settlements"

COLUMNS: dict[str, str] = {
    "bill_ids": "bill_ids JSON",
    "adjustment": "adjustment DECIMAL(12,2) NOT NULL DEFAULT 0",
}


def _columns(engine: Engine) -> set[str] | None:
    """`driver_settlements` 现有的列名；None = 表还不存在（全新库由 `create_all` 按模型建全）。"""
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
