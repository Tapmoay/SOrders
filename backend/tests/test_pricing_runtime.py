"""承运运费的**唯一组装点**（Composition Root）与 Canary —— R4-20。

用户 §8：
> 「必须在核心的唯一组装点切换。不要在 orders.py / driver_pay.py / accounting_service.py
>  分别加 if extension_enabled，否则你刚刚建立的 R4 又开始腐烂。」

用户 §9：
> 「Canary 最重要的一条：**同一订单不能在运行过程中换算法**。」

这一份钉四件事：
| # | 钉什么 |
| --- | --- |
| ① | 策略是**纯函数**（按订单编号分桶）—— 同一张单永远同一个答案 |
| ② | **关掉时**与改造前一字不差（金额、快照形状都一样） |
| ③ | **开满时**金额由**契约**确认，快照里如实写 `agreed` / 契约身份 |
| ④ | 派单员改过价时**以人为准**，但两个数都留下（⛔ 换"算钱的源"不是这一格的事） |
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from tests.conftest import auth_headers

import app.config as app_config


def _pin_canary(monkeypatch, percent: int) -> None:
    """把 Canary 比例钉成 `percent`。

    ⚠️ `get_settings` 是 `@lru_cache` 的，所以**不能**靠改环境变量（进程里已经缓存过了）；
    钉的是 `app.config.get_settings` 这个**函数**，而组装点是**在函数体内**import 它的，
    所以钉得住（这也正是"配置只在一处读"带来的好处）。
    """
    class _S:
        freight_pricing_canary_percent = percent

    monkeypatch.setattr(app_config, "get_settings", lambda: _S())


def _mk_driver(client, h, name: str = "组装点探针司机") -> int:
    phone = "13" + uuid.uuid4().hex[:9].translate(str.maketrans("abcdef", "012345"))
    r = client.post("/api/v1/users",
                    json={"phone": phone, "password": "pass12345", "full_name": name, "role": "driver"},
                    headers=h)
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _seed_price_world(db_session, *, address: str, fee: str, driver_id: int) -> int:
    """给这位司机铺一份**真实形状**的价目世界：一条价目 + 一份规则 + 规则勾上它。

    ⛔ 为什么必须铺：契约能不能算，取决于**核心读出来的候选集**
    （`freight_snapshot_of` → `driver_template_ids` → 这个司机的规则勾了哪些价目）。
    司机没挂规则 / 规则没勾价目 ⇒ 契约算不出来 ⇒ 组装点**如实退回旧路**（那是对的行为，
    但测"走契约"就得先把世界铺好）。
    """
    import datetime
    from decimal import Decimal as D

    from app.models import (
        DriverBillingRule, DriverBillingRuleTemplate, FreightCategory, FreightTemplate,
        FreightTemplateCategory, ShipperAddress, User,
    )

    addr = ShipperAddress(shipper_id=1, detail_address=address, receiver_name="", phone="")
    db_session.add(addr)
    # ⚠️ 分类名是 **UNIQUE** 的，而这个库是整个 worker 共用的（同一份测试库）——
    #    同名再建一次会 IntegrityError。有一次就用那一次（"组装点蔬菜"本来是同一个意思）。
    cat = db_session.query(FreightCategory).filter_by(name="组装点蔬菜").first()
    if cat is None:
        cat = FreightCategory(name="组装点蔬菜", sort_order=0)
        db_session.add(cat)
    db_session.flush()
    tmpl = FreightTemplate(name="组装点价目", price_name="", fee=D(fee),
                           route_id=addr.id, to_place=address, from_place="")
    db_session.add(tmpl)
    db_session.flush()
    db_session.add(FreightTemplateCategory(template_id=tmpl.id, category_id=cat.id))
    rule = DriverBillingRule(name="组装点规则", salary=D("0"), piece_amount=D("0"),
                             commission_rate=D("0"), vehicle_type=None, is_deleted=False)
    db_session.add(rule)
    db_session.flush()
    db_session.add(DriverBillingRuleTemplate(rule_id=rule.id, template_id=tmpl.id))
    u = db_session.get(User, driver_id)
    assert u is not None
    u.driver_rule_id = rule.id
    db_session.commit()
    return int(cat.id)


def _mk_order(client, h, **over) -> int:
    payload = {
        "shipper_id": 2,
        "lines": [{"product_name_snapshot": "组装点探针货", "quantity": 1,
                   "unit_price": "100", "line_total": "100"}],
        "address_detail": "组装点探针路 1 号",
    }
    payload.update(over)
    r = client.post("/api/v1/orders", json=payload, headers=h)
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _snapshot(db_session, order_id: int) -> dict:
    import json

    from app.models import Order

    db_session.expire_all()
    o = db_session.get(Order, order_id)
    assert o is not None
    return json.loads(o.freight_rule_snapshot) if o.freight_rule_snapshot else {}


def _fee(db_session, order_id: int):
    from app.models import Order

    db_session.expire_all()
    return db_session.get(Order, order_id).freight_fee


# ---------------------------------------------------------------- ① 纯函数

def test_策略只由订单编号与比例决定():
    """⛔ 纯函数：同样的输入永远同样的答案（同一张单不会在两次调用之间换算法）。"""
    from app.core.pricing_runtime import KIND_CONTRACT, KIND_LEGACY, policy_for

    assert policy_for(1, 0) == KIND_LEGACY, "0% = 关（缺省必须是关）"
    assert policy_for(1, 100) == KIND_CONTRACT, "100% = 全走契约"
    for oid in range(1, 60):
        first = policy_for(oid, 37)
        assert all(policy_for(oid, 37) == first for _ in range(3)), "同一张单三次问出两个答案"
    hits = sum(1 for oid in range(100) if policy_for(oid, 37) == KIND_CONTRACT)
    assert hits == 37, "37% 应当正好命中 37 个桶，实际 " + str(hits)


def test_订单编号缺失时按旧路走():
    """⛔ 拿不到订单编号时**不许**走契约 —— 那正是"这次请求带什么就是什么"的形状。"""
    from app.core.pricing_runtime import KIND_LEGACY, policy_for

    assert policy_for(None, 99) == KIND_LEGACY


# ---------------------------------------------------------------- ② 关掉 = 一字不差

def test_关掉时行为与改造前一致(client, db_session, token_dispatcher, monkeypatch):
    _pin_canary(monkeypatch, 0)
    h = auth_headers(token_dispatcher)
    did = _mk_driver(client, h)
    oid = _mk_order(client, h)
    r = client.post(f"/api/v1/orders/{oid}/assign",
                    json={"driver_id": did, "freight_fee": "120"}, headers=h)
    assert r.status_code in (200, 201), r.text
    assert str(_fee(db_session, oid)) == "120.00"
    snap = _snapshot(db_session, oid)
    assert snap["pricing"]["kind"] == "legacy_client"
    assert snap["pricing"]["contract"] == {"name": "FreightPricingCore", "version": 1}
    assert "agreed" not in snap["pricing"], "没走契约时不该有「算得一样不一样」这一栏"


# ---------------------------------------------------------------- ③ 开满 = 契约确认

def test_开满时金额由契约确认并如实记进凭据(client, db_session, token_dispatcher, monkeypatch):
    _pin_canary(monkeypatch, 100)
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, h)
    did = _mk_driver(client, h)
    cat_id = _seed_price_world(db_session, address="组装点探针路 1 号", fee="135", driver_id=did)
    assert client.post(f"/api/v1/orders/{oid}/price-freight",
                       json={"freight_fee": "135", "category_id": cat_id}, headers=h
                       ).status_code in (200, 201)
    # 派单时界面带的数就是价目那个数 → 契约应当**agree**
    r = client.post(f"/api/v1/orders/{oid}/assign",
                    json={"driver_id": did, "freight_fee": "135"}, headers=h)
    assert r.status_code in (200, 201), r.text

    assert str(_fee(db_session, oid)) == "135.00"
    snap = _snapshot(db_session, oid)
    p = snap["pricing"]
    assert p["kind"] == "freight_template", "开满时这一单必须走契约"
    assert p["contract"] == {"name": "PricingContract", "version": 2}, p["contract"]
    assert p["agreed"] is True and p["override"] is False, p


# ---------------------------------------------------------------- ④ 人改过价 = 以人为准

def test_派单员改过价时以人为准但两个数都留下(client, db_session, token_dispatcher, monkeypatch):
    """⛔ 用户 §14：这一格**只补"记事实"** —— 换"算钱的源"是 ⑧ Full Cutover 的事。"""
    _pin_canary(monkeypatch, 100)
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, h)
    did = _mk_driver(client, h)
    cat_id = _seed_price_world(db_session, address="组装点探针路 1 号", fee="135", driver_id=did)
    assert client.post(f"/api/v1/orders/{oid}/price-freight",
                       json={"freight_fee": "135", "category_id": cat_id}, headers=h
                       ).status_code in (200, 201)
    r = client.post(f"/api/v1/orders/{oid}/assign",
                    json={"driver_id": did, "freight_fee": "150"}, headers=h)
    assert r.status_code in (200, 201), r.text

    assert str(_fee(db_session, oid)) == "150.00", "⛔ 以人为准：人的那个数必须原样落库"
    p = _snapshot(db_session, oid)["pricing"]
    assert p["agreed"] is False and p["override"] is True, p
    assert "135" in p["note"] and "150" in p["note"], "两个数都要留在说明里：" + str(p.get("note"))


# ---------------------------------------------------------------- ⑤ 算不出来 = 退回旧路

def test_契约算不出来时退回旧路不让派单失败(client, db_session, token_dispatcher, monkeypatch):
    """来源凭据是**记录**，不是**前置条件** —— 契约出错绝不能让派单失败。"""
    _pin_canary(monkeypatch, 100)
    import app.core.pricing_runtime as rt

    monkeypatch.setattr(rt, "contract_quote", lambda db, order, *, driver_id:
                        rt.ContractQuote(ok=False, reason=rt.REASON_ERROR, detail="boom"))
    h = auth_headers(token_dispatcher)
    did = _mk_driver(client, h)
    oid = _mk_order(client, h)
    r = client.post(f"/api/v1/orders/{oid}/assign",
                    json={"driver_id": did, "freight_fee": "120"}, headers=h)
    assert r.status_code in (200, 201), "⛔ 契约算不出来不该让派单失败"
    assert str(_fee(db_session, oid)) == "120.00"
    p = _snapshot(db_session, oid)["pricing"]
    assert p["kind"] == "legacy_client", p
    assert p["reason"] == "error", p
    assert "契约没算出结论" in p.get("note", ""), "退回旧路这件事必须**写在凭据里**：" + str(p)


# ---------------------------------------------------------------- ⑥ 原因码说得出是哪一种

def test_候选集为空时原因码说得出为什么(client, db_session, token_dispatcher, monkeypatch):
    """⭐ 生产上最常见的那一支（价目表压根没配）—— 它必须**自己说清是哪一种**。

    R4-21 在生产上拿到的是第一版那句笼统的"契约没算出结论（缺料或多条价目）"，
    而我**必须去查库才知道**到底是"没配规则"还是"同一档多条" —— 那两种的修法完全不同。
    """
    _pin_canary(monkeypatch, 100)
    h = auth_headers(token_dispatcher)
    did = _mk_driver(client, h)          # 这个司机**没挂规则**（_seed_price_world 不调用）
    oid = _mk_order(client, h)
    r = client.post(f"/api/v1/orders/{oid}/assign",
                    json={"driver_id": did, "freight_fee": "120"}, headers=h)
    assert r.status_code in (200, 201), r.text
    p = _snapshot(db_session, oid)["pricing"]
    assert p["kind"] == "legacy_client", p
    assert p["reason"] == "no_candidates", p
    # 人话那一栏也要能指着**这一步**：这个司机没挂规则 / 规则没勾价目
    assert "没挂计费规则" in p["note"] or "没勾价目" in p["note"], p["note"]
