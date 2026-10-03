"""BUG-0001 的回归：**整单退货之后，被冲掉的那行自动账必须仍然可见**。

| 缺陷 | 后果 |
|---|---|
| 整单退货把订单转成 `RETURNED`，而 `visible_ledger_clause()` 的 `source=ORDER` 只认 `DELIVERED` | 原行被读口径吃掉、红冲行留着 → 账上**只剩一减**。真机 5554 实测：整单退货后「订单账（今天）」合计 **−85.5 / 1 笔流水**，而库里明明是 +85.5 与 −85.5 两行（`ledgers` id=878 / 879，`order_id=551`）；「货主账」「批发商账」同错 |

⚠️ 对称性是这三条用例的重点：**红冲行本来就可见**（`source != ORDER` 只要求订单没进回收站），
所以只要原行不可见，账本净额就一定偏负；而营业额那边整单退货的单根本不进
（`services/reports/loader.py::load_delivered` 只收 `status == DELIVERED`），
于是「账本净额 = 营业额」这条不变量当场破掉。
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.core.business_time import business_today
from tests.conftest import auth_headers
from tests.test_audit_round20_ledger_scope import _deliver, _ledger_total, _order


def _visible_rows_for(db_session, order_id: int) -> list:
    """这一张单**读口径下**能看见的账本行（就是页面与导出会看到的那一份）。"""
    from app.services.ledger_scope import visible_ledger_select

    db_session.expire_all()
    return [x for x in db_session.scalars(visible_ledger_select()) if x.order_id == order_id]


def _all_rows_for(db_session, order_id: int) -> list:
    """这一张单在库里**实际有多少行**（我们从不删账本行）。"""
    from app.models import Ledger

    db_session.expire_all()
    return list(db_session.scalars(select(Ledger).where(Ledger.order_id == order_id)))


def _request_full_return(client, hs, h, order_id: int, quantity: int) -> None:
    """货主申请退货 → 派单员办理（走两个真实端点，不直接调服务）。"""
    r = client.get(f"/api/v1/order-products?order_id={order_id}", headers=h)
    assert r.status_code == 200, r.text
    lines = r.json()
    assert len(lines) == 1, f"本用例只造了一行商品，实际 {len(lines)} 行"
    r = client.post(
        "/api/v1/return-requests",
        headers=hs,
        json={
            "order_id": order_id,
            "items": [{"order_product_id": int(lines[0]["id"]), "quantity": quantity}],
            "note": "退货账本口径探针",
        },
    )
    assert r.status_code == 201, r.text
    req_id = int(r.json()["id"])
    r = client.post(f"/api/v1/return-requests/{req_id}/fulfill", headers=h)
    assert r.status_code == 200, r.text


def test_full_return_keeps_the_reversed_row_visible(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """整单退货：库里两行俱在 → 读口径也必须是两行、相抵为 0。

    这是本缺陷的本体。改前 `source=ORDER` 只认 `DELIVERED`，整单退完订单转 `RETURNED`，
    原行被藏掉、红冲行留着 —— 账上只剩一减。
    """
    from app.models import Order
    from app.models.enums import LedgerSource, OrderStatus

    h = auth_headers(token_dispatcher)
    hs = auth_headers(token_shipper)
    hd = auth_headers(token_driver)
    shipper_id = users["shipper"].id

    oid = _order(client, h, shipper_id, "整单退货账本探针", qty=3, price="500")
    pre = _ledger_total(client, h, shipper_id)  # 送达之前
    _deliver(client, h, hd, oid, users["driver"].id)

    delivered = _visible_rows_for(db_session, oid)
    assert len(delivered) == 1 and delivered[0].source == LedgerSource.ORDER, (
        "前提不成立：送达没有写自动账本行"
    )
    assert _ledger_total(client, h, shipper_id) == pre + Decimal("1500"), (
        "前提不成立：送达之后账本口径没有加上这一单"
    )

    _request_full_return(client, hs, h, oid, quantity=3)
    db_session.expire_all()
    assert db_session.get(Order, oid).status == OrderStatus.RETURNED, (
        "前提不成立：整单退货之后订单应当转成 RETURNED"
    )

    # ① 库里两行俱在（我们从不删账本行 —— 用户在 2026-09-20 定过这条硬规矩）
    stored = _all_rows_for(db_session, oid)
    assert len(stored) == 2, f"库里应当有原行与红冲行两行，实际 {len(stored)} 行"

    # ② 读口径必须也是两行，且相抵为 0（改前这里只有 1 行、净额 −1500）
    visible = _visible_rows_for(db_session, oid)
    assert len(visible) == 2, (
        f"整单退货之后读口径只剩 {len(visible)} 行（库里 {len(stored)} 行）—— "
        "被冲掉的原行不见了，账上会只剩一减"
    )
    assert {x.source for x in visible} == {LedgerSource.ORDER, LedgerSource.RETURN}
    assert sum((x.total for x in visible), Decimal("0")) == Decimal("0"), (
        "原行与红冲行没有相抵为 0"
    )

    # ③ 账户口径（页面上那个数）回到退货之前
    assert _ledger_total(client, h, shipper_id) == pre, (
        "整单退货之后账户总额没有回到退货之前 —— 页面会显示凭空少了一笔营收"
    )


def test_ledger_net_equals_turnover_after_a_full_return(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """不变量：**账本净额 = 营业额**。整单退货把两边一起退回原样（不是只退一边）。

    营业额侧整单退货的单根本不进（`loader.py` 只收 `DELIVERED`），
    所以账本侧必须相抵为 0；改前账本净额留着 −700，两个数当场不一致。
    """
    h = auth_headers(token_dispatcher)
    hs = auth_headers(token_shipper)
    hd = auth_headers(token_driver)
    today = business_today().isoformat()

    def turnover() -> Decimal:
        r = client.get(f"/api/v1/reports/turnover?mode=day&date={today}", headers=h)
        assert r.status_code == 200, r.text
        return Decimal(str(r.json()["total_amount"]))

    def ledger() -> Decimal:
        rows = client.get("/api/v1/ledger/accounts?kind=shipper", headers=h).json()
        return sum((Decimal(str(x["total"])) for x in rows), Decimal("0"))

    oid = _order(client, h, users["shipper"].id, "整单退货对账探针", qty=1, price="700")
    t0, l0 = turnover(), ledger()
    _deliver(client, h, hd, oid, users["driver"].id)
    t1, l1 = turnover(), ledger()
    assert t1 == t0 + Decimal("700"), f"营业额没加上这一单：{t0} → {t1}"
    assert l1 == l0 + Decimal("700"), f"账本口径没加上这一单：{l0} → {l1}"

    _request_full_return(client, hs, h, oid, quantity=1)
    t2, l2 = turnover(), ledger()
    assert t2 == t0, f"整单退货的单不该留在营业额里：{t0} → {t2}"
    assert l2 == l0, f"整单退货之后账本净额没回到原样：{l0} → {l2}（改前会留着 −700）"
    assert t2 - t0 == l2 - l0, "账本净额与营业额对不上"


def test_partial_return_keeps_counting_the_remaining_rows(
    client, token_dispatcher, token_shipper, token_driver, users, db_session
):
    """边界：**部分退货**订单仍是 `DELIVERED`，两行本来就都可见 —— 改前改后必须逐位一致。

    这条是「别把口径改宽」的看门用例：如果哪天有人把红冲行也一起藏掉，
    或者把 `source=ORDER` 的可见状态放宽到「任何状态」，它会给出不同的数。
    """
    from app.models import Order
    from app.models.enums import LedgerSource, OrderStatus

    h = auth_headers(token_dispatcher)
    hs = auth_headers(token_shipper)
    hd = auth_headers(token_driver)
    shipper_id = users["shipper"].id

    oid = _order(client, h, shipper_id, "部分退货账本探针", qty=3, price="500")
    _deliver(client, h, hd, oid, users["driver"].id)
    after_delivery = _ledger_total(client, h, shipper_id)

    _request_full_return(client, hs, h, oid, quantity=1)  # 只退 1 件
    db_session.expire_all()
    assert db_session.get(Order, oid).status == OrderStatus.DELIVERED, (
        "部分退货不该把订单转成 RETURNED（整单退完才转）"
    )

    visible = _visible_rows_for(db_session, oid)
    assert len(visible) == 2, f"部分退货应当看到原行与红冲行两行，实际 {len(visible)} 行"
    assert {x.source for x in visible} == {LedgerSource.ORDER, LedgerSource.RETURN}
    assert sum((x.total for x in visible), Decimal("0")) == Decimal("1000"), (
        "部分退货的净额应当是剩下的 1 件 × 500"
    )
    assert _ledger_total(client, h, shipper_id) == after_delivery - Decimal("500"), (
        "部分退货之后账户口径应当只减掉退掉的那 1 件"
    )
