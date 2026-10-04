"""发票台账与税账（FEAT-0014）：登记 / 开具 / 作废 / 回收站 + 进销项税汇。

## 用户拍板的四条口径（docs/changes/FEAT-0014.md）
① 发票台账一张表管两边（销项 / 进项）：进项票必须挂采购单（不然答不出「这批货有没有票」），
   销项票必须写客户；
② 「税」不许编：税率与税额同生同灭（不填税率 = 未税票，单独计数、⛔ 不进税汇），
   ⛔ 不许拿默认税率替老板算一个数出来；
③ 利润表把两份税分成两行：**税金及附加**（已经花掉的税，从期间费用里搬出来单列、⛔ 不双扣）
   与**应交增值税**（销项 − 进项，代收代付的价外税、⛔ 不进营业利润）；
④ 挂着还算数的进项票的采购单**删不掉**（⛔ 不连票一起删、也不替它作废 —— 那两种做法都会让
   进项税额在没人知道的情况下变掉）。

## 这个文件守八件事（每一条都是「不报错但会错」的形状）
1. **税额只有一个算法**（`tax_service.tax_of_amount`）：票面只给「价税合计」，税额由后端算；
   客户端自己算一遍再传上来，四舍五入的差就会漏进税汇；
2. **票必须挂在真实存在的单据上**：进项票挂采购单（供应商还要与票的供应商同一家）、销项票写客户，
   ⛔ 不许「先登记一张票，货以后再说」—— 那样税汇上多出一笔无出处的进项；
3. **没填税率的票不进税汇**，但单独计数（`untaxed_count`）——「还有票没税率」要一眼看得出；
4. **两种「不算数」都要退出税汇，恢复后原样回来**：作废（`VOIDED`）与进回收站（`is_deleted`）；
   作废 ≠ 删掉：明细里还看得见这张票，只是「不算数」；
5. **票号在同一方向内唯一**：撞号如实 409，⛔ 不悄悄改号；恢复时号被占了也要 409（不是自动改名）；
6. **已开具 / 已作废的票改不动**（要改就作废重开一张）—— 不然「开出去的那张票」与库里的对不上；
7. **采购单删单闸**：它还挂着没作废的进项票就拦下，一个字节都不改（库存 / 流水 / 应付都不许动）；
8. **每一步都留痕**（六个 `TAX_INVOICE_*` 动作码），货主与司机一个口子都进不来。
"""
from __future__ import annotations

import json
import random
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import InventoryMovement, OperationLog, Product
from tests.conftest import auth_headers

INV = "/api/v1/invoices"
ORD = "/api/v1/purchase-orders"
SUP = "/api/v1/suppliers"
CUS = "/api/v1/customers"
EXP = "/api/v1/expenses"
TAX = "/api/v1/reports/tax-summary"
PROFIT = "/api/v1/reports/profit"

#: 六个动作码：谁登记的、谁把票号改了、谁开出去的、谁作废的、谁删进回收站的、谁恢复的。
TAX_ACTIONS = (
    "TAX_INVOICE_CREATE",
    "TAX_INVOICE_UPDATE",
    "TAX_INVOICE_ISSUE",
    "TAX_INVOICE_VOID",
    "TAX_INVOICE_DELETE",
    "TAX_INVOICE_RESTORE",
)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{random.randint(100000, 999999)}"


def _num(v) -> Decimal:
    """金额一律按字符串读：接口上的 Decimal 是两位小数的字符串（端点层格式化）。"""
    return Decimal(str(v))


