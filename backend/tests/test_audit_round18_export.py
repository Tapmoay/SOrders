"""第十七轮审计的回归测试（导出与软删的两条"名字/内容不符"缺陷）。

| 缺陷 | 后果 |
|---|---|
| **`kind=audit` 导出的「敏感操作日志」完全不看区间**（`order_by(id.desc()).limit(200)`） | 导出一份"09-01 的审计报告"，里面躺着的是**库里最新**的 200 条日志（可能是 09-18 的）。审计凭证"名字写着 A、内容是 B"比"少给几条"严重得多——看的人会以为那就是当天的全部动作 |
| **导出文件名只用 `anchor`** | `?date_from=2026-09-01&date_to=2026-09-01` 导出的文件叫 `finance-report-2026-09-18.xlsx`，内容却是 09-01~09-01：按文件名找回来会拿到一份名字与内容不符的凭证 |
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from io import BytesIO

from openpyxl import load_workbook

from tests.conftest import auth_headers


def _mk_log(db_session, operator_id: int, when: datetime, action: str) -> int:
    from app.models import OperationLog

    row = OperationLog(
        operator_id=operator_id,
        action=action,
        change_content=f'{{"probe":"{action}"}}',
        created_at=when,
    )
    db_session.add(row)
    db_session.commit()
    return row.id


def _cells(ws) -> list:
    return [c.value for row in ws.iter_rows() for c in row if c.value is not None]


def _audit_export(client, h, **params) -> tuple[str, list]:
    """导出一份 audit 报表，返回（文件名, 表里所有非空格子）。"""
    q = "&".join(f"{k}={v}" for k, v in params.items())
    r = client.get(f"/api/v1/reports/export?kind=audit&{q}", headers=h)
    assert r.status_code == 200, r.text
    disp = r.headers.get("content-disposition") or ""
    fn = disp.split("filename=")[-1].strip('"')
    wb = load_workbook(BytesIO(r.content))
    return fn, _cells(wb["异常与审计"])


def test_audit_export_only_lists_logs_inside_the_range(client, token_dispatcher, db_session, users):
    """「敏感操作日志」必须**按区间过滤**：区间外的日志不许出现在这份报表里。"""
    h = auth_headers(token_dispatcher)
    # 选一个"过去"的窗口，避免与其它用例刚写下的日志混在一起：
    # 窗口 = 10 天前那一天（业务当地日）
    day = date.today() - timedelta(days=10)
    inside = datetime(day.year, day.month, day.day, 3, 0, tzinfo=timezone.utc)  # 当地 11:00
    outside = datetime(day.year, day.month, day.day, 3, 0, tzinfo=timezone.utc) + timedelta(days=2)

    in_id = _mk_log(db_session, users["dispatcher"].id, inside, "PROBE_AUDIT_INSIDE")
    out_id = _mk_log(db_session, users["dispatcher"].id, outside, "PROBE_AUDIT_OUTSIDE")

    fn, cells = _audit_export(client, h, mode="day", date=day.isoformat())
    joined = "\n".join(str(c) for c in cells)
    assert "PROBE_AUDIT_INSIDE" in joined, f"区间内的日志没被列出来（{fn}）：{joined[:300]}"
    assert "PROBE_AUDIT_OUTSIDE" not in joined, (
        f"区间外的日志出现在这份审计报表里（{fn}）—— 这就是「名字写着 A、内容是 B」的凭证"
    )
    # 文件名必须写真实取数日（这里 date=锚点、mode=day → 单日）
    assert day.isoformat() in fn, f"文件名里没有真实取数日：{fn}"

    from app.models import OperationLog

    db_session.query(OperationLog).filter(OperationLog.id.in_([in_id, out_id])).delete(
        synchronize_session=False
    )
    db_session.commit()


def test_export_filename_follows_the_real_range_not_the_anchor(client, token_dispatcher):
    """按区间导出时，文件名必须写**区间**，不是锚点日。"""
    h = auth_headers(token_dispatcher)
    fn, _ = _audit_export(
        client,
        h,
        mode="day",
        date="2026-09-18",
        date_from="2026-09-01",
        date_to="2026-09-01",
    )
    assert "2026-09-01" in fn, f"文件名没写真实区间：{fn}"
    assert "2026-09-18" not in fn, (
        f"文件名还在用锚点日（内容是 09-01、名字却写 09-18）：{fn}"
    )

    # 不传区间时仍按锚点（老行为不许被改坏）
    fn2, _ = _audit_export(client, h, mode="day", date="2026-09-18")
    assert "2026-09-18" in fn2, f"没传区间时文件名应当是锚点日：{fn2}"


def test_audit_export_says_when_the_log_block_is_truncated(client, token_dispatcher, db_session, users):
    """区间内日志超过 200 条时要**如实说清**（"共 N 条，这里只列了最近 200 条"）。"""
    h = auth_headers(token_dispatcher)
    day = date.today() - timedelta(days=11)
    base = datetime(day.year, day.month, day.day, 2, 0, tzinfo=timezone.utc)
    ids = [_mk_log(db_session, users["dispatcher"].id, base + timedelta(seconds=i), f"PROBE_BULK_{i}") for i in range(205)]

    _fn, cells = _audit_export(client, h, mode="day", date=day.isoformat())
    joined = "\n".join(str(c) for c in cells)
    assert "205" in joined and "200" in joined, (
        f"日志块被截断了却没说清楚（应当写『区间内共 205 条，这里只列了最近 200 条』）：{joined[:400]}"
    )

    from app.models import OperationLog

    db_session.query(OperationLog).filter(OperationLog.id.in_(ids)).delete(synchronize_session=False)
    db_session.commit()
