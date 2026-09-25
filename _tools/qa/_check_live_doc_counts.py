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
5. 算不出真值时**报错而不是放过**（生成器或源码结构变了就来改这个脚本，不许静悄悄地不查）；
6. ⭐ 给 `_check_all.py` 写**耗时**（「约一分钟」）也算同一类毛病 —— 写的时候是真的、之后必然过期
   （实测写着「约一分钟」而它当时要跑 171 秒）。那个数现在由 `_check_all.py` 自己打在输出里
   （「跑完 N 个检查，总耗时 X 秒。」），活文档里再写一份就是**第二份真相** → 判红。

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
    # ---- 2026-09-25 扩容：另外几页也是"动手前会看"的，它们同样会长出会变的数字 ----
    #     实测这一扩就抓到两处过期：`_tools/backup/README.md` 里写着「50 条判据」、AGENTS.md 写着「55 条」，
    #     而 `_check_backup.py` 当时自己打印的是 **54** —— 同一个数字在两页里不一致，**而且两个都是错的**。
    "_tools/backup/README.md",
    "docs/CORE_AND_EXTENSION.md",
    "README.md",
    "backend/app/migrations/README.md",
]

#: 跑不动/不该在检查里跑的脚本（口径见 `script_total` 里的说明）。
CANNOT_RUN = {"_check_all.py"}

MIN_RULES = 30
RE_SCRIPTS = re.compile(r"(\d+)\s*个脚本")
RE_ENDPOINTS = re.compile(r"(\d+)\s*个端点")
#: ⚠️ 只在**紧挨着文件名**的位置判（`orders.py` 后面 45 个字符内）—— 地图里的长表格行会顺带提到
#: 别的文件的行数（`shipper.py`（405 行）…），不设窗口就会把它们当成 orders 组的数字。
RE_ORDERS_LINES = re.compile(r"orders\.py[^\n]{0,45}?([\d,]+)\s*行")
RE_ORDERS_EPS = re.compile(r"orders\.py[^\n]{0,45}?(\d+)\s*个端点")
RE_VERIFY = re.compile(r"(\d+)\s*份")
#: 「某个检查脚本有多少条判据」——活文档里很爱写这个数（它确实有信息量），而它**每次加判据都会过期**。
#: 形状两种：`_check_x.py`（55 条）与 `（50 条判据，… _check_x.py）`；只在**非表格行**上判（地图的长表格行会
#: 顺带提到别的数字）。
RE_CHECK_COUNT = re.compile(
    # ⚠️ 数字后面那一格还要在代码里再筛一次（见下面 `ok = …`）：光靠正则分不清
    #    「（55 条，已进必跑组）」这种**声明**与「点出 6 条，其中 …」那种**叙事**。
    r"(_(?:check|reverse_verify)_[a-z0-9_]+\.py)[^\n|]{0,24}?(\d+)\s*条"
    r"|(\d+)\s*条[^\n|]{0,24}?(_(?:check|reverse_verify)_[a-z0-9_]+\.py)"
)
#: ⭐ 给 `_check_all.py` 手写的**耗时**（R3-07c 实测：AGENTS.md 写着「约一分钟」，而它当时要 171 秒）。
#: 那个数只能由 `_check_all.py` 自己打（它现在会打一行「跑完 N 个检查，总耗时 X 秒。」）——
#: 活文档里再写一份就是第二份真相，而且**写的时候是真的、之后必然过期**。
RE_DURATION = re.compile(r"\d+(?:\.\d+)?\s*(?:分钟|小时|秒钟|秒|min)")

#: 脚本**自己报的**总数（口径是它的输出，不是我们数源码里的 want() 调用 —— 那有五六种写法）。
#: 静态检查脚本报总数的那几种写法（它自己的总结句）。
RULE_PATTERNS = (
    r"全部\s*(\d+)\s*项通过",
    r"共\s*(\d+)\s*项检查",
    # `_check_all.py` 的第一行是「共 100 个检查脚本」（"个"不是"项"）
    r"共\s*(\d+)\s*个检查",
    r"通过\s*(\d+)\s*项",
    r"判据条数\s*(\d+)",
    r"判据总数\s*(\d+)",
)
#: 反向验证脚本报**注入条数**的那几种写法。
#: ⚠️ 两类必须分开：反向验证脚本会先跑一遍红线（输出里也有「全部 39 项通过」），
#:    用"总数"那组模式会取到**红线的条数**而不是注入条数（第一版就把 6 条读成了 39）。
INJECTION_PATTERNS = (
    r"(\d+)\s*条注入都证明",
    r"全部\s*(\d+)\s*条注入",
    r"(\d+)/\d+\s*种破坏方式",
    r"(\d+)/\d+\s*条成立",
    r"(\d+)/\d+\s*全部成立",
)


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


