#!/usr/bin/env python3
"""_drill.py —— 生产故障演练（R3-06）：五个演练，一条命令（方案见 docs/R3_FAILURE_DRILL.md）。

### 它回答的问题
指南 §十九：不能只验证「正常时能不能跑」，还要验证「**故障时能不能恢复**」：
A 杀掉一个 worker（worker）｜B Redis 不可用（redis）｜C 事件消费者延迟（event）｜
D 迁移锁竞争（lock）｜E 磁盘将满（disk）。

### 四条纪律（写在**代码里**，⛔ 不靠记性）
G1 **默认只打印**：不给 --go 一律不执行任何东西。
G2 **默认目标是本机**：要动生产必须同时给三个信号 —— --target prod **和** --go **和** --i-know-prod；
   缺一个就拒绝（本仓库对「顺手在生产上试一下」是有过教训的）。
G3 **算不出事实就拒绝**（fail-closed）。
G4 **本机跑不了的那一格如实报 NOT RUN**：⛔ 不许把「没跑」写成「通过」（本项目的老账：永远绿的检查＝没有检查）。
   ⚠️ 因此：生产那三格（Redis 停掉 / 事件延迟 / 磁盘将满）在本工具里**只打印过程与判据**，不代跑 ——
   它们要么会停掉线上服务，要么要往磁盘里写垃圾文件，必须人按方案逐条做并留痕。

### 与台账的关系
台账 R3-06 的五条退出条件要的是**生产**演练的结果；本工具能自动化的是**本机预演**与**过程固化**，
所以五条**仍然是 ❌**，直到真的在生产上做过（要写许可）。

用法：
    python _tools/ops/_drill.py --list                  # 五个演练：目的 / 期望 / 本机能跑到哪一步
    python _tools/ops/_drill.py --selftest              # 护栏自检（假事实，⛔ 不连生产）
    python _tools/ops/_drill.py --case lock-contention --go      # 本机真跑（两个进程同时迁移）
    python _tools/ops/_drill.py --case worker-crash   --go      # 本机真跑（两实例 + 杀掉 A + 验 B）
    python _tools/ops/_drill.py --case redis-down     --go      # 本机真跑（本机没有 Redis ⇒ 现场就是它）
    python _tools/ops/_drill.py --case event-delay    --go      # 本机真跑（入队→堆积→追平→不重复）
    python _tools/ops/_drill.py --case disk-full      --go      # 本机只能证阈值判得对（生产那格 NOT RUN）
    python _tools/ops/_drill.py --case redis-down --target prod --go --i-know-prod   # ⛔ 只打印过程
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prodssh  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

CASES: tuple[str, ...] = ("worker-crash", "redis-down", "event-delay", "lock-contention", "disk-full")


def _p(*parts: str) -> str:
    return str(ROOT.joinpath(*parts))


#: 每个演练：(目的, 期望信号, 本机怎么跑, 本机能跑到哪一步, 生产怎么跑)
CASE_DOC: dict[str, tuple[str, str, str, str, str]] = {
    "worker-crash": (
        "杀掉一个 worker，服务是否恢复",
        "① 另一路请求不中断（/health 连续 200）② systemd/uvicorn 监督把 worker 补回来 ③ 被杀的 worker 上在飞的请求会有失败（如实记条数）",
        "python _tools/ops/_dual_instance.py --kill（两个真实例 + 杀掉 A + 验 B 继续服务）",
        "**本机真跑**（但形态不同：本机是**两个独立进程**，生产是**一个 systemd 里两个 worker** —— ⛔ 不能互相顶替）",
        "pgrep -f uvicorn app.main → kill -9 其中一个；盯 journalctl -u " + _prodssh.SERVICE + " -f；再打 /health",
    ),
    "redis-down": (
        "Redis 不可用，业务还能不能工作",
        "① /health 里 redis 字段变红但接口仍可用 ② 下单/派单/账本读写全部正常（业务不经过 Redis）",
        "本机**根本没有 Redis** ⇒ 现场本身就是「Redis 不可用」：先打印 redis_ok()，再跑业务用例（订单流 + 账本同步）",
        "**本机真跑**（证的是「架构上不依赖 Redis」；生产那一格仍要演练）",
        "systemctl stop redis → 打 /health 与几笔真实业务 → systemctl start redis（⛔ 必须放回 finally）",
    ),
    "event-delay": (
        "事件消费者延迟，业务数据是否仍然正确",
        "① 业务写入照常成功（先落库后投递）② outbox_events 里 pending 堆起来但不丢 ③ 消费者恢复后追平，且不重复投递",
        "临时库 + prepare_schema：入队 → 断言堆着 pending → dispatch_sync 抽干 → 断言 pending=0 且已发条数等于入队条数 → 再抽一次断言不重复",
        "**本机真跑**（证的是发件箱语义；「业务数据在延迟期间仍然正确」由 R3-04 用例与全量用例在本机证）",
        "生产还没有 outbox_events 表（这一版代码没上生产）⇒ ⛔ 这一格只能**发布之后**验",
    ),
    "lock-contention": (
        "迁移锁竞争，第二实例是否正常等待",
        "两个进程最终都成功；每个版本在 schema_versions 里恰好一行；没有 table already exists",
        "python _tools/ops/_migration_tests.py --concurrent（R3-01 的并发迁移用例）",
        "**本机真跑**（本机是 SQLite：证的是**本机互斥**；生产是 MySQL GET_LOCK，跨主机那条路**从未在生产上真跑过**）",
        "生产上只能靠发布时两个实例同时启动来验 —— 本工具不代跑（会动库）",
    ),
    "disk-full": (
        "磁盘将满，能否被发现",
        "① >85% 给出**告警**、>95% 给出**失败**（退出码 1 / 2）② 这条告警真的有人收到",
        "读 _health_check.py 的阈值常量并逐档断言映射（50→ok / 90→warn / 96→fail）+ 打印当前实测占用",
        "**部分**：本机能证的只有「阈值判得对」；「报警链路有人收到」⛔ 本机证不了",
        "造占位大文件把使用率推到 90%+ → 跑 _tools/ops/_health_check.py → 看退出码与告警（⛔ 这确实是写操作）",
    ),
}


def decide(case: str, target: str, go: bool, i_know_prod: bool) -> tuple[str, str]:
    """**纯函数**：这一次该「打印」「拒绝」「本机真跑」还是「打印生产过程」。

    返回 (action, why)，action ∈ {"plan", "refuse", "run-local", "print-prod"}。
    ⛔ 这里一行副作用都没有 —— --selftest 直接测它。
    """
    if case not in CASES:
        return "refuse", "不认识的演练：" + case + "（只有 " + "、".join(CASES) + "）"
    if target not in ("local", "prod"):
        return "refuse", "不认识的目标：" + target + "（只有 local / prod）"
    if target == "prod":                                              # G2
        if not go:
            return "plan", "没给 --go：只打印，不执行"
        if not i_know_prod:
            return "refuse", ("要动生产必须同时给 --target prod、--go、--i-know-prod 三个信号 —— "
                              "缺 --i-know-prod（这一条是故意的：本仓库对「顺手在生产上试一下」有过教训）")
        return "print-prod", "生产演练只打印过程与判据（⛔ 本工具不代跑生产）"
    if not go:                                                        # G1
        return "plan", "没给 --go：只打印，不执行"
    return "run-local", "本机真跑"


def build_cases() -> list[tuple[str, dict, str, str]]:
    """(说明, decide 的入参, 期望 action, 期望 why 里必须出现的词)。"""
    return [
        ("G1 不给 --go（本机）⇒ 只打印",
         dict(case="redis-down", target="local", go=False, i_know_prod=False), "plan", "只打印"),
        ("G1 不给 --go（生产）⇒ 也只打印",
         dict(case="redis-down", target="prod", go=False, i_know_prod=True), "plan", "只打印"),
        ("G2 --target prod + --go 但没 --i-know-prod ⇒ 拒绝",
         dict(case="redis-down", target="prod", go=True, i_know_prod=False), "refuse", "三个信号"),
        ("G2 生产三个信号齐了 ⇒ 只打印过程（不代跑）",
         dict(case="redis-down", target="prod", go=True, i_know_prod=True), "print-prod", "不代跑"),
        ("本机 + --go ⇒ 真跑",
         dict(case="lock-contention", target="local", go=True, i_know_prod=False), "run-local", "真跑"),
        ("不认识的演练 ⇒ 拒绝",
         dict(case="reboot", target="local", go=True, i_know_prod=False), "refuse", "不认识的演练"),
        ("不认识的目标 ⇒ 拒绝",
         dict(case="redis-down", target="staging", go=True, i_know_prod=True), "refuse", "不认识的目标"),
    ]


def selftest() -> int:
    bad = 0
    cases = build_cases()
    for label, kw, want_action, want_word in cases:
        action, why = decide(**kw)
        ok = (action == want_action) and (want_word in why)
        print(("  OK   " if ok else "  BAD  ") + label + " → " + action + "：" + why)
        bad += 0 if ok else 1
    for c in CASES:      # ⛔ 自检还要证明「默认不动手」：没有 --go 时五个演练都只能是 plan
        action, _ = decide(case=c, target="local", go=False, i_know_prod=False)
        if action != "plan":
            print("  BAD  没有 --go 时演练 " + c + " 居然不是 plan")
            bad += 1
    print("演练工具护栏自检：" + str(len(cases) + len(CASES) - bad) + "/" + str(len(cases) + len(CASES)) + " 通过")
    return 1 if bad else 0
# ------------------------------------------------------------------ 本机真跑（只有 --go 才走到这儿）
def _run(cmd: list[str], cwd: Path | None = None) -> int:
    print("  → " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=str(cwd or ROOT)).returncode


EVENT_DELAY_SCRIPT = """
import os, sys, tempfile
d = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = 'sqlite:///' + d.replace(os.sep, '/') + '/m.db'
sys.path.insert(0, '.')
from app.database import engine, SessionLocal
from app.core.schema_bootstrap import prepare_schema
prepare_schema(engine)
from app.core import outbox
db = SessionLocal()
n = 0
for i in range(3):
    if outbox.enqueue(db, 'orders.created', {'order_id': 1000 + i}):
        n += 1
