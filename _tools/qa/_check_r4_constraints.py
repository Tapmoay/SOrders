#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_r4_constraints.py —— R4 指南**归档件**的结构判据（P5 补的：它此前是个不存在的脚本）。

### 为什么会有它（这是一条**被 Final Review 抓出来的**缺口）

`docs/R4_PROGRESS.md` 里有一条 ✅ 写着：

    指南原文归档为 docs/ARCHITECTURE_RECTIFICATION_R4.md（带来源 SHA256），
    北极星那一句同页可查 —— 复现：python _tools/qa/_check_r4_constraints.py

⭐ 而**那个脚本根本不存在** —— 54 条复现命令里唯一指向空气的一条。
（本仓库的 `_check_report_facts.py` 只逐条跑 `docs/R3_PROGRESS.md` 的 ✅，R4 那一侧没人核。）

### ⛔ 它**证不了**什么（这一条比它证了什么更重要）

归档件里声明原件是 **26669 字节 / SHA256 E45A6CAF…**。
⚠️ 本轮实测：把归档正文切出来，按任何常规归一（原样 / 去尾空白 / LF→CRLF…）
**都得不到那个字节数或那个 SHA**（最接近的一档差 7 字节）。
⇒ 因为**原件 `ppkk.md` 不在仓库里**，那个值**从仓库重算不出来**。
所以本判据只核**归档结构**与**声明值的一致性**，
⛔ **不核「正文逐字节等于原件」** —— 那条只能由**持有原件的人**核对。
⛔ 不许把这里的 ✅ 读成「归档正文与原件逐字节相同」。

### R3-BOUNDARY-JUSTIFICATION

R3-BOUNDARY-JUSTIFICATION: 这条**没法用边界消除** —— 归档是一次性人工产物（原件不在仓库里），
没有任何代码不变式能推出「附录里写的那个 SHA 就是原件的 SHA」。
能机器核的只有「结构完整 + 声明值与常量一致 + 北极星可查」，
⛔ 而这条判据**必须同时明说它没核什么** —— 否则那行 ✅ 会被读成比它实际更强的东西
（这正是本轮 Final Review 抓到的问题本身）。

用法：python _tools/qa/_check_r4_constraints.py
"""
from __future__ import annotations

import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "docs" / "ARCHITECTURE_RECTIFICATION_R4.md"

#: 原件声明的两个值（写在附录 A 开头）。⛔ 它们**无法从仓库重算** —— 见模块头。
DECLARED_BYTES = "26669"
DECLARED_SHA = "E45A6CAF01143418BDB5F20D36401382456754C267367424B3FAE91D9DA230E0"
#: 附录的起始标记（那一段是**施工方**加的，⛔ 不是指南原文）。
APPENDIX_MARK = "# 附录 A（⛔ 不是指南原文）"
#: 北极星那一句（指南 §44 建议写在这里的）。
NORTH_STAR = "核心业务负责稳定系统语义"


def main() -> int:
    bad: list[str] = []
    seen = 0

    seen += 1
    if not ARCHIVE.exists():
        print("❌ 归档件不在：" + str(ARCHIVE))
        return 1
    text = ARCHIVE.read_text(encoding="utf-8")
    print("  OK   归档件在 -> docs/ARCHITECTURE_RECTIFICATION_R4.md（"
          + str(len(text.encode("utf-8"))) + " 字节）")

    seen += 1
    pos = text.find(APPENDIX_MARK)
    if pos < 0:
        bad.append("找不到附录标记行（附录必须显式标着⛔不是指南原文）")
        print("  BAD  附录标记行")
    else:
        head_lines = text[:pos].count(chr(10))
        print("  OK   附录标记行在正文之后 -> 正文 " + str(head_lines) + " 行，附录起于其后")
        if head_lines < 100:
            bad.append("正文只有 " + str(head_lines) + " 行 —— 太短，不像归档了整份指南")

    seen += 1
    miss = [k for k, v in (("字节数", DECLARED_BYTES), ("SHA256", DECLARED_SHA))
            if pos >= 0 and v not in text[pos:]]
    if pos < 0 or miss:
        bad.append("附录里没有声明：" + "、".join(miss or ["（附录缺失）"]))
        print("  BAD  附录里的来源声明")
    else:
        print("  OK   附录声明了原件字节数与 SHA256（与常量一致）")

    seen += 1
    if pos >= 0 and NORTH_STAR in text[pos:]:
        print("  OK   北极星那一句在附录里可查")
    else:
        bad.append("附录里查不到北极星那一句")
        print("  BAD  北极星那一句")

    print("")
    if bad:
        print("❌ R4 归档件判据 " + str(seen) + " 组，" + str(len(bad)) + " 条不成立：")
        for b in bad:
            print("   - " + b)
        return 1
    print("✅ " + str(seen) + " 组判据全部通过：归档结构完整、附录标注齐全、来源声明与常量一致、北极星可查。")
    print("   ⛔ 本次**没有**核「正文逐字节等于原件」—— 原件不在仓库里，那个值重算不出来；")
    print("      要核它得拿原件比。⛔ 不许把上面那行 ✅ 读成逐字节相同。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())