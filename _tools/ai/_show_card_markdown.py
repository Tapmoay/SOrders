"""列出「会渲染到确认卡上」的文案里所有 Markdown 星号（修之前先看全）。

用法：python _tools/ai/_show_card_markdown.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402
from _check_ai_guardrails import string_literals  # noqa: E402

AI = repo_root() / "android/app/src/main/java/com/tapmoay/sorders/ai"

# 两种造卡形状都要覆盖：
#   · 处理器的 `card(...)` 包装  `card(summary = …, details = buildList { … }, payload = …)`
#   · 直接调 store（CRUD / 撤回 / 先攒变量那种）
#     `store.card(actionId, summary = …, details = buildList { … }, payload = …)`
#   ⚠️ v3.32 前后这里叫 `store.offer(… detailLines = …)`；2026-09-21 造卡收成一处后参数名统一
#      成 `details`。两种参数名都还认（正则里 `(?:details|detailLines)`），免得漏扫。
SUMMARY = r"\n\s+summary = ([\s\S]{0,300}?),\n\s+(?:details|detailLines) = "
DETAILS = r"\n\s+(?:details|detailLines) = buildList \{(.*?)\n\s+\},\n\s+payload = "


def main() -> int:
    total = 0
    for f in sorted(AI.glob("AiWrite*.kt")):
        src = f.read_text(encoding="utf-8")
        blocks = re.findall(SUMMARY, src, re.S) + re.findall(DETAILS, src, re.S)
        bad = [s for b in blocks for s in string_literals(b) if "**" in s or "__" in s]
        if bad:
            print(f"{f.name}:")
            for b in bad:
                print("   ", b)
            total += len(bad)
    print(f"\n共 {total} 处" if total else "\n卡片文案里没有 Markdown 记号")
    return 0


if __name__ == "__main__":
    sys.exit(main())
