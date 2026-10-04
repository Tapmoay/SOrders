"""采购单（FEAT-0013）：一次进货同时写**库存、成本价、供应商应付**。

## 用户拍板的四条口径（docs/changes/FEAT-0013.md）
① 新增「采购单」页（不是给现有入库页加两格）；② 应付**自动**生成一张；
③ **允许改单**（改数量/单价时自动补写差额）；④ 要做「成本覆盖」看板。

## 这个文件守七件事（每一条都是「不报错但会错」的形状）
1. **一次采购 = 一个事实**：建单之后库存、`products.cost_price`、应付单三样必须同时对；
2. **一行明细绑定一条入库流水**：改单是**改写**那条流水（`change` / `unit_cost`），
   ⛔ 不是再记一笔冲销 —— `cost_basis._weighted_avg` 的分母只认 `change > 0 AND unit_cost IS NOT NULL`，
   冲销行进不了分母，再记一笔会让两批货的价一起留在均价里（毛利算错而不报错）；
3. **恒等式 `Σ(inventory_movements.change) == products.stock`** 在任何一步之后都成立；
4. **整单替换的撤行语义**：请求里没给的行 = 撤掉（行留在单上、`is_void`、金额计 0、库存退回）；
5. **应付金额只有一处写入点**（`_sync_payable`），且 ① 不许改到小于已付 ② 付过钱不许换供应商
   ③ 在供应商页改/删它必须被拦下（同一笔欠款两处可改，必然对不上）；
6. **整张单的撤销/恢复是软删**：库存退回、应付进回收站，恢复时原样回来；
7. **每一步都留痕**（四个 `PURCHASE_ORDER_*` 动作码）。
"""
from __future__ import annotations

import json
import random
from decimal import Decimal

from sqlalchemy import select

from app.models import InventoryMovement, OperationLog, Product, PurchaseOrder, SupplierPayable
from tests.conftest import auth_headers

ORD = "/api/v1/purchase-orders"
SUP = "/api/v1/suppliers"
PAY = "/api/v1/supplier-payables"
PAYMENT = "/api/v1/supplier-payments"
INV = "/api/v1/inventory/movements"


def _uniq(prefix: str) -> str:
    return f"{prefix}-{random.randint(1000, 9999)}"


