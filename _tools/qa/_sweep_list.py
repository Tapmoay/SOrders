"""把声明式 CRUD 动作按域列出来（真机扫尾用：挑哪几条上真机）。

用法：python _tools/qa/_sweep_list.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
FILES = ["AiWriteBasicData.kt", "AiWriteMasterData.kt"]


def main() -> int:
    total = 0
    for name in FILES:
        src = (AI / name).read_text(encoding="utf-8")
        for m in re.finditer(
            r"id = (AiWrites\.\w+),\s*\n\s*title = \"([^\"]+)\",\s*\n\s*risk = (AiWriteRisk\.\w+),\s*\n\s*group = (AiWrites\.\w+)",
            src,
        ):
            total += 1
            print(f"  {m.group(1):<42} {m.group(2):<14} {m.group(3).replace('AiWriteRisk.',''):<7} {m.group(4)}")
    print(f"\n声明式 CRUD 动作：{total} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
