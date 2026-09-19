# -*- coding: utf-8 -*-
"""数据保留治理（由 lifespan 后台循环每日调用一次）：
- 业务数据：服务器保留 3 年（orders/ledgers/operation_logs/cash_flows），到期物理删除（连带图片文件）
- 软删除（用户删除）：隔离 30 天，用户不可见、派单员可恢复；到期物理删除
- 原始图片：保留 1 年后自动压缩为「感知无损」WebP（Q90 / 长边≤1920），原图删除
注意：本模块无任何常驻定时器之外的额外调度；调用方 = main.lifespan 每日循环。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.cash_flow import CashFlow
from app.models.ledger import Ledger
from app.models.notification import Notification
from app.models.operation_log import OperationLog
from app.models.order import Order, OrderProduct
from app.services.image_archive import archive_images_older_than

logger = logging.getLogger(__name__)

# ---- 保留策略常量（用户拍板 2026-09-04）----
DATA_RETENTION_DAYS = 365 * 3          # 业务数据 3 年
SOFT_DELETE_RETENTION_DAYS = 30        # 软删除隔离 30 天（派单员可恢复）
NOTIFICATION_RETENTION_DAYS = 30       # 消息保留 30 天（与原消息中心约定一致）
BATCH_LIMIT = 2000                     # 每轮每表批量上限（大库分批收敛）


def delete_orders_by_ids(db: Session, ids: list[int]) -> int:
    """物理删除订单及明细、关联账本/操作日志，并清理其图片文件目录。"""
    if not ids:
        return 0
    ids = list(dict.fromkeys(int(i) for i in ids))
    db.execute(delete(Ledger).where(Ledger.order_id.in_(ids)))
    db.execute(delete(OperationLog).where(OperationLog.order_id.in_(ids)))
    db.execute(delete(OrderProduct).where(OrderProduct.order_id.in_(ids)))
    db.execute(delete(Order).where(Order.id.in_(ids)))
    # 图片文件级联（delivery/{order_id} 目录）
    for oid in ids[:200]:
        try:
            d = Path("uploads") / "delivery" / str(oid)
            if d.is_dir():
                for f in d.iterdir():
                    f.unlink(missing_ok=True)
                d.rmdir()
        except Exception:
            logger.warning("清理订单图片目录失败 orders=%s", oid, exc_info=True)
    return len(ids)


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def purge_soft_deleted_orders(db: Session) -> int:
    """软删除超过 30 天的订单 → 物理清理（隔离期结束）。"""
    cutoff = _now_utc_naive() - timedelta(days=SOFT_DELETE_RETENTION_DAYS)
    ids = [int(r[0]) for r in db.execute(
        select(Order.id).where(Order.deleted_at.isnot(None), Order.deleted_at < cutoff)
        .limit(BATCH_LIMIT)
    ).all()]
    n = delete_orders_by_ids(db, ids)
    logger.info("软删除隔离到期物理清理 %s 单（id=%s）", n, ids[:10])
    return n


def purge_expired_data(db: Session) -> int:
    """业务数据超过 3 年 → 物理清理（订单+账本+操作日志+现金流水）。"""
    cutoff = _now_utc_naive() - timedelta(days=DATA_RETENTION_DAYS)
    n = 0
    # 1) 订单（非软删，软删单走 30 天更快）
    ids = [int(r[0]) for r in db.execute(
        select(Order.id).where(Order.created_at < cutoff, Order.deleted_at.is_(None))
        .limit(BATCH_LIMIT)
    ).all()]
    if ids:
        n += delete_orders_by_ids(db, ids)
    # 2) 手工账本流水（非订单生成部分；订单生成部分随订单删除）
    try:
        n += db.execute(delete(Ledger).where(
            Ledger.order_id.is_(None), Ledger.entry_date < cutoff.date()
        ).execution_options(synchronize_session=False)).rowcount
    except Exception:
        logger.warning("ledgers 3年清理跳过", exc_info=True)
    # 3) 操作日志 / 费用流水 / 通知（临时数据，3 年清理）
    try:
        n += db.execute(delete(OperationLog).where(OperationLog.created_at < cutoff)
                        .execution_options(synchronize_session=False)).rowcount
        n += db.execute(delete(CashFlow).where(CashFlow.created_at < cutoff)
                        .execution_options(synchronize_session=False)).rowcount
        n += db.execute(delete(Notification).where(Notification.created_at < cutoff)
                        .execution_options(synchronize_session=False)).rowcount
    except Exception:
        logger.warning("logs/cashflows/notifications 3年清理跳过", exc_info=True)
    logger.info("3 年期数据清理完成 %s 行", n)
    return n


def purge_expired_notifications(db: Session) -> int:
    """消息保留 30 天（与前端消息中心一致）。"""
    cutoff = _now_utc_naive() - timedelta(days=NOTIFICATION_RETENTION_DAYS)
    n = db.execute(delete(Notification).where(Notification.created_at < cutoff)
                   .execution_options(synchronize_session=False)).rowcount
    return n


def run_daily_retention(db: Session) -> dict[str, int]:
    """数据治理总入口。返回各步骤删除量。"""
    r = {
        "soft_deleted_purged": purge_soft_deleted_orders(db),
        "expired_purged": purge_expired_data(db),
        "notifications_purged": purge_expired_notifications(db),
    }
    # 图片：1 年原图自动压缩（Q90 感知无损，原图删除）
    r["images_archived"] = archive_images_older_than(days=365)
    db.commit()
    return r
