"""车辆属性**判据**的纯单测（不碰数据库）—— 2026-09-27 用户要的"车辆属性"。

判据本体在 `app/services/vehicle_attrs.py`。为什么值得单测：这几条规则写错的后果都**不报错** ——
打错一个键（`load_ton`）会存进一个**永远读不出来**的属性；给平板车存"车厢高"会让
界面上的叫法与库里的列从此对不上；`0` 与"没填"在界面上长得一样，
却会让"一车 = 0 方"看起来像个正经结果。

⛔ 这里还钉着两条**范围决定**（免得下一个人以为是漏了）：
① `载重(吨)` / `容积(方)` 对**每一种型式**都开放（它们是"任何货车都有"的容量事实）；
② 本模块**一个字节的钱都不算**，也不接进单位换算的消费点（那是 FEAT-0005）。
"""

from decimal import Decimal

import pytest

from app.services import vehicle_attrs as va


# ---------------------------------------------------------------- 车身型式


def test_body_labels_cover_every_type():
    """每一种合法型式都必须有中文名 —— 少一个，界面上就会显示原始码（`box`）。"""
    for b in va.BODY_TYPES:
        assert va.BODY_LABELS[b]


def test_clean_body_accepts_known_and_trims():
    assert va.clean_body("box") == "box"
    assert va.clean_body("  dump  ") == "dump"
    # 空 / None = 「未设置」——它是**正式取值**（老车、以及"还不知道这车是什么型式"）
    assert va.clean_body("") == ""
    assert va.clean_body(None) == ""


@pytest.mark.parametrize("raw", ["truck", "BOX", "箱式车", "大货车", "small"])
def test_clean_body_rejects_junk(raw):
    """⛔ 不许兜默认值：认不出就当箱式车，等于替用户认了一辆车的型式。"""
    with pytest.raises(ValueError) as e:
        va.clean_body(raw)
    assert "车身型式只能是" in str(e.value)
    # 提示里要把可选项列全，用户才知道填什么
    assert "箱式车" in str(e.value) and "挂车" in str(e.value)


def test_body_label_does_not_invent_a_name():
    """认不出的取值**原样返回**，不编一个名字出来（老数据里可能有别的写法）。"""
    assert va.body_label("box") == "箱式车"
    assert va.body_label("dump") == "自卸车"
    assert va.body_label("something_else") == "something_else"


# ---------------------------------------------------------------- 属性表


def _keys(body: str) -> set[str]:
    return {f.key for f in va.fields_for(body)}


def test_fields_are_the_approved_list():
    """需求方 2026-09-27 深夜逐条批准的那张表（「属性清单可以啊，就可以就这样子」）。

    ⛔ 改这张表 = 改"一辆车能填哪些属性"，是一条要重新拍板的事，不是顺手加一列。
    """
    common = {"height_m", "width_m", "curb_weight_t", "load_tons", "volume_cubic"}
    assert _keys("") == common
    # 箱式车：车厢长 / 宽 / 高
    assert _keys("box") == common | {"cargo_length_m", "cargo_width_m", "cargo_height_m"}
    # 平板车：台面长 / 宽（**没有台面高** —— 需求方给的清单里就没有这一项）
    assert _keys("flat") == common | {"cargo_length_m", "cargo_width_m"}
    # 自卸车：车斗长 / 宽 / 高
    assert _keys("dump") == common | {"cargo_length_m", "cargo_width_m", "cargo_height_m"}
    # 挂车：轴数
    assert _keys("trailer") == common | {"axle_count"}


def test_capacity_keys_are_open_to_every_body():
    """⭐ 吨 / 方 是**任何货车都有**的容量事实（用户：「主要的是吨和方这种计量单位」），
    所以对每一种型式都开放 —— 包括"未设置"。

    ⛔ 这一条同时钉住"**它们就是参与换算的那两项**"：谁把 `volume_cubic` 挪出通用档，
    或者往 `CAPACITY_KEYS` 里塞第三个键，这条会当场红。
    """
    assert va.CAPACITY_KEYS == ("load_tons", "volume_cubic")
    for b in va.BODY_TYPES:
        assert set(va.CAPACITY_KEYS) <= _keys(b), b


def test_same_fact_has_one_column_per_body():
    """车厢 / 台面 / 车斗的长宽高是**同一个事实的不同叫法**（载货区的长宽高），
    所以是**三列**，不是九列 —— 拆开之后"这辆车载货区多长"会有三个 Owner。"""
    for key, names in {
        "cargo_length_m": ("车厢长", "台面长", "车斗长"),
        "cargo_width_m": ("车厢宽", "台面宽", "车斗宽"),
    }.items():
        f = va.FIELDS_BY_KEY[key]
        assert tuple(f.per_body[b] for b in ("box", "flat", "dump")) == names
    # 高度只有两种车有
    h = va.FIELDS_BY_KEY["cargo_height_m"]
    assert set(h.bodies) == {"box", "dump"}


def test_title_carries_the_unit():
    """标题必须带量纲：`车高` 不带单位时，4 与 400 在界面上都像是对的。"""
    assert va.title_of(va.FIELDS_BY_KEY["height_m"], "box") == "车高(米)"
    assert va.title_of(va.FIELDS_BY_KEY["load_tons"], "box") == "载重(吨)"
    assert va.title_of(va.FIELDS_BY_KEY["volume_cubic"], "dump") == "斗容(方)"
    assert va.title_of(va.FIELDS_BY_KEY["cargo_length_m"], "flat") == "台面长(米)"
    assert va.title_of(va.FIELDS_BY_KEY["axle_count"], "trailer") == "轴数(个)"


# ---------------------------------------------------------------- 取值校验


