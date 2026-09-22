"""货主**申请**退货 → 派单员**实际执行**（2026-09-21 用户要求）。

## 这一批钉住的东西（每条都有"不钉住会怎样"）

| 判据 | 不钉住会怎样 |
|---|---|
| **申请阶段：库存/账本/已退数量/订单状态全都不许动** | 货主按一下就把自己的应收和公司库存改了，而派单员根本不知道 —— 这正是 `rbac.py` 当初不给货主退货权的理由，申请制存在的全部意义就是保住那条核对 |
| 提交申请后派单员**收到站内信**（带申请单号） | 申请提了没人知道，货主只能打电话催（那这个功能就白做了） |
| 办理**恰好退申请单上那些数量** | 「申请 5 件、账上退 3 件」两边各说各话 |
| 办理后：红冲 + 回补 + 状态 + 申请单转「已办理」+ 货主收到消息 | 少一样就是"办了但没说"或"说了但没办" |
| 驳回**必带理由**，货主收到带理由的消息 | 货主唯一能拿到的答复没了，他只会反复重提 |
| 撤回后派单员办不了 | 撤销过的申请还能被办理 = 货主撤了也没用 |
| 一张单**同时只有一张**待处理申请 | 派单员看到两张待办以为是两次退货（实际退了第一张第二张就没货了），只能逐张驳回 |
| 申请之后余量变小 → 办理**拒绝**且申请仍是待处理 | 退出去超过下单量的货，或者"办失败"却把申请标成已办（货主以为退了，库存没回来） |
| 货主**不能**直接调退货接口（403） | 申请制被绕过，等于什么都没做 |
| 普通货主与批发商**都能**申请 | 用户拍板「所有货主都能申请」，只给批发商就漏了一半订单 |
| 货主只能看/撤回**自己**的申请 | 越权读取 + 撤回别人的申请 |
"""
from __future__ import annotations

from decimal import Decimal

from tests.conftest import auth_headers


def _order_with_product(client, token_shipper, db_session, name: str, qty: int, price: str, stock: int = 100):
    """建一张**带商品编号**的单（带编号才会取成本快照，红冲的负成本快照要靠它）。"""
    from app.models import Product

    prod = Product(name=name, unit="件", stock=stock, cost_price=Decimal("30.00"))
    db_session.add(prod)
    db_session.commit()
    line = {
        "product_name_snapshot": name,
        "quantity": qty,
        "unit_price": price,
        "line_total": str(Decimal(price) * qty),
        "product_id": prod.id,
    }
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={"lines": [line], "delivery_description": f"{name}地址", "address_detail": f"{name}地址"},
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"]), int(prod.id)


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


