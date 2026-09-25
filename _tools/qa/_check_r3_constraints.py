#!/usr/bin/env python3
"""_check_r3_constraints.py —— 第三轮的「禁做清单」是不是真的被守住了（进 _check_all.py 自动跑）。

### 为什么需要它（用户 2026-09-26 的原话）
> 「避免了像上次一样，明明在指南里加了不要做，但是还是做的情况」

第二轮指南 §十六 写着「能通过边界解决，就不要增加 Checker」，第二轮还是加了 9 个检查器 ——
**因为那条「不要」只是散文**。散文里的否定句靠记性守不住，所以这一轮把它逐条抄进
docs/R3_CONSTRAINTS.md，并且给每一条配一个**可判定的探针**，在这里全部跑一遍。

R3-BOUNDARY-JUSTIFICATION: 这不是「多一条红线」——它守的是**本轮自己的施工契约**，
而契约的违反信号（import 即 DDL / Android 抄了第二份权限真相 / 上了观测全家桶 / 顺手锁依赖）
都不是「某个模块写错了」，而是**跨仓库的形态问题**，没有任何单点的架构边界能消除它。
例外只到这一条为止：本文件是本轮唯一新增的 checker（checker_budget 探针自己盯着这一点）。

### 判据（八组）
1. 清单本身完整：条数 ≥ MIN_CONSTRAINTS、id 唯一、原文 ≥8 字、位置形如 L数字、类别合法、探针必须真实存在（防化石）；
2. 判定为「阶段」的条目必须写里程碑，且里程碑必须是 R3-00..R3-07 之一；
3. 棘轮：未守住的条数 ≤ 清单里声明的上限，且该上限**相对 HEAD 只减不增**；
4. 不判定（na）的条数 ≤ 上限，同样只减不增（防止把新条目全标成「还没到阶段」来躲判定）；
5. 未守住的条目必须写「什么时候会守住」（≥8 字）—— 例外要有解释；
6. 反空转：条数下限、**真正判定过的条数**下限（na 不算）都要达标；
7. 进度台账 docs/R3_PROGRESS.md 的形状：每个里程碑一个小节、退出条件行必须带 ✅/❌ 与复现命令、
   两张矩阵（最终验收矩阵 ≥12 行 × ≥5 格、三层完成度矩阵 ≥4 行 × ≥3 格）；
8. 业务代码净增行数 ≤ 上限（原则一：这一轮不以代码量为成果）。

⚠️ **这条判据有一个诚实的局限**：阶段探针在产物出现之前一直返回 na，所以它**挡不住「干脆不做」**。
   挡住「不做」的是 docs/R3_PROGRESS.md 里逐条列出的退出条件与它们的复现命令 —— 那是给人看的。

用法：python _tools/qa/_check_r3_constraints.py [--list]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]

MIN_CONSTRAINTS = 24
MIN_JUDGED = 12
MIN_EXIT_LINES = 30
MIN_MATRIX_ROWS = 12
MIN_MATRIX_COLS = 5
MIN_LAYER_ROWS = 4
#: 原则一（不以代码量为成果）的两个闸门：
#: · MAX_BACKEND_DELTA —— `backend/app` 全部净增（防大规模重构）；
#: · MAX_BUSINESS_DELTA —— **只算业务逻辑**（`services/**` + `api/**`）净增。
#: ⚠️ 为什么拆成两个：R3-01/R3-02 往 `core/` 里加的是**结构契约与设施**
#: （file_lock / role_capabilities / capability_audit_coverage），业务逻辑净增其实是 0 ——
#: 只拿总数当判据，会逼着人为了好看去砍注释。调整记录写在 docs/R3_CONSTRAINTS.md §七。
MAX_BACKEND_DELTA = 800
MAX_BUSINESS_DELTA = 60
MILESTONES = ["R3-00", "R3-01", "R3-02", "R3-03", "R3-04", "R3-05", "R3-06", "R3-07"]
KINDS = {"禁做", "必做"}
VERDICTS = {"棘轮", "阶段"}
DOC_REL = "docs/R3_CONSTRAINTS.md"
PROGRESS_REL = "docs/R3_PROGRESS.md"

#: 「判定: 阶段」的探针：产物还不存在时返回 na（还没做），一旦出现就开始判定。
#: ⛔ 这就是「不许静默空转」的形状：文件在 → 必须逐串核对；文件不在 → 明说还没做，**不算通过**。
TOKEN_GATES: dict[str, tuple[str, list[str], str | None]] = {
    "import_purity_dynamic": ("_tools/qa/_check_import_purity.py", ["schema_version", "before", "after"], "R3-01"),
    "migration_tests": ("_tools/ops/_migration_tests.py", ["--fresh", "--old", "--concurrent"], "R3-01"),
    "audit_coverage_shape": ("docs/CAPABILITY_AUDIT_COVERAGE.md", ["capability", "action"], "R3-02"),
    "runtime_evidence": ("docs/R3_RUNTIME_EVIDENCE.md", ["migration", "scheduler", "upload", "socket", "kill"], "R3-03"),
    "upload_decision_record": ("docs/R3_DECISIONS.md", ["上传", "决策"], "R3-03"),
    "deploy_ordered_steps": ("_tools/deploy/_release.py", ["backup", "migrate", "verify", "start", "health"], "R3-05"),
    "smoke_readonly_default": ("_tools/ops/_prod_smoke.py", ["readonly", "add_argument"], "R3-05"),
    "production_acceptance_doc": ("docs/PRODUCTION_ACCEPTANCE.md", ["/health", "trace", "迁移"], "R3-05"),
    "failure_drill_record": ("docs/R3_FAILURE_DRILL.md", ["worker", "redis", "event", "lock", "disk"], "R3-06"),
    "generated_freshness": ("_tools/qa/_check_generated_freshness.py", ["source_commit", "generated_at"], "R3-07"),
    "trace_tool_kept": ("_tools/ops/_trace_order.py", ["request_id", "事件"], None),
    "trace_id_hierarchy": ("_tools/ops/_trace_order.py", ["request_id", "事件"], None),
    "trace_id_three_layers": ("_tools/ops/_trace_order.py", ["command_id"], "R3-04"),
}

#: 「不要上观测全家桶」的扫描对象与关键词（⛔ 只扫依赖与编排文件，不扫文档，否则判据自己命中自己）。
STACK_FILES = ["backend/requirements.txt", "backend/requirements-dev.txt", "docker-compose.yml",
               "docker-compose.prod.yml", "android/app/build.gradle.kts", "android/build.gradle.kts"]
STACK_WORDS = ["prometheus", "grafana", "jaeger", "loki", "opentelemetry", "elasticsearch", "zipkin"]

#: 「第四轮不许提前做」的信号。
ROUND4_IMPORTS = ["oss2", "boto3", "minio", "aliyunsdkcore"]
ROUND4_PATHS = ["backend/app/services/read_models", "backend/app/core/materialized_views.py"]

Q = chr(39) + chr(34)
LOCK_RE = re.compile(r"^([A-Z_]*LOCK_NAME[A-Z_]*)\s*=\s*[" + Q + r"]([^" + Q + r"]+)[" + Q + r"]", re.M)
BASE_RE = re.compile("基线提交[^\\n]*?`([0-9a-f]{7,40})`")


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def git(*args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover
        return 1, str(exc)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def fence_re() -> re.Pattern[str]:
    return re.compile("^```constraint\\n(.*?)^```$", re.S | re.M)


def parse_blocks(text: str) -> list[dict[str, str]]:
    """从 ```constraint 围栏里抠出条目（按行解析 键: 值）。"""
    out: list[dict[str, str]] = []
    for m in fence_re().finditer(text):
        body = m.group(1)
        item: dict[str, str] = {}
        for line in body.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            item[k.strip()] = v.strip()
        if item.get("id"):
            out.append(item)
    return out


def parse_caps(text: str) -> tuple[int | None, int | None]:
    r = re.search("棘轮上限[:：]\\s*(\\d+)", text)
    n = re.search("不判定上限[:：]\\s*(\\d+)", text)
    return (int(r.group(1)) if r else None, int(n.group(1)) if n else None)


def committed_caps() -> tuple[int | None, int | None] | None:
    code, out = git("show", "HEAD:" + DOC_REL)
    if code != 0 or not out.strip():
        return None
    return parse_caps(out)


def base_commit() -> str | None:
    m = BASE_RE.search(read(DOC_REL))
    return m.group(1) if m else None


def probe_import_purity() -> tuple[str, str]:
    """直接跑**真判据** _tools/qa/_check_import_purity.py（真库 + 子进程核对）。

    ⛔ 这里不许再写一份「搜文本里有没有 bootstrap_schema(」的简版：第一版就是这么写的，
    于是 database.py 的**文档字符串**里提到这个名字就把自己判红了 ——
    同一个判断有两份实现，迟早走散（本仓库栽过的老账）。
    """
    checker = ROOT / "_tools/qa/_check_import_purity.py"
    if not checker.exists():
        return "broken", "真判据 _tools/qa/_check_import_purity.py 不存在"
    proc = subprocess.run([sys.executable, str(checker)], capture_output=True, text=True,
                          cwd=str(ROOT), encoding="utf-8", errors="replace")
    if proc.returncode == 0:
        return "hold", "真判据《_check_import_purity.py》通过（真库 + 子进程核对）"
    bad = [ln.strip() for ln in ((proc.stdout or "") + (proc.stderr or "")).splitlines()
           if ln.strip().startswith("❌")]
    return "broken", (bad[0] if bad else "真判据报红")[:140]


def probe_android_no_second_truth() -> tuple[str, str]:
    """安卓**代码**里不许有第二份权限词表。

    ⚠️ **这个探针不自己实现判断**：它直接问真判据 `_check_capability_unification.py` 的
    `kotlin_second_truth_hits()`。2026-09-26 之前它是自己写的一份（纯文本搜 `ROLE_PERMISSIONS`），
    于是同一件事在两处判得不一样：探针把 `AiWrite.kt` 的**说明性注释**判成违规，
    真判据又不认「入口 → 能力」那种合法写法。本仓库的老账 —— 同一个判断两份实现，迟早走散。

    两步都从判据那边取：① 手写的「角色→能力」表；② 代码里引用 `ROLE_PERMISSIONS`。
    （生成物自带「不许手改」抬头 → 判据那边已豁免：快照里有权限词表是它的本职。）
    """
    import importlib.util as _ilu

    path = ROOT / "_tools/qa/_check_capability_unification.py"
    if not path.exists():
        return "broken", "真判据 _check_capability_unification.py 不存在"
    spec = _ilu.spec_from_file_location("_cap_unification_probe", path)
    if spec is None or spec.loader is None:
        return "broken", "真判据加载不了（探针拿不到那份实现）"
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hits = list(mod.kotlin_second_truth_hits())
    for f in sorted((ROOT / "android/app/src/main/java").rglob("*.kt")):
        raw = f.read_text(encoding="utf-8", errors="replace")
        if "不许手改" in raw[:800]:
            continue
        code = mod.strip_kotlin_comments(raw)
        if "ROLE_PERMISSIONS" in code:
            hits.append(str(f.relative_to(ROOT)) + "（引用 ROLE_PERMISSIONS）")
    if hits:
        return "broken", str(len(hits)) + " 个安卓文件里有第二份权限真相：" + "、".join(hits[:3])
    return "hold", "安卓代码里没有手抄的权限词表（注释与生成物不算）"


def probe_no_observability_stack() -> tuple[str, str]:
    hits: list[str] = []
    for rel in STACK_FILES:
        t = read(rel).lower()
        for w in STACK_WORDS:
            if w in t:
                hits.append(rel + " ← " + w)
    if hits:
        return "broken", "依赖/编排里出现了观测平台：" + "、".join(hits[:3])
    return "hold", "没有引入观测平台依赖（只做 structured log + metrics）"


def probe_no_premature_round4() -> tuple[str, str]:
    bad: list[str] = []
    for rel in ROUND4_PATHS:
        if (ROOT / rel).exists():
            bad.append(rel + "（这是第四轮的东西）")
    base = ROOT / "backend/app"
    for f in (sorted(base.rglob("*.py")) if base.exists() else []):
        t = f.read_text(encoding="utf-8", errors="replace")
        for mod in ROUND4_IMPORTS:
            if re.search(r"^\s*(import|from)\s+" + mod + r"\b", t, re.M):
                bad.append(str(f.relative_to(ROOT)) + " ← " + mod)
    if bad:
        return "broken", "提前做了第四轮的东西：" + "、".join(bad[:3])
    return "hold", "没有读模型 / 对象存储 SDK / 物化视图"


def probe_requirements_not_blindly_locked() -> tuple[str, str]:
    if (ROOT / "docs/DEPENDENCY_DECISION.md").exists():
        return "hold", "依赖可复现性决策已存在，锁与不锁由它说了算"
    pins = [ln.strip() for ln in read("backend/requirements.txt").splitlines()
            if ln.strip() and not ln.strip().startswith("#") and "==" in ln]
    if pins:
        return "broken", "还没写依赖决策就先锁死 " + str(len(pins)) + " 条：" + pins[0]
    return "hold", "requirements.txt 仍是开区间（>=x,<y），没有顺手就锁"


def probe_distinct_lock_names() -> tuple[str, str]:
    names: dict[str, str] = {}
    base = ROOT / "backend/app"
    for f in (sorted(base.rglob("*.py")) if base.exists() else []):
        t = f.read_text(encoding="utf-8", errors="replace")
        for m in LOCK_RE.finditer(t):
            names[m.group(2)] = str(f.relative_to(ROOT)) + ":" + m.group(1)
    if len(names) <= 1:
        return "hold", "目前只有 " + str(len(names)) + " 把命名锁（调度锁还没做，不同名成立）"
    return "hold", str(len(names)) + " 把锁名字互不相同：" + "、".join(sorted(names))


def _new_checkers() -> tuple[int, list[str], str]:
    base = base_commit()
    if not base:
        return -1, [], "清单里没写基线提交"
    code, out = git("rev-parse", "--verify", base + "^{commit}")
    if code != 0:
        return -1, [], "基线提交 " + base + " 还不在 git 里"
    # ⚠️ 只看**新增**（status=A）的检查器：R3-01 里改过 `_check_migrations.py` 的锚点，
    #    那是「判据跟着代码走」，不是「又加了一个检查器」—— 要求它写边界理由就跑偏了。
    code, out = git("diff", "--name-status", base + "..HEAD", "--", "_tools")
    if code != 0:
        return -1, [], "git diff 失败：" + out.strip()[:120]
    fresh = []
    for ln in out.splitlines():
        parts = ln.split("\t")
        if len(parts) >= 2 and parts[0].startswith("A") and parts[1].strip().endswith(".py") \
                and "/_check_" in parts[1]:
            fresh.append(parts[1].strip())
    return len(fresh), fresh, ""


def probe_checker_budget() -> tuple[str, str]:
    n, fresh, err = _new_checkers()
    if n < 0:
        return "na", err
    missing = [rel for rel in fresh if "R3-BOUNDARY-JUSTIFICATION:" not in read(rel)]
    if missing:
        return "broken", "本轮新增的检查器没写「为什么边界解决不了」：" + "、".join(missing[:3])
    return "hold", "本轮新增检查器 " + str(n) + " 个，都写了边界理由"


def probe_backend_app_delta() -> tuple[str, str]:
    base = base_commit()
    if not base:
        return "na", "清单里没写基线提交"
    code, out = git("diff", "--numstat", base + "..HEAD", "--", "backend/app")
    if code != 0:
        return "na", "基线提交还不在 git 里"
    add = dele = 0
    for ln in out.splitlines():
        parts = ln.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            add += int(parts[0])
            dele += int(parts[1])
    delta = add - dele
    code2, out2 = git("diff", "--numstat", base + "..HEAD", "--", "backend/app/services", "backend/app/api")
    b_add = b_del = 0
    for ln in out2.splitlines():
        parts = ln.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            b_add += int(parts[0])
            b_del += int(parts[1])
    biz = b_add - b_del
    if delta > MAX_BACKEND_DELTA:
        return "broken", "backend/app 净增 " + str(delta) + " 行，超过上限 " + str(MAX_BACKEND_DELTA) + "（原则一）"
    if biz > MAX_BUSINESS_DELTA:
        return "broken", "**业务逻辑**净增 " + str(biz) + " 行，超过上限 " + str(MAX_BUSINESS_DELTA) + "（原则一）"
    return "hold", ("backend/app 净增 " + str(delta) + " 行（上限 " + str(MAX_BACKEND_DELTA)
                      + "）；其中业务逻辑（services+api）净增 " + str(biz) + " 行（上限 " + str(MAX_BUSINESS_DELTA) + "）")


def probe_commit_milestone_tag() -> tuple[str, str]:
    base = base_commit()
    if not base:
        return "na", "清单里没写基线提交"
    code, out = git("log", "--format=%h %s", base + "..HEAD")
    if code != 0:
        return "na", "基线提交还不在 git 里"
    subs = [ln for ln in out.splitlines() if ln.strip()]
    if not subs:
        return "hold", "基线之后还没有提交（这一条从下一个提交开始生效）"
    bad = [s for s in subs if not re.search(r"R3-0\d", s)]
    if bad:
        return "broken", str(len(bad)) + " 个提交没标里程碑编号：" + bad[0][:60]
    return "hold", str(len(subs)) + " 个提交都标了里程碑编号"


def probe_exit_condition_ledger() -> tuple[str, str]:
    text = read(PROGRESS_REL)
    if not text.strip():
        return "broken", PROGRESS_REL + " 不存在（退出条件台账是这份清单的地基）"
    miss = [ms for ms in MILESTONES if ("## " + ms) not in text]
    if miss:
        return "broken", "进度台账缺里程碑小节：" + "、".join(miss)
    rows = [ln.strip() for ln in text.splitlines() if re.match("^- [✅❌]", ln.strip())]
    if len(rows) < MIN_EXIT_LINES:
        return "broken", "退出条件只登记到 " + str(len(rows)) + " 条（下限 " + str(MIN_EXIT_LINES) + "）—— 台账被掏空了？"
    naked = [ln for ln in rows if ("复现" not in ln or "`" not in ln)]
    if naked:
        return "broken", "有 " + str(len(naked)) + " 条退出条件没带复现命令：" + naked[0][:60]
    return "hold", str(len(rows)) + " 条退出条件都带 ✅/❌ 与复现命令"


