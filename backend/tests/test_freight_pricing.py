"""运费分类 / 运价匹配 / 手动定价（2026-09-21 用户那一轮的后端回归）。

钉住四件事（**都是"不报错但算错钱"的形状**）：
1. 分类名册的删除：还有价目/规则挂着 → 拒绝；改名**不级联**（按编号挂）；
2. 匹配：路线 + 分类 + 司机 → 唯一一条；多条同样优先 → **不猜**（ambiguous）；
   没匹配到 → 带原因，不许静默当 0；
3. 手动定价：写订单 + 分类快照 + （可选）沉淀出线路与价目，并留审计；
4. 按分类定价的**钱**：`driver_pay.order_pay` 按这一单的分类取基价；没分类 → 不算
   （而不是拿统一价兜底，那会让"按分类"看起来生效了）。
"""

from datetime import date
from decimal import Decimal

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import auth_headers
def _uniq(prefix: str) -> str:
    """测试库跨轮次保留（API 调用会 commit）—— 名字必须每轮唯一，否则第二轮撞唯一约束。"""
    return f"{prefix}-{uuid.uuid4().hex[:6]}"

from app.models import (
    DriverBillingRule,
    DriverBillingRuleCategory,
    FreightCategory,
    FreightTemplate,
    FreightTemplateCategory,
    Order,
    OrderProduct,
    Product,
    ShipperAddress,
    User,
)
from app.models.enums import OrderStatus, UserRole
from app.services import driver_pay, freight_pricing


def _driver(db, phone="13900000001", name="司机甲") -> User:
    u = User(phone=phone, username=phone, full_name=name, password_hash="x", role=UserRole.DRIVER.value)
    db.add(u)
    db.flush()
    return u


def _order(db, addr="城北市场 1 号", driver=None) -> Order:
    o = Order(
        order_no=f"SO{db.query(Order).count() + 1:018d}",
        status=OrderStatus.DISPATCHED,
        order_date=date(2026, 9, 21),
        address_detail=addr,
        driver_id=driver.id if driver else None,
    )
    db.add(o)
    db.flush()
    return o


def _route(db, dispatcher, addr="城北市场 1 号", origin="城南仓库") -> ShipperAddress:
    a = ShipperAddress(shipper_id=dispatcher.id, detail_address=addr, origin_address=origin, phone="13800000000")
    db.add(a)
    db.flush()
    return a


def _template(db, route, fee="120.00", cats=(), drivers=(), name="城北价") -> FreightTemplate:
    t = FreightTemplate(
        name=name, route_id=route.id, to_place=route.detail_address, from_place=route.origin_address or "",
        fee=Decimal(fee), created_by=route.shipper_id,
    )
    db.add(t)
    db.flush()
    for c in cats:
        db.add(FreightTemplateCategory(template_id=t.id, category_id=c.id))
    from app.models import FreightTemplateDriver

    for d in drivers:
        db.add(FreightTemplateDriver(template_id=t.id, driver_id=d.id))
    db.flush()
    return t


# ---------------------------------------------------------------- ① 分类名册


def test_删除还有价目挂着的分类会被拒(client, db_session, users, token_dispatcher):
    dispatcher = users["dispatcher"]
    cat = FreightCategory(name=_uniq("冻品"), sort_order=1)
    db_session.add(cat)
    db_session.flush()
    _template(db_session, _route(db_session, dispatcher), cats=[cat])
    db_session.commit()

    r = client.delete(
        f"/api/v1/freight-categories/{cat.id}", headers=auth_headers(token_dispatcher)
    )
    assert r.status_code == 400, r.text
    assert "1 条运费价目" in r.json()["detail"]


