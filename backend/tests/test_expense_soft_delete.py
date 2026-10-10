"""开销的撤销（软删）与恢复：三个状态、一个等式（2026-10-10 BUG-0034 / 台账 TA-16）。

## 为什么要有这个文件

台账 TA-16 的原文是「开销（expenses）全系统没有任何删除或修改入口：**记错一笔永久留在账上**」
（第 4 轮方向 A 普查实测：`DELETE /api/v1/expenses/54` → 404、列表页「删/撤销」零命中、
`PRAGMA table_info(expenses)` 连软删列都没有）。用户 2026-09-20 定的硬规矩是
「**所有删除一律软删 ＋ 必须有恢复路径 ＋ 界面要有手边的撤销入口**」。

这个文件钉五件事：

1. **三态**：活着（默认列表里）→ 撤销（默认列表里没有、回收站档 `deleted_only=true` 里有）
   → 恢复（回到第一个状态，逐字段与撤销前**完全一样**）；
2. **撤销不是物理删**：库里那一行还在，金额/分类/司机/车辆/订单一个字节都没动
   （只多了 `is_deleted=1` 与 `deleted_at`）；
3. **它写下的那条资金流水一起打标记**（`party_type='expense'` + `party_id=expenses.id`）——
   少这一处就是"开销撤销了、收支页的钱还挂着"；
4. **等式证据**：撤销之后每一处合计都**正好少这一笔**（利润表的期间费用 / 车辆成本表的窗口开销
   / 收支页的流出三个数各验一遍，"删前 − 这一笔 = 删后"），恢复之后又正好回到删前；
5. 两个审计码（`EXPENSE_DELETE` / `EXPENSE_RESTORE`）都真的写进了 `operation_logs`。

本文件不连开发库：tests/conftest.py:143 把 DATABASE_URL 指向本进程自己的
backend/tests/.test_dbs/sorders_test_<worker>_<pid>.db（每个 pytest 进程一份）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import CashFlow, Expense, ExpenseCategory, OperationLog
from app.models.enums import OperationAction
from tests.conftest import auth_headers

#: 探针标记：本文件造出来的行都带它，收尾按它清干净。
PROBE = "TB16-PROBE"
#: 固定窗口取远期（2032-06）：避开其它用例的数据，也让"三个合计各验一遍"是确定的。
WIN_FROM = date(2032, 6, 1)
WIN_TO = date(2032, 6, 30)
ANCHOR = "2032-06-15"
CAT = "TB16探针撤销开销"
AMOUNT = Decimal("123.45")


def _dec(x) -> Decimal:
    return Decimal(str(x))


@pytest.fixture(autouse=True)
def clean_probe(db_session):
    """收尾把探针行删干净（开销 / 它写下的流水 / 探针分类），别给同 worker 的其它用例留垃圾。"""
    yield
    db_session.rollback()
    ids = [e.id for e in db_session.scalars(select(Expense).where(Expense.note == PROBE)).all()]
    if ids:
        for f in db_session.scalars(
            select(CashFlow).where(CashFlow.party_type == "expense", CashFlow.party_id.in_(ids))
        ).all():
            db_session.delete(f)
    for e in db_session.scalars(select(Expense).where(Expense.note == PROBE)).all():
        db_session.delete(e)
    for c in db_session.scalars(select(ExpenseCategory).where(ExpenseCategory.name == CAT)).all():
        db_session.delete(c)
    db_session.commit()


def _create(client, h, *, amount: Decimal = AMOUNT) -> dict:
    r = client.post(
        "/api/v1/expenses",
        json={"exp_date": str(WIN_FROM), "category": CAT, "amount": str(amount), "note": PROBE},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _list(client, h, **params) -> list[dict]:
    p = {"date_from": str(WIN_FROM), "date_to": str(WIN_TO)}
    p.update(params)
    r = client.get("/api/v1/expenses", params=p, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _find(rows: list[dict], eid: int) -> dict | None:
    for r in rows:
        if int(r["id"]) == int(eid):
            return r
    return None


def _totals(client, h) -> dict[str, Decimal]:
    """三处合计：利润表的期间费用 / 车辆成本表的窗口开销 / 收支页的流出。"""
    r = client.get("/api/v1/reports/profit", params={"mode": "month", "date": ANCHOR}, headers=h)
    assert r.status_code == 200, r.text
    profit = r.json()
    r = client.get("/api/v1/reports/vehicle-cost", params={"mode": "month", "date": ANCHOR}, headers=h)
    assert r.status_code == 200, r.text
    vehicle = r.json()
    r = client.get(
        "/api/v1/cash-flows/summary",
        params={"date_from": str(WIN_FROM), "date_to": str(WIN_TO)},
        headers=h,
    )
    assert r.status_code == 200, r.text
    cash = r.json()
    return {
        "利润表期间费用": _dec(profit["operating_expense_total"]),
        "车辆成本表窗口开销": _dec(vehicle["expense_window_total"]),
        "收支页流出": _dec(cash["expense"]),
    }


def _flows(db_session, eid: int) -> list[CashFlow]:
    return list(
        db_session.scalars(
            select(CashFlow).where(CashFlow.party_type == "expense", CashFlow.party_id == eid)
        ).all()
    )


# ---------------------------------------------------------------- 三态


def test_三态_活着_撤销_恢复(client, token_dispatcher, db_session):
    """默认列表 → 回收站档 → 恢复，三个状态各自看得到什么。"""
    h = auth_headers(token_dispatcher)
    e = _create(client, h)
    eid = int(e["id"])

    # ① 活着：默认列表里有，回收站档里没有
    assert _find(_list(client, h), eid) is not None
    assert _find(_list(client, h, deleted_only=True), eid) is None

    # ② 撤销：默认列表里没有，回收站档里有且带着 is_deleted / deleted_at
    r = client.delete(f"/api/v1/expenses/{eid}", headers=h)
    assert r.status_code == 204, r.text
    assert r.content == b"", "204 不许带响应体"
    assert _find(_list(client, h), eid) is None
    row = _find(_list(client, h, deleted_only=True), eid)
    assert row is not None, "撤销之后回收站档里必须看得见它（那一档就是「恢复」的落点）"
    assert row["is_deleted"] is True
    assert row["deleted_at"], "撤销必须记下 deleted_at"

    # ③ 恢复：又回到默认列表，回收站档里没有了
    r = client.post(f"/api/v1/expenses/{eid}/restore", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["is_deleted"] is False
    assert r.json()["deleted_at"] is None
    assert _find(_list(client, h), eid) is not None
    assert _find(_list(client, h, deleted_only=True), eid) is None


def test_撤销不是物理删_行还在且字段一个都没动(client, token_dispatcher, db_session):
    """⛔ 撤销只打标记：库里那一行还在，金额/分类/关联一个字节都不许变。"""
    h = auth_headers(token_dispatcher)
    e = _create(client, h)
    eid = int(e["id"])
    before = db_session.get(Expense, eid)
    snapshot = (
        before.exp_date, before.category, before.amount,
        before.driver_id, before.vehicle_id, before.order_id, before.note, before.operator_id,
    )
    assert client.delete(f"/api/v1/expenses/{eid}", headers=h).status_code == 204

    db_session.expire_all()
    after = db_session.get(Expense, eid)
    assert after is not None, "撤销必须是软删 —— 行不见了就是物理删了"
    assert (
        after.exp_date, after.category, after.amount,
        after.driver_id, after.vehicle_id, after.order_id, after.note, after.operator_id,
    ) == snapshot, "撤销不许改任何一个业务字段"
    assert after.is_deleted is True
    assert after.deleted_at is not None


def test_恢复把每个字段原样放回来(client, token_dispatcher, db_session):
    """恢复前后逐字段比（不是"看起来对"）—— 含司机/车辆/订单三个关联。"""
    h = auth_headers(token_dispatcher)
    e = _create(client, h)
    eid = int(e["id"])
    row = _find(_list(client, h), eid)
    keys = ("id", "exp_date", "category", "amount", "driver_id", "vehicle_id", "order_id",
            "note", "operator_id", "link_kind")
    before = {k: row.get(k) for k in keys}

    assert client.delete(f"/api/v1/expenses/{eid}", headers=h).status_code == 204
    r = client.post(f"/api/v1/expenses/{eid}/restore", headers=h)
    assert r.status_code == 200, r.text
    after_row = _find(_list(client, h), eid)
    assert after_row is not None
    assert {k: after_row.get(k) for k in keys} == before, "恢复必须原样放回（含金额与三个关联）"


def test_撤销过的不能再撤_没撤过的不能恢复(client, token_dispatcher):
    """幂等护栏：两边都只认"确实处在那个状态"，第二次调用不许把数改第二遍。"""
    h = auth_headers(token_dispatcher)
    e = _create(client, h)
    eid = int(e["id"])

    r = client.post(f"/api/v1/expenses/{eid}/restore", headers=h)
    assert r.status_code == 400, "没撤过的不能恢复：" + r.text
    assert "没有被撤销" in r.json()["detail"]

    assert client.delete(f"/api/v1/expenses/{eid}", headers=h).status_code == 204
    r = client.delete(f"/api/v1/expenses/{eid}", headers=h)
    assert r.status_code == 400, "撤销过的不能再撤（那会把账上的数改第二遍）：" + r.text
    assert "已经撤销过" in r.json()["detail"]


def test_不存在的开销是两个_404(client, token_dispatcher):
    """查不到就是 404，不是 400/204（否则界面会把"没有这条"显示成"撤销成功"）。"""
    h = auth_headers(token_dispatcher)
    assert client.delete("/api/v1/expenses/999999", headers=h).status_code == 404
    assert client.post("/api/v1/expenses/999999/restore", headers=h).status_code == 404


# ---------------------------------------------------------------- 等式证据


def test_撤销之后每一处合计正好少这一笔(client, token_dispatcher, db_session):
    """**核心等式**：删前 − 这一笔 = 删后（三处合计各验一遍），恢复之后又正好回到删前。

    ⛔ 不是"结果看起来差不多"：三处各取一次快照，断言的是**差恰好等于这一笔的金额**。
    """
    h = auth_headers(token_dispatcher)
    e = _create(client, h)
    eid = int(e["id"])
    amount = _dec(e["amount"])
    assert amount == AMOUNT

    before = _totals(client, h)
    assert client.delete(f"/api/v1/expenses/{eid}", headers=h).status_code == 204
    after = _totals(client, h)

    for name, b in before.items():
        assert b - after[name] == amount, (
            f"{name} 在撤销一笔 {amount} 的开销之后必须正好少 {amount}："
            f"删前 {b}、删后 {after[name]}、差 {b - after[name]}"
        )

    r = client.post(f"/api/v1/expenses/{eid}/restore", headers=h)
    assert r.status_code == 200, r.text
    back = _totals(client, h)
    for name, b in before.items():
        assert back[name] == b, f"{name} 恢复之后必须原样回到 {b}，实际 {back[name]}"


def test_撤销把它写下的那条资金流水一起打标记(client, token_dispatcher, db_session):
    """少这一处就是"开销撤销了、收支页的钱还挂着"（两个答案、两边都不报错）。"""
    h = auth_headers(token_dispatcher)
    e = _create(client, h)
    eid = int(e["id"])
    flows = _flows(db_session, eid)
    assert len(flows) == 1, "记一笔开销必须正好写下一条资金流水"
    fid = flows[0].id
    assert flows[0].is_deleted is False

    assert client.delete(f"/api/v1/expenses/{eid}", headers=h).status_code == 204
    db_session.expire_all()
    f = db_session.get(CashFlow, fid)
    assert f is not None, "流水是软删，行必须在"
    assert f.is_deleted is True and f.deleted_at is not None
    assert _dec(f.amount) == AMOUNT, "流水金额一个字节都不许动"

    assert client.post(f"/api/v1/expenses/{eid}/restore", headers=h).status_code == 200
    db_session.expire_all()
    f = db_session.get(CashFlow, fid)
    assert f.is_deleted is False and f.deleted_at is None


# ---------------------------------------------------------------- 审计 / 名册


def test_两个审计码都真的写进了操作日志(client, token_dispatcher, db_session):
    """钱的动作必须留痕：撤销与恢复各写一条，且带着这笔开销的编号与金额。"""
    h = auth_headers(token_dispatcher)
    e = _create(client, h)
    eid = int(e["id"])
    assert client.delete(f"/api/v1/expenses/{eid}", headers=h).status_code == 204
    assert client.post(f"/api/v1/expenses/{eid}/restore", headers=h).status_code == 200

    rows = list(
        db_session.scalars(
            select(OperationLog)
            .where(OperationLog.action.in_([OperationAction.EXPENSE_DELETE.value, OperationAction.EXPENSE_RESTORE.value]))
            .order_by(OperationLog.id)
        ).all()
    )
    got = {r.action: r for r in rows}
    assert OperationAction.EXPENSE_DELETE.value in got, "撤销没有写审计"
    assert OperationAction.EXPENSE_RESTORE.value in got, "恢复没有写审计"
    for action, row in got.items():
        assert str(eid) in (row.change_content or ""), f"{action} 的留痕里没有这笔开销的编号"
        assert str(AMOUNT) in (row.change_content or ""), f"{action} 的留痕里没有金额"


def test_分类名册的在用笔数不算已撤销的(client, token_dispatcher, db_session):
    """撤销之后这个分类的「在用笔数」必须少 1，否则"名册说 1 笔、点进去是空的"。"""
    h = auth_headers(token_dispatcher)
    e = _create(client, h)
    eid = int(e["id"])

    def count_of(name: str) -> int:
        r = client.get("/api/v1/expense-categories", headers=h)
        assert r.status_code == 200, r.text
        for c in r.json():
            if c["name"] == name:
                return int(c["expense_count"])
        raise AssertionError("名册里没有这个分类：" + name)

    n0 = count_of(CAT)
    assert client.delete(f"/api/v1/expenses/{eid}", headers=h).status_code == 204
    assert count_of(CAT) == n0 - 1, "已撤销的开销不算「在用」"
    assert client.post(f"/api/v1/expenses/{eid}/restore", headers=h).status_code == 200
    assert count_of(CAT) == n0, "恢复之后名册的计数必须回来"


# ---------------------------------------------------------------- 权限


def test_只有派单员能撤销或恢复(client, token_shipper, token_driver, db_session):
    """开销这一块本来就只有派单员能看 —— 撤销/恢复不许给别的角色开口子。"""
    for token in (token_shipper, token_driver):
        h = auth_headers(token)
        assert client.delete("/api/v1/expenses/1", headers=h).status_code in (401, 403)
        assert client.post("/api/v1/expenses/1/restore", headers=h).status_code in (401, 403)
