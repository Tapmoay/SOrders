"""单位换算**判据**的纯单测（不碰数据库）—— 2026-09-24 用户要求。

判据本体在 `app/services/unit_conversion.py`。为什么值得单测：这四条规则里，
"一个源单位只能有一条"和"反向对不许并存"写错的后果是**同一批货有两个都像是对的答案**，
而两个数都不报错 —— 界面上只会挑一个显示，用户以为是系统算的。

⛔ 这里也钉着"**不做链式换算**"这条明确的范围决定（见服务模块文件头）。
"""

from decimal import Decimal

import pytest

from app.services import unit_conversion as rules


def _p(id_: int | None, f: str, t: str, factor: str = "8") -> rules.ConversionPair:
    return rules.pair_of(f, t, Decimal(factor), id_)


# ---------------------------------------------------------------- 单位名


def test_units_are_trimmed():
    assert rules.validate_units("  车 ", " 方 ") == ("车", "方")


@pytest.mark.parametrize("f, t", [("", "方"), ("   ", "方"), ("车", ""), ("车", "  ")])
def test_units_cannot_be_blank(f, t):
    with pytest.raises(ValueError) as e:
        rules.validate_units(f, t)
    assert "不能为空" in str(e.value)


def test_same_unit_is_rejected():
    """`1 车 = 1 车` 在列表里看起来像一条正常换算 —— 而且它什么也没说。"""
    with pytest.raises(ValueError) as e:
        rules.validate_units("车", "车")
    assert "没有意义" in str(e.value)
    # 只差大小写也算同一个单位
    with pytest.raises(ValueError):
        rules.validate_units("kg", "KG")


def test_unit_length_is_capped():
    with pytest.raises(ValueError) as e:
        rules.validate_units("车" * (rules.MAX_UNIT_LEN + 1), "方")
    assert "最多" in str(e.value)


# ---------------------------------------------------------------- 换算率


@pytest.mark.parametrize("raw", ["8", 8, Decimal("8"), " 8 ", 8.0])
def test_factor_accepts_number_and_string(raw):
    assert rules.validate_factor(raw) == Decimal("8")


@pytest.mark.parametrize("raw", [None, "", "  ", "abc", "8方", "一车"])
def test_factor_must_be_a_number(raw):
    with pytest.raises(ValueError) as e:
        rules.validate_factor(raw)
    assert "不是数字" in str(e.value) or "不能为空" in str(e.value)


def test_factor_must_be_positive():
    """`1 车 = 0 方` 会让「10 车 ≈ 0 方」看起来像个正经结果。"""
    for bad in ("0", 0, "-8", Decimal("-0.5")):
        with pytest.raises(ValueError) as e:
            rules.validate_factor(bad)
        assert "大于 0" in str(e.value)


def test_factor_has_an_upper_bound():
    with pytest.raises(ValueError) as e:
        rules.validate_factor(str(rules.FACTOR_MAX + 1))
    assert "太大" in str(e.value)


def test_factor_keeps_decimal_exactness():
    """换算率是 Decimal —— 浮点会让"10 车"显示成 79.99999999999999。"""
    assert rules.validate_factor("0.5") == Decimal("0.5")
    assert rules.validate_factor("0.1") * 3 == Decimal("0.3")


# ---------------------------------------------------------------- 不重复：源单位唯一


def test_same_from_unit_is_rejected_and_names_the_existing_one():
    rows = [_p(1, "车", "方", "8")]
    reason = rules.conflict_reason(rows, "车", "袋")
    assert reason is not None
    assert "1 车 = 8 方" in reason  # 说清挡住它的是哪一条
    assert "只能换算到一处" in reason


def test_from_unit_compare_ignores_case_and_space():
    rows = [_p(1, "车", "方")]
    assert rules.conflict_reason(rows, " 车 ", "袋") is not None


def test_exclude_id_lets_a_row_update_itself():
    """改这一条自己的备注/换算率时，不许被自己挡住。"""
    rows = [_p(1, "车", "方", "8")]
    assert rules.conflict_reason(rows, "车", "方", exclude_id=1) is None


# ---------------------------------------------------------------- 不重复：反向对


def test_reverse_pair_is_rejected():
    """`1 车 = 8 方` 与 `1 方 = 0.125 车` 并存 = 同一批货两个互相矛盾的数。"""
    rows = [_p(1, "方", "车", "0.125")]
    reason = rules.conflict_reason(rows, "车", "方")
    assert reason is not None
    assert "反过来" in reason


def test_different_source_units_coexist():
    rows = [_p(1, "车", "方")]
    # 「袋」没有换算过，可以新建
    assert rules.conflict_reason(rows, "袋", "斤") is None
    # 「方」可以有自己的换算（一车=8方 与 1方=50袋 是两条独立的一跳换算）
    assert rules.conflict_reason(rows, "方", "袋") is None


def test_no_chain_conversion_is_a_decision_not_an_omission():
    """⛔ 明确不做链式：`一车=8方` + `1方=50袋` **不**推 `一车=400袋`。

    这条用例的价值是把"范围决定"钉在代码里：判据**只**看一跳，
    所以上面那两条能同时存在，而它们之间不产生任何推导。
    """
    rows = [_p(1, "车", "方", "8"), _p(2, "方", "袋", "50")]
    # 车 → 袋 会被"车已经有了换算"挡住（而不是推出 400 袋）
    reason = rules.conflict_reason(rows, "车", "袋")
    assert reason is not None and "只能换算到一处" in reason
    # 判据里根本没有"沿链找路径"这回事：给它两跳也只会答一跳的答案
    assert rules.conflict_reason(rows, "斤", "两") is None


# ---------------------------------------------------------------- 显示


def test_format_factor_strips_trailing_zeros():
    assert rules.format_factor(Decimal("8.0000")) == "8"
    assert rules.format_factor(Decimal("0.5000")) == "0.5"
    assert rules.format_factor(Decimal("0.1250")) == "0.125"
    assert rules.format_factor(Decimal("10")) == "10"


def test_max_targets_constant_is_one():
    """"一个源单位只能一条"这件事必须出现在**调用点**看得见的地方。"""
    assert rules.MAX_TARGETS_PER_UNIT == 1