def _mk_product(client, h, cost: str = "0") -> dict:
    r = client.post(
        "/api/v1/products",
        json={
            "name": _uniq("发票商品"),
            "default_unit_price": "20",
            "cost_price": cost,
            "unit": "件",
            "stock": 0,
            "category": _uniq("发票分类"),
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _new_supplier(client, h, name: str) -> dict:
    r = client.post(SUP, json={"name": name, "contact_name": "老陈", "phone": "13800001111"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _new_customer(client, h, name: str) -> dict:
    me = client.get("/api/v1/users/me", headers=h)
    assert me.status_code == 200, me.text
    r = client.post(CUS, json={"name": name, "user_id": me.json()["id"]}, headers=h)
    assert r.status_code in (200, 201), r.text  # 客户建档既有端点返回 200（不是 201）
    return r.json()


def _create_po(client, h, sid: int, items: list[dict], *, doc_date: str = "2026-09-10") -> dict:
    r = client.post(
        ORD,
        json={"supplier_id": sid, "doc_date": doc_date, "remark": "", "items": items},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _input_ready(client, h, *, qty: int = 10, cost: str = "12.50"):
    """建一套「可以登记进项票」的东西：一家供应商 + 一个商品 + 一张采购单。

    返回 (供应商, 商品, 采购单)。进项票必须挂采购单，所以每条用例都要先有这张单。
    """
    s = _new_supplier(client, h, _uniq("发票供应商"))
    p = _mk_product(client, h)
    o = _create_po(client, h, s["id"], [{"product_id": p["id"], "quantity": qty, "unit_cost": cost}])
    return s, p, o


def _try(client, h, body: dict):
    r = client.post(INV, json=body, headers=h)
    return r.status_code, (r.json() if r.content else {})


def _new(client, h, body: dict) -> dict:
    st, data = _try(client, h, body)
    assert st == 201, data
    return data


def _detail(client, h, iid: int) -> dict:
    r = client.get(f"{INV}/{iid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _act(client, h, iid: int, what: str, expect: int = 200):
    r = client.post(f"{INV}/{iid}/{what}", headers=h)
    assert r.status_code == expect, r.text
    return r.json() if r.content else {}


def _patch(client, h, iid: int, body: dict, expect: int = 200):
    r = client.patch(f"{INV}/{iid}", json=body, headers=h)
    assert r.status_code == expect, r.text
    return r.json() if r.content else {}


def _drop(client, h, iid: int) -> None:
    r = client.delete(f"{INV}/{iid}", headers=h)
    assert r.status_code == 204, r.text


def _tax(client, h, start: str, end: str) -> dict:
    r = client.get(TAX, headers=h, params={"mode": "month", "date": start, "date_from": start, "date_to": end})
    assert r.status_code == 200, r.text
    return r.json()


def _profit(client, h, day: str) -> dict:
    r = client.get(PROFIT, headers=h, params={"mode": "day", "date": day})
    assert r.status_code == 200, r.text
    return r.json()


def _d(now, before) -> Decimal:
    """窗口内新增的量。

    ⚠️ 一律用**差值**断言：同一个测试库里可能已经有别的用例留下的票（税汇是整段窗口的聚合，
       绝对数会被别人污染 —— 差值只认这一条用例自己造的那几张）。
    """
    return _num(now) - _num(before)


def _stock(db, pid: int) -> int:
    db.expire_all()
    row = db.get(Product, pid)
    assert row is not None
    return int(row.stock or 0)


def _assert_identity(db, pid: int) -> None:
    """恒等式：Σ(入库流水的 change) == 商品的 stock（采购单那边立的规矩，删单闸不许破坏它）。"""
    db.expire_all()
    rows = db.scalars(select(InventoryMovement).where(InventoryMovement.product_id == pid)).all()
    assert sum(int(r.change or 0) for r in rows) == _stock(db, pid), f"商品 #{pid} 的流水与库存对不上"


def _logs(db, action: str) -> list[dict]:
    db.expire_all()
    rows = db.scalars(select(OperationLog).where(OperationLog.action == action)).all()
    return [json.loads(r.change_content or "{}") for r in rows]


def _in_body(no: str, s: dict, o: dict, **kw) -> dict:
    """一张进项票的默认形状（用例只覆盖自己关心的那几个字段）。"""
    body = {
        "direction": "INPUT",
        "invoice_no": no,
        "invoice_date": "2026-09-12",
        "amount": "103.00",
        "tax_rate": "3.00",
        "supplier_id": s["id"],
        "purchase_order_ids": [o["id"]],
    }
    body.update(kw)
    return body


def _out_body(no: str, c: dict, **kw) -> dict:
    """一张销项票的默认形状。"""
    body = {
        "direction": "OUTPUT",
        "invoice_no": no,
        "invoice_date": "2026-09-12",
        "amount": "103.00",
        "tax_rate": "3.00",
        "customer_id": c["id"],
    }
    body.update(kw)
    return body


# ---------------- ① 登记：税额由后端按税率算 ----------------
@pytest.mark.dispatcher
@pytest.mark.fast
def test_登记一张进项票_税额由后端按税率算出来(client, token_dispatcher):
    """价税合计 103.00 含 3% 税 -> 净额 100.00、税额 3.00；状态是「已登记」。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    v = _new(client, h, _in_body(_uniq("IN"), s, o))

    assert v["direction"] == "INPUT"
    assert v["status"] == "REGISTERED"
    assert _num(v["tax_rate"]) == Decimal("3.00")
    assert _num(v["tax_amount"]) == Decimal("3.00"), v
    assert _num(v["amount"]) == Decimal("103.00")
    assert v["counts_in_tax"] is True
    assert v["purchase_order_ids"] == [o["id"]]
    assert v["supplier_name"] == s["name"]
    # 列表 / 详情共用一份形状（两处不一致时，界面与税账就会各说各话）
    d = _detail(client, h, v["id"])
    assert d["tax_amount"] == v["tax_amount"] and d["invoice_no"] == v["invoice_no"]


@pytest.mark.dispatcher
@pytest.mark.fast
def test_进项票不挂采购单_或者挂错供应商_都要拦下(client, token_dispatcher):
    """票必须挂在真实存在的进货单上：空挂、挂别人家的货、不写供应商，三条都 400 且一句解释。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    other = _new_supplier(client, h, _uniq("另一家供应商"))
    no = _uniq("IN")

    st, d = _try(client, h, {"direction": "INPUT", "invoice_no": no, "invoice_date": "2026-09-12",
                            "amount": "103.00", "tax_rate": "3.00", "supplier_id": s["id"]})
    assert st == 400 and "采购单" in d["detail"], d

    st, d = _try(client, h, _in_body(no, s, o, supplier_id=other["id"]))
    assert st == 400 and "不是同一家" in d["detail"], d

    st, d = _try(client, h, _in_body(no, s, o, supplier_id=None))
    assert st == 400 and "供应商" in d["detail"], d

    st, d = _try(client, h, _in_body(no, s, o, purchase_order_ids=[999999]))
    assert st == 400 and "不存在" in d["detail"], d

    r = client.get(INV, headers=h, params={"keyword": no})
    assert r.status_code == 200 and r.json() == [], "被拦下的建票请求不许留下半张票"


@pytest.mark.dispatcher
@pytest.mark.fast
def test_进项票不许填客户_也不许挂账本(client, token_dispatcher):
    """进项票是供应商开给我们的：填客户、挂账本条目都是把两个方向搅在一起。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    c = _new_customer(client, h, _uniq("发票客户"))
    no = _uniq("IN")

    st, d = _try(client, h, _in_body(no, s, o, customer_id=c["id"]))
    assert st == 400 and "不该填客户" in d["detail"], d

    st, d = _try(client, h, _in_body(no, s, o, ledger_ids=[1]))
    assert st == 400 and "不该挂账本" in d["detail"], d


@pytest.mark.dispatcher
@pytest.mark.fast
def test_销项票要写客户_不许填供应商_也不许挂采购单(client, token_dispatcher):
    """销项票反过来：必须写客户，⛔ 不许挂采购单（那是进项的事）。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    c = _new_customer(client, h, _uniq("发票客户"))
    no = _uniq("OUT")

    st, d = _try(client, h, {"direction": "OUTPUT", "invoice_no": no, "invoice_date": "2026-09-12",
                            "amount": "103.00", "tax_rate": "3.00"})
    assert st == 400 and "客户" in d["detail"], d

    st, d = _try(client, h, _out_body(no, c, supplier_id=s["id"]))
    assert st == 400 and "不该填供应商" in d["detail"], d

    st, d = _try(client, h, _out_body(no, c, purchase_order_ids=[o["id"]]))
    assert st == 400 and "不该挂采购单" in d["detail"], d

    v = _new(client, h, _out_body(no, c))
    assert v["direction"] == "OUTPUT" and v["counts_in_tax"] is True


@pytest.mark.dispatcher
@pytest.mark.fast
def test_挂在回收站里的采购单上要如实拦下(client, token_dispatcher):
    """采购单撤了，它上面的货就不在账上了 —— 票要挂回去必须先把那张单恢复出来。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    r = client.delete(f"{ORD}/{o['id']}", headers=h)
    assert r.status_code == 204, r.text

    st, d = _try(client, h, _in_body(_uniq("IN"), s, o))
    assert st == 400 and "恢复" in d["detail"], d


# ---------------- ② 票号唯一 ----------------
@pytest.mark.dispatcher
@pytest.mark.fast
def test_同方向同票号只能登记一次_空号可以多张(client, token_dispatcher):
    """同方向撞号 409（如实说号写错了）；换方向不算撞；票还没拿到时空号可以登记多张。"""
    h = auth_headers(token_dispatcher)
    s1, p1, o1 = _input_ready(client, h)
    s2, p2, o2 = _input_ready(client, h)
    s3, p3, o3 = _input_ready(client, h)
    c = _new_customer(client, h, _uniq("发票客户"))
    no = _uniq("IN")

    _new(client, h, _in_body(no, s1, o1))
    st, d = _try(client, h, _in_body(no, s2, o2))
    assert st == 409 and no in d["detail"], d

    # 销项与进项各有一套号：同一个号在两个方向上不冲突
    out = _new(client, h, _out_body(no, c))
    assert out["invoice_no"] == no

    # 空号（票还没拿到）可以登记多张 —— ⛔ 不许拿「票号不能为空」把老板堵在门外
    a = _new(client, h, _in_body("", s2, o2))
    b = _new(client, h, _in_body("", s3, o3))
    assert a["id"] != b["id"] and a["invoice_no"] == "" and b["invoice_no"] == ""


# ---------------- ③ 税额与未税票 ----------------
@pytest.mark.dispatcher
@pytest.mark.fast
def test_税额填得比价税合计还大_要说是不是填反了(client, token_dispatcher):
    """只给税率时后端算（100.00 含 13% -> 11.50）；税额 > 合计、未税票却填了税额都要拦下。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    no = _uniq("IN")

    st, d = _try(client, h, _in_body(no, s, o, amount="100.00", tax_rate="13.00", tax_amount="999.00"))
    assert st == 400 and "填反" in d["detail"], d

    st, d = _try(client, h, _in_body(no, s, o, amount="100.00", tax_amount="5.00", tax_rate=None))
    assert st == 400 and "不该有税额" in d["detail"], d

    v = _new(client, h, _in_body(no, s, o, amount="100.00", tax_rate="13.00"))
    assert _num(v["tax_amount"]) == Decimal("11.50"), v


@pytest.mark.dispatcher
@pytest.mark.fast
def test_没填税率的票单独计数_不进税汇(client, token_dispatcher):
    """未税票（票还没到 / 小规模代开）进 `untaxed_*`，⛔ 不进 `tax_amount`，也不算进已计税的票数。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    w = ("2023-03-01", "2023-03-31")
    before = _tax(client, h, *w)

    v = _new(client, h, _in_body(_uniq("IN"), s, o, invoice_date="2023-03-15", amount="500.00", tax_rate=None))
    assert v["tax_rate"] is None and v["tax_amount"] is None

    after = _tax(client, h, *w)
    assert _d(after["input"]["untaxed_count"], before["input"]["untaxed_count"]) == 1
    assert _d(after["input"]["untaxed_amount"], before["input"]["untaxed_amount"]) == Decimal("500.00")
    assert _d(after["input"]["count"], before["input"]["count"]) == 0
    assert _d(after["input"]["tax_amount"], before["input"]["tax_amount"]) == Decimal("0")
    assert _d(after["input"]["net_amount"], before["input"]["net_amount"]) == Decimal("0")
    assert not [b for b in after["by_rate"] if b["direction"] == "INPUT" and _num(b["tax_rate"]) == 0]
    row = next(x for x in after["invoices"] if x["id"] == v["id"])
    assert row["tax_rate"] is None
    assert row["counts_in_tax"] is False, "没税率的票不算进税汇（只进 untaxed_*），明细里照实标出来"


# ---------------- ④ 状态机：登记 -> 开具 -> 作废 ----------------
@pytest.mark.dispatcher
@pytest.mark.fast
def test_开具之后改不动_要改就作废重开(client, token_dispatcher):
    """已登记能改（只改金额时税额按税率重算）；已开具 / 已作废一律 400。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    v = _new(client, h, _in_body(_uniq("IN"), s, o))

    _patch(client, h, v["id"], {"amount": "120.00"})
    d = _detail(client, h, v["id"])
    assert _num(d["amount"]) == Decimal("120.00")
    assert _num(d["tax_amount"]) == Decimal("3.50"), "改金额时要按税率把税额一起重算（120.00 含 3% -> 3.50）"

    _act(client, h, v["id"], "issue")
    r = client.patch(f"{INV}/{v['id']}", json={"amount": "130.00"}, headers=h)
    assert r.status_code == 400 and "改不动" in r.json()["detail"], r.text

    _act(client, h, v["id"], "void")
    r = client.patch(f"{INV}/{v['id']}", json={"invoice_no": _uniq("IN")}, headers=h)
    assert r.status_code == 400 and "改不动" in r.json()["detail"], r.text


@pytest.mark.dispatcher
@pytest.mark.fast
def test_开具两次_作废两次_都被拦下(client, token_dispatcher):
    """状态机只有三条边：REGISTERED -> ISSUED -> VOIDED。往回走、原地再走都要如实拦。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    v = _new(client, h, _in_body(_uniq("IN"), s, o))

    assert _act(client, h, v["id"], "issue")["status"] == "ISSUED"
    r = client.post(f"{INV}/{v['id']}/issue", headers=h)
    assert r.status_code == 400 and "开具过" in r.json()["detail"], r.text

    assert _act(client, h, v["id"], "void")["status"] == "VOIDED"
    r = client.post(f"{INV}/{v['id']}/void", headers=h)
    assert r.status_code == 400 and "作废过" in r.json()["detail"], r.text

    r = client.post(f"{INV}/{v['id']}/issue", headers=h)
    assert r.status_code == 400 and "不能再开具" in r.json()["detail"], r.text


# ---------------- ⑤ 作废 / 回收站：退出税汇，恢复回来 ----------------
@pytest.mark.dispatcher
@pytest.mark.fast
def test_作废的票退出税汇_明细里还看得见(client, token_dispatcher):
    """作废不等于删掉：税汇上退出（不计税、不计票数），明细里还在、只是「不算数」。"""
    h = auth_headers(token_dispatcher)
    s1, p1, o1 = _input_ready(client, h)
    s2, p2, o2 = _input_ready(client, h)
    w = ("2022-11-01", "2022-11-30")
    before = _tax(client, h, *w)

    a = _new(client, h, _in_body(_uniq("IN"), s1, o1, invoice_date="2022-11-10", amount="103.00", tax_rate="3.00"))
    b = _new(client, h, _in_body(_uniq("IN"), s2, o2, invoice_date="2022-11-11", amount="113.00", tax_rate="13.00"))
    mid = _tax(client, h, *w)
    assert _d(mid["input"]["count"], before["input"]["count"]) == 2
    assert _d(mid["input"]["tax_amount"], before["input"]["tax_amount"]) == Decimal("16.00")
    assert _d(mid["vat_payable"], before["vat_payable"]) == Decimal("-16.00"), "进项税多了，应交增值税就该往下走"

    _act(client, h, b["id"], "void")
    after = _tax(client, h, *w)
    assert _d(after["input"]["count"], before["input"]["count"]) == 1
    assert _d(after["input"]["tax_amount"], before["input"]["tax_amount"]) == Decimal("3.00")
    assert _d(after["voided_count"], before["voided_count"]) == 1

    ids = {x["id"] for x in after["invoices"]}
    assert {a["id"], b["id"]} <= ids, "作废的票也要留在明细里（否则「这张票去哪了」答不出来）"
    row = next(x for x in after["invoices"] if x["id"] == b["id"])
    assert row["counts_in_tax"] is False and row["status"] == "VOIDED"
    assert _num(row["tax_amount"]) == Decimal("13.00"), "票面税额还在（作废不改票面）"


@pytest.mark.dispatcher
@pytest.mark.fast
def test_回收站里的票退出税汇_恢复后原样回来(client, token_dispatcher):
    """软删的票同样退出税汇（但详情还查得到），恢复之后一分不差地回来。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    w = ("2021-07-01", "2021-07-31")
    before = _tax(client, h, *w)

    a = _new(client, h, _in_body(_uniq("IN"), s, o, invoice_date="2021-07-05"))
    assert _d(_tax(client, h, *w)["input"]["tax_amount"], before["input"]["tax_amount"]) == Decimal("3.00")

    _drop(client, h, a["id"])
    gone = _tax(client, h, *w)
    assert _d(gone["input"]["tax_amount"], before["input"]["tax_amount"]) == Decimal("0")
    assert a["id"] not in {x["id"] for x in gone["invoices"]}
    assert _detail(client, h, a["id"])["is_deleted"] is True

    back = _act(client, h, a["id"], "restore")
    assert back["is_deleted"] is False and back["counts_in_tax"] is True
    assert _d(_tax(client, h, *w)["input"]["tax_amount"], before["input"]["tax_amount"]) == Decimal("3.00")


@pytest.mark.dispatcher
@pytest.mark.fast
def test_回收站里的票仍然占着号_再登记同号要指向回收站(client, token_dispatcher):
    """票号唯一性是两列唯一索引、软删不清号：删掉的票还占着号，再登记同号 409 并指向回收站。"""
    h = auth_headers(token_dispatcher)
    s1, p1, o1 = _input_ready(client, h)
    s2, p2, o2 = _input_ready(client, h)
    no = _uniq("IN")

    first = _new(client, h, _in_body(no, s1, o1))
    _drop(client, h, first["id"])

    st, d = _try(client, h, _in_body(no, s2, o2))
    assert st == 409 and "回收站" in d["detail"], d

    # 恢复：那个号一直是这一行的，谁也挡不住
    back = _act(client, h, first["id"], "restore")
    assert back["invoice_no"] == no and back["is_deleted"] is False

    # 已经在手上的票再点一次恢复：400（不是 409）
    r = client.post(f"{INV}/{first['id']}/restore", headers=h)
    assert r.status_code == 400 and "回收站" in r.json()["detail"], r.text


# ---------------- ⑥ 采购单删单闸 ----------------
@pytest.mark.dispatcher
@pytest.mark.fast
def test_删掉挂着没作废进项票的采购单要拦下(client, token_dispatcher, db_session):
    """票还挂在单上就删单，进项税额会凭空少掉 —— 拦下，且一个字节都不许改。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    assert _stock(db_session, p["id"]) == 10
    _new(client, h, _in_body(_uniq("IN"), s, o))

    r = client.delete(f"{ORD}/{o['id']}", headers=h)
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "进项票" in detail and "作废" in detail, detail

    assert client.get(f"{ORD}/{o['id']}", headers=h).status_code == 200, "被拦下之后单还在"
    assert _stock(db_session, p["id"]) == 10
    _assert_identity(db_session, p["id"])


@pytest.mark.dispatcher
@pytest.mark.fast
def test_把票作废之后_采购单就能删了_库存退回去(client, token_dispatcher, db_session):
    """闸门是「还算数的票」：作废之后删单放行，库存退回 0，恒等式仍然成立。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    v = _new(client, h, _in_body(_uniq("IN"), s, o))
    _act(client, h, v["id"], "void")

    r = client.delete(f"{ORD}/{o['id']}", headers=h)
    assert r.status_code == 204, r.text
    assert _stock(db_session, p["id"]) == 0, "整单撤销要把货退回去"
    _assert_identity(db_session, p["id"])

    back = client.post(f"{ORD}/{o['id']}/restore", headers=h)
    assert back.status_code == 200, back.text
    assert _stock(db_session, p["id"]) == 10, "恢复采购单，货也要回来（票还是作废状态）"
    _assert_identity(db_session, p["id"])


# ---------------- ⑦ 税汇：窗口 / 税率分组 ----------------
@pytest.mark.dispatcher
@pytest.mark.fast
def test_税账窗口按开票日期落_窗外那一天不算(client, token_dispatcher):
    """窗口按 `invoice_date`（⛔ 不按 created_at）：月底补录上月的票要落在上月。"""
    h = auth_headers(token_dispatcher)
    s1, p1, o1 = _input_ready(client, h)
    s2, p2, o2 = _input_ready(client, h)
    w = ("2020-05-01", "2020-05-31")
    before = _tax(client, h, *w)

    inside = _new(client, h, _in_body(_uniq("IN"), s1, o1, invoice_date="2020-05-31"))
    outside = _new(client, h, _in_body(_uniq("IN"), s2, o2, invoice_date="2020-06-01"))

    after = _tax(client, h, *w)
    assert _d(after["input"]["count"], before["input"]["count"]) == 1
    assert _d(after["input"]["tax_amount"], before["input"]["tax_amount"]) == Decimal("3.00")
    ids = {x["id"] for x in after["invoices"]}
    assert inside["id"] in ids and outside["id"] not in ids


@pytest.mark.dispatcher
@pytest.mark.fast
def test_按税率分组_销项在前_税率从高到低(client, token_dispatcher):
    """`by_rate` 回答「13% 那批开了多少」：销项在前、税率降序，小格的合计与税汇两侧对得上。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    c = _new_customer(client, h, _uniq("发票客户"))
    w = ("2019-02-01", "2019-02-28")
    before = _tax(client, h, *w)

    _new(client, h, _out_body(_uniq("OUT"), c, invoice_date="2019-02-10", amount="113.00", tax_rate="13.00"))
    _new(client, h, _out_body(_uniq("OUT"), c, invoice_date="2019-02-11", amount="103.00", tax_rate="3.00"))
    _new(client, h, _in_body(_uniq("IN"), s, o, invoice_date="2019-02-12", amount="226.00", tax_rate="13.00"))

    after = _tax(client, h, *w)
    assert _d(after["output"]["tax_amount"], before["output"]["tax_amount"]) == Decimal("16.00")
    assert _d(after["input"]["tax_amount"], before["input"]["tax_amount"]) == Decimal("26.00")
    assert _d(after["vat_payable"], before["vat_payable"]) == Decimal("-10.00")

    seen = [(b["direction"], _num(b["tax_rate"]), b["count"], _num(b["tax_amount"])) for b in after["by_rate"]]
    mine = [x for x in seen if x[1] in (Decimal("13.00"), Decimal("3.00"))]
    assert ("OUTPUT", Decimal("13.00"), 1, Decimal("13.00")) in mine
    assert ("OUTPUT", Decimal("3.00"), 1, Decimal("3.00")) in mine
    assert ("INPUT", Decimal("13.00"), 1, Decimal("26.00")) in mine
    i_out = [i for i, x in enumerate(seen) if x[0] == "OUTPUT"]
    i_in = [i for i, x in enumerate(seen) if x[0] == "INPUT"]
    assert max(i_out) < min(i_in), f"销项要排在前：{seen}"
    rates = [x[1] for x in seen if x[0] == "OUTPUT"]
    assert rates == sorted(rates, reverse=True), f"税率要从高到低：{seen}"


# ---------------- ⑧ 利润表：两份税 ----------------
@pytest.mark.dispatcher
@pytest.mark.fast
def test_利润表的税那一格取分类名带税的开销_且不双扣(client, token_dispatcher):
    """分类名带「税」的开销从期间费用里**搬**到 `tax_total`：期间费用合计不变，营业利润少这一笔。"""
    h = auth_headers(token_dispatcher)
    day = "2023-04-11"
    before = _profit(client, h, day)

    r = client.post(
        EXP,
        json={"exp_date": day, "category": "税金及附加", "amount": "50.00", "note": "测试：印花税"},
        headers=h,
    )
    assert r.status_code == 200, r.text

    after = _profit(client, h, day)
    assert _d(after["tax_total"], before["tax_total"]) == Decimal("50.00")
    assert _d(after["operating_expense_total"], before["operating_expense_total"]) == Decimal("0"), (
        "税是从期间费用里搬出来的：两边都算一遍就是双扣"
    )
    assert _d(after["operating_profit"], before["operating_profit"]) == Decimal("-50.00")

    hit = [x for x in after["tax_expenses"] if _num(x["amount"]) == Decimal("50.00")]
    assert hit and hit[0]["category"] == "税金及附加", after["tax_expenses"]
    assert not [x for x in after["operating_expenses"] if x["category"] == "税金及附加"], (
        "搬走的那些笔不许在期间费用明细里再出现一次"
    )


@pytest.mark.dispatcher
@pytest.mark.fast
def test_利润表多出应交增值税_但它不进营业利润(client, token_dispatcher):
    """应交增值税 = 销项 − 进项，是代收代付的价外税：三个数都要动，营业利润一个字节不动。"""
    h = auth_headers(token_dispatcher)
    day = "2023-04-12"
    before = _profit(client, h, day)
    c = _new_customer(client, h, _uniq("发票客户"))
    s, p, o = _input_ready(client, h)

    _new(client, h, _out_body(_uniq("OUT"), c, invoice_date=day, amount="113.00", tax_rate="13.00"))
    _new(client, h, _in_body(_uniq("IN"), s, o, invoice_date=day, amount="103.00", tax_rate="3.00"))

    after = _profit(client, h, day)
    assert _d(after["vat_output"], before["vat_output"]) == Decimal("13.00")
    assert _d(after["vat_input"], before["vat_input"]) == Decimal("3.00")
    assert _d(after["vat_payable"], before["vat_payable"]) == Decimal("10.00")
    assert _d(after["operating_profit"], before["operating_profit"]) == Decimal("0"), (
        "增值税是价外税：它一进营业利润，利润表就把「税」算了两遍"
    )


# ---------------- ⑨ 留痕 / 权限 / 列表筛选 ----------------
@pytest.mark.dispatcher
@pytest.mark.fast
def test_每一步都留痕_六个动作码(client, token_dispatcher, db_session):
    """登记 / 改 / 开具 / 作废 / 删进回收站 / 恢复：六个动作码各写一条（多一条少一条都要能看见）。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    n_before = {a: len(_logs(db_session, a)) for a in TAX_ACTIONS}

    v = _new(client, h, _in_body(_uniq("IN"), s, o))
    _patch(client, h, v["id"], {"note": "改个备注"})
    _act(client, h, v["id"], "issue")
    _act(client, h, v["id"], "void")
    _drop(client, h, v["id"])
    _act(client, h, v["id"], "restore")

    for action in TAX_ACTIONS:
        rows = _logs(db_session, action)
        assert len(rows) == n_before[action] + 1, f"{action} 没有留痕（或写了两条）"
        assert str(v["id"]) in json.dumps(rows[-1], ensure_ascii=False), f"{action} 的留痕里没有这张票的编号"


@pytest.mark.dispatcher
@pytest.mark.fast
def test_货主和司机一个口子都进不来(client, token_shipper, token_driver):
    """发票与税账都不给货主 / 司机：四个口子（列表、建票、税账、利润表）逐个试。"""
    body = {"direction": "INPUT", "invoice_no": "X-1", "invoice_date": "2026-09-12", "amount": "103.00"}
    for token in (token_shipper, token_driver):
        h = auth_headers(token)
        assert client.get(INV, headers=h).status_code == 403
        assert client.post(INV, json=body, headers=h).status_code == 403
        assert client.get(TAX, headers=h, params={"mode": "month", "date": "2026-09-01"}).status_code == 403
        assert client.get(PROFIT, headers=h, params={"mode": "day", "date": "2026-10-04"}).status_code == 403


@pytest.mark.dispatcher
@pytest.mark.fast
def test_列表按住方向与日期筛(client, token_dispatcher):
    """台账列表的三个常用筛子：方向、开票日期区间、票号关键字。"""
    h = auth_headers(token_dispatcher)
    s, p, o = _input_ready(client, h)
    c = _new_customer(client, h, _uniq("发票客户"))

    a = _new(client, h, _in_body(_uniq("IN"), s, o, invoice_date="2023-06-05"))
    b = _new(client, h, _out_body(_uniq("OUT"), c, invoice_date="2023-06-06"))

    r = client.get(INV, headers=h, params={"direction": "OUTPUT", "date_from": "2023-06-01", "date_to": "2023-06-30"})
    assert r.status_code == 200, r.text
    ids = {x["id"] for x in r.json()}
    assert b["id"] in ids and a["id"] not in ids

    r = client.get(INV, headers=h, params={"keyword": a["invoice_no"]})
    assert r.status_code == 200, r.text
    assert {x["id"] for x in r.json()} == {a["id"]}
