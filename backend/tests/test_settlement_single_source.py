"""BUG-0007 回归：结算单的金额与明细必须**同源**（建单当刻定死，确认 / 付款 / 作废照它走）。

## 缺陷长什么样（2026-10-03 用户拍板：「金钱对不上账会出现问题的，这个必须要修」）

`create_settlement` 按「司机 + 月 + 类型 + OPEN + 订单未软删」取明细 —— 其中
`or_(DriverBill.order_id.is_(None), ...)` 让 `order_id` 为空的历史孤儿账单**也算进金额**；
`confirm_settlement` 却按 `order_ids` 重取，孤儿没有单号 ⇒ 永远取不回来 ⇒
`amount` 比明细合计多出孤儿那几笔，确认接口必然 400：

    {"detail":"结算单金额 970.00 与明细合计 940.00 不一致，请核对"}

（全量套件里那 3 条长期红：`test_money_audit_trail.py` / `test_full_loop_regression.py` /
`test_timezone_family.py`，差额 30.00 就是另一条用例留在库里的孤儿明细。）
真机上的表现是**那张结算单永远确认不了、司机这笔钱结不掉**，只能改库。

## 本文件钉住六件事

1. 孤儿明细建单当刻被锁定、确认能过、付得掉（钱不再卡死）；
2. 明细在确认前被抢走 → 明确 400，不许拿旧金额硬确认；
3. 建单之后**新出现**的明细不进这一单（确认不再按月重取 —— 病根的另一半）；
4. 手工改额记 `adjustment` 差额，恒等式 `amount == 明细合计 + adjustment` 成立；
   金额被绕过接口改坏时，报错里要点出那笔手工调整；
5. 老草稿（没有 `bill_ids`）仍走老路（兼容既有数据）；
6. 作废解锁不再挂 `order_ids` 门闩（历史竞态里的「作废单 + 明细已锁」解得开）。

⚠️ 月份一律用 2019-xx（冷门老月份）：结算单是**按月取数**的，跟别的用例撞月就会串味
（上面那 3 条红的来历正是如此）。⛔ 不能用未来月份 —— `validate_month` 的上界是本月，
用它换隔离会被 422 挡在门口（2026-10-03 实测，当时的写法是 2031-xx）。
"""

from __future__ import annotations

from decimal import Decimal

from app.models import DriverBill, DriverSettlement
from app.models.enums import DriverBillStatus, DriverBillType, SettlementStatus
from tests.conftest import auth_headers


def _mk_orphan(db_session, driver_id: int, month: str, amount: str) -> int:
    """插一条 `order_id` 为空的历史孤儿账单（生产路径造不出来，只有历史数据 / 测试有）。"""
    row = DriverBill(
        driver_id=driver_id,
        bill_type=DriverBillType.PIECE,
        order_id=None,  # ⛔ 病根就是这一列：确认时按单号重取，永远取不到它
        month=month,
        amount=Decimal(amount),
        status=DriverBillStatus.OPEN,
        note="孤儿明细探针（BUG-0007）",
    )
    db_session.add(row)
    db_session.commit()
    return int(row.id)


def _mk_order(client, h, shipper_id: int) -> int:
    """真建一张订单 —— `settleable_bills` 会 outerjoin orders，单号必须真实存在。"""
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [{"product_name_snapshot": "结算同源探针", "quantity": 1, "unit_price": "66"}],
            "address_detail": "结算同源探针",
            "delivery_description": "结算同源探针",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _mk_bill(db_session, driver_id: int, order_id: int, month: str, amount: str) -> int:
    """插一条**带单号**的 OPEN PIECE 明细（生产是送达那一刻生成的，这里只关心确认时取不取得到）。"""
    row = DriverBill(
        driver_id=driver_id,
        bill_type=DriverBillType.PIECE,
        order_id=order_id,
        month=month,
        amount=Decimal(amount),
        status=DriverBillStatus.OPEN,
        note="带单号明细探针（BUG-0007）",
    )
    db_session.add(row)
    db_session.commit()
    return int(row.id)


def _create(client, h, driver_id: int, month: str, amount: str | None = None):
    body: dict = {"driver_id": driver_id, "month": month, "settle_type": "piece"}
    if amount is not None:
        body["amount"] = amount
    return client.post("/api/v1/driver-settlements", json=body, headers=h)


def _act(client, h, sid: int, action: str, **extra):
    return client.patch(f"/api/v1/driver-settlements/{sid}", json={"action": action, **extra}, headers=h)