def _mk_product(client, h, cost: str = "0") -> dict:
    r = client.post(
        "/api/v1/products",
        json={
            "name": _uniq("采购单商品"),
            "default_unit_price": "20",
            "cost_price": cost,
            "unit": "件",
            "stock": 0,
            "category": _uniq("采购单分类"),
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _product(client, h, pid: int) -> dict:
    r = client.get(f"/api/v1/products/{pid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _new_supplier(client, h, name: str) -> dict:
    r = client.post(SUP, json={"name": name, "contact_name": "老陈", "phone": "13800001111"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _supplier(client, h, sid: int) -> dict:
    r = client.get(f"{SUP}/{sid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _create(client, h, sid: int, items: list[dict], *, doc_date: str = "2026-09-10", remark: str = "") -> dict:
    r = client.post(
        ORD,
        json={"supplier_id": sid, "doc_date": doc_date, "remark": remark, "items": items},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _patch(client, h, oid: int, body: dict) -> dict:
    r = client.patch(f"{ORD}/{oid}", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _order(client, h, oid: int) -> dict:
    r = client.get(f"{ORD}/{oid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _payables_of(client, h, sid: int) -> list[dict]:
    r = client.get(PAY, headers=h)
    assert r.status_code == 200, r.text
    return [x for x in r.json() if x["supplier_id"] == sid]


def _pay(client, h, payable_id: int, amount: str) -> dict:
    r = client.post(
        f"{PAY}/{payable_id}/payments",
        json={"amount": amount, "pay_date": "2026-09-20", "channel": "transfer"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _movement(db, mid: int) -> InventoryMovement:
    db.expire_all()
    row = db.get(InventoryMovement, mid)
    assert row is not None, f"流水 #{mid} 不见了"
    return row


def _stock(db, pid: int) -> int:
    db.expire_all()
    row = db.get(Product, pid)
    assert row is not None
    return int(row.stock or 0)


def _cost_price(db, pid: int) -> Decimal | None:
    db.expire_all()
    row = db.get(Product, pid)
    assert row is not None
    return Decimal(str(row.cost_price)) if row.cost_price is not None else None


def _sum_moves(db, pid: int) -> int:
    """恒等式左边：这个商品所有入库/出库流水的净和（⛔ 不筛来源，全部都要算）。"""
    db.expire_all()
    rows = db.scalars(select(InventoryMovement).where(InventoryMovement.product_id == pid)).all()
    return sum(int(r.change or 0) for r in rows)


def _assert_identity(db, pid: int) -> None:
    """恒等式：Σ(流水的 change) == 商品的 stock。

    ⚠️ 改写流水（而不是记冲销）正是为了保住它：再记一笔冲销，库存对了、流水和货也对不上，
       但谁也看不出来 —— 只能靠这一条断言。
    """
    assert _sum_moves(db, pid) == _stock(db, pid), f"商品 #{pid} 的流水与库存对不上"


def _logs(db, action: str) -> list[dict]:
    db.expire_all()
    rows = db.scalars(select(OperationLog).where(OperationLog.action == action)).all()
    return [json.loads(r.change_content or "{}") for r in rows]


# ---------------- 建单：三件事一次写完 ----------------
def test_建一张采购单_库存成本价应付一次写完(client, token_dispatcher, db_session):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("采购供应商"))
    p = _mk_product(client, h)
    o = _create(client, h, s["id"], [{"product_id": p["id"], "quantity": 10, "unit_cost": "12.50"}],
                doc_date="2026-09-10", remark="9 月第一批")
    # 单头：合计与行数都是服务端算的（字符串两位小数）
    assert o["total"] == "125.00" and o["item_count"] == 1 and o["remark"] == "9 月第一批"
    assert o["supplier_name"] == s["name"] and o["payable_id"] is not None
    assert o["payable_unpaid"] == "125.00" and o["payable_paid"] == "0.00"
    line = o["items"][0]
    assert (line["quantity"], line["unit_cost"], line["amount"]) == (10, "12.50", "125.00")
    assert line["is_void"] is False and line["movement_id"] is not None
    # ① 库存
    assert _product(client, h, p["id"])["stock"] == 10
    # ② 成本价（商品卡上的「最近一次进货价」）
    assert Decimal(_product(client, h, p["id"])["cost_price"]) == Decimal("12.50")
    # ③ 应付单：金额、日期、分类、事由全都对齐这张单
    payable = db_session.get(SupplierPayable, o["payable_id"])
    assert payable is not None
    assert Decimal(payable.amount) == Decimal("125.00")
    assert payable.doc_date.isoformat() == "2026-09-10"
    assert payable.category == "货款" and str(payable.title) == f"采购单 #{o['id']}"
    assert _supplier(client, h, s["id"])["unpaid_total"] == "125.00"
    _assert_identity(db_session, p["id"])


def test_一条明细就是一条入库流水_价格记在流水上(client, token_dispatcher, db_session):
    """进货价的一手数据在 `inventory_movements.unit_cost` —— 加权平均进货价读的就是它。"""
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("流水供应商"))
    p = _mk_product(client, h)
    o = _create(client, h, s["id"], [{"product_id": p["id"], "quantity": 7, "unit_cost": "3.25"}])
    mv = _movement(db_session, o["items"][0]["movement_id"])
    assert int(mv.change) == 7 and Decimal(mv.unit_cost) == Decimal("3.25")
    assert mv.source == "PURCHASE" and mv.status == "COMMITTED"
    assert f"采购单 #{o['id']}" in (mv.note or "")
    assert mv.order_id is None
    _assert_identity(db_session, p["id"])


# ---------------- 改单：改写那条流水，不是再记一笔 ----------------
def test_改数量与单价_改写那条流水而不是再记一笔(client, token_dispatcher, db_session):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("改单供应商"))
    p = _mk_product(client, h)
    o = _create(client, h, s["id"], [{"product_id": p["id"], "quantity": 10, "unit_cost": "12.50"}])
    line = o["items"][0]
    o2 = _patch(client, h, o["id"], {"items": [
        {"id": line["id"], "product_id": p["id"], "quantity": 4, "unit_cost": "10.00"},
    ]})
    assert o2["total"] == "40.00" and o2["payable_unpaid"] == "40.00"
    # 流水还是那一条（id 不变），只是被改写了
    mv = _movement(db_session, line["movement_id"])
    assert int(mv.change) == 4 and Decimal(mv.unit_cost) == Decimal("10.00")
    assert mv.status == "COMMITTED"
    rows = db_session.scalars(
        select(InventoryMovement).where(InventoryMovement.product_id == p["id"])
    ).all()
    assert len(rows) == 1, "改单又记了一笔流水：均价会被两批货污染"
    assert _stock(db_session, p["id"]) == 4
    assert _cost_price(db_session, p["id"]) == Decimal("10.00")
    _assert_identity(db_session, p["id"])


def test_改单可以新加一行_也会写一条新流水(client, token_dispatcher, db_session):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("加行供应商"))
    a = _mk_product(client, h)
    b = _mk_product(client, h)
    o = _create(client, h, s["id"], [{"product_id": a["id"], "quantity": 2, "unit_cost": "5.00"}])
    o2 = _patch(client, h, o["id"], {"items": [
        {"id": o["items"][0]["id"], "product_id": a["id"], "quantity": 2, "unit_cost": "5.00"},
        {"product_id": b["id"], "quantity": 3, "unit_cost": "4.00"},
    ]})
    assert o2["item_count"] == 2 and o2["total"] == "22.00"
    assert _stock(db_session, b["id"]) == 3
    _assert_identity(db_session, a["id"])
    _assert_identity(db_session, b["id"])


def test_数量改小要减库存_不够就拒绝并且一个字都不改(client, token_dispatcher, db_session):
    """10 件进了 8 件出去之后再改成 5 件 = 要减 5 件，库里只剩 2 件 ⇒ 如实拒绝。

    ⚠️ 拒绝之后**整单一个字都不能变**（库存 / 流水 / 应付都是一个事务里的）。
    """
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("库存不足供应商"))
    p = _mk_product(client, h)
    o = _create(client, h, s["id"], [{"product_id": p["id"], "quantity": 10, "unit_cost": "12.50"}])
    line = o["items"][0]
    r = client.post(INV, json={"product_id": p["id"], "change": -8, "note": "卖出去了"}, headers=h)
    assert r.status_code == 201, r.text
    assert _stock(db_session, p["id"]) == 2
    bad = client.patch(f"{ORD}/{o['id']}", json={"items": [
        {"id": line["id"], "product_id": p["id"], "quantity": 5, "unit_cost": "12.50"},
    ]}, headers=h)
    assert bad.status_code == 400 and "库存不足" in bad.json()["detail"], bad.text
    assert _stock(db_session, p["id"]) == 2
    assert int(_movement(db_session, line["movement_id"]).change) == 10
    assert _order(client, h, o["id"])["total"] == "125.00"
    assert _order(client, h, o["id"])["payable_unpaid"] == "125.00"
    _assert_identity(db_session, p["id"])


def test_请求里没给的行算撤行_库存退回去_流水留痕但不算数(client, token_dispatcher, db_session):
    """整单替换的语义：撤掉的行**还在单子上**（`is_void`），金额计 0，一键可查。

    ⚠️ 成本价⛔ 不抹成 0：0 会被报表读成「成本是 0」= 毛利虚高，比留着旧价错得更贵。
    """
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("撤行供应商"))
    a = _mk_product(client, h)
    b = _mk_product(client, h)
    o = _create(client, h, s["id"], [
        {"product_id": a["id"], "quantity": 10, "unit_cost": "12.50"},
        {"product_id": b["id"], "quantity": 5, "unit_cost": "4.00"},
    ])
    assert o["total"] == "145.00"
    keep, drop = o["items"][0], o["items"][1]
    o2 = _patch(client, h, o["id"], {"items": [
        {"id": keep["id"], "product_id": a["id"], "quantity": 10, "unit_cost": "12.50"},
    ]})
    assert o2["total"] == "125.00" and o2["item_count"] == 1
    voided = next(x for x in o2["items"] if x["id"] == drop["id"])
    assert voided["is_void"] is True and voided["amount"] == "0.00"
    assert _stock(db_session, b["id"]) == 0
    mv = _movement(db_session, drop["movement_id"])
    assert int(mv.change) == 0 and mv.unit_cost is None and mv.status == "VOID"
    assert _cost_price(db_session, b["id"]) == Decimal("4.00"), "撤行把成本价抹成 0 了"
    assert _order(client, h, o["id"])["payable_unpaid"] == "125.00"
    _assert_identity(db_session, a["id"])
    _assert_identity(db_session, b["id"])


def test_只改单头_明细一行都不动(client, token_dispatcher, db_session):
    """`items` 这个键干脆不带 = 只改单头。⛔ 与「传空数组」不是一回事。"""
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("改单头供应商"))
    p = _mk_product(client, h)
    o = _create(client, h, s["id"], [{"product_id": p["id"], "quantity": 6, "unit_cost": "2.00"}])
    o2 = _patch(client, h, o["id"], {"remark": "改成送货上门", "doc_date": "2026-09-12"})
    assert o2["remark"] == "改成送货上门" and o2["doc_date"] == "2026-09-12"
    assert o2["total"] == "12.00" and o2["item_count"] == 1
    assert _stock(db_session, p["id"]) == 6
    payable = db_session.get(SupplierPayable, o["payable_id"])
    assert payable.doc_date.isoformat() == "2026-09-12"
    _assert_identity(db_session, p["id"])


# ---------------- 校验（中文 400，不是 422 的结构体） ----------------
def test_同一张单里一个商品只能有一行(client, token_dispatcher):
    """两批价钱不一样就开两张单 —— 同一行商品两个价，均价算谁的都说不清。"""
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("重复行供应商"))
    p = _mk_product(client, h)
    r = client.post(ORD, json={"supplier_id": s["id"], "doc_date": "2026-09-10", "items": [
        {"product_id": p["id"], "quantity": 1, "unit_cost": "1.00"},
        {"product_id": p["id"], "quantity": 2, "unit_cost": "2.00"},
    ]}, headers=h)
    assert r.status_code == 400 and "同一个商品" in r.json()["detail"], r.text


def test_数量为零_进货价为零或超过四位小数_都要拦下来(client, token_dispatcher):
    """0 元的进货价会让 `cost_basis` 的「算得出成本」（cost > 0）失效 —— 那行收入永远进不了毛利。"""
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("校验供应商"))
    p = _mk_product(client, h)

    def _bad(qty: int, cost: str) -> str:
        r = client.post(ORD, json={"supplier_id": s["id"], "doc_date": "2026-09-10", "items": [
            {"product_id": p["id"], "quantity": qty, "unit_cost": cost},
        ]}, headers=h)
        assert r.status_code == 400, r.text
        return r.json()["detail"]

    assert "数量要大于 0" in _bad(0, "1.00")
    assert "进货价要大于 0" in _bad(1, "0")
    assert "最多 4 位小数" in _bad(1, "1.23456")
    # 校验失败不该留下任何痕迹
    assert _product(client, h, p["id"])["stock"] == 0


# ---------------- 应付：唯一写入点 + 供应商页的保护 ----------------
def test_已经付过钱的单_删不掉_也改不到小于已付(client, token_dispatcher, db_session):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("已付供应商"))
    p = _mk_product(client, h)
    o = _create(client, h, s["id"], [{"product_id": p["id"], "quantity": 10, "unit_cost": "10.00"}])
    line = o["items"][0]
    _pay(client, h, o["payable_id"], "60.00")
    assert _order(client, h, o["id"])["payable_unpaid"] == "40.00"

    # ① 整张单删不掉（那 60 元是付给这张单的货款的）
    d = client.delete(f"{ORD}/{o['id']}", headers=h)
    assert d.status_code == 400 and "没撤销的付款" in d.json()["detail"], d.text
    assert _stock(db_session, p["id"]) == 10, "删单失败却把库存退了"
    assert int(_movement(db_session, line["movement_id"]).change) == 10

    # ② 改到比已付还少也不行
    bad = client.patch(f"{ORD}/{o['id']}", json={"items": [
        {"id": line["id"], "product_id": p["id"], "quantity": 5, "unit_cost": "10.00"},
    ]}, headers=h)
    assert bad.status_code == 400 and "改完的合计" in bad.json()["detail"], bad.text
    assert _order(client, h, o["id"])["total"] == "100.00"
    assert _stock(db_session, p["id"]) == 10

    # ③ 改到不小于已付就可以（这里 80.00 > 60.00）
    ok = _patch(client, h, o["id"], {"items": [
        {"id": line["id"], "product_id": p["id"], "quantity": 8, "unit_cost": "10.00"},
    ]})
    assert ok["total"] == "80.00" and ok["payable_unpaid"] == "20.00"
    _assert_identity(db_session, p["id"])


def test_付过钱的单不许换供应商(client, token_dispatcher):
    """那些付款是付给原供应商的 —— 换个名字，欠款就挂到别人头上了。"""
    h = auth_headers(token_dispatcher)
    first = _new_supplier(client, h, _uniq("原供应商"))
    other = _new_supplier(client, h, _uniq("别家供应商"))
    p = _mk_product(client, h)
    o = _create(client, h, first["id"], [{"product_id": p["id"], "quantity": 5, "unit_cost": "10.00"}])
    _pay(client, h, o["payable_id"], "50.00")
    r = client.patch(f"{ORD}/{o['id']}", json={"supplier_id": other["id"]}, headers=h)
    assert r.status_code == 400 and "不能换供应商" in r.json()["detail"], r.text


def test_供应商页改不动也删不掉采购单生成的应付(client, token_dispatcher):
    """那笔欠款的金额 = 采购单明细合计；两处都能改，必然对不上（改完还会被下一次改单覆盖）。"""
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("保护供应商"))
    p = _mk_product(client, h)
    o = _create(client, h, s["id"], [{"product_id": p["id"], "quantity": 2, "unit_cost": "30.00"}])
    r = client.patch(f"{PAY}/{o['payable_id']}", json={"amount": "10.00"}, headers=h)
    assert r.status_code == 400 and f"采购单 #{o['id']}" in r.json()["detail"], r.text
    d = client.delete(f"{PAY}/{o['payable_id']}", headers=h)
    assert d.status_code == 400 and "采购单" in d.json()["detail"], d.text
    assert _payables_of(client, h, s["id"])[0]["amount"] == "60.00"