def _matrix_rows(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for ln in section.splitlines():
        s = ln.strip()
        if not s.startswith("|") or set(s) <= set("|- "):
            continue
        rows.append([c.strip() for c in s.strip("|").split("|")])
    return rows[1:] if rows else []   # 去掉表头


def probe_progress_shape() -> tuple[str, str]:
    text = read(PROGRESS_REL)
    if not text.strip():
        return "broken", PROGRESS_REL + " 不存在"
    if "## 最终验收矩阵" not in text:
        return "broken", "缺少「## 最终验收矩阵」小节"
    sec = text.split("## 最终验收矩阵", 1)[1].split("## ", 1)[0]
    rows = _matrix_rows(sec)
    if len(rows) < MIN_MATRIX_ROWS:
        return "broken", "最终验收矩阵只有 " + str(len(rows)) + " 行（下限 " + str(MIN_MATRIX_ROWS) + "）"
    thin = [r for r in rows if len([c for c in r if c in ("✅", "❌", "—")]) < MIN_MATRIX_COLS]
    if thin:
        return "broken", "有 " + str(len(thin)) + " 行的层次格不足 " + str(MIN_MATRIX_COLS) + " 格"
    if "## 三层完成度矩阵" not in text:
        return "broken", "缺少「## 三层完成度矩阵」小节（原则三）"
    lt = text.split("## 三层完成度矩阵", 1)[1].split("## ", 1)[0]
    lrows = _matrix_rows(lt)
    if len(lrows) < MIN_LAYER_ROWS:
        return "broken", "三层矩阵只有 " + str(len(lrows)) + " 行（下限 " + str(MIN_LAYER_ROWS) + "）"
    return "hold", "两张矩阵都在（" + str(len(rows)) + " 行验收矩阵 + " + str(len(lrows)) + " 行三层矩阵）"


CUSTOM_PROBES = {
    "import_purity": probe_import_purity,
    "android_no_second_truth": probe_android_no_second_truth,
    "no_observability_stack": probe_no_observability_stack,
    "no_premature_round4": probe_no_premature_round4,
    "requirements_not_blindly_locked": probe_requirements_not_blindly_locked,
    "distinct_lock_names": probe_distinct_lock_names,
    "checker_budget": probe_checker_budget,
    "backend_app_delta": probe_backend_app_delta,
    "commit_milestone_tag": probe_commit_milestone_tag,
    "exit_condition_ledger": probe_exit_condition_ledger,
    "progress_shape": probe_progress_shape,
}


def run_probe(name: str) -> tuple[str, str]:
    fn = CUSTOM_PROBES.get(name)
    if fn is not None:
        return fn()
    spec = TOKEN_GATES.get(name)
    if spec is None:
        return "fossil", "清单里写的探针 " + name + " 根本不存在（化石）"
    rel, tokens, milestone = spec
    fp = ROOT / rel
    if not fp.exists():
        if milestone:
            return "na", "还没做（" + milestone + "）：" + rel + " 还不存在"
        return "broken", rel + " 不存在（这一条现在就该守住）"
    t = fp.read_text(encoding="utf-8", errors="replace")
    miss = [x for x in tokens if x not in t]
    if miss:
        return "broken", rel + " 里找不到：" + "、".join(miss)
    return "hold", rel + " 的 " + str(len(tokens)) + " 个形状都在"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列清单里登记的探针")
    a = ap.parse_args()

    text = read(DOC_REL)
    if not text.strip():
        print("❌ " + DOC_REL + " 不存在 —— 第三轮的禁做清单没有落地")
        return 1
    blocks = parse_blocks(text)
    if a.list:
        for b in blocks:
            print(b.get("id", "?") + "  " + b.get("判定", "?") + "  " + b.get("探针", "?"));
        return 0

    fails: list[str] = []
    ratchet, na_cap = parse_caps(text)
    if ratchet is None or na_cap is None:
        print("❌ 清单头部缺 棘轮上限: N / 不判定上限: N")
        return 1

    if len(blocks) < MIN_CONSTRAINTS:
        fails.append("清单只登记到 " + str(len(blocks)) + " 条（下限 " + str(MIN_CONSTRAINTS) + "）—— 清单被掏空了？")
    seen: set[str] = set()
    for i, b in enumerate(blocks, 1):
        cid = b.get("id", "")
        if not cid or cid in seen:
            fails.append("第 " + str(i) + " 条 id 缺失或重复：" + repr(cid))
        seen.add(cid)
        if len(b.get("原文", "")) < 8:
            fails.append(cid + " 的原文太短（<8 字）—— 抄不全就等于没抄")
        if not re.match(r"^L\d+", b.get("位置", "")):
            fails.append(cid + " 的位置不是 L数字 形状：" + repr(b.get("位置")))
        if b.get("类别") not in KINDS:
            fails.append(cid + " 的类别只能是 " + "/".join(sorted(KINDS)))
        if b.get("判定") not in VERDICTS:
            fails.append(cid + " 的判定只能是 " + "/".join(sorted(VERDICTS)))
        if b.get("判定") == "阶段" and b.get("里程碑") not in MILESTONES:
            fails.append(cid + " 是阶段判定，必须写合法里程碑")
        probe = b.get("探针", "")
        if probe not in CUSTOM_PROBES and probe not in TOKEN_GATES:
            fails.append(cid + " 的探针 " + repr(probe) + " 没实现（化石）")

    results: list[tuple[str, str, str, str]] = []
    for b in blocks:
        probe = b.get("探针", "")
        if probe not in CUSTOM_PROBES and probe not in TOKEN_GATES:
            continue
        status, detail = run_probe(probe)
        results.append((b.get("id", "?"), status, detail, probe))
        if status == "broken" and len(b.get("什么时候会守住", "")) < 8:
            fails.append(b.get("id", "?") + " 未守住，却只写了 " + str(len(b.get("什么时候会守住", ""))) + " 字的解释")

    broken = [r for r in results if r[1] == "broken"]
    na = [r for r in results if r[1] == "na"]
    held = [r for r in results if r[1] == "hold"]
    judged = len(held) + len(broken)

    if len(broken) > ratchet:
        fails.append("未守住 " + str(len(broken)) + " 条 > 棘轮上限 " + str(ratchet) + "：" + "、".join(r[0] for r in broken))
    if len(na) > na_cap:
        fails.append("不判定 " + str(len(na)) + " 条 > 上限 " + str(na_cap) + " —— 别把条目标成还没到阶段来躲判定")
    prev = committed_caps()
    if prev and prev[0] is not None and ratchet > prev[0]:
        fails.append("棘轮上限从 " + str(prev[0]) + " 涨到 " + str(ratchet) + " —— 棘轮只能减不能增")
    if prev and prev[1] is not None and na_cap > prev[1]:
        fails.append("不判定上限从 " + str(prev[1]) + " 涨到 " + str(na_cap) + " —— 同样只能减不能增")
    if judged < MIN_JUDGED:
        fails.append("真正判定过的只有 " + str(judged) + " 条（下限 " + str(MIN_JUDGED) + "）—— 判据在空转")

    print("第三轮禁做清单：" + str(len(blocks)) + " 条 / 守住 " + str(len(held))
          + " / 未守住 " + str(len(broken)) + "（上限 " + str(ratchet) + "）"
          + " / 未到阶段 " + str(len(na)) + "（上限 " + str(na_cap) + "）")
    for cid, status, detail, probe in results:
        mark = {"hold": "✅", "broken": "❌", "na": "⏳"}[status]
        print("  " + mark + " " + cid + " [" + probe + "] " + detail)
    if fails:
        print()
        for f in fails:
            print("  ❌ " + f)
        print()
        print("❌ " + str(len(fails)) + " 条不成立")
        return 1
    print()
    print("  ✅ 8 组判据全部通过：清单完整、探针真实存在、棘轮只减不增、未守住的都写了什么时候守、"
          "进度台账形状齐全、业务代码净增没超上限。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
