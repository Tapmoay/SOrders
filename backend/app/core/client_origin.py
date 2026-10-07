"""**这一次请求是谁发起的**（人工 / AI 助手）—— 报告 §15 ② 那两个指标的最后一块拼图。

## 为什么后端必须自己记，而不是让 App 报一个计数上来
`AI_write_confirmed`（「AI 确认卡点了几次写入」）原来列在 `core/metrics.py` 的 `NOT_TRACKED` 里，
理由写的是「后端看不到」：AI 写入走的是**普通业务端点**，与人工写入**完全同形**
（那是当初刻意的设计，见 AI 写操作架构），所以从 `operation_logs` 里分不出来。

要让两者分得开只有一条路：**App 在「这张卡是用户确认过的 AI 写入」时带一个请求头**，
后端把它记进 `operation_logs.origin`。

⛔ **关键取舍：计数由后端从库里数出来，不是让 App 报一个数字上来。**
后者能被一个客户端 bug 直接改掉，而且与 `operation_logs` 对不上账 ——
而指标的价值恰恰在于「它与审计表是同一个事实」。

## 为什么只认白名单里的值
请求头是客户端可控的。⛔ 不校验就等于让任何人往 `origin` 里写任意字符串（还会污染指标口径）。
所以只认白名单；**认不出的值不报错，落回 `human`** —— 一个拼错的头不该让业务请求失败，
但也绝不能被当成 `ai`。
"""

from __future__ import annotations

from contextvars import ContextVar, Token

#: 白名单。`human` 是默认值（也是"不在请求里"时的值）。
HUMAN = "human"
AI = "ai"
ALLOWED = frozenset({HUMAN, AI})

HEADER = "X-SOrders-Origin"
#: 截断长度：只可能放进白名单里的短词，多出来的字节没有意义。
MAX_LEN = 16

#: 2026-10-08 CHG-0082：**这一次 AI 动作是哪一个**（值形如 `orders.create`，即 App 里
#: `AiWriteAction.id`）。与上面的 origin 头一起由 App 在**同一个地方**带上
#: （`ai/AiWriteService.commit`），供「AI 操作流水」（`core/ai_operation.py`）记下动作名。
#: ⛔ 它**不是**授权依据（授权仍然只看登录用户的角色与权限）：动作名只用于"看得懂"这一件事。
ACTION_HEADER = "X-SOrders-Ai-Action"
#: 动作名的上限：与 `ai_operation_logs.action` 那一列（String(64)）同宽。
ACTION_MAX_LEN = 64

_origin: ContextVar[str] = ContextVar("client_origin", default=HUMAN)
_action: ContextVar[str | None] = ContextVar("client_ai_action", default=None)

#: 动作名允许出现的字符（见 [normalize_action]）。
_ACTION_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
)


def normalize_origin(raw: str | None) -> str:
    """把请求头归一成白名单里的值；认不出的一律 `human`。"""
    v = (raw or "").strip().lower()[:MAX_LEN]
    return v if v in ALLOWED else HUMAN


def get_origin() -> str:
    """当前请求的来源（不在请求上下文里时是 `human`）。审计写入处用它。"""
    return _origin.get()


def set_origin(raw: str | None) -> Token:
    return _origin.set(normalize_origin(raw))


def reset_origin(token: Token) -> None:
    _origin.reset(token)


def normalize_action(raw: str | None) -> str | None:
    """把动作头归一成"能存进库"的形状；认不出的一律 `None`。

    ⛔ 白名单是**字符集**而不是一张动作清单（与 origin 那张 `ALLOWED` 不同）：
    动作清单长在 App 里（`AiWrite.kt`），后端抄一份必然走散。
    所以这里只做"允许长什么样"的校验：`[A-Za-z0-9_.:-]`、长度 ≤ 64，
    其它一律 `None`（= 这次动作名认不出）—— 既不报错、也不让任意字符串进库。

    ⚠️ 字符集是**显式 ASCII 常量**、不用 `str.isalnum()`：后者对中文也返回 True
    （动作 id 是代码标识符，中文名进库只会让管理端那一页多出一列看不懂的乱码）。
    """
    v = (raw or "").strip()[:ACTION_MAX_LEN]
    if not v:
        return None
    if not all(c in _ACTION_CHARS for c in v):
        return None
    return v


def get_action() -> str | None:
    """当前请求的 AI 动作名（不是 AI 请求 / 没带 / 认不出时为 `None`）。"""
    return _action.get()


def set_action(raw: str | None) -> Token:
    return _action.set(normalize_action(raw))


def reset_action(token: Token) -> None:
    _action.reset(token)