"""金额入参的**统一上限**：超出数据库能存的范围，本地就该和生产一样被拒。

## 为什么必须拦（2026-09-18 模糊测试实测）
金额列是 `Numeric(12,2)` / `Numeric(14,4)`，能存的最大值是 **9,999,999,999.99**。
- 生产 MySQL：超了直接 `Out of range value`
- 本地 SQLite：**照单全收** —— `POST /driver-billing-rules {"salary": 1e20}` 真的返回 201，
  `POST /expenses {"amount": 1e20}` 返回 200，`POST /price-rules/batch {"value": 1e20}`
  更是一次把 2880 条专属价全改成天文数字。

于是"生产会炸的输入在本地全绿"——本地测试最没用的那种假安全感。
把上限写进 schema 之后，两边行为一致，而且用户拿到的是**中文 + 字段名**。

## 判据只有一处
`MONEY_RE` / `MONEY_MAX` / `RATE_MAX` 就是全部规则；静态审计脚本
`_tools/qa/_audit_money_fields.py` 直接 import 它们（不另抄一份正则，
否则两边会走散：这个项目已经栽过"清单手写"好几次）。
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, model_validator

#: 金额语义字段名
MONEY_RE = re.compile(
    r"(^|_)(price|amount|fee|salary|cost|total|freight|commission_amount|piece_amount|"
    r"value|balance|money|pay|payment|received|deposit|discount|unit_price|line_total)($|_)",
    re.IGNORECASE,
)
#: 比例语义字段名（百分数）——**这里刻意不判**：
#: "提成比例不能超过 100%" 是**业务规则**，判据在 `validate_rule_params` /
#: `driver_pay.override_problem` 里（返回 400 + 一句能照着改的中文）。
#: 本基类只管"能不能存进数据库"这条**平台**约束，抢业务规则的活会把
#: 已有的中文 400 变成 422 结构体（`test_driver_billing_api.py` 就是这么抓住的）。
RATE_FIELDS = ("commission_rate",)
#: 命中 MONEY_RE 但**不该由本基类判**的字段（判据在别处，见上）
NOT_MONEY = {
    "value_type", "value_kind", "commission_product_ids", "commission_base",
    "rate_type", "freight_template_id", "payment_method", "is_paid", "paid", "value_label",
    "commission_rate",
    # 逐单覆盖的两个值：范围判据在 `driver_pay.override_problem`（给的是能照着改的中文，
    # 而且要先能说清"这个司机没挂规则，填了不生效"）——这里不抢它的活。
    "driver_piece_amount", "driver_commission_rate",
}

#: `Numeric(12,2)` 与 `Numeric(14,4)` 都能存下的最大金额
MONEY_MAX = Decimal("9999999999.99")

MONEY_TIP = "金额超出可保存范围（最大 9999999999.99）：请检查是不是多打了几位"


class MoneyInput(BaseModel):
    """金额入参基类：把"存不进数据库的数"挡在业务逻辑之前。

    只认**标量**（`Decimal` / `int` / `float`）：列表字段（如
    `commission_product_ids`）走不进来，布尔也不当数字。
    比例类字段（`commission_rate`）不在管辖范围，见 `NOT_MONEY` 的说明。
    """

    @model_validator(mode="after")
    def _money_within_storable_range(self) -> "MoneyInput":
        for name in type(self).model_fields:
            if name.startswith("_") or name in NOT_MONEY:
                continue
            value: Any = getattr(self, name, None)
            if value is None or isinstance(value, bool):
                continue
            # 列表/字典/嵌套模型不在这里判（各自的字段会自己判）
            if not isinstance(value, (int, float, Decimal)):
                continue
            try:
                num = Decimal(str(value))
            except Exception:  # pragma: no cover - Decimal(str()) 对数字不会失败
                continue
            if MONEY_RE.search(name) and abs(num) > MONEY_MAX:
                raise ValueError(f"{name} {MONEY_TIP}")
        return self
