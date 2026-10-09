"""TB-08 / BUG-0024 回归：**建单当刻就把明细锁住**，两种流失原因分开报。

## 缺陷长什么样（2026-10-10 测试会话实测，证据 _tmp/test_round3/evidence_TB08_settlement_dup.txt）

driver_id=3 / 2026-06 / 明细 bill id=12（22.00 元）：连续两次
`POST /api/v1/driver-settlements {"driver_id":3,"settle_type":"piece","month":"2026-06"}`
两次都 200，两张草稿 #59 / #60 的 `bill_ids` 都是 [12]、金额都是 22.00 —— 而那时
明细仍是 `open` / `settled_doc_id=NULL`。确认 #59 → 200；确认 #60 →
400「这张结算单锁定的 1 笔明细里有 1 笔已经不在了（被删除或已被别的结算单占用），请作废后重新结算」。

三处病根：
1. `create_settlement` 只写单、**一行明细都不碰** —— 而 `api/v1/driver_settlements.py:93`
   的注释写的是「建结算单＝把一批「待结」明细锁进一张单子（…已经不能再被第二张单占用）」，
   **注释与行为正好相反**；
2. 于是「锁」实际发生在 `confirm` 那一刻 ⇒ 冲突要等到用户点确认才炸，且两张废单已经躺在列表里；
3. 报错把「被别的结算单占用」与「明细已被删除」糊成一句 —— 用户以为明细被删了，
   实际是被另一张草稿锁着（去作废那张单就行）。

⚠️ 月份一律用 2018-xx（冷门老月份，只有 test_cash_flow_breakdown.py 用了 2018-01）：
结算单是**按月 + 按司机**取数的，跟别的用例撞月就会串味。⛔ 不能用未来月份 ——
`validate_month` 的上界是本月。

## 本文件钉住七件事（前五条在修复前是红的）

1. 同一笔明细不能被两张草稿单同时锁住（建单当刻写 `settled_doc_id`，状态仍是 `open`）；
2. 确认失败时把两种原因**分开说**：被别的结算单占用（附单号）/ 已被删除（附明细号）；
3. 作废草稿单把锁放回待结（否则那笔明细这辈子结不掉）；
4. 老草稿（没有 `bill_ids`，2026-10-03 之前的历史数据）按月重取时**也不许**抢别人锁住的明细；
5. 保留任务已作废（`CANCELLED`）的明细，作废草稿单时**不许复活**成待结；
6. 不同月份各自的草稿单互不影响（锁不是全局的）；
7. 确认 → 付款的正常顺路还在（`settled_doc_id` / 状态 / 付款时间都对）。
"""

from __future__ import annotations

from decimal import Decimal

from app.models import DriverBill, DriverSettlement
from app.models.enums import DriverBillStatus, DriverBillType, SettlementStatus
from tests.conftest import auth_headers

M_DUP = "2018-02"        # ① 两张草稿单抢同一笔明细
M_SPLIT = "2018-03"      # ② 两种流失原因分开报
M_RELEASE = "2018-04"    # ③ 作废解锁
M_LEGACY = "2018-06"     # ④ 老草稿按月重取
M_RETENTION = "2018-07"  # ⑤ 保留任务作废不许复活
M_A = "2018-09"          # ⑥ 两个月份互不影响
M_B = "2018-10"
M_HAPPY = "2018-08"      # ⑦ 确认 → 付款顺路


def _mk_bill(db_session, driver_id: int, month: str, amount: str, **kw) -> DriverBill:
    """插一条待结明细（缺省是 `order_id` 为空的历史孤儿 —— 建单取数照样收它）。"""
    row = DriverBill(
        driver_id=driver_id,
        bill_type=DriverBillType.PIECE,
        order_id=kw.get("order_id"),
        month=month,
        amount=Decimal(amount),
        status=kw.get("status", DriverBillStatus.OPEN),
        note="TB-08 锁探针",
    )
    db_session.add(row)
    db_session.commit()
    return row


def _create(client, h, driver_id: int, month: str, amount: str | None = None):
    body: dict = {"driver_id": driver_id, "settle_type": "piece", "month": month}
    if amount is not None:
        body["amount"] = amount
    return client.post("/api/v1/driver-settlements", json=body, headers=h)


