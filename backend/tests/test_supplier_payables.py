"""供应商 / 厂商档案 + 应付款：欠款口径、分次付款、撤销付款、软删与恢复、审计、权限。

## 为什么这几条必须钉住（每一条都是"不报错但会错"的形状）
1. **欠款是算出来的，不是存下来的**：付一笔款之后「还欠多少」必须立刻变；
   撤销之后必须变回来。这一条同时钉住三处（列表 / 应付单 / 供应商合计）。
2. **付款＝一行资金流水**：付了钱就要能在 `cash_flows` 里看见那一行（`PAYMENT_SUPPLIER`），
   撤销之后**收支页不能再看见它**（`is_deleted` 过滤）。⛔ 少了那个过滤，
   表现是"欠款说没付、收支说付了"，两边都不报错 —— 这是本项目最贵的一类错。
3. **撤销是软删**（用户定的硬规矩）：流水行还在库里，`restore` 能原样放回来。
4. **有付款的应付单不许删**（哪怕付款已撤销）：删了那些流水就永远指不到应付款了。
5. **有应付单的供应商不许删**：欠款不能挂在一个看不见的供应商上。
6. **付款不许超过还差**：超了就是预付款，而预付款在这套账里没有位置（欠款会变成负数）。
7. **改金额不许改到小于已付**：那等于把已经付出去的钱说成没付。
8. **每次写都要留痕**：这一组同时决定"欠他多少"和"钱什么时候出去的"。
"""
from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import select

from app.models import CashFlow, OperationLog, Supplier, SupplierPayable
from tests.conftest import auth_headers

SUP = "/api/v1/suppliers"
PAY = "/api/v1/supplier-payables"
FLOW = "/api/v1/supplier-payments"


