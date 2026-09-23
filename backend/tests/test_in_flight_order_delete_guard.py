"""「异常」不是删除通行证：在途订单不许被货主删进回收站（2026-09-19 审计）。

## 原来的样子
货主删除的门槛是 `if 状态不在(已撤销, 已送达) and not is_exception: 拒绝` ——
那个 `and` 让"是异常单"成了**万能钥匙**，而括号里那句"进行中的订单请走撤销或撤回"
正是它要防的情况。真实链路（全是日常操作）：

1. 派单员给一张**已接单、司机在途**的单标了异常（客户催单，很正常）；
2. 货主打开那一单 → 界面出现「删除订单」（`OrderDetailScreen` 用同一套判据算 `canDelete`）；
3. 一删，单子进回收站 → **司机端列表里它直接消失**（`GET /orders` 对司机过滤 `deleted_at`）；
4. 司机拿着打不开的单跑车，到现场发现单子没了、也没法送达、拿不到运费。

修法：异常单必须**先撤销/撤回**（把状态变成终态）才能删；拒绝时把"这是进行中的单
（已标异常）"写进文案，用户才知道下一步该做什么。
"""
from __future__ import annotations

from tests.conftest import auth_headers


def _mk_order(client, h_dispatcher, shipper_id: int) -> int:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [{"product_name_snapshot": "在途删除探针", "quantity": 1, "unit_price": "10"}],
            "address_detail": "在途删除探针地址",
        },
        headers=h_dispatcher,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_shipper_cannot_delete_exception_order_that_is_still_in_flight(
    client, users, token_dispatcher, token_shipper, token_driver
):
    """已接单 + 已标异常 → 货主删除必须被拒（司机还在路上）。"""
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, h, users["shipper"].id)
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "20"},
        headers=h,
    ).status_code == 200
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_driver)).status_code == 200
    # 派单员标异常（客户催单）
    assert client.patch(
        f"/api/v1/orders/{oid}/exception",
        json={"is_exception": True, "exception_reason": "客户催单"},
        headers=h,
    ).status_code == 200

    r = client.delete(f"/api/v1/orders/{oid}", headers=auth_headers(token_shipper))
    assert r.status_code == 400, f"在途（已接单）订单不该被货主删掉：{r.status_code} {r.text}"
    assert "进行中" in r.json()["detail"]

    # 单子必须还在司机眼里（没进回收站）
    got = client.get(f"/api/v1/orders/{oid}", headers=auth_headers(token_driver))
    assert got.status_code == 200, "司机仍然要能看到这张单"


def test_shipper_can_still_delete_cancelled(client, users, token_dispatcher, token_shipper):
    """对照：终态（**已撤销**）仍然可以删 —— 别把正当需求一起堵死。"""
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, h, users["shipper"].id)
    assert client.post(f"/api/v1/orders/{oid}/cancel", headers=h).status_code == 200
    r = client.delete(f"/api/v1/orders/{oid}", headers=auth_headers(token_shipper))
    assert r.status_code in (200, 204), r.text


def test_shipper_cannot_delete_delivered(client, users, token_dispatcher, token_shipper, token_driver):
    """⛔ 货主**不许**删自己「已送达」的单（2026-09-24 第 20 轮 D12-F3）。

    用户 2026-09-21 的原话：「他**不能删他的订单**……**除非是那个已撤销的订单信息**」。
    这条规矩当时只落在 AI 侧（`SHIPPER_AI_DELETABLE = {CANCELLED}`）——同一个动作
    AI 拒绝、界面放行。而放行的代价是**钱**：`shipper_ledger` 的「我该付的」按
    `deleted_at is None` 聚合，货主删掉一张已送达的单 = 自己把那笔应收从账上抹掉，
    派单员按货主账催收永远看不到。

    ⚠️ 这条用例**原来钉的是相反的行为**（`test_shipper_can_still_delete_delivered_and_cancelled`
    同时断言"已送达也能删"）—— 判据钉错了侧，与用户在 2026-09-21 明确表达的规矩相反。
    """
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, h, users["shipper"].id)
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "20"},
        headers=h,
    ).status_code == 200
    assert client.post(
        f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_driver)
    ).status_code == 200
    assert client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe-del-guard.jpg"]},
        headers=auth_headers(token_driver),
    ).status_code == 200

    r = client.delete(f"/api/v1/orders/{oid}", headers=auth_headers(token_shipper))
    assert r.status_code == 400, (
        f"货主把自己「已送达」的单删掉了（HTTP {r.status_code}）—— 那笔应收会从货主账上消失，"
        "而用户 2026-09-21 明确说过「除非是那个已撤销的订单信息」"
    )
    assert "已撤销" in r.json()["detail"], r.json().get("detail")


def test_dispatcher_can_still_delete_any_state(client, users, token_dispatcher):
    """派单员按设计可以删任意状态（含待派单）—— 这条守卫只针对货主。"""
    h = auth_headers(token_dispatcher)
    oid = _mk_order(client, h, users["shipper"].id)
    r = client.delete(f"/api/v1/orders/{oid}", headers=h)
    assert r.status_code in (200, 204), r.text
