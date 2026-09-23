"""`?date_from&date_to` 的**唯一**校验口径（两个都是 `Date` 列的那种窗口）。

## 为什么要有这个模块（2026-09-24 第 19 轮实测）
同一族参数在项目里有两套解析：
- `deps.parse_date_window()` —— 给**时间戳**列用（返回带时间的 `datetime`，还要做业务时区换算）；
- 各端点自己那几句 `date.fromisoformat(...)` —— 给 **`Date` 列**用（账本 `entry_date`、
  资金流水 `flow_date`、开销 `exp_date`）。

后者原来**只有格式校验、没有顺序校验**，于是同一个"日期反了"的输入：
- `/orders`、`/inventory/movements` → **400**「开始日期不能晚于结束日期」；
- `/ledger/entries`、`/cash-flows`、`/expenses`、`/ledger/receipts` → **200 + 0 条**。

后果不是"少看到几条"，而是用户照着一个**错的结论**做决定：日期选择器先点晚、再点早
是日常操作，界面上会显示「这段时间没有流水、流入 0」—— 而账本页与资金流水页
正是"钱的三方对账"要盯的两页，用户会以为这段时间真的没有账。

所以这一族现在也只有一处实现：**格式错 400、顺序反了 400**，与 `deps` 那一套同口径。
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException


def date_window(date_from: str | None, date_to: str | None) -> tuple[date | None, date | None]:
    """两个 ISO 日期串 → `(start, end)`（`None` = 该端不限）。

    - 只取前 10 位（容忍客户端带时间戳）；
    - 格式不对 → 400 中文；
    - `date_from > date_to` → 400 中文（⛔ 不许安静地返回空集）。
    """
    start = end = None
    if date_from:
        try:
            start = date.fromisoformat(str(date_from)[:10])
        except ValueError:
            raise HTTPException(status_code=400, detail="开始日期格式无效") from None
    if date_to:
        try:
            end = date.fromisoformat(str(date_to)[:10])
        except ValueError:
            raise HTTPException(status_code=400, detail="结束日期格式无效") from None
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
    return start, end


def ensure_date_order(date_from: date | None, date_to: date | None) -> None:
    """两个**已经是 `date` 对象**的查询参数 → 顺序反了就 400（与 [date_window] 同口径、同一句文案）。

    ## 为什么还要有第二个函数（2026-09-24 第 22 轮 F8 实测）
    上面 [date_window] 管的是"端点在函数体里自己 `fromisoformat`"那一族（账本/资金流水/开销）。
    聚合端点的参数是 **FastAPI 直接解析成 `date` 的**（`date_from: date = Query(...)`），
    格式错由它回 422 —— 但**顺序没人管**，于是同一个"日期反了"的输入：

    - `/orders`、`/inventory/movements`、`/reports/turnover`、`/ledger/accounts`、
      `/cash-flows/summary`、`/expenses` → **400**；
    - `/stats/*`（6 个）、`/reports/arrears-summary`、`/freight-settlement`、
      `/supplier-payments` → **200 + 空集**，`/stats/driver-performance` 还把反序区间
      当合法区间回显（`period_label:"2026-09-30 ~ 2026-09-01"`）。

    后果不是"少看几条"：报表中心把同一段日期发给这些端点，于是**营业纵览报红字、
    司机绩效/客户经营/异常与审计显示"没有数据"** —— 同一页上四个格子对同一段时间给出
    两种结论。日期选择器"先点晚、再点早"是日常操作，所以这条必须显式拦。

    调用点由 `backend/tests/test_date_window_business_day.py` 从**路由表自己算**
    （带 `date_from`+`date_to` 的端点逐个打反序），所以新加聚合端点漏了会被测试抓住。
    """
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
