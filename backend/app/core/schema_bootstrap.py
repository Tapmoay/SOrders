"""启动时建表并补齐旧库缺失列（如 users.username、products.image_url）。"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app.models.base import Base

logger = logging.getLogger(__name__)


def _sqlite_shipper_id_is_notnull(pragma_rows: list) -> bool:
    for row in pragma_rows:
        if len(row) >= 4 and row[1] == "shipper_id" and row[3] == 1:
            return True
    return False


def _sqlite_rebuild_table_for_nullable_shipper_id(engine: Engine, model_cls: type) -> None:
    """SQLite 无法 ALTER 列可空：改名旧表 → 按模型建新表 → INSERT 复制数据。

    用于旧库 orders/ledgers.shipper_id 仍为 NOT NULL 时，否则派单员无货主/临时货主下单 INSERT 失败（500）。
    """
    from sqlalchemy import inspect as sa_inspect

    table = model_cls.__table__
    tbl = table.name
    insp = sa_inspect(engine)
    if tbl not in insp.get_table_names():
        return
    with engine.connect() as conn:
        pragma_rows = conn.execute(text(f"PRAGMA table_info({tbl})")).fetchall()
    if not _sqlite_shipper_id_is_notnull(pragma_rows):
        return

    logger.warning("SQLite：正在重建表 %s，使 shipper_id 可空并保留数据…", tbl)
    new_col_names = [c.name for c in table.columns]
    old_col_names = [r[1] for r in pragma_rows if len(r) >= 2]
    old_set = set(old_col_names)
    select_parts: list[str] = []
    for c in new_col_names:
        if c in old_set:
            select_parts.append(f'"{c}"')
        else:
            select_parts.append("NULL")
    legacy = f"{tbl}_legacy_migrate"
    cols_sql = ",".join(f'"{c}"' for c in new_col_names)
    sel_sql = ",".join(select_parts)

    try:
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text(f"DROP TABLE IF EXISTS {legacy}"))
            conn.execute(text(f'ALTER TABLE "{tbl}" RENAME TO "{legacy}"'))
        table.create(bind=engine, checkfirst=True)
        with engine.begin() as conn:
            conn.execute(text(f'INSERT INTO "{tbl}" ({cols_sql}) SELECT {sel_sql} FROM "{legacy}"'))
            conn.execute(text(f'DROP TABLE "{legacy}"'))
    finally:
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))


def _import_all_models() -> None:
    import app.models  # noqa: F401 — 注册所有 Table


def bootstrap_schema(engine: Engine) -> None:
    _import_all_models()
    Base.metadata.create_all(bind=engine, checkfirst=True)

    insp = inspect(engine)

    if "users" in insp.get_table_names():
        col_names = {c["name"] for c in insp.get_columns("users")}
        if "username" not in col_names:
            logger.warning("检测到旧库缺少 users.username，正在补列并从 phone 回填…")
            dialect = engine.dialect.name

            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(32)"))
                except OperationalError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
                conn.execute(text("UPDATE users SET username = phone"))

            with engine.begin() as conn:
                try:
                    if dialect == "sqlite":
                        conn.execute(
                            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)")
                        )
                    else:
                        conn.execute(text("CREATE UNIQUE INDEX ix_users_username ON users (username)"))
                except OperationalError:
                    logger.debug("ix_users_username 可能已存在，跳过")

    if "products" in insp.get_table_names():
        pcols = {c["name"] for c in insp.get_columns("products")}
        if "image_url" not in pcols:
            logger.warning("检测到旧库缺少 products.image_url，正在补列…")
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE products ADD COLUMN image_url VARCHAR(512)"))
                except OperationalError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
            pcols = {c["name"] for c in insp.get_columns("products")}
        if "name_color" not in pcols:
            logger.warning("检测到旧库缺少 products.name_color，正在补列…")
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE products ADD COLUMN name_color VARCHAR(32)"))
                except OperationalError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise

    if "ledgers" in insp.get_table_names():
        lcols = {c["name"] for c in insp.get_columns("ledgers")}
        if "order_product_id" not in lcols:
            logger.warning("检测到旧库缺少 ledgers.order_product_id，正在补列（订单送达自动记账幂等键）…")
            dialect = engine.dialect.name
            with engine.begin() as conn:
                try:
                    if dialect == "sqlite":
                        conn.execute(text("ALTER TABLE ledgers ADD COLUMN order_product_id INTEGER"))
                    else:
                        conn.execute(text("ALTER TABLE ledgers ADD COLUMN order_product_id INT NULL"))
                except OperationalError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise

    if "orders" in insp.get_table_names():
        dialect = engine.dialect.name
        # 派单员可不选货主：旧库 orders.shipper_id 常为 NOT NULL，反射在部分 MySQL 版本上 nullable 不准，故每次启动尝试一次 ALTER（已为可空时通常仍成功）
        if dialect == "mysql":
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE orders MODIFY COLUMN shipper_id INT NULL"))
                except OperationalError as e:
                    logger.warning("orders.shipper_id 可空迁移跳过: %s", e)

        ocols = {c["name"] for c in insp.get_columns("orders")}
        if "temp_shipper_name" not in ocols:
            logger.warning("检测到旧库缺少 orders.temp_shipper_name，正在补列…")
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN temp_shipper_name VARCHAR(128)"))
                except OperationalError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise

        if dialect == "sqlite":
            from app.models.order import Order

            _sqlite_rebuild_table_for_nullable_shipper_id(engine, Order)

    if "ledgers" in insp.get_table_names():
        lcols = {c["name"] for c in insp.get_columns("ledgers")}
        if "temp_shipper_name" not in lcols:
            logger.warning("检测到旧库缺少 ledgers.temp_shipper_name，正在补列…")
            dialect = engine.dialect.name
            with engine.begin() as conn:
                try:
                    if dialect == "sqlite":
                        conn.execute(text("ALTER TABLE ledgers ADD COLUMN temp_shipper_name VARCHAR(128)"))
                    else:
                        conn.execute(text("ALTER TABLE ledgers ADD COLUMN temp_shipper_name VARCHAR(128) NULL"))
                except OperationalError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
        dialect = engine.dialect.name
        if dialect == "mysql":
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE ledgers MODIFY COLUMN shipper_id INT NULL"))
                except OperationalError as e:
                    logger.warning("ledgers.shipper_id 可空迁移跳过: %s", e)
        elif dialect == "sqlite":
            from app.models.ledger import Ledger

            _sqlite_rebuild_table_for_nullable_shipper_id(engine, Ledger)
