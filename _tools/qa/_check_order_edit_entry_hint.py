#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_order_edit_entry_hint.py —— 「货主要改单就打电话给派单员」这条提示（CHG-0136）。

用户 2026-10-22 逐字：「不让货主和批发商自己去改订单信息了，但是在订单详情下面加一句提示 ——
**要改订单信息请打电话给派单员**；因为我们派单员要知道他到底要改什么信息，
不然他在没收到信息的情况下胡乱改，司机就很难判断到底送什么、送多少、送到哪。」

这条判据盯三件事：
1. 那句提示在（逐字），且**只有货主/批发商**看得到（司机与派单员自己不需要这句）；
2. 它走 `Hint`（解释句，跟提示总开关）而不是 `Text`，且**不是按钮**（点了也拨不出去）；
3. ⛔ **货主端没有任何编辑入口** —— `canEditInfo` / `canEditLines` 仍然只给派单员。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
DETAIL = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt"
MIN_RULES = 6

bad: list[str] = []
checked = 0


def _ok(m: str) -> None:
    global checked
    checked += 1
    print("  OK   " + m)


def _bad(m: str) -> None:
    global checked
    checked += 1
    print("  BAD  " + m)
    bad.append(m)


def _need(name: str, cond: bool, why: str = "") -> None:
    if cond:
        _ok(name)
    else:
        _bad(name + ("　—— " + why if why else ""))


def main() -> int:
    src = DETAIL.read_text(encoding="utf-8", errors="replace") if DETAIL.is_file() else ""

    _need("详情页存在", bool(src))
    _need("那句提示逐字在：「要改订单信息，请打电话给派单员。」", "要改订单信息，请打电话给派单员。" in src)
    _need(
        "它只在货主/批发商那一侧画（`role == Role.SHIPPER`）",
        re.search(r'if \(role == Role\.SHIPPER\) \{[\s\S]{0,600}?要改订单信息', src) is not None,
        "司机与派单员自己不需要这句 —— 他们本来就能改",
    )
    _need(
        "它是一张**独立小卡片**（SectionCard），不是底部一行小字",
        re.search(r"SectionCard \{[\s\S]{0,400}?要改订单信息", src) is not None,
        "用户 2026-10-22：「在这两个卡片之间插一个信息……插一个小卡片吧，那个卡片就是信息」",
    )
    _need(
        "位置在**单号卡之后、收货信息卡之前**（用户指着那块空白说的）",
        src.find("要改订单信息") > src.find("#\" + order.orderNo")
        and src.find("要改订单信息") < src.find("\"收货信息\""),
        "放到底部（第一版）用户否掉了：那是页面最后，读完整个订单才看到",
    )
    _need(
        "它走 Text（操作指引必须一直看得见），⛔ 不是 Hint",
        re.search(r'Text\(\s*"要改订单信息', src) is not None,
        "提示总开关关掉时，货主在界面上就找不到任何\"怎么改单\"的答案",
    )
    _need(
        "⛔ 它不是按钮（没有 onClick / Button）",
        re.search(r'Button\([\s\S]{0,120}?要改订单信息', src) is None,
        "点了也拨不出去：派单员是谁因单而异，这里没有\"哪个人\"的答案",
    )
    _need(
        "⛔ 货主端仍然没有编辑入口（canEditInfo / canEditLines 只给派单员）",
        "val canEditInfo = role == Role.DISPATCHER" in src
        and "val canEditLines = role == Role.DISPATCHER" in src,
        "这一句是\"改单的唯一入口说明\"，不是\"顺手把编辑权也放开\"",
    )

    print()
    if bad:
        print("❌ 失败 %d 项（共 %d）" % (len(bad), checked))
        for b in bad:
            print("   - " + b)
        return 1
    if checked < MIN_RULES:
        print("❌ 只跑到 %d 项（下限 %d）" % (checked, MIN_RULES))
        return 1
    print("✅ 全部通过：%d 项" % checked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
