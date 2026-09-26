# -*- coding: utf-8 -*-
"""PricingContract v1 —— 算钱的**扩展契约**（R4-02）。

六个要素逐条写在 docs/R4_CONTRACTS.md §2；这一页是它的**代码形态**。

## 一句话（指南 §20）

    Order -> PricingContext -> PricingContract -> Money -> Core Settlement / Ledger

> 核心只接受 **Money**，不能接受某个插件自己的对象。

## ⛔ 三条不许（每一条都对应一个真实事故的形状）

1. **⛔ 扩展不许写账本。** 它只能 calculate -> Money，最终事实交给核心事务
   （指南 §14 / §31 坑 5：「calculate -> UPDATE ledger」是最高危的一类）。
2. **⛔ 核心不许认识具体实现。** 核心侧只 import 本模块；
   `Core -> PricingContract` 可以，`Core -> ColdChainPricing` 不行（指南 §13）。
3. **⛔ 匹配到多条时不许猜。** 抛 AmbiguousPricingRule 带候选清单，让派单员自己挑 ——
   这与 services/freight_pricing.py 既有的「同一档里多于一条 = 不猜」是**同一条规矩**，
   只是从"一处实现"提升成了"契约要求每个实现都遵守"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable

from app.core.contracts.money import Money
from app.core.contracts.quantity import Quantity

#: 契约名与版本。判据 _check_extension_contracts.py 核对它们与文档一致。
CONTRACT_NAME = "PricingContract"
CONTRACT_VERSION = 1


class PricingError(ValueError):
    """算价这件事上说不通时抛的错（消息是一句能照着改的中文）。"""


class NoPricingRule(PricingError):
    """一条都匹配不上。

    这不是异常情况 —— 项目的既有口径是「**没匹配到就没有定价**，由派单员手动定价」
    （用户 2026-09-21 原话）。所以它是个**有名字的结果**，不是一个"系统错误"。
    """


class AmbiguousPricingRule(PricingError):
    """同一档里匹配到多条 —— **不猜**，把候选交出去让人挑。

    这正是本项目最恨的那类静默错误（"默默取到另一条"），所以它在契约层面就被禁止。
    """

    def __init__(self, message: str, candidates: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.candidates = candidates


@dataclass(frozen=True)
class PricingContext:
    """扩展算价时**能看到**的全部东西 —— 就这些，多一样都不给。

    ⛔ 这里没有 Session / db / 用户身份：拿得到 db 就能改写事实，
    而"扩展不许写核心表"这条边界靠"根本不给它写的能力"来守，比靠判据守更硬。
    """

    order_id: int | None = None
    order_no: str = ""
    #: 货类（运费分类名）。空 = 这一单没有被分类。
    category: str = ""
    from_place: str = ""
    to_place: str = ""
    #: 数量（带单位与量纲）。它不是 Money，所以合法地跨得进扩展。
    quantity: Quantity | None = None
    #: 商品单价（商品单才有）。
    unit_price: Decimal | None = None
    driver_id: int | None = None
    vehicle_type: str | None = None
    #: 派单时**定格**进订单的规则快照（历史可解释的那一份，指南 §25 C 类数据）。
    rule_snapshot: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 快照必须是**只读**的：扩展算价时顺手改快照，就等于改历史。
        object.__setattr__(self, "rule_snapshot", MappingProxyType(dict(self.rule_snapshot or {})))


@dataclass(frozen=True)
class PricingResult:
    """输出：**核心的 Money** + 这次算价的依据。

    rule_name / detail 是给人和审计看的：账单要能**独立复核**"按什么算的"
    （这与 driver_bills 另存 rule_id / rule_name / piece_amount 是同一条口径）。
    """

    money: Money
    rule_name: str
    detail: str = ""
    #: 只在"有歧义"时非空（配套 AmbiguousPricingRule）。
    candidates: tuple[str, ...] = ()


@runtime_checkable
class PricingContract(Protocol):
    """算钱扩展的接口（v1）。

    ⛔ 同样**没有** initialize / execute / shutdown —— 指南 §7 否掉了万能插件基类。
    """

    name: str
    version: int

    def price(self, context: PricingContext) -> PricingResult:
        """按上下文算出这一单该收多少。

        匹配不到 -> NoPricingRule；同一档多条 -> AmbiguousPricingRule（带候选）。
        ⛔ 不许返回 None、不许返回裸 Decimal、不许返回自定义对象 —— 只许 PricingResult。
        """
        ...
