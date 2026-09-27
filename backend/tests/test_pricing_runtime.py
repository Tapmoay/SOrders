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


def _set_category_only(db_session, order_id: int, cat_id: int) -> None:
    """只把「这一单算哪类货」铺上，⛔ **刻意不走 price-freight**。

    为什么（R4-26 决策冻结之后才知道）：`price-freight` 会写出**一次真实的计价决策**，
    而那一刻还没有司机 ⇒ 契约看到的候选集是**全部价目**（不是这个司机的）⇒ 多半算不出来 ⇒
    如实退回旧路 ⇒ **这一单的来源就此冻结在 legacy**，后面派单本该走契约也不再走。
    这一格要测的是**派单那一次**决策，所以分类用夹具直接给。
    （"提前冻住"那件事本身由 `test_派单前先手动定价会把来源提前冻住` 专门钉。）
    """
    from app.models import Order

    db_session.expire_all()
    o = db_session.get(Order, order_id)
    assert o is not None
    o.freight_category_id = cat_id
    db_session.commit()
    db_session.expire_all()


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
    _set_category_only(db_session, oid, cat_id)
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
    _set_category_only(db_session, oid, cat_id)
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

# ---------------------------------------------------------------- ⑦ 冻结（⑧-a 出口条件 ③）

def test_已经定过的来源只认得出两种取值():
    """读「这张单已经定过什么」只走一处，且**认不出的取值当没定过**。

    ⛔ 不认识的 kind 不许拿去冻结后面所有写入 —— 与 freight_provenance_of 对坏快照的口径一致。
    """
    import json
    from types import SimpleNamespace

    from app.services.order_money import freight_kind_of

    def o(snap):
        return SimpleNamespace(freight_rule_snapshot=snap)

    assert freight_kind_of(o(None)) is None
    assert freight_kind_of(o("")) is None
    assert freight_kind_of(o("{坏掉的 JSON")) is None
    assert freight_kind_of(o(json.dumps({"source": "assign"}))) is None
    assert freight_kind_of(o(json.dumps({"pricing": {}}))) is None
    assert freight_kind_of(o(json.dumps({"pricing": {"kind": "未来才有的 kind"}}))) is None
    assert freight_kind_of(o(json.dumps({"pricing": {"kind": "legacy_client"}}))) == "legacy_client"
    assert freight_kind_of(o(json.dumps({"pricing": {"kind": "freight_template"}}))) == "freight_template"


def test_没定过来源的单仍然按比例抽签():
    """⛔ 冻结不许把 Canary 变成「永远关着」：没定过的单照样按比例走。"""
    from app.core.pricing_runtime import KIND_CONTRACT, KIND_LEGACY, policy_for

    assert policy_for(1, 0, frozen=None) == KIND_LEGACY
    assert policy_for(1, 100, frozen=None) == KIND_CONTRACT
    # 冻结参数给了「认不出的东西」时**不许静默生效** —— 照样按比例
    assert policy_for(1, 100, frozen="") == KIND_CONTRACT
    assert policy_for(1, 100, frozen="某个未来的 kind") == KIND_CONTRACT


def test_先形成旧路之后把比例开到满_这次计价仍然是旧路(client, db_session, token_dispatcher, monkeypatch):
    """⛔ 用户点名的第 1 个实验：**同一个 Pricing Decision 不因 Canary 配置变化而改变来源**。

    比例 0 → 第一次派单形成 legacy_client；
    比例改成 100 → 同一张单**再次**写入 → 来源必须仍然是 legacy_client。

    ⚠️ 不冻结的话，这里会变成 freight_template —— 同一张单的「钱凭什么」跟着配置变了一次。
    """
    h = auth_headers(token_dispatcher)
    _pin_canary(monkeypatch, 0)
    did = _mk_driver(client, h)
    oid = _mk_order(client, h)
    r = client.post(f"/api/v1/orders/{oid}/assign",
                    json={"driver_id": did, "freight_fee": "120"}, headers=h)
    assert r.status_code in (200, 201), r.text
    assert _snapshot(db_session, oid)["pricing"]["kind"] == "legacy_client"

    _pin_canary(monkeypatch, 100)                    # ← 观察期里比例被调了
    r = client.post(f"/api/v1/orders/{oid}/freight",
                    json={"freight_fee": "130"}, headers=h)
    assert r.status_code in (200, 201), r.text
    p = _snapshot(db_session, oid)["pricing"]
    assert p["kind"] == "legacy_client", "⛔ 比例调到 100 之后，这张单换了来源：" + str(p)
    assert p["contract"] == {"name": "FreightPricingCore", "version": 1}, p["contract"]


