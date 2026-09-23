"""导出的**另外四个 kind** 也要逐格与接口一致（2026-09-23 第 12 轮）。

第 11 轮把 `turnover` / `products` 逐格钉住了（见 `test_export_cells_match_api.py`），
这一份补齐剩下四个 —— 它们各有各的"两处口径"风险，而**分叉了不会有任何接口报错**：

| kind | 工作表 | 风险（都是本仓库真栽过的形状） |
|---|---|---|
| `finance` | 资金收支 | 流入/流出/净额是自己**在内存里按行求和**的 → 少一个 `is_deleted` 过滤就等于把已撤销的流水又算了一遍；净额的正负号写反也看不出来 |
| `customers` | 客户经营 | 导出**自己写了一份**客户账聚合（不是复用 `/ledger/accounts`）→ 隔离区（软删）订单的账算不算、窗口怎么下推，两处一旦不一致，"客户经营"和"账本-货主账"就是两个数 |
| `drivers` | 司机绩效 | 「待结运费」必须是**数字**（文本在 Excel 里 SUM 得 0）、工资制那一格必须是**文字「工资制」**（印 0 会被读成"这个月一分钱都不用付"）、`""` 与 `0` 的取舍 |
| `audit` | 异常与审计 | 「敏感操作日志」曾经**完全不看区间**（导 09-01 的报告里躺着库里最新的 200 条）—— 审计凭证"名字写着 A、内容是 B"比"少给几条"严重得多；截断说明必须如实 |

判据手法与第 11 轮同一套：**同一段窗口**分别打接口与导出，逐格比。
具体的"读表 / 比金额 / 清理"管道直接复用 `test_export_cells_match_api`（**一份实现**，
否则这些助手自己就会分叉）。
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.business_time import business_range_utc, business_today
from app.models import CashFlow, Expense, Ledger, OperationLog, Order, Supplier, SupplierPayable
from app.services.stats_service import driver_performance
from tests.conftest import auth_headers
from tests.test_export_cells_match_api import (
    _cells,
    _cleanup,
    _mk_driver,
    _mk_product,
    _money,
    _rows_cols,
    _span_label,
    _uniq,
    _xlsx,
)


def _mk_delivered_order(
    client: TestClient,
    h: dict[str, str],
    users: dict,
    *,
    collect_cash: bool,
    piece: str | None = None,
    salary: str | None = None,
) -> dict:
    """走真实链路造一张当日已送达的单。

    - `collect_cash=True` → 司机会收现金；
    - `piece="100"` → 给这位司机挂一份"每单固定 100"的计费规则（**待结运费 > 0**：
      司机绩效那一格的"数字 vs 文字"两支才有人覆盖）；
    - `salary="5000"` → 建一个**工资制**司机（那一格必须是文字「工资制」）。
    """
    product = _mk_product(client, h, cost="6.4")
    driver_id, dtoken = _mk_driver(
        client, h, **({"billing_mode": "SALARY", "salary": salary} if salary else {})
    )
    if piece:
        r = client.post(
            "/api/v1/driver-billing-rules",
            json={"name": _uniq("导出对账计费规则"), "piece_amount": piece, "remark": "导出逐格对账"},
            headers=h,
        )
        assert r.status_code in (200, 201), r.text
        r = client.post(
            "/api/v1/driver-billing-rules/attach",
            json={"driver_id": driver_id, "rule_id": int(r.json()["id"])},
            headers=h,
        )
        assert r.status_code in (200, 201), r.text
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [
                {
                    "product_id": product["id"],
                    "product_name_snapshot": product["name"],
                    "quantity": 2,
                    "unit_price": "40",
                    "line_total": "80",
                }
            ],
            "address_detail": "导出四 kind 对账路 1 号",
            "freight_fee": "30",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    order = r.json()
    body: dict = {"driver_id": driver_id}
    if collect_cash:
        body["collect_cash"] = True
    assert client.post(
        f"/api/v1/orders/{order['id']}/assign", json=body, headers=h
    ).status_code in (200, 201)
    hd = auth_headers(dtoken)
    assert client.post(f"/api/v1/orders/{order['id']}/driver-ack", headers=hd).status_code in (200, 201)
    r = client.post(
        f"/api/v1/orders/{order['id']}/complete",
        json={
            "payment": "cash" if collect_cash else "arrears",
            "delivery_photo_urls": [f"/static/uploads/delivery/{order['id']}/export-probe.jpg"],
        },
        headers=hd,
    )
    assert r.status_code in (200, 201), r.text
    order["__product_ids"] = [int(product["id"])]
    return order


# ---------------------------------------------------------------- finance

@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_finance_export_matches_cash_flow_summary_and_expense_categories(
    client: TestClient, token_dispatcher: str, db_session: Session
) -> None:
    """资金收支三格 == `/cash-flows/summary`；而且**撤销掉的那笔付款两边都不算**。

    为什么要造"撤销"这个现场（2026-09-23 第 12 轮）：`cash_flows` 的软删是
    **「撤销一笔付款 = 把那一行藏起来，历史一行不丢」**（`DELETE /supplier-payments/{id}`）。
    模型的纪律写着"凡是从 `cash_flows` 取数的地方都必须带 `is_deleted.is_(False)`，
    漏一处的后果是同一笔钱两个答案"—— 导出的那三格正是"取数的地方"之一，
    而它自己**在内存里按行求和**（不走 `/summary`），所以漏没漏只有比出来才知道。
    """
    h = auth_headers(token_dispatcher)
    today = business_today()
    anchor = today.isoformat()
    category = _uniq("导出对账开销分类")
    r = client.post(
        "/api/v1/expenses",
        json={"exp_date": anchor, "category": category, "amount": "12.34", "note": "导出逐格对账"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    expense_id = int(r.json()["id"])
    supplier_id = payable_id = payment_id = None
    try:
        # 供应商 + 应付 + 一笔付款（流出），然后**撤销**这笔付款（软删那行流水）
        r = client.post("/api/v1/suppliers", json={"name": _uniq("导出对账供应商")}, headers=h)
        assert r.status_code in (200, 201), r.text
        supplier_id = int(r.json()["id"])
        r = client.post(
            f"/api/v1/suppliers/{supplier_id}/payables",
            json={"supplier_id": supplier_id, "title": _uniq("导出对账应付"), "amount": "100", "doc_date": anchor},
            headers=h,
        )
        assert r.status_code in (200, 201), r.text
        payable_id = int(r.json()["id"])
        r = client.post(
            f"/api/v1/supplier-payables/{payable_id}/payments",
            json={"amount": "100", "pay_date": anchor, "channel": "cash", "remark": "导出逐格对账"},
            headers=h,
        )
        assert r.status_code in (200, 201), r.text
        payment_id = int(r.json()["id"])
        hidden = Decimal(str(r.json()["amount"]))
        assert hidden > 0
        r = client.delete(f"/api/v1/supplier-payments/{payment_id}", headers=h)
        assert r.status_code in (200, 204), r.text

        sheets, name = _xlsx(client, h, kind="finance", mode="day", date=anchor)
        assert "资金收支" in sheets, f"导出的工作表叫 {list(sheets)}"
        ws = sheets["资金收支"]
        assert name == f"finance-report-{anchor}.xlsx", name
        head = _cells(ws, 1)
        # ⚠️ 这四个 kind 的表头窗口写法**与 turnover/products 不一样**：后者走
        #    `_span_label(s, e)`（`9-23`），这四个写 `f"{s} ~ {e}"`（`2026-09-23 ~ 2026-09-23`）。
        #    同一个导出功能里两种日期写法 —— 已记进台账「待拍板」第 18 条（要不要统一、要不要都带年份），
        #    这里先**如实钉住现状**，免得以后改了没人知道。
        assert head[0] == "资金收支" and head[1] == f"{anchor} ~ {anchor}", head

        summary = client.get(
            "/api/v1/cash-flows/summary",
            params={"date_from": anchor, "date_to": anchor},
            headers=h,
        )
        assert summary.status_code == 200, summary.text
        s = summary.json()

        # ① 「撤销」必须真的生效：接口的流出 = 窗口内**全部**流出 − 撤销掉那笔
        everything_out = db_session.scalar(
            select(func.coalesce(func.sum(CashFlow.amount), 0)).where(
                CashFlow.flow_date >= today,
                CashFlow.flow_date <= today,
                func.lower(CashFlow.direction) == "out",
            )
        )
        assert _money(s["expense"]) == _money(Decimal(str(everything_out)) - hidden), (
            f"撤销了一笔 {hidden} 的付款，但接口的流出还是 {s['expense']}（应扣掉它）——"
            "「撤销付款」在收支页没生效"
        )
        assert _money(s["expense"]) > 0, "这一窗口没有流出，下面几格就没得比"

        # ② 导出的那三格 == 接口（导出漏掉 is_deleted 过滤就会多出被撤销的那笔）
        row2 = _cells(ws, 2)
        assert row2[0] == "流入" and _money(row2[1]) == _money(s["income"]), (row2, s)
        assert row2[2] == "流出" and _money(row2[3]) == _money(s["expense"]), (row2, s)
        assert row2[4] == "净额" and _money(row2[5]) == _money(s["net"]), (row2, s)
        # 净额必须是"流入 − 流出"（符号写反这一格看着也像个数）
        assert _money(row2[5]) == _money(Decimal(str(s["income"])) - Decimal(str(s["expense"]))), row2

        # ③ 明细行数 == 接口给的笔数（导出没有 limit；接口说有 N 笔就必须是 N 行）
        flow_head = next(r for r in range(1, ws.max_row + 1) if _cells(ws, r)[:1] == ["日期"])
        assert _cells(ws, flow_head) == ["日期", "方向", "金额", "对象", "渠道", "类型", "备注"], _cells(ws, flow_head)
        flows = _rows_cols(ws, flow_head, 7)
        assert len(flows) == int(s["count"]), f"导出明细 {len(flows)} 行、接口说这一窗口 {s['count']} 笔"
        for direction, column in (("收入", "income"), ("支出", "expense")):
            got = sum((_money(row[2]) for row in flows if row[1] == direction), Decimal("0"))
            assert got == _money(s[column]), (direction, got, s[column])
        # ④ 金额列必须是**数**不是文本（Excel 里 SUM 得 0 的老毛病）
        for row in flows:
            assert isinstance(row[2], (int, float)), f"流水金额被写成了文本：{row!r}"

        # ⑤ 开销分类那一块 == GET /expenses 按分类合计（同一窗口）
        exp = client.get("/api/v1/expenses", params={"date_from": anchor, "date_to": anchor}, headers=h)
        assert exp.status_code == 200, exp.text
        want: dict[str, Decimal] = {}
        for e in exp.json():
            want[e["category"]] = want.get(e["category"], Decimal("0")) + Decimal(str(e["amount"]))
        assert want.get(category), f"刚建的开销没出现在 /expenses 里：{list(want)[:5]}"
        cat_head = next(r for r in range(1, ws.max_row + 1) if _cells(ws, r)[:1] == ["分类"])
        assert _cells(ws, cat_head) == ["分类", "金额"], _cells(ws, cat_head)
        got_cats = {row[0]: _money(row[1]) for row in _rows_cols(ws, cat_head, 2)}
        assert len(got_cats) == len(want), f"导出 {len(got_cats)} 个分类、接口 {len(want)} 个"
        for cat, amt in want.items():
            assert got_cats.get(cat) == _money(amt), (cat, got_cats.get(cat), amt)
    finally:
        if payment_id is not None:
            db_session.execute(delete(CashFlow).where(CashFlow.id == payment_id))
        if payable_id is not None:
            db_session.execute(delete(SupplierPayable).where(SupplierPayable.id == payable_id))
        if supplier_id is not None:
            db_session.execute(delete(Supplier).where(Supplier.id == supplier_id))
        db_session.execute(delete(Expense).where(Expense.id == expense_id))
        db_session.commit()


# ---------------------------------------------------------------- customers

@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_customers_export_matches_ledger_accounts(
    client: TestClient, token_dispatcher: str, db_session: Session, users: dict
) -> None:
    """「客户经营」的货主账那一块 == `GET /ledger/accounts?kind=shipper`（**两处实现**必须同源）。"""
    h = auth_headers(token_dispatcher)
    today = business_today()
    anchor = today.isoformat()
    order = _mk_delivered_order(client, h, users, collect_cash=False)
    order_ids = [int(order["id"])]
    product_ids = order["__product_ids"]
    # 再送一张，然后把它删进**回收站**（隔离区）：它的账本行还在库里，但两边都不许算
    trashed = _mk_delivered_order(client, h, users, collect_cash=False)
    order_ids.append(int(trashed["id"]))
    product_ids += trashed["__product_ids"]
    try:
        r = client.delete(f"/api/v1/orders/{trashed['id']}", headers=h)
        assert r.status_code in (200, 204), r.text
        db_session.expire_all()
        assert db_session.get(Order, trashed["id"]).deleted_at is not None, "这一单没进回收站"

        sheets, name = _xlsx(client, h, kind="customers", mode="day", date=anchor)
        assert "客户经营" in sheets, f"导出的工作表叫 {list(sheets)}"
        ws = sheets["客户经营"]
        assert name == f"customers-report-{anchor}.xlsx", name
        assert _cells(ws, 1)[0] == "客户账汇总", _cells(ws, 1)

        # `/ledger/accounts?kind=shipper` **同时包含真货主与"临时货主"两种桶**
        # （`temp_name` 字段区分），而导出把它们分成两个「类别」。所以正确的对法是把导出的
        # 「货主」+「临时货主」两段合起来跟它比（第一版只比「货主」那一段，被别的用例留下的
        # 临时货主「UTC 探针」打成假红 —— 那不是缺陷，是判据比错了对象）。
        def _accounts(kind: str) -> dict[str, tuple[int, Decimal]]:
            r = client.get(
                "/api/v1/ledger/accounts",
                params={"kind": kind, "date_from": anchor, "date_to": anchor},
                headers=h,
            )
            assert r.status_code == 200, r.text
            return {a["name"]: (int(a["count"]), _money(a["total"])) for a in r.json()}

        want = _accounts("shipper")
        want_member = _accounts("member")
        assert want, "刚送达的单没进 /ledger/accounts（后面就没有可比的了）"

        head_row = next(r for r in range(1, ws.max_row + 1) if _cells(ws, r)[:1] == ["类别"])
        assert _cells(ws, head_row) == ["类别", "客户", "笔数", "总额"], _cells(ws, head_row)
        got: dict[str, tuple[int, Decimal]] = {}
        got_member: dict[str, tuple[int, Decimal]] = {}
        for row in _rows_cols(ws, head_row, 4):
            bucket = got_member if row[0] == "批发商" else got
            bucket[row[1]] = (int(row[2]), _money(row[3]))
        assert got, f"导出的货主/临时货主账一行都没有：{_rows_cols(ws, head_row, 4)}"
        assert set(got) == set(want), f"货主对不上：导出 {sorted(got)} vs 接口 {sorted(want)}"
        for name_, (cnt, total) in want.items():
            assert got[name_] == (cnt, total), (name_, got[name_], (cnt, total))
        assert set(got_member) == set(want_member), (
            f"批发商对不上：导出 {sorted(got_member)} vs 接口 {sorted(want_member)}"
        )

        # ⛔ 隔离区那一单的账**两边都不算**（R13-R6）：导出这条数不许比接口多
        trashed_ledgers = db_session.scalar(
            select(func.count()).select_from(Ledger).where(Ledger.order_id == trashed["id"])
        )
        assert trashed_ledgers, "被删的那一单没有账本行 —— 「隔离区不算」这条就没被覆盖到"
        trashed_total = db_session.scalar(
            select(func.coalesce(func.sum(Ledger.total), 0)).where(Ledger.order_id == trashed["id"])
        )
        assert Decimal(str(trashed_total)) > 0, "被删那一单的账不是正数，判据没有锋利度"
        got_total = sum((t for _, t in got.values()), Decimal("0"))
        want_total = sum((t for _, t in want.values()), Decimal("0"))
        assert got_total == want_total, (got_total, want_total)

        # 挂账未收 TOP 那一段 == /reports/arrears-summary（同一窗口）
        summary = client.get(
            "/api/v1/reports/arrears-summary",
            params={"date_from": anchor, "date_to": anchor},
            headers=h,
        )
        assert summary.status_code == 200, summary.text
        want_units = {u["name"]: (int(u["count"]), _money(u["amount"])) for u in summary.json()}
        top_head = next(r for r in range(1, ws.max_row + 1) if _cells(ws, r)[:1] == ["单位"])
        got_units = {row[0]: (int(row[1]), _money(row[2])) for row in _rows_cols(ws, top_head, 3)}
        assert set(got_units) == set(want_units), (sorted(got_units), sorted(want_units))
        for name_, val in want_units.items():
            assert got_units[name_] == val, (name_, got_units[name_], val)
    finally:
        _cleanup(db_session, order_ids, product_ids)


# ---------------------------------------------------------------- drivers

@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_drivers_export_matches_driver_performance_cells(
    client: TestClient, token_dispatcher: str, db_session: Session, users: dict
) -> None:
    """「司机绩效」逐格 == `GET /stats/driver-performance`（含"数字 vs 文字"那两条规矩）。

    ⚠️ 必须**同时**造出两支现场，否则那两条规矩没有发言权（反向验证实测：只造普通司机时，
    「待结运费写成文本」这个注入照样全绿 —— 因为那一格走的是 `else: 0` 分支）：
    · `piece="100"` → 计件司机，待结运费 > 0（**数字**）；
    · `salary="5000"` → 工资制司机（那一格必须是文字「工资制」，不是 0）。
    """
    h = auth_headers(token_dispatcher)
    today = business_today()
    anchor = today.isoformat()
    order = _mk_delivered_order(client, h, users, collect_cash=True, piece="100")
    salary_order = _mk_delivered_order(client, h, users, collect_cash=False, salary="5000")
    order_ids = [int(order["id"]), int(salary_order["id"])]
    product_ids = order["__product_ids"] + salary_order["__product_ids"]
    try:
        sheets, name = _xlsx(client, h, kind="drivers", mode="day", date=anchor)
        assert "司机绩效" in sheets, f"导出的工作表叫 {list(sheets)}"
        ws = sheets["司机绩效"]
        assert name == f"drivers-report-{anchor}.xlsx", name
        assert _cells(ws, 1)[0] == "司机绩效", _cells(ws, 1)

        perf = client.get(
            "/api/v1/stats/driver-performance",
            params={"date_from": anchor, "date_to": anchor},
            headers=h,
        )
        assert perf.status_code == 200, perf.text
        drivers = perf.json()["drivers"]
        assert drivers, "这一窗口没有司机绩效行（判据会空转）"

        head_row = next(r for r in range(1, ws.max_row + 1) if _cells(ws, r)[:1] == ["司机"])
        assert _cells(ws, head_row) == [
            "司机", "完成单量", "准时率", "拍照率", "平均送达分钟", "计费方式", "待结运费",
        ], _cells(ws, head_row)
        got = _rows_cols(ws, head_row, 7)
        assert len(got) == len(drivers), f"导出 {len(got)} 行、接口 {len(drivers)} 行"
        saw_salary = saw_number = False
        for row, d in zip(got, drivers):
            assert row[0] == d["driver_name"], (row, d)
            assert int(row[1]) == int(d["completed_count"]), (row, d)
            rate = d["on_time_rate"]
            assert row[2] == ("" if rate is None else round(rate, 4)), (row, d)
            assert row[3] == round(d["photo_upload_rate"] or 0.0, 4), (row, d)
            avg = d["avg_delivery_seconds"]
            # ⚠️ 2026-09-24 第 21 轮（D11-5）：分钟保留 **2** 位（原来 1 位）——
            #    `/stats/export` 的「司机绩效」与这张表是同一个数，两份导出必须逐格一致；
            #    1 位会把 9358.8 秒印成 156.0、2 位是 155.98（同一份数据的两个值就是 8 分钟误差）。
            assert row[4] == ("" if avg is None else round(avg / 60, 2)), (row, d)
            assert row[5] == (d["billing_mode"] or ""), (row, d)
            owed = d["freight_owed"]
            if d["billing_mode"] == "SALARY":
                # ⛔ 工资制必须是**文字**：印 0 会被读成"这个月一分钱都不用付给他"
                assert row[6] == "工资制", (row, d)
                saw_salary = True
            elif owed:
                # ⛔ 待结运费必须是**数字**：文本在 Excel 里 SUM 得 0（R2-3(exp)）
                assert isinstance(row[6], (int, float)), f"待结运费被写成了文本：{row[6]!r}"
                assert _money(row[6]) == _money(owed), (row, d)
                saw_number = True
            else:
                assert row[6] == 0, (row, d)
        assert saw_salary, "这一窗口没有工资制司机 —— 「工资制」那一支没被覆盖（判据会恒真）"
        assert saw_number, "这一窗口没有待结运费 > 0 的司机 —— 「必须是数字」那一支没被覆盖"
    finally:
        _cleanup(db_session, order_ids, product_ids)


# ---------------------------------------------------------------- audit

@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_audit_export_window_is_real_and_truncation_is_honest(
    client: TestClient, token_dispatcher: str, db_session: Session, users: dict
) -> None:
    """「异常与审计」：异常块逐行 == `/stats/exception-orders`；日志块**必须真的落在窗口里**，
    且截断说明（"共 N 条" / "只列了最近 M 条"）必须与库里的真实条数一致。"""
    import re

    h = auth_headers(token_dispatcher)
    today = business_today()
    anchor = today.isoformat()
    order = _mk_delivered_order(client, h, users, collect_cash=False)
    order_ids = [int(order["id"])]
    product_ids = order["__product_ids"]

    # ⚠️ 先**造一条窗口外的历史日志**，否则"日志块不看区间"这件事在测试库上验不出来
    #    （库里的日志全是"今天"的：反向验证实测，把区间放宽十年也不会有别天的行 —— 判据恒真）。
    from app.models.enums import OperationAction
    from app.models.operation_log import OperationLog as _OL

    OLD_TEXT = "导出逐格对账-窗口外的历史日志"
    old_stamp = business_range_utc(today - timedelta(days=3), today - timedelta(days=3))[0]
    old_log = _OL(
        operator_id=users["dispatcher"].id,
        order_id=None,
        action=OperationAction.ORDER_CREATE,
        change_content=OLD_TEXT,
        created_at=old_stamp,
    )
    db_session.add(old_log)
    db_session.commit()
    old_id = int(old_log.id)
    try:
        sheets, name = _xlsx(client, h, kind="audit", mode="day", date=anchor)
        assert "异常与审计" in sheets, f"导出的工作表叫 {list(sheets)}"
        ws = sheets["异常与审计"]
        assert name == f"audit-report-{anchor}.xlsx", name
        assert _cells(ws, 1)[0] == "异常订单", _cells(ws, 1)

        ex = client.get(
            "/api/v1/stats/exception-orders",
            params={"date_from": anchor, "date_to": anchor},
            headers=h,
        )
        assert ex.status_code == 200, ex.text
        want_rows = ex.json()
        head_row = next(r for r in range(1, ws.max_row + 1) if _cells(ws, r)[:1] == ["订单号"])
        assert _cells(ws, head_row) == [
            "订单号", "货主", "司机", "异常原因", "处理结果", "解决时间",
        ], _cells(ws, head_row)
        got_rows = _rows_cols(ws, head_row, 6)
        assert len(got_rows) == len(want_rows), f"导出异常单 {len(got_rows)} 行、接口 {len(want_rows)} 行"
        for row, item in zip(got_rows, want_rows):
            assert row[0] == item["order_no"], (row, item)
            # ⚠️ 空值一律按空串比：导出写的是 `None`（openpyxl 存成"空单元格"），
            #    接口给的是 `""` —— 在 Excel 与界面上**都是空白**，不是口径分叉；
            #    但按 `==` 直接比就会红的（全量跑时被别的用例留下的"处理结果为空"的单抓到）。
            assert (row[2] or "") == (item["driver_name"] or ""), (row, item)
            assert (row[3] or "") == (item["exception_reason"] or ""), (row, item)
            assert (row[4] or "") == (item["exception_resolution"] or ""), (row, item)
            resolved = item["exception_resolved_at"]
            assert (row[5] or "") == (resolved.isoformat() if resolved else ""), (row, item)

        # ---- 日志块 ----
        note_row = next(
            r for r in range(1, ws.max_row + 1) if _cells(ws, r)[:1] == ["敏感操作日志"]
        )
        note = _cells(ws, note_row)[1]
        log_head = next(r for r in range(note_row, ws.max_row + 1) if _cells(ws, r)[:1] == ["时间"])
        assert _cells(ws, log_head) == ["时间", "操作", "内容"], _cells(ws, log_head)
        logs = _rows_cols(ws, log_head, 3)

        lo, hi = business_range_utc(today, today)
        real_total = db_session.scalar(
            select(func.count()).select_from(OperationLog).where(
                OperationLog.created_at >= lo, OperationLog.created_at < hi
            )
        ) or 0
        # ① 每一行都必须是**本窗口**的时间（R12 那一类"名字写着 A、内容是 B"）
        for row in logs:
            stamp = row[0]
            assert stamp, row
            assert anchor in stamp, f"日志行落在窗口外：{stamp}（导出的是 {anchor} 这一天的审计）"
        # ①b 那条窗口外的历史日志**一行都不许出现**（这是"区间真的生效"最锋利的判据）
        assert not any(OLD_TEXT in str(row[2]) for row in logs), (
            "导出把窗口外的历史日志也列进来了（导 09-01 的报告里躺着别天的动作）"
        )
        # ② 截断说明必须与真实条数一致
        m = re.search(r"共 (\d+) 条", note)
        assert m, f"截断说明里没有条数：{note!r}"
        assert int(m.group(1)) == int(real_total), (
            f"说明写『共 {m.group(1)} 条』，库里这一窗口实际 {real_total} 条：{note!r}"
        )
        if logs:
            assert len(logs) <= 200, len(logs)
    finally:
        db_session.execute(delete(OperationLog).where(OperationLog.id == old_id))
        db_session.commit()
        _cleanup(db_session, order_ids, product_ids)
