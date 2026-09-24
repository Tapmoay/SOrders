"""请求追踪 id（core/request_id.py）：每个请求一个 id，回写响应头、进日志。

## 为什么单独立一条（2026-09-24 整改阶段 8 ①）

报告 §15 把 Request ID 列为可观测性要做的第一件小事：出了问题只能靠「时间点 + 接口 + 单号」
在日志里捞，而**并发下两条请求的日志是交错的** —— grep 出来的顺序是假的。

这条用例钉六件事（都是「错了也不报错」的那种）：
1. 响应头里必须有 X-Request-ID（客户端报障时要能贴过来）；
2. 客户端带了这个头就沿用（前置链路串起来的前提）；
3. 两个请求的 id 必须不同（相同 = 所有请求挤在一个 id 里，追踪等于没有）；
4. 请求外没有 id（后台任务不该蹭上某个请求的 id）；
5. **最后一跳**：审计行 `operation_logs.request_id` 必须有（2026-09-25 补 —— 报告 §15 ① 的链条
   `HTTP → request_id → service → DB/log → operation_log` 原来**断在这里**，前四跳早就通了）；
6. 请求外写的审计行是 NULL（脚本/后台任务写的那条，本来就不是「某个人点出来的」）。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.request_id import HEADER, MAX_ID_LEN, get_request_id
from app.main import fastapi_app
from tests.conftest import auth_headers


def test_response_carries_a_generated_request_id():
    with TestClient(fastapi_app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    rid = r.headers.get(HEADER)
    assert rid, "响应里没有 X-Request-ID —— 追踪链路的第一跳就断了"
    assert 8 <= len(rid) <= MAX_ID_LEN, rid


def test_incoming_request_id_is_reused():
    with TestClient(fastapi_app) as c:
        r = c.get("/health", headers={HEADER: "trace-from-nginx-001"})
    assert r.headers.get(HEADER) == "trace-from-nginx-001"


def test_two_requests_get_different_ids():
    with TestClient(fastapi_app) as c:
        a = c.get("/health").headers.get(HEADER)
        b = c.get("/health").headers.get(HEADER)
    assert a and b and a != b, "两个请求拿到同一个 id —— 日志会混成一锅"


def test_overlong_incoming_id_is_truncated():
    long_id = "x" * 200
    with TestClient(fastapi_app) as c:
        r = c.get("/health", headers={HEADER: long_id})
    assert r.headers.get(HEADER) == long_id[:MAX_ID_LEN]


def test_no_request_id_outside_a_request():
    assert get_request_id() == "", "请求外不该有 id（后台任务会蹭上别人的）"


# ------------------------------- 最后一跳：审计行（报告 §15 ①） -------------------------------
def test_operation_log_carries_the_request_id(client, token_dispatcher, db_session):
    """**最后一跳**：审计行里必须记得住产生它的那次请求 —— 否则报障时接不上。

    这一段为什么值得单独立一条：它断掉的样子**完全不报错** —— 审计行照写、审计页照显示，
    只是那一格永远是 NULL。真实场景是用户说「10:31 那笔账不对」，你有 HTTP 日志、
    却接不到审计表里那一行（而审计表才是「谁改了什么」的权威记录）。
    """
    from app.models import OperationLog

    h = auth_headers(token_dispatcher)
    h[HEADER] = "trace-audit-0001"
    made = client.post(
        "/api/v1/places",
        json={"name": "追踪点-最后一跳", "address_lat": 30.51, "address_lng": 114.31},
        headers=h,
    )
    assert made.status_code == 201, made.text
    # 走的是一条**确定会写审计**的端点（共享地点改名；`POST /places` 本身不写审计）。
    r = client.patch(
        f"/api/v1/places/{made.json()['id']}",
        json={"name": "追踪点-最后一跳（改过名）"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    row = (
        db_session.query(OperationLog)
        .filter(OperationLog.request_id == "trace-audit-0001")
        .order_by(OperationLog.id.desc())
        .first()
    )
    assert row is not None, "审计行没有带上 request_id —— 追踪链路的最后一跳还是断的"
    assert row.action, row.action


def test_operation_log_request_id_is_null_outside_a_request(db_session, users):
    """请求外写的审计行 → NULL（不是空串）：它本来就不是「某个人点出来的」。"""
    from app.models import OperationLog
    from app.models.enums import OperationAction
    from app.services.operation_log_service import write_log

    write_log(
        db_session,
        operator_id=users["dispatcher"].id,
        order_id=None,
        action=OperationAction.PLACE_UPDATE,
        change_payload={"why": "单元测试：请求外写日志"},
    )
    db_session.commit()
    row = db_session.query(OperationLog).order_by(OperationLog.id.desc()).first()
    assert row is not None
    assert row.request_id is None, f"请求外写的审计行不该有 request_id，实际 {row.request_id!r}"
