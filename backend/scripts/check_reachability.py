#!/usr/bin/env python3
"""check_reachability.py —— 校验「自动加载入口 → 全部文档」的可达性，并补上 markdown 链接的校验盲区。

为什么需要它（两个都已实测的问题）：

1. **反引号路径校验器（agentctx-refcheck 的 check_refs.py）看不见 markdown 链接。**
   `[文本](docs/x.md)` 这种写法整段不被覆盖——而入口文件里的链接**恰恰全是这种形式**。
   也就是说：**最重要的那个文件的链接，此前从未被校验过。**
   一旦它写错，整套文档对 agent 就"不存在"了，且没有任何机制会报警。

2. **"文件存在"不等于"能被找到"。**
   一份新文档写完、放在目录里、甚至加进了索引页，只要**没有从入口链过去**，
   对新会话就等于不存在。真实案例：一个项目建了 94 KB 的项目地图（7 份文档 + 自己的索引页），
   但入口文件从未被修改过——那份资产对 agent 沉睡了 5 个月。
   可达性必须**从入口做图遍历**来验证，不能靠"我记得挂过"。

检查项：
    R1  markdown 链接目标存在（相对路径按引用文件所在目录解析，失败再按仓库根试）
    R2  从入口文件出发，能到达 `--docs` 下每一份 Markdown（否则报"孤儿文档"）
    R3  入口文件里的链接都能解析（入口断了等于全断）

用法：
    python check_reachability.py                          # 自动探测入口与仓库根
    python check_reachability.py --repo-root . --entry AGENTS.md --docs docs
退出码：0 = 全部可达；1 = 有断链或孤儿（可接 CI / pre-commit）。
"""

from __future__ import annotations

import argparse
import os
import re
import sys

# 常见入口文件名，按优先级排列（哪个存在用哪个）
ENTRY_CANDIDATES = (
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", "AGENT.md", ".cursorrules",
    os.path.join(".github", "copilot-instructions.md"),
)

# markdown 链接：[文本](目标) —— 排除外链与锚点
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
# 行内代码：`...` —— 必须先剥掉再找链接。
# ⚠️ 为什么必需：文档里经常**举例说明**链接语法（如「`[文本](路径)` 这种写法」），
#    不剥掉行内代码就会把示例当成真链接，报出假断链（实测踩过）。
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", "build",
             "dist", ".gradle", ".pytest_cache", ".idea", ".mypy_cache"}


def find_repo_root(start: str) -> str:
    """从 start 向上找 .git；找不到就返回 start。"""
    cur = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(start)
        cur = parent


def find_entry(repo: str) -> str | None:
    for cand in ENTRY_CANDIDATES:
        p = os.path.join(repo, cand)
        if os.path.isfile(p):
            return p
    return None


def _links(path: str) -> list[str]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = INLINE_CODE_RE.sub("", fh.read())     # 剥掉行内代码，示例不算链接
    out = []
    for raw in LINK_RE.findall(text):
        t = raw.strip()
        if t.startswith(("http://", "https://", "mailto:", "#")):
            continue
        t = t.split("#")[0].strip()
        if t:
            out.append(t)
    return out


