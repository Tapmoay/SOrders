"""
Pytest fixtures: parallel-test-ready with worker isolation.

Key optimizations:
1. File-based SQLite **per process** (not :memory:) for parallel execution
2. Session-scoped fixtures where possible to reduce setup overhead
3. Automatic worker ID **+ PID** detection for isolation
4. Proper cleanup on shutdown (**only this process's own file**)

⚠️ 第 3 与第 4 条是 R4-47 修的（原来只有 worker id、且退出时删整个目录）——
详见 get_db_path() 与 cleanup_test_dbs() 的说明，以及判据
`_tools/qa/_probe_test_db_isolation.py`。
"""

from __future__ import annotations

import os
import sys
from collections import namedtuple
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from starlette.testclient import TestClient

# ============================================================
# Worker Isolation Setup
# ============================================================


def get_worker_id() -> str:
    """Get pytest-xdist worker ID or 'master' if running without xdist."""
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


#: `iter_api_routes` 的产出：只暴露两个测试真正要的四个字段（见下面那段说明）。
ApiRoute = namedtuple("ApiRoute", "path methods dependant endpoint")


def _join_path(a: str, b: str) -> str:
    if not a:
        return b or "/"
    if not b:
        return a
    return a.rstrip("/") + "/" + b.lstrip("/")


def iter_api_routes(node):
    """把应用里的**叶子路由**递归拍平 —— 跨 starlette 版本，两种形状都认。

    ⚠️ 为什么不能直接遍历 `fastapi_app.routes`（2026-09-25 CI 实测，代价是 3 个用例红）：
    · 本机 starlette 0.52.1：`include_router` 的路由被**摊平**进 `.routes`，
      直接遍历就拿得到 `APIRoute`（有 `.path` / `.dependant`）；
    · CI 上是 starlette **1.7.0**（`requirements.txt` 写的是 `fastapi>=0.110,<1`，
      CI 装到的是新版）：`.routes` 里放的是 `_IncludedRouter` —— 它既**没有** `.path`
      也**没有** `.dependant`，子路由藏在 `.original_router.routes` 里，而且**还能再套一层**。
    直接遍历的两种后果都很隐蔽：要么 `AttributeError`（`test_metrics` 那条就是这么红的），
    要么 `getattr(r, "dependant", None) is None` 一路 `continue` → **扫到 0 个候选端点**
    （`test_date_order_guard` 那两条）—— 也就是"判据静默失效"，本项目最怕的那一类。

    还有第二个坎：新形状里子路由的 `.path` **不含** include 时的前缀
    （旧形状是在 include 那一刻就把前缀套在 path 上了）。所以这里一边下钻一边**累加**
    `_IncludedRouter.include_context.prefix`（顶层那个就是 `/api/v1`）——
    不补的话扫出来的 path 会全部 404（实测：20 个候选端点全变成 404，
    于是"反序窗口被 400 拒绝"那条判据变成一句空话）。

    ⛔ 产出的是 `ApiRoute` 这个**投影**（只含两个测试真正要的四个字段），
    不是框架自己的路由对象：starlette 内部结构下次再变，改这一处就够了，
    调用方永远不用认识 `_IncludedRouter`。
    """
    stack: list[tuple[object, str]] = [(node, "")]
    seen: set[int] = set()
    while stack:
        cur, prefix = stack.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        sub = getattr(cur, "routes", None)
        nxt = prefix
        if sub is None:
            inner = getattr(cur, "original_router", None)
            if inner is not None:
                sub = getattr(inner, "routes", None)
                ctx = getattr(cur, "include_context", None)
                nxt = _join_path(prefix, getattr(ctx, "prefix", None) or "")
        if sub:
            stack.extend((s, nxt) for s in sub)
            continue
        path = getattr(cur, "path", None)
        if path is None:
            continue
        yield ApiRoute(_join_path(prefix, path), getattr(cur, "methods", None) or set(),
                       getattr(cur, "dependant", None), getattr(cur, "endpoint", None))