def _new_supplier(client, h, name: str, **over) -> dict:
    body = {"name": name, "contact_name": "老陈", "phone": "13800001111"}
    body.update(over)
    r = client.post(SUP, json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _new_payable(client, h, sid: int, title: str, amount: str, **over) -> dict:
    body = {"supplier_id": sid, "title": title, "amount": amount, "doc_date": "2026-09-01"}
    body.update(over)
    r = client.post(f"{SUP}/{sid}/payables", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _pay(client, h, pid: int, amount: str, **over) -> dict:
    body = {"amount": amount, "pay_date": "2026-09-02", "channel": "transfer"}
    body.update(over)
    r = client.post(f"{PAY}/{pid}/payments", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _find(client, h, sid: int) -> dict:
    """从列表里取这一条（列表是端点的真实出参，不是直接读库）。"""
    return next(r for r in client.get(SUP, headers=h).json() if r["id"] == sid)


def _payable(client, h, pid: int) -> dict:
    r = client.get(PAY, headers=h)
    assert r.status_code == 200, r.text
    return next(x for x in r.json() if x["id"] == pid)


def _logs(db, action: str) -> list[dict]:
    rows = db.scalars(select(OperationLog).where(OperationLog.action == action)).all()
    return [json.loads(r.change_content or "{}") for r in rows]


# ---------------- 档案 ----------------
def test_建一个供应商档案(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "永盛食品有限公司", address="仲恺区惠风东三路")
    assert s["name"] == "永盛食品有限公司"
    assert s["phone"] == "13800001111"
    # 新档案没有欠款：三个数都是 0.00（不是空、不是 null）
    assert (s["payable_total"], s["paid_total"], s["unpaid_total"]) == ("0.00", "0.00", "0.00")
    assert s["open_payables"] == 0
    # 列表里立刻能看到
    assert any(r["id"] == s["id"] for r in client.get(SUP, headers=h).json())


def test_同名供应商不许建两个(client, token_dispatcher):
    """重复档案会把同一个供应商的欠款拆成两半，而两边都不报错。"""
    h = auth_headers(token_dispatcher)
    _new_supplier(client, h, "重名供应商")
    r = client.post(SUP, json={"name": "重名供应商"}, headers=h)
    assert r.status_code == 400 and "已经有一个供应商" in r.json()["detail"]


def test_电话不合规要拦下来(client, token_dispatcher):
    """带汉字的电话存进去 = 真要打的时候打不通（`core/phone.py` 的理由）。"""
    h = auth_headers(token_dispatcher)
    r = client.post(SUP, json={"name": "电话很怪的供应商", "phone": "电话问老王"}, headers=h)
    assert r.status_code == 422


# ---------------- 应付单 + 付款：欠款口径 ----------------
def test_挂一笔应付_欠款就是总额(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "欠款供应商A")
    p = _new_payable(client, h, s["id"], "9 月货款", "1200.50")
    assert p["amount"] == "1200.50" and p["paid"] == "0.00" and p["unpaid"] == "1200.50"
    assert p["payment_count"] == 0
    row = _find(client, h, s["id"])
    assert (row["payable_total"], row["paid_total"], row["unpaid_total"]) == ("1200.50", "0.00", "1200.50")
    assert row["open_payables"] == 1


def test_分次付款_每次都要看得见(client, token_dispatcher):
    """用户原话要的就是"**可分次付款**"：一张单付三次，欠款一步步降。"""
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "分次付款供应商")
    p = _new_payable(client, h, s["id"], "采购叉车", "1000.00")
    _pay(client, h, p["id"], "300.00")
    mid = _payable(client, h, p["id"])
    assert (mid["paid"], mid["unpaid"], mid["payment_count"]) == ("300.00", "700.00", 1)
    _pay(client, h, p["id"], "200.00")
    mid = _payable(client, h, p["id"])
    assert (mid["paid"], mid["unpaid"], mid["payment_count"]) == ("500.00", "500.00", 2)
    _pay(client, h, p["id"], "500.00")
    done = _payable(client, h, p["id"])
    assert (done["paid"], done["unpaid"], done["payment_count"]) == ("1000.00", "0.00", 3)
    row = _find(client, h, s["id"])
    assert (row["paid_total"], row["unpaid_total"]) == ("1000.00", "0.00")
    # 付清之后再付一笔 → 明确拒绝（不许变成"倒欠他钱"）
    r = client.post(f"{PAY}/{p['id']}/payments", json={"amount": "1", "pay_date": "2026-09-03"}, headers=h)
    assert r.status_code == 400 and "已经付清" in r.json()["detail"]


def test_付款不许超过还差(client, token_dispatcher):
    """超了就是预付款 —— 而预付款在这套账里没有位置（欠款会变成负数，界面上没人读得对）。"""
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "超付供应商")
    p = _new_payable(client, h, s["id"], "运费", "100.00")
    r = client.post(f"{PAY}/{p['id']}/payments", json={"amount": "150", "pay_date": "2026-09-02"}, headers=h)
    assert r.status_code == 400 and "超过了这张单还差的 100.00" in r.json()["detail"]
    # 一分钱都没动
    assert _payable(client, h, p["id"])["paid"] == "0.00"


def test_付款真的写了一行资金流水(client, token_dispatcher, db_session):
    """付款＝`cash_flows` 的一行（`PAYMENT_SUPPLIER`）—— 账本「收支」页看的就是它。"""
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "查流水供应商")
    p = _new_payable(client, h, s["id"], "邮费", "38.50")
    f = _pay(client, h, p["id"], "38.50", remark="顺丰到付")
    assert f["supplier_name"] == "查流水供应商" and f["payable_title"] == "邮费"
    assert f["remark"] == "顺丰到付" and f["channel"] == "transfer"
    row = db_session.scalars(select(CashFlow).where(CashFlow.id == f["id"])).first()
    assert row is not None
    assert str(row.biz_type) == "PAYMENT_SUPPLIER"
    assert str(row.direction).lower() == "out"
    assert row.party_type == "supplier" and row.party_id == s["id"] and row.doc_id == p["id"]
    assert Decimal(row.amount) == Decimal("38.50")
    assert row.is_deleted is False


