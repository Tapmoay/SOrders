"""「动钱」的写端点必须留下操作日志（2026-09-19 审计的缺陷 M9）。

## 原来是什么样
`docs/ACCOUNTING_V2_DESIGN.md` §4.10 写着「所有写账接口（收款 / 结算 / 开销 / 手工补单 / 客户合并）
都要写 operation_logs」，而实际代码里这几条路径**一条日志都不写**：

| 端点 | 动了什么钱 | 原来有日志吗 |
|---|---|---|
| `POST /ledger/receipts` | 收款单 + 现金流水 + 把订单标已收款 | ❌ |
| `POST /driver-settlements` | 锁定一批待结明细 | ❌ |
| `PATCH /driver-settlements/{id}` | 确认 / **付款**（钱真的出去）/ 作废 | ❌ |
| `POST /expenses` | 开销 + 现金流出 | ❌ |
| `POST /driver-bills/generate` | 造出可支付的应付 | ❌ |
| `POST /customers/merge` | 改写账本与收款单归属 + 删档案 | ❌ |

后果不是"审计页少几条"，而是**事后无法回答"这笔钱谁录的、这张单谁点的付款"** ——
对账时只能看着金额猜。这里逐条钉住。
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import OperationLog
from tests.conftest import auth_headers


def _bill_month(db_session, driver_id: int) -> str:
    """该司机**现存待结明细**的月份（由后端在送达时按 UTC 生成）。"""
    from app.models import DriverBill

    db_session.expire_all()
    bill = db_session.scalars(
        select(DriverBill).where(DriverBill.driver_id == driver_id, DriverBill.status == "open")
    ).first()
    assert bill is not None, (
        "探针前提不成立：这张送达的单没有生成待结明细"
        "（多半是这个司机挂着工资制规则 / 已有结算单把它收走了）"
    )
    return bill.month


def _logs(db_session, action: str) -> list[tuple[OperationLog, dict]]:
    """返回 [(日志行, 解析后的 change 内容)]。

    ⚠️ 字段名是 `change_content`（JSON **文本**，见 `models/operation_log.py`），不是 `change_payload`
    —— 后者是 `write_log` 的入参名。这里顺手把文本解析成 dict，免得每条断言都写 json.loads。
    """
    import json

    db_session.expire_all()
    rows = list(db_session.scalars(select(OperationLog).where(OperationLog.action == action)))
    out: list[tuple[OperationLog, dict]] = []
    for r in rows:
        try:
            payload = json.loads(r.change_content or "{}")
        except ValueError:
            payload = {}
        out.append((r, payload if isinstance(payload, dict) else {}))
    return out


def test_expense_create_writes_log(client, db_session, token_dispatcher):
    h = auth_headers(token_dispatcher)
    r = client.post(
        "/api/v1/expenses",
        json={"exp_date": "2026-09-19", "category": "fuel", "amount": "120.50", "note": "审计探针加油"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    rows = [(x, c) for x, c in _logs(db_session, "EXPENSE_CREATE") if c.get("expense_id") == eid]
    assert rows, "记开销必须留痕（钱出去了，审计页要能查到是谁记的）"
    assert rows[-1][0].operator_id is not None


def test_receipt_create_writes_log(client, db_session, users, token_dispatcher, token_shipper, token_driver):
    h = auth_headers(token_dispatcher)
    # 需要一张该客户名下、已送达、未收款的单 → 走最小链路造一张
    cust = client.post(
        "/api/v1/customers",
        json={"name": "留痕探针客户", "user_id": users["shipper"].id},
        headers=h,
    )
    assert cust.status_code in (200, 201), cust.text
    cid = cust.json()["id"]

    o = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [{"product_name_snapshot": "留痕探针货", "quantity": 1, "unit_price": "80"}],
            "address_detail": "留痕探针地址",
        },
        headers=h,
    ).json()
    client.post(f"/api/v1/orders/{o['id']}/assign",
                json={"driver_id": users["driver"].id, "freight_fee": "20"}, headers=h)
    hd = auth_headers(token_driver)
    client.post(f"/api/v1/orders/{o['id']}/driver-ack", headers=hd)
    client.post(f"/api/v1/orders/{o['id']}/complete",
                json={"delivery_photo_urls": ["/static/uploads/delivery/log.jpg"]}, headers=hd)

    r = client.post(
        "/api/v1/ledger/receipts",
        json={
            "customer_id": cid, "amount": "80.00", "method": "cash",
            "settle_mode": "itemized", "order_ids": [o["id"]], "received_at": "2026-09-19",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    rid = r.json()["id"]
    rows = [(x, c) for x, c in _logs(db_session, "RECEIPT_CREATE") if c.get("receipt_id") == rid]
    assert rows, "客户收款必须留痕（这笔钱谁录的，事后必须答得上来）"
    assert rows[-1][1].get("amount") == "80.00"


def test_settlement_pay_writes_log(client, db_session, users, token_dispatcher, token_driver):
    """**付款**是最要紧的一条：钱真的出去了，审计页必须看得到。"""
    h = auth_headers(token_dispatcher)
    # 先给司机挂一份"每单 50"的规则：不然送达不生成按单应付（`has_per_order_pay` 为假），
    # 后面就没有待结明细可结算 —— 而这条测试要验的正是"结算付款留痕"。
    rule = client.post(
        "/api/v1/driver-billing-rules",
        # 不限车型：测试司机没设车型，规则限车型会被 attach 拒绝（"车型对不上"）
        json={"name": "留痕探针规则", "piece_amount": "50"},
        headers=h,
    )
    assert rule.status_code in (200, 201), rule.text
    attached = client.post(
        "/api/v1/driver-billing-rules/attach",
        json={"driver_id": users["driver"].id, "rule_id": rule.json()["id"]},
        headers=h,
    )
    assert attached.status_code in (200, 201), attached.text
    o = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [{"product_name_snapshot": "留痕探针货2", "quantity": 1, "unit_price": "100"}],
            "address_detail": "留痕探针地址",
        },
        headers=h,
    ).json()
    client.post(f"/api/v1/orders/{o['id']}/assign",
                json={"driver_id": users["driver"].id, "freight_fee": "60"}, headers=h)
    hd = auth_headers(token_driver)
    client.post(f"/api/v1/orders/{o['id']}/driver-ack", headers=hd)
    client.post(f"/api/v1/orders/{o['id']}/complete",
                json={"delivery_photo_urls": ["/static/uploads/delivery/log2.jpg"]}, headers=hd)

    r = client.post(
        "/api/v1/driver-settlements",
        # ⚠️ 月份必须按**后端算出来的那个月**（账单月来自 `delivered_at`，基准是 UTC）——
        #    写死字符串会在"本地日期与 UTC 差一天"的那几个小时里失败。
        json={"driver_id": users["driver"].id, "month": _bill_month(db_session, users["driver"].id),
              "settle_type": "piece"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    sid = r.json()["id"]
    created = [c for _x, c in _logs(db_session, "SETTLEMENT_CREATE") if c.get("settlement_id") == sid]
    assert created, "建结算单必须留痕（且 settlement_id 必须写进去，不能是 null）"

    assert client.patch(f"/api/v1/driver-settlements/{sid}", json={"action": "confirm"}, headers=h).status_code == 200
    assert client.patch(f"/api/v1/driver-settlements/{sid}",
                        json={"action": "pay", "method": "cash"}, headers=h).status_code == 200
    pay_logs = [c for _x, c in _logs(db_session, "SETTLEMENT_STATUS")
                if c.get("settlement_id") == sid and c.get("action") == "pay"]
    assert pay_logs, "结算付款必须留痕（这是真正把钱付出去的那一下）"


def test_customer_merge_writes_log(client, db_session, token_dispatcher):
    h = auth_headers(token_dispatcher)
    a = client.post("/api/v1/customers", json={"name": "留痕探针-保留"}, headers=h).json()
    b = client.post("/api/v1/customers", json={"name": "留痕探针-被并"}, headers=h).json()
    r = client.post("/api/v1/customers/merge", json={"keep_id": a["id"], "merge_ids": [b["id"]]}, headers=h)
    assert r.status_code in (200, 201), r.text
    rows = [(x, c) for x, c in _logs(db_session, "CUSTOMER_MERGE") if c.get("keep_id") == a["id"]]
    assert rows, "客户合并必须留痕（它改写了账本与收款单的归属）"
