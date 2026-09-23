"""报表窗口索引：**模型里声明了**要能在真建库时变成**真索引**（含列序）。

## 为什么单独立一条（2026-09-23 第 9 轮）

生产 `EXPLAIN ANALYZE` 实测：报表那一族查询（`status='DELIVERED' AND deleted_at IS NULL
AND delivered_at ∈ [窗口)`）走的是 **`Table scan on o`** —— 窗口条件没进任何索引。
也就是说第 3 轮加的"窗口预过滤"（`delivered_span_sql`）**只减少了进内存的行，没减少从库里读的行**；
而数据保留策略是 3 年，代价随时间线性长。

修法两处、缺一不可：`models/order.py` 声明 `(status, delivered_at)` 复合索引（新库由
`create_all` 建出来）+ `core/schema_bootstrap.py` 给**老库**幂等补建
（`SHOW INDEX … Key_name` 守卫 + `ALTER TABLE … ADD INDEX`）。

红线 `_tools/qa/_check_report_window.py` 的 ⑤c 是**看文本**（模型里有没有那一行、列序写没写反、
bootstrap 有没有守卫、窗口条件是不是裸列比较）；这条测试是**看结果**：拿一份全新的库建一遍，
再问 SQLite 这个索引到底在不在、列序是什么。两者不重复 ——
"文本对但建不出来"（列名写错、被后来的 `__table_args__` 覆盖、索引名撞了）只有这条能抓到。

⚠️ 刻意**不用** `tests/.test_dbs/` 那份模板库：`create_all(checkfirst=True)` 对**已存在的表**
是整表跳过（连它上面的索引一起跳过），而模板是历史文件 —— 拿它断言等于在断言"上个版本的库"。
所以这里用 `tmp_path` 里一份全新的库（与 conftest 建库用的是同一套 `Base.metadata`）。
"""
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401 - 注册全部模型
from app.models.base import Base

INDEX_NAME = "ix_orders_status_delivered"
#: 列序不是审美问题：`status` 是等值条件、`delivered_at` 是范围条件，
#: 反过来（范围列在前）就只有第一段能用上，窗口那一段仍然是全表扫。
EXPECTED_COLUMNS = ["status", "delivered_at"]


def _orders_indexes(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'schema_check.db'}")
    try:
        Base.metadata.create_all(bind=engine)
        return inspect(engine).get_indexes("orders")
    finally:
        engine.dispose()


def test_report_window_index_is_created_with_the_right_column_order(tmp_path):
    indexes = {ix["name"]: ix for ix in _orders_indexes(tmp_path)}
    assert INDEX_NAME in indexes, f"建库之后 orders 上找不到 {INDEX_NAME}：{sorted(indexes)}"
    assert indexes[INDEX_NAME]["column_names"] == EXPECTED_COLUMNS, indexes[INDEX_NAME]


def test_report_window_index_is_composite_not_just_status(tmp_path):
    """⛔ 只要 `status` 一列不算数：单列 `status` 索引下，窗口那一段还是全表扫（改前的样子）。"""
    ix = {i["name"]: i for i in _orders_indexes(tmp_path)}[INDEX_NAME]
    assert len(ix["column_names"]) >= 2, ix
    assert "delivered_at" in ix["column_names"], ix