def test_付款列表只回这个供应商的(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    a = _new_supplier(client, h, "供应商甲")
    b = _new_supplier(client, h, "供应商乙")
    pa = _new_payable(client, h, a["id"], "甲的单", "100.00")
    pb = _new_payable(client, h, b["id"], "乙的单", "200.00")
    _pay(client, h, pa["id"], "100.00")
    _pay(client, h, pb["id"], "50.00")
    only_a = client.get(FLOW, headers=h, params={"supplier_id": a["id"]}).json()
    assert [r["payable_title"] for r in only_a] == ["甲的单"]
    only_pb = client.get(FLOW, headers=h, params={"payable_id": pb["id"]}).json()
    assert len(only_pb) == 1 and only_pb[0]["amount"] == "50.00"


# ---------------- 撤销付款（软删 + 恢复） ----------------
def _supplier_expense(client, h) -> Decimal:
    """账本「收支」页口径里"付供应商"这一路一共算了多少（走端点，不直接读库）。"""
    r = client.get(
        "/api/v1/cash-flows/breakdown", headers=h,
        params={"date_from": "2026-09-01", "date_to": "2026-09-30"},
    )
    assert r.status_code == 200, r.text
    return Decimal(next((x["amount"] for x in r.json()["expense"] if x["biz_type"] == "PAYMENT_SUPPLIER"), "0"))


def test_撤销一笔付款_欠款变回来_收支也不再算它(client, token_dispatcher, db_session):
    """⛔ 这一条是整个设计的支点：撤销之后**两边**都要变，不能只有一边。

    ⚠️ 断言用**前后差值**而不是"这一路等于几"：测试库在同一次运行里是累积的
       （别的用例也付过供应商款），写死一个数就是假红。
    """
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "撤销付款供应商")
    p = _new_payable(client, h, s["id"], "设备采购", "800.00")
    f = _pay(client, h, p["id"], "800.00")
    assert _payable(client, h, p["id"])["unpaid"] == "0.00"
    before = _supplier_expense(client, h)

    r = client.delete(f"{FLOW}/{f['id']}", headers=h)
    assert r.status_code == 204, r.text
    # ① 欠款回来了
    assert _payable(client, h, p["id"])["unpaid"] == "800.00"
    assert _find(client, h, s["id"])["unpaid_total"] == "800.00"
    # ② **收支页也少算了这 800**（`cash_flows` 的 is_deleted 过滤真的生效了）
    assert before - _supplier_expense(client, h) == Decimal("800.00")
    # ③ 流水行**还在库里**（软删是"藏起来"，不是"抹掉"）
    row = db_session.scalars(select(CashFlow).where(CashFlow.id == f["id"])).first()
    assert row is not None and row.is_deleted is True and row.deleted_at is not None
    # ④ 默认列表里看不见，带 include_deleted 才看得见
    assert all(x["id"] != f["id"] for x in client.get(FLOW, headers=h).json())
    assert any(x["id"] == f["id"] for x in client.get(FLOW, headers=h, params={"include_deleted": True}).json())
    # ⑤ 恢复之后两边一起回来
    assert client.post(f"{FLOW}/{f['id']}/restore", headers=h).status_code == 200
    assert _supplier_expense(client, h) == before


def test_恢复撤销掉的付款_原样回来(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "恢复付款供应商")
    p = _new_payable(client, h, s["id"], "货款", "500.00")
    f = _pay(client, h, p["id"], "500.00")
    client.delete(f"{FLOW}/{f['id']}", headers=h)
    back = client.post(f"{FLOW}/{f['id']}/restore", headers=h)
    assert back.status_code == 200, back.text
    assert back.json()["amount"] == "500.00"
    assert _payable(client, h, p["id"])["unpaid"] == "0.00"
    # 再撤一次（现在它没被撤销）→ 明确拒绝，不是静默 200
    r2 = client.post(f"{FLOW}/{f['id']}/restore", headers=h)
    assert r2.status_code == 400 and "没有被撤销" in r2.json()["detail"]


def test_撤销的付款不能算已经付过(client, token_dispatcher):
    """付清 → 撤销 → 还能再付一次（欠款是唯一判据，不是"付过一次就锁死"）。"""
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "撤销后再付供应商")
    p = _new_payable(client, h, s["id"], "货款", "120.00")
    f = _pay(client, h, p["id"], "120.00")
    client.delete(f"{FLOW}/{f['id']}", headers=h)
    f2 = _pay(client, h, p["id"], "120.00")
    assert f2["amount"] == "120.00"
    assert _payable(client, h, p["id"])["unpaid"] == "0.00"


