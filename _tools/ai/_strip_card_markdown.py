"""把「会渲染到确认卡上」的文案里的 Markdown 星号去掉。

### 为什么需要它
确认卡用的是普通 `Text()`，**不解析 Markdown**。写 `**下架**` 屏幕上就是一堆星号。

同一个文件里同时存在两类文案：
- `headline` / `details` → **渲染到卡片上**，不能有 Markdown；
- `blurb` / `hint` / `paramHint` → **给模型看的**，那里 `**` 是有意义的
  （模型读 Markdown 没问题，加粗还能提高它照做的概率）。

所以只能按 lambda 切块处理，不能整个文件一刀切。
红线 §2e 会守着同一件事；这个脚本是用来**一次性修完**的。

用法：python _tools/ai/_strip_card_markdown.py
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
FILES = ("AiWriteMasterData.kt", "AiWriteBasicData.kt", "AiWritePricing.kt")

# headline = { ... },   details = { ... },   两块
BLOCK = re.compile(r"(\n\s+(?:headline|details) = \{)(.*?)(\n\s+\},)", re.S)
# 字符串字面量（粗略：\" 之间不跨行）
LIT = re.compile(r'"(?:[^"\\]|\\.)*"')


def clean(text: str) -> str:
    return LIT.sub(lambda m: m.group(0).replace("**", "").replace("__", ""), text)


def main() -> int:
    total = 0
    for name in FILES:
        p = AI / name
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8")
        hits = 0

        def repl(m: re.Match) -> str:
            nonlocal hits
            body = m.group(2)
            new = clean(body)
            if new != body:
                hits += len(re.findall(r"\*\*", body))
            return m.group(1) + new + m.group(3)

        src = BLOCK.sub(repl, src)
        if hits:
            p.write_text(src, encoding="utf-8")
        print(f"  {name}: 清掉 {hits} 处星号")
        total += hits
    print(f"合计 {total} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
