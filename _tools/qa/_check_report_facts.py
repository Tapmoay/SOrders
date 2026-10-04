#!/usr/bin/env python3
'''_check_report_facts.py —— 台账里每条 ✅ 都要**跑得通**，写下的数都要**当场核**（R3-07 · 指南原则四）。

### 为什么要有它（指南 §二十一 ④ + 原则四）

> 原则四：**不再允许「文档语义超过代码事实」**。Fact first, wording second.

`docs/R3_PROGRESS.md` 是这一轮**唯一**的「已完成」出处，每条 ✅ 后面都跟着一条 `复现：` 命令。
但「跟着一条命令」和「那条命令真的能跑通」是两件事 —— 这一条判据把它们接上：
**逐条把那条命令跑一遍，非零退出就是文档说了假话**。

R3-BOUNDARY-JUSTIFICATION: 这条**没法用边界消除** —— 它管的是「文档里那句已完成」与
「机器现在跑出来的结果」之间的一致性。每条 ✅ 指向的判据各自都对，但**没有任何地方**
保证台账里那句话当前仍然成立（改一行代码就可能让它变成过去时，而台账是手写的）。
这是这份台账唯一可能的腐烂方式，也是「文档说 UI/Audit 已接 Capability，实际没有」那类事故的通用防线。

### 判据（六组）
1. 台账存在、且 ✅ 行数 ≥ MIN_CLAIMS（**扫描坏了先喊**，不许安静地一条都不查）；
2. ⭐ 每条 ✅ 都必须带 `复现：` + 一个反引号包住的命令 —— 没有就报错（不是跳过）；
3. ⭐ 每条 ✅ 的命令**真的跑**，退出码必须是 0；非零就把最后几行输出贴出来；
4. 去重后至少跑 MIN_RUN 条；跑不动/超时的按**失败**算（不是跳过）；
5. ⭐ 明确不跑的（自引用 / 太慢 / 要真实数据）必须在 SKIP 表里写清「为什么」+「什么时候删掉这一条」，
   而且那些键**必须还是台账里真有的命令**（防化石：留着的旧理由会把「跳过了几条」这个数越糊越假）；
6. ⭐ 行里写了期望值（`→ ` + 反引号包住的片段）的，那段文字必须**在命令现在的输出里** ——
   写下的数就得有人核；⛔ **跳过的那几条不许写期望值**（没人跑它，那个数就没人数）。

### ⛔ 它**自己**踩过的坑（2026-09-26，写它的第一天）

台账里那条 R3-07c 的 ✅ 写得没错（`复现：python _tools/qa/_check_report_facts.py`），
但它让**检查去跑检查自己**：每一代隔 7~8 秒生一个，40 分钟长出 **400 多个 python 进程**，
把整台机器拖到 `_check_all.py` 要跑 171 秒。
修法三条（都在这份脚本里）：① 环境变量守卫 —— 子命令带着 `SORDERS_REPORT_FACTS_DEPTH`，
下一代一启动就报错退出；② 自己那条命令进 SKIP 表（写明为什么 + 什么时候删掉这一条）；
③ 一条结构性判据：台账里凡是要跑起本脚本的命令，必须在 SKIP 表里显式登记。
教训与「永远红的检查＝没有检查」同源：**判据的爆炸半径，本身也是判据要管的东西**。

### 并发编排（2026-10-04 补：这一条判据自己踩过的第二个坑）

台账里的命令**不是彼此独立的**：会 bootstrap 数据库的那些抢的是**同一把固定路径的本机文件锁**
（`backend/app/core/schema_bootstrap.py:33` 的 `sorders_bootstrap.lock` —— ⛔ 一把锁管**所有**库，
不是每库一把），拿不到要等 `backend/app/core/file_lock.py:36` 的 `DEFAULT_WAIT_S = 60` 秒才抛。
整轮 8 路并发里 `_check_r3_constraints.py` + `_migration_tests.py --fresh/--old/--concurrent` 四条
同时报「拿不到文件锁」、**逐条单独跑却全绿** —— 台账没错，是本判据的编排把它们锁死了。三条修法：

· 会 bootstrap 的命令走**单 worker 的串行车道**（`SERIAL_HINTS`，含**间接** bootstrap 的那些）；
· 两条车道**不许重叠**：并行车道**跑完**才开串行车道。其中 `_migration_tests.py --concurrent`、
  `_drill.py --verify lock-contention`、`_dual_instance.py` 这几条**断言的就是锁/端口的争用行为** ——
  旁边有人同时在建库，它们断言的就不是自己那两个进程了（2026-10-04 实测：并行车道里的 pytest
  在 bootstrap 临时库，串行车道里的 `--concurrent` 就红了；单独跑必绿）；
· 万一还有别人（上一次检查留下的进程、正在跑的后端）占着锁：命中 `LOCK_BUSY` 的命令**单独重跑一次**，
  过了就记为通过、并在输出里**点名**（⛔ 不许悄悄咽掉：重跑名单是下一次再红时唯一的线索）；
· 红的命令**完整输出落盘**到 `_tmp/rf_fail/<命令>.txt` 并把路径打出来 —— 只印最后三行，
  下次红了只能靠猜（`--concurrent` 那次只留下「❌ 不成立」四个字，看不出是哪条断言）。

### ⛔ 它证不了什么

· 它证的是「那条命令现在退出 0」+「写的期望值现在还打得出」，**不证**「文档里那句话描述得准确」——
  一句话有没有说过头，机器判不了（那是人读报告时要盯的）；
· SKIP 掉的几条本判据**没有**核，如实列在输出里，不假装覆盖。

用法：python _tools/qa/_check_report_facts.py [--list]
'''
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / 'docs/R3_PROGRESS.md'

