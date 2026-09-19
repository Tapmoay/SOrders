"""第十九轮审计的回归测试：**没传运费 ≠ 把运费清空**（H3，高）。

## 缺陷形状（旧 H5 的单条派单路径）
`PATCH`/`POST /orders/{id}/assign` 的 `freight_fee` 缺省是 `None`，而端点是
**无条件** `order.freight_fee = body.freight_fee` —— 于是"派单时没填运费"会把订单上
**原有的运费清成 NULL**：

1. 司机没有计费规则时，他的应得 = `freight_fee`（`driver_pay` 的 PIECE 分支）→ **¥0.00**；
2. `post_delivery_accounting` 里 `if pay.total <= 0: return None` →
   **连账单都不生成、不报错、不留痕** —— 司机这一趟白跑，账面上查不到任何异常。

老 H5 的单条派单弹层**没有运费输入框**（批量派单那条路径不碰 `freight_fee`）→ 同一屏两个按钮
两个结果。本机旁证：132 张 `freight_fee` 为 NULL 的已送达单，`driver_bills` **0 条**。

⚠️ 为什么这条缺陷活了这么久：`tests/test_audit_round12_guards.py` 里那条运费口径测试
**正在做这件事**（建单 `freight_fee=1000` → `assign` 不传运费 → 已经被清成 NULL），
但它只断言 `driver_piece_amount`；隔壁那条注释还写着"订单运费是 1000，那是虚高"——
**作者以为 1000 还在**，只因那个司机挂了 `piece=100` 的规则才没露馅。
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from tests.conftest import auth_headers


def _mk_driver(client, h) -> tuple[int, str]:
    """建一个**按单计费**、且没有计费规则的司机（他的应得 = 订单运费）。"""
    phone = f"139{abs(hash('h3')) % 100000000:08d}"
    r = client.post(
        "/api/v1/users",
        json={
            "phone": phone,
            "password": "pass12345",
            "full_name": "H3探针司机",
            "role": "driver",
            # 没挂规则时：`resolve_billing_mode` 只有 trailer 默认 PIECE，
            # 所以这里必须显式给 piece —— 本用例要测的正是"运费=司机的钱"那条路径。
            "billing_mode": "piece",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"]), phone


def _driver_token(client, h, phone: str) -> str:
    r = client.post("/api/v1/auth/login", json={"phone": phone, "password": "pass12345"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _mk_order(client, h, shipper_id: int) -> int:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [
                {
                    "product_name_snapshot": "运费清空探针货",
                    "quantity": 1,
                    "unit_price": "100",
                    "line_total": "100",
                }
            ],
            "address_detail": "运费清空探针地址",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _set_freight(client, h, oid: int, value: str) -> None:
    """运费是在派单前单独补录的（`POST /orders/{id}/freight`）—— 建单 body 里没有这个键。"""
    r = client.post(f"/api/v1/orders/{oid}/freight", json={"freight_fee": value}, headers=h)
    assert r.status_code == 200, r.text


def test_assign_without_freight_keeps_the_existing_freight(
    client, token_dispatcher, users, db_session
):
    """派单时不传运费 → 订单上原有的运费**必须还在**（否则司机拿 0 元且不生成账单）。"""
    from app.models import Order

    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, h, users["shipper"].id)
    _set_freight(client, h, oid, "600")

    db_session.expire_all()
    before = db_session.get(Order, oid).freight_fee
    assert before is not None and Decimal(str(before)) == Decimal("600"), f"建单运费没落库：{before}"

    # 老 H5 就是只传 driver_id（没有运费输入框）
    r = client.post(
        f"/api/v1/orders/{oid}/assign", json={"driver_id": users["driver"].id}, headers=h
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    after = db_session.get(Order, oid).freight_fee
    assert after is not None and Decimal(str(after)) == Decimal("600"), (
        f"派单没传运费却把运费清成了 {after!r} —— 司机会拿到 ¥0.00，而且不会生成账单"
    )


def test_assign_with_freight_still_sets_it(client, token_dispatcher, users, db_session):
    """传了运费就照改（守卫不许把正常用法一起挡住）。"""
    from app.models import Order

    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, h, users["shipper"].id)
    _set_freight(client, h, oid, "600")
    r = client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "880"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert Decimal(str(db_session.get(Order, oid).freight_fee)) == Decimal("880")


def test_freight_survives_delivery_so_the_driver_gets_paid(
    client, token_dispatcher, users, db_session
):
    """端到端：建单带运费 → 派单不传运费 → 送达 → **必须生成账单且金额=运费**。"""
    from app.models import DriverBill, Order

    h = auth_headers(token_dispatcher)
    uid, phone = _mk_driver(client, h)
    oid = _mk_order(client, h, users["shipper"].id)
    _set_freight(client, h, oid, "777")
    r = client.post(f"/api/v1/orders/{oid}/assign", json={"driver_id": uid}, headers=h)
    assert r.status_code == 200, r.text
    dtok = _driver_token(client, h, phone)
    hd = auth_headers(dtok)
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hd).status_code == 200
    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=hd,
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    order = db_session.get(Order, oid)
    assert order.driver_billing_mode_snapshot == "PIECE", (
        f"没挂计费规则的司机应当是 PIECE（按运费全额），实际 {order.driver_billing_mode_snapshot}"
    )
    bills = list(db_session.scalars(select(DriverBill).where(DriverBill.order_id == oid)))
    assert bills, "送达之后没有生成司机账单（运费被清空时 pay.total<=0 → 静默不生成）"
    assert Decimal(str(bills[0].amount)) == Decimal("777"), f"账单金额是 {bills[0].amount}"
