"""司机账单页与结算页必须**同一批数**（2026-09-24 第 25 轮；第 24 轮 08 区 D2 实测）。

## 缺陷长什么样
同一个月份、同一名司机，三个页面三个数（本机实测 司机 3 / 2026-09）：

| 页面 | 数字 | 它自己的判据 |
|---|---|---|
| `/driver-bills`（账单驱动） | 9 笔 **¥198** | 只看 `driver_bills`，**一个订单级过滤都没有** |
| 结算单能结的（`create_settlement`） | 6 笔 **¥132** | 外加「订单未软删」 |
| `/freight-settlement`（订单驱动） | 4 单 **¥88** | 外加 `status=DELIVERED` |

第一行与第二行的差**正好是"订单已被软删"的那几笔**，而结算侧那句注释写着
「口径统一到**页面看得见的单才结得掉**」—— 账单页当时没跟上，于是：
派单员按 ¥198 跟司机对账、点进结算只能结 ¥132，**两边都不报错**。

修法：`/driver-bills` 缺省与结算侧**同一条判据**（`or_(order_id is None, Order.deleted_at is None)`），
`include_deleted=true` 仍可查（留痕，不删行）。

⚠️ 第三行与第二行的差是**另一件事**（整单退货的单还算不算司机那笔应付）——**产品决策**，
本文件不替它做主，只在声明页挂着。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers


def _mk_order(client: TestClient, token_dispatcher: str, shipper_id: int) -> int:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [{"product_name_snapshot": "账单口径探针", "quantity": 1, "unit_price": "66"}],
            "address_detail": "账单口径探针",
            "delivery_description": "账单口径探针",
        },
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _mk_bill(db_session, driver_id: int, order_id: int, month: str, amount: str) -> int:
    """直接插一条 PIECE 账单（账单是送达那一刻生成的，这里只关心"列表怎么筛"）。"""
    from app.models import DriverBill

    bill = DriverBill(
        driver_id=driver_id,
        # ⚠️ 小写是**出参**的取值（`DriverBillOut` 校验 `piece`/`salary`、`open`/`settled`/`cancelled`）——
        #    库里同时存在 `.name`（大写）与 `.value`（小写）两种形状的坑见台账 D5-⑤，
        #    这里按出参要的那种写，免得探针自己被 500 挡住。
        bill_type="piece",
        order_id=order_id,
        month=month,
        amount=Decimal(amount),
        status="open",
        note=f"口径探针-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(bill)
    db_session.commit()
    return int(bill.id)


def _rows(client: TestClient, h: dict, driver_id: int, month: str, **extra) -> dict[int, str]:
    r = client.get(
        "/api/v1/driver-bills",
        params={"driver_id": driver_id, "month": month, **extra},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return {int(x["id"]): str(x["amount"]) for x in r.json()}


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_回收站里的单的账单默认不显示(
    client: TestClient, db_session, users: dict, token_dispatcher: str
) -> None:
    h = auth_headers(token_dispatcher)
    did = users["driver"].id
    month = "2026-09"

    live_oid = _mk_order(client, token_dispatcher, users["shipper"].id)
    gone_oid = _mk_order(client, token_dispatcher, users["shipper"].id)
    live_bill = _mk_bill(db_session, did, live_oid, month, "66.00")
    gone_bill = _mk_bill(db_session, did, gone_oid, month, "44.00")

    # 把第二张单丢进回收站（派单员可删任意状态）
    assert client.delete(f"/api/v1/orders/{gone_oid}", headers=h).status_code == 204

    shown = _rows(client, h, did, month)
    assert live_bill in shown, f"活单的账单必须在：{shown}"
    assert gone_bill not in shown, (
        "订单已进回收站的账单还在默认列表里 —— 结算侧早就不算它了"
        f"（`create_settlement` 的 `or_(order_id is None, Order.deleted_at is None)`）：{shown}"
    )

    # 留痕：显式要就看得到（不删行、不藏证据）
    with_gone = _rows(client, h, did, month, include_deleted="true")
    assert gone_bill in with_gone, f"`include_deleted=true` 应当把回收站里的账单也列出来：{with_gone}"
    assert live_bill in with_gone


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_孤儿账单_订单号为空_不受影响(
    client: TestClient, db_session, users: dict, token_dispatcher: str
) -> None:
    """`order_id` 为空的历史账单仍按原样显示 —— 别把"另一条已知问题"顺手改掉。"""
    h = auth_headers(token_dispatcher)
    did = users["driver"].id
    orphan = _mk_bill(db_session, did, None, "2026-10", "30.00")  # type: ignore[arg-type]
    shown = _rows(client, h, did, "2026-10")
    assert orphan in shown, f"孤儿账单不该被这次过滤误伤：{shown}"