# ---------------- 整张单的撤销 / 恢复（软删） ----------------
def test_撤销整张单_库存退回去_应付进回收站_能原样恢复(client, token_dispatcher, db_session):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("撤销供应商"))
    p = _mk_product(client, h)
    o = _create(client, h, s["id"], [{"product_id": p["id"], "quantity": 4, "unit_cost": "7.50"}])
    line = o["items"][0]

    d = client.delete(f"{ORD}/{o['id']}", headers=h)
    assert d.status_code == 204, d.text
    assert _stock(db_session, p["id"]) == 0
    mv = _movement(db_session, line["movement_id"])
    assert int(mv.change) == 0 and mv.unit_cost is None and mv.status == "VOID"
    assert _supplier(client, h, s["id"])["unpaid_total"] == "0.00"
    # 列表默认看不见，带 include_deleted 看得见（软删不是消失）
    assert all(x["id"] != o["id"] for x in client.get(ORD, headers=h).json())
    gone = client.get(ORD, headers=h, params={"include_deleted": True}).json()
    assert next(x for x in gone if x["id"] == o["id"])["is_deleted"] is True
    assert _order(client, h, o["id"])["is_deleted"] is True
    _assert_identity(db_session, p["id"])

    back = client.post(f"{ORD}/{o['id']}/restore", headers=h)
    assert back.status_code == 200, back.text
    assert back.json()["is_deleted"] is False and back.json()["total"] == "30.00"
    assert _stock(db_session, p["id"]) == 4
    mv2 = _movement(db_session, line["movement_id"])
    assert int(mv2.change) == 4 and Decimal(mv2.unit_cost) == Decimal("7.50")
    assert mv2.status == "COMMITTED"
    assert _supplier(client, h, s["id"])["unpaid_total"] == "30.00"
    _assert_identity(db_session, p["id"])


