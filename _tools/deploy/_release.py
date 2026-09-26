#!/usr/bin/env python3
"""_release.py —— 生产发布：**先迁移、后应用**（R3-05-B · 禁做 #13）。

### 为什么必须有它
指南 §十七 的原话是「**不要** restart systemd → hope」，要的是这个顺序：

    backup → **stage（代码落位，不重启）** → migration → verify → start new backend → health
           → readonly smoke → business smoke

### 为什么是**八**步（2026-09-26 执行 A 阶段前实测发现，⛔ 不是设计时就有的）

迁移的入口 `-m app.migrations` **属于新代码**，而生产上当时**还没有这个包**（`ls .../app/migrations`
→ No such file）。所以「先迁移后应用」在**第一次**发布时**落不了地**：迁移命令会以
`No module named app.migrations` 失败，而那不是数据问题、是顺序问题。
=> 拆出独立的 `stage` 步：**先把代码落到 <SHA> 但⛔不重启服务**，再迁移、再重启。
三个状态分开，失败时才分得清是「代码没落位」「迁移失败」还是「服务起不来」。

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
import re
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
STEPS: tuple[str, ...] = ("backup", "stage", "migrate", "verify", "start", "health", "smoke", "business")

#: 每一步：命令 / 期望 / 失败怎么办（打印给操作的人看，⛔ 不指望他记得住）。
STEP_DOC: dict[str, tuple[str, str, str]] = {
    "backup": ("调 _tools/backup/_pre_release.py（库 + 上传 + 清单）",
               "清单落到 _tools/backup/manifests/，并打印回滚命令",
               "备份失败 → **停止发布**（没有回滚点就不许往前走）"),
    "stage": ("生产上 git fetch origin + git checkout <SHA>（**只落代码，不重启服务**）",
              "生产 HEAD = <SHA>，且 app/migrations 这个包**在**了；服务仍 active（跑的还是旧代码）",
              "失败 → 停止（服务与库都还没被动过；要退只需 checkout 回旧 SHA）"),
    "migrate": ("生产上跑迁移的唯一入口：.venv/bin/python -m app.migrations upgrade",
                "版本 0 → 8；schema_versions 出现 8 行",
                "失败 → 不启动服务；按 RELEASE_CANDIDATE §五 前向修复或从 dump 恢复"),
    "verify": ("生产上 .venv/bin/python -m app.migrations status --json",
               "当前版本 == 本仓库迁移头；待跑 0 / 漂移 0 / 陌生版本 0",
               "与期望不符 → 不启动"),
    "start": ("再核一次 git checkout <SHA>，然后**滚动重启所有 enabled 的 sorders-api* unit**（⛔ 不是重启某个写死的 unit）",
              "逐个实例：is-active=active ＋ /health=200 ＋ 重启期间**经 nginx 的入口一直有活上游**；全部通过才算过",
              "任一实例不 active / health 非 200 / 入口拿不到活上游 → 停下看 journalctl -u <unit>；按 §五 处置"),
    "health": ("本机跑 _tools/ops/_health_check.py",
               "退出码 0（或只有「已知/已接受」的证书告警 = 1）",
               "退出码 2 → 立刻回滚"),
    "smoke": ("本机跑 _tools/ops/_prod_smoke.py --readonly --json <tmp>",
              "**ERROR 0 条** 且 **没有未批准的 WARN**（已批准的告警可以存在，但必须带理由；"
              "「与这一版不一致」永远是 ERROR）",
              "有健康类 ❌ → 回滚（2）；有一致性类 ❌ → 看是哪几项（1）"),
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


def expected_head() -> int | None:
    """本仓库的**迁移头**（`backend/app/migrations/0*.py` 里最大的 VERSION）。算不出返回 None。

    ⛔ 不 import backend（那要装依赖、还会触发 app 包的一串副作用）—— 直接读文件里的 VERSION。
    ⛔ 算不出**不许**当成 0（G4）：调用方拿到 None 必须判失败。
    """
    d = ROOT / "backend" / "app" / "migrations"
    vs: list[int] = []
    for p in sorted(d.glob("0*.py")):
        m = re.search(r"^VERSION\s*=\s*(\d+)", p.read_text(encoding="utf-8", errors="replace"), re.M)
        if m:
            vs.append(int(m.group(1)))
    return max(vs) if vs else None


def verify_verdict(st: dict, head: int | None) -> tuple[bool, str]:
    """**纯函数**：`status --json` 的结论 + 本仓库迁移头 ⇒ (过不过, 一句话)。

    ⛔ 为什么要抽成纯函数：原来的判据是「输出里必须有『待跑：0 条』」——
    而 `status` **只在有待跑的时候才打那一行**（`if st["pending"]:`），
    于是**迁移跑得越干净，这句话越不出现**，判据必然误报失败。
    2026-09-26 生产 A 阶段实测踩到：库已经 8/8 全应用，判据却说「迁移没跑干净」。
    抽成纯函数 + 进 --selftest，就是为了让「判据从没被真输出验过」这件事不再发生。
    """
    pending = st.get("pending") or []
    drifted = st.get("drifted") or []
    unknown = st.get("unknown_in_db") or []
    current = st.get("current")
    if head is None:
        return False, "算不出本仓库的迁移头 —— 算不出就不许往下走（G4）"
    if pending:
        return False, "还有 " + str(len(pending)) + " 条待跑：不启动服务"
    if drifted:
        return False, "有 " + str(len(drifted)) + " 条**漂移**（库里记录的校验和与文件对不上）：不启动服务"
    if unknown:
        return False, "库里有仓库里没有的版本号 " + str(unknown) + "：不启动服务"
    if current != head:
        return False, ("库里的版本（" + str(current) + "）与本仓库的迁移头（" + str(head)
                       + "）对不上：不启动服务")
    return True, ("当前版本 " + str(current) + " == 本仓库迁移头 " + str(head)
                  + "；待跑 0 / 漂移 0 / 陌生版本 0")


def build_cases() -> list[tuple[str, dict, str, str]]:
    """(说明, decide 的入参, 期望 action, 期望 why 里必须出现的词)。"""
    done3 = {"done": ["backup", "stage", "migrate", "verify"]}
    fresh = {"backup_age_hours": 1.0, "sha_in_repo": True, "sha": "a" * 40}
    return [
        ("G1 不给 --go ⇒ 只打印（哪怕护栏全过）",
         dict(step="start", go=False, facts=fresh, state=done3), "plan", "只打印"),
        ("G2 start 之前没 backup/migrate/verify ⇒ 拒绝",
         dict(step="start", go=True, facts=fresh, state={}), "refuse", "顺序强制"),
        ("G1 计划模式**不需要**生产事实（facts 里没有备份年龄）⇒ 仍然只打印",
         dict(step="start", go=False, facts={"sha_in_repo": True}, state=done3), "plan", "只打印"),
        ("G2 stage 之前没 backup ⇒ 拒绝",
         dict(step="stage", go=True, facts=fresh, state={}), "refuse", "顺序强制"),
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


#: verify_verdict 的用例：(说明, status --json 的结论, 仓库迁移头, 期望过不过, 期望话里必须有的词)
VERIFY_CASES: list[tuple[str, dict, int | None, bool, str]] = [
    ("8/8 全应用、没待跑 ⇒ 过",
     {"current": 8, "applied": [{"version": i} for i in range(1, 9)], "pending": [],
      "drifted": [], "unknown_in_db": []}, 8, True, "待跑 0"),
    ("还有 2 条待跑 ⇒ 不过",
     {"current": 6, "applied": [], "pending": [{"version": 7}, {"version": 8}],
      "drifted": [], "unknown_in_db": []}, 8, False, "还有 2 条待跑"),
    ("有漂移（文件被改过）⇒ 不过",
     {"current": 8, "applied": [], "pending": [],
      "drifted": [{"version": 3}], "unknown_in_db": []}, 8, False, "漂移"),
    ("库里有仓库里没有的版本 ⇒ 不过",
     {"current": 8, "applied": [], "pending": [], "drifted": [], "unknown_in_db": [9]},
     8, False, "仓库里没有的版本号"),
    ("版本对不上仓库（库里 7 / 仓库 8）⇒ 不过",
     {"current": 7, "applied": [], "pending": [], "drifted": [], "unknown_in_db": []},
     8, False, "对不上"),
    ("算不出仓库迁移头 ⇒ 不过（G4 fail-closed）",
     {"current": 8, "applied": [], "pending": [], "drifted": [], "unknown_in_db": []},
     None, False, "算不出"),
]


#: roll_plan / roll_verdict 的用例：(说明, 测哪个, 入参, 期望过不过, 期望话里必须有的词)
ROLL_CASES: list[tuple[str, str, object, bool, str]] = [
    ("roll_plan：一个 unit 都没有 ⇒ 不许瞎猜", "plan", [], False, "没找到"),
    ("roll_plan：两个 unit ⇒ 按名字排序（稳定可复现）", "plan",
     ["sorders-api-b.service", "sorders-api-a.service"], True, "sorders-api-a.service、sorders-api-b.service"),
    ("roll_verdict：没有任何实例结果 ⇒ 不过（算不出事实）", "verdict", [], False, "没有任何实例结果"),
    ("roll_verdict：单实例全绿 ⇒ 过", "verdict", [("u", True, True, True)], True, "全部 1 个实例"),
    ("roll_verdict：两个实例全绿 ⇒ 过", "verdict", [("a", True, True, True), ("b", True, True, True)],
     True, "全部 2 个实例"),
    ("roll_verdict：有一个不是 active ⇒ 不过并点名它", "verdict", [("a", True, True, True), ("b", False, True, True)],
     False, "b 不是 active"),
    ("roll_verdict：health 不是 200 ⇒ 不过", "verdict", [("a", True, False, True)], False, "/health 不是 200"),
    ("roll_verdict：滚动中途入口没有活上游 ⇒ 不过", "verdict", [("a", True, True, False)], False, "活上游"),
]


def selftest() -> int:
    bad = 0
    cases = build_cases()
    for label, kw, want_action, want_word in cases:
        action, why = decide(**kw)
        ok = (action == want_action) and (want_word in why)
        print(("  OK   " if ok else "  BAD  ") + label + " → " + action + "：" + why)
        bad += 0 if ok else 1
    for label, st, head, want_ok, want_word in VERIFY_CASES:
        ok, why = verify_verdict(st, head)
        good = (ok == want_ok) and (want_word in why)
        print(("  OK   " if good else "  BAD  ") + label + " → " + ("过" if ok else "不过") + "：" + why)
        bad += 0 if good else 1
    for label, kind, args, want_ok, want_word in ROLL_CASES:
        if kind == "plan":
            plan, why = roll_plan(args)  # type: ignore[arg-type]
            got_ok = bool(plan) and (plan == sorted(args))
        else:
            got_ok, why = roll_verdict(args)  # type: ignore[arg-type]
        good = (got_ok == want_ok) and (want_word in why)
        print(("  OK   " if good else "  BAD  ") + label + " → " + ("过" if got_ok else "不过") + "：" + why)
        bad += 0 if good else 1
    for s in STEPS:      # ⛔ 自检还要证明「默认不动手」：没有 --go 时任何步骤都只能是 plan
        action, _ = decide(step=s, go=False, facts={"backup_age_hours": 1.0, "sha_in_repo": True}, state={})
        if action != "plan":
            print("  BAD  没有 --go 时步骤 " + s + " 居然不是 plan")
            bad += 1
    total = len(cases) + len(VERIFY_CASES) + len(ROLL_CASES) + len(STEPS)
    print("发布工具护栏自检：" + str(total - bad) + "/" + str(total) + " 通过")
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


def run_stage(sha: str, fetch: bool) -> int:
    """把代码落到 <SHA>，**但不重启服务**（服务继续用它内存里的旧代码）。

    ⛔ 为什么不能省掉这一步：下一步 migrate 跑的是 `python -m app.migrations upgrade`，
    而那个包**来自新代码**。生产第一次升级时它还不存在 ⇒ 先迁移后应用这条纪律会撞在
    「模块不存在」上。G4 在这里同样生效：**核不出生产 HEAD == <SHA> 就不许往下走**。
    """
    pre = ("git -C " + _prodssh.APP_DIR + " fetch origin && " if fetch else "")
    code, out = ssh(pre + "git -C " + _prodssh.APP_DIR + " checkout " + sha)
    print(out[-1200:])
    if code != 0:
        return code
    code, out = ssh("git -C " + _prodssh.APP_DIR + " rev-parse HEAD")
    head = out.strip().splitlines()[-1].strip() if out.strip() else ""
    print("   生产 HEAD = " + (head or "（读不到）"))
    if head != sha:
        print("⛔ 生产 HEAD 与要发布的 SHA 对不上 —— 不继续（算不出事实就不许往前走）")
        return 1
    code, out = ssh("ls -d " + _prodssh.BACKEND_DIR + "/app/migrations")
    print("   迁移包：" + out.strip()[:200])
    if code != 0:
        print("⛔ 落位之后仍然没有 app/migrations —— 下一步（migrate）必然失败，不继续")
        return 1
    return 0


def run_migrate() -> int:
    code, out = ssh("cd " + _prodssh.BACKEND_DIR + " && " + _prodssh.VENV_PY + " -m app.migrations upgrade")
    print(out[-2000:])
    return code


def run_verify() -> int:
    """核结构：拿 `status --json` 的**结论**判，而不是拿一句中文措辞判（见 verify_verdict）。"""
    code, out = ssh("cd " + _prodssh.BACKEND_DIR + " && " + _prodssh.VENV_PY
                    + " -m app.migrations status --json")
    print(out[-2000:])
    if code != 0:
        return code
    try:
        st = json.loads(out[out.index("{"): out.rindex("}") + 1])
    except (ValueError, IndexError):
        print("⛔ 解析不出 status --json 的输出 —— 算不出事实就不许往下走（G4）")
        return 1
    ok, why = verify_verdict(st, expected_head())
    print("   " + ("✅ " if ok else "⛔ ") + why)
    return 0 if ok else 1


def api_units() -> list[str]:
    """**enabled** 的 sorders-api* unit（⛔ 拓扑从系统来，不在这里硬编码 unit 名）。"""
    out = _prodssh.ssh_lines("systemctl list-unit-files 'sorders-api*.service' --state=enabled"
                             " --no-legend 2>/dev/null | awk '{print $1}'")
    return sorted(u.strip() for u in out if u.strip())


def unit_port(unit: str) -> str | None:
    """从 unit 的 ExecStart 里取 `--port N`（⛔ 不硬编码 8111/8112）。算不出返回 None。"""
    out = _prodssh.ssh_lines("systemctl show -p ExecStart --value " + unit)
    m = re.search(r"--port[= ](\d+)", " ".join(out))
    return m.group(1) if m else None


def roll_plan(units: list[str]) -> tuple[list[str], str]:
    """滚动重启的**计划**（纯函数 ⇒ --selftest 直接测）。

    ⛔ 为什么是滚动而不是「一起重启」：生产现在是**两个实例 + nginx upstream**，
    一起重启会出现「两个后端同时不在」，那一瞬间 nginx 就是 `no live upstreams` ——
    等于把这个拓扑唯一的冗余白白丢掉。
    ⛔ 顺序按 unit 名**排序**：稳定、可复现，也不依赖 systemctl 的返回顺序。
    """
    us = sorted(u.strip() for u in units if u.strip())
    if not us:
        return [], "没找到任何 enabled 的 API unit —— 算不出要重启谁，不许瞎猜"
    return us, "滚动重启 " + str(len(us)) + " 个（按名字排序）：" + "、".join(us)


def roll_verdict(results: list[tuple[str, bool, bool, bool]]) -> tuple[bool, str]:
    """(unit, active, health200, nginx_has_live_upstream) 逐实例结果 ⇒ (过不过, 一句话)。纯函数。

    ⛔ 判据是**逐实例的不变量**，不是一个总退出码：重启一个就核一个（active / health / 入口仍可用），
    全部核完才算过。任何一项不成立就点名是哪个 unit 的哪一项 —— 排障时这一点最值钱。
    """
    if not results:
        return False, "没有任何实例结果 —— 算不出事实就不许判过"
    bad = []
    for unit, active, health, nginx_ok in results:
        if not active:
            bad.append(unit + " 不是 active")
        if not health:
            bad.append(unit + " 的 /health 不是 200")
        if not nginx_ok:
            bad.append("重启 " + unit + " 之后，经 nginx 的入口拿不到活上游")
    if bad:
        return False, "；".join(bad[:3])
    return True, ("全部 " + str(len(results)) + " 个实例：active + /health 200 + 滚动全程 nginx 都有活上游")


def run_start(sha: str, fetch: bool) -> int:
    """滚动重启**所有 enabled 的 API unit**（⛔ 不是重启某一个写死的 unit）。

    2026-09-26 B 段把生产从「一个 unit 两个 worker（:8000）」换成「两个 unit :8111/:8112 + nginx upstream」，
    而这一步原来写死 `systemctl restart sorders-api` —— 拓扑一变，它就**在重启一个已经停用的 unit**：
    命令会「成功」返回、`is-active` 却不是 active。那是**发布控制面自己的契约漂移**，必须先消掉。
    """
    pre = ("git -C " + _prodssh.APP_DIR + " fetch origin && " if fetch else "")
    code, out = ssh(pre + "git -C " + _prodssh.APP_DIR + " checkout " + sha)
    print(out[-1200:])
    if code != 0:
        return code
    code, head = ssh("git -C " + _prodssh.APP_DIR + " rev-parse HEAD")
    head = head.strip().splitlines()[-1].strip() if head.strip() else ""
    if head != sha:                                   # G4：对不上就不许往下走
        print("⛔ 生产 HEAD（" + (head or "读不到") + "）≠ 要发布的 SHA —— 不重启")
        return 1

    units, why = roll_plan(api_units())
    print("   拓扑：" + why)
    if not units:
        return 1
    results: list[tuple[str, bool, bool, bool]] = []
    for idx, unit in enumerate(units, 1):
        port = unit_port(unit)
        print("   [" + str(idx) + "/" + str(len(units)) + "] 重启 " + unit
              + "（端口 " + str(port or "?") + "）")
        _, out = ssh("systemctl restart " + unit + " && sleep 3 && systemctl is-active " + unit)
        tail = out.strip().splitlines()[-1].strip() if out.strip() else ""
        active = tail == "active"
        health = False
        if port:
            _, hout = ssh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:" + port + "/health")
            health = hout.strip().endswith("200")
            print("        is-active=" + (tail or "?") + " ｜ /health=" + hout.strip()[-3:])
        else:
            print("        is-active=" + (tail or "?") + " ｜ ⛔ 读不出端口，健康检查跳过")
        # ⛔ 每重启一个就核一次**入口仍有活上游** —— 这正是滚动重启的意义
        _, nout = ssh("curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/api/v1/orders")
        nginx_ok = nout.strip()[-3:] in ("200", "401", "403")
        print("        经 nginx 入口：" + nout.strip()[-3:] + "（"
              + ("有活上游" if nginx_ok else "⛔ 没有可用上游") + "）")
        results.append((unit, active, health, nginx_ok))
    ok, verdict = roll_verdict(results)
    print("   " + ("✅ " if ok else "⛔ ") + verdict)
    return 0 if ok else 1


def run_smoke() -> int:
    """只读烟测：判据是「**❌ 的项 0 条**」，⛔ 不是「退出码必须是 0」。

    为什么不用退出码：`_prod_smoke.py` 的「1」档**同时**装着两件性质不同的事 ——
    ①「生产与这一版代码不一致」（发布要消除的）与 ②「有 warn_only 的**既知告警**」
    （Redis 无口令 / MySQL 服务端默认时区 —— 那两件都不属于发布这一步，各有各的许可）。
    要求退出码 0 等于要求「顺手把已知缺口也修掉」，而那正是 A 阶段明令**不许**做的事。
    ⇒ 拿 `--json` 的逐行 level 判：**fail 一条都不许有**；warn 如实打印并留档。
    ⛔ G4 同样生效：读不出 json 就算不出事实，不许得出「大概没事」的结论。
    """
    out_json = Path(tempfile.gettempdir()) / "sorders_r3_smoke.json"
    try:
        out_json.unlink()
    except OSError:
        pass
    code = run_local_script("_tools/ops/_prod_smoke.py", ["--readonly", "--json", str(out_json)])
    try:
        payload = json.loads(out_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 读不出就判失败，不许猜
        print("⛔ 烟测没有写出 --json 结果（退出码 " + str(code) + "）—— 算不出事实就不许往下走")
        return 1
    rows = payload.get("rows") or []
    errs = payload.get("errors") or [r.get("name") for r in rows if r.get("level") == "fail"]
    unapproved = payload.get("unapproved_warns") or []
    approved = payload.get("approved_warns") or []
    # ⛔ **A5 的语义（用户 2026-09-26 拍板）**：通过 = **ERROR 0 条** 且 **没有未批准的 WARN**。
    #    「已登记、明确接受的告警」可以存在，但它们必须**带着批准理由**出现，⛔ 不许伪装成成功；
    #    而「与当前发布版本不一致」那一类**永远是 ERROR**（在 _prod_smoke 里就没有 warn_only 这一档）。
    if errs or unapproved:
        print("⛔ 烟测不通过：ERROR " + str(len(errs)) + " 条" +
              ("，其中**未批准的告警** " + str(len(unapproved)) + " 条" if unapproved else "") +
              "：" + "；".join(str(x) for x in (errs or unapproved)[:3]))
        bad = [r for r in rows if r.get("level") == "fail"]
        return 2 if any(r.get("category") == "health" for r in bad) else 1
    print("   ✅ ERROR 0 条、未批准告警 0 条；已批准告警 " + str(len(approved)) + " 条（都带理由）："
          + "；".join(str(w.get("name")) for w in approved[:4]))
    return 0


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
        print("  本机 HEAD：" + sha[:12] + "（--sha 可覆盖；--all 会按顺序走完**八**步）")
        return 0

    state = load_state()
    for step in todo:
        facts: dict = {"sha": sha, "sha_in_repo": repo_sha_ok(sha)}
        if step == "start" and a.go:
            # ⛔ 计划模式**不连生产**：G1 说「不给 --go 绝不执行任何一步」，而读一次备份年龄要 SSH。
            #    2026-09-26 实测：原来不判 a.go，于是 `--step start`（只打印）也会去 SSH ——
            #    后果是「只打印」这个模式**依赖生产可达**（CI 上跑不了，台账里也就没法把它写成复现命令）。
            #    decide() 的第一条就是 `if not go: return "plan"`，所以计划模式下这个事实根本用不到。
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
        elif step == "stage":
            code = run_stage(sha, fetch=not a.no_fetch)
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
            code = run_smoke()
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