def test_撤销的付款_应付单还在回收站里时恢复不了(client, token_dispatcher):
    """⛔ 三道门之一：恢复的付款必须对得上一张活着的单 —— 否则"钱回来了、账上没单据"。"""
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "门卫供应商")
    p = _new_payable(client, h, s["id"], "临时单", "60.00")
    f = _pay(client, h, p["id"], "60.00")
    client.delete(f"{FLOW}/{f['id']}", headers=h)
    # 付款已撤销 → 这张单可以删（没有活着的付款）
    assert client.delete(f"{PAY}/{p['id']}", headers=h).status_code == 204
    r = client.post(f"{FLOW}/{f['id']}/restore", headers=h)
    assert r.status_code == 400 and "应付单还在回收站里" in r.json()["detail"]


# ---------------- 软删与恢复 ----------------
def test_有付款的单不许删(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "有付款的单供应商")
    p = _new_payable(client, h, s["id"], "货款", "300.00")
    _pay(client, h, p["id"], "100.00")
    r = client.delete(f"{PAY}/{p['id']}", headers=h)
    assert r.status_code == 400 and "没撤销的付款" in r.json()["detail"]
    # 撤销那笔付款之后就能删了（"付错了 → 撤销 → 这张单也不要了"是正常路径）
    f = client.get(FLOW, headers=h, params={"payable_id": p["id"]}).json()[0]
    assert client.delete(f"{FLOW}/{f['id']}", headers=h).status_code == 204
    assert client.delete(f"{PAY}/{p['id']}", headers=h).status_code == 204


def test_有应付单的供应商不许删(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "有账单的供应商")
    _new_payable(client, h, s["id"], "货款", "10.00")
    r = client.delete(f"{SUP}/{s['id']}", headers=h)
    assert r.status_code == 400 and "应付单" in r.json()["detail"]


def test_删掉供应商_回收站里看得见_名字释放_能恢复(client, token_dispatcher, db_session):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "要删掉的供应商")
    assert client.delete(f"{SUP}/{s['id']}", headers=h).status_code == 204
    # ① 默认列表看不见
    assert all(r["id"] != s["id"] for r in client.get(SUP, headers=h).json())
    # ② 带 include_deleted 看得见（界面上那个"回收站"入口用的就是它）
    assert any(r["id"] == s["id"] for r in client.get(SUP, headers=h, params={"include_deleted": True}).json())
    # ③ 名字被释放了（不然"删掉再建同名"会撞唯一索引 500）
    s2 = _new_supplier(client, h, "要删掉的供应商")
    assert s2["id"] != s["id"]
    # ④ 恢复：名字被占了就保留带后缀的名字（不硬抢），但行是活的
    back = client.post(f"{SUP}/{s['id']}/restore", headers=h)
    assert back.status_code == 200, back.text
    assert back.json()["id"] == s["id"]
    row = db_session.get(Supplier, s["id"])
    assert row is not None and row.is_deleted is False


def test_回收站里的供应商改不了(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "回收站供应商")
    client.delete(f"{SUP}/{s['id']}", headers=h)
    r = client.patch(f"{SUP}/{s['id']}", json={"remark": "想偷偷改"}, headers=h)
    assert r.status_code == 400 and "回收站" in r.json()["detail"]


def test_删掉应付单_能恢复(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "删单供应商")
    p = _new_payable(client, h, s["id"], "要删的单", "77.00")
    assert client.delete(f"{PAY}/{p['id']}", headers=h).status_code == 204
    assert all(r["id"] != p["id"] for r in client.get(PAY, headers=h).json())
    assert any(r["id"] == p["id"] for r in client.get(PAY, headers=h, params={"include_deleted": True}).json())
    back = client.post(f"{PAY}/{p['id']}/restore", headers=h)
    assert back.status_code == 200 and back.json()["unpaid"] == "77.00"
    # 回收站里的单不能付款
    client.delete(f"{PAY}/{p['id']}", headers=h)
    r = client.post(f"{PAY}/{p['id']}/payments", json={"amount": "1", "pay_date": "2026-09-02"}, headers=h)
    assert r.status_code == 400 and "回收站" in r.json()["detail"]


