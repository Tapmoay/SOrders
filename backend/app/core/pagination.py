"""列表端点的**唯一**出口：把「这次是不是被截断了」如实写进响应头。

### 为什么要有这个模块（2026-09-19 外部完整检查 §9.1 + 本轮补）
列表接口的形状是「`limit` 参数 + 裸数组响应体」。裸数组加不了元数据，所以"还有更多"
只能走响应头：`X-Truncated`（`1`/`0`）与 `X-Result-Limit`（本次上限）。
判据是**多取一行**：拿到 `limit + 1` 行就说明还有更多，然后把多的那行丢掉。

⛔ 不这么做的后果**不是"少看到几条"**，而是用户/模型据此得出**错误结论**：
- 派单员在「全部订单」里以为看到了全部，据此判断"这单不存在"（第八轮 R14-8）；
- 现金流水页把"拉一页自己求和"当成总额 —— 实测默认 200 条求和 ¥18,842，
  真值 ¥48,905.50（少算 **62%**，见 `api/v1/cash_flows.py::cash_flow_summary` 的注释）；
- AI 读能力少要一行就永远测不出截断，答"你一共有 200 条消息"（真值 2336）。

### 为什么是一个共享函数，而不是每个模块抄一遍
这条规则原来散在 3 个模块里各写一份，而**另外 5 个有 `limit` 的端点一份都没有**
（`cash_flows`/`inventory`/`operation_logs`/`places`/`users`）——"有上限却不说"这一类
就是这么漏出来的。现在只有一个实现：谁有 `limit` 就调 `finish_page()`。
红线 `_tools/qa/_check_pagination_wiring.py` **自己算**哪些端点声明了 `limit`
（正则扫函数签名，带数量下限），少一个接线就红。
"""

from __future__ import annotations

from typing import Any, Sequence, TypeVar

from fastapi import Response

T = TypeVar("T")


def finish_page(rows: Sequence[T], limit: int, response: Response) -> list[T]:
    """`rows` 是**多取了一行**的结果 → 判截断、写两个响应头、返回截断后的行。

    用法（所有列表端点都长这样）：

        stmt = stmt.limit(limit + 1)          # ← 多取一行
        rows = list(db.scalars(stmt).all())
        return finish_page(rows, limit, response)

    ⚠️ `limit` 必须是**本次真正生效的上限**（用户传的值或缺省值），不是常量：
    写错了客户端会说"一共就这么多"。
    """
    truncated = len(rows) > limit
    out = list(rows[:limit]) if truncated else list(rows)
    response.headers["X-Result-Limit"] = str(limit)
    response.headers["X-Truncated"] = "1" if truncated else "0"
    return out


def page_size(requested: int | None, default: int) -> int:
    """`limit` 参数的取值口径：没传用缺省，传了按传的（范围由 Endpoint 的 `Query(ge/le)` 管）。"""
    return int(requested) if requested else default


__all__ = ["finish_page", "page_size", "Any"]
