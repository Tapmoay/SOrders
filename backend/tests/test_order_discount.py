"""订单打折（CHG-0071 / 台账 L-34）：折后行金额、幂等替换、退货按折后实付退。

## 这一批要钉住的东西（每条都有"不钉住会怎样"）

| 判据 | 不钉住会怎样 |
|---|---|
| 折扣摊到**行**上（Σ line_total = 折后总额） | goods_amount / 账本 / 营业额各说一个数 |
| 再打一次折是**替换**不是叠加 | 连打两次 10% 变成 19%（用户看到的钱会少） |
| 取消折扣按快照 before **精确还原** | 生产库里 line_total != 单价×数量 的历史行会被改成另一个数 |
| 勾到「不参与打折」的行 => 400 | 派单员以为打了折、其实没打（最坏的一种成功） |
| 整单折扣**自动跳过**不参与的行 | 用户明确说了这个商品不参与 |
| 退货按**折后实付**退 | 退得比收的多（公司倒贴） |
| 改数量 / 删行之后折扣重算 | 快照一直在说一个已经不存在的优惠 |
| 司机视角八格全遮蔽 | 司机的出参里带着客户的优惠金额 |
| 只有派单员能打折（ORDER_EDIT） | 货主自己给自己打折 |
| 审计落 ORDER_DISCOUNT / ORDER_DISCOUNT_CLEAR | 少收的钱没有一条记录说是谁打的折 |

用户口径（逐字见 docs/changes/CHG-0071.md）：ref m01280（商品可打折 / 有不参与打折的商品）、
ref m01347（入口只有派单员改单；两种表达；不参与打折只跳过、价格照旧可改；整单与勾选两档）、
ref m13365（理由选填要留痕；**退货按折后实付退**）。
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from tests.conftest import auth_headers

API = "/api/v1"


def _order(client, token_shipper, lines: list[dict], name: str = "打折探针") -> int:
    r = client.post(
        f"{API}/orders",
        headers=auth_headers(token_shipper),
        json={
            "contact_dongjia_name": "收货人甲",
            "delivery_description": f"{name}地址",
            "address_detail": f"{name}地址",
            "lines": lines,
        },
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _line(name: str, qty: int, price: str, product_id: int | None = None) -> dict:
    line = {
        "product_name_snapshot": name,
        "quantity": qty,
        "unit_price": price,
        "line_total": str(Decimal(price) * qty),
    }
    if product_id is not None:
        line["product_id"] = product_id
    return line


def _apply(client, h, oid: int, kind: str, value: str, line_ids=None, reason=None):
    body: dict = {"kind": kind, "value": value}
    if line_ids is not None:
        body["line_ids"] = line_ids
    if reason is not None:
        body["reason"] = reason
    return client.post(f"{API}/orders/{oid}/discount", headers=h, json=body)


def _clear(client, h, oid: int):
    return client.delete(f"{API}/orders/{oid}/discount", headers=h)


def _detail(client, h, oid: int) -> dict:
    r = client.get(f"{API}/orders/{oid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _amounts(body: dict) -> dict[int, Decimal]:
    return {int(op["id"]): Decimal(str(op["line_total"])) for op in body["order_products"]}


def _sum_lines(body: dict) -> Decimal:
    return sum(_amounts(body).values(), Decimal("0"))


def _assign(client, h, users, oid: int) -> None:
    r = client.post(f"{API}/orders/{oid}/assign", json={"driver_id": users["driver"].id}, headers=h)
    assert r.status_code == 200, r.text


def _deliver(client, h, hd, users, oid: int) -> None:
    _assign(client, h, users, oid)
    assert client.post(f"{API}/orders/{oid}/driver-ack", headers=hd).status_code == 200
    r = client.post(
        f"{API}/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=hd,
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------- 纯函数 / 服务层
def test_plan_uses_the_before_snapshot_not_unit_price_times_qty(db_session) -> None:
    """生产库里有 line_total != 单价×数量 的历史行：折扣只能作用在**它现在的金额**上。

    3 x 10.0000 却只记 1.0000 的行（历史折扣 / 手工改过的老单）打 50% 之后是 0.50，
    取消折扣时要**精确还原成 1.00** —— 按乘法反推会把它改成 5.00，账上凭空多出 4 元。
    """
    from app.models import Order, OrderProduct
    from app.models.enums import OrderStatus
    from app.services.order_discount import apply_discount, clear_discount, has_discount

    order = Order(
        order_no="DISCOUNT-PROBE-1",
        status=OrderStatus.PENDING_DISPATCH,
        order_date=date(2026, 10, 6),
    )
    db_session.add(order)
    db_session.flush()
    op = OrderProduct(
        order_id=order.id,
        product_name_snapshot="历史行",
        quantity=3,
        unit_price=Decimal("10.0000"),
        line_total=Decimal("1.0000"),
    )
    db_session.add(op)
    db_session.flush()

    plan = apply_discount(db_session, order=order, kind="percent", value="50", actor_id=None)
    assert plan.amount == Decimal("0.50")
    assert op.line_total == Decimal("0.50")
    assert has_discount(order) is True

    clear_discount(db_session, order=order)
    assert op.line_total == Decimal("1.00"), "取消折扣把历史行改成了单价×数量"
    assert has_discount(order) is False


def test_plan_discount_rejects_bad_kind_value_and_scope(db_session) -> None:
    """四种拒绝：方式不认识 / 值 <= 0 / 百分比 >= 100 / 抹零比货款还多。"""
    from app.models import OrderProduct
    from app.services.order_discount import OrderDiscountError, plan_discount

    op = OrderProduct(id=1, order_id=1, product_name_snapshot="甲", quantity=1, unit_price=Decimal("100.00"))
    op.line_total = Decimal("100.00")
    rows = [op]
    for kind, value, word in (
        ("free", "10", "折扣方式"),
        ("percent", "0", "大于 0"),
        ("percent", "100", "小于 100"),
        ("amount", "150", "抹零"),
    ):
        try:
            plan_discount(rows, kind=kind, value=value)
        except OrderDiscountError as exc:
            assert word in str(exc), f"{kind}/{value} 的报错没说到点子上：{exc}"
        else:
            raise AssertionError(f"{kind}/{value} 居然通过了")


def test_spread_is_exact_to_the_cent_and_never_goes_negative(db_session) -> None:
    """摊分到分：Σ 各行减掉的 = 整单优惠额（差一分就与 goods_amount 对不上）。"""
    from app.models import OrderProduct
    from app.services.order_discount import plan_discount

    rows = []
    for i, a in enumerate(["33.33", "33.33", "33.34"], start=1):
        op = OrderProduct(id=i, order_id=1, product_name_snapshot=f"行{i}", quantity=1, unit_price=Decimal(a))
        op.line_total = Decimal(a)
        rows.append(op)
    plan = plan_discount(rows, kind="percent", value="33.33")
    saved = sum((s.before - s.after for s in plan.spread), Decimal("0"))
    assert saved == plan.amount, f"摊出来 {saved} != 优惠额 {plan.amount}"
    for s in plan.spread:
        assert s.after >= Decimal("0"), "摊出了负的行金额"


# ---------------------------------------------------------------- 端点 / 出参 / 审计
def test_percent_discount_lands_on_every_line_and_keeps_goods_amount(
    client, token_dispatcher, token_shipper
) -> None:
    """整单 10%：钱真的从每一行里少掉，Σ 行金额 = 折后总额（goods_amount 跟着变）。"""
    h = auth_headers(token_dispatcher)
    oid = _order(
        client,
        token_shipper,
        [_line("甲", 3, "100.00"), _line("乙", 2, "50.00"), _line("丙", 1, "33.33")],
    )
    before = _detail(client, h, oid)
    assert before["discount_amount"] is None, "新单不该带着折扣"
    assert Decimal(before["goods_amount"]) == Decimal("433.33")
    old = _amounts(before)
    old_price = {int(op["id"]): Decimal(str(op["unit_price"])) for op in before["order_products"]}

    r = _apply(client, h, oid, "percent", "10", reason="老客户让利")
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(body["discount_amount"]) == Decimal("43.33"), body
    assert body["discount_kind"] == "percent"
    assert Decimal(str(body["discount_value"])) == Decimal("10")
    assert body["discount_reason"] == "老客户让利"
    assert body["discount_at"] is not None
    assert body["discount_by_name"], "详情页要显示是谁打的折"
    assert Decimal(body["goods_amount"]) == Decimal("390.00")
    assert _sum_lines(body) == Decimal("390.00"), "行金额之和与 goods_amount 对不上"
    for op in body["order_products"]:
        assert Decimal(str(op["line_total"])) < old[int(op["id"])], "这一行一分钱都没少"
        assert Decimal(str(op["unit_price"])) == old_price[int(op["id"])], "折扣改掉了行单价（单价是货主的价，折扣只动行金额）"
    snap = body["discount_lines"]
    assert isinstance(snap, list) and len(snap) == 3, f"折扣快照没有逐行记：{snap}"
    assert all(s["before"] and s["after"] for s in snap), snap


def test_discounting_twice_replaces_instead_of_compounding(client, token_dispatcher, token_shipper) -> None:
    """再打一次折 = 把上一份撤掉再算新的（⛔ 不是"再乘一遍"）。"""
    h = auth_headers(token_dispatcher)
    oid = _order(client, token_shipper, [_line("甲", 1, "100.00")])
    assert _apply(client, h, oid, "percent", "10").status_code == 200

    body = _apply(client, h, oid, "amount", "5").json()
    assert body["discount_kind"] == "amount"
    assert Decimal(body["discount_amount"]) == Decimal("5.00")
    assert _amounts(body)[int(body["order_products"][0]["id"])] == Decimal("95.00"), "两次折扣叠乘了"
    assert Decimal(body["goods_amount"]) == Decimal("95.00")
    assert len(body["discount_lines"]) == 1, "快照还留着上一份折扣的行"


def test_clear_puts_every_line_back_and_writes_the_audit_row(
    client, token_dispatcher, token_shipper, db_session
) -> None:
    """取消折扣：每一行精确还原 + 七个快照列清空 + 落 ORDER_DISCOUNT_CLEAR 审计。"""
    from app.models import OperationLog
    from app.models.enums import OperationAction

    h = auth_headers(token_dispatcher)
    oid = _order(client, token_shipper, [_line("甲", 3, "100.00"), _line("乙", 1, "33.33")])
    old = _amounts(_detail(client, h, oid))
    assert _apply(client, h, oid, "percent", "10").status_code == 200

    r = _clear(client, h, oid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["discount_kind"] is None and body["discount_amount"] is None
    assert body["discount_lines"] is None and body["discount_reason"] is None
    assert body["discount_by_id"] is None and body["discount_at"] is None
    assert _amounts(body) == old, "取消折扣没有把每一行还原成原来的数"
    rows = (
        db_session.query(OperationLog)
        .filter(OperationLog.order_id == oid, OperationLog.action == OperationAction.ORDER_DISCOUNT_CLEAR)
        .all()
    )
    assert len(rows) == 1, "取消折扣没有落审计"


def test_amount_discount_beyond_scope_total_is_rejected(client, token_dispatcher, token_shipper) -> None:
    """抹零不能超过参与行的合计（优惠最多把货款抹到 0，不能变成倒找钱）。"""
    h = auth_headers(token_dispatcher)
    oid = _order(client, token_shipper, [_line("甲", 1, "100.00")])
    r = _apply(client, h, oid, "amount", "150")
    assert r.status_code == 400, r.text
    assert "抹零" in r.json()["detail"], r.text
    assert _detail(client, h, oid)["discount_amount"] is None, "被拒的折扣还是写进去了"


def test_bad_kind_and_bad_value_are_rejected(client, token_dispatcher, token_shipper) -> None:
    """四种拒绝走到端点：方式不认识 / 值 <= 0 / 百分比 >= 100（报错说清是哪一种）。"""
    h = auth_headers(token_dispatcher)
    oid = _order(client, token_shipper, [_line("甲", 1, "100.00")])
    for kind, value, word in (
        ("free", "10", "折扣方式"),
        ("percent", "0", "大于 0"),
        ("percent", "100", "小于 100"),
    ):
        r = _apply(client, h, oid, kind, value)
        assert r.status_code == 400, f"{kind}/{value} 没被拦：{r.text}"
        assert word in r.json()["detail"], r.text
    assert _detail(client, h, oid)["discount_amount"] is None


def test_only_dispatcher_can_discount(client, token_shipper) -> None:
    """货主自己给自己打折 —— 门在 Permission.ORDER_EDIT 上。"""
    oid = _order(client, token_shipper, [_line("甲", 1, "100.00")])
    r = client.post(
        f"{API}/orders/{oid}/discount",
        headers=auth_headers(token_shipper),
        json={"kind": "percent", "value": "10"},
    )
    assert r.status_code == 403, r.text


def test_no_discount_product_is_skipped_on_whole_order_and_rejected_when_picked(
    client, token_dispatcher, token_shipper, db_session
) -> None:
    """商品级「不参与打折」：整单折扣自动跳过它；派单员显式勾到它 => 400（不静默过滤）。"""
    from app.models import Product

    locked = Product(name="不参与打折探针", unit="件", default_unit_price=Decimal("100.00"), no_discount=True)
    normal = Product(name="普通探针", unit="件", default_unit_price=Decimal("100.00"))
    db_session.add_all([locked, normal])
    db_session.commit()
    h = auth_headers(token_dispatcher)
    oid = _order(
        client,
        token_shipper,
        [_line("不参与打折探针", 1, "100.00", locked.id), _line("普通探针", 1, "100.00", normal.id)],
    )
    rows = _detail(client, h, oid)["order_products"]
    picked = [int(op["id"]) for op in rows if int(op["product_id"]) == int(locked.id)]
    assert picked, "前提不成立：订单里没有那个不参与打折的商品"

    r = _apply(client, h, oid, "percent", "10", line_ids=picked)
    assert r.status_code == 400, r.text
    assert "不参与打折" in r.json()["detail"], r.text

    body = _apply(client, h, oid, "percent", "10").json()
    per_product = {int(op["product_id"]): Decimal(str(op["line_total"])) for op in body["order_products"]}
    assert per_product[int(locked.id)] == Decimal("100.00"), "勾了不参与打折的商品被减钱了"
    assert per_product[int(normal.id)] == Decimal("90.00"), "参与打折的行没减钱"


def test_line_ids_must_belong_to_the_order(client, token_dispatcher, token_shipper) -> None:
    """勾到了别的单的行 => 400（不静默丢掉那一行）。"""
    h = auth_headers(token_dispatcher)
    oid = _order(client, token_shipper, [_line("甲", 1, "100.00")])
    r = _apply(client, h, oid, "percent", "10", line_ids=[99999999])
    assert r.status_code == 400, r.text
    assert "不属于这张订单" in r.json()["detail"], r.text


def test_editing_a_line_recomputes_the_discount(client, token_dispatcher, token_shipper) -> None:
    """改数量之后：折扣按新金额重算一遍，Σ 行金额仍然 = goods_amount。"""
    h = auth_headers(token_dispatcher)
    oid = _order(client, token_shipper, [_line("甲", 1, "100.00"), _line("乙", 1, "200.00")])
    assert Decimal(_apply(client, h, oid, "percent", "10").json()["discount_amount"]) == Decimal("30.00")
    first = _detail(client, h, oid)["order_products"][0]

    r = client.patch(f"{API}/order-products/{first["id"]}", headers=h, json={"quantity": 2})
    assert r.status_code == 200, r.text
    body = _detail(client, h, oid)
    assert Decimal(body["discount_amount"]) == Decimal("40.00"), body
    assert _sum_lines(body) == Decimal("360.00") == Decimal(body["goods_amount"]), "改单后行金额与折扣对不上"


def test_deleting_a_line_recomputes_the_discount(client, token_dispatcher, token_shipper) -> None:
    """删掉一行之后：折扣跟着重算（快照不能一直说一个已经不存在的优惠）。"""
    h = auth_headers(token_dispatcher)
    oid = _order(client, token_shipper, [_line("甲", 1, "100.00"), _line("乙", 1, "200.00")])
    assert _apply(client, h, oid, "percent", "10").status_code == 200
    last = _detail(client, h, oid)["order_products"][1]

    r = client.delete(f"{API}/order-products/{last["id"]}", headers=h)
    assert r.status_code == 204, r.text
    body = _detail(client, h, oid)
    assert Decimal(body["discount_amount"]) == Decimal("10.00"), body
    assert _sum_lines(body) == Decimal("90.00") == Decimal(body["goods_amount"])


def test_return_of_a_discounted_line_refunds_the_discounted_amount(
    client, token_dispatcher, token_shipper, token_driver, users
) -> None:
    """退货按**折后实付**退：4 x 25 的单抹零 20（行金额 80），退货退回 80 而不是 100。"""
    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order(client, token_shipper, [_line("甲", 4, "25.00")])
    assert _apply(client, h, oid, "amount", "20").status_code == 200
    op = _detail(client, h, oid)["order_products"][0]
    assert Decimal(str(op["line_total"])) == Decimal("80.00")
    assert Decimal(str(op["unit_price"])) == Decimal("25.00"), "行单价被折扣改掉了（退货要拿它算就错上加错）"

    _deliver(client, h, hd, users, oid)
    r = client.post(
        f"{API}/orders/{oid}/return",
        headers=h,
        json={"items": [{"order_product_id": op["id"], "quantity": 4}], "note": "打折单退货"},
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["returned_amount"]) == Decimal("80.00"), "按原价退了（公司倒贴 20）"


def test_driver_sees_none_of_the_discount_fields(
    client, token_dispatcher, token_shipper, token_driver, users
) -> None:
    """司机视角：八个折扣字段整块遮蔽（只清 amount 等于没清）；派单员照旧看得见。"""
    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order(client, token_shipper, [_line("甲", 1, "100.00")])
    assert _apply(client, h, oid, "percent", "10", reason="老客户让利").status_code == 200
    _assign(client, h, users, oid)

    d = _detail(client, hd, oid)
    for field in (
        "discount_kind",
        "discount_value",
        "discount_amount",
        "discount_lines",
        "discount_reason",
        "discount_by_id",
        "discount_by_name",
        "discount_at",
    ):
        assert d[field] is None, f"司机的出参里带着 {field}"
    assert d["goods_amount"] is None, "司机的出参里带着货款"

    disp = _detail(client, h, oid)
    assert Decimal(disp["discount_amount"]) == Decimal("10.00")
    assert disp["discount_reason"] == "老客户让利"
    assert disp["discount_by_name"], "派单员看不到是谁打的折"


def test_finished_order_cannot_be_discounted(
    client, token_dispatcher, token_shipper, token_driver, users
) -> None:
    """已送达 / 已撤销 / 已退货的单不能再打折（钱已经入账了）。"""
    h, hd = auth_headers(token_dispatcher), auth_headers(token_driver)
    oid = _order(client, token_shipper, [_line("甲", 1, "100.00")])
    _deliver(client, h, hd, users, oid)
    r = _apply(client, h, oid, "percent", "10")
    assert r.status_code == 400, r.text
    assert "不能打折" in r.json()["detail"], r.text


def test_clear_without_discount_is_rejected(client, token_dispatcher, token_shipper) -> None:
    """没折扣的单取消折扣 => 400（放行会落一堆"取消了折扣"的假审计行）。"""
    h = auth_headers(token_dispatcher)
    oid = _order(client, token_shipper, [_line("甲", 1, "100.00")])
    r = _clear(client, h, oid)
    assert r.status_code == 400, r.text
    assert "本来就没有折扣" in r.json()["detail"], r.text


def test_audit_log_records_who_discounted_and_why(
    client, token_dispatcher, token_shipper, users, db_session
) -> None:
    """审计：谁、什么时候、打了什么折、为什么（操作日志里要能查出来）。"""
    from app.models import OperationLog
    from app.models.enums import OperationAction

    h = auth_headers(token_dispatcher)
    oid = _order(client, token_shipper, [_line("甲", 1, "100.00")])
    assert _apply(client, h, oid, "percent", "10", reason="老客户让利").status_code == 200

    row = (
        db_session.query(OperationLog)
        .filter(OperationLog.order_id == oid, OperationLog.action == OperationAction.ORDER_DISCOUNT)
        .order_by(OperationLog.id.desc())
        .first()
    )
    assert row is not None, "打折没有落审计"
    assert row.operator_id == users["dispatcher"].id, "审计里的操作人不对"
    payload = json.loads(row.change_content or "{}")
    assert payload.get("kind") == "percent", payload
    assert payload.get("reason") == "老客户让利", payload
    assert Decimal(str(payload.get("amount"))) == Decimal("10.00"), payload

