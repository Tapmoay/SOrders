"""退现那一行的**对象名**必须是这笔钱的货主（2026-09-23 第 15 轮，真机 E2E 抓到）。

## 缺陷现场（真机走「派单(收现金) → 司机收现金送达 → 货主申请退货 → 派单员办理」时看到）

退款流水的「对象」列写着 **「临时货主」**，而那张单在账本/订单页上写的是「永盛食品」——
同一笔钱两个名字。根因在 `order_return` 原来那一行：

```python
party_name = cust.name if cust else ((order.temp_shipper_name or "").strip() or "临时货主")
```

`cust = resolve_customer_for_order(db, order)` 查的是**客户档案行**（`customers.user_id`），
而**不是每个注册货主都有客户档案**（生产 34 个货主账号里 32 个有 → 那 2 个的单一旦退现就会写成
「临时货主」；本机开发库里货主 2 就没有档案，所以真机一退就现形）。

⚠️ 这条规矩**本仓库早就写过**（`services/ledger_response._shipper_name` 的注释：
"宁可给个编号，也不要给一个'临时货主'——那会把**注册货主的账说成临时货主的**"），
只是那一份用在了**账本出参**上，退款流水这一处漏了 —— 同一件事两份实现、只改了其中一份。
现在两边共用 `ledger_response.order_shipper_label(db, order)`。

## 判据

1. **注册货主且没有客户档案** → 退现的对象名是**那个人的名字**（不是「临时货主」）；
2. **临时货主**（无账号）→ 用它那句称呼；两者都没有 → 「临时货主」（这一档仍然保留）；
3. 顺带把「同一笔钱两个名字」这条钉死：**退款流的对象名 == 订单出参里的货主名**。
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models import CashFlow, Customer
from app.services.ledger_response import order_shipper_label
from tests.conftest import auth_headers


def _uniq(prefix: str) -> str:
    return f"{prefix}-{random.randint(100000, 999999)}"


def _deliver_and_return(client: TestClient, h: dict[str, str], users: dict) -> tuple[int, list[int]]:
    """走真实链路：建单 → 派单(收现金) → 接单 → 收现金送达 → 退货（整单）→ 返回 (订单 id, 要清理的 id)。"""
    from app.services.auth_service import issue_token

    dtoken = issue_token(users["driver"])
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [{"product_name_snapshot": _uniq("退现对象探针货"), "quantity": 2,
                       "unit_price": "10", "line_total": "20"}],
            "address_detail": "退现对象探针路 1 号",
            "freight_fee": "5",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    oid = int(r.json()["id"])
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "collect_cash": True}, headers=h,
    ).status_code in (200, 201)
    hd = auth_headers(dtoken)
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hd).status_code in (200, 201)
    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"payment": "cash", "delivery_photo_urls": [f"/static/uploads/delivery/{oid}/probe.jpg"]},
        headers=hd,
    )
    assert r.status_code in (200, 201), r.text
    # 退货（整单：数量 = 2）
    detail = client.get(f"/api/v1/order-products?order_id={oid}", headers=h)
    assert detail.status_code == 200, detail.text
    rows = detail.json()
    assert rows, "订单行查不到"
    r = client.post(
        f"/api/v1/orders/{oid}/return",
        json={"items": [{"order_product_id": rows[0]["id"], "quantity": 2}]},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return oid, [oid]


def _cleanup(db: Session, order_ids: list[int]) -> None:
    from sqlalchemy import delete as _d

    from app.models import Ledger, OperationLog, Order, OrderProduct
    from app.models.place import Place

    if not order_ids:
        return
    db.execute(update(Place).where(Place.first_order_id.in_(order_ids)).values(first_order_id=None))
    db.execute(update(Order).where(Order.parent_order_id.in_(order_ids)).values(parent_order_id=None))
    db.execute(_d(CashFlow).where(CashFlow.order_id.in_(order_ids)))
    for model, col in ((Ledger, Ledger.order_id), (OperationLog, OperationLog.order_id),
                       (OrderProduct, OrderProduct.order_id)):
        db.execute(_d(model).where(col.in_(order_ids)))
    db.execute(update(Order).where(Order.id.in_(order_ids)).values(deleted_at=None))
    db.execute(_d(Order).where(Order.id.in_(order_ids)))
    db.commit()


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_refund_row_names_the_registered_shipper_even_without_a_customer_row(
    client: TestClient, token_dispatcher: str, db_session: Session, users: dict
) -> None:
    """**注册货主 + 没有客户档案** → 退现对象名是那个人的名字（不是「临时货主」）。"""
    # 先把这位货主的客户档案删掉 —— 生产上确实有这种账号（34 个里 2 个没有档案）
    stale = db_session.scalars(select(Customer).where(Customer.user_id == users["shipper"].id)).all()
    backup = [(c.id, c.user_id, c.name) for c in stale]
    db_session.execute(delete(Customer).where(Customer.user_id == users["shipper"].id))
    db_session.commit()
    h = auth_headers(token_dispatcher)
    oid, ids = _deliver_and_return(client, h, users)
    try:
        flows = db_session.scalars(
            select(CashFlow).where(CashFlow.order_id == oid, CashFlow.biz_type == "REFUND_CUSTOMER")
        ).all()
        assert flows, "退货没有写退现流水（说明这单压根没结过账，这条判据没被覆盖到）"
        name = flows[0].party_name
        assert name != "临时货主", (
            f"退现对象名写成了「临时货主」，而这单的货主是注册账号 {users['shipper'].full_name}："
            "同一笔钱在资金收支与账本上两个名字（真机 E2E 抓到的那个缺陷）"
        )
        assert name == (users["shipper"].full_name or users["shipper"].phone), name
        # 与订单出参同源：出参里的货主名与流水上的对象名必须是同一个
        detail = client.get(f"/api/v1/orders/{oid}", headers=h)
        assert detail.status_code == 200, detail.text
        order = db_session.get(type(users["shipper"]), users["shipper"].id)  # 触发会话刷新
        assert order is not None
        from app.models import Order

        row = db_session.get(Order, oid)
        assert order_shipper_label(db_session, row) == name
        assert Decimal(str(detail.json()["refunded_amount"])) == Decimal("20.00")
    finally:
        db_session.rollback()
        for cid, uid, cname in backup:
            db_session.add(Customer(id=cid, user_id=uid, name=cname))
        db_session.commit()
        _cleanup(db_session, ids)


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_refund_row_falls_back_to_the_temp_name_for_accountless_shippers(
    client: TestClient, token_dispatcher: str, db_session: Session, users: dict
) -> None:
    """**临时货主**（无账号）→ 用它那句称呼；这才是「临时货主」这个兜底该出现的地方。"""
    from app.models import Order

    h = auth_headers(token_dispatcher)
    temp_name = _uniq("退现对象临时货主")
    r = client.post(
        "/api/v1/orders",
        json={
            "temp_shipper_name": temp_name,
            "lines": [{"product_name_snapshot": _uniq("退现对象临时货"), "quantity": 1,
                       "unit_price": "10", "line_total": "10"}],
            "address_detail": "退现对象探针路 2 号",
            "freight_fee": "0",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    oid = int(r.json()["id"])
    try:
        row = db_session.get(Order, oid)
        db_session.refresh(row)
        assert row.shipper_id is None
        assert order_shipper_label(db_session, row) == temp_name
    finally:
        _cleanup(db_session, [oid])
