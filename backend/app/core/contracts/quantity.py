# -*- coding: utf-8 -*-
"""量的**核心表示**：Quantity / Unit / Dimension（R4-02 · UnitConversionContract v1 的 Core 侧）。

## 边界（指南 §8 原话）

> 核心只认识：Quantity / Unit / Dimension
> 具体：kg -> g、lb -> kg、斤 -> kg **由扩展提供**。

⛔ 所以这一页**故意一个单位都不认识**：核心不知道有几个 kg，也不知道 1 斤等于几克。
它只知道「一个量 = 一个数 + 一个单位 + 这个单位属于哪个量纲」。
单位名册与换算率全部在**扩展**侧（契约见 docs/R4_CONTRACTS.md §1）。

## 为什么必须带量纲

没有量纲，「把 8 车换算成 5 公斤」在类型上完全合法 —— 而它显然是错的。
量纲由**扩展**声明（mass / volume / length / count …），核心只做一件事：
⛔ 量纲不同的两个量**不许直接换算**（抛 QuantityError，而不是给一个看起来合理的数）。
这一点与 services/unit_conversion.py 既有的那条规矩同源：宁可拒绝，也不猜。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

#: 量纲未知时的取值。⛔ 它不是「随便什么都能换算」的意思，恰恰相反：
#: 两个 unknown 之间也**不许**自动换算 —— 那正是「10 车 ≈ 50 袋」这类静默错误的来源。
UNKNOWN_DIMENSION = "unknown"


class QuantityError(ValueError):
    """量这件事上说不通时抛的错（消息是一句能照着改的中文）。"""


@dataclass(frozen=True)
class Quantity:
    """一个量：**不可变**。数值 + 单位 + 量纲。

        Quantity(Decimal("10"), "车", "volume")
        Quantity(Decimal("80"), "方", "volume")   # 同一个量纲，才允许换算
        Quantity(Decimal("5"), "公斤", "mass")     # 与上面不同量纲 —— 换算会被拒
    """

    value: Decimal
    unit: str
    dimension: str = UNKNOWN_DIMENSION

    def __post_init__(self) -> None:
        try:
            value = Decimal(self.value)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise QuantityError("数量必须是数字：" + repr(self.value)) from exc
        unit = (self.unit or "").strip()
        if not unit:
            raise QuantityError("数量必须带单位（空单位会让「10」变成没有意义的数）")
        dimension = (self.dimension or UNKNOWN_DIMENSION).strip()
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "dimension", dimension)

    def same_dimension(self, other: "Quantity") -> bool:
        """两个量能不能换算：量纲相同，且**都不是 unknown**。"""
        return (self.dimension == other.dimension
                and self.dimension != UNKNOWN_DIMENSION
                and other.dimension != UNKNOWN_DIMENSION)

    def with_value(self, value: object, unit: str | None = None) -> "Quantity":
        """换一个数值（/单位）造一个新的量 —— ⛔ 不许就地改（frozen）。"""
        return Quantity(Decimal(str(value)), unit or self.unit, self.dimension)

    def as_text(self) -> str:
        text = format(self.value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return (text or "0") + " " + self.unit
