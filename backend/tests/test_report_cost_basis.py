"""毛利的成本口径 = **入库流水的加权平均进货价**（2026-09-19 用户要求）。

## 用户的原话

> 「他那个毛利率会做一个计算的…他不是有那个入库记录吗？不能这么算啊，这么算的话，
>   毛利率会偏低啊。所以要分开来，算毛利率的话，我们可以算一个平均的成本，
>   也就是说在单位时间内的平均成本，比如在这 1 年之内或者一个月之内的」

改之前的口径：毛利成本 = 订单行的 `cost_price_snapshot` = **下单那一刻的最新进货价**。
于是"进货价涨了、卖的却是之前进的货"那些单，成本被按**新高价**算 → 毛利偏低。

## 这个文件守四件事

1. **进货价真的落在流水上**（`inventory_movements.unit_cost`）—— 不落库就什么都算不了；
2. 三级口径各自的取舍：本期均价 → 累计均价 → 下单快照（老数据兜底，**不许归零**）；
3. 出库与订单自动流水**不参与**进货均价（它们没有进价，也不该拉低均价）；
4. **端到端**：报表的毛利真的会随"补录进货价"而变，且不再等于旧快照口径那个偏低的值。
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.business_time import business_day_start_utc, business_today
from app.models import InventoryMovement
from app.services.cost_basis import CUMULATIVE, PERIOD, SNAPSHOT, CostBasis
from tests.conftest import auth_headers


def _uniq(prefix: str) -> str:
    return f"{prefix}-{random.randint(1000, 9999)}"


def _mk_product(client: TestClient, h: dict[str, str], *, cost: str = "0", price: str = "40") -> dict:
    r = client.post(
        "/api/v1/products",
        json={
            "name": _uniq("成本口径探针"),
            "default_unit_price": price,
            "cost_price": cost,
            "unit": "件",
            "stock": 0,
            "category": _uniq("成本口径分类"),
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _inbound_raw(
    db: Session, product_id: int, operator_id: int, qty: int, cost: str | None, day: date
) -> None:
    """直接写一条入库流水（用来构造"本期之前"的历史，接口造不出过去的时间）。"""
    db.add(
        InventoryMovement(
            product_id=product_id,
            change=qty,
            note="",
            operator_id=operator_id,
            source="MANUAL",
            status="COMMITTED",
            unit_cost=Decimal(cost) if cost is not None else None,
            created_at=business_day_start_utc(day) + timedelta(hours=6),
        )
    )
    db.commit()


def _inbound(
    client: TestClient, h: dict[str, str], product_id: int, qty: int, cost: str
) -> None:
    """走**真实接口**入库（这才验得到"进货价真的落库了"）。"""
    r = client.post(
        "/api/v1/inventory/movements",
        json={"product_id": product_id, "change": qty, "note": "测试进货", "unit_cost": cost},
        headers=h,
    )
    assert r.status_code == 201, r.text


def _turnover(client: TestClient, tok: str) -> dict:
    r = client.get(f"/api/v1/reports/turnover?mode=day&date={business_today().isoformat()}", headers=auth_headers(tok))
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("cost_total", "cost_covered_amount", "total_amount"):
        d[k] = Decimal(d[k])
    return d


# ---------------------------------------------------------------- ① 进货价必须落库


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_入库的进货价真的落在流水上(client: TestClient, token_dispatcher: str) -> None:
    """⛔ 这条是本轮的地基：以前进货价只被拿去改 `products.cost_price`，流水里什么都没有。

    "流水上没有这一列"的后果不是少一个字段，而是**"按入库记录算平均成本"根本无从下手**
    —— 毛利只能用"最新一次进货价"，进货价一涨、旧库存的毛利就偏低。
    """
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h)
    _inbound(client, h, p["id"], 30, "6.4")

    r = client.get("/api/v1/inventory/movements", params={"product_id": p["id"]}, headers=h)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert rows, "刚入的库在流水里查不到"
    assert rows[0].get("unit_cost") is not None, (
        "进货价没落库 —— 毛利就永远只能退回『最新一次进货价』那个不准的口径"
    )
    assert Decimal(str(rows[0]["unit_cost"])) == Decimal("6.4")


# ---------------------------------------------------------------- ② 三级口径


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_本期均价按数量加权(client: TestClient, token_dispatcher: str, db_session: Session, users: dict) -> None:
    """① 本期进过货 → 用本期进货的加权平均（用户要的"单位时间内的平均成本"）。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h)
    today = business_today()
    _inbound_raw(db_session, p["id"], users["dispatcher"].id, 100, "10", today)
    _inbound_raw(db_session, p["id"], users["dispatcher"].id, 100, "20", today)

    cost, src = CostBasis(db_session, today, today).of(p["id"], Decimal("999"))
    assert src == PERIOD
    # ⛔ 不是算术平均（10+20)/2=15 恰好相同，所以这组数证明不了加权 —— 见下一个用例
    assert cost == Decimal("15.0000")


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_均价是加权不是算术平均(client: TestClient, token_dispatcher: str, db_session: Session, users: dict) -> None:
    """数量不同的时候，加权平均 ≠ 算术平均（3 件 @10 与 4 件 @20 → 15.7143，不是 15）。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h)
    today = business_today()
    _inbound_raw(db_session, p["id"], users["dispatcher"].id, 3, "10", today)
    _inbound_raw(db_session, p["id"], users["dispatcher"].id, 4, "20", today)

    cost, src = CostBasis(db_session, today, today).of(p["id"], Decimal("0"))
    assert src == PERIOD
    assert cost == Decimal("15.7143"), f"110/7 应当量化到四位小数 15.7143，实际 {cost}"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_本期没进货就用累计到期末的均价(client: TestClient, token_dispatcher: str, db_session: Session, users: dict) -> None:
    """② 这个月没进货（卖的是以前的库存）→ 退回累计均价，而不是退回"最新一次进货价"。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h)
    today = business_today()
    _inbound_raw(db_session, p["id"], users["dispatcher"].id, 50, "8", today - timedelta(days=1))

    cost, src = CostBasis(db_session, today, today).of(p["id"], Decimal("999"))
    assert src == CUMULATIVE
    assert cost == Decimal("8.0000")


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_从没记过进货价就退回下单快照而不是归零(
    client: TestClient, token_dispatcher: str, db_session: Session
) -> None:
    """③ 兜底级。**这条不是可有可无的**：`unit_cost` 是 2026-09-19 才加的列，
    老数据一条都没有 —— 少了这一级，所有历史报表的毛利覆盖率会一夜之间变成 0。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h)
    today = business_today()

    cost, src = CostBasis(db_session, today, today).of(p["id"], Decimal("7.5"))
    assert src == SNAPSHOT
    assert cost == Decimal("7.5")

    # 连快照都没有（老单没成本）→ 返回 0，行为与改造前一致（这一行不进毛利）
    cost, src = CostBasis(db_session, today, today).of(p["id"], None)
    assert src == SNAPSHOT
    assert cost == Decimal("0")

    # 商品行没有 product_id（商品被删/老数据）→ 同样退回快照，不许当成均价 0
    cost, src = CostBasis(db_session, today, today).of(None, Decimal("3"))
    assert src == SNAPSHOT
    assert cost == Decimal("3")


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_出库与订单自动流水不参与进货均价(
    client: TestClient, token_dispatcher: str, db_session: Session, users: dict
) -> None:
    """出库、以及订单的预占/实扣/回冲流水都不该被算成"进货"。

    ⛔ 不排掉的话，一笔 90 件的出库就能把均价从 10 拉到 1 —— 而且是**静默**的。
    """
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h)
    today = business_today()
    _inbound_raw(db_session, p["id"], users["dispatcher"].id, 100, "10", today)
    # 出库（负数、无价）
    _inbound_raw(db_session, p["id"], users["dispatcher"].id, -90, None, today)
    # 订单自动流水：预占（负数、source=ORDER、无价）
    db_session.add(
        InventoryMovement(
            product_id=p["id"], change=-5, note="", operator_id=users["dispatcher"].id,
            source="ORDER", status="RESERVED", unit_cost=None,
            created_at=business_day_start_utc(today) + timedelta(hours=7),
        )
    )
    db_session.commit()

    cost, src = CostBasis(db_session, today, today).of(p["id"], Decimal("0"))
    assert src == PERIOD
    assert cost == Decimal("10.0000"), "出库/订单流水被算进了进货均价"


# ---------------------------------------------------------------- ③ 端到端：报表毛利


def _deliver_line(
    client: TestClient, token_shipper: str, token_dispatcher: str, token_driver: str,
    driver_id: int, product: dict, *, qty: int, unit_price: str,
) -> int:
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "lines": [{
                "product_id": product["id"],
                "product_name_snapshot": product["name"],
                "quantity": qty,
                "unit_price": unit_price,
                "line_total": str(Decimal(unit_price) * qty),
            }],
            "delivery_description": "成本口径探针",
        },
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        headers=auth_headers(token_dispatcher),
        json={"driver_id": driver_id, "freight_fee": "30.00", "collect_cash": True},
    ).status_code == 200
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(token_driver)).status_code == 200
    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        headers=auth_headers(token_driver),
        json={"delivery_photo_urls": ["/static/uploads/delivery/cost.jpg"], "payment": "cash"},
    )
    assert r.status_code == 200, r.text
    return oid


@pytest.mark.dispatcher
@pytest.mark.driver
@pytest.mark.integration
@pytest.mark.regression
def test_报表毛利用入库均价而不是下单快照(
    client: TestClient, token_shipper: str, token_dispatcher: str, token_driver: str
) -> None:
    """**这条用例就是用户那句话**：「这么算的话，毛利率会偏低」。

    构造的是他描述的场景（有 300 件旧库存 @10，中途进了 100 件 @20）：

    | | 第一单 | 第二单 | 报表口径的合计成本 |
    |---|---|---|---|
    | 下单时的商品成本价（旧口径的快照） | 10 | **20** | 10×10 + 20×10 = **300** ← 偏低 |
    | 本期入库加权平均（新口径） | 12.5 | 12.5 | 12.5×20 = **250** ← 正确 |

    第二单卖的是 300 件 @10 那批旧库存，却因为中途进了 100 件 @20 而被按 20 算成本
    —— 那就是"毛利率会偏低"。
    """
    from tests.test_driver_billing_api import _mk_driver

    h = auth_headers(token_dispatcher)
    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    p = _mk_product(client, h, cost="0", price="40")
    base = _turnover(client, token_dispatcher)

    # ① 进 300 件 @10（走真实接口：流水记价 + 商品成本价 → 10）
    _inbound(client, h, p["id"], 300, "10")
    # ② 第一单：下单时成本价 10 → 快照 10
    _deliver_line(client, token_shipper, token_dispatcher, driver_tok, driver_id, p, qty=10, unit_price="40")
    # ③ 再进 100 件 @20 → 商品成本价 → 20
    _inbound(client, h, p["id"], 100, "20")
    # ④ 第二单：下单时成本价 20 → 快照 20（**这一单卖的是 ① 那批旧库存**）
    _deliver_line(client, token_shipper, token_dispatcher, driver_tok, driver_id, p, qty=10, unit_price="40")

    after = _turnover(client, token_dispatcher)
    assert after["cost_covered_amount"] - base["cost_covered_amount"] == Decimal("800"), "参与毛利的收入应当是 20 件 × 40"
    d_cost = after["cost_total"] - base["cost_total"]
    assert d_cost == Decimal("250.0000"), (
        f"成本应当是 20 件 × 本期均价 12.5 = 250，实际 {d_cost}；"
        f"若等于 300 说明又退回『下单快照』那个偏低的口径了"
    )
    # 两行都真的走了"入库均价"这一级（界面要按它说明口径）
    assert after["cost_avg_lines"] - base["cost_avg_lines"] == 2
    assert after["cost_snapshot_lines"] == base["cost_snapshot_lines"]


@pytest.mark.dispatcher
@pytest.mark.driver
@pytest.mark.integration
@pytest.mark.regression
def test_补录进货价之前毛利按快照_补录之后同一张单的成本会变(
    client: TestClient, token_shipper: str, token_dispatcher: str, token_driver: str
) -> None:
    """过渡期行为：**已经送达的单在补录进货价之后，报表里的成本会跟着变**。

    这是有意的：`unit_cost` 之前根本没有这一列，老数据的进货价只能靠补录找回来。
    不这样的话，"上个季度的毛利"就永远是那个偏低的快照数，且**没有任何办法修**。
    代价是同一张单的毛利会随补录而变 —— 所以界面必须把口径（多少行按均价）说出来。
    """
    from tests.test_driver_billing_api import _mk_driver

    h = auth_headers(token_dispatcher)
    driver_id, driver_tok = _mk_driver(client, token_dispatcher, vehicle="trailer")
    p = _mk_product(client, h, cost="10", price="40")
    base = _turnover(client, token_dispatcher)

    _deliver_line(client, token_shipper, token_dispatcher, driver_tok, driver_id, p, qty=10, unit_price="40")
    before = _turnover(client, token_dispatcher)
    assert before["cost_total"] - base["cost_total"] == Decimal("100.0000"), "还没有进货记录，应当按下单快照 10 算"
    assert before["cost_snapshot_lines"] - base["cost_snapshot_lines"] == 1

    _inbound(client, h, p["id"], 100, "12")  # 补录：这批货其实 12 块
    after = _turnover(client, token_dispatcher)
    assert after["cost_total"] - base["cost_total"] == Decimal("120.0000"), "补录进货价之后应当改按均价 12 算"
    assert after["cost_avg_lines"] - base["cost_avg_lines"] == 1
