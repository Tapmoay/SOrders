"""下次车辆年检日期：**只有这一处**算法（FEAT-0022，用户口径 2026-10-11）。

## 这一单治的病

用户 2026-10-11：
> 「关于这个车辆年检提醒啊，到我给那个车子建档案的时候会填一下就是这车的**上牌日期**。
>   或者说是**上一个年检日期**啊方便我们去做一个提醒」

注意他**没有**要一个「下次年检日期」字段 —— 他只愿意录**已经发生过的事实**（这车哪天上的牌、
上一次什么时候检的），"下次该检了"是系统**算**出来的。所以：

* 输入是 `vehicles.registration_date` / `vehicles.last_inspection_date` 两个**已发生**的日期；
* 输出是派生量，**⛔ 一个字节都不落库**（落库就意味着"改了上次年检日期之后，算出来的旧值还在库里"，
  与 `services/vehicle_depreciation.py` 的折旧额同一条纪律）；
* 因此改口径（比如"两年一检"）只改这一个文件，不需要迁移、不需要回填任何一行。

## 三条判定（⛔ 判据逐条钉着）

1. **两格都空 ⇒ `None`**：这台车没有可用的起点，**不产生任何提醒**。
   ⛔ 不许拿"建档日期"或"今天"当上牌日期去凑一个出来 —— 那不是提醒，是系统自己编的事实。
2. **以「上次年检日期」为准，没有它才回落到「上牌日期」**：
   前者是更近的一次事实（这次检完满一年要再检），后者只在从来没有年检记录时兜底
   （"上牌满一年"是第一次年检的常见口径）。两格都录了时，⛔ 上牌日期**不参与**计算。
3. **按周年算**（`+ 1 年` 同月同日），2/29 落在平年时**夹到 2/28**：
   2 月 29 日上牌的车，在平年里"满一年"的那一天只能是 2 月 28 日（夹到 3/1 会让提醒晚一天，
   而"提前一天"与"晚一天"之间，提前一天是安全的那一侧）。

## 分档（临期 / 逾期）

`inspection_kind()` 是**唯一**的分档判据，形状与 `message_producers.payable_kind` 完全同形：

| 距到期天数 `left = (due - day).days` | 返回 | 档位（由 `message_center` 定） |
| --- | --- | --- |
| `left < 0` | `"vehicle.inspection_overdue"` | danger（**已经出事**：年检过期上路要罚款扣车） |
| `0 <= left <= INSPECTION_DUE_SOON_DAYS` | `"vehicle.inspection_due"` | warn（还没出事，但要处理） |
| `left > INSPECTION_DUE_SOON_DAYS` | `None` | 不发 |

⚠️ **到期日当天算"临期"、不算"逾期"**：那一天车还能合法上路，说"已逾期"是错的话。
⛔ 风险档**不在这里定**（`SEVERITY_BY_TYPE` 说了算），这里只回答"算哪一档"。

## 谁在用

`services/message_producers.py` 的 `notify_inspection` / `scan_inspection_due`（每日兜底扫描）。
单测：`backend/tests/test_inspection_due.py`。
"""

from __future__ import annotations

from datetime import date

#: 到期前多少天开始提醒（warn 档）。30 天 ≈ 一个月，够预约一次年检（年检要上线检测，
#: 不是当天去就能办完的事）。
INSPECTION_DUE_SOON_DAYS = 30

#: 年检周期（年）。写在这里而不是散在调用点：将来改成"两年一检"只动这一行。
INSPECTION_PERIOD_YEARS = 1


def one_period_later(day: date) -> date:
    """一个年检周期之后的日期（按**周年**算，2/29 落在平年时夹到 2/28）。

    ⚠️ 只处理"加一年"这一种：`date.replace(year=+1)` 对 2/29 会抛 `ValueError`
    （平年没有 2 月 29 日），夹到 2/28 是**刻意**的 —— 见模块 docstring 第 3 条。
    """
    try:
        return day.replace(year=day.year + INSPECTION_PERIOD_YEARS)
    except ValueError:
        # 只有 2/29 → 平年 这一种可能（replace 的其它越界这里构造不出来）。
        return day.replace(year=day.year + INSPECTION_PERIOD_YEARS, month=2, day=28)


def next_due_date(
    registration_date: date | None, last_inspection_date: date | None
) -> date | None:
    """下次年检日期；两格都空 ⇒ `None`（这台车不产生任何提醒）。

    ⛔ **这是全项目唯一一处算它的地方**（判据：`def next_due_date(` 在 `backend/app` 下只出现一次）。
    """
    base = last_inspection_date or registration_date
    if base is None:
        return None
    return one_period_later(base)


def inspection_kind(
    registration_date: date | None, last_inspection_date: date | None, *, day: date
) -> str | None:
    """这台车**今天**算哪一档（唯一的分档判据）；还早 = `None`。

    ⛔ 返回值是**消息类型名**，不是档位名：`vehicle.inspection_due`=warn、
    `vehicle.inspection_overdue`=danger 由 `message_center.SEVERITY_BY_TYPE` 说了算。
    """
    due = next_due_date(registration_date, last_inspection_date)
    if due is None:
        return None
    left = (due - day).days
    if left < 0:
        return "vehicle.inspection_overdue"
    if left <= INSPECTION_DUE_SOON_DAYS:
        return "vehicle.inspection_due"
    return None
