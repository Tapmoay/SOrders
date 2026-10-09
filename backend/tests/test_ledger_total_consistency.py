"""账本行的「合计」只许有一个答案：数量 × 单价（BUG-0025；测试台账 TB-10）。

## 抓到的是什么（错数）

`PATCH /api/v1/ledger/entries/{id}` 原来写着「显式给了 total 就用 total」（`ledger.py` 的
`if "total" in raw …: row.total = raw["total"]`），**不看它与 数量×单价 的关系**。
于是 3 × 20.00 = 60.00 的一行可以被改成 `total = 288.00` 并且真的落库：同一行两个答案
（数量单价说 60、合计说 288），账户/欠款按 total 走（Shipper 200.0000 → 488.0000）、
界面按数量×单价看，**两边都不报错**。用户唯一能走到这条路的是 AI 的「改合计金额」
（`AiWriteLedgerHandlers.kt` 的 new_amount 只把 total 放进 payload）。

## 现在的不变式

**手工账行的 合计 ≡ 数量 × 单价**（一处实现：`ledger.py::resolve_line_total`）；要记
「整笔金额」就写 数量 1 / 单价 = 合计（或把数量、单价一起给成乘积等于它的值），
文案会把这两个数都报出来。

唯一例外是 `source=order` 的行：它的合计**就是订单行的金额**（`line_total`，可含让价），
权威在订单那一侧，所以那里仍然允许显式 total —— 它另有「已送达/已退货」闸
（`_reject_if_order_closed`）挡着，别把那条闸碰坏。
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.models import Ledger
from app.models.enums import LedgerSource
from tests.conftest import auth_headers


def _mk_manual_row(client: TestClient, shipper_id: int, token: str, **over: object) -> dict:
    """手工记一笔（AI 与界面都走这个端点）：数量 3 × 单价 20.00 → 合计 60.00。"""
    body: dict = {
        "shipper_id": shipper_id,
        "entry_date": dt.date.today().isoformat(),
        "product_name": "TB10 合计一致性探针",
        "quantity": 3,
        "unit_price": "20.00",
        "note": "BUG-0025 探针，随后删除",
    }
    body.update(over)
    r = client.post("/api/v1/ledger/entries", json=body, headers=auth_headers(token))
    assert r.status_code in (200, 201), r.text
    return r.json()


def _account_total(client: TestClient, shipper_id: int, token: str) -> Decimal | None:
    today = dt.date.today()
    r = client.get(
        "/api/v1/ledger/accounts",
        params={
            "date_from": (today - dt.timedelta(days=366)).isoformat(),
            "date_to": today.isoformat(),
        },
        headers=auth_headers(token),
    )
    assert r.status_code == 200, r.text
    for bucket in r.json():
        if bucket.get("id") == shipper_id and not bucket.get("temp_name"):
            return Decimal(str(bucket.get("total")))
    return None


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_只把合计改成与数量单价不符的值会被拒(
    client: TestClient, users: dict, token_dispatcher: str, db_session
) -> None:
    """3 × 20.00 = 60.00 的一行，PATCH {"total": "288.00"} 必须 400，且一个数都不许动。"""
    sid = int(users["shipper"].id)
    row = _mk_manual_row(client, sid, token_dispatcher)
    assert Decimal(str(row["total"])) == Decimal("60.00"), row
    before_account = _account_total(client, sid, token_dispatcher)

    bad = client.patch(
        f"/api/v1/ledger/entries/{int(row['id'])}",
        json={"total": "288.00"},
        headers=auth_headers(token_dispatcher),
    )
    assert bad.status_code == 400, (
        f"合计与 数量×单价 不符却落库了（实际 {bad.status_code}）：同一行会变成两个答案"
        f" —— 数量 3 × 单价 20.00 = 60.00 vs 合计 {bad.json().get('total') if bad.status_code < 300 else '288.00'}"
    )
    detail = bad.json()["detail"]
    for want in ("288.00", "60.00", "数量", "单价", "合计"):
        assert want in detail, f"拒绝理由要能让人自己改对（缺 {want}）：{detail}"
    assert "数量 1" in detail or "单价 96.00" in detail, f"要给出可行的改法：{detail}"

    db_session.expire_all()
    still = db_session.get(Ledger, int(row["id"]))
    assert still is not None
    assert Decimal(str(still.total)) == Decimal("60.00"), "被拒绝的改动却真的落库了"
    assert Decimal(str(still.unit_price)) == Decimal("20.00")
    assert int(still.quantity) == 3
    assert _account_total(client, sid, token_dispatcher) == before_account, (
        "被拒绝的改动动了货主账（账户按 total 计，闸门必须在落库之前）"
    )


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_同时给出数量与单价就改得动合计(
    client: TestClient, users: dict, token_dispatcher: str
) -> None:
    """反向：一致就放行 —— 3 × 96.00 = 288.00（别把闸门做成"什么都拦"）。"""
    row = _mk_manual_row(client, int(users["shipper"].id), token_dispatcher)
    ok = client.patch(
        f"/api/v1/ledger/entries/{int(row['id'])}",
        json={"total": "288.00", "unit_price": "96.00"},
        headers=auth_headers(token_dispatcher),
    )
    assert ok.status_code == 200, ok.text
    out = ok.json()
    assert Decimal(str(out["total"])) == Decimal("288.00"), out
    assert Decimal(str(out["unit_price"])) == Decimal("96.00"), out
    assert int(out["quantity"]) == 3, out


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_只改数量或单价时合计跟着重算(
    client: TestClient, users: dict, token_dispatcher: str
) -> None:
    """老口径不变：没给 total 就按 数量×单价 重算（5 × 20.00 = 100.00）。"""
    row = _mk_manual_row(client, int(users["shipper"].id), token_dispatcher)
    r = client.patch(
        f"/api/v1/ledger/entries/{int(row['id'])}",
        json={"quantity": 5},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    assert Decimal(str(r.json()["total"])) == Decimal("100.00"), r.json()


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_只改备注绝不动钱(
    client: TestClient, users: dict, token_dispatcher: str, db_session
) -> None:
    """历史脏行（合计已经与数量单价不符）也不许被"顺手治一下"：改备注就是改备注。"""
    sid = int(users["shipper"].id)
    stale = Ledger(
        source=LedgerSource.MANUAL,
        shipper_id=sid,
        product_name="TB10 历史脏行探针",
        quantity=3,
        unit_price=Decimal("20.00"),
        total=Decimal("288.00"),
        entry_date=dt.date.today(),
    )
    db_session.add(stale)
    db_session.commit()

    r = client.patch(
        f"/api/v1/ledger/entries/{int(stale.id)}",
        json={"note": "只改备注"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    assert Decimal(str(r.json()["total"])) == Decimal("288.00"), (
        "改备注把这一行的金额改掉了 —— 历史行该长什么样就长什么样，不许顺手改钱"
    )


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_手工记账建行时合计也要与数量单价对得上(
    client: TestClient, users: dict, token_dispatcher: str
) -> None:
    """记一笔时同时给了三个数：对不上就 400（两个入口同一条规则）。"""
    sid = int(users["shipper"].id)
    bad = client.post(
        "/api/v1/ledger/entries",
        json={
            "shipper_id": sid,
            "entry_date": dt.date.today().isoformat(),
            "product_name": "TB10 建行对不上探针",
            "quantity": 3,
            "unit_price": "20.00",
            "total": "288.00",
        },
        headers=auth_headers(token_dispatcher),
    )
    assert bad.status_code == 400, (
        f"建行时就写进了两个答案（实际 {bad.status_code}）：{bad.text[:200]}"
    )
    assert "288.00" in bad.json()["detail"] and "60.00" in bad.json()["detail"], bad.json()

    # 反向：想记「整笔金额」就写 数量 1 / 单价 288.00 —— 这个能力没有被消灭
    ok = client.post(
        "/api/v1/ledger/entries",
        json={
            "shipper_id": sid,
            "entry_date": dt.date.today().isoformat(),
            "product_name": "TB10 整笔金额探针",
            "quantity": 1,
            "unit_price": "288.00",
        },
        headers=auth_headers(token_dispatcher),
    )
    assert ok.status_code in (200, 201), ok.text
    assert Decimal(str(ok.json()["total"])) == Decimal("288.00"), ok.json()


@pytest.mark.dispatcher
@pytest.mark.integration
def test_订单来的行仍按订单行金额记账(
    client: TestClient, users: dict, token_dispatcher: str, token_shipper: str, db_session
) -> None:
    """`source=order` 的行合计**就是订单行的金额**（可含让价，本来就可以 ≠ 数量×单价）：

    这条口径没被这一单改掉 —— 它另有「已送达/已退货」闸挡着（见 test_ledger_closed_gate.py）。
    """
    o = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "contact_dongjia_name": "收货人甲",
            "lines": [{"product_name_snapshot": "TB10 订单行", "quantity": 3, "unit_price": "20.00"}],
            "delivery_description": "TB10 订单行探针",
        },
    )
    assert o.status_code == 201, o.text
    oid = int(o.json()["id"])

    row = Ledger(
        source=LedgerSource.ORDER,
        order_id=oid,
        shipper_id=int(users["shipper"].id),
        product_name="TB10 订单行",
        quantity=3,
        unit_price=Decimal("20.00"),
        total=Decimal("50.00"),  # 让价后的订单行金额：本来就不等于 3 × 20.00
        entry_date=dt.date.today(),
    )
    db_session.add(row)
    db_session.commit()

    r = client.patch(
        f"/api/v1/ledger/entries/{int(row.id)}",
        json={"total": "50.00"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, (
        f"订单行的合计是订单行金额（权威在订单那一侧），不该被手工账的规则拦下：{r.status_code} {r.text[:200]}"
    )
    assert Decimal(str(r.json()["total"])) == Decimal("50.00"), r.json()

    db_session.expire_all()
    ops = client.get(
        f"/api/v1/order-products?order_id={oid}", headers=auth_headers(token_dispatcher)
    ).json()
    assert ops and Decimal(str(ops[0]["line_total"])) == Decimal("50.00"), (
        "改订单行金额要回写订单明细（sync_order_product_from_ledger），这条链路不许断"
    )
