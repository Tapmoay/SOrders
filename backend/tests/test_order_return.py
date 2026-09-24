"""退货 + 按商品核销的回归测试（2026-09-20 用户要求的功能，同批钉住四条底线）。

## 这一批要钉住的东西（每条都有"不钉住会怎样"）

| 判据 | 不钉住会怎样 |
|---|---|
| 退货写**负金额**账本红冲行（source=RETURN） | 营业额不减 = 退了货还照记收入 |
| 退货**回补库存**（`stock += n`） | 库存永久少一批货，盘库找不出原因 |
| 已结账的单退货**自动退现**（REFUND_CUSTOMER） | 客户的钱收了、货也退了，账上还欠他 300 |
| 没收到过钱的单退货**不许退现** | 公司倒贴现金 |
| 退现**不超过真正收过的钱** | 客户只付了 300、退了值 400 的货 → 退 400 = 倒贴 100 |
| 按商品核销后 `paid` **仍是 False** | 这张单从「挂账未收」名单里消失，而它还欠一半 |
| 核销金额**不许超过欠款** | 一张欠 700 的单能收 1000，`arrears` 变负数 = 预收，账上说不清 |
| 恒等式 `应收 = 净已收 + 欠款` | 报表/账本页/订单详情各说一个数 |
| 整单退完才进 `RETURNED` | 带损单的剩余欠款会从所有催收入口消失（挂账报表的集合是 `status=DELIVERED`） |
| 货损那几件**不能退** | 同一批货既算损失又算回库 |
"""
from __future__ import annotations

from decimal import Decimal

from tests.conftest import auth_headers


def _order_as_shipper(
    client, token_shipper, name: str, qty: int = 1, price: str = "100.00", product_id: int | None = None
) -> int:
    line = {
        "product_name_snapshot": name,
        "quantity": qty,
        "unit_price": price,
        "line_total": str(Decimal(price) * qty),
    }
    # 带上商品编号才会取**成本快照**（`build_order_products` 只在有 product_id 时取）——
    # 退货红冲的负成本快照要靠它，不带的话这条断言永远看到 0。
    if product_id is not None:
        line["product_id"] = product_id
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "lines": [line],
            "delivery_description": f"{name}地址",
            "address_detail": f"{name}地址",
        },
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _deliver(client, h, hd, users, oid: int) -> None:
    r = client.post(f"/api/v1/orders/{oid}/assign", json={"driver_id": users["driver"].id}, headers=h)
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hd).status_code == 200
    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=hd,
    )
    assert r.status_code == 200, r.text


def _customer_for(client, h, token_shipper, tag: str) -> int:
    me = client.get("/api/v1/users/me", headers=auth_headers(token_shipper)).json()
    r = client.post("/api/v1/customers", headers=h, json={"name": f"{tag}客户", "user_id": me["id"]})
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _receipt(client, h, customer_id: int, amount: str, order_ids: list[int], lines: list[int] | None = None):
    body = {
        "customer_id": customer_id,
        "amount": amount,
        "method": "cash",
        "settle_mode": "itemized",
        "order_ids": order_ids,
        "received_at": "2026-09-20",
    }
    if lines:
        body["order_product_ids"] = lines
    return client.post("/api/v1/ledger/receipts", headers=h, json=body)


def _return(client, h, oid: int, items: list[tuple[int, int]], note: str = ""):
    return client.post(
        f"/api/v1/orders/{oid}/return",
        headers=h,
        json={"items": [{"order_product_id": pid, "quantity": q} for pid, q in items], "note": note},
    )


