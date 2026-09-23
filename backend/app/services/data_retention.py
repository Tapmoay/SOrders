# -*- coding: utf-8 -*-
"""数据保留治理（由 lifespan 后台循环每日调用一次）：
- 业务数据：服务器保留 3 年（orders/ledgers/operation_logs/cash_flows），到期物理删除（连带图片文件）
- 软删除（用户删除）：隔离 30 天，用户不可见、派单员可恢复；到期物理删除
- 原始图片：保留 1 年后自动压缩为「感知无损」WebP（Q90 / 长边≤1920），原图删除
注意：本模块无任何常驻定时器之外的额外调度；调用方 = main.lifespan 每日循环。
⚠️ 入口 `run_daily_retention` 自带**跨进程互斥**（见 `_single_runner`）：多 worker 部署下
只有一个进程会真的执行，其余进程当轮跳过（不是排队重跑）。
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.business_time import business_today, utc_now_naive
from app.models.cash_flow import CashFlow
from app.models.driver_bill import DriverBill
from app.models.enums import DriverBillStatus, UserRole
from app.models.inventory import InventoryMovement
from app.models.ledger import Ledger
from app.models.notification import Notification
from app.models.operation_log import OperationLog
from app.models.order import Order, OrderProduct
from app.models.order_return_request import OrderReturnRequest
from app.models.place import Place
from app.models.product import ProductCostHistory
from app.models.shipper_settlement import ShipperSettlement
from app.models.user import User
from app.services.image_archive import (
    archive_images_older_than,
    purge_orphan_compressed,
    purge_orphan_images,
)
from app.services.ledger_export_paths import EXPORT_DIR, LEGACY_UPLOAD_EXPORTS
from app.services.money_text import money_text

logger = logging.getLogger(__name__)

#: 治理的跨进程锁文件（与 `schema_bootstrap` 同一个思路）。
GOVERNANCE_LOCK_PATH = "/tmp/sorders_retention.lock"

#: 「今天已经治理过了」的标记文件。
#:
#: ⚠️ 为什么光有锁不够（2026-09-19 **生产实测**）：锁只挡**并发**。空库上第一轮治理 200 毫秒
#: 就跑完并释放了锁，另一个 worker 紧接着拿到锁**又跑了一遍** —— journal 里两条
#: "数据保留治理完成"，时间差 203ms。任务幂等所以不毁数据，但"每天一次"变成了"每天 N 次"；
#: 而在真实的库上（几万张图要重新扫 mtime、几万行要重新比时间）那是白烧 CPU 与磁盘 IO。
#: 所以拿到锁之后再问一句"今天是不是已经跑过"。
#: 用**文本文件**而不是数据库行：治理的第一步就是删数据，标记不能跟着那份事务一起回滚。
GOVERNANCE_MARKER_PATH = "/tmp/sorders_retention.last"

#: 导出产物的保留期（天）。派生数据，源数据在库里还能再导一次——不需要留 3 年。
EXPORT_FILE_RETENTION_DAYS = 30

# ---- 保留策略常量（用户拍板 2026-09-04）----
DATA_RETENTION_DAYS = 365 * 3          # 业务数据 3 年
SOFT_DELETE_RETENTION_DAYS = 30        # 软删除隔离 30 天（派单员可恢复）
NOTIFICATION_RETENTION_DAYS = 30       # 消息保留 30 天（与原消息中心约定一致）
BATCH_LIMIT = 2000                     # 每轮每表批量上限（大库分批收敛）


def _already_ran_today() -> bool:
    """今天（**业务当地日**）是不是已经治理过一轮了。读不到标记就当"没跑过"。"""
    try:
        return Path(GOVERNANCE_MARKER_PATH).read_text(encoding="utf-8").strip() == business_today().isoformat()
    except OSError:
        return False


def _mark_ran_today() -> None:
    """写"今天跑过了"。**跑完才写**：中途崩掉时另一个 worker 还应该能接手。"""
    try:
        Path(GOVERNANCE_MARKER_PATH).write_text(business_today().isoformat(), encoding="utf-8")
    except OSError:
        # 写不进去只意味着"另一个 worker 会再跑一遍"（幂等，无害），不该让治理失败。
        logger.warning("写治理标记失败（另一个 worker 会重复跑一轮，无副作用）：%s", GOVERNANCE_MARKER_PATH)


@contextmanager
def _single_runner():
    """跨进程互斥：**拿不到锁就跳过本轮**，而不是排队等它跑完再原样跑一遍。

    ⚠️ 为什么必须有（2026-09-19 外部完整检查 PERF-05 / R2-5(bak)）：
    治理循环挂在 `main.lifespan` 上，而生产是 `uvicorn --workers 2`
    （systemd 的 `ExecStart`）—— **两个 worker 启动后各跑一遍，之后每天再各跑一遍**，
    而整套治理（物理删单、作废应付明细、压图、清导出产物）原来没有任何互斥。
    实测后果：两个执行者同时压同一张图时，40 轮里有 4 张**根本没压成**、
    30 轮一方失败；单执行者对照 40/40 全成。而"删数据"被重复执行的后果比压图严重得多。

    同仓库为并发 DDL 专门加过 `fcntl` 锁（`schema_bootstrap.bootstrap_schema`），
    这里的道理完全一样，只是当时漏了。

    ⚠️ 用 `LOCK_NB`（非阻塞）而不是 `LOCK_EX`（阻塞）：阻塞会让第二个 worker
    **等第一个跑完、然后自己再跑一遍** —— 那正是要避免的重复执行，跳过才是本意。
    Windows 本机开发没有 `fcntl`（单进程也无所谓），照常执行。
    """
    try:
        import fcntl
    except ImportError:                    # pragma: no cover - Windows 本机开发
        yield True
        return
    lock_file = open(GOVERNANCE_LOCK_PATH, "w")
    try:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
    finally:
        lock_file.close()


def _orders_with_blocking_docs(db: Session, ids: list[int]) -> list[int]:
    """这些单**还有凭证/单据指着它** → 不做物理清理（返回它们的 id）。

    ### 为什么必须有这一条（2026-09-23 第 13 轮：把"指向 orders 的外键"逐个盘了一遍）

    `orders` 上有 **9 个外键**指着它，而 `delete_orders_by_ids` 原来只解开了 5 个
    （`places.first_order_id` 置空 + `driver_bills` 作废 + `ledgers`/`operation_logs`/
    `inventory_movements`/`order_products` 删除）。漏掉的四个里，`orders.parent_order_id`
    是可空自引用（现在置空），另外三个是 **NOT NULL**：

    | 表 | 是什么 | 漏掉的后果 |
    |---|---|---|
    | `order_return_requests` | 货主提的**退货申请**（带办理/驳回记录） | 删单时 InnoDB 抛 `IntegrityError` |
    | `shipper_settlements` | 货主/批发商的**核销凭证**（"这笔钱收到了"） | 同上 |
    | `shipper_settlement_lines` | 上面那张凭证的逐商品明细 | 同上 |

    ⚠️ **后果不是"这一单删不掉"，而是"当天的治理全部停摆"**：异常一路冒到
    `main._retention_sync` 被吞成一行日志 + `db.rollback()` —— 于是当天的 3 年清理、
    消息清理、图片归档、导出产物清理**全部不执行，而且每天重复失败**
    （2026-09-19 审计 R12 那一类，当时是 `places.first_order_id`）。

    ⛔ 为什么不直接把这些凭证删掉：它们是**钱的凭证**（核销单）与**客户的诉求**
    （退货申请），删了就再也复核不了 —— 与 R12-H4 给司机账单定的口径一致
    （"已结算的账单保留不动，那是已经付过的钱，删掉才是真的毁账"）。
    所以这里的选择是：**这一单不做物理清理**，写日志 + 给派单员发站内信
    （钱/单据的事必须有人能在界面上看见），由人去界面上处理掉那张凭证后再让它过期。

    ⚠️ 代价要说清：这些单会**超过 30 天还在回收站里**。那是"承诺的例外"，
    不是静默失败 —— 探针里那条「隔离区超过 30 天 + 1 天」的不变式会把它报出来。
    """
    blocked: set[int] = set()
    for want in (OrderReturnRequest, ShipperSettlement):
        rows = db.execute(
            select(want.order_id).where(want.order_id.in_(ids)).distinct()
        ).all()
        blocked.update(int(r[0]) for r in rows)
    return sorted(blocked)


def _notify_orders_not_purged(db: Session, ids: list[int]) -> None:
    """把"这些单没被物理清理、为什么"写成**站内信**（给派单员）。

    同 `_notify_bills_cancelled` 的理由：只写日志等于没人看得见 ——
    单还躺在回收站里、账还占着口径，而界面上没有任何提示。
    """
    body = (
        f"{len(ids)} 张订单已过 30 天隔离期，但**没有被物理清理**：它们上面还挂着"
        "退货申请或货主核销凭证，清掉单会把凭证一起毁掉。"
        f"涉及订单 id={ids[:10]}。请在「订单回收站」里先处理掉那些凭证（或恢复该单）。"
    )
    dispatchers = db.scalars(
        select(User).where(User.role == UserRole.DISPATCHER.value, User.is_active.is_(True))
    ).all()
    for u in dispatchers:
        db.add(
            Notification(
                recipient_id=u.id,
                category="reminder",
                type="order_purge_blocked",
                title="有订单因凭证未处理而没有被清理",
                content=body,
                speech_important=True,
                payload={"order_ids": ids[:50]},
            )
        )


def delete_orders_by_ids(db: Session, ids: list[int]) -> int:
    """物理删除订单及明细、关联账本/操作日志，并清理其图片文件目录。

    ⚠️ 2026-09-19 审计补的两件事（都是"到期必然发生"的，不是理论风险）：

    ① **先把 `places.first_order_id` 置空**。那一列是 `ForeignKey("orders.id")`，而 MySQL/InnoDB
       默认 RESTRICT —— 只要有一张"司机补过导航"的软删单（`place_service.upsert_place` 会把
       `first_order_id` 永久绑到那张单上），下面的 `DELETE FROM orders` 就会抛 IntegrityError；
       而异常会被 `main.py` 的循环吞成一行日志并 rollback → **当天的 3 年清理、消息清理、
       图片归档全部不执行，且每天重复失败**（本机 SQLite 不校验外键，所以本地永远绿）。
    ② **把还开着的司机应付明细作废（不是删除）**。原来只删订单/明细/账本/日志，`driver_bills`
       原样留着 —— 一张**用户已经删掉、库里也已经不存在**的单，它的运费照样能被结算单收进去并
       **真金白银付出去**（`create_settlement` 按 driver+month+OPEN 取明细，不看订单在不在），
       而同一张单在运费结算页是被明确排除的（口径相反且两边都不报错）。
       作废用 `DriverBillStatus.CANCELLED`（这个值以前全仓库 0 个写入点），并留一行日志；
       **已结算（SETTLED）的账单保留不动** —— 那是已经付过的钱，删掉才是真的毁账。
    """
    if not ids:
        return 0
    ids = list(dict.fromkeys(int(i) for i in ids))
    # ⓪ 还有凭证/单据指着的单：**不做物理清理**（外键 NOT NULL，删凭证等于毁账）。
    #    详见 `_orders_with_blocking_docs`：漏了这一条不是"删不掉这一单"，
    #    而是当天的整套治理全部停摆（异常被吞、每天重复失败）。
    blocked = _orders_with_blocking_docs(db, ids)
    if blocked:
        logger.warning(
            "订单到期清理：%s 张单还有退货申请/核销凭证，**跳过物理清理**（id=%s）",
            len(blocked), blocked[:10],
        )
        _notify_orders_not_purged(db, blocked)
        ids = [i for i in ids if i not in set(blocked)]
        if not ids:
            return 0
    # ① 解开外键（否则整轮保留任务停摆）
    db.execute(
        update(Place).where(Place.first_order_id.in_(ids)).values(first_order_id=None)
    )
    # ⚠️ 拆单的子单指着父单（`orders.parent_order_id`，自引用外键）：父单被物理清理时
    #    必须先把子单那根指向解开 —— 否则同样是 IntegrityError → 当天治理全停。
    #    子单本身是独立可用的单（金额、账本、账单都是自己的），置空不影响任何口径。
    db.execute(
        update(Order).where(Order.parent_order_id.in_(ids)).values(parent_order_id=None)
    )
    # ② 还开着的司机应付明细 → 作废（保住"没有单就不该有人能付这笔钱"）
    open_bills = list(
        db.scalars(
            select(DriverBill).where(
                DriverBill.order_id.in_(ids),
                DriverBill.status == DriverBillStatus.OPEN,
            )
        ).all()
    )
    for bill in open_bills:
        bill.status = DriverBillStatus.CANCELLED
        bill.note = (bill.note or "").strip() + (
            # 这句 `note` 是给**人**看的（派单员要照着这行人工复核）→ 金额过 `money_text` 去尾零。
            f"［订单已过 30 天隔离期被物理清理，应付明细随之作废；金额 {money_text(bill.amount)} 元需人工复核］"
        )
    if open_bills:
        total = sum((b.amount or 0) for b in open_bills)
        logger.warning(
            "订单到期清理：作废 %s 条司机应付明细（合计 %s 元），涉及订单 id=%s",
            len(open_bills),
            total,
            ids[:10],
        )
        # ⚠️ 光记日志**不算通知**（2026-09-19 审计 R12-H4）：司机在司机端看不到这张账单
        #    （账单状态只认 open），派单员在结算页也收不到它 —— 那笔钱就这么没了，
        #    而唯一的痕迹是服务器上一行日志 + 一个界面上查不到的 note 字段。
        #    这里给**司机和派单员各发一条站内信**：钱的事必须有人能在界面上看见。
        _notify_bills_cancelled(db, open_bills, total)
    db.execute(delete(Ledger).where(Ledger.order_id.in_(ids)))
    db.execute(delete(OperationLog).where(OperationLog.order_id.in_(ids)))
    # ⚠️ 库存流水也要一起删（2026-09-19 审计第十七轮）：只删 Order/OrderProduct 的话，
    #    那些 `RESERVED` 流水会**永久**留在库里，被 `/inventory/summary` 当成"在途占用"
    #    一直计入（用户按它决定要不要补货），而对应的订单早已不存在。
    #    台账 D3 只修了"账单那一半"，这一半漏了。
    db.execute(delete(InventoryMovement).where(InventoryMovement.order_id.in_(ids)))
    db.execute(delete(OrderProduct).where(OrderProduct.order_id.in_(ids)))
    db.execute(delete(Order).where(Order.id.in_(ids)))
    # 图片文件级联（delivery/{order_id} 目录）
    # ⚠️ 这里原来写的是 `ids[:200]`，而每轮上限是 [BATCH_LIMIT]（2000）——
    #    第 201 张起，订单行已经删了、**没有任何东西再引用那些文件**，
    #    于是送达照片（本系统最大一类文件）永久残留在磁盘上（2026-09-19 审计 R12-M7）。
    #    口径改成与批量上限同源：这一轮删了哪些单，就清哪些单的目录。
    for oid in ids:
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
    """保留任务用的"现在"（UTC naive）—— 与业务时间同源，见 `business_time.utc_now_naive`。

    2026-09-19 审计 R14-9：这个函数原来自己 `datetime.now(timezone.utc)` 了一份，
    而 `GET /notifications?days=` 用的是 `datetime.now()`（**本地**时间）——
    同一个"30 天"在两处是两个基准，现在统一到一处。
    """
    return utc_now_naive()


def _notify_bills_cancelled(db: Session, bills: list[DriverBill], total) -> None:
    """把"谁的哪笔钱被作废了"写成**站内信**（司机一条、派单员各一条）。

    2026-09-19 审计 R12-H4：原来只有 `logger.warning` + 账单 `note` 字段。
    而司机端账单状态只认 `open`（作废的看不见）、结算页也只取 OPEN，
    派单员在界面上**没有任何入口**能看到"这笔钱被系统抹掉了"——
    唯一的痕迹是服务器日志里一行字。钱的事必须有人能在界面上看见。
    """
    from app.models.notification import Notification

    order_ids = sorted({int(b.order_id) for b in bills if b.order_id is not None})
    drivers = {int(b.driver_id): b for b in bills if b.driver_id is not None}
    body = (
        f"{len(bills)} 条司机应付明细因订单过了 30 天隔离期被物理清理而作废，"
        f"合计 {money_text(total)} 元，涉及订单 {order_ids[:10]}。"
        "这些单的明细在界面上已不再显示，如需追溯请查审计日志。"
    )
    for driver_id in drivers:
        db.add(
            Notification(
                recipient_id=driver_id,
                category="reminder",
                type="driver_bill_cancelled",
                title="有一笔应付明细已作废",
                content=body,
                speech_important=True,
                payload={"order_ids": order_ids, "amount": str(total)},
            )
        )
    dispatchers = db.scalars(
        select(User).where(User.role == UserRole.DISPATCHER.value, User.is_active.is_(True))
    ).all()
    for u in dispatchers:
        db.add(
            Notification(
                recipient_id=u.id,
                category="reminder",
                type="driver_bill_cancelled",
                title="订单到期清理作废了司机应付明细",
                content=body,
                speech_important=True,
                payload={"order_ids": order_ids, "amount": str(total)},
            )
        )


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
    # 4) 成本价时间轴：**跟着账本走**（用户 2026-09-19：「这个保留是跟着他的账本走的。
    #    假如他的账本是一直保留着，那他这个成本价就一直保留着」）→ 与 ledgers 同一档 3 年。
    #    ⚠️ 判据必须用 `effective_to`（**这段价什么时候结束**），不是 `effective_from`：
    #       用后者会把"三年前定的价、现在还在用"那一行删掉 —— 而它正是当前生效价，
    #       删了之后这个商品的成本时间轴就断在最需要它的地方。
    try:
        n += db.execute(delete(ProductCostHistory).where(
            ProductCostHistory.effective_to.isnot(None),
            ProductCostHistory.effective_to < cutoff,
        ).execution_options(synchronize_session=False)).rowcount
    except Exception:
        logger.warning("product_cost_history 3年清理跳过", exc_info=True)
    logger.info("3 年期数据清理完成 %s 行", n)
    return n


def purge_expired_notifications(db: Session) -> int:
    """消息保留 30 天（与前端消息中心一致）。"""
    cutoff = _now_utc_naive() - timedelta(days=NOTIFICATION_RETENTION_DAYS)
    n = db.execute(delete(Notification).where(Notification.created_at < cutoff)
                   .execution_options(synchronize_session=False)).rowcount
    return n


def purge_old_export_files(days: int = EXPORT_FILE_RETENTION_DAYS) -> int:
    """导出产物过期清理（2026-09-19 审计 R12-M9）。

    ### 为什么必须清
    每次导出都写一个新文件（文件名带随机段、不覆盖），而治理原来只清
    orders/ledgers/logs/notifications —— `exports/` 从来没被碰过。两条后果：
    ① 磁盘只增不减；② **保留承诺被绕过**：3 年后连订单行和账本行都物理删了，
       当年导出的那份 Excel（货主名/商品/单价/总额/订单号）还躺在服务器上，
       既没人知道有几份、也没人负责清。

    保留期取 [EXPORT_FILE_RETENTION_DAYS]（比 30 天隔离期长，够用户回来重下；
    比业务数据的 3 年短得多，因为它是**派生数据**，源数据在库里还能再导一次）。
    """
    cutoff = time.time() - days * 86400
    removed = 0
    for d in (EXPORT_DIR, LEGACY_UPLOAD_EXPORTS):
        p = Path(d)
        if not p.is_dir():
            continue
        for f in p.iterdir():
            try:
                if not f.is_file():
                    continue
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
                    removed += 1
            except Exception:
                logger.warning("清理导出产物失败 file=%s", f, exc_info=True)
    if removed:
        logger.info("导出产物过期清理 %s 个（保留 %s 天）", removed, days)
    return removed


def run_daily_retention(db: Session) -> dict[str, int]:
    """数据治理总入口。返回各步骤删除量。

    拿不到跨进程锁 → `{"skipped": 1}`；今天已经跑过 → `{"skipped_same_day": 1}`。

    ⚠️ 顺序是**故意的**（2026-09-19 审计 R12-L8）：先把数据库那几步提交，再做文件级清理
    （图片压缩、导出产物过期、孤儿压缩图）。原来四步共用一个事务、最后才 `commit`：
    图片压缩里任何一张图抛错 → **当天三块 DB 清理全部回滚，而磁盘上的文件已经真删了**，
    于是出现"文件没了、行还在"（订单还在、照片 404），下一次要等 24 小时。
    """
    with _single_runner() as is_runner:
        if not is_runner:
            logger.info(
                "本机已有另一个进程在跑数据治理，本轮跳过（跨进程锁 %s）", GOVERNANCE_LOCK_PATH
            )
            return {"skipped": 1}
        if _already_ran_today():
            # 锁只挡并发：第一个 worker 200ms 跑完释放锁后，第二个会拿到锁再跑一遍
            # （2026-09-19 生产实测，journal 里两条"治理完成"）。任务幂等，但没必要。
            return {"skipped_same_day": 1}
        r = _run_daily_retention_locked(db)
        _mark_ran_today()
        return r


def _run_daily_retention_locked(db: Session) -> dict[str, int]:
    r: dict[str, int] = {}
    # ⚠️ **每一步各自一个 savepoint**（2026-09-23 第 13 轮）：整套治理是"一个事务 + 最后
    #    一次 commit"，于是**任何一步抛异常都会让当天的全部清理一起回滚**（而且每天重复失败）——
    #    2026-09-19 审计 R12 就是因为 `places.first_order_id` 那个外键，让"3 年清理、消息清理、
    #    图片归档"一起停摆。现在一步失败只丢那一步：记 -1（调用方与 journal 能看出是哪一步），
    #    其余照跑。⚠️ `begin_nested` 在 MySQL/SQLite 上都是 SAVEPOINT（不需要额外配置）。
    for name, step in (
        ("soft_deleted_purged", purge_soft_deleted_orders),
        ("expired_purged", purge_expired_data),
        ("notifications_purged", purge_expired_notifications),
    ):
        try:
            with db.begin_nested():
                r[name] = step(db)
        except Exception:
            logger.exception(
                "数据治理的这一步失败了，跳过它继续跑后面的（一步失败不该让当天全部清理停摆）：%s", name
            )
            db.rollback()
            r[name] = -1
    db.commit()
    # ---- 以下是**文件级**清理：与上面的事务分开（失败不该把 DB 那几步一起回滚）----
    r["images_archived"] = archive_images_older_than(days=365)
    r["compressed_orphans_purged"] = purge_orphan_compressed()
    r["exports_purged"] = purge_old_export_files()
    # ⚠️ 放在 DB 那几步**之后**：它要按"库里还引用着哪些 URL"来判，必须看到本轮删完之后的真实引用集。
    r["orphan_images_purged"] = purge_orphan_images(db)
    return r
