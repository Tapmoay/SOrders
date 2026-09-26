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

#: 命令里出现这些片段的**不能并发跑**（它们抢同一组端口）—— 串行处理。
SERIAL_HINTS = ('_dual_instance.py',)

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


def run(cmd: str) -> tuple[int, str]:
    '''在 **PowerShell** 里跑：台账里的命令是这本仓库的方言（`cd backend; python …`、`Get-FileHash`）。'''
    env = dict(os.environ)
    env[RECURSION_ENV] = str(int(os.environ.get(RECURSION_ENV, '0')) + 1)
    try:
        p = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', cmd],
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
    if parallel:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for c, r in zip(parallel, ex.map(run, parallel)):
                results[c] = r
    for c in serial:
        results[c] = run(c)

    n_exp = 0
    for c in todo:
        code, out = results.get(c, (1, '没跑到'))
        if code != 0:
            tail = [ln for ln in out.splitlines() if ln.strip()][-3:]
            fails.append('台账里那条 ✅ 现在跑不通（退出码 ' + str(code) + '）：' + c
                          + '  ← ' + ' / '.join(x.strip()[:100] for x in tail))
            continue
        for ln, x in expects.get(c, []):
            n_exp += 1
            if x not in out:
                fails.append('第 ' + str(ln) + ' 行写的期望值「' + x + '」**不在命令现在的输出里**：' + c
                             + '  ← 它现在打出来的是「' + last_line(out) + '」')

    print('报告事实核对：台账 ' + str(total_ok) + ' 条 ✅ / 去重后 ' + str(len(cmds)) + ' 条命令'
          + '（跑 ' + str(len(todo)) + ' / 跳过 ' + str(len(cmds) - len(todo)) + '）'
          + '；期望值核了 ' + str(n_exp) + ' 条')
    for c in cmds:
        if c in SKIP:
            print('  ⏭  ' + c)
        else:
            code, _ = results.get(c, (1, ''))
            mark = '✅' if code == 0 else '❌'
            got = expects.get(c, [])
            print('  ' + mark + '  ' + c + (('  → ' + ', '.join(x for _ln, x in got)) if got else ''))
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
