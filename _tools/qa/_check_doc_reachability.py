#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_doc_reachability.py —— 把「**文档可达性**」接进 `_check_all.py` 的必跑清单。

### 为什么要有它（一个已经发生过的真缺陷）

`backend/scripts/check_reachability.py` 早就写好了（它做两件事：
① 校验 markdown 链接；② 从 `AGENTS.md` 做**图遍历**，列出到达不了的"孤儿文档"），
而且**质量很高** —— 但 2026-09-27 实测发现：

  · 它**从来没被跑过**（它不在 `_tools/*/_check_*.py` 的自动清单里，因为它在 `backend/scripts/`）；
  · 跑一次的结果是 **39 份孤儿文档** —— R3 / R4 的**全部证据页与报告**从入口出发都到不了。

后果不是"没人读"，而是 **"对新会话等于不存在"**：写的人做完就走了，
下一个会话从 `AGENTS.md` 冷启动，磁盘上那 39 份东西对它是一片空白。
本项目对这件事有明确的先例（一份 94 KB / 7 份文档的项目地图沉睡 5 个月，就因为没人改入口文件）。

所以这条判据只做一件事：**让那份检查每天都在跑**，并且**不许它静默退化**
（文档数降到下限以下就先喊 —— "0 份文档 → 0 个孤儿 → 通过"是本项目栽过的形状）。

### ⛔ 它证不了什么

· 它证不了"链接通 = 内容对"：可达性只保证**找得到**，不保证**写得对**。
· 它证不了"agent 真的会去读"：那是行为验证，机器做不到（规范 §0.2 已如实写明这一点）。

### R3-BOUNDARY-JUSTIFICATION

R3-BOUNDARY-JUSTIFICATION: 这条**没法用边界消除** —— 它是"**让另一条已经存在的检查真的被跑**"，
不是再加一层判断。判别非法链接与孤儿的逻辑**只有一份**（在 `check_reachability.py` 里），
本脚本不复制它、只调用它并设下限。⛔ 把 `check_reachability.py` 搬进 `_tools/` 不算边界解法：
搬过去会打断 `docs/PROJECT_MAP` 里已有的引用，而且"脚本放哪"与"它会不会被跑"本来就没有关系。

用法：python _tools/qa/_check_doc_reachability.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "backend" / "scripts" / "check_reachability.py"

#: 兜底下限：低于它就说明"扫描坏了"或"文档被大量删除"，必须先喊，⛔ 不许安静地报绿。
MIN_DOCS = 60


def main() -> int:
    if not CHECKER.is_file():
        print("❌ 找不到 " + str(CHECKER.relative_to(ROOT)) + " —— 可达性检查不存在，拒绝出结论")
        return 1

    r = subprocess.run(
        [sys.executable, str(CHECKER)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    out = (r.stdout or "") + (r.stderr or "")
    print(out.rstrip())

    bad: list[str] = []
    if r.returncode != 0:
        bad.append("可达性检查非零退出（有断链或孤儿文档）")

    m = re.search(r"可达文档\s*[:：]\s*(\d+)\s*/\s*(\d+)", out)
    if not m:
        bad.append("读不出「可达文档 N / M」这一行（输出格式变了？不许当成通过）")
    else:
        reach, total = int(m.group(1)), int(m.group(2))
        if total < MIN_DOCS:
            bad.append("只扫到 " + str(total) + " 份文档，低于下限 " + str(MIN_DOCS) + "（扫描坏了）")
        if reach != total:
            bad.append("可达 " + str(reach) + " / 共 " + str(total) + " 份 —— 有孤儿文档")

    if "入口文件" not in out:
        bad.append("输出里没有「入口文件」那一行 —— 它可能没认到 AGENTS.md")

    print("")
    if bad:
        print("❌ 文档可达性判据不成立：")
        for b in bad:
            print("   - " + b)
        print("")
        print("   修法：把到不了的那份文档链进 docs/PROJECT_MAP/INDEX.md 的「全量文档目录」——")
        print("        ⛔ 不要因为它「过时/不该读」就放着不管：找不到与知道它不该读是两回事。")
        return 1
    print("✅ 文档可达性：链接全部有效、从入口可达全部文档、孤儿 0 份。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