def test_供应商不在了_单恢复不了(client, token_dispatcher):
    """单挂在供应商下面：供应商在回收站里时把单放回来，等于放回一个看不见的名下。"""
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "连坐供应商")
    p = _new_payable(client, h, s["id"], "单", "10.00")
    client.delete(f"{PAY}/{p['id']}", headers=h)   # 先删单（不然供应商删不掉）
    assert client.delete(f"{SUP}/{s['id']}", headers=h).status_code == 204
    r = client.post(f"{PAY}/{p['id']}/restore", headers=h)
    assert r.status_code == 400 and "供应商还在回收站里" in r.json()["detail"]


# ---------------- 改金额的边界 ----------------
def test_改金额不许改到小于已付(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "改金额供应商")
    p = _new_payable(client, h, s["id"], "货款", "500.00")
    _pay(client, h, p["id"], "400.00")
    r = client.patch(f"{PAY}/{p['id']}", json={"amount": "300"}, headers=h)
    assert r.status_code == 400 and "不能改成比它小" in r.json()["detail"]
    # 改成等于已付 / 大于已付都可以
    assert client.patch(f"{PAY}/{p['id']}", json={"amount": "400"}, headers=h).status_code == 200
    up = client.patch(f"{PAY}/{p['id']}", json={"amount": "900"}, headers=h)
    assert up.status_code == 200 and up.json()["unpaid"] == "500.00"


def test_改事由与分类(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "改事由供应商")
    p = _new_payable(client, h, s["id"], "旧事由", "100.00", category="货款")
    r = client.patch(f"{PAY}/{p['id']}", json={"title": "新事由", "category": "设备采购"}, headers=h)
    assert r.status_code == 200
    assert r.json()["title"] == "新事由" and r.json()["category"] == "设备采购"
    # 只改一个键，其它键原样不动
    r2 = client.patch(f"{PAY}/{p['id']}", json={"remark": "只改备注"}, headers=h)
    assert r2.json()["title"] == "新事由" and r2.json()["amount"] == "100.00"


def test_只看没结清的(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "筛未结供应商")
    paid_off = _new_payable(client, h, s["id"], "已付清", "10.00")
    _pay(client, h, paid_off["id"], "10.00")
    open_one = _new_payable(client, h, s["id"], "还欠着", "20.00")
    rows = client.get(PAY, headers=h, params={"supplier_id": s["id"], "only_open": True}).json()
    assert [r["id"] for r in rows] == [open_one["id"]]


