"""逐债务人应收余额与账龄（FEAT-0015）：时点账 / 账龄桶 / 预收 / 信用额度。

## 用户拍板的口径（docs/changes/FEAT-0015.md）
① 一行一个**债务人**（挂账单位 / 货主 / 临时货主），不是 customers 档案 ——
   订单与客户档案之间隔着 `customers.arrears_unit_id` 这条**可空非唯一**的映射，
   按档案分组必然出现"同一个客户两个答案"；
② 这是**时点账**（as of）：报表日往前调 = 「那些天之前送达的单，到今天还欠着多少」，
   窗口起点不参与余额（那是"这一段发生了多少"的报表的活）；
③ 欠款 = 应收 − 已收 + 已退；**负数是预收**，预收不进账龄桶；
④ 账龄从**最早一次记账**（那张应收凭证的 entry_date）起算，红冲只冲金额、不冲起算点；
⑤ 信用额度长在**挂账单位**上，NULL = 不限额（⛔ 不是 0）；超限只是提示，不拦收单。

## 这个文件守七件事（每一条都是「不报错但会错」的形状）
1. 挂账送达的单必须出现在报表里，且**逐分**等于订单上的欠款（含 include_orders 的逐单明细）；
2. **行余额 == Σ四个桶 − 预收**：正欠款进桶、预收单独一列，两边⛔ 不许各算各的；
3. 桶的边界按 **30/31/60/61/90/91 天**切（差一天就换桶，这是催收口径）；
4. **报表日往前调要真的排除那天之后送达的单**，否则"时点"是假的、用户拿它当历史账看；
5. 预收（已收 > 应收）⛔ 不许混进桶里，否则"欠款"与"该催多少"互相矛盾；
6. 不限额（NULL）**不等于**额度 0：credit_available 必须是 null、over_limit 必须是 false，
   而显式设成 0 之后必须**真的**超限（0 是一个会咬人的额度）；
7. 与既有口径**对拍**：本报表的合计欠款必须等于营业纵览（/reports/turnover）的 arrears_total。
"""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import text
from starlette.testclient import TestClient

from app.core.business_time import business_today
from app.models import ArrearsUnit, CashFlow
from app.models.enums import CashFlowBizType, CashFlowDirection
from app.services.reports.balance_query import BUCKET_KEYS, bucket_of
from tests.conftest import auth_headers

ORD = "/api/v1/orders"
BAL = "/api/v1/reports/customer-balances"
TURN = "/api/v1/reports/turnover"
UNITS = "/api/v1/arrears-units"


def _uniq(prefix: str) -> str:
    return f"{prefix}-{random.randint(100000, 999999)}"


def _num(v) -> Decimal:
    """金额一律按字符串读：接口上的 Decimal 是两位小数的字符串。"""
    return Decimal(str(v))


def _cleanup(db_session, order_ids: list[int], unit_ids: list[int]) -> None:
    """把自己造的行收掉（测试库按 worker 共享，端点会 commit）。

    删的顺序按外键：先子女表，再 orders，最后挂账单位。⚠️ **必须做** ——
    这份报表把**全库**已送达未收款的单都算进来，留下脏数据会污染后面所有用例。
    """
    for oid in order_ids:
        for table in ("cash_flows", "ledgers", "driver_bills", "inventory_movements",
                      "operation_logs", "order_products"):
            db_session.execute(text(f"delete from {table} where order_id = :o"), {"o": oid})
        db_session.execute(text("delete from orders where id = :o"), {"o": oid})
    for uid in unit_ids:
        db_session.execute(text("delete from arrears_units where id = :u"), {"u": uid})
    db_session.commit()


def _unit(client: TestClient, token_dispatcher: str, name: str, **kw) -> dict:
    r = client.post(UNITS, json={"name": name, **kw}, headers=auth_headers(token_dispatcher))
    assert r.status_code in (200, 201), r.text
    return r.json()


