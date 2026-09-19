"""第十四轮审计的回归测试：**钱相关的主数据改动必须留痕**（R14-1）。

真机实证：用 AI 建了一个挂账单位（`arrears_units id=49`），库里多了一行、
**审计页上什么都没有** —— `arrears.py` 四个写端点一次 `write_log` 都没调；
`freight_templates.py` 同样（4 个写端点、0 条日志）。

为什么这是缺陷而不是"少个功能"：
- 挂账单位决定**钱挂在谁名下**，单位改名之后历史欠款按 `arrears_unit_name` **快照**分组，
  改名/删除之后没有任何地方能回答"这名字是谁改的、什么时候改的"；
- 运费模板是派单填运费的**参考价**，改一个数字影响所有人报价；
- 而 AI 写操作的设计承诺就是"与人工操作同形、事后可回查"（`operation_logs` 是审计页唯一的数据源）。
"""
from __future__ import annotations

from decimal import Decimal

from tests.conftest import auth_headers


def _log_count(db_session, action: str) -> int:
    from app.models import OperationLog

    return db_session.query(OperationLog).filter(OperationLog.action == action).count()


def test_arrears_unit_writes_leave_an_audit_trail(client, token_dispatcher, db_session):
    from app.models import OperationAction

    h = auth_headers(token_dispatcher)
    before = _log_count(db_session, OperationAction.ARREARS_UNIT_UPSERT)

    r = client.post("/api/v1/arrears-units", json={"name": "留痕探针单位", "phone": "13900002222"}, headers=h)
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    assert _log_count(db_session, OperationAction.ARREARS_UNIT_UPSERT) == before + 1, "新建挂账单位没有留痕"

    r = client.patch(f"/api/v1/arrears-units/{uid}", json={"name": "留痕探针单位改"}, headers=h)
    assert r.status_code == 200, r.text
    assert _log_count(db_session, OperationAction.ARREARS_UNIT_UPSERT) == before + 2, "改挂账单位没有留痕"

    # 日志里要能看出**改前叫什么**（不然"改名"这件事查不出来）
    from app.models import OperationLog

    last = (
        db_session.query(OperationLog)
        .filter(OperationLog.action == OperationAction.ARREARS_UNIT_UPSERT)
        .order_by(OperationLog.id.desc())
        .first()
    )
    assert last is not None and last.change_content is not None
    assert "留痕探针单位" in last.change_content and "before" in last.change_content, last.change_content

    before_del = _log_count(db_session, OperationAction.ARREARS_UNIT_DELETE)
    assert client.delete(f"/api/v1/arrears-units/{uid}", headers=h).status_code in (200, 204)
    assert _log_count(db_session, OperationAction.ARREARS_UNIT_DELETE) == before_del + 1, "删挂账单位没有留痕"

    before_res = _log_count(db_session, OperationAction.ARREARS_UNIT_RESTORE)
    assert client.post(f"/api/v1/arrears-units/{uid}/restore", headers=h).status_code == 200
    assert _log_count(db_session, OperationAction.ARREARS_UNIT_RESTORE) == before_res + 1, "恢复挂账单位没有留痕"


def test_freight_template_writes_leave_an_audit_trail(client, token_dispatcher, db_session):
    from app.models import OperationAction, OperationLog

    h = auth_headers(token_dispatcher)
    before = _log_count(db_session, OperationAction.FREIGHT_TEMPLATE_UPSERT)

    r = client.post(
        "/api/v1/freight-templates",
        json={"name": "留痕探针线", "from_place": "甲", "to_place": "乙", "fee": 100},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    tid = r.json()["id"]
    assert _log_count(db_session, OperationAction.FREIGHT_TEMPLATE_UPSERT) == before + 1, "新建运费模板没有留痕"

    r = client.put(f"/api/v1/freight-templates/{tid}", json={"fee": 250}, headers=h)
    assert r.status_code == 200, r.text
    assert _log_count(db_session, OperationAction.FREIGHT_TEMPLATE_UPSERT) == before + 2, "改运费模板没有留痕"
    last = (
        db_session.query(OperationLog)
        .filter(OperationLog.action == OperationAction.FREIGHT_TEMPLATE_UPSERT)
        .order_by(OperationLog.id.desc())
        .first()
    )
    assert last is not None and last.change_content is not None
    # 价格改动必须能看出"从多少改到多少"
    assert "100" in last.change_content and "250" in last.change_content, last.change_content

    before_del = _log_count(db_session, OperationAction.FREIGHT_TEMPLATE_DELETE)
    assert client.delete(f"/api/v1/freight-templates/{tid}", headers=h).status_code in (200, 204)
    assert _log_count(db_session, OperationAction.FREIGHT_TEMPLATE_DELETE) == before_del + 1, "删运费模板没有留痕"

    before_res = _log_count(db_session, OperationAction.FREIGHT_TEMPLATE_RESTORE)
    assert client.post(f"/api/v1/freight-templates/{tid}/restore", headers=h).status_code == 200
    assert _log_count(db_session, OperationAction.FREIGHT_TEMPLATE_RESTORE) == before_res + 1, "恢复运费模板没有留痕"


def test_ai_created_arrears_unit_shows_up_in_the_audit_list(client, token_dispatcher, db_session):
    """AI 建的挂账单位必须能在审计页（operation_logs 驱动）里查到——真机上就是查不到。"""
    h = auth_headers(token_dispatcher)
    r = client.post("/api/v1/arrears-units", json={"name": "审计页探针单位"}, headers=h)
    uid = r.json()["id"]

    rows = client.get("/api/v1/reports/export?kind=audit&mode=day&date=2026-09-19", headers=h)
    assert rows.status_code == 200, rows.text  # 导出能跑通（下面查日志表本身）
    from app.models import OperationLog

    hit = (
        db_session.query(OperationLog)
        .filter(OperationLog.action == "ARREARS_UNIT_UPSERT")
        .order_by(OperationLog.id.desc())
        .first()
    )
    assert hit is not None and f'"unit_id": {uid}' in (hit.change_content or ""), hit
