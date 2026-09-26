# -*- coding: utf-8 -*-
"""UnitConversionContract v1 —— 单位换算的**扩展契约**（R4-02）。

六个要素（输入 / 输出 / 错误 / 不变量 / 兼容要求 / 生命周期）逐条写在 docs/R4_CONTRACTS.md §1；
这一页是它的**代码形态**，也是扩展必须满足的那份接口。

## ⛔ 这一页一行实现都没有

它不查库、不查表、**不认识任何一种单位**（核心侧的量只有 Quantity / Unit / Dimension，见 quantity.py）。
具体「1 车 = 8 方」由扩展提供 —— 第一个实现见
backend/app/extensions/unit_conversion/（R4-04）。

## 为什么 convert 可以返回 None（这是"多实现"的关键）

一个实现**只负责自己认识的那些单位**。认不出来时它返回 None，由注册表去问下一个实现 ——
⛔ 而不是抛错（"不是我的活"与"这个换算不合法"是两件事，混在一起就没法多实现并存了）。
真的**不合法**（同单位、空单位、量纲冲突）才抛 UnitConversionError。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from app.core.contracts.quantity import Quantity

#: 契约名与版本。判据 _check_extension_contracts.py 核对它们与文档一致。
CONTRACT_NAME = "UnitConversionContract"
CONTRACT_VERSION = 1


class UnitConversionError(ValueError):
    """这次换算**不合法**（不是"这个实现不认识"）。消息是一句能照着改的中文。"""


@dataclass(frozen=True)
class ConversionRequest:
    """输入：一个数值 + 从哪个单位 + 到哪个单位。

    ⛔ 刻意不带 Session / db / 用户 —— 换算是**纯函数**：同样的输入必须给同样的输出，
    否则"同一批货两个数"就没人能复核了（这是本契约最重要的一条输入约束）。
    """

    value: Decimal
    from_unit: str
    to_unit: str


@dataclass(frozen=True)
class ConversionResult:
    """输出：一个**核心的** Quantity + 这次换算的依据。

    ⛔ 输出的量必须是 Quantity（核心类型），不许是实现自己的对象 —— 指南 §20 的同一句话。
    """

    quantity: Quantity
    factor: Decimal
    #: 结果是不是**精确**的（发生过四舍五入就是 False）—— 界面要能说出"约"这个字。
    exact: bool
    #: 哪个实现算的。⛔ 给人看的理由，**核心不许拿它做分支**（那就等于核心认识了具体实现）。
    source: str
    note: str = ""


@runtime_checkable
class UnitConversionContract(Protocol):
    """单位换算扩展的接口（v1）。

    ⛔ 这里**没有** initialize / execute / shutdown —— 指南 §7 明确否掉了"万能插件基类"：
    单位换算、定价、导出、通知根本不是同一种能力，塞进同一个接口只会把复杂度藏起来。
    """

    #: 实现自己的短名（排障用）。⛔ 核心不认识任何具体取值。
    name: str
    #: 实现自己按哪个契约版本写的。
    version: int

    def supports(self, from_unit: str, to_unit: str) -> bool:
        """我认不认识这一对单位。认不认识 ≠ 合不合法。"""
        ...

    def convert(self, request: ConversionRequest) -> ConversionResult | None:
        """换算；**不是我的活就返回 None**，不合法才抛 UnitConversionError。"""
        ...
