#!/usr/bin/env python3
'''_check_import_purity.py —— **import 不得产生持久化副作用**（R3-01 的核心不变量）。

指南 §R3-01-C 的原话：

    import app.database 不能产生 CREATE / ALTER / DROP / INSERT / UPDATE / DELETE 任何副作用。
    这个判据最好做成真正的反向验证：注入一个 import → 检查数据库 schema version → 必须完全不变。

R3-01 之前它是这样的：backend/app/database.py 的最后两行是
from app.core.schema_bootstrap import bootstrap_schema + bootstrap_schema(engine) ——
于是 import app.database 就等于改库：一个只读排障脚本只要 import 它，就会在别人的库上跑 DDL。

## 八组判据
1. app/database.py 里不许出现建库/迁移调用（bootstrap_schema / prepare_schema / create_all / DDL 文本）；
2. app/database.py 不许 import app.core.schema_bootstrap；
3. 启动路径（app/main.py 的 lifespan）不许调用迁移，只准 schema_ready(；
4. 动态：**已经建好结构的库**，import app.database 前后结构必须逐字节相同（表/列/索引/版本行）；
5. 动态：**不存在的库**，import app.database 之后文件仍不得被创建；
6. 动态：from app.main import app 同样零副作用（导入应用 ≠ 准备数据库）；
7. 动态：schema_ready() 是**只读**的 —— 在没跑过迁移的库上返回 False，且不许建出 schema_versions；
8. 反空转：快照里必须有 ≥ MIN_TABLES 张表、版本行 ≥ MIN_VERSIONS，否则「零差异」可能只是两边都空。

用法：python _tools/qa/_check_import_purity.py
'''
from __future__ import annotations

import ast
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
MIN_TABLES = 40
MIN_VERSIONS = 7

#: 不许出现的**调用**（按 AST 的函数名匹配 —— ⛔ 不扫注释/文档字符串：文档里提到这些名字是应该的，
#:  扫文本会把自己文档里的说明判成违规，那正是本仓库栽过的「判据被文字满足/被文字误伤」。）
FORBIDDEN_CALLS = {'bootstrap_schema', 'prepare_schema', 'run_migrations', 'create_all'}
DDL_WORDS = ('ALTER TABLE', 'CREATE TABLE', 'DROP TABLE')


def _tree(src: str) -> ast.Module:
    return ast.parse(src)


def called_names(src: str) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(_tree(src)):
        if isinstance(node, ast.Call):
            name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            if name:
                out.add(name)
    return out


def imported_modules(src: str) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(_tree(src)):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.add(node.module or '')
    return out


def ddl_literals(src: str) -> list[str]:
    out: list[str] = []
    for node in ast.walk(_tree(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            up = node.value.upper()
            out.extend(w for w in DDL_WORDS if w in up)
    return out


def startup_closure(src: str) -> tuple[set[str], str]:
    '''从 lifespan 出发、只沿着本文件内定义的函数往下走，收集所有被调用的名字。'''
    tree = _tree(src)
    local: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local[node.name] = node
    if 'lifespan' not in local:
        return set(), ''
    seen: set[str] = set()
    calls: set[str] = set()
    stack = ['lifespan']
    while stack:
        name = stack.pop()
        if name in seen or name not in local:
            continue
        seen.add(name)
        for node in ast.walk(local[name]):
            if isinstance(node, ast.Call):
                callee = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
                if callee:
                    calls.add(callee)
                    stack.append(callee)
    return calls, 'lifespan'


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8', errors='replace')


def snapshot(db: Path) -> dict:
    '''结构快照：表/索引的建表语句 + 每张表的列 + 迁移版本行。⛔ 不 import app。'''
    con = sqlite3.connect(str(db))
    try:
        rows = con.execute(
            'SELECT type, name, sql FROM sqlite_master ORDER BY type, name'
        ).fetchall()
        objects = [(r[0], r[1], r[2] or '') for r in rows]
        cols: dict[str, list] = {}
        for row in objects:
            if row[0] == 'table':
                cols[row[1]] = con.execute('PRAGMA table_info(' + row[1] + ')').fetchall()
        try:
            versions = con.execute(
                'SELECT version, name, checksum FROM schema_versions ORDER BY version'
            ).fetchall()
        except sqlite3.Error:
            versions = []
    finally:
        con.close()
    return {'objects': objects, 'columns': cols, 'versions': versions}


def sub_env(url: str) -> dict:
    env = dict(os.environ)
    env['DATABASE_URL'] = url
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    env.pop('SORDERS_SKIP_MIGRATIONS', None)
    return env


def run_py(code: str, url: str) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, '-c', code], cwd=str(BACKEND), env=sub_env(url),
                          capture_output=True, text=True, encoding='utf-8', errors='replace')
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def prepare(db: Path) -> tuple[bool, str]:
    '''用「迁移的唯一入口」把结构建好（= python -m app.migrations upgrade）。'''
    proc = subprocess.run([sys.executable, '-m', 'app.migrations', 'upgrade'], cwd=str(BACKEND),
                          env=sub_env('sqlite:///' + str(db)), capture_output=True, text=True,
                          encoding='utf-8', errors='replace')
    ok = proc.returncode == 0 and db.exists()
    return ok, ((proc.stdout or '') + (proc.stderr or ''))[-400:]


