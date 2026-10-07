"""AI 操作流水（CHG-0082 / 台账 L-52）：**AI 发起的每一次请求都要留下一行**。

用户的验收口径（2026-10-08 原话）：「每次 AI 动作都落一行（谁、何时、什么动作、成没成、失败原因），
管理端单独一页看」。于是这个文件钉的就是那五个词 —— 每一个都对应一条断言：

| 用户要的 | 钉在哪 |
|---|---|
| **每一次**（成没成都算） | 成功记一行 + **失败也记一行**（`operation_logs` 只在业务写成功之后才有行，两条用例并排就是差别） |
| **谁** | `user_id` = 登录用户；**鉴权通过但被权限拦下**时也照样是他的 id |
| **什么动作** | `X-SOrders-Ai-Action` 头 → `action` 列 |
| **成没成** | `ok` / `status_code` |
| **失败原因** | `error` = 后端给用户的那句 `detail` |

还有两条**只在这类中间件上才会犯**的错，各配一条反向用例：

- **顺序错**：AI 流水挂在 `RequestIdMiddleware` **外面**时，收尾读到的 `request_id` 已经被清空
  （那三个上下文变量是那一层的 `finally` 清的）⇒ 流水里全是 NULL。判据：流水行的
  `request_id` 必须**等于响应头 `X-Request-ID`**（不是"非空"——非空也能是别的值）。
- **审计把业务搞挂**：写流水一旦抛错不能影响响应。判据：把写入函数打瘸，请求照样 200/403。
"""

from __future__ import annotations

from sqlalchemy import func

from app.models import AiOperationLog, User
from tests.conftest import auth_headers

#: 与 App 里 `core/ClientOrigin.kt` 的两个头一字不差（改这里必须两边一起改）。
ORIGIN_HEADER = "X-SOrders-Origin"
ACTION_HEADER = "X-SOrders-Ai-Action"


def _ai_headers(token: str, action: str | None = None) -> dict[str, str]:
    h = {**auth_headers(token), ORIGIN_HEADER: "ai"}
    if action is not None:
        h[ACTION_HEADER] = action
    return h


def _rows(db, since_id: int) -> list[AiOperationLog]:
    """本次请求产生的那几行（按 id > 请求前的最大 id 取，免得被同一个 worker 库里的别的行干扰）。"""
    db.expire_all()
    return (
        db.query(AiOperationLog)
        .filter(AiOperationLog.id > since_id)
        .order_by(AiOperationLog.id)
        .all()
    )


def _max_id(db) -> int:
    return int(db.query(func.max(AiOperationLog.id)).scalar() or 0)


def test_ai_request_leaves_one_row_with_who_what_and_result(client, db_session, token_dispatcher, users):
    """成功的一次 AI 请求：一行，五个字段齐全，`request_id` 与响应头对得上。"""
    before = _max_id(db_session)
    r = client.get("/api/v1/orders", headers=_ai_headers(token_dispatcher, "orders.list"))
    assert r.status_code == 200, r.text

    rows = _rows(db_session, before)
    assert len(rows) == 1, f"一次 AI 请求应该恰好留一行，实际 {len(rows)} 行"
    row = rows[0]
    assert row.user_id == users["dispatcher"].id           # 谁
    assert row.action == "orders.list"                      # 什么动作
    assert row.path == "/api/v1/orders" and row.method == "GET"
    assert row.ok is True and row.status_code == 200        # 成没成
    assert row.error is None                                # 成功了就不该有"失败原因"
    assert row.duration_ms >= 0
    # ⚠️ 这一条钉的是**中间件顺序**：挂在 RequestIdMiddleware 外面时这里是 None（见文件头）。
    assert row.request_id is not None, "流水里没有 request_id —— AI 流水挂到请求 id 那一层外面了"
    assert row.request_id == r.headers.get("X-Request-ID")
    assert row.created_at is not None


def test_human_request_leaves_nothing(client, db_session, token_dispatcher):
    """同一个端点、同一张令牌，**不带** origin 头：一行都不许有（普通用户不是 AI）。"""
    before = _max_id(db_session)
    r = client.get("/api/v1/orders", headers=auth_headers(token_dispatcher))
    assert r.status_code == 200, r.text
    assert _rows(db_session, before) == []


def test_failed_ai_request_is_recorded_with_reason(client, db_session, token_shipper, users):
    """**被权限拦下的 AI 请求也要留痕**——这正是"AI 试了但没做成"那半本账。

    ⚠️ 顺带钉死一件事：`X-SOrders-Origin: ai` **不是**提权手段。
    货主拿着 AI 头去读审计（派单员专属），照样 403 —— 权限只看登录用户。
    """
    before = _max_id(db_session)
    r = client.get("/api/v1/operation-logs", headers=_ai_headers(token_shipper, "operation_logs.list"))
    assert r.status_code == 403, r.text

    rows = _rows(db_session, before)
    assert len(rows) == 1, f"失败也要留一行，实际 {len(rows)} 行"
    row = rows[0]
    assert row.user_id == users["shipper"].id
    assert row.ok is False and row.status_code == 403
    assert row.error, "403 那一行没有失败原因 —— 管理端会看到一个'不知道为什么没做成'的 AI"
    assert row.action == "operation_logs.list"


