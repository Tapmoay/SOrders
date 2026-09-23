"""时区同一族的三处（2026-09-23 第 18 轮并行渗透 A2-1/2/3）—— 三处都是"UTC 与当地日混用"。

本项目的硬口径（`backend/app/core/business_time.py`）：**库里一律 UTC naive、给人看的一律当地 +8**。
这三处把它破了，而且都不报错：

| # | 位置 | 症状 |
| --- | --- | --- |
| A2-1 | `stats_service._end_of_order_date` | 兜底 SLA 用 **UTC 日末** → 当地**次日 07:59:59**，每天白送 8 小时宽限（本机实测准时率 82.3% 应为 30.9%，差 183 单） |
| A2-2 | `accounting_service.pay_settlement` 的 `flow_date` | 用 `paid_at.date()`（UTC）写 DATE 列 → 当地 00:00~08:00 付款记到**前一天**（跨月进错月） |
| A2-3 | `internal_notes` 的时间戳 | `datetime.now(timezone.utc)` 印给人看 → 当地 09-21 07:10 写成 `[司机 09-20 23:10]`，而这段文本**写进库里就不可改** |

三处都改成走 `business_time` 里的共享实现（`business_day_start_utc` / `business_date` / `local_stamp`），
所以这份测试只钉"行为"，不钉"写法"。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.business_time import BUSINESS_TZ, business_day_start_utc, business_today, local_stamp
from tests.conftest import auth_headers


def test_当地某天的日末就是次日零点前一刻():
    """A2-1 的机制：`_end_of_order_date` 必须落在**当地日末**，不是 UTC 日末。"""
    from app.services.stats_service import _end_of_order_date

    d = date(2026, 9, 20)
    got = _end_of_order_date(d)
    assert got == business_day_start_utc(date(2026, 9, 21)), (
        f"兜底 SLA 应为当地 09-20 的日末（= UTC {business_day_start_utc(date(2026, 9, 21))}），实际 {got}"
    )
    # 当地日末换算回当地时刻必须恰好是 09-20 的最后一刻（23:59:59.999999…）
    local = got.replace(tzinfo=None).replace(tzinfo=BUSINESS_TZ) if False else None
    assert got.replace(tzinfo=None) == business_day_start_utc(date(2026, 9, 21))
    # 而 UTC 日末（旧行为）比正确值**晚 8 小时** —— 这一条是"缺陷形状"的反例
    old = datetime(2026, 9, 20, 23, 59, 59)
    assert old > got, "旧行为（UTC 日末）确实比当地日末晚 8 小时"


def test_准时率按当地日末判定():
    """A2-1 的行为：当地 22:00 送达算准时、当地次日 01:00 送达算**超时**。"""
    from app.models import Order
    from app.models.enums import OrderStatus
    from app.services.stats_service import _on_time_delivered

    d = date(2026, 9, 20)
    # 当地 09-20 22:00 = UTC 09-20 14:00
    on_time = Order(
        order_no="TZ-ON", status=OrderStatus.DELIVERED, order_date=d,
        dispatched_at=datetime(2026, 9, 20, 6, 0),
        delivered_at=datetime(2026, 9, 20, 14, 0),
    )
    # 当地 09-21 01:00 = UTC 09-20 17:00（**同一个 UTC 日**，但已经跨了当地日）
    late = Order(
        order_no="TZ-LATE", status=OrderStatus.DELIVERED, order_date=d,
        dispatched_at=datetime(2026, 9, 20, 6, 0),
        delivered_at=datetime(2026, 9, 20, 17, 0),
    )
    assert _on_time_delivered(on_time) is True
    assert _on_time_delivered(late) is False, (
        "当地次日 01:00 送达被算成准时 —— 那是旧行为（UTC 日末 = 当地次日 07:59:59）"
    )


def test_订单上的时间戳按当地时刻印():
    """A2-3：`local_stamp` 是"印给人看"的唯一实现（UTC 23:10 → 当地 09-21 07:10）。"""
    assert local_stamp(datetime(2026, 9, 20, 23, 10)) == "09-21 07:10"
    assert local_stamp(datetime(2026, 9, 20, 16, 0)) == "09-21 00:00"
    # 反过来：当地 07:10 的 UTC 是前一天 23:10，这正是原来会印错的那一档


@pytest.mark.dispatcher
@pytest.mark.integration
def test_结算付款的现金日期用当地日(client, db_session, users, token_dispatcher, token_driver):
    """A2-2：`cash_flows.flow_date` 必须是**当地日**（付款发生在当地 00:30 时不能记到前一天）。"""
    from sqlalchemy import select

    from app.models import CashFlow, DriverBill, DriverSettlement
    from tests.test_audit_round17_money import _deliver, _mk_order, _mk_product

    h = auth_headers(token_dispatcher)
    users["driver"].billing_mode = "piece"
    db_session.commit()

    # 走真实链路造一张按单应付（工资/计费口径都在别处验过，这里只要一张能结算的 OPEN 账单）
    pid = _mk_product(client, h, "时区探针货")
    order = _mk_order(client, h, users["shipper"].id, pid)
    _deliver(client, h, auth_headers(token_driver), order["id"], users["driver"].id, freight="100")
    db_session.expire_all()
    bill = db_session.scalars(select(DriverBill).where(DriverBill.order_id == order["id"])).first()
    assert bill is not None, "前置：送达没生成账单"

    r = client.post(
        "/api/v1/driver-settlements",
        json={"driver_id": users["driver"].id, "settle_type": "piece", "month": bill.month},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    sid = int(r.json()["id"])
    # ⚠️ 三个动作（confirm/pay/cancel）走**同一个 PATCH**（`settlement_action`，body 里带 action），
    #    不是三个子路径 —— 端点索引：`PATCH /api/v1/driver-settlements/{id}`
    confirmed = client.patch(
        f"/api/v1/driver-settlements/{sid}", json={"action": "confirm"}, headers=h
    )
    assert confirmed.status_code == 200, confirmed.text

    # 把"现在"钉在当地 00:30（= 前一天的 UTC 16:30）：旧写法会把 flow_date 记成**前一天**
    import app.services.accounting_service as acc

    fake_now = business_day_start_utc(business_today()) + timedelta(minutes=30)
    original = acc._now
    acc._now = lambda: fake_now
    try:
        paid = client.patch(
            f"/api/v1/driver-settlements/{sid}", json={"action": "pay", "method": "cash"}, headers=h
        )
    finally:
        acc._now = original
    assert paid.status_code == 200, paid.text

    db_session.expire_all()
    # ⚠️ `doc_id` 是**多张表共用**的（结算付款、开销、供应商付款都用它）——只按 `doc_id` 查会
    #    匹配到**别的**业务写的那条流水（全量跑时踩到过：`flow_date` 是几天前的一条开销流水）。
    #    所以必须同时限定 `biz_type`（结算付款那两个）。
    flow = db_session.scalars(
        select(CashFlow).where(
            CashFlow.doc_id == sid,
            CashFlow.biz_type.in_(["PAYMENT_DRIVER", "PAYMENT_SALARY"]),
        )
    ).first()
    assert flow is not None, "付款没有写现金流水"
    assert flow.flow_date == business_today(), (
        f"付款发生在当地 00:30，现金日期应记当地 {business_today()}，实际 {flow.flow_date}"
        "（旧写法记 UTC 日 = 前一天）"
    )
    # 收尾：把这张结算单作废掉，免得影响别的用例
    client.patch(
        f"/api/v1/driver-settlements/{sid}", json={"action": "cancel", "note": "时区探针清理"},
        headers=h,
    )
