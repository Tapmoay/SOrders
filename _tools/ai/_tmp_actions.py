"""临时：列出 AiWrite.kt 的全部动作 id 与其来源（crud / 手写）、风险档、域。"""
import re
import sys
from pathlib import Path

AI = Path(__file__).resolve().parents[2] / "android/app/src/main/java/com/tapmoay/sorders/ai"
src = (AI / "AiWrite.kt").read_text(encoding="utf-8")

# 1. 常量表：NAME = "x.y"
consts = dict(re.findall(r'const val (\w+) = "([^"]+)"', src))
print(f"动作常量 {len(consts)} 个")
for k, v in consts.items():
    print(f"  {k:38s} -> {v}")
