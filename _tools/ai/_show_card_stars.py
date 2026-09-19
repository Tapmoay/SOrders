"""列出 AiWrite*.kt 里所有**字符串字面量里**的 `**`，并标出它前后 120 字符的上下文。

用途：给"卡片文案不许有 Markdown 星号"这条红线换一个**fail-closed** 的判据——
不再按"details 长什么样"去找卡片（形状一改就漏），而是全文件扫，
再看每一处的上下文是不是"给模型看的"（异常话术/参数提示），不是就算卡片文案。

用法：python _tools/ai/_show_card_stars.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

AI = repo_root() / "android/app/src/main/java/com/tapmoay/sorders/ai"
LIT = re.compile(r'"((?:[^"\\]|\\.)*)"', re.S)

total = 0
for p in sorted(AI.glob("AiWrite*.kt")):
    src = p.read_text(encoding="utf-8")
    for m in LIT.finditer(src):
        if "**" not in m.group(1):
            continue
        total += 1
        ctx = src[max(0, m.start() - 120): m.start()].replace("\n", " ")
        print(f"{p.name}: …{ctx[-110:]}  ==>  {m.group(1)[:80]!r}")
print(f"\n共 {total} 处")
