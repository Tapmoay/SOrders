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
os.environ["SMS_REVEAL_CODE"] = "true"

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
