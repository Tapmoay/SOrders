#!/usr/bin/env python3
"""_release.py —— 生产发布：**先迁移、后应用**（R3-05-B · 禁做 #13）。

### 为什么必须有它
指南 §十七 的原话是「**不要** restart systemd → hope」，要的是这个顺序：

    backup → migration → verify → start new backend → health → readonly smoke → business smoke

手工敲这七条有三个问题（本仓库三个都踩过）：
① **顺序会被临时改**：先起服务再迁库 ⇒ 新代码对着旧结构跑；
② **「备份了吗」没人验**：备份脚本静默失败等于没有备份；
③ **失败之后现场只剩一行报错**：回滚指引不在手边，人就会开始「再试一次」。

### 四条硬护栏（写在**代码里**，不是靠记性）
G1 **默认只打印**：⛔ 不给 --go 绝不执行任何一步 —— 所有有副作用的调用都在 if go: 之后，
   而 decide() 是**纯函数**（--selftest 直接测它，不连生产）。
G2 **顺序强制**：每一步只有在**前面所有步**都成功记在同一份 run-file 里时才允许跑
   （--step start 在「没备份 / 没迁移过」时**直接拒绝**）。
G3 **备份必须新鲜**：--step start 要求最近一次 pre-release 备份 < 6 小时，否则拒绝。
G4 **算不出事实就拒绝**（fail-closed）：连不上生产、读不到备份年龄时**不许**当成「大概没事」。

⛔ 生产事实只在 _prodssh.py 一处（主机 / 路径 / 密钥一律 import，本文件不写死任何一台机器）。
⛔ 备份那一步不自己实现：直接调 _tools/backup/_pre_release.py（口径一处）。

用法：
    python _tools/deploy/_release.py --plan            # 打印七步与判据（⛔ 不碰生产）
    python _tools/deploy/_release.py --selftest        # 护栏自检（**假事实**，⛔ 不连生产）
    python _tools/deploy/_release.py --step start      # 只判「现在能不能跑 start」，不执行
    python _tools/deploy/_release.py --step backup --go
    python _tools/deploy/_release.py --all --go        # 按顺序全跑，任何一步失败就停
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ops"))
import _prodssh  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKUP_HOURS_MAX = 6          #: 备份新鲜度上限（小时）—— 超过就不许 start
STATE_FILE = Path(tempfile.gettempdir()) / "sorders_r3_release.json"

#: 顺序**就是**判据：改这里的顺序等于改纪律，必须同步改 docs/RELEASE_CANDIDATE.md §四。
STEPS: tuple[str, ...] = ("backup", "migrate", "verify", "start", "health", "smoke", "business")

#: 每一步：命令 / 期望 / 失败怎么办（打印给操作的人看，⛔ 不指望他记得住）。
STEP_DOC: dict[str, tuple[str, str, str]] = {
    "backup": ("调 _tools/backup/_pre_release.py（库 + 上传 + 清单）",
               "清单落到 _tools/backup/manifests/，并打印回滚命令",
               "备份失败 → **停止发布**（没有回滚点就不许往前走）"),
    "migrate": ("生产上跑迁移的唯一入口：.venv/bin/python -m app.migrations upgrade",
                "版本 0 → 8；schema_versions 出现 8 行",
                "失败 → 不启动服务；按 RELEASE_CANDIDATE §五 前向修复或从 dump 恢复"),
    "verify": ("生产上 .venv/bin/python -m app.migrations status",
               "「当前版本：8 / 待跑：0 条」",
               "与期望不符 → 不启动"),
    "start": ("git checkout <SHA> + systemctl restart sorders-api",
              "systemctl is-active = active",
              "起不来 → 看 journalctl -u sorders-api；按 §五 处置"),
    "health": ("本机跑 _tools/ops/_health_check.py",
               "退出码 0（或只有「已知/已接受」的证书告警 = 1）",
               "退出码 2 → 立刻回滚"),
    "smoke": ("本机跑 _tools/ops/_prod_smoke.py --readonly",
              "退出码 0（现状健康**且**与这一版代码一致）",
              "退出码 2 → 回滚；1 → 看是哪几项不一致"),
    "business": ("按 docs/PRODUCTION_ACCEPTANCE.md §三 做**有限写**烟测",
                 "逐条按那份清单走",
                 "任何一条不符合 → 回滚或前向修复"),
}


# ------------------------------------------------------------------ 纯逻辑（可自检）
def decide(step: str, go: bool, facts: dict, state: dict) -> tuple[str, str]:
    """**纯函数**：这一步该「打印计划」「拒绝」还是「执行」（action ∈ plan / refuse / run）。

    ⛔ 这里一行副作用都没有 —— 所以 --selftest 能把四条护栏逐条验掉，不用连生产。
    """
    if step not in STEPS:
        return "refuse", "不认识的步骤：" + step + "（只有 " + "、".join(STEPS) + "）"
    if not go:                                                       # G1
        return "plan", "没给 --go：只打印，不执行"
    done = list(state.get("done") or [])
    idx = STEPS.index(step)
    missing = [s for s in STEPS[:idx] if s not in done]               # G2
    if missing:
        return "refuse", ("顺序强制：这一步之前还有没跑成功的步骤 —— " + "、".join(missing)
                          + "（--all 会按顺序自己走；单步跑就从第一步开始）")
    if step == "start":
        age = facts.get("backup_age_hours")
        if age is None:                                              # G4
            return "refuse", "算不出最近一次备份的年龄（连不上生产？）—— 算不出就不许 start"
        if age > BACKUP_HOURS_MAX:
            return "refuse", ("备份太旧：" + format(age, ".1f") + " 小时前（上限 "
                              + str(BACKUP_HOURS_MAX) + " 小时）—— 先跑 backup")
        if not facts.get("sha_in_repo"):
            return "refuse", ("--sha 不是本仓库里的提交（" + str(facts.get("sha") or "没给")
                              + "）—— 发布必须落在**本仓库真实提交**上")
    return "run", "护栏全过"


def build_cases() -> list[tuple[str, dict, str, str]]:
    """(说明, decide 的入参, 期望 action, 期望 why 里必须出现的词)。"""
    done3 = {"done": ["backup", "migrate", "verify"]}
    fresh = {"backup_age_hours": 1.0, "sha_in_repo": True, "sha": "a" * 40}
    return [
        ("G1 不给 --go ⇒ 只打印（哪怕护栏全过）",
         dict(step="start", go=False, facts=fresh, state=done3), "plan", "只打印"),
        ("G2 start 之前没 backup/migrate/verify ⇒ 拒绝",
         dict(step="start", go=True, facts=fresh, state={}), "refuse", "顺序强制"),
        ("G2 migrate 之前没 backup ⇒ 拒绝",
         dict(step="migrate", go=True, facts=fresh, state={}), "refuse", "顺序强制"),
        ("G3 备份 40 小时前 ⇒ 拒绝",
         dict(step="start", go=True, state=done3, facts={"backup_age_hours": 40.0, "sha_in_repo": True}),
         "refuse", "备份太旧"),
        ("G4 算不出备份年龄 ⇒ 拒绝（不许猜成没事）",
         dict(step="start", go=True, state=done3, facts={"backup_age_hours": None, "sha_in_repo": True}),
         "refuse", "算不出"),
        ("--sha 不是本仓库提交 ⇒ 拒绝",
         dict(step="start", go=True, state=done3,
              facts={"backup_age_hours": 1.0, "sha_in_repo": False, "sha": "deadbeef" * 5}),
         "refuse", "不是本仓库里的提交"),
        ("护栏全过 ⇒ 才允许执行",
         dict(step="start", go=True, state=done3, facts=fresh), "run", "护栏全过"),
        ("不认识的步骤 ⇒ 拒绝",
         dict(step="deploy", go=True, state=done3, facts=fresh), "refuse", "不认识的步骤"),
    ]


def selftest() -> int:
    bad = 0
    cases = build_cases()
    for label, kw, want_action, want_word in cases:
        action, why = decide(**kw)
        ok = (action == want_action) and (want_word in why)
        print(("  OK   " if ok else "  BAD  ") + label + " → " + action + "：" + why)
        bad += 0 if ok else 1
    for s in STEPS:      # ⛔ 自检还要证明「默认不动手」：没有 --go 时任何步骤都只能是 plan
        action, _ = decide(step=s, go=False, facts={"backup_age_hours": 1.0, "sha_in_repo": True}, state={})
        if action != "plan":
            print("  BAD  没有 --go 时步骤 " + s + " 居然不是 plan")
            bad += 1
    print("发布工具护栏自检：" + str(len(cases) + len(STEPS) - bad) + "/" + str(len(cases) + len(STEPS)) + " 通过")
    return 1 if bad else 0
# ------------------------------------------------------------------ 事实（只读）
def repo_sha_ok(sha: str) -> bool:
    r = subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=str(ROOT), capture_output=True)
    return r.returncode == 0


def backup_age_hours() -> float | None:
    """最近一次 pre-release 备份的年龄（小时）。读不到返回 None —— ⛔ 不当成 0。"""
    cmd = ("find " + _prodssh.BACKUP_ROOT + " -name manifest.json -printf '%T@\\n' 2>/dev/null"
           " | sort -rn | head -1")
    try:
        lines = [x.strip() for x in _prodssh.ssh_lines(cmd) if x.strip()]
    except Exception:  # noqa: BLE001 —— 连不上就是算不出（fail-closed）
        return None
    if not lines:
        return None
    try:
        return (time.time() - float(lines[0])) / 3600.0
    except ValueError:
        return None


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8", newline="")


# ------------------------------------------------------------------ 七个步骤（只有 --go 才走到这儿）
def ssh(cmd: str) -> tuple[int, str]:
    r = _prodssh.ssh_script(cmd, check=False)
    return r.returncode, r.stdout.decode("utf-8", "replace")


def run_backup(note: str) -> int:
    cmd = [sys.executable, str(ROOT / "_tools" / "backup" / "_pre_release.py"), "--note", note]
    print("  → " + " ".join(cmd))
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def run_migrate() -> int:
    code, out = ssh("cd " + _prodssh.BACKEND_DIR + " && " + _prodssh.VENV_PY + " -m app.migrations upgrade")
    print(out[-2000:])
    return code


def run_verify() -> int:
    code, out = ssh("cd " + _prodssh.BACKEND_DIR + " && " + _prodssh.VENV_PY + " -m app.migrations status")
    print(out[-2000:])
    if code != 0:
        return code
    if "待跑：0" not in out:
        print("⛔ status 里没有「待跑：0 条」—— 迁移没跑干净，不启动服务")
        return 1
    return 0


def run_start(sha: str, fetch: bool) -> int:
    pre = ("git -C " + _prodssh.APP_DIR + " fetch origin && " if fetch else "")
    code, out = ssh(pre + "git -C " + _prodssh.APP_DIR + " checkout " + sha)
    print(out[-1200:])
    if code != 0:
        return code
    code, out = ssh("systemctl restart " + _prodssh.SERVICE + " && sleep 2 && systemctl is-active "
                    + _prodssh.SERVICE)
    print(out.strip())
    return 0 if out.strip() == "active" else 1


def run_local_script(rel: str, extra: list[str] | None = None) -> int:
    cmd = [sys.executable, str(ROOT / rel)] + (extra or [])
    print("  → " + " ".join(cmd))
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


ROLLBACK_HINT = (
    "   · 代码回退：git -C {app} checkout <上一个可用提交> && systemctl restart {svc}\n"
    "   · 库回滚：用 backup 那一步的 dump（⛔ 会丢掉 dump 之后写入的数据）\n"
    "   · 前向修复：数据没错、问题小而明确时，宁可再修一版（见 RELEASE_CANDIDATE §5.4）"
)


def print_plan() -> None:
    print("发布顺序（⛔ 不许调：R3-01 之后应用启动会核对结构，库没准备好就拒绝启动）：")
    for i, s in enumerate(STEPS, 1):
        cmd, expect, fail = STEP_DOC[s]
        print("  " + str(i) + ". " + s.ljust(9) + cmd)
        print("     " + " " * 9 + "期望：" + expect)
        print("     " + " " * 9 + "失败：" + fail)
    print("")
    print("  每一步都要 --go 才真的跑；顺序由 run-file 强制（" + str(STATE_FILE) + "）")


def main() -> int:
    ap = argparse.ArgumentParser(description="生产发布：先迁移、后应用（默认只打印）")
    ap.add_argument("--step", choices=list(STEPS), help="只做某一步（缺省：打印计划）")
    ap.add_argument("--all", action="store_true", help="按顺序全跑（任何一步失败就停）")
    ap.add_argument("--plan", action="store_true", help="只打印（默认行为）")
    ap.add_argument("--selftest", action="store_true", help="护栏自检（假事实，不连生产）")
    ap.add_argument("--go", action="store_true", help="⛔ 真的执行（没有它一律只打印）")
    ap.add_argument("--sha", help="--step start 要发布的提交（缺省＝本机 HEAD）")
    ap.add_argument("--no-fetch", action="store_true", help="--step start 时不 git fetch")
    ap.add_argument("--note", help="备份清单里的说明（缺省自动生成）")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    sha = a.sha or subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True,
                                  text=True).stdout.strip()
    note = a.note or ("R3-05 发布 " + sha[:8])
    hint = ROLLBACK_HINT.format(app=_prodssh.APP_DIR, svc=_prodssh.SERVICE)

    if a.all:
        todo = list(STEPS)
    elif a.step:
        todo = [a.step]
    else:
        print_plan()
        print("")
        print("  本机 HEAD：" + sha[:12] + "（--sha 可覆盖；--all 会按顺序走完七步）")
        return 0

    state = load_state()
    for step in todo:
        facts: dict = {"sha": sha, "sha_in_repo": repo_sha_ok(sha)}
        if step == "start":
            facts["backup_age_hours"] = backup_age_hours()
        action, why = decide(step=step, go=a.go, facts=facts, state=state)
        cmd, expect, fail = STEP_DOC[step]
        print("")
        print("== " + step + "：" + cmd)
        print("   期望：" + expect + " ｜ 失败：" + fail)
        print("   护栏：" + why)
        if action != "run":
            print("   ⛔ 不执行" + ("（计划模式）" if action == "plan" else "（护栏拒绝）"))
            return 0 if action == "plan" else 1

        if step == "backup":
            code = run_backup(note)
        elif step == "migrate":
            code = run_migrate()
        elif step == "verify":
            code = run_verify()
        elif step == "start":
            code = run_start(sha, fetch=not a.no_fetch)
        elif step == "health":
            code = run_local_script("_tools/ops/_health_check.py")
            code = 0 if code in (0, 1) else code          # 1 = 告警（证书那种已知项）
        elif step == "smoke":
            code = run_local_script("_tools/ops/_prod_smoke.py", ["--readonly"])
        else:   # business
            print("   ⛔ business 这一步**故意不自动化**：它要往生产写业务数据（建单/派单/撤销），"
                  "必须人按 docs/PRODUCTION_ACCEPTANCE.md §三 逐条做并留痕。")
            code = 0

        if code != 0:
            print("❌ " + step + " 失败（退出码 " + str(code) + "）—— **停下**，按 docs/RELEASE_CANDIDATE.md §五 处置：")
            print(hint)
            return code
        state["sha"] = sha
        state["done"] = sorted(set(list(state.get("done") or []) + [step]), key=STEPS.index)
        save_state(state)
        print("✅ " + step + " 完成；已完成：" + "、".join(state["done"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
