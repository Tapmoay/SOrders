"""
Pytest fixtures: parallel-test-ready with worker isolation.

Key optimizations:
1. File-based SQLite per worker (not :memory:) for parallel execution
2. Session-scoped fixtures where possible to reduce setup overhead
3. Automatic worker ID detection for isolation
4. Proper cleanup on shutdown
"""

from __future__ import annotations

import os
import shutil
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


def get_db_path() -> str:
    """Get unique database path for this worker."""
    worker_id = get_worker_id()
    temp_dir = Path(__file__).parent / ".test_dbs"
    temp_dir.mkdir(exist_ok=True)
    return str(temp_dir / f"sorders_test_{worker_id}.db")


# Set database URL BEFORE importing app modules
TEST_DB_URL = f"sqlite:///{get_db_path()}"
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-32chars-minimum!!"

# Import app modules AFTER setting environment
from app.config import get_settings

get_settings.cache_clear()

import app.models  # noqa: E402, F401 - register models
from app.core.security import hash_password
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
# Cleanup (after all tests)
# ============================================================


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_dbs():
    """Clean up test database files after all tests complete."""
    yield

    worker_id = get_worker_id()
    if worker_id != "master":
        temp_dir = Path(__file__).parent / ".test_dbs"
        if temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
