"""第十七轮审计的回归测试：**"派过单没有"的判据不许看流水**（预占补不回来 → 送达不扣库）。

红队审计员（只读）在本机实测出来的形状（`_archive/audit/FINDINGS.md` 第十七轮）：

> 「补预占」的守卫拿**"有没有 RESERVED 流水"**当"这张单派过没有"的判据，
> 而 `auto_stock_out` 是**逐行**写的、行的商品解析不出来时那一行一条流水都没有
> （手输商品名就是这么下单的，设计如此）。

于是这条链一路静默：

1. 手输商品名下单 → 派单（这一行**没有**预占流水）
2. 派单员在明细里把该行改成库里的商品（界面允许，此时货还没发）
3. 老守卫查到 0 条 RESERVED → 直接 `return 0` → **预占永远补不回来**
4. 送达时 `auto_stock_commit` 只遍历 RESERVED → 那一件货**一件都不扣**

本机只读复核（2026-09-19）：在途未删订单里"有商品编号却零预占"的 (单,商品) 对 **21** 个，
`GET /inventory/summary` 的「在途占用」与在途订单行有 **9** 个商品对不上（合计至少 72 件），
而 `note='订单行变更后重算预占'` 的流水**一行都没有** —— 这个守卫从来没放行过。

判据改成**订单自己的状态**（`dispatched_at`），重算期间锁住订单行
（两个并发的行编辑各写同一个差额 → 预占翻倍 → 送达**多扣**）。
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import InventoryMovement, Product
from tests.conftest import auth_headers


def _mk_product(client, h, name: str, stock: int = 100) -> int:
    r = client.post(
        "/api/v1/products",
        json={"name": name, "default_unit_price": "10", "cost_price": "4", "stock": stock},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _mk_order_with_freeform_line(client, h, shipper_id: int, name: str, qty: int) -> dict:
    """下单时**只给商品名、不给商品编号**（解析不出商品 → 派单时这一行不会写预占）。"""
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [
                {"product_name_snapshot": name, "quantity": qty, "unit_price": "10", "line_total": str(10 * qty)}
            ],
            "address_detail": "预占判据探针地址",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _assign(client, h, order_id: int, driver_id: int) -> None:
    r = client.post(
        f"/api/v1/orders/{order_id}/assign",
        json={"driver_id": driver_id, "freight_fee": "20"},
        headers=h,
    )
    assert r.status_code == 200, r.text


def _reserved(db_session, order_id: int) -> dict[int, int]:
    rows = db_session.scalars(
        select(InventoryMovement).where(
            InventoryMovement.order_id == order_id,
            InventoryMovement.source == "ORDER",
            InventoryMovement.status == "RESERVED",
        )
    ).all()
    out: dict[int, int] = {}
    for m in rows:
        out[m.product_id] = out.get(m.product_id, 0) + int(m.change)
    return out


def _stock(db_session, pid: int) -> int:
    db_session.expire_all()
    return int(db_session.get(Product, pid).stock or 0)


def test_binding_a_product_after_dispatch_creates_the_reservation(
    client, db_session, users, token_dispatcher, token_driver
):
    """手输商品名 → 派单（零预占）→ 改行绑商品 → 送达：库存必须**真的减**。

    老守卫在第二步 `return 0`：预占一条都不写，送达时 `auto_stock_commit` 遍历不到任何
    RESERVED 流水 → 这件货**一件都不扣**，而接口全程 200。
    """
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, "预占判据探针货", stock=50)
    order = _mk_order_with_freeform_line(client, h, users["shipper"].id, "手输的货名", 3)

    _assign(client, h, order["id"], users["driver"].id)
    db_session.expire_all()
    assert _reserved(db_session, order["id"]) == {}, (
        "前提不成立：手输商品名的行居然已经有预占了（那这条测试就测不到判据）"
    )

    line = client.get(f"/api/v1/order-products?order_id={order['id']}", headers=h).json()[0]
    r = client.patch(f"/api/v1/order-products/{line['id']}", json={"product_id": pid}, headers=h)
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert _reserved(db_session, order["id"]) == {pid: -3}, (
        f"改行绑上商品之后预占没补上：{_reserved(db_session, order['id'])} —— 送达时这件货一件都不会扣"
    )

    before = _stock(db_session, pid)
    hd = auth_headers(token_driver)
    r = client.post(f"/api/v1/orders/{order['id']}/driver-ack", headers=hd)
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/orders/{order['id']}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=hd,
    )
    assert r.status_code == 200, r.text
    assert _stock(db_session, pid) == before - 3, (
        f"送达之后库存是 {_stock(db_session, pid)}，应当是 {before - 3} —— 这件货一件都没扣"
    )


def test_editing_lines_of_an_undispatched_order_creates_no_reservation(
    client, db_session, users, token_dispatcher
):
    """没派过单的单：改行**不该**凭空造出预占（判据换成 `dispatched_at` 之后不许误伤这条）。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, "未派单探针货", stock=30)
    order = _mk_order_with_freeform_line(client, h, users["shipper"].id, "未派单探针货", 2)

    line = client.get(f"/api/v1/order-products?order_id={order['id']}", headers=h).json()[0]
    r = client.patch(f"/api/v1/order-products/{line['id']}", json={"product_id": pid}, headers=h)
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert _reserved(db_session, order["id"]) == {}, "没派过单的单不该有预占"
    assert _stock(db_session, pid) == 30, "没派单就不该动库存"


def test_recalled_order_line_edit_creates_no_reservation(client, db_session, users, token_dispatcher):
    """撤回派单之后（`dispatched_at` 被清空）：改行也不该再补预占（那时预占已释放）。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, "撤回后再改行探针货", stock=40)
    order = _mk_order_with_freeform_line(client, h, users["shipper"].id, "撤回探针手输行", 1)
    _assign(client, h, order["id"], users["driver"].id)
    r = client.post(
        f"/api/v1/orders/{order['id']}/recall", json={"reason": "探针撤回"}, headers=h
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert _reserved(db_session, order["id"]) == {}

    line = client.get(f"/api/v1/order-products?order_id={order['id']}", headers=h).json()[0]
    r = client.patch(f"/api/v1/order-products/{line['id']}", json={"product_id": pid, "quantity": 5}, headers=h)
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert _reserved(db_session, order["id"]) == {}, "撤回之后不该再按新行补预占（重新派单时会按当时的行重算）"
