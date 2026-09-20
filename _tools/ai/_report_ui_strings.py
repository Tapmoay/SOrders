import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402
"""探针：安卓 UI 里的中文文案能不能自动抽取出来，用于生成"用户话术→入口"映射。

⚠️ **这是报告，不是检查**（2026-09-21 从 `_check_*` 改名）：它统计素材量、永远退出 0。
⛔ 不要把它改回 `_check_*`：除非给它加一条真会红的判据。

背景（方案 v3.1 §6.4）：后端没有中文功能名（docstring 覆盖 24%、summary= 0 个、
tags 全是英文 slug），中文只在 Android UI 里。本脚本量化"到底能抽多少"。只读。
"""
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

APP = repo_root() / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"

CJK = re.compile(r"[\u4e00-\u9fff]")
# 各类"用户可见文案"的常见写法
PATTERNS = {
    "label =": re.compile(r'label\s*=\s*"([^"]*[\u4e00-\u9fff][^"]*)"'),
    "Text(字面量)": re.compile(r'Text\(\s*"([^"]*[\u4e00-\u9fff][^"]*)"'),
    "title =": re.compile(r'title\s*=\s*"([^"]*[\u4e00-\u9fff][^"]*)"'),
    "placeholder =": re.compile(r'placeholder\s*=\s*"([^"]*[\u4e00-\u9fff][^"]*)"'),
    "ModuleEntry": re.compile(r'ModuleEntry\(\s*"([^"]*[\u4e00-\u9fff][^"]*)"'),
    "任意中文字面量": re.compile(r'"([^"\n]*[\u4e00-\u9fff][^"\n]*)"'),
}


def main() -> int:
    kt = sorted(APP.rglob("*.kt"))
    print(f"扫描 .kt 文件：{len(kt)} 个（{APP.name} 下）\n")

    totals: Counter[str] = Counter()
    all_cn: set[str] = set()
    per_file: list[tuple[str, int]] = []

    for f in kt:
        text = f.read_text(encoding="utf-8", errors="ignore")
        if not CJK.search(text):
            continue
        cnt = 0
        for name, pat in PATTERNS.items():
            hits = pat.findall(text)
            totals[name] += len(hits)
            if name == "任意中文字面量":
                all_cn.update(h for h in hits if 1 < len(h) <= 24)
                cnt = len(hits)
        per_file.append((f.relative_to(APP).as_posix(), cnt))

    print("=== 各类文案命中数 ===")
    for name in PATTERNS:
        print(f"  {name:<16} {totals[name]}")

    print(f"\n=== 去重后的中文短文案（1~24 字）：{len(all_cn)} 条 ===")
    sample = sorted(all_cn, key=lambda s: (len(s), s))[:25]
    for s in sample:
        print(f"   {s}")

    print("\n=== 中文文案最多的 12 个文件 ===")
    for name, n in sorted(per_file, key=lambda x: -x[1])[:12]:
        print(f"  {n:>5}  {name}")

    print("\n=== 结论 ===")
    print(f"  可用中文文案候选：约 {len(all_cn)} 条（去重后，含短标签）")
    print("  → 数量足够覆盖 14 个入口 + 各页标题/按钮，说明这一列**可以半自动生成**；")
    print("  → 但『用户会怎么口语化描述』必须人工/实测补，脚本给不了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
