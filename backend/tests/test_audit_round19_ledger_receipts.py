"""第十八轮审计的回归测试：**账本与收款**（红队审计员报的 F1/F2/F3/F7）。

| 缺陷 | 后果 |
|---|---|
| **F1（高）送达把"已经收过的款"静默改回未收** | `_apply_complete_payment` 无条件 `paid=False`：先收了一笔钱（预收/代收）→ 送达时 `collect_cash` 默认 False → 落到 else 分支 → `paid` 被抹回未收，而收款单与现金流水都还在 → 这张单又出现在「客户收款」的"已送达未收"列表里 → **再核销一次**：资金流入 = 2×、营业额 = 1×、客户被重复催收。本机实例：订单 841（`paid=1` + 收款单 #76 + 流水 #258） |
| **F1b（高）已撤销的单也能收款** | `create_receipt` 的存在/归属/已收三道校验里**唯独没有状态** → 本机有 **73 张已撤销**的单挂着逐单核销的收款单 + 流水（¥2,900）：客户的"已收"虚高，而真正该收的那张单还欠着 |
| **F2（高）改一行"货损红冲"账本流水的备注，会把订单商品行静默清零** | `sync_order_product_from_ledger` 只排除 `MANUAL`，于是 `REFUND` 行也回写 —— 而红冲行的数量/单价/金额记的是**被冲掉的那一部分**（本机 ledgers#17：qty=2/单价=0/金额=0 → order_products#26 现状 qty=10/单价=23.5/金额=235）。改一次备注 → 该单营业额 235→0，而司机账单与 ORDER 账本行仍是 235 = **一张单三个数** |
| **F3（中）账本行可以改挂到别的订单上** | `_reject_if_order_closed` 按**改之前**的 order_id 判，改完却按**新的** order_id 回写 → 可以把一行订单账改挂到别的单，并让回写落到那张单的商品行（订单状态守卫等于被绕过） |
| **F7（低）导出金额用银行家舍入** | `_money()` / 单均价缺 `rounding=ROUND_HALF_UP`，与全项目 `driver_pay.money()` 不一致（半分位差 1 分） |
"""
from __future__ import annotations

from decimal import Decimal

from tests.conftest import auth_headers


def _order_as_shipper(client, token_shipper, name: str, qty: int = 1, price: str = "100.00") -> int:
    """用货主本人账号下单（订单才挂在它的客户档案下）。"""
    hs = auth_headers(token_shipper)
    r = client.post(
        "/api/v1/orders",
        headers=hs,
        json={
            "lines": [
                {
                    "product_name_snapshot": name,
                    "quantity": qty,
                    "unit_price": price,
                    "line_total": str(Decimal(price) * qty),
                }
            ],
            "delivery_description": f"{name}探针地址",
            "address_detail": f"{name}探针地址",
        },
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _customer_for(client, h, token_shipper, tag: str) -> int:
    me = client.get("/api/v1/users/me", headers=auth_headers(token_shipper)).json()
    r = client.post("/api/v1/customers", headers=h, json={"name": f"{tag}客户", "user_id": me["id"]})
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _receipt(client, h, customer_id: int, amount: str, order_ids: list[int], mode: str = "itemized"):
    return client.post(
        "/api/v1/ledger/receipts",
        headers=h,
        json={
            "customer_id": customer_id,
            "amount": amount,
            "method": "cash",
            "settle_mode": mode,
            "order_ids": order_ids,
            "received_at": "2026-09-18",
        },
    )


# --------------------------------------------------------------- F1 送达不许抹掉已收的钱
def test_delivery_does_not_reset_an_already_collected_order(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """先收了钱 → 送达**不许**把 `paid` 改回 False（否则这张单能被再收一次）。"""
    from app.models import Order

    h = auth_headers(token_dispatcher)
    oid = _order_as_shipper(client, token_shipper, "先收款后送达探针")
    customer_id = _customer_for(client, h, token_shipper, "先收款后送达")

    first = _receipt(client, h, customer_id, "100.00", [oid])
    assert first.status_code in (200, 201), first.text
    db_session.expire_all()
    assert db_session.get(Order, oid).paid is True, "前提不成立：收款没把订单标成已收"

    # 正常派送 → 司机送达（collect_cash 默认 False → 老代码会落进 else 分支把 paid 抹回 False）
    r = client.post(f"/api/v1/orders/{oid}/assign", json={"driver_id": users["driver"].id}, headers=h)
    assert r.status_code == 200, r.text
    hd = auth_headers(token_driver)
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hd).status_code == 200
    r = client.post(f"/api/v1/orders/{oid}/complete", json={"delivery_photo_urls": []}, headers=hd)
    # 送达照片在本项目是硬要求（司机端必须先拍照），拿不到 200 说明这道前置条件变了
    if r.status_code == 400 and "照片" in r.text:
        r = client.post(
            f"/api/v1/orders/{oid}/complete",
            json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
            headers=hd,
        )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    after = db_session.get(Order, oid)
    assert after.paid is True, (
        "送达把『已经收过款』改回了未收 —— 这张单会重新出现在「客户收款」的待收列表里，"
        "再核销一次就是资金流入翻倍"
    )

    # 再核销一次必须被拒（收款侧唯一的防重判据就是 paid / inbound 流水）
    again = _receipt(client, h, customer_id, "100.00", [oid])
    assert again.status_code == 400, f"同一张单又被收了一次款：{again.status_code} {again.text[:200]}"

    # 留痕：送达这一步动过收款状态的话，审计页上必须看得见
    from app.models import OperationLog

    logs = (
        db_session.query(OperationLog)
        .filter(OperationLog.order_id == oid, OperationLog.action == "ORDER_COMPLETE")
        .all()
    )
    assert any("payment" in (x.change_content or "") for x in logs), (
        f"送达时的收款处理没有留痕：{[x.change_content for x in logs]}"
    )


def test_delivery_with_cash_is_refused_when_already_collected(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """已经收过款的单：司机再报「收了现金」必须被拒（那就是重复收款）。"""
    h = auth_headers(token_dispatcher)
    oid = _order_as_shipper(client, token_shipper, "重复收现金探针")
    customer_id = _customer_for(client, h, token_shipper, "重复收现金")
    assert _receipt(client, h, customer_id, "100.00", [oid]).status_code in (200, 201)

    r = client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "collect_cash": True},
        headers=h,
    )
    assert r.status_code == 200, r.text
    hd = auth_headers(token_driver)
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hd).status_code == 200
    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"], "payment": "cash"},
        headers=hd,
    )
    assert r.status_code == 400, f"重复收现金被放行了：{r.status_code} {r.text[:200]}"
    assert "已经收过款" in r.text, r.text[:200]


