"""司机计费规则 → 钱：纯函数单测（不碰数据库，跑得飞快）。

为什么这些断言必须存在：这是**钱**的算法，出错的表现是"某类司机每一单都少拿 5%"，
而界面上一切正常（金额是个数字，没人知道它该是多少）。
用户 2026-09-18 要的那几种算法逐条钉在这里：
固定工资 / 每单（每车）固定 / 每件固定 / 运费提成 / 商品金额提成 / 组合 / 老口径不回归。
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.driver_pay import (
    PayRule,
    has_per_order_pay,
    monthly_salary_of,
    order_goods_amount,
    order_pay,
    pay_summary_for,
    rule_from_snapshot,
    rule_of_user,
    rule_to_snapshot,
    snapshot_mode,
)
from app.schemas.driver_billing_rule import validate_rule_params


def _user(**kw):
    """假的司机对象（只需要那几个属性，不建表、不连库）。"""
    base = dict(id=1, role="driver", vehicle_type=None, billing_mode=None, salary=None, driver_rule=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _rule(**kw) -> PayRule:
    base = dict(rule_id=7, name="测试规则", salary=Decimal("0"), piece_amount=Decimal("0"),
                piece_unit="order", commission_base="none", commission_rate=Decimal("0"))
    base.update(kw)
    return PayRule(**base)


# ---------------------------------------------------------------- 三件怎么组合

def test_没挂规则就是老口径_拿全额运费():
    """改造前的行为必须一字不变：计件 = 该单运费全额。"""
    p = order_pay(None, freight_fee="500.00", goods_amount="9999.00", quantity=3)
    assert p.piece == Decimal("500.00")
    assert p.commission == Decimal("0.00")
    assert p.total == Decimal("500.00")


def test_只拿固定工资时_这一单不产生按单应付():
    r = _rule(salary=Decimal("8000"))
    p = order_pay(r, freight_fee="500.00")
    assert p.total == Decimal("0.00")
    assert not r.has_per_order_pay
    assert r.has_salary


def test_每单固定金额_就是车辆提成那种():
    p = order_pay(_rule(piece_amount=Decimal("200")), freight_fee="500.00")
    assert p.piece == Decimal("200.00")
    assert p.total == Decimal("200.00")


def test_每件固定金额要乘件数():
    p = order_pay(_rule(piece_amount=Decimal("3"), piece_unit="item"), freight_fee="0", quantity=7)
    assert p.piece == Decimal("21.00")


def test_按运费提成():
    p = order_pay(_rule(commission_base="freight", commission_rate=Decimal("5")), freight_fee="1000.00")
    assert p.commission == Decimal("50.00")
    assert p.basis == Decimal("1000.00")


def test_按商品金额提成():
    p = order_pay(
        _rule(commission_base="goods", commission_rate=Decimal("3")),
        freight_fee="1000.00",
        goods_amount="2000.00",
    )
    assert p.commission == Decimal("60.00")
    assert p.basis == Decimal("2000.00")


def test_固定工资加提成加每单_三件可以同时给():
    r = _rule(salary=Decimal("6000"), piece_amount=Decimal("200"), commission_base="freight", commission_rate=Decimal("5"))
    p = order_pay(r, freight_fee="1000.00")
    assert p.piece == Decimal("200.00")
    assert p.commission == Decimal("50.00")
    assert p.total == Decimal("250.00")   # 工资不进按单账单，另有月度工资单
    assert r.has_salary and r.has_per_order_pay


def test_百分之百运费_等价于老口径():
    """想要"这个司机就拿这单运费"也能配出来，不用特例。"""
    r = _rule(commission_base="freight", commission_rate=Decimal("100"))
    assert order_pay(r, freight_fee="500.00").total == order_pay(None, freight_fee="500.00").total


def test_每单拿这一单的钱_金额由派单员逐单定():
    """用户 2026-09-18：「每单有多少钱，但每单是不固定的，几百块、几十块，由派单员来决定的」。"""
    r = _rule(piece_unit="order_price")
    assert order_pay(r, freight_fee="380.00").piece == Decimal("380.00")
    assert order_pay(r, freight_fee="45.00").piece == Decimal("45.00")   # 同一份规则，逐单不同


def test_派单员可以给某一单单独定金额和比例():
    """「提成又是另外一回事，可能设置这一单、或者这一类单」→ 这一单单独给。"""
    r = _rule(piece_amount=Decimal("300"), commission_base="freight", commission_rate=Decimal("5"))
    p = order_pay(r, freight_fee="1000.00", piece_override="200", rate_override="8")
    assert p.piece == Decimal("200.00")
    assert p.commission == Decimal("80.00")            # 8% 而不是规则里的 5%
    assert p.rate_used == Decimal("8.00")
    assert p.piece_overridden and p.rate_overridden    # 账单要能写清"这单是单独定的"
    plain = order_pay(r, freight_fee="1000.00")
    assert plain.piece == Decimal("300.00") and not plain.piece_overridden
    assert plain.rate_used == Decimal("5.00")


def test_抽成限定商品时_只算这些商品的行():
    """用户 2026-09-18：「哪些商品是要抽成的」。"""
    order = SimpleNamespace(order_products=[
        SimpleNamespace(product_id=11, line_total=Decimal("100"), quantity=1),
        SimpleNamespace(product_id=22, line_total=Decimal("900"), quantity=2),
        SimpleNamespace(product_id=None, line_total=Decimal("50"), quantity=1),  # 手工行
    ])
    assert order_goods_amount(order) == Decimal("1050.00")
    assert order_goods_amount(order, (11,)) == Decimal("100.00")
    assert order_goods_amount(order, (11, 22)) == Decimal("1000.00")
    # 范围里只有 11 → 提成基数是 100，不是 1050
    r = _rule(commission_base="goods", commission_rate=Decimal("10"), commission_product_ids=(11,))
    p = order_pay(
        r,
        freight_fee="0",
        goods_amount=order_goods_amount(order, r.commission_product_ids),
    )
    assert p.commission == Decimal("10.00")


def test_一句话说明会写明抽成范围():
    r = _rule(commission_base="goods", commission_rate=Decimal("10"), commission_product_ids=(1, 2))
    assert "指定商品" in r.describe()
    assert _rule(commission_base="goods", commission_rate=Decimal("10")).describe() == "商品金额的 10%"


def test_运费为空时提成算零_不会把None当0乘出崩():
    p = order_pay(_rule(commission_base="freight", commission_rate=Decimal("5")), freight_fee=None)
    assert p.total == Decimal("0.00")


def test_小于一分的尾数按四舍五入进账单():
    # 333.33 的 3.33% = 11.1008…，账单只能有两位小数
    p = order_pay(_rule(commission_base="freight", commission_rate=Decimal("3.33")), freight_fee="333.33")
    assert p.commission == Decimal("11.10")


# ---------------------------------------------------------------- 文案（界面/卡片/账单同源）

def test_一句话说明把三件都说清楚():
    # ⚠️ 金额末尾多余的 0 **去掉**（2026-09-22 用户定的显示口径：「有零的全省」）——
    #    但只动末尾的 0：`8000.00 → 8000`、`2.5% → 2.5%`（比例里的 5 一位不少）。
    r = _rule(salary=Decimal("8000"), piece_amount=Decimal("200"), commission_base="freight", commission_rate=Decimal("5"))
    assert r.describe() == "固定工资 8000 元/月 + 每单 200 元 + 运费的 5%"


def test_每件与商品金额的说法():
    assert _rule(piece_amount=Decimal("3"), piece_unit="item").describe() == "每件 3 元"
    assert _rule(commission_base="goods", commission_rate=Decimal("2.5")).describe() == "商品金额的 2.5%"
    # 小数位**有值**时一位不少（去尾零 ≠ 约掉）
    assert _rule(piece_amount=Decimal("3.25"), piece_unit="item").describe() == "每件 3.25 元"


def test_按分类定价那句话里的金额也去尾零():
    r = _rule(
        piece_mode="category",
        by_category=((1, Decimal("120.00"), Decimal("5.00")), (2, Decimal("80.50"), Decimal("0"))),
    )
    assert r.describe({1: "日化", 2: "冻品"}) == "按分类定价（日化 120 元/单 · 5%、冻品 80.5 元/单）"


def test_什么都不给的规则说明为不计费():
    assert _rule().describe() == "不计费"


# ---------------------------------------------------------------- 快照（历史不可变）

def test_快照能原样读回来():
    r = _rule(salary=Decimal("6000"), piece_amount=Decimal("150"), commission_base="goods", commission_rate=Decimal("4"))
    back = rule_from_snapshot(rule_to_snapshot(r))
    assert back is not None
    assert (back.rule_id, back.name, back.salary, back.piece_amount) == (7, "测试规则", Decimal("6000.00"), Decimal("150.00"))
    assert (back.commission_base, back.commission_rate) == ("goods", Decimal("4.00"))


def test_坏掉的快照退回老口径而不是抛异常():
    """快照坏了不能让送达直接 500——那会卡住司机交单（拿不到钱比算错钱更急）。"""
    for bad in (None, "", "not json", "[1,2,3]", "{}"):
        r = rule_from_snapshot(bad)
        assert r is None or isinstance(r, PayRule)


def test_空字典快照读出来是一份不计费的规则():
    r = rule_from_snapshot("{}")
    assert r is not None and r.pays_nothing


def test_谁有按单应付_按订单快照判():
    assert has_per_order_pay(SimpleNamespace(driver_billing_mode_snapshot="PIECE", freight_fee="1")) is True
    assert has_per_order_pay(SimpleNamespace(driver_billing_mode_snapshot="piece", freight_fee="1")) is True
    assert has_per_order_pay(SimpleNamespace(driver_billing_mode_snapshot="SALARY", freight_fee="1")) is False
    # 老单（快照为空）：与结算页同口径——有运费就算有
    assert has_per_order_pay(SimpleNamespace(driver_billing_mode_snapshot=None, freight_fee="1")) is True
    assert has_per_order_pay(SimpleNamespace(driver_billing_mode_snapshot=None, freight_fee=None)) is False


# ---------------------------------------------------------------- 司机身上的规则

def test_挂了规则时_模式快照由规则决定():
    user = _user(driver_rule=SimpleNamespace(id=3, name="R", salary=0, piece_amount=200, piece_unit="order",
                                             commission_base="none", commission_rate=0, vehicle_type=None))
    assert snapshot_mode(user) == "PIECE"                     # 有按单应付
    assert rule_of_user(user).rule_id == 3

    salary_only = _user(driver_rule=SimpleNamespace(id=4, name="S", salary=6000, piece_amount=0, piece_unit="order",
                                                    commission_base="none", commission_rate=0, vehicle_type=None))
    assert snapshot_mode(salary_only) == "SALARY"             # 只拿月薪


def test_没挂规则时_模式沿用车型与手填值():
    assert snapshot_mode(_user(vehicle_type="trailer", billing_mode=None)) == "PIECE"
    assert snapshot_mode(_user(vehicle_type="large", billing_mode=None)) == "SALARY"
    assert snapshot_mode(_user(vehicle_type="large", billing_mode="piece")) == "PIECE"


def test_月薪只认规则的_挂了规则就不再看users_salary():
    assert monthly_salary_of(_user(billing_mode="SALARY", salary=Decimal("4500"))) == Decimal("4500.00")
    assert monthly_salary_of(_user(billing_mode="PIECE", salary=Decimal("4500"))) == Decimal("0.00")
    rule_user = _user(billing_mode="PIECE", salary=Decimal("4500"),
                      driver_rule=SimpleNamespace(id=5, name="R", salary=Decimal("7000"), piece_amount=100,
                                                  piece_unit="order", commission_base="none", commission_rate=0,
                                                  vehicle_type=None))
    assert monthly_salary_of(rule_user) == Decimal("7000.00")


def test_非派单员视角那句话不带金额():
    user = _user(driver_rule=SimpleNamespace(id=6, name="R", salary=Decimal("8888"), piece_amount=0,
                                             piece_unit="order", commission_base="none", commission_rate=0,
                                             vehicle_type=None))
    assert "8888" in pay_summary_for(user, include_money=True)
    assert "8888" not in pay_summary_for(user, include_money=False)


# ---------------------------------------------------------------- 参数校验（创建与修改共用）

def _params(**kw) -> dict:
    base = dict(name="规则A", vehicle_type=None, salary=0, piece_amount=0, piece_unit="order",
                commission_base="none", commission_rate=0, commission_product_ids=[], remark="")
    base.update(kw)
    return base


def test_合法参数通过():
    assert validate_rule_params(_params(piece_amount=200)) is None
    assert validate_rule_params(_params(salary=8000)) is None
    assert validate_rule_params(_params(commission_base="freight", commission_rate=5)) is None
    assert validate_rule_params(_params(piece_unit="order_price")) is None
    assert validate_rule_params(
        _params(commission_base="goods", commission_rate=10, commission_product_ids=[1])
    ) is None


def test_抽成范围只能配在商品金额抽成上():
    err = validate_rule_params(_params(commission_base="freight", commission_rate=5, commission_product_ids=[1]))
    assert err and "指定商品" in err


def test_拿这一单的钱不能同时再按运费抽成或再填固定每单():
    """两个一起配等于拿 100% 再加提成，几乎一定是配错了。"""
    a = validate_rule_params(_params(piece_unit="order_price", commission_base="freight", commission_rate=5))
    assert a and "不能同时配" in a
    b = validate_rule_params(_params(piece_unit="order_price", piece_amount=300))
    assert b and "不要再填" in b
    # 拿这一单的钱 + 按**商品**抽成是正当的（不同基数）
    assert validate_rule_params(
        _params(piece_unit="order_price", commission_base="goods", commission_rate=3)
    ) is None


def test_一分钱都不给的规则要被拒绝():
    err = validate_rule_params(_params())
    assert err and "一分钱" in err


def test_有比例没基数_有基数没比例都要被拒绝():
    assert "提成基数" in (validate_rule_params(_params(commission_rate=5)) or "")
    assert "提成比例" in (validate_rule_params(_params(commission_base="freight")) or "")


def test_名称不能空_比例不能超100_金额不能负():
    assert validate_rule_params(_params(name="  ", piece_amount=1))
    assert validate_rule_params(_params(commission_base="freight", commission_rate=101))
    assert validate_rule_params(_params(piece_amount=-1))
    assert validate_rule_params(_params(vehicle_type="飞机", piece_amount=1))
    assert validate_rule_params(_params(commission_base="利润", commission_rate=5))
