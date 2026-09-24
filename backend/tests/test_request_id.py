"""请求追踪 id（core/request_id.py）：每个请求一个 id，回写响应头、进日志。

## 为什么单独立一条（2026-09-24 整改阶段 8 ①）

报告 §15 把 Request ID 列为可观测性要做的第一件小事：出了问题只能靠「时间点 + 接口 + 单号」
在日志里捞，而**并发下两条请求的日志是交错的** —— grep 出来的顺序是假的。

这条用例钉四件事（都是「错了也不报错」的那种）：
1. 响应头里必须有 X-Request-ID（客户端报障时要能贴过来）；
2. 客户端带了这个头就沿用（前置链路串起来的前提）；
3. 两个请求的 id 必须不同（相同 = 所有请求挤在一个 id 里，追踪等于没有）；
4. 请求外没有 id（后台任务不该蹭上某个请求的 id）。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.request_id import HEADER, MAX_ID_LEN, get_request_id
from app.main import fastapi_app


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
