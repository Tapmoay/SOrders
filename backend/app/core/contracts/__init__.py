# -*- coding: utf-8 -*-
"""扩展契约的**核心侧**（R4-02）。

## 这一包是什么

指南 §7 明确否掉了「一个万能插件接口」：

> 千万不要设计一个万能插件接口（Plugin.initialize / execute / shutdown），
> 然后所有东西都往里面塞。UnitConversion / Pricing / AI Provider / Excel Exporter / Notification
> 这些东西根本不是同一种能力。

所以这里是**多种稳定扩展契约**，一种能力一个模块、一个版本：

| 模块 | 契约 | 版本 | 核心侧提供 | 扩展侧提供 |
| --- | --- | --- | --- | --- |
| money.py | （核心类型，不是扩展点） | - | Money / Currency / Rounding | - |
| quantity.py | （核心类型，不是扩展点） | - | Quantity / Unit / Dimension | - |
| unit_conversion.py | UnitConversionContract | v1 | 输入 / 输出 / 错误 / 不变量 | 具体换算（kg->g、斤->kg …） |
| pricing.py | PricingContract | v1 | Money / PricingContext / 错误 | PricingAlgorithm |

## 依赖方向（指南 §13，⛔ 单向）

    Core Contract  <-  Extension Implementation  <-  Infrastructure Adapter

    Core -> PricingContract        ✅
    Pricing -> MoneyCore           ✅
    Core -> ColdChainPricing       ❌（核心不许认识具体实现）

判据见 _tools/qa/_check_extension_contracts.py 与 _check_extension_dependencies.py。

## 怎么加一个新扩展（顺序不许颠倒，指南 §43）

1. 先在**这一包**里加契约（六个要素写进 docs/R4_CONTRACTS.md）；
2. 再写第一个实现，并让**同一组契约用例**跑它；
3. 出现第二个实现之后，才谈版本兼容（指南 §18：先证明会被多个实现用，再设计兼容）。

## ⛔ 这一包不许 import 具体扩展

它只能 import 标准库与同包内的模块。判据会在 AST 层面核对。
"""