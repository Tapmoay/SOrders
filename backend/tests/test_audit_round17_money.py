"""第十七轮审计的回归测试（**钱的流出侧**）：红队审计员在本机实测出来的四条。

| 缺陷 | 后果 |
|---|---|
| **已软删订单的 OPEN 账单被结算单收走并真付款** | 运费结算页与报表都排除了软删单，账单表没有 → 账单比页面多出这些单的应付（本机 2026-09 实测 38 张 ¥1130.00）；**已有既成事实**：结算单 #3（¥880、已付）的明细里就含一张已软删的订单（先删单、后付款） |
| **月薪单"先查再插"没有兜底** | 唯一索引是 `(order_id, bill_type)`，而月薪单的 `order_id` 是 NULL（NULL 在唯一索引里互不相等）→ 并发生成两张月薪单（¥4500 变 ¥9000），而确认时的"金额与明细合计一致"校验**会通过** |
| **货损金额的进位方式与全项目不一致** | `.quantize(Decimal("0.01"))` 默认 ROUND_HALF_EVEN，而 `driver_pay.money()` 是 ROUND_HALF_UP → 成本价正好落在半分上时两处差 1 分 |
| **绩效/导出的「计费方式」读 `users.billing_mode`** | 给工资制司机挂上"每单 300 + 运费 5%"的规则后，账单/结算页都按规则算钱，绩效却仍说"工资制、无待结"（同一件事四句话） |

另外两条与库存有关（在途占用、保留任务）也在本文件里。
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from tests.conftest import auth_headers


def _mk_product(client, h, name: str, stock: int = 100, cost: str = "4") -> int:
    r = client.post(
        "/api/v1/products",
        json={"name": name, "default_unit_price": "10", "cost_price": cost, "stock": stock},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _mk_order(client, h, shipper_id: int, pid: int, qty: int = 1, price: str = "100") -> dict:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [
                {
                    "product_id": pid,
                    "product_name_snapshot": "钱流出侧探针货",
                    "quantity": qty,
                    "unit_price": price,
                    "line_total": str(Decimal(price) * qty),
                }
            ],
            "address_detail": "钱流出侧探针地址",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _deliver(client, h_dispatcher, h_driver, order_id: int, driver_id: int, freight: str = "100") -> None:
    r = client.post(
        f"/api/v1/orders/{order_id}/assign",
        json={"driver_id": driver_id, "freight_fee": freight},
        headers=h_dispatcher,
    )
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/orders/{order_id}/driver-ack", headers=h_driver)
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/orders/{order_id}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=h_driver,
    )
    assert r.status_code == 200, r.text


# --------------------------------------------------- ① 软删单的账单不许被结算
def test_soft_deleted_order_bills_are_not_collected_by_a_settlement(
    client, db_session, users, token_dispatcher, token_driver
):
    """订单进了回收站 → 它的 OPEN 账单不许再被结算单收走（页面与账单必须同口径）。"""
    from app.models import DriverBill, DriverSettlement
    from app.models.enums import DriverBillStatus

    h = auth_headers(token_dispatcher)
    # 司机必须是**按单计费**才会有 PIECE 账单（工资制司机本来就不产生按单应付）
    users["driver"].billing_mode = "piece"
    # ⛔ **只改 billing_mode 不够**：挂着的计费规则优先于这一列（`driver_pay.snapshot_mode`）。
    #    同一个文件里的 `test_salary_generate_is_idem` / `test_driver_performance_bill` 会给这个
    #    司机挂上工资制规则；用例一换顺序（倒序扫描）那条规则还在 → 送达不产生按单账单 →
    #    这条用例的前提（第 91 行那句"送达没生成账单"）直接不成立。2026-09-25 实测。
    #    与 `test_audit_round25_export_content.py` 同一写法：两个都清干净。
    users["driver"].driver_rule_id = None
    db_session.commit()
    pid = _mk_product(client, h, "软删账单探针货")
    order = _mk_order(client, h, users["shipper"].id, pid)
    _deliver(client, h, auth_headers(token_driver), order["id"], users["driver"].id, freight="300")

    db_session.expire_all()
    bill = db_session.scalars(
        select(DriverBill).where(DriverBill.order_id == order["id"])
    ).first()
    assert bill is not None, "送达没生成账单（前提不成立）"
    month = bill.month

    # 派单员把这一单删掉（软删进回收站）
    r = client.delete(f"/api/v1/orders/{order['id']}", headers=h)
    assert r.status_code in (200, 204), r.text

    # 现在再为这个月建结算单：那张账单**不该**被收走
    r = client.post(
        "/api/v1/driver-settlements",
        json={"driver_id": users["driver"].id, "settle_type": "piece", "month": month},
        headers=h,
    )
    if r.status_code in (200, 201):
        body = r.json()
        db_session.expire_all()
        s = db_session.get(DriverSettlement, body["id"])
        assert order["id"] not in (s.order_ids or []), (
            f"已软删订单的账单被结算单收走了：order_ids={s.order_ids}"
        )
        # 收尾：把这张结算单作废，免得影响别的用例
        client.post(
            f"/api/v1/driver-settlements/{s.id}/cancel", json={"note": "探针清理"}, headers=h
        )
    else:
        # 也可以表现为"这个月没有可结算明细"——同样说明没把它收走
        assert "无待结算明细" in r.text, f"既没收走也没说清楚：{r.status_code} {r.text[:200]}"
    db_session.expire_all()
    assert db_session.get(DriverBill, bill.id).status == DriverBillStatus.OPEN, (
        "被拒绝的结算不该改账单状态"
    )


# --------------------------------------------------- ② 月薪单不许生成两张
def test_salary_generate_is_idempotent_and_takes_a_lock(client, db_session, users, token_dispatcher):
    """月薪单：连跑两次只许有一张（并发下的兜底是司机行锁，见 driver_bills 里的说明）。"""
    from app.models import DriverBill, User
    from app.models.enums import DriverBillStatus, DriverBillType
    from app.services.driver_pay import monthly_salary_of

    h = auth_headers(token_dispatcher)
    # 给这个司机一个"只有固定工资"的规则（车型对上才挂得上）
    r = client.post(
        "/api/v1/driver-billing-rules",
        json={
            "name": "探针月薪规则",
            "vehicle_type": users["driver"].vehicle_type or "",
            "salary": "4500",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    rule_id = r.json()["id"]
    r = client.post(
        "/api/v1/driver-billing-rules/attach",
        json={"driver_id": users["driver"].id, "rule_id": rule_id},
        headers=h,
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    driver = db_session.get(User, users["driver"].id)
    if monthly_salary_of(driver) <= 0:
        # 车型对不上时挂不上规则 → 这条用例的前提不成立，明确跳过而不是假绿
        import pytest

        pytest.skip("该司机拿不到月薪（车型/参数不匹配），本机无法构造该场景")

    month = "2026-08"
    for _ in range(2):
        r = client.post(
            "/api/v1/driver-bills/generate",
            json={"driver_id": users["driver"].id, "bill_type": "salary", "month": month},
            headers=h,
        )
        assert r.status_code in (200, 201), r.text

    rows = db_session.scalars(
        select(DriverBill).where(
            DriverBill.driver_id == users["driver"].id,
            DriverBill.bill_type == DriverBillType.SALARY,
            DriverBill.month == month,
        )
    ).all()
    assert len(rows) == 1, f"同一个月的月薪单生成了 {len(rows)} 张：{[(x.id, str(x.amount)) for x in rows]}"
    assert rows[0].status == DriverBillStatus.OPEN


# --------------------------------------------------- ③ 货损金额的进位方式
def test_damage_amount_rounds_like_the_rest_of_the_project(client, db_session, users, token_dispatcher, token_driver):
    """货损金额必须用 ROUND_HALF_UP（与 `driver_pay.money()` 同源），不是银行家舍入。

    货损走的是**送达那一次**请求（`OrderCompleteBody.damage_items`），不是另一个端点。
    """
    from app.models import Expense, OrderProduct

    h = auth_headers(token_dispatcher)
    # 成本价 12.3450 × 1 件 = 12.345 → HALF_UP 是 12.35，HALF_EVEN 是 12.34
    pid = _mk_product(client, h, "半分进位探针货", cost="12.3450")
    order = _mk_order(client, h, users["shipper"].id, pid)

    hd = auth_headers(token_driver)
    r = client.post(
        f"/api/v1/orders/{order['id']}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "100"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/orders/{order['id']}/driver-ack", headers=hd).status_code == 200

    db_session.expire_all()
    line = db_session.scalars(select(OrderProduct).where(OrderProduct.order_id == order["id"])).first()
    assert line is not None and str(line.cost_price_snapshot) == "12.3450", (
        f"前提不成立：行的成本快照是 {line.cost_price_snapshot}"
    )

    r = client.post(
        f"/api/v1/orders/{order['id']}/complete",
        json={
            "delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"],
            "damage_items": [{"order_product_id": line.id, "quantity": 1}],
            "damage_note": "探针货损",
        },
        headers=hd,
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    exp = db_session.scalars(select(Expense).where(Expense.order_id == order["id"])).all()
    amounts = [str(x.amount) for x in exp]
    assert any(a.startswith("12.35") for a in amounts), (
        f"货损金额没按 ROUND_HALF_UP 进位：{amounts}（应当是 12.35；12.34 说明是银行家舍入）"
    )


# --------------------------------------------------- ④ 绩效的计费方式跟规则走
def test_driver_performance_billing_mode_follows_the_rule(
    client, db_session, users, token_dispatcher, token_driver
):
    """工资制司机挂上"每单固定"的规则之后，绩效里的计费方式必须是按单（不是"工资制"）。"""
    from app.models import User

    h = auth_headers(token_dispatcher)
    driver = db_session.get(User, users["driver"].id)
    # ⚠️ 必须把用户表里的计费方式**显式设成工资制**：这条测试要证明的正是
    #    "用户表说工资制、但挂了按单规则 → 绩效必须报按单"。不设的话（默认值或
    #    前一个用例改成的 piece）老代码也会报 PIECE，这条断言就变成恒绿。
    driver.billing_mode = "salary"
    db_session.commit()
    vt = driver.vehicle_type or ""
    r = client.post(
        "/api/v1/driver-billing-rules",
        json={"name": "探针每单规则", "vehicle_type": vt, "piece_amount": "300", "piece_unit": "order"},
        headers=h,
    )
    if r.status_code not in (200, 201):
        import pytest

        pytest.skip(f"挂不上规则（车型不匹配？）：{r.status_code} {r.text[:120]}")
    rule_id = r.json()["id"]
    r = client.post(
        "/api/v1/driver-billing-rules/attach",
        json={"driver_id": users["driver"].id, "rule_id": rule_id},
        headers=h,
    )
    assert r.status_code == 200, r.text

    pid = _mk_product(client, h, "绩效口径探针货")
    order = _mk_order(client, h, users["shipper"].id, pid)
    _deliver(client, h, auth_headers(token_driver), order["id"], users["driver"].id, freight="1000")

    r = client.get(
        f"/api/v1/stats/driver-performance?date_from=2026-01-01&date_to=2026-12-31", headers=h
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body["drivers"] if isinstance(body, dict) else body
    mine = [x for x in rows if int(x.get("driver_id") or 0) == users["driver"].id]
    assert mine, f"绩效里没有这个司机：{str(body)[:300]}"
    assert mine[0]["billing_mode"] == "PIECE", (
        f"挂了每单规则却仍报 {mine[0]['billing_mode']}（用户表里还是 SALARY）——"
        "绩效与账单/结算页会各说一套"
    )
    assert mine[0].get("freight_owed") is not None, "按单司机必须有待结运费（不能印成工资制）"


# --------------------------------------------------- ⑥ 商品毛利三处必须同一个数
def test_product_profit_is_the_same_number_everywhere(
    client, db_session, users, token_dispatcher, token_driver
):
    """商品毛利的口径必须**只有一处**：接口 / 导出表头 / 导出逐行 / App 都读同一批行。

    实测（2026-09-19，同一月）：App 商品页 11,071.00、正确口径 10,789.00、
    导出逐行毛利列合计 72,177.75 —— 三处三个数，而每一处看起来都正常。
    """
    from io import BytesIO

    from openpyxl import load_workbook

    h = auth_headers(token_dispatcher)
    with_cost = _mk_product(client, h, "毛利探针-有成本", cost="40")
    # 成本价 0 = 没有成本快照（`_mk_product` 的默认值是 4，所以必须显式传 0）
    no_cost = _mk_product(client, h, "毛利探针-无成本", cost="0")

    # 同一张单里三行：
    # ① 有成本快照的一行（进毛利）
    # ② **同名但手输**的一行（没有商品编号 → 成本快照 0 → 不进毛利）
    #    ⚠️ 这一行是**必须的**：只有"同一个商品名既有进毛利的行、又有不进毛利的行"时，
    #    "拿全额金额减成本"和"拿参与毛利的金额减成本"才会给出不同的数
    #    （实测里那个 7.2 倍的混合组 ttt 就是这个形状）。少了它，两种口径在本机数据上
    #    恰好相等 → 判据恒绿（反向验证第二次就是这样漏掉的）。
    # ③ 完全没有成本价的一个商品（逐行毛利必须是「—」）
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [
                {
                    "product_id": with_cost,
                    "product_name_snapshot": "毛利探针-有成本",
                    "quantity": 2,
                    "unit_price": "100",
                    "line_total": "200",
                },
                {
                    "product_name_snapshot": "毛利探针-有成本",
                    "quantity": 1,
                    "unit_price": "500",
                    "line_total": "500",
                },
                {
                    "product_id": no_cost,
                    "product_name_snapshot": "毛利探针-无成本",
                    "quantity": 1,
                    "unit_price": "900",
                    "line_total": "900",
                },
            ],
            "address_detail": "毛利探针地址",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    order_id = r.json()["id"]
    _deliver(client, h, auth_headers(token_driver), order_id, users["driver"].id, freight="100")

    db_session.expire_all()
    from app.models import OrderProduct

    rows = db_session.scalars(
        select(OrderProduct).where(OrderProduct.order_id == order_id)
    ).all()
    costs = [(r.product_name_snapshot, Decimal(r.cost_price_snapshot or 0)) for r in rows]
    assert ("毛利探针-有成本", Decimal("40")) in costs, costs
    assert ("毛利探针-有成本", Decimal("0")) in costs, costs
    assert ("毛利探针-无成本", Decimal("0")) in costs, costs

    today = date.today()
    url = f"/api/v1/reports/products?mode=day&date={today.isoformat()}"
    r = client.get(url, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    # 测试库是**累积**的（别的用例今天也送达过单），所以这里断言的是**口径不变式**，
    # 而不是"总数等于我这单"——不变式才是这条缺陷真正要守的东西。
    items = data["items"]
    assert Decimal(data["cost_covered_amount"]) == sum(
        (Decimal(i["covered_amount"]) for i in items), Decimal("0")
    ), "cost_covered_amount 与逐行 covered_amount 之和对不上（说明两处口径不一致）"
    assert int(data["cost_covered_lines"]) == sum(int(i["covered_lines"]) for i in items)
    assert Decimal(data["cost_total"]) == sum((Decimal(i["cost"]) for i in items), Decimal("0"))
    assert Decimal(data["cost_covered_amount"]) <= Decimal(data["total_amount"]), (
        "参与毛利的收入不可能大于总营业额"
    )

    by_name = {i["product_name"]: i for i in items}
    covered = by_name["毛利探针-有成本"]
    uncovered = by_name["毛利探针-无成本"]
    assert Decimal(covered["covered_amount"]) == Decimal("200") and covered["covered_lines"] == 1
    # ⭐ 混合组的判据：同一个商品名下"进毛利的金额 200" ≠ "全额金额 700"。
    #    老口径（全额 − 成本）会算成 700−80=620，正确口径是 200−80=120 —— 差 5 倍。
    assert Decimal(covered["amount"]) == Decimal("700"), covered
    assert Decimal(uncovered["covered_amount"]) == Decimal("0") and uncovered["covered_lines"] == 0
    assert Decimal(uncovered["amount"]) == Decimal("900"), "无成本那行的金额仍是 900（不进毛利而已）"

    # 导出：表头毛利与逐行毛利必须都由同一批行算出来
    r = client.get(
        f"/api/v1/reports/export?kind=products&mode=day&date={today.isoformat()}", headers=h
    )
    assert r.status_code == 200, r.text
    wb = load_workbook(BytesIO(r.content))
    ws = wb["商品经营"]
    header_rows = [[c.value for c in row] for row in ws.iter_rows(min_row=1, max_row=3)]
    flat = [v for row in header_rows for v in row if v is not None]
    # 与 `reports._money()` 同一套进位（ROUND_HALF_UP 到两位），用 Decimal 算、
    # 不要用 Python 的 round(float)：303.655 在二进制里是 303.65499999…，round 会给 303.65 而
    # 金额那边给 303.66 —— 那是浮点误差，不是口径不一致。
    expect_header = (
        Decimal(data["cost_covered_amount"]) - Decimal(data["cost_total"])
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert any(
        isinstance(v, (int, float)) and abs(Decimal(str(v)) - expect_header) < Decimal("0.0001")
        for v in flat
    ), f"导出表头的商品毛利不是『参与毛利收入 − 成本』= {expect_header}：{flat}"
    # 位置也要对：毛利那一格必须**紧跟**在标签后面（不是把营业额那一格当毛利）
    label_at = next(
        (i for i, v in enumerate(flat) if isinstance(v, str) and v.startswith("商品毛利")), None
    )
    assert label_at is not None, f"导出表头没有『商品毛利』这一格：{flat}"
    assert abs(Decimal(str(flat[label_at + 1])) - expect_header) < Decimal("0.0001"), (
        f"导出表头『商品毛利』那一格是 {flat[label_at + 1]}，应当是 {expect_header}"
    )
    # 逐行：混合组那行的毛利列 = covered_amount − cost = 200 − 80 = 120（**不是** 700 − 80 = 620）；
    #      完全没有成本快照的商品必须是 "—"（不是把 900 当毛利）
    body = [[c.value for c in row] for row in ws.iter_rows(min_row=5)]
    line_with = next(row for row in body if row and row[0] == "毛利探针-有成本")
    line_without = next(row for row in body if row and row[0] == "毛利探针-无成本")
    assert line_with[4] == 200.0, f"逐行的『参与毛利的金额』列不是 200：{line_with}"
    assert line_with[5] == 120.0, f"逐行毛利不是 120.00（620 就是那个被修掉的老口径）：{line_with}"
    assert line_without[5] == "—", f"没有成本快照的行不该印毛利数字：{line_without}"

def test_inventory_summary_ignores_reservations_of_soft_deleted_orders(
    client, db_session, users, token_dispatcher
):
    """「在途占用」不许计入已软删（进回收站）订单的预占流水。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, "在途占用探针货", stock=10)
    order = _mk_order(client, h, users["shipper"].id, pid, qty=4)
    r = client.post(
        f"/api/v1/orders/{order['id']}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "10"},
        headers=h,
    )
    assert r.status_code == 200, r.text

    def reserved_now() -> int:
        rows = client.get("/api/v1/inventory/summary", headers=h).json()
        return next((int(x["reserved"]) for x in rows if x["product_id"] == pid), 0)

    assert reserved_now() == 4, "在途占用没算上（前提不成立）"
    r = client.delete(f"/api/v1/orders/{order['id']}", headers=h)
    assert r.status_code in (200, 204), r.text
    assert reserved_now() == 0, "已软删订单的预占仍被当成在途占用"


