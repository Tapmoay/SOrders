"""订单行锁（`lock_order_row`）的两条路径都要有测试。

背景（2026-09-18 重放测试实测）：并发重复提交同一张单的"送达"时，**第二个请求拿到 500**：

    sqlalchemy.exc.InvalidRequestError: Could not refresh instance '<Order at 0x…>'
    at order_flow.py:95  db.refresh(order, with_for_update=True)

原因是第一版 `lock_order_row` 只写了一行 `db.refresh(...)`：另一个请求刚把这行改到终态、
或让本会话里那份实例失效时，`refresh` 取不回那一行就抛异常。
"锁不住"和"崩"是两件事——现在退化成"重新查一次并把新对象返回给调用方"。
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models import Order
from app.models.enums import OrderStatus
from app.services.order_flow import lock_order_row
from tests.conftest import auth_headers  # noqa: F401  (保持与其它测试一致的导入面)


def test_lock_order_row_returns_same_object_when_healthy(db_session, users) -> None:
    order = Order(
        order_no="LOCKTEST-1",
        status=OrderStatus.PENDING_DISPATCH,
        shipper_id=users["shipper"].id,
        order_date=date.today(),
    )
    db_session.add(order)
    db_session.commit()

    got = lock_order_row(db_session, order)
    assert got.id == order.id
    assert got.status == OrderStatus.PENDING_DISPATCH


def test_lock_order_row_recovers_from_stale_instance(db_session, users) -> None:
    """实例失效（并发下真实发生过）时：不能抛异常，要重新查一份回来。"""
    order = Order(
        order_no="LOCKTEST-2",
        status=OrderStatus.PENDING_DISPATCH,
        shipper_id=users["shipper"].id,
        order_date=date.today(),
    )
    db_session.add(order)
    db_session.commit()
    order_id = order.id

    # 把实例踢出会话 = 模拟"这份对象已经不能 refresh"（并发里就是这种状态）
    db_session.expunge(order)
    with pytest.raises(Exception):
        db_session.refresh(order)  # 先证明这条路确实会抛（不是空转）

    fresh = lock_order_row(db_session, order)
    assert fresh.id == order_id
    assert fresh is not order, "必须返回重新查到的那个对象，不能把失效的旧对象给调用方"