def _lines_of(client, h, oid: int) -> list[dict]:
    r = client.get(f"/api/v1/orders/{oid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["order_products"]


def _apply(client, token_shipper, oid: int, items: list[tuple[int, int]], note: str = ""):
    return client.post(
        "/api/v1/return-requests",
        headers=auth_headers(token_shipper),
        json={
            "order_id": oid,
            "items": [{"order_product_id": pid, "quantity": q} for pid, q in items],
            "note": note,
        },
    )


def _snapshot(db_session, oid: int) -> dict:
    """把"申请本不该动的那几样"一次拍下来，用于前后对比。

    ⚠️ 库存（`products.stock`）不在这里比：它属于**另一个对象**，
       单独断言更清楚（见 `test_apply_touches_nothing`）。
    """
    from app.models import CashFlow, Ledger, Order, OrderProduct
    from app.models.enums import LedgerSource

    db_session.expire_all()
    order = db_session.get(Order, oid)
    return {
        "status": order.status,
        "returned_at": order.returned_at,
        "returned_qty": [
            int(x.returned_quantity or 0)
            for x in db_session.query(OrderProduct).filter(OrderProduct.order_id == oid).all()
        ],
        "return_rows": db_session.query(Ledger)
        .filter(Ledger.order_id == oid, Ledger.source == LedgerSource.RETURN)
        .count(),
        "ledger_rows": db_session.query(Ledger).filter(Ledger.order_id == oid).count(),
        "cash_rows": db_session.query(CashFlow).filter(CashFlow.order_id == oid).count(),
    }


# ---------------------------------------------------------------- 核心：申请什么都不动
def test_apply_touches_nothing(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """★ 申请退货**只写申请单**：库存、账本、已退数量、订单状态、现金流水一个都不许动。

    （用户原话：「派单员进行完了之后，整个才进行库存才会发生一个改变和变动」。）
    """
    from app.models import Order, Product
    from app.models.enums import OrderStatus

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, pid = _order_with_product(client, token_shipper, db_session, "申请不动探针", qty=4, price="25.00")
    _deliver(client, h, hd, users, oid)
    db_session.expire_all()
    assert db_session.get(Product, pid).stock == 96, "前提不成立：送达没有实扣库存"
    before = _snapshot(db_session, oid)

    line = _lines_of(client, h, oid)[0]
    r = _apply(client, token_shipper, oid, [(line["id"], 2)], note="有两件破了")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending" and body["status_label"] == "待派单员处理", body
    assert body["lines"][0]["quantity"] == 2, body
    assert body["note"] == "有两件破了", body

    after = _snapshot(db_session, oid)
    assert db_session.get(Product, pid).stock == 96, f"申请把库存动了：{db_session.get(Product, pid).stock}"
    assert after == before, f"申请改了本不该动的东西：{before} → {after}"
    assert db_session.get(Order, oid).status == OrderStatus.DELIVERED, "申请不该改订单状态"

    # 订单出参里的钱一个都没变（货主看到的应收也不变）
    detail = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert Decimal(detail["returned_amount"]) == Decimal("0.00"), detail["returned_amount"]
    assert Decimal(detail["arrears_amount"]) == Decimal("100.00"), detail["arrears_amount"]
    assert Decimal(detail["refunded_amount"]) == Decimal("0.00")


def test_dispatcher_gets_notified_with_request_id(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """派单员收到站内信，`payload.request_id` 必须在（否则点开消息找不到是哪一张申请）。"""
    from app.models import Notification

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, _pid = _order_with_product(client, token_shipper, db_session, "申请通知探针", qty=2, price="10.00")
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 1)]).json()["id"]

    db_session.expire_all()
    rows = (
        db_session.query(Notification)
        .filter(
            Notification.recipient_id == users["dispatcher"].id,
            Notification.type == "order.return_request",
        )
        .all()
    )
    assert rows, "派单员没有收到退货申请的站内信"
    payload = rows[-1].payload or {}
    assert payload.get("request_id") == rid, payload
    assert payload.get("order_id") == oid, payload
    assert "申请退货" in (rows[-1].content or ""), rows[-1].content
    assert "请办理或驳回" in (rows[-1].content or ""), rows[-1].content


