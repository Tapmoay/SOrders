"""启动时建表并补齐旧库缺失列（如 users.username、products.image_url）。"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, OperationalError

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
    """跨进程互斥：uvicorn --workers 2 会同时执行 bootstrap，防止并发 DDL 冲突(1684)。
    Windows 无 fcntl 时直接执行（本地单进程开发无碍）。"""
    try:
        import fcntl

        lock_file = open("/tmp/sorders_bootstrap.lock", "w")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            _bootstrap_impl(engine)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()
    except (ImportError, OSError):
        _bootstrap_impl(engine)


def _bootstrap_impl(engine: Engine) -> None:
    _import_all_models()
    Base.metadata.create_all(bind=engine, checkfirst=True)

    insp = inspect(engine)
    # ---------- 司机分类计费迁移（2026-09） ----------
    if "users" in insp.get_table_names():
        col_names = {c["name"] for c in insp.get_columns("users")}
        with engine.begin() as conn:
            if "vehicle_type" not in col_names:
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN vehicle_type VARCHAR(16)"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
            if "billing_mode" not in col_names:
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN billing_mode VARCHAR(16)"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
            if "salary" not in col_names:
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN salary NUMERIC(12,2)"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
            if "is_member" not in col_names:
                try:
                    # MySQL: TINYINT(1) BOOLEAN；SQLite 亦兼容
                    conn.execute(text("ALTER TABLE users ADD COLUMN is_member BOOLEAN NOT NULL DEFAULT 0"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
            # 计费规则模板（v3.36）：司机身上只挂一个外键，"怎么算钱"全在规则表里。
            # 新表本身由 create_all 自动建（见上面的 _import_all_models），这里只补这个新列。
            if "driver_rule_id" not in col_names:
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN driver_rule_id INTEGER"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
    if "orders" in insp.get_table_names():
        col_names = {c["name"] for c in insp.get_columns("orders")}
        with engine.begin() as conn:
            if "freight_fee" not in col_names:
                try:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN freight_fee NUMERIC(12,2)"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
            if "collect_cash" not in col_names:
                try:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN collect_cash BOOLEAN DEFAULT 0"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
            if "driver_billing_mode_snapshot" not in col_names:
                try:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN driver_billing_mode_snapshot VARCHAR(16)"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
            # 计费规则快照（v3.36）：规则改了/换了，已经派出去的单的金额不能跟着变。
            if "driver_rule_snapshot" not in col_names:
                try:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN driver_rule_snapshot TEXT"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
            # 派单员对这一单单独定的数（v3.36）：每单的钱不固定、提成也能逐单给
            for col, ddl in (
                ("driver_piece_amount", "NUMERIC(12,2)"),
                ("driver_commission_rate", "NUMERIC(5,2)"),
            ):
                if col not in col_names:
                    try:
                        conn.execute(text(f"ALTER TABLE orders ADD COLUMN {col} {ddl}"))
                    except DBAPIError as e:
                        msg = str(e).lower()
                        if "duplicate" in msg or "already exists" in msg:
                            pass
                        else:
                            raise
            if "parent_order_id" not in col_names:
                try:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN parent_order_id INTEGER"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
            if "exception_resolved_at" not in col_names:
                try:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN exception_resolved_at DATETIME"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
    # ---------- 司机账单上的计费规则留痕（v3.36）----------    # ⚠️ 新列必须在这里补：`create_all(checkfirst=True)` 只会建**缺失的表**，
    #    对**已存在的表**一个列都不会加（这是最容易误判的一条——"我加了字段怎么没生效"）。
    # ---------- 计费规则的「抽成商品范围」（v3.36 第二轮加）----------
    if "driver_billing_rules" in insp.get_table_names():
        rcols = {c["name"] for c in insp.get_columns("driver_billing_rules")}
        if "commission_product_ids" not in rcols:
            with engine.begin() as conn:
                try:
                    # MySQL: TEXT 列不允许 DEFAULT；NULL 由应用层容错为 []
                    if engine.dialect.name == "sqlite":
                        conn.execute(text("ALTER TABLE driver_billing_rules ADD COLUMN commission_product_ids TEXT DEFAULT '[]'"))
                    else:
                        conn.execute(text("ALTER TABLE driver_billing_rules ADD COLUMN commission_product_ids TEXT"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise

    if "driver_bills" in insp.get_table_names():
        bcols = {c["name"] for c in insp.get_columns("driver_bills")}
        for col, ddl in (
            ("rule_id", "INTEGER"),
            ("rule_name", "VARCHAR(128) DEFAULT ''"),
            ("piece_amount", "NUMERIC(12,2)"),
            ("commission_amount", "NUMERIC(12,2)"),
        ):
            if col in bcols:
                continue
            with engine.begin() as conn:
                try:
                    conn.execute(text(f"ALTER TABLE driver_bills ADD COLUMN {col} {ddl}"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise

    if "shipper_addresses" in insp.get_table_names():
        acols = {c["name"] for c in insp.get_columns("shipper_addresses")}
        if "image_url" not in acols:
            logger.warning("检测到旧库缺少 shipper_addresses.image_url，正在补列…")
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE shipper_addresses ADD COLUMN image_url VARCHAR(512)"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
        if "image_urls" not in acols:
            logger.warning("检测到旧库缺少 shipper_addresses.image_urls，正在补列（多图 JSON 数组）…")
            with engine.begin() as conn:
                try:
                    if engine.dialect.name == "sqlite":
                        conn.execute(text("ALTER TABLE shipper_addresses ADD COLUMN image_urls TEXT DEFAULT '[]'"))
                    else:
                        # MySQL: TEXT 列不允许 DEFAULT；NULL 由应用层容错为 []
                        conn.execute(text("ALTER TABLE shipper_addresses ADD COLUMN image_urls TEXT"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise

    if "shipper_locations" in insp.get_table_names():
        lcols = {c["name"] for c in insp.get_columns("shipper_locations")}
        if "image_url" not in lcols:
            logger.warning("检测到旧库缺少 shipper_locations.image_url，正在补列…")
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE shipper_locations ADD COLUMN image_url VARCHAR(512)"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
        if "image_urls" not in lcols:
            logger.warning("检测到旧库缺少 shipper_locations.image_urls，正在补列（多图 JSON 数组）…")
            with engine.begin() as conn:
                try:
                    if engine.dialect.name == "sqlite":
                        conn.execute(text("ALTER TABLE shipper_locations ADD COLUMN image_urls TEXT DEFAULT '[]'"))
                    else:
                        conn.execute(text("ALTER TABLE shipper_locations ADD COLUMN image_urls TEXT"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
    # ---------- 库存流水订单联动迁移（2026-09） ----------
    if "inventory_movements" in insp.get_table_names():
        mcols = {c["name"] for c in insp.get_columns("inventory_movements")}
        with engine.begin() as conn:
            if "source" not in mcols:
                try:
                    conn.execute(text("ALTER TABLE inventory_movements ADD COLUMN source VARCHAR(20) DEFAULT 'MANUAL'"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" not in msg and "already exists" not in msg:
                        raise
            if "order_id" not in mcols:
                try:
                    conn.execute(text("ALTER TABLE inventory_movements ADD COLUMN order_id INTEGER"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" not in msg and "already exists" not in msg:
                        raise
            if "status" not in mcols:
                try:
                    conn.execute(text("ALTER TABLE inventory_movements ADD COLUMN status VARCHAR(20) DEFAULT 'COMMITTED'"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" not in msg and "already exists" not in msg:
                        raise

    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_vehicle_type ON users (vehicle_type)"))
    except DBAPIError as e:
        # MySQL 不支持 IF NOT EXISTS；索引已存在或语法差异时忽略
        msg = str(e).lower()
        if "duplicate" not in msg and "already exists" not in msg and "syntax" not in msg:
            raise

    if "users" in insp.get_table_names():
        col_names = {c["name"] for c in insp.get_columns("users")}
        if "username" not in col_names:
            logger.warning("检测到旧库缺少 users.username，正在补列并从 phone 回填…")
            dialect = engine.dialect.name

            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(32)"))
                except DBAPIError as e:
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
                except DBAPIError:
                    logger.debug("ix_users_username 可能已存在，跳过")

    if "products" in insp.get_table_names():
        pcols = {c["name"] for c in insp.get_columns("products")}
        if "image_url" not in pcols:
            logger.warning("检测到旧库缺少 products.image_url，正在补列…")
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE products ADD COLUMN image_url VARCHAR(512)"))
                except DBAPIError as e:
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
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
        if "tier_prices" not in pcols:
            logger.warning("检测到旧库缺少 products.tier_prices，正在补列…")
            with engine.begin() as conn:
                try:
                    if engine.dialect.name == "sqlite":
                        conn.execute(text("ALTER TABLE products ADD COLUMN tier_prices TEXT DEFAULT '[]'"))
                    else:
                        conn.execute(text("ALTER TABLE products ADD COLUMN tier_prices TEXT"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
        if "unit" not in pcols:
            logger.warning("检测到旧库缺少 products.unit，正在补列…")
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE products ADD COLUMN unit VARCHAR(32) DEFAULT '件'"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
        if "low_stock_alert" not in pcols:
            logger.warning("检测到旧库缺少 products.low_stock_alert，正在补列…")
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE products ADD COLUMN low_stock_alert INTEGER DEFAULT 0"))
                except DBAPIError as e:
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
                except DBAPIError as e:
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
                except DBAPIError as e:
                    logger.warning("orders.shipper_id 可空迁移跳过: %s", e)
                # 旧库 orders.status 枚举缺少 DISPATCHED（历史版本只有 4 态）→ 派单接口 500
                try:
                    col_type = conn.execute(text(
                        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orders' AND COLUMN_NAME = 'status'"
                    )).scalar()
                    if col_type and "DISPATCHED" not in col_type:
                        logger.warning("检测到旧库 orders.status 枚举缺少 DISPATCHED，正在修复…")
                        conn.execute(text(
                            "ALTER TABLE orders MODIFY COLUMN status "
                            "ENUM('PENDING_DISPATCH','DISPATCHED','ACCEPTED','DELIVERED','CANCELLED') NOT NULL"
                        ))
                except DBAPIError as e:
                    logger.warning("orders.status 枚举修复跳过: %s", e)
                # 复合索引 (status, created_at)：待派池/列表查询加速，防万级积压全表扫
                try:
                    idx_rows = conn.execute(text(
                        "SHOW INDEX FROM orders WHERE Key_name = 'ix_orders_status_created'"
                    )).fetchall()
                    if not idx_rows:
                        conn.execute(text(
                            "ALTER TABLE orders ADD INDEX ix_orders_status_created (status, created_at)"
                        ))
                except DBAPIError as e:
                    logger.warning("orders 复合索引创建跳过: %s", e)

        ocols = {c["name"] for c in insp.get_columns("orders")}
        if "address_image_url" not in ocols:
            logger.warning("检测到旧库缺少 orders.address_image_url，正在补列…")
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN address_image_url VARCHAR(512)"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
        if "image_urls" not in ocols:
            logger.warning("检测到旧库缺少 orders.image_urls，正在补列（多图 JSON 数组）…")
            with engine.begin() as conn:
                try:
                    if engine.dialect.name == "sqlite":
                        conn.execute(text("ALTER TABLE orders ADD COLUMN image_urls TEXT DEFAULT '[]'"))
                    else:
                        conn.execute(text("ALTER TABLE orders ADD COLUMN image_urls TEXT"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
        if "temp_shipper_name" not in ocols:
            logger.warning("检测到旧库缺少 orders.temp_shipper_name，正在补列…")
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN temp_shipper_name VARCHAR(128)"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise

        ocols = {c["name"] for c in insp.get_columns("orders")}
        if "cancelled_at" not in ocols:
            logger.warning("检测到旧库缺少 orders.cancelled_at，正在补列并回填已撤销订单…")
            with engine.begin() as conn:
                try:
                    if dialect == "sqlite":
                        conn.execute(text("ALTER TABLE orders ADD COLUMN cancelled_at DATETIME"))
                    else:
                        conn.execute(text("ALTER TABLE orders ADD COLUMN cancelled_at DATETIME NULL"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
                try:
                    conn.execute(
                        text(
                            "UPDATE orders SET cancelled_at = updated_at "
                            "WHERE status = 'CANCELLED' AND cancelled_at IS NULL"
                        )
                    )
                except DBAPIError as e:
                    logger.warning("orders.cancelled_at 回填跳过: %s", e)

        ocols = {c["name"] for c in insp.get_columns("orders")}
        if "deleted_at" not in ocols:
            logger.warning("检测到旧库缺少 orders.deleted_at，正在补列（软删除隔离时间）…")
            with engine.begin() as conn:
                try:
                    if dialect == "sqlite":
                        conn.execute(text("ALTER TABLE orders ADD COLUMN deleted_at DATETIME"))
                    else:
                        conn.execute(text("ALTER TABLE orders ADD COLUMN deleted_at DATETIME NULL"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" in msg or "already exists" in msg:
                        pass
                    else:
                        raise
        if dialect == "mysql":
            with engine.begin() as conn:
                # orders(created_at)：3 年保留清理与前台列表都需要
                try:
                    if not conn.execute(text(
                        "SHOW INDEX FROM orders WHERE Key_name = 'ix_orders_created_at'"
                    )).fetchall():
                        conn.execute(text("ALTER TABLE orders ADD INDEX ix_orders_created_at (created_at)"))
                except DBAPIError as e:
                    logger.warning("orders.created_at 索引创建跳过: %s", e)
                # ledgers(entry_date)：账本 3 年保留清理
                try:
                    if not conn.execute(text(
                        "SHOW INDEX FROM ledgers WHERE Key_name = 'ix_ledgers_entry_date'"
                    )).fetchall():
                        conn.execute(text("ALTER TABLE ledgers ADD INDEX ix_ledgers_entry_date (entry_date)"))
                except DBAPIError as e:
                    logger.warning("ledgers.entry_date 索引创建跳过: %s", e)

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
                except DBAPIError as e:
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
                except DBAPIError as e:
                    logger.warning("ledgers.shipper_id 可空迁移跳过: %s", e)
                # 旧库 ledgers.source 枚举缺少 REFUND（货损成本回冲）→ 货损完成单 500
                try:
                    src_type = conn.execute(text(
                        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ledgers' AND COLUMN_NAME = 'source'"
                    )).scalar()
                    if src_type and "REFUND" not in src_type:
                        logger.warning("检测到旧库 ledgers.source 枚举缺少 REFUND，正在修复…")
                        conn.execute(text(
                            "ALTER TABLE ledgers MODIFY COLUMN source ENUM('ORDER','MANUAL','REFUND') NOT NULL"
                        ))
                except DBAPIError as e:
                    logger.warning("ledgers.source 枚举修复跳过: %s", e)
        elif dialect == "sqlite":
            from app.models.ledger import Ledger

            _sqlite_rebuild_table_for_nullable_shipper_id(engine, Ledger)

    # ---------- 账本 V2 迁移（2026-09） ----------
    if "order_products" in insp.get_table_names():
        opcols = {c["name"] for c in insp.get_columns("order_products")}
        with engine.begin() as conn:
            if "cost_price_snapshot" not in opcols:
                try:
                    conn.execute(text("ALTER TABLE order_products ADD COLUMN cost_price_snapshot NUMERIC(14,4) DEFAULT 0"))
                except DBAPIError as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise
            if "damage_quantity" not in opcols:
                try:
                    conn.execute(text("ALTER TABLE order_products ADD COLUMN damage_quantity INTEGER DEFAULT 0"))
                except DBAPIError as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise

    if "ledgers" in insp.get_table_names():
        lcols = {c["name"] for c in insp.get_columns("ledgers")}
        with engine.begin() as conn:
            if "cost_price_snapshot" not in lcols:
                try:
                    conn.execute(text("ALTER TABLE ledgers ADD COLUMN cost_price_snapshot NUMERIC(14,4) DEFAULT 0"))
                except DBAPIError as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise
            if "customer_id" not in lcols:
                try:
                    conn.execute(text("ALTER TABLE ledgers ADD COLUMN customer_id INTEGER"))
                except DBAPIError as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise

    if "orders" in insp.get_table_names():
        ocols = {c["name"] for c in insp.get_columns("orders")}
        if "damage_note" not in ocols:
            with engine.begin() as conn:
                try:
                    if engine.dialect.name == "sqlite":
                        conn.execute(text("ALTER TABLE orders ADD COLUMN damage_note TEXT DEFAULT ''"))
                    else:
                        conn.execute(text("ALTER TABLE orders ADD COLUMN damage_note TEXT"))
                except DBAPIError as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise

    if "ledger_export_jobs" in insp.get_table_names():
        ejcols = {c["name"] for c in insp.get_columns("ledger_export_jobs")}
        if "kind" not in ejcols:
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE ledger_export_jobs ADD COLUMN kind VARCHAR(16) DEFAULT 'ledger'"))
                except DBAPIError as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise

    # ---------- 商品软删除（2026-09-16 v3.26） ----------
    # 商品删除从"物理删除"改成"打标记"，否则 `inventory_movements` 会被级联整批删掉
    # （同一个商品的三种历史，订单/账本留、流水抹），而且删错了没法恢复。
    if "products" in insp.get_table_names():
        pcols = {c["name"] for c in insp.get_columns("products")}
        with engine.begin() as conn:
            if "is_deleted" not in pcols:
                try:
                    conn.execute(text("ALTER TABLE products ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0"))
                except DBAPIError as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise
            if "deleted_at" not in pcols:
                try:
                    conn.execute(text("ALTER TABLE products ADD COLUMN deleted_at DATETIME"))
                except DBAPIError as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise

    # ---------- 主数据「伪装删除」（2026-09-16 v3.26） ----------
    # 用户的底线是「不要删了就搞不回来了」：地址/地点/联系人/挂账单位/运费模板/专属价
    # 六张表都加 is_deleted + deleted_at，删除只打标记，`POST /{id}/restore` 逐字段照搬回来。
    # 唯一键的处理各不相同（联系人手机号加后缀释放、挂账单位名字加后缀释放、
    # 专属价靠"复活同一行"），见各自的 API 注释。
    for tbl in (
        "shipper_addresses",
        "shipper_locations",
        "shipper_contacts",
        "arrears_units",
        "freight_templates",
        "price_rules",
    ):
        if tbl not in insp.get_table_names():
            continue
        cols = {c["name"] for c in insp.get_columns(tbl)}
        if "is_deleted" in cols and "deleted_at" in cols:
            continue
        with engine.begin() as conn:
            if "is_deleted" not in cols:
                try:
                    conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0"))
                except DBAPIError as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise
            if "deleted_at" not in cols:
                try:
                    conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN deleted_at DATETIME"))
                except DBAPIError as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise

    # ---------- 计费方式归一成大写（2026-09-17） ----------
    #
    # 为什么要有这一步（不是"顺手清理"）：`billing_mode` 各消费点的大小写判据互相矛盾，
    # 而库里**同时存在**小写 `piece` 与大写 `PIECE`（AI 走的是小写、页面走的是大写）。
    # 后果不是显示问题，是钱：小写的司机在「司机运费结算」页看不到自己的单，
    # 在派单页被判成工资制（**不显示运费输入框** → 那一单的运费永远是空的），
    # 而司机账单里又算他是计件。写入侧已经收口（`normalize_billing_mode`），
    # 这里把**存量行**也拉齐，否则那些司机要等到下次有人改他们的账号才会好。
    if "users" in insp.get_table_names() and "billing_mode" in {c["name"] for c in insp.get_columns("users")}:
        with engine.begin() as conn:
            for tbl, col in (("users", "billing_mode"), ("orders", "driver_billing_mode_snapshot")):
                try:
                    r = conn.execute(
                        text(
                            f"UPDATE {tbl} SET {col} = UPPER({col}) "
                            f"WHERE {col} IS NOT NULL AND {col} <> UPPER({col})"
                        )
                    )
                    if r.rowcount:
                        logger.warning("计费方式归一：%s.%s 修正了 %s 行（小写 → 大写）", tbl, col, r.rowcount)
                except DBAPIError:
                    logger.debug("%s.%s 归一跳过（表或列可能不存在）", tbl, col)

    # ---------- 司机账单唯一性：同一单同一类型只能有一张（2026-09-18） ----------
    #
    # 为什么是**数据库级**约束而不是代码里多写一次判断：送达生成账单是"读-判断-写"，
    # 两个并发请求会各自读到"还没有账单"（本机 SQLite 实测：同一张单两条 60 元账单，
    # 见 tests/test_concurrent_delivery_money.py）。v3.40 给状态跃迁加了条件 UPDATE 占位，
    # 挡住了这一条路径；但补单接口 / 脚本 / 以后的批处理都能再插一次，唯一索引才是最后那道闸。
    #
    # ⚠️ 有重复行时**不建索引**并吵一声，绝不让启动崩掉：DDL 失败会让整个服务起不来
    #    （这一节历史上出过一次"启动崩溃循环"），而脏数据只是"多了一笔待结"。
    #    重复行由 `_tools/fuzz/_fuzz_invariants.py` 报出来、人工处置后再启动即自动建索引。
    if "driver_bills" in insp.get_table_names():
        dups: list = []
        try:
            with engine.connect() as conn:
                dups = conn.execute(
                    text(
                        "SELECT order_id, bill_type, COUNT(*) AS c FROM driver_bills "
                        "WHERE order_id IS NOT NULL GROUP BY order_id, bill_type HAVING c > 1"
                    )
                ).fetchall()
        except DBAPIError:
            logger.debug("driver_bills 重复检查跳过（表可能刚建）")
        if dups:
            logger.warning(
                "driver_bills 存在同一单多张账单的重复行（%s 组，例：订单 %s），"
                "**暂不创建唯一索引**。请先用 _tools/fuzz/_fuzz_invariants.py 定位、人工核对后清理，"
                "下次启动会自动补上索引。",
                len(dups),
                ", ".join(str(d[0]) for d in dups[:5]),
            )
        else:
            with engine.begin() as conn:
                if engine.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS uq_driver_bills_order_type "
                            "ON driver_bills (order_id, bill_type)"
                        )
                    )
                else:
                    try:
                        conn.execute(
                            text(
                                "CREATE UNIQUE INDEX uq_driver_bills_order_type "
                                "ON driver_bills (order_id, bill_type)"
                            )
                        )
                    except DBAPIError as e:
                        # MySQL 没有 IF NOT EXISTS：已存在时报 duplicate key name
                        if "duplicate" not in str(e).lower():
                            raise

    # ---------- 账本唯一性：同一订单行同一来源只能有一行（2026-09-19 审计） ----------
    #
    # 为什么必须是**数据库级**约束：送达自动入账（`ledger_sync.sync_ledger_from_delivered_order`）
    # 是"按 order_product_id + source 先查再插"的读-判断-写。并发下两个请求都读到"还没有"，
    # 就落两行同样的账 —— **营业额直接虚增**。本机实测复现过（订单 581 两条 60 元，
    # 就是 `_fuzz_invariants.py` 那条"订单账本净额与订单金额对不上"抓出来的）。
    # 生产实测目前 0 组重复（`ledgers` 上只有普通索引），所以可以安全补索引。
    #
    # ⚠️ 与 driver_bills 同一套纪律：有重复行时**不建索引**并吵一声，绝不让启动崩掉。
    if "ledgers" in insp.get_table_names():
        ldups: list = []
        try:
            with engine.connect() as conn:
                ldups = conn.execute(
                    text(
                        "SELECT order_product_id, source, COUNT(*) AS c FROM ledgers "
                        "WHERE order_product_id IS NOT NULL "
                        "GROUP BY order_product_id, source HAVING c > 1"
                    )
                ).fetchall()
        except DBAPIError:
            logger.debug("ledgers 重复检查跳过（表可能刚建）")
        if ldups:
            logger.warning(
                "ledgers 存在同一订单行重复入账（%s 组，例：order_product_id=%s），"
                "**暂不创建唯一索引**。请用 _tools/fuzz/_fuzz_invariants.py 的"
                "「订单账本净额与订单金额对不上」定位后人工清理，下次启动会自动补上索引。",
                len(ldups),
                ", ".join(str(d[0]) for d in ldups[:5]),
            )
        else:
            with engine.begin() as conn:
                if engine.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ledgers_order_product_source "
                            "ON ledgers (order_product_id, source)"
                        )
                    )
                else:
                    try:
                        conn.execute(
                            text(
                                "CREATE UNIQUE INDEX uq_ledgers_order_product_source "
                                "ON ledgers (order_product_id, source)"
                            )
                        )
                    except DBAPIError as e:
                        if "duplicate" not in str(e).lower():
                            raise

    # ---------- 散客电话唯一性：改成两库都成立的形式（2026-09-19 外部完整检查 S2） ----------
    #
    # 缺陷现场：`Customer` 上写的是
    # `Index("uq_customers_tmp_phone", "phone", unique=True, sqlite_where=text("kind='tmp' …"))`
    # —— `sqlite_where` 是 **SQLite 专属**参数，MySQL 上被**静默忽略**，于是这条"部分唯一索引"
    # 在生产被编译成**整表唯一**：给一个已存在的注册货主建同号散客档案 **必然 409**
    # （本机 SQLite 是 201，所以整套单测与探针都是绿的）。而"注册货主与散客同号"业务上很正常。
    #
    # 修法：把"谁参与唯一"编码进**列值**（`customers.tmp_phone_key`：散客填电话、其余 NULL），
    # 在它上面建普通唯一索引 —— 两种库对"唯一索引里的多个 NULL"语义一致，方言差异消失。
    # 迁移四步：① 加列 ② 回填 ③ **丢掉旧索引**（MySQL 上它就是那条错误的整表唯一，不丢则 bug 还在）
    # ④ 在新列上建唯一索引。
    if "customers" in insp.get_table_names():
        cust_cols = {c["name"] for c in insp.get_columns("customers")}
        if "tmp_phone_key" not in cust_cols:
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE customers ADD COLUMN tmp_phone_key VARCHAR(32)"))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if "duplicate" not in msg and "already exists" not in msg:
                        raise
        # 回填：老库上"散客 + 有电话"的行补上键值（幂等，只补空的那批）。
        # ⚠️ 这一步必须在**建新索引之前**，否则新索引建成后再回填会撞唯一约束。
        with engine.begin() as conn:
            try:
                conn.execute(
                    text(
                        "UPDATE customers SET tmp_phone_key = phone "
                        "WHERE kind = 'tmp' AND phone IS NOT NULL AND tmp_phone_key IS NULL"
                    )
                )
            except DBAPIError:
                logger.warning("customers.tmp_phone_key 回填失败（下次启动会重试）", exc_info=True)
        # ③ 丢旧索引：**这一步才是真正修掉生产那条 409 的地方**。
        #    SQLite 上旧索引与新的语义相同（本来就没坏），一起换掉只是为了两库同形。
        with engine.begin() as conn:
            try:
                if engine.dialect.name == "sqlite":
                    conn.execute(text("DROP INDEX IF EXISTS uq_customers_tmp_phone"))
                else:
                    conn.execute(text("ALTER TABLE customers DROP INDEX uq_customers_tmp_phone"))
            except DBAPIError as e:
                msg = str(e).lower()
                # MySQL 上没有这个索引时是 "Can't DROP …; check that column/key exists"
                if "check that column" not in msg and "doesn't exist" not in msg:
                    logger.warning("丢掉旧的 uq_customers_tmp_phone 失败（下次启动会重试）：%s", e)
        with engine.begin() as conn:
            try:
                if engine.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_tmp_phone "
                            "ON customers (tmp_phone_key)"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX uq_customers_tmp_phone "
                            "ON customers (tmp_phone_key)"
                        )
                    )
            except DBAPIError as e:
                msg = str(e).lower()
                if "duplicate" in msg or "already exists" in msg:
                    pass
                elif "duplicate entry" in msg or "1062" in msg:
                    # 老库上真的存在重复的"散客+电话" → **不建索引**并吵一声，绝不让启动崩掉
                    # （与 driver_bills / ledgers 那两处同一条纪律）。
                    logger.warning(
                        "customers 存在重复的散客电话，**暂不创建唯一索引**：%s。"
                        "请人工确认后清理，下次启动会自动补上。",
                        e,
                    )
                else:
                    raise

    # ---------- 商品分类 + 订单行单位 + 导航来源（2026-09-18） ----------
    #
    # 三列都是**纯展示/来源**信息，不参与任何金额计算，但没有它们界面就做不出来：
    # - `products.category`：选品页左侧分类导航（外卖式）按它分组。默认空串 = 「未分类」，
    #   老数据全部落在这一档，不逼用户先补分类才能下单。
    # - `order_products.unit_snapshot`：下单时定格的单位。空串 = 老数据，客户端显示时按空处理。
    # - `orders.nav_source`：导航信息是下单带的还是司机到场补录的（货主端那句提示必须是真的）。
    for tbl, col, ddl in (
        ("products", "category", "ALTER TABLE products ADD COLUMN category VARCHAR(32) NOT NULL DEFAULT ''"),
        (
            "order_products",
            "unit_snapshot",
            "ALTER TABLE order_products ADD COLUMN unit_snapshot VARCHAR(32) NOT NULL DEFAULT ''",
        ),
        ("orders", "nav_source", "ALTER TABLE orders ADD COLUMN nav_source VARCHAR(16)"),
    ):
        if tbl not in insp.get_table_names():
            continue
        cols = {c["name"] for c in insp.get_columns(tbl)}
        if col in cols:
            continue
        with engine.begin() as conn:
            try:
                conn.execute(text(ddl))
            except DBAPIError as e:
                if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                    raise

    # `places`（全局共享地点库）由 `Base.metadata.create_all` 建表，这里只补索引：
    # 老库上不存在这张表时 create_all 已经建好了；表存在但缺索引的情况只会出现在
    # "模型加了索引而表已经建过"的时候 —— 那种情况下按唯一名建，重复即跳过。
    if "places" in insp.get_table_names():
        for ddl, dup_ok in (
            ("CREATE INDEX ix_places_lat ON places (lat)", True),
            ("CREATE INDEX ix_places_lng ON places (lng)", True),
        ):
            with engine.begin() as conn:
                try:
                    conn.execute(text(ddl))
                except DBAPIError as e:
                    msg = str(e).lower()
                    if not dup_ok or ("duplicate" not in msg and "already exists" not in msg):
                        raise

    # ---------- 商品可见范围开关（2026-09-18 v3.43） ----------
    #
    # `users.product_scope`：`all`（默认，不限制）/ `custom`（只给白名单里的商品）。
    # ⚠️ 默认值必须是 `all` 并且**存量行也回填成 all**：这个字段是"是否启用白名单"的开关，
    #    回填成 custom 的话所有老货主的选品页会当场变空 —— 这类"默认把功能关掉"的迁移
    #    在界面上看起来像"商品全没了"，而真正的原因藏在一条 ALTER 里。
    if "users" in insp.get_table_names():
        ucols = {c["name"] for c in insp.get_columns("users")}
        if "product_scope" not in ucols:
            with engine.begin() as conn:
                try:
                    conn.execute(
                        text("ALTER TABLE users ADD COLUMN product_scope VARCHAR(16) NOT NULL DEFAULT 'all'")
                    )
                    logger.warning("users.product_scope 已补列并回填为 all（白名单默认关闭）")
                except DBAPIError as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise

        # ---------- 令牌版本列（2026-09-19）：服务端撤销令牌 ----------
        # 没有这一列时 `deps.get_current_user` 的版本比对取不到属性（按 0 兜底），
        # 于是"改密码 / 停用 / 登出立刻作废旧令牌"这条能力在老库上**静默失效**。
        # 默认 0 与"老令牌没有 tv claim 也按 0"一致 → 补列不会把任何人踢下线。
        if "token_version" not in ucols:
            with engine.begin() as conn:
                try:
                    col_type = "INTEGER" if engine.dialect.name == "sqlite" else "INT"
                    conn.execute(
                        text(f"ALTER TABLE users ADD COLUMN token_version {col_type} NOT NULL DEFAULT 0")
                    )
                    logger.warning("users.token_version 已补列（默认 0：旧令牌继续有效，改密码后立刻作废）")
                except DBAPIError as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise

    # ---------- 商品分类名册（2026-09-18 v3.43） ----------    #
    # `product_categories` 表由 `create_all` 建。这里做**存量回填**：
    # v3.42 的分类只是 `products.category` 上的一个字符串，名册是空的话选品页左侧那一列
    # 只能按"商品数倒序"推 —— 也就是用户说的"顺序不是我定的"。
    # 回填口径：把已经在用的分类名收进名册，**按用到的商品数从多到少**排
    # （这是最不意外的初始顺序，之后由派单员自己拖）。
    if "product_categories" in insp.get_table_names() and "products" in insp.get_table_names():
        rows: list = []
        try:
            with engine.connect() as conn:
                existing = conn.execute(text("SELECT COUNT(*) FROM product_categories")).scalar() or 0
            if existing == 0:
                with engine.begin() as conn:
                    rows = conn.execute(
                        text(
                            "SELECT TRIM(category) AS c, COUNT(*) AS n FROM products "
                            "WHERE category IS NOT NULL AND TRIM(category) <> '' "
                            "GROUP BY TRIM(category) ORDER BY n DESC, c ASC"
                        )
                    ).fetchall()
                    for idx, (name, _n) in enumerate(rows):
                        conn.execute(
                            text(
                                "INSERT INTO product_categories (name, sort_order, created_at, updated_at) "
                                "VALUES (:n, :s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                            ),
                            {"n": name, "s": idx},
                        )
                if rows:
                    logger.warning("商品分类名册已回填 %s 个分类（按在用的商品数排序）", len(rows))
        except DBAPIError:
            logger.debug("商品分类名册回填跳过（表可能刚建或字段不同）")
