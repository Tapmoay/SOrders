"""「按分类定价 + 这一单没有分类」必须**留痕**，不许静默算成 0 元（2026-09-24 第 31 轮）。

这一条补的是第 30 轮（R11-3）欠下的**永久仓库测试**：那一轮只做了直连服务层验证。

## 缺陷（第 25 轮 06 区缺陷 1，[高]）
`driver_pay` 早就算出了 `OrderPay.category_unmatched`（"规则是按分类定价，但这一单没匹配到分类"），
而**全仓一个消费点都没有**。于是 `generate_piece_bill` 见 `pay.total <= 0` 直接 `return None`：
不建明细、不写日志、不给原因 —— 订单在司机账单页与运费结算页**同时消失**，
司机白跑一趟、派单员看得见"已送达"却看不出异常，**月底对账才发现少了一单**。

## 判据（走完整链路：建规则 → 挂司机 → 派单 → 接单 → 送达）
1. **没分类的按分类规则** → 不建账单（金额确实是 0，这一条行为不变）；
2. 但**必须有一条** `driver_bill_unmatched_category` 的操作日志（话术要能照着改）；
3. **反空转**：统一金额的规则（不是按分类）正常送达 → **有账单、且没有那条日志** ——
   否则"说出来"会变成"每张单都记一笔"，而噪音等于没说。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.models import DriverBill, FreightCategory, OperationLog
from tests.conftest import auth_headers


def _mk_driver(client: TestClient, h: dict, name: str) -> tuple[int, dict]:
    """建一个司机并**用他自己的账号登录**（送达要用司机本人 token）。"""
    phone = "13" + uuid.uuid4().hex[:9].translate(str.maketrans("abcdef", "012345"))
    r = client.post(
        "/api/v1/users",
        headers=h,
        json={"phone": phone, "password": "pass12345", "full_name": name, "role": "driver"},
    )
    assert r.status_code in (200, 201), r.text
    did = int(r.json()["id"])
    r = client.post("/api/v1/auth/login", json={"phone": phone, "password": "pass12345"})
    assert r.status_code == 200, r.text
    return did, {"Authorization": f"Bearer {r.json()['access_token']}"}


def _deliver(client: TestClient, h: dict, hd: dict, shipper_id: int, driver_id: int) -> int:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [{"product_name_snapshot": "分类留痕探针", "quantity": 1, "unit_price": "10"}],
            "address_detail": "分类留痕探针",
            "delivery_description": "分类留痕探针",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": driver_id, "freight_fee": "100"},
        headers=h,
    ).status_code == 200
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hd).status_code == 200
    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=hd,
    )
    assert r.status_code == 200, r.text
    return oid


def _logs(db_session, oid: int) -> list[str]:
    db_session.expire_all()
    return [
        lg.change_content or ""
        for lg in db_session.scalars(
            select(OperationLog).where(OperationLog.order_id == oid)
        )
    ]


@pytest.mark.dispatcher
@pytest.mark.regression
def test_按分类定价没匹配到分类_不建账单但必须留痕(
    client: TestClient, db_session, users: dict, token_dispatcher: str
) -> None:
    h = auth_headers(token_dispatcher)
    suffix = uuid.uuid4().hex[:6]
    cat = FreightCategory(name=f"留痕探针分类-{suffix}")
    db_session.add(cat)
    db_session.commit()

    did, hd = _mk_driver(client, h, f"留痕探针司机-{suffix}")
    r = client.post(
        "/api/v1/driver-billing-rules",
        headers=h,
        json={
            "name": f"留痕探针规则-{suffix}",
            "piece_mode": "category",
            "piece_amount": "0",
            "categories": [{"category_id": cat.id, "piece_amount": "25"}],
            "remark": "按分类定价留痕探针",
        },
    )
    assert r.status_code == 201, r.text
    rid = int(r.json()["id"])
    assert client.post(
        "/api/v1/driver-billing-rules/attach",
        json={"driver_id": did, "rule_id": rid},
        headers=h,
    ).status_code == 200

    # 这一单**没有运费分类** → 规则算不出钱
    oid = _deliver(client, h, hd, users["shipper"].id, did)

    db_session.expire_all()
    bills = list(db_session.scalars(select(DriverBill).where(DriverBill.order_id == oid)))
    assert bills == [], f"算出来是 0 元，不该建账单：{[(b.id, str(b.amount)) for b in bills]}"

    logs = _logs(db_session, oid)
    hit = [x for x in logs if "driver_bill_unmatched_category" in x]
    assert hit, (
        "按分类定价但这一单没匹配到分类 → 算出来是 0、没建账单，**却一条日志都没写**："
        "订单会从司机账单页与结算页同时消失，司机白跑一趟且月底才发现。"
        f"该单的日志：{logs}"
    )
    assert "没有匹配到任何分类" in hit[0], f"留痕的话术要能照着改：{hit[0]}"
    assert "补一档金额" in hit[0], f"要给出路（哪种改法能修好）：{hit[0]}"


@pytest.mark.dispatcher
@pytest.mark.regression
def test_统一金额的规则正常建账单_且不写那条日志(
    client: TestClient, db_session, users: dict, token_dispatcher: str
) -> None:
    """**反空转**：不是按分类的规则照旧建账单，且不许写那条"没匹配到分类"的日志。"""
    h = auth_headers(token_dispatcher)
    suffix = uuid.uuid4().hex[:6]
    did, hd = _mk_driver(client, h, f"反空转司机-{suffix}")
    r = client.post(
        "/api/v1/driver-billing-rules",
        headers=h,
        json={
            "name": f"反空转规则-{suffix}",
            "piece_amount": "80",
            "remark": "统一每单金额",
        },
    )
    assert r.status_code == 201, r.text
    assert client.post(
        "/api/v1/driver-billing-rules/attach",
        json={"driver_id": did, "rule_id": int(r.json()["id"])},
        headers=h,
    ).status_code == 200

    oid = _deliver(client, h, hd, users["shipper"].id, did)

    db_session.expire_all()
    bills = list(db_session.scalars(select(DriverBill).where(DriverBill.order_id == oid)))
    assert len(bills) == 1, f"统一金额的规则应当正常建账单：{bills}"
    assert str(bills[0].amount) == "80.00", bills[0].amount
    assert not [x for x in _logs(db_session, oid) if "driver_bill_unmatched_category" in x], (
        "没匹配到分类这条日志**只该在按分类定价且确实没匹配到时**写 —— 现在它每张单都写，"
        "那就变成噪音（噪音等于没说）"
    )
