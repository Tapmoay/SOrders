"""「我的 → 管下游的账」那颗开关（CHG-0076 / 台账 L-39）。

## 这份测试真正要钉住的是什么

不是「开关能存下来」，而是四件**不报错却做错**的事：

1. **两道闸都要**：只改客户端＝没做 —— 老包 / AI / 直接打接口照样能读写这本账。
   所以关掉之后：两个**读**端点返空，三个**写**端点 403。
2. **关掉不是 403**（读端点）：旧 App 收到 403 会弹报错，收到 0.00 只是「没有」
   —— 这是用户口径①「返回空 ＋ 一个标记」。
3. **关掉不许动任何金额**（shipper_settlement.py 头号忌讳：两本账绝不互写）：
   支出侧三个数一个都不许变；收入侧只是「不显示」，**再打开必须原样回来**。
4. **开关与身份是两件事**：is_member 不许被它改动（工作台那个「批发商」徽章靠它），
   普通货主也不许拨（他本来就没有这本账）。

## ⚠️ 共用账号上的可变标志
开发货主账号（13800000002）是**整个 worker 共用**的 —— 这一格与 is_member 都由
tests/conftest.py::_reset_shared_users 在每个用例开始前摆回基线（开着）。
每个用例仍然**自己摆前提**（_switch_on），不靠「我的文件排在前面」。
"""
from __future__ import annotations

import pytest

from app.models import OperationLog
from app.models.shipper_settlement import ShipperSettlement
from tests.conftest import auth_headers

SUMMARY = "/api/v1/shipper-ledger/summary"
SETTLEMENTS = "/api/v1/shipper-ledger/settlements"
SWITCH = "/api/v1/users/me/downstream-ledger"
ME = "/api/v1/users/me"

#: 用例之间避免互相污染：每个用例用自己那个下游货主名 + 电话筛（同 test_shipper_ledger_summary 的规矩）。
_NAME_SEQ = {"n": 0}


@pytest.fixture
def member(users, db_session):
    """把开发货主账号变成**批发商**（下游这本账只有批发商有），并把开关摆在「开」。

    ⚠️ fixture 是**每个测试文件各写一份**的（conftest 只放共用件）——
       test_shipper_ledger_summary 与 test_shipper_settlement 里各有一份同样的。
    """
    u = users["shipper"]
    u.is_member = True
    u.downstream_ledger_enabled = True
    db_session.commit()
    return u


def _next_customer(tag: str) -> tuple[str, str]:
    _NAME_SEQ["n"] += 1
    n = _NAME_SEQ["n"]
    return f"下游开关{tag}{n}", f"1350009{n:04d}"


def _set_switch(client, h, enabled: bool):
    return client.patch(SWITCH, json={"enabled": enabled}, headers=h)


def _switch_on(client, h) -> None:
    """摆前提：这一格必须是开着的（同一个 worker 里别的用例可能关过它）。"""
    r = _set_switch(client, h, True)
    assert r.status_code == 200, r.text


def _delivered_order(client, h, users, *, dongjia: str, dongjia_phone: str) -> int:
    """造一张**已送达**的两行订单：白菜 2×10=20、萝卜 3×20=60（合计 80）。"""
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [
                {"product_name_snapshot": "白菜", "quantity": 2, "unit_price": "10"},
                {"product_name_snapshot": "萝卜", "quantity": 3, "unit_price": "20"},
            ],
            "address_detail": "下游开关测试地址",
            "contact_dongjia_name": dongjia,
            "contact_dongjia_phone": dongjia_phone,
            "contact_boss_name": "永盛食品",
            "contact_boss_phone": "13800000002",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    dtok = client.post(
        "/api/v1/auth/login", json={"phone": users["driver"].phone, "password": "pass12345"}
    ).json()["access_token"]
    assert (
        client.post(
            f"/api/v1/orders/{oid}/assign",
            json={"driver_id": users["driver"].id, "freight_fee": "20"},
            headers=h,
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(dtok)).status_code == 200
    done = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={
            "delivery_photo_urls": ["/static/uploads/delivery/downstream-switch.jpg"],
            "payment": "arrears",
        },
        headers=auth_headers(dtok),
    )
    assert done.status_code == 200, done.text
    return oid


def _summary(client, h, **params) -> dict:
    r = client.get(SUMMARY, headers=h, params={k: v for k, v in params.items() if v is not None})
    assert r.status_code == 200, r.text
    return r.json()


def _settlements(client, h, oid: int) -> list:
    r = client.get(SETTLEMENTS, headers=h, params={"order_id": oid})
    assert r.status_code == 200, r.text
    return r.json()


def test_关掉之后读端点返空但不是403(client, users, token_shipper, token_dispatcher, member):
    """口径①：返回空 ＋ 一个标记；同时钉住「支出侧一分钱都不许动」。"""
    h = auth_headers(token_shipper)
    disp_h = auth_headers(token_dispatcher)
    name, phone = _next_customer("A")
    oid = _delivered_order(client, disp_h, users, dongjia=name, dongjia_phone=phone)
    settled = client.post(SETTLEMENTS, json={"order_id": oid}, headers=h)
    assert settled.status_code == 201, settled.text
    assert settled.json()["amount"] == "80.00"

    before = _summary(client, h, customer_name=name, customer_phone=phone)
    assert before["is_member"] is True
    assert before["downstream_ledger_enabled"] is True
    assert before["receivable"] == "80.00"
    assert before["received"] == "80.00"
    assert before["settlements"] == 1
    assert len(_settlements(client, h, oid)) == 1

    assert _set_switch(client, h, False).status_code == 200

    after = _summary(client, h, customer_name=name, customer_phone=phone)
    # ⛔ 身份不许被这颗开关改动：工作台那个「批发商」徽章靠 is_member（别的判据也盯着它）
    assert after["is_member"] is True
    # 标记必须跟着回来：**只看空列表分不清「他关掉了」还是「本来就没有」**
    assert after["downstream_ledger_enabled"] is False
    assert (after["receivable"], after["received"], after["unreceived"], after["settlements"]) == (
        "0.00",
        "0.00",
        "0.00",
        0,
    )
    for key in ("orders", "cleared_orders", "payable", "paid", "unpaid"):
        assert after[key] == before[key], f"关开关只是不显示，⛔ 不许改任何金额（{key}）"

    listed = client.get(SETTLEMENTS, headers=h, params={"order_id": oid})
    assert listed.status_code == 200, "⛔ 不是 403：旧 App 收到 403 会弹报错"
    assert listed.json() == []

    me = client.get(ME, headers=h)
    assert me.status_code == 200
    assert me.json()["downstream_ledger_enabled"] is False
    assert me.json()["is_member"] is True


