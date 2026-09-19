"""异常"登记 → 解决 → 再登记"的状态必须自洽（2026-09-19 审计的缺陷 R7）。

`exception_resolved_at` 原来只在"解决"那条路径写，`PATCH /orders/{id}/exception` 从来不清它。
于是用户重新登记一条异常时：接口 200、提示"异常已登记"，但那一行**带着上一次的解决时间** ——
报表的「要处理」按 resolved 过滤 → 它永远不出现在待处理列表里；
自动异常判定（`stats_service`）看到 resolved_at 非空也不再判它。
典型的"操作成功但事情没做"，而界面上一切正常。
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import Order
from tests.conftest import auth_headers


def _mk_order(client, token_dispatcher, shipper_id: int) -> int:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [{"product_name_snapshot": "异常探针", "quantity": 1, "unit_price": "10"}],
            "address_detail": "异常探针地址",
        },
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_reregistering_exception_clears_previous_resolution(client, db_session, users, token_dispatcher):
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, token_dispatcher, users["shipper"].id)

    # 先登记并"解决"（解决时间直接写库，模拟报表页的解决动作）
    assert client.patch(
        f"/api/v1/orders/{oid}/exception",
        json={"is_exception": True, "exception_reason": "客户催单"},
        headers=h,
    ).status_code == 200
    db_session.expire_all()
    o = db_session.get(Order, oid)
    o.exception_resolved_at = datetime.now(timezone.utc)
    o.exception_resolution = "已电话沟通"
    db_session.commit()

    # 再登记一次 → 旧的解决痕迹必须被清掉，它才会重新出现在「要处理」里
    r = client.patch(
        f"/api/v1/orders/{oid}/exception",
        json={"is_exception": True, "exception_reason": "又出问题了"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    fresh = db_session.get(Order, oid)
    assert fresh.is_exception is True
    assert fresh.exception_resolved_at is None, "重新登记异常必须清掉上一次的解决时间"
    assert (fresh.exception_resolution or "") == "", "上一次的解决说明也不该留着"


def test_resolving_keeps_marker(client, db_session, users, token_dispatcher):
    """对照：登记（不清）与解除（is_exception=false）都要能用。"""
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, token_dispatcher, users["shipper"].id)
    assert client.patch(
        f"/api/v1/orders/{oid}/exception",
        json={"is_exception": True, "exception_reason": "探针"},
        headers=h,
    ).status_code == 200
    assert client.patch(
        f"/api/v1/orders/{oid}/exception",
        json={"is_exception": False, "exception_resolution": "已处理"},
        headers=h,
    ).status_code == 200
    db_session.expire_all()
    assert db_session.get(Order, oid).is_exception is False