# ---------------------------------------------------------------- 办理：此刻才变
def test_fulfill_returns_exactly_what_was_applied(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """★ 办理 = 按申请单原样退货：库存回补、账本红冲、状态、申请转已办理、货主收消息。"""
    from app.models import InventoryMovement, Ledger, Notification, Order, OrderProduct, Product
    from app.models.enums import LedgerSource, OrderStatus

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, pid = _order_with_product(client, token_shipper, db_session, "申请办理探针", qty=4, price="25.00")
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 2)]).json()["id"]

    db_session.expire_all()
    assert db_session.get(Product, pid).stock == 96, "申请阶段库存就不该变"

    r = client.post(f"/api/v1/return-requests/{rid}/fulfill", headers=h)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["request"]["status"] == "done", got["request"]
    assert got["request"]["handled_by"] == users["dispatcher"].id
    assert Decimal(got["returned"]["returned_amount"]) == Decimal("50.00"), got["returned"]
    assert got["returned"]["fully_returned"] is False, "只退了一半，不该整单退完"

    db_session.expire_all()
    # ★ 库存**此刻**才变：96 → 98（退回来 2 件）
    assert db_session.get(Product, pid).stock == 98, f"办理没有回补库存：{db_session.get(Product, pid).stock}"
    moves = (
        db_session.query(InventoryMovement)
        .filter(InventoryMovement.order_id == oid, InventoryMovement.status == "RETURNED")
        .all()
    )
    assert len(moves) == 1 and moves[0].change == 2, [(m.change, m.status) for m in moves]
    # 账本红冲行（负数量、负金额）
    red = db_session.query(Ledger).filter(Ledger.order_id == oid, Ledger.source == LedgerSource.RETURN).all()
    assert len(red) == 1 and red[0].quantity == -2, [(x.quantity, x.total) for x in red]
    # 已退数量落在订单行上（数量锁死：就是申请的那 2 件）
    op = db_session.get(OrderProduct, int(line["id"]))
    assert int(op.returned_quantity or 0) == 2, op.returned_quantity
    # 部分退货 → 仍是「已送达」
    assert db_session.get(Order, oid).status == OrderStatus.DELIVERED

    # 货主收到「已办理」的消息（带金额）
    db_session.expire_all()
    notes = (
        db_session.query(Notification)
        .filter(
            Notification.recipient_id == users["shipper"].id,
            Notification.type == "order.return_request.done",
        )
        .all()
    )
    assert notes, "办完了却没告诉货主"
    # 金额末尾多余的 0 去掉（2026-09-22 用户定的显示口径）；这条正文是给**人**看的
    assert "退货金额 ¥50" in (notes[-1].content or ""), notes[-1].content


def test_full_return_through_request_sets_returned_status(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """整单申请 + 办理 → 订单变「已退货」，库存回到 100。"""
    from app.models import Order, Product
    from app.models.enums import OrderStatus

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, pid = _order_with_product(client, token_shipper, db_session, "申请整单探针", qty=3, price="40.00")
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 3)]).json()["id"]

    r = client.post(f"/api/v1/return-requests/{rid}/fulfill", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["returned"]["fully_returned"] is True

    db_session.expire_all()
    assert db_session.get(Order, oid).status == OrderStatus.RETURNED
    assert db_session.get(Product, pid).stock == 100, db_session.get(Product, pid).stock
    detail = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert Decimal(detail["arrears_amount"]) == Decimal("0.00"), detail["arrears_amount"]


def test_fulfill_refuses_when_cap_shrank_and_stays_pending(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """申请之后余量变小（别处已经动过这一行）→ 办理**拒绝**，且申请**仍是待处理**。

    ⛔ 最坏的结果是"办失败却把申请标成已办"：货主以为退了，库存没回来，没人再去看它。

    ⚠️ 2026-09-21：余量变小**不再能靠"派单员先手工退一批"造出来** —— 申请待处理时那条路
       已经被 fail-closed 堵了（见 `test_direct_return_is_blocked_while_a_request_is_pending`，
       堵的理由正是"同一批货会被退两遍"）。所以这里**直接在库里**把那 3 件记成已退，
       模拟"别处动过这一行"（并发办理 / 别的路径改过数据），验的仍是那条不变量。
    """
    from sqlalchemy import text

    h = auth_headers(token_dispatcher)
    oid, _pid = _order_with_product(client, token_shipper, db_session, "余量变小探针", qty=4, price="25.00")
    hd = auth_headers(token_driver)
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 3)]).json()["id"]

    # 别处已经退掉 2 件（4 − 2 = 只剩 2 件可退）
    db_session.execute(
        text("update order_products set returned_quantity = 2 where id = :i"), {"i": line["id"]}
    )
    db_session.commit()

    r = client.post(f"/api/v1/return-requests/{rid}/fulfill", headers=h)
    assert r.status_code == 400, f"余量不够居然办成了：{r.status_code} {r.text[:200]}"
    assert "只剩 2 件可退" in r.text, r.text

    mine = client.get("/api/v1/return-requests/mine", headers=auth_headers(token_shipper)).json()
    target = [x for x in mine["items"] if x["id"] == rid][0]
    assert target["status"] == "pending", f"办失败却把申请标成了 {target['status']}"


