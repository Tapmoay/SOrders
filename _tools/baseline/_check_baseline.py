#!/usr/bin/env python3
"""_check_baseline.py —— 基线快照的静态判据（进 `_check_all.py` 自动跑）。

### 为什么快照需要自己的检查
报告 §2 的第一条建议就是「先建立真实世界基线」，而基线**唯一的价值**是「改造前的样子」——
所以 `_tools/baseline/_capture_baseline.py` 自己写着第 3 条口径：「`before/` 快照不可覆盖」。

⚠️ **2026-09-24 实测：这条口径被绕过了一次**——重采时忘了换标签 + `--force`，
`before/2026-09-24/baseline.json` 被换成了改造后的数据（模型表数 45 → 46、
`schema_versions` 出现在 `infra_tables` 里、`git_ahead` 88 → 109），而 `docs/BASELINE.md` 那一页
还指着它说「快照」。**没有任何检查会说话**——正是本项目反复栽的那一类：
「写在文档/工具文档字符串里的规矩没人执行」。

### 判据（每条都对应一种「事后才发现」的事故）
1. 结构是 `<标签>/<YYYY-MM-DD>/baseline.json`，且至少一份；
2. `before/` 至少一份（对照物没了，后面所有「改了多少」都无从谈起）；
3. 每份能解析 + 必需键齐全（改字段名时先喊，别等到用时才发现少一列）；
4. 每份都被 git 跟踪（**快照是记录，不是草稿**：只在某人本机躺着等于没有）；
5. 已跟踪的每份与 HEAD 一致（`git diff HEAD`）—— 冻结的东西不许事后改；
6. `before/` 那份记录的 `git_commit` 必须是「引入本工具那个提交」的**祖先**
   （改造后采的数据必然是它的**后代** → 判据当场红，正是上面那次事故的形状）；
7. 那个 `git_commit` 在库里真实存在（防手改 JSON 编一个号）；
8. 快照的 `captured_at` 日期 == 它所在目录的日期（防「把今天的数塞进昨天的目录」）；
9. `docs/BASELINE.md` 至少指着一份快照，且指着的那份真实存在（文档与快照成对）；
10. 采集脚本默认拒绝覆盖、支持 `--label`、快照路径用 `args.label`。

用法：
    python _tools/baseline/_check_baseline.py --check   # 非零退出＝有问题
    python _tools/baseline/_check_baseline.py           # 打印逐条明细
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOC = ROOT / "docs" / "BASELINE.md"
TOOL = HERE / "_capture_baseline.py"
CAPTURE_REL = "_tools/baseline/_capture_baseline.py"
MIN_RULES = 15

REQUIRED = [
    "captured_at", "git_commit", "git_branch", "git_ahead", "endpoints_total",
    "model_table_count", "static_checks", "version_file",
]
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LABEL = re.compile(r"^[a-z][a-z0-9_-]*$")
SNAP_IN_DOC = re.compile(r"_tools/baseline/[A-Za-z0-9_.-]+/\d{4}-\d{2}-\d{2}/baseline\.json")


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "").strip()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    check_mode = "--check" in sys.argv[1:]
    passed: list[str] = []
    failures: list[str] = []

    def want(ok: bool, good: str, bad: str) -> bool:
        (passed if ok else failures).append(("OK  " if ok else "BAD ") + (good if ok else bad))
        return ok

    snaps = sorted(HERE.glob("*/*/baseline.json"))
    want(bool(snaps), "有 " + str(len(snaps)) + " 份快照（" +
         "、".join(sorted({p.parents[1].name for p in snaps})) + "）",
         "一份快照都没有（跑 _tools/baseline/_capture_baseline.py）")
    want(all(LABEL.match(p.parents[1].name) and DAY.match(p.parent.name) for p in snaps),
         "目录结构 <标签>/<YYYY-MM-DD>/baseline.json 合法",
         "⛔ 有快照不在 <标签>/<YYYY-MM-DD>/baseline.json 结构上：")
    before = [p for p in snaps if p.parents[1].name == "before"]
    want(bool(before), "before/ 有改造前的快照（对照物在）",
         "⛔ before/ 没有快照 —— 没有对照物，后面所有「改了多少」都无从谈起")

    for p in snaps:
        rel = p.relative_to(ROOT).as_posix()
        try:
            local = json.loads(p.read_text(encoding="utf-8"))["local"]
        except Exception as exc:  # noqa: BLE001
            want(False, "", rel + " 读不出来/解析失败：" + str(exc))
            continue
        missing = [k for k in REQUIRED if local.get(k) in (None, "")]
        want(not missing, rel + " 必需键齐全", rel + " 缺键（改字段名了？）：" + str(missing))
        rc, _ = git("ls-files", "--error-unmatch", "--", rel)
        tracked = rc == 0
        want(tracked, rel + " 已被 git 跟踪",
             "⛔ " + rel + " 没有进 git —— 快照是记录不是草稿，只在某台机器上躺着等于没有")
        if tracked:
            rc2, _ = git("diff", "--quiet", "HEAD", "--", rel)
            want(rc2 == 0, rel + " 与 HEAD 一致（冻结未被改）",
                 "⛔ " + rel + " 与 HEAD 不一致 —— 冻结的快照被改过；"
                 "要采「现在这一刻」请换标签：--label after")
        day = p.parent.name
        cap = str(local.get("captured_at") or "")
        want(cap[:10] == day, rel + " captured_at 与目录日期一致",
             "⛔ " + rel + " 的 captured_at（" + cap[:10] + "）与目录日期（" + day + "）对不上")

    _, adders = git("log", "--diff-filter=A", "--format=%H", "--", CAPTURE_REL)
    add_commit = adders.splitlines()[-1] if adders else ""
    want(bool(add_commit), "找到引入采集工具的提交 " + add_commit[:8],
         "找不引入 _capture_baseline.py 的提交（git 历史被改写？）")
    for p in before:
        rel = p.relative_to(ROOT).as_posix()
        try:
            sha = str(json.loads(p.read_text(encoding="utf-8"))["local"].get("git_commit") or "")
        except Exception:  # noqa: BLE001
            continue
        rc, _ = git("cat-file", "-e", sha + "^{commit}")
        want(rc == 0, rel + " 记录的提交 " + sha[:8] + " 在库里存在",
             "⛔ " + rel + " 记录的提交 " + sha[:8] + " 在库里不存在（JSON 被手改过？）")
        if add_commit and rc == 0:
            rc2, _ = git("merge-base", "--is-ancestor", sha, add_commit)
            want(rc2 == 0,
                 rel + " 记的是「引入本工具之前」的状态 " + sha[:8],
                 "⛔ " + rel + " 记录的 " + sha[:8] + " 不是引入本工具那个提交 " + add_commit[:8]
                 + " 的祖先 —— 这是**改造后**采的数据被塞进了 before/（2026-09-24 发生过一次）")

    doc = DOC.read_text(encoding="utf-8", errors="replace") if DOC.exists() else ""
    want(bool(doc), "docs/BASELINE.md 存在", "⛔ docs/BASELINE.md 不存在（文档与快照必须成对）")
    mentioned = sorted(set(SNAP_IN_DOC.findall(doc)))
    want(bool(mentioned), "docs/BASELINE.md 指着快照（" + str(len(mentioned)) + " 处）",
         "⛔ docs/BASELINE.md 没有提到任何快照路径 —— 页面上那些数字对不上任何一份记录")
    for m in mentioned:
        want((ROOT / m).exists(), "文档里提到的快照存在：" + m,
             "⛔ 文档指着 " + m + "，但那份快照不存在（渲染到一半/被删了）")

    src = TOOL.read_text(encoding="utf-8", errors="replace") if TOOL.exists() else ""
    want("--label" in src and "args.label" in src,
         "采集脚本支持 --label（before / after 分开落盘）",
         "⛔ 采集脚本没有 --label：重采只能覆盖 before/（2026-09-24 那次事故的根因）")
    want("snap.exists() and not args.force" in src,
         "采集脚本默认拒绝覆盖已存在的快照",
         "⛔ 采集脚本不再拒绝覆盖 —— 「改造前的样子」会被后来的数据悄悄覆盖")
    want("--force" in src, "确实要覆盖时得显式 --force", "⛔ --force 开关没了")

    total = len(passed) + len(failures)
    want(total >= MIN_RULES, "判据条数 " + str(total) + " ≥ " + str(MIN_RULES),
         "⛔ 只跑了 " + str(total) + " 条判据（< " + str(MIN_RULES) + "）—— 检查可能空转了")

    print("基线快照判据：" + str(len(passed)) + " 通过 / " + str(len(failures)) + " 失败")
    if not check_mode:
        for n in passed:
            print("  ✅ " + n[4:])
    for f in failures:
        print("  " + f)
    if failures:
        return 1
    print("  ✅ 全部通过（改造前的快照还在，且没被改过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
