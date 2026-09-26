# -*- coding: utf-8 -*-
"""中国传统单位换算 —— **第二个实现**（R4-04 的 Add 演练就是加这个文件）。

## 它是怎么"加"进来的（一个文件，别处一个字都没改）

本模块只做两件事：写一个满足 `UnitConversionContract v1` 的类；在模块级放 `PROVIDER`。
包里的 `_discover_providers()` 会扫到它 —— ⛔ 不需要改核心、不需要改 `manifest.py`、
不需要改 `api.py`、连包里的 `__init__.py` 都不用动。判据在 `_tools/ops/_r4_add_drill.py`：
**Core 修改数 = 0、既有扩展模块修改数 = 0**。

## 为什么它也认识 kg / m / l 这几个公制单位

因为用户真正要问的是「**一斤等于几公斤**」。一个只认识「斤」、不认识「kg」的实现，
面对这个问题只能回"不是我的活"，而那显然不是用户要的答案。
所以每个实现都要认识**自己那套单位 + 它要桥接过去的那几个**。

⚠️ 这带来一件必须处理的事：**两个实现会在重叠的那些对上都能回答**（例如 kg 到 g）。
于是谁先回答就取决于名字的字典序 —— 这不能靠"反正答案一样"糊过去。
所以契约用例里加了一条硬判据：**凡是有两个以上实现都支持的一对单位，
它们给出的答案必须逐位相同**（值、因子、量纲）。重叠因此从隐患变成不变量。

## 换算率（都是**定义值**，不是量出来的）

| 单位 | 量纲 | 相对基准 | 依据 |
| --- | --- | --- | --- |
| 钱 | 质量 | 5 克 | 1 两 = 10 钱 |
| 两 | 质量 | 50 克 | 1 斤 = 10 两 |
| 斤 | 质量 | 500 克 | 市制 1 斤 = 500 克（1959 年定） |
| 担 | 质量 | 50000 克 | 1 担 = 100 斤 |
| 里 | 长度 | 500 米 | 市制 1 里 = 500 米 |
| 升 | 体积 | 1 升 | 市制与公制同名同值 |
| 斗 | 体积 | 10 升 | 1 斗 = 10 升 |
| 石 | 体积 | 100 升 | 1 石 = 10 斗 |

⛔ **刻意不收「尺」与「寸」**：1 尺 = 1/3 米，十进制除不尽 —— 收进来会让
`1 尺 到 米 到 尺` 回不到 1（实测口径见契约用例的往返回归）。要收它们，
得先回答"保留几位、谁来定"，那是另一件事，不在本轮。
"""
from __future__ import annotations

from decimal import Decimal

from app.core.contracts.quantity import Quantity
from app.core.contracts.unit_conversion import (
    ConversionRequest,
    ConversionResult,
    UnitConversionError,
)

#: 单位名 -> (量纲, 相对本量纲基准的倍数)。基准与 SI 实现**同一套**：克 / 米 / 升。
CHINA_UNITS: dict[str, tuple[str, Decimal]] = {
    # 质量（市制）
    "钱": ("mass", Decimal("5")),
    "两": ("mass", Decimal("50")),
    "斤": ("mass", Decimal("500")),
    "担": ("mass", Decimal("50000")),
    # 长度（市制）
    "里": ("length", Decimal("500")),
    # 体积（市制）
    "升": ("volume", Decimal("1")),
    "斗": ("volume", Decimal("10")),
    "石": ("volume", Decimal("100")),
    # ---- 桥接用的公制单位：没有它们就答不了「一斤等于几公斤」 ----
    "g": ("mass", Decimal("1")),
    "kg": ("mass", Decimal("1000")),
    "m": ("length", Decimal("1")),
    "km": ("length", Decimal("1000")),
    "l": ("volume", Decimal("1")),
    "m3": ("volume", Decimal("1000")),
}

DIMENSION_NAMES = {"mass": "质量", "length": "长度", "volume": "体积"}


def _lookup(unit: str) -> tuple[str, str, Decimal] | None:
    key = (unit or "").strip().lower()
    hit = CHINA_UNITS.get(key)
    return (key, hit[0], hit[1]) if hit else None


class ChinaTraditionalUnitConversion:
    """市制单位的换算实现（`UnitConversionContract v1`）。"""

    name = "china_traditional"
    version = 1

    def units(self) -> dict[str, str]:
        """我认识哪些单位：单位名 -> 量纲。契约用例靠它自动跑遍每一个实现。"""
        return {name: dim for name, (dim, _factor) in CHINA_UNITS.items()}

    def supports(self, from_unit: str, to_unit: str) -> bool:
        """这两个单位归不归我管（⛔ 归我管 ≠ 这次换算合法，分工见契约里的说明）。"""
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
        scaled = value * a[2]
        exact = (scaled % b[2]) == 0
        return ConversionResult(
            quantity=Quantity(scaled / b[2], b[0], b[1]),
            factor=a[2] / b[2],
            exact=exact,
            source=self.name,
            note="按市制定义值换算（1 斤 = 500 克、1 两 = 10 钱、1 担 = 100 斤、1 里 = 500 米、1 石 = 10 斗）",
        )


#: ⛔ 这一行是**唯一**的登记方式：扫描器只认模块级的 PROVIDER。
PROVIDER = ChinaTraditionalUnitConversion()