def _say(msg: str) -> None:
    """往控制台打一行，⛔ 保证**不会因为编码差异把收尾搞崩**。

    ⚠️ R4-47 实测（抓到的原样）：

        print("⚠️ 本进程的测试库没能删掉…")
        UnicodeEncodeError: 'gbk' codec can't encode character '\u26a0'

    于是"如实报一句警告"**本身变成了一条 teardown error**（而它想说的只是
    "有个文件没删掉、不影响结果"）。⛔ 一个诊断输出不该有能力把整轮跑挂掉 ——
    所以这里兜一层：编不出来就用替换字符，而不是抛。
    """
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(msg.encode(enc, "replace").decode(enc, "replace"))


def get_db_path() -> str:
    """Get unique database path for **this process**.

    ⚠️ **为什么必须带上 PID**（R4-47 修的缺陷）：

    `PYTEST_XDIST_WORKER` 在**没有 xdist** 时**恒为 "master"** ——
    于是两个并发的 pytest 会话（例如本机全量 ∥ 检查套件里的一条子集命令）
    会算出**同一个文件**，双双 `create_all()` 并互相踩。

    实测（同一份代码、同一条命令、只是并发跑）：

        A → 1099 passed (142s)
        B → **1099 errors** (317s)

    ⛔ 这类红最难查：它看起来像回归，其实是被测代码一个字都没改。
    ⛔ 判据不是"两个路径字符串不一样"，而是"两个进程**真的各自连上了自己的库**"——
    见 `_tools/qa/_probe_test_db_isolation.py`（它会读回自己写的那一行来证明）。
    """
    worker_id = get_worker_id()
    temp_dir = Path(__file__).parent / ".test_dbs"
    temp_dir.mkdir(exist_ok=True)
    return str(temp_dir / f"sorders_test_{worker_id}_{os.getpid()}.db")


# Set database URL BEFORE importing app modules
TEST_DB_URL = f"sqlite:///{get_db_path()}"
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-32chars-minimum!!"

# Import app modules AFTER setting environment
from app.config import get_settings

get_settings.cache_clear()

import app.models  # noqa: E402, F401 - register models
from app.core.security import hash_password
from app.migrations import run_migrations  # noqa: E402
from app.database import get_db
from app.main import app, fastapi_app
from app.models import User
from app.models.base import Base

# ============================================================
# Database Setup
# ============================================================

_test_engine = None
_test_session_factory = None


