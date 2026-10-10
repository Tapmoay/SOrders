"""未指定订单的收款（滚动收款）要**冲减**客户欠款、冲掉的部分进「预收」（测试台账 TB-14 → BUG-0036）。

## 病灶（第 4 轮 · 方向 B · 金额口径连锁普查实测）

滚动收款（settle_mode=rolling，不绑订单）只写现金流水：/cash-flows/summary 的 income 323 → 199（收 124）
→ 323（撤销），而**欠款表一分不冲** —— totals.balance 与那一行的 balance 一动不动、prepaid 恒 0。
后果是：客户明明付过 124，催收名单上还是全款，会被**重复催收**；设计文档
docs/ACCOUNTING_V2_DESIGN.md（「rolling：冲抵该客户应收余额」）与 CashFlowBizType.RECEIPT_PREPAID
（models/enums.py）本来就是为这件事准备的，但全仓没有写入点。

## 改法与判据

backend/app/services/reports/balance_query.py 新增 _rolling_credit_map：把**未撤销、截止报表日**的
滚动收款按债务人归集（走 customers 的 arrears_unit_id → 认挂账单位、user_id → 认货主账号；
认不出来的散客**不猜**），在出报表前 prepaid += credit; balance -= credit
（恒等式 balance == Σ buckets − prepaid 保持不变）。

| 判据 | 不钉住会怎样 |
|---|---|
| 收一笔滚动收款 → 该债务人的 balance 减少、prepaid 增加 | 客户付过钱还被按全款催（TB-14） |
| 撤销那笔收款 → 两个数原样回到收款前 | 撤销不生效，欠款表比实际少收 |
| 别的债务人的行不许被改 | 一笔钱冲两家的账 |
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from tests.conftest import auth_headers
from tests.test_receipt_undo import RECEIPTS, _customer_for, _order_delivered

BALANCES = "/api/v1/reports/customer-balances"


def _key(r) -> str:
    return r["kind"] + ":" + str(r.get("unit_id") or r["name"])


def _rows(client, h):
    anchor = date.today().isoformat()
    r = client.get(f"{BALANCES}?mode=month&date={anchor}", headers=h)
    assert r.status_code == 200, r.text
    return {_key(x): x for x in r.json()["rows"]}


def _mine_key(rows, shipper_user) -> str:
    """这一位货主在欠款表里的那一行（行按债务人分：没挂单位的认货主账号，键是名字不是 id）。"""
    phone = (getattr(shipper_user, "phone", "") or "").strip()
    for key, row in rows.items():
        if row["kind"] == "shipper" and (row.get("phone") or "").strip() == phone:
            return key
    raise AssertionError("找不到这位货主的欠款行：%s" % list(rows))


def _roll(client, h, customer_id: int, amount: str):
    return client.post(
        RECEIPTS,
        headers=h,
        json={
            "customer_id": customer_id,
            "amount": amount,
            "method": "cash",
            "settle_mode": "rolling",
            "received_at": date.today().isoformat(),
        },
    )


def test_rolling_receipt_offsets_arrears_and_shows_as_prepaid(
    client, token_dispatcher, token_shipper, token_driver, users
):
    h = auth_headers(token_dispatcher)
    _order_delivered(client, h, token_shipper, token_driver, users, "TB14滚动", "124.00")
    cust = _customer_for(client, h, token_shipper, "TB14滚动")

    # ⚠️ 这一份测试库是**整个 pytest 会话共用**的：别的用例留下的欠款会累加，
    #    所以断言一律用**增量**（收 124 → 少 124），不写死绝对数。
    rows = _rows(client, h)
    mine = _mine_key(rows, users["shipper"])
    b0 = Decimal(rows[mine]["balance"])
    p0 = Decimal(rows[mine]["prepaid"])

    r = _roll(client, h, cust, "124.00")
    assert r.status_code in (200, 201), r.text
    rid = int(r.json()["id"])

    rows = _rows(client, h)
    assert Decimal(rows[mine]["balance"]) == b0 - Decimal("124.00"), (
        "滚动收款没有冲减欠款（TB-14：客户会被重复催）：%s → %s" % (b0, rows[mine]["balance"]))
    assert Decimal(rows[mine]["prepaid"]) == p0 + Decimal("124.00"), (
        "冲掉的部分没有进「预收」列：%s → %s" % (p0, rows[mine]["prepaid"]))

    assert client.delete(f"{RECEIPTS}/{rid}", headers=h).status_code == 204
    rows = _rows(client, h)
    assert Decimal(rows[mine]["balance"]) == b0, "撤销之后欠款没有回来"
    assert Decimal(rows[mine]["prepaid"]) == p0, "撤销之后预收没有清掉"


def test_rolling_receipt_never_moves_another_debtors_row(
    client, token_dispatcher, token_shipper, token_driver, users
):
    h = auth_headers(token_dispatcher)
    _order_delivered(client, h, token_shipper, token_driver, users, "TB14别家", "124.00")
    other = _customer_for(client, h, token_shipper, "TB14另一份档案")

    first = _rows(client, h)
    mine = _mine_key(first, users["shipper"])
    before = {k: v["balance"] for k, v in first.items()}
    assert _roll(client, h, other, "50.00").status_code in (200, 201)
    after = {k: v["balance"] for k, v in _rows(client, h).items()}

    for k in before:
        if k != mine and k in after:
            assert after[k] == before[k], "别的债务人的余额被这笔收款改动了：%s" % k