def test_先形成契约之后把比例关到零_这次计价仍然是契约(client, db_session, token_dispatcher, monkeypatch):
    """⛔ 用户点名的第 2 个实验（反方向）。

    比例 100 → 第一次派单形成 freight_template；
    比例改成 0 → 同一张单**再次**写入 → 来源必须仍然是 freight_template，
    而且**契约身份也一并保住**（pricing.contract 仍是 PricingContract v2）。
    """
    h = auth_headers(token_dispatcher)
    _pin_canary(monkeypatch, 100)
    oid = _mk_order(client, h)
    did = _mk_driver(client, h)
    cat_id = _seed_price_world(db_session, address="组装点探针路 1 号", fee="135", driver_id=did)
    _set_category_only(db_session, oid, cat_id)
    r = client.post(f"/api/v1/orders/{oid}/assign",
                    json={"driver_id": did, "freight_fee": "135"}, headers=h)
    assert r.status_code in (200, 201), r.text
    assert _snapshot(db_session, oid)["pricing"]["kind"] == "freight_template"

    _pin_canary(monkeypatch, 0)                      # ← 比例被调回 0（甚至整个关掉）
    r = client.post(f"/api/v1/orders/{oid}/freight",
                    json={"freight_fee": "150"}, headers=h)
    assert r.status_code in (200, 201), r.text
    p = _snapshot(db_session, oid)["pricing"]
    assert p["kind"] == "freight_template", "⛔ 比例关到 0 之后，这张单换了来源：" + str(p)
    assert p["contract"] == {"name": "PricingContract", "version": 2}, p["contract"]
    assert p["agreed"] is False and p["override"] is True, "冻结的是**来源**，不是金额：" + str(p)
    assert str(_fee(db_session, oid)) == "150.00", "⛔ 以人为准：人的那个数仍然必须原样落库"


def test_运费被清空后再定价_按当时的比例重新抽签(client, db_session, token_dispatcher, monkeypatch):
    """⭐ 一条**明确的边界**（不是漏洞，但要写下来）：把运费清成 null 时凭据**一起清空**
    （不变量 2：同生共死）。凭据都没了，下一次定价就是**新的一次决策** —— 按**当时**的比例抽签。

    ⛔ 这条边界必须写死，否则将来有人会以为「冻结」是永久的、
    然后拿一张清空过的单去解释为什么来源变了。
    """
    h = auth_headers(token_dispatcher)
    _pin_canary(monkeypatch, 0)
    oid = _mk_order(client, h)
    did = _mk_driver(client, h)
    _seed_price_world(db_session, address="组装点探针路 1 号", fee="135", driver_id=did)
    r = client.post(f"/api/v1/orders/{oid}/assign",
                    json={"driver_id": did, "freight_fee": "120"}, headers=h)
    assert r.status_code in (200, 201), r.text
    assert _snapshot(db_session, oid)["pricing"]["kind"] == "legacy_client"

    # 清空运费 → 凭据一起清空（不变量 2）
    r = client.post(f"/api/v1/orders/{oid}/freight",
                    json={"freight_fee": None}, headers=h)
    assert r.status_code in (200, 201), r.text
    assert _snapshot(db_session, oid) == {}, "凭据必须跟着金额一起清空"
    assert _fee(db_session, oid) is None

    _pin_canary(monkeypatch, 100)
    r = client.post(f"/api/v1/orders/{oid}/freight",
                    json={"freight_fee": "135"}, headers=h)
    assert r.status_code in (200, 201), r.text
    p = _snapshot(db_session, oid)["pricing"]
    assert p["kind"] == "freight_template", "清空过 = 新的一次决策，按当时的比例：" + str(p)


