"""枚举补全 DDL：`schema_bootstrap.enum_repair_ddl` 生成出来的文本必须就是模型那一份。

## 为什么单独立一条（2026-09-23 第 10 轮）

MySQL 里往枚举列写一个**不在枚举里**的值是直接报错。老库那一列可能停在更早的取值集合上，
于是"新加了一个状态/来源"就变成线上 500 —— 2026-09-04 那两次生产事故正是这个形状
（`orders.status` 缺 `DISPATCHED` → 派单 100% 500；`ledgers.source` 缺 `REFUND` → 货损完成 500）。

当时的修法是在 `schema_bootstrap` 里**手写** `ALTER TABLE … MODIFY COLUMN … ENUM(…)`。
本轮盘点发现同一个文件里攒了**四**句、两句已过期（少了 `RETURNED` / `RETURN`）—— 而且谁都不报错。
现在取值清单从模型生成（`enum_repair_ddl`），这条单测钉住三件事：

1. 生成出来的 DDL **含模型里的每一个取值**（漏一个就等于没修）；
2. 列序与代码一致（枚举顺序影响 `ORDER BY`，不能随手重排）；
3. `orders.status` / `ledgers.source` 这两句的**全文**（含当年的新值）—— 改动必须是故意的。

⚠️ 单测不连数据库：文本层由这里钉，**真机层**由 `_tools/qa/_probe_prod_readonly.py --validate-ddl`
在生产那台 MySQL 上验（临时表造"旧枚举 + 已有数据"，跑生成出来的 DDL，验新值写得进、老数据不丢）。
"""
from sqlalchemy import Enum as SAEnum

import app.models  # noqa: F401 - 注册全部模型
from app.core.schema_bootstrap import _enum_columns, enum_repair_ddl
from app.models.base import Base
from app.models.order import Order

#: 历史事故那两列：当年缺的就是这两个取值，生成出来的 DDL 里必须都有。
HISTORICAL = {("orders", "status"): "RETURNED", ("ledgers", "source"): "RETURN"}


def test_every_enum_column_is_generatable_and_complete():
    """逐列生成 —— 每一列的每一个取值都要出现在 DDL 里，`NULL/NOT NULL` 跟着模型走。"""
    cols = _enum_columns()
    assert len(cols) >= 5, f"枚举列只有 {len(cols)} 个，模型没注册全？{cols}"
    for table_name, column in cols:
        values = [str(v) for v in column.type.enums]
        ddl = enum_repair_ddl(table_name, column)
        assert ddl.startswith(f"ALTER TABLE `{table_name}` MODIFY COLUMN `{column.name}` ENUM("), ddl
        for value in values:
            assert f"'{value}'" in ddl, f"{table_name}.{column.name} 的 DDL 缺取值 {value}：{ddl}"
        # 列序也必须是代码那一份（枚举顺序影响 ORDER BY，不是审美）
        assert ddl.index("ENUM(") < ddl.index(f"'{values[0]}'") < ddl.index(f"'{values[-1]}'"), ddl
        want_null = "NULL" if column.nullable else "NOT NULL"
        assert ddl.rstrip().endswith(want_null), ddl


def test_enum_repair_ddl_skips_columns_that_are_not_enums():
    """⛔ 别把非枚举列传进来 —— 那会生成一句 `ENUM()` 把列改坏（自己先断言拦住）。"""
    not_enum = next(c for c in Order.__table__.c if not isinstance(c.type, SAEnum))
    try:
        enum_repair_ddl("orders", not_enum)
    except AssertionError:
        return
    raise AssertionError(f"`{not_enum.name}` 不是枚举列，生成器却照做了")


def test_orders_status_ddl_is_the_current_six_value_list():
    """`orders.status` 的全文（历史事故那一列，改动必须是故意的）。"""
    ddl = enum_repair_ddl("orders", Order.__table__.c.status)
    assert ddl == (
        "ALTER TABLE `orders` MODIFY COLUMN `status` "
        "ENUM('PENDING_DISPATCH','DISPATCHED','ACCEPTED','DELIVERED','CANCELLED','RETURNED') NOT NULL"
    ), ddl


def test_historical_columns_keep_the_value_that_once_went_missing():
    """这两列当年就是**缺这个值**才 500 的：生成出来的 DDL 必须带着它。"""
    by_name = {(t, c.name): c for t, c in _enum_columns()}
    for key, value in HISTORICAL.items():
        column = by_name.get(key)
        assert column is not None, f"模型里找不到 {key}（改列名了？判据要跟着改）"
        assert f"'{value}'" in enum_repair_ddl(key[0], column)
        assert value in [str(v) for v in column.type.enums]


def test_enum_column_list_is_the_only_inventory():
    """`_enum_columns()` 必须等于"metadata 里所有 Enum 列" —— 它就是这个清单的唯一一份。"""
    expected = sorted(
        (t, c.name)
        for t, table in Base.metadata.tables.items()
        for c in table.columns
        if isinstance(c.type, SAEnum)
    )
    assert sorted((t, c.name) for t, c in _enum_columns()) == expected