MIN_CLAIMS = 20
MIN_RUN = 12
TIMEOUT_S = 180
WORKERS = 8

#: 命令里出现这些片段的**不能并发跑** —— 走下面那条**单 worker 的串行车道**。两类理由：
#:
#: ① **抢端口**：`_dual_instance.py` 自己会起两个实例（18000 段）。
#: ② **抢同一把固定路径的本机文件锁** —— 这是 2026-10-04 实测到的那一类：
#:    会 bootstrap 数据库的命令（**真库或临时库都一样**）抢的是 `backend/app/core/schema_bootstrap.py:33`
#:    里那把 `BOOTSTRAP_LOCK_FILE`（`<临时目录>/sorders_bootstrap.lock`，⛔ **一把锁管所有库**、不是每库一把）；
#:    而 `backend/app/core/file_lock.py:36` 的 `DEFAULT_WAIT_S = 60` 意味着**拿不到就等满 60 秒再抛**
#:    `FileLockTimeout`。于是 8 路并发里只要有几条要 bootstrap，后面的就成排地报「拿不到文件锁」——
#:    实测那一轮：`_check_r3_constraints.py`（它自己内部还会再跑 `_migration_tests.py` 三种形态）
#:    + `_migration_tests.py --fresh/--old/--concurrent` 四条同时假红，**逐条单独跑却全绿**：
#:    台账一个字都没写错，是这条判据自己的编排把它们锁死了。
#:
#: ⛔ 判据：会 bootstrap 的命令包括「**间接** bootstrap 的命令」（`_check_r3_constraints.py` 会跑
#:    `_migration_tests.py` 与 `_check_import_purity.py`）—— 串行是**按命令**串的，进程树内部的先后
#:    由那条命令自己管，但两条命令行不许同时在跑。
SERIAL_HINTS = (
    '_dual_instance.py',          # ① 抢端口
    '_migration_tests.py',        # ② 四种形态都要建库（真库 + 临时库）
    '_check_import_purity.py',    # ② 真库 + 子进程核对
    '_check_r3_constraints.py',   # ② 里面就跑上面两条
    '_check_migrations.py',       # ② 走迁移入口
    '_drill.py',                  # ② lock-contention / event-delay / redis-down 三格都建库
    'prepare_schema(',            # ② 台账里那段内联脚本
    'app.migrations',             # ② `python -m app.migrations …`（upgrade 就是 prepare_schema）
)

#: 「拿不到锁」的指纹：命令本身没错，是**撞上别人的本机锁**（bootstrap / 迁移 / SQLite 写锁）。
#: 命中它才允许「单独重跑一次」；而且重跑名单**必须打出来** ——
#: ⛔ 它不许变成掩盖真实失败的橡皮擦（真失败重跑几次都还是失败）。
LOCK_BUSY = re.compile(r'FileLockTimeout|拿不到文件锁|database is locked|Resource temporarily unavailable')

