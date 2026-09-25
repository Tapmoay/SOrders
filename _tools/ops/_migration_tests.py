#!/usr/bin/env python3
'''_migration_tests.py —— R3-01-E 要求的三个（这里是四个）迁移测试。

指南 §R3-01-E 原文：

    测试 1：Migration Fresh DB   空数据库 → migration → current version → 启动
    测试 2：Migration Old DB     version N → migration → version N+1
    测试 3：双实例同时 migration 只能一个实际执行，另一个等待 → 发现已经完成 → 继续启动

本仓库多一个「失败不许留下半截」的用例（指南 R3-01 退出条件第 7 条：
migration 失败不会启动半残服务）。

用法：
    python _tools/ops/_migration_tests.py --all
    python _tools/ops/_migration_tests.py --fresh --old --concurrent --fail-fast

⛔ 全程只用 %TEMP% 下的临时库，不碰任何已有数据库。
'''
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
#: ⛔ **不许写死版本号**：写死的那一版（7）在 R3-04 加了迁移 008 之后就过期了 ——
#: 而它不会报错，只会让「空库迁移通过」这条用例静默地判错（实测：R3-07 的报告事实核对
#: 判据把它抓出来时，台账里那三行 ✅ 已经挂了两轮）。现在从 `app.migrations` 现算。
def _latest_version() -> int:
    code, out = py('from app.migrations import discover; print(max(m.version for m in discover()))', 'sqlite://')
    for ln in reversed(out.splitlines()):
        if ln.strip().isdigit():
            return int(ln.strip())
    raise SystemExit('❌ 拿不到迁移版本数（app.migrations.discover() 没回答）：' + out[-300:])


#: 由 `main()` 现算后写进来（每次运行都重新问一遍 `app.migrations`）。
LATEST = 0
MIN_TABLES = 40


def sub_env(url: str) -> dict:
    env = dict(os.environ)
    env['DATABASE_URL'] = url
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    env.pop('SORDERS_SKIP_MIGRATIONS', None)
    return env


def py(code: str, url: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, '-c', code], cwd=str(BACKEND), env=sub_env(url),
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.returncode, ((p.stdout or '') + (p.stderr or ''))


def cli(url: str, *args: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, '-m', 'app.migrations', *args], cwd=str(BACKEND),
                       env=sub_env(url), capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.returncode, ((p.stdout or '') + (p.stderr or ''))


def url_of(db: Path) -> str:
    return 'sqlite:///' + str(db)


def versions(db: Path) -> list[int]:
    if not db.exists():
        return []
    con = sqlite3.connect(str(db))
    try:
        try:
            return [int(r[0]) for r in con.execute('SELECT version FROM schema_versions ORDER BY version')]
        except sqlite3.Error:
            return []
    finally:
        con.close()


def shape(db: Path) -> dict:
    con = sqlite3.connect(str(db))
    try:
        rows = con.execute('SELECT type, name, sql FROM sqlite_master ORDER BY type, name').fetchall()
        cols = {}
        for r in rows:
            if r[0] == 'table':
                cols[r[1]] = [c[1] for c in con.execute('PRAGMA table_info(' + r[1] + ')').fetchall()]
        return {'objects': rows, 'columns': cols}
    finally:
        con.close()


def case_fresh(tmp: Path) -> tuple[bool, list[str]]:
    db = tmp / 'fresh.db'
    rc, out = cli(url_of(db), 'upgrade')
    lines = ['  upgrade 退出码 ' + str(rc)]
    if rc != 0:
        return False, lines + ['  ' + out.strip()[-300:]]
    v = versions(db)
    sh = shape(db)
    ok = v == list(range(1, LATEST + 1)) and len(sh['columns']) >= MIN_TABLES
    lines.append('  版本 ' + str(v[-1] if v else 0) + ' / 表 ' + str(len(sh['columns'])))
    rc2, out2 = py('from app.main import assert_schema_ready; assert_schema_ready(); print('
                   + repr('启动核对通过') + ')', url_of(db))
    lines.append('  启动核对退出码 ' + str(rc2) + ' ' + out2.strip().splitlines()[-1][:60])
    return ok and rc2 == 0, lines


def case_old(tmp: Path) -> tuple[bool, list[str]]:
    db = tmp / 'old.db'
    rc, out = py('import os;'
                 'from sqlalchemy import create_engine;'
                 'from app.core.schema_bootstrap import apply_runtime_self_heal as f;'
                 'f(create_engine(os.environ[' + repr('DATABASE_URL') + '], future=True));'
                 'print(' + repr('自愈完成') + ')', url_of(db))
    lines = ['  自愈（老库：结构在、没有迁移记录）退出码 ' + str(rc)]
    if rc != 0:
        return False, lines + ['  ' + out.strip()[-300:]]
    before = shape(db)
    v0 = versions(db)
    lines.append('  自愈后：表 ' + str(len(before['columns'])) + ' / 版本 ' + str(v0))
    rc2, out2 = cli(url_of(db), 'upgrade')
    after = shape(db)
    v1 = versions(db)
    lost = [t for t in before['columns'] if t not in after['columns']]
    lost_cols = [t + '.' + c for t in before['columns'] for c in before['columns'][t]
                 if c not in after['columns'].get(t, [])]
    ok = rc2 == 0 and v0 == [] and v1 == list(range(1, LATEST + 1)) and not lost and not lost_cols
    lines.append('  upgrade 退出码 ' + str(rc2) + ' / 版本 ' + str(v1[-1] if v1 else 0))
    lines.append('  结构有没有丢：' + ('没有' if not lost and not lost_cols
                 else '丢了 ' + ','.join(lost + lost_cols)))
    return ok, lines


