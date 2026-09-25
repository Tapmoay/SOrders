#!/usr/bin/env python3
'''反向验证 `_tools/qa/_check_reverse_verify_restore.py` 真的抓得住「还原契约被破」。

## 五种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 某份反向验证的代码里真的去跑 `git checkout` | 红：真的执行了 git checkout |
| ② | 抹掉某份的按字节还原（`write_bytes(`） | 红：没有快照/还原 |
| ③ | 抹掉某份的还原比对 | （L2 计数下降）红：L2 棘轮只增不减 |
| ④ | 例外表里加一条没有理由的 | 红：没写清「为什么 + 什么时候删掉这一条」 |
| ⑤ | 扫描下限失守（脚本被掏空却不喊） | 红：下限 |

⚠️ 与仓库里其它 `_reverse_verify_*.py` 同一套纪律：按**字节**备份/还原、跑完逐文件核对、
⛔ 全程不碰 `git checkout --`。
'''
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'ai'))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / '_tools/qa/_check_reverse_verify_restore.py'
CHK = '_tools/qa/_check_reverse_verify_restore.py'
VICTIM = '_tools/ai/_reverse_verify_ai_entry.py'

CASES: list[tuple[str, str, str, str, str]] = [
    ('① 某份反向验证真的去跑 git checkout', VICTIM,
     'def read_src(path: Path) -> tuple[str, bool]:',
     'def _hack(path):' + chr(10) + '    subprocess.run(["git", "checkout", "--", str(path)])' + chr(10)
     + chr(10) + 'def read_src(path: Path) -> tuple[str, bool]:',
     '真的执行了 git checkout'),
    ('② 抹掉按字节还原', VICTIM, '    path.write_bytes(data.encode("utf-8"))',
     '    pass  # 反向验证注入：不写回了', '没有快照/还原'),
    # ⚠️ ③ 试过「抹掉某一份的比对」：那只让 L2 从 72 掉到 71，**仍在 70 之上**，判据照样绿 ——
    #    说明棘轮是按**总数**判的，单点回退抓不到。要证棘轮真的在守，就把下限抬到计数之上；
    #    单点回退的防线在别处（每份脚本自己跑完会打印「还原后判据全绿」）。
    ('③ L2 棘轮被抬到计数之上（棘轮真的在守）', CHK, 'MIN_L2 = 70', 'MIN_L2 = 139', 'L2'),
    ('④ 例外表里加一条没理由的', CHK,
     "EXCEPTIONS: dict[str, str] = {", "EXCEPTIONS: dict[str, str] = {" + chr(10)
     + "    '_tools/ai/_reverse_verify_ai_entry.py': '先这样',", '没写清'),
    ('⑤ 扫描下限失守（脚本被掏空）', CHK, 'MIN_SCRIPTS = 130', 'MIN_SCRIPTS = 99999', '下限'),
]

CRLF = chr(13) + chr(10)


class Sandbox:
    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def apply(self, rel: str, old: str, new: str) -> None:
        path = ROOT / rel
        if not path.exists():
            raise ValueError('找不到 ' + rel)
        self.saved.setdefault(path, path.read_bytes())
        raw = path.read_bytes()
        crlf = CRLF.encode('utf-8') in raw
        text = raw.decode('utf-8')
        if crlf:
            text = text.replace(CRLF, chr(10))
        if text.count(old) != 1:
            raise ValueError(rel + ' 里锚点出现 ' + str(text.count(old)) + ' 次（要恰好一次）')
        text = text.replace(old, new, 1)
        path.write_bytes((text.replace(chr(10), CRLF) if crlf else text).encode('utf-8'))

    def restore(self) -> None:
        for path, raw in self.saved.items():
            path.write_bytes(raw)

    def dirty(self) -> list[str]:
        return [str(p.relative_to(ROOT)) for p, raw in self.saved.items() if p.read_bytes() != raw]


def run_check() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', cwd=str(ROOT))
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(CASES, 1):
            print(str(i) + '. ' + name + chr(10) + '      ' + rel + '   ← 期望被「' + want + '」抓到')
        return 0

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print('❌ 前提不成立：源码完好时这条判据就没过')
            print(out[-1500:])
            return 1
        print('✅ 前提：源码完好时判据是绿的')
        for label, rel, old, new, want in CASES:
            sb.restore()
            try:
                sb.apply(rel, old, new)
                code, out = run_check()
            except ValueError as exc:
                print('  [SKIP] ' + label + ' —— ' + str(exc))
                bad += 1
                continue
            finally:
                sb.restore()
            hit = code != 0 and want in out
            if hit:
                print('  [OK] ' + label + ' → 判据报红并命中「' + want + '」')
            else:
                bad += 1
                why = '判据居然还是绿的' if code == 0 else '退出了，但没报出「' + want + '」'
                print('  [MISS] ' + label + ' → ' + why)
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith('❌')][:5]:
                    print('       判据实际报的：' + ln)
        sb.restore()
        code, out = run_check()
        ok = code == 0
        print('  [OK] 还原后判据全绿' if ok else '  [MISS] 还原后判据没恢复')
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
    print('✅ ' + str(total) + '/' + str(total) + ' 全部成立：真跑 git checkout / 没有还原 / '
          '少了比对 / 例外没理由 / 扫描下限失守 都会被抓到')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

