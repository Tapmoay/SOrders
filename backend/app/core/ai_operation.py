"""AI 操作流水（CHG-0082 / 台账 L-52）：**只在 AI 发起的那次请求上记一行**。

## 为什么是中间件（而不是各端点自己写）

AI 的写动作走的是**普通业务端点**（本项目 AI 架构的既定事实：模型只能"申请"，用户在确认卡上
点过之后由 `ai/AiWriteService` 调真实接口执行）—— 所以**没有一个"AI 端点"可以挂**。
唯一区分得出来的是请求头 `X-SOrders-Origin: ai`（`core/client_origin.py`）。
放在这里还有两个端点里拿不到的好处：

- **4xx / 5xx 也看得见**（含后端给用户的那句 `detail`）—— 而"AI 试了但被拦住"正是用户要的那半本账；
- **一处生效**：以后新增多少 AI 动作都不用改这里（这正是用户要的"每次 AI 动作都落一行"）。

## 三条硬纪律（每一条都是踩过的那类坑）

1. **独立的 DB 会话**（`SessionLocal()`，不用请求那条 `get_db`）：业务事务回滚**不该**把审计行
   一起带走 —— 否则"失败的动作"刚好一行都不剩，而它正是这本账存在的理由。
2. **放到线程里跑**（`run_in_threadpool`）：这是 ASGI 中间件，**同步 DB 调用会卡住事件循环**
   （本项目后端是 `def` 同步端点 + 线程池的混合形态，规矩是"异步上下文里不碰同步 Session"）。
3. **任何异常都吞掉、只记日志**：审计绝不许把一次**业务上成功**的请求变成 500。
   ⛔ 这一条是刻意的：本模块的失败模式只能是"少记一行"，不能是"把用户的操作搞失败"。

## 它不做什么

- **不做授权**：`X-SOrders-Origin` / `X-SOrders-Ai-Action` 都是客户端可控的，
  权限永远只看登录用户的角色（`deps.require_permission`）。这里记的是"App 说这是 AI 干的"，
  与 `operation_logs.origin` 是同一个口径（那边也只有这一条证据）。
- **不记用户名 / 订单号**：那一页要显示的名字由端点 join 出来（`api/v1/ai_operations.py`）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.core.client_origin import AI, HEADER as ORIGIN_HEADER, get_action, normalize_origin
from app.core.request_id import get_request_id

logger = logging.getLogger("app.ai_operation")

#: 失败原因最多存这么多字符（后端那句 `detail` 一般不到 100 字，截断只是兜底）。
MAX_ERROR_LEN = 500
#: 失败响应体最多读这么多字节（**只在失败时**读：成功响应可能是几万行的列表）。
MAX_BODY_BYTES = 8192
#: `path` 那一列是 String(255)：超长路径（几乎不会发生）截断存，别让一次记录失败。
MAX_PATH_LEN = 255


def is_ai_request(scope: dict[str, Any]) -> bool:
    """这次请求带了 `X-SOrders-Origin: ai` 吗（与 `core/client_origin.py` 同一套归一）。

    ⚠️ 这里**自己读头**、不读 `get_origin()`：中间件比 `RequestIdMiddleware` **靠外**
    （后挂的更靠外），它运行时那个上下文变量还没被设上。
    """
    headers = dict(scope.get("headers") or [])
    raw = headers.get(ORIGIN_HEADER.lower().encode(), b"").decode("latin-1")
    return normalize_origin(raw) == AI


def extract_error(status_code: int, raw: bytes) -> str | None:
    """把一次失败响应的**原因**抠出来（成功响应返回 `None`）。

    取的是后端给用户看的那句话（`{"detail": "..."}`）—— 它本来就是人话，
    而管理端那一页要回答的正是"AI 为什么没做成"。抠不出来就退回原始文本（截断）。
    """
    if status_code < 400:
        return None
    text = raw.decode("utf-8", "replace").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    if isinstance(payload, dict) and "detail" in payload:
        detail = payload["detail"]
        text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
    text = text.strip()
    return text[:MAX_ERROR_LEN] or None


def record_ai_operation(
    *,
    user_id: int | None,
    action: str | None,
    method: str,
    path: str,
    status_code: int,
    error: str | None,
    request_id: str | None,
    duration_ms: int,
) -> None:
    """把一行写进 `ai_operation_logs`（**同步**函数，由中间件丢进线程池调）。

    ⛔ 独立的 `SessionLocal()`：与请求那条会话无关（见模块说明第 1 条）。
    ⛔ 这里的异常**必须**被吞掉：少记一行可以，让用户的操作失败不行。
    """
    from app.core.business_time import utc_now_naive
    from app.database import SessionLocal
    from app.models.ai_operation_log import AiOperationLog

    db = SessionLocal()
    try:
        db.add(
            AiOperationLog(
                user_id=user_id,
                action=action,
                method=method[:8],
                path=path[:MAX_PATH_LEN],
                status_code=int(status_code),
                ok=int(status_code) < 400,
                error=error,
                request_id=request_id,
                duration_ms=int(duration_ms),
                created_at=utc_now_naive(),
            )
        )
        db.commit()
    except Exception as exc:                      # noqa: BLE001 —— 见上面第 3 条纪律
        db.rollback()
        logger.warning("AI 操作流水写入失败：%s", exc)
    finally:
        db.close()


class AiOperationMiddleware:
    """纯 ASGI：AI 请求结束时写一行流水（成功/失败都写）。非 AI 请求零开销地放行。"""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not is_ai_request(scope):
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        state = {"status": 500, "started": False}
        body = bytearray()

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                state["status"] = int(message["status"])
                state["started"] = True
            elif message["type"] == "http.response.body" and state["status"] >= 400:
                # 只有失败才攒响应体（成功的列表可能很大，攒它没有意义）。
                chunk = message.get("body") or b""
                room = MAX_BODY_BYTES - len(body)
                if room > 0:
                    body.extend(chunk[:room])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            status_code = state["status"] if state["started"] else 500
            if state["started"]:
                error = extract_error(status_code, bytes(body))
            else:
                # 没走到响应：被取消 / 未捕获异常（外层 ServerErrorMiddleware 会回 500）。
                error = "（这次请求没有走到响应）"
            # `scope["state"]` 由 `deps.get_current_user` 写（同一个 dict，一路传下来的就是它）；
            # 认不出人时为 None —— 那不是缺陷，"有个没登录的请求带着 AI 头"本身就是事实。
            user_id = (scope.get("state") or {}).get("user_id")
            try:
                await run_in_threadpool(
                    record_ai_operation,
                    user_id=user_id if isinstance(user_id, int) else None,
                    action=get_action(),
                    method=str(scope.get("method", "?")),
                    path=str(scope.get("path", "?")),
                    status_code=status_code,
                    error=error,
                    request_id=get_request_id() or None,
                    duration_ms=duration_ms,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:              # noqa: BLE001 —— 同文献第 3 条纪律
                logger.warning("AI 操作流水记录失败：%s", exc)
