"""用户输入 → `LIKE` 的 pattern：**唯一**一处（2026-09-24 第 19 轮）。

## 为什么必须有（实测）
全项目 4 处把用户输入直接拼成 `f"%{kw}%"` 塞进 `LIKE`，没有一处转义 `%` / `_`：
`places.py`、`orders.py`（两条路径）、`core/user_search.py`。
LIKE 里这两个字符是**通配符**，于是用户在搜索框里打一个 `%`：

| 请求 | 结果 |
| --- | --- |
| `GET /places?q=%25` | 200 / **64 条 = 全表**（库真值 64） |
| `GET /orders?q=%25&limit=5000` | 200 / **426 条 = 全部订单** |
| `GET /users?q=%25` | 200 / **59 条 = 全部账号** |
| `GET /customers?q=%25` | 200 / **35 条 = 全部客户**（该端点无 limit，整表下发） |
| `GET /orders?q=zzz` | 0 条（对照） |

用户看到的是"搜索没生效"（列表回到全量），而真实的后果是**越权面**与**成本**：
`/customers`、`/users` 会整表下发，`/orders` 会退化成全量扫描 + 大响应。
`_` 同理（单字符通配）。

## 口径
- 只转义 `\\`、`%`、`_` 三个字符（反斜杠必须**先**转义，否则会把后面刚加的反斜杠再转一次）；
- 两侧仍是 `%…%`（子串匹配，语义不变）；
- 调用方 `.like(pattern, escape="\\\\")` —— 两处必须成对，所以 pattern 与 escape 由
  本模块的两个常量一起给出（见 [LIKE_ESCAPE]）。

⚠️ 这个 docstring 是**普通字符串**，所以上面写"反斜杠"时必须写成 `\\`（两个字符）——
   直接写一个反斜杠后面跟反引号会让 Python 3.12+ 每次编译本模块都报
   `SyntaxWarning: invalid escape sequence`（第 19 轮漏了，第 22 轮发现：它把两个
   生成脚本的输出都染了一行警告，看着像生成器坏了）。

⚠️ 不要去改 `field.contains(kw)`：SQLAlchemy 的 `contains()` 同样不转义
（它只是 `like` 的语法糖），所以这一族必须显式构造 pattern。
"""

from __future__ import annotations

#: 与 [like_pattern] 成对使用的 escape 字符（SQLAlchemy `.like(..., escape=LIKE_ESCAPE)`）。
LIKE_ESCAPE = "\\"


def like_pattern(keyword: str | None) -> str | None:
    """`kw` → `%…%` 的 LIKE pattern（`%`/`_`/`\\` 全部转义）；空输入 → `None`（不加条件）。

    调用方拿到 `None` 时**不要**构造恒真谓词（那会让"搜索生效了没有"说不清）。
    """
    term = (keyword or "").strip()
    if not term:
        return None
    escaped = (
        term.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"