def test_货已经卖掉时_恢复不回来要如实报库存不足(client, token_dispatcher, db_session):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("恢复不足供应商"))
    p = _mk_product(client, h)
    o = _create(client, h, s["id"], [{"product_id": p["id"], "quantity": 5, "unit_cost": "6.00"}])
    assert client.delete(f"{ORD}/{o['id']}", headers=h).status_code == 204
    # 撤单之后这 5 件又被手工入进来 1 件、卖掉 1 件：恢复时库存够（1 + 5 >= 0 不成立？）
    r = client.post(INV, json={"product_id": p["id"], "change": 1, "note": "别的渠道进货"}, headers=h)
    assert r.status_code == 201, r.text
    back = client.post(f"{ORD}/{o['id']}/restore", headers=h)
    assert back.status_code == 200, back.text
    assert _stock(db_session, p["id"]) == 6
    _assert_identity(db_session, p["id"])


# ---------------- 留痕 / 权限 / 列表 ----------------
def test_每一步都留痕(client, token_dispatcher, db_session):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, _uniq("留痕供应商"))
    p = _mk_product(client, h)
    o = _create(client, h, s["id"], [{"product_id": p["id"], "quantity": 3, "unit_cost": "9.00"}])
    _patch(client, h, o["id"], {"remark": "改个备注"})
    client.delete(f"{ORD}/{o['id']}", headers=h)
    client.post(f"{ORD}/{o['id']}/restore", headers=h)

    created = [x for x in _logs(db_session, "PURCHASE_ORDER_CREATE") if x.get("id") == o["id"]]
    assert created and created[-1]["total"] == "27.00" and len(created[-1]["items"]) == 1
    updated = [x for x in _logs(db_session, "PURCHASE_ORDER_UPDATE") if x.get("after", {}).get("id") == o["id"]]
    assert updated and updated[-1]["before"]["remark"] != updated[-1]["after"]["remark"]
    assert [x for x in _logs(db_session, "PURCHASE_ORDER_DELETE") if x.get("after", {}).get("id") == o["id"]]
    assert [x for x in _logs(db_session, "PURCHASE_ORDER_RESTORE") if x.get("id") == o["id"]]


