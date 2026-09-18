#!/usr/bin/env python3
"""check_refs.py —— 校验文档里引用的文件路径是否真实存在。

为什么需要它：文档写错一个路径，agent 按图索骥扑空后要么放弃文档回到全库搜索
（文档白写），要么相信文档的结论而不再核实（更糟）。而这类错误**人眼查不出**——
大脑做的是"看起来对"的模式匹配，不是逐字符比对。

用法：
    python check_refs.py docs/**/*.md                  # 校验多个文档
    python check_refs.py DOC.md --repo-root /path/repo # 指定仓库根
    python check_refs.py DOC.md --ext .py .kt          # 只校验这些扩展名
    python check_refs.py DOC.md --quiet                # 只输出结论

退出码：0 = 全部有效；1 = 有失效引用（可直接接进 CI / pre-commit）。

豁免规则（三级，用于文档里的"反例"引用）：
    a. 段级：最近的标题含 NEGATION_HEADINGS 里的词（误区/不存在/反例/别去/陷阱…）
    b. 行级：同一行含 NEGATION_WORDS 里的否定词
    c. 显式：行内任意位置写 [ignore-ref]

    ⚠️ 代价：段级豁免会把该段里**真实存在**的引用也一起跳过（宁可漏检，不误报）。
    所以写文档时：**反例表格单独成段、标题带否定词；正例表格不要放在这种标题下。**

路径解析策略：
    1. 完整路径 → 依次在「仓库根」及「自动探测到的子项目根」下尝试
    2. 裸文件名（无 /）→ 走全仓 basename 索引
    子项目根默认自动探测：仓库根下直接包含代码的第一层目录（backend/ src/ app/ …）。
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

# 需要校验的扩展名（可用 --ext 覆盖）
DEFAULT_EXTS = (".py", ".kt", ".java", ".ts", ".tsx", ".js", ".vue", ".go",
                ".rs", ".c", ".h", ".cpp", ".cs", ".rb", ".php", ".swift",
                ".md", ".json", ".yaml", ".yml", ".toml", ".sql", ".sh")

# 行级否定词：同行出现则视为反例
NEGATION_WORDS = ("不存在", "都没有", "没有", "已移除", "已删除", "勿用", "别找",
                  "does not exist", "doesn't exist", "removed", "deleted")
# 段级否定：标题含这些词则整段豁免
NEGATION_HEADINGS = ("误区", "不存在", "反例", "别去", "不要", "陷阱", "已移除",
                     "pitfall", "anti-pattern", "does not exist", "myth")
# 显式豁免标记
IGNORE_MARKER = "[ignore-ref]"

# 文档内联的"公共前缀"声明：用于文档省略深层源码根的场合
#   <!-- ref-prefix: android/app/src/main/java/com/example/app/ -->
# 从该行起生效，直到文件结束，或被 <!-- ref-prefix: --> 清除。
# 为什么需要：Kotlin/Java 的包根有 6+ 层深，文档通常会声明一次然后省略，
# 纯靠自动探测会把所有深层目录都当候选根，既慢又容易误判。
REF_PREFIX_PAT = re.compile(r"<!--\s*ref-prefix:\s*([^>]*?)\s*-->")

# 深层源码根的自定义识别：这些目录名的父路径也算候选根
SOURCE_ROOT_MARKERS = (
    os.path.join("src", "main", "java"),
    os.path.join("src", "main", "kotlin"),
    os.path.join("src", "main", "python"),
    "src",
    "app",
    "lib",
)

# 扫描 basename 索引时跳过的目录
SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", ".pytest_cache", "node_modules",
    ".gradle", "build", "dist", ".idea", ".mypy_cache", ".ruff_cache",
    ".next", "target", "vendor", "coverage", ".tox", ".cache",
}


def detect_project_roots(repo_root: str, exts: tuple[str, ...], max_depth: int = 6) -> list[str]:
    """探测候选根前缀。

    候选来源：
      1. 仓库根本身
      2. 第一层直接包含代码的目录（backend/ src/ …）
      3. 深层源码根（…/src/main/java、…/src、…/app …）——Kotlin/Java 包根动辄 6+ 层

    这样文档里写 `app/services/x.py`（子项目相对）、`backend/app/x.py`（仓库相对）、
    `ui/nav/A.kt`（Android 包根相对）都能解析——写文档的人不必记住用哪种基准。
    """
    roots = [""]
    try:
        entries = sorted(os.listdir(repo_root))
    except OSError:
        return roots

    for name in entries:
        full = os.path.join(repo_root, name)
        if not os.path.isdir(full) or name in SKIP_DIRS or name.startswith("."):
            continue
        if _has_code(full, exts, max_depth=2):
            roots.append(name + "/")

    # 深层源码根
    for dirpath, dirnames, _ in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        rel = os.path.relpath(dirpath, repo_root).replace("\\", "/")
        depth = rel.count("/") + 1
        if depth > max_depth:
            dirnames[:] = []
            continue
        for marker in SOURCE_ROOT_MARKERS:
            if rel.endswith(marker.replace("\\", "/")):
                prefix = rel + "/"
                if prefix not in roots:
                    roots.append(prefix)
    return roots


def _has_code(root: str, exts: tuple[str, ...], max_depth: int) -> bool:
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        depth = dirpath[len(root):].count(os.sep)
        if depth >= max_depth:
            dirnames[:] = []
        if any(f.endswith(exts) for f in filenames):
            return True
    return False


def build_basename_index(repo_root: str, prefixes: list[str], exts: tuple[str, ...]) -> dict[str, int]:
    """basename -> 出现次数，用于裸文件名引用的校验与歧义提示。"""
    index: dict[str, int] = {}
    for prefix in prefixes:
        base = os.path.join(repo_root, prefix) if prefix else repo_root
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(exts):
                    index[fn] = index.get(fn, 0) + 1
    return index


def check_file(doc: str, repo_root: str, exts: tuple[str, ...],
               prefixes: list[str], index: dict[str, int],
               quiet: bool) -> tuple[int, int, list[tuple[int, str]]]:
    """返回 (已校验数, 豁免数, 失效清单)。"""
    with open(doc, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    ext_alt = "|".join(re.escape(e.lstrip(".")) for e in exts)
    pat = re.compile(r"`([A-Za-z0-9_\-./]+\.(?:" + ext_alt + r"))`")

    checked = skipped = 0
    broken: list[tuple[int, str]] = []
    section_negative = False
    doc_prefix = ""                     # 文档内联声明的公共前缀

    for lineno, line in enumerate(lines, 1):
        # 段级：进入含否定词的标题后整段按反例处理，直到下一个标题
        if line.lstrip().startswith("#"):
            section_negative = any(w in line for w in NEGATION_HEADINGS)

        # 文档内联前缀声明
        pm = REF_PREFIX_PAT.search(line)
        if pm:
            doc_prefix = pm.group(1).strip().lstrip("/")
            if doc_prefix and not doc_prefix.endswith("/"):
                doc_prefix += "/"

        # 有效候选根：文档声明的优先，其次是自动探测的
        cands = ([doc_prefix] if doc_prefix else []) + prefixes

        for m in pat.finditer(line):
            token = m.group(1)
            if (section_negative
                    or IGNORE_MARKER in line
                    or any(w in line for w in NEGATION_WORDS)):
                skipped += 1
                continue
            checked += 1

            if "/" not in token:                      # 裸文件名
                if token not in index:
                    broken.append((lineno, token))
                continue

            if not any(os.path.isfile(os.path.join(repo_root, p + token)) for p in cands):
                broken.append((lineno, token))

    return checked, skipped, broken


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):           # Windows 控制台默认 GBK
        try:
            stream.reconfigure(encoding="utf-8")      # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        description="校验文档里引用的文件路径是否真实存在")
    ap.add_argument("docs", nargs="+", help="要校验的文档（支持通配符）")
    ap.add_argument("--repo-root", default=None, help="仓库根目录（默认：文档所在目录向上找 .git）")
    ap.add_argument("--ext", nargs="+", default=None, help="只校验这些扩展名")
    ap.add_argument("--quiet", action="store_true", help="只输出结论与失效项")
    args = ap.parse_args(argv)

    # 展开通配符
    docs: list[str] = []
    for d in args.docs:
        hits = sorted(glob.glob(d, recursive=True))
        docs.extend(h for h in hits if os.path.isfile(h))
    if not docs:
        print("error: 没有匹配到任何文档", file=sys.stderr)
        return 2

    repo_root = args.repo_root or _find_repo_root(docs[0])
    repo_root = os.path.abspath(repo_root)
    exts = tuple(args.ext) if args.ext else DEFAULT_EXTS

    prefixes = detect_project_roots(repo_root, exts)
    index = build_basename_index(repo_root, prefixes, exts)

    if not args.quiet:
        print(f"仓库根        : {repo_root}")
        print(f"候选根前缀     : {', '.join(repr(p) for p in prefixes)}")
        print(f"basename 索引 : {len(index)} 个文件")
        print()

    total_checked = total_skipped = 0
    all_broken: list[tuple[str, int, str]] = []
    for doc in docs:
        checked, skipped, broken = check_file(
            doc, repo_root, exts, prefixes, index, args.quiet)
        total_checked += checked
        total_skipped += skipped
        all_broken.extend((doc, ln, tok) for ln, tok in broken)
        if not args.quiet:
            status = "OK" if not broken else f"{len(broken)} 处失效"
            print(f"  {doc}  —  校验 {checked} / 豁免 {skipped}  —  {status}")

    if not args.quiet:
        print()
    print(f"合计：校验 {total_checked} 处引用，豁免 {total_skipped} 处（反例）")

    if all_broken:
        print(f"\n失效引用 {len(all_broken)} 处：")
        for doc, ln, tok in all_broken:
            print(f"  {doc}:{ln}  {tok}")
        print("\n修复后重跑。过期/错误的引用比没有更糟——"
              "agent 会相信结论而不再核实。")
        return 1

    print("全部引用有效 ✅")
    return 0


def _find_repo_root(start: str) -> str:
    """从文档所在目录向上找 .git。"""
    cur = os.path.abspath(os.path.dirname(start) or ".")
    while True:
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(os.path.dirname(start) or ".")
        cur = parent


if __name__ == "__main__":
    raise SystemExit(main())