def test_派单前先手动定价会把来源提前冻住_这是有意的(client, db_session, token_dispatcher, monkeypatch):
    """⭐ 一条**一定会被问到**的后果，写死在判据里，⛔ 不留给人去猜。

    比例 100、价目世界也铺好了，但派单员**先手动定价、后派单**：
    手动定价那一刻**还没有司机**，契约看到的候选集是**全部价目**（不是这个司机的）——
    于是多半算不出来 ⇒ 如实退回旧路（reason 非 ok）⇒ **这一单的来源就此冻在 legacy**。
    等到派单那一刻（本来该走契约），它仍然是 legacy。

    ⛔ 这不是 bug：不变量是「同一张单不换来源」，而「先手动定价」确实已经形成了一次计价事实。
    ⚠️ 但它有一条**必须知道**的生产后果：
       实际走契约的比例会**低于**配置的比例 ——
       ⑧-a 的观察窗口必须**按来源拆开看**，不能拿「配了 30% 就该有 30% 走契约」当判据。
    """
    h = auth_headers(token_dispatcher)
    _pin_canary(monkeypatch, 100)
    oid = _mk_order(client, h)
    did = _mk_driver(client, h)
    cat_id = _seed_price_world(db_session, address="组装点探针路 1 号", fee="135", driver_id=did)

    # ① 先手动定价（此刻 driver_id 还是 None）
    r = client.post(f"/api/v1/orders/{oid}/price-freight",
                    json={"freight_fee": "135", "category_id": cat_id}, headers=h)
    assert r.status_code in (200, 201), r.text
    first = _snapshot(db_session, oid)["pricing"]
    assert first["kind"] == "legacy_client", first
    assert first["reason"] in ("no_match", "ambiguous", "no_candidates"), \
        "⛔ 必须是「算不出来」而不是「没轮到我」——两者混起来就看不出 Canary 覆盖了多少：" + str(first)

    # ② 再派单：这一次本该走契约
    r = client.post(f"/api/v1/orders/{oid}/assign",
                    json={"driver_id": did, "freight_fee": "135"}, headers=h)
    assert r.status_code in (200, 201), r.text
    assert _snapshot(db_session, oid)["pricing"]["kind"] == "legacy_client", \
        "提前冻住：已经形成过的来源不许在派单时被换掉"


def test_每一条决策都带得出原因码(client, db_session, token_dispatcher, monkeypatch):
    """⛔ ⑧-a 出口条件 ⑦：**允许退回，但不许没有记录地退回**。

    三种情形各走一遍，看组装点有没有哪一次给出空原因码（空 = 库里少一格 = 静默）：
      ① 不在 canary 桶里（比例 0）—— 也要留 ok，⛔ 不是「没记录」；
      ② 在桶里、契约算得出来；
      ③ 在桶里、契约算不出来（这个司机没挂规则）—— 退回**必须带得出是哪一种**。
    """
    from app.core.pricing_runtime import REASON_TEXT

    h = auth_headers(token_dispatcher)

    _pin_canary(monkeypatch, 0)
    oid = _mk_order(client, h)
    did = _mk_driver(client, h)
    r = client.post(f"/api/v1/orders/{oid}/assign",
                    json={"driver_id": did, "freight_fee": "120"}, headers=h)
    assert r.status_code in (200, 201), r.text
    p1 = _snapshot(db_session, oid)["pricing"]
    assert p1.get("reason"), "① 不在桶里也要留下原因码（ok）：" + str(p1)
    assert p1["reason"] in REASON_TEXT, p1

    _pin_canary(monkeypatch, 100)
    oid2 = _mk_order(client, h)
    did2 = _mk_driver(client, h)
    cat_id = _seed_price_world(db_session, address="组装点探针路 1 号", fee="135", driver_id=did2)
    _set_category_only(db_session, oid2, cat_id)
    r = client.post(f"/api/v1/orders/{oid2}/assign",
                    json={"driver_id": did2, "freight_fee": "135"}, headers=h)
    assert r.status_code in (200, 201), r.text
    p2 = _snapshot(db_session, oid2)["pricing"]
    assert p2["kind"] == "freight_template", p2
    assert p2.get("reason") in REASON_TEXT, "② " + str(p2)

    oid3 = _mk_order(client, h)
    did3 = _mk_driver(client, h)          # 这个司机**没挂规则** ⇒ 契约必然算不出来
    r = client.post(f"/api/v1/orders/{oid3}/assign",
                    json={"driver_id": did3, "freight_fee": "120"}, headers=h)
    assert r.status_code in (200, 201), r.text
    p3 = _snapshot(db_session, oid3)["pricing"]
    assert p3["kind"] == "legacy_client", p3
    assert p3["reason"] == "no_candidates", "③ 退回必须带得出是哪一种：" + str(p3)
    assert "契约没算出结论" in p3.get("note", ""), p3


