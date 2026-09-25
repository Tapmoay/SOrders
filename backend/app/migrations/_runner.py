"""迁移运行器：`schema_versions` 版本表 + 按版本执行 `migrations/` 下的变更。

### 为什么要有它（整改报告 §4）
报告把这件事列为「整个架构改造的第一核心任务」，原话是：

```text
现在：app.database → schema_bootstrap → 启动 → ALTER TABLE
风险：应用启动 = 数据库迁移 = 服务可用性
```

而 `schema_bootstrap.py` 已经 1600+ 行、且**同时兼任两个角色**（正式变更机制 + 运行时自愈）。
它最要命的一条不是"文件太大"，而是：**没人知道数据库现在是什么状态** ——
「这句 DDL 到底跑过没有」只能靠"这句是幂等的，所以跑不跑都行"来兜。

### 分工（本轮只加这一圈外框，既有 DDL 的行为一个字都不改）

| 角色 | 谁负责 | 什么时候跑 |
|---|---|---|
| **正式变更**（一次性的结构/数据搬迁） | 本目录下的 `NNN_*.py` | 每个版本**只跑一次**，跑过就记进 `schema_versions` |
| **运行时自愈**（缺表补表、缺列补列、枚举补值、列宽放宽） | `core/schema_bootstrap.py` | 每次启动都跑（必须幂等） |

⛔ 本轮**没有**把 bootstrap 里那 1600 行搬进 migrations —— 报告 §18 规则 1「一次只动一个维度」：
搬它＝同时在动"迁移机制"和"全部既有 DDL"，一旦出错分不清是哪一层。
既有那些 DDL 保持原样（它们是幂等的自愈），新变更从今天起走 `migrations/`。

### 三条刻意的设计选择（都有代价，写在这里免得后人踩）

1. **发现到"改了历史迁移"时只报错、不拦启动**：
   已经跑过的迁移文件内容变了（checksum 不一致）是**真问题**，但"让 API 起不来"是更大的问题 ——
   一个校验和笔误就能把线上打死。所以：`logger.error` + 状态里标红 + `_tools/qa/_check_migrations.py` 在 CI 里红。
2. **默认不带 `--force` 就不重跑任何东西**：版本表里有的版本一律跳过（哪怕它的 checksum 变了）。
3. **锁是独立的**（`/tmp/sorders_migrations.lock`，不是 bootstrap 那把）：
   `flock` 是"文件描述符级"的，同一个进程里对**同一个文件**再 `LOCK_EX` 会**自己把自己锁死**。
   调用顺序恒为 bootstrap → migrations（拿到两把锁的顺序必须一致，反着写就会和 `--workers 2` 死锁）。
4. **多实例的前置条件（2026-09-25 补）**：文件锁只在**同一台机器**上有效，所以迁移另外拿一把
   **服务端命名锁**（MySQL `GET_LOCK("sorders_migrations")`，超时 60s）。
   没有它，A/B 两台机器各拿自己的 `/tmp` 锁都会成功 → 同一条迁移被同时跑两遍。
   顺序恒为 **本机 flock → 服务端 GET_LOCK**（反了会死锁）。
   ⚠️ SQLite 下**如实不做**跨主机锁（它本来就不可能多主机共享），只记一行日志说明。
"""

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.business_time import utc_now_naive
from app.core.file_lock import FileLock, FileLockTimeout

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent
VERSION_TABLE = "schema_versions"

#: 迁移文件名格式：`001_baseline.py` —— **必须**带三位以上版本号，否则 discover 会当场报错。
#: 为什么要这么严：一个没有版本号的文件在旧实现里就是"静静地谁也不跑它"，而它看起来又像一条迁移。
FILE_RE = re.compile(r"^(\d{3,})_([a-z0-9_]+\.py)$")
#: 只在**同一个进程**里互斥（flock 是 fd 级的），跨进程互斥靠下面这个文件。
#: 本机迁移锁的锁文件。⛔ 用 `gettempdir()` 而不是写死 `/tmp`：
#: Windows 上没有 `/tmp` 这个目录（会解析成当前盘的 `\tmp`，通常不存在），
#: 而 R3-01 之前 Windows 分支根本不走锁，所以这个路径问题一直没暴露。
LOCK_FILE = str(Path(tempfile.gettempdir()) / "sorders_migrations.lock")

#: 迁移的**服务端命名锁**（MySQL `GET_LOCK`）—— **跨主机**互斥靠它。
#: ⚠️ `/tmp` 那把 flock 只在**同一台机器**上有效：多实例部署时 A、B 两台各自拿自己的 `/tmp` 锁
#:    都能成功，于是同一条迁移被**同时执行两遍**（DDL 半途撞车、版本表互相覆盖）。
#:    这正是报告 §16 说的「单实例 + 没有迁移协调」—— 它才是多实例真正的前置条件。
DB_LOCK_NAME = "sorders_migrations"
DB_LOCK_TIMEOUT_S = 60

_CREATE_SQL: dict[str, str] = {
    # 版本表**故意不写成 SQLAlchemy 模型**：它必须能在"模型还没建/建不出来"的库上先存在，
    # 而且 `create_all` 不该有机会去 drop/recreate 它（那会把"跑过哪些迁移"一起抹掉）。
    "mysql": (
        f"CREATE TABLE IF NOT EXISTS {VERSION_TABLE} ("
        "  version INT NOT NULL COMMENT '迁移版本号（= 文件名前缀）',"
        "  name VARCHAR(120) NOT NULL COMMENT '迁移名（= 文件名去掉前缀）',"
        "  checksum CHAR(64) NOT NULL COMMENT '迁移文件内容的 sha256（CRLF 归一后）',"
        "  description VARCHAR(255) NOT NULL DEFAULT '',"
        "  applied_at DATETIME NOT NULL COMMENT 'UTC',"
        "  duration_ms INT NOT NULL DEFAULT 0,"
        "  app_version VARCHAR(32) NOT NULL DEFAULT '',"
        "  PRIMARY KEY (version)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    ),
    "sqlite": (
        f"CREATE TABLE IF NOT EXISTS {VERSION_TABLE} ("
        "  version INTEGER NOT NULL PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  checksum TEXT NOT NULL,"
        "  description TEXT NOT NULL DEFAULT '',"
        "  applied_at TEXT NOT NULL,"
        "  duration_ms INTEGER NOT NULL DEFAULT 0,"
        "  app_version TEXT NOT NULL DEFAULT ''"
        ")"
    ),
}


class MigrationError(RuntimeError):
    """迁移体系的错误基类（发现/执行/校验各有一种）。"""


class MigrationFailed(MigrationError):
    """某条迁移执行到一半失败。**不写版本表**，所以下次启动会重试它。

    ⚠️ MySQL 的 DDL 是隐式提交的：失败时库里可能已经改了一半。
    所以迁移里**必须**写成"能重跑的"（先判存在再建/加），见本目录 README。
    """


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    checksum: str
    description: str = ""
    module: ModuleType | None = field(default=None, compare=False)


def _checksum(path: Path) -> str:
    """文件内容的 sha256（**先把 CRLF 归一到 LF 再算**）。

    为什么必须归一：本机是 Windows（工作区里 .py 是 CRLF），生产是 Linux（LF）。
    不归一的话同一份迁移在两处算出的校验和不同 —— 表现是"到了生产就说你改了历史迁移"，
    而这种假红会让人学会**无视**这条检查（本项目 §15 的教训：永远红的检查 = 没有检查）。
    """
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"app_migrations_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise MigrationError(f"迁移文件加载不了：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover(directory: Path | None = None, *, load: bool = False) -> list[Migration]:
    """按版本号升序列出 `migrations/` 下的迁移（**不执行**）。

    `load=True` 时把模块也读进来（会执行文件顶层代码，所以只在真要跑/要看描述时用）。
    """
    d = Path(directory) if directory else MIGRATIONS_DIR
    out: list[Migration] = []
    seen: dict[int, Path] = {}
    for path in sorted(d.glob("*.py")):
        if path.name.startswith("_"):            # `_runner.py` / `__init__.py` 不是迁移
            continue
        m = FILE_RE.match(path.name)
        if not m:
            raise MigrationError(
                f"{path.name} 不符合迁移命名 `NNN_名字.py`（三位以上版本号）。\n"
                "  ⛔ 不报错的话它就是一个「看起来像迁移、实际谁也不跑」的文件 —— 那种东西最危险。"
            )
        version = int(m.group(1))
        if version in seen:
            raise MigrationError(f"版本号 {version} 被两个文件用了：{seen[version].name} 与 {path.name}")
        seen[version] = path
        module = _load_module(path) if load else None
        out.append(Migration(
            version=version, name=path.stem.split("_", 1)[1], path=path, checksum=_checksum(path),
            description=str(getattr(module, "DESCRIPTION", "")) if module else "", module=module,
        ))
    out.sort(key=lambda x: x.version)
    return out


def _dialect(engine: Engine) -> str:
    return engine.dialect.name


def ensure_version_table(engine: Engine) -> None:
    """建版本表（幂等）。**不认识的方言直接报错**，不静默跳过 ——
    静默跳过的后果是"换了个库之后所有迁移每次都重跑"。"""
    name = _dialect(engine)
    sql = _CREATE_SQL.get(name)
    if sql is None:
        raise MigrationError(
            f"迁移版本表还没有 {name} 方言的建表语句（现有：{', '.join(sorted(_CREATE_SQL))}）。\n"
            "  新方言请显式补一句，别让它静默跳过。"
        )
    with engine.begin() as conn:
        conn.execute(text(sql))


def applied_versions(engine: Engine) -> dict[int, dict]:
    ensure_version_table(engine)
    with engine.begin() as conn:
        rows = conn.execute(text(
            f"SELECT version, name, checksum, description, duration_ms FROM {VERSION_TABLE} ORDER BY version"
        )).mappings().all()
    return {int(r["version"]): dict(r) for r in rows}


def current_version(engine: Engine) -> int:
    applied = applied_versions(engine)
    return max(applied) if applied else 0


def last_migration_duration_ms(engine: Engine) -> int:
    """最近一次迁移的耗时（毫秒）；没有迁移记录时 0。

    ⛔ **只读**（与 `schema_ready` 同一条纪律）：不调 `applied_versions` / `ensure_version_table`，
    所以任何抓取路径（指标、体检）都能安全地调它 —— 那是 R3-01 定下的规矩：
    「看一眼状态」这件事本身不该改库。
    ⛔ 表名的字面量只出现在**本模块**里：它是这张表的拥有者，别的模块想读一律走这里
    （判据 `_check_migrations.py` 盯着「谁又写了一遍 schema_versions」）。
    """
    try:
        if not inspect(engine).has_table(VERSION_TABLE):
            return 0
        with engine.connect() as conn:
            got = conn.execute(text(
                f"SELECT duration_ms FROM {VERSION_TABLE} ORDER BY version DESC LIMIT 1"
            )).scalar()
    except Exception:                       # noqa: BLE001 —— 读不到就是 0，不该拖垮抓取
        return 0
    return int(got or 0)


def schema_ready(engine: Engine, *, directory: Path | None = None) -> tuple[bool, str]:
    """结构准备好了吗？—— **只读**核对，供应用启动时用（R3-01）。

    ⛔ **本函数一个 DDL 都不许有**：所以它不调用 `applied_versions()` / `migration_status()`
    —— 那两个都会 `ensure_version_table()`（建表）。这里用 `has_table` + 裸 SELECT。
    理由与整轮的主题一致：**「看一眼状态」这件事本身不该改库**。

    返回 `(True, 说明)` 或 `(False, 为什么还没准备好)`。三种「没准备好」分得开：
      · 连不上库；
      · 没有 `schema_versions`（从没跑过迁移 —— 老版本代码或全新库）；
      · 库在版本 N，而仓库里有更新的迁移没跑。
    """
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:                       # noqa: BLE001 —— 连不上就是没准备好
        return False, f"连不上数据库：{exc}"

    try:
        if not inspect(engine).has_table(VERSION_TABLE):
            return False, f"没有迁移记录表 `{VERSION_TABLE}` —— 这个库从没跑过迁移"
        with engine.connect() as conn:
            rows = conn.execute(text(f"SELECT version FROM {VERSION_TABLE}")).scalars().all()
    except Exception as exc:                       # noqa: BLE001
        return False, f"读迁移版本失败：{exc}"

    current = max((int(v) for v in rows), default=0)
    latest = max((m.version for m in discover(directory)), default=0)
    if current < latest:
        return False, f"库在版本 {current}，仓库里有到版本 {latest} 的迁移没跑"
    if current > latest:
        return True, f"版本 {current}（比仓库里的 {latest} 还新 —— 代码可能比库旧，已知情）"
    return True, f"版本 {current}"


def migration_status(engine: Engine, *, directory: Path | None = None) -> dict:
    """给人和 CI 看的状态：当前版本 / 待跑 / **跑了但内容变过**（drifted）。"""
    migrations = discover(directory)
    applied = applied_versions(engine)
    pending = [m for m in migrations if m.version not in applied]
    drifted = [m for m in migrations
               if m.version in applied and applied[m.version]["checksum"] != m.checksum]
    unknown = [v for v in applied if v not in {m.version for m in migrations}]
    return {
        "current": max(applied) if applied else 0,
        "applied": [{"version": v, **{k: applied[v][k] for k in ("name", "checksum", "duration_ms")}}
                    for v in sorted(applied)],
        "pending": [{"version": m.version, "name": m.name} for m in pending],
        "drifted": [{"version": m.version, "name": m.name,
                     "db_checksum": applied[m.version]["checksum"], "file_checksum": m.checksum}
                    for m in drifted],
        "unknown_in_db": unknown,
    }


def _app_version() -> str:
    """把"哪一版代码跑的这条迁移"记下来（排障时用它对齐代码与库）。"""
    try:
        # ⚠️ 取 settings 的唯一正确入口是 `get_settings()`（`app.config` 里**没有**模块级 `settings`）。
        #    第一版写成 `from app.config import settings` —— 这个 ImportError 被下面的 except 吞掉，
        #    表现是**版本号永远是空串**（留痕字段静默失效）；而 CLI（`__main__.py`）里同样的写法
        #    是**直接起不来**。两处都改掉了，并补了一条"真跑 CLI"的单测钉着。
        from app.config import get_settings

        return str(getattr(get_settings(), "app_version", "") or "")[:32]
    except Exception:                                    # noqa: BLE001 —— 版本号只是留痕，读不到不该拦迁移
        return ""


class _db_lock:
    """**跨主机**互斥（MySQL `GET_LOCK`）；SQLite 如实不做 —— 它本来就不可能多主机共享。

    ⛔ 为什么不用 `BEGIN IMMEDIATE` 之类糊一个"看起来有锁"的东西：
    **算不出真值就别说自己锁住了**。SQLite 是单机文件库，"跨主机共享它"这件事本身不成立，
    假装有锁只会让人以为可以多实例 —— 而那正是这一条要防的误判。

    ⚠️ `GET_LOCK` 是**连接级**的：锁挂在拿它的那条连接上，所以必须**抱着这条连接**活到迁移跑完
    （不能 execute 完就把连接还回池里 —— 那样锁会跟着连接一起被放掉，等于没锁）。
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._conn = None

    def __enter__(self):
        if self.engine.dialect.name != "mysql":
            logger.info(
                "迁移互斥：当前库是 %s（单机文件库），只用本机 flock；"
                "跨主机互斥只在 MySQL 上成立（多实例部署时请确认库是 MySQL）。",
                self.engine.dialect.name,
            )
            return self
        self._conn = self.engine.connect()
        got = self._conn.execute(
            text("SELECT GET_LOCK(:n, :t)"), {"n": DB_LOCK_NAME, "t": DB_LOCK_TIMEOUT_S}
        ).scalar()
        if got != 1:
            self._conn.close()
            self._conn = None
            raise MigrationFailed(
                f"拿不到迁移锁 `{DB_LOCK_NAME}`（等了 {DB_LOCK_TIMEOUT_S}s）—— "
                "另一个实例正在跑迁移。**不要**绕过它：两条迁移同时跑会把 DDL 撞在半路，"
                "而且版本表会互相覆盖（谁后写谁赢，先跑完的那条等于没记账）。"
            )
        logger.warning("拿到迁移锁 %s（超时 %ss）", DB_LOCK_NAME, DB_LOCK_TIMEOUT_S)
        return self

    def __exit__(self, *exc):
        if self._conn is None:
            return False
        try:
            self._conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": DB_LOCK_NAME})
            self._conn.commit()
        finally:
            self._conn.close()
            self._conn = None
        return False


def run_migrations(engine: Engine, *, directory: Path | None = None, dry_run: bool = False) -> dict:
    """把没跑过的迁移按版本号顺序跑掉；返回一份可打印的报告。

    · 跑过的（版本表里有）**一律跳过**；
    · 内容变过的（checksum 不一致）**只报错不拦**（理由见模块开头第 1 条）；
    · 某条失败 → 抛 `MigrationFailed`，**不写版本表**（下次启动重试它）。
    """
    migrations = discover(directory, load=True)
    # 锁的顺序恒为 **本机 flock → 服务端 GET_LOCK**。⛔ 顺序必须一致：
    # 反着写会和 `--workers 2` 死锁（同一进程再拿同一把 flock 会自己锁死，见模块开头第 3 条）。
    with _lock(), _db_lock(engine):
        ensure_version_table(engine)
        # ⚠️ 拿锁**之后**再读一次：uvicorn --workers 2 会两个进程同时进这里，
        #    先读后锁会让两边都以为"还没跑"，然后各跑一遍（DDL 不是原子的）。
        applied = applied_versions(engine)
        report: dict = {"applied": [], "skipped": [], "drifted": [], "failed": None}

        for m in migrations:
            if m.version in applied:
                if applied[m.version]["checksum"] != m.checksum:
                    logger.error(
                        "迁移 %s_%s 的内容与已经记录在库里的不一致（库里 %s / 文件 %s）——"
                        "**已经跑过的迁移不许再改**，要改请新加一条。这条不会被重跑。",
                        f"{m.version:03d}", m.name, applied[m.version]["checksum"][:12], m.checksum[:12],
                    )
                    report["drifted"].append(m.version)
                else:
                    report["skipped"].append(m.version)
                continue

            if dry_run:
                report["applied"].append({"version": m.version, "name": m.name, "dry_run": True})
                continue

            upgrade = getattr(m.module, "upgrade", None)
            if not callable(upgrade):
                raise MigrationError(f"迁移 {m.path.name} 没有定义 upgrade(engine)")

            started = time.monotonic()
            logger.warning("执行迁移 %03d_%s：%s", m.version, m.name, m.description or "(无描述)")
            try:
                upgrade(engine)
            except Exception as e:                            # noqa: BLE001 —— 原样包一层，带上版本号再抛
                logger.error("迁移 %03d_%s 失败：%s", m.version, m.name, e)
                report["failed"] = {"version": m.version, "name": m.name, "error": str(e)[:400]}
                raise MigrationFailed(f"{m.version:03d}_{m.name} 失败：{e}") from e
            duration_ms = int((time.monotonic() - started) * 1000)

            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"INSERT INTO {VERSION_TABLE} "
                        "(version, name, checksum, description, applied_at, duration_ms, app_version) "
                        "VALUES (:v, :n, :c, :d, :a, :ms, :av)"
                    ),
                    {"v": m.version, "n": m.name, "c": m.checksum, "d": m.description[:255],
                     "a": utc_now_naive(), "ms": duration_ms, "av": _app_version()},
                )
            report["applied"].append({"version": m.version, "name": m.name, "duration_ms": duration_ms})
            logger.warning("迁移 %03d_%s 完成（%s ms）", m.version, m.name, duration_ms)

    if not report["applied"] and not report["drifted"]:
        logger.debug("数据库结构已是最新版本 %s", report.get("current", ""))
    return report


class _lock:
    """同一台机器上的迁移互斥（`FileLock`：Linux 用 flock，Windows 用 msvcrt）。

    ⛔ 曾经的写法是「import fcntl 失败就往下跑」—— 在 Windows 上**等于没有锁**，
    R3-01 的并发迁移测试当场抓到：两个进程同时 upgrade，第二个在 `create_all` 上
    撞 `table already exists` 直接失败。现在两条平台都是真锁，且进程崩了由系统释放。
    """

    def __enter__(self):
        self._impl = FileLock(LOCK_FILE)
        try:
            self._impl.__enter__()
        except FileLockTimeout as e:
            # 与 `_db_lock` 的口径一致：拿不到锁是**明确失败**，不许悄悄往下跑。
            raise MigrationError(str(e)) from e
        return self

    def __exit__(self, *exc):
        self._impl.__exit__(*exc)
        return False