def test_孤儿明细建单当刻锁定_确认付得掉(client, db_session, users, token_dispatcher):
    """孤儿明细不再让这张单永远确认不了 —— 钱能结掉。"""
    h = auth_headers(token_dispatcher)
    did = users["driver"].id
    bid = _mk_orphan(db_session, did, "2019-01", "30.00")

    r = _create(client, h, did, "2019-01")
    assert r.status_code in (200, 201), r.text
    sid = int(r.json()["id"])
    # 建单那一刻就把"覆盖哪几行"写下来（含没有单号的孤儿）
    assert r.json()["bill_ids"] == [bid], r.text
    assert not (r.json()["order_ids"] or []), f"孤儿没有单号可列：{r.text}"
    assert Decimal(str(r.json()["amount"])) == Decimal("30.00")

    ok = _act(client, h, sid, "confirm")
    assert ok.status_code == 200, f"孤儿明细必须能被确认（旧代码在这里 400）：{ok.text}"
    db_session.expire_all()
    row = db_session.get(DriverBill, bid)
    assert row.status == DriverBillStatus.SETTLED and row.settled_doc_id == sid

    paid = _act(client, h, sid, "pay", method="cash")
    assert paid.status_code == 200, paid.text
    db_session.expire_all()
    assert db_session.get(DriverSettlement, sid).status == SettlementStatus.PAID


def test_确认前明细被抢走就明确报错(client, db_session, users, token_dispatcher):
    """建单之后明细被别的结算单占用 → 说清楚"已经不在了"，不许拿旧金额硬确认。"""
    h = auth_headers(token_dispatcher)
    did = users["driver"].id
    bid = _mk_orphan(db_session, did, "2019-02", "88.00")
    created = _create(client, h, did, "2019-02")
    assert created.status_code in (200, 201), created.text
    sid = int(created.json()["id"])

    row = db_session.get(DriverBill, bid)
    row.status = DriverBillStatus.SETTLED
    row.settled_doc_id = 999_999  # 被别的结算单抢走了
    db_session.commit()

    bad = _act(client, h, sid, "confirm")
    assert bad.status_code == 400, bad.text
    detail = bad.json()["detail"]
    assert "已经不在了" in detail and "请作废后重新结算" in detail, detail
    db_session.expire_all()
    assert db_session.get(DriverSettlement, sid).status == SettlementStatus.DRAFT


def test_建单之后新增的明细不进这一单(client, db_session, users, token_dispatcher):
    """确认只认建单那一刻锁定的明细 —— 不再按月重取（旧代码会拿 100.00 与 30.00 判对不上）。"""
    h = auth_headers(token_dispatcher)
    did = users["driver"].id
    first = _mk_orphan(db_session, did, "2019-03", "30.00")
    created = _create(client, h, did, "2019-03")
    assert created.status_code in (200, 201), created.text
    sid = int(created.json()["id"])
    later = _mk_orphan(db_session, did, "2019-03", "70.00")  # 建单之后才出现的明细

    ok = _act(client, h, sid, "confirm")
    assert ok.status_code == 200, ok.text
    db_session.expire_all()
    assert db_session.get(DriverBill, first).status == DriverBillStatus.SETTLED
    assert db_session.get(DriverBill, later).status == DriverBillStatus.OPEN, (
        "建单之后新增的明细不许被这张单收走（它还 OPEN，留给下一张单）"
    )


def test_手工改额记差额_确认与付款都认它(client, db_session, users, token_dispatcher):
    """手工改额 = 记下差额，不是把金额硬改掉（`amount == 明细合计 + adjustment`）。"""
    h = auth_headers(token_dispatcher)
    did = users["driver"].id
    _mk_orphan(db_session, did, "2019-04", "80.00")
    r = _create(client, h, did, "2019-04", amount="100.00")
    assert r.status_code in (200, 201), r.text
    sid = int(r.json()["id"])
    assert Decimal(str(r.json()["amount"])) == Decimal("100.00")
    assert Decimal(str(r.json()["adjustment"])) == Decimal("20.00"), r.text

    assert _act(client, h, sid, "confirm").status_code == 200
    paid = _act(client, h, sid, "pay", method="cash")
    assert paid.status_code == 200, paid.text


def test_金额被绕过接口改坏_报错要点出手工调整(client, db_session, users, token_dispatcher):
    """金额与「明细 + 差额」对不上时必须拦住，并且把差额写进那句话（否则没人看得懂差在哪）。"""
    h = auth_headers(token_dispatcher)
    did = users["driver"].id
    _mk_orphan(db_session, did, "2019-07", "80.00")
    created = _create(client, h, did, "2019-07", amount="100.00")
    assert created.status_code in (200, 201), created.text
    sid = int(created.json()["id"])
    row = db_session.get(DriverSettlement, sid)
    row.amount = Decimal("95.00")  # 绕过接口硬改金额（明细一动没动）
    db_session.commit()

    bad = _act(client, h, sid, "confirm")
    assert bad.status_code == 400, bad.text
    detail = bad.json()["detail"]
    assert "与明细合计 80.00 不一致" in detail and "手工调整 +20.00" in detail, detail
    # 报错之后这张单还活着：改回来就能确认（不是被判死）
    db_session.expire_all()
    row = db_session.get(DriverSettlement, sid)
    row.amount = Decimal("100.00")
    db_session.commit()
    assert _act(client, h, sid, "confirm").status_code == 200