# ---------------- 审计与权限 ----------------
def test_每一步都留痕(client, token_dispatcher, db_session):
    """每一次写都要有审计行，**而且那一条必须指向本次操作**。

    ⛔ 2026-09-25 修掉的两个毛病（根因与 CI 那两个红 job 是同一个：用例靠别人的数据通过）：
    1. 原来删的是**已经有付款的那张应付单**，而规矩是「有付款的应付单不许删」——
       端点**正确地拒绝了**（于是没有日志）。它当时还能绿，是因为 `_logs()` 是**全库按动作码
       查**的，前面某个用例留下的同码日志把它喂饱了（最典型的假绿）。同理最后两步「删供应商」
       也不合法（那家供应商名下还有应付单）。→ 现在：付过款的那张单上只验付款三件事，
       删/恢复另开**没有付款的**应付单与**没有应付单的**供应商。
    2. 每一步都不看状态码 → 被拒了也不知道。现在每步都断言 2xx。
    """
    h = auth_headers(token_dispatcher)
    s = _new_supplier(client, h, "留痕供应商")
    p = _new_payable(client, h, s["id"], "留痕单", "50.00")
    f = _pay(client, h, p["id"], "50.00")

    def call(method: str, url: str, **kw):
        r = getattr(client, method)(url, headers=h, **kw)
        assert r.status_code in (200, 204), f"{method.upper()} {url} → {r.status_code} {r.text}"
        return r

    call("delete", f"{FLOW}/{f['id']}")             # 撤销付款
    call("post", f"{FLOW}/{f['id']}/restore")       # 恢复付款
    call("patch", f"{PAY}/{p['id']}", json={"remark": "改一下"})
    # 删/恢复要另开对象：付过款的应付单不许删（自己的用例 `test_有付款的单不许删`），
    # 有应付单的供应商也不许删（`test_有应付单的供应商不许删`）—— 在这条用例里它们都会被拒。
    p2 = _new_payable(client, h, s["id"], "留痕单-没付过款", "1.00")
    call("delete", f"{PAY}/{p2['id']}")
    call("post", f"{PAY}/{p2['id']}/restore")
    s2 = _new_supplier(client, h, "留痕供应商-空壳")
    call("delete", f"{SUP}/{s2['id']}")
    call("post", f"{SUP}/{s2['id']}/restore")

    for action, ent_id in (
        ("SUPPLIER_UPSERT", s["id"]),
        ("SUPPLIER_PAYABLE_UPSERT", p["id"]),
        ("SUPPLIER_PAYMENT_CREATE", f["id"]),
        ("SUPPLIER_PAYMENT_CANCEL", f["id"]),
        ("SUPPLIER_PAYMENT_RESTORE", f["id"]),
        ("SUPPLIER_PAYABLE_DELETE", p2["id"]),
        ("SUPPLIER_PAYABLE_RESTORE", p2["id"]),
        ("SUPPLIER_DELETE", s2["id"]),
        ("SUPPLIER_RESTORE", s2["id"]),
    ):
        rows = _logs(db_session, action)
        mine = [r for r in rows if str(ent_id) in json.dumps(r, ensure_ascii=False)]
        assert mine, (
            f"{action} 没有为**本次**操作留痕（id={ent_id}）——"
            f"库里同码日志共 {len(rows)} 条，但没有一条指向它"
        )


def test_货主和司机都进不来(client, token_shipper, token_driver):
    """这些端点能动钱（付款会写资金流水），货主/司机不该碰。"""
    for tok in (token_shipper, token_driver):
        h = auth_headers(tok)
        assert client.get(SUP, headers=h).status_code == 403
        assert client.post(SUP, json={"name": "偷偷建的"}, headers=h).status_code == 403
        assert client.get(FLOW, headers=h).status_code == 403


def test_路径里的供应商与请求体对不上要拒绝(client, token_dispatcher):
    """⛔ 别把账挂到别人头上：路径 `/suppliers/1/payables` 而 body 里写 2，必须拒绝。"""
    h = auth_headers(token_dispatcher)
    a = _new_supplier(client, h, "对不上甲")
    b = _new_supplier(client, h, "对不上乙")
    r = client.post(
        f"{SUP}/{a['id']}/payables",
        json={"supplier_id": b["id"], "title": "挂错人", "amount": "10", "doc_date": "2026-09-01"},
        headers=h,
    )
    assert r.status_code == 400 and "对不上" in r.json()["detail"]


def test_付款记录取不到别人的流水(client, token_dispatcher, db_session):
    """`cash_flows` 是所有收付的总账：按 id 撤销时必须认出"这不是一笔付款"。"""
    from datetime import date

    h = auth_headers(token_dispatcher)
    # 直接造一行**别的业务**的流水（开销/结算那一类）
    other = CashFlow(
        flow_date=date(2026, 9, 2), direction="out", amount=Decimal("9.99"),
        party_type="expense", party_id=1, party_name="加油", channel="cash",
        biz_type="EXPENSE_FUEL", doc_id=1, note="不是付款",
    )
    db_session.add(other)
    db_session.commit()
    assert client.delete(f"{FLOW}/{other.id}", headers=h).status_code == 404
    assert client.post(f"{FLOW}/{other.id}/restore", headers=h).status_code == 404


def test_应付单必须属于一个活着的供应商(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    r = client.post(f"{SUP}/999999/payables", json={"supplier_id": 999999, "title": "x", "amount": "1", "doc_date": "2026-09-01"}, headers=h)
    assert r.status_code == 404
