"""商品成本价的**生效区间**（用户 2026-09-19 要求）。

## 用户原话

> 「那个成本价去做一个保留…这个保留是跟着他的账本走的。假如他的账本是一直保留着，
>   那他这个成本价就一直保留着。如果成本价发生了变化，就直接变化成本价就可以了，
>   这样子我们就好溯源。而且我们保留的时候不仅保留成本价，还保留这个成本价存在的时间，
>   比如说他是从什么时候开始变的、从什么时候结束的，精确到小时和分钟，
>   这样子的话，我们就能方便且精确地算出来在这段时间的毛利率是多少。」

## 这个文件守六件事

1. **三个改价入口全都写区间**：建商品 / 进货带价 / 编辑里改 ——
   少一个就会出现"价格变了、区间表没变"，而界面上完全看不出来；
2. **价没变就不写**（否则每次编辑商品都塞一段"没变"的记录，"这个价用了多久"就查不出来）；
3. **区间首尾相接**（旧行 `effective_to` == 新行 `effective_from`）：不留缝、不重叠；
4. **同一时刻连改两次也只命中一个价**（零长度区间不会被选中）；
5. 权限：**货主拿不到**（成本是内部数，商品详情里的 `cost_price` 对他们都是 null）；
6. 保留期跟着账本：3 年前的区间清掉，但**当前生效的那一段不许被清**。
"""

from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.business_time import utc_now_naive
from app.models import ProductCostHistory
from app.services.cost_history import SOURCE_CREATE, SOURCE_MANUAL, SOURCE_PURCHASE, cost_at
from tests.conftest import auth_headers


def _uniq(prefix: str) -> str:
    return f"{prefix}-{random.randint(1000, 9999)}"