def test_分类改名不级联价目(db_session, users):
    """两条线都是按**编号**挂的 —— 改名之后匹配照旧（级联反而会改错）。"""
    db = db_session
    dispatcher = users["dispatcher"]
    cat = FreightCategory(name=_uniq("冻品"), sort_order=1)
    db.add(cat)
    db.flush()
    route = _route(db, dispatcher)
    tpl = _template(db, route, cats=[cat])
    db.commit()

    cat.name = "冷冻品"
    db.commit()
    db.refresh(tpl)
    got = list(db.query(FreightTemplateCategory).filter_by(template_id=tpl.id))
    assert [g.category_id for g in got] == [cat.id], "改名不该动绑定（按编号挂）"
    quote = freight_pricing.quote_for(db, _order(db, driver=_driver(db)), category_id=cat.id)
    assert quote.matched is not None and quote.matched.template_id == tpl.id


# ---------------------------------------------------------------- ② 匹配


def _rule_with(db, driver, templates, name=None) -> DriverBillingRule:
    """给司机挂一份**勾了这些价目**的规则（价目归规则：没勾就不算候选）。"""
    from app.models import DriverBillingRuleTemplate

    rule = DriverBillingRule(name=name or _uniq("规则"), piece_amount=Decimal("50"), piece_mode="uniform")
    db.add(rule)
    db.flush()
    driver.driver_rule_id = rule.id
    for t in templates:
        db.add(DriverBillingRuleTemplate(rule_id=rule.id, template_id=t.id))
    db.flush()
    return rule


def test_候选只来自这个司机的规则勾的价目(db_session, users):
    """用户原话：「价目归这个计费规则，而这个规则在匹配对应的司机」。"""
    db = db_session
    dispatcher = users["dispatcher"]
    cat = FreightCategory(name=_uniq("蔬菜"), sort_order=1)
    db.add(cat)
    db.flush()
    route = _route(db, dispatcher)
    picked = _template(db, route, fee="100.00", cats=[cat], name="勾了的")
    _template(db, route, fee="150.00", cats=[cat], name="没勾的")
    driver = _driver(db, "139" + uuid.uuid4().hex[:8].translate(str.maketrans("abcdef", "012345")), "甲")
    _rule_with(db, driver, [picked])
    order = _order(db, driver=driver)
    db.commit()

    q = freight_pricing.quote_for(db, order, driver_id=driver.id, category_id=cat.id)
    assert q.matched is not None and q.matched.template_id == picked.id
    assert q.matched.fee == Decimal("100.00"), "没勾的那条不许被匹配到"


def test_司机没挂规则就没有候选(db_session, users):
    db = db_session
    dispatcher = users["dispatcher"]
    route = _route(db, dispatcher)
    _template(db, route, fee="100.00")
    driver = _driver(db, "139" + uuid.uuid4().hex[:8].translate(str.maketrans("abcdef", "012345")), "乙")
    order = _order(db, driver=driver)
    db.commit()

    q = freight_pricing.quote_for(db, order, driver_id=driver.id)
    assert q.matched is None and "还没挂计费规则" in q.reason


def test_规则没勾价目也要说清楚(db_session, users):
    db = db_session
    dispatcher = users["dispatcher"]
    route = _route(db, dispatcher)
    _template(db, route, fee="100.00")
    driver = _driver(db, "139" + uuid.uuid4().hex[:8].translate(str.maketrans("abcdef", "012345")), "丙")
    _rule_with(db, driver, [])
    order = _order(db, driver=driver)
    db.commit()

    q = freight_pricing.quote_for(db, order, driver_id=driver.id)
    assert q.matched is None and "还没勾价目" in q.reason


def test_多条同样优先时不猜(db_session, users):
    db = db_session
    dispatcher = users["dispatcher"]
    cat = FreightCategory(name=_uniq("蔬菜"), sort_order=1)
    db.add(cat)
    db.flush()
    route = _route(db, dispatcher)
    a = _template(db, route, fee="100.00", cats=[cat], name="价一")
    b = _template(db, route, fee="120.00", cats=[cat], name="价二")
    driver = _driver(db, "139" + uuid.uuid4().hex[:8].translate(str.maketrans("abcdef", "012345")), "丁")
    _rule_with(db, driver, [a, b])
    order = _order(db, driver=driver)
    db.commit()

    q = freight_pricing.quote_for(db, order, driver_id=driver.id, category_id=cat.id)
    assert q.matched is None and len(q.ambiguous) == 2
    assert "挑一条" in q.reason or "不替你猜" in q.reason


