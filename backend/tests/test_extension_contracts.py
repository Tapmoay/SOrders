# -*- coding: utf-8 -*-
"""扩展契约（R4-02）的单元测试：**契约本身就是被测对象**。

为什么契约要单测：契约是"核心对扩展的承诺"，它一旦不小心长出了实现或者漏掉了校验，
后果是**所有扩展一起错**，而且每一处都看起来合理。所以这里测的不是"某个算法对不对"，
而是"核心答应的那几条不变量还算不算数"。

⚠️ 这一份**不许** import 任何具体扩展（也不许 import 数据库）：
    契约必须能在没有库、没有扩展的情况下单独跑起来 —— 那是它"核心侧"的证明。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.contracts import pricing as pricing_contract
from app.core.contracts import unit_conversion as uc_contract
from app.core.contracts.money import DEFAULT_CURRENCY, QUANTUM, ROUNDING, Money, MoneyError
from app.core.contracts.pricing import (
    AmbiguousPricingRule,
    NoPricingRule,
    PricingContext,
    PricingContract,
    PricingError,
    PricingResult,
)
from app.core.contracts.quantity import UNKNOWN_DIMENSION, Quantity, QuantityError
from app.core.contracts.unit_conversion import (
    ConversionRequest,
    ConversionResult,
    UnitConversionContract,
    UnitConversionError,
)


# ---------------------------------------------------------------- 契约的元信息

def test_contracts_declare_version_one():
    assert uc_contract.CONTRACT_NAME == "UnitConversionContract"
    assert uc_contract.CONTRACT_VERSION == 1
    assert pricing_contract.CONTRACT_NAME == "PricingContract"
    assert pricing_contract.CONTRACT_VERSION == 1


def test_rounding_matches_the_project_wide_convention():
    """两位小数 + ROUND_HALF_UP —— 与仓库里那批既有实现同一条口径。"""
    assert QUANTUM == Decimal("0.01")
    from decimal import ROUND_HALF_UP

    assert ROUNDING is ROUND_HALF_UP


def test_error_types_are_value_errors_with_chinese_messages():
    """错误消息必须是能照着改的中文（后端抛的中文会被 App 原样显示）。"""
    for exc in (MoneyError, QuantityError, UnitConversionError, PricingError):
        assert issubclass(exc, ValueError)
    assert issubclass(NoPricingRule, PricingError)
    assert issubclass(AmbiguousPricingRule, PricingError)
    with pytest.raises(MoneyError) as e:
        Money("1") + Money("1", "USD")
    assert "币种" in str(e.value)


# ---------------------------------------------------------------- Money

def test_money_quantizes_half_up():
    """⛔ 不是 quantize 的默认 ROUND_HALF_EVEN —— 半分上会差一分钱。"""
    assert Money("1.005").amount == Decimal("1.01")
    assert Money("1.004").amount == Decimal("1.00")
    assert Money("8").amount == Decimal("8.00")


def test_money_defaults_to_cny_and_normalizes_case():
    assert Money("1").currency == DEFAULT_CURRENCY
    assert Money("1", " cny ").currency == "CNY"


def test_money_refuses_float():
    """float 在 0.1 上就不精确，放进来等于把一个已知的误差源引进钱里。"""
    with pytest.raises(MoneyError):
        Money.of(0.1)
    with pytest.raises(MoneyError):
        Money("1").times(0.1)


def test_money_refuses_mixed_currency_and_money_times_money():
    with pytest.raises(MoneyError):
        Money("1") - Money("1", "USD")
    with pytest.raises(MoneyError):
        Money("1").times(Money("2"))


def test_money_is_immutable():
    m = Money("1")
    with pytest.raises(Exception):
        m.amount = Decimal("2")  # type: ignore[misc]


def test_money_arithmetic_stays_two_decimals():
    assert (Money("0.1") + Money("0.2")).amount == Decimal("0.30")
    assert (Money("8.00").times(3)).amount == Decimal("24.00")
    assert (-Money("1.50")).amount == Decimal("-1.50")
    assert Money.zero().is_zero()


# ---------------------------------------------------------------- Quantity

def test_quantity_requires_a_unit():
    with pytest.raises(QuantityError):
        Quantity("10", "   ")
    with pytest.raises(QuantityError):
        Quantity("不是数", "车")


def test_quantity_dimension_rule():
    """同量纲才允许换算；unknown 之间也**不许** —— 那正是"10 车 ≈ 50 袋"的来源。"""
    a = Quantity("10", "车", "volume")
    b = Quantity("80", "方", "volume")
    assert a.same_dimension(b)
    assert Quantity("10", "车").dimension == UNKNOWN_DIMENSION
    assert not Quantity("10", "车").same_dimension(Quantity("10", "车"))
    assert not Quantity("10", "车").same_dimension(Quantity("5", "公斤", "mass"))


def test_quantity_is_immutable_and_has_no_unit_table():
    """⛔ 核心**不认识任何单位**：这里只有类型，没有名册、没有换算率。"""
    q = Quantity("10", "车", "volume")
    assert q.with_value("20").value == Decimal("20")
    with pytest.raises(Exception):
        q.value = Decimal("1")  # type: ignore[misc]


# ---------------------------------------------------------------- 两个契约的形状

def test_unit_conversion_contract_shape():
    class Impl:
        name = "reverse-verify"
        version = 1

        # ⚠️ R4-04 给协议补了 units()（见契约里的说明）—— 这个内联实现要跟上，
        #    否则 isinstance 会假失败，而那会把"协议改了"误报成"实现坏了"。
        def units(self) -> dict[str, str]:
            return {"a": "dim-a", "b": "dim-a"}

        def supports(self, from_unit: str, to_unit: str) -> bool:
            return True

        def convert(self, request: ConversionRequest) -> ConversionResult | None:
            return None

    assert isinstance(Impl(), UnitConversionContract)
    # ⛔ 认不出来返回 None（不是抛错）—— 多实现并存的全部前提
    assert Impl().convert(ConversionRequest(Decimal("1"), "a", "b")) is None


def test_pricing_contract_shape_and_money_only_output():
    class Impl:
        name = "reverse-verify"
        version = 1

        def price(self, context: PricingContext) -> PricingResult:
            return PricingResult(money=Money("12.34"), rule_name="r", detail="按规则 r")

    assert isinstance(Impl(), PricingContract)
    result = Impl().price(PricingContext(order_no="SO1"))
    assert isinstance(result.money, Money)


def test_pricing_context_snapshot_is_read_only():
    """扩展算价时顺手改快照 = 改历史 —— 契约层面就堵死。"""
    ctx = PricingContext(rule_snapshot={"rule_name": "x"})
    with pytest.raises(TypeError):
        ctx.rule_snapshot["rule_name"] = "y"  # type: ignore[index]


def test_ambiguous_pricing_carries_candidates():
    exc = AmbiguousPricingRule("同一档匹配到两条", ("价目 A", "价目 B"))
    assert exc.candidates == ("价目 A", "价目 B")
