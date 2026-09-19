"""司机钱的**三方对账**与结算语义（v3.39 缺陷挖掘第三轮）。

同一个司机的钱在三处出现，历史上它们各自抄过 `freight_fee`（v3.36 才收口到 `driver_pay`）：

| 地方 | 是什么 | 结算确认后 | 付款后 |
| --- | --- | --- | --- |
| `driver_bills`（OPEN 明细） | 每条待结明细 | 变 SETTLED（锁定，不能被第二张结算单占用） | 不变 |
| 绩效页 `freight_owed` | 应结 **− 已付款(PAID)** 的结算单 | **不变**（确认 ≠ 付钱） | **归零** |
| 运费结算页 | 本月司机运费**支出**（界面标题就是"支出合计"） | 不变 | 不变 |

最后两行是最容易吵起来的地方：**"确认"只是锁定明细，钱还没出去**，
所以绩效页的"待结"必须等付款才归零；而结算页那个数是"这个月他跑了多少"，
本来就该一直是全月合计。这条测试把三件事实钉死，免得以后有人"顺手"把它们改成一样。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers
from tests.test_driver_billing_api import _attach, _mk_driver, _mk_rule, _uniq


def _today_utc() -> str:
    """报表/绩效的锚点 = **业务当地日**（2026-09-19 审计 R12-M11；见 report_reconciliation 里的说明）。"""
    from app.core.business_time import business_today

    return business_today().isoformat()


def _deliver(client: TestClient, token_shipper: str, token_dispatcher: str, token_driver: str,
             driver_id: int, *, freight: str) -> int:
    r = client.post(
        "/api/v1/orders", headers=auth_headers(token_shipper),
        json={"lines": [{"product_name_snapshot": "对账探针货", "quantity": 1,
                         "unit_price": "80.00", "line_total": "80.00"}],
              "delivery_description": "对账探针"},
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert client.post(f"/api/v1/orders/{oid}/assign", headers=auth_headers(token_dispatcher),
                       json={"driver_id": driver_id, "freight_fee": freight,
                             "collect_cash": True}).status_code == 200
    assert client.post(f"/api/v1/orders/{oid}/driver-ack",
                       headers=auth_headers(token_driver)).status_code == 200
    assert client.post(f"/api/v1/orders/{oid}/complete", headers=auth_headers(token_driver),
                       json={"delivery_photo_urls": ["/static/uploads/delivery/rec.jpg"],
                             "payment": "cash"}).status_code == 200
    return oid


def _owed(client: TestClient, tok: str, driver_id: int) -> Decimal | None:
    r = client.get(f"/api/v1/stats/driver-performance?date_from={_today_utc()}&date_to={_today_utc()}",
                   headers=auth_headers(tok))
    assert r.status_code == 200, r.text
    rows = [x for x in r.json()["drivers"] if x["driver_id"] == driver_id]
    if not rows:
        return None
    v = rows[0].get("freight_owed")
    return None if v is None else Decimal(v)


@pytest.mark.dispatcher
@pytest.mark.driver
@pytest.mark.integration
def test_司机钱三方对账与结算语义(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """规则「每单 300 + 运费 5%」，两张单运费 1000 / 500 → 各 350 / 325。"""
    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    rule = _mk_rule(client, token_dispatcher, name=_uniq("对账规则"), vehicle_type="trailer",
                    salary="0", piece_amount="300", commission_base="freight", commission_rate="5")
    assert _attach(client, token_dispatcher, driver_id, rule["id"]).status_code == 200

    month = _today_utc()[:7]
    before = client.get(f"/api/v1/driver-bills?driver_id={driver_id}",
                        headers=auth_headers(token_dispatcher)).json()
    open_before = sum((Decimal(b["amount"]) for b in before
                       if b["bill_type"] == "piece" and b["status"] == "open"), Decimal("0"))

    oids = [
        _deliver(client, token_shipper, token_dispatcher, driver_tok, driver_id, freight="1000.00"),
        _deliver(client, token_shipper, token_dispatcher, driver_tok, driver_id, freight="500.00"),
    ]
    expected = Decimal("350.00") + Decimal("325.00")

    # ① 账单：按规则算出来的钱（不是运费）
    bills = client.get(f"/api/v1/driver-bills?driver_id={driver_id}",
                       headers=auth_headers(token_dispatcher)).json()
    bill_sum = sum((Decimal(b["amount"]) for b in bills
                    if b["bill_type"] == "piece" and b["status"] == "open"), Decimal("0")) - open_before
    assert bill_sum == expected, f"司机账单 {bill_sum} ≠ 手算 {expected}"

    # ② 绩效页待结
    assert _owed(client, token_dispatcher, driver_id) == expected

    # ③ 运费结算页（本月支出）
    settle = client.get(f"/api/v1/freight-settlement?month={month}",
                        headers=auth_headers(token_dispatcher)).json()
    grp = [g for g in settle["groups"] if g["driver_id"] == driver_id]
    assert grp and Decimal(str(grp[0]["total"])) == expected, f"结算页 {grp}"

    # ④ 结算：确认锁定明细，但"待结"要等**付款**才归零
    created = client.post("/api/v1/driver-settlements", headers=auth_headers(token_dispatcher),
                          json={"driver_id": driver_id, "month": month, "settle_type": "piece"})
    assert created.status_code in (200, 201), created.text
    sid = created.json()["id"]
    assert client.patch(f"/api/v1/driver-settlements/{sid}", headers=auth_headers(token_dispatcher),
                        json={"action": "confirm"}).status_code == 200
    after = client.get(f"/api/v1/driver-bills?driver_id={driver_id}",
                       headers=auth_headers(token_dispatcher)).json()
    still_open = [b for b in after
                  if b["bill_type"] == "piece" and b["status"] == "open" and b["order_id"] in oids]
    assert not still_open, f"确认后这批账单仍是待结：{[(b['order_id'], b['amount']) for b in still_open]}"
    assert _owed(client, token_dispatcher, driver_id) == expected, "只确认没付款时，「待结」不该变"

    # ⑤ 付款之后归零
    paid = client.patch(f"/api/v1/driver-settlements/{sid}", headers=auth_headers(token_dispatcher),
                        json={"action": "pay", "method": "cash"})
    assert paid.status_code == 200, paid.text
    assert _owed(client, token_dispatcher, driver_id) == Decimal("0"), "付款之后不该还算欠他"

    # ⑥ 一张账单不能被两张结算单各自占用（第二张确认时明细已被锁定）
    dup = client.post("/api/v1/driver-settlements", headers=auth_headers(token_dispatcher),
                      json={"driver_id": driver_id, "month": month, "settle_type": "piece"})
    assert dup.status_code == 400, dup.text          # 已经没有 OPEN 明细了


# ---------------------------------------------------------------- 付款那一刻复核明细
#
# 缺陷挖掘第 5 轮在库里查到一张 **已付款、0 条明细** 的结算单（352 元，探针：
# `_tools/qa/_probe_settlement_orphan.py`）。那张单是造数工具直接写库造出来的假账，
# 但它暴露的缝是真的：`pay_settlement` 原来只看状态（CONFIRMED 就付），
# 不核对明细还在不在、对不对得上。确认与付款是两次点击，中间明细可能已经没了
# （订单硬删、清理脚本、以后的数据保留策略都能造成），而钱付出去撤不回来。


def _settle(client: TestClient, tok: str, driver_id: int, month: str) -> tuple[int, str]:
    """建单 + 确认，返回 (结算单 id, 明细合计)。"""
    created = client.post("/api/v1/driver-settlements", headers=auth_headers(tok),
                          json={"driver_id": driver_id, "month": month, "settle_type": "piece"})
    assert created.status_code == 200, created.text
    sid = int(created.json()["id"])
    amount = Decimal(str(created.json()["amount"]))
    ok = client.patch(f"/api/v1/driver-settlements/{sid}", headers=auth_headers(tok),
                      json={"action": "confirm"})
    assert ok.status_code == 200, ok.text
    return sid, amount


def _paid_flows(db_session, sid: int) -> int:
    from sqlalchemy import text as _text

    return db_session.execute(
        _text("SELECT COUNT(*) FROM cash_flows WHERE doc_id = :d AND biz_type LIKE 'PAYMENT%'"),
        {"d": sid},
    ).scalar()


@pytest.mark.dispatcher
@pytest.mark.integration
def test_明细被删掉之后不许付款(
    client: TestClient, token_shipper: str, token_dispatcher: str, db_session
) -> None:
    """明细没了 → 付款必须被拒（400 + 中文），且状态与流水都不许动。"""
    from app.models import DriverBill, DriverSettlement

    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    month = _today_utc()[:7]
    _deliver(client, token_shipper, token_dispatcher, driver_tok, driver_id, freight="120.00")
    sid, amount = _settle(client, token_dispatcher, driver_id, month)
    assert amount == Decimal("120.00")

    # 模拟"明细被别的路径删掉"（不是通过任何接口——那正是这条检查要拦的场景）
    n = db_session.query(DriverBill).filter(DriverBill.settled_doc_id == sid).delete()
    db_session.commit()
    assert n == 1, f"该结算单名下应恰好 1 条明细，实际 {n}"

    r = client.patch(f"/api/v1/driver-settlements/{sid}", headers=auth_headers(token_dispatcher),
                     json={"action": "pay", "method": "cash"})
    assert r.status_code == 400, f"明细没了还让付款：{r.status_code} {r.text}"
    assert "明细" in r.text and "不能付款" in r.text, r.text

    db_session.expire_all()
    s = db_session.get(DriverSettlement, sid)
    status = str(getattr(s.status, "value", s.status))
    assert status == "confirmed", f"被拒之后结算单状态不该变（现在 {status!r}）"
    assert _paid_flows(db_session, sid) == 0, "被拒之后不该有付款流水（钱一分都没出去）"

    # 反向对照：**正常路径必须照常能付款**（否则上面那条可能只是"一律拒绝"）
    _deliver(client, token_shipper, token_dispatcher, driver_tok, driver_id, freight="60.00")
    sid2, amount2 = _settle(client, token_dispatcher, driver_id, month)
    assert amount2 == Decimal("60.00")
    ok = client.patch(f"/api/v1/driver-settlements/{sid2}", headers=auth_headers(token_dispatcher),
                      json={"action": "pay", "method": "cash"})
    assert ok.status_code == 200, ok.text
    assert _paid_flows(db_session, sid2) == 1, "正常付款必须写出付款流水"


@pytest.mark.dispatcher
@pytest.mark.integration
def test_明细金额或状态被改过之后不许付款(
    client: TestClient, token_shipper: str, token_dispatcher: str, db_session
) -> None:
    """金额对不上 / 明细被改回待结 / 明细换了司机 —— 三种都要拦住。"""
    from app.models import DriverBill

    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    month = _today_utc()[:7]
    _deliver(client, token_shipper, token_dispatcher, driver_tok, driver_id, freight="200.00")
    sid, _ = _settle(client, token_dispatcher, driver_id, month)
    bill = db_session.query(DriverBill).filter(DriverBill.settled_doc_id == sid).one()

    pay = lambda: client.patch(  # noqa: E731
        f"/api/v1/driver-settlements/{sid}", headers=auth_headers(token_dispatcher),
        json={"action": "pay", "method": "cash"},
    )

    bill.amount = Decimal(str(bill.amount)) + Decimal("10")
    db_session.commit()
    r = pay()
    assert r.status_code == 400 and "明细合计" in r.text, r.text

    bill.amount = Decimal(str(bill.amount)) - Decimal("10")
    bill.status = "open"  # type: ignore[assignment]
    db_session.commit()
    r = pay()
    assert r.status_code == 400 and "对不上" in r.text, r.text

    bill.status = "settled"  # type: ignore[assignment]
    bill.driver_id = driver_id + 100000
    db_session.commit()
    r = pay()
    assert r.status_code == 400, f"明细换了司机还能付款：{r.status_code} {r.text}"
    assert _paid_flows(db_session, sid) == 0, "三种被拒都不该留下付款流水"