def test_老草稿没有_bill_ids_仍走老路(client, db_session, users, token_dispatcher):
    """老草稿（`bill_ids` 为空）走原来那条按月取数的路 —— 既有数据不许被判死。"""
    h = auth_headers(token_dispatcher)
    did = users["driver"].id
    b1 = _mk_orphan(db_session, did, "2019-05", "11.00")
    b2 = _mk_orphan(db_session, did, "2019-05", "22.00")
    s = DriverSettlement(
        driver_id=did,
        settle_type=DriverBillType.PIECE,
        month="2019-05",
        amount=Decimal("33.00"),
        status=SettlementStatus.DRAFT,
        order_ids=[],
        bill_ids=None,
        adjustment=Decimal("0"),
        operator_id=None,
        note="老草稿探针（BUG-0007）",
    )
    db_session.add(s)
    db_session.commit()

    ok = _act(client, h, int(s.id), "confirm")
    assert ok.status_code == 200, ok.text
    db_session.expire_all()
    assert {
        db_session.get(DriverBill, b1).status,
        db_session.get(DriverBill, b2).status,
    } == {DriverBillStatus.SETTLED}


def test_作废解锁不再看_order_ids(client, db_session, users, token_dispatcher):
    """`cancel` 必须把它锁住的明细放回 OPEN —— 哪怕这张单一个单号都没有。

    历史竞态留下的「CANCELLED + 明细已 SETTLED」在旧门闩（`settle_type == PIECE and order_ids`）
    下永远解不开：那批账单既不在 OPEN 里、也不可付，司机这笔钱只能改库。
    """
    h = auth_headers(token_dispatcher)
    did = users["driver"].id
    bid = _mk_orphan(db_session, did, "2019-06", "44.00")
    created = _create(client, h, did, "2019-06")
    assert created.status_code in (200, 201), created.text
    sid = int(created.json()["id"])
    s = db_session.get(DriverSettlement, sid)
    assert not (s.order_ids or []), "孤儿明细建出来的单一个单号都没有 —— 旧门闩正是在这种单上失效"

    row = db_session.get(DriverBill, bid)  # 模拟"明细已被这张单锁住"的现场
    row.status = DriverBillStatus.SETTLED
    row.settled_doc_id = sid
    db_session.commit()

    assert _act(client, h, sid, "cancel").status_code == 200
    db_session.expire_all()
    row = db_session.get(DriverBill, bid)
    assert row.status == DriverBillStatus.OPEN and row.settled_doc_id is None
def test_混着单号明细与孤儿明细_确认不再少算(client, db_session, users, token_dispatcher):
    """最像生产现场的一单：同一个月里**既有**带单号的明细、**又有**孤儿明细。

    旧代码里 `order_ids` 非空 ⇒ 确认走 order_ids 分支 ⇒ 只算得到带单号那笔，
    而 `amount` 是把孤儿也算进去的 ⇒ 恒等式永远差孤儿那几笔 ⇒ 400，这张单再也确认不了。
    （全量套件里那条「结算单金额 970.00 与明细合计 940.00 不一致」正是这个形状：差额 30.00。）
    """
    h = auth_headers(token_dispatcher)
    did = users["driver"].id
    oid = _mk_order(client, h, users["shipper"].id)
    bid_order = _mk_bill(db_session, did, oid, "2019-08", "50.00")
    bid_orphan = _mk_orphan(db_session, did, "2019-08", "30.00")

    created = _create(client, h, did, "2019-08")
    assert created.status_code in (200, 201), created.text
    body = created.json()
    sid = int(body["id"])
    assert body["order_ids"] == [oid], body
    assert sorted(body["bill_ids"]) == sorted([bid_order, bid_orphan]), body
    assert Decimal(str(body["amount"])) == Decimal("80.00"), body

    ok = _act(client, h, sid, "confirm")
    assert ok.status_code == 200, f"同一月混着孤儿明细时必须确认得过（旧代码在这里 400）：{ok.text}"
    db_session.expire_all()
    for b in (bid_order, bid_orphan):
        row = db_session.get(DriverBill, b)
        assert row.status == DriverBillStatus.SETTLED and row.settled_doc_id == sid, f"明细 {b} 没被这张单锁住"