def get_test_engine():
    """Get or create the test engine (cached per worker)."""
    global _test_engine
    if _test_engine is None:
        _test_engine = create_engine(
            TEST_DB_URL,
            connect_args={"check_same_thread": False},
            echo=False,
        )

        @event.listens_for(_test_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(bind=_test_engine)
        # R3-01：`import app.database` 不再建表/迁移了，测试必须**自己显式**把结构准备好
        # （create_all 建结构 → run_migrations 写版本表，两者合起来等价于以前的 import 副作用）。
        # ⛔ 少了这一句，启动期的结构核对会拒绝启动 —— 那正是它该有的行为。
        run_migrations(_test_engine)

    return _test_engine


def get_test_session_factory():
    """Get or create the test session factory (cached per worker)."""
    global _test_session_factory
    if _test_session_factory is None:
        _test_session_factory = sessionmaker(
            autocommit=False, autoflush=False, bind=get_test_engine()
        )
    return _test_session_factory


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """Initialize test database once per worker."""
    engine = get_test_engine()

    # Create test users in a new session
    factory = get_test_session_factory()
    session = factory()

    try:
        existing = session.query(User).first()
        if existing is None:
            pw = hash_password("pass12345")
            dispatcher = User(
                username="13800000001",
                phone="13800000001",
                password_hash=pw,
                full_name="Dispatcher",
                role="dispatcher",  # type: ignore
            )
            shipper = User(
                username="13800000002",
                phone="13800000002",
                password_hash=pw,
                full_name="Shipper",
                role="shipper",  # type: ignore
            )
            driver = User(
                username="13800000003",
                phone="13800000003",
                password_hash=pw,
                full_name="Driver",
                role="driver",  # type: ignore
            )
            session.add_all([dispatcher, shipper, driver])
            session.commit()
    finally:
        session.close()

    yield

    # Cleanup
    Base.metadata.drop_all(bind=get_test_engine())
    get_test_engine().dispose()


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Function-scoped session with transaction rollback for isolation."""
    session = get_test_session_factory()()

    try:
        yield session
    finally:
        try:
            session.rollback()
        except Exception:
            pass
        try:
            session.close()
        except Exception:
            pass


@pytest.fixture(scope="function")
def users(db_session: Session) -> dict[str, User]:
    """Get test users from current session."""
    dispatcher = db_session.query(User).filter_by(phone="13800000001").first()
    shipper = db_session.query(User).filter_by(phone="13800000002").first()
    driver = db_session.query(User).filter_by(phone="13800000003").first()

    return {
        "dispatcher": dispatcher,
        "shipper": shipper,
        "driver": driver,
    }


@pytest.fixture(autouse=True)
def _reset_shared_users(db_session: Session) -> None:
    """每个用例开始前，把**三个共用账号**的可变标志摆回建号时的基线。

    ## 为什么（2026-09-25 抓到，代价很实在）
    这三行是**每个 xdist worker 共用**的（同一个 SQLite 库、整个 worker 共享），而有些用例会改它们
    且**不还原**：批发商那几条把 `is_member` 设成 True（`test_shipper_ledger_summary` /
    `test_shipper_settlement` / `test_shipper_settle_ceiling`），计费那几条改 `billing_mode` /
    `driver_rule_id`。xdist 是**动态分发**的，谁先跑不确定 —— 于是受害者偶发红：
    实测 `test_export_cells_other_kinds.py::test_customers_export_matches_ledger_accounts`
    把这位货主导成了「批发商」那一桶（全新检出并行跑 5 次里红 2 次；断言原话是
    「导出的货主/临时货主账一行都没有：[['批发商', 'Shipper', 15, 640]]」）。

    ⛔ 修法不是「再去把某一个用例改成自己摆前提」（那是打地鼠）：**基线摆在这里**，
    谁要别的状态就**在自己用例里**设 —— 与「每个文件单独跑都过」同一条纪律。
    """
    from app.models import User

    changed = False
    for phone in ("13800000001", "13800000002", "13800000003"):
        u = db_session.query(User).filter_by(phone=phone).first()
        if u is None:
            continue
        if u.is_member:
            u.is_member = False
            changed = True
        if getattr(u, "driver_rule_id", None) is not None:
            u.driver_rule_id = None
            changed = True
        if getattr(u, "billing_mode", None) is not None:
            u.billing_mode = None
            changed = True
    if changed:
        db_session.commit()


@pytest.fixture(scope="function")
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Function-scoped test client with DB override."""

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    fastapi_app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    fastapi_app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def token_dispatcher(users: dict[str, User]) -> str:
    from app.services.auth_service import issue_token

    return issue_token(users["dispatcher"])


@pytest.fixture(scope="function")
def token_shipper(users: dict[str, User]) -> str:
    from app.services.auth_service import issue_token

    return issue_token(users["shipper"])


@pytest.fixture(scope="function")
def token_driver(users: dict[str, User]) -> str:
    from app.services.auth_service import issue_token

    return issue_token(users["driver"])


# ============================================================
# Helper Functions
# ============================================================


def auth_headers(token: str) -> dict[str, str]:
    """Helper to create auth headers."""
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# 跨进程资源隔离（R4-47）
# ============================================================


@pytest.fixture(scope="session", autouse=True)
def isolate_scheduler_lock(tmp_path_factory):
    """把**调度器跨进程锁**挪到本进程自己的临时目录下。

    ⚠️ 为什么必须有（R4-47）：`scheduler_lock.SCHEDULER_LOCK_FILE` 默认是
    **全机共用的一个固定文件**（在 tempdir 下）。于是——

    · 并发跑两个 pytest 会话：一边拿着锁，另一边 `run_daily_retention` 会返回
      `{"skipped": 1}`（拿不到锁）而不是 `{"skipped_same_day": 1}`（今天跑过了）；
    · 本机**正开着一个后端**时同理（lifespan 里那个每日治理循环也要拿这把锁）。

    确定性复现（R4-47，同一份代码同一条测试，只差"有没有别的进程占着锁"）：

        没别人占锁   → 1 passed
        有人占着锁   → 1 failed   ← 这就是假红
        占锁的人走了 → 1 passed

    ⛔ 这里动的是**测试进程里的常量**，生产一个字没改；
    ⛔ 也不削弱被测语义：锁仍然是真的 `FileLock`（Windows 上走 `msvcrt.locking`，
      同进程两次获取照样拿不到 —— 那正是 `_single_runner` 那几条测试要的证据），
      只是不再与**别的进程**抢同一份文件。
    """
    import app.core.scheduler_lock as sl

    monkeypatch = pytest.MonkeyPatch()
    lock = tmp_path_factory.mktemp("locks") / "scheduler_retention.lock"
    # ⚠️ 必须打在 `scheduler_lock` 模块上：`data_retention.GOVERNANCE_LOCK_PATH`
    #    是 import 时的一个**副本**，而且只被用在日志文案里 —— 改它等于假修复。
    monkeypatch.setattr(sl, "SCHEDULER_LOCK_FILE", str(lock), raising=False)
    yield
    monkeypatch.undo()


# ============================================================
# Cleanup (after all tests)
# ============================================================


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_dbs():
    """收工：只删**本进程自己**那一份测试库。

    ⚠️ 原来这里是 `shutil.rmtree(temp_dir)` —— **删整个目录**。两处后果：

    · xdist 下每个 worker 退出时会把**别人的库**一起删掉（谁先退谁先删）；
    · 而 `worker_id == "master"`（无 xdist）时**一份都不删**，于是那份文件一直留着 ——
      这正是两个并发会话能踩到同一份库的另一半原因。

    本仓库更早就吃过一次这个形状：并发两个 pytest 会话得到 `13 failed / 644 errors`
    （记录在 `docs/AI_WORK_CLAIM.md`），当时只立了"不要并发跑"的纪律，没有修。
    ⇒ 现在改成**只删自己这一份**；目录**空了**才顺手删目录。
    """
    yield

    # ⚠️ Windows 上 SQLite **占着文件句柄**：不先 dispose，unlink 必然 PermissionError。
    #    第一版把它 `except OSError: pass` 吞掉了 ⇒ 实测收工后本次四个会话的库**一份都没删掉**、
    #    `.test_dbs` 一直涨。⛔ "静默吞错"正是这个缺陷能藏住的原因，所以现在**删不掉要说出来**。
    # ⚠️ 指向同一个库文件的 engine **有两个**：conftest 自己的 _test_engine，
    #    以及 app.database.engine（conftest 在 import 应用之前就把 DATABASE_URL 指过去了）。
    #    只 dispose 前者 ⇒ unlink 仍然 PermissionError —— R4-47 实测就是这么栽的第二次。
    if _test_engine is not None:
        try:
            _test_engine.dispose()
        except Exception as exc:  # noqa: BLE001
            _say("[conftest] 释放测试库连接失败（" + type(exc).__name__ + "）：" + str(exc)[:120])
    try:
        from app import database as _app_db
        _app_db.engine.dispose()
    except Exception as exc:  # noqa: BLE001
        _say("[conftest] 释放 app.database.engine 失败（" + type(exc).__name__ + "）："
             + str(exc)[:120])

    # ⚠️ 光 dispose 还不够：全量跑时仍会 PermissionError —— 说明还有**用例漏关了 session**
    #    （连接被 checked out，dispose 不会回收它），而 Windows 释放文件句柄又常常**滞后**于 close。
    #    ⇒ gc 一次 + 重试几轮。⛔ 仍然失败就如实说，不吞（这条实测过：吞掉的后果是
    #      ".test_dbs 一直涨、而没有任何人知道"）。
    import gc
    import time as _time

    p = Path(get_db_path())
    gc.collect()
    last: OSError | None = None
    for _attempt in range(4):
        try:
            p.unlink(missing_ok=True)
            last = None
            break
        except OSError as exc:
            last = exc
            _time.sleep(0.25)
    if last is not None:
        _say("[conftest] 本进程的测试库没能删掉（" + type(last).__name__ + "）：" + str(p)
             + " —— 不影响本次结果；文件名带 PID 不会与别人撞，但 .test_dbs 会继续累积")
        return
    try:
        p.parent.rmdir()          # ⛔ 只在**空**的时候才成功：并发会话时别人的库还在，不许动
    except OSError:
        pass