def test_action_header_is_sanitised_before_it_reaches_the_database(client, db_session, token_dispatcher):
    """动作名是客户端说了算的字符串 ⇒ 认不出的形状一律 **NULL**，不许原样进库。

    中文动作名（`str.isalnum()` 对它是 True）和超长串是两种最容易被放过去的形状。
    """
    before = _max_id(db_session)
    # ⚠️ 这里只能用 **ASCII 但形状非法** 的值：HTTP 头本身放不下非 ASCII 字符
    #    （httpx 在发出去之前就 UnicodeEncodeError 了），所以"中文动作名"那条在下面的
    #    纯函数用例里钉（`normalize_action("下单")` —— `str.isalnum()` 对中文返回 True 的那个坑）。
    client.get("/api/v1/orders", headers=_ai_headers(token_dispatcher, "orders.create!"))
    client.get("/api/v1/orders", headers=_ai_headers(token_dispatcher, "x" * 200))
    rows = _rows(db_session, before)
    assert len(rows) == 2
    assert rows[0].action is None, "非法字符的动作名原样进了库"
    assert rows[1].action == "x" * 64, "超长动作名没有被截到 64"


def test_ai_operations_endpoint_lists_and_filters(client, db_session, token_dispatcher, token_shipper, users):
    """管理端那一页的数据源：列表 + 三把筛子 + 截断位。"""
    before = _max_id(db_session)
    client.get("/api/v1/orders", headers=_ai_headers(token_dispatcher, "orders.list"))
    client.get("/api/v1/operation-logs", headers=_ai_headers(token_shipper, "operation_logs.list"))

    r = client.get("/api/v1/ai/operations", headers=auth_headers(token_dispatcher), params={"limit": 50})
    assert r.status_code == 200, r.text
    body = r.json()
    # ⚠️ 列表是 id **倒序**（新的在前）：先排一次序，别拿"第一条"当"第一笔写的"。
    ids = sorted(item["id"] for item in body if item["id"] > before)
    assert len(ids) == 2, f"列表里应当有刚写的两行，实际 {ids}"
    mine = next(item for item in body if item["id"] == ids[0])
    assert mine["user_name"] == "Dispatcher", "列表没带出用户名（管理端只能看到编号）"
    assert mine["action"] == "orders.list"
    # 列表接口必须报截断状态（响应体是裸数组，加不了元数据）
    assert "X-Truncated" in r.headers and "X-Result-Limit" in r.headers

    only_failed = client.get(
        "/api/v1/ai/operations", headers=auth_headers(token_dispatcher), params={"ok": "false", "user_id": users["shipper"].id}
    ).json()
    assert [i["id"] for i in only_failed if i["id"] > before] == [ids[1]]
    assert only_failed[0]["ok"] is False and only_failed[0]["error"]

    by_action = client.get(
        "/api/v1/ai/operations", headers=auth_headers(token_dispatcher), params={"action": "orders.list"}
    ).json()
    assert ids[1] not in [i["id"] for i in by_action]


def test_ai_operations_page_is_dispatcher_only(client, token_shipper):
    """能看审计页（`OPERATION_LOG_READ`）的人才看得到 AI 流水；货主 403。"""
    assert client.get("/api/v1/ai/operations", headers=auth_headers(token_shipper)).status_code == 403


def test_audit_write_failure_never_breaks_the_request(client, db_session, token_dispatcher, monkeypatch):
    """**审计绝不许把业务搞挂**：写流水这一路抛错时，请求该 200 还是 200。

    这是本模块唯一允许的失败模式（"少记一行"），而它必须被钉住 ——
    否则哪天 `ai_operation_logs` 结构漂了，AI 的所有动作会一起变成 500。
    """
    import app.core.ai_operation as mod

    def boom(*_a, **_kw):
        raise RuntimeError("库写不进去（这条用例故意打的）")

    monkeypatch.setattr(mod, "record_ai_operation", boom)
    r = client.get("/api/v1/orders", headers=_ai_headers(token_dispatcher, "orders.list"))
    assert r.status_code == 200, r.text


def test_normalize_action_and_extract_error_units():
    """两个纯函数：动作名的形状校验、失败原因的抠取。"""
    from app.core.ai_operation import extract_error
    from app.core.client_origin import normalize_action

    assert normalize_action("orders.create") == "orders.create"
    assert normalize_action("  orders.create  ") == "orders.create"
    assert normalize_action("order.discount:apply") == "order.discount:apply"
    assert normalize_action("") is None
    assert normalize_action(None) is None
    assert normalize_action("下单") is None
    assert normalize_action("orders.create!") is None
    assert normalize_action("x" * 200) == "x" * 64

    assert extract_error(200, b'{"ok": true}') is None
    # ⚠️ 用 .encode() 而不是 b"…"：bytes 字面量只能是 ASCII，中文写进去是 SyntaxError。
    assert extract_error(404, '{"detail": "未找到对应记录"}'.encode()) == "未找到对应记录"
    assert extract_error(422, b"not-json") == "not-json"
    assert extract_error(500, b"") is None
    assert len(extract_error(500, b'{"detail": "' + b"x" * 900 + b'"}') or "") == 500
