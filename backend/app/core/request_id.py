"""请求追踪 ID（2026-09-24 整改阶段 8 的第 ① 件：报告 §15「先做三件小事」之一）。

### 为什么先做它

报告对可观测性的要求是"先不要上复杂的平台，只做三个东西"，第一个就是 **Request ID**：

```text
HTTP → request_id → service → DB/log → operation_log
```

现状是：出了问题只能靠"时间点 + 接口 + 单号"在日志里捞，而**同一条日志可能来自任何一次请求**；
并发下两条请求的日志交错在一起，`grep` 出来的顺序是假的。给每个请求一个 id，
这一串日志才第一次成为"一次请求的完整轨迹"。

### 做了什么（刻意保持最小）

1. 每个请求拿一个 id：头里有 `X-Request-ID` 就用它（便于客户端 / nginx / 前置链路串起来），
   没有就现生成一个 12 位十六进制；
2. id 存进 `ContextVar` —— 业务代码用 `get_request_id()` 就能拿到，**不用层层传参**；
3. 响应带上同一个 `X-Request-ID`（客户端报障时把它贴过来即可）；
4. 一条访问日志：`方法 路径 状态码 耗时 request_id`；
5. `RequestIdFilter` 把 id 注入**所有**日志记录（配在 formatter 里），所以已有的 logger 一行都不用改。

### 三条刻意的取舍

· **纯 ASGI 中间件**（不是 `BaseHTTPMiddleware`）：后者会把流式响应包一层，导出大文件那种接口会掉性能，
  而且在"客户端断开"时的异常语义更绕；
· **不记查询串**：`?q=13800000000` 这种会把手机号写进日志（本仓库真发生过凭据进日志的事）；
· **id 由客户端给时不校验格式**，只截断到 64 字符 —— 它是**追踪用**的，不是安全边界；
  拿它当鉴权/去重依据是另一回事（这里不做，也不该做）。
"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

logger = logging.getLogger("app.access")

#: 当前请求的追踪 id。默认空串 = "不在请求上下文里"（后台任务 / 启动期日志）。
_request_id: ContextVar[str] = ContextVar("request_id", default="")

HEADER = "X-Request-ID"
#: 客户端给的 id 只截断、不校验格式（见文件头第 3 条取舍）。
MAX_ID_LEN = 64


def get_request_id() -> str:
    """当前请求的追踪 id（不在请求里时返回空串）。业务代码 / 日志 filter 都用它。"""
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """给**每一条**日志记录塞一个 `request_id` 字段（formatter 里用 `%(request_id)s`）。

    为什么用 filter 而不是改每个 logger：本仓库有几百处 `logger.warning(...)`，
    逐个加参数既改不完、也没人保证新代码会加 —— filter 是**一处生效**的那条路。
    不在请求上下文里（启动、后台任务）时是 `-`，一眼能区分。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", ""):
            record.request_id = get_request_id() or "-"
        return True


class RequestIdMiddleware:
    """纯 ASGI：给每个请求分配/透传 id，回写响应头，并打一行访问日志。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":            # websocket / lifespan 不管
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(HEADER.lower().encode(), b"").decode("latin-1").strip()
        rid = incoming[:MAX_ID_LEN] or uuid.uuid4().hex[:12]
        token = _request_id.set(rid)
        status_holder = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                raw = list(message.get("headers") or [])
                raw.append((HEADER.lower().encode(), rid.encode()))
                message = {**message, "headers": raw}
            await send(message)

        started = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            cost_ms = (time.perf_counter() - started) * 1000
            # ⛔ 只记路径，不记查询串（`?q=手机号` 会进日志，仓库里真发生过这类事）。
            logger.info(
                "%s %s → %s（%.1f ms）",
                scope.get("method", "?"), scope.get("path", "?"), status_holder["code"], cost_ms,
            )
            _request_id.reset(token)