def script_total(rel: str, cache: dict[str, int | None]) -> int | None:
    """跑 `rel` 那个脚本，从**它自己的输出**里取「一共多少条判据」。

    ⛔ 取不到就返回 None —— 调用方会把它判成红（"算不出真值＝红"，本项目的老规矩）。
    ⚠️ 不另数源码里的 `want(...)`/`c.ok(...)`：那有五六种写法，数错了会得出一个更糟的东西 ——
    一个看起来可信的假数字。
    """
    if rel in cache:
        return cache[rel]
    if Path(rel).name in CANNOT_RUN or "_reverse_verify_" in Path(rel).name:
        # ⛔ 两类脚本不准在这里跑：
        #    ① `_check_all.py` —— 它一次要 1~2 分钟，而它的条数由「检查脚本数」那条判据盯着
        #       （口径本来就在那儿）。实测：第一版没排除它，这条检查直接超时；
        #    ② **反向验证脚本** —— 它们会**注入并改工作区**（这正是 `_check_all.py --deep` 单独一份的原因）。
        #       实测撞过一次：这个检查跑它的时候我又手动跑了一遍，两个注入实验互相踩，
        #       那条脚本当场报「还原后红线没恢复」——检查本身成了事故源。
        #    所以"反向验证有多少条注入"「`_check_all.py` 有多少条」这类数字**给不出真值** ——
        #    按本项目的规矩「算不出真值＝红」（见下面调用方），逼活文档把它改成
        #    「条数以它自己打印的为准」。⛔ 不许在这里悄悄跳过：那等于允许手写一个没人核的数字。
        #    ⚠️ 两条已知盲区（都不许当"已覆盖"）：① 超过 200 字符的超长行整行跳过（定位表那些
        #      几百字一行会顺带提到别的数字）；② 这一族只认「N **条**」，「N **项**」不判
        #      （实测 `docs/CORE_AND_EXTENSION.md` 里「核心冻结（7 项）」早就该是 39 项，没人守）。
        cache[rel] = None
        return None
    path = ROOT / rel
    if not path.exists():
        cache[rel] = None
        return None
    base = [sys.executable, str(path)]
    with_check = base[:]
    try:
        sys.path.insert(0, str(HERE))
        from _check_all import declares_check_flag  # noqa: PLC0415

        if declares_check_flag(path):
            with_check.append("--check")
    except Exception:  # noqa: BLE001 —— 拿不到就按不带参数跑（多数检查的缺省就是"跑一遍"）
        pass
    # ⚠️ 两种调用都要试：`--check` 只打失败（**不打那句总数**），不带参数才会把总结句打全。
    #    第一版只试了 `--check`，于是 `_check_backup.py` 的条数永远"算不出来"。
    order = (INJECTION_PATTERNS + RULE_PATTERNS) if "_reverse_verify_" in rel else (
        RULE_PATTERNS + INJECTION_PATTERNS
    )
    for args in (with_check, base):
        try:
            proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=90, cwd=str(ROOT))
        except subprocess.TimeoutExpired:
            continue
        text = (proc.stdout or "") + (proc.stderr or "")
        for pat in order:
            m = re.search(pat, text)
            if m:
                cache[rel] = int(m.group(1))
                return int(m.group(1))
    cache[rel] = None
    return None


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

    totals_cache: dict[str, int | None] = {}
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

        # ⑥ ⭐ 给 `_check_all.py` 手写的耗时。它自己会打总耗时，活文档里再写一份就是第二份真相 ——
        #    而且那个数**写的时候是真的、之后必然过期**（实测写着「约一分钟」而它当时要 171 秒）。
        durs = [(i, m.group(0).strip()) for i, ln in enumerate(lines, 1) if "_check_all" in ln
                for m in RE_DURATION.finditer(ln)]
        if durs:
            want(False, "", rel + "：给 `_check_all.py` 手写了耗时（"
                 + "、".join("L" + str(i) + "「" + d + "」" for i, d in durs) + "）—— "
                 + "那个数写的时候是真的、之后必然过期（实测「约一分钟」而实际 171 秒）。"
                 + "改成「耗时它自己打在输出里」")
        else:
            want(True, rel + "：没给 `_check_all.py` 手写耗时", "")

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

        # ⑤ 活文档里引用的「某个检查脚本有多少条判据」。
        #    ⚠️ 只在**非表格行**上判：地图的长表格行会顺带提到别的数字（第一版误报过）。
        claimed: dict[str, list[tuple[int, int]]] = {}
        for i, ln in enumerate(lines, 1):
            # ⚠️ 只跳过**超长表格行**（定位表那些几百字的一行会顺带提到别的数字）；
            #    短表格行（如 README 里「| `_check_backup.py` | …（50 条…） |」）要照判 ——
            #    第一版一律跳过含 `|` 的行，于是那处过期数字被放过了。
            if len(ln) > 200:
                continue
            for m in RE_CHECK_COUNT.finditer(ln):
                script = m.group(1) or m.group(4)
                num = m.group(2) or m.group(3)
                # 只认「声明」，两种形状各有各的判法（第一版把两种混着判，误报过一条）：
                #   ① 脚本在前、数字在后（`` `_check_x.py`（55 条） ``）：数字后 4 字内要有「判据/注入」，
                #      或者数字前面紧挨着左括号；
                #   ② 数字在前、脚本在后（`（50 条判据，… `_check_x.py`）`）：**中间那一段必须自己写着
                #      「判据/注入」** —— ⛔ 这一支不许拿"数字前面有没有左括号"当判据：表格行里那对括号
                #      常常属于**上一个格子**。实测 `_tools/backup/README.md` L44
                #      `| `_check_backup.py` | …（54 条，进 `_check_all.py` 自动跑） |` 被错记成
                #      「`_check_all.py` 有 54 条判据」→ 一条假红（那个脚本本来也算不出真值）。
                #   叙事句（「点出 6 条，其中 `_reverse_verify_x.py`…」）两种都不满足 → 跳过。
                if m.group(4):
                    gap = ln[m.end(3): m.start(4)]
                    if "判据" not in gap and "注入" not in gap:
                        continue
                else:
                    tail = ln[m.end(): m.end() + 4]
                    prev = ln[max(0, m.start() - 2): m.start()]
                    if ("判据" not in tail and "注入" not in tail) and not ("（" in prev or "(" in prev):
                        continue
                claimed.setdefault(script, []).append((i, int(num)))
        for script, items in sorted(claimed.items()):
            # 文档里写的是文件名（可能带目录），解析成仓库里的真实路径
            hit = sorted(ROOT.glob("_tools/*/" + Path(script).name))
            real = script_total(str(hit[0].relative_to(ROOT)).replace("\\", "/"), totals_cache) if hit else None
            if real is None:
                if Path(script).name in CANNOT_RUN or "_reverse_verify_" in Path(script).name:
                    # ⛔ 这类脚本**故意不在这里跑**（见 `script_total` 的说明）⇒ 真值拿不到 ⇒ 不许手写。
                    want(False, "", rel + "：" + Path(script).name + " 的条数**不许手写** —— 那个脚本"
                         + "**不会在这里跑**（反向验证会注入并改工作区；`_check_all.py` 是这个检查的宿主），"
                         + "真值拿不到。改成「条数以它自己打印的为准」或干脆删掉那个数字")
                else:
                    want(False, "", rel + "：" + script + " 的判据条数**算不出来**（脚本找不到，或它的输出里没有「一共多少条」）"
                         + " —— 要么把那个数字删掉改成指向脚本，要么给那个脚本补一句总结（算不出真值＝红）")
                continue
            judge(rel + "·" + Path(script).name, "判据条数",
                  [(ln, n, "条判据（" + Path(script).name + "）") for ln, n in items], real,
                  "把它改对（这个数每次加判据都会过期）或删掉、改成指向那个脚本自己")

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