READONLY_PROBE = '\n'.join([
    'from sqlalchemy import create_engine, inspect',
    'import os',
    'from app.migrations import schema_ready, VERSION_TABLE',
    'eng = create_engine(os.environ.get(' + repr('DATABASE_URL') + '), future=True)',
    'ok, why = schema_ready(eng)',
    'print(ok, why)',
    'assert ok is False, ' + repr('空库上 schema_ready 居然说准备好了'),
    'assert not inspect(eng).has_table(VERSION_TABLE), ' + repr('schema_ready 建了版本表 —— 它不是只读的'),
    'print(' + repr('只读核对通过') + ')',
])


def main() -> int:
    fails: list[str] = []
    checks = 0

    # ① / ② app/database.py 不许建库、不许 import 自愈模块（按 AST 看调用与导入，不扫文字）
    src = read('backend/app/database.py')
    calls = called_names(src)
    checks += 1
    hit = sorted(FORBIDDEN_CALLS & calls) + ddl_literals(src)
    if hit:
        fails.append('app/database.py 里出现了建库/迁移动作：' + '、'.join(sorted(set(hit))))
    checks += 1
    if 'app.core.schema_bootstrap' in imported_modules(src):
        fails.append('app/database.py 还 import 了 app.core.schema_bootstrap')

    # ③ 启动路径（lifespan 及其在本文件内调用的函数）只准核对，不准迁移
    main_src = read('backend/app/main.py')
    closure, why = startup_closure(main_src)
    checks += 1
    if not closure:
        fails.append('在 app/main.py 里找不到 lifespan —— 启动路径核对不了（' + why + '）')
    else:
        bad = sorted(FORBIDDEN_CALLS & closure)
        if bad:
            fails.append('启动路径里出现了迁移调用：' + '、'.join(bad))
        if 'schema_ready' not in closure:
            fails.append('启动路径里没有 schema_ready —— 没法证明「启动只核对结构」')

    tmp = Path(tempfile.mkdtemp(prefix='r3_impurity_'))
    try:
        # ④ 已有结构的库：import 前后必须完全一样
        db = tmp / 'prepared.db'
        ok, out = prepare(db)
        checks += 1
        if not ok:
            fails.append('前提不成立：建库失败 —— ' + out.strip()[-160:])
        else:
            before = snapshot(db)
            checks += 1
            if len(before['columns']) < MIN_TABLES or len(before['versions']) < MIN_VERSIONS:
                fails.append('快照太小（表 ' + str(len(before['columns'])) + ' / 版本 '
                              + str(len(before['versions'])) + '）—— 判据在空转，先查建库那一步')
            else:
                code, out = run_py('import app.database', 'sqlite:///' + str(db))
                checks += 1
                if code != 0:
                    fails.append('import app.database 直接失败了：' + out.strip()[-200:])
                else:
                    after = snapshot(db)
                    if after != before:
                        diffs = []
                        if after['objects'] != before['objects']:
                            diffs.append('建表/索引语句变了')
                        if after['columns'] != before['columns']:
                            diffs.append('列变了')
                        if after['versions'] != before['versions']:
                            diffs.append('迁移版本行变了')
                        fails.append('import app.database **改了库**：' + '、'.join(diffs))

        # ⑤ 不存在的库：import 之后不许冒出来
        fresh = tmp / 'fresh.db'
        code, out = run_py('import app.database', 'sqlite:///' + str(fresh))
        checks += 1
        if code != 0:
            fails.append('空库上 import app.database 失败了：' + out.strip()[-200:])
        elif fresh.exists():
            fails.append('import app.database 在空目录里**建出了库文件**（副作用）')

        # ⑥ 导入应用同样零副作用
        app_db = tmp / 'prepared2.db'
        ok2, _ = prepare(app_db)
        checks += 1
        if not ok2:
            fails.append('前提不成立：第二份库没建起来')
        else:
            before2 = snapshot(app_db)
            code, out = run_py('from app.main import app; assert app is not None',
                               'sqlite:///' + str(app_db))
            checks += 1
            if code != 0:
                fails.append('import app.main 失败了：' + out.strip()[-200:])
            elif snapshot(app_db) != before2:
                fails.append('import app.main **改了库**（导入应用不该碰结构）')

        # ⑦ schema_ready 必须是只读的
        blank = tmp / 'blank.db'
        sqlite3.connect(str(blank)).close()
        checks += 1
        code, out = run_py(READONLY_PROBE, 'sqlite:///' + str(blank))
        if code != 0:
            fails.append('schema_ready 不是只读的：' + out.strip()[-220:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if fails:
        for f in fails:
            print('  ❌ ' + f)
        print()
        print('❌ ' + str(len(fails)) + ' 条不成立（共核对 ' + str(checks) + ' 处）')
        return 1
    print('  ✅ import 纯净：import app.database / import app.main 都不改库，'
          'schema_ready 只读，启动只核对不迁移。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