def _arrears_order(client: TestClient, db_session, token_dispatcher: str, token_driver: str,
                   users: dict, *, amount: str = "100.00", unit_id: int | None = None,
                   temp_name: str | None = None) -> int:
    """建单 → 派给司机 → 接单 →（可选）挂账到某个单位 → 司机按**挂账**送达。返回订单 id。"""
    users["driver"].billing_mode = "piece"
    db_session.commit()
    body: dict = {
        "lines": [{"product_name_snapshot": "客户欠款探针货", "quantity": 1, "unit_price": amount}],
    }
    if temp_name:
        body["temp_shipper_name"] = temp_name
    else:
        body["shipper_id"] = users["shipper"].id
    r = client.post(ORD, json=body, headers=auth_headers(token_dispatcher))
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    a = client.post(f"{ORD}/{oid}/assign",
                    json={"driver_id": users["driver"].id, "collect_cash": True,
                          "freight_fee": "60.00"},
                    headers=auth_headers(token_dispatcher))
    assert a.status_code in (200, 201, 204), a.text
    k = client.post(f"{ORD}/{oid}/driver-ack", headers=auth_headers(token_driver))
    assert k.status_code in (200, 201, 204), k.text
    if unit_id is not None:
        c = client.post(f"{ORD}/{oid}/charge", json={"arrears_unit_id": unit_id},
                        headers=auth_headers(token_dispatcher))
        assert c.status_code == 200, c.text
    done = client.post(f"{ORD}/{oid}/complete",
                       json={"payment": "arrears",
                             "delivery_photo_urls": ["/static/uploads/delivery/bal.jpg"]},
                       headers=auth_headers(token_driver))
    assert done.status_code in (200, 201, 204), done.text
    return oid


def _report(client: TestClient, token_dispatcher: str, *, day: str | None = None,
            include_orders: bool = False) -> dict:
    d = day or business_today().isoformat()
    r = client.get(BAL, params={"mode": "day", "date": d,
                                "include_orders": "true" if include_orders else "false"},
                   headers=auth_headers(token_dispatcher))
    assert r.status_code == 200, r.text
    return r.json()


def _row(data: dict, unit_id: int) -> dict | None:
    for row in data["rows"]:
        if row["unit_id"] == unit_id:
            return row
    return None


def _assert_invariants(data: dict) -> None:
    """模型 docstring 里写死的三条恒等式：逐行 + 合计都要真的成立。"""
    total = Decimal("0")
    bucket_sum = {k: Decimal("0") for k in BUCKET_KEYS}
    for row in data["rows"]:
        buckets = sum((_num(row["buckets"][k]) for k in BUCKET_KEYS), Decimal("0"))
        assert _num(row["balance"]) == buckets - _num(row["prepaid"]), (
            f"行「{row['name']}」余额 != Σ桶 − 预收："
            f"{row['balance']} vs {buckets} − {row['prepaid']}"
        )
        if row["limit"] is None:
            assert row["credit_available"] is None, "不限额的行不许给出一个假的可用额度"
            assert row["over_limit"] is False, "不限额的行不可能超限"
        else:
            assert _num(row["credit_available"]) == (
                _num(row["limit"]) - _num(row["credit_used"])
            ), "可用额度 != 额度 − 已用"
        assert row["over_limit"] is (_num(row["credit_used"]) > _num(row["limit"])
                                     if row["limit"] is not None else False)
        total += _num(row["balance"])
        for k in BUCKET_KEYS:
            bucket_sum[k] += _num(row["buckets"][k])
    assert _num(data["totals"]["balance"]) == total, "合计欠款 != 逐行相加"
    for k in BUCKET_KEYS:
        assert _num(data["totals"]["buckets"][k]) == bucket_sum[k], f"{k} 桶的合计对不上"