def test_四种走法各自说得出走的是哪条路(client, db_session, token_dispatcher, monkeypatch):
    """⛔ R4-36（用户 2026-09-27 点名的语义坑）：**一个 kind 盖不住四件事**。

    `kind` 只回答「金额最终由谁产生」；「这一次是怎么走到那一步的」得由 `resolution` 回答。
四种各造一次，四个取值必须**各自出现**：

      not_in_canary  比例 0          —— 压根没去问契约
      contract       比例 100 + 铺好 —— 契约算出来了
      fallback       比例 100 + 没挂规则 —— 去了、没算出来、如实退回
      frozen         **已经定过来源的单再写一次** —— ⛔ 这一条以前与 not_in_canary 长得一模一样
    """
    from app.core.pricing_runtime import RESOLUTIONS

    h = auth_headers(token_dispatcher)

    # ① not_in_canary
    _pin_canary(monkeypatch, 0)
    a = _mk_order(client, h)
    da = _mk_driver(client, h)
    assert client.post(f"/api/v1/orders/{a}/assign",
                       json={"driver_id": da, "freight_fee": "120"}, headers=h).status_code in (200, 201)
    pa = _snapshot(db_session, a)["pricing"]
    assert pa["resolution"] == "not_in_canary", pa
    assert pa["kind"] == "legacy_client", pa

    # ② contract
    _pin_canary(monkeypatch, 100)
    b = _mk_order(client, h)
    db_ = _mk_driver(client, h)
    cat = _seed_price_world(db_session, address="组装点探针路 1 号", fee="135", driver_id=db_)
    _set_category_only(db_session, b, cat)
    assert client.post(f"/api/v1/orders/{b}/assign",
                       json={"driver_id": db_, "freight_fee": "135"}, headers=h).status_code in (200, 201)
    pb = _snapshot(db_session, b)["pricing"]
    assert pb["resolution"] == "contract", pb
    assert pb["kind"] == "freight_template", pb

    # ③ fallback
    c = _mk_order(client, h)
    dc = _mk_driver(client, h)          # 这个司机没挂规则 ⇒ 算不出来
    assert client.post(f"/api/v1/orders/{c}/assign",
                       json={"driver_id": dc, "freight_fee": "120"}, headers=h).status_code in (200, 201)
    pc = _snapshot(db_session, c)["pricing"]
    assert pc["resolution"] == "fallback", pc
    assert pc["kind"] == "legacy_client" and pc["reason"] == "no_candidates", pc

    # ④ frozen：把比例调到 0，对**已经定过来源的** c 再写一次
    _pin_canary(monkeypatch, 0)
    assert client.post(f"/api/v1/orders/{c}/freight",
                       json={"freight_fee": "130"}, headers=h).status_code in (200, 201)
    pc2 = _snapshot(db_session, c)["pricing"]
    assert pc2["resolution"] == "frozen", pc2
    assert pc2["kind"] == "legacy_client", pc2

    seen = {pa["resolution"], pb["resolution"], pc["resolution"], pc2["resolution"]}
    assert seen == set(RESOLUTIONS), "四个取值要各自出现：" + str(seen)


