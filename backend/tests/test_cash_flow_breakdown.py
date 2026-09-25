"""「收入来源 / 支出明细」分项必须与汇总**逐项对得上**（账本管理「收支」页的两段）。

## 这一页为什么要有一个新端点

账本管理的「收支」页要给用户看的是**每一路钱分别多少**（客户收款/挂账结清/油费/司机运费/付供应商…），
而不是只有三个总数。而"每一路的金额"**只能在数据库里算**：
客户端拉 `GET /cash-flows`（有 `limit`，默认 200）自己按 `biz_type` 分类求和，
在两个方向上都会错——少算（截断）与错分类（大小写、NULL）各一次。

所以这里钉四件事：
1. 分项之和 == `GET /cash-flows/summary` 的总数（**两条独立路径必须同一个数**，含 `count`）；
2. 一路一行，金额与笔数都与落库的那几笔相符；
3. 历史脏数据（方向存成大写 `IN`）不算成支出；
4. 货主看不了（全公司成本不能从这一页漏出去）。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models import CashFlow
from tests.conftest import auth_headers

#: 挑一个**别的测试不会碰**的日期：本文件两条断言是"精确相等"，
#: 蹭别人的日期就会把别人造的行算进来（`test_cash_flow_summary` 用的是 2026-09-19）。
DAY = "2019-03-05"


def _mk_expense(client, h, amount: str, category: str = "fuel") -> None:
    r = client.post(
        "/api/v1/expenses",
        json={"exp_date": DAY, "category": category, "amount": amount, "note": "收支分项探针"},
        headers=h,
    )
    assert r.status_code == 200, r.text


def _mk_flow(db, direction: str, biz_type: str, amount: str) -> None:
    """直接落一条流水（收入那一路的真实写法是"逐单核销收款"，要造订单+收款单，
    与这里要验的东西无关；这一页只认表里的行，怎么来的不影响）。"""
    db.add(
        CashFlow(
            flow_date=date(2019, 3, 5),
            direction=direction,
            amount=Decimal(amount),
            party_type="customer" if direction.lower() == "in" else "expense",
            biz_type=biz_type,
            note="收支分项探针",
        )
    )
    db.commit()


def _breakdown(client, h, **params):
    r = client.get("/api/v1/cash-flows/breakdown", params=params, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _by_biz(rows: list[dict]) -> dict[str, Decimal]:
    return {x["biz_type"]: Decimal(x["amount"]) for x in rows}


def test_分项之和等于汇总_且每一路金额与落库相符(client, db_session, token_dispatcher):
    h = auth_headers(token_dispatcher)
    _mk_expense(client, h, "10.00")
    _mk_expense(client, h, "20.00")
    _mk_expense(client, h, "30.50")
    _mk_expense(client, h, "5.00", category="toll")
    _mk_flow(db_session, "in", "RECEIPT_CASH", "100.00")
    _mk_flow(db_session, "in", "RECEIPT_TRANSFER", "250.25")
    _mk_flow(db_session, "out", "PAYMENT_DRIVER", "80.00")

    win = {"date_from": DAY, "date_to": DAY}
    b = _breakdown(client, h, **win)
    s = client.get("/api/v1/cash-flows/summary", params=win, headers=h).json()

    # ① 两条独立路径必须同一个数（分项之和 = 汇总；笔数也一样）
    assert Decimal(b["income_total"]) == Decimal(s["income"]), "收入分项加不到汇总上"
    assert Decimal(b["expense_total"]) == Decimal(s["expense"]), "支出分项加不到汇总上"
    assert b["count"] == s["count"], "分项的笔数与汇总对不上（说明有一路被漏掉/多算）"
    assert Decimal(b["net"]) == Decimal(b["income_total"]) - Decimal(b["expense_total"])

    # ② 每一路都在，金额精确
    inc = _by_biz(b["income"])
    exp = _by_biz(b["expense"])
    assert inc["RECEIPT_CASH"] == Decimal("100.00")
    assert inc["RECEIPT_TRANSFER"] == Decimal("250.25")
    assert exp["EXPENSE_FUEL"] == Decimal("60.50"), "同一个分类的两笔必须并成一行"
    assert exp["EXPENSE_TOLL"] == Decimal("5.00")
    assert exp["PAYMENT_DRIVER"] == Decimal("80.00")
    # ⚠️ 笔数只数**我自己造的那几路**：同一个文件里「历史脏数据」那条用例也在同一个 DAY 上写
    #    （它加的是 RECEIPT_PREPAID）。整个窗口的总笔数会把别人的算进来 ——
    #    文件内一换顺序（倒序扫描）就变成 4 != 2（2026-09-25 实测）。
    #    下面那条脏数据用例早就是这么写的（它按 biz_type 取），这里补齐成同一纪律。
    mine_in = {"RECEIPT_CASH", "RECEIPT_TRANSFER"}
    mine_out = {"EXPENSE_FUEL", "EXPENSE_TOLL", "PAYMENT_DRIVER"}
    assert sum(x["count"] for x in b["income"] if x["biz_type"] in mine_in) == 2
    assert sum(x["count"] for x in b["expense"] if x["biz_type"] in mine_out) == 5

    # ③ 钱多的排前面
    amounts = [Decimal(x["amount"]) for x in b["income"]]
    assert amounts == sorted(amounts, reverse=True), "收入那一段没按金额从大到小排"


def test_历史脏数据_方向存成大写也算收入不算支出(client, db_session, token_dispatcher):
    """枚举是小写 `in`/`out`，但老数据里存过大写。判据只让 `in` 进收入那一侧 ——
    归一漏掉一处，这笔钱就会**从收入里消失、跑到支出里**（两边都不报错）。"""
    h = auth_headers(token_dispatcher)
    _mk_flow(db_session, "IN", "RECEIPT_PREPAID", "33.00")

    b = _breakdown(client, h, date_from=DAY, date_to=DAY)
    assert _by_biz(b["income"])["RECEIPT_PREPAID"] == Decimal("33.00")
    assert "RECEIPT_PREPAID" not in _by_biz(b["expense"])
    # 大写与小写必须并成**同一条**（分组键不归一就会裂成两行）
    _mk_flow(db_session, "in", "RECEIPT_PREPAID", "7.00")
    b2 = _breakdown(client, h, date_from=DAY, date_to=DAY)
    assert _by_biz(b2["income"])["RECEIPT_PREPAID"] == Decimal("40.00")
    assert sum(1 for x in b2["income"] if x["biz_type"] == "RECEIPT_PREPAID") == 1


def test_空窗口返回全零而不是报错(client, token_dispatcher):
    """没数的窗口要给"零"，不是 500、也不是把别的窗口的数端上来。"""
    h = auth_headers(token_dispatcher)
    b = _breakdown(client, h, date_from="2018-01-01", date_to="2018-01-02")
    assert b["income"] == [] and b["expense"] == []
    assert Decimal(b["income_total"]) == 0 and Decimal(b["expense_total"]) == 0
    assert b["count"] == 0


def test_货主看不了(client, token_shipper):
    r = client.get("/api/v1/cash-flows/breakdown", headers=auth_headers(token_shipper))
    assert r.status_code == 403, r.text
