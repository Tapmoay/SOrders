#!/usr/bin/env python3
'''反向验证 `_tools/qa/_check_generated_freshness.py` 真的抓得住「产物与源码走散」。

## 六种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 改一个真源文件（而不重跑生成器） | 红：与现算指纹不一致 |
| ② | 手改产物里的 source_hash | 红：与现算指纹不一致 |
| ③ | 把产物里的 source_hash 抹掉 | 红：里没有 source_hash |
| ④ | 把某产物的真源 glob 改成匹配不到文件的 | 红：一个文件都没匹配上 |
| ⑤ | 产物声明的 source_commit 编一个不存在的 sha | 红：不是本仓库里的提交 |
| ⑥ | 反空转下限失守（产物清单被掏空却不喊） | 红：下限 |

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
CHECK = ROOT / '_tools/qa/_check_generated_freshness.py'
GEN = 'backend/scripts/gen_endpoint_index.py'
IDX = 'docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md'
SNAP = 'docs/CAPABILITY_SNAPSHOT.json'
AIREPO = '_tools/ai/_airepo.py'
CHK = '_tools/qa/_check_generated_freshness.py'

CASES: list[tuple[str, str, str, str, str]] = [
    ('① 改真源而不重跑生成器', GEN,
     'import ast', 'import ast' + chr(10) + '# 反向验证注入的一行（不改语义，只改字节）',
     '与现算指纹不一致'),
    ('② 手改产物里的 source_hash', IDX,
     '<!-- source_hash: sha256:', '<!-- source_hash: sha256:0', '与现算指纹不一致'),
    ('③ 把产物里的 source_hash 抹掉', IDX,
     '<!-- source_hash: ', '<!-- hash: ', '里没有 source_hash'),
    ('④ 真源 glob 改成匹配不到文件的', AIREPO,
     "sources=('backend/app/**/*.py', 'android/app/src/main/**/*.kt'),",
     "sources=('nope/**/*.zzz',),", '一个文件都没匹配上'),
    ('⑤ 声明一个不存在的 source_commit', SNAP,
     '"source_commit": "', '"source_commit": "deadbeef', '不是本仓库里的提交'),
    ('⑥ 反空转下限失守（产物清单被掏空）', CHK,
     'MIN_ARTIFACTS = 4', 'MIN_ARTIFACTS = 99', '下限'),
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
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print('✅ 前提：源码完好时判据是绿的 —— ' + last.strip())
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
    print('✅ ' + str(total) + '/' + str(total) + ' 全部成立：真源变了没重跑 / 手改指纹 / 抹掉指纹 / '
          '真源 glob 空转 / 编造提交 / 产物清单被掏空 都会被抓到')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

