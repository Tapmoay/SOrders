"""订单明细编辑与状态跃迁之间**没有互斥**：编辑必须先看到"这一刻的真实状态"。

## 这一轮抓到的东西（2026-09-23 第 6 轮，逐域核对"读状态 → 判断 → 写"）

`order_products.py` 的三个写端点（新建/改/删明细）的守卫是这么写的：

    order = db.get(Order, op.order_id)          # ← 普通 SELECT，读的是**身份映射里那份**
    if not _order_allows_line_edit(order):      # ← 判据挂在**那一刻读到**的状态上
        raise 400

而司机送达走的是另一条完全不同的路（`order_flow.complete_delivery`）：
它用**条件 UPDATE** 抢占 `ACCEPTED → DELIVERED`，成功之后立刻按**当时的订单行**
写出账本（`ledger_sync.sync_ledger_from_delivered_order`，一行一条、按 `order_product_id` 幂等）。

于是并发下有这么一条缝：

| 时刻 | 派单员（改明细） | 司机（点送达） |
|---|---|---|
| T1 | 读到订单 = 已接单 ✔ 放行 | |
| T2 | | 抢占成功：订单 = 已送达，账本按**改前**的行金额写入 |
| T3 | 写入新数量/新金额（没人再拦它） | |

→ 终态是**「已送达」的订单，行金额是新的、账本金额是旧的**。
两个数各说各的，而**没有任何地方会报错**：收款按账本收、报表按订单行算毛利，
用户要到对账时才发现差一笔。这正是这个项目反复在治的那一类缺陷。

⚠️ 顺序执行时它是好的（送达后 `_order_allows_line_edit` 直接拒），所以探针/单测
只要**串行**打就永远绿 —— 必须把"手上那份是旧状态"这一刻单独造出来。

### 这两条测试怎么造出那一刻
`conftest` 的 `client` 与 `db_session` **共用同一个 Session**（`override_get_db` yield 同一个），
所以：先用 `db_session.get()` 把订单读进身份映射（此刻 ACCEPTED），再用一条原生 UPDATE
把库里的行改成 DELIVERED（**模拟"另一个请求已经送达并提交了"**），
此时"库里的行"与"手上的对象"状态不一致 —— 正是并发窗口里那一瞬间的样子。
修好之后，端点必须先取锁/重读再判，于是第二条断言会变成 400。

这不是"多线程打同一个 app"（那种测试在本项目会撞 SQLite 的 `InterfaceError`，见
`test_concurrent_delivery_money.py` 的说明），而是把**并发窗口里的那个状态**确定性地摆出来。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select, text
from starlette.testclient import TestClient

from app.models import Order, OrderProduct, Product
from app.models.enums import OrderStatus
from app.models.inventory import InventoryMovement
from app.services.order_flow import lock_order_row
from tests.conftest import auth_headers


def _accepted_order(client: TestClient, db_session, token_disp: str, token_drv: str,
                    users: dict) -> tuple[int, int, int]:
    """建一张「已接单」的单，返回 (订单 id, 明细行 id, 行数量)。"""
    users["driver"].billing_mode = "piece"
    db_session.commit()
    r = client.post(
        "/api/v1/orders",
        json={
            "lines": [{"product_name_snapshot": "改行竞态货", "quantity": 2, "unit_price": "50"}],
            "shipper_id": users["shipper"].id,
        },
        headers=auth_headers(token_disp),
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    a = client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "60.00", "collect_cash": True},
        headers=auth_headers(token_disp),
    )
    assert a.status_code in (200, 201, 204), a.text
    k = client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_drv))
    assert k.status_code in (200, 201, 204), k.text
    line = db_session.scalars(
        select(OrderProduct).where(OrderProduct.order_id == oid).order_by(OrderProduct.id)
    ).first()
    assert line is not None
    return oid, int(line.id), int(line.quantity)


def test_stale_status_must_not_let_line_edit_through(
    client: TestClient, db_session, token_dispatcher: str, token_driver: str, users: dict
) -> None:
    """① 库里已经是「已送达」、手上那份还停在「已接单」→ 改明细必须被拒。

    ⛔ 这条断言的意义：判据只许挂在**数据库里这一刻的真实状态**上。
    挂在身份映射里那份旧对象上，就等于"并发窗口里看运气"。
    """
    oid, line_id, qty = _accepted_order(client, db_session, token_dispatcher, token_driver, users)

    order = db_session.get(Order, oid)
    assert order is not None and order.status == OrderStatus.ACCEPTED, "前置：这一单此刻是已接单"
    # 模拟"另一个请求（司机送达）已经提交"：库里的行变了，手上的对象没变。
    db_session.execute(text("UPDATE orders SET status='DELIVERED' WHERE id=:i"), {"i": oid})

    r = client.patch(
        f"/api/v1/order-products/{line_id}",
        json={"quantity": qty + 1},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 400, (
        f"已送达的订单不该还能改明细（实际 {r.status_code}）—— "
        "守卫读的是身份映射里那份旧状态，并发下会让「行金额 ≠ 账本金额」"
    )


def test_lock_order_row_returns_the_fresh_row(db_session, users: dict) -> None:
    """② 机制：`lock_order_row` 必须把**库里这一刻**的状态交回给调用方。

    这是①的修法所依赖的那一步。它被"简化"掉（比如改回 `db.get`）之后，
    ①会重新变红 —— 但那时报错的位置离根因很远，所以这里单独钉一次。
    """
    order = Order(
        order_no="LOCKROW-TEST-1",
        status=OrderStatus.ACCEPTED,
        shipper_id=users["shipper"].id,
        order_date=date.today(),
    )
    db_session.add(order)
    db_session.commit()
    oid = int(order.id)

    stale = db_session.get(Order, oid)
    assert stale is not None and stale.status == OrderStatus.ACCEPTED
    db_session.execute(text("UPDATE orders SET status='CANCELLED' WHERE id=:i"), {"i": oid})

    fresh = lock_order_row(db_session, stale)
    assert fresh.status == OrderStatus.CANCELLED, (
        "lock_order_row 必须重读到最新状态（拿它去判「这单还能不能改」才有意义）"
    )


def test_resync_reservations_skips_finished_orders(db_session, users: dict) -> None:
    """③ 兜底：已送达的单**不许**再补预占流水。

    `_resync_stock_if_assigned` 原来的判据只有"派过单没有"（`dispatched_at is not None`），
    而这一列在送达后**不会清掉** → 一旦有人（并发窗口里）改了已送达单的明细，
    `resync_reservations` 会按新行补出 RESERVED 流水：那张单早就扣过库存了，
    这些流水没人再消费，只会在「在途占用」里永久挂着（用户按它决定要不要补货）。
    """
    from app.api.v1.order_products import _resync_stock_if_assigned

    # ⚠️ 行上**必须带一个真实商品**：`resync_reservations` 只对"能解析出商品编号的行"写流水
    #    （手输商品名的行一条都不写，这是设计如此）。不带商品的话这条断言会因为
    #    "本来就没东西可写"而通过 —— 那就成了一条永远绿的假判据。
    prod = Product(name="竞态测试货", unit="件", default_unit_price=10, stock=100)
    db_session.add(prod)
    db_session.flush()
    order = Order(
        order_no="RESYNC-TEST-1",
        status=OrderStatus.DELIVERED,
        shipper_id=users["shipper"].id,
        order_date=date.today(),
        dispatched_at=date.today(),
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(
        OrderProduct(
            order_id=order.id,
            product_id=prod.id,
            product_name_snapshot="竞态测试货",
            quantity=3,
            unit_price=10,
            line_total=30,
        )
    )
    db_session.commit()

    created = _resync_stock_if_assigned(db_session, order, users["dispatcher"].id)
    db_session.commit()
    rows = db_session.scalars(
        select(InventoryMovement).where(InventoryMovement.order_id == order.id)
    ).all()
    reserved = [m for m in rows if m.status == "RESERVED"]
    assert created == 0 and not reserved, (
        f"已送达的单被补出了 {len(reserved)} 条预占流水（在途占用会永久虚高）"
    )
