# -*- coding: utf-8 -*-
"""PricingContract v1 的**共享契约用例** + 指南 §20 那条链的验证。

## 这一份证明两件事

1. **每一个实现都守契约**（与单位换算那份同形：遍历 PROVIDERS，用例不认识任何具体实现）；
2. **Order -> PricingContext -> PricingContract -> Money 这条链真的成立** ——
   链路左边两格由核心的 `core/pricing_context.py::context_of` 负责，
   右边必须是**核心的 Money**（指南 §20：核心只接受 Money）。

## 以及 R4-05 的 Replace 演练在同一份用例里

"替换一种计价方式"**不是改代码，是换数据**：同一张订单，只把规则快照里的 `pricing_kind`
换成另一个值，算法就换了 —— 而核心与扩展的代码一个字节都没动。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.contracts.money import Money
from app.core.contracts.quantity import Quantity
from app.core.contracts.pricing import (
    CONTRACT_VERSION,
    PricingContractV2,
    as_v2,
    AmbiguousPricingRule,
    NoPricingRule,
    PricingContext,
    PricingContract,
    PricingResult,
)
from app.core.pricing_context import context_of, driver_rule_of
from app.extensions.pricing import PROVIDERS, resolve
from app.models.order import Order


def order_fixture() -> Order:
    """一张**未落库**的订单（本用例不需要数据库：链路证的是映射与契约，不是持久化）。"""
    return Order(
        order_no="SO-RV-0001",
        driver_id=7,
        freight_category="建材",
        address_detail="测试路 1 号",
        freight_fee=Decimal("88.00"),
    )


def test_there_is_at_least_one_provider() -> None:
    """空名单会让下面每个参数化用例**静默不跑** —— 那正是"永远绿的检查"。"""
    assert PROVIDERS, "一条计价规则都没有：契约用例会变成空转"
    names = [p.name for p in PROVIDERS]
    assert len(names) == len(set(names)), "实现名重复：" + str(names)


@pytest.mark.parametrize("provider", PROVIDERS, ids=[p.name for p in PROVIDERS])
class TestEveryImplementation:
    """同一组用例，**每一个实现**都跑一遍。"""

    def test_satisfies_the_contract(self, provider: PricingContract) -> None:
        assert isinstance(provider, PricingContract)
        assert provider.name and isinstance(provider.name, str)
        assert provider.version == CONTRACT_VERSION

    def test_it_does_not_claim_other_peoples_orders(self, provider: PricingContract) -> None:
        """⛔ 快照里没写按哪条规则算时，谁都不许认领（那正是"等派单员手动定价"）。"""
        assert provider.applies_to(PricingContext()) is False
        assert provider.applies_to(PricingContext(rule_snapshot={"pricing_kind": "RULE-NOT-EXIST"})) is False

    def test_missing_input_is_not_the_same_as_not_my_rule(self, provider: PricingContract) -> None:
        """⭐ 契约分工：归我管但缺料 -> applies_to True、price 抛 NoPricingRule。"""
        kind = getattr(provider, "kind", None)
        if not kind:
            pytest.skip("这个实现没有自报 kind，跳过（选择依据由它自己决定）")
        ctx = PricingContext(rule_snapshot={"pricing_kind": kind})
        assert provider.applies_to(ctx) is True, "快照点名要它，就该承认归自己管"
        with pytest.raises(NoPricingRule) as exc:
            provider.price(ctx)
        assert str(exc.value), "缺料时必须给一句能照着改的中文"


def test_chain_order_to_pricing_to_money() -> None:
    """⭐ 指南 §20 的那条链：Order -> PricingContext -> PricingContract -> Money。

    ⛔ 右边必须是**核心的 Money**（"核心只接受 Money，不能接受某个插件自己的对象"）。
    """
    order = order_fixture()
    context = context_of(order, rule_snapshot={"pricing_kind": "standard", "amount": "120.00"})
    assert isinstance(context, PricingContext)
    assert context.order_no == order.order_no
    assert context.category == order.freight_category
    assert context.driver_id == order.driver_id
    assert context.to_place == order.address_detail
    provider = resolve(context)
    result = provider.price(context)
    assert isinstance(result, PricingResult)
    assert isinstance(result.money, Money), "核心只接受 Money —— 这是 §20 那一句的机器形态"
    assert result.money.amount == Decimal("120.00")
    assert result.rule_name and result.detail, "账单要能独立复核按什么算的"


def test_no_rule_matching_says_so_in_chinese() -> None:
    """没匹配到 = **一个有名有姓的结果**，不是系统错误（既有口径：派单员手动定价）。"""
    context = context_of(order_fixture())          # 快照为空
    with pytest.raises(NoPricingRule) as exc:
        resolve(context)
    assert "手动定价" in str(exc.value)


def test_two_rules_claiming_one_order_refuses_to_guess() -> None:
    """⛔ 同一单被两条规则认领 -> 不猜，抛 AmbiguousPricingRule 并带上候选。"""

    class Also:
        name, version, kind = "rv-also", 1, "standard"     # 与 standard 抢同一单

        def applies_to(self, context: PricingContext) -> bool:
            return True

        def price(self, context: PricingContext) -> PricingResult:
            return PricingResult(money=Money("1"), rule_name="rv")

    import app.extensions.pricing as pkg

    original = pkg.PROVIDERS
    try:
        pkg.PROVIDERS = tuple([*original, Also()])
        context = PricingContext(rule_snapshot={"pricing_kind": "standard", "amount": "1.00"})
        with pytest.raises(AmbiguousPricingRule) as exc:
            pkg.resolve(context)
        assert "不猜" in str(exc.value)
        assert set(exc.value.candidates) >= {"standard", "rv-also"}
    finally:
        pkg.PROVIDERS = original


def test_replace_is_a_data_change_not_a_code_change() -> None:
    """⭐ R4-05 的 Replace 演练：同一张订单，**只换数据**，算法就换了。

    这里证明的是"契约允许这件事"；"代码一行没改"由 _tools/ops/_r4_replace_drill.py 用 git diff 证明。
    两个实现对同一张订单给出**不同的、但都合法**的结果 —— 这就是"可替换"。
    """
    order = order_fixture()
    seen: dict[str, str] = {}
    for provider in PROVIDERS:
        kind = getattr(provider, "kind", None)
        if not kind:
            continue
        # ⚠️ 两种算法的结果**必须不同**：一样的话就分不出替换有没有生效（实测踩过）。
        #     统一价 120.00 元 vs 按量 8.50 × 15 件 = 127.50 元。
        snapshot: dict[str, object] = {"pricing_kind": kind, "unit_price": "8.50"}
        snapshot["amount"] = "120.00"
        context = context_of(order, rule_snapshot=snapshot)
        context = PricingContext(
            order_id=context.order_id, order_no=context.order_no, category=context.category,
            to_place=context.to_place, driver_id=context.driver_id,
            unit_price=Decimal("8.50"),
            quantity=Quantity(Decimal("15"), "件", "count"),
            rule_snapshot=snapshot,
        )
        try:
            result = resolve(context).price(context)
        except NoPricingRule:
            continue
        assert isinstance(result.money, Money)
        seen[kind] = result.money.as_text()
    assert seen, "没有任何一条规则算得出这一单 —— 这条用例在空转"
    assert len(set(seen.values())) == len(seen), (
        "不同的计价方式给了**完全相同**的数，那就分不出替换有没有生效：" + str(seen)
    )



# ---------------------------------------------------------------- v2（R4-07 兼容性）

def test_v2_is_a_superset_of_v1() -> None:
    """⚠️ v2 **不是另一个协议世界**：满足 v2 的实现必须同时满足 v1 ——
    "旧消费方照常工作"这条就是这么来的，不需要为它写第二套调用代码。"""
    for provider in PROVIDERS:
        v2 = as_v2(provider)
        assert isinstance(v2, PricingContractV2)
        assert isinstance(v2, PricingContract), "v2 实现也必须还是 v1 —— 否则旧消费方要改代码"
        assert v2.name == provider.name and v2.version == provider.version


def test_v1_implementations_still_work_through_the_adapter() -> None:
    """指南 §17：**旧实现还能工作**。每个实现都要能经适配器拿到明细。"""
    for provider in PROVIDERS:
        kind = getattr(provider, "kind", None)
        if not kind:
            continue
        ctx = PricingContext(rule_snapshot={"pricing_kind": kind, "amount": "120.00",
                                            "unit_price": "8.50",
                                            "base_price": "8.00", "base_qty": "10",
                                            "over_price": "9.00"},
                             unit_price=Decimal("8.50"),
                             quantity=Quantity(Decimal("15"), "件", "count"))
        v2 = as_v2(provider)
        result = v2.price(ctx)
        lines = v2.breakdown(ctx)
        assert lines, provider.name + " 经适配器后一行明细都给不出"
        assert all(isinstance(ln.money, Money) for ln in lines), "明细里的金额也必须是核心 Money"
        total = lines[0].money
        for ln in lines[1:]:
            total = total + ln.money
        assert total.amount == result.money.amount, (
            provider.name + " 的明细加起来不等于总额：" + total.as_text() + " vs " + result.money.as_text()
        )


def test_breakdown_is_synthesized_and_says_so() -> None:
    """v1 实现给不出真明细，适配器**合成**一行 —— 它如实标着 synthesized_breakdown，
    ⛔ 不许假装那是原生的多行明细（那会让界面以为"这一单只有一项"）。"""
    for provider in PROVIDERS:
        v2 = as_v2(provider)
        if isinstance(provider, PricingContractV2) and "breakdown" in type(provider).__dict__:
            continue                       # 原生 v2 实现，不适用
        assert getattr(v2, "synthesized_breakdown", False) is True, (
            provider.name + " 经适配器包了一层，却没说这行明细是合成的"
        )


def test_resolve_v2_works_for_every_implementation() -> None:
    """`resolve_v2` 把"挑实现"与"用 v2 视角看它"两件事接起来。"""
    from app.extensions.pricing import resolve_v2

    for provider in PROVIDERS:
        kind = getattr(provider, "kind", None)
        if not kind:
            continue
        ctx = PricingContext(rule_snapshot={"pricing_kind": kind, "amount": "120.00"})
        picked = resolve_v2(ctx)
        assert isinstance(picked, PricingContractV2)
        assert picked.name == provider.name


def test_driver_rule_snapshot_is_readable_and_never_throws() -> None:
    """订单上的 JSON 快照列是 Text：坏了就当没有，⛔ 不许让整条链路 500。"""
    order = order_fixture()
    assert driver_rule_of(order) == {}
    order.driver_rule_snapshot = "{不是合法 JSON"
    assert driver_rule_of(order) == {}
    order.driver_rule_snapshot = "[1, 2]"
    assert driver_rule_of(order) == {}