def test_货主和司机都进不来(client, token_shipper, token_driver):
    for token in (token_shipper, token_driver):
        h = auth_headers(token)
        assert client.get(ORD, headers=h).status_code == 403
        assert client.post(ORD, json={"supplier_id": 1, "doc_date": "2026-09-10", "items": []}, headers=h).status_code == 403


def test_列表按住供应商与单据日期筛(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    s1 = _new_supplier(client, h, _uniq("列表甲"))
    s2 = _new_supplier(client, h, _uniq("列表乙"))
    p = _mk_product(client, h)
    a = _create(client, h, s1["id"], [{"product_id": p["id"], "quantity": 1, "unit_cost": "1.00"}], doc_date="2026-08-01")
    b = _create(client, h, s2["id"], [{"product_id": p["id"], "quantity": 2, "unit_cost": "2.00"}], doc_date="2026-09-15")
    only1 = client.get(ORD, headers=h, params={"supplier_id": s1["id"]}).json()
    assert [x["id"] for x in only1] == [a["id"]]
    win = client.get(ORD, headers=h, params={"date_from": "2026-09-01", "date_to": "2026-09-30"}).json()
    assert b["id"] in [x["id"] for x in win] and a["id"] not in [x["id"] for x in win]
    bad = client.get(ORD, headers=h, params={"date_from": "2026-09-30", "date_to": "2026-09-01"})
    assert bad.status_code == 400


# ---------------- 成本覆盖报表（第 4 条口径） ----------------
def test_成本覆盖报表_没记过进货价的商品列在里面_记了就出列(client, token_dispatcher):
    """这张表的用途：告诉用户「还有多少收入算不出成本」+「哪些商品从来没记过进货价」。

    ⚠️ 清单是**商品维度**（有没有带价入库流水），不是「这窗口那笔收入的来源」——
       它只是找补录入口的线索，页面文案必须写清这一条。
    """
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h)
    params = {"mode": "month", "date": "2026-09-30"}
    before = client.get("/api/v1/reports/cost-coverage", headers=h, params=params)
    assert before.status_code == 200, before.text
    data = before.json()
    assert {"revenue_total", "revenue_covered", "revenue_uncovered", "total_lines",
            "covered_lines", "missing_purchase_price_count", "missing_purchase_price",
            "notes"} <= set(data)
    assert data["missing_purchase_price_count"] == len(data["missing_purchase_price"])
    assert p["id"] in [x["product_id"] for x in data["missing_purchase_price"]]
    assert all("*" not in n for n in data["notes"])
    assert Decimal(str(data["revenue_uncovered"])) == (
        Decimal(str(data["revenue_total"])) - Decimal(str(data["revenue_covered"]))
    )

    s = _new_supplier(client, h, _uniq("覆盖供应商"))
    _create(client, h, s["id"], [{"product_id": p["id"], "quantity": 5, "unit_cost": "8.00"}])
    after = client.get("/api/v1/reports/cost-coverage", headers=h, params=params).json()
    assert p["id"] not in [x["product_id"] for x in after["missing_purchase_price"]]