def test_冻结过的单_resolution_必须说得出是冻结而不是没抽中(client, db_session, token_dispatcher, monkeypatch):
    """⭐⭐ 这一条正是**生产上 T0/T1/T2 之前验不了的那个分辨点**（R4-34 实测踩到）。

    冻结住 ⇒ 沿用 legacy ⇒ 走旧路那一支；没冻住 ⇒ 比例已是 0、这单也不在桶里 ⇒ **同样**走旧路那一支。
两条路是同一支代码，`kind` 与 `reason` 写出来一模一样 ⇒ ⛔ 实验证明不了冻结。
⇒ 拆出 `resolution` 之后：冻住的是 `frozen`、没抽中的是 `not_in_canary`，**一眼分得开**。
    """
    h = auth_headers(token_dispatcher)

    # 对照组：**没有**冻结过的单，在比例 0 下写一次 ⇒ not_in_canary
    _pin_canary(monkeypatch, 0)
    fresh = _mk_order(client, h)
    d1 = _mk_driver(client, h)
    assert client.post(f"/api/v1/orders/{fresh}/assign",
                       json={"driver_id": d1, "freight_fee": "120"}, headers=h).status_code in (200, 201)
    p_fresh = _snapshot(db_session, fresh)["pricing"]
    assert p_fresh["resolution"] == "not_in_canary", p_fresh

    # 实验组：先在 100% 下**定过一次来源**（契约算不出来 ⇒ fallback），再调到 0 写第二次
    _pin_canary(monkeypatch, 100)
    frozen_oid = _mk_order(client, h)
    d2 = _mk_driver(client, h)          # 没挂规则 ⇒ 第一次必然是 fallback
    assert client.post(f"/api/v1/orders/{frozen_oid}/assign",
                       json={"driver_id": d2, "freight_fee": "120"}, headers=h).status_code in (200, 201)
    first = _snapshot(db_session, frozen_oid)["pricing"]
    assert first["resolution"] == "fallback", first

    _pin_canary(monkeypatch, 0)         # ← 比例换了（生产上 T1 做的就是这个）
    assert client.post(f"/api/v1/orders/{frozen_oid}/freight",
                       json={"freight_fee": "130"}, headers=h).status_code in (200, 201)
    second = _snapshot(db_session, frozen_oid)["pricing"]
    assert second["resolution"] == "frozen", "冻结的那一单必须是 frozen：" + str(second)
    assert second["kind"] == first["kind"], "来源不许变：" + str((first, second))
    assert second["resolution"] != p_fresh["resolution"], "⛔ 与「没抽中」必须是两个取值"


def test_拆单产生的子单是新的一次定价决策_不继承父单的来源(client, db_session, token_dispatcher, monkeypatch):
    """⭐⭐ **冻结的粒度**用一条可执行的边界钉死（用户 2026-09-27 §十一 要求「必须先定义」）。

    定义（同时写在 core/pricing_runtime.py 里，代码是权威）：

      · 冻结粒度 = **订单上的那一个「承运运费定价事实」**；
      · 「后续写入」（派单 / 改价 / 补录）是**同一次事实的修订** ⇒ 沿用原来源；
      · **新的订单 = 新的一次决策** ⇒ 按**当时**的策略走，⛔ 不继承别人的来源。

    拆单子单正好是后半句的试金石：split_order **不**给子单写 freight_fee / 快照，
    所以子单是从「没有定价事实」开始的 —— 这一条把「什么算新决策」从口头定义变成了判据。
    """
    h = auth_headers(token_dispatcher)

    _pin_canary(monkeypatch, 0)
    oid = _mk_order(client, h)
    assert client.post(f"/api/v1/orders/{oid}/price-freight",
                       json={"freight_fee": "120"}, headers=h).status_code in (200, 201)
    assert _snapshot(db_session, oid)["pricing"]["resolution"] == "not_in_canary", "父单先定一次价"

    r = client.post(f"/api/v1/orders/{oid}/split", json={"parts": [1, 1]}, headers=h)
    assert r.status_code in (200, 201), r.text
    kid = int(r.json()[0]["id"])

    # ⛔ 子单不许继承父单的运费与凭据
    assert _snapshot(db_session, kid) == {}, "子单不该带着父单的来源凭据"
    assert _fee(db_session, kid) is None, "子单不该继承父单的运费"

    did = _mk_driver(client, h)
    cat = _seed_price_world(db_session, address="组装点探针路 1 号", fee="135", driver_id=did)
    _set_category_only(db_session, kid, cat)
    _pin_canary(monkeypatch, 100)          # ← 策略变了
    assert client.post(f"/api/v1/orders/{kid}/assign",
                       json={"driver_id": did, "freight_fee": "135"}, headers=h).status_code in (200, 201)
    p = _snapshot(db_session, kid)["pricing"]
    assert p["resolution"] == "contract", "子单按**当时**的策略走，⛔ 不是继承父单的：" + str(p)
