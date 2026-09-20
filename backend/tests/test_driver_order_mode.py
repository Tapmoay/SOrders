"""「这一单司机按不按单拿钱」：读侧与钱侧必须是同一个答案（2026-09-21 收口）。

### 抓到的形状
`orders.driver_billing_mode_snapshot` 是 v3.36 才加的列 —— **之前派出去的老单是 NULL**。
钱那一侧对 NULL 的口径早就定过（`driver_pay.has_per_order_pay`：有运费就算 PIECE；
`driver_bills` / `freight_settlement` 两处筛选是同形的
`snapshot == 'PIECE' OR snapshot IS NULL`）。

而四个**展示/门控**消费点各自抄了一份兜底 `快照 or resolve_billing_mode(车型, 计费)`——
那算的是司机**现在**的档案，于是同一张老单会出现
「账单按单给他结、界面上却看不见运费」（或反过来：免了拍照，却在按单付钱），
而且两边都不报错。现在兜底只有 `driver_pay.order_mode` 一处，这个文件钉住三件事：

1. 老单（快照 NULL）：钱说 PIECE，界面就必须看得见运费；
2. 新单听快照的（SALARY 的单运费不许露出来）—— 防止"统一"成永远可见；
3. 出参 `driver_billing_mode` 与门控判据同源（客户端也照它显示）。

4. **SQL 与 Python 同答案**：`per_order_pay_filter`（SQL）与 `order_mode`（Python）逐行对齐
   （取值矩阵：NULL / 空串 / 纯空白 / 大小写 / 带空格）—— 两处各写一遍时，空串的答案就相反。

⚠️ 在收口之前，`freight_visible` 这个字段**一个测试都没有**，所以它走散了很久没人知道。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Order, User
from app.models.enums import OrderStatus
from app.services.driver_pay import has_per_order_pay, order_mode
from app.services.order_response import apply_driver_view_gating
from tests.conftest import auth_headers


def _uniq(prefix: str) -> str:
    """测试库跨轮次保留（API 调用会 commit）—— 地址/单号必须每轮唯一。"""
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------- ① 模式怎么读


def test_快照说了算():
    assert order_mode(SimpleNamespace(driver_billing_mode_snapshot="PIECE", freight_fee="1")) == "PIECE"
    assert order_mode(SimpleNamespace(driver_billing_mode_snapshot="SALARY", freight_fee="1")) == "SALARY"


def test_大小写与空串的快照也认得():
    """历史数据里出现过小写；空串等同于没写（落到"没有快照"那一档）。"""
    assert order_mode(SimpleNamespace(driver_billing_mode_snapshot="piece", freight_fee=None)) == "PIECE"
    assert order_mode(SimpleNamespace(driver_billing_mode_snapshot="", freight_fee="500.00")) == "PIECE"
    assert order_mode(SimpleNamespace(driver_billing_mode_snapshot="", freight_fee=None)) == "SALARY"


def test_老单没有快照_有运费就算有():
    """与 `driver_bills` / `freight_settlement` 两处 SQL 同口径（那两处没法调 Python 函数）。"""
    assert order_mode(SimpleNamespace(driver_billing_mode_snapshot=None, freight_fee="500.00")) == "PIECE"
    assert order_mode(SimpleNamespace(driver_billing_mode_snapshot=None, freight_fee=Decimal("0"))) == "PIECE"
    assert order_mode(SimpleNamespace(driver_billing_mode_snapshot=None, freight_fee=None)) == "SALARY"


def test_谁有按单应付只由模式决定():
    """钱的开关（送达生不生成按单账单）与读侧同源：`has_per_order_pay` 就是 `order_mode == PIECE`。"""
    for snap, fee in ((None, "1"), ("PIECE", "1"), ("piece", None), ("SALARY", "1"), (None, None)):
        o = SimpleNamespace(driver_billing_mode_snapshot=snap, freight_fee=fee)
        assert has_per_order_pay(o) is (order_mode(o) == "PIECE")


# ---------------------------------------------------------------- ② 司机视角门控


def _gated(order) -> dict:
    data = {
        "order_products": [{"unit_price": "12.00", "line_total": "120.00"}],
        "freight_fee": "500.00",
    }
    apply_driver_view_gating(data, order)
    return data


def test_老单看得见运费_账单按单结界面就得显示():
    """快照为空的老单：钱按 PIECE 结（`has_per_order_pay` 为真），运费必须可见。"""
    o = SimpleNamespace(driver_billing_mode_snapshot=None, freight_fee=Decimal("500.00"))
    data = _gated(o)
    assert data["freight_visible"] is True
    assert data["freight_fee"] == "500.00", "账单里有这笔钱，司机却看不到运费"


def test_快照说工资制的单_运费必须看不见():
    """**不许**为了"统一"而把运费永远露出来：工资制司机就是不该看到运费。"""
    o = SimpleNamespace(driver_billing_mode_snapshot="SALARY", freight_fee=Decimal("500.00"))
    data = _gated(o)
    assert data["freight_visible"] is False
    assert data["freight_fee"] is None


def test_门控永远剥离货款():
    """两档模式下货款都只属于货主，司机不许看到（与模式无关的老约定）。"""
    for snap in (None, "PIECE", "SALARY"):
        data = _gated(SimpleNamespace(driver_billing_mode_snapshot=snap, freight_fee=Decimal("1")))
        assert data["order_products"][0]["unit_price"] is None
        assert data["order_products"][0]["line_total"] is None


# ---------------------------------------------------------------- ③ 真接口上的老单


def test_接口上老单的运费对司机可见(
    client: TestClient, db_session: Session, users: dict, token_driver: str
) -> None:
    """上面测的是函数；这一条测**接口真的这么答**（出参与门控同一处口径）。

    老单（快照 NULL）在详情接口里必须 `freight_visible=true` 且带上运费；
    快照一旦是 SALARY，同一张单就必须立刻藏起来。
    """
    d = users["driver"]
    o = Order(
        order_no=f"SO{uuid.uuid4().int % 10**18:018d}",
        status=OrderStatus.DISPATCHED,
        order_date=date(2026, 9, 21),
        address_detail=_uniq("老单地址"),
        driver_id=d.id,
        freight_fee=Decimal("88.00"),
        driver_billing_mode_snapshot=None,  # v3.36 之前派出去的老单
    )
    db_session.add(o)
    db_session.flush()

    r = client.get(f"/api/v1/orders/{o.id}", headers=auth_headers(token_driver))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["freight_visible"] is True, "账单按单给他结，界面却把运费藏起来"
    assert body["freight_fee"] is not None
    assert body["driver_billing_mode"] == "PIECE"

    o.driver_billing_mode_snapshot = "SALARY"
    db_session.flush()
    body2 = client.get(f"/api/v1/orders/{o.id}", headers=auth_headers(token_driver)).json()
    assert body2["freight_visible"] is False
    assert body2["freight_fee"] is None
    assert body2["driver_billing_mode"] == "SALARY"


def test_挂在规则上的司机_老单也按单结(
    db_session: Session,
) -> None:
    """派单时那条规则决定快照；老单没快照时，**不许**回去问司机档案（旧模型）。

    这里只钉判据本身：规则给"有按单应付"的司机，`snapshot_mode` 是 PIECE，
    所以他的新单快照也会是 PIECE；而老单（NULL）走的是同一侧的钱口径。
    """
    from app.services.driver_pay import snapshot_mode

    rule = SimpleNamespace(
        id=9, name="运费提成", salary=Decimal("0"), piece_amount=Decimal("0"), piece_unit="order",
        commission_base="freight", commission_rate=Decimal("10"), vehicle_type=None,
    )
    driver = SimpleNamespace(
        id=3, role="driver", vehicle_type="large", billing_mode="salary", salary=None, driver_rule=rule,
    )
    assert snapshot_mode(driver) == "PIECE", "规则里有按单应付 → 这张单按单结"
    old = SimpleNamespace(driver_billing_mode_snapshot=None, freight_fee=Decimal("500.00"))
    assert has_per_order_pay(old) is True, "老单与他的新单必须同一答案（旧模型会说是 SALARY）"


# ---------------------------------------------------------------- ④ SQL 与 Python 同答案


def test_SQL判据与Python判据对同一批取值同答案(db_session: Session) -> None:
    """`per_order_pay_filter`（SQL）与 `order_mode`（Python）对**每一个**取值都必须同答案。

    这是"一份判据、两种写法"的合同测试，也是这一轮真正的收获：原先 Python 把空串当"没写"
    （`snapshot or ""`）、SQL 把空串当"写了但不是 PIECE"（`is_(None)`）—— 于是一张快照是空串、
    有运费的单**账单会生成、结算页却不列它**，两张表对不上而谁都不报错。
    """
    from sqlalchemy import select as sa_select

    from app.models import Order
    from app.services.driver_pay import has_per_order_pay, per_order_pay_filter

    tag = _uniq("MODE")
    rows: list[Order] = []
    for i, snap in enumerate((None, "", "   ", "PIECE", "piece", " PIECE ", "SALARY", "salary", "??")):
        for fee in (None, Decimal("50.00")):
            o = Order(
                order_no=f"SO{uuid.uuid4().int % 10**18:018d}",
                status=OrderStatus.DISPATCHED,
                order_date=date(2026, 9, 21),
                address_detail=f"{tag}-{i}-{1 if fee is not None else 0}",
                driver_billing_mode_snapshot=snap,
                freight_fee=fee,
            )
            db_session.add(o)
            rows.append(o)
    db_session.flush()

    matched = set(
        db_session.scalars(
            sa_select(Order.id).where(Order.address_detail.like(f"{tag}-%"), per_order_pay_filter())
        )
    )
    assert len(rows) == 18, "取值矩阵变了（每条都要有快照 × 运费两种）"
    mismatch = [
        (repr(o.driver_billing_mode_snapshot), str(o.freight_fee))
        for o in rows
        if (o.id in matched) is not has_per_order_pay(o)
    ]
    assert not mismatch, f"SQL 与 Python 对这些取值答案不同（快照, 运费）：{mismatch}"


def test_结算页列出空串快照的老单(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """这张单的**账单会生成**（`has_per_order_pay` 为真）→ 结算页就必须列它。

    空串是这一列历史数据里的第三种写法（另两种是大小写）。原来 SQL 只认 `IS NULL`，
    于是这一张单**在结算页看不见**：派单员照着这一页付钱，永远不会付到它 ——
    而账单页（另一个查询）算得出来，两张表对不上且谁都不报错。
    """
    from app.core.business_time import utc_now_naive

    d = users["driver"]
    o = Order(
        order_no=f"SO{uuid.uuid4().int % 10**18:018d}",
        status=OrderStatus.DELIVERED,
        order_date=date(2026, 9, 21),
        delivered_at=utc_now_naive(),
        address_detail=_uniq("空串快照"),
        driver_id=d.id,
        freight_fee=Decimal("66.00"),
        driver_billing_mode_snapshot="",  # 历史数据里的空串写法
    )
    db_session.add(o)
    db_session.flush()

    r = client.get(
        "/api/v1/freight-settlement",
        params={"from": "2000-01-01T00:00:00", "to": "2100-01-01T00:00:00"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    listed = {int(x["order_id"]) for g in r.json()["groups"] for x in g["orders"]}
    assert o.id in listed, "这张单有按单应付（账单会生成），结算页却不列它 —— 两张表对不上"
