"""扫描：找出**跨文件重复代码块**（同 N 行规范化后完全一致）—— 报告工具，不是红线。

为什么要写它：`_tools/qa/_check_dead_code.py` 只能看见"没人用的 import / 私有声明"，
看不见"同一段逻辑在 8 个文件里各抄了一遍"——而后者才是真正的冗余来源（改一处漏七处，
且漏掉的那几处**不报错**）。

⚠️ 它**不进 `_check_all.py`**（没声明 `--check`，也不是 `_check_*`）：重复代码是一条连续谱，
把它做成红线只会得到一条"永远红"的检查（＝没有检查）。它的用法是**做精简前后各跑一次**，
看组数有没有降下来。

判据（宁可漏报，不要噪音）：
- 只扫主源码（android main + backend app），不扫测试与工具；
- 去注释、去空行、去纯括号行；
- 规范化空白后取连续 WINDOW 行做指纹；
- 丢掉"重排后不同行数 < 4"的窗口（`}` `)` `import` 这类样板会刷屏）；
- **同一个重复块的连续窗口要合并**（滑一行换一个指纹，不合并会把 30 行的块报 19 次）；
- 同一指纹出现在 ≥2 个文件才报，按「可省行数 =（处数-1）× 窗口」排序。

用法：python _tools/qa/_scan_dup.py [窗口行数，默认 12] [最少处数，默认 2]
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
SRC_DIRS = [
    ROOT / "android/app/src/main/java/com/tapmoay/sorders",
    ROOT / "backend/app",
]
EXTS = {".kt", ".py"}

TRIVIAL = re.compile(r"^[\s{}()\[\];,]*$")
NOISE = {"else:", "try:", "} else {", "}", ")", "});", "return", "pass", "break", "continue"}


def strip_comments_py(src: str) -> str:
    out = []
    for line in src.split("\n"):
        s = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
        out.append(s)
    return "\n".join(out)


def strip_comments_kt(src: str) -> str:
    """简化版：去掉 // 行注释与 /* */ 块（够用；不去字符串内的 //，宁可漏报）。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(l.split("//", 1)[0] for l in src.split("\n"))


def norm_lines(path: Path) -> list[tuple[int, str]]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    raw = strip_comments_py(raw) if path.suffix == ".py" else strip_comments_kt(raw)
    out: list[tuple[int, str]] = []
    for i, line in enumerate(raw.split("\n"), 1):
        s = line.strip()
        if not s or TRIVIAL.match(s) or s in NOISE:
            continue
        out.append((i, re.sub(r"\s+", " ", s)))
    return out


def main() -> int:
    window = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    min_hits = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    files: list[Path] = []
    for d in SRC_DIRS:
        for p in d.rglob("*"):
            if p.suffix in EXTS and p.is_file():
                if "test" in p.parts:
                    continue
                files.append(p)
    files.sort()

    buckets: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for p in files:
        lines = norm_lines(p)
        rel = p.relative_to(ROOT).as_posix()
        for i in range(len(lines) - window + 1):
            chunk = lines[i : i + window]
            if len({c[1] for c in chunk}) < 4:
                continue
            key = "\n".join(c[1] for c in chunk)
            buckets[key].append((rel, chunk[0][0]))

    groups = [(k, v) for k, v in buckets.items() if len(v) >= min_hits]
    # 合并**同一个重复块的连续窗口**：窗口每滑一行就换一个指纹，所以一个 30 行的重复块
    # 会以 19 个指纹各报一次（第一版就是这样，输出里全是同一段代码）。
    # 判据：这一组里还有几处**落在已报过的行区间之外**；少于 min_hits 就说明
    # 它整段已经被上面某一组覆盖了（按"可省行数"从大到小看，先看到的就是最长的那个窗口）。
    merged: list[tuple[int, str, list[tuple[str, int]]]] = []
    covered: dict[str, list[tuple[int, int]]] = defaultdict(list)

    def inside(rel: str, line: int) -> bool:
        return any(lo <= line <= hi for lo, hi in covered.get(rel, ()))

    for key, hits in sorted(groups, key=lambda kv: -len(kv[1])):
        fresh = [h for h in hits if not inside(h[0], h[1])]
        if len(fresh) < min_hits:
            continue
        for rel, line in hits:
            covered[rel].append((line, line + window - 1))
        merged.append(((len(fresh) - 1) * window, key, fresh))
    merged.sort(key=lambda x: -x[0])

    print(f"扫到 {len(files)} 个文件；窗口 {window} 行；跨文件重复组 {len(merged)} 组\n")
    total_saved = 0
    for saved, key, hits in merged[:40]:
        locs = sorted(hits)
        print(f"--- 可省≈{saved} 行 · 出现在 {len(locs)} 处 ---")
        for rel, ln in locs:
            print(f"    {rel}:{ln}")
        print("    " + key.replace("\n", "\n    ")[:900])
        print()
        total_saved += saved
    print(f"（只列前 40 组）前 40 组理论可省 ≈ {total_saved} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