def _act(client, h, sid: int, action: str, **extra):
    return client.patch(
        f"/api/v1/driver-settlements/{sid}", json={"action": action, **extra}, headers=h
    )


def _bill(db_session, bid: int) -> DriverBill:
    db_session.expire_all()
    return db_session.get(DriverBill, bid)


def test_同一笔明细不能被两张草稿单同时锁住(client, db_session, users, token_dispatcher):
    h = auth_headers(token_dispatcher)
    driver = users["driver"]
    bill = _mk_bill(db_session, driver.id, M_DUP, "22.00")

    r1 = _create(client, h, driver.id, M_DUP)
    assert r1.status_code == 200, r1.text
    doc = r1.json()
    assert doc["bill_ids"] == [bill.id], doc
    assert doc["amount"] == "22.00", doc

    # 建单当刻就该锁住：`settled_doc_id` 已经写上，而**钱还没出**（状态仍是 open）
    row = _bill(db_session, bill.id)
    assert row.settled_doc_id == doc["id"], "建单当刻没锁：第二张单还会把这笔明细收进去"
    assert row.status == DriverBillStatus.OPEN, "建单不该改动明细状态（钱未出）"

    # 第二张草稿单：同一笔明细不能再被收走 —— 建单时就该被挡下，并说清被谁锁着
    r2 = _create(client, h, driver.id, M_DUP)
    assert r2.status_code == 400, (
        f"同一笔明细被两张草稿单同时锁住了（HTTP {r2.status_code}）：{r2.text}"
    )
    detail = r2.json()["detail"]
    assert f"#{doc['id']}" in detail, f"报错没说是哪张单锁着：{detail}"
    assert "已经被别的结算单锁住" in detail, detail

    # 第二张单**根本没建出来**
    assert db_session.query(DriverSettlement).filter_by(month=M_DUP).count() == 1


def test_确认时报错要把被占用与已删除分开说(client, db_session, users, token_dispatcher):
    h = auth_headers(token_dispatcher)
    driver = users["driver"]
    occ = _mk_bill(db_session, driver.id, M_SPLIT, "10.00")
    dele = _mk_bill(db_session, driver.id, M_SPLIT, "12.00")

    r1 = _create(client, h, driver.id, M_SPLIT)
    assert r1.status_code == 200, r1.text
    doc = r1.json()
    assert sorted(doc["bill_ids"]) == sorted([occ.id, dele.id]), doc

    # 人为制造两种流失：一条被别的结算单占用（历史竞态），一条被删掉
    db_session.expire_all()
    o = db_session.get(DriverBill, occ.id)
    o.status = DriverBillStatus.SETTLED
    o.settled_doc_id = 999999
    db_session.delete(db_session.get(DriverBill, dele.id))
    db_session.commit()

    r2 = _act(client, h, doc["id"], "confirm")
    assert r2.status_code == 400, r2.text
    d = r2.json()["detail"]
    assert "已经不在了" in d and "请作废后重新结算" in d, d
    assert "被别的结算单占用" in d, f"没说是「被占用」：{d}"
    assert "#999999" in d, f"没附上是哪张单占用：{d}"
    assert "已被删除" in d and str(dele.id) in d, f"没说是「被删除」并指出明细号：{d}"
    assert "被删除或已被别的结算单占用" not in d, f"两种原因还被糊在一句里：{d}"


def test_作废草稿单把锁放回待结(client, db_session, users, token_dispatcher):
    h = auth_headers(token_dispatcher)
    driver = users["driver"]
    bill = _mk_bill(db_session, driver.id, M_RELEASE, "30.00")

    r1 = _create(client, h, driver.id, M_RELEASE)
    assert r1.status_code == 200, r1.text
    did = r1.json()["id"]
    assert _bill(db_session, bill.id).settled_doc_id == did

    r2 = _act(client, h, did, "cancel")
    assert r2.status_code == 200, r2.text
    row = _bill(db_session, bill.id)
    assert row.settled_doc_id is None, "作废后锁没放回去：这笔明细再也结不了"
    assert row.status == DriverBillStatus.OPEN

    # 放回去之后，新的草稿单能正常收走它
    r3 = _create(client, h, driver.id, M_RELEASE)
    assert r3.status_code == 200, r3.text
    assert r3.json()["bill_ids"] == [bill.id], r3.json()


