"""025_order_discount：给 orders 加七列折扣快照、给 products 加一列 no_discount（CHG-0071 / 台账 L-34）。

### 为什么加它（用户 2026-10-07 原话）

> 「我们要加个新功能就是**商品可以打折**，就是**订单它可以给订单进行打折**，
>   然后我们**对应的商品是可以固定价格的，就是不参与打折**。」（ref m01280）

今天没有任何一处能打折：改单只能改地址 / 收货人 / 备注，改价只能改商品档案单价
（**那是改所有人的报价**）或批发商专属价（**那是永久价**，把一次促销写死进报价体系）。
抹零、减 10% 这类一次性让价没有落点，也看不出「这一单为什么便宜」。

折扣必须**摊到行金额**：收款 / 账本 / 营业额 / 毛利全按 `order_products.line_total` 算
（`services/order_money.py`，`goods_amount = Σ line_total`）。只记一个整单折扣而不动行，
这条恒等式当场破 —— 所以这七列只是**快照**，钱落在行上（`services/order_discount.py` 是唯一算法）。

### 为什么走迁移而不是 schema_bootstrap

migrations/README.md 的分工：**正式变更**走本目录、**运行时自愈**走 bootstrap。
加列是正式变更（老库要 ALTER、新库由 create_all 按模型建），所以是一条迁移 ——
与 `009_freight_rule_snapshot`、`024_product_visibility_targets` 同一条理由。
⛔ 不两边都写：`schema_bootstrap.py` 里**没有**给 orders / products 补这八列的代码，本次也不新开。

### 四条设计选择

1. **八列全部可空、⛔ 一个默认值都不给、⛔ 不回填老数据**（`no_discount` 的 DEFAULT 0 是
   "老商品默认参与打折"这个业务事实，不是回填 —— 它没有把任何一单的金额改写）。
   老单七列留 NULL，含义明确的「这一单没打过折」，不是"忘了填"；拿今天的规则去猜历史折扣
   = 伪造历史事实（同 009「千万不要猜着补快照」）。
2. **七列同生共死**：写入口只有 `services/order_discount.py`（apply / clear 两处），
   ⛔ 不写 CHECK 约束 —— 老数据七列全 NULL 本来就不是"非法"，加 CHECK 会把它们一起判死。
3. **`discount_lines` 是 JSON 数组**，每项 `{"line_id": …, "before": …, "after": …}` ——
   参与折扣的 `order_products.id`、这一行打折**之前**是多少、打完是多少。
   `before` 不是"再算一遍单价×数量"：生产库里存在 `line_total ≠ 单价×数量` 的历史行，
   取消折扣 / 换一种折扣时要**精确还原我们改之前那个数**（`services/order_discount.py`）；
   `after` 让详情页不用自己反推"这一行当时便宜了多少"。空/NULL = 这一单没打过折
   （正常路径下**总是写全**参与行的 id；空值只在老数据或空单上出现）。
4. **不加索引**：折扣只在看**单张订单**时被读（详情 / 出参），从来不参与筛选
   （同 009 第 2 条、023 那条理由）。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 25
NAME = "order_discount"
DESCRIPTION = (
    "orders 加七列折扣快照（kind / value / discount_amount / 参与行 / 理由 / 操作人 / 时刻），"
    "products 加 no_discount（不参与打折）。⛔ 可空、无默认值、不回填老数据、不建索引"
)

#: 表 → 要补的列（列名, DDL 类型）。逐列判存在、逐列执行：MySQL 的 DDL 隐式提交，
#: 一条迁移可能"改了一半"才失败，下次重跑必须能接着往下走（README 硬要求 2）。
COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "orders": (
        ("discount_kind", "VARCHAR(16)"),
        ("discount_value", "NUMERIC(14,4)"),
        ("discount_amount", "NUMERIC(14,4)"),
        # 参与折扣的行（JSON 数组：line_id / before / after）。老库上 SQLite 与 MySQL 都认 JSON 这个列类型。
        ("discount_lines", "JSON"),
        ("discount_reason", "VARCHAR(255)"),
        ("discount_by_id", "INTEGER"),
        ("discount_at", "DATETIME"),
    ),
    # 商品级「不参与打折」：语义只有一条 —— 算折扣时跳过它（⛔ 不是"价格不能变"）。
    # DEFAULT 0 = 老商品照旧参与打折，与模型里的 default=False 对齐（同 collect_cash 的写法）。
    "products": (("no_discount", "BOOLEAN DEFAULT 0"),),
}


def _columns(engine: Engine) -> dict[str, set[str]]:
    """每张表现有的列名；表不存在就不放进结果（全新库由 create_all 建，没什么可做的）。"""
    insp = inspect(engine)
    names = set(insp.get_table_names())
    return {t: {c["name"] for c in insp.get_columns(t)} for t in COLUMNS if t in names}


def upgrade(engine: Engine) -> None:
    have = _columns(engine)
    for table, cols in COLUMNS.items():
        present = have.get(table)
        if present is None:
            continue
        for name, ddl in cols:
            if name in present:
                continue
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
