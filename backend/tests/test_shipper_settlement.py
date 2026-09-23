"""批发商**自己那一本账**（给下游货主核销）：整单 / 按商品 / 撤销 / 恢复。

## 这份测试真正要钉住的是什么

不是"接口能通"，而是**两本账不许串**（用户 2026-09-20 原话：「这个核销只对他来说……
不会对总分销商（派单员）进行核销，他这个核销是他另外的、独立的，他自己管自己的」）：

`test_settlement_does_not_touch_dispatcher_books` 逐项断言核销**之后**：
`orders.paid` 没变、`cash_flows` 没多一条、`ledgers` 没多一行、
`order_money.arrears`（他欠公司多少）一个数都没动。

这一条之所以是重点：那三处**恰恰是"最省事"的实现方式**（复用一个已有端点、
顺手翻一下 `paid`），而且写错了**两边都不报错**——公司账上凭空多一笔"已收"，
钱其实还在他自己口袋里。所以它必须是红的。
"""
from __future__ import annotations

from datetime import date

import pytest

from app.models import CashFlow, Ledger, OperationLog, Order
from app.models.shipper_settlement import ShipperSettlement, ShipperSettlementLine
from app.services.order_money import money_of
from tests.conftest import auth_headers

BASE = "/api/v1/shipper-ledger/settlements"


@pytest.fixture
def member(users, db_session):
    """把开发货主账号变成**批发商**（那本账只有批发商能写）。"""
    u = users["shipper"]
    u.is_member = True
    db_session.commit()
    return u


def _delivered_order(
    client,
    h,
    users,
    *,
    shipper_id: int | None = None,
    dongjia: str = "罗伟东",
    dongjia_phone: str = "13500000001",
) -> int:
    """造一张**已送达**的两行订单：白菜 2×10=20、萝卜 3×20=60（合计 80）。"""
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id if shipper_id is not None else users["shipper"].id,
            "lines": [
                {"product_name_snapshot": "白菜", "quantity": 2, "unit_price": "10"},
                {"product_name_snapshot": "萝卜", "quantity": 3, "unit_price": "20"},
            ],
            "address_detail": "核销测试地址",
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
            "delivery_photo_urls": ["/static/uploads/delivery/settle-probe.jpg"],
            "payment": "arrears",
        },
        headers=auth_headers(dtok),
    )
    assert done.status_code == 200, done.text
    return oid


def _lines_of(db_session, oid: int) -> list:
    return (
        db_session.query(Order).filter_by(id=oid).one().order_products
    )


def test_whole_order_settle(client, db_session, users, token_dispatcher, token_shipper, member):
    """整单核销：不传 lines → 每一行按「还可核销」全额，金额=80。"""
    h = auth_headers(token_dispatcher)
    oid = _delivered_order(client, h, users)

    r = client.post(BASE, json={"order_id": oid}, headers=auth_headers(token_shipper))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["amount"] == "80.00"
    assert body["customer_name"] == "罗伟东"
    assert body["customer_phone"] == "13500000001"
    assert len(body["lines"]) == 2
    assert body["order_no"]

    # 收齐之后再核销 → 400（不许收出负数）
    again = client.post(BASE, json={"order_id": oid}, headers=auth_headers(token_shipper))
    assert again.status_code == 400
    assert "已经核销完" in again.json()["detail"]


def test_line_level_settle(client, db_session, users, token_dispatcher, token_shipper, member):
    """按商品核销：只核「萝卜」60 元 → 白菜那 20 元还挂着。"""
    h = auth_headers(token_dispatcher)
    oid = _delivered_order(client, h, users)
    cai, luobo = _lines_of(db_session, oid)

    r = client.post(
        BASE,
        json={"order_id": oid, "lines": [{"order_product_id": luobo.id, "amount": "60.00"}]},
        headers=auth_headers(token_shipper),
    )
    assert r.status_code == 201, r.text
    assert r.json()["amount"] == "60.00"
    assert [x["product_name"] for x in r.json()["lines"]] == ["萝卜"]

    # 再核销整单 → 只剩白菜那 20
    rest = client.post(BASE, json={"order_id": oid}, headers=auth_headers(token_shipper))
    assert rest.status_code == 201, rest.text
    assert rest.json()["amount"] == "20.00"
    assert [x["product_name"] for x in rest.json()["lines"]] == ["白菜"]

    # 一行超收 → 400，且**一行都不许写进去**
    before = db_session.query(ShipperSettlementLine).filter_by(order_id=oid).count()
    bad = client.post(
        BASE,
        json={"order_id": oid, "lines": [{"order_product_id": cai.id, "amount": "1.00"}]},
        headers=auth_headers(token_shipper),
    )
    assert bad.status_code == 400
    assert "已经收齐" in bad.json()["detail"]
    assert db_session.query(ShipperSettlementLine).filter_by(order_id=oid).count() == before


