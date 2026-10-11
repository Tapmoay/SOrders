"""下次车辆年检日期与**提前量分档**：只有这一处算法（FEAT-0022 → CHG-0115，用户口径 2026-10-11）。

## 这一单治的病（CHG-0115）

用户 2026-10-11（逐字）：

> 「这个车辆年检是**不能逾期**的。意思就是说，我们不能等已经到了年检期、或者说年检期过了 ——
>   这是不可能的，因为**一旦过了的话那车子是不能上路的**。我们按照我们的交规来提醒，
>   我们的交规是大概在**一个月，还是三个月前**就会有提醒的。」

也就是说：**等到期才提醒就已经晚了**。年检要预约、要上线检测，不是当天去就能办完的事。
CHG-0115 之前只有"临期 / 逾期"两档，而那个"临期"是 30 天 —— 等于**只剩一个月**才第一次
告诉用户，正是用户说的"不能等已经到了年检期"。现在改成**提前 3 个月就开口**：

| 距到期天数 `left = (due - day).days` | 返回 | 档位（由 `message_center` 定） |
| --- | --- | --- |
| `left < 0` | `"vehicle.inspection_overdue"` | danger —— **兜底**，设计目标是**不让它发生** |
| `0 <= left <= INSPECTION_URGENT_DAYS`（30） | `"vehicle.inspection_urgent"` | danger（只剩一个月，必须去了） |
| `INSPECTION_URGENT_DAYS < left <= INSPECTION_DUE_SOON_DAYS`（90） | `"vehicle.inspection_due"` | warn（还有三个月，该安排年检了） |
| `left > INSPECTION_DUE_SOON_DAYS` | `None` | 不发 |

⚠️ **三档互斥、一天只会命中一档** —— 这是"同一台车、同一个到期日，三段各只发一条"的
**结构性保证**：本函数返回的是**单个**类型名，扫描按它发一条；不是"先发 90 天那条、
再发 30 天那条"（那样同一天会刷两条）。幂等键再带上类型名（`message_producers.notify_inspection`），
所以进入下一档那天发的那条与上一档那条**各是各的记录**，谁也不顶掉谁。

⚠️ **到期日当天算"紧急"、不算"逾期"**：那一天车还能合法上路，说"已过期"是错的话
（与 `payable_kind` 的第 0 天 = 临期同形）；但它是"今天就得去"的那一档。

⛔ 风险档**不在这里定**（`message_center.SEVERITY_BY_TYPE` 说了算），这里只回答"算哪一档"。

## 两个日期（都是**已发生过的事实**，⛔ 不落库）

用户 2026-10-11（FEAT-0022，逐字）：

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

## 谁在用

`services/message_producers.py` 的 `notify_inspection` / `scan_inspection_due`（每日兜底扫描）。
App 端同一条规则的另一份实现：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleInspection.kt`
（两边的提前量必须一样：90 天 / 30 天）。
单测：`backend/tests/test_inspection_due.py`。
"""

from __future__ import annotations

from datetime import date

#: 到期前多少天**进入紧急档**（danger，只剩一个月）。
#: 用户 2026-10-11：「按我们的交规……大概在**一个月**，还是三个月前就会有提醒的」
#: —— 一个月这一档是"必须去了"，不是第一次开口。
INSPECTION_URGENT_DAYS = 30

#: 到期前多少天**开始提醒**（warn 档，提前 3 个月 = 90 天）。
#: 用户 2026-10-11：「这个车辆年检是**不能逾期**的……**一旦过了的话那车子是不能上路的**」
#: —— 所以第一次提醒必须落在**到期之前足够早**的地方：90 天够预约、够安排上线检测。
#: ⛔ 两个天数都只在这里定义一处（App 侧 `VehicleInspection.kt` 是另一份、必须同值）。
INSPECTION_DUE_SOON_DAYS = 90

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
    """这台车**今天**算哪一档（唯一的**分档**判据）；还早 = `None`。

    三档互斥、**一天只命中一档**（见模块 docstring 的那张表）—— 所以"同一天不会同时发两条"。

    ⛔ 返回值是**消息类型名**，不是档位名：`vehicle.inspection_due`=warn、
    `vehicle.inspection_urgent` / `vehicle.inspection_overdue`=danger
    由 `message_center.SEVERITY_BY_TYPE` 说了算。
    ⛔ 预判今天之前不许出现（`today` / `business_today`）：起点只能是那两个**已发生**的日期。
    """
    due = next_due_date(registration_date, last_inspection_date)
    if due is None:
        return None
    left = (due - day).days
    if left < 0:
        return "vehicle.inspection_overdue"
    if left <= INSPECTION_URGENT_DAYS:
        return "vehicle.inspection_urgent"
    if left <= INSPECTION_DUE_SOON_DAYS:
        return "vehicle.inspection_due"
    return None
