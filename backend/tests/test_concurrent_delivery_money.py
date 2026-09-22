"""并发重复提交的**钱**不变式：同一张单无论被点几次，只许生成一条司机账单。

## 现场（2026-09-18 实测复现过，不是假想）
两个并发的 `complete` 都读到「已接单」→ 各自往下走 → 订单 620 拿到**两条 60 元账单**（合计 120）。
根因：SQLite **不支持 `SELECT … FOR UPDATE`**，SQLAlchemy 直接忽略它，
所以"只靠行锁"的保护**在本地是空的**（MySQL 上行锁能挡，但"只在生产有效"的保护本地测不出来）。

修法：状态跃迁改成**条件 UPDATE 占位**（`WHERE status='ACCEPTED'`）——
改到 1 行的请求继续，改到 0 行的立刻出局。这条判据在 SQLite / MySQL 上都成立。

## 为什么这里不写"多线程打同一个 app"
试过了：pytest 的 `client` fixture 给**所有请求共用同一个 Session**（`override_get_db` yield 同一个
session），多线程下 SQLite 连接直接 `InterfaceError: bad parameter or other API misuse`——
那是测试脚手架的形态，不是被测代码的问题（生产每个请求一个 session）。
所以这一层拆成两条，各测各能测的：
1. **机制**：条件 UPDATE 在本机数据库上确实是"只有一个赢家"（`test_conditional_claim_*`）；
2. **端到端**：串行重复提交只产生一条账单（`test_double_complete_*`）。
真正"两个请求抢跑"的端到端复现与验证，在 `_tools/fuzz/_fuzz_replay.py`（打真后端、真并发）：
修复前它会报「并发送达产生了多张司机账单」，修复后连跑 5 轮都是"只产生一张 + 一个请求 4xx"。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select, text, update
from starlette.testclient import TestClient

from app.models import Order
from app.models.enums import OrderStatus
from tests.conftest import auth_headers


def test_conditional_claim_is_atomic_on_this_db(db_session, users) -> None:
    """条件 UPDATE 占位：第一次 1 行、第二次 0 行——这正是并发时"只让一个人赢"的依据。"""
    order = Order(
        order_no="CAS-TEST-1",
        status=OrderStatus.PENDING_DISPATCH,
        shipper_id=users["shipper"].id,
        order_date=date.today(),
    )
    db_session.add(order)
    db_session.commit()

    def claim() -> int:
        res = db_session.execute(
            update(Order)
            .where(Order.id == order.id, Order.status == OrderStatus.PENDING_DISPATCH)
            .values(status=OrderStatus.DISPATCHED)
        )
        db_session.commit()
        return res.rowcount

    assert claim() == 1, "第一次占位必须成功"
    assert claim() == 0, "第二次占位必须失败（否则并发下两个请求都会往下走）"


def _accepted_order(client: TestClient, db_session, token_disp: str, token_drv: str,
                    users: dict) -> int:
    # 司机必须是**按单计费**才会有 PIECE 账单（工资制司机送达本来就不产生按单应付）
    users["driver"].billing_mode = "piece"
    db_session.commit()
    r = client.post(
        "/api/v1/orders",
        json={
            "lines": [{"product_name_snapshot": "重复送达货", "quantity": 1, "unit_price": "50"}],
            "shipper_id": users["shipper"].id,
        },
        headers=auth_headers(token_disp),
    )
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    a = client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "60.00", "collect_cash": True},
        headers=auth_headers(token_disp),
    )
    assert a.status_code in (200, 201, 204), a.text
    k = client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_drv))
    assert k.status_code in (200, 201, 204), k.text
    return oid


def test_double_complete_sequential_creates_one_bill(
    client: TestClient, db_session, token_dispatcher: str, token_driver: str, users: dict
) -> None:
    oid = _accepted_order(client, db_session, token_dispatcher, token_driver, users)
    body = {"payment": "cash", "delivery_photo_urls": ["/static/uploads/delivery/t.jpg"]}

    first = client.post(f"/api/v1/orders/{oid}/complete", json=body, headers=auth_headers(token_driver))
    assert first.status_code in (200, 201, 204), first.text
    second = client.post(f"/api/v1/orders/{oid}/complete", json=body, headers=auth_headers(token_driver))
    assert second.status_code == 400, f"重复送达必须被挡住，实际 {second.status_code}：{second.text[:200]}"

    bills = client.get(f"/api/v1/driver-bills?driver_id={users['driver'].id}",
                       headers=auth_headers(token_dispatcher))
    assert bills.status_code == 200, bills.text
    rows = [b for b in bills.json() if b.get("order_id") == oid and b.get("bill_type") == "piece"]
    assert len(rows) == 1, f"同一张单生成了 {len(rows)} 条账单（钱付两次）：{rows}"

    detail = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_dispatcher))
    # 状态枚举出参是**大写**（OrderStatus.DELIVERED），别按小写断言
    assert detail.json()["status"] == "DELIVERED", detail.text


# ---------------------------------------------------------------- 逐单核销的同一个占位
#
# 2026-09-18 又在本机实测复现了一次同族缺陷（探针 `_probe_core_flows.py` 的并发组）：
# 两个并发的逐单核销请求**都返回 200**，同一张单落了两条收款记录、两条现金流水
# （库里实测：order 656 有收款单 47/48 各 60 元）。根因与并发送达一模一样
# —— 逐单核销也只有 `with_for_update()`（SQLite 忽略），没有原子占位。
# 修法也照抄：`UPDATE orders SET paid=1 WHERE id=? AND paid=0`，改到行的人才能继续。


def test_paid_claim_is_atomic_on_this_db(db_session, users) -> None:
    """`paid=false → true` 的条件占位：第一次 1 行、第二次 0 行。"""
    order = Order(
        order_no="CAS-TEST-PAID-1",
        status=OrderStatus.PENDING_DISPATCH,
        shipper_id=users["shipper"].id,
        order_date=date.today(),
        paid=False,
    )
    db_session.add(order)
    db_session.commit()

    def claim() -> int:
        res = db_session.execute(
            update(Order).where(Order.id == order.id, Order.paid.is_(False)).values(paid=True)
        )
        db_session.commit()
        return res.rowcount

    assert claim() == 1, "第一次占位必须成功"
    assert claim() == 0, "第二次占位必须失败（否则并发下同一张单会被核销两次）"


def test_double_itemized_receipt_sequential_records_money_once(
    client: TestClient, db_session, token_dispatcher: str, token_shipper: str, users: dict
) -> None:
    """串行重复核销：第二次必须 400，且那笔钱只有**一条**收款记录（占位生效）。"""
    r = client.post(
        "/api/v1/orders",
        json={"lines": [{"product_name_snapshot": "重复核销货", "quantity": 1, "unit_price": "70"}],
              "shipper_id": users["shipper"].id},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])

    cust = client.post("/api/v1/customers",
                       json={"name": "重复核销客户", "user_id": users["shipper"].id},
                       headers=auth_headers(token_dispatcher))
    assert cust.status_code in (200, 201), cust.text
    cid = int(cust.json()["id"])

    body = {"customer_id": cid, "amount": "70.00", "method": "cash", "settle_mode": "itemized",
            "order_ids": [oid], "received_at": date.today().isoformat()}
    first = client.post("/api/v1/ledger/receipts", json=body, headers=auth_headers(token_dispatcher))
    assert first.status_code in (200, 201), first.text
    second = client.post("/api/v1/ledger/receipts", json=body, headers=auth_headers(token_dispatcher))
    assert second.status_code == 400, f"重复核销必须被挡住，实际 {second.status_code}：{second.text[:200]}"

    rows = client.get(f"/api/v1/ledger/receipts?customer_id={cid}",
                      headers=auth_headers(token_dispatcher))
    assert rows.status_code == 200, rows.text
    hits = [x for x in rows.json() if oid in (x.get("order_ids") or [])]
    assert len(hits) == 1, f"同一张单落了 {len(hits)} 条收款记录（钱多记）：{hits}"


def test_return_quantity_cap_is_enforced_by_the_update_itself(db_session, users) -> None:
    """退货的「这一行最多还能退几件」必须写进**那条 UPDATE 的 where** 里。

    为什么不能只测"顺序双击两次退货"（那条测试本项目早就有）：
    顺序双击在**修复前**也是 400 —— Python 侧那句 `if it.quantity > max_returnable(op)` 挡得住。
    真正漏掉的是**并发**：三个请求各自读到 `returned_quantity=0`、各自通过那句检查，
    然后三条 `returned_quantity = returned_quantity + qty` 各自 +1（SQL 表达式只防丢更新，
    不防越过上限）。2026-09-23 并发实测的后果：**一件货退成 3 件**、
    账本红冲 −45 元（货值 15 元）、多出 3 笔退款流水。

    所以这里直接钉**判据本身**（与上面 `test_conditional_claim_is_atomic_on_this_db` 同一手法）：
    同样的 where 连续执行两次，第二次必须改不到行。
    """
    from app.models import OrderProduct

    order = Order(
        order_no="RET-CAP-1",
        status=OrderStatus.DELIVERED,
        shipper_id=users["shipper"].id,
        order_date=date.today(),
    )
    db_session.add(order)
    db_session.flush()
    line = OrderProduct(
        order_id=order.id,
        product_name_snapshot="一件货",
        quantity=1,
        unit_price=Decimal("15"),
        line_total=Decimal("15"),
    )
    db_session.add(line)
    db_session.commit()

    def claim(qty: int) -> int:
        res = db_session.execute(
            update(OrderProduct)
            .where(
                OrderProduct.id == line.id,
                func.coalesce(OrderProduct.quantity, 0)
                - func.coalesce(OrderProduct.damage_quantity, 0)
                - func.coalesce(OrderProduct.returned_quantity, 0)
                >= qty,
            )
            .values(returned_quantity=func.coalesce(OrderProduct.returned_quantity, 0) + qty)
        )
        db_session.commit()
        return res.rowcount

    assert claim(1) == 1, "第一次退这一件必须成功"
    assert claim(1) == 0, (
        "第二次必须改不到行（否则并发下同一件货会被退两次、退两份钱）——"
        "上限判据必须在那条 UPDATE 的 where 里，不能只在 Python 里读一遍"
    )
    db_session.expire_all()
    assert int(db_session.get(OrderProduct, line.id).returned_quantity or 0) == 1

    # 同上：测试库按 worker 共享，自己造的行自己收掉
    db_session.query(OrderProduct).filter(OrderProduct.order_id == order.id).delete()
    db_session.query(Order).filter(Order.id == order.id).delete()
    db_session.commit()


def test_supplier_payment_cap_is_enforced_by_the_conditional_update(db_session, users) -> None:
    """供应商付款的「不许超过还差的」也必须由**那条条件 UPDATE 的 WHERE** 判定。

    为什么不是"读一遍余额再判断"：付款写的是**一行新的 `cash_flows`**，没有行可以像订单那样
    CAS（`paid=false→true`），于是"已付合计 + 这次 ≤ 应付"只能在**语句里**求值 ——
    做法是把应付单那一行当互斥量（`update(SupplierPayable) … .where(余额够)`），
    由数据库的写锁串行化。2026-09-23 并发实测的后果：一张 1000 元的应付单**付出去 3000**。

    这里钉三个事实：够 → 改得到；不够 → 改不到；付掉一部分之后剩下的额度按**新的已付**算。
    """
    from app.models import CashFlow, Supplier, SupplierPayable
    from app.models.enums import CashFlowBizType, CashFlowDirection

    # ⚠️ 用自己的供应商（不用 id=1）：测试库按 worker 共享，占用别人的行会连带把
    #    别的用例打红（见文件末尾的清理段）。
    supplier = Supplier(name="并发付款上限供应商")
    db_session.add(supplier)
    db_session.flush()
    payable = SupplierPayable(
        supplier_id=supplier.id,
        title="并发付款上限",
        category="货款",
        amount=Decimal("100.00"),
        doc_date=date.today(),
    )
    db_session.add(payable)
    db_session.commit()
    pid = payable.id

    def claim(amt: Decimal) -> int:
        paid_sub = (
            select(func.coalesce(func.sum(CashFlow.amount), 0))
            .where(
                CashFlow.party_type == "supplier",
                CashFlow.direction == CashFlowDirection.OUT,
                CashFlow.biz_type == CashFlowBizType.PAYMENT_SUPPLIER,
                CashFlow.doc_id == pid,
                CashFlow.is_deleted.is_(False),
            )
            .scalar_subquery()
        )
        res = db_session.execute(
            update(SupplierPayable)
            .where(
                SupplierPayable.id == pid,
                SupplierPayable.is_deleted.is_(False),
                SupplierPayable.amount - paid_sub >= amt,
            )
            .values(updated_at=datetime.now(timezone.utc).replace(tzinfo=None))
        )
        db_session.commit()
        return res.rowcount

    assert claim(Decimal("60")) == 1, "余额够时必须改得到行（否则正常付款会被误拒）"
    # 模拟"第一笔 60 已经落库"（真实路径由 pay_supplier 插这一行）
    db_session.add(
        CashFlow(
            flow_date=date.today(),
            direction=CashFlowDirection.OUT,
            amount=Decimal("60"),
            party_type="supplier",
            party_id=supplier.id,
            party_name=supplier.name,
            channel="cash",
            biz_type=CashFlowBizType.PAYMENT_SUPPLIER,
            doc_id=pid,
            note="测试：已付 60",
        )
    )
    db_session.commit()

    assert claim(Decimal("60")) == 0, (
        "已付 60 之后再付 60 必须改不到行（100 − 60 = 40 < 60）——"
        "这就是并发下第二个请求被挡住的那道闸"
    )
    assert claim(Decimal("40")) == 1, "剩下的 40 必须还能付"

    # ⚠️ **必须自己收干净**：测试库是**按 worker 共享**的（`sorders_test_<worker>.db`），
    #    第一版拿 `supplier_id=1` 建单又没删，直接把 `test_建一个供应商档案` 里
    #    "新供应商三列都是 0" 的断言打红了（应付 100 / 已付 60）——测试之间互相污染的
    #    表现是"一个毫不相干的用例红了"，比这条测试自己失败难查得多。
    db_session.query(CashFlow).filter(CashFlow.doc_id == pid).delete()
    db_session.query(SupplierPayable).filter(SupplierPayable.id == pid).delete()
    db_session.delete(supplier)
    db_session.commit()