#: ⛔ **绝对不许由本判据启动**的命令：反向验证会**注入并改工作区**（还带注入锁）。
#: 实测事故（2026-09-26）：台账里一条 ✅ 的复现命令写成了「按域全量跑反向验证」（~50 分钟），
#: 本判据照着跑 ⇒ 它自己 300 秒超时，而那个**后台的全量跑还活着**：注入锁把后面所有检查拦成
#: 「反向验证正在跑，给不出可信结论」，源码树里还留着两处注入。
#: 规矩：✅ 的复现命令必须是**不改源码**的判据（要证明注入还活着，用静态的
#: `_check_reverse_verify_anchors.py`；逐份跑反向验证由人来跑）。
NEVER_RUN_HINTS = ('_reverse_verify',)


#: 明确不跑的：为什么 + **什么时候删掉这一条**。
SKIP: dict[str, str] = {
    # ⛔ 自引用：这条命令**就是本判据自己**（台账 R3-07c 那条 ✅ 的复现命令就是它）。
    'python _tools/qa/_check_report_facts.py':
        '自引用：跑它＝检查跑检查 → 无限套娃（2026-09-26 实测 40 分钟长出 400+ 个 python 进程）。'
        ' ⛔ 它成立的证据由**外层**给出：`_check_all.py` 每次都会跑本判据本身（那条由它自己的 SKIP 管），'
        '而「这条判据真的会红」由 _reverse_verify_report_facts.py 的 7/7 证。'
        ' **什么时候删掉这一条**：如果哪天台账那条 ✅ 不再把本脚本写成复现命令。',
    'python _tools/qa/_check_all.py':
        '自引用：本判据就跑在 _check_all.py 里面，再跑一遍等于递归。要证的事由外层那次调用本身证。'
        ' **什么时候删掉这一条**：如果哪天本判据改成只在 --deep 里跑。',
    'cd backend; python -m pytest -q':
        '跑一次约 2 分钟（1018 个用例），而 CI 的 Gate 与 _gen_acceptance.py --full 各跑过一遍。'
        ' **什么时候删掉这一条**：如果哪天本判据有了 --deep 模式，把它挪进那里。',
    'cd backend; python ..\\_tools\\ops\\_trace_order.py --latest':
        '要本机开发库里有订单才打得出东西（CI 上没有），而且它读真实库、不是判据。'
        ' 台账那一条的证据是「工具没被丢掉 + 只读」，由 _check_traceability.py 与'
        ' _check_r3_constraints.py 的 trace_tool_kept 探针核。'
        ' **什么时候删掉这一条**：如果 CI 上有种子数据，或给它加一个「无数据也退出 0」的模式。',
}

#: 自己的文件名（判「台账里那条命令是不是在跑我自己」用）。
SELF_NAME = Path(__file__).name

#: ⛔ 自引用的**硬守卫**（2026-09-26 实测事故，写这条判据的当天就踩了）：
#:    台账里那条 ✅ 的复现命令**就是本脚本自己** ⇒ 检查跑检查 → 40 分钟里长出 **400 多个 python 进程**
#:    （每一代隔 7~8 秒生一个，机器被拖到跑什么都慢）。
#:    修法不是「记得别这么写」，而是**让递归在第一步就撞墙**：本脚本给每条子命令带上这个环境变量，
#:    子进程一启动就发现自己在递归里 → 报错退出（不再往下跑）。
RECURSION_ENV = 'SORDERS_REPORT_FACTS_DEPTH'

CMD = re.compile(r'复现：`([^`]+)`')
#: 行里写的期望值：`→ ` + 反引号（如 `→ `1018 passed``）。写了就得当场核。
EXPECT = re.compile(r'→\s*`([^`]+)`')
#: SKIP 的每条理由里必须有的那句话 —— 例外没有退出条件就会永远留在那儿。
NEED_IN_REASON = '什么时候删掉这一条'