def test_没匹配到要说明原因而不是给零(db_session, users):
    db = db_session
    order = _order(db, addr="没配过价的地方")
    db.commit()
    q = freight_pricing.quote_for(db, order)
    assert q.matched is None and q.reason, "没匹配到必须给一句能看懂的原因"
    assert q.ambiguous == []


# ---------------------------------------------------------------- ③ 手动定价 + 沉淀


def test_手动定价会沉淀线路与价目并绑分类(db_session, users, client, token_dispatcher):
    db = db_session
    headers = auth_headers(token_dispatcher)
    cat = FreightCategory(name=_uniq("蔬菜"), sort_order=1)
    db.add(cat)
    driver = _driver(db, "139" + uuid.uuid4().hex[:8].translate(str.maketrans("abcdef", "012345")), "沉淀司机")
    # ⚠️ 地址也要**每轮唯一**：测试库跨轮次保留，写死地址的话上一轮沉淀出来的价目会先被查到
    addr = "城北市场 " + uuid.uuid4().hex[:6] + " 号"
    order = _order(db, addr=addr, driver=driver)
    # 价目归规则：先给他挂一份**还没勾任何价目**的规则（沉淀时要自动勾进去）
    _rule_with(db, driver, [])
    db.commit()

    r = client.post(
        f"/api/v1/orders/{order.id}/price-freight",
        json={"freight_fee": "88.5", "category_id": cat.id, "save_template": True},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    o = db.get(Order, order.id)
    assert o.freight_fee == Decimal("88.50")
    assert o.freight_category_id == cat.id and o.freight_category == cat.name
    # 线路与价目都沉淀下来了，而且挂在这一类上
    tpl = (
        db.query(FreightTemplate)
        .filter(FreightTemplate.to_place == addr, FreightTemplate.is_deleted.is_(False))
        .first()
    )
    assert tpl is not None and tpl.fee == Decimal("88.50")
    assert [c.category_id for c in db.query(FreightTemplateCategory).filter_by(template_id=tpl.id)] == [cat.id]
    # 沉淀出来的价目**自动勾进了他的规则** —— 否则"下次自动带价"是假的（价目归规则）
    db.expire_all()
    from app.models import DriverBillingRuleTemplate

    linked = list(
        db.query(DriverBillingRuleTemplate).filter_by(template_id=tpl.id)
    )
    assert linked, "沉淀的价目没有进司机的规则 —— 下次匹配不到，等于没沉淀"
    # 下次同样的一单**自动带价**（这就是"沉淀"的意义）
    q = freight_pricing.quote_for(db, _order(db, addr=addr, driver=driver), category_id=cat.id)
    assert q.matched is not None and q.matched.fee == Decimal("88.50")


def test_手动定价不改异常标记(db_session, users, client, token_dispatcher):
    db = db_session
    headers = auth_headers(token_dispatcher)
    order = _order(db, driver=_driver(db, "13900000009", "司机丙"))
    db.commit()
    r = client.post(
        f"/api/v1/orders/{order.id}/price-freight",
        json={"freight_fee": "10", "save_template": False},
        headers=headers,
    )
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Order, order.id).is_exception is False, "定价是待办，不是业务异常"


# ---------------------------------------------------------------- ④ 按分类给司机算钱


