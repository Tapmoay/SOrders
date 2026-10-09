"""开销单 ↔ 现金流水：记账只有一个口径（2026-10-09 BUG-0018 / 台账 TB-02）。

背景：`scripts/seed_demo_data.py` 原来直接 `db.add(Expense(...))` 造了 30 笔历史开销，**绕过了
服务层的记账** —— 那些钱在「账本 / 收支」页上一分都看不见（现金流水里一笔都没有）。这一套用例
钉三件事：

1. 记一笔开销（`POST /expenses`）**必定**留下一条 `cash_flows` OUT，分类 → 口径只有一张表；
2. 存量回填（`scripts.backfill_expense_cash_flows`）**幂等**：已经有流水的一张都不碰，
   预览模式（默认）一条都不写；
3. 认不出的分类落到 `EXPENSE_OTHER`（用户新加一个分类不该让这笔开销存不进去）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.models import CashFlow, Expense
from app.models.enums import CashFlowBizType, CashFlowDirection
from app.services.accounting_service import expense_biz_type
from scripts.backfill_expense_cash_flows import (
    backfill_expense_cash_flows,
    expenses_without_cash_flow,
)
from tests.conftest import auth_headers

#: 探针日期故意挑在很久以前：这一套用例会 commit（回填函数自己 commit），万一清理没走到，
#: 也不会落进任何"按 2026 年窗口求和"的报表用例里。
PROBE_DAY = date(2001, 1, 1)


def _flows_of(db, expense_id: int) -> list[CashFlow]:
    return list(db.scalars(
        select(CashFlow).where(CashFlow.party_type == "expense", CashFlow.doc_id == expense_id)
    ).all())


def _flush_expense(db, category: str, amount: str, note: str) -> Expense:
    """直接插一张"绕过记账"的开销单 —— 就是当年那份播种脚本干的事（不回填函数的手）。"""
    e = Expense(exp_date=PROBE_DAY, category=category, amount=Decimal(amount), note=note)
    db.add(e)
    db.flush()
    return e


def _drop(db, expense: Expense) -> None:
    """把探针留下的行清干净（这一套用例会 commit，不能指望 teardown 的 rollback）。"""
    for f in _flows_of(db, expense.id):
        db.delete(f)
    db.delete(expense)
    db.commit()


def test_记一笔开销必定留下一条现金流水(client, token_dispatcher, db_session):
    """POST /expenses → 恰好一条 cash_flows OUT，字段与那张开销单逐字一致。"""
    h = auth_headers(token_dispatcher)
    r = client.post("/api/v1/expenses", headers=h,
                    json={"exp_date": "2026-10-09", "category": "加油", "amount": "123.45",
                          "note": "BUG-0018 探针"})
    assert r.status_code in (200, 201), r.text
    eid = r.json()["id"]
    flows = _flows_of(db_session, eid)
    assert len(flows) == 1, f"记一笔开销应当恰好留一条流水，实际 {len(flows)} 条"
    f = flows[0]
    assert f.direction == CashFlowDirection.OUT
    assert f.amount == Decimal("123.45")
    assert f.flow_date == date(2026, 10, 9)
    assert f.party_name == "加油"
    assert f.biz_type == CashFlowBizType.EXPENSE_FUEL
    assert f.channel == "cash"
    # 收尾：这行是 API 建的（已 commit），自己删掉，别留给同一个 worker 后面的用例
    from app.models import Expense as E

    _drop(db_session, db_session.get(E, eid))


def test_存量回填幂等_已经有流水的一张都不碰(db_session):
    """插一张没有流水的开销单 → 回填补一条；再跑一遍，**那条流水的 id 一个都不变**。"""
    e = _flush_expense(db_session, "维修", "999.00", "BUG-0018 存量探针")
    eid = e.id
    assert _flows_of(db_session, eid) == []
    assert eid in [x.id for x in expenses_without_cash_flow(db_session)]

    try:
        first, _had = backfill_expense_cash_flows(db_session, dry_run=False)
        assert first >= 1, "回填应当至少补上这一条"
        flows = _flows_of(db_session, eid)
        assert len(flows) == 1, f"回填应当恰好补一条，实际 {len(flows)} 条"
        assert flows[0].biz_type == CashFlowBizType.EXPENSE_REPAIR
        assert flows[0].amount == Decimal("999.00")
        assert flows[0].flow_date == PROBE_DAY
        assert eid not in [x.id for x in expenses_without_cash_flow(db_session)]

        before = sorted(f.id for f in _flows_of(db_session, eid))
        backfill_expense_cash_flows(db_session, dry_run=False)
        assert sorted(f.id for f in _flows_of(db_session, eid)) == before, \
            "回填不幂等：又给同一张开销单插了一条流水"
    finally:
        _drop(db_session, db_session.get(Expense, eid))


def test_回填预览不写库(db_session):
    """默认 `dry_run=True`：报得出待补条数，但库里的流水一条都不多。"""
    e = _flush_expense(db_session, "过路", "58.00", "BUG-0018 预览探针")
    try:
        before = db_session.scalar(select(func.count()).select_from(CashFlow)) or 0
        n, _had = backfill_expense_cash_flows(db_session, dry_run=True)
        assert n >= 1, "预览应当报出至少这一条待补"
        after = db_session.scalar(select(func.count()).select_from(CashFlow)) or 0
        assert after == before, "预览模式写库了"
        assert _flows_of(db_session, e.id) == []
    finally:
        _drop(db_session, e)


def test_分类认不出落_OTHER_带空格的也认得():
    """认不出的分类不许抛异常（用户新加一个分类不该让这笔开销存不进去）；带空格的照样认得。"""
    assert expense_biz_type("装卸费-探针") == CashFlowBizType.EXPENSE_OTHER
    assert expense_biz_type("fuel") == CashFlowBizType.EXPENSE_FUEL
    assert expense_biz_type(" 加油 ") == CashFlowBizType.EXPENSE_FUEL
    assert expense_biz_type("") == CashFlowBizType.EXPENSE_OTHER
