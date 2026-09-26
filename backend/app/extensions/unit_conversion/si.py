# -*- coding: utf-8 -*-
"""SI 单位换算 —— **第一个实现**（指南 §19 的"然后实现 SI"）。

它只认**国际单位制**里那几个常用单位，量纲分三类：质量 / 长度 / 体积。
每个单位给一个"相对本量纲基准单位的倍数"（质量→克、长度→米、体积→升），
换算就是两次乘除 —— 没有查表、没有数据库、没有状态。

## 三条不许（与 `services/unit_conversion.py` 那四条规则同源，但这里是契约层）

1. **量纲不同的两个量不许换算** —— 抛中文错，⛔ 不是给一个看起来合理的数；
2. **源单位与目标单位相同不许换算** —— 那行会显示成一条"正常"的换算（既有实现里已经栽过）；
3. **认不出来的单位一律返回 None** —— "不是我的活"与"不合法"是两件事，混在一起就没法多实现并存。
"""
from __future__ import annotations

from decimal import Decimal

from app.core.contracts.quantity import Quantity
from app.core.contracts.unit_conversion import (
    ConversionRequest,
    ConversionResult,
    UnitConversionError,
)

#: 单位名（一律小写）-> (量纲, 相对本量纲基准单位的倍数)。
#: 基准：mass=克 / length=米 / volume=升。
SI_UNITS: dict[str, tuple[str, Decimal]] = {
    # 质量
    "mg": ("mass", Decimal("0.001")),
    "g": ("mass", Decimal("1")),
    "kg": ("mass", Decimal("1000")),
    "t": ("mass", Decimal("1000000")),
    # 长度
    "mm": ("length", Decimal("0.001")),
    "cm": ("length", Decimal("0.01")),
    "m": ("length", Decimal("1")),
    "km": ("length", Decimal("1000")),
    # 体积
    "ml": ("volume", Decimal("0.001")),
    "l": ("volume", Decimal("1")),
    "m3": ("volume", Decimal("1000")),
}

#: 量纲的中文名（给用户看的错里必须说人话）。
DIMENSION_NAMES = {"mass": "质量", "length": "长度", "volume": "体积"}


def _lookup(unit: str) -> tuple[str, str, Decimal] | None:
    """单位 -> (小写规范名, 量纲, 倍数)；不认识返回 None。"""
    key = (unit or "").strip().lower()
    hit = SI_UNITS.get(key)
    return (key, hit[0], hit[1]) if hit else None


class SiUnitConversion:
    """国际单位制的换算实现（`UnitConversionContract v1`）。"""

    name = "si"
    version = 1

    def units(self) -> dict[str, str]:
        """我认识哪些单位：单位名 -> 量纲。契约用例靠它自动跑遍每一个实现。"""
        return {name: dim for name, (dim, _factor) in SI_UNITS.items()}

    def supports(self, from_unit: str, to_unit: str) -> bool:
        """这两个单位归不归我管。

        ⛔ 「归我管」≠「这次换算合法」：量纲冲突与同单位都由 convert 抛中文错，
        只有**认不出单位**（那是"不是我的活"）才返回 False / None。
        这条分工是 R4-04 实测定下来的：第一版把量纲冲突也算成"不支持"，
        结果用户问「cm 到 g」时拿到的是「没有实现认得这对单位」——
        而真正该说的是「一个是长度、一个是质量，不能换算」。
        """
        return _lookup(from_unit) is not None and _lookup(to_unit) is not None


    def convert(self, request: ConversionRequest) -> ConversionResult | None:
        a = _lookup(request.from_unit)
        b = _lookup(request.to_unit)
        if a is None or b is None:
            return None                      # 不是我的活
        if a[1] != b[1]:
            raise UnitConversionError(
                "「" + request.from_unit + "」是" + DIMENSION_NAMES.get(a[1], a[1])
                + "，「" + request.to_unit + "」是" + DIMENSION_NAMES.get(b[1], b[1])
                + " —— 不同量纲不能换算，请换成同一类的单位"
            )
        if a[0] == b[0]:
            raise UnitConversionError(
                "源单位与目标单位相同（都是「" + a[0] + "」）—— 没有可换算的东西"
            )
        value = Decimal(request.value)
        scaled = value * a[2]                 # 先化成基准单位
        exact = (scaled % b[2]) == 0          # 除得尽才算精确
        return ConversionResult(
            quantity=Quantity(scaled / b[2], b[0], b[1]),
            factor=a[2] / b[2],
            exact=exact,
            source=self.name,
            note="按国际单位制换算（基准：质量=克 / 长度=米 / 体积=升）",
        )


#: ⛔ 这一行是**唯一**的登记方式：扫描器只认模块级的 PROVIDER（见包头的说明）。
PROVIDER = SiUnitConversion()