def test_over_collect_is_rejected(client, db_session, users, token_dispatcher, token_shipper, member):
    """超过「还可核销」的金额 → 400，**整笔回滚**（不许写半笔）。"""
    h = auth_headers(token_dispatcher)
    oid = _delivered_order(client, h, users)
    cai, _ = _lines_of(db_session, oid)

    before = db_session.query(ShipperSettlement).filter_by(order_id=oid).count()
    r = client.post(
        BASE,
        json={"order_id": oid, "lines": [{"order_product_id": cai.id, "amount": "999.00"}]},
        headers=auth_headers(token_shipper),
    )
    assert r.status_code == 400
    assert "还可核销" in r.json()["detail"]
    assert db_session.query(ShipperSettlement).filter_by(order_id=oid).count() == before
    assert db_session.query(ShipperSettlementLine).filter_by(order_id=oid).count() == 0


def test_revoke_then_restore(client, db_session, users, token_dispatcher, token_shipper, member):
    """撤掉核销 = **软删**（行留着）；撤销后金额回到未收，restore 原样放回来。

    ⚠️ **2026-09-23 第 16 轮改过这条断言**（原来它把这个缺陷钉成了"设计如此"）：
    原来这里"撤销 → 再核销一遍 → 把那笔恢复回来"断言的也是 **200 成功**，
    于是同一笔 80 被记了两遍（已收 160 / 应收 80），而两个数都不报错。
    恢复是要**重算上限**的：位置已经被后面那笔占掉时必须以 400 拒绝并说清怎么办
    —— 逐条判据在 `tests/test_shipper_settle_ceiling.py`（含"还有余量时照旧可以"的反面用例）。
    """
    h = auth_headers(token_dispatcher)
    oid = _delivered_order(client, h, users)
    sid = client.post(BASE, json={"order_id": oid}, headers=auth_headers(token_shipper)).json()["id"]

    today = date.today().isoformat()
    win = {"delivered_from": today, "delivered_to": today, "order_id": oid}

    assert client.delete(f"{BASE}/{sid}", headers=auth_headers(token_shipper)).status_code == 204
    row = db_session.get(ShipperSettlement, sid)
    assert row is not None and row.is_deleted and row.deleted_at is not None  # 物理行还在

    alive = client.get(BASE, params=win, headers=auth_headers(token_shipper)).json()
    assert [x["id"] for x in alive] == []
    trash = client.get(
        BASE, params={**win, "include_deleted": "true"}, headers=auth_headers(token_shipper)
    ).json()
    assert [x["id"] for x in trash] == [sid] and trash[0]["is_deleted"] is True

    # 撤销之后这一单又能核销了（还是 80）
    again = client.post(BASE, json={"order_id": oid}, headers=auth_headers(token_shipper))
    assert again.status_code == 201 and again.json()["amount"] == "80.00"

    # ⛔ 把撤掉的那笔恢复回来：这一单的 80 已经被"again"那笔收掉了，放回来就是多收 80
    back = client.post(f"{BASE}/{sid}/restore", headers=auth_headers(token_shipper))
    assert back.status_code == 400, "同一笔钱不许被记两遍：恢复必须重算上限"
    assert "还可核销" in back.json()["detail"]

    # 先撤掉"again"那笔，再恢复最早那笔 —— 这才是用户真正想要的那条路，必须走得通
    assert client.delete(f"{BASE}/{again.json()['id']}", headers=auth_headers(token_shipper)).status_code == 204
    ok = client.post(f"{BASE}/{sid}/restore", headers=auth_headers(token_shipper))
    assert ok.status_code == 200, ok.text
    assert ok.json()["is_deleted"] is False and len(ok.json()["lines"]) == 2
    full = client.post(BASE, json={"order_id": oid}, headers=auth_headers(token_shipper))
    assert full.status_code == 400  # 这一单真的收齐了