def test_fulfill_twice_is_refused(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """同一张申请办两次 → 第二次 400（不许把同一批货退两遍）。"""
    from app.models import Product

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, pid = _order_with_product(client, token_shipper, db_session, "重复办理探针", qty=4, price="25.00")
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 2)]).json()["id"]

    assert client.post(f"/api/v1/return-requests/{rid}/fulfill", headers=h).status_code == 200
    second = client.post(f"/api/v1/return-requests/{rid}/fulfill", headers=h)
    assert second.status_code == 400, second.text
    assert "已经办完了" in second.text, second.text

    db_session.expire_all()
    assert db_session.get(Product, pid).stock == 98, "同一张申请被办了两次（库存多补了一遍）"


# ---------------------------------------------------------------- 驳回 / 撤回
def test_reject_requires_reason_and_notifies_shipper(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """驳回必带理由；理由要送到货主那里；订单/库存仍然一点没动。"""
    from app.models import Notification, Product

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, pid = _order_with_product(client, token_shipper, db_session, "驳回探针", qty=4, price="25.00")
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 2)]).json()["id"]

    blank = client.post(f"/api/v1/return-requests/{rid}/reject", headers=h, json={"reason": "   "})
    assert blank.status_code in (400, 422), f"空理由居然能驳回：{blank.status_code}"

    ok = client.post(
        f"/api/v1/return-requests/{rid}/reject", headers=h, json={"reason": "货已经拆封，不能退"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "rejected" and ok.json()["reject_reason"] == "货已经拆封，不能退"

    db_session.expire_all()
    assert db_session.get(Product, pid).stock == 96, "驳回把库存动了"
    notes = (
        db_session.query(Notification)
        .filter(
            Notification.recipient_id == users["shipper"].id,
            Notification.type == "order.return_request.rejected",
        )
        .all()
    )
    assert notes and "货已经拆封，不能退" in (notes[-1].content or ""), notes[-1].content if notes else None


def test_withdraw_then_dispatcher_cannot_fulfill(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """货主撤回后，派单员再点办理 → 400（撤了就没用了，那撤回才有意义）。"""
    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, _pid = _order_with_product(client, token_shipper, db_session, "撤回探针", qty=2, price="10.00")
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 1)]).json()["id"]

    w = client.post(f"/api/v1/return-requests/{rid}/withdraw", headers=auth_headers(token_shipper))
    assert w.status_code == 200, w.text
    assert w.json()["status"] == "withdrawn"

    r = client.post(f"/api/v1/return-requests/{rid}/fulfill", headers=h)
    assert r.status_code == 400, r.text
    assert "撤回" in r.text, r.text


def test_only_one_pending_request_per_order(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """同一张单不能挂两张待办申请（否则派单员看到的"两笔退货"实际只有一批货）。"""
    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, _pid = _order_with_product(client, token_shipper, db_session, "重复申请探针", qty=4, price="25.00")
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]

    assert _apply(client, token_shipper, oid, [(line["id"], 1)]).status_code == 201
    again = _apply(client, token_shipper, oid, [(line["id"], 2)])
    assert again.status_code == 400, again.text
    assert "已经有一张待处理的退货申请" in again.text, again.text


