"""迁移版本化（`app/migrations`）：版本表 / 顺序执行 / 内容漂移 / 失败不记账。

## 为什么单独立一条（2026-09-24 整改阶段 2）

报告把「schema 迁移版本化」列为整个架构改造的第一核心任务，理由是：
现在「应用启动 ＝ 数据库迁移 ＝ 服务可用性」，而 `schema_bootstrap.py` 1600+ 行里
**没有版本表** —— 「这句 DDL 到底跑过没有」只能靠"它是幂等的"来兜。

这一族判据守的是**恢复现场**才会暴露的东西：

1. 跑过的**不许再跑**（重复执行业务迁移＝数据被搬两遍，而且谁也不报错）；
2. 跑过的迁移**内容变了**要说出来（改了历史迁移＝别人的库和你以为的不一样）；
3. 失败的迁移**不许记账**（记了就等于"下次不重试"，结构永远停在半截）；
4. 校验和要**跨平台一致**（本机 Windows 是 CRLF、生产是 LF —— 不归一会天天假红）。

⚠️ 单测只用 SQLite 临时库：**不碰** `conftest.py` 那套共享测试库（本仓库踩过"两个 pytest 会话互踩"）。
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.migrations import (
    MIGRATIONS_DIR,
    VERSION_TABLE,
    MigrationError,
    MigrationFailed,
    current_version,
    discover,
    migration_status,
    run_migrations,
)
from app.migrations._runner import _CREATE_SQL, _checksum


def _engine(tmp_path: Path):
    return create_engine(f"sqlite:///{tmp_path / 'mig.db'}", future=True)


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


MIG_TEMPLATE = """
VERSION = {v}
NAME = "{name}"
DESCRIPTION = "测试用迁移 {name}"


def upgrade(engine):
    with engine.begin() as conn:
        conn.execute(__import__("sqlalchemy").text(
            "CREATE TABLE IF NOT EXISTS t_{v} (id INTEGER PRIMARY KEY)"))
