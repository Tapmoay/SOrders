"""按路线自动带价（CHG-0129）—— 「最贴近」的挑选规则与"手改优先"的判据。

这里的每一条都钉着一个**静默**的坏结果（不报错、也没人看得出来）：
带错一条价目的钱 / 该带没带 / 拿别类货的价顶上 / 平手时随便取一条还不说。
用户 2026-10-15 的口径是「**运费模板已经绑定了路线，派单时路线匹配就直接带出钱**」，
以及"多条命中取**最贴近**、并把**选了谁**显示出来"。
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import auth_headers

from app.models import (
    FreightCategory,
    FreightTemplate,
    FreightTemplateCategory,
    Order,
    ShipperAddress,
    User,
)
from app.models.enums import OrderStatus, UserRole
from app.services import freight_pricing, freight_route_autofill as auto


def _uniq(prefix: str) -> str:
    """测试库跨轮次保留（API 调用会 commit）—— 名字必须每轮唯一。"""
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def _phone() -> str:
    return "139" + uuid.uuid4().hex[:8].translate(str.maketrans("abcdef", "012345"))


# ---------------------------------------------------------------- 建数据（照 test_freight_pricing 的样子）

def _order(db: Session, addr: str = "城北市场 1 号", category_id: int | None = None) -> Order:
    o = Order(
        order_no=f"SO{db.query(Order).count() + 1:018d}",
        status=OrderStatus.DISPATCHED,
        order_date=date(2026, 10, 15),
        address_detail=addr,
        freight_category_id=category_id,
    )
    db.add(o)
    db.flush()
    return o


def _route(db: Session, dispatcher: User, addr: str, origin: str = "城南仓库") -> ShipperAddress:
    a = ShipperAddress(
        shipper_id=dispatcher.id, detail_address=addr, origin_address=origin, phone="13800000000"
    )
    db.add(a)
    db.flush()
    return a


def _template(
    db: Session,
    route: ShipperAddress | None,
    *,
    fee: str,
    name: str,
    to_place: str = "",
    cats: tuple[FreightCategory, ...] = (),
    vehicle_type: str = "",
) -> FreightTemplate:
    t = FreightTemplate(
        name=name,
        route_id=route.id if route is not None else None,
        to_place=to_place or (route.detail_address if route is not None else ""),
        from_place=(route.origin_address or "") if route is not None else "",
        vehicle_type=vehicle_type,
        fee=Decimal(fee),
        created_by=route.shipper_id if route is not None else None,
    )
    db.add(t)
    db.flush()
    for c in cats:
        db.add(FreightTemplateCategory(template_id=t.id, category_id=c.id))
    db.flush()
    return t


def _fact(t: FreightTemplate, cats: tuple[FreightCategory, ...] = (), updated: str = "") -> auto.TplFact:
    return auto.TplFact(
        template_id=int(t.id),
        name=t.name,
        fee=str(t.fee),
        price_name=t.price_name or "",
        route=(t.from_place + " → " + t.to_place) if t.from_place else t.to_place,
        route_id=int(t.route_id) if t.route_id is not None else None,
        to_place=(t.to_place or "").strip(),
        category_ids=tuple(int(c.id) for c in cats),
        category_names=tuple(c.name for c in cats),
        vehicle_type=(t.vehicle_type or ""),
        updated_at=updated,
    )


def _fact_raw(
    tid: int,
    *,
    name: str = "价目",
    fee: str = "100.00",
    price_name: str = "",
    route_id: int | None = 7,
    to_place: str = "城北市场 1 号",
    cats: tuple[int, ...] = (),
    cat_names: tuple[str, ...] = (),
    vehicle_type: str = "",
    updated: str = "2026-10-01T00:00:00",
) -> auto.TplFact:
    """纯函数用的价目事实（不碰库）。"""
    return auto.TplFact(
        template_id=tid,
        name=name,
        fee=fee,
        price_name=price_name,
        route="城南仓库 → " + to_place,
        route_id=route_id,
        to_place=to_place,
        category_ids=cats,
        category_names=cat_names,
        vehicle_type=vehicle_type,
        updated_at=updated,
    )


# ---------------------------------------------------------------- ① 纯函数：路线这一维


def test_绑了这条路线就带出这条价目的钱():
    f = _fact_raw(1, fee="120.00", name="城北价")
    best = auto.pick_closest([f], auto.Wish(address_detail="城北市场 1 号", route_ids=(7,)))
    assert best.ok and best.pick is not None
    assert best.pick.fact.fee == "120.00"
    assert best.pick.route_hit == auto.ROUTE_BOUND


def test_绑了路线优先于只有终点文字对得上的():
    """老价目可能没绑路线（route_id 是 NULL）—— 文字命中仍然能带价，但排在绑定命中的后面。"""
    bound = _fact_raw(1, fee="100.00", name="绑路线的", route_id=7)
    text = _fact_raw(2, fee="200.00", name="只有文字的", route_id=None)
    best = auto.pick_closest([text, bound], auto.Wish(address_detail="城北市场 1 号", route_ids=(7,)))
    assert best.pick is not None and best.pick.fact.name == "绑路线的"


def test_老数据没绑路线也能靠终点文字带价():
    text = _fact_raw(2, fee="200.00", name="只有文字的", route_id=None)
    best = auto.pick_closest([text], auto.Wish(address_detail="城北市场 1 号", route_ids=()))
    assert best.ok and best.pick is not None and best.pick.fact.fee == "200.00"
    assert best.pick.route_hit == auto.ROUTE_TEXT


def test_路线对不上就什么都不带():
    other = _fact_raw(1, route_id=99, to_place="别的市场", fee="999.00")
    best = auto.pick_closest([other], auto.Wish(address_detail="城北市场 1 号", route_ids=(7,)))
    assert best.pick is None and best.reason
    assert "还没有价目" in best.reason


def test_没有送货地址就什么都不带():
    best = auto.pick_closest([_fact_raw(1)], auto.Wish(address_detail="", route_ids=()))
    assert best.pick is None and "没有送货地址" in best.reason


# ---------------------------------------------------------------- ② 纯函数：分类与车型


def test_别的分类的价目不参选():
    frozen = _fact_raw(1, cats=(9,), cat_names=("冻品",), fee="300.00")
    best = auto.pick_closest(
        [frozen],
        auto.Wish(address_detail="城北市场 1 号", route_ids=(7,), category_id=5, category_name="蔬菜"),
    )
    assert best.pick is None
    assert "蔬菜" in best.reason and "手动定价" in best.reason


def test_没过分类的这一单可以拿通用价():
    """这一单没填分类时，分类这一维不参与 —— 不然待定价页明明有价也会报"没价"。"""
    f = _fact_raw(1, cats=(9,), fee="300.00")
    best = auto.pick_closest([f], auto.Wish(address_detail="城北市场 1 号", route_ids=(7,)))
    assert best.ok and best.pick is not None and best.pick.category_hit == auto.CAT_UNKNOWN


def test_分类对得上优先于没限分类():
    hit = _fact_raw(1, cats=(5,), fee="100.00", name="这一类的")
    anyc = _fact_raw(2, cats=(), fee="200.00", name="通用兜底")
    best = auto.pick_closest(
        [anyc, hit],
        auto.Wish(address_detail="城北市场 1 号", route_ids=(7,), category_id=5, category_name="蔬菜"),
    )
    assert best.pick is not None and best.pick.fact.name == "这一类的"


def test_车型对得上优先但车型对不上也照样带价():
    """车型**只排序不筛**：拿它当筛子的话"司机开大车、价目只写了小车"会一毛钱都带不出来。"""
    small = _fact_raw(1, fee="100.00", name="小车的", vehicle_type="small")
    large = _fact_raw(2, fee="200.00", name="大车的", vehicle_type="large")
    only_small = [_fact_raw(1, fee="100.00", name="小车的", vehicle_type="small")]
    wish = auto.Wish(address_detail="城北市场 1 号", route_ids=(7,), vehicle_type="large")

    best = auto.pick_closest([small, large], wish)
    assert best.pick is not None and best.pick.fact.name == "大车的"
    # 只有小车的价目时：仍然带出来（排序维度，不是筛子）
    only = auto.pick_closest(only_small, wish)
    assert only.ok and only.pick is not None and only.pick.vehicle_hit == auto.VEH_OTHER
    assert "车型不完全一致" in auto.why_text(only)


# ---------------------------------------------------------------- ③ 纯函数：平手与理由


def test_同为最贴近时取最近改过的那一条并且要说明():
    old = _fact_raw(1, fee="100.00", name="老的", updated="2026-09-01T00:00:00")
    new = _fact_raw(2, fee="100.00", name="新改的", updated="2026-10-14T00:00:00")
    best = auto.pick_closest([old, new], auto.Wish(address_detail="城北市场 1 号", route_ids=(7,)))
    assert best.pick is not None and best.pick.fact.name == "新改的"
    assert best.ties == 2
    why = auto.why_text(best)
    assert "新改的" in why and "同样贴近还有 1 条" in why


def test_理由要说清选了谁凭什么():
    f = _fact_raw(1, fee="120.00", name="城北价", price_name="价格一", cats=(5,), vehicle_type="large")
    best = auto.pick_closest(
        [f],
        auto.Wish(
            address_detail="城北市场 1 号",
            route_ids=(7,),
            category_id=5,
            category_name="蔬菜",
            vehicle_type="large",
        ),
    )
    why = auto.why_text(best)
    assert "城北价" in why and "价格一" in why
    assert "价目绑的就是这条路线" in why and "分类对得上" in why and "车型对得上" in why


def test_没挑到时理由就是那句话():
    best = auto.pick_closest([], auto.Wish(address_detail="城北市场 1 号", route_ids=(7,)))
    assert auto.why_text(best) == best.reason


# ---------------------------------------------------------------- ④ 接口：closest=true


def test_接口_按路线自动带价并说清选了谁(client: TestClient, db_session: Session, users, token_dispatcher):
    db = db_session
    addr = "自动带价市场 " + uuid.uuid4().hex[:6] + " 号"
    cat = FreightCategory(name=_uniq("蔬菜"), sort_order=1)
    db.add(cat)
    route = _route(db, users["dispatcher"], addr)
    tpl = _template(db, route, fee="88.50", name=_uniq("城北价"), cats=(cat,))
    order = _order(db, addr=addr, category_id=cat.id)
    db.commit()

    r = client.get(
        "/api/v1/freight-templates/quote",
        params={"order_id": order.id, "closest": "true"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matched"] is not None, body
    assert Decimal(str(body["matched"]["fee"])) == Decimal("88.50")
    assert body["matched"]["template_id"] == tpl.id
    # 「选了谁、凭什么」必须跟着回去（用户口径：界面上要看得见）
    assert tpl.name in body["why"] and "价目绑的就是这条路线" in body["why"]


def test_接口_不传closest时报价语义一字不变(client: TestClient, db_session: Session, users, token_dispatcher):
    """两条同路线同分类的价目：老路（不传 closest）仍然**不猜**，新路才按车型挑。"""
    db = db_session
    addr = "双价目市场 " + uuid.uuid4().hex[:6] + " 号"
    cat = FreightCategory(name=_uniq("冻品"), sort_order=2)
    db.add(cat)
    route = _route(db, users["dispatcher"], addr)
    _template(db, route, fee="100.00", name=_uniq("小车价"), cats=(cat,), vehicle_type="small")
    big = _template(db, route, fee="200.00", name=_uniq("大车价"), cats=(cat,), vehicle_type="large")
    order = _order(db, addr=addr, category_id=cat.id)
    db.commit()

    old = client.get(
        "/api/v1/freight-templates/quote",
        params={"order_id": order.id},
        headers=auth_headers(token_dispatcher),
    )
    assert old.status_code == 200, old.text
    assert old.json()["matched"] is None
    assert len(old.json()["ambiguous"]) == 2
    assert old.json()["why"] == ""

    new = client.get(
        "/api/v1/freight-templates/quote",
        params={"order_id": order.id, "closest": "true", "vehicle_type": "large"},
        headers=auth_headers(token_dispatcher),
    )
    assert new.status_code == 200, new.text
    assert new.json()["matched"]["template_id"] == big.id
    assert Decimal(str(new.json()["matched"]["fee"])) == Decimal("200.00")


def test_接口_自动带价是只读的(client: TestClient, db_session: Session, users, token_dispatcher):
    """报价**不许**顺手把运费写进订单（那会让"手改优先"变成笑话）。"""
    db = db_session
    addr = "只读市场 " + uuid.uuid4().hex[:6] + " 号"
    route = _route(db, users["dispatcher"], addr)
    tpl = _template(db, route, fee="66.00", name=_uniq("只读价"))
    order = _order(db, addr=addr)
    db.commit()

    r = client.get(
        "/api/v1/freight-templates/quote",
        params={"order_id": order.id, "closest": "true"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    o = db.get(Order, order.id)
    assert o.freight_fee is None
    assert o.freight_category_id is None
    row = db.get(FreightTemplate, tpl.id)
    assert row is not None and row.fee == Decimal("66.00") and row.is_deleted is False


def test_服务_自动带价不看司机的规则(db_session: Session, users):
    """「按路线自动带价」与「按司机的规则带价」是两条路：前者不需要司机挂规则。"""
    db = db_session
    addr = "无规则市场 " + uuid.uuid4().hex[:6] + " 号"
    route = _route(db, users["dispatcher"], addr)
    tpl = _template(db, route, fee="77.00", name=_uniq("无规则价"))
    order = _order(db, addr=addr)
    db.commit()

    best = auto.autofill_for(db, order)
    assert best.ok and best.pick is not None and best.pick.fact.template_id == tpl.id
    # 同一单走"司机的规则"那条路时是**没有候选**的（他还没挂规则）
    q = freight_pricing.quote_for(db, order, driver_id=None)
    assert q.matched is not None  # driver_id=None 时看全量价目（待定价页的兜底口径）
