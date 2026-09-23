"""「商品毛利」在**两个端点**里必须是同一个数（2026-09-23 第 17 轮并行渗透抓到）。

## 抓到的是什么（高）

`GET /reports/turnover`（营业纵览）与 `GET /reports/products`（商品经营）各自有一段**按订单行**的循环：

| | 营业纵览（对的那一侧） | 商品经营（原来错的那一侧） |
| --- | --- | --- |
| 数量 | `quantity − returned_quantity` | `quantity`（**毛额**） |
| 收入 | `line_receivable`（行金额 − 退掉那部分） | `line_total`（**全额**） |
| 成本 | `cost × 净件数` | `cost × quantity`（**全额**） |
| 整行退完 | `continue`（不进毛利） | 照记 |

于是同一个词「商品毛利(仅算得出成本的行)」在同一份导出里出现两次且不同值
（本机实测同窗口 **4,896.60 vs 4,911.10**、全部窗口 **19.90** 的差，可逐行复算：
行850 +6.10、行851 +5.60、行908 +2.80、行29 +5.40），而按项目自己写下的理由
（turnover 注释：「退货的货回到库里了 → 这一行的成本不能照全额算」）**商品经营那一侧是错的**。

## 这份测试怎么钉

用**增量**比（测试库在同一次运行里是累积的，绝对值会被别的用例搅乱）：
先记一次基线，造一张两行的已送达单并给两行写上成本快照，
再**退掉其中一行的 2 件 + 整行退掉另一行**，然后：

1. 两个端点的 `cost_total / cost_covered_amount / cost_covered_lines / total_lines`**增量必须逐项相等**；
2. 而且增量是**净额那套数**（成本 = 单价成本 × 净件数、收入 = 行金额 − 退掉的部分），
   不是毛额 —— 只比"两边相等"会被"两边一起改成毛额"骗过去。

⚠️ 判据必须落在**两个端点之间**：`test_audit_round17_money.py` 只断言端点**内部**自洽
（`Σ covered_amount == 表头`），那种断言在两边一起算错时照样绿。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.models import Order, OrderProduct
from tests.conftest import auth_headers

#: 两行：A 10×10（成本 6/件）、B 4×25（成本 20/件）
LINE_A = {"product_name_snapshot": "毛利同源甲", "quantity": 10, "unit_price": "10"}
LINE_B = {"product_name_snapshot": "毛利同源乙", "quantity": 4, "unit_price": "25"}


def _today() -> str:
    from app.core.business_time import business_today

    return business_today().isoformat()


def _agg(client: TestClient, path: str, tok: str) -> dict[str, Decimal | int]:
    """两个端点里那四个字段（金额是字符串，统一转 Decimal 再比）。"""
    r = client.get(f"/api/v1{path}?mode=day&date={_today()}", headers=auth_headers(tok))
    assert r.status_code == 200, r.text
    d = r.json()
    return {
        "cost_total": Decimal(d["cost_total"]),
        "cost_covered_amount": Decimal(d["cost_covered_amount"]),
        "cost_covered_lines": int(d["cost_covered_lines"]),
        "total_lines": int(d["total_lines"]),
    }


def _deliver(client: TestClient, token_shipper: str, token_dispatcher: str, token_driver: str,
             driver_id: int) -> tuple[int, list[int]]:
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={"lines": [LINE_A, LINE_B], "delivery_description": "毛利同源探针"},
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": driver_id, "freight_fee": "20.00"},
    ).status_code == 200
    assert client.post(
        f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_driver)
    ).status_code == 200
    done = client.post(
        f"/api/v1/orders/{oid}/complete",
        headers=auth_headers(token_driver),
        json={"delivery_photo_urls": ["/static/uploads/delivery/gp.jpg"], "payment": "arrears"},
    )
    assert done.status_code == 200, done.text
    return oid, []


@pytest.mark.dispatcher
@pytest.mark.integration
def test_商品毛利两个端点必须逐项相等_且按净额(
    client: TestClient, db_session, token_shipper: str, token_dispatcher: str,
    token_driver: str
) -> None:
    from tests.test_driver_billing_api import _mk_driver  # 复用"建司机并登录"的助手

    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    oid, _ = _deliver(client, token_shipper, token_dispatcher, driver_tok, driver_id)

    # 给两行写上成本快照（`cost_basis` 在"没有带价入库流水"时退回快照那一档）
    db_session.expire_all()
    lines = list(
        db_session.scalars(
            select(OrderProduct).where(OrderProduct.order_id == oid).order_by(OrderProduct.id)
        ).all()
    )
    assert len(lines) == 2, lines
    lines[0].cost_price_snapshot = Decimal("6")
    lines[1].cost_price_snapshot = Decimal("20")
    db_session.commit()
    a_id, b_id = int(lines[0].id), int(lines[1].id)

    base_t = _agg(client, "/reports/turnover", token_dispatcher)
    base_p = _agg(client, "/reports/products", token_dispatcher)

    # 退：甲 2 件（部分）+ 乙整行 4 件（整行退完）
    r = client.post(
        f"/api/v1/orders/{oid}/return",
        headers=auth_headers(token_dispatcher),
        json={"items": [{"order_product_id": a_id, "quantity": 2},
                        {"order_product_id": b_id, "quantity": 4}]},
    )
    assert r.status_code in (200, 201), r.text

    now_t = _agg(client, "/reports/turnover", token_dispatcher)
    now_p = _agg(client, "/reports/products", token_dispatcher)

    dt = {k: now_t[k] - base_t[k] for k in base_t}
    dp = {k: now_p[k] - base_p[k] for k in base_p}

    # ① 两个端点逐项相等（这一条就是缺陷本身：原来差 ¥19.90 那一类）
    for k in dt:
        assert dt[k] == dp[k], (
            f"{k}：营业纵览增量 {dt[k]} vs 商品经营增量 {dp[k]} —— "
            "同一个词两个数（退货行的口径必须同源）"
        )

    # ② 而且是**净额**那一套数。基线（送达时）→ 退货后：
    #    送达：甲 10 件 × 成本 6 = 60、乙 4 件 × 成本 20 = 80 → 成本 140、收入 200、2 行
    #    退货：甲 10−2=8 件 → 成本 48、收入 80；乙整行退完且无货损 → **整行不进毛利**
    #    ⇒ 增量 = 48 − 140 = −92、80 − 200 = −120、参与行数 −1、行数 −1
    assert dt["cost_total"] == Decimal("-92"), dt
    assert dt["cost_covered_amount"] == Decimal("-120"), dt
    assert dt["cost_covered_lines"] == -1, dt
    assert dt["total_lines"] == -1, dt