#: 用哪个 shell 跑台账里的命令。台账的命令是这本仓库的**方言**（`cd backend; python …`），
#: 本地是 Windows PowerShell 5.1 —— 但 CI 是 ubuntu：那里**没有 `powershell`**，只有 PowerShell 7（`pwsh`）。
#: ⛔ 2026-09-26 实测：写死 `powershell` 的后果不是「CI 上这条判据红」，而是它**每一条行**都返回 125
#:    （`FileNotFoundError`），于是整个 Gate 的「全部静态检查」作业红，而**本机 119/119 全绿** ——
#:    这正是本仓库最难查的那类红（红在 CI、绿在本机、日志还要登录才看得到）。
def _pick_shell() -> list[str]:
    '''选一个能跑台账命令的 shell。⛔ 选不到时**不许静默**：返回空表，调用处会如实报错。

    Windows：`powershell`（5.1，本仓库的命令方言就是它）。
    POSIX（CI）：优先 `pwsh`（ubuntu runner 自带 PowerShell 7；台账里那些 `cd backend; python …`
    在它下面照样成立）；**没有 pwsh 就退回 `bash -c`** —— 退回去之后 Windows 写法（反斜杠路径、
    `Get-FileHash`）会失败，但那是**如实失败**（退出码非 0），比「整条判据在 CI 上一条都跑不了」好。
    '''
    if os.name == 'nt':
        return ['powershell', '-NoProfile', '-NonInteractive', '-Command']
    if shutil.which('pwsh'):
        return ['pwsh', '-NoProfile', '-NonInteractive', '-Command']
    if shutil.which('bash'):
        return ['bash', '-c']
    return []


SHELL: list[str] = _pick_shell()