def test_retention_purge_deletes_inventory_movements(db_session, users):
    """物理清理订单时，该单的库存流水必须一起删（否则在途占用永久残留）。"""
    from app.core.business_time import utc_now_naive
    from app.models import InventoryMovement, Order, Product
    from app.models.enums import OrderStatus
    from app.services.data_retention import SOFT_DELETE_RETENTION_DAYS, purge_soft_deleted_orders

    from datetime import timedelta

    p = Product(name="保留任务探针货", unit="件", default_unit_price=Decimal("10"), stock=5)
    db_session.add(p)
    db_session.flush()
    o = Order(
        order_no="SORETENTION1",
        shipper_id=users["shipper"].id,
        status=OrderStatus.DISPATCHED,
        order_date=date(2025, 1, 1),
        deleted_at=utc_now_naive() - timedelta(days=SOFT_DELETE_RETENTION_DAYS + 1),
    )
    db_session.add(o)
    db_session.flush()
    db_session.add(
        InventoryMovement(
            product_id=p.id,
            change=-3,
            note="保留任务探针预占",
            operator_id=users["dispatcher"].id,
            source="ORDER",
            order_id=o.id,
            status="RESERVED",
        )
    )
    db_session.commit()
    oid = o.id

    purge_soft_deleted_orders(db_session)
    db_session.expire_all()
    left = db_session.scalars(
        select(InventoryMovement).where(InventoryMovement.order_id == oid)
    ).all()
    assert left == [], f"订单被物理清理了，库存流水还在：{[(x.id, x.status) for x in left]}"
