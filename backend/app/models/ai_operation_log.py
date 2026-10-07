"""AI 操作流水（CHG-0082 / 台账 L-52）：**AI 每一次动作都落一行，成没成都记**。

## 用户要的是哪一件事

用户 2026-10-08 原话（ref m26776，勾选项）：「**再加一张 AI 操作流水**：每次 AI 动作都落一行
（谁、何时、什么动作、成没成、失败原因），**管理端单独一页看**」。

## 为什么不是往 operation_logs 里加几列

`operation_logs` 记的是**业务写入成功之后**那一下（`services/operation_log_service.write_log`），
它有三个恰好配不上这个需求的形状：

1. **只有成功**（而且是"业务真的改了数据"的成功）—— AI 试了一次被 403 拒掉、被 422 打回来，
   在库里**一行都没有**，所以「成没成 / 失败原因」这两个问题它答不上来；
2. **一行 = 一次业务写入**，不是**一次 AI 动作**：一次 AI 动作可能改好几张表、也可能一个字节都没改
   （只是读）；反过来，批量派单那种一次请求会落下 N 行；
3. 它挂在**业务对象**上（`order_id` + `change_content`），而这本流水要回答的是
   「AI 什么时候、替谁、动了哪条接口」。

⛔ 所以这是一张**请求级**的表：一行 = 一次 `X-SOrders-Origin: ai` 的 HTTP 请求。
它与 `operation_logs` **不互相替代**：那本记"数据被改成了什么"，这本记"AI 动过什么、成没成"。
两者能用 `request_id` 对上（同一次请求里两行同 id）。

## 为什么记在中间件里，而不是各端点自己写

AI 的写动作走的是**普通业务端点**（这是本项目 AI 架构的既定事实：模型只能"申请"，
用户在确认卡上点过之后走真实接口执行）—— 所以**没有一个"AI 端点"可以挂**。
唯一区分得出来的东西就是那个请求头（`core/client_origin.py`，App 里只有一处会带它）。
把它记在 ASGI 中间件里，还有一个别处拿不到的好处：**4xx / 5xx 也看得见**（含响应体的 `detail`）。

## 口径

- `user_id` 可空：401 / 令牌失效时后端根本认不出人，但"有人拿 AI 头试过"这件事要留下（NULL = 认不出）；
- `action` 可空：动作 id 是**客户端给的**（`X-SOrders-Ai-Action`，值形如 `orders.create`），
  只做字符集与长度的白名单校验，认不出写 NULL —— ⛔ 不校验就等于让任何人往库里写任意字符串；
- `ok` = `status_code < 400`（与访问日志同一口径），单独建索引：管理端第一眼要看的就是"哪些失败了"；
- `error` 只在失败时写，取自后端 4xx/5xx 响应体里的 `detail`（用户看得懂的那句话），截断后存。
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.business_time import utc_now_naive
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class AiOperationLog(Base):
    __tablename__ = "ai_operation_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: 这次 AI 动作是**替谁**做的。NULL = 后端认不出人（401 / 令牌失效），不是"没有用户"。
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    #: AI 动作 id（`X-SOrders-Ai-Action`，形如 `orders.create`）。NULL = 这次请求没带 / 带了认不出。
    action: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 成没成（`status_code < 400`）。管理端的第一个筛选就是它。
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    #: 失败原因（只有失败时才有）：取后端响应体里的 `detail`，截断后存。
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 与 `operation_logs.request_id` 同一个 id —— 两本能对上同一次请求。
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 与全仓同一口径：**Python 写 UTC**（审计页按它排序、保留期治理也拿它比）。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now_naive, server_default=func.now(), index=True
    )

    user: Mapped["User | None"] = relationship()