def test_关掉之后再打开数字原样回来(client, users, token_shipper, token_dispatcher, member):
    """关掉只是「不显示 / 不提供」—— **数据一个字节都没动**。"""
    h = auth_headers(token_shipper)
    disp_h = auth_headers(token_dispatcher)
    name, phone = _next_customer("B")
    oid = _delivered_order(client, disp_h, users, dongjia=name, dongjia_phone=phone)
    assert client.post(SETTLEMENTS, json={"order_id": oid}, headers=h).status_code == 201
    before = _summary(client, h, customer_name=name, customer_phone=phone)

    assert _set_switch(client, h, False).status_code == 200
    assert _summary(client, h, customer_name=name, customer_phone=phone)["received"] == "0.00"

    assert _set_switch(client, h, True).status_code == 200
    again = _summary(client, h, customer_name=name, customer_phone=phone)
    assert again == before, "关掉再打开必须一模一样（否则就是「关开关动了数据」）"
    assert len(_settlements(client, h, oid)) == 1


def test_关掉之后三个写端点都403(client, db_session, users, token_shipper, token_dispatcher, member):
    """⛔ 只改客户端＝没做：老包 / AI / 直接打接口照样能写这本账。"""
    h = auth_headers(token_shipper)
    disp_h = auth_headers(token_dispatcher)
    name, phone = _next_customer("C")
    first = _delivered_order(client, disp_h, users, dongjia=name, dongjia_phone=phone)
    second = _delivered_order(client, disp_h, users, dongjia=name, dongjia_phone=phone)
    created = client.post(SETTLEMENTS, json={"order_id": first}, headers=h)
    assert created.status_code == 201, created.text
    sid = int(created.json()["id"])

    assert _set_switch(client, h, False).status_code == 200

    attempts = (
        ("记一笔核销", client.post(SETTLEMENTS, json={"order_id": second}, headers=h)),
        ("撤销一笔核销", client.delete(f"{SETTLEMENTS}/{sid}", headers=h)),
        ("恢复一笔核销", client.post(f"{SETTLEMENTS}/{sid}/restore", headers=h)),
    )
    for label, resp in attempts:
        assert resp.status_code == 403, f"{label}：关掉之后必须 403（{resp.text}）"
        assert "管下游的账" in resp.json()["detail"], f"{label}：报错要说清出路"

    # 而且**真的没写进去**：那一笔还在、第二单没被核销
    assert _set_switch(client, h, True).status_code == 200
    still_there = db_session.query(ShipperSettlement).filter_by(id=sid, is_deleted=False).one_or_none()
    assert still_there is not None, "被拦下的删除不许真的删掉"
    after = _summary(client, h, customer_name=name, customer_phone=phone)
    assert after["receivable"] == "160.00", "两单各 80"
    assert after["received"] == "80.00", "只该有第一笔核销"
    assert after["settlements"] == 1


def test_普通货主不许拨这个开关(client, db_session, users, token_shipper):
    """口径④：这是**批发商自己**的选择 —— 他本来就没有下游这本账。"""
    users["shipper"].is_member = False
    db_session.commit()
    r = _set_switch(client, auth_headers(token_shipper), False)
    assert r.status_code == 403
    assert "只有批发商" in r.json()["detail"]
    me = client.get(ME, headers=auth_headers(token_shipper)).json()
    assert me["downstream_ledger_enabled"] is True, "被拒之后这一格不许被动过"


def test_派单员不许代设(client, token_dispatcher):
    """口径④：派单员不给看、**也不代设**。"""
    assert _set_switch(client, auth_headers(token_dispatcher), False).status_code == 403


def test_拨到同一档不写日志_真改动写一条(client, db_session, users, token_shipper, member):
    """审计要能回答「这颗开关是谁、什么时候关的」；而「开了又开」不该把日志埋掉。"""
    h = auth_headers(token_shipper)
    _switch_on(client, h)
    uid = users["shipper"].id

    def logs() -> int:
        return db_session.query(OperationLog).filter_by(operator_id=uid).count()

    before = logs()
    assert _set_switch(client, h, True).status_code == 200
    assert logs() == before, "拨到同一档（本来就是开）不该写日志"

    assert _set_switch(client, h, False).status_code == 200
    assert logs() == before + 1, "真改动要留一条"
    last = (
        db_session.query(OperationLog)
        .filter_by(operator_id=uid)
        .order_by(OperationLog.id.desc())
        .first()
    )
    assert "USER_UPDATE" in str(last.action), "复用既有动作名（⛔ 不新加枚举：App 侧没有中文名）"
    content = last.change_content or ""
    assert "downstream_ledger_enabled" in content, f"日志要写清改的是哪一格：{content[:200]}"
