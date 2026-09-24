#!/usr/bin/env python3
"""_check_live_doc_counts.py —— 活文档里**手写的「会变的数字」**（整改报告 §13）。

### 为什么要有它
报告 §13：「会变化的数字一律不写进文档，或者写成断言让机器守住。」
本项目第一个例子就在**每次会话都会读**的 `AGENTS.md` 里：

```text
python _tools/qa/_check_all.py          # 全部静态检查（当前 50 个脚本，约一分钟）
```

写的时候确实是 50 个，现在已经是 97 个 —— 而读到它的人（尤其是 AI）会拿它当参照：
「我只看到 97 个？文档说 50 个，是不是哪儿坏了」。同一页另外两处也一样：
「155 个端点」（实际 228）；`03_BACKEND_DETAILS.md` 说 `orders.py`「1,165 行 / 23 个端点」
（阶段 4 拆完之后它只剩装配说明，25 个端点分在 8 个 `orders*.py` 里）。
**过期地图比没有地图更糟** —— 这句就写在 `AGENTS.md` 自己身上。

### 判据（每个「文件 × 判据族」一条，不按命中数算 —— 免得「没命中」被当成检查空转）

1. 活文档 = **每次会话都要读的那几页**（`AGENTS.md` + 项目地图的关键页）；
   ⛔ 不包括历史审计/报告/存档 —— 那里的数字是**当时的快照**，改了反而丢证据；
2. 三类**能现算**的数字：检查脚本数（`_check_all.discover()` 自己数）、端点总数
   （端点索引那个生成器的 `collect()`）、`orders.py` 的规模（文件行数 + 该组端点数）；
3. ⚠️ 数字只在**它自己声明「这是当前值」的上下文里**才判（同一行提到那个生成物 / 那个命令），
   于是「155 个端点里只有 78 个挂了 require_permission」这类**当时的结论**不会被误判；
4. ⚠️ `orders.py` 的行数只在**紧挨着文件名**的位置判（地图里的长表格行会顺带提到别的文件的行数）；
5. 算不出真值时**报错而不是放过**（生成器或源码结构变了就来改这个脚本，不许静悄悄地不查）。

用法：
    python _tools/qa/_check_live_doc_counts.py --check   # 非零退出＝有对不上的数字
    python _tools/qa/_check_live_doc_counts.py           # 打印逐条明细
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

#: 活文档：**每次会话都要读**的那几页。新增页面时加进来，别让它烂在一边。
LIVE = [
    "AGENTS.md",
    "docs/PROJECT_MAP/INDEX.md",
    "docs/PROJECT_MAP/02_BACKEND_API.md",
    "docs/PROJECT_MAP/03_BACKEND_DETAILS.md",
    "docs/PROJECT_MAP/05_TESTING.md",
    "docs/PROJECT_MAP/08_CODE_LOCATOR.md",
]

MIN_RULES = 20
RE_SCRIPTS = re.compile(r"(\d+)\s*个脚本")
RE_ENDPOINTS = re.compile(r"(\d+)\s*个端点")
#: ⚠️ 只在**紧挨着文件名**的位置判（`orders.py` 后面 45 个字符内）—— 地图里的长表格行会顺带提到
#: 别的文件的行数（`shipper.py`（405 行）…），不设窗口就会把它们当成 orders 组的数字。
RE_ORDERS_LINES = re.compile(r"orders\.py[^\n]{0,45}?([\d,]+)\s*行")
RE_ORDERS_EPS = re.compile(r"orders\.py[^\n]{0,45}?(\d+)\s*个端点")
RE_VERIFY = re.compile(r"(\d+)\s*份")


def check_total() -> int:
    """检查脚本总数 = 跑 `_check_all.py` 时它自己数的那个数（同一份发现规则，不另写一遍）。"""
    sys.path.insert(0, str(HERE))
    from _check_all import discover  # noqa: PLC0415

    run_all, _notes = discover()
    return len(run_all)


def reverse_verify_total() -> int:
    """反向验证脚本数 = `_reverse_verify_all.py --list` 自己列出来的
    （**与基线采集器 `_capture_baseline.py` 同一口径**，不另数一遍文件）。"""
    tool = ROOT / "_tools" / "ai" / "_reverse_verify_all.py"
    proc = subprocess.run([sys.executable, str(tool), "--list"], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=300,
                          cwd=str(ROOT))
    text = (proc.stdout or "") + (proc.stderr or "")
    return len([ln for ln in text.splitlines()
                if ln.strip().endswith(".py") and "reverse_verify" in ln])


def endpoints() -> list[dict]:
    """端点 = 端点索引生成器那一份 `collect()`（口径与 08A 一致，不另写 AST 解析）。"""
    sys.path.insert(0, str(ROOT / "backend" / "scripts"))
    from gen_endpoint_index import SKIP_DIRS, collect  # noqa: PLC0415

    app_root = str(ROOT / "backend" / "app")
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(app_root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                full = os.path.join(dirpath, fn)
                files.append(os.path.relpath(full, app_root).replace("\\", "/"))
    files.sort()
    rows, _aliases = collect(app_root, files)
    return rows


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

    def judge(where: str, label: str, claims: list, real: int, hint: str) -> None:
        """一条判据 = 一个文件的一个判据族：没写＝过；写了就每处都必须与现状一致。"""
        bad = [(c[0], c[1], c[2]) for c in claims if c[1] != real]
        if bad:
            detail = "；".join("L" + str(ln) + " 写着「" + str(n) + " " + what + "」" for ln, n, what in bad)
            want(False, "", where + " " + label + "：" + detail + "，实际是 " + str(real) + " —— " + hint)
            return
        if claims:
            want(True, where + " " + label + "：" + str(len(claims)) + " 处声明，全部与现状（" + str(real) + "）一致", "")
            return
        want(True, where + " " + label + "：没手写这类当前值", "")

    total_checks = check_total()
    rv_total = reverse_verify_total()
    rows = endpoints()
    total_endpoints = len(rows)
    orders_rows = [r for r in rows if str(r.get("file", "")).startswith("api/v1/orders")]
    orders_api = ROOT / "backend" / "app" / "api" / "v1" / "orders.py"
    orders_lines = -1
    if orders_api.exists():
        orders_lines = len(io.open(orders_api, encoding="utf-8").read().splitlines())

    ok_real = total_endpoints > 100 and orders_lines > 0 and len(orders_rows) > 0 and rv_total > 10
    want(ok_real,
         "真值算出来了：检查 " + str(total_checks) + " 个 / 端点 " + str(total_endpoints)
         + " 个 / orders.py " + str(orders_lines) + " 行、该组 " + str(len(orders_rows))
         + " 个端点 / 反向验证 " + str(rv_total) + " 份",
         "算不出真值（检查 " + str(total_checks) + "、端点 " + str(total_endpoints)
         + "、orders.py " + str(orders_lines) + " 行 / " + str(len(orders_rows))
         + " 个端点 / 反向验证 " + str(rv_total) + " 份）—— 生成器或源码结构变了，来改这个脚本，不许静悄悄地不查")

    found = 0
    for rel in LIVE:
        path = ROOT / rel
        if not path.exists():
            want(False, "", rel + " 不存在（活文档被删/改名了？来改这个脚本的 LIVE 清单）")
            continue
        found += 1
        lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()

        claims = [(i, int(m.group(1)), "个脚本")
                  for i, ln in enumerate(lines, 1) if "_check_all" in ln
                  for m in RE_SCRIPTS.finditer(ln)]
        judge(rel, "检查脚本数", claims, total_checks, "删掉数字、改成指向 `_check_all.py` 第一行（它自己数）")

        claims = [(i, int(m.group(1)), "个端点")
                  for i, ln in enumerate(lines, 1) if "08A_ENDPOINT_INDEX" in ln
                  for m in RE_ENDPOINTS.finditer(ln)]
        judge(rel, "端点索引端点数", claims, total_endpoints, "删掉数字、改成指向 08A（它是生成的）")

        # ⚠️ 两条收紧（第一版误报过）：① 数字要**紧挨着** `_reverse_verify` 才算（地图里的长表格行会
        # 顺带写别的"5 份/4 份"）；② 行里写了「以…为准」的是**自带免责的历史记录**（如
        # 「2026-09-19 实测 49 份」），不许当成"当前值"来判 —— 那种注记留着的价值就是它标了日期。
        claims = []
        for i, ln in enumerate(lines, 1):
            for m in re.finditer(r"_reverse_verify", ln):
                window = ln[max(0, m.start() - 30): m.end() + 30]
                if "为准" in window:
                    continue
                for mm in RE_VERIFY.finditer(window):
                    claims.append((i, int(mm.group(1)), "份（反向验证）"))
        judge(rel, "反向验证份数", claims, rv_total, "删掉数字、改成指向 `_reverse_verify_all.py --list`（它自己列）")

        claims = []
        for i, ln in enumerate(lines, 1):
            if "orders.py" not in ln:
                continue
            for m in RE_ORDERS_LINES.finditer(ln):
                claims.append((i, int(m.group(1).replace(",", "")), "行（orders.py）"))
            for m in RE_ORDERS_EPS.finditer(ln):
                claims.append((i, int(m.group(1)), "个端点（orders 组）"))
        bad = []
        for ln, n, what in claims:
            if what == "行（orders.py）" and n != orders_lines:
                bad.append((ln, n, what))
            if what == "个端点（orders 组）" and n != len(orders_rows):
                bad.append((ln, n, what))
        if bad:
            detail = "；".join("L" + str(ln) + " 写着「" + str(n) + " " + what + "」" for ln, n, what in bad)
            want(False, "", rel + " " + detail + "，实际是 " + str(orders_lines) + " 行 / "
                 + str(len(orders_rows)) + " 个端点（阶段 4 搬迁之后只剩装配说明）")
        elif claims:
            want(True, rel + "：" + str(len(claims)) + " 处 orders 规模声明都与现状一致", "")
        else:
            want(True, rel + "：没手写 orders 组的规模数字", "")

    want(found >= 5, "扫到 " + str(found) + " 份活文档",
         "只扫到 " + str(found) + " 份活文档 —— 路径集体失效了？")
    total = len(passed) + len(failures)
    want(total >= MIN_RULES, "判据条数 " + str(total) + " ≥ " + str(MIN_RULES),
         "只跑了 " + str(total) + " 条判据（< " + str(MIN_RULES) + "）—— 检查可能空转了")

    print("活文档数字判据：" + str(len(passed)) + " 通过 / " + str(len(failures)) + " 失败")
    if not check_mode:
        for n in passed:
            print("  ✅ " + n[4:])
    for f in failures:
        print("  " + f)
    if failures:
        return 1
    print("  ✅ 全部通过（活文档里手写的数字都与现状一致，或已被指向生成物）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
