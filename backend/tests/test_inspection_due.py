"""FEAT-0022 下次年检日期的算法：**只有这一处**，所以边界要在这里钉死。

## 为什么单独一个文件

"加一年"看起来是最不容易写错的一行 —— 恰恰因为如此，它错起来最安静：
算早一天会让人早去一趟检测站；算晚一天会让车**过期上路**（罚款、扣车）。
而 2 月 29 日上牌的车每四年才撞上这个分叉一次，真出问题时没人会想到是这里。

消息那一层（谁收、几点发、文案怎么写）在 `tests/test_message_producers.py`；
这里只钉**日期本身**：周年、2/29、以谁为准、两格都空。
"""

from __future__ import annotations

from datetime import date, timedelta

from app.services import inspection_due


# ---------------------------------------------------------------- 周年

def test_next_due_is_the_same_month_and_day_one_year_later() -> None:
    """**按周年算**（同月同日），⛔ 不是"加 365 天"——后者每四年就会漂一天。"""
    assert inspection_due.next_due_date(date(2024, 3, 15), None) == date(2025, 3, 15)
    assert inspection_due.next_due_date(date(2025, 12, 31), None) == date(2026, 12, 31)
    assert inspection_due.next_due_date(date(2024, 1, 1), None) == date(2025, 1, 1)


def test_period_is_one_year_and_defined_in_one_place() -> None:
    """周期是具名常量：将来改成"两年一检"只动那一行。"""
    assert inspection_due.INSPECTION_PERIOD_YEARS == 1
    base = date(2026, 5, 20)
    due = inspection_due.next_due_date(base, None)
    assert due == base.replace(year=base.year + inspection_due.INSPECTION_PERIOD_YEARS)


# ---------------------------------------------------------------- 2/29

def test_feb_29_clamps_to_feb_28_in_a_common_year() -> None:
    """2/29 上牌的车，平年里"满一年"只能是 2/28（⛔ 不是 3/1）。

    夹到 2/28 是**刻意**的：夹到 3/1 会让提醒比"满一年"晚一天，
    而这件事的两侧不对称 —— 早一天只是多提醒一次，晚一天是让车主可能过期上路。
    """
    assert inspection_due.next_due_date(date(2024, 2, 29), None) == date(2025, 2, 28)
    # 上一次就是在这个"被夹过"的日子检的：再下一年还是 2/28（不会又跳回 2/29）
    assert inspection_due.next_due_date(None, date(2025, 2, 28)) == date(2026, 2, 28)
    # 下一个闰年里仍然是 2/28 —— 起点是"上一次年检日期"，不是"原来的 2/29"
    assert inspection_due.next_due_date(None, date(2027, 2, 28)) == date(2028, 2, 28)


def test_feb_28_and_mar_1_are_not_shifted() -> None:
    """只有 2/29 这一种越界；邻近日不许被顺手改掉。"""
    assert inspection_due.next_due_date(date(2024, 2, 28), None) == date(2025, 2, 28)
    assert inspection_due.next_due_date(date(2024, 3, 1), None) == date(2025, 3, 1)
    assert inspection_due.next_due_date(date(2024, 2, 29), None) != date(2025, 3, 1)


# ---------------------------------------------------------------- 以谁为准

def test_last_inspection_date_wins_and_registration_is_only_a_fallback() -> None:
    """两格都录了 ⇒ **以上次年检日期为准**（它是更近的一次事实）。

    上牌日期只在"从来没有年检记录"时兜底（"上牌满一年"是第一次年检的常见口径）。
    这一条错了的表现是"提醒的到期日差好几年"，而界面上完全看不出来。
    """
    assert inspection_due.next_due_date(date(2019, 5, 1), None) == date(2020, 5, 1)
    assert inspection_due.next_due_date(None, date(2025, 5, 1)) == date(2026, 5, 1)
    assert inspection_due.next_due_date(date(2019, 5, 1), date(2025, 5, 1)) == date(2026, 5, 1)


def test_no_base_date_means_no_reminder_at_all() -> None:
    """⛔ 两格都空 ⇒ `None`：那是"没录"，不是"没上牌"。

    不许拿今天或建档日期凑一个到期日 —— 那不是提醒，是系统自己编的事实。
    """
    assert inspection_due.next_due_date(None, None) is None
    assert inspection_due.inspection_kind(None, None, day=date(2026, 10, 11)) is None


# ---------------------------------------------------------------- 分档

def test_kind_buckets_with_two_exact_boundaries() -> None:
    """两条边界：**还剩 30 天**（含）进临期、**到期日当天**仍算临期、**过 1 天**才算逾期。

    ⚠️ 到期日当天车还能合法上路，说"已逾期"是错的话 —— 这条边界与 `payable_kind` 同形。
    """
    day = date(2026, 10, 11)

    def base(days_to_due: int) -> date:
        """构造一个起点，使"下次年检日期"正好是 `day + days_to_due`。"""
        d = day + timedelta(days=days_to_due)
        return d.replace(year=d.year - 1)

    assert inspection_due.INSPECTION_DUE_SOON_DAYS == 30
    assert inspection_due.inspection_kind(base(31), None, day=day) is None
    assert inspection_due.inspection_kind(base(30), None, day=day) == "vehicle.inspection_due"
    assert inspection_due.inspection_kind(base(1), None, day=day) == "vehicle.inspection_due"
    assert inspection_due.inspection_kind(base(0), None, day=day) == "vehicle.inspection_due"
    assert inspection_due.inspection_kind(base(-1), None, day=day) == "vehicle.inspection_overdue"
    assert inspection_due.inspection_kind(base(-400), None, day=day) == "vehicle.inspection_overdue"


def test_kind_follows_the_same_base_rule_as_the_date() -> None:
    """分档只回答"算哪一档"，起点规则与 `next_due_date` 完全同源（⛔ 不另写一遍）。"""
    day = date(2026, 10, 11)
    # 上牌很久以前、上次年检刚刚过：按"上次年检"算 = 已逾期；按"上牌"算会是别的结果
    assert inspection_due.inspection_kind(date(2015, 1, 1), date(2025, 10, 8), day=day) == (
        "vehicle.inspection_overdue"
    )
    assert inspection_due.next_due_date(date(2015, 1, 1), date(2025, 10, 8)) == date(2026, 10, 8)