def test_老草稿按月重取也不许抢别人锁住的明细(client, db_session, users, token_dispatcher):
    """2026-10-03（BUG-0007）之前建的老草稿没有 `bill_ids`，确认时走「按月重取」老路。"""
    h = auth_headers(token_dispatcher)
    driver = users["driver"]
    bill = _mk_bill(db_session, driver.id, M_LEGACY, "22.00")

    r1 = _create(client, h, driver.id, M_LEGACY)
    assert r1.status_code == 200, r1.text
    did = r1.json()["id"]

    legacy = DriverSettlement(
        driver_id=driver.id,
        settle_type=DriverBillType.PIECE,
        month=M_LEGACY,
        amount=Decimal("22.00"),
        status=SettlementStatus.DRAFT,
        order_ids=[],
        bill_ids=None,  # 老单：没有这份清单
        adjustment=Decimal("0"),
        note="老草稿（锁探针）",
    )
    db_session.add(legacy)
    db_session.commit()

    r2 = _act(client, h, legacy.id, "confirm")
    assert r2.status_code == 400, (
        f"老草稿按月重取把别人锁住的明细抢走了（HTTP {r2.status_code}）：{r2.text}"
    )
    row = _bill(db_session, bill.id)
    assert row.status == DriverBillStatus.OPEN and row.settled_doc_id == did


def test_保留任务已作废的明细_作废草稿单时不许复活(client, db_session, users, token_dispatcher):
    """订单过保留期被物理清理时，`data_retention` 会把还 OPEN 的明细翻成 CANCELLED。"""
    h = auth_headers(token_dispatcher)
    driver = users["driver"]
    bill = _mk_bill(db_session, driver.id, M_RETENTION, "18.00")

    r1 = _create(client, h, driver.id, M_RETENTION)
    assert r1.status_code == 200, r1.text
    did = r1.json()["id"]

    db_session.expire_all()
    row = db_session.get(DriverBill, bill.id)
    row.status = DriverBillStatus.CANCELLED  # 保留任务：作废，但 settled_doc_id 不动
    db_session.commit()

    r2 = _act(client, h, did, "confirm")
    assert r2.status_code == 400, f"明细已被保留任务作废，确认不该能过：{r2.text}"

    r3 = _act(client, h, did, "cancel")
    assert r3.status_code == 200, r3.text
    row = _bill(db_session, bill.id)
    assert row.status == DriverBillStatus.CANCELLED, (
        "作废草稿单把已被保留任务作废的明细复活成待结了（会凭空多出一笔应付）"
    )


def test_两个月份的草稿单各自锁各自的(client, db_session, users, token_dispatcher):
    h = auth_headers(token_dispatcher)
    driver = users["driver"]
    a = _mk_bill(db_session, driver.id, M_A, "11.00")
    b = _mk_bill(db_session, driver.id, M_B, "13.00")

    ra = _create(client, h, driver.id, M_A)
    rb = _create(client, h, driver.id, M_B)
    assert (ra.status_code, rb.status_code) == (200, 200), (ra.text, rb.text)
    assert ra.json()["bill_ids"] == [a.id]
    assert rb.json()["bill_ids"] == [b.id]
    assert _bill(db_session, a.id).settled_doc_id == ra.json()["id"]
    assert _bill(db_session, b.id).settled_doc_id == rb.json()["id"]


def test_确认到付款的顺路还在(client, db_session, users, token_dispatcher):
    h = auth_headers(token_dispatcher)
    driver = users["driver"]
    bill = _mk_bill(db_session, driver.id, M_HAPPY, "40.00")

    r1 = _create(client, h, driver.id, M_HAPPY)
    assert r1.status_code == 200, r1.text
    did = r1.json()["id"]

    r2 = _act(client, h, did, "confirm")
    assert r2.status_code == 200, r2.text
    row = _bill(db_session, bill.id)
    assert row.status == DriverBillStatus.SETTLED and row.settled_doc_id == did

    r3 = _act(client, h, did, "pay", method="bank")
    assert r3.status_code == 200, r3.text
    db_session.expire_all()
    doc = db_session.get(DriverSettlement, did)
    assert doc.status == SettlementStatus.PAID and doc.paid_at is not None
