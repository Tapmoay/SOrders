"""承运运费的**来源凭据**（freight provenance）—— R4-11。

用户 2026-09-27 拍板（§6）：「**① §6 做。**」并给了五条退出条件 P1-02a…e。
这一份用例钉的是**运行时**那三件（⛔ 静态判据只能证明"代码写了"）：

| 退出条件 | 这一份怎么证 |
| --- | --- |
| P1-02b Write Atomicity | 三个写入点**各自**跑一遍：金额与凭据**同一行、同一次决定**都落下来 |
| P1-02c Provenance Completeness | 快照能恢复定价来源 / 计价方式 / 契约身份与版本 / 当时算出来多少 |
| P1-02d Legacy Safety | 老单（这一列为 NULL）**照常读、照常改价**，不会被静默改写成别的东西 |
| P1-02e Reverse Verification | 见 `_tools/qa/_reverse_verify_pricing_provenance.py`（5 种破坏各自报红） |

⛔ 本轮**只补事实记录，不改任何算法**：所以这些用例同时断言**金额一分没变**
（用户 §14：风险 A「记录事实失败」与风险 B「金额变化」不许混在一起排查）。
"""
from __future__ import annotations

import json
import uuid

from tests.conftest import auth_headers


def _mk_driver(client, h, name: str = "来源凭据探针司机") -> int:
    phone = "13" + uuid.uuid4().hex[:9].translate(str.maketrans("abcdef", "012345"))
    r = client.post(
        "/api/v1/users",
        json={"phone": phone, "password": "pass12345", "full_name": name, "role": "driver"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _mk_order(client, h, **over) -> int:
    payload = {
        "shipper_id": 2,
        "lines": [{"product_name_snapshot": "凭据探针货", "quantity": 1,
                   "unit_price": "100", "line_total": "100"}],
        "address_detail": "凭据探针路 1 号",
    }
    payload.update(over)
    r = client.post("/api/v1/orders", json=payload, headers=h)
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _snapshot(db_session, order_id: int) -> dict:
    from app.models import Order

    db_session.expire_all()
    o = db_session.get(Order, order_id)
    assert o is not None
    return json.loads(o.freight_rule_snapshot) if o.freight_rule_snapshot else {}


def _fee(db_session, order_id: int):
    from app.models import Order

    db_session.expire_all()
    return db_session.get(Order, order_id).freight_fee


def test_派单带运费时同时写下来源凭据(client, db_session, token_dispatcher):
    """写入点 ②：派单。金额与凭据必须**同一次决定**都落下来。"""
    h = auth_headers(token_dispatcher)
    did = _mk_driver(client, h)
    oid = _mk_order(client, h)

    r = client.post(f"/api/v1/orders/{oid}/assign",
                    json={"driver_id": did, "freight_fee": "120"}, headers=h)
    assert r.status_code in (200, 201), r.text

    o = None
    from app.models import Order
    db_session.expire_all()
    o = db_session.get(Order, oid)
    assert o.freight_fee == o.freight_fee.quantize(o.freight_fee)  # 占位：下面断言具体值
    assert str(o.freight_fee) == "120.00"
    snap = _snapshot(db_session, oid)
    assert snap, "派单写了金额却没写来源凭据 —— 这正是 R4-09 审计查出来的那个缺口"
    # P1-02c：五样东西都要能恢复
    assert snap["source"] == "assign"
    assert snap["fee"] == "120.00"
    assert snap["pricing"]["kind"]
    assert snap["pricing"]["contract"]["name"]
    assert snap["pricing"]["contract"]["version"] >= 1
    assert snap["category"]["id"] is None
    # 金额与凭据**同生**：不存在"有金额没凭据"
    assert o.freight_rule_snapshot is not None


def test_手动定价把那条价目也记进凭据(client, db_session, token_dispatcher):
    """写入点 ①：手动定价（+ 沉淀成价目）—— `rule.origin` 必须是 "saved"。"""
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, h)

    r = client.post(f"/api/v1/orders/{oid}/price-freight",
                    json={"freight_fee": "135", "save_template": True,
                          "template_name": "凭据探针价目", "price_name": "探针价"},
                    headers=h)
    assert r.status_code in (200, 201), r.text
    assert str(_fee(db_session, oid)) == "135.00"

    snap = _snapshot(db_session, oid)
    assert snap["source"] == "manual"
    assert snap["fee"] == "135.00"
    assert snap["rule"] is not None, "手动定价沉淀了价目，凭据里必须记着是哪一条"
    assert snap["rule"]["origin"] == "saved"
    assert snap["rule"]["template_id"], "价目身份是这条缺口的核心 —— 不许空"
    assert snap["rule"]["fee"] == "135.00", "价目**当时**的金额也要留下（改价之后才对得上）"
    assert snap["rule"]["template_name"] == "凭据探针价目"


def test_事后补录运费也写下来源凭据(client, db_session, token_dispatcher):
    """写入点 ③：事后补录/改运费。"""
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, h)

    r = client.post(f"/api/v1/orders/{oid}/freight", json={"freight_fee": "88"}, headers=h)
    assert r.status_code in (200, 201), r.text
    assert str(_fee(db_session, oid)) == "88.00"

    snap = _snapshot(db_session, oid)
    assert snap["source"] == "adjust"
    assert snap["fee"] == "88.00"


