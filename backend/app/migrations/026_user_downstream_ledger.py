"""026_user_downstream_ledger：给 users 加一列 downstream_ledger_enabled（CHG-0076 / 台账 L-39）。

### 为什么加它（用户 2026-10-07 原话，ref m01547）

> 「就是他在那个**我的**里面加一个**按钮**……因为有些批发商他可能**不想让我们去管他的账**，
>   所以我们就给一个功能，**开启**这个按钮：他那个我的账本就会显示**别人欠他的钱**……
>   如果**关闭**了的话，他就**没有这些功能**，他这个账本**只显示他欠我们的钱**。」

### 为什么是一列新列，而不是复用 is_member

`is_member` 是**身份**（批发商货主 / 普通货主）：只有派单员能改
（`api/v1/users.py:347-348`），工作台那个「批发商」徽章也靠它
（`_tools/qa/_check_workbench_member_badge.py:183`）。
本列是**他自己的偏好**（要不要管下游的账），只有他本人能改（`PATCH /users/me/downstream-ledger`）。
两者是"同一种角色的两种人"（`api/v1/shipper_ledger.py::_require_member` 的注释逐字写着
角色目录表达不了它）—— ⛔ 合成一列就会把身份与这本账一起关掉。

### 为什么走迁移而不是 schema_bootstrap

README 的分工：**正式变更**走本目录、**运行时自愈**走 `core/schema_bootstrap.py`。
加列是正式变更（老库要 ALTER、新库由 create_all 按模型建），所以是一条迁移 ——
与 `009_freight_rule_snapshot` / `024_product_visibility_targets` / `025_order_discount` 同一条理由。
⛔ 不两边都写：`core/schema_bootstrap.py` 里**没有**这一列，本次也不新开。

### 默认值为什么必须是 1（开）

`DEFAULT 1` ⇒ 老库上每一个账号保持今天的行为（批发商照样管下游的账）。
默认 0 会让上线那一刻所有批发商的下游账**突然消失** —— 同 024 那条"默认把功能关掉"的教训。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

VERSION = 26
NAME = "downstream_ledger"
DESCRIPTION = (
    "users 加 downstream_ledger_enabled（批发商自己决定要不要管下游的账）。"
    "NOT NULL DEFAULT 1 = 老库回填「开」，上线那一刻行为与今天完全一致"
)

TABLE = "users"
COLUMN = "downstream_ledger_enabled"


def upgrade(engine: Engine) -> None:
    """给已有库补这一列；全新库由 `create_all` 按模型建，这里什么都不做。"""
    insp = inspect(engine)
    if TABLE not in set(insp.get_table_names()):
        return
    # 可重跑：先判列在不在（MySQL 的 DDL 隐式提交，一条迁移可能改了一半才失败）
    if COLUMN in {c["name"] for c in insp.get_columns(TABLE)}:
        return
    with engine.begin() as conn:
        conn.execute(
            text(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} BOOLEAN NOT NULL DEFAULT 1")
        )
