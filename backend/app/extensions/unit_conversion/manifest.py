# -*- coding: utf-8 -*-
"""单位换算扩展的清单（R4-03 的 Manifest 契约）。

字段含义逐条写在 `docs/R4_EXTENSIONS.md` §1；这里只解释**取值为什么是这些**：

* `kind="pure-function"` —— 它是纯函数式扩展（指南 §8：输入明确、输出明确、无副作用、不碰库）；
* `provides=("unit.convert",)` —— 它提供的**能力名**，与边界图里 `unit.conversion` 那一条对应；
* `requires=("quantity.core",)` —— 它依赖的核心契约是"量"（Quantity / Unit / Dimension）；
* `compatibility="UnitConversionContract v1"` —— 它按哪个契约的哪个版本写的；
* `config=("UNIT_SYSTEM",)` —— 唯一一个配置键（环境变量 `EXT_UNIT_CONVERSION_UNIT_SYSTEM`），
  目前**没有任何代码读它**：它是"配置要经注册表"这条规矩的活样本，不是摆设（R4-06 的 orphan config
  核查会拿它做对象）；
* `owns_tables=()` —— ⛔ 它**不拥有任何表**：换算是纯计算，一个字节都不落库；
* `routes="api"` + `capability="ORDER_CREATE"` —— 按指南 §27：扩展声明路由与能力点，
  **核心**在装配时施加 `require_permission`。选 `ORDER_CREATE` 的理由：试算换算出现在下单页，
  能下单的人就该能试算 —— 与既有 `POST /api/v1/unit-conversions` 的 shipper+dispatcher 口径一致。
"""
from __future__ import annotations

from app.core.extension_registry import ExtensionManifest

MANIFEST = ExtensionManifest(
    id="unit_conversion",
    version=1,
    kind="pure-function",
    provides=("unit.convert",),
    requires=("quantity.core",),
    consumes=(),
    emits=(),
    config=("UNIT_SYSTEM",),
    compatibility="UnitConversionContract v1",
    owns_tables=(),
    routes="api",
    capability="ORDER_CREATE",
    why="量纲感知的内建单位换算：把 kg/g/t、m/km、L/m3 之间的换算收成一条纯函数契约，新增一种单位体系只加一个文件",
)