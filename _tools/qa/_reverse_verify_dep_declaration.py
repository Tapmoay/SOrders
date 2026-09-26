#!/usr/bin/env python3
'''反向验证「依赖声明对账」这条判据**真的会红**（R3-07d）。

## 为什么这条要反向验证
_check_dep_declaration.py 判的是「声明」与「本机实际装的版本」之间的差。它的失效方式很安静：
版本比较写反了、例外表把真违反盖住了、棘轮被悄悄调大 —— 三种都表现为**全绿**。

所以这里把每一种失效方式各注入一次（注入 = 把工作区改成「该报红」的样子，跑完按**字节**还原）：

  ① 把一条声明改成**本机装不到**的区间（fastapi <0.100）→ 必须点名那条声明；
  ② 那条违反**登记了但没写退出条件** → 必须报「没写 什么时候删掉这一条」；
  ③ 例外表里塞一条**仓库里根本不存在的声明** → 必须报「不是真实存在的声明」（化石）；
  ④ 加一条**真**违反的例外但棘轮不动 → 必须报「超过棘轮」（棘轮是只减不增的）；
  ⑤ 负面对照（必须仍然全绿）：把 `cryptography` 的声明改成**本机满足**的 `<49` 并清空例外表
     → 证明这条判据**真的在比版本**，而不是「见到 cryptography 就红」。

## ⛔ 已知盲区
- 它只比本机环境；生产上是哪个版本，这条判据**一个字都没有核**（要 R3-05 上机器 `pip freeze`）；
- `-r` 引用的子文件（`requirements-all.txt`）不单独判（它只是把两份拼起来）。

⚠️ 与其它反向验证同一套纪律：注入/还原都按字节做，跑完逐文件核对。
跑之前先上注入锁（lock_reverse_verify）。

用法：python _tools/qa/_reverse_verify_dep_declaration.py
'''
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'ai'))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / '_tools' / 'qa' / '_check_dep_declaration.py'
REQS = ROOT / 'backend' / 'requirements.txt'
NL = chr(10)

#: `cryptography` 那条例外（本仓库当前唯一一条）—— 换掉它就能造出「例外表不同形状」的各种注入。
CRYPTO_KEY = 'cryptography cryptography>=42,<44'
RE_DICT = re.compile(r'EXCEPTIONS: dict\[str, str\] = \{.*?\n\}', re.S)


def compose(*fns):
    def f(text: str) -> str:
        for fn in fns:
            text = fn(text)
        return text
    return f


def sub_once(old: str, new: str):
    def f(text: str) -> str:
        if text.count(old) != 1:
            raise ValueError('注入锚点出现 ' + str(text.count(old)) + ' 次（要恰好一次）：' + old)
        return text.replace(old, new, 1)
    return f


def set_exceptions(literal: str):
    '''把 EXCEPTIONS 整块换成 literal（如 `{}` 或 `{'k': 'v',}`）—— 用来造例外表的各种形状。'''

    def f(text: str) -> str:
        if len(RE_DICT.findall(text)) != 1:
            raise ValueError('EXCEPTIONS 那块认不出来（改过这个脚本？）')
        return RE_DICT.sub('EXCEPTIONS: dict[str, str] = ' + literal, text, count=1)

    return f


CRYPTO_OK = '{' + NL + "    '" + CRYPTO_KEY + "': '已登记。 **什么时候删掉这一条**：拍板后。'," + NL + '}'
THIN = '{' + NL + "    'fastapi fastapi>=0.110,<0.100': '先记一笔。'," + NL + '}'
# ⚠️ 2026-09-26 改了这个注入的**形状**：原来是「塞一条其实不违反的**真**声明（redis）」——
#    那条现在**故意不再报红**（例外描述的是**某个环境**的状态：CI 按声明装到区间内，本来就不该命中，
#    见判据文件头第 5 条）。真正的化石是「挂在一条**仓库里根本不存在**的声明上」：改名 / 抄错 / 依赖被删。
FOSSIL = ('{' + NL + "    '" + CRYPTO_KEY + "': '已登记。 **什么时候删掉这一条**：拍板后。'," + NL
          + "    'foo foo>=1,<2': '这条声明仓库里根本没有。 **什么时候删掉这一条**：不会。'," + NL + '}')
RATCHET_OVER = ('{' + NL + "    '" + CRYPTO_KEY + "': '已登记。 **什么时候删掉这一条**：拍板后。'," + NL
                + "    'fastapi fastapi>=0.110,<0.100': '新违反。 **什么时候删掉这一条**：等升级。'," + NL + '}')

BREAK_FASTAPI = sub_once('fastapi>=0.110,<1', 'fastapi>=0.110,<0.100')
FIX_CRYPTO = sub_once('cryptography>=42,<44', 'cryptography>=42,<49')

CASES: list[tuple] = [
    (
        '把一条声明改成本机装不到的区间 → 必须点名那条声明',
        [(REQS, False, BREAK_FASTAPI)],
        True, 'fastapi>=0.110,<0.100',
    ),
    (
        '违反登记了但没写退出条件 → 必须报「没写 什么时候删掉这一条」',
        [(REQS, False, BREAK_FASTAPI), (CHECK, True, set_exceptions(THIN))],
        True, '什么时候删掉这一条',
    ),
    (
        '例外表里塞一条仓库里根本不存在的声明 → 必须报「不是真实存在的声明」',
        [(CHECK, True, compose(set_exceptions(FOSSIL), sub_once('EXCEPTION_RATCHET = 1', 'EXCEPTION_RATCHET = 2')))],
        True, '真实存在的声明',
    ),
    (
        '加一条真违反的例外但棘轮不动 → 必须报「超过棘轮」',
        [(REQS, False, BREAK_FASTAPI), (CHECK, True, set_exceptions(RATCHET_OVER))],
        True, '超过棘轮',
    ),
    (
        '负面对照：把声明改成**本机满足**的区间并清空例外表 → 必须仍然全绿（判据真的在比版本）',
        [(REQS, False, FIX_CRYPTO), (CHECK, True, set_exceptions('{}'))],
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

    def mutate_copy(self, path: Path, mutate, tag: int) -> Path:
        '''改一份**副本**：注入目标就是检查脚本自己时用（别让检查在被改的状态下跑自己）。'''
        tmp = path.with_suffix('.py.injected' + str(tag))
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
    if not CHECK.exists():
        print('❌ 找不到 ' + str(CHECK))
        return 1

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print('❌ 前提不成立：源码完好时这条判据就没过')
            print(out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print('✅ 前提：源码完好时这条判据是绿的 —— ' + last.strip())

        for label, injections, expect_red, keyword in CASES:
            sb.restore()
            tmps: list[Path] = []
            target: Path | None = None
            try:
                try:
                    for path, is_self, mutate in injections:
                        if is_self:
                            # ⛔ 同一个文件注入两次时要各用一份副本（第二份以**原件**为底，见下面合并）
                            target = sb.mutate_copy(path, mutate, len(tmps))
                            tmps.append(target)
                        else:
                            sb.apply(path, mutate)
                    if len(tmps) == 1:
                        target = tmps[0]
                    elif len(tmps) > 1:
                        raise ValueError('同一个用例里对检查脚本注入两次：合并成一次注入')
                    code, out = run_check(target)
                except ValueError as exc:
                    print('  [MISS] ' + label + ' → 注入没做成（锚点变了就改本脚本）：' + str(exc))
                    bad += 1
                    continue
            finally:
                for t in tmps:
                    if t.exists():
                        t.unlink()
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
        print('  [OK] 还原后这条判据全绿' if ok else '  [MISS] 还原后这条判据没恢复')
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