db.commit()
st = outbox.outbox_stats(db)
waiting = st.get('pending', -1)
print('  1) 入队 ' + str(n) + ' 条；消费者还没跑 -> pending = ' + str(waiting) + '（堆着但不丢）')
got = []
res = outbox.dispatch_sync(db, got.append, limit=10)
after = outbox.outbox_stats(db).get('pending', -1)
res2 = outbox.dispatch_sync(db, got.append, limit=10)
print('  2) 消费者恢复：dispatched=' + str(res) + ' -> pending=' + str(after) + '，收到=' + str(len(got)))
print('  3) 再抽一次（不许重复投递）：' + str(res2))
ok = (n == 3) and (waiting == 3) and (after == 0) and (len(got) == 3) and (int(res2.get('sent', 9)) == 0)
print('  结论：' + ('通过（先落库后投递 / 追平 / 不重复）' if ok else '不通过'))
sys.exit(0 if ok else 1)
"""

DISK_SCRIPT = """
import shutil, sys
sys.path.insert(0, '.')
import _health_check as h

def level(pct):
    return 'fail' if pct >= h.DISK_FAIL_PCT else ('warn' if pct >= h.DISK_WARN_PCT else 'ok')

bad = 0
for pct, want in ((50, 'ok'), (85, 'warn'), (90, 'warn'), (95, 'fail'), (99, 'fail')):
    got = level(pct)
    print('  ' + str(pct).rjust(3) + '% -> ' + got + '（期望 ' + want + '）')
    bad += 0 if got == want else 1