"""


def _table_exists(engine, name: str) -> bool:
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars().all()
    return name in rows


# ---------------------------------------------------------------- 命名与发现


def test_unversioned_file_is_rejected(tmp_path: Path):
    """没有版本号的文件**必须当场报错**：不报错的话它就是一个"看起来像迁移、谁也不跑"的东西。"""
    _write(tmp_path / "add_something.py", "def upgrade(engine):\n    pass\n")
    with pytest.raises(MigrationError) as e:
        discover(tmp_path)
    assert "NNN" in str(e.value)


def test_duplicate_version_is_rejected(tmp_path: Path):
    _write(tmp_path / "002_a.py", MIG_TEMPLATE.format(v=2, name="a"))
    _write(tmp_path / "002_b.py", MIG_TEMPLATE.format(v=2, name="b"))
    with pytest.raises(MigrationError) as e:
        discover(tmp_path)
    assert "被两个文件用了" in str(e.value)


def test_checksum_ignores_crlf(tmp_path: Path):
    """同一份内容在 Windows(CRLF) 与 Linux(LF) 上必须算出**同一个**校验和。

    不归一的话，同一份迁移在本机算一个值、在生产算另一个 —— 表现是生产上永远报
    "你改了历史迁移"，而那种假红会让人学会无视这条检查。
    """
    lf = tmp_path / "lf.py"
    crlf = tmp_path / "crlf.py"
    body = "VERSION = 1\nNAME = 'x'\ndef upgrade(engine):\n    pass\n"
    lf.write_bytes(body.encode())
    crlf.write_bytes(body.replace("\n", "\r\n").encode())
    assert _checksum(lf) == _checksum(crlf)


def test_dialect_ddl_is_explicit_for_both_engines():
    """版本表的建表语句必须显式支持 mysql 与 sqlite —— 不认识的方言要报错，不许静默跳过。"""
    assert set(_CREATE_SQL) >= {"mysql", "sqlite"}, _CREATE_SQL.keys()
    for name, ddl in _CREATE_SQL.items():
        assert VERSION_TABLE in ddl and "version" in ddl and "checksum" in ddl, (name, ddl)


# ---------------------------------------------------------------- 执行与记账


def test_first_run_registers_baseline(tmp_path: Path):
    """真实 `migrations/` 目录：第一次跑应当把基线登记成版本 1，并把文件校验和写进去。"""
    engine = _engine(tmp_path)
    report = run_migrations(engine, directory=MIGRATIONS_DIR)
    assert [a["version"] for a in report["applied"]] == [1], report
    assert report["failed"] is None
    assert current_version(engine) == 1
    with engine.begin() as conn:
        row = conn.execute(text(f"SELECT name, checksum FROM {VERSION_TABLE} WHERE version = 1")).one()
    assert row[0] == "baseline"
    assert row[1] == _checksum(MIGRATIONS_DIR / "001_baseline.py")


def test_second_run_is_a_noop(tmp_path: Path):
    """幂等：第二次跑**什么都不做**（版本表里的版本一律跳过）。"""
    engine = _engine(tmp_path)
    run_migrations(engine, directory=MIGRATIONS_DIR)
    with engine.begin() as conn:
        before = conn.execute(text(f"SELECT applied_at FROM {VERSION_TABLE} WHERE version = 1")).scalar()
    report = run_migrations(engine, directory=MIGRATIONS_DIR)
    assert report["applied"] == [] and report["skipped"] == [1], report
    with engine.begin() as conn:
        after = conn.execute(text(f"SELECT applied_at FROM {VERSION_TABLE} WHERE version = 1")).scalar()
    assert before == after, "第二次跑把 applied_at 改了 —— 说明它其实重跑了一遍"


def test_pending_run_in_version_order_and_create_tables(tmp_path: Path):
    """待跑的按版本号升序执行，而且真的落了库（不是只记账）。"""
    engine = _engine(tmp_path)
    d = tmp_path / "migs"
    d.mkdir()
    for v, name in ((2, "beta"), (3, "gamma"), (1, "alpha")):
        _write(d / f"{v:03d}_{name}.py", MIG_TEMPLATE.format(v=v, name=name))
    report = run_migrations(engine, directory=d)
    assert [a["version"] for a in report["applied"]] == [1, 2, 3], report
    for v in (1, 2, 3):
        assert _table_exists(engine, f"t_{v}")


def test_failed_migration_is_not_recorded_and_retried(tmp_path: Path):
    """失败的迁移**不许记账** —— 记了就等于"下次不再重试"，结构永远停在半截。"""
    engine = _engine(tmp_path)
    d = tmp_path / "migs"
    d.mkdir()
    _write(d / "001_boom.py",
           "VERSION = 1\nNAME = 'boom'\nDESCRIPTION = '炸'\n\n\n"
           "def upgrade(engine):\n    raise RuntimeError('炸了')\n")
    with pytest.raises(MigrationFailed) as e:
        run_migrations(engine, directory=d)
    assert "001_boom" in str(e.value)
    assert current_version(engine) == 0, "失败的迁移被记账了"
    # 修好之后重跑必须能补上（说明它确实"下次还会再试"）
    _write(d / "001_boom.py", MIG_TEMPLATE.format(v=1, name="boom"))
    assert [a["version"] for a in run_migrations(engine, directory=d)["applied"]] == [1]


# ---------------------------------------------------------------- 漂移 / 异常状态


def test_changed_historical_migration_is_reported_not_rerun(tmp_path: Path):
    """改过的历史迁移：**报出来、但不重跑、也不拦启动**（拦启动＝一个笔误把线上打死）。"""
    engine = _engine(tmp_path)
    d = tmp_path / "migs"
    shutil.copytree(MIGRATIONS_DIR, d)
    run_migrations(engine, directory=d)
    with io.open(d / "001_baseline.py", "a", encoding="utf-8") as f:
        f.write("\n# 事后偷偷改了历史迁移\n")
    report = run_migrations(engine, directory=d)
    assert report["drifted"] == [1], report
    assert report["applied"] == [], "改过的历史迁移又被跑了一遍"
    st = migration_status(engine, directory=d)
    assert st["drifted"][0]["version"] == 1
    assert st["drifted"][0]["db_checksum"] != st["drifted"][0]["file_checksum"]


def test_status_reports_pending_and_unknown(tmp_path: Path):
    engine = _engine(tmp_path)
    d = tmp_path / "migs"
    d.mkdir()
    _write(d / "001_a.py", MIG_TEMPLATE.format(v=1, name="a"))
    _write(d / "002_b.py", MIG_TEMPLATE.format(v=2, name="b"))
    run_migrations(engine, directory=d)
    # 造一个"库里有、仓库里没有"的版本号（有人在别的分支跑过迁移）
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO {VERSION_TABLE} "
                         "(version, name, checksum, description, applied_at, duration_ms, app_version) "
                         "VALUES (99, 'ghost', 'x', '', '2026-01-01 00:00:00', 0, '')"))
    st = migration_status(engine, directory=d)
    assert st["unknown_in_db"] == [99], st
    assert st["current"] == 99
    assert [m["version"] for m in st["pending"]] == []


def test_baseline_is_a_noop(tmp_path: Path):
    """基线**不许**碰库：它的意义是"留一个版本锚点"，不是"把 bootstrap 重跑一遍"。"""
    from app.migrations import _runner as r

    mod = __import__("app.migrations.001_baseline", fromlist=["upgrade"])
    engine = _engine(tmp_path)
    assert mod.upgrade(engine) is None
    assert r.discover(MIGRATIONS_DIR)[0].version == 1


def test_cli_runs_for_real(tmp_path: Path):
    """CLI 必须**真的能跑起来** —— 这一条是被实测逼出来的。

    第一版 `__main__.py` 写的是 `from app.config import settings`，而 `app.config` 里**没有**
    模块级 `settings`（只有 `get_settings()`）。单元测试全绿（它们只 import `_runner`），
    但 `python -m app.migrations status` **当场起不来** —— 而这条命令正是"出事时唯一能用的那条"。
    所以：连命令行的入口也要有一条真跑的用例。
    """
    db = tmp_path / "cli.db"
    url = f"sqlite:///{db}"
    backend = Path(__file__).resolve().parents[1]

    # ⚠️ 必须显式给 encoding：子进程的 CLI 把 stdout 重配成了 UTF-8，而 text=True 会按
    #    **本机首选编码**（zh-CN = GBK）去解 → UnicodeDecodeError，然后 stdout 变成 None。
    #    本仓库在 _check_backend_fresh.py 里踩过同一个坑（那里还留着一整段注释）。
    up = subprocess.run([sys.executable, "-m", "app.migrations", "upgrade", "--url", url],
                        cwd=backend, capture_output=True, encoding="utf-8", errors="replace",
                        timeout=120)
    assert up.returncode == 0, up.stderr
    assert "001_baseline" in up.stdout + up.stderr

    st = subprocess.run([sys.executable, "-m", "app.migrations", "status", "--url", url],
                        cwd=backend, capture_output=True, encoding="utf-8", errors="replace",
                        timeout=120)
    assert st.returncode == 0, st.stderr
    assert "当前版本：1" in st.stdout, st.stdout
    assert db.exists()


def test_cli_refuses_when_migration_drifted(tmp_path: Path):
    """漂移时 CLI 的退出码要**非零**（CI/发布脚本靠它拦人），但服务端仍不拦启动。"""
    import json

    db = tmp_path / "drift.db"
    url = f"sqlite:///{db}"
    backend = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, "-m", "app.migrations", "upgrade", "--url", url],
                   cwd=backend, capture_output=True, encoding="utf-8", errors="replace",
                   timeout=120, check=True)
    # 直接改库里的 checksum，模拟"文件被改过"（比对的是文件与库里记录的值）
    engine = create_engine(url, future=True)
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE {VERSION_TABLE} SET checksum = 'deadbeef' WHERE version = 1"))
    st = subprocess.run([sys.executable, "-m", "app.migrations", "status", "--url", url, "--json"],
                        cwd=backend, capture_output=True, encoding="utf-8", errors="replace",
                        timeout=120)
    assert st.returncode == 1, (st.returncode, st.stdout, st.stderr)
    data = json.loads(st.stdout)
    assert data["drifted"] and data["drifted"][0]["version"] == 1, data




