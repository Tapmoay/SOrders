#!/usr/bin/env python3
'''反向验证「报告事实核对」这条判据**真的会红**（R3-07c）。

## 为什么这条要反向验证
_check_report_facts.py 是一条**元检查**：它判的不是代码，而是**台账里的每一句「已完成」**。
元检查最典型的失效方式是「安静地少查」—— 正则写窄了（漏掉没带命令的行）、去重把命令吃掉了、
SKIP 表越写越长（把真该跑的也跳过去），三种都表现为**全绿**。
本项目已经栽过 5 次这种空转（见各 _reverse_verify_*.py 的开头）。

所以这里把它的每一种失效方式各注入一次（注入 = 把工作区改成「该报红」的样子，跑完按**字节**还原）：

  ① 某条 ✅ 的命令**现在必然失败**          → 必须点名那条命令（退出码非 0）；
  ② 某条 ✅ 的命令**指向不存在的脚本**      → 同上；
  ③ 某条 ✅ **被抹掉了复现命令**             → 必须报「没写 复现 命令」（不许当成跳过）；
  ④ 台账里所有 ✅ 被换成别的符号            → 必须报「只有 0 条 ✅ … 扫描坏了」（下限判据有牙）；
  ⑤ SKIP 表里塞一条台账里没有的命令         → 必须报「化石」；
  ⑥ 给一条**跳过**的命令写期望值            → 必须红（没人跑它，那个数就没人数）；
  ⑦ 给一条真跑的命令写**假**期望值          → 必须红（写下的数要当场核得住）；
  ⑧ 负面对照（必须仍然全绿）：给一条真跑的命令写**真**期望值 + 把一条 ✅ 原样重复一遍
     （重复的命令必须被去重掉，而不是「跑两遍」或「算两条」）。

## ⛔ 已知盲区（不许当成「已覆盖」）
- 它只在**单行**上找 `复现：`（与判据本身同一口径：跨行写法两边都漏）；
- 「那句中文描述得准不准」机器判不了，这里也不试。

⚠️ 与其它反向验证同一套纪律：注入/还原都按字节做，跑完逐文件核对（本项目栽过「注入把 bug 留在源码里」）。
跑之前先上注入锁（lock_reverse_verify）。

用法：python _tools/qa/_reverse_verify_report_facts.py
'''
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'ai'))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / '_tools' / 'qa' / '_check_report_facts.py'
LEDGER = ROOT / 'docs' / 'R3_PROGRESS.md'
NL = chr(10)
Q = chr(34)

#: 台账里的四个**行首前缀**（定位某一整行；命中 0 行或 2 行都当场报错，不许悄悄跳过）。
ROW_PYTEST = '- ✅ 退出条件 9/10：'
ROW_FRESH = '- ✅ **生成物新鲜度**（R3-07a）'
ROW_TRACE = '- ✅ **command_id 与 request_id / event_id 分成三个概念**'
ROW_CONSTRAINTS = '- ✅ 判据不许静默空转（本轮'
FRESH_CMD = 'python _tools/qa/_check_generated_freshness.py'
TRACE_CMD = 'cd backend; python -m pytest tests/test_r3_trace_ids.py -q'
FAIL_CMD = 'python -c ' + Q + 'import sys; sys.exit(1)' + Q


def lines_of(text: str) -> list[str]:
    return text.split(NL)


def on_row(prefix: str, transform):
    '''对**某一整行**做变换（按行首前缀定位）。'''

    def f(text: str) -> str:
        out = lines_of(text)
        hits = [i for i, ln in enumerate(out) if ln.startswith(prefix)]
        if len(hits) != 1:
            raise ValueError('行首前缀 ' + repr(prefix) + ' 命中 ' + str(len(hits)) + ' 行（要恰好一行）')
        out[hits[0]] = transform(out[hits[0]])
        return NL.join(out)

    return f


def dup_row(prefix: str):
    '''把某一整行**原样再插一遍**（用来证明重复的命令会被去重，而不是被算两条）。'''

    def f(text: str) -> str:
        out = lines_of(text)
        hits = [i for i, ln in enumerate(out) if ln.startswith(prefix)]
        if len(hits) != 1:
            raise ValueError('行首前缀 ' + repr(prefix) + ' 命中 ' + str(len(hits)) + ' 行（要恰好一行）')
        out.insert(hits[0] + 1, out[hits[0]])
        return NL.join(out)

    return f


def compose(*fns):
    def f(text: str) -> str:
        for fn in fns:
            text = fn(text)
        return text
    return f


def swap_cmd(old: str, new: str):
    '''把某一整行里的命令换成另一条（那一行必须**恰好含一次** old）。'''

    def g(line: str) -> str:
        if line.count(old) != 1:
            raise ValueError('那一行里 ' + repr(old) + ' 出现 ' + str(line.count(old)) + ' 次（要恰好一次）')
        return line.replace(old, new, 1)

    return g


def drop_cmd(cmd: str):
    def g(line: str) -> str:
        return line.replace(cmd, '')
    return g


def add_expect(text: str):
    def g(line: str) -> str:
        return line + ' → `' + text + '`'
    return g


def all_rows(text: str) -> str:
    return text.replace('- ✅', '- [x]')


def put_fossil(text: str) -> str:
    anchor = 'SKIP: dict[str, str] = {'
    if text.count(anchor) != 1:
        raise ValueError('注入锚点出现 ' + str(text.count(anchor)) + ' 次（要恰好一次）：' + anchor)
    return text.replace(anchor, anchor + NL + "    'python _tools/qa/_no_such_command.py': '测试用 **什么时候删掉这一条**：不会。',", 1)