u = shutil.disk_usage('.')
print('  本机磁盘实测：' + str(round(u.used / u.total * 100)) + '% 已用；阈值 = '
      + str(h.DISK_WARN_PCT) + ' / ' + str(h.DISK_FAIL_PCT))
sys.exit(1 if bad else 0)
"""


def _run_inline(code: str, cwd: Path, title: str) -> int:
    p = Path(tempfile.gettempdir()) / ("sorders_drill_" + title + ".py")
    p.write_text(code, encoding="utf-8", newline="")
    print("  → python " + str(p) + "（cwd=" + str(cwd) + "）")
    return subprocess.run([sys.executable, str(p)], cwd=str(cwd)).returncode


def run_local(case: str) -> int:
    """五个演练的**本机部分**（⛔ 每一格都如实说明它证到了什么、没证到什么）。"""
    if case == "worker-crash":
        print("  ⚠️ 本机证到的是「两个独立进程里杀掉一个、另一个继续服务」；" 
              "⛔ 生产那格是「一个 systemd 里两个 worker」，两者形态不同、不许互顶。")
        return _run([sys.executable, _p("_tools", "ops", "_dual_instance.py"), "--kill"])
    if case == "lock-contention":
        print("  ⚠️ 本机是 SQLite（证的是本机互斥）；生产是 MySQL GET_LOCK（跨主机），那条路从未在生产上真跑过。")
        return _run([sys.executable, _p("_tools", "ops", "_migration_tests.py"), "--concurrent"])
    if case == "redis-down":
        print("  1) 本机 Redis 状态：")
        code = _run([sys.executable, "-c",
                     "import sys; sys.path.insert(0, '.'); from app.redis_client import redis_ok;"
                     " print('     redis_ok() =', redis_ok())"], cwd=BACKEND)
        if code != 0:
            return code
        print("  2) Redis 不可用时，业务用例（订单流 + 账本同步）能不能过：")
        return _run([sys.executable, "-m", "pytest", "tests/test_orders_flow.py",
                     "tests/test_ledger_sync.py", "-q"], cwd=BACKEND)
    if case == "event-delay":
        print("  ⚠️ 本机证到的是**发件箱语义**（先落库后投递 / 追平 / 不重复）；" 
              "「业务数据在延迟期间仍然正确」由 R3-04 用例与本机全量用例证。")
        return _run_inline(EVENT_DELAY_SCRIPT, BACKEND, "event_delay")
    if case == "disk-full":
        print("  ⚠️ 本机**只能证「阈值判得对」**；「报警链路真的有人收到」本机证不了（⛔ 那要生产）。")
        return _run_inline(DISK_SCRIPT, ROOT / "_tools" / "ops", "disk")
    return 1


def print_prod(case: str) -> None:
    """生产演练：**只打印**过程与判据（⛔ 本工具不代跑生产）。"""
    purpose, expect, _local, _reach, prod = CASE_DOC[case]
    print("  目的：" + purpose)
    print("  期望信号：" + expect)
    print("  生产怎么做：" + prod)
    print("  ⛔ 本工具**不代跑**生产（停服务 / 断 Redis / 塞磁盘都会影响线上）：请人按 "
          "docs/R3_FAILURE_DRILL.md 的「手动等价」列逐条做，并把原始输出贴进台账。")
    print("  ⛔ 演练前先备份：python _tools/backup/_pre_release.py --note \"R3-06 演练前\"")
    print("  ⛔ 演练完把服务放回原样并复跑：python _tools/ops/_health_check.py 与 "
          "python _tools/ops/_prod_smoke.py --readonly")


def print_list() -> None:
    print("五个演练（方案：docs/R3_FAILURE_DRILL.md；台账 R3-06 五条退出条件要的是**生产**结果）：")
    for c in CASES:
        purpose, expect, local, reach, prod = CASE_DOC[c]
        print("")
        print("  " + c)
        print("    目的：" + purpose)
        print("    期望：" + expect)
        print("    本机：" + local)
        print("    本机能到哪一步：" + reach)
        print("    生产：" + prod)


def main() -> int:
    ap = argparse.ArgumentParser(description="生产故障演练（默认只打印；本机只在 --go 时真跑）")
    ap.add_argument("--case", choices=list(CASES), help="要跑哪个演练")
    ap.add_argument("--target", choices=["local", "prod"], default="local",
                    help="目标（缺省 local —— ⛔ 要动生产必须显式写 prod）")
    ap.add_argument("--go", action="store_true", help="⛔ 真的执行（没有它一律只打印）")
    ap.add_argument("--i-know-prod", action="store_true", help="确认知道这一步会动生产（与 --target prod 同时给才有效）")
    ap.add_argument("--all-local", action="store_true",
                    help="把五个演练的**本机部分**依次真跑一遍（⛔ 要几分钟；跑不了的那格会明说）")
    ap.add_argument("--list", action="store_true", help="列出五个演练")
    ap.add_argument("--selftest", action="store_true", help="护栏自检（假事实，不连生产）")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.all_local:
        if not a.go:                                          # G1 对 --all-local 同样成立
            print("没给 --go：只打印。五个本机预演分别是：")
            for c in CASES:
                print("  python _tools/ops/_drill.py --case " + c + " --go")
            return 0
        bad: list[str] = []
        for c in CASES:
            print("")
            print("== " + c + "（本机预演）")
            code = run_local(c)
            if code != 0:
                bad.append(c)
        print("")
        print("本机预演：" + str(len(CASES) - len(bad)) + "/" + str(len(CASES)) + " 通过"
              + ("" if not bad else "，不通过：" + "、".join(bad)))
        print("⛔ 这一行**不是** R3-06 的完成证据：那五条要的是**生产**演练的结果（要写许可）。")
        return 1 if bad else 0
    if a.list or not a.case:
        print_list()
        return 0

    action, why = decide(case=a.case, target=a.target, go=a.go, i_know_prod=a.i_know_prod)
    print("演练 " + a.case + "（目标 " + a.target + "）：" + why)
    if action == "refuse":
        return 1
    if action == "plan":
        purpose, expect, local, reach, prod = CASE_DOC[a.case]
        print("  目的：" + purpose)
        print("  期望信号：" + expect)
        print("  本机怎么做：" + local + "（" + reach + "）")
        print("  生产怎么做：" + prod)
        print("  ⛔ 没给 --go：什么都没跑。")
        return 0
    if action == "print-prod":
        print_prod(a.case)
        return 0
    code = run_local(a.case)
    print(("✅ 本机部分通过" if code == 0 else "❌ 本机部分不通过（退出码 " + str(code) + "）")
          + " —— ⛔ 这不等于生产那一格验过了：台账 R3-06 五条仍是 ❌。")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