def test_挂账送达的单出现在客户欠款里_且逐分对得上(
    client: TestClient, db_session, token_dispatcher: str, token_driver: str, users: dict
) -> None:
    """一行一个债务人：挂账到单位的单必须挂在**这个单位**名下，金额与订单上的欠款逐分相等。"""
    unit = _unit(client, token_dispatcher, _uniq("欠款单位"), phone="13800002222")
    oid = _arrears_order(client, db_session, token_dispatcher, token_driver, users,
                         unit_id=unit["id"])
    try:
        data = _report(client, token_dispatcher, include_orders=True)
        _assert_invariants(data)
        today = business_today().isoformat()
        assert data["as_of"] == today, f"as_of 必须是业务当地日（实际 {data['as_of']}）"
        row = _row(data, unit["id"])
        assert row is not None, "刚刚挂账送达的单没有出现在客户欠款报表里"
        assert row["kind"] == "unit" and row["name"] == unit["name"]
        assert row["phone"] == "13800002222", "催收要打的电话必须在行上"
        assert _num(row["balance"]) == Decimal("100.00")
        assert _num(row["buckets"]["0_30"]) == Decimal("100.00"), "今天送达的单在第 1 个桶"
        assert _num(row["prepaid"]) == Decimal("0.00")
        assert row["oldest_days"] == 0 and row["order_count"] == 1
        (item,) = row["orders"]
        assert item["order_id"] == oid and item["bucket"] == "0_30" and item["days"] == 0
        assert _num(item["arrears"]) == Decimal("100.00")
        assert item["anchor"] == today, "账龄从最早一次记账起算（今天送达 → 今天记账）"
        assert item["delivered_on"] == today
        # 与既有口径对拍：营业纵览的 arrears_total 是同一批单的同一个数。
        t = client.get(TURN, params={"mode": "day", "date": today,
                                     "date_from": "1970-01-01", "date_to": today},
                       headers=auth_headers(token_dispatcher))
        assert t.status_code == 200, t.text
        assert _num(t.json()["arrears_total"]) == _num(data["totals"]["balance"]), (
            "客户欠款合计与营业纵览的挂账合计不是同一个数 —— 同一批单两个答案"
        )
    finally:
        _cleanup(db_session, [oid], [unit["id"]])


def test_账龄桶的边界按三十天切() -> None:
    """差一天就换桶：这是催收口径（30 / 60 / 90 天），⛔ 不许写成"大约"。"""
    assert [bucket_of(d) for d in (0, 1, 30)] == ["0_30", "0_30", "0_30"]
    assert [bucket_of(d) for d in (31, 60)] == ["31_60", "31_60"]
    assert [bucket_of(d) for d in (61, 90)] == ["61_90", "61_90"]
    assert [bucket_of(d) for d in (91, 365, 4000)] == ["over_90", "over_90", "over_90"]
    assert bucket_of(-5) == "0_30", "时钟偏差（锚点晚于报表日）算最年轻一档，⛔ 不出负数"


def test_预收单列不进桶_余额等于各桶之和减预收(
    client: TestClient, db_session, token_dispatcher: str, token_driver: str, users: dict
) -> None:
    """同一个单位上「欠 100」与「多收 50」：欠款净额 50、桶里只有 100、预收 50。"""
    unit = _unit(client, token_dispatcher, _uniq("预收单位"))
    owing = _arrears_order(client, db_session, token_dispatcher, token_driver, users,
                           amount="100.00", unit_id=unit["id"])
    over = _arrears_order(client, db_session, token_dispatcher, token_driver, users,
                          amount="100.00", unit_id=unit["id"])
    try:
        # 手工补一笔比应收还多的进账（150 > 100）＝ 预收 50。
        # 走 ORM 直接写：收款端点没有"多收"这条路（真实的多收来自历史导入 / 退款前收款）。
        db_session.add(CashFlow(
            flow_date=business_today(), direction=CashFlowDirection.IN,
            amount=Decimal("150.00"), party_type="customer", party_name=unit["name"],
            channel="transfer", biz_type=CashFlowBizType.RECEIPT_PREPAID, order_id=over,
            note="预收探针",
        ))
        db_session.commit()
        data = _report(client, token_dispatcher)
        _assert_invariants(data)
        row = _row(data, unit["id"])
        assert row is not None
        assert row["order_count"] == 2
        assert _num(row["balance"]) == Decimal("50.00"), "余额 = 欠 100 − 预收 50"
        assert _num(row["prepaid"]) == Decimal("50.00"), "预收要单独看得见（催收时不能再要这 50）"
        assert _num(row["buckets"]["0_30"]) == Decimal("100.00"), "预收⛔ 不许从桶里减"
    finally:
        _cleanup(db_session, [owing, over], [unit["id"]])