# ---------------------------------------------------------------- 越权与边界
def test_direct_return_closes_the_pending_request(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """★ 派单员**直连退货**（订单管理那条老路）→ 那张申请**自动关闭**，数据照常变。

    用户 2026-09-21 拍板：「把规则改成派单员退货之后，**自动取消申请**，然后它对应的数据发生改变，
    状态变成已退货多少多少」。

    ⚠️ 这条规则**换过一次方向**（同一天早些时候这里是 400 fail-closed），所以这条用例的
       存在意义是"钉住现在跑的是哪一条"：直连退货**必须成功**，且申请**必须自动关闭**。
    ⛔ 自动关闭不是美化：它就是"同一批货被退两遍"的堵法 —— 申请一旦不是 pending，
       `fulfill` 会被 `_check_pending` 拒（下面最后一段验的就是这个）。
    """
    from app.models import Notification, OrderReturnRequest, Product
    from app.models.enums import ReturnRequestStatus

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, pid = _order_with_product(client, token_shipper, db_session, "直连关单探针", qty=5, price="10.00")
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 2)]).json()["id"]

    # ① 直连退货照旧能用（用户：「如果是派单员的话，就不需要去修改这个按钮」）
    direct = client.post(
        f"/api/v1/orders/{oid}/return",
        headers=h,
        json={"items": [{"order_product_id": line["id"], "quantity": 2}]},
    )
    assert direct.status_code == 200, f"派单员直连退货被挡住了：{direct.status_code} {direct.text[:200]}"

    # ② 那张申请自动关闭
    db_session.expire_all()
    req = db_session.get(OrderReturnRequest, rid)
    assert req.status == ReturnRequestStatus.CLOSED.value, f"申请没有自动关闭：{req.status}"
    assert req.handled_by == users["dispatcher"].id
    assert req.handled_at is not None

    # ③ 数据照常变：库存回补 + 已退数量
    assert db_session.get(Product, pid).stock == 97, db_session.get(Product, pid).stock
    detail = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert Decimal(detail["returned_amount"]) == Decimal("20.00"), detail["returned_amount"]

    # ④ 货主收到一条"申请已关闭（派单员直接退了货）"，且写明退了多少 + 与申请是否一致
    db_session.expire_all()
    notes = (
        db_session.query(Notification)
        .filter(
            Notification.recipient_id == users["shipper"].id,
            Notification.type == "order.return_request.closed",
        )
        .all()
    )
    assert notes, "申请被自动关闭却没告诉货主"
    assert "退货金额 ¥20" in (notes[-1].content or ""), notes[-1].content
    assert "与申请的一致" in (notes[-1].content or ""), notes[-1].content

    # ⑤ ⛔ 关闭它才是"退两遍"的堵法：再点办理必须被拒
    again = client.post(f"/api/v1/return-requests/{rid}/fulfill", headers=h)
    assert again.status_code == 400, f"关闭之后还能办理（＝同一批货会退两遍）：{again.text[:200]}"
    assert "自动关闭" in again.text, again.text


