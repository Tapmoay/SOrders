#!/usr/bin/env python3
"""_check_ci_workflows.py —— CI 工作流自己的判据（进 `_check_all.py` 自动跑）。

### 为什么 workflow 需要检查
整改报告 §5 的原话是：「你的质量体系非常强，但 CI 并没有把它们真正接管 —— 你已经造好了检测器，
只是没有接到自动生产线上。」于是阶段 3 把三层闸门写进了 `.github/workflows/gate.yml`。

但 **workflow 是一份不会在自己身上跑的清单**，它的三类错误没有一个会在本地暴露：

1. **路径写错**（脚本改名/搬走）→ 只有 CI 上那一步红，而人看的是本机 `_check_all.py` 全绿；
2. **分支筛错**（只挂 main/develop，而代码长期落在 `p`）→ CI 从来没跑过真正的开发分支，
   而且**看起来一切正常**（这个坑本仓库已经踩过：见 gate.yml 开头那两条诚实说明）；
3. **任务名写错**（`testPhoneDebugUnitTest` 里的 flavor 与 `build.gradle.kts` 对不上）→
   夜闸红，而没人看夜闸。

共同形状还是那一条：**写在 YAML 里的规矩没人执行**。所以这里把它变成机器判据。

### 判据（尽量从仓库现状**算**出来，不手写名单）
1. 两个 workflow 都能被 YAML 解析；
2. 触发分支必须包含**这个仓库真正在用的分支**（从 git 推：当前分支 + 它的 upstream）——
   换了开发分支而 CI 没跟上，当场红；
3. 每条 `run:` 里引用的仓库内路径（`.py` / `.sh` / `.ps1`，以及 `python -m <模块>`）必须真实存在；
4. 三层结构在：fast/normal/nightly 各自有 job，且 fast 是被 `needs` 依赖的那一层；
5. 报告 §5 点名的 fast gate 四件事（语法 / 端点索引没过期 / 核心区冻结 / 密钥自检）都在；
6. PR 闸里真的跑了 `_tools/qa/_check_all.py`（"CI 正式接管已有检查体系"的那一步）；
7. gradle 任务名里的 flavor 必须在 `android/app/build.gradle.kts` 的 `productFlavors` 里存在；
8. 会**注入缺陷/吃满 CPU** 的 job（反向验证、安卓单测）必须只在 `schedule` / `workflow_dispatch` 上跑
   —— 它们在 PR 上并发会互相踩（本仓库实测过：反向验证跑着的时候别人改代码会被抹掉）；
9. 有 `concurrency` 组（同一分支的重复触发要能互相取消）；
10. 判据条数下限（防检查空转）；
11. **`cd <目录>` / `working-directory:` 指到的目录必须存在**（2026-09-25 补）。
    为什么它必须单独一条：第 3 条只查 "run: 里出现的**文件**路径"，而 `cd frontend` 这种
    **目录**目标完全不在扫描范围内 —— 于是 gate.yml 里那个 `frontend-build` 作业
    （每一步都先 `cd frontend`）在 `frontend/` 被归档之后依然"看起来没问题"，
    是本仓库**人工**发现再删掉的，**不是**被这条检查拦下的。反例已钉进
    `_tools/qa/_reverse_verify_ci_workflows.py` 的 ① 与 ②（两个方向：`cd` 与 step 级工作目录）。

用法：
    python _tools/qa/_check_ci_workflows.py --check   # 非零退出＝有问题
    python _tools/qa/_check_ci_workflows.py           # 打印逐条明细
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("⚠️ 需要 PyYAML：pip install pyyaml")
    raise SystemExit(2)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WF = ROOT / ".github" / "workflows"
PLAN_REL = "_tools/qa/_check_all.py"
MIN_RULES = 14

# fast gate 四件事（报告 §5 图里的 "syntax / changed checks / endpoint freshness / core freeze"）
FAST_SHOULD = {
    "compileall": "语法（后端 .py 能编译）",
    "gen_endpoint_index": "端点索引没过期",
    "_check_core_freeze.py": "核心区冻结",
    "_check_secrets.py": "密钥自检（仓库是公开的）",
}
PATH_RE = re.compile(r"(?<![\w.$-])((?:backend|frontend|_tools|android|docs)/[\w./-]+\.(?:py|sh|ps1|kts|md|txt|json|yml))")
MOD_RE = re.compile(r"python3?\s+-m\s+([\w.]+)")
FLAVOR_RE = re.compile(r":app:test([A-Z][A-Za-z0-9]*)DebugUnitTest")
#: `cd <目录>` 里的目录目标（与上面的"文件路径"是**两件事**，见 §3b）。
CD_RE = re.compile(r"\bcd\s+([^\s;&|)]+)")
#: 不算"仓库内相对目录"的 cd 目标。
SKIP_CD = {"", ".", "..", "~"}


def git(*args: str) -> str:
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return (p.stdout or "").strip()


def load(p: Path) -> dict:
    data = yaml.safe_load(p.read_text(encoding="utf-8", errors="replace")) or {}
    # YAML 1.1 把裸 `on` 解析成布尔 True —— 两种写法都得认
    if True in data and "on" not in data:
        data["on"] = data[True]
    return data


def triggers(doc: dict) -> dict:
    t = doc.get("on") or {}
    return t if isinstance(t, dict) else {}


def runs_of(doc: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name, job in (doc.get("jobs") or {}).items():
        for step in (job or {}).get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                out.append((name, step["run"]))
    return out


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

    files = sorted(WF.glob("*.yml")) + sorted(WF.glob("*.yaml"))
    docs: dict[str, dict] = {}
    for p in files:
        try:
            docs[p.name] = load(p)
            want(True, p.name + " 能被 YAML 解析", "")
        except Exception as exc:  # noqa: BLE001
            want(False, "", p.name + " YAML 解析失败：" + str(exc))
    want(len(docs) >= 2, "workflow 文件 " + str(len(docs)) + " 个",
         "⛔ workflow 少于 2 个（gate.yml 之外的那份没了？）")

    # ---------- 2. 分支口径：代码真正落在哪个分支，就挂哪个分支 ----------
    cur = git("rev-parse", "--abbrev-ref", "HEAD")
    up = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    dev = {b for b in [cur, up.split("/")[-1] if up else ""] if b and b != "HEAD"}
    want(bool(dev), "推出在用的开发分支：" + "、".join(sorted(dev)) if dev else "",
         "⛔ 推不出当前分支（git 历史被改写？）")
    for name, doc in docs.items():
        tr = triggers(doc)
        for ev in ("push", "pull_request"):
            blk = tr.get(ev)
            if blk is None:
                continue
            brs = blk.get("branches") if isinstance(blk, dict) else blk
            brs = brs or []
            missing = sorted(b for b in dev if b not in brs)
            want(not missing, name + " 的 " + ev + " 挂了 " + "、".join(sorted(dev)),
                 "⛔ " + name + " 的 " + ev + " 没挂 " + "、".join(missing) +
                 "（而这个仓库的代码就落在那儿 —— CI 会一次都不跑，而且看不出来）")

    # ---------- 3. run: 里引用的仓库内路径必须真实存在 ----------
    missing_paths: list[str] = []
    missing_mods: list[str] = []
    for name, doc in docs.items():
        for job, run in runs_of(doc):
            for m in PATH_RE.finditer(run):
                if (ROOT / m.group(1)).exists():
                    continue
                missing_paths.append(name + "/" + job + " → " + m.group(1))
            for m in MOD_RE.finditer(run):
                mod = m.group(1)
                leaf = mod.split(".")[-1]
                if any(ROOT.glob("backend/**/" + leaf + ".py")) or any(ROOT.glob("_tools/**/" + leaf + ".py")):
                    continue   # 仓库里的模块（真存在）
                try:   # 标准库/已装的三方模块（compileall / pytest 这类）不算路径
                    known = importlib.util.find_spec(mod.split(".")[0]) is not None
                except (ImportError, ValueError):
                    known = False
                if known:
                    continue
                missing_mods.append(name + "/" + job + " → python -m " + mod)
    want(not missing_paths, "run: 里引用的仓库内路径都存在",
         "⛔ 有路径在仓库里找不到：" + "；".join(sorted(set(missing_paths))[:6]))
    want(not missing_mods, "run: 里 python -m 的模块都存在",
         "⛔ 有模块找不到：" + "；".join(sorted(set(missing_mods))[:6]))

    # ---------- 3b. `cd <目录>` / `working-directory:` 指到的目录必须存在 ----------
    # 为什么单列一条：上面第 3 条只查 "run: 里出现的**文件**路径存在"，而 `cd frontend`
    # 这种**目录**目标一个都不在扫描范围内。于是 `.github/workflows/gate.yml` 里的
    # `frontend-build` 作业（每一步都先 `cd frontend`）在 `frontend/` 被归档之后依然
    # "看起来没问题"，判据一声不吭 —— 2026-09-25 实测：那个作业是**人工**发现再删掉的，
    # **不是**被这条检查拦下的。路径类判据的漏洞都是同一个形状：只扫了自己想得到的那一种。
    cd_targets: list[tuple[str, str, str]] = []
    for name, doc in docs.items():
        for job, run in runs_of(doc):
            for m in CD_RE.finditer(run):
                cd_targets.append((name, job, m.group(1)))
        for job_name, job in (doc.get("jobs") or {}).items():
            wd = (((job or {}).get("defaults") or {}).get("run") or {}).get("working-directory")
            if wd:
                cd_targets.append((name, job_name, str(wd)))
            for step in (job or {}).get("steps") or []:
                if isinstance(step, dict) and step.get("working-directory"):
                    cd_targets.append((name, job_name, str(step["working-directory"])))
    # 只认**仓库内的相对目录**：带 `$`（表达式/环境变量）、`~`、绝对路径、`.`/`..` 一律不算。
    real_cd = sorted({(w, j, d.strip("\"'").rstrip("/"))
                      for w, j, d in cd_targets
                      if d.strip("\"'").rstrip("/") not in SKIP_CD
                      and "$" not in d and "~" not in d and not d.startswith("/")})
    bad_cd = [w + "/" + j + " → " + d for w, j, d in real_cd if not (ROOT / d).is_dir()]
    want(len(real_cd) >= 4,
         "扫到 " + str(len(real_cd)) + " 个 cd / working-directory 的仓库内目录",
         "⛔ 只扫到 " + str(len(real_cd)) + " 个 cd 目标 —— 判据在空转（workflow 结构变了？）")
    want(not bad_cd, "cd / working-directory 指到的目录都真实存在",
         "⛔ 指到不存在的目录：" + "；".join(bad_cd[:6]) +
         "（那一步会在不存在的目录里跑；本机 _check_all.py 全绿，所以本机看不出来）")

    # ---------- 4/5/6/8. 三层结构与各自的职责 ----------
    gate = docs.get("gate.yml") or {}
    jobs = gate.get("jobs") or {}
    want(len(jobs) >= 5, "gate.yml 有 " + str(len(jobs)) + " 个 job（三层）",
         "⛔ gate.yml 的 job 太少 —— 三层闸门被拆掉了？")
    names = " ".join(jobs)
    want(bool(re.search(r"fast", names, re.I)) and bool(re.search(r"night|reverse", names, re.I)),
         "快闸与夜闸都在（" + "、".join(sorted(jobs)) + "）",
         "⛔ 找不到快闸/夜闸的 job")
    needs_fast = [n for n, j in jobs.items() if "fast" in (j or {}).get("needs", []) or (j or {}).get("needs") == "fast"]
    want(len(needs_fast) >= 3, str(len(needs_fast)) + " 个 job 依赖快闸（快闸确实在最前面）",
         "⛔ 依赖快闸的 job 少于 3 个 —— 层序散了")

    fast_job = next((j for n, j in jobs.items() if "fast" in n), {})
    fast_runs = "\n".join(s.get("run", "") for s in (fast_job.get("steps") or []) if isinstance(s, dict))
    for key, label in FAST_SHOULD.items():
        want(key in fast_runs, "快闸里有：" + label, "⛔ 快闸里少了：" + label + "（" + key + "）")

    all_runs = {n: "\n".join(r for j, r in runs_of(gate) if j == n) for n in jobs}
    pr_jobs = [n for n, j in jobs.items()
               if not str((j or {}).get("if") or "").startswith("github.event_name ==")]
    want(any(PLAN_REL in all_runs.get(n, "") for n in pr_jobs),
         "PR 闸里跑 _tools/qa/_check_all.py（CI 真的接管了检查体系）",
         "⛔ PR 闸里没有 _check_all.py —— 检查体系又只剩人在本机跑")

    # 反向验证会**往源码里注入缺陷**，与任何并发的改动互相踩（本仓库实测过被抹掉 15 个文件）→ 只能夜闸。
    inject = {n: r for n, r in all_runs.items() if "_reverse_verify_all.py" in r}
    want(bool(inject), "认出注入式的 job：" + "、".join(sorted(inject)) + "（反向验证）",
         "⛔ 没认出跑反向验证的 job —— 本判据要盯的就是它")
    for n in inject:
        cond = str((jobs.get(n) or {}).get("if") or "")
        want("schedule" in cond,
             n + " 只在夜闸/手动跑（注入式验证不能在 PR 上跑）",
             "⛔ " + n + " 没有限定在 schedule/workflow_dispatch —— 它会在 PR 上注入缺陷，"
             "与并发改动互相踩（2026-09-20 实测被抹掉过 15 个文件）")

    # 安卓单测不吃注入，但吃时间：报告 §14 的目标是「PR 上就拦住」，所以这里**不许**把它钉死在夜闸，
    # 只要求「跑得起来」的四件事实在（JDK / gradle 版本 pin / 任务名 / 失败也给结论的报告步骤）。
    gradle_jobs = {n: r for n, r in all_runs.items() if FLAVOR_RE.search(r)}
    want(bool(gradle_jobs), "认出跑安卓单测的 job：" + "、".join(sorted(gradle_jobs)),
         "⛔ 没认出跑 gradle 单测的 job")
    for n, r in gradle_jobs.items():
        steps = (jobs.get(n) or {}).get("steps") or []
        uses = [str(s.get("uses") or "") for s in steps if isinstance(s, dict)]
        want(any("setup-java" in u for u in uses), n + " 装了 JDK（setup-java）",
             "⛔ " + n + " 没有 setup-java —— gradle 在 runner 上跑不起来")
        want(any("setup-gradle" in u for u in uses), n + " 装了 gradle（setup-gradle）",
             "⛔ " + n + " 没有 setup-gradle —— runner 上没有 gradle")
        ver = ""
        for s in steps:
            if isinstance(s, dict) and "setup-gradle" in str(s.get("uses") or ""):
                ver = str((s.get("with") or {}).get("gradle-version") or "")
        want(bool(re.match(r"^\d+\.\d+", ver)), n + " 把 gradle 版本钉成 " + (ver or "（空）"),
             "⛔ " + n + " 没钉 gradle 版本 —— runner 自带的版本变了，构建结果就跟着变")
        want(any(isinstance(s, dict) and "always()" in str(s.get("if") or "") for s in steps),
             n + " 失败也给结论（if: always() 的报告步骤）",
             "⛔ " + n + " 失败时只留一句 exit 1 —— 没人知道是哪几个用例挂了")

    want(all(bool((d or {}).get("concurrency")) for d in docs.values()),
         "每份 workflow 都有 concurrency 组",
         "⛔ 有 workflow 没有 concurrency：同一分支重复触发会一起跑")

    # ---- 12. 并行 pytest 必须带 --dist loadfile（★ 2026-09-25 实测出来的，不是猜的）----
    #    本测试套件是「每个 xdist worker 一个 SQLite 库」（tests/conftest.py::get_db_path），
    #    而**同一个文件的用例会共享那个库的状态** → 默认的 --dist load 把一个文件的用例拆到不同
    #    worker 上，就有用例看不到同伴留下的行。用 CI 的原命令实测：
    #        pytest -n auto                      → 2 failed / 1013 passed
    #        pytest -n auto --dist loadfile      → 1015 passed（0 failed）
    #    这条判据的作用是「别哪天有人把 --dist loadfile 删了而没人发现」—— 删了 CI 就红，而 CI 红的
    #    原因**又要靠人猜**：那两个 job 之前红了整整几轮（公开仓库读不到 job 日志），就是这么来的。
    par_runs = [(name, job, run) for name, doc_ in docs.items() for job, run in runs_of(doc_)]
    n_par = 0
    missing_dist: list[str] = []
    for name, job, run in par_runs:
        for ln in run.splitlines():
            if not re.search(r"pytest[^\n]*\s-n\s*(?:\d|auto)", ln):
                continue
            n_par += 1
            if "--dist loadfile" not in ln:
                missing_dist.append(name + "/" + job + " → " + ln.strip()[:90])
    want(n_par >= 3, "盘到 " + str(n_par) + " 处并行 pytest（判据没空转）",
         "⛔ 只盘到 " + str(n_par) + " 处并行 pytest（<3）—— 判据在空转")
    want(not missing_dist, "每一处并行 pytest 都带 --dist loadfile（文件内的用例必须落在同一个 worker）",
         "⛔ 这些并行 pytest 没带 --dist loadfile：" + "；".join(missing_dist[:6])
         + "（默认分发会把一个文件的用例拆开 → 有用例看不到同伴留下的行，实测 2 failed；"
         "这不是环境问题，见计划表第 42 轮）")

    # ---------- 7. gradle 任务名里的 flavor 必须真实存在 ----------
    gradle_kts = ROOT / "android" / "app" / "build.gradle.kts"
    src = gradle_kts.read_text(encoding="utf-8", errors="replace") if gradle_kts.exists() else ""
    flavors = {f.lower() for f in re.findall(r'create\("([A-Za-z0-9]+)"\)', src)}
    used = {m.group(1).lower() for _n, doc in docs.items() for _j, r in runs_of(doc) for m in [FLAVOR_RE.search(r)] if m}
    want(bool(flavors), "build.gradle.kts 里数出 flavor：" + "、".join(sorted(flavors)),
         "⛔ 数不出 productFlavors（判据要盯的就是「任务名与 flavor 对不上」）")
    for u in sorted(used):
        want(u in flavors, "gradle 任务里的 flavor `" + u + "` 真实存在",
             "⛔ 任务里的 flavor `" + u + "` 在 build.gradle.kts 里没有 —— 夜闸会红，而没人看夜闸")

    total = len(passed) + len(failures)
    want(total >= MIN_RULES, "判据条数 " + str(total) + " ≥ " + str(MIN_RULES),
         "⛔ 只跑了 " + str(total) + " 条判据（< " + str(MIN_RULES) + "）—— 检查可能空转了")

    print("CI 工作流判据：" + str(len(passed)) + " 通过 / " + str(len(failures)) + " 失败")
    if not check_mode:
        for n in passed:
            print("  ✅ " + n[4:])
    for f in failures:
        print("  " + f)
    if failures:
        return 1
    print("  ✅ 全部通过（分支口径 / 路径 / 层序 / 危险 job 的时机 / gradle 任务名都对得上）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