def _mk_product(client: TestClient, h: dict[str, str], cost: str = "0") -> dict:
    r = client.post(
        "/api/v1/products",
        json={
            "name": _uniq("成本时间轴探针"),
            "default_unit_price": "20",
            "cost_price": cost,
            "unit": "件",
            "stock": 0,
            "category": _uniq("成本时间轴分类"),
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _history(client: TestClient, h: dict[str, str], pid: int) -> list[dict]:
    """成本价时间轴。

    ⚠️ 商品是**查询参数**不是路径参数（`/products/cost-history?product_id=`）：
    带 `{}` 的端点对 AI 是死的（模型看不到内部编号），而这个能力用户要求 AI 也要有。
    """
    r = client.get("/api/v1/products/cost-history", params={"product_id": pid}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _rows(db: Session, pid: int) -> list[ProductCostHistory]:
    return list(
        db.query(ProductCostHistory)
        .filter(ProductCostHistory.product_id == pid)
        .order_by(ProductCostHistory.effective_from, ProductCostHistory.id)
        .all()
    )


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_建商品就开出第一段区间(client: TestClient, token_dispatcher: str, db_session: Session) -> None:
    """建的时候填的那个价就是时间轴的起点 —— 不能"从第一次改价才开始记"。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h, cost="8.5")

    rows = _rows(db_session, p["id"])
    assert len(rows) == 1, f"建商品应当开出恰好一段区间，实际 {len(rows)} 段"
    assert rows[0].source == SOURCE_CREATE
    assert Decimal(rows[0].cost_price) == Decimal("8.5000")
    assert rows[0].effective_to is None, "第一段应当是「仍在生效」"
    assert rows[0].effective_from is not None


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_进货带价会收尾旧区间并开出新区间(
    client: TestClient, token_dispatcher: str, db_session: Session
) -> None:
    """进货改成本价的**全部意义**：查得到"这个价从哪一刻到哪一刻"。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h, cost="8")

    r = client.post(
        "/api/v1/inventory/movements",
        json={"product_id": p["id"], "change": 10, "note": "第一次进货", "unit_cost": "9.5"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    movement_id = r.json()["id"]

    rows = _rows(db_session, p["id"])
    assert len(rows) == 2, f"改一次价应当有 2 段（旧的收尾 + 新的开始），实际 {len(rows)}"
    old, new = rows
    assert old.effective_to is not None, "旧区间没收尾 —— 时间轴上会同时有两段「生效中」"
    assert new.effective_to is None
    assert old.effective_to == new.effective_from, "区间首尾必须相接：留缝的时段会查不到价"
    assert Decimal(new.cost_price) == Decimal("9.5000")
    assert new.source == SOURCE_PURCHASE
    # 溯源：这条价是哪批货带进来的
    assert new.movement_id == movement_id, "进货带进来的价没连回那条库存流水，溯源就断在这里"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_进货不带价不写区间(client: TestClient, token_dispatcher: str, db_session: Session) -> None:
    """⛔ 价没变就不写。否则盘点补录几次就塞进一堆零长度区间，"这个价用了多久"查不出来。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h, cost="7")
    for _ in range(3):
        client.post(
            "/api/v1/inventory/movements",
            json={"product_id": p["id"], "change": 1, "note": "盘点"},
            headers=h,
        )
    assert len(_rows(db_session, p["id"])) == 1, "没改价却写了区间"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_编辑里改成本价也走时间轴(client: TestClient, token_dispatcher: str, db_session: Session) -> None:
    """第三个入口（PATCH）也必须写 —— 只接进货那一处是最容易漏的。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h, cost="5")

    r = client.patch(f"/api/v1/products/{p['id']}", json={"cost_price": "6.25"}, headers=h)
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["cost_price"]) == Decimal("6.2500")

    rows = _rows(db_session, p["id"])
    assert len(rows) == 2
    assert rows[1].source == SOURCE_MANUAL
    assert Decimal(rows[1].cost_price) == Decimal("6.2500")

    # 价没变再 PATCH 一次：不写第三段
    client.patch(f"/api/v1/products/{p['id']}", json={"cost_price": "6.25"}, headers=h)
    assert len(_rows(db_session, p["id"])) == 2, "价没变却又开了一段"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_同一时刻连改两次_按时刻取价仍唯一(
    client: TestClient, token_dispatcher: str, db_session: Session
) -> None:
    """零长度区间（from == to）必须**不会被任何时刻选中** —— 否则"这一刻多少钱"有两个答案。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h, cost="1")
    client.patch(f"/api/v1/products/{p['id']}", json={"cost_price": "2"}, headers=h)
    client.patch(f"/api/v1/products/{p['id']}", json={"cost_price": "3"}, headers=h)

    db_session.expire_all()
    now = utc_now_naive()
    assert Decimal(cost_at(db_session, p["id"], now) or 0) == Decimal("3.0000")
    # 很久以前（回填起点之前）查不到 → None，不编一个数
    assert cost_at(db_session, p["id"], now - timedelta(days=3650)) is None


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_区间列表新的在前_且不带内部主键(client: TestClient, token_dispatcher: str) -> None:
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h, cost="4")
    client.patch(f"/api/v1/products/{p['id']}", json={"cost_price": "5"}, headers=h)

    rows = _history(client, h, p["id"])
    assert len(rows) == 2
    assert Decimal(rows[0]["cost_price"]) == Decimal("5.0000"), "最新的那段应当排在最前"
    assert rows[0]["effective_to"] is None
    assert rows[1]["effective_to"] is not None
    # 出参里不许有 operator_id（内部主键不进界面，见 schema 注释）
    assert "operator_id" not in rows[0]


@pytest.mark.dispatcher
@pytest.mark.shipper
@pytest.mark.fast
@pytest.mark.regression
def test_货主查不到成本价历史(
    client: TestClient, token_dispatcher: str, token_shipper: str
) -> None:
    """⛔ 成本是内部数：货主连商品详情里的 `cost_price` 都是 null，历史当然也不能给。"""
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h, cost="9")
    r = client.get(
        "/api/v1/products/cost-history",
        params={"product_id": p["id"]},
        headers=auth_headers(token_shipper),
    )
    assert r.status_code == 403, f"货主拿到了成本价历史！{r.status_code} {r.text[:120]}"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_保留期跟着账本_当前生效的那一段不许被清(
    client: TestClient, token_dispatcher: str, db_session: Session
) -> None:
    """用户：「这个保留是跟着他的账本走的」→ 与 ledgers 同一档 3 年。

    ⚠️ 判据必须用 `effective_to`（这段价**什么时候结束**），不是 `effective_from`：
       用后者会把"三年前定的价、现在还在用"那一行删掉 —— 而它正是当前生效价，
       删了之后这个商品的成本时间轴断在最需要它的地方。
    """
    from app.services.data_retention import DATA_RETENTION_DAYS, purge_expired_data

    h = auth_headers(token_dispatcher)
    p = _mk_product(client, h, cost="3")
    db_session.expire_all()
    live = _rows(db_session, p["id"])[0]

    # 手工造两段历史：一段三年前就结束了（该清），一段三年前开始但**至今仍在生效**（该留）
    long_ago = utc_now_naive() - timedelta(days=DATA_RETENTION_DAYS + 10)
    db_session.add(
        ProductCostHistory(
            product_id=p["id"], cost_price=Decimal("1.5"),
            effective_from=long_ago - timedelta(days=30), effective_to=long_ago,
            source=SOURCE_MANUAL,
        )
    )
    live.effective_from = long_ago
    db_session.commit()

    purge_expired_data(db_session)
    db_session.expire_all()
    left = _rows(db_session, p["id"])
    assert len(left) == 1, f"应当只剩「当前生效」那一段，实际剩 {len(left)} 段"
    assert left[0].effective_to is None, "清错了：把当前生效价删了，这个商品的成本时间轴就断了"