def test_按分类定价取这一单的分类():
    rule = driver_pay.PayRule(
        name="分类计价",
        piece_mode="category",
        by_category=((1, Decimal("50"), Decimal("0")), (2, Decimal("80"), Decimal("0"))),
    )
    assert driver_pay.order_pay(rule, freight_fee="0", category_id=1).piece == Decimal("50.00")
    assert driver_pay.order_pay(rule, freight_fee="0", category_id=2).piece == Decimal("80.00")
    # 没有分类 / 那一类没定价 → **不算**（不许拿统一价兜底：那会让"按分类"看起来生效了）
    missed = driver_pay.order_pay(rule, freight_fee="0", category_id=None)
    assert missed.piece == Decimal("0.00") and missed.category_unmatched is True


def test_按分类的规则算有按单应付():
    rule = driver_pay.PayRule(piece_mode="category", by_category=((1, Decimal("50"), Decimal("0")),))
    assert rule.has_per_order_pay is True, "否则派单快照写成 SALARY → 送达连账单都不生成"
    assert "按分类定价" in rule.describe({1: "蔬菜"})


def test_快照带得走按分类表():
    rule = driver_pay.PayRule(piece_mode="category", by_category=((3, Decimal("66"), Decimal("5")),))
    back = driver_pay.rule_from_snapshot(driver_pay.rule_to_snapshot(rule))
    assert back is not None and back.piece_mode == "category"
    assert back.by_category == ((3, Decimal("66.00"), Decimal("5.00")),)
    o = Order(order_no="SOX", status=OrderStatus.DELIVERED, order_date=date(2026, 9, 21),
              driver_billing_mode_snapshot="PIECE", freight_fee=Decimal("0"),
              freight_category_id=3, driver_rule_snapshot=driver_pay.rule_to_snapshot(rule))
    assert driver_pay.pay_for_order(o).piece == Decimal("66.00")


def test_待定价过滤在两条查询路径上都生效(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """`GET /orders?unpriced=true` 的**行为**（2026-09-21 真机抓到的静默 bug）。

    `list_orders` 里有**两套互不相干**的查询构造：派单员带搜索词那条用 `stmt`，
    普通列表那条用 `q` —— 同一个过滤条件要各写一遍。`unpriced` 一开始只加在前者上，
    于是**待定价页（不带 q）返回了全部订单**：页面上写着"这些单已经派出去了、但还没有运费"，
    用户照着核对时看到的却是一堆有运费、甚至已撤销的单。
    ⚠️ 当时静态检查（`_check_freight_pricing.py`）只断言「参数存在」—— 一路绿灯。
    所以这里断言的是**返回了什么**，两条路径都测。
    """
    d = _driver(db_session, phone="13900000091", name="待定价司机")
    uniq = _uniq("ADDR")
    priced = _order(db_session, addr=f"{uniq}-有运费", driver=d)
    priced.freight_fee = Decimal("50")
    blank = _order(db_session, addr=f"{uniq}-没运费", driver=d)
    never = _order(db_session, addr=f"{uniq}-还没派", driver=None)
    dead = _order(db_session, addr=f"{uniq}-已撤销", driver=d)
    dead.status = OrderStatus.CANCELLED
    db_session.flush()

    def listed(path: str) -> set[int]:
        r = client.get(path, headers=auth_headers(token_dispatcher))
        assert r.status_code == 200, r.text
        return {int(o["id"]) for o in r.json()}

    # ① 待定价页走的就是这条（**不带 q** —— 原来漏的就是它）
    got = listed("/api/v1/orders?unpriced=true&limit=200")
    assert blank.id in got, "已派单 + 没运费 = 待定价，必须在列表里"
    assert priced.id not in got, "有运费的单不是待定价"
    assert never.id not in got, "还没派出去的单不是待定价（连司机都没有）"
    assert dead.id not in got, "撤销的单不是待定价"

    # ② 带搜索词那条路径：同一个口径（修一条漏一条正是这个 bug 的形状）
    got_q = listed(f"/api/v1/orders?unpriced=true&q={uniq}&limit=200")
    assert blank.id in got_q
    assert priced.id not in got_q and never.id not in got_q and dead.id not in got_q


# ---------------------------------------------------------------- 小工具