def _lines_of(client, h, oid: int) -> list[dict]:
    r = client.get(f"/api/v1/orders/{oid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["order_products"]


# ---------------------------------------------------------------- 整单退货
def test_full_return_reverses_ledger_restocks_and_sets_status(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """整单退货：账本红冲 + 库存回补 + 状态变「已退货」+ 应收清零。"""
    from app.models import InventoryMovement, Ledger, Order, Product
    from app.models.enums import LedgerSource, OrderStatus

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    prod = Product(name="退货整单探针", unit="件", stock=100, cost_price=Decimal("30.00"))
    db_session.add(prod)
    db_session.commit()
    pid = prod.id

    oid = _order_as_shipper(client, token_shipper, "退货整单探针", qty=4, price="25.00", product_id=pid)
    _deliver(client, h, hd, users, oid)
    db_session.expire_all()
    assert db_session.get(Product, pid).stock == 96, "前提不成立：送达没有实扣库存"

    line = _lines_of(client, h, oid)[0]
    r = _return(client, h, oid, [(line["id"], 4)], note="客户不要了")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fully_returned"] is True
    assert Decimal(body["returned_amount"]) == Decimal("100.00"), body
    assert Decimal(body["refund_amount"]) == Decimal("0.00"), "没收到过钱的单不该退现"

    db_session.expire_all()
    order = db_session.get(Order, oid)
    assert order.status == OrderStatus.RETURNED, f"整单退完没进已退货：{order.status}"
    assert order.returned_at is not None

    # 账本红冲行：数量/金额/成本快照**全为负**
    rows = [x for x in db_session.query(Ledger).filter(Ledger.order_id == oid).all()]
    red = [x for x in rows if x.source == LedgerSource.RETURN]
    assert len(red) == 1, f"退货红冲行不是一条：{[(x.id, x.source) for x in rows]}"
    assert red[0].quantity == -4, f"红冲行数量该是负数：{red[0].quantity}"
    assert Decimal(red[0].total) == Decimal("-100.0000"), red[0].total
    assert Decimal(red[0].cost_price_snapshot) == Decimal("-120.0000"), "成本快照没冲回"

    # 库存回补
    stock = db_session.get(Product, pid).stock
    assert stock == 100, f"退货没有回补库存：{stock}"
    moves = (
        db_session.query(InventoryMovement)
        .filter(InventoryMovement.order_id == oid, InventoryMovement.status == "RETURNED")
        .all()
    )
    assert len(moves) == 1 and moves[0].change == 4, [(m.change, m.status) for m in moves]

    # 应收/欠款
    detail = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert Decimal(detail["arrears_amount"]) == Decimal("0.00"), detail["arrears_amount"]
    assert Decimal(detail["settled_amount"]) == Decimal("0.00")


def test_return_after_collection_refunds_the_customer(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """已经结过账的单退货 → **自动退现**（REFUND_CUSTOMER 流出），欠款归零。"""
    from app.models import CashFlow, Order
    from app.models.enums import CashFlowBizType

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order_as_shipper(client, token_shipper, "退货退现探针", qty=3, price="40.00")
    _deliver(client, h, hd, users, oid)
    customer_id = _customer_for(client, h, token_shipper, "退货退现")
    got = _receipt(client, h, customer_id, "120.00", [oid])
    assert got.status_code in (200, 201), got.text
    db_session.expire_all()
    assert db_session.get(Order, oid).paid is True

    line = _lines_of(client, h, oid)[0]
    r = _return(client, h, oid, [(line["id"], 3)])
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["refund_amount"]) == Decimal("120.00"), r.json()

    db_session.expire_all()
    outs = (
        db_session.query(CashFlow)
        .filter(
            CashFlow.order_id == oid,
            CashFlow.biz_type == CashFlowBizType.REFUND_CUSTOMER,
        )
        .all()
    )
    assert len(outs) == 1, f"退款流水不是一条：{outs}"
    assert Decimal(outs[0].amount) == Decimal("120.00"), outs[0].amount
    assert str(getattr(outs[0].direction, "value", outs[0].direction)).lower() == "out"

    detail = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert Decimal(detail["arrears_amount"]) == Decimal("0.00"), (
        f"退了钱又退了货，客户不该还欠钱：{detail['arrears_amount']}"
    )


def test_partial_return_stays_delivered_and_keeps_the_rest_owed(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """部分退货：留在「已送达」，应收减掉退掉那部分。**不许**进已退货。"""
    from app.models import Order
    from app.models.enums import OrderStatus

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order_as_shipper(client, token_shipper, "退货部分探针", qty=10, price="10.00")
    _deliver(client, h, hd, users, oid)

    line = _lines_of(client, h, oid)[0]
    r = _return(client, h, oid, [(line["id"], 4)])
    assert r.status_code == 200, r.text
    assert r.json()["fully_returned"] is False

    db_session.expire_all()
    assert db_session.get(Order, oid).status == OrderStatus.DELIVERED, "部分退货不该改状态"
    detail = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert Decimal(detail["returned_amount"]) == Decimal("40.00"), detail
    assert Decimal(detail["arrears_amount"]) == Decimal("60.00"), (
        f"应收没有减掉退掉的部分：{detail['arrears_amount']}"
    )

    # 再退 3 件 → 累加到**同一行**红冲（唯一约束 (order_product_id, source) 钉着）
    r2 = _return(client, h, oid, [(line["id"], 3)])
    assert r2.status_code == 200, r2.text
    db_session.expire_all()
    from app.models import Ledger
    from app.models.enums import LedgerSource

    red = (
        db_session.query(Ledger)
        .filter(Ledger.order_product_id == line["id"], Ledger.source == LedgerSource.RETURN)
        .all()
    )
    assert len(red) == 1, f"多次退货该累加到同一行，实际 {len(red)} 行"
    assert red[0].quantity == -7, red[0].quantity
    detail2 = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert Decimal(detail2["arrears_amount"]) == Decimal("30.00"), detail2["arrears_amount"]


def test_return_is_refused_unless_delivered(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """没送达的单不能退货（要走「撤销」）。"""
    h = auth_headers(token_dispatcher)
    oid = _order_as_shipper(client, token_shipper, "未送达退货探针")
    line = _lines_of(client, h, oid)[0]
    r = _return(client, h, oid, [(line["id"], 1)])
    assert r.status_code == 400, f"未送达的单居然能退货：{r.status_code} {r.text[:200]}"
    assert "已送达" in r.text


def test_return_cap_excludes_damaged_and_already_returned(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """可退上限 = 数量 − 货损 − 已退；超了就给一句能照着改的中文。"""
    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order_as_shipper(client, token_shipper, "退货上限探针", qty=6, price="10.00")
    r = client.post(f"/api/v1/orders/{oid}/assign", json={"driver_id": users["driver"].id}, headers=h)
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hd).status_code == 200
    line = _lines_of(client, h, oid)[0]
    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={
            "delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"],
            "damage_items": [{"order_product_id": line["id"], "quantity": 2}],
        },
        headers=hd,
    )
    assert r.status_code == 200, r.text

    over = _return(client, h, oid, [(line["id"], 5)])
    assert over.status_code == 400, f"货损那 2 件居然能退：{over.status_code} {over.text[:200]}"
    assert "最多只能退 4" in over.text, over.text

    ok = _return(client, h, oid, [(line["id"], 4)])
    assert ok.status_code == 200, ok.text


# ---------------------------------------------------------------- 按商品核销
def test_itemized_by_product_keeps_paid_false_until_fully_settled(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """按商品核销：收一半 → `paid` 仍 False、欠一半；收完 → True、欠 0。"""
    from app.models import Order

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "lines": [
                {"product_name_snapshot": "核销甲", "quantity": 1, "unit_price": "100.00", "line_total": "100.00"},
                {"product_name_snapshot": "核销乙", "quantity": 1, "unit_price": "60.00", "line_total": "60.00"},
            ],
            "delivery_description": "按商品核销地址",
            "address_detail": "按商品核销地址",
        },
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    _deliver(client, h, hd, users, oid)
    customer_id = _customer_for(client, h, token_shipper, "按商品核销")
    lines = sorted(_lines_of(client, h, oid), key=lambda x: x["id"])
    first, second = lines[0], lines[1]

    r1 = _receipt(client, h, customer_id, "100.00", [oid], lines=[first["id"]])
    assert r1.status_code in (200, 201), r1.text
    db_session.expire_all()
    assert db_session.get(Order, oid).paid is False, (
        "只收了一件商品就把整单标成已收 —— 这张单会从「挂账未收」名单里消失，而它还欠 60"
    )
    detail = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert Decimal(detail["settled_amount"]) == Decimal("100.00"), detail["settled_amount"]
    assert Decimal(detail["arrears_amount"]) == Decimal("60.00"), detail["arrears_amount"]

    r2 = _receipt(client, h, customer_id, "60.00", [oid], lines=[second["id"]])
    assert r2.status_code in (200, 201), r2.text
    db_session.expire_all()
    assert db_session.get(Order, oid).paid is True, "收完了还没标已收"
    detail2 = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert Decimal(detail2["arrears_amount"]) == Decimal("0.00"), detail2["arrears_amount"]

    # 收完之后再核销 → 400
    again = _receipt(client, h, customer_id, "100.00", [oid], lines=[first["id"]])
    assert again.status_code == 400, f"已收完的单又被收了一次：{again.text[:200]}"


def test_receipt_over_arrears_is_refused(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """核销金额不许超过**欠款**（退过货的单上，`line_total` 之和已经不是欠款了）。"""
    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order_as_shipper(client, token_shipper, "超额核销探针", qty=10, price="10.00")
    _deliver(client, h, hd, users, oid)
    customer_id = _customer_for(client, h, token_shipper, "超额核销")
    line = _lines_of(client, h, oid)[0]
    assert _return(client, h, oid, [(line["id"], 4)]).status_code == 200

    over = _receipt(client, h, customer_id, "100.00", [oid])
    assert over.status_code == 400, f"退过货的单被按原价收了钱：{over.text[:200]}"

    ok = _receipt(client, h, customer_id, "60.00", [oid])
    assert ok.status_code in (200, 201), ok.text
    detail = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert Decimal(detail["arrears_amount"]) == Decimal("0.00"), detail["arrears_amount"]


def test_returned_order_cannot_be_collected(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """已退货的单不能再收款（货款已经红冲掉了）。"""
    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order_as_shipper(client, token_shipper, "退货后收款探针", qty=2, price="50.00")
    _deliver(client, h, hd, users, oid)
    customer_id = _customer_for(client, h, token_shipper, "退货后收款")
    line = _lines_of(client, h, oid)[0]
    assert _return(client, h, oid, [(line["id"], 2)]).status_code == 200

    r = _receipt(client, h, customer_id, "100.00", [oid])
    assert r.status_code == 400, f"已退货的单还能收款：{r.status_code} {r.text[:200]}"
    assert "退货" in r.text


def test_money_identity_holds_after_return_and_partial_receipt(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """恒等式：`应收 = 净已收 + 欠款`（这一条一旦破了，三个页面就会各说一个数）。"""
    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "lines": [
                {"product_name_snapshot": "恒等甲", "quantity": 10, "unit_price": "20.00", "line_total": "200.00"},
                {"product_name_snapshot": "恒等乙", "quantity": 5, "unit_price": "10.00", "line_total": "50.00"},
            ],
            "delivery_description": "恒等式地址",
            "address_detail": "恒等式地址",
        },
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    _deliver(client, h, hd, users, oid)
    customer_id = _customer_for(client, h, token_shipper, "恒等式")
    a, b = sorted(_lines_of(client, h, oid), key=lambda x: x["id"])

    # 按商品核销：只核销乙（50）；**金额必须与所选行的应收一致**（这里给 50 才对）
    assert _receipt(client, h, customer_id, "50.00", [oid], lines=[b["id"]]).status_code in (200, 201)
    # 给一个和所选行对不上的金额 → 必须被拒（否则就是"随口收一笔钱"）
    bad = _receipt(client, h, customer_id, "30.00", [oid], lines=[a["id"]])
    assert bad.status_code == 400, bad.text

    # 再退甲里的 3 件（3×20=60）
    assert _return(client, h, oid, [(a["id"], 3)]).status_code == 200

    d = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    total = sum(Decimal(x["line_total"]) for x in d["order_products"])
    returned = Decimal(d["returned_amount"])
    settled = Decimal(d["settled_amount"])
    refunded = Decimal(d["refunded_amount"])
    arrears = Decimal(d["arrears_amount"])
    assert returned == Decimal("60.00"), returned
    assert settled == Decimal("50.00"), settled
    # 退掉的是甲（值 60），但客户只付过 50（而且是给乙付的）→ **只退 50，不倒贴**
    assert refunded == Decimal("50.00"), refunded
    # 剩下的账：甲还剩 7 件 ×20 = 140，乙 50 → 应收 190；净已收 0 → 欠 190
    assert arrears == Decimal("190.00"), arrears
    assert total - returned == (settled - refunded) + arrears, (
        f"恒等式破了：应收 {total - returned} != 净已收 {settled - refunded} + 欠款 {arrears}"
    )


def test_return_amount_is_one_number_even_with_four_decimal_prices(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """**四位单价**下，同一个响应体里的三个数必须是同一个数（2026-09-21 修：原来差 1 分）。

    两行各 `unit_price=12.3456 × 1`（`order_products.unit_price` 是 `Numeric(14,4)`，
    拆单会算出这种单价）。原来有两个算法各算一遍：

    · 「本次退货金额」按行先取两位再求和 → **24.70**（并照这个数退现）；
    · 账本红冲按行落四位，汇总再取两位 → **24.69**。

    也就是 `POST /orders/{id}/return` 的响应里 `returned_amount` 与 `order.returned_amount`
    不相等，退出去的真金白银比账上红冲的多一分，**而两边都不报错**。
    """
    from app.models import CashFlow, Ledger
    from app.models.enums import CashFlowBizType, LedgerSource

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "lines": [
                {"product_name_snapshot": "四分单价甲", "quantity": 1, "unit_price": "12.3456",
                 "line_total": "12.3456"},
                {"product_name_snapshot": "四分单价乙", "quantity": 1, "unit_price": "12.3456",
                 "line_total": "12.3456"},
            ],
            "delivery_description": "四位单价地址",
            "address_detail": "四位单价地址",
        },
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])

    # 派单时勾「收取现金」→ 送达时 paid=True（现场收现金没有流水）→ 退货会走到退现分支
    assigned = client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "collect_cash": True},
        headers=h,
    )
    assert assigned.status_code == 200, assigned.text
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hd).status_code == 200
    done = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"], "payment": "cash"},
        headers=hd,
    )
    assert done.status_code == 200, done.text

    lines = _lines_of(client, h, oid)
    res = _return(client, h, oid, [(x["id"], 1) for x in lines])
    assert res.status_code == 200, res.text
    body = res.json()

    db_session.expire_all()
    red = (
        db_session.query(Ledger)
        .filter(Ledger.order_id == oid, Ledger.source == LedgerSource.RETURN)
        .all()
    )
    assert len(red) == 2, f"两行各退一次，红冲行该是两条：{[(x.id, x.total) for x in red]}"
    ledger_sum = -sum((Decimal(x.total) for x in red), Decimal("0"))
    # ⚠️ 这是**前提**，不是结论：账本按行落四位（4 位列，退货要精确冲回卖出去的那笔）
    assert ledger_sum == Decimal("24.6912"), f"前提不成立：账本红冲不是两行四位之和：{ledger_sum}"

    # ★ 三个数一个都不能差：本次退货金额 = 累计已退（账本出的）= 实际退现 = 现金流水
    assert Decimal(body["returned_amount"]) == Decimal("24.69"), body
    assert Decimal(body["order"]["returned_amount"]) == Decimal(body["returned_amount"]), (
        f"同一个响应体里两个数不一致：本次 {body['returned_amount']} "
        f"/ 累计 {body['order']['returned_amount']}"
    )
    assert Decimal(body["refund_amount"]) == Decimal("24.69"), body
    outs = (
        db_session.query(CashFlow)
        .filter(CashFlow.order_id == oid, CashFlow.biz_type == CashFlowBizType.REFUND_CUSTOMER)
        .all()
    )
    assert [Decimal(x.amount) for x in outs] == [Decimal("24.69")], [str(x.amount) for x in outs]

    detail = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert Decimal(detail["returned_amount"]) == Decimal("24.69"), detail["returned_amount"]
