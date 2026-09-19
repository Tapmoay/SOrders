import logging
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
if settings.database_url.startswith("sqlite"):
    # ⚠️ **只有内存库才用 StaticPool**（2026-09-19 审计）。
    #
    # `StaticPool` = 所有 Session 复用**同一条** SQLite 连接。对 `:memory:` 是必需的
    # （每条新连接都是另一个空库），但对**文件库**是个陷阱：
    #   · FastAPI 的同步端点在**线程池**里跑、`background_tasks` 又各自开 `SessionLocal()`
    #     —— 它们拿到的是**同一条连接**；
    #   · 于是 A 请求的事务还没提交时，B（后台任务）的 `commit()`/`rollback()` 会把 A 的改动
    #     **一起提交或一起回滚**。
    # 实测症状（两轮探针各撞到一次，查下来都不是代码缺陷）：
    #   ① 撤销订单返回 200，紧接着再派单也 200（中间那次 CANCELLED 被别的会话回滚了）；
    #   ② 建单后立刻查不到行 → 500「订单保存失败」。
    # 两者单独重跑都正常，而**生产是 MySQL**（正常连接池、每个 Session 独占连接）不会这样。
    # 影响不止"偶尔红"：它会让本机所有并发结论都不可信 —— 所以按库类型区分。
    _is_memory = ":memory:" in settings.database_url
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        **(
            dict(poolclass=StaticPool)
            if _is_memory
            else dict(pool_size=5, max_overflow=5, pool_timeout=30)
        ),
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record) -> None:
        """WAL + busy_timeout：多线程/多进程共享 SQLite 时避免锁等待与数据库被锁。"""
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA wal_autocheckpoint=1000")
        finally:
            cur.close()
else:
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=64,
        max_overflow=32,
        pool_timeout=30,
    )

    @event.listens_for(engine, "connect")
    def _mysql_session_utc(dbapi_conn, _record) -> None:
        """把 MySQL 会话时区钉成 **UTC** —— 这是「库里一律存 UTC」这条口径的另一半。

        ### 为什么（2026-09-19 外部完整检查 C-2）
        本项目的口径写在 `core/business_time.py`：**库里存 UTC，报表按业务当地日分桶**。
        但 MySQL 的 `NOW()` 取的是**会话时区**的当前时间，生产是 `SYSTEM`（+08:00）——
        于是凡是由库端时钟写出来的值（`server_default=func.now()`、任何原生 SQL 里的 `NOW()`）
        都变成 +08:00 墙上时间，和 Python 写的 UTC **差 8 小时**：
        「待派超时 4 小时」实际 12 小时、保留策略与审计窗口整体偏 8 小时。
        本机 SQLite 的 `CURRENT_TIMESTAMP` 本来就是 UTC，所以这个偏差**只有生产才有**，
        单测与探针全绿 —— 它就是这么活下来的。

        现在：Python 侧统一由 `utc_now_naive()` 提供值（见 `TimestampMixin`），
        这里再把**库端**的时钟也钉成 UTC，两条路都指向同一个基准，
        `server_default` 这类兜底路径也不会再引入第二个基准。

        ⚠️ 只对 MySQL 生效（SQLite 分支在上面，没有这句话）。`SET time_zone` 是**会话级**的，
        所以必须每条新连接都执行（`connect` 事件正是干这个的）；连接池复用连接时不会重复执行，
        也不需要重复执行。
        """
        cur = dbapi_conn.cursor()
        try:
            cur.execute("SET time_zone = '+00:00'")
        except Exception:  # noqa: BLE001
            # 权限不足/时区表没装时**不要**让应用起不来：记一条日志，退回原来的行为（与修复前一致）。
            logging.getLogger(__name__).warning(
                "MySQL 会话时区没能设成 UTC（SET time_zone 失败）——"
                "由库端时钟写出的时间会比 Python 写的 UTC 快 8 小时（见 database._mysql_session_utc）",
                exc_info=True,
            )
        finally:
            cur.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)

# 确保无论 ASGI lifespan 是否执行（如仅引用 database 或未走 FastAPI 生命周期），旧库都能补列/迁移
from app.core.schema_bootstrap import bootstrap_schema  # noqa: E402

bootstrap_schema(engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()