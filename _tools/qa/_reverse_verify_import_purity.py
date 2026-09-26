#!/usr/bin/env python3
'''反向验证 `_tools/qa/_check_import_purity.py` 真的抓得住「import 就会改库」这一类错误。

## 六种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 把 `bootstrap_schema(engine)` 注回 `app/database.py` | 红：出现了建库/迁移动作 |
| ② | `app/database.py` 重新 import `app.core.schema_bootstrap` | 红：还 import 了 app.core.schema_bootstrap |
| ③ | 启动路径里调用迁移（`prepare_schema`） | 红：启动路径里出现了迁移调用 |
| ④ | 把启动核对 `assert_schema_ready()` 删掉 | 红：启动路径里没有 schema_ready |
| ⑤ | 让 `schema_ready()` 建表（`ensure_version_table`） | 红：schema_ready 不是只读的 |
| ⑥ | 快照下限失守（判据在空转却不喊） | 红：快照太小 |

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
CHECK = ROOT / '_tools/qa/_check_import_purity.py'
DB = 'backend/app/database.py'
MAIN = 'backend/app/main.py'
RUNNER = 'backend/app/migrations/_runner.py'
CHK = '_tools/qa/_check_import_purity.py'
NL = chr(10)

SESS = 'SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)'
LIFE = '    assert_schema_ready()' + NL + '    task = asyncio.create_task(_retention_loop())'
# ⛔ 2026-09-26 修锚点：`try:` + `if not inspect(engine).has_table(VERSION_TABLE):` 这一对在
#    `_runner.py` 里出现了**两次**（`applied_versions()` 与 `schema_ready()`）—— 要求恰好一次的注入
#    于是恒 SKIP。锚点往下多带一行（`schema_ready` 独有的那句中文报错），就唯一了。
READY_TRY = ('    try:' + NL + '        if not inspect(engine).has_table(VERSION_TABLE):' + NL
             + '            return False, f' + chr(34) + '没有迁移记录表 `{VERSION_TABLE}` —— 这个库从没跑过迁移' + chr(34))

CASES: list[tuple[str, str, str, str, str]] = [
    ('① 把 bootstrap_schema(engine) 注回 database.py', DB, SESS, SESS + NL + 'bootstrap_schema(engine)',
     '出现了建库/迁移动作'),
    ('② database.py 重新 import 自愈模块', DB, SESS,
     'from app.core.schema_bootstrap import bootstrap_schema' + NL + SESS,
     '还 import 了 app.core.schema_bootstrap'),
    ('③ 启动路径里调用迁移', MAIN, LIFE, '    prepare_schema(None)' + NL + LIFE,
     '启动路径里出现了迁移调用'),
    ('④ 启动核对被删掉', MAIN, LIFE, '    task = asyncio.create_task(_retention_loop())',
     '启动路径里没有 schema_ready'),
    ('⑤ schema_ready 变成会建表', RUNNER, READY_TRY,
     '    try:' + NL + '        ensure_version_table(engine)' + NL + READY_TRY,
     'schema_ready 不是只读的'),
    ('⑥ 快照下限失守（判据空转）', CHK, 'MIN_TABLES = 40', 'MIN_TABLES = 999', '快照太小'),
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
            text = text.replace(CRLF, NL)
        if text.count(old) != 1:
            raise ValueError(rel + ' 里锚点出现 ' + str(text.count(old)) + ' 次（要恰好一次）')
        text = text.replace(old, new, 1)
        path.write_bytes((text.replace(NL, CRLF) if crlf else text).encode('utf-8'))

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
            print(str(i) + '. ' + name + NL + '      ' + rel + '   ← 期望被「' + want + '」抓到')
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
    print('✅ ' + str(total) + '/' + str(total) + ' 全部成立：import 时建库 / 重新 import 自愈模块 / '
          '启动偷偷迁移 / 启动不核对 / 只读核对变成写 / 判据空转 都会被抓到')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

