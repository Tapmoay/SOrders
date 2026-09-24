#!/usr/bin/env python3
"""_gen_acceptance.py —— 生成「整改验收」页（整改报告 §13：会变的数字一律不手写）。

## 为什么要有它
整改的目标是「按报告的全部建议分阶段整改」，而**「做完了」这件事必须可复现地证明**：
每个阶段都要有 ① 一件落地产物、② 一条能重跑的命令、③ 那条命令**自己打印出来的结论**。
所以这一页不是人写的总结，而是**跑出来的**：

    报告章节 → 落地产物（当场判存在）→ 复现命令 → 命令输出的那一行

## 口径（三条，与仓库其它生成物同一套）
1. 每个数字都来自**命令的输出**，不手写（手写的数字会腐烂，本项目已经栽过多次）；
2. 产物不存在 / 命令跑不动 / 超时 → 记 ❌ 并以非零退出（「算不出真值＝红」）；
3. 默认只跑**快**的那一批；--full 才跑全量静态检查与后端全量用例（各一两分钟）。

⛔ 刻意**不**声明 --check：那条路会被 _check_all.py 自动收进必跑组，而这一页要跑 pytest。
   它的定位是**快照**（页脚写着生成于哪个提交），不是每次提交都要重跑的门禁。

用法：
    python _tools/qa/_gen_acceptance.py --out docs/RECTIFICATION_ACCEPTANCE.md
    python _tools/qa/_gen_acceptance.py --full --out docs/RECTIFICATION_ACCEPTANCE.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PY = sys.executable
TICK = chr(96)


@dataclass(frozen=True)
class Evidence:
    """一条证据：报告章节 → 产物 → 复现命令 → 结论行。"""

    phase: str
    section: str
    what: str
    artifacts: tuple[str, ...]
    cmd: tuple[str, ...]
    pick: str = ""            # 从输出里挑结论行的正则；挑不到就取最后一个非空行
    cwd: str = ""             # 相对仓库根的运行目录
    timeout: int = 300
    only_full: bool = False   # 只在 --full 时跑（重命令）


EVIDENCE: tuple[Evidence, ...] = (
    Evidence("0", "§2 真实世界基线", "基线由脚本采集（before/ 冻结、after/ 可重采）",
             ("docs/BASELINE.md", "_tools/baseline/_capture_baseline.py",
              "_tools/baseline/_check_baseline.py"),
             (PY, "_tools/baseline/_check_baseline.py")),
    Evidence("1", "§3 备份 / 恢复演练", "脚本化备份 + 默认不碰生产库的恢复 + 每周演练",
             ("_tools/backup/_backup.sh", "_tools/backup/_restore.sh", "_tools/backup/_drill.sh",
              "_tools/backup/README.md"),
             (PY, "_tools/backup/_check_backup.py", "--check")),
    Evidence("2", "§4 Schema 迁移版本化", "版本表 + 每次结构变更一条迁移（跑过记进 schema_versions）",
             ("backend/app/migrations/_runner.py", "backend/app/migrations/001_baseline.py",
              "backend/app/migrations/002_outbox_events.py",
              "backend/app/migrations/003_operation_log_request_id.py",
              "backend/app/migrations/README.md"),
             (PY, "-m", "app.migrations", "status"), pick=r"当前版本", cwd="backend"),
    Evidence("2", "§4 迁移判据", "命名 / 版本号唯一递增 / 接线 / 失败不记账 / 漂移不抛异常",
             ("_tools/qa/_check_migrations.py",), (PY, "_tools/qa/_check_migrations.py")),
    Evidence("3", "§5 CI 正式接管检查体系", "三层闸门（快闸 / 常闸 / 夜闸）+ 分支口径 p、new",
             (".github/workflows/gate.yml", ".github/workflows/test-parallel.yml",
              "_tools/qa/_check_ci_workflows.py"),
             (PY, "_tools/qa/_check_ci_workflows.py")),
    Evidence("4", "§6 API 层纯搬迁", "orders.py / reports.py 拆开，URL 与出参一个字不变",
             ("backend/app/api/v1/orders.py", "backend/app/api/v1/orders_assignment.py",
              "backend/app/api/v1/orders_delivery.py", "backend/app/api/v1/orders_common.py",
              "backend/app/services/reports_service.py"),
             (PY, "_tools/qa/_check_endpoint_index_fresh.py")),
    Evidence("5", "§7 钱：从文件冻结升级为领域契约", "钱只有一处实现，消费方一律从契约 import",
             ("backend/app/services/money_contract.py", "_tools/qa/_check_money_contract.py"),
             (PY, "_tools/qa/_check_money_contract.py")),
    Evidence("5", "§8 状态机唯一写入口", "状态迁移只在 order_flow；写前取锁 + 原子占位",
             ("backend/app/services/order_flow.py", "_tools/qa/_check_status_gate_locking.py"),
             (PY, "_tools/qa/_check_status_gate_locking.py")),
    Evidence("5", "§9 权限模型真的在执行", "26 个权限点逐个有交代（在用 / 有理由）",
             ("backend/app/deps.py", "_tools/qa/_check_permission_points.py"),
             (PY, "_tools/qa/_check_permission_points.py")),
    Evidence("6", "§10 事务发件箱（可靠事件）", "事件与业务同事务；worker 派发 + 重试；生产者不许绕开",
             ("backend/app/core/outbox.py", "backend/app/models/outbox.py",
              "backend/app/migrations/002_outbox_events.py", "_tools/qa/_check_outbox.py"),
             (PY, "_tools/qa/_check_outbox.py")),
    Evidence("7", "§11 客户端大文件按职责拆", "AiWriteService 的三块职责＝三个文件（判据读并集，搬文件对判据不可见）",
             ("android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteService.kt",
              "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteJson.kt",
              "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteDataSource.kt"),
             (PY, "_tools/ai/_check_ai_guardrails.py", "--check")),
    Evidence("8", "§12 AI 能力目录与后端权限同源", "读能力由后端权限点**生成**，不手写（对账探针在 CI）",
             ("android/app/src/main/java/com/tapmoay/sorders/ai/AiReadCatalog.kt",
              "_tools/ai/_gen_ai_read_catalog.py", "_tools/ai/_probe_read_roles.py",
              "_tools/ai/_check_role_parity.py"),
             (PY, "_tools/ai/_check_role_parity.py")),
    Evidence("8", "§13 文档事实源自动化", "会变的数字不手写：生成物 + 判据守住",
             ("_tools/qa/_check_live_doc_counts.py", "docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md",
              "docs/PROJECT_MAP/09A_HINT_CATALOG.md"),
             (PY, "_tools/qa/_check_live_doc_counts.py")),
    Evidence("10", "§15 可观测性", "Request ID 一条链路 / 业务指标现算 / 外部监控四项（跑得到生产）",
             ("backend/app/core/request_id.py", "backend/app/core/metrics.py",
              "_tools/ops/_health_check.py", "backend/app/migrations/003_operation_log_request_id.py"),
             (PY, "_tools/ops/_check_ops.py")),
    Evidence("-", "§18 施工纪律：判据自己也要被验证", "反向验证的注入原文还找得到（锚点不许腐烂）",
             ("_tools/qa/_check_reverse_verify_anchors.py",),
             (PY, "_tools/qa/_check_reverse_verify_anchors.py")),
    Evidence("-", "§19 Domain + Database invariants", "直接查库：钱 / 库存 / 状态 / 单据自相矛盾吗",
             ("_tools/fuzz/_fuzz_invariants.py",),
             (PY, "_tools/fuzz/_fuzz_invariants.py", "--check"), pick=r"小结："),
    Evidence("-", "§5 全量静态检查（移交 CI 的那一套）", "清单自己算，一条命令跑完全部静态检查",
             ("_tools/qa/_check_all.py",), (PY, "_tools/qa/_check_all.py"), pick=r"个检查全部通过",
             timeout=900, only_full=True),
    Evidence("9", "§14 后端全量用例", "重构的等价性靠用例钉住（每一步都跑过）",
             ("backend/tests",), (PY, "-m", "pytest", "-q"), pick=r"[0-9]+ passed",
             cwd="backend", timeout=1800, only_full=True),
)


def git(*args: str) -> str:
    p = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return (p.stdout or "").strip()


def run_one(ev: Evidence) -> tuple[bool, str, str]:
    """跑一条证据。返回 (成功, 结论行, 备注)。"""
    missing = [a for a in ev.artifacts if not (ROOT / a).exists()]
    if missing:
        return False, "", "产物不存在：" + "、".join(missing)
    # ⚠️ 命令里那个 .py 自己也要判存在：写这一页的第一版把 _check_role_parity.py 写成了
    #    _tools/qa/（真身在 _tools/ai/），于是命令 exit 2、**没有任何输出** ——
    #    只看结论行只会看到「（没有输出）」，看不出是路径写错了。这一条就是那次踩坑补的。
    script = next((c for c in ev.cmd if c.endswith(".py") and not c.startswith("-")), "")
    if script and not Path(script).is_absolute() and not (ROOT / script).exists():
        return False, "", "命令里那个脚本不存在（路径写错了？）：" + script
    try:
        proc = subprocess.run(list(ev.cmd), cwd=str(ROOT / ev.cwd) if ev.cwd else str(ROOT),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=ev.timeout)
    except subprocess.TimeoutExpired:
        return False, "", "超时（>" + str(ev.timeout) + "s）"
    text = (proc.stdout or "") + (proc.stderr or "")
    line = ""
    if ev.pick:
        for ln in text.splitlines():
            if re.search(ev.pick, ln):
                line = ln.strip()
                break
    if not line:
        nonempty = [x.strip() for x in text.splitlines() if x.strip()]
        line = nonempty[-1] if nonempty else "（没有输出）"
    if proc.returncode != 0:
        return False, line, "退出码 " + str(proc.returncode)
    return True, line, ""


def render(rows: list[tuple[Evidence, bool, str, str]], *, full: bool) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    commit = git("rev-parse", "--short", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    # ⚠️ 不报「工作区干不干净」：这一页**自己**就是未提交的改动，永远会显示「有未提交改动」——
    #    一个永远说同一句话的字段等于没有信息（本项目的老话：永远红的检查＝没有检查）。
    o: list[str] = []
    o.append("# 整改验收（按报告章节逐条对账）")
    o.append("")
    o.append("> **本文件由 " + TICK + "_tools/qa/_gen_acceptance.py" + TICK
             + " 生成，不要手改**（报告 §13：会变化的数字一律不手写）。")
    o.append("> 重新生成： " + TICK + "python _tools/qa/_gen_acceptance.py --full --out "
             + "docs/RECTIFICATION_ACCEPTANCE.md" + TICK)
    o.append("")
    o.append("生成于 " + now + " UTC ｜ 分支 " + branch + " ｜ 提交 " + commit
             + (" ｜ 模式：完整（含全量静态检查与后端用例）" if full else " ｜ 模式：快速（略过两条重命令）"))
    o.append("")
    o.append("⚠️ 本页是**快照**：生成之后仓库还会往前走。**数字以重新跑出来的为准**，"
             "别拿这一页当当前值（这正是报告 §13 说的「文档系统要变成事实生成系统」）。")
    o.append("")
    o.append("这张表回答一个问题：**报告的每一条建议，落在哪个文件、用哪条命令能重新证明它还在。**")
    o.append("最后一列是**命令自己打印出来的那一行**，不是人写的。")
    o.append("")
    o.append("| 阶段 | 报告章节 | 做了什么 | 复现命令 | 命令自己打印的结论 |")
    o.append("| --- | --- | --- | --- | --- |")
    for ev, ok, line, note in rows:
        mark = "✅" if ok else "❌"
        cmd = " ".join(("python" if c == PY else c) for c in ev.cmd)
        cell = line.replace("|", "/")
        if ev.only_full and not full:
            mark = "·"
            cell = "（完整模式才跑，耗时较长）"
            cmd = "—"
        elif not ok and note:
            cell = (cell + "  ← " + note).strip()
        o.append("| " + ev.phase + " | " + ev.section + " | " + ev.what + " | " + mark + " "
                 + TICK + cmd + TICK + " | " + cell + " |")
    o.append("")
    o.append("## 还没做的（如实列，附原因与卡在谁那儿）")
    o.append("")
    o.append("| 事项 | 现状 | 原因 |")
    o.append("| --- | --- | --- |")
    o.append("| 把这些提交推到 GitHub，让 CI 真的跑那三层闸门 | 本地领先 origin/new | "
             "本机到 GitHub 的链路不通（代理整体失效、22 与 443 都被切断）；国内站点与生产 SSH 正常 |")
    o.append("| 读 Tests (Parallel) 那两个红 job 的 CI 注解 | 已把失败摘要改成**公开可读的 CI 注解**，等下一次 push | "
             "同上：拿不到 run 之前读不了 |")
    o.append("| 安卓单测从夜闸挪进 PR 闸 | 仍在夜闸（机器判据已把「跑得起来」的四件事钉住） | "
             "需要 CI 能跑，才能验证「挪进去不会让每个 PR 都红」 |")
    o.append("| 把整改后的代码发到生产 | 生产仍跑旧代码（外部监控里如实写着「还没有 outbox_events 表」「迁移版本 —」） | "
             "**等你拍板**；上线时启动会自动跑 002/003 两条迁移，迁移失败会拒绝启动（逃生门 SORDERS_SKIP_MIGRATIONS=1） |")
    o.append("")
    o.append("## 需要环境才能跑的两条（不摆进上表，免得把「本机没数据」记成失败）")
    o.append("")
    o.append("- _tools/ai/_probe_read_roles.py ：要一个**跑着的后端**（CI 的 read-roles-probe job 就是干这个的）。")
    o.append("- _tools/fuzz/_fuzz_invariants.py ：要**本机开发库**；没有库时它会响亮地跳过（不会假装通过）。")
    o.append("")
    o.append("---")
    o.append("")
    o.append("报告 §20 结尾的提醒也适用于这一页：**不要再加检查器，要改架构**。")
    o.append("所以这里没有新增任何判据 —— 它只是把**已有的那些**按报告章节摆成一张可复现的对照表。")
    return chr(10).join(o) + chr(10)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="生成整改验收页（数字全部来自命令输出）")
    ap.add_argument("--out", help="写到这个路径（如 docs/RECTIFICATION_ACCEPTANCE.md）")
    ap.add_argument("--full", action="store_true", help="连全量静态检查与后端用例一起跑（各一两分钟）")
    args = ap.parse_args(argv)

    rows: list[tuple[Evidence, bool, str, str]] = []
    for ev in EVIDENCE:
        if ev.only_full and not args.full:
            print("· 略过（完整模式才跑）：" + ev.section)
            rows.append((ev, True, "", ""))
            continue
        ok, line, note = run_one(ev)
        rows.append((ev, ok, line, note))
        print(("✅ " if ok else "❌ ") + ev.section + "： " + line + (("  ← " + note) if note else ""))

    md = render(rows, full=args.full)
    if args.out:
        path = ROOT / args.out
        path.write_text(md, encoding="utf-8")
        print("")
        print("已写入 " + str(path.relative_to(ROOT)) + "（" + str(len(md)) + " 字符）")
    else:
        print("")
        print(md)

    bad = [ev.section for ev, ok, _l, _n in rows if not ok]
    if bad:
        print("")
        print("❌ " + str(len(bad)) + " 条对不上：" + "、".join(bad))
        return 1
    print("")
    print("✅ 全部对得上（每一条都有产物、命令跑得通、结论行拿得到）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