def case_concurrent(tmp: Path) -> tuple[bool, list[str]]:
    db = tmp / 'dual.db'
    procs = [subprocess.Popen([sys.executable, '-m', 'app.migrations', 'upgrade'], cwd=str(BACKEND),
                              env=sub_env(url_of(db)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding='utf-8', errors='replace') for _ in range(2)]
    outs = []
    for p in procs:
        # ⛔ 必须 communicate()：先 wait() 再 read() 会在管道写满时**死锁**（实测把整条用例挂住）。
        try:
            text_out, _ = p.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            p.kill()
            text_out, _ = p.communicate()
            outs.append((-9, text_out or ''))
            continue
        outs.append((p.returncode, text_out or ''))
    v = versions(db)
    lines = ['  两个进程退出码 ' + str([o[0] for o in outs])]
    lines.append('  版本表：' + str(v) + '（每个版本必须恰好一行）')
    dup = len(v) != len(set(v))
    ok = all(o[0] == 0 for o in outs) and not dup and v == list(range(1, LATEST + 1))
    lines.append('  重复记账：' + ('有 ⛔' if dup else '没有'))
    plat = 'msvcrt.locking（Windows）' if sys.platform.startswith('win') else 'fcntl.flock（POSIX）'
    lines.append('  本机互斥：' + plat + '；跨**主机**互斥是 MySQL GET_LOCK（生产；SQLite 上如实只用本机锁）')
    return ok, lines


def case_fail_fast(tmp: Path) -> tuple[bool, list[str]]:
    src_dir = BACKEND / 'app' / 'migrations'
    work = tmp / 'migrations'
    work.mkdir()
    for f in sorted(src_dir.glob('[0-9][0-9][0-9]_*.py')):
        shutil.copy2(f, work / f.name)
    (work / '099_broken.py').write_text(
        'DESCRIPTION = ' + repr('故意失败的迁移（测试用）') + '\n'
        'def upgrade(engine):\n'
        '    raise RuntimeError(' + repr('boom') + ')\n', encoding='utf-8')
    db = tmp / 'failfast.db'
    code = ('import os;'
            'from sqlalchemy import create_engine;'
            'from pathlib import Path;'
            'from app.migrations import run_migrations, MigrationFailed;'
            'd = Path(os.environ[' + repr('MIG_DIR') + ']);'
            'eng = create_engine(os.environ[' + repr('DATABASE_URL') + '], future=True);'
            '\n'
            'try:\n'
            '    run_migrations(eng, directory=d)\n'
            'except MigrationFailed as e:\n'
            '    print(' + repr('按预期失败：') + ' + str(e)[:80])\n'
            '    raise SystemExit(3)\n'
            'raise SystemExit(0)\n')
    env = sub_env(url_of(db))
    env['MIG_DIR'] = str(work)
    p = subprocess.run([sys.executable, '-c', code], cwd=str(BACKEND), env=env,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    v = versions(db)
    leaked = 99 in v
    lines = ['  退出码 ' + str(p.returncode) + '（3 = 按预期抛了 MigrationFailed）']
    lines.append('  版本表：' + str(v) + '（⛔ 不许出现 99）')
    lines.append('  ' + ((p.stdout or '') + (p.stderr or '')).strip().splitlines()[-1][:90]
                 if ((p.stdout or '') + (p.stderr or '')).strip() else '  （无输出）')
    ok = p.returncode == 3 and not leaked and 7 in v
    lines.append('  半残启动：')
    if ok:
        lines[-1] += '不会 —— 失败的版本没记账，1..7 都在，下一次会重试 99'
    else:
        lines[-1] += '⛔ 用例不成立'
    return ok, lines


CASES = {
    'fresh': ('测试 1：空库 → 迁移 → 当前版本 → 启动核对', case_fresh),
    'old': ('测试 2：老库（结构在、无迁移记录）→ 迁移 → 最新版本，且结构没被破坏', case_old),
    'concurrent': ('测试 3：两个进程同时迁移 → 只能记一次账', case_concurrent),
    'fail-fast': ('测试 4（本仓库加的）：迁移失败 → 不记账、不半残', case_fail_fast),
}


def main() -> int:
    global LATEST
    LATEST = _latest_version()          # ⛔ 现算，不写死（写死过 7，加了迁移 008 之后就判错了）
    ap = argparse.ArgumentParser(description='R3-01 迁移生命周期测试')
    for name in CASES:
        ap.add_argument('--' + name, action='store_true')
    ap.add_argument('--all', action='store_true', help='四个都跑')
    a = ap.parse_args()
    picked = [n for n in CASES if getattr(a, n.replace('-', '_'))]
    if a.all or not picked:
        picked = list(CASES)

    tmp = Path(tempfile.mkdtemp(prefix='r3_mig_'))
    bad = 0
    try:
        for name in picked:
            title, fn = CASES[name]
            print('▶ ' + title)
            try:
                ok, lines = fn(tmp)
            except Exception as exc:                       # noqa: BLE001
                ok, lines = False, ['  抛异常：' + repr(exc)[:200]]
            for ln in lines:
                print(ln)
            print('  ' + ('✅ 成立' if ok else '❌ 不成立'))
            print()
            bad += 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if bad:
        print('❌ ' + str(bad) + '/' + str(len(picked)) + ' 个用例不成立')
        return 1
    print('✅ ' + str(len(picked)) + '/' + str(len(picked)) + ' 个用例全部成立')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
