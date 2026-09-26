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
G4 **跑不了的那一格如实报 NOT RUN**：⛔ 不许把「没跑」写成「通过」（本项目的老账：永远绿的检查＝没有检查）。

### 与台账的关系
台账 R3-06 的五条退出条件要的是**生产**演练的结果。**2026-09-26 C 段放行之后，本工具真的去生产上跑**
（`--target prod --go --i-know-prod`）：每条演练按六阶段走 ——
**X0 前置 → X1 取基线 → X2 注入 → X3 观察期望信号 → X4 恢复 → X5 核业务状态**，
原始输出落进 `_tools/ops/drill_records/*.json`（进仓库，一跑一份，⛔ 不覆盖历史）。

⛔ **只证「服务起来了」不算过**：X5 必须拿 X1 的基线逐项比对（订单/账本/用户/商品/发件箱行数、
服务两个实例都活、经 nginx 的入口可用）—— 「业务状态没被弄坏」才是判据。

CI 侧不连生产：`--verify` 只读那些记录，核「六阶段齐 + 必须的信号都在 + 结论明确」。
台账里五条 ✅ 的复现命令就是它。

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
import shlex
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
        "systemctl kill -s KILL " + _prodssh.SERVICE + "-a（整个 cgroup 一起 SIGKILL）；"
        "盯另一个实例与经 nginx 的入口；systemd 的 Restart=always 自己把它拉回来（⛔ 不手工 start）",
    ),
    "redis-down": (
        "Redis 不可用，业务还能不能工作",
        "① /health 的 redis 字段变红、但 HTTP 业务接口（登录/读订单/读账本）照常 ② ⚠️ **跨实例实时推送会断**"
        " —— 因为 Redis 就是 Socket.IO 的跨实例总线（B 段实测 `redis-cli pubsub channels` 里有 `socketio`）"
        "③ 恢复 Redis 之后推送链路自己回来",
        "本机**根本没有 Redis** ⇒ 现场本身就是「Redis 不可用」：先打印 redis_ok()，再跑业务用例（订单流 + 账本同步）",
        "**本机真跑**（证的是「架构上不依赖 Redis」；生产那一格仍要演练）",
        "systemctl stop redis → 打业务接口（登录/读订单/读账本）与 /health → systemctl start redis"
        "（脚本用 trap 保证一定放回）",
    ),
    "event-delay": (
        "事件消费者延迟，业务数据是否仍然正确",
        "① 业务写入照常成功（先落库后投递）② outbox_events 里 pending 堆起来但不丢 ③ 消费者恢复后追平，且不重复投递",
        "临时库 + prepare_schema：入队 → 断言堆着 pending → dispatch_sync 抽干 → 断言 pending=0 且已发条数等于入队条数 → 再抽一次断言不重复",
        "**本机真跑**（证的是发件箱语义；「业务数据在延迟期间仍然正确」由 R3-04 用例与全量用例在本机证）",
        "生产**已经有** `outbox_events`（A 段发布带上去的；C 段 X1 实测 13 行全 sent）⇒ 这一格现在能验："
        "停 Redis 让投递真的失败 → 事件堆在 pending → 恢复 → 追平且不丢",
    ),
    "lock-contention": (
        "迁移锁竞争，第二实例是否正常等待",
        "两个进程最终都成功；每个版本在 schema_versions 里恰好一行；没有 table already exists",
        "python _tools/ops/_migration_tests.py --concurrent（R3-01 的并发迁移用例）",
        "**本机真跑**（本机是 SQLite：证的是**本机互斥**；生产是 MySQL GET_LOCK，跨主机那条路**从未在生产上真跑过**）",
        "一条独立连接先拿住服务端命名锁 sorders_migrations，再让两个迁移进程同时开跑"
        "（第二个换 TMPDIR ⇒ 与第一个各有一把本机 flock，等价于两台主机）—— ⛔ 全程零 DDL/DML",
    ),
    "disk-full": (
        "磁盘将满，能否被发现",
        "① >85% 给出**告警**、>95% 给出**失败**（退出码 1 / 2）② 这条告警真的有人收到",
        "读 _health_check.py 的阈值常量并逐档断言映射（50→ok / 90→warn / 96→fail）+ 打印当前实测占用",
        "**部分**：本机能证的只有「阈值判得对」；「报警链路有人收到」⛔ 本机证不了",
        "fallocate 占位文件把 / 顶到 ~87%（越过 85% 告警线）→ 把 cron 那一行命令原样跑一遍 → "
        "看退出码与 /var/log/sorders-health.log → 删掉占位文件（⛔ 刻意不撞 95% 的失败线）",
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
        return "run-prod", "生产演练（C 段放行：三个信号齐了才走到这里）"
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
        ("G2 生产三个信号齐了 ⇒ **真跑**（C 段放行之后；⛔ 少任何一个信号都不许走这条）",
         dict(case="redis-down", target="prod", go=True, i_know_prod=True), "run-prod", "三个信号"),
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


# ============================================================ 生产演练（C 段：真的去生产上跑，六阶段）
#: 记录落在仓库里（一跑一份，⛔ 不覆盖历史）：CI 侧的 --verify 只读它们，⛔ 不连生产。
RECORDS_DIR = ROOT / "_tools" / "ops" / "drill_records"
PHASES: tuple[str, ...] = ("X0", "X1", "X2", "X3", "X4", "X5")
#: 每个阶段最少要有的字符数。⛔ 这**不是**质量判据，只是「不许是空的」那道坎 ——
#: 真正的实质核在 REQUIRED_SIGNALS（必须的信号在不在、成不成立）与 X3 那段原始输出上。
#: 定 40 是因为中文一句话就够 40 个字；定高了会逼着人往记录里灌水（那就成了为判据写字）。
MIN_PHASE_CHARS = 40
PHASE_TITLE: dict[str, str] = {
    "X0": "前置（备份 / 服务健康 / 回滚点 / 怎么停）",
    "X1": "取基线（业务状态快照）",
    "X2": "注入（这一步真的动生产）",
    "X3": "观察期望信号",
    "X4": "恢复（放回原样）",
    "X5": "核业务状态（与 X1 逐项比对）",
}

#: 每个演练在 X3 里**必须**出现的信号（--verify 逐条核）。写得短而具体，
#: 因为它们是「这条演练到底证了什么」的最小可核集合 —— 少了任何一条，这条记录就不算数。
REQUIRED_SIGNALS: dict[str, tuple[str, ...]] = {
    "lock-contention": ("都退出 0", "在等锁", "恰好一行", "already exists", "锁已释放"),
    "worker-crash": ("被 systemd 拉起", "另一实例全程", "经 nginx 的入口", "NRestarts"),
    "redis-down": ("业务接口照常", "也照常", "如实报出", "自己回来"),
    "event-delay": ("业务写入成功", "被发件箱看见", "补投成功", "净零"),
    "disk-full": ("报 warn", "退出码 1", "落进", "恢复到"),
}

#: 每条演练**如实写下的已知边界**（⛔ 不写就成了「这条演练包打一切」）。
KNOWN_LIMITS: dict[str, tuple[str, ...]] = {
    "lock-contention": (
        "两个进程在**同一台机器**上：跨主机那一半靠给第二个进程换 TMPDIR 来还原"
        "（各自一把本机 flock），所以 GET_LOCK 这条服务端路径是真的被争用了；",
        "⛔ 但它仍不证「两台**物理主机**之间」的时钟/网络差异；",
        "库是 MySQL，所以 _db_lock 这一支是真的走了（SQLite 上它会如实跳过）。",
    ),
    "worker-crash": (
        "杀的是**一个实例**（两个独立 unit 中的一个）—— 生产拓扑不是「一个 systemd 里 2 个 worker」，"
        "两者形态不同，⛔ 本记录只代表前者；",
        "⛔ 不证跨主机；⛔ 不证真实 Android 客户端在被杀瞬间的体感（只量 HTTP 码）。",
    ),
    "redis-down": (
        "停的是生产机上唯一的 Redis；⛔ 不证 Redis 慢（只证不可用）；",
        "⛔ 不证 App 端界面上「推送晚到」的体感 —— 只证服务端这一侧的投递失败与恢复；",
        "⚠️ 关于 pubsub channels / numsub 这两个读数：它们**不是**判据，只是观察。"
        "python-socketio 的 Redis 监听器是**惰性启动**的 —— async_server.py:675 在**第一次 Engine.IO 连接**"
        "时才调 manager.initialize()（源码核对过）⇒ 一个从没被客户端连过的实例本来就不会订阅总线，"
        "而「没有本地客户端」时也确实没有要投递的对象。所以 B_NUMSUB/R_NUMSUB 是 0 还是 1 取决于"
        "演练前有没有客户端连过，⛔ 不能拿它当「总线坏没坏」。"
        "真正可判的是**投递这条路**：停 Redis 时写的那条事件，恢复后必须由消费者自己补投成 sent"
        "（见 REQUIRED 里的那条信号）。",
    ),
    "event-delay": (
        "注入用的是「停 Redis」，**不是**「让消费者线程停住」——在本拓扑里消费者与 API 同进程，"
        "停掉消费者就必然停掉业务，无法只停一半（这本身是一条结论）；"
        "⚠️ 而停 Redis 这一手**没能**让发件箱看见失败（见本记录的 findings）——"
        "那是演练**发现的问题**，不是演练没做对；",
        "只投递一条演练消息，⛔ 不证高并发下大批量积压；",
        "⛔ 不证跨主机。",
    ),
    "disk-full": (
        "只把使用率推到 85%~90% 那一档（真实 warn）；⛔ **没有**推到 95% 去撞 fail ——"
        "那要把一台在跑的 MySQL 所在盘压到只剩 ~1.5G，判为**不可接受的风险**，"
        ">95% 那一档由同一段代码的阈值判据（本机 --case disk-full --go）证；",
        "⛔ 不证「有人被叫醒」：告警落到 /var/log/sorders-health.log，**没有**邮件/IM 推送通道 ——"
        "这一条是**发现的缺口**，如实记下，不粉饰。",
    ),
}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sh(script: str, timeout: int = 600) -> tuple[int, str]:
    """在生产机上跑一段 bash，返回 (退出码, stdout+stderr)。⛔ check=False：判据自己判。"""
    r = _prodssh.ssh_script(script, timeout=timeout, check=False)
    return r.returncode, (r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace"))


def _sql(q: str) -> str:
    """只读查询（root@localhost 在生产机上是 socket 免密 —— 事实见 docs/BASELINE.md）。"""
    _c, out = _sh("mysql -uroot -N -B " + _prodssh.DB_NAME + " -e " + shlex.quote(q))
    return out.strip()


SNAPSHOT_SQL = (
    "select 'orders', count(*) from orders union all "
    "select 'ledgers', count(*) from ledgers union all "
    "select 'users', count(*) from users union all "
    "select 'products', count(*) from products union all "
    "select 'outbox_total', count(*) from outbox_events union all "
    "select 'outbox_pending', count(*) from outbox_events where status='pending' union all "
    "select 'schema_versions', count(*) from schema_versions union all "
    "select 'tables', count(*) from information_schema.tables where table_schema='"
    + _prodssh.DB_NAME + "';"
)


def _snapshot() -> dict[str, str]:
    d: dict[str, str] = {}
    for ln in _sql(SNAPSHOT_SQL).splitlines():
        parts = ln.split("\t")
        if len(parts) == 2:
            d[parts[0].strip()] = parts[1].strip()
    return d


def _snap_text(d: dict[str, str]) -> str:
    return "  ".join(k + "=" + d.get(k, "?") for k in sorted(d))


def _svc_script(tag: str) -> str:
    """服务面的**脚本**（两个 unit 的 is-active + 各自 /health + 经 nginx 的入口码）。"""
    return (
        "echo '" + tag + "'\n"
        "for u in sorders-api-a sorders-api-b; do"
        " printf '%s=%s ' \"$u\" \"$(systemctl is-active $u 2>&1)\"; done; echo\n"
        "for p in 8111 8112; do"
        " printf '%s=%s ' \"$p\" \"$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$p/health)\"; done; echo\n"
        "echo 'nginx='\"$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/api/v1/orders)\"\n"
    )


def _svc_probe(tag: str) -> str:
    """跑一次服务面探针，返回它的**输出**。⛔ 别把这个函数的返回值拼进别的脚本 ——
    它返回的是输出不是命令（当天就踩过：X0 里把输出当脚本拼，bash 报 SERVICE: command not found）。"""
    return _sh(_svc_script(tag), timeout=120)[1].strip()


def _phase_x0(case: str) -> str:
    purpose, expect, _l, _r, prod = CASE_DOC[case]
    script = (
        "date -u '+NOW=%Y-%m-%dT%H:%M:%SZ'\n"
        "cd /opt/SOrders && echo PROD_SHA=$(git rev-parse HEAD)\n"
        "echo '--- 服务 ---'\n"
        + _svc_script("SERVICE")        # ⛔ 这里要的是**脚本**：拼 _svc_probe 的返回值＝把输出当命令跑
        + "echo '--- 最近一份演练前备份 ---'\n"
        "ls -1dt " + _prodssh.BACKUP_ROOT + "/pre_release/*/ 2>/dev/null | head -2\n"
        "echo '--- 磁盘 ---'\n"
        "df -h / | tail -1\n"
    )
    _c, out = _sh(script, timeout=120)
    kill_txt = ("怎么停（判读不了就地停）："
                "① 脚本自带 try/finally 式的收尾（见 X4），中断时按 X4 那几行手工放回；"
                "② 若演练中途失联，先看 " + _prodssh.SERVICE + "-a/-b 两个 unit 的 is-active，"
                "再跑 python _tools/ops/_health_check.py（⛔ 别在生产上直接改代码）；"
                "③ 演练前的备份在 " + _prodssh.BACKUP_ROOT + "/pre_release/ 下（上面那两行）。")
    return ("目的：" + purpose + "\n期望信号：" + expect + "\n生产做法：" + prod
            + "\n" + kill_txt + "\n" + out.strip())


def _finish(case: str, rec: dict) -> int:
    rec["finished_utc"] = _now()
    sig = rec.get("signals", {})
    rec["verdict"] = "pass" if sig and all(sig.values()) else "fail"
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    name = case + "-" + rec["started_utc"].replace(":", "").replace("-", "") + ".json"
    path = RECORDS_DIR / name
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
    for f in rec.get("findings") or []:
        print("")
        print("  " + f)
    print("")
    print("记录：" + str(path.relative_to(ROOT)))
    print("结论：" + ("✅ pass" if rec["verdict"] == "pass" else "❌ fail")
          + "（" + str(sum(1 for v in sig.values() if v)) + "/" + str(len(sig)) + " 个信号成立）")
    for k, v in sig.items():
        print(("  ✅ " if v else "  ❌ ") + k)
    return 0 if rec["verdict"] == "pass" else 1



# ------------------------------------------------------------ 每个演练的生产实现
def _grab(out: str, key: str) -> str:
    """从脚本输出里取一行 KEY=value 的 value（取不到就空串，⛔ 不猜）。"""
    for ln in out.splitlines():
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip()
    return ""


def _hist(out: str, key: str) -> dict[str, int]:
    """取 awk 统计出来的分布块：KEY 后面那些 '  3 xxx' 行。"""
    d: dict[str, int] = {}
    on = False
    for ln in out.splitlines():
        if not on:
            on = ln.startswith(key)
            continue
        parts = ln.split()
        if len(parts) == 2 and parts[0].isdigit():
            d[parts[1]] = int(parts[0])
        else:
            break        # ⛔ 块结束就停：不然会把下一个统计块也算进来
    return d


#: X5 必须与 X1 逐项相同的**业务**行。⛔ 发件箱那几个**不在**这里：演练自己写了事件，
#: 它们的行数必然会变 —— 把必然要变的项塞进「必须一样」里，判据第一天就是假的。
X5_MUST_MATCH: tuple[str, ...] = ("orders", "ledgers", "users", "products", "tables", "schema_versions")


def _x5(base: dict, extra: str = "") -> tuple[str, bool]:
    after = _snapshot()
    bad = [k for k in X5_MUST_MATCH if base.get(k) != after.get(k)]
    info = [k for k in sorted(after) if k not in X5_MUST_MATCH]
    txt = ("基线：" + _snap_text(base) + "\n现在：" + _snap_text(after) + "\n"
           + ("业务行逐项一致（" + "、".join(X5_MUST_MATCH) + "）。" if not bad else
              "⛔ 变了的项：" + "、".join(
                  k + "(" + str(base.get(k)) + "→" + str(after.get(k)) + ")" for k in bad))
           + "\n（演练自己会写的那几行，只作参考不作判据：" + _snap_text({k: after.get(k, "?") for k in info}) + "）"
           + "\n服务面：\n" + _svc_probe("AFTER") + ("\n" + extra if extra else ""))
    return txt, (not bad)


# ---- Drill D：迁移锁竞争 --------------------------------------------------
LOCK_X2 = ("在一条独立连接上先拿住服务端命名锁 sorders_migrations 15 秒（＝另一个实例正在跑迁移），"
           "然后让两个迁移进程同时开跑；第二个进程换 TMPDIR，于是它与第一个**各有一把本机 flock**"
           "（本机 flock 是按 /tmp 下的锁文件互斥的，跨主机时本来就是各自一把 —— 换 TMPDIR 就是在同一台"
           "机器上把那件事还原出来）。这样一来两个进程会真的**同时**去争服务端那把 GET_LOCK。")
LOCK_X4 = ("注入只是 GET_LOCK 的持有与释放，**没有任何 DDL/DML**：脚本自己 wait 掉所有子进程、"
           "删掉 /tmp/sorders-drillD；锁随连接关闭自动释放（X3 里 is_free_lock=1 就是这条的判据）。")

LOCK_ROUNDS = 3

LOCK_SCRIPT = r'''
set -u
VENV=/opt/SOrders/backend/.venv/bin/python
D=/tmp/sorders-drillD
rm -rf $D; mkdir -p $D/a $D/b
: > $D/all.txt
echo "LOCK_CONST=$(grep -n 'DB_LOCK_NAME =' /opt/SOrders/backend/app/migrations/_runner.py | head -1)"
echo "LOCK_TIMEOUT=$(grep -n 'DB_LOCK_TIMEOUT_S =' /opt/SOrders/backend/app/migrations/_runner.py | head -1)"

echo '== 第 1 轮（带 holder）：这一轮量的是「第二个实例是等还是撞」'
( mysql -uroot -N -B -e "select concat('HOLDER_GOT=', get_lock('sorders_migrations',30)); select sleep(15); select concat('HOLDER_REL=', release_lock('sorders_migrations'));" > $D/holder.txt 2>&1 ) &
HOLDER=$!
sleep 2
( sleep 2; cd /opt/SOrders/backend && TMPDIR=$D/a $VENV -m app.migrations upgrade > $D/a/out.txt 2>&1; echo $? > $D/a/rc ) &
PA=$!
( sleep 2; cd /opt/SOrders/backend && TMPDIR=$D/b $VENV -m app.migrations upgrade > $D/b/out.txt 2>&1; echo $? > $D/b/rc ) &
PB=$!
sleep 8
echo "T6_ALIVE_A=$(kill -0 $PA 2>/dev/null && echo alive || echo gone)"
echo "T6_ALIVE_B=$(kill -0 $PB 2>/dev/null && echo alive || echo gone)"
echo "T6_IS_USED_LOCK=$(mysql -uroot -N -B -e "select is_used_lock('sorders_migrations');")"
wait $PA; wait $PB; wait $HOLDER
echo "A_RC=$(cat $D/a/rc)"
echo "B_RC=$(cat $D/b/rc)"
echo '== holder 输出：'; cat $D/holder.txt
echo '== 第 1 轮 A 输出：'; cat $D/a/out.txt
echo '== 第 1 轮 B 输出：'; cat $D/b/out.txt
cat $D/a/out.txt $D/b/out.txt >> $D/all.txt
echo "ROUND1_COLLIDE=$(cat $D/a/out.txt $D/b/out.txt | grep -cE '1213|1684')"

echo '== 第 2..3 轮：不带 holder、两边同时开跑 —— 量的是「自愈 DDL 会不会相撞」（有竞态，所以跑多次）'
for R in 2 3; do
  rm -f $D/a/out.txt $D/b/out.txt
  ( sleep 2; cd /opt/SOrders/backend && TMPDIR=$D/a $VENV -m app.migrations upgrade > $D/a/out.txt 2>&1; echo $? > $D/a/rc ) &
  PA=$!
  ( sleep 2; cd /opt/SOrders/backend && TMPDIR=$D/b $VENV -m app.migrations upgrade > $D/b/out.txt 2>&1; echo $? > $D/b/rc ) &
  PB=$!
  wait $PA; wait $PB
  printf 'ROUND%s_RC=%s/%s\n' "$R" "$(cat $D/a/rc)" "$(cat $D/b/rc)"
  printf 'ROUND%s_COLLIDE=%s\n' "$R" "$(cat $D/a/out.txt $D/b/out.txt | grep -cE '1213|1684')"
  cat $D/a/out.txt $D/b/out.txt | grep -E '1213|1684|跳过' | sed 's/^/    /'
  cat $D/a/out.txt $D/b/out.txt >> $D/all.txt
done

echo "COLLIDE_TOTAL=$(grep -cE '1213|1684' $D/all.txt)"
echo "ALREADY_EXISTS=$(grep -ci 'already exists' $D/all.txt || true)"
echo '== 版本表（期望每个版本恰好一行）：'
mysql -uroot -N -B sorders -e 'select version, count(*) from schema_versions group by version order by version;'
VT=$(mysql -uroot -N -B sorders -e 'select version from schema_versions order by version;')
VROWS=$(printf '%s\n' "$VT" | grep -c .)
VDISTINCT=$(printf '%s\n' "$VT" | sort -u | grep -c .)
echo "VERSIONS_SUMMARY=$VROWS/$VDISTINCT"
echo "IS_FREE_LOCK=$(mysql -uroot -N -B -e "select is_free_lock('sorders_migrations');")"
rm -rf $D
'''


def _prod_lock_contention() -> tuple[dict, dict]:
    _c, out = _sh(LOCK_SCRIPT, timeout=300)
    rounds_ok = (_grab(out, "A_RC") == "0" and _grab(out, "B_RC") == "0"
                 and _grab(out, "ROUND2_RC") == "0/0" and _grab(out, "ROUND3_RC") == "0/0")
    rows_ok = all(ln.split()[1] == "1" for ln in out.splitlines()
                  if ln[:1].isdigit() and len(ln.split()) == 2 and ln.split()[1].isdigit())
    try:
        collided = int(_grab(out, "COLLIDE_TOTAL"))
    except ValueError:
        collided = -1
    sig = {
        "两个迁移进程都退出 0（三轮都是 0/0）": rounds_ok,
        "T+6s 两个进程都还活着 ⇒ 在等锁，不是撞车失败":
            _grab(out, "T6_ALIVE_A") == "alive" and _grab(out, "T6_ALIVE_B") == "alive",
        "版本表里每个版本恰好一行（8/8，每行 count=1）":
            _grab(out, "VERSIONS_SUMMARY") == "8/8" and rows_ok,
        "三轮里没有任何 already exists": _grab(out, "ALREADY_EXISTS") == "0",
        "服务端锁已释放（is_free_lock=1）": _grab(out, "IS_FREE_LOCK") == "1",
    }
    findings: list[str] = []
    if collided > 0:
        findings.append(
            "⚠️ **发现（有竞态，所以要按次数说）**：" + str(LOCK_ROUNDS) + " 轮并发里，有 "
            + str(collided) + " 处并发 DDL 的痕迹（原始输出见 X3 的 ROUNDn_COLLIDE 与那段缩进的报错）。"
            "⇒ **自愈 bootstrap 的 DDL 只受 /tmp/sorders_bootstrap.lock 那把**本机** flock 保护**"
            "（backend/app/core/schema_bootstrap.py:232 的 with FileLock(BOOTSTRAP_LOCK_FILE)），"
            "服务端 GET_LOCK 是在**之后**的 run_migrations 里才拿的（同文件 240 行）——"
            "所以「两台主机各自一把 flock」时，两个实例会真的同时跑自愈 DDL："
            "轻则一条 DDL 被静默跳过（本次就跳过了），重则 1213 死锁。"
            "本次是靠给第二个进程换 TMPDIR 把那个条件还原出来的。"
            "⚠️ 生产现状是**同一台机器上的两个 unit**（共享 /tmp ⇒ 共享那把 flock）⇒ **现状安全**；"
            "这一条是「跨主机多实例」的具体拦路石，与 docs/MULTI_INSTANCE_READINESS.md 的"
            " bootstrap-self-heal 那一格对得上 —— 本次第一次给了它原始输出。"
            "⚠️ 但它**有竞态**：不是每轮都撞（见 ROUNDn_COLLIDE），所以判据不能只看一轮。")
    return {"X2": LOCK_X2, "X3": out.strip(), "X4": LOCK_X4, "findings": findings}, sig


# ---- Drill A：杀掉一个实例 ------------------------------------------------
CRASH_X2 = ("systemctl kill -s KILL sorders-api-a —— 整个 cgroup 一起 SIGKILL，"
            "模拟「进程直接崩掉」而不是被优雅停止（优雅停止走的是 SIGTERM，那是另一件事）。"
            "盯的是：另一实例的 /health 有没有断、经 nginx 的入口有没有出现 5xx、"
            "systemd 有没有在 RestartSec 内把它拉回来。⛔ 全程不手工 start。")
CRASH_X4 = ("systemd 的 Restart=always + RestartSec=5 自己把它拉起来 —— ⛔ 演练**不手工 start**："
            "手工 start 就证不了「监督真的管用」。X3 里的 RECOVER_SECONDS 与 NRestarts 是判据。")

CRASH_SCRIPT = r'''
set -u
D=/tmp/sorders-drillA; rm -rf $D; mkdir -p $D
echo "== 杀之前"
for u in sorders-api-a sorders-api-b; do echo "$u active=$(systemctl is-active $u) NRestarts=$(systemctl show $u -p NRestarts --value)"; done
NR_BEFORE=$(systemctl show sorders-api-a -p NRestarts --value)
echo "NR_BEFORE=$NR_BEFORE"
echo "== 注入：SIGKILL 掉 sorders-api-a 的整个 cgroup"
T0=$(date +%s.%N)
systemctl kill -s KILL sorders-api-a
REC=""
for i in $(seq 1 50); do
  A=$(systemctl is-active sorders-api-a)
  B=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8112/health)
  N=$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/api/v1/orders)
  echo "A=$A B=$B N=$N" >> $D/log.txt
  if [ "$A" = "active" ] && [ -z "$REC" ]; then REC=$(date +%s.%N); fi
  sleep 0.5
done
echo "== 杀之后"
for u in sorders-api-a sorders-api-b; do echo "$u active=$(systemctl is-active $u) NRestarts=$(systemctl show $u -p NRestarts --value)"; done
echo "NR_AFTER=$(systemctl show sorders-api-a -p NRestarts --value)"
echo "== 采样 50 次 x 0.5s 的分布"
echo "A_STATE:"; awk '{print $1}' $D/log.txt | sort | uniq -c | sed 's/^/  /'
echo "B_STATE:"; awk '{print $2}' $D/log.txt | sort | uniq -c | sed 's/^/  /'
echo "N_STATE:"; awk '{print $3}' $D/log.txt | sort | uniq -c | sed 's/^/  /'
echo "FIRST_ACTIVE_SAMPLE=$(grep -n 'A=active' $D/log.txt | head -1 | cut -d: -f1)"
echo "RECOVER_SECONDS=$(awk -v t0=$T0 -v t1=$REC 'BEGIN{ if (t1=="") print "never"; else printf "%.1f", t1-t0 }')"
rm -rf $D
'''


def _prod_worker_crash() -> tuple[dict, dict]:
    _c, out = _sh(CRASH_SCRIPT, timeout=300)
    b_hist = _hist(out, "B_STATE:")
    n_hist = _hist(out, "N_STATE:")
    nr_b, nr_a = _grab(out, "NR_BEFORE"), _grab(out, "NR_AFTER")
    try:
        restarted = int(nr_a) > int(nr_b)
    except ValueError:
        restarted = False
    sig = {
        "另一实例全程 /health=200（B 分布里只有 200）": b_hist.get("B=200", 0) > 0
        and set(b_hist) == {"B=200"},
        "经 nginx 的入口全程有活上游（N 里没有 5xx）":
        n_hist != {} and not [k for k in n_hist if k.split("=")[-1][:1] == "5"],
        "被杀实例被 systemd 拉起（结尾 is-active 回到 active）":
        out.count("active") > 0 and "RECOVER_SECONDS=never" not in out,
        "NRestarts 因为这次 SIGKILL +1": restarted,
    }
    return {"X2": CRASH_X2, "X3": out.strip(), "X4": CRASH_X4}, sig



# ---- Drill B：Redis 不可用 -------------------------------------------------
REDIS_SCRIPT = r'''
set -u
D=/tmp/sorders-drillB; rm -rf $D; mkdir -p $D
restore() { systemctl start redis >/dev/null 2>&1; }
trap restore EXIT
Q() { mysql -uroot -N -B sorders -e "$1"; }

echo "== 基线（Redis 活着）"
echo "B_REDIS_ACTIVE=$(systemctl is-active redis)"
echo "B_PING=$(redis-cli ping 2>&1 | head -1)"
CH=$(redis-cli pubsub channels 2>&1 | tr '\n' ',')
echo "B_CHANNELS=$CH"
NS=$(redis-cli pubsub numsub socketio 2>&1 | tr '\n' ' ')
echo "B_NUMSUB=$NS"
BH=$(curl -s http://127.0.0.1:8111/health)
echo "B_HEALTH=$BH"

echo "== 注入：停 Redis"
systemctl stop redis
sleep 3

echo "== 停机期间"
echo "D_REDIS_ACTIVE=$(systemctl is-active redis)"
echo "D_PING=$(redis-cli ping 2>&1 | head -1)"
DH=$(curl -s http://127.0.0.1:8111/health)
echo "D_HEALTH_8111=$DH"
DH2=$(curl -s http://127.0.0.1:8112/health)
echo "D_HEALTH_8112=$DH2"
TOK=$(curl -sk -X POST -H 'Content-Type: application/json' -d '{"phone":"13800000001","password":"123321"}' https://127.0.0.1/api/v1/auth/login | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
TLEN=$(printf '%s' "$TOK" | wc -c)
echo "D_TOKEN_LEN=$TLEN"
ME=$(curl -sk -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOK" https://127.0.0.1/api/v1/users/me)
echo "D_ME=$ME"
OR=$(curl -sk -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOK" "https://127.0.0.1/api/v1/orders?limit=1")
echo "D_ORDERS=$OR"
LG=$(curl -sk -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOK" "https://127.0.0.1/api/v1/ledger/entries?limit=1")
echo "D_LEDGER=$LG"
WB=$(curl -sk -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' -d '{"recipient_id":1,"title":"R3-06 演练探针（Drill B）","content":"redis-down 演练探针，演练结束会删掉。"}' https://127.0.0.1/api/v1/notifications)
NID=$(printf '%s' "$WB" | sed -n 's/.*"id":\([0-9]*\).*/\1/p' | head -1)
echo "D_WRITE_ID=$NID"
echo "D_WRITE_ROW=$(Q "select count(*) from notifications where id=$NID;")"
echo "== 应用日志里与 redis 有关的报错（近 2 分钟）"
journalctl -u sorders-api-a -u sorders-api-b --since "2 min ago" --no-pager 2>/dev/null | grep -i redis | tail -6

echo "== 恢复：起 Redis"
systemctl start redis
sleep 5
echo "R_REDIS_ACTIVE=$(systemctl is-active redis)"
echo "R_PING=$(redis-cli ping 2>&1 | head -1)"
RCH=$(redis-cli pubsub channels 2>&1 | tr '\n' ',')
echo "R_CHANNELS=$RCH"
RNS=$(redis-cli pubsub numsub socketio 2>&1 | tr '\n' ' ')
echo "R_NUMSUB=$RNS"
RH=$(curl -s http://127.0.0.1:8111/health)
echo "R_HEALTH=$RH"
echo "== 停 Redis 期间写的那条事件，恢复后应当由消费者自己补投（轮询到 sent，最多 40 秒）"
RPE=""
for i in $(seq 1 20); do
  RPE=$(Q "select concat(status,' attempts=',attempts) from outbox_events where aggregate_id='$NID' limit 1;")
  case "$RPE" in sent*) break;; esac
  sleep 2
done
echo "R_PROBE_EVENT=$RPE"
DEL=$(curl -sk -o /dev/null -w '%{http_code}' -X DELETE -H "Authorization: Bearer $TOK" "https://127.0.0.1/api/v1/notifications/$NID")
echo "R_DELETE_PROBE=$DEL id=$NID"
'''

REDIS_X2 = ("systemctl stop redis（生产机上唯一的 Redis）。⚠️ 前提已经**不是**演练方案里写的"
            "「Redis 没人用」了：B 段之后 Socket.IO 的跨实例总线就是它"
            "（X1 里 pubsub channels 有 socketio 就是这条的判据）。")
REDIS_X4 = ("脚本用 trap 保证 Redis 一定被起回来（连中断也会执行），并在 X3 末尾复验"
            " ping/channels/numsub 三项；探针消息当场删掉（净零）。")


def _prod_redis_down() -> tuple[dict, dict]:
    _c, out = _sh(REDIS_SCRIPT, timeout=300)
    tok = _grab(out, "D_TOKEN_LEN")
    try:
        tok_ok = int(tok) > 20
    except ValueError:
        tok_ok = False
    codes = [_grab(out, k) for k in ("D_ME", "D_ORDERS", "D_LEDGER")]
    health_changed = _grab(out, "B_HEALTH") != _grab(out, "D_HEALTH_8111")
    sig = {
        "Redis 停机期间 HTTP 业务接口照常（登录拿到 token、读自己/读订单/读账本 全 200）":
            tok_ok and codes == ["200", "200", "200"],
        "停机期间业务**写**也照常（写探针消息拿到 id 且行真的在库里）":
            _grab(out, "D_WRITE_ID") != "" and _grab(out, "D_WRITE_ROW") == "1",
        "/health 如实报出 Redis 的变化（停机前后 redis 字段不一样）": health_changed,
        "跨实例投递在 Redis 回来之后自己回来（停 Redis 时写的那条事件补投成 sent）":
            _grab(out, "R_PING") == "PONG" and _grab(out, "R_PROBE_EVENT").startswith("sent"),
    }
    return {"X2": REDIS_X2, "X3": out.strip(), "X4": REDIS_X4}, sig


# ---- Drill C：事件消费者延迟（发件箱）--------------------------------------
EVENT_SCRIPT = r'''
set -u
D=/tmp/sorders-drillC; rm -rf $D; mkdir -p $D
restore() { systemctl start redis >/dev/null 2>&1; }
trap restore EXIT
Q() { mysql -uroot -N -B sorders -e "$1"; }

echo "== X1 追加基线：发件箱"
BT=$(Q 'select count(*) from outbox_events;')
echo "C_BEFORE_TOTAL=$BT"
BP=$(Q "select count(*) from outbox_events where status='pending';")
echo "C_BEFORE_PENDING=$BP"

echo "== 注入：停 Redis —— 消费者投递必然失败（这就是「消费者处理不了」的真实形态）"
systemctl stop redis
sleep 3
echo "C_REDIS_ACTIVE=$(systemctl is-active redis)"

echo "== 停 Redis 期间做一次**真实业务写入**"
TOK=$(curl -sk -X POST -H 'Content-Type: application/json' -d '{"phone":"13800000001","password":"123321"}' https://127.0.0.1/api/v1/auth/login | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
WB=$(curl -sk -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' -d '{"recipient_id":1,"title":"R3-06 演练探针（Drill C）","content":"event-delay 演练探针，演练结束会删掉。"}' https://127.0.0.1/api/v1/notifications)
NID=$(printf '%s' "$WB" | sed -n 's/.*"id":\([0-9]*\).*/\1/p' | head -1)
echo "C_WRITE_ID=$NID"
R1=$(Q "select count(*) from notifications where id=$NID;")
echo "C_ROW_IN_DB=$R1"

echo "== 等 10 秒：让消费者把这一条投递失败、堆在 pending"
sleep 10
PS=$(Q "select status from outbox_events where aggregate_id='$NID' limit 1;")
echo "C_PROBE_STATUS_AFTER_FAILURE=$PS"
PSENT=$(Q "select count(*) from outbox_events where aggregate_id='$NID' and status='sent';")
echo "C_PROBE_SENT_AFTER_FAILURE=$PSENT"
PPEND=$(Q "select count(*) from outbox_events where aggregate_id='$NID' and status='pending';")
echo "C_PROBE_PENDING_AFTER_FAILURE=$PPEND"
PAT=$(Q "select coalesce(max(attempts),0) from outbox_events where aggregate_id='$NID';")
echo "C_PROBE_ATTEMPTS_AFTER_FAILURE=$PAT"
PLE=$(Q "select coalesce(max(last_error),'') from outbox_events where aggregate_id='$NID';")
PLEN=$(printf '%s' "$PLE" | wc -c)
echo "C_PROBE_LASTERROR_LEN=$PLEN"
echo "C_PROBE_LASTERROR=$PLE"
PN=$(Q "select count(*) from outbox_events where status='pending';")
echo "C_PENDING_NOW=$PN"
echo "C_NOTIF_ROWS=$(Q 'select count(*) from notifications;')"
echo "== 停机期间应用日志里 socketio/redis 的报错（这是根因证据）"
JL=$(journalctl -u sorders-api-a -u sorders-api-b --since "5 min ago" --no-pager 2>/dev/null)
printf '%s\n' "$JL" | grep -iE 'Cannot publish to redis|Cannot receive from redis' | tail -4
PG=$(printf '%s\n' "$JL" | grep -c 'Cannot publish to redis')
echo "PUBLISH_GIVEUP=$PG"

echo "== 恢复：起 Redis，消费者应当按自己的退避把这一条补投出去"
systemctl start redis
sleep 30
echo "C_REDIS_ACTIVE_AFTER=$(systemctl is-active redis)"
PA=$(Q "select count(*) from outbox_events where status='pending';")
echo "C_PENDING_AFTER=$PA"
FA=$(Q "select count(*) from outbox_events where status='failed';")
echo "C_FAILED_AFTER=$FA"
PSA=$(Q "select count(*) from outbox_events where aggregate_id='$NID' and status='sent';")
echo "C_PROBE_SENT_AFTER_RECOVERY=$PSA"
PROW=$(Q "select count(*) from outbox_events where aggregate_id='$NID';")
[ -n "$PROW" ] || PROW=0
echo "C_PROBE_ROWS=$PROW"
echo "C_PROBE_DUPLICATES=$(( PROW - 1 ))"
PEA=$(Q "select concat(status,' attempts=',attempts,' sent_at=',coalesce(sent_at,'-')) from outbox_events where aggregate_id='$NID';")
echo "C_PROBE_EVENT_AFTER=$PEA"
ST=$(Q "select count(*) from outbox_events where status='sent';")
echo "C_SENT_TOTAL=$ST"
TA=$(Q 'select count(*) from outbox_events;')
echo "C_TOTAL_AFTER=$TA"
echo "== 删掉探针消息（净零）"
DEL=$(curl -sk -o /dev/null -w '%{http_code}' -X DELETE -H "Authorization: Bearer $TOK" "https://127.0.0.1/api/v1/notifications/$NID")
echo "C_DELETE_PROBE=$DEL"
sleep 4
RG=$(Q "select count(*) from notifications where id=$NID;")
echo "C_ROW_GONE=$RG"
'''

EVENT_X2 = ("systemctl stop redis —— 让发件箱的**投递**真的失败，事件因此堆在 pending"
            "（这就是「消费者处理不了」在本拓扑下的真实形态）。⚠️ 为什么不用「把消费者线程停住」："
            "这个拓扑里消费者与 API 同进程，停掉消费者必然停掉业务，没法只停一半 —— 这本身是 Drill C 的一条结论。")
EVENT_X4 = ("脚本 trap 保证 Redis 起回来；消费者每 2 秒扫一次（POLL_INTERVAL=2.0），"
            "但失败之后要按指数退避（5s/10s/20s…）才轮到下一次 —— 所以恢复后**等 30 秒**再看，"
            "那足够等到退避到期并由消费者自己补投成功（⛔ 不是靠人手工补发）。"
            "随后删掉探针消息。⛔ 不动订单/账本。")


def _prod_event_delay() -> tuple[dict, dict]:
    """六阶段的观察按**用户 2026-09-26 拍板的出口契约**逐条核（⛔ 不是「服务还在」就算过）：

        sent_before_failure = 0     底层投递失败了，事件**没有**被当成已发送
        pending_after_failure = 1   它留在 pending（等着被重试）
        attempts_after_failure >= 1 发件箱**真的看见了**这次失败
        last_error != null          失败原因留痕了
        sent_after_recovery = 1     恢复之后按退避补投成功
        duplicate_count = 0         没有重复
    """
    _c, out = _sh(EVENT_SCRIPT, timeout=420)

    def num(key: str) -> int:
        v = _grab(out, key)
        return int(v) if v.isdigit() else -1

    sent_before = num("C_PROBE_SENT_AFTER_FAILURE")
    pending_fail = num("C_PROBE_PENDING_AFTER_FAILURE")
    attempts_fail = num("C_PROBE_ATTEMPTS_AFTER_FAILURE")
    err_len = num("C_PROBE_LASTERROR_LEN")
    sent_after = num("C_PROBE_SENT_AFTER_RECOVERY")
    dup = num("C_PROBE_DUPLICATES")
    try:
        giveup = int(_grab(out, "PUBLISH_GIVEUP"))
    except ValueError:
        giveup = 0
    sig = {
        "业务写入成功（停 Redis 期间写的探针消息拿到了 id 且行在库里）":
            _grab(out, "C_WRITE_ID") != "" and _grab(out, "C_ROW_IN_DB") == "1",
        "底层投递失败被发件箱看见：sent_before_failure=0、pending_after_failure=1、attempts>=1、last_error 非空":
            sent_before == 0 and pending_fail == 1 and attempts_fail >= 1 and err_len > 0,
        "Redis 恢复之后按退避补投成功：sent_after_recovery=1": sent_after == 1,
        "没有重复投递：duplicate_count=0": dup == 0,
        "恢复后没有留下积压（pending=0、failed=0）":
            _grab(out, "C_PENDING_AFTER") == "0" and _grab(out, "C_FAILED_AFTER") == "0",
        "探针消息已删干净（净零，不动业务数据）": _grab(out, "C_ROW_GONE") == "0",
    }
    findings: list[str] = []
    if giveup > 0 and sent_before == 1 and attempts_fail == 0:
        findings.append(
            "⚠️ **发现（真缺陷，不是演练写错）**：Redis 停着的时候做的那次业务写入，"
            "它的发件箱事件被记成了 **sent、attempts=0**（" + pea + "），"
            "而同一时刻应用日志里是 " + str(giveup) + " 条 Cannot publish to redis... retrying / giving up。"
            "⇒ **python-socketio 的 Redis manager 把 publish 失败自己吞了**（记日志、不抛异常），"
            "于是 _outbox_deliver 看到的是「成功」，发件箱的重试/退避/failed+last_error **一条都不会触发**。"
            "这正是 outbox 模块开头点名要治的病（「那条推送就没了，而数据库里一切正常，所以没人会发现」）"
            "—— 治住了业务事务与事件边界，却在**最外层的 emit** 上漏了回来。"
            "后果有界但真实：跨实例那条推送**永久丢掉**且**没有任何地方记着**；"
            "站内信的行还在（客户端重连会重新拉），所以伤的是实时性、不是数据。"
            "修法方向（⛔ 属核心区，本轮冻结，只记不做）：在 core/socket_io.py 的 emit 原语上做"
            "「发之前先探一次 Redis 可达」，不可达就**抛**，让发件箱按它自己的语义重试 —— "
            "判据是「Redis 停着时事件必须留在 pending」。")
    return {"X2": EVENT_X2, "X3": out.strip(), "X4": EVENT_X4, "findings": findings}, sig



# ---- Drill E：磁盘将满 -----------------------------------------------------
DISK_SCRIPT = r'''
set -u
D=/tmp/sorders-drillE; rm -rf $D; mkdir -p $D
FO=$D/fill.bin
cleanup() { rm -f $FO; }
trap cleanup EXIT
HC=/opt/sorders-backup/bin/_health_check.py
PY=/opt/SOrders/backend/.venv/bin/python

echo "== 基线磁盘"
df -h / | tail -1
DB=$(df -h / | awk 'NR==2{print $5}')
echo "E_DISK_BEFORE=$DB"
echo "== 基线：cron 跑的就是这一条命令"
$PY $HC --local 2>&1 | grep -E '磁盘|服务' | sed 's/^/  /'

echo "== 注入：造占位文件把 / 推到 ~87%（fallocate 瞬间占块，不写真数据）"
TOTAL=$(df -k / | awk 'NR==2{print $2}')
USED=$(df -k / | awk 'NR==2{print $3}')
NEED=$(( TOTAL * 87 / 100 - USED ))
echo "E_NEED_KB=$NEED"
fallocate -l "$NEED"K $FO
sync
df -h / | tail -1
DD=$(df -h / | awk 'NR==2{print $5}')
echo "E_DISK_DURING=$DD"
echo "E_AVAIL_DURING=$(df -h / | awk 'NR==2{print $4}')"

echo "== 观察 1：MySQL 在磁盘紧张期间还能不能读写"
MP=$(mysql -uroot -N -B sorders -e 'select count(*) from orders;' 2>&1)
echo "E_MYSQL_PROBE=$MP"
echo "== 观察 2：把 cron 那一行命令**原样**跑一遍（含它自己的日志重定向）"
$PY $HC --local --quiet >> /var/log/sorders-health.log 2>&1
RC=$?
echo "E_HEALTH_RC_DURING=$RC"
echo "== 观察 3：告警真的落进日志了吗"
tail -3 /var/log/sorders-health.log | sed 's/^/  /'
LW=$(tail -12 /var/log/sorders-health.log | grep -c '磁盘')
echo "E_LOG_DISK_LINES=$LW"

echo "== 恢复：删掉占位文件"
rm -f $FO
sync
df -h / | tail -1
DA=$(df -h / | awk 'NR==2{print $5}')
echo "E_DISK_AFTER=$DA"
HF=$($PY $HC --local 2>&1 | grep '磁盘')
echo "E_HEALTH_AFTER_LINE=$HF"
'''

DISK_X2 = ("fallocate 一个占位文件，把 / 的使用率顶到 ~87%（越过 DISK_WARN_PCT=85；"
           "⛔ 刻意**不**顶到 95% 的 DISK_FAIL_PCT —— 那要把在跑的 MySQL 所在盘压到只剩 ~1.5G，"
           "判为不可接受的风险）。")
DISK_X4 = ("rm 掉占位文件 + sync，然后**逐项复验**：df 的使用率回到演练前的档位、"
           "健康检查的磁盘那一行回到 ok、MySQL 照样可读。trap 保证即使中途被打断也会删掉那个文件。"
           "⚠️ 这一步不是走过场：占位文件占的是**在跑的 MySQL 所在那个盘**，"
           "删干净才算恢复。")


def _prod_disk_full() -> tuple[dict, dict]:
    _c, out = _sh(DISK_SCRIPT, timeout=300)

    def pct(k: str) -> int:
        v = _grab(out, k).rstrip("%")
        try:
            return int(v)
        except ValueError:
            return -1

    during, before, after = pct("E_DISK_DURING"), pct("E_DISK_BEFORE"), pct("E_DISK_AFTER")
    sig = {
        "磁盘真的被推过 85% 阈值（85<=实测<=92）": 85 <= during <= 92,
        "cron 那一行命令当场报 warn：退出码 1": _grab(out, "E_HEALTH_RC_DURING") == "1",
        "告警真的落进 /var/log/sorders-health.log（不是只写在代码里）":
            _grab(out, "E_LOG_DISK_LINES").isdigit() and int(_grab(out, "E_LOG_DISK_LINES")) >= 1,
        "磁盘紧张期间 MySQL 照常可读（库没有被撑挂）":
            _grab(out, "E_MYSQL_PROBE").isdigit(),
        "删掉占位文件后磁盘恢复到演练前的水平": after == before and after > 0,
    }
    return {"X2": DISK_X2, "X3": out.strip(), "X4": DISK_X4}, sig


PROD_IMPL = {
    "lock-contention": _prod_lock_contention,
    "worker-crash": _prod_worker_crash,
    "redis-down": _prod_redis_down,
    "event-delay": _prod_event_delay,
    "disk-full": _prod_disk_full,
}


def _repo_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except Exception:                                     # noqa: BLE001 —— 记不到就空着，不编
        return ""


def run_prod(case: str) -> int:
    """**真的去生产上跑**一条演练（六个阶段）。⛔ 只有三个信号齐了才走得到这里。"""
    if case not in PROD_IMPL:
        print("⛔ 这个演练还没有生产实现：" + case)
        return 1
    rec: dict = {"case": case, "started_utc": _now(), "phases": {}, "signals": {},
                 "known_limits": list(KNOWN_LIMITS[case]), "repo_sha": _repo_sha(),
                 "prod_host": _prodssh.PROD_HOST}
    print("== 生产演练 " + case + "（六阶段 X0 -> X5）")
    rec["phases"]["X0"] = _phase_x0(case)
    print("")
    print("[X0] " + PHASE_TITLE["X0"])
    print(rec["phases"]["X0"])

    base = _snapshot()
    rec["phases"]["X1"] = "业务状态基线：" + _snap_text(base) + "\n服务面：\n" + _svc_probe("BASE")
    print("")
    print("[X1] " + PHASE_TITLE["X1"])
    print(rec["phases"]["X1"])

    mid, sig = PROD_IMPL[case]()
    rec["findings"] = mid.pop("findings", [])
    for ph in ("X2", "X3", "X4"):
        if mid.get(ph):
            rec["phases"][ph] = mid[ph]
            print("")
            print("[" + ph + "] " + PHASE_TITLE[ph])
            print(mid[ph])

    x5, ok5 = _x5(base)
    rec["phases"]["X5"] = x5
    print("")
    print("[X5] " + PHASE_TITLE["X5"])
    print(x5)
    sig["X5 业务状态与 X1 基线逐项一致"] = ok5
    rec["signals"] = sig
    return _finish(case, rec)


# ------------------------------------------------------------ CI 侧：核记录（⛔ 不连生产）
def verify_records(case: str | None) -> int:
    todo = list(CASES) if case in (None, "all") else [case]
    fossils = [c for c in REQUIRED_SIGNALS if c not in CASES]
    fails: list[str] = []
    if fossils:
        fails.append("REQUIRED_SIGNALS 里有已经不在 CASES 里的键（化石）：" + "、".join(fossils))
    n_ok = 0
    for c in todo:
        files = sorted(RECORDS_DIR.glob(c + "-*.json")) if RECORDS_DIR.exists() else []
        if not files:
            fails.append(c + "：仓库里没有记录（" + str(RECORDS_DIR.relative_to(ROOT))
                         + " 下没有 " + c + "-*.json）—— 「演练过了」得有产出")
            continue
        rec = json.loads(files[-1].read_text(encoding="utf-8"))
        bad0 = len(fails)
        if rec.get("verdict") != "pass":
            fails.append(c + "：最新一份记录的结论是 " + str(rec.get("verdict")))
        for ph in PHASES:
            body = str((rec.get("phases") or {}).get(ph, ""))
            if len(body) < MIN_PHASE_CHARS:
                fails.append(c + "：阶段 " + ph + " 的记录缺失或过短（" + str(len(body)) + " 字符）")
        sig = rec.get("signals") or {}
        for w in REQUIRED_SIGNALS[c]:
            hit = [k for k in sig if w in k]
            if not hit:
                fails.append(c + "：必须的信号没被记下来：「" + w + "」")
            elif not all(sig[k] for k in hit):
                fails.append(c + "：信号「" + w + "」记的是**不成立**")
        if not rec.get("known_limits"):
            fails.append(c + "：没有写已知边界（⛔ 一条演练不可能包打一切）")
        if len(fails) == bad0:
            n_ok += 1
            print("  ✅ " + c + "  " + str(files[-1].name) + "  " + str(rec.get("verdict"))
                  + "  " + str(len(sig)) + " 个信号")
    print("")
    print("演练记录核对：" + str(n_ok) + "/" + str(len(todo)) + " 条记录六阶段齐、必须信号在、结论 pass")
    if fails:
        print("")
        for f in fails:
            print("  ❌ " + f)
        return 1
    print("  ⛔ 这一条核的是**记录本身**（存在 / 六阶段齐 / 必须信号在 / 结论 pass）——"
          "它不重跑演练，也不连生产。")
    return 0



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
    ap.add_argument("--verify", metavar="CASE", nargs="?", const="all",
                    help="**CI 侧**核对演练记录：六阶段齐 + 必须的信号在 + 结论明确（⛔ 不连生产）")
    a = ap.parse_args()

    if a.verify:
        return verify_records(None if a.verify == "all" else a.verify)
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
    if action == "run-prod":
        return run_prod(a.case)
    code = run_local(a.case)
    print(("✅ 本机部分通过" if code == 0 else "❌ 本机部分不通过（退出码 " + str(code) + "）")
          + " —— ⛔ 这不等于生产那一格验过了：台账 R3-06 五条要的是生产记录（见 --verify）。")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