def run(cmd: str) -> tuple[int, str]:
    '''用 SHELL 跑：台账里的命令是这本仓库的方言（`cd backend; python …`），两个平台都能解。'''
    env = dict(os.environ)
    env[RECURSION_ENV] = str(int(os.environ.get(RECURSION_ENV, '0')) + 1)
    try:
        if not SHELL:
            return 125, ('既没有 powershell/pwsh 也没有 bash —— 这不是「命令失败」，'
                         '是这条判据在本机跑不起来（装一个 shell，或如实说明这里不适用）')
        p = subprocess.run([*SHELL, cmd],
                           cwd=str(ROOT), capture_output=True, text=True, env=env,
                           encoding='utf-8', errors='replace', timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return 124, '超时 ' + str(TIMEOUT_S) + 's'
    except OSError as exc:
        return 125, str(exc)
    return p.returncode, ((p.stdout or '') + (p.stderr or '')).strip()


def last_line(out: str) -> str:
    tail = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return tail[-1][:120] if tail else '(没有输出)'


#: 失败命令的完整输出落在这里（相对仓库根）—— 只印最后三行看不出「是哪条断言、是不是锁」。
FAIL_DIR = ROOT / '_tmp' / 'rf_fail'


def dump_fail(cmd: str, out: str) -> Path:
    '''把失败命令的完整输出写进 _tmp/rf_fail/，返回相对路径（写不进去也不许把判据带崩）。'''
    name = re.sub(r'[^0-9A-Za-z_]+', '_', cmd)[:60].strip('_') or 'cmd'
    try:
        FAIL_DIR.mkdir(parents=True, exist_ok=True)
        assert FAIL_DIR.is_dir(), '路径被占用'
        path = FAIL_DIR / (name + '.txt')
        path.write_text('$ ' + cmd + chr(10) + chr(10) + out, encoding='utf-8', errors='replace')
        return path.relative_to(ROOT)
    except Exception as exc:  # noqa: BLE001 —— 落盘失败只是少一份证据，不该让判据自己崩
        return Path('(落盘失败：' + type(exc).__name__ + ')')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()

    # ⛔ 第一件事：我是不是**被别人当命令跑起来的**（＝台账里有一条 ✅ 的复现命令就是我自己）。
    if os.environ.get(RECURSION_ENV):
        print('❌ 递归调用：本脚本（报告事实核对）是被上一代「报告事实核对」当命令跑起来的 ——')
        print('   台账里有一条 ✅ 的复现命令就是它自己，这样会无限套娃')
        print('   （2026-09-26 实测：40 分钟长出 400+ 个 python 进程，把机器拖垮）。')
        print('   修法：那条命令要写进本脚本的 SKIP 表，并写明为什么 + 什么时候删掉这一条。')
        return 1

    if not LEDGER.exists():
        print('❌ 台账不存在：' + str(LEDGER.relative_to(ROOT)))
        return 1
    text = LEDGER.read_text(encoding='utf-8', errors='replace')
    rows = [(i, ln) for i, ln in enumerate(text.splitlines(), 1) if ln.startswith('- ✅')]
    total_ok = len(rows)
    pairs: list[tuple[int, str, list[str]]] = []
    for i, ln in rows:
        m = CMD.search(ln)
        if m:
            pairs.append((i, m.group(1).strip(), EXPECT.findall(ln)))
    cmds: list[str] = []
    expects: dict[str, list[tuple[int, str]]] = {}
    for i, c, exps in pairs:
        if c and c not in cmds:
            cmds.append(c)
        for x in exps:
            expects.setdefault(c, []).append((i, x))

    if a.list:
        for c in cmds:
            tag = 'SKIP  ' if c in SKIP else 'RUN   '
            got = expects.get(c, [])
            print(tag + c + (('  → ' + ', '.join(x for _ln, x in got)) if got else ''))
        return 0

    fails: list[str] = []
    if total_ok < MIN_CLAIMS:
        fails.append('台账里只有 ' + str(total_ok) + ' 条 ✅（下限 ' + str(MIN_CLAIMS) + '）—— 扫描坏了？')
    if len(pairs) < total_ok:
        fails.append('有 ' + str(total_ok - len(pairs)) + ' 条 ✅ 没写 复现 命令 —— 没命令的「已完成」没法核')

    # ⑤ SKIP 表的两种腐烂：键已经不是台账里的命令了（化石）／理由里没写退出条件。
    fossils = [c for c in SKIP if c not in cmds]
    if fossils:
        fails.append('SKIP 表里这些命令**已经不在台账里了**（化石）：' + ' / '.join(fossils)
                     + ' —— 删掉它们；留着会让「跳过了几条」这个数越糊越假')
    thin = [c for c, why in SKIP.items() if NEED_IN_REASON not in why]
    if thin:
        fails.append('SKIP 表里这些条没写「' + NEED_IN_REASON + '」：' + ' / '.join(thin)
                     + ' —— 例外必须带退出条件，否则它会永远留在那儿')

    # ⑥ 期望值：跳过的那几条不许写（写了也没人跑得出那个数）。
    for c, items in expects.items():
        if c in SKIP:
            fails.append('第 ' + str(items[0][0]) + ' 行给一条**跳过**的命令写了期望值「' + items[0][1]
                         + '」—— 没人跑它，那个数就没人数：要么让它进必跑组，要么把期望值删掉')

    # ⛔ 自引用必须在 SKIP 表里**显式**写出来（不写就会套娃，见 RECURSION_ENV 的说明）。
    selfref = [c for c in cmds if SELF_NAME in c and c not in SKIP]
    if selfref:
        fails.append('台账里这些命令会**跑起本脚本自己**，却没写进 SKIP 表：' + ' / '.join(selfref)
                     + ' —— 那会无限套娃（实测 40 分钟 400+ 个进程）；写进 SKIP 并写明为什么')

    # ⛔ 会把工作区改坏的命令：**不跑**，而且**计为不达标**（不许安静地跳过）
    # ⚠️ 只认**会注入的**那些（`_reverse_verify_*.py`）：`_check_reverse_verify_restore.py` /
    #    `_check_reverse_verify_anchors.py` 名字里也有 `_reverse_verify`，但它们**只读源码**（第一版误伤，
    #    把 R3-07b 那条正常的复现命令也判红了）。
    mutating = [c for c in cmds
                if any(h in c for h in NEVER_RUN_HINTS) and '_check_reverse_verify' not in c]
    for c in mutating:
        fails.append('台账里这条 ✅ 的复现命令**会跑反向验证**（注入 + 改工作区）：' + c
                     + ' —— 判据不许启动它（实测：后台留下一次 50 分钟的全量跑 + 注入锁，把后面的检查全拦了）。'
                     + '改成引用**不改源码**的判据（如 `_check_reverse_verify_anchors.py`）')

    todo = [c for c in cmds if c not in SKIP and c not in mutating]
    if len(todo) < MIN_RUN:
        fails.append('真跑的命令只有 ' + str(len(todo)) + ' 条（下限 ' + str(MIN_RUN) + '）—— 判据在空转')

    parallel = [c for c in todo if not any(h in c for h in SERIAL_HINTS)]
    serial = [c for c in todo if any(h in c for h in SERIAL_HINTS)]
    results: dict[str, tuple[int, str]] = {}
    # ⛔ 两条车道**不许重叠**（见文件头 §并发编排）：并行车道先跑完，串行车道才开跑。
    #    理由是 2026-10-04 实测到的那次假红 —— `_migration_tests.py --concurrent` 在并行车道还在跑
    #    （那里面有 pytest：`backend/tests/conftest.py` 会 bootstrap 一堆临时库）的时候红了，
    #    而它单独跑必绿。**它断言的就是「两个进程同时迁移只能记一次账」**：
    #    旁边有人也在迁移/建库，它断言的就不是自己那两个进程了 —— 这类命令必须独占机器。
    #    代价是多花「并行车道」那一小段（实测总时长仍在 300 秒预算内）。
    with ThreadPoolExecutor(max_workers=WORKERS) as par_pool:
        par_futs = {c: par_pool.submit(run, c) for c in parallel}
        for c, fut in par_futs.items():
            results[c] = fut.result()
    for c in serial:
        results[c] = run(c)

    # ⚠️ 只被**别人的锁**挡住的命令：单独再跑一次（这时两条车道都空了）。
    #    这一档存在的理由：本判据的 8 路并发 + 上一次检查可能留下的进程 + 正在跑的后端，
    #    都可能正握着那把锁；那是**环境**在响，不是台账在写假话。
    retried: list[str] = []
    for c in todo:
        code, out = results.get(c, (1, '没跑到'))
        if code == 0 or not LOCK_BUSY.search(out):
            continue
        code2, out2 = run(c)
        if code2 == 0:
            results[c] = (0, out2)
            retried.append(c)

    n_exp = 0
    for c in todo:
        code, out = results.get(c, (1, '没跑到'))
        if code != 0:
            tail = [ln for ln in out.splitlines() if ln.strip()][-3:]
            # ⛔ 只印最后三行＝下次红了只能靠猜（2026-10-04 实测：`_migration_tests.py --concurrent`
            #    在并发那一轮红，而它只留下「❌ 不成立」四个字，看不出是哪条断言、也看不出是不是锁）。
            #    所以完整输出**落盘**并把路径打出来 —— 三行给人看，文件给下一个人（或下一轮的我）看。
            fails.append('台账里那条 ✅ 现在跑不通（退出码 ' + str(code) + '）：' + c
                          + '  ← ' + ' / '.join(x.strip()[:100] for x in tail)
                          + '  （完整输出：' + str(dump_fail(c, out)) + '）')
            continue
        for ln, x in expects.get(c, []):
            n_exp += 1
            if x not in out:
                fails.append('第 ' + str(ln) + ' 行写的期望值「' + x + '」**不在命令现在的输出里**：' + c
                             + '  ← 它现在打出来的是「' + last_line(out) + '」')

    print('报告事实核对：台账 ' + str(total_ok) + ' 条 ✅ / 去重后 ' + str(len(cmds)) + ' 条命令'
          + '（跑 ' + str(len(todo)) + ' / 跳过 ' + str(len(cmds) - len(todo)) + '）'
          + '；期望值核了 ' + str(n_exp) + ' 条'
          + ('；**被锁挡住、单独重跑才过** ' + str(len(retried)) + ' 条' if retried else ''))
    if retried:
        # ⛔ 这一行不许删：重跑通过**不是**「台账没问题」的沉默证据，它得让人看见
        #    「这一轮有人和我抢那把 sorders_bootstrap.lock」——下一次再红时这是唯一的线索。
        print('  ⚠️ 这些命令第一次跑撞上了本机文件锁（并发抢锁，不是台账写错），单独重跑一次才过：')
        for c in retried:
            print('     ⚠️ ' + c)
    for c in cmds:
        if c in SKIP:
            print('  ⏭  ' + c)
        else:
            code, _ = results.get(c, (1, ''))
            mark = '✅' if code == 0 else '❌'
            got = expects.get(c, [])
            note = '  ⚠️ 重跑一次才过（并发抢锁）' if c in retried else ''
            print('  ' + mark + '  ' + c + (('  → ' + ', '.join(x for _ln, x in got)) if got else '') + note)
    if fails:
        print()
        for f in fails:
            print('  ❌ ' + f)
        print()
        print('❌ ' + str(len(fails)) + ' 条不成立')
        return 1
    print()
    print('  ✅ 6 组判据全部通过：台账里每条 ✅ 都带命令、那些命令**现在真的退出 0**、'
          + '写下的期望值现在还打得出、理由表里没有化石。')
    print('     ⛔ 跳过的 ' + str(len(cmds) - len(todo)) + ' 条见上面的 ⏭（理由与退出条件写在脚本的 SKIP 表里）。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
