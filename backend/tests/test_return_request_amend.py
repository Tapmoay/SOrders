"""退货申请**可以直接改**（2026-10-15 CHG-0130，用户口径逐字见变更单）。

## 这一批钉住的东西（每条都有"不钉住会怎样"）

| 判据 | 不钉住会怎样 |
|---|---|
| 派单员改了明细 → 申请单上**真是**新数量 | 消息说改了、办理却按旧数量退货，两边各说各话 |
| 改完**只发一条**给货主（正文带"原来是…现在是…"） | 用户明确否掉了"每个字段发一条"；发多条等于把改动变成骚扰 |
| 货主 / 批发商在**派单员还没确认**时可改 | 用户原话「只要派单员还没有确认，他也是可以更改」——不许逼他撤回重提 |
| 已办理 / 已驳回 / 已撤回 / 已自动关闭一律拒 | 结论已经执行（或凭证已经作废），事后改明细 = 凭证与事实对不上 |
| 改动**只动申请单**：库存 / 账本 / 现金 / 订单状态 / 已退数量一个都不动 | "改一下"就等于退货，申请制的意义整个没了（红线也盯着这条） |
| 一条都不勾 / 填 0 / 超上限 / 非整数 → **中文**被拒 | 用户看到英文结构体，只会反复重试（或干脆找派单员手工改库存） |
| 不是自己的申请改不了；司机 403 | 越权改别人的凭证 |
| 改完之后办理**就按新数量**退 | 改了却不生效 = 这个功能白做，用户下次直接放弃 |

⚠️ 与 `test_return_request.py` 的分工：那个文件钉「申请 → 办理」这条主链，本文件只钉
"改明细"这一件事（含改动**不该**碰到的东西）。两边都建自己的单，互不依赖。
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func

from tests.conftest import auth_headers


# --------------------------------------------------------------------- 建单 / 走链
def _order_with_products(
    client, token_shipper, db_session, specs: list[tuple[str, int, str]], *, stock: int = 100
) -> int:
    """建一张带 N 行商品的单（每行都建 Product：库存与红冲才有对象可断言）。"""
    from app.models import Product

    lines = []
    for name, qty, price in specs:
        prod = Product(name=name, unit="件", stock=stock, cost_price=Decimal("30.00"))
        db_session.add(prod)
        db_session.commit()
        lines.append(
            {
                "product_name_snapshot": name,
                "quantity": qty,
                "unit_price": price,
                "line_total": str(Decimal(price) * qty),
                "product_id": prod.id,
            }
        )
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            # L-32：下单必须至少一端有联系信息（后端命令层硬拦，与 App 下单页同源）
            "contact_dongjia_name": "收货人甲",
            "lines": lines,
            "delivery_description": "改动探针地址",
            "address_detail": "改动探针地址",
        },
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _deliver(client, h, hd, users, oid: int) -> None:
    assert client.post(f"/api/v1/orders/{oid}/assign", json={"driver_id": users["driver"].id}, headers=h).status_code == 200
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
        json={"order_id": oid, "items": [{"order_product_id": pid, "quantity": q} for pid, q in items], "note": note},
    )


def _amend(client, h, rid: int, items: list[tuple[int, int]], *, raw: dict | None = None):
    """改明细。`raw` 用来发**故意畸形**的请求体（测试拒绝路径时要能绕过 helper 的规整）。"""
    body = raw if raw is not None else {"items": [{"order_product_id": pid, "quantity": q} for pid, q in items]}
    return client.post(f"/api/v1/return-requests/{rid}/amend", headers=h, json=body)


def _note_watermark(db_session) -> int:
    """当前最大的站内信 id。

    ⚠️ 为什么非要它：三个共用账号 + 共用一个 SQLite 测试库 ⇒ **上一个用例留下的通知还在**，
    直接 `.all()` 会把别人那条也算进来（实测：本文件第 2 个用例就撞上了第 1 个留下的 2 条）。
    所有"改动通知"的断言都只数**水位线之后**的那几条。
    """
    from app.models import Notification

    db_session.expire_all()
    return int(db_session.query(func.max(Notification.id)).scalar() or 0)


def _amended_notes(db_session, recipient_id: int, since_id: int = 0):
    from app.models import Notification

    db_session.expire_all()
    return (
        db_session.query(Notification)
        .filter(
            Notification.id > since_id,
            Notification.recipient_id == recipient_id,
            Notification.type == "order.return_request.amended",
        )
        .order_by(Notification.id)
        .all()
    )


def _untouched(db_session, oid: int) -> dict:
    """把"改明细本不该动的那几样"一次拍下来（钱、库存、状态、已退数量）。"""
    from app.models import CashFlow, Ledger, Order, OrderProduct

    db_session.expire_all()
    order = db_session.get(Order, oid)
    return {
        "status": order.status,
        "returned_at": order.returned_at,
        "returned_qty": [
            int(x.returned_quantity or 0)
            for x in db_session.query(OrderProduct).filter(OrderProduct.order_id == oid).all()
        ],
        "ledger_rows": db_session.query(Ledger).filter(Ledger.order_id == oid).count(),
        "cash_rows": db_session.query(CashFlow).filter(CashFlow.order_id == oid).count(),
    }


# ---------------------------------------------------------------- ① 派单员改 → 真变了 + 一条通知
def test_dispatcher_amend_changes_lines_and_notifies_shipper_once(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """★ 派单员改数量：申请单上真变、货主**收到一条**改动通知、其余一切不动。"""
    from app.models import Notification, OperationAction, OperationLog, OrderReturnRequest, OrderReturnRequestLine

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order_with_products(client, token_shipper, db_session, [("改动探针", 4, "25.00")])
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 2)], note="有两件破了").json()["id"]
    before_state = _untouched(db_session, oid)
    base = _note_watermark(db_session)

    r = _amend(client, h, rid, [(line["id"], 3)])
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["id"] == rid, got
    assert got["status"] == "pending", f"改明细不该动状态：{got['status']}"
    assert got["lines"][0]["quantity"] == 3, got["lines"]
    assert got["note"] == "有两件破了", f"改明细不该动备注：{got['note']}"

    db_session.expire_all()
    req = db_session.get(OrderReturnRequest, rid)
    rows = db_session.query(OrderReturnRequestLine).filter(OrderReturnRequestLine.request_id == rid).all()
    assert len(rows) == 1 and rows[0].quantity == 3, [(x.order_product_id, x.quantity) for x in rows]
    assert req.lines[0].quantity == 3, req.lines[0].quantity

    # 只动申请单：钱 / 库存 / 状态 / 已退数量一个都不动
    assert _untouched(db_session, oid) == before_state, "改明细动了本不该动的东西"

    # 货主**只收到一条**（用户明确不要"每个字段发一条"）
    notes = _amended_notes(db_session, users["shipper"].id, base)
    assert len(notes) == 1, f"改动通知应该只有一条，实际 {len(notes)} 条：" + " | ".join(n.content or "" for n in notes)
    assert notes[0].title == "退货申请有改动", notes[0].title
    assert "原来是 改动探针×2" in (notes[0].content or ""), notes[0].content
    assert "现在是 改动探针×3" in (notes[0].content or ""), notes[0].content
    assert (notes[0].payload or {}).get("request_id") == rid, notes[0].payload
    assert (notes[0].payload or {}).get("actor_role") == "dispatcher", notes[0].payload
    # 派单员自己不该收到"他改的"这条（收件人是另外两方）
    assert _amended_notes(db_session, users["dispatcher"].id, base) == [], "派单员收到了自己改出来的通知"

    # 审计留痕：改动前 / 改动后 / 改动人
    log = (
        db_session.query(OperationLog)
        .filter_by(action=OperationAction.ORDER_RETURN_REQUEST_AMEND)
        .order_by(OperationLog.id.desc())
        .first()
    )
    assert log is not None and log.order_id == oid, log
    assert "改动前" in (log.change_content or "") and "改动后" in (log.change_content or ""), log.change_content
    assert "改动探针×2" in (log.change_content or "") and "改动探针×3" in (log.change_content or ""), log.change_content
    # change_content 是 json.dumps(..., ensure_ascii=False) ⇒ 键名带引号，逐字对得上。
    assert '"改动人"' in (log.change_content or ""), log.change_content
    assert "派单员" in (log.change_content or ""), log.change_content

    # 再改一次 → 再发一条（一条改动一条通知，不是一条申请一条）
    base2 = _note_watermark(db_session)
    assert _amend(client, h, rid, [(line["id"], 1)]).status_code == 200
    again = _amended_notes(db_session, users["shipper"].id, base2)
    assert len(again) == 1, f"第二次改动没有通知货主（新通知 {len(again)} 条）"
    assert "原来是 改动探针×3" in (again[0].content or "") and "现在是 改动探针×1" in (again[0].content or ""), again[0].content


# ---------------------------------------------------------------- ② 货主未确认可改 / 终态拒绝
def test_shipper_amend_while_pending_then_fulfill_uses_new_quantity(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """★ 货主在**派单员还没确认**时可改，改完通知派单员；办理就按**新**数量退。"""
    from app.models import Notification, OrderProduct, Product

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order_with_products(client, token_shipper, db_session, [("货主改动探针", 4, "25.00")])
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 3)]).json()["id"]
    db_session.expire_all()
    stock_after_delivery = db_session.query(Product).filter(Product.name == "货主改动探针").first().stock
    assert stock_after_delivery == 96, f"前提不成立：送达没实扣库存（{stock_after_delivery}）"
    base = _note_watermark(db_session)

    r = _amend(client, auth_headers(token_shipper), rid, [(line["id"], 1)])
    assert r.status_code == 200, f"派单员还没确认，货主却改不了：{r.status_code} {r.text[:300]}"
    assert r.json()["lines"][0]["quantity"] == 1, r.json()["lines"]

    # 通知发给**派单员**（货主改的 → 告诉派单员"此退货订单发生了改动"）
    notes = _amended_notes(db_session, users["dispatcher"].id, base)
    assert len(notes) == 1, f"货主改了却没告诉派单员（{len(notes)} 条）"
    assert "请按新的数量办理" in (notes[0].content or ""), notes[0].content
    assert (notes[0].payload or {}).get("actor_role") == "shipper", notes[0].payload
    assert _amended_notes(db_session, users["shipper"].id, base) == [], "货主收到了自己改出来的通知"

    # 办理按**新**数量：1×25 = 25（不是申请时的 3×25 = 75）
    r = client.post(f"/api/v1/return-requests/{rid}/fulfill", headers=h)
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["returned"]["returned_amount"]) == Decimal("25.00"), r.json()["returned"]
    db_session.expire_all()
    assert int(db_session.get(OrderProduct, int(line["id"])).returned_quantity or 0) == 1
    assert db_session.query(Product).filter(Product.name == "货主改动探针").first().stock == 97
    assert len(_amended_notes(db_session, users["dispatcher"].id, base)) == 1, "办理不该再补发一条改动通知"


def test_amend_refused_after_done_rejected_or_withdrawn(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """★ 终态就是终态：已办理 / 已驳回 / 已撤回一律拒绝（话术与撤回、驳回同一套）。"""
    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    hs = auth_headers(token_shipper)

    # 已办理
    oid = _order_with_products(client, token_shipper, db_session, [("已办理改动探针", 2, "10.00")])
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 1)]).json()["id"]
    assert client.post(f"/api/v1/return-requests/{rid}/fulfill", headers=h).status_code == 200
    done = _amend(client, h, rid, [(line["id"], 2)])
    assert done.status_code == 400, done.text
    assert "已经办完了" in done.text and "不能改" in done.text, done.text
    # 货主那边同样拒绝（不是只挡派单员）
    assert _amend(client, hs, rid, [(line["id"], 2)]).status_code == 400

    # 已驳回
    oid2 = _order_with_products(client, token_shipper, db_session, [("已驳回改动探针", 2, "10.00")])
    _deliver(client, h, hd, users, oid2)
    line2 = _lines_of(client, h, oid2)[0]
    rid2 = _apply(client, token_shipper, oid2, [(line2["id"], 1)]).json()["id"]
    rej = client.post(f"/api/v1/return-requests/{rid2}/reject", json={"reason": "货没坏"}, headers=h)
    assert rej.status_code == 200, rej.text
    after_reject = _amend(client, hs, rid2, [(line2["id"], 2)])
    assert after_reject.status_code == 400, after_reject.text
    assert "已经被驳回了" in after_reject.text, after_reject.text

    # 已撤回（货主自己撤的，然后自己也不能改）
    oid3 = _order_with_products(client, token_shipper, db_session, [("已撤回改动探针", 2, "10.00")])
    _deliver(client, h, hd, users, oid3)
    line3 = _lines_of(client, h, oid3)[0]
    rid3 = _apply(client, token_shipper, oid3, [(line3["id"], 1)]).json()["id"]
    assert client.post(f"/api/v1/return-requests/{rid3}/withdraw", headers=hs).status_code == 200
    after_withdraw = _amend(client, hs, rid3, [(line3["id"], 2)])
    assert after_withdraw.status_code == 400, after_withdraw.text
    assert "已经被申请人撤回了" in after_withdraw.text, after_withdraw.text


# ---------------------------------------------------------------- ③ 空明细 / 0 / 越界 / 非整数
def test_amend_refuses_empty_zero_over_cap_and_non_integer(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """★ 拒绝路径全说中文：一条都不勾、填 0、超上限、小数、字母 —— 申请本身不受损。"""
    from app.models import OrderReturnRequestLine

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order_with_products(client, token_shipper, db_session, [("拒绝路径探针", 2, "10.00")])
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 2)]).json()["id"]

    empty = _amend(client, h, rid, [], raw={"items": []})
    assert empty.status_code == 422, empty.text
    assert "商品明细" in empty.text and "至少 1 项" in empty.text, empty.text

    zero = _amend(client, h, rid, [], raw={"items": [{"order_product_id": line["id"], "quantity": 0}]})
    assert zero.status_code == 422, zero.text
    assert "数量" in zero.text and "不能小于 1" in zero.text, zero.text

    over = _amend(client, h, rid, [(line["id"], 5)])
    assert over.status_code == 400, over.text
    assert "最多只能退 2" in over.text, over.text

    half = _amend(client, h, rid, [], raw={"items": [{"order_product_id": line["id"], "quantity": 1.5}]})
    assert half.status_code == 422, half.text
    assert "要填整数" in half.text, half.text

    letters = _amend(client, h, rid, [], raw={"items": [{"order_product_id": line["id"], "quantity": "abc"}]})
    assert letters.status_code == 422, letters.text
    assert "要填整数" in letters.text, letters.text

    # 被拒这么多次之后，申请还是原样、还能正常改
    db_session.expire_all()
    rows = db_session.query(OrderReturnRequestLine).filter(OrderReturnRequestLine.request_id == rid).all()
    assert len(rows) == 1 and rows[0].quantity == 2, f"被拒的请求动到了明细：{[(x.order_product_id, x.quantity) for x in rows]}"
    ok = _amend(client, h, rid, [(line["id"], 1)])
    assert ok.status_code == 200, ok.text
    assert ok.json()["lines"][0]["quantity"] == 1, ok.json()["lines"]


# ---------------------------------------------------------------- ④ 换商品种类（不是新建一张）
def test_amend_swaps_product_kind_and_keeps_one_request(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """★ 用户口径里的"商品种类可以改"：换一行商品 = 改这张申请，**不是**新建一张。"""
    from app.models import OrderReturnRequest, OrderReturnRequestLine

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order_with_products(client, token_shipper, db_session, [("换种类探针甲", 2, "10.00"), ("换种类探针乙", 2, "30.00")])
    _deliver(client, h, hd, users, oid)
    op_a, op_b = _lines_of(client, h, oid)
    rid = _apply(client, token_shipper, oid, [(op_a["id"], 2)]).json()["id"]

    r = _amend(client, auth_headers(token_shipper), rid, [(op_b["id"], 1)])
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["id"] == rid, f"换商品种类不该换一张申请：{got['id']} != {rid}"
    assert [x["order_product_id"] for x in got["lines"]] == [op_b["id"]], got["lines"]
    assert got["lines"][0]["quantity"] == 1, got["lines"]

    db_session.expire_all()
    n_reqs = db_session.query(OrderReturnRequest).filter(OrderReturnRequest.order_id == oid).count()
    # 文案拆两段：判据 _check_return_request_editable.py 认的是前半段（含结尾引号）。
    assert n_reqs == 1, f"换种类多出了一张申请" + f"（这张单上有 {n_reqs} 张）"
    rows = db_session.query(OrderReturnRequestLine).filter(OrderReturnRequestLine.request_id == rid).all()
    assert [x.order_product_id for x in rows] == [op_b["id"]], [(x.order_product_id, x.quantity) for x in rows]
    assert rows[0].product_name == "换种类探针乙", rows[0].product_name

    # 勾一行**不属于这张单**的商品 → 中文拒绝（不是 500、也不是静默接受）
    other = _order_with_products(client, token_shipper, db_session, [("别人家的探针", 1, "10.00")])
    _deliver(client, h, hd, users, other)
    foreign = _lines_of(client, h, other)[0]
    bad = _amend(client, h, rid, [(foreign["id"], 1)])
    assert bad.status_code == 400, bad.text
    assert "不在这一单里" in bad.text, bad.text


# ---------------------------------------------------------------- ⑤ 谁能改、谁不能
def test_amend_refuses_stranger_driver_and_missing_request(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """★ 司机 403、别的货主 400、申请不存在 404 —— 越权与不存在的答复都要是中文。"""
    from app.models import OrderReturnRequest, User
    from app.models.enums import UserRole
    from app.services.auth_service import issue_token

    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order_with_products(client, token_shipper, db_session, [("越权改动探针", 2, "10.00")])
    _deliver(client, h, hd, users, oid)
    line = _lines_of(client, h, oid)[0]
    rid = _apply(client, token_shipper, oid, [(line["id"], 1)]).json()["id"]

    # 司机：连这个权限点都没有
    as_driver = _amend(client, hd, rid, [(line["id"], 2)])
    assert as_driver.status_code == 403, f"司机居然能改退货申请：{as_driver.status_code} {as_driver.text[:200]}"

    # 别的货主：申请不是他的
    other = User(
        phone="13710000031",
        username="13710000031",
        full_name="另一个货主",
        password_hash="x",
        role=UserRole.SHIPPER.value,
    )
    db_session.add(other)
    db_session.commit()
    try:
        stranger = _amend(client, auth_headers(issue_token(other)), rid, [(line["id"], 2)])
        assert stranger.status_code == 400, stranger.text
        assert "不是你的" in stranger.text, stranger.text
        db_session.expire_all()
        kept = db_session.get(OrderReturnRequest, rid)
        assert kept.lines[0].quantity == 1, f"越权那次改动居然生效了：{kept.lines[0].quantity}"
    finally:
        db_session.delete(other)
        db_session.commit()

    # 不存在的申请
    missing = _amend(client, h, rid + 99999, [(line["id"], 1)])
    assert missing.status_code == 404, missing.text
    assert "未找到" in missing.text, missing.text