def test_values_accept_string_number_and_decimal():
    """App 传字符串、AI 可能传数字 —— 两种都收（与 `validate_factor` 同一个做法）。"""
    for raw in ("8", 8, 8.0, Decimal("8"), " 8 "):
        got = va.parse_attrs("box", {"volume_cubic": raw})
        assert got == {"volume_cubic": Decimal("8.000")}


def test_blank_and_none_mean_not_filled():
    """空串 / None **不算填了** —— 客户端可以把整份表单原样传过来，不必自己先筛一遍。"""
    assert va.parse_attrs("box", {"volume_cubic": "", "load_tons": None, "height_m": "   "}) == {}
    assert va.parse_attrs("box", None) == {}


def test_values_are_rounded_to_storage_precision():
    """列宽是 `NUMERIC(…,3)`；多出来的位在这里就砍掉，免得读回来与填进去的不是同一个数。"""
    assert va.parse_attrs("box", {"volume_cubic": "8.00049"})["volume_cubic"] == Decimal("8.000")
    assert va.parse_attrs("box", {"volume_cubic": "8.0006"})["volume_cubic"] == Decimal("8.001")


def test_unknown_key_is_rejected():
    """打错一个字母（`load_ton`）会存进一个**永远读不出来**的属性，界面上什么都不显示。"""
    with pytest.raises(ValueError) as e:
        va.parse_attrs("box", {"load_ton": "8"})
    assert "不认识的车辆属性" in str(e.value)
    assert "load_tons" in str(e.value)  # 提示里要有正确的键名


def test_attribute_must_belong_to_the_body():
    """给平板车存"车厢高" —— 两边叫法从此对不上，而界面上也永远填不出来。"""
    with pytest.raises(ValueError) as e:
        va.parse_attrs("flat", {"cargo_height_m": "2"})
    assert "台面高" in str(e.value) or "货厢高" in str(e.value)
    assert "箱式车" in str(e.value)
    # 轴数只有挂车有
    with pytest.raises(ValueError):
        va.parse_attrs("box", {"axle_count": "3"})
    # 反向对照：同一项在允许的型式上必须过
    assert va.parse_attrs("dump", {"cargo_height_m": "1.5"})["cargo_height_m"] == Decimal("1.500")


@pytest.mark.parametrize("raw", ["0", "0.0", "-1", "-0.001"])
def test_value_must_be_positive(raw):
    """`0` 与"没填"在界面上长得一样，但 `0` 会让"一车 = 0 方"看起来像个正经结果。"""
    with pytest.raises(ValueError) as e:
        va.parse_attrs("box", {"volume_cubic": raw})
    assert "必须大于 0" in str(e.value)


# ⚠️ 空串**不在**这一组里：它是"没填"（见 test_blank_and_none_mean_not_filled），不是"填错了"。
@pytest.mark.parametrize("raw", ["abc", "8方", "八", "NaN", "Infinity"])
def test_value_must_be_a_number(raw):
    with pytest.raises(ValueError) as e:
        va.parse_attrs("box", {"height_m": raw})
    assert "不是数字" in str(e.value)


def test_value_has_an_upper_bound():
    """厘米当米填（车高 400）在界面上看不出来 —— 宁可当场拒绝，也不要存一个荒谬的数。"""
    ok = va.FIELDS_BY_KEY["height_m"].max_value
    assert va.parse_attrs("box", {"height_m": str(ok)})["height_m"] == ok    # 边界：正好等于上限，允许
    with pytest.raises(ValueError) as e:
        va.parse_attrs("box", {"height_m": str(ok + Decimal("0.001"))})
    assert "太大了" in str(e.value)


def test_axle_count_must_be_whole():
    assert va.parse_attrs("trailer", {"axle_count": "3"})["axle_count"] == Decimal("3.000")
    with pytest.raises(ValueError) as e:
        va.parse_attrs("trailer", {"axle_count": "3.5"})
    assert "整数" in str(e.value)


def test_attrs_must_be_a_mapping():
    with pytest.raises(ValueError) as e:
        va.parse_attrs("box", ["8"])      # type: ignore[arg-type]
    assert "属性名" in str(e.value)


# ---------------------------------------------------------------- 出参 / 落库


class _FakeVehicle:
    """够用的假车：`attrs_of` / `apply_attrs` 只按属性名读，不 import ORM。"""

    def __init__(self, **kw: object) -> None:
        for f in va.FIELDS:
            setattr(self, f.key, None)
        for k, v in kw.items():
            setattr(self, k, v)


def test_format_value_drops_trailing_zeros():
    """与单位换算那边 `format_factor` 同一个口径（设计系统 §4.1.1）。"""
    assert va.format_value(Decimal("8.000")) == "8"
    assert va.format_value(Decimal("12.500")) == "12.5"
    assert va.format_value(Decimal("0.001")) == "0.001"


def test_attrs_of_returns_only_what_was_filled():
    """⛔ 没填的属性**不出现**：回一个 `0` 或 `null`，界面上就会画出一个"系统说是 0"的数。"""
    v = _FakeVehicle(volume_cubic=Decimal("8.000"), load_tons=None)
    assert va.attrs_of(v) == {"volume_cubic": "8"}


def test_apply_attrs_replaces_wholesale():
    """整份替换：没在 values 里的列一律清空（需求方要的「属性不可能变」——改就是一次说清）。"""
    v = _FakeVehicle(volume_cubic=Decimal("8"), load_tons=Decimal("12"), height_m=Decimal("4"))
    va.apply_attrs(v, va.parse_attrs("box", {"volume_cubic": "9"}))
    assert v.volume_cubic == Decimal("9")
    assert v.load_tons is None and v.height_m is None