def test_信用额度_null是不限额_零是真的零_超限只提示(
    client: TestClient, db_session, token_dispatcher: str, token_driver: str, users: dict
) -> None:
    """额度三档：NULL（不限额，⛔ 不是 0）/ 显式 0（真的超限）/ 显式 50（欠 100 才超）。"""
    unit = _unit(client, token_dispatcher, _uniq("额度单位"))
    oid = _arrears_order(client, db_session, token_dispatcher, token_driver, users,
                         unit_id=unit["id"])
    try:
        db_session.expire_all()
        assert db_session.get(ArrearsUnit, unit["id"]).credit_limit is None, (
            "新建的单位就是不限额（NULL），⛔ 不许回填成 0"
        )
        row = _row(_report(client, token_dispatcher), unit["id"])
        assert row["limit"] is None and row["credit_available"] is None
        assert row["over_limit"] is False

        # 设成 50：欠 100 → 超限；写入必须照收（额度是提示，⛔ 不是闸）
        p = client.patch(f"{UNITS}/{unit['id']}", json={"credit_limit": "50.00"},
                         headers=auth_headers(token_dispatcher))
        assert p.status_code == 200, p.text
        row = _row(_report(client, token_dispatcher), unit["id"])
        assert _num(row["limit"]) == Decimal("50.00")
        assert _num(row["credit_used"]) == Decimal("100.00")
        assert _num(row["credit_available"]) == Decimal("-50.00")
        assert row["over_limit"] is True

        # 显式 0：0 是一个会咬人的额度（NULL 与 0 必须能区分）
        p = client.patch(f"{UNITS}/{unit['id']}", json={"credit_limit": "0"},
                         headers=auth_headers(token_dispatcher))
        assert p.status_code == 200, p.text
        row = _row(_report(client, token_dispatcher), unit["id"])
        assert _num(row["limit"]) == Decimal("0.00") and row["over_limit"] is True

        # 清回不限额：null 是合法值（端点看 model_fields_set，不看 None）
        p = client.patch(f"{UNITS}/{unit['id']}", json={"credit_limit": None},
                         headers=auth_headers(token_dispatcher))
        assert p.status_code == 200, p.text
        db_session.expire_all()
        assert db_session.get(ArrearsUnit, unit["id"]).credit_limit is None
        row = _row(_report(client, token_dispatcher), unit["id"])
        assert row["limit"] is None and row["credit_available"] is None
        assert row["over_limit"] is False
    finally:
        _cleanup(db_session, [oid], [unit["id"]])


def test_报表日往前调_那天之后送达的单不算欠款(
    client: TestClient, db_session, token_dispatcher: str, token_driver: str, users: dict
) -> None:
    """时点账：把报表日调到昨天，今天才送达的单必须**整个消失**（窗口起点不参与）。"""
    unit = _unit(client, token_dispatcher, _uniq("时点单位"))
    oid = _arrears_order(client, db_session, token_dispatcher, token_driver, users,
                         unit_id=unit["id"])
    try:
        yesterday = (business_today() - timedelta(days=1)).isoformat()
        data = _report(client, token_dispatcher, day=yesterday)
        assert data["as_of"] == yesterday
        assert _row(data, unit["id"]) is None, (
            "报表日调回昨天，今天送达的单还算欠款 —— 那这份报表就不是时点账"
        )
    finally:
        _cleanup(db_session, [oid], [unit["id"]])


def test_没挂单位的单落到真人_不叫未分配挂账单位(
    client: TestClient, db_session, token_dispatcher: str, token_driver: str, users: dict
) -> None:
    """临时货主的欠款要写成**那个人的称呼**（催收要能找到人），⛔ 不许一锅端成"未分配"。"""
    temp = _uniq("临时货主")
    oid = _arrears_order(client, db_session, token_dispatcher, token_driver, users,
                         temp_name=temp)
    try:
        data = _report(client, token_dispatcher)
        _assert_invariants(data)
        hit = [r for r in data["rows"] if r["name"] == temp]
        assert len(hit) == 1, "临时货主的欠款没有单独成行（行名前五：{0}）".format(
            [r["name"] for r in data["rows"]][:5]
        )
        assert hit[0]["kind"] == "temp"
        assert _num(hit[0]["balance"]) >= Decimal("100.00")
        assert all("未分配挂账单位" not in r["name"] for r in data["rows"]), (
            "这一期把「未分配挂账单位」这个找不到人的桶拆掉了"
        )
    finally:
        _cleanup(db_session, [oid], [])
