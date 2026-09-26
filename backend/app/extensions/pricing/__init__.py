# -*- coding: utf-8 -*-
"""算价扩展（Pricing）—— R4 的**第二个真实扩展**，也是第一个 Policy 型扩展。

## 它要证明什么（指南 §20 / §38）

> 核心只接受 **Money**，不能接受某个插件自己的对象。
> 验证：Order -> PricingContext -> PricingContract -> Money Core 能够成立。
> 然后替换两种 Pricing implementation。验证：**Core 不动**。

## 与单位换算扩展同一套形状（这不是巧合）

每个实现模块：写一个满足 PricingContract v1 的类 + 模块级放一个 PROVIDER。
PROVIDERS 是**扫出来的** —— 所以"换一种计价方式"等于加一个文件，
核心、清单、路由、连这一份 __init__.py 都不用动。

## 这条扩展碰不到钱的事实（指南 §14 / §31 坑 5）

它只能 calculate 出一个 Money，**最终事实交给核心事务**：
这一包里一条写语句都没有、也 import 不到任何表（判据 _check_data_ownership.py 第 3/4 组）。

## "替换"是怎么发生的（R4-05 的 Replace 演练）

**不是改代码，是换数据**：每一单在派单那一刻把规则定格进 orders.driver_rule_snapshot，
其中 pricing_kind 决定谁认领它。把 pricing_kind 从一个值换成另一个值 ——
核心 0 行、扩展 0 行，而这一单的算法变了。判据在 _tools/ops/_r4_replace_drill.py。
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from app.core.contracts.pricing import (
    AmbiguousPricingRule,
    NoPricingRule,
    PricingContract,
    PricingContext,
    PricingContractV2,
    as_v2,
)

_NOT_IMPLEMENTATIONS = ("manifest", "api")


def _discover_providers() -> tuple[PricingContract, ...]:
    """扫本包，把每个实现模块里的 PROVIDER 收集起来（**部署期**扫包，与核心注册表同形）。"""
    found: list[PricingContract] = []
    for info in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if info.name.startswith("_") or info.name in _NOT_IMPLEMENTATIONS:
            continue
        module = importlib.import_module(__name__ + "." + info.name)
        provider = getattr(module, "PROVIDER", None)
        if provider is None:
            continue
        if not isinstance(provider, PricingContract):
            raise TypeError(
                module.__name__ + " 里的 PROVIDER 不满足 PricingContract v1：" + repr(type(provider))
            )
        found.append(provider)
    return tuple(sorted(found, key=lambda p: p.name))


PROVIDERS: tuple[PricingContract, ...] = _discover_providers()


def resolve_v2(context: PricingContext) -> PricingContractV2:
    """v2 视角的 resolve：v2 实现原样返回，**v1 实现经适配器包一层**（指南 §17）。

    ⚠️ 实测（R4-07）：这一条**必须在这里、不能进适配器** —— 适配器只该认识契约，
    不该认识"我们包里有哪些实现"；而"从上下文挑一个实现"是**这个扩展包**的事。
    ⛔ 加它的时候要注意：v1 实现**一个字节都不用改**，旧消费方照常调 resolve()。
    """
    return as_v2(resolve(context))


def resolve(context: PricingContext) -> PricingContract:
    """挑出认领这一单的那一条规则。

    一条都没有 -> NoPricingRule（本项目既有口径：「没匹配到就没有定价，由派单员手动定价」）；
    两条以上认领 -> AmbiguousPricingRule 并带上候选 —— **不猜**（指南一贯口径）。
    """
    hits = [p for p in PROVIDERS if p.applies_to(context)]
    if not hits:
        kind = context.rule_snapshot.get("pricing_kind")
        tail = ("（规则快照里的 pricing_kind=" + repr(kind) + " 没有对应实现）" if kind
                else "（规则快照里没写按哪条规则算）")
        raise NoPricingRule("没有一条计费规则管这一单" + tail + " —— 请派单员手动定价")
    if len(hits) > 1:
        raise AmbiguousPricingRule(
            "同一单被 " + str(len(hits)) + " 条规则同时认领 —— 不猜，请只留一条",
            tuple(p.name for p in hits),
        )
    return hits[0]