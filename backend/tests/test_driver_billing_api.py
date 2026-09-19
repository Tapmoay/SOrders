"""司机计费规则：接口 + **钱走通了没有**（真下单 → 真派单 → 真送达 → 查账单金额）。

这一组测的是"改完之后账单会不会算错钱"，所以最后三条是完整链路：
派单（带运费）→ 司机接单 → 送达 → `driver_bills` 里的金额必须等于**手算的那个数**。
纯函数单测只能证明"算法对"，证明不了"送达那一刻真的调了这个算法"——
这个仓库里"算法对但接线错"的先例不止一次。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from app.models import DriverBillingRule, User
from tests.conftest import auth_headers


def _uniq(prefix: str) -> str:
    """规则名要唯一：测试库跨轮次保留（API 调用会 commit），写死名字第二轮就 409。"""
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def _mk_driver(client: TestClient, token_dispatcher: str, *, vehicle: str = "large") -> tuple[int, str]:
    """建一个司机并**用他自己的账号登录**，返回 (id, token)。

    为什么不复用 fixture 里那个司机：接单/送达要的是**司机本人**的 token，
    而"把规则挂到公用司机身上再解挂"会污染同一次运行里的其它用例
    （测试库跨轮次保留，这种互相影响最难查）。
    """
    phone = "13" + uuid.uuid4().hex[:9].translate(str.maketrans("abcdef", "012345"))
    r = client.post(
        "/api/v1/users",
        headers=auth_headers(token_dispatcher),
        json={"phone": phone, "password": "pass12345", "full_name": "计费测试司机",
              "role": "driver", "vehicle_type": vehicle},
    )
    assert r.status_code in (200, 201), r.text
    driver_id = int(r.json()["id"])
    r = client.post("/api/v1/auth/login", json={"phone": phone, "password": "pass12345"})
    assert r.status_code == 200, r.text
    return driver_id, r.json()["access_token"]


def _mk_rule(client: TestClient, token_dispatcher: str, **kw) -> dict:
    body = {"name": _uniq("规则"), "piece_amount": "200", "remark": "测试"}
    body.update(kw)
    r = client.post("/api/v1/driver-billing-rules", headers=auth_headers(token_dispatcher), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _attach(client: TestClient, token_dispatcher: str, driver_id: int, rule_id: int | None):
    return client.post(
        "/api/v1/driver-billing-rules/attach",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": driver_id, "rule_id": rule_id},
    )


# ---------------------------------------------------------------- 模板 CRUD

@pytest.mark.dispatcher
@pytest.mark.fast
def test_新建规则返回一句话说明和挂载数(client: TestClient, token_dispatcher: str) -> None:
    body = _mk_rule(
        client, token_dispatcher,
        salary="0", piece_amount="300", commission_base="freight", commission_rate="5",
    )
    assert body["summary"] == "每单 300.00 元 + 运费的 5%"   # 文案由后端生成，界面直接显示
    assert body["attached_count"] == 0
    assert body["is_deleted"] is False


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.parametrize(
    "kw, keyword",
    [
        ({"salary": "0", "piece_amount": "0"}, "一分钱"),                       # 什么都不给
        ({"piece_amount": "0", "commission_rate": "5"}, "提成基数"),            # 有比例没基数
        ({"piece_amount": "0", "commission_base": "freight"}, "提成比例"),      # 有基数没比例
        ({"piece_amount": "0", "commission_base": "freight", "commission_rate": "150"}, "100%"),
        ({"piece_amount": "-5"}, "负数"),
    ],
)
def test_参数不合法要给出中文原因(client: TestClient, token_dispatcher: str, kw: dict, keyword: str) -> None:
    """越界/组合不对必须返回**中文原因**（422 的英文结构体用户和 AI 都没法照着改）。"""
    body = {"name": _uniq("坏规则"), **kw}
    r = client.post("/api/v1/driver-billing-rules", headers=auth_headers(token_dispatcher), json=body)
    assert r.status_code == 400, r.text
    assert keyword in r.json()["detail"]


@pytest.mark.dispatcher
@pytest.mark.fast
def test_规则不能重名(client: TestClient, token_dispatcher: str) -> None:
    name = _uniq("重名")
    first = _mk_rule(client, token_dispatcher, name=name)
    r = client.post(
        "/api/v1/driver-billing-rules",
        headers=auth_headers(token_dispatcher),
        json={"name": name, "piece_amount": "100"},
    )
    assert r.status_code == 409
    assert name in r.json()["detail"]
    assert first["name"] == name


@pytest.mark.dispatcher
@pytest.mark.fast
def test_司机不能自己建规则(client: TestClient, token_driver: str) -> None:
    r = client.post(
        "/api/v1/driver-billing-rules",
        headers=auth_headers(token_driver),
        json={"name": _uniq("越权"), "piece_amount": "100"},
    )
    assert r.status_code == 403


@pytest.mark.dispatcher
@pytest.mark.fast
def test_改规则时也要按合并后的完整参数校验(client: TestClient, token_dispatcher: str) -> None:
    """只校验补丁本身的话，`{"commission_base": "freight"}` 能绕过"比例必须大于 0"。"""
    rule = _mk_rule(client, token_dispatcher, piece_amount="200")
    r = client.put(
        f"/api/v1/driver-billing-rules/{rule['id']}",
        headers=auth_headers(token_dispatcher),
        json={"piece_amount": "0", "commission_base": "freight"},
    )
    assert r.status_code == 400, r.text
    assert "提成比例" in r.json()["detail"]


# ---------------------------------------------------------------- 挂载（三条拦截）

@pytest.mark.dispatcher
@pytest.mark.fast
def test_挂载给非司机账号要被拦住(client: TestClient, token_dispatcher: str, users: dict) -> None:
    rule = _mk_rule(client, token_dispatcher)
    r = _attach(client, token_dispatcher, users["shipper"].id, rule["id"])
    assert r.status_code == 400
    assert "只能挂给司机" in r.json()["detail"]


@pytest.mark.dispatcher
@pytest.mark.fast
def test_车型对不上要被拦住并说清怎么办(client: TestClient, token_dispatcher: str) -> None:
    rule = _mk_rule(client, token_dispatcher, vehicle_type="trailer")
    driver_id, _ = _mk_driver(client, token_dispatcher, vehicle="large")
    r = _attach(client, token_dispatcher, driver_id, rule["id"])
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "车型对不上" in detail and "挂车" in detail and "大车" in detail


@pytest.mark.dispatcher
@pytest.mark.fast
def test_还挂着司机时不许删_并说出还有几个人(client: TestClient, token_dispatcher: str) -> None:
    rule = _mk_rule(client, token_dispatcher, vehicle_type="large")
    driver_id, _ = _mk_driver(client, token_dispatcher, vehicle="large")
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200

    r = client.delete(f"/api/v1/driver-billing-rules/{rule['id']}", headers=auth_headers(token_dispatcher))
    assert r.status_code == 400
    assert "1 个司机" in r.json()["detail"]

    # 解挂之后才能删；删了还能从回收站拿回来（撤回底线）
    assert _attach(client, token_dispatcher, driver_id, None).status_code == 200
    assert client.delete(
        f"/api/v1/driver-billing-rules/{rule['id']}", headers=auth_headers(token_dispatcher)
    ).status_code == 204
    assert client.get(
        "/api/v1/driver-billing-rules", params={"deleted_only": True}, headers=auth_headers(token_dispatcher)
    ).json()[0]["id"] == rule["id"]
    assert client.post(
        f"/api/v1/driver-billing-rules/{rule['id']}/restore", headers=auth_headers(token_dispatcher)
    ).status_code == 200


@pytest.mark.dispatcher
@pytest.mark.fast
def test_司机列表里能看出他按哪份规则算钱(client: TestClient, token_dispatcher: str) -> None:
    rule = _mk_rule(client, token_dispatcher, vehicle_type="large", salary="6000", piece_amount="0",
                    commission_base="freight", commission_rate="5")
    driver_id, _ = _mk_driver(client, token_dispatcher, vehicle="large")
    before = client.get("/api/v1/users?role=driver", headers=auth_headers(token_dispatcher)).json()
    me_before = next(u for u in before if u["id"] == driver_id)
    assert me_before["driver_rule_id"] is None
    # 没挂规则时那句话说的是老口径（不是空着——空着用户不知道他到底怎么算钱）
    assert "固定工资" in me_before["pay_summary"]
    assert rule["name"] not in me_before["pay_summary"]

    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200
    after = client.get("/api/v1/users?role=driver", headers=auth_headers(token_dispatcher)).json()
    me_after = next(u for u in after if u["id"] == driver_id)
    assert me_after["driver_rule_id"] == rule["id"]
    assert me_after["driver_rule_name"] == rule["name"]
    assert me_after["pay_summary"] == "固定工资 6000.00 元/月 + 运费的 5%"


@pytest.mark.dispatcher
@pytest.mark.fast
def test_司机看不到别人工资那种金额(client: TestClient, token_dispatcher: str) -> None:
    """规则里带着工资金额，而"工资仅派单员可见"是既有硬约定——那句话也不能漏出去。"""
    rule = _mk_rule(client, token_dispatcher, salary="8888", piece_amount="0")
    driver_id, token = _mk_driver(client, token_dispatcher)
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200
    me = client.get("/api/v1/users/me", headers=auth_headers(token))
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["salary"] is None
    assert "8888" not in (body["pay_summary"] or "")


# ---------------------------------------------------------------- 钱：完整链路

def _deliver(
    client: TestClient,
    token_shipper: str,
    token_dispatcher: str,
    token_driver: str,
    driver_id: int,
    *,
    freight_fee: str,
    goods_unit_price: str = "10.00",
    quantity: int = 2,
    extra_assign: dict | None = None,
) -> tuple[int, dict]:
    """下单 → 派单（带运费，可带这一单单独的计费参数）→ 接单 → 送达 → 返回 (订单号, 该单的司机账单)。"""
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "lines": [{"product_name_snapshot": "计费测试货", "quantity": quantity,
                       "unit_price": goods_unit_price,
                       "line_total": str(Decimal(goods_unit_price) * quantity)}],
            "delivery_description": "计费测试地址",
        },
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])

    r = client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": driver_id, "freight_fee": freight_fee, **(extra_assign or {})},
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["freight_fee"]) == Decimal(freight_fee)

    assert client.post(
        f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_driver)
    ).status_code == 200
    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        headers=auth_headers(token_driver),
        json={"delivery_photo_urls": ["/static/uploads/delivery/test-billing.jpg"], "driver_remark": "ok"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "DELIVERED"

    bills = client.get(
        f"/api/v1/driver-bills?driver_id={driver_id}", headers=auth_headers(token_dispatcher)
    ).json()
    hit = [b for b in bills if b.get("order_id") == oid and b["bill_type"] == "piece"]
    assert hit, f"送达后没有生成司机账单：{bills[-3:]}"
    return oid, hit[0]


@pytest.mark.dispatcher
@pytest.mark.driver
@pytest.mark.integration
def test_每单固定加运费提成_送达后账单等于手算的数(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """规则「每单 200 + 运费 5%」，运费 1000 → 账单必须是 250.00；解挂后回到老口径。"""
    rule = _mk_rule(
        client, token_dispatcher, vehicle_type=None,
        salary="0", piece_amount="200", commission_base="freight", commission_rate="5",
    )
    # 挂车司机：解挂之后他的老口径是"计件=全额运费"，正好能在同一条用例里验完两个方向
    driver_id, token_driver = _mk_driver(client, token_dispatcher, vehicle="trailer")
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200

    _, bill = _deliver(client, token_shipper, token_dispatcher, token_driver, driver_id, freight_fee="1000.00")
    assert Decimal(bill["amount"]) == Decimal("250.00")
    # 账单要能独立复核：规则名 + 两件金额都落库了（只留一个总数的话月底没人能对账）
    assert bill["rule_name"] == rule["name"]
    assert Decimal(bill["piece_amount"]) == Decimal("200.00")
    assert Decimal(bill["commission_amount"]) == Decimal("50.00")
    assert "运费" in bill["note"] and "250.00" in bill["note"]

    # 解挂 → 回到老口径（挂车司机 = 计件，拿该单全额运费）
    assert _attach(client, token_dispatcher, driver_id, None).status_code == 200
    _, bill2 = _deliver(client, token_shipper, token_dispatcher, token_driver, driver_id, freight_fee="1000.00")
    assert Decimal(bill2["amount"]) == Decimal("1000.00")
    assert bill2["rule_name"] == ""


@pytest.mark.dispatcher
@pytest.mark.driver
@pytest.mark.integration
def test_按商品金额提成的司机_账单按商品行合计算(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """商品金额 10×3=30，按 10% 提成 → 3.00。用商品行合计当基数这件事必须真的走通。"""
    rule = _mk_rule(
        client, token_dispatcher, salary="0", piece_amount="0",
        commission_base="goods", commission_rate="10",
    )
    driver_id, token_driver = _mk_driver(client, token_dispatcher, vehicle="trailer")
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200
    _, bill = _deliver(
        client, token_shipper, token_dispatcher, token_driver, driver_id,
        freight_fee="500.00", goods_unit_price="10.00", quantity=3,
    )
    assert Decimal(bill["amount"]) == Decimal("3.00")
    assert Decimal(bill["commission_amount"]) == Decimal("3.00")


@pytest.mark.dispatcher
@pytest.mark.driver
@pytest.mark.integration
def test_改规则不动已经派出去的单_但影响之后派的单(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """这是"账单是钱"的底线：派单那一刻的规则被快照到订单上，之后改规则不能追溯。"""
    rule = _mk_rule(client, token_dispatcher, piece_amount="200", salary="0")
    driver_id, token_driver = _mk_driver(client, token_dispatcher, vehicle="trailer")
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200

    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={"lines": [{"product_name_snapshot": "快照测试货", "quantity": 1,
                         "unit_price": "10.00", "line_total": "10.00"}],
              "delivery_description": "快照测试地址"},
    )
    oid = int(r.json()["id"])
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": driver_id, "freight_fee": "100.00"},
    ).status_code == 200

    upd = client.put(
        f"/api/v1/driver-billing-rules/{rule['id']}",
        headers=auth_headers(token_dispatcher),
        json={"piece_amount": "900"},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["summary"] == "每单 900.00 元"

    client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_driver))
    client.post(
        f"/api/v1/orders/{oid}/complete",
        headers=auth_headers(token_driver),
        json={"delivery_photo_urls": ["/static/uploads/delivery/snap.jpg"]},
    )
    bills = client.get(
        f"/api/v1/driver-bills?driver_id={driver_id}", headers=auth_headers(token_dispatcher)
    ).json()
    hit = [b for b in bills if b.get("order_id") == oid and b["bill_type"] == "piece"]
    assert hit, "送达后没有生成账单"
    # 派单时快照的是 200，改规则之后这一单仍然是 200
    assert Decimal(hit[0]["amount"]) == Decimal("200.00")

    # 之后派的单才按 900
    _, bill2 = _deliver(client, token_shipper, token_dispatcher, token_driver, driver_id, freight_fee="100.00")
    assert Decimal(bill2["amount"]) == Decimal("900.00")


@pytest.mark.dispatcher
@pytest.mark.integration
def test_固定工资加提成_月薪单和按单账单是两张(
    client: TestClient, token_dispatcher: str
) -> None:
    """「工资 6000 + 运费 5%」的司机：月薪单照生成（他的 billing_mode 是 PIECE，不能因此漏掉）。"""
    rule = _mk_rule(
        client, token_dispatcher, salary="6000", piece_amount="0",
        commission_base="freight", commission_rate="5",
    )
    driver_id, _ = _mk_driver(client, token_dispatcher, vehicle="trailer")
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200
    month = "2031-07"   # 挑一个不可能有历史数据的月份，避免和别的用例互相污染
    r = client.post(
        "/api/v1/driver-bills/generate",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": driver_id, "month": month, "bill_type": "salary"},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1, r.json()
    assert Decimal(r.json()[0]["amount"]) == Decimal("6000.00")
    assert rule["name"] in r.json()[0]["note"]

    # 没挂规则、也不是工资制的司机不该被生成工资单
    other_id, _ = _mk_driver(client, token_dispatcher, vehicle="trailer")
    r = client.post(
        "/api/v1/driver-bills/generate",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": other_id, "month": month, "bill_type": "salary"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == []


@pytest.mark.dispatcher
@pytest.mark.driver
@pytest.mark.integration
def test_按商品金额提成_可以只对指定商品抽(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """用户 2026-09-18：「哪些商品是要抽成的」——范围之外的商品一分钱不提。"""
    p1 = client.post("/api/v1/products", headers=auth_headers(token_dispatcher),
                     json={"name": _uniq("抽成商品A"), "default_unit_price": "10"}).json()
    p2 = client.post("/api/v1/products", headers=auth_headers(token_dispatcher),
                     json={"name": _uniq("不抽商品B"), "default_unit_price": "10"}).json()
    rule = _mk_rule(
        client, token_dispatcher, salary="0", piece_amount="0",
        commission_base="goods", commission_rate="10", commission_product_ids=[p1["id"]],
    )
    assert "指定商品" in rule["summary"]
    driver_id, token_driver = _mk_driver(client, token_dispatcher, vehicle="trailer")
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200

    r = client.post(
        "/api/v1/orders", headers=auth_headers(token_shipper),
        json={"lines": [
            {"product_id": p1["id"], "product_name_snapshot": p1["name"], "quantity": 2,
             "unit_price": "10.00", "line_total": "20.00"},
            {"product_id": p2["id"], "product_name_snapshot": p2["name"], "quantity": 3,
             "unit_price": "10.00", "line_total": "30.00"},
        ], "delivery_description": "抽成范围测试"},
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert client.post(f"/api/v1/orders/{oid}/assign", headers=auth_headers(token_dispatcher),
                       json={"driver_id": driver_id, "freight_fee": "100.00"}).status_code == 200
    client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_driver))
    client.post(f"/api/v1/orders/{oid}/complete", headers=auth_headers(token_driver),
                json={"delivery_photo_urls": ["/static/uploads/delivery/scope.jpg"]})

    bills = client.get(f"/api/v1/driver-bills?driver_id={driver_id}", headers=auth_headers(token_dispatcher)).json()
    hit = next(b for b in bills if b.get("order_id") == oid)
    # 只对 p1（20.00）抽 10% = 2.00，而不是 (20+30) 的 10%
    assert Decimal(hit["amount"]) == Decimal("2.00")


@pytest.mark.dispatcher
@pytest.mark.driver
@pytest.mark.integration
def test_派单时能给这一单单独定提成比例(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """「提成是另外一回事，可能设置这一单」→ 逐单覆盖，账单按覆盖值算。"""
    rule = _mk_rule(client, token_dispatcher, salary="0", piece_amount="0",
                    commission_base="freight", commission_rate="5")
    driver_id, token_driver = _mk_driver(client, token_dispatcher, vehicle="trailer")
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200

    oid, bill = _deliver(client, token_shipper, token_dispatcher, token_driver, driver_id,
                                  freight_fee="1000.00", extra_assign={"driver_commission_rate": "8"})
    assert Decimal(bill["amount"]) == Decimal("80.00")      # 8% 而不是规则里的 5%
    # ⚠️ 说明里必须是**这一次实际用的比例**。原来这条断言写的是 `"8" in note`，
    #    而 note 里的 "80.00" 本身就含 "8" —— 它是**恒真**的，于是"说明印的是规则里的 5%"
    #    这个错一直没被抓住（真机 E2E 才看到"运费 1000.00 的 5.00% = 80.00"）。
    assert "8.00%" in bill["note"], bill["note"]
    assert "5.00%" not in bill["note"], bill["note"]
    assert "这一单单独定的" in bill["note"], bill["note"]


@pytest.mark.dispatcher
@pytest.mark.driver
@pytest.mark.integration
def test_逐单定额的账单说明也不许印规则里的默认值(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """每单金额被逐单覆盖时，说明里那一项要标出来（账单是钱，得能独立复核）。"""
    rule = _mk_rule(client, token_dispatcher, salary="0", piece_amount="200")
    driver_id, token_driver = _mk_driver(client, token_dispatcher, vehicle="trailer")
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200

    _, bill = _deliver(client, token_shipper, token_dispatcher, token_driver, driver_id,
                       freight_fee="100.00", extra_assign={"driver_piece_amount": "300"})
    assert Decimal(bill["amount"]) == Decimal("300.00")
    assert "每单 300.00（这一单单独定的）" in bill["note"], bill["note"]


@pytest.mark.dispatcher
@pytest.mark.driver
@pytest.mark.integration
def test_两个司机各挂各的规则_算钱互不干扰(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """用户 2026-09-18：「挂到这个司机上，然后这个司机所有的订单就按这个计费规则走并且互不干扰」。"""
    rule_a = _mk_rule(client, token_dispatcher, salary="0", piece_amount="500")
    rule_b = _mk_rule(client, token_dispatcher, salary="0", piece_amount="0",
                      commission_base="freight", commission_rate="5")
    da, ta = _mk_driver(client, token_dispatcher, vehicle="trailer")
    db_, tb = _mk_driver(client, token_dispatcher, vehicle="trailer")
    assert _attach(client, token_dispatcher, da, rule_a["id"]).status_code == 200
    assert _attach(client, token_dispatcher, db_, rule_b["id"]).status_code == 200

    # 同样的单、同样的运费，两个人拿的钱按各自规则算
    _, bill_a = _deliver(client, token_shipper, token_dispatcher, ta, da, freight_fee="1000.00")
    _, bill_b = _deliver(client, token_shipper, token_dispatcher, tb, db_, freight_fee="1000.00")
    assert Decimal(bill_a["amount"]) == Decimal("500.00")
    assert Decimal(bill_b["amount"]) == Decimal("50.00")

    # 改 A 的规则，B 的下一单不受影响
    client.put(f"/api/v1/driver-billing-rules/{rule_a['id']}",
               headers=auth_headers(token_dispatcher), json={"piece_amount": "900"})
    _, bill_b2 = _deliver(client, token_shipper, token_dispatcher, tb, db_, freight_fee="1000.00")
    assert Decimal(bill_b2["amount"]) == Decimal("50.00")
    _, bill_a2 = _deliver(client, token_shipper, token_dispatcher, ta, da, freight_fee="1000.00")
    assert Decimal(bill_a2["amount"]) == Decimal("900.00")


def _mk_order(client: TestClient, token_shipper: str) -> int:
    """只下单不派单（用来单独测"派单这一步"的拦截），返回订单 id。"""
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={"lines": [{"product_name_snapshot": "派单拦截测试货", "quantity": 1,
                         "unit_price": "10.00", "line_total": "10.00"}],
              "delivery_description": "派单拦截测试地址"},
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _deliver_quiet(
    client: TestClient, token_shipper: str, token_dispatcher: str,
    token_driver: str, driver_id: int, *, freight_fee: str,
) -> tuple[int, None]:
    """和 `_deliver` 同一条链路，但**不要求**有账单（用于"本来就不该生成账单"的用例）。"""
    oid = _mk_order(client, token_shipper)
    r = client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": driver_id, "freight_fee": freight_fee},
    )
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/orders/{oid}/driver-ack",
                       headers=auth_headers(token_driver)).status_code == 200
    r = client.post(f"/api/v1/orders/{oid}/complete", headers=auth_headers(token_driver),
                    json={"delivery_photo_urls": ["/static/uploads/delivery/quiet.jpg"]})
    assert r.status_code == 200, r.text
    return oid, None


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.parametrize(
    "rule_kw, extra, keyword",
    [
        # 司机压根没挂规则 → order_pay 直接返回全额运费，两个覆盖值一个都没读
        (None, {"driver_piece_amount": "300"}, "没有地方生效"),
        # 规则是"每单固定 200"，没有提成项 → basis=0，比例乘出来恒为 0
        ({"salary": "0", "piece_amount": "200"}, {"driver_commission_rate": "8"}, "没有提成项"),
        ({"salary": "0", "piece_amount": "200"}, {"driver_piece_amount": "-1"}, "负数"),
        (
            {"salary": "0", "piece_amount": "0", "commission_base": "freight", "commission_rate": "5"},
            {"driver_commission_rate": "150"},
            "100%",
        ),
    ],
)
def test_逐单覆盖值不生效时要拒绝_不能收了不算(
    client: TestClient, token_shipper: str, token_dispatcher: str,
    rule_kw: dict | None, extra: dict, keyword: str,
) -> None:
    """用户 2026-09-18：「每单是不固定的…这些单价是由派单员来决定的」。

    逐单给钱是常态，所以"**填了却不生效**"是最坏的一种失败：界面上有数字、
    账单里也有数字，两边都不报错，只有月底对账才发现两个数没关系。
    """
    driver_id, _ = _mk_driver(client, token_dispatcher, vehicle="trailer")
    if rule_kw is not None:
        rule = _mk_rule(client, token_dispatcher, **rule_kw)
        assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200
    oid = _mk_order(client, token_shipper)

    r = client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": driver_id, "freight_fee": "100.00", **extra},
    )
    assert r.status_code == 400, r.text          # 400 + 中文，而不是 422 + 英文结构体
    assert keyword in r.json()["detail"]

    # 先验再做：被拒之后订单一个字段都没动过（否则会留下"派了但没金额"的半截状态）
    after = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_dispatcher)).json()
    assert after["status"] == "PENDING_DISPATCH", after
    assert after["driver_id"] in (None, 0), after


@pytest.mark.dispatcher
@pytest.mark.driver
@pytest.mark.integration
def test_工资制司机被逐单定额_这张单就按单付钱(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """规则里只有固定工资的司机，派单员给这一单单独定了 300 → 这单就得按单生成账单。

    判据是模式快照（`driver_billing_mode_snapshot`）——它决定送达时**生不生成**按单账单。
    要是留在 SALARY，那 300 会掉进"工资制司机不生成按单账单"的缝里：
    钱在订单上、账单里没有，两边都不报错。
    """
    rule = _mk_rule(client, token_dispatcher, salary="8000", piece_amount="0")
    driver_id, token_driver = _mk_driver(client, token_dispatcher, vehicle="large")
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200

    _, bill = _deliver(client, token_shipper, token_dispatcher, token_driver, driver_id,
                       freight_fee="100.00", extra_assign={"driver_piece_amount": "300"})
    assert Decimal(bill["amount"]) == Decimal("300.00")

    # 同一个司机、同样的单，这一单没单独定额 → 回到"只拿月薪"，不生成按单账单
    oid, _ = _deliver_quiet(client, token_shipper, token_dispatcher, token_driver, driver_id,
                            freight_fee="100.00")
    bills = client.get(f"/api/v1/driver-bills?driver_id={driver_id}",
                       headers=auth_headers(token_dispatcher)).json()
    assert not [b for b in bills if b.get("order_id") == oid], "工资制司机的单不该生成按单账单"


def test_模型层_规则的参数快照函数存在() -> None:
    """规则参数要能整体取出来记审计（改前/改后逐字段比）。"""
    r = DriverBillingRule(name="x", salary=Decimal("1"), piece_amount=Decimal("2"))
    assert set(r.params()) >= {"name", "salary", "piece_amount", "commission_base", "commission_rate"}


def test_模型层_驱动规则关系是懒加载可用的(db_session) -> None:
    u = db_session.query(User).filter_by(phone="13800000003").first()
    assert hasattr(u, "driver_rule")