def _resolve(ref: str, base_dir: str, repo: str) -> str | None:
    """把链接目标解析成真实文件路径。

    先按引用文件所在目录解析；失败再按仓库根解析——因为文档里两种基准都有人用，
    而"基准不统一"本身就是最常见的断链原因之一。两种都失败才算断链，
    这样既不会因为基准不同报假断链，也不会漏掉真断链。
    """
    for base in (base_dir, repo):
        cand = os.path.normpath(os.path.join(base, ref.replace("/", os.sep)))
        if os.path.isfile(cand):
            return cand
    return None


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")     # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        prog="check_reachability",
        description="校验入口 → 文档的可达性，并校验 markdown 链接")
    ap.add_argument("--repo-root", default=None, help="仓库根（默认从当前目录向上找 .git）")
    ap.add_argument("--entry", default=None,
                    help=f"入口文件（默认自动探测：{', '.join(ENTRY_CANDIDATES[:3])} …）")
    ap.add_argument("--docs", default=None,
                    help="应被可达性覆盖的文档目录（默认 docs/，不存在则用仓库根）")
    args = ap.parse_args(argv)

    repo = os.path.abspath(args.repo_root) if args.repo_root else find_repo_root(os.getcwd())
    entry = os.path.abspath(args.entry) if args.entry else find_entry(repo)
    if not entry or not os.path.isfile(entry):
        print("error: 找不到入口文件（用 --entry 指定）", file=sys.stderr)
        return 2

    if args.docs:
        docs_root = os.path.abspath(args.docs)
    else:
        d = os.path.join(repo, "docs")
        docs_root = d if os.path.isdir(d) else repo

    # ⚠️ 扫描范围不存在时必须报错，不能"0 份文档 → 0 个孤儿 → 通过"。
    #    实测 `--docs 打错的路径` 会输出"✅ 无孤儿文档 / 可达性检查通过"——**什么都没扫却是绿的**。
    #    "没看" 与 "看过了没问题" 必须在输出上能区分，否则这个校验器给的是虚假安全感。
    if not os.path.isdir(docs_root):
        print(f"error: 待扫描的文档目录不存在: {docs_root}", file=sys.stderr)
        print("       （这不是「没有孤儿」，而是根本没扫——请检查 --docs）", file=sys.stderr)
        return 2
    if not os.path.isdir(repo):
        print(f"error: 仓库根不存在: {repo}", file=sys.stderr)
        return 2

    problems: list[str] = []

    # ── R1/R3：从入口开始 BFS，同时校验沿途每一条 markdown 链接 ──
    seen: set[str] = set()
    queue = [entry]
    broken: list[tuple[str, str]] = []
    n_links = 0
    while queue:
        cur = queue.pop()
        if cur in seen or not cur.endswith(".md"):
            continue
        seen.add(cur)
        for ref in _links(cur):
            n_links += 1
            target = _resolve(ref, os.path.dirname(cur), repo)
            if target is None:
                broken.append((os.path.relpath(cur, repo), ref))
                continue
            if target.endswith(".md") and target not in seen:
                queue.append(target)

    # ── R2：docs 下每份文档都应可达 ──
    all_docs: list[str] = []
    for dp, dn, fs in os.walk(docs_root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith(".")]
        for f in fs:
            if f.endswith(".md"):
                all_docs.append(os.path.abspath(os.path.join(dp, f)))
    all_docs.sort()
    orphans = [d for d in all_docs if d not in seen]

    print(f"仓库根        : {repo}")
    print(f"入口文件      : {os.path.relpath(entry, repo)}")
    print(f"扫描范围      : {os.path.relpath(docs_root, repo)}/")
    print(f"markdown 链接 : {n_links} 条")
    print(f"可达文档      : {len(all_docs) - len(orphans)} / {len(all_docs)}")

    if broken:
        problems.append(f"断链 {len(broken)} 条")
        print(f"\n❌ 断链 {len(broken)} 条（反引号路径校验器查不出这类）：")
        for src, ref in broken[:40]:
            print(f"   {src}  →  {ref}")
    else:
        print("\n✅ markdown 链接全部有效")

    if orphans:
        problems.append(f"孤儿文档 {len(orphans)} 份")
        print(f"\n❌ 孤儿文档 {len(orphans)} 份（从入口出发无法到达 = 对新会话不存在）：")
        for d in orphans[:40]:
            print(f"   {os.path.relpath(d, repo)}")
        print("\n   修法二选一：")
        print("     ① 从入口/索引页加一行链过去（多数情况）；")
        print("     ② 若它确实不该被读（历史归档），**也要链过去**，但注明状态")
        print("        ——「找不到」和「知道它不该读」是两回事。")
    else:
        print("✅ 无孤儿文档：从入口可达全部文档")

    if problems:
        print(f"\n共 {len(problems)} 类问题：" + "、".join(problems))
        return 1
    print("\n可达性检查通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