# --------------------------------------------------------------- F1b 已撤销的单不许收款
def test_cancelled_order_cannot_be_collected(client, token_dispatcher, token_shipper, db_session):
    """已撤销的单不能再收款（本机有 73 张已撤销单挂着收款单 + 流水）。"""
    from app.models import CashFlow, ShipperReceipt

    h = auth_headers(token_dispatcher)
    oid = _order_as_shipper(client, token_shipper, "已撤销收款探针")
    customer_id = _customer_for(client, h, token_shipper, "已撤销收款")
    r = client.post(f"/api/v1/orders/{oid}/cancel", json={"reason": "探针撤销"}, headers=h)
    assert r.status_code == 200, r.text

    before_receipts = db_session.query(ShipperReceipt).count()
    before_flows = db_session.query(CashFlow).count()
    r = _receipt(client, h, customer_id, "100.00", [oid])
    assert r.status_code == 400, f"已撤销的单被收款了：{r.status_code} {r.text[:200]}"
    assert "撤销" in r.text, r.text[:200]

    db_session.expire_all()
    assert db_session.query(ShipperReceipt).count() == before_receipts, "被拒绝的收款却写了收款单"
    assert db_session.query(CashFlow).count() == before_flows, "被拒绝的收款却写了现金流水"


# --------------------------------------------------------------- F2 红冲行的备注不许清零订单行
def test_editing_a_refund_note_does_not_zero_the_order_line(
    client, token_dispatcher, token_shipper, db_session
):
    """改「货损红冲」账本行的备注：备注要落下去，**订单行一个字都不许动**。"""
    from app.models import Ledger, Order, OrderProduct
    from app.models.enums import LedgerSource, OrderStatus

    h = auth_headers(token_dispatcher)
    oid = _order_as_shipper(client, token_shipper, "红冲备注探针", qty=10, price="23.50")
    db_session.expire_all()
    line = db_session.query(OrderProduct).filter(OrderProduct.order_id == oid).first()
    assert line is not None
    before = (line.quantity, str(line.unit_price), str(line.line_total))

    # 造一条 REFUND 行（真实链路里由货损核算生成：数量=被冲的件数、单价/金额=0）
    refund = Ledger(
        shipper_id=None,
        temp_shipper_name="红冲探针",
        entry_date=__import__("datetime").date(2026, 9, 18),
        product_name="红冲备注探针",
        quantity=2,
        unit_price=Decimal("0"),
        total=Decimal("0"),
        order_id=oid,
        order_product_id=line.id,
        source=LedgerSource.REFUND,
        note="送达货损成本冲回（自动）2 件",
    )
    db_session.add(refund)
    db_session.commit()
    refund_id = refund.id

    r = client.patch(
        f"/api/v1/ledger/entries/{refund_id}", json={"note": "改成我自己的备注"}, headers=h
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    after_line = db_session.get(OrderProduct, line.id)
    assert (after_line.quantity, str(after_line.unit_price), str(after_line.line_total)) == before, (
        f"改一条红冲流水的备注把订单行改了：{before} → "
        f"{(after_line.quantity, str(after_line.unit_price), str(after_line.line_total))}"
    )
    assert db_session.get(Ledger, refund_id).note == "改成我自己的备注", "备注本身要改成功"
    assert db_session.get(Order, oid) is not None


def test_refund_row_detail_edit_is_refused_when_order_closed(
    client, token_dispatcher, token_shipper, db_session
):
    """红冲流水的**明细**永远不许改（金额已经定了）。

    ⚠️ 挡住它的**不是**"订单已结束"那道守卫，而是更前面一道按 `source` 判的门
    （`detail_editable = row.source in (MANUAL, ORDER)` → REFUND 直接 400）。
    这条测试存在的意义是**钉住那道门**：它一旦被放宽成"什么来源都能改明细"，
    F2 那条洞（改一条红冲行就把订单行清零）就会从**备注**扩到数量/单价/金额。
    """
    from datetime import date as _date

    from app.models import Ledger, OrderProduct
    from app.models.enums import LedgerSource, OrderStatus

    h = auth_headers(token_dispatcher)
    oid = _order_as_shipper(client, token_shipper, "红冲守卫探针")
    r = client.post(f"/api/v1/orders/{oid}/cancel", json={"reason": "探针撤销"}, headers=h)
    assert r.status_code == 200, r.text
    db_session.expire_all()
    line = db_session.query(OrderProduct).filter(OrderProduct.order_id == oid).first()
    assert line is not None

    refund = Ledger(
        shipper_id=None,
        temp_shipper_name="红冲守卫",
        entry_date=_date(2026, 9, 18),
        product_name="红冲守卫探针",
        quantity=1,
        unit_price=Decimal("0"),
        total=Decimal("0"),
        order_id=oid,
        order_product_id=line.id,
        source=LedgerSource.REFUND,
        note="冲回",
    )
    db_session.add(refund)
    db_session.commit()

    r = client.patch(
        f"/api/v1/ledger/entries/{refund.id}", json={"quantity": 99}, headers=h
    )
    assert r.status_code == 400, f"已撤销订单的红冲行明细被改了：{r.status_code} {r.text[:200]}"
    db_session.expire_all()
    assert db_session.get(Ledger, refund.id).quantity == 1, "被拒绝的修改却改了库"


# --------------------------------------------------------------- F3 账本行不许改挂订单
def test_ledger_entry_cannot_be_repointed_to_another_order(
    client, token_dispatcher, token_shipper, db_session
):
    """改账本行的 `order_id` = 把回写目标换一张单 → 必须拒绝。"""
    from app.models import Ledger
    from app.models.enums import LedgerSource

    h = auth_headers(token_dispatcher)
    oid_a = _order_as_shipper(client, token_shipper, "改挂探针A")
    oid_b = _order_as_shipper(client, token_shipper, "改挂探针B")
    db_session.expire_all()

    row = Ledger(
        shipper_id=None,
        temp_shipper_name="改挂探针",
        entry_date=__import__("datetime").date(2026, 9, 18),
        product_name="改挂探针A",
        quantity=1,
        unit_price=Decimal("100"),
        total=Decimal("100"),
        order_id=oid_a,
        source=LedgerSource.MANUAL,
        note="手工账",
    )
    db_session.add(row)
    db_session.commit()

    r = client.patch(f"/api/v1/ledger/entries/{row.id}", json={"order_id": oid_b}, headers=h)
    assert r.status_code == 400, f"账本行被改挂到别的订单上了：{r.status_code} {r.text[:200]}"
    assert "改挂" in r.text or "订单" in r.text, r.text[:200]
    db_session.expire_all()
    assert db_session.get(Ledger, row.id).order_id == oid_a


# --------------------------------------------------------------- F7 导出金额的进位
def test_export_money_uses_half_up_like_the_rest_of_the_project():
    """`.quantize()` 默认是银行家舍入；导出金额必须与全项目一致用 HALF_UP。"""
    from app.api.v1.reports import _money

    assert _money(Decimal("0.125")) == 0.13, "持仓半分位时必须进位（HALF_UP），不是 0.12（HALF_EVEN）"
    assert _money(Decimal("0.135")) == 0.14, "0.135 在 HALF_EVEN 下会落到 0.14/0.12 之间，必须稳定进位"
    assert _money(Decimal("100.005")) == 100.01
    assert _money(None) == ""
    assert _money("") == ""