# ---------------------------------------------------------------- 状态跃迁必须是条件 UPDATE（报告 §7）
def test_returned_transition_is_a_conditional_update(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """整单退货那一步（`DELIVERED → RETURNED`）必须是**条件 UPDATE**，不是无条件赋值。

    ## 为什么单独立一条（这一处在本地差点永远测不出来）
    它原来是 `order.status = OrderStatus.RETURNED`。并发的「退货 × 送达 / 撤销」下，
    无条件赋值会把**别人刚写进去的状态覆盖掉，而两边都不报错**：
    一张刚被撤销的单会被改成「已退货」——账本红冲、库存回补都做了，而这单其实已经撤了。
    ⚠️ 端点上确实写了 `with_for_update()`，但 **SQLite 不认 `FOR UPDATE`**（本仓库那条教训：
    「只在生产有效的保护等于本地测不出来」）→ 本地跑一百遍也看不到这个问题。

    ## 怎么在单进程里造出那个并发窗口
    让手上那份 `Order` 快照**是陈旧的**：先读出来、`expunge`（从此与 session 无关），
    再用**另一个 session** 把库里的状态改成 CANCELLED —— 这正是并发下的真实形状
    （请求 A 先读到单，请求 B 在这之间把它撤销了）。改之前：A 的无条件赋值覆盖 B；
    改之后：A 的条件 UPDATE 改到 0 行 → 拒绝。
    """
    from sqlalchemy import update

    from app.models import Order
    from app.models.enums import OrderStatus
    from app.services.order_flow import mark_returned
    from tests.conftest import get_test_session_factory

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order_as_shipper(client, token_shipper, "退货并发探针", qty=2, price="10.00")
    _deliver(client, h, hd, users, oid)

    stale = db_session.get(Order, oid)
    assert stale.status == OrderStatus.DELIVERED, "前提不成立：这一单没有送达"
    db_session.expunge(stale)   # 手上这份快照就此独立（＝另一个请求手里的那个对象）
    db_session.rollback()       # 把我这边的读事务收掉，免得下面那个 session 写不进去（SQLite 锁）
    assert stale.status == OrderStatus.DELIVERED, "前提：手上那份快照仍然是旧的"

    other = get_test_session_factory()()
    try:
        other.execute(update(Order).where(Order.id == oid).values(status=OrderStatus.CANCELLED))
        other.commit()
    finally:
        other.close()

    raised = False
    try:
        mark_returned(db_session, stale)
    except ValueError:
        raised = True
    assert raised, "陈旧快照把别人写的状态覆盖掉了 —— 条件 UPDATE 没起作用"

    db_session.expire_all()
    now = db_session.get(Order, oid).status
    assert now == OrderStatus.CANCELLED, f"撤销被退货覆盖成了 {now}（这条用例要挡的就是它）"


def test_mark_returned_refuses_orders_never_delivered(
    client, token_shipper, db_session
):
    """没送达的单**永远**不该被标成「已退货」：判据是 CAS 的 WHERE，不靠调用方自觉。"""
    from app.models import Order
    from app.models.enums import OrderStatus
    from app.services.order_flow import mark_returned

    oid = _order_as_shipper(client, token_shipper, "退货未送达探针", qty=1, price="9.00")
    order = db_session.get(Order, oid)
    assert order.status == OrderStatus.PENDING_DISPATCH, "前提不成立：新单不是待派单"

    raised = False
    try:
        mark_returned(db_session, order)
    except ValueError:
        raised = True
    assert raised, "待派单的单被标成了「已退货」"

    db_session.expire_all()
    assert db_session.get(Order, oid).status == OrderStatus.PENDING_DISPATCH