CASES: list[tuple] = [
    (
        '某条 ✅ 的命令现在必然失败 → 必须点名那条命令',
        LEDGER, False,
        on_row(ROW_FRESH, swap_cmd(FRESH_CMD, FAIL_CMD)),
        True, '现在跑不通',
    ),
    (
        '某条 ✅ 的命令指向不存在的脚本 → 同样点名那条命令',
        LEDGER, False,
        on_row(ROW_FRESH, swap_cmd(FRESH_CMD, 'python _tools/qa/_no_such_checker_xyz.py')),
        True, '现在跑不通',
    ),
    (
        '某条 ✅ 被抹掉复现命令 → 必须报「没写复现命令」（不许当成跳过）',
        LEDGER, False,
        on_row(ROW_TRACE, drop_cmd(TRACE_CMD)),
        True, '没写 复现 命令',
    ),
    (
        '台账里所有 ✅ 被换成别的符号 → 必须报「只有 0 条 ✅ … 扫描坏了」（下限判据有牙）',
        LEDGER, False,
        all_rows,
        True, '扫描坏了',
    ),
    (
        'SKIP 表里塞一条台账里没有的命令 → 必须报「化石」',
        CHECK, True,
        put_fossil,
        True, '化石',
    ),
    (
        '给一条**跳过**的命令写期望值 → 必须红（没人跑它，那个数就没人数）',
        LEDGER, False,
        on_row(ROW_PYTEST, add_expect('999 passed')),
        True, '跳过',
    ),
    (
        '给一条真跑的命令写**假**期望值 → 必须红（写下的数要当场核得住）',
        LEDGER, False,
        on_row(ROW_FRESH, add_expect('999/999')),
        True, '不在命令现在的输出里',
    ),
    (
        '负面对照：真期望值 + 重复一条 ✅（重复的命令要被去重，不许算两条）',
        LEDGER, False,
        compose(on_row(ROW_FRESH, add_expect('生成器自己说没过期')), dup_row(ROW_CONSTRAINTS)),
        False, '',
    ),
]


class Sandbox:
    '''按字节记住原样，最后一次性还原（⛔ 不用 git checkout --：那会抹掉未提交的真实改动）。'''

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    @staticmethod
    def _mutate(data: bytes, mutate) -> bytes:
        crlf = (chr(13) + chr(10)).encode('utf-8') in data
        text = data.decode('utf-8')
        if crlf:
            text = text.replace(chr(13) + chr(10), NL)
        text = mutate(text)
        return (text.replace(NL, chr(13) + NL) if crlf else text).encode('utf-8')

    def apply(self, path: Path, mutate) -> None:
        self.saved.setdefault(path, path.read_bytes())
        path.write_bytes(self._mutate(path.read_bytes(), mutate))

    def mutate_copy(self, path: Path, mutate) -> Path:
        '''改一份**副本**：注入目标就是检查脚本自己时用（别让检查在被改的状态下跑自己）。'''
        tmp = path.with_suffix('.py.injected')
        tmp.write_bytes(self._mutate(path.read_bytes(), mutate))
        return tmp

    def restore(self) -> None:
        for path, raw in self.saved.items():
            path.write_bytes(raw)

    def dirty(self) -> list[str]:
        return [str(p.relative_to(ROOT)) for p, raw in self.saved.items() if p.read_bytes() != raw]


def run_check(target: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(target or CHECK)],
        capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=str(ROOT),
    )
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def main() -> int:
    if not CHECK.exists() or not LEDGER.exists():
        print('❌ 找不到 ' + str(CHECK) + ' 或 ' + str(LEDGER))
        return 1

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print('❌ 前提不成立：源码完好时这条检查就没过')
            print(out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print('✅ 前提：源码完好时这条检查是绿的 —— ' + last.strip())

        for label, path, is_check_itself, mutate, expect_red, keyword in CASES:
            sb.restore()
            tmp: Path | None = None
            try:
                try:
                    if is_check_itself:
                        tmp = sb.mutate_copy(path, mutate)
                        code, out = run_check(tmp)
                    else:
                        sb.apply(path, mutate)
                        code, out = run_check()
                except ValueError as exc:
                    print('  [MISS] ' + label + ' → 注入没做成（锚点变了就改本脚本）：' + str(exc))
                    bad += 1
                    continue
            finally:
                if tmp is not None and tmp.exists():
                    tmp.unlink()
                sb.restore()
            if expect_red:
                hit = code != 0 and keyword in out
                detail = '报了红' if code != 0 else '仍然全绿（判据没牙）'
                if code != 0 and keyword not in out:
                    detail += '，但没点出「' + keyword + '」'
            else:
                hit = code == 0
                detail = '仍然全绿（这正是要的）' if hit else '被误判成红了（假红）'
            print('  [' + ('OK' if hit else 'MISS') + '] ' + label + ' → ' + detail)
            if not hit:
                bad += 1
                for ln in out.splitlines()[-10:]:
                    print('        ' + ln)

        sb.restore()
        code, out = run_check()
        ok = code == 0
        print('  [OK] 还原后这条检查全绿' if ok else '  [MISS] 还原后这条检查没恢复')
        bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()

    dirty = sb.dirty()
    if dirty:
        bad += 1
        print('⛔ 跑完没逐字节还原：' + '、'.join(dirty))
    total = len(CASES) + 1
    print()
    if bad:
        print('❌ ' + str(bad) + '/' + str(total) + ' 条不成立')
        return 1
    print('✅ ' + str(total) + '/' + str(total) + ' 全部成立：'
          + str(len(CASES) - 1) + ' 条注入各自让对应的判据报红，负面对照仍然全绿，还原后逐字节一致')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
