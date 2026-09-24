#!/usr/bin/env python3
"""_capture_baseline.py —— 采集「真实世界基线」（整改阶段 0）。

### 为什么要有它
报告 §2 的第一条建议就是："第一件应该做的事情"是**先建立真实世界基线** ——
报告里 10 个信息缺口，一半是"生产上到底是什么"，一半是"这些检查/用例现在是不是真的全绿"。
不先把这些数钉住，后面每一轮重构都**没有"改之前是多少"的对照物**：
重构完只能靠"我看代码差不多"判断，而报告 §18 规则 3 明确否掉了这种判断方式。

### 三条口径（都是本项目已经栽过的坑）
1. **数字一律算出来，不手写**（本项目已栽 5 次"手写清单过期"）：端点从
   `backend/scripts/gen_endpoint_index.py` 现算、表数从模型源码数、用例数从 pytest 与
   安卓测试报告读、检查数从 `_check_all.py --list` 读。
2. **文档与代码不一致要看得见**：报告说"版本号统一"，而版本号其实有**四处**
   （`VERSION` / `backend` / `frontend/package.json` / `android versionName`）——
   基线把它们并排列出来，漂移一眼可见（实测：生产 `/health` 报 0.2.0 而仓库是 0.2.4）。
3. **`before/` 快照不可覆盖**：每次采集落到 `_tools/baseline/before/<日期>/baseline.json`，
   已存在就报错（要重采请显式 `--force`）——否则"改造前的样子"会被后来的数据悄悄覆盖，
   而那正是它唯一的价值。

### 用法
    python _tools/baseline/_capture_baseline.py              # 本地事实（不联网、不碰生产）
    python _tools/baseline/_capture_baseline.py --tests      # 顺带采后端/安卓用例数（慢约 1 分钟）
    python _tools/baseline/_capture_baseline.py --prod       # 额外走 ssh 采生产只读事实
    python _tools/baseline/_capture_baseline.py --out docs/BASELINE.md   # 渲染成文档
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools" / "ops"))

import _prodssh  # noqa: E402  （唯一一处写生产主机/密钥/路径——见该文件开头）


#: 报告成文时的数字。**来源是存档的原文**（docs/ARCHITECTURE_RECTIFICATION.md 的行号写在注释里），
#: 不是"现在的真值"——它这一列存在的意义就是让漂移可见（报告 §13 的要求）。
REPORT_CLAIMS: dict[str, tuple[str, str]] = {
    "报告原文": ("docs/ARCHITECTURE_RECTIFICATION.md", "sha256 1838dd55…"),
    "端点数": ("227", "L57 / L940"),
    "数据库表数": ("45", "L57"),
    "service 文件数": ("41", "L57"),
    "api/v1 行数": ("13724", "L395"),
    "services 行数": ("9837", "L396"),
    "orders.py 行数": ("2055", "L402"),
    "schema_bootstrap.py 行数": ("1697", "L142 / L234"),
    "静态检查数": ("92", "L332 / L1454"),
    "反向验证数": ("108", "L332 / L1454"),
    "后端用例数": ("820", "L334 / L983"),
    "安卓用例数": ("1126", "L335 / L985（源码 @Test 注解口径）"),
    "docs 文件数": ("502", "L915"),
    "_tools Python 文件数": ("325", "L1454"),
    "权限点数": ("26", "L658"),
}


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, timeout=timeout)


def text_of(cp: subprocess.CompletedProcess) -> str:
    return cp.stdout.decode("utf-8", "replace") + cp.stderr.decode("utf-8", "replace")


def git(*args: str) -> str:
    return text_of(run(["git", *args])).strip()


def lines_of(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def py_lines(folder: Path) -> int:
    return sum(lines_of(p) for p in folder.glob("*.py"))


# ---------------------------------------------------------------- 本地事实
def collect_local(notes: list[str], *, with_tests: bool) -> dict:
    f: dict = {}

    # --- git ---
    f["git_commit"] = git("rev-parse", "HEAD")
    f["git_branch"] = git("branch", "--show-current")
    dirty = [ln for ln in git("status", "--short").splitlines() if ln.strip()]
    f["git_dirty"] = dirty
    try:
        lr = git("rev-list", "--left-right", "--count", "HEAD...@{u}").split()
        f["git_ahead"], f["git_behind"] = int(lr[0]), int(lr[1])
    except (ValueError, IndexError):
        f["git_ahead"] = f["git_behind"] = None
        notes.append("git 上游分支不可用（@{u} 解析失败）—— ahead/behind 记为 None")
    f["git_last_commit_date"] = git("log", "-1", "--format=%cI")

    # --- 版本号：四处（报告 §2 的"版本号统一"就是这一条） ---
    f["version_file"] = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    try:
        pkg = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
        f["version_frontend"] = pkg.get("version")
    except OSError:
        f["version_frontend"] = None
    # ⚠️ 安卓的 versionName **不是字面量**：2026-09-21 起它构建时读仓库根 VERSION
    #    （android/app/build.gradle.kts:25 rootProject.file("../VERSION")）。所以这里记的是"它取哪个源"，
    #    而不是一个字符串——否则基线会永远显示 _未采集_，把"已经统一了"误报成"没采到"。
    gradle = ROOT / "android" / "app" / "build.gradle.kts"
    gsrc = gradle.read_text(encoding="utf-8", errors="replace") if gradle.exists() else ""
    f["version_android"] = (f"{f['version_file']}（构建时读 VERSION 文件）"
                            if 'rootProject.file("../VERSION")' in gsrc else None)
    # 后端的版本号是**硬编码**在 config.py 里的（实测 0.2.0）—— 这就是报告 §20 要的"版本号统一"缺口。
    cfg = ROOT / "backend" / "app" / "config.py"
    m2 = re.search(r'app_version\s*:\s*str\s*=\s*"([^"]+)"',
                   cfg.read_text(encoding="utf-8", errors="replace")) if cfg.exists() else None
    f["version_backend_declared"] = m2.group(1) if m2 else None

    # --- 端点：现算（不读手写文档） ---
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "ep.md"
        cp = run([sys.executable, "-m", "scripts.gen_endpoint_index", "--out", str(out)],
                 cwd=ROOT / "backend")
        if out.exists():
            rows = [ln for ln in out.read_text(encoding="utf-8").splitlines()
                    if re.match(r"^\| \d+ \| `(GET|POST|PUT|PATCH|DELETE) ", ln)]
            f["endpoints_total"] = len(rows)
            f["endpoints_write"] = len([ln for ln in rows if not re.match(r"^\| \d+ \| `GET ", ln)])
        else:
            f["endpoints_total"] = f["endpoints_write"] = None
            notes.append(f"端点索引生成失败：{text_of(cp)[-300:]}")

    # --- 表 / 代码体量 ---
    models = list((ROOT / "backend" / "app" / "models").glob("*.py"))
    tables: set[str] = set()
    for p in models:
        tables |= set(re.findall(r'__tablename__\s*=\s*"([^"]+)"', p.read_text(encoding="utf-8", errors="replace")))
    f["model_tables"] = sorted(tables)
    f["model_table_count"] = len(tables)
    f["api_v1_lines"] = py_lines(ROOT / "backend" / "app" / "api" / "v1")
    f["services_lines"] = py_lines(ROOT / "backend" / "app" / "services")
    f["services_files"] = len(list((ROOT / "backend" / "app" / "services").glob("*.py")))
    f["schema_bootstrap_lines"] = lines_of(ROOT / "backend" / "app" / "core" / "schema_bootstrap.py")
    f["orders_py_lines"] = lines_of(ROOT / "backend" / "app" / "api" / "v1" / "orders.py")
    f["docs_files"] = sum(1 for p in (ROOT / "docs").rglob("*") if p.is_file())
    f["tools_py_files"] = len(list((ROOT / "_tools").rglob("*.py")))

    # --- 检查 / 反向验证（清单自己算） ---
    cp = run([sys.executable, str(ROOT / "_tools" / "qa" / "_check_all.py"), "--list"], timeout=300)
    m = re.search(r"共 (\d+) 个检查脚本", text_of(cp))
    f["static_checks"] = int(m.group(1)) if m else None
    if not m:
        notes.append("静态检查数没解析出来（_check_all.py --list 的输出格式变了？）")
    cp = run([sys.executable, str(ROOT / "_tools" / "ai" / "_reverse_verify_all.py"), "--list"], timeout=300)
    f["reverse_verify_scripts"] = len([ln for ln in text_of(cp).splitlines()
                                       if ln.strip().endswith(".py") and "reverse_verify" in ln])

    # --- 安卓用例（从最近一次测试报告读，不重新跑 Gradle） ---
    total = fails = 0
    results = list((ROOT / "android" / "app" / "build" / "test-results").glob("*/TEST-*.xml"))
    for p in results:
        head = p.read_text(encoding="utf-8", errors="replace")[:2000]
        mt = re.search(r'tests="(\d+)"', head)
        mf = re.search(r'failures="(\d+)"', head)
        total += int(mt.group(1)) if mt else 0
        fails += int(mf.group(1)) if mf else 0
    # ⚠️ 两个口径都要，因为它们是**不同的事实**：
    #    · android_tests_declared = 源码里 @Test 注解数（1126）—— 静态、稳定、与"跑没跑"无关；
    #    · android_tests_last_run = 最近一次测试报告的用例数（308）—— 只覆盖跑过的那些 variant，
    #      拿它当"总用例数"会得出"少了 818 个"的假漂移（报告那份数字用的就是注解口径）。
    f["android_tests_last_run"] = total if results else None
    f["android_test_failures"] = fails if results else None
    f["android_test_report_files"] = len(results)
    declared = 0
    for src in (ROOT / "android" / "app" / "src").rglob("*.kt"):
        declared += len(re.findall(r"@Test", src.read_text(encoding="utf-8", errors="replace")))
    f["android_tests_declared"] = declared
    f["android_main_kt"] = len(list((ROOT / "android" / "app" / "src" / "main").rglob("*.kt")))

    # --- 后端用例（可选：要跑 collect，约 30 秒） ---
    if with_tests:
        cp = run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                 cwd=ROOT / "backend", timeout=900)
        m = re.search(r"(\d+) tests? collected", text_of(cp))
        f["backend_tests"] = int(m.group(1)) if m else None
        if not m:
            notes.append("后端用例数没解析出来（pytest --collect-only 失败？）")
    else:
        f["backend_tests"] = None

    f["largest_android_files"] = top_files(ROOT / "android", "*.kt", skip="build", n=8)
    f["largest_backend_files"] = top_files(ROOT / "backend" / "app", "*.py", skip=None, n=8)
    return f


def top_files(base: Path, pattern: str, *, skip: str | None, n: int) -> list[list]:
    items = []
    for p in base.rglob(pattern):
        if skip and f"{os.sep}{skip}{os.sep}" in str(p):
            continue
        items.append([lines_of(p), str(p.relative_to(ROOT)).replace("\\", "/")])
    items.sort(reverse=True)
    return items[:n]


# ---------------------------------------------------------------- 生产事实（只读）
def collect_prod(notes: list[str]) -> dict:
    """走 ssh 采生产只读事实。任何一步失败都记进 notes —— **不许静默跳过**。"""
    out: dict = {}
    try:
        cp = _prodssh.ssh_script(_prodssh.prod_facts_script(), timeout=180)
    except Exception as e:                                      # noqa: BLE001
        notes.append(f"生产事实采集失败（整段）：{e}")
        return {"_error": str(e)[:500]}
    for ln in cp.stdout.decode("utf-8", "replace").splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip()
    f = out.get("db_tables_list", "")
    out["db_tables_set"] = sorted(x for x in f.split(",") if x)
    return out


# ---------------------------------------------------------------- 风险判定（基线的价值在这一段）
def assess(local: dict, prod: dict | None, notes: list[str]) -> list[dict]:
    """机器判定的漂移/风险清单。**只报事实与差额，不给"应该改成多少"的结论**。"""
    risks: list[dict] = []

    def add(kind: str, what: str, detail: str) -> None:
        risks.append({"kind": kind, "what": what, "detail": detail})

    versions = {
        "VERSION": local.get("version_file"),
        "frontend/package.json": local.get("version_frontend"),
        "android versionName": local.get("version_android"),
        "backend main.py": local.get("version_backend_declared"),
    }
    if prod and prod.get("api_health_body"):
        m = re.search(r'"version"\s*:\s*"([^"]+)"', prod["api_health_body"])
        if m:
            versions["生产 /health"] = m.group(1)
    uniq = {v for v in versions.values() if v}
    if len(uniq) > 1:
        add("版本漂移", "版本号多处不一致",
            " ｜ ".join(f"{k}={v}" for k, v in versions.items()))

    if prod:
        mt = set(local.get("model_tables") or [])
        pt = set(prod.get("db_tables_set") or [])
        if mt and pt and mt != pt:
            add("结构漂移", "模型声明的表与生产库的表不一致",
                f"只在模型里：{sorted(mt - pt)} ｜ 只在生产库里：{sorted(pt - mt)}")
        try:
            days = int(prod.get("cert_sorders.top_days_left") or prod.get("cert_sorders.top-0001_days_left") or 999)
            if days < 30:
                add("证书", "域名证书剩余天数 < 30（或已过期）",
                    f"days_left={days}（end={prod.get('cert_sorders.top_end')}）")
        except ValueError:
            pass
        if prod.get("backup_db_count") == "0":
            add("备份", "生产机上没有任何脚本化备份产物",
            "备份根目录下 .sql.gz 计数 = 0 —— 这轮整改阶段 1 就是要消掉它")
        if prod.get("api_paths") and local.get("endpoints_total"):
            try:
                if int(prod["api_paths"]) != int(local["endpoints_total"]):
                    add("代码漂移", "生产在跑的代码与本地工作区不是同一份",
                        f"生产 openapi paths={prod['api_paths']}，本地端点={local['endpoints_total']}；"
                        f"生产 commit={prod.get('repo_commit','')[:8]}，本地 commit={local.get('git_commit','')[:8]}")
            except ValueError:
                pass

    if local.get("android_test_failures"):
        add("测试", "最近一次安卓单测报告里有失败", f"failures={local['android_test_failures']}")
    if local.get("git_dirty"):
        add("工作区", "工作区有未提交改动（结构性改造前必须先确认归属）",
            " ；".join(local["git_dirty"][:10]))
    if local.get("backend_tests") is None and not any("后端用例数" in n for n in notes):
        add("口径", "这次没采后端用例数（没加 --tests）", "后端用例数记 None，不要拿 None 当 0")
    return risks


# ---------------------------------------------------------------- 渲染
def render_md(local: dict, prod: dict | None, risks: list[dict], *, snapshot: Path, notes: list[str]) -> str:
    o: list[str] = []
    o.append("# 真实世界基线（BASELINE）\n")
    o.append("> **本文件由 `_tools/baseline/_capture_baseline.py` 生成，不要手改**（报告 §13：会变化的数字一律不手写）。\n"
             "> 重新采：`python _tools/baseline/_capture_baseline.py --tests --prod --out docs/BASELINE.md`\n")
    o.append(f"> 本次采集时间：{local.get('captured_at', '')}　｜　快照：`{snapshot.relative_to(ROOT).as_posix()}`\n")
    o.append("> 说明：这一页回答的是「现在到底是什么样」，不回答「应该改成什么样」——"
             "后者在 [RECTIFICATION_PLAN.md](RECTIFICATION_PLAN.md)。\n")

    o.append("\n## 1. 与报告成文时的对照（漂移一眼可见）\n")
    o.append("| 项 | 报告成文时 | 本次实测 | 差额 | 来源 |")
    o.append("|---|---:|---:|---:|---|")
    pairs = [
        ("端点数", "endpoints_total"), ("数据库表数（模型）", "model_table_count"),
        ("service 文件数", "services_files"), ("api/v1 行数", "api_v1_lines"),
        ("services 行数", "services_lines"), ("orders.py 行数", "orders_py_lines"),
        ("schema_bootstrap.py 行数", "schema_bootstrap_lines"), ("静态检查数", "static_checks"),
        ("反向验证数", "reverse_verify_scripts"), ("后端用例数", "backend_tests"),
        ("安卓用例数", "android_tests_declared"), ("docs 文件数", "docs_files"),
        ("_tools Python 文件数", "tools_py_files"),
    ]
    for label, key in pairs:
        claim = REPORT_CLAIMS.get(label)
        was, src = (claim if claim else (None, "—"))
        now = local.get(key)
        delta = "—"
        if was and now is not None:
            try:
                d = int(now) - int(was)
                delta = f"{d:+d}" if d else "0"
            except ValueError:
                delta = "—"
        o.append(f"| {label} | {was if was else '—'} | {now if now is not None else '_未采集_'} | {delta} | {src} |")
    o.append("\n> 报告的数字**不是错误**，它记录的是报告成文那一刻的快照；"
             "这一列留着的目的是让「文档写着 92 个检查、实际 92 个」这种话**有机器可核的依据**。\n")

    o.append("\n## 2. 本地基线\n")
    o.append("| 项 | 值 |")
    o.append("|---|---|")
    rows = [
        ("分支", "git_branch"), ("提交", "git_commit"), ("最后提交时间", "git_last_commit_date"),
        ("领先上游", "git_ahead"), ("落后上游", "git_behind"),
        ("版本号 VERSION", "version_file"), ("版本号 frontend", "version_frontend"),
        ("版本号 android", "version_android"), ("版本号 backend(main.py)", "version_backend_declared"),
        ("端点数（含写）", "endpoints_total"), ("其中写端点", "endpoints_write"),
        ("模型声明表数", "model_table_count"), ("api/v1 总行数", "api_v1_lines"),
        ("services 总行数", "services_lines"), ("静态检查数", "static_checks"),
        ("反向验证脚本数", "reverse_verify_scripts"), ("后端用例数", "backend_tests"),
        ("安卓用例数（源码 @Test 注解）", "android_tests_declared"),
        ("安卓最近一次跑到的用例数", "android_tests_last_run"),
        ("安卓用例失败数（最近一次）", "android_test_failures"),
        ("安卓主源码 .kt 数", "android_main_kt"),
    ]
    for label, key in rows:
        o.append(f"| {label} | {local.get(key) if local.get(key) is not None else '_未采集_'} |")

    o.append("\n### 最大的安卓源文件（报告 §11 点名的「大文件」）\n")
    o.append("| 行数 | 文件 |")
    o.append("|---:|---|")
    for n, p in local.get("largest_android_files", []):
        o.append(f"| {n} | `{p}` |")
    o.append("\n### 最大的后端文件\n")
    o.append("| 行数 | 文件 |")
    o.append("|---:|---|")
    for n, p in local.get("largest_backend_files", []):
        o.append(f"| {n} | `{p}` |")

    if prod:
        o.append("\n## 3. 生产基线（只读采集）\n")
        o.append("| 项 | 值 |")
        o.append("|---|---|")
        for k in ("host", "date", "os", "kernel", "cpu", "mem_mb", "uptime_days",
                  "service_state", "service_since", "service_restarts", "service_hash",
                  "api_health", "api_health_body", "api_paths",
                  "mysql_version", "db_tables", "db_size_mb", "db_orders", "db_ledgers",
                  "db_users", "db_products", "redis_version", "redis_maxmemory", "redis_requirepass_len",
                  "nginx_version", "nginx_config_hash",
                  "cert_sorders-ip-chain_end", "cert_sorders-ip-chain_days_left",
                  "cert_sorders.top_end", "cert_sorders.top_days_left",
                  "disk_total", "disk_used", "disk_avail", "disk_pct",
                  "uploads_size", "uploads_files", "backup_root_size", "backup_db_count",
                  "repo_commit", "repo_branch", "repo_dirty", "repo_commit_date", "crontab"):
            if k in prod:
                o.append(f"| {k} | `{prod[k]}` |")

    o.append("\n## 4. 机器判定的风险 / 漂移\n")
    if risks:
        o.append("| 类别 | 是什么 | 细节 |")
        o.append("|---|---|---|")
        for r in risks:
            o.append(f"| {r['kind']} | {r['what']} | {r['detail']} |")
    else:
        o.append("_（本次采集没有判定出漂移）_")
    o.append("")

    if notes:
        o.append("\n## 5. 本次没采到 / 采失败的项（**不许当「一切正常」读**）\n")
        for n in notes:
            o.append(f"- {n}")
        o.append("")
    return "\n".join(o) + "\n"


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")           # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="采集真实世界基线（整改阶段 0）")
    ap.add_argument("--prod", action="store_true", help="额外走 ssh 采生产只读事实")
    ap.add_argument("--tests", action="store_true", help="顺带采后端用例数（慢约 30~60 秒）")
    ap.add_argument("--out", help="渲染成 Markdown 写到这个路径（如 docs/BASELINE.md）")
    ap.add_argument("--force", action="store_true", help="允许覆盖今天的 before/ 快照")
    ap.add_argument("--no-snapshot", action="store_true", help="只打印，不写 before/ 快照")
    args = ap.parse_args(argv)

    notes: list[str] = []
    local = collect_local(notes, with_tests=args.tests)
    local["captured_at"] = git("log", "-1", "--format=%cI") and __import__("datetime").datetime.now().isoformat(timespec="seconds")
    prod = collect_prod(notes) if args.prod else None
    risks = assess(local, prod, notes)

    day = date.today().isoformat()
    snap = ROOT / "_tools" / "baseline" / "before" / day / "baseline.json"
    if not args.no_snapshot:
        if snap.exists() and not args.force:
            print(f"⛔ 今天的快照已存在：{snap}\n"
                  f"   （before/ 记的是「改造前的样子」，默认不许覆盖；确实要重采加 --force）")
            return 2
        snap.parent.mkdir(parents=True, exist_ok=True)
        payload = {"local": local, "prod": prod, "risks": risks, "notes": notes}
        snap.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 快照：{snap.relative_to(ROOT)}（sha256 {hashlib.sha256(snap.read_bytes()).hexdigest()[:16]}）")

    if args.out:
        md = render_md(local, prod, risks, snapshot=snap, notes=notes)
        outp = ROOT / args.out
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(md, encoding="utf-8")
        print(f"✅ 文档：{args.out}（{len(md.splitlines())} 行）")

    print(f"\n本地：端点 {local.get('endpoints_total')} ｜ 检查 {local.get('static_checks')} ｜ "
          f"后端用例 {local.get('backend_tests')} ｜ 安卓用例 {local.get('android_tests_declared')}"
          f"（最近一次跑到 {local.get('android_tests_last_run')}）")
    print(f"风险判定：{len(risks)} 条")
    for r in risks:
        print(f"  · [{r['kind']}] {r['what']} —— {r['detail'][:160]}")
    if notes:
        print(f"未采到 {len(notes)} 项：")
        for n in notes:
            print(f"  ! {n[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())