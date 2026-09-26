# -*- coding: utf-8 -*-
"""UnitConversionContract v1 的**共享契约用例**。

## 这一份为什么是这个形状（R4-04 的 Add 演练靠它）

它不是"测 SI 换算得对不对"，而是"**每一个实现是不是都守契约**"。所以：

* 用例**遍历 PROVIDERS**（扫出来的，不是手写名单）—— 新增一个实现文件，
  它自动被同一组用例跑一遍，⛔ 不需要来这里加一行；
* 用例**不认识任何一种单位** —— 单位与量纲从实现自己的 `units()` 里读，
  所以加"中国传统单位"或"英制"时这一份**一个字都不用改**。

这就是指南 §37「Contract tested / Add implementation tested」的落地：
**同一组契约用例，两个实现各跑一遍**。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.contracts.unit_conversion import (
    CONTRACT_VERSION,
    ConversionRequest,
    ConversionResult,
    UnitConversionContract,
    UnitConversionError,
)
from app.extensions.unit_conversion import PROVIDERS, resolve


def test_there_is_at_least_one_provider():
    """⛔ 空名单会让下面每一个参数化用例**静默不跑** —— 那正是"永远绿的检查"。"""
    assert PROVIDERS, "一个换算实现都没有：契约用例会变成空转"
    names = [p.name for p in PROVIDERS]
    assert len(names) == len(set(names)), "实现名重复：" + str(names)


@pytest.mark.parametrize("provider", PROVIDERS, ids=[p.name for p in PROVIDERS])
class TestEveryImplementation:
    """同一组用例，**每一个实现**都跑一遍。"""

    def test_satisfies_the_contract(self, provider: UnitConversionContract) -> None:
        assert isinstance(provider, UnitConversionContract)
        assert provider.name and isinstance(provider.name, str)
        assert provider.version == CONTRACT_VERSION

    def test_declares_what_it_covers(self, provider: UnitConversionContract) -> None:
        units = provider.units()
        assert units, provider.name + " 的 units() 是空的 —— 调用方只能靠猜"
        for unit, dimension in units.items():
            assert unit == unit.strip().lower(), "单位名要归一（小写、无空白）：" + repr(unit)
            assert dimension and isinstance(dimension, str), unit + " 没有量纲"

    def test_unknown_units_are_not_its_job(self, provider: UnitConversionContract) -> None:
        """认不出来 = 返回 None，⛔ 不是抛错（"不是我的活"与"不合法"是两件事）。"""
        assert provider.supports("不存在的单位", "另一个不存在的单位") is False
        assert provider.convert(ConversionRequest(Decimal("1"), "不存在的单位", "kg")) is None

    def test_cross_dimension_is_refused(self, provider: UnitConversionContract) -> None:
        """不同量纲不许换算：**归我管但仍要拒绝**，而且拒绝的话必须说清是量纲问题。"""

        by_dim: dict[str, list[str]] = {}
        for unit, dim in provider.units().items():
            by_dim.setdefault(dim, []).append(unit)
        if len(by_dim) < 2:
            pytest.skip("这个实现只有一种量纲，跨量纲这条不适用")
        dims = sorted(by_dim)
        a = by_dim[dims[0]][0]
        b = by_dim[dims[1]][0]
        # ⛔ 契约分工：认不出单位才是"不是我的活"；量纲冲突是**归我管但不合法**。
        assert provider.supports(a, b) is True, "两个单位都认识，就该承认归自己管"
        with pytest.raises(UnitConversionError) as exc:
            provider.convert(ConversionRequest(Decimal("1"), a, b))
        assert str(exc.value), "拒绝时必须给一句能照着改的中文"

    def test_same_unit_is_refused(self, provider: UnitConversionContract) -> None:
        """源单位 == 目标单位：那会显示成一条"正常"的换算（既有实现里已经栽过）。"""
        unit = sorted(provider.units())[0]
        assert provider.supports(unit, unit) is True
        with pytest.raises(UnitConversionError):
            provider.convert(ConversionRequest(Decimal("1"), unit, unit))

    def test_same_dimension_pairs_round_trip(self, provider: UnitConversionContract) -> None:
        """同量纲两两换算：factor 自洽、往返回得来、量纲不变、输出是核心类型。"""
        by_dim: dict[str, list[str]] = {}
        for unit, dim in provider.units().items():
            by_dim.setdefault(dim, []).append(unit)
        checked = 0
        for dim, units in by_dim.items():
            for a in units:
                for b in units:
                    if a == b:
                        continue
                    assert provider.supports(a, b) is True, a + " -> " + b + " 应当被支持"
                    result = provider.convert(ConversionRequest(Decimal("1"), a, b))
                    assert isinstance(result, ConversionResult)
                    assert result.quantity.dimension == dim
                    assert result.quantity.unit == b
                    assert result.quantity.value == result.factor, "factor 与结果不自洽"
                    assert result.source == provider.name
                    back = provider.convert(
                        ConversionRequest(result.quantity.value, b, a)
                    )
                    assert back is not None
                    assert back.quantity.value == Decimal("1"), a + " -> " + b + " -> " + a + " 回不到 1"
                    checked += 1
        assert checked > 0, provider.name + " 一个可换算的对都没有 —— 用例在空转"

    def test_result_is_exact_only_when_it_divides(self, provider: UnitConversionContract) -> None:
        """exact 这一位要如实：除得尽才是 True（界面要靠它说出"约"这个字）。"""
        pairs = []
        by_dim: dict[str, list[str]] = {}
        for unit, dim in provider.units().items():
            by_dim.setdefault(dim, []).append(unit)
        for units in by_dim.values():
            if len(units) >= 2:
                pairs.append((sorted(units)[0], sorted(units)[1]))
        assert pairs, provider.name + " 没有可换算的对"
        for a, b in pairs:
            result = provider.convert(ConversionRequest(Decimal("1"), a, b))
            assert result is not None
            assert result.exact is True or result.exact is False
            if result.exact:
                assert result.quantity.value * Decimal("1") == result.quantity.value


def test_resolve_picks_a_provider_or_says_it_cannot():
    """`resolve` 只负责"谁来回答"：认得就给人，认不得就给 None（⛔ 不猜）。"""
    for provider in PROVIDERS:
        units = sorted(provider.units())
        if len(units) < 2:
            continue
        found = resolve(units[0], units[1])
        assert found is not None, units[0] + " -> " + units[1] + " 应当有人认得（两个单位都认识）"
    assert resolve("不存在的单位", "也不存在") is None