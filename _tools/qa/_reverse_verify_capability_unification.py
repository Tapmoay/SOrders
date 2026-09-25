#!/usr/bin/env python3
'''反向验证 `_tools/qa/_check_capability_unification.py` 真的抓得住「两端各走各的」。

## 七种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 改后端能力表的一句话（产物该跟着变） | 红：产物已过期 |
| ② | 手改生成的 Kotlin 里的 SOURCE_HASH | 红：与后端不一致 |
| ③ | 往某个 Kotlin 文件里塞 3 个权限键字面量 | 红：手写的权限键表 |
| ④ | 角色能力的 gate 指到一行不是角色门的地方 | 红：不是角色门 |
| ⑤ | 角色能力键改成与权限点同名 | 红：与权限点重名 |
| ⑥ | 从一个能力下面删掉它的动作码 | 红：既没有能力认领 |
| ⑦ | 反空转下限失守（覆盖表被掏空却不喊） | 红：被覆盖的动作码只有 |

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
CHECK = ROOT / '_tools/qa/_check_capability_unification.py'
CAPS = 'backend/app/core/capabilities.py'
ROLE_CAPS = 'backend/app/core/role_capabilities.py'
COVER = 'backend/app/core/capability_audit_coverage.py'
KT = 'android/app/src/main/java/com/tapmoay/sorders/core/Capabilities.kt'
MODULES = 'android/app/src/main/java/com/tapmoay/sorders/ui/nav/Modules.kt'
CHK = '_tools/qa/_check_capability_unification.py'

CASES: list[tuple[str, str, str, str, str]] = [
    ('① 改后端能力表的一句话（产物该跟着变）', CAPS,
     'what="把待派单派给某位司机"', 'what="把待派单派给某位司机（改过）"', '产物已过期'),
    ('② 手改生成物里的 SOURCE_HASH', KT,
     'const val SOURCE_HASH: String = "sha256:41fc',
     'const val SOURCE_HASH: String = "sha256:dead', '与后端不一致'),
    ('③ 往 Kotlin 里塞手写的权限键表', MODULES, 'data class ModuleEntry(',
     'private val HACK = setOf("order:create", "order:edit", "order:dispatch")' + chr(10)
     + 'data class ModuleEntry(', '手写的权限键表'),
    ('④ 角色能力的 gate 指到不是角色门的一行', ROLE_CAPS,
     "gate='backend/app/api/v1/unit_conversions.py:44'", "gate='backend/app/api/v1/unit_conversions.py:1'",
     '不是角色门'),
    ('⑤ 角色能力键与权限点同名', ROLE_CAPS, "key='address:manage'", "key='order:dispatch'", '与权限点重名'),
    ('⑥ 从一个能力下面删掉动作码', COVER,
     "'order:recall': ('ORDER_RECALL',),", "'order:recall': (),", '既没有能力认领'),
    ('⑦ 反空转下限失守（覆盖表被掏空）', CHK,
     'MIN_ACTION_CODES = 80', 'MIN_ACTION_CODES = 999', '被覆盖的动作码只有'),
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
    print('✅ ' + str(total) + '/' + str(total) + ' 全部成立：产物过期 / 生成物被手改 / Kotlin 里手写权限表 / '
          '假角色门 / 键重名 / 动作码失去认领 / 覆盖表被掏空 都会被抓到')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

