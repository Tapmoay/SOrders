# -*- coding: utf-8 -*-
"""单位换算扩展（Unit Conversion）—— R4 的**第一个真实扩展**。

## 它要证明什么（指南 §19 原话）

> 先做：Unit / Dimension / Quantity / ConversionContract
> 然后实现：SI。再增加：Imperial。然后：China-traditional。
> 整个过程中：**Core 不应该为了新增一种单位而不断修改。这就是第一次真实证明。**

## 它怎么做到"加一种单位只加一个文件"

本包里的每一个实现模块只做两件事：

1. 写一个满足 `UnitConversionContract v1` 的类；
2. 在模块级放一个 `PROVIDER = 那个类的实例`。

`PROVIDERS` 是**扫出来的**（见 `_discover_providers`）—— 所以新增一种单位体系 =
**新增一个文件**，⛔ 既不用改核心、也不用改本包的任何既有模块（连这一份 `__init__.py` 都不用动）。
这就是 R4-04 的 Add 演练要证明的那句话；判据在 `_tools/ops/_r4_add_drill.py`。

## 边界（⛔ 不许越界，三个判据盯着）

* 只 import `app.core.contracts.*`（判据 `_check_extension_dependencies.py` 第 2 组）；
* 不许写任何表（判据 `_check_data_ownership.py` 第 3 组）；
* 不许自己写鉴权 —— 路由的能力点由**核心**装配时施加（判据同文件第 3 组）。

## 与既有 `services/unit_conversion.py` 的关系（必须说清，免得读成"重复实现"）

那一份是**用户自己填的换算率**（`1 车 = 8 方`，存在 `unit_conversions` 表里，带四条校验规则），
本轮**一个字节都没动**。这一包是**量纲感知的内建单位换算**（kg/g/t、m/km、L/m3 …），
两者是同一个契约 `UnitConversionContract v1` 的不同实现方向：
前者由用户声明、后者由物理常数给出。⛔ 谁也没抄谁。
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from app.core.contracts.unit_conversion import UnitConversionContract

#: 这两个模块里**没有** PROVIDER（一个是清单，一个是路由），扫描时要跳过。
_NOT_IMPLEMENTATIONS = ("manifest", "api")


def _discover_providers() -> tuple[UnitConversionContract, ...]:
    """扫本包，把每个实现模块里的 `PROVIDER` 收集起来。

    ⚠️ 这与核心注册表的 `discover()` 是同一个形状（**部署期**扫包）：
    实现是仓库里的代码、随发布一起上去，⛔ 没有上传、没有文件监听、没有 exec/eval。
    按 `name` 排序是为了让"谁先回答"这件事是**确定的**，而不是取决于文件系统顺序。
    """
    found: list[UnitConversionContract] = []
    for info in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if info.name.startswith("_") or info.name in _NOT_IMPLEMENTATIONS:
            continue
        module = importlib.import_module(__name__ + "." + info.name)
        provider = getattr(module, "PROVIDER", None)
        if provider is None:
            continue
        if not isinstance(provider, UnitConversionContract):
            raise TypeError(
                module.__name__ + " 里的 PROVIDER 不满足 UnitConversionContract v1：" + repr(type(provider))
            )
        found.append(provider)
    return tuple(sorted(found, key=lambda p: p.name))


#: 当前所有实现。**按 name 排序**，所以"谁先回答"是确定的。
PROVIDERS: tuple[UnitConversionContract, ...] = _discover_providers()


def resolve(from_unit: str, to_unit: str) -> UnitConversionContract | None:
    """挑一个认得这对单位的实现（认不出来返回 None）。

    ⛔ 这里**不猜**：一个都认不出来就是 None，由调用方决定怎么说（本项目的一贯口径）。
    """
    for provider in PROVIDERS:
        if provider.supports(from_unit, to_unit):
            return provider
    return None