def test_direct_return_notes_the_difference_from_the_request(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """直连退货的件数与申请**不一致**时，差异必须如实写出来（⛔ 不许盖成"已办理"）。"""
    from app.models import Notification

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, _pid = _order_with_product(client, token_shipper, db_session, "直连差异探针", qty=6, price="10.00")
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    _apply(client, token_shipper, oid, [(line["id"], 2)])  # 申请退 2 件

    # 派单员直接退 3 件（与申请不一致）
    direct = client.post(
        f"/api/v1/orders/{oid}/return",
        headers=h,
        json={"items": [{"order_product_id": line["id"], "quantity": 3}]},
    )
    assert direct.status_code == 200, direct.text

    db_session.expire_all()
    notes = (
        db_session.query(Notification)
        .filter(
            Notification.recipient_id == users["shipper"].id,
            Notification.type == "order.return_request.closed",
        )
        .all()
    )
    assert notes, "没有关闭通知"
    text = notes[-1].content or ""
    assert "与申请的不一致" in text, f"差异被盖掉了：{text}"
    assert "×2" in text and "×3" in text, f"两边件数都要写出来：{text}"


def test_shipper_cannot_call_the_real_return_endpoint(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """★ 货主**不能**直接退货（403）——申请制存在的意义就是这条线。

    这条如果破了，货主按一下就能改自己的应收和公司库存，整套申请流程等于装饰。
    """
    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, _pid = _order_with_product(client, token_shipper, db_session, "越权退货探针", qty=2, price="10.00")
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    r = client.post(
        f"/api/v1/orders/{oid}/return",
        headers=auth_headers(token_shipper),
        json={"items": [{"order_product_id": line["id"], "quantity": 1}]},
    )
    assert r.status_code == 403, f"货主居然能直接退货：{r.status_code} {r.text[:200]}"


def test_driver_cannot_apply_or_read_the_todo_list(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """司机既不能申请（403），也看不到派单员的待办列表（403）。"""
    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, _pid = _order_with_product(client, token_shipper, db_session, "司机越权探针", qty=2, price="10.00")
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]

    r = client.post(
        "/api/v1/return-requests",
        headers=hd,
        json={"order_id": oid, "items": [{"order_product_id": line["id"], "quantity": 1}]},
    )
    assert r.status_code == 403, f"司机居然能申请退货：{r.status_code} {r.text[:200]}"
    assert client.get("/api/v1/return-requests", headers=hd).status_code == 403


def test_shipper_sees_only_own_requests_and_cannot_withdraw_others(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """货主只能看/撤自己的申请；派单员列表里两条都在（他自己的那条不能撤）。"""
    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, _pid = _order_with_product(client, token_shipper, db_session, "归属探针", qty=4, price="25.00")
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 1)]).json()["id"]

    # 派单员也去调"我的申请" → 他不该看到货主那条（这个端点按 shipper_id 过滤）
    mine_as_dispatcher = client.get("/api/v1/return-requests/mine", headers=h).json()
    assert all(x["id"] != rid for x in mine_as_dispatcher["items"]), mine_as_dispatcher

    # 司机撤别人的申请 → 403
    assert client.post(f"/api/v1/return-requests/{rid}/withdraw", headers=hd).status_code == 403

    # 派单员待办列表里能看到，且带申请人与单号
    todo = client.get("/api/v1/return-requests", headers=h).json()
    row = [x for x in todo["items"] if x["id"] == rid][0]
    assert row["shipper_id"] == users["shipper"].id
    assert row["order_no"], row
    assert todo["pending_count"] >= 1, todo["pending_count"]


def test_apply_requires_delivered_and_cannot_over_ask(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """没送达的单不能申请；数量超过可退上限要给一句能照着改的中文。"""
    h = auth_headers(token_dispatcher)
    # 还没派送的
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "lines": [{"product_name_snapshot": "未送达申请探针", "quantity": 2, "unit_price": "10.00", "line_total": "20.00"}],
            "delivery_description": "未送达申请地址",
            "address_detail": "未送达申请地址",
        },
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    line = _lines_of(client, h, oid)[0]
    not_yet = _apply(client, token_shipper, oid, [(line["id"], 1)])
    assert not_yet.status_code == 400, not_yet.text
    assert "已送达" in not_yet.text

    # 送达之后超量申请
    hd = auth_headers(token_driver)
    _deliver(client, h, hd, users, oid)
    over = _apply(client, token_shipper, oid, [(line["id"], 5)])
    assert over.status_code == 400, over.text
    assert "最多只能退 2" in over.text, over.text


def test_apply_does_not_check_membership(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """★ 普通货主与批发商**都能**申请（用户拍板：所有货主都能申请，不只看 is_member）。

    这一条是防"将来有人把申请入口按 is_member 收窄"——那会让一半订单没有退货入口。
    """
    from app.models import User

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid, _pid = _order_with_product(client, token_shipper, db_session, "非批发商申请探针", qty=2, price="10.00")
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]

    db_session.expire_all()
    me = db_session.get(User, users["shipper"].id)
    assert not me.is_member, "前提不成立：这个测试货主应该是普通货主"
    r = _apply(client, token_shipper, oid, [(line["id"], 1)])
    assert r.status_code == 201, f"普通货主申请不了退货：{r.status_code} {r.text[:200]}"
