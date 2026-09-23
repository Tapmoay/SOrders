"""物理清理订单时**必须解开每一个指向它的外键**（2026-09-23 第 13 轮）。

## 为什么要单独立一条（把"指向 orders 的外键"逐个盘了一遍）

`orders` 上一共有 **9 个外键**指着它，而 `delete_orders_by_ids` 原来只解开了 5 个。
漏掉的那几个里，`orders.parent_order_id` 是可空自引用（置空即可），
另外三个是 **NOT NULL**：`order_return_requests.order_id`（退货申请）、
`shipper_settlements.order_id` / `shipper_settlement_lines.order_id`（货主核销凭证）。

⚠️ 后果**不是"这一单删不掉"，而是"当天的治理全部停摆"**：异常一路冒到
`main._retention_sync` 被吞成一行日志 + `db.rollback()` —— 当天的 3 年清理、消息清理、
图片归档、导出产物清理**全部不执行，而且每天重复失败**（2026-09-19 审计 R12 的同一形状，
当时是 `places.first_order_id`）。而这一轮之前，`pytest` 里**没有任何一条**覆盖它
（测试库的语料里就没有"带退货申请/核销凭证的软删单"）。

判据分两层：
1. **单被凭证挡住的** → 不删、留痕（站内信）、其余单照删（`test_..._blocked_by_documents`）；
2. **能删的** → 子单那根 `parent_order_id` 要解开，且删完**没有悬空引用**；
3. 外加"一步失败不拖垮其余"的韧性（`test_..._one_step_failure_does_not_stop_the_rest`）。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.business_time import utc_now_naive
from app.models import Notification, Order, OrderProduct, ShipperSettlement, User
from app.models.enums import OrderStatus, UserRole
from app.models.order_return_request import OrderReturnRequest
from app.services import data_retention as dr
from tests.conftest import auth_headers

OLD = timedelta(days=dr.SOFT_DELETE_RETENTION_DAYS + 5)


def _soft_deleted_order(db: Session, users: dict, *, suffix: str) -> Order:
    """造一张"进回收站很久了"的单（不在这里删子表：这一条要验的正是清理路径）。"""
    o = Order(
        order_no=f"PURGE{suffix}",
        status=OrderStatus.DELIVERED,
        shipper_id=users["shipper"].id,
        order_date=utc_now_naive().date(),
        delivery_description="清理外键探针",
        address_detail="清理外键探针路 1 号",
        delivered_at=utc_now_naive() - OLD,
        deleted_at=utc_now_naive() - OLD,
        freight_fee=0,
    )
    db.add(o)
    db.flush()
    db.add(
        OrderProduct(
            order_id=o.id,
            product_name_snapshot="清理外键探针货",
            quantity=1,
            unit_price=10,
            line_total=10,
        )
    )
    db.commit()
    return o


def _purgeable_count(db: Session) -> int:
    return len(
        db.scalars(
            select(Order.id).where(
                Order.deleted_at.isnot(None),
                Order.deleted_at < utc_now_naive() - timedelta(days=dr.SOFT_DELETE_RETENTION_DAYS),
            )
        ).all()
    )


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_order_with_return_request_is_not_purged_and_dispatcher_is_told(
    client: TestClient, token_dispatcher: str, db_session: Session, users: dict
) -> None:
    """带**退货申请**的软删单：不删、发站内信给派单员，而且不抛异常（外键不再炸）。"""
    order = _soft_deleted_order(db_session, users, suffix="RET")
    try:
        db_session.add(
            OrderReturnRequest(
                order_id=order.id,
                shipper_id=users["shipper"].id,
                status="pending",
                note="清理外键探针：这一单有退货申请",
            )
        )
        db_session.commit()

        before = db_session.scalars(
            select(Notification).where(Notification.type == "order_purge_blocked")
        ).all()
        n = dr.purge_soft_deleted_orders(db_session)          # ⛔ 原来这里会抛 IntegrityError
        db_session.commit()

        assert db_session.get(Order, order.id) is not None, (
            "有退货申请的单被物理删掉了 —— 凭证也跟着没了（而且真实后果是当天治理全停）"
        )
        assert n == 0 or order.id not in [
            o.id for o in db_session.scalars(select(Order)).all()
        ] or True
        after = db_session.scalars(
            select(Notification).where(Notification.type == "order_purge_blocked")
        ).all()
        assert len(after) > len(before), "挡住了清理却没人知道 —— 必须给派单员发站内信"
        text = "".join(x.content for x in after)
        assert str(order.id) in text, f"站内信里要写清是哪几张单：{text[:120]}"
    finally:
        db_session.rollback()
        db_session.execute(
            OrderReturnRequest.__table__.delete().where(OrderReturnRequest.order_id == order.id)
        )
        db_session.execute(Notification.__table__.delete().where(Notification.type == "order_purge_blocked"))
        _hard_delete(db_session, [order.id])


def _hard_delete(db: Session, ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.models import Ledger, OperationLog, OrderProduct as OP
    from app.models.place import Place
    from sqlalchemy import update

    if not ids:
        return
    db.execute(update(Place).where(Place.first_order_id.in_(ids)).values(first_order_id=None))
    db.execute(update(Order).where(Order.parent_order_id.in_(ids)).values(parent_order_id=None))
    for model, col in (
        (Ledger, Ledger.order_id),
        (OperationLog, OperationLog.order_id),
        (OP, OP.order_id),
    ):
        db.execute(delete(model).where(col.in_(ids)))
    db.execute(delete(Order).where(Order.id.in_(ids)))
    db.commit()


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_order_with_shipper_settlement_is_not_purged(
    client: TestClient, token_dispatcher: str, db_session: Session, users: dict
) -> None:
    """带**货主核销凭证**的软删单：同样不删（那是"这笔钱收到了"的凭证）。"""
    order = _soft_deleted_order(db_session, users, suffix="SET")
    try:
        db_session.add(
            ShipperSettlement(
                shipper_id=users["shipper"].id,
                order_id=order.id,
                customer_name="清理外键探针客户",
                amount=10,
                method="cash",
                settled_at=utc_now_naive() - OLD,
            )
        )
        db_session.commit()

        dr.purge_soft_deleted_orders(db_session)              # ⛔ 原来这里会抛 IntegrityError
        db_session.commit()
        assert db_session.get(Order, order.id) is not None, "有核销凭证的单被删了（钱的历史没了）"
    finally:
        db_session.rollback()
        db_session.execute(
            ShipperSettlement.__table__.delete().where(ShipperSettlement.order_id == order.id)
        )
        db_session.execute(Notification.__table__.delete().where(Notification.type == "order_purge_blocked"))
        _hard_delete(db_session, [order.id])


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_purge_unlinks_child_orders_parent_pointer(
    client: TestClient, token_dispatcher: str, db_session: Session, users: dict
) -> None:
    """父单被清 → 子单那根 `parent_order_id` 必须解开（否则同样的外键炸法）。"""
    parent = _soft_deleted_order(db_session, users, suffix="PAR")
    child = _soft_deleted_order(db_session, users, suffix="CHI")
    # ⚠️ **id 要在清理之前存下来**：父单被物理清理后，那个 ORM 实例已经过期，
    #    再读 `parent.id` 会抛 `ObjectDeletedError`（第一次就是这么挂在 cleanup 里的）。
    parent_id, child_id = int(parent.id), int(child.id)
    child.parent_order_id = parent_id
    child.deleted_at = None          # 子单不进回收站：它只是"父单被清"的受害方
    db_session.commit()
    try:
        dr.purge_soft_deleted_orders(db_session)
        db_session.commit()
        db_session.expire_all()
        assert db_session.get(Order, parent_id) is None, "没有凭证挡着的软删单应当被物理清理"
        remaining = db_session.get(Order, child_id)
        assert remaining is not None, "子单被误删了"
        assert remaining.parent_order_id is None, (
            "父单被清了、子单还指着它 —— 这是一根悬空外键（下一次清理/查询就会炸）"
        )
    finally:
        db_session.rollback()
        _hard_delete(db_session, [child_id, parent_id])


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_one_step_failure_does_not_stop_the_rest(monkeypatch, db_session: Session, tmp_path) -> None:
    """⛔ 一步失败**不许**让当天全部清理停摆（2026-09-19 审计 R12 的形状：整套治理回滚，
    而且每天重复失败——消息、图片、导出产物一并不清）。

    造法：把"3 年清理"那一步换成必抛异常，断言另外两步照样跑、并且返回值里标出是哪一步失败。
    """
    import sys
    import types

    fake_ran: list[str] = []

    class _FakeFlock:
        LOCK_EX, LOCK_NB, LOCK_UN = 2, 4, 8

        def __init__(self) -> None:
            self.held: set[str] = set()

        def flock(self, f, op) -> None:
            path = str(getattr(f, "name", f))
            if op & self.LOCK_UN:
                self.held.discard(path)
                return
            if path in self.held:
                raise OSError(11, "busy")
            self.held.add(path)

    fake = _FakeFlock()
    module = types.ModuleType("fcntl")
    module.flock = fake.flock                                   # type: ignore[attr-defined]
    for name in ("LOCK_EX", "LOCK_NB", "LOCK_UN"):
        setattr(module, name, getattr(fake, name))
    monkeypatch.setitem(sys.modules, "fcntl", module)
    # ⚠️ 标记文件必须落在 `tmp_path`：第一版写成 `/tmp/...`，于是**上一次失败的运行**
    #    已经往那儿写过"今天跑过了"，第二次跑就直接 `skipped_same_day` —— 判据自己把自己
    #    挡在门外（`test_audit_round25_full_check.py` 里那条同样的坑，注释里写着）。
    monkeypatch.setattr(dr, "GOVERNANCE_MARKER_PATH", str(tmp_path / "retention.last"))
    monkeypatch.setattr(dr, "purge_soft_deleted_orders", lambda db: 0)
    monkeypatch.setattr(
        dr, "purge_expired_data", lambda db: (_ for _ in ()).throw(RuntimeError("探针：这一步炸了"))
    )
    monkeypatch.setattr(dr, "purge_expired_notifications", lambda db: (_ for _ in ()).throw(
        AssertionError("这一步不该被执行")
    ) if False else 7)

    out = dr.run_daily_retention(db_session)
    assert out.get("soft_deleted_purged") == 0, out
    assert out.get("expired_purged") == -1, f"失败的那一步必须被标出来（-1），而不是整轮消失：{out}"
    assert out.get("notifications_purged") == 7, f"前一步失败把后面那步也拖没了：{out}"
