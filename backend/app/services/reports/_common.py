"""报表只读查询的**共用助手**（窗口换算 / 标签 / 金额舍入）。


⛔ **只读**：本包下的模块只允许 SELECT / JOIN / GROUP BY —— 判据 _tools/qa/_check_report_boundary.py
在 AST 层面禁止落库写法与写服务依赖，而且它是**算出来的**（services/reports/** 由 glob 自动收）。
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fastapi import HTTPException
from app.core.date_window import ensure_date_order



def _window(mode: str, anchor: date) -> tuple[date, date]:
    """[mode] 对应的时间窗口，**两端都是闭区间里的最后一天**。

    ⚠️ 月窗口的上界以前是"下月 1 日"（`day=1 + 32 天 → day=1`），而调用方用的是
    **闭区间** `ds <= end`（见 `build_turnover`），于是**下个月 1 号的单会被算进本月**。
    报表上的表现很隐蔽：本月最后一天的日报是对的，月报却多了一天的数据。
    现在统一返回"本月最后一天"，与周/日两种模式一致。
    """
    d = anchor
    if mode == "week":
        start = d - timedelta(days=d.weekday())
        return start, start + timedelta(days=6)
    if mode == "month":
        first = d.replace(day=1)
        return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return d, d


def _label(d: date, mode: str) -> str:
    if mode == "week":
        start = d - timedelta(days=d.weekday())
        return f"{start.month}-{start.day}~{start + timedelta(days=6):%m-%d}"
    if mode == "month":
        return f"{d.year}-{d.month:02d}月"
    return f"{d.month}-{d.day}"


def _span_label(start: date, end: date) -> str:
    """给了**明确区间**时那个标签（`9-1~9-20` / 整天 `9-18` / 整月 `2026-09月`）。

    与 `_label(d, mode)` 同一套写法：整月仍然写成 `2026-09月`（导出的表头读它），
    其余一律写成一段区间 —— 用户看到"这两个数"时必须能从标题上认出是哪一段。
    """
    if start == end:
        return f"{start.month}-{start.day}"
    if start.day == 1 and (start + timedelta(days=32)).replace(day=1) - timedelta(days=1) == end:
        return f"{start.year}-{start.month:02d}月"
    return f"{start.month}-{start.day}~{end.month}-{end.day}"


def _span(
    mode: str,
    anchor: date,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date]:
    """这一次报表要看的窗口 —— **后端唯一的入口**（接口与导出都走它）。

    给了 `date_from` + `date_to` 就用它（App 的档位药丸走这条：今天/昨天/近 7 天/本月/上月/自定义
    都是**一段区间**，六个页签共用同一段）；没给就还是老的 `mode` + `anchor`
    （`day`/`week`/`month`，既有调用方与既有测试一行都不用改）。

    ⚠️ **只给一头 → 400**，不许"猜另一头"：半截窗口要么查全量要么查出空列表，
       两种都不是用户想要的（App 侧那条规矩同理：`DateRangeDialog` 只选一头时"应用"什么都不做）。
    """
    if (date_from is None) != (date_to is None):
        raise HTTPException(status_code=400, detail="date_from 与 date_to 必须同时给")
    if date_from is not None and date_to is not None:
        # ⚠️ 顺序这条判据**不在本文件里再写一遍**（2026-09-24 第 22 轮）：原来这里是
        #    「结束日期不能早于开始日期」，而 `deps`/`date_window`/账本那几处是
        #    「开始日期不能晚于结束日期」—— 同一件事两句话，用户在不同页面收到的提示不一样。
        #    现在全项目只有 `core/date_window.py::ensure_date_order` 一处。
        ensure_date_order(date_from, date_to)
        return date_from, date_to
    return _window(mode, anchor)


def _range_dates(start: date, end: date) -> list[date]:
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out
def _money(v) -> float:
    """导出里的金额写成**数字**（不是文本），保留两位小数。

    2026-09-19 审计 R13-R7：原来一律 `str(decimal)` 写进单元格，openpyxl 存成**文本**
    （实测 `B2='97131.7500' type=s`）——用户在 Excel 里 `SUM` 选一列金额，
    得到的是 0（或只把"单数/件数"这种真数字加起来），账要自己拿计算器重算。
    金额是给人算的，必须能被 Excel 当数用。

    ⚠️ 进位方式必须显式写 `ROUND_HALF_UP`（2026-09-19 审计 F7）：`.quantize()` 的默认是
    **ROUND_HALF_EVEN**（银行家舍入），而全项目的 `driver_pay.money()` 是 ROUND_HALF_UP ——
    金额正好落在半分位上时（如 0.125）两处差 1 分，而"导出与页面差 1 分"是对账时最难查的那种。
    同族的货损两处已在第十五轮改过，这里是最后一处。
    """
    if v is None or v == "":
        return ""
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
