"""TB-09 / BUG-0029 的定点用例：**客户收款登记之后要有一条撤销（软删）与恢复的路**。

## 为什么这几条必须钉住（每一条都是"不报错但会错"的形状）
1. **一次收款写四个落点**：`shipper_receipts` 一行 ＋ `cash_flows`（`RECEIPT_CASH` /
   `RECEIPT_TRANSFER` / `RECEIPT_ARREARS`）若干行 ＋
   `orders.paid=True` ＋ （由前两者算出来的）`turnover.collected/arrears` 与 `customer-balances`。
   **撤销必须四个一起回滚、恢复必须四个一起回来** —— 少回滚一处，账上就是"钱说没了、
   单还说收了"（`services/order_money.py` 的口径：有流水按流水算、没流水才看 `paid`，
   所以只软删流水不改 `paid`、或只改 `paid` 不软删流水，**数字都回不去**）。
2. **撤销是软删**（用户 2026-09-20 的硬规矩：所有删除一律软删 ＋ 必须有恢复路径）：
   流水行与收款单行都还在库里，只是 `is_deleted=1`；`restore` 原样放回来。
3. **只回滚一次**：第二次撤销 / 第二次恢复必须是明确的拒绝（400），
   ⛔ 绝不允许"把数改两遍"（那会让账上多出一笔或少掉一笔）。
4. **每一次都要留痕**：撤销与恢复各写一条 `operation_logs`（`RECEIPT_CANCEL` / `RECEIPT_RESTORE`），
   与写入同一个事务。
5. **列表默认看不见已撤销的**（回收站式）：`GET /ledger/receipts` 默认过滤，
   `include_deleted=true` 才看得见它们（界面上那个"撤销"键就落在这个列表里）。

⚠️ 改前（HEAD）这五条里的前四条**一条都跑不过**：`DELETE /ledger/receipts/{id}` 与
`POST /ledger/receipts/{id}/restore` 在这个版本里是 **404**（路由根本不存在）。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models import CashFlow, OperationLog, Order, ShipperReceipt
from tests.conftest import auth_headers

RECEIPTS = "/api/v1/ledger/receipts"


def _order_delivered(client, h, token_shipper, token_driver, users, name: str, price: str = "100.00") -> int:
    """货主下单 → 派单 → 司机接单 → 送达。**必须送到"已送达"**：营业额与客户余额这两处
    只在已送达的单上认钱（`reports/turnover_query.py`），停在待派单的话那两条判据会恒真。"""
    hs = auth_headers(token_shipper)
    r = client.post(
        "/api/v1/orders",
        headers=hs,
        json={
            "contact_dongjia_name": "收货人甲",
            "lines": [
                {
                    "product_name_snapshot": name,
                    "quantity": 1,
                    "unit_price": price,
                    "line_total": price,
                }
            ],
            "delivery_description": f"{name}探针地址",
            "address_detail": f"{name}探针地址",
        },
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert client.post(f"/api/v1/orders/{oid}/assign", json={"driver_id": users["driver"].id}, headers=h).status_code == 200
    hd = auth_headers(token_driver)
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=hd).status_code == 200
    done = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=hd,
    )
    assert done.status_code == 200, done.text
    return oid


def _customer_for(client, h, token_shipper, tag: str) -> int:
    me = client.get("/api/v1/users/me", headers=auth_headers(token_shipper)).json()
    r = client.post("/api/v1/customers", headers=h, json={"name": f"{tag}客户", "user_id": me["id"]})
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _receipt(client, h, customer_id: int, amount: str, order_ids: list[int], mode: str = "itemized"):
    return client.post(
        RECEIPTS,
        headers=h,
        json={
            "customer_id": customer_id,
            "amount": amount,
            "method": "cash",
            "settle_mode": mode,
            "order_ids": order_ids,
            "received_at": date.today().isoformat(),
        },
    )


def _landing_points(client, h) -> dict[str, Decimal]:
    """四个落点里"算出来的那三个"当前各是多少（第 1 个落点 `orders.paid` 由调用处直接读库）。

    ⛔ 三处都必须走**端点**（不是读库自己求和）：判据要的是"用户看得见的那个数"。
    ⛔ 值一律定成 `Decimal` 再比：`cash-flows/summary` 在零的时候回的是 `"0"`，
       而 `"0" != "0.00"`（字符串）—— 按字符串比会得到一条假红。
    """
    anchor = date.today().isoformat()
    t = client.get(f"/api/v1/reports/turnover?mode=month&date={anchor}", headers=h)
    assert t.status_code == 200, t.text
    tj = t.json()
    c = client.get("/api/v1/cash-flows/summary", headers=h)
    assert c.status_code == 200, c.text
    b = client.get(f"/api/v1/reports/customer-balances?mode=month&date={anchor}", headers=h)
    assert b.status_code == 200, b.text
    return {
        "collected": Decimal(str(tj["collected"])),
        "arrears_total": Decimal(str(tj["arrears_total"])),
        "income": Decimal(str(c.json()["income"])),
        "balance": Decimal(str(b.json()["totals"]["balance"])),
    }


def _flows(db, receipt_id: int) -> list[CashFlow]:
    return list(
        db.scalars(
            select(CashFlow).where(CashFlow.doc_id == receipt_id, CashFlow.party_type == "customer")
        ).all()
    )


def _logs(db, action: str) -> list[OperationLog]:
    return list(db.scalars(select(OperationLog).where(OperationLog.action == action)).all())


def _dump(tag: str, client, h, db, receipt_id: int, order_id: int) -> None:
    """把「这一刻四个落点各是多少」打出来（证据文件要的正是这三组数）。

    ⚠️ 只在测试里打印：交付证据（_tmp/test_round3/green_receipt_undo.txt）要求
       「撤销前 / 撤销后 / 再恢复后」逐项可见，而不是只有一句"断言通过"。
    """
    db.expire_all()
    points = _landing_points(client, h)
    paid = db.get(Order, order_id).paid
    flow_state = "、".join(f"#{f.id}:is_deleted={int(bool(f.is_deleted))}" for f in _flows(db, receipt_id))
    receipt_state = int(bool(db.get(ShipperReceipt, receipt_id).is_deleted))
    print(
        "[四落点] " + tag
        + " | orders.paid=" + str(paid)
        + " | receipt.is_deleted=" + str(receipt_state)
        + " | flows: " + flow_state
        + " | turnover.collected=" + str(points["collected"])
        + " | turnover.arrears_total=" + str(points["arrears_total"])
        + " | cash-flows.income=" + str(points["income"])
        + " | customer-balances.balance=" + str(points["balance"])
    )


def _scenario(client, token_dispatcher, token_shipper, token_driver, users, db_session, tag: str):
    """送达一张 100 元的单 → 逐单核销收 100 元 → 返回 (h, oid, customer_id, receipt)。"""
    h = auth_headers(token_dispatcher)
    oid = _order_delivered(client, h, token_shipper, token_driver, users, f"{tag}探针")
    customer_id = _customer_for(client, h, token_shipper, tag)
    r = _receipt(client, h, customer_id, "100.00", [oid])
    assert r.status_code in (200, 201), r.text
    db_session.expire_all()
    return h, oid, customer_id, r.json()


# --------------------------------------------------------------- 四个落点一起回滚
def test_cancel_then_restore_moves_all_four_landing_points(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    h, oid, _cid, receipt = _scenario(client, token_dispatcher, token_shipper, token_driver, users, db_session, "撤销四落点")
    rid = int(receipt["id"])

    db_session.expire_all()
    assert db_session.get(Order, oid).paid is True, "前提不成立：收款没把订单标成已收"
    after_receipt = _landing_points(client, h)
    flows = _flows(db_session, rid)
    assert flows, "前提不成立：这笔收款没有写资金流水"
    assert [str(f.amount) for f in flows] == ["100.00"], [str(f.amount) for f in flows]

    _dump("① 收款后（撤销前）", client, h, db_session, rid, oid)

    # ——— 撤销：四个落点一起回到收款前 ———
    got = client.delete(f"{RECEIPTS}/{rid}", headers=h)
    assert got.status_code == 204, f"撤销收款没有这条路：{got.status_code} {got.text[:200]}"

    db_session.expire_all()
    assert db_session.get(Order, oid).paid is False, "撤销之后订单还是「已收」——这张单会带着一笔不存在的钱继续往下走"
    assert db_session.get(ShipperReceipt, rid).is_deleted is True, "撤销没有落在收款单上（软删标记）"
    for f in _flows(db_session, rid):
        assert f.is_deleted is True, f"流水 {f.id} 没有被软删——「收支」里还留着这笔钱"
    _dump("② 撤销后（回到收款前）", client, h, db_session, rid, oid)
    before_receipt = _landing_points(client, h)
    assert before_receipt["collected"] == after_receipt["collected"] - Decimal("100.00"), before_receipt
    assert before_receipt["arrears_total"] == after_receipt["arrears_total"] + Decimal("100.00"), before_receipt
    assert before_receipt["income"] == after_receipt["income"] - Decimal("100.00"), before_receipt
    assert before_receipt["balance"] == after_receipt["balance"] + Decimal("100.00"), before_receipt

    # ——— 恢复：四个落点一起回来 ———
    back = client.post(f"{RECEIPTS}/{rid}/restore", headers=h)
    assert back.status_code == 200, f"恢复收款没有这条路：{back.status_code} {back.text[:200]}"

    db_session.expire_all()
    assert db_session.get(Order, oid).paid is True, "恢复之后订单没有回到「已收」"
    assert db_session.get(ShipperReceipt, rid).is_deleted is False, "恢复没有清掉收款单上的软删标记"
    for f in _flows(db_session, rid):
        assert f.is_deleted is False, f"流水 {f.id} 没有被放回来"
    _dump("③ 再恢复后（回到收款时）", client, h, db_session, rid, oid)
    assert _landing_points(client, h) == after_receipt, "恢复之后四个落点没有回到收款时那一组数"


# --------------------------------------------------------------- 只回滚一次
def test_second_cancel_and_second_restore_are_rejected(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    h, _oid, _cid, receipt = _scenario(client, token_dispatcher, token_shipper, token_driver, users, db_session, "撤销幂等")
    rid = int(receipt["id"])

    assert client.delete(f"{RECEIPTS}/{rid}", headers=h).status_code == 204
    after_cancel = _landing_points(client, h)

    again = client.delete(f"{RECEIPTS}/{rid}", headers=h)
    assert again.status_code == 400, f"第二次撤销没有被明确拒绝：{again.status_code} {again.text[:200]}"
    assert "已经撤销" in again.text, again.text
    assert _landing_points(client, h) == after_cancel, "第二次撤销把账上的数又改了一遍"

    assert client.post(f"{RECEIPTS}/{rid}/restore", headers=h).status_code == 200
    after_restore = _landing_points(client, h)

    twice = client.post(f"{RECEIPTS}/{rid}/restore", headers=h)
    assert twice.status_code == 400, f"第二次恢复没有被明确拒绝：{twice.status_code} {twice.text[:200]}"
    assert "没有被撤销" in twice.text, twice.text
    assert _landing_points(client, h) == after_restore, "第二次恢复把账上的数又改了一遍"


# --------------------------------------------------------------- 软删、不是物删
def test_cancel_never_physically_deletes_anything(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    h, oid, _cid, receipt = _scenario(client, token_dispatcher, token_shipper, token_driver, users, db_session, "软删留行")
    rid = int(receipt["id"])
    flow_ids = sorted(f.id for f in _flows(db_session, rid))
    assert flow_ids, "前提不成立：这笔收款没有写资金流水"
    receipt_rows = db_session.query(ShipperReceipt).count()
    flow_rows = db_session.query(CashFlow).count()

    assert client.delete(f"{RECEIPTS}/{rid}", headers=h).status_code == 204
    db_session.expire_all()

    assert db_session.get(ShipperReceipt, rid) is not None, "撤销把收款单整行删掉了（用户定的规矩是软删）"
    assert db_session.query(ShipperReceipt).count() == receipt_rows
    assert db_session.query(CashFlow).count() == flow_rows
    assert sorted(f.id for f in _flows(db_session, rid)) == flow_ids, "撤销把资金流水删掉了（那笔钱的历史没了）"
    assert db_session.get(Order, oid) is not None


# --------------------------------------------------------------- 列表与回收站
def test_receipt_list_hides_cancelled_until_include_deleted(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    h, _oid, customer_id, receipt = _scenario(client, token_dispatcher, token_shipper, token_driver, users, db_session, "回收站")
    rid = int(receipt["id"])
    assert rid in [x["id"] for x in client.get(RECEIPTS, headers=h).json()]

    assert client.delete(f"{RECEIPTS}/{rid}", headers=h).status_code == 204

    live = client.get(RECEIPTS, headers=h).json()
    assert rid not in [x["id"] for x in live], "已撤销的收款还留在收款记录里（用户会以为这笔钱还在）"
    binned = client.get(f"{RECEIPTS}?include_deleted=true", headers=h).json()
    row = next((x for x in binned if x["id"] == rid), None)
    assert row is not None, "回收站里找不到这笔已撤销的收款 —— 恢复入口就没有落点"
    assert row["is_deleted"] is True and row["deleted_at"], row
    assert row["customer_id"] == customer_id
    assert binned and any(x["id"] in [x["id"] for x in live] for x in binned)


# --------------------------------------------------------------- 留痕
def test_cancel_and_restore_each_leave_one_audit_log(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    h, _oid, _cid, receipt = _scenario(client, token_dispatcher, token_shipper, token_driver, users, db_session, "撤销留痕")
    rid = int(receipt["id"])
    # ⚠️ 同一个进程里几个用例共用同一个测试库，所以只能判"这一次多出来几条"，
    #    不能判"全库只有一条"（那会让第二个跑到的用例假红）。
    before = {x.id for x in _logs(db_session, "RECEIPT_CANCEL")}

    assert client.delete(f"{RECEIPTS}/{rid}", headers=h).status_code == 204
    db_session.expire_all()
    cancels = [x for x in _logs(db_session, "RECEIPT_CANCEL") if x.id not in before]
    assert len(cancels) == 1, f"撤销没有恰好留一条痕：这一次多了 {len(cancels)} 条"
    assert f'"receipt_id": {rid}' in (cancels[0].change_content or ""), cancels[0].change_content
    assert cancels[0].operator_id is not None, "撤销日志没有记下是谁干的"

    before2 = {x.id for x in _logs(db_session, "RECEIPT_RESTORE")}
    assert client.post(f"{RECEIPTS}/{rid}/restore", headers=h).status_code == 200
    db_session.expire_all()
    restores = [x for x in _logs(db_session, "RECEIPT_RESTORE") if x.id not in before2]
    assert len(restores) == 1, f"恢复没有恰好留一条痕：这一次多了 {len(restores)} 条"
    assert f'"receipt_id": {rid}' in (restores[0].change_content or ""), restores[0].change_content


# --------------------------------------------------------------- 恢复的三道门
def test_restore_refuses_when_the_order_was_collected_again(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """撤销之后这一单又被收了一次款 —— 这时把第一笔恢复回来，同一笔钱会被算两遍。"""
    h, oid, customer_id, receipt = _scenario(client, token_dispatcher, token_shipper, token_driver, users, db_session, "恢复门")
    rid = int(receipt["id"])
    assert client.delete(f"{RECEIPTS}/{rid}", headers=h).status_code == 204
    one = _landing_points(client, h)

    second = _receipt(client, h, customer_id, "100.00", [oid])
    assert second.status_code in (200, 201), second.text
    two = _landing_points(client, h)
    assert two["collected"] == one["collected"] + Decimal("100.00"), two

    blocked = client.post(f"{RECEIPTS}/{rid}/restore", headers=h)
    assert blocked.status_code == 400, f"同一笔钱被恢复成两遍：{blocked.status_code} {blocked.text[:200]}"
    assert str(oid) in blocked.text, f"拒绝时没有点名是哪一张单：{blocked.text}"
    assert _landing_points(client, h) == two, "被拒绝的恢复却改了账"


# --------------------------------------------------------------- 权限与不存在
def test_cancel_needs_dispatcher_and_a_real_receipt(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    h, _oid, _cid, receipt = _scenario(client, token_dispatcher, token_shipper, token_driver, users, db_session, "撤销权限")
    rid = int(receipt["id"])
    before_cancel = len(_logs(db_session, "RECEIPT_CANCEL"))
    before_restore = len(_logs(db_session, "RECEIPT_RESTORE"))

    assert client.delete(f"{RECEIPTS}/{rid}", headers=auth_headers(token_shipper)).status_code == 403
    assert client.delete(f"{RECEIPTS}/{rid}", headers=auth_headers(token_driver)).status_code == 403
    assert client.post(f"{RECEIPTS}/{rid}/restore", headers=auth_headers(token_shipper)).status_code == 403

    assert client.delete(f"{RECEIPTS}/999999", headers=h).status_code == 404
    assert client.post(f"{RECEIPTS}/999999/restore", headers=h).status_code == 404

    # 权限被拒 / 点不存在的单那几次不许留下任何痕迹（同一个进程里别的用例写过的不算）
    assert len(_logs(db_session, "RECEIPT_CANCEL")) == before_cancel, "被拒绝的撤销却留了痕"
    assert len(_logs(db_session, "RECEIPT_RESTORE")) == before_restore, "被拒绝的恢复却留了痕"