def test_清空运费时来源凭据一起清空(client, db_session, token_dispatcher):
    """不变量：**同生共死** —— "金额没有了、凭据还挂着"会让下一个人以为这笔钱还在。"""
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, h)
    assert client.post(f"/api/v1/orders/{oid}/freight",
                       json={"freight_fee": "88"}, headers=h).status_code in (200, 201)
    assert _snapshot(db_session, oid), "前提：先得有一份凭据"

    r = client.post(f"/api/v1/orders/{oid}/freight", json={"freight_fee": None}, headers=h)
    assert r.status_code in (200, 201), r.text

    from app.models import Order
    db_session.expire_all()
    o = db_session.get(Order, oid)
    assert o.freight_fee is None
    assert o.freight_rule_snapshot is None, "金额清空了、凭据还在 —— 不变量被破坏"


def test_派单不带运费时不碰已有的来源凭据(client, db_session, token_dispatcher):
    """⚠️ 这是那个历史缺陷（审计 H3）的同一条口径：**没传 ≠ 清空**。"""
    h = auth_headers(token_dispatcher)
    did = _mk_driver(client, h)
    oid = _mk_order(client, h)
    assert client.post(f"/api/v1/orders/{oid}/price-freight",
                       json={"freight_fee": "150"}, headers=h).status_code in (200, 201)
    before = _snapshot(db_session, oid)

    r = client.post(f"/api/v1/orders/{oid}/assign", json={"driver_id": did}, headers=h)
    assert r.status_code in (200, 201), r.text

    assert str(_fee(db_session, oid)) == "150.00", "没传运费不该把已有的运费清掉"
    assert _snapshot(db_session, oid) == before, "金额没动，凭据也不该动"


def test_老单没有来源凭据也照常读照常改价(client, db_session, token_dispatcher):
    """P1-02d **Legacy Safety**：R4-11 之前落库的单这一列是 NULL —— 不回填、不报错、不篡改。"""
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, h)
    assert client.post(f"/api/v1/orders/{oid}/freight",
                       json={"freight_fee": "66"}, headers=h).status_code in (200, 201)

    # 把那两列**按老数据的形状**恢复：金额在、来源没有（⛔ 只许这样造，不许反过来倒推）
    from app.models import Order
    db_session.expire_all()
    o = db_session.get(Order, oid)
    o.freight_rule_snapshot = None
    db_session.commit()

    r = client.get(f"/api/v1/orders/{oid}", headers=h)
    assert r.status_code == 200, r.text
    assert str(r.json()["freight_fee"]) in ("66.00", "66.0", "66"), r.text
    assert _snapshot(db_session, oid) == {}, "读一次不该把凭据凭空补出来"

    # 老单还能继续被正常改价（改完就**有**凭据了 —— 新的决定、新的凭据）
    r = client.post(f"/api/v1/orders/{oid}/freight", json={"freight_fee": "77"}, headers=h)
    assert r.status_code in (200, 201), r.text
    assert str(_fee(db_session, oid)) == "77.00"
    assert _snapshot(db_session, oid)["fee"] == "77.00"


def test_凭据里没有金额的数字对不上时读出来是安全的(db_session):
    """坏 JSON 不许让订单详情 500（与 driver_pay.rule_from_snapshot 同一条口径）。"""
    from app.services.order_money import freight_provenance_of

    class _O:
        freight_rule_snapshot = "{这不是 JSON"

    assert freight_provenance_of(_O()) == {}