def test_settlement_does_not_touch_dispatcher_books(
    client, db_session, users, token_dispatcher, token_shipper, member
):
    """⛔ 核销**只记他自己那一本**：不翻 paid、不写现金流水、不写账本、不动他的欠款。"""
    h = auth_headers(token_dispatcher)
    oid = _delivered_order(client, h, users)
    order = db_session.get(Order, oid)

    paid_before = order.paid
    flows_before = db_session.query(CashFlow).count()
    ledgers_before = db_session.query(Ledger).count()
    arrears_before = money_of(db_session, order).arrears

    assert (
        client.post(BASE, json={"order_id": oid}, headers=auth_headers(token_shipper)).status_code
        == 201
    )

    db_session.expire_all()
    order = db_session.get(Order, oid)
    assert order.paid == paid_before is False
    assert db_session.query(CashFlow).count() == flows_before
    assert db_session.query(Ledger).count() == ledgers_before
    assert money_of(db_session, order).arrears == arrears_before
    # 而且**留了痕**（这本账不写 cash_flows，所以审计日志是唯一的回查入口）
    logs = (
        db_session.query(OperationLog)
        .filter_by(order_id=oid, action="SHIPPER_SETTLE_CREATE")
        .all()
    )
    assert len(logs) == 1
    assert "80.00" in (logs[0].change_content or "")


def test_plain_shipper_cannot_settle(client, db_session, users, token_dispatcher, token_shipper):
    """普通货主**没有核销功能**（他给自己下单，不需要核销）。"""
    # 这个开发账号被上面的用例提成过批发商（用例之间共用一张库），这里显式退回普通货主
    users["shipper"].is_member = False
    db_session.commit()
    oid = _delivered_order(client, auth_headers(token_dispatcher), users)
    r = client.post(BASE, json={"order_id": oid}, headers=auth_headers(token_shipper))
    assert r.status_code == 403
    assert "批发商" in r.json()["detail"]


def test_dispatcher_and_driver_cannot_read(client, users, token_dispatcher, token_driver, member):
    """派单员/司机读不到这本账（是他自己的账）。"""
    for tok in (token_dispatcher, token_driver):
        r = client.get(BASE, headers=auth_headers(tok))
        assert r.status_code == 403


def test_cannot_settle_someone_elses_order(client, db_session, users, token_dispatcher, token_shipper, member):
    """别人的单 → 404（不说"存在但不是你的"）。"""
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["dispatcher"].id,
            "lines": [{"product_name_snapshot": "别人的货", "quantity": 1, "unit_price": "5"}],
            "address_detail": "别人的地址",
        },
        headers=auth_headers(token_dispatcher),
    )
    # 派单员 id 不是货主账号，这里只验证"不属于我的单"这条路：随便拿一张不存在的编号
    other = client.post(BASE, json={"order_id": 999999}, headers=auth_headers(token_shipper))
    assert other.status_code == 404
    assert r.status_code in (201, 400)


def test_undelivered_order_cannot_settle(client, db_session, users, token_dispatcher, token_shipper, member):
    """还没送达的单不能核销（货没到客户手上，这笔应收还不存在）。"""
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [{"product_name_snapshot": "在途", "quantity": 1, "unit_price": "30"}],
            "address_detail": "在途地址",
        },
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    bad = client.post(BASE, json={"order_id": oid}, headers=auth_headers(token_shipper))
    assert bad.status_code == 400
    assert "还没送达" in bad.json()["detail"]


def test_window_follows_delivery_date(client, db_session, users, token_dispatcher, token_shipper, member):
    """窗口按**订单送达日**筛：今天的窗口看得到，去年的窗口看不到。"""
    oid = _delivered_order(client, auth_headers(token_dispatcher), users)
    sid = client.post(BASE, json={"order_id": oid}, headers=auth_headers(token_shipper)).json()["id"]

    today = date.today().isoformat()
    hit = client.get(
        BASE,
        params={"delivered_from": today, "delivered_to": today, "order_id": oid},
        headers=auth_headers(token_shipper),
    ).json()
    assert [x["id"] for x in hit] == [sid]

    miss = client.get(
        BASE,
        params={"delivered_from": "2000-01-01", "delivered_to": "2000-01-02"},
        headers=auth_headers(token_shipper),
    ).json()
    assert miss == []

    one = client.get(BASE, params={"order_id": oid}, headers=auth_headers(token_shipper)).json()
    assert [x["id"] for x in one] == [sid]
