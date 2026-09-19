"""第十二轮审计的回归测试（多 agent 交叉审查 + 真后端实测抓到的六条）。

每一条都对应一个**已被证明会真实发生**的缺陷，且都在原始症状上钉死：

| 编号 | 症状 | 这条测试钉什么 |
|---|---|---|
| R12-H1 | 进价 `cost_price` 对所有登录角色下发（司机 `GET /products/{id}` 实测 200 带进价） | 货主/司机拿到 `None`，派单员仍拿到真实进价 |
| R12-M1 | 撤回派单不清逐单覆盖值 → 新司机按**上一个司机**的数字算钱 | 撤回后再派，落库的是"不特殊" |
| R12-M2 | 报表「司机运费支出」= Σ 订单运费，与运费结算页差 93% | 两处同源（Σ `pay_for_order`） |
| R12-M3 | 账本行是已送达订单的第二个写钱入口（PATCH 回写订单行、DELETE 只删账本） | 已送达的单：账本行不许改金额、不许删 |
| R12-M4 | 滚动收款带订单号时不校验金额 → 整单标已收、差额静默抹掉 | 绑了订单就必须对得上（否则 400 且订单仍未收款） |
| R12-A1 | 导出下载端点读一个**不存在的属性** → 每次下载 500 | 真的下载一次，断言 200 + 是 xlsx |
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from tests.conftest import auth_headers


# ------------------------------------------------------------------ 公共构造工具
def _mk_order(client, h, **over) -> dict:
    """用**真实接口**建单（不手搓 ORM 行：order_no/order_date 这些字段自己拼容易拼错）。"""
    payload = {
        "shipper_id": 2,
        "lines": [
            {"product_name_snapshot": "探针货", "quantity": 1, "unit_price": "100", "line_total": "100"}
        ],
        "address_detail": "审计探针路 1 号",
        "freight_fee": "1000",
    }
    payload.update(over)
    r = client.post("/api/v1/orders", json=payload, headers=h)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _mk_driver(client, h) -> tuple[int, str]:
    """建一个**专用**司机（连同他的登录令牌）。

    为什么不复用 fixture 里那个司机：给他的账号挂计费规则会改变**同一轮里其它用例**的行为
    （`test_generate_bills_*`、`test_double_complete_*` 全都会跟着变，实测被污染过 7 条），
    而测试库跨轮次保留，这种互相影响最难查。与 `test_driver_billing_api.py` 同一条理由。
    """
    import uuid

    phone = "13" + uuid.uuid4().hex[:9].translate(str.maketrans("abcdef", "012345"))
    r = client.post(
        "/api/v1/users",
        json={"phone": phone, "password": "pass12345", "full_name": "审计专用司机", "role": "driver"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    driver_id = int(r.json()["id"])
    r = client.post("/api/v1/auth/login", json={"phone": phone, "password": "pass12345"})
    assert r.status_code == 200, r.text
    return driver_id, r.json()["access_token"]


def _attach_rule(client, h, driver_id: int, piece: str = "200", commission: bool = True) -> int:
    """给司机挂一份计费规则。

    为什么必须先挂：逐单覆盖值（`driver_piece_amount`）在**没有规则**的司机身上是无效的，
    后端会明确拒绝（`override_problem`：「这个司机还没挂计费规则，逐单的金额/比例没有地方生效」）
    —— 那是设计如此，不是缺陷；要验"撤回清覆盖值"就得先造出"有规则"的前提。

    `commission=False` = 只有"每单固定"那一项（用来造出"司机应得 ≠ 订单运费"的现场）。
    """
    body = {
        "name": f"覆盖值探针规则-{driver_id}",
        "piece_amount": piece,
        "remark": "审计探针",
    }
    if commission:
        # 提成基数也要选上：规则里没有提成项时，逐单定**比例**会被后端明确拒绝
        # （「…没有提成项，逐单定比例算出来永远是 0」），那是设计如此。
        body["commission_base"] = "freight"
        body["commission_rate"] = "5"
    r = client.post("/api/v1/driver-billing-rules", json=body, headers=h)
    assert r.status_code in (200, 201), r.text
    rule_id = r.json()["id"]
    r = client.post(
        "/api/v1/driver-billing-rules/attach", json={"driver_id": driver_id, "rule_id": rule_id}, headers=h
    )
    assert r.status_code in (200, 201), r.text
    return rule_id


def _set_status(db, order_id: int, status) -> None:
    from app.models import Order

    db.expire_all()
    o = db.get(Order, order_id)
    o.status = status
    db.commit()


def _add_order_ledger_row(db, order_id: int, shipper_id: int, total: str = "100") -> int:
    from app.models import Ledger, LedgerSource

    row = Ledger(
        source=LedgerSource.ORDER,
        shipper_id=shipper_id,
        order_id=order_id,
        product_name="探针货",
        quantity=1,
        unit_price=Decimal(total),
        total=Decimal(total),
        entry_date=date(2026, 9, 19),
    )
    db.add(row)
    db.commit()
    return row.id


# --------------------------------------------------------------- R12-H1 进价不外泄
def test_cost_price_only_visible_to_product_manager(client, token_dispatcher, token_shipper, token_driver, db_session):
    from app.models import Product

    p = Product(name="进价探针商品", default_unit_price=Decimal("30"), cost_price=Decimal("20"), stock=0)
    db_session.add(p)
    db_session.commit()

    h = auth_headers(token_dispatcher)
    detail = client.get(f"/api/v1/products/{p.id}", headers=h).json()
    assert detail["cost_price"] is not None and Decimal(detail["cost_price"]) == Decimal("20"), detail

    rows = client.get("/api/v1/products?limit=500", headers=auth_headers(token_shipper)).json()
    mine = next((r for r in rows if r["id"] == p.id), None)
    assert mine is not None, "货主应当能看到商品目录（否则下不了单）"
    assert mine["cost_price"] is None, f"货主不该看到进价：{mine}"

    r = client.get(f"/api/v1/products/{p.id}", headers=auth_headers(token_driver))
    assert r.status_code in (200, 403, 404), r.text
    if r.status_code == 200:
        assert r.json()["cost_price"] is None, f"司机的商品详情里出现了进价：{r.json()}"


def test_cost_price_redaction_is_single_sourced():
    """形状断言：裁剪必须只有一处实现（否则迟早有第三个出口漏掉）。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app/api/v1/products.py").read_text(encoding="utf-8")
    assert "def product_out(" in src, "商品出参的裁剪函数不见了"
    assert src.count("product_out(") >= 3, "列表与详情必须都走同一个裁剪函数（定义 1 处 + 使用 2 处）"


# ------------------------------------------------- R12-M1 撤回必须清掉逐单覆盖值
def test_recall_clears_per_order_driver_amount(client, token_dispatcher, db_session):
    from app.models import Order, OrderStatus

    h = auth_headers(token_dispatcher)
    driver_id, _ = _mk_driver(client, h)
    _attach_rule(client, h, driver_id)
    o = _mk_order(client, h)

    r = client.post(
        f"/api/v1/orders/{o['id']}/assign",
        json={"driver_id": driver_id, "driver_piece_amount": 300, "driver_commission_rate": 8},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    db_session.expire_all()
    assert Decimal(db_session.get(Order, o["id"]).driver_piece_amount) == Decimal("300")

    r = client.post(f"/api/v1/orders/{o['id']}/recall", json={"reason": "派错了"}, headers=h)
    assert r.status_code in (200, 201), r.text
    db_session.expire_all()
    after = db_session.get(Order, o["id"])
    assert after.driver_id is None and after.status == OrderStatus.PENDING_DISPATCH
    assert after.driver_piece_amount is None, (
        "撤回之后「这一单单独定的金额」还留着 —— 下一个司机会按上一个司机的数字算钱"
    )
    assert after.driver_commission_rate is None, "撤回之后逐单提成比例还留着"


def test_assign_without_override_does_not_inherit_previous_value(client, token_dispatcher, db_session):
    """`assign` 的语义：**没给就是不特殊**（字段注释就是这么写的）——R12-M1 的另一半。"""
    from app.models import Order

    h = auth_headers(token_dispatcher)
    driver_id, _ = _mk_driver(client, h)
    o = _mk_order(client, h, address_detail="审计探针路 2 号")

    db_session.expire_all()
    row = db_session.get(Order, o["id"])
    row.driver_piece_amount = Decimal("999")  # 人为制造"上一次残留"
    db_session.commit()

    # ⚠️ 这里**不挂规则**：引擎对"没有规则的司机 + 没给覆盖值"是直接放行的
    #    （`override_problem` 只在真的给了覆盖值时才拦），所以正是能验出残留的场景。
    r = client.post(f"/api/v1/orders/{o['id']}/assign", json={"driver_id": driver_id}, headers=h)
    assert r.status_code in (200, 201), r.text
    db_session.expire_all()
    assert db_session.get(Order, o["id"]).driver_piece_amount is None, (
        "派单没填这一单的金额，残留的 999 却跟着走了"
    )


# --------------------------------------------- R12-M2 报表与结算页必须同源
def test_turnover_driver_freight_matches_settlement(client, token_dispatcher, db_session):
    """「司机运费支出」= 司机应得（`pay_for_order`），**不是** Σ 订单运费（R12-M2）。

    实测过的量级：同一天 47870.00（订单运费）vs 24770.00（实际应付）—— 虚高 93%，
    而两个页面都不报错，老板照这一格判断车费成本就会系统性高估。

    这条测试**自己造出**"两者不相等"的现场（规则：每单固定 100；订单运费 1000），
    否则在只有"按运费全额"的库里两边永远相等，判据等于没有（第一版就是这样，
    反向验证注入了 bug 它照样绿）。

    ⚠️ **送达时刻必须钉成"当地 04:00"**（2026-09-19 审计第十五轮修）：
    原来送达时刻就是"现在"，而这条测试的第二个断言（报表 == 结算页）对
    **"客户端传的当地窗口要不要换算成 UTC"** 这件事的敏感度**取决于跑测试的钟点** ——
    当地 08:00 之后送达时，UTC 时刻仍落在"当地 00:00~23:59"这个裸窗口里，
    于是把 `to_utc_naive` 整段删掉注入之后测试**照样通过**（反向验证全量跑时才暴露：
    上午 5~7 点能抓到、下午抓不到 —— 那等于这条判据每天只有三分之一时间有效）。
    现在固定成当地 04:00（UTC 前一天 20:00），两种写法必然给出不同结果。
    """
    from datetime import datetime as _dt
    from datetime import time as _time
    from datetime import timezone as _tz

    h = auth_headers(token_dispatcher)
    driver_id, dtoken = _mk_driver(client, h)
    _attach_rule(client, h, driver_id, piece="100", commission=False)

    # ⚠️ 锚点用**业务当地日**（`delivered_at` 存 UTC；东八区当地 00:00~08:00 送达时两者差一天，
    #    那正是 R12-M11 修的另一个缺陷——不修的话这段时间里这条断言会算出 delta=0）
    from app.core.business_time import BUSINESS_TZ, business_date, business_today

    anchor = business_today().isoformat()
    query = f"/api/v1/reports/turnover?mode=day&date={anchor}"
    before = Decimal(str(client.get(query, headers=h).json()["total_freight"]))

    o = _mk_order(client, h, freight_fee="1000", address_detail="运费口径探针路 1 号")
    r = client.post(f"/api/v1/orders/{o['id']}/assign", json={"driver_id": driver_id}, headers=h)
    assert r.status_code in (200, 201), r.text
    hd = auth_headers(dtoken)
    assert client.post(f"/api/v1/orders/{o['id']}/driver-ack", headers=hd).status_code in (200, 201)
    r = client.post(f"/api/v1/orders/{o['id']}/complete", json={"payment": "arrears"}, headers=hd)
    assert r.status_code in (200, 201), r.text

    # 把送达时刻钉成**当地 04:00**（= UTC 前一天 20:00）：这条单在"当地日窗口"里，
    # 而它的 UTC 时刻在裸窗口 [当天 00:00, 23:59] 之外 —— 只有换算过才看得到它。
    from app.models import Order

    db_session.expire_all()
    row = db_session.get(Order, o["id"])
    local_4am = _dt.combine(business_date(row.delivered_at), _time(4, 0), tzinfo=BUSINESS_TZ)
    row.delivered_at = local_4am.astimezone(_tz.utc)
    db_session.commit()
    assert business_date(row.delivered_at).isoformat() == anchor, "基准日必须仍是同一天"

    after = Decimal(str(client.get(query, headers=h).json()["total_freight"]))
    delta = after - before
    assert delta == Decimal("100.00"), (
        f"营业纵览这一格增加了 {delta}；应当是司机应得 100（订单运费是 1000，那是虚高）"
    )

    # 与「司机运费结算」页同源（它一直是按 driver_pay 算的）
    fs = client.get(
        f"/api/v1/freight-settlement?from={anchor}T00:00:00&to={anchor}T23:59:59", headers=h
    ).json()
    settle = sum((Decimal(str(g["total"])) for g in fs["groups"]), Decimal("0"))
    assert settle == Decimal("100.00"), (
        f"结算页没算到这张「当地 04:00 送达」的单（{settle}）：客户端传的是**当地**窗口，"
        "必须换算成 UTC 再去比 delivered_at（R12-M11）"
    )
    assert after == settle, f"报表 {after} 与运费结算页 {settle} 不一致（两边都叫司机运费支出）"


# ------------------------------------- R12-M11 报表按业务当地日分桶
def test_turnover_buckets_by_business_day_not_utc(client, token_dispatcher, db_session):
    """把送达时刻定成"当地 09-19 04:00 = UTC 09-18 20:00"，它必须落进 **09-19** 的日报。

    这条是**确定性**的（不依赖"现在几点"），钉的是分桶的接线：
    注入"改回 `o.delivered_at.date()`"之后它会立刻报红。
    """
    from datetime import datetime as _dt

    from app.api.v1.reports import build_turnover
    from app.models import Order, OrderStatus

    h = auth_headers(token_dispatcher)
    d19 = date(2026, 9, 19)
    d18 = date(2026, 9, 18)
    before19 = build_turnover(db_session, "day", d19)["total_amount"]
    before18 = build_turnover(db_session, "day", d18)["total_amount"]

    o = _mk_order(client, h, address_detail="分桶探针路 1 号")
    db_session.expire_all()
    row = db_session.get(Order, o["id"])
    row.status = OrderStatus.DELIVERED
    # UTC 2026-09-18 20:00 == 业务当地 2026-09-19 04:00
    row.delivered_at = _dt(2026, 9, 18, 20, 0)
    db_session.commit()

    after19 = build_turnover(db_session, "day", d19)["total_amount"]
    after18 = build_turnover(db_session, "day", d18)["total_amount"]
    assert after19 - before19 == Decimal("100"), (
        f"当地 09-19 凌晨送达的单没算进 09-19 的日报（差 {after19 - before19}）"
    )
    assert after18 - before18 == Decimal("0"), "这一单被算进了前一天的日报（UTC 分桶的老行为）"


def test_business_date_buckets_utc_into_local_day():
    """UTC 时刻 → **业务当地日**：东八区当地 00:00~08:00 送达的单算**当天**。

    不修的话：早上 7 点打开「今天的营业纵览」看到的是 0（单被算进了前一天），
    而同一批单在「司机运费结算」页里明明在——两个页面都不报错。
    """
    from datetime import datetime, timezone

    from app.core.business_time import BUSINESS_TZ, business_date

    # 当地 2026-09-19 04:00 = UTC 2026-09-18 20:00
    assert BUSINESS_TZ.utcoffset(None).total_seconds() == 8 * 3600
    assert business_date(datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)) == date(2026, 9, 19)
    # 库里读回来是 naive（SQLite）：按"写进去的就是 UTC"处理，结果必须一致
    assert business_date(datetime(2026, 9, 18, 20, 0)) == date(2026, 9, 19)
    # 边界：当地 00:00（= UTC 前一天 16:00）算新的一天；当地 23:59 还算当天
    assert business_date(datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc)) == date(2026, 9, 19)
    assert business_date(datetime(2026, 9, 19, 15, 59, tzinfo=timezone.utc)) == date(2026, 9, 19)
    assert business_date(datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)) == date(2026, 9, 20)
    assert business_date(None) is None


def test_turnover_freight_shape_uses_pay_for_order():
    """形状断言：turnover 的 freight 必须来自 `pay_for_order`（与账单/结算页同源）。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app/api/v1/reports.py").read_text(encoding="utf-8")
    body = src.split("def build_turnover", 1)[1].split("\ndef ", 1)[0]
    assert "pay_for_order(" in body, "营业纵览的司机运费支出没有走 pay_for_order"
    assert "o.freight_fee or Decimal" not in body, "营业纵览仍在累加订单运费（虚高）"


# ------------------------------- R12-M3 已送达订单的账本行不许改钱、不许删
def test_delivered_order_ledger_row_cannot_be_edited_or_deleted(client, token_dispatcher, db_session):
    from app.models import Ledger, OrderStatus

    h = auth_headers(token_dispatcher)
    o = _mk_order(client, h, address_detail="审计探针路 3 号")
    _set_status(db_session, o["id"], OrderStatus.DELIVERED)
    ledger_id = _add_order_ledger_row(db_session, o["id"], 2)

    r = client.patch(f"/api/v1/ledger/entries/{ledger_id}", json={"total": 500}, headers=h)
    assert r.status_code == 400, f"已送达订单的账本行不该能改金额：{r.status_code} {r.text}"
    assert "已送达" in r.json()["detail"], r.json()

    r = client.delete(f"/api/v1/ledger/entries/{ledger_id}", headers=h)
    assert r.status_code == 400, f"已送达订单的账本行不该能删：{r.status_code} {r.text}"

    db_session.expire_all()
    still = db_session.get(Ledger, ledger_id)
    assert still is not None and Decimal(still.total) == Decimal("100"), "被拒绝的改动却真的落库了"


def test_manual_ledger_row_still_editable_and_deletable(client, token_dispatcher, db_session):
    """反向对照：手工行不受这条限制（守卫只针对**订单来的**行）。"""
    from app.models import Ledger, LedgerSource

    h = auth_headers(token_dispatcher)
    row = Ledger(
        source=LedgerSource.MANUAL,
        shipper_id=2,
        product_name="手工探针",
        quantity=1,
        unit_price=Decimal("10"),
        total=Decimal("10"),
        entry_date=date(2026, 9, 19),
    )
    db_session.add(row)
    db_session.commit()

    r = client.patch(f"/api/v1/ledger/entries/{row.id}", json={"total": 20}, headers=h)
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["total"]) == Decimal("20")
    assert client.delete(f"/api/v1/ledger/entries/{row.id}", headers=h).status_code in (200, 204)


def test_ledger_edit_log_records_before_and_after(client, token_dispatcher, db_session):
    """改钱必须留下"改前是多少"（原来 payload 里只有 ledger_id）。"""
    from app.models import Ledger, LedgerSource, OperationAction, OperationLog

    h = auth_headers(token_dispatcher)
    row = Ledger(
        source=LedgerSource.MANUAL,
        shipper_id=2,
        product_name="留痕探针",
        quantity=1,
        unit_price=Decimal("10"),
        total=Decimal("10"),
        entry_date=date(2026, 9, 19),
    )
    db_session.add(row)
    db_session.commit()
    r = client.patch(f"/api/v1/ledger/entries/{row.id}", json={"total": 20}, headers=h)
    assert r.status_code == 200, r.text

    log = (
        db_session.query(OperationLog)
        .filter_by(action=OperationAction.LEDGER_UPDATE)
        .order_by(OperationLog.id.desc())
        .first()
    )
    assert log is not None and log.change_content is not None
    assert '"before"' in log.change_content and '"after"' in log.change_content, log.change_content
    assert "10" in log.change_content and "20" in log.change_content, log.change_content


# ------------------------- R12-M4 滚动收款绑了订单也要对得上金额
def _mk_customer(client, h, name: str = "滚动收款探针客户") -> int:
    r = client.post(
        "/api/v1/customers",
        json={"name": name, "phone": "13700009999", "user_id": 2},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_rolling_receipt_with_orders_requires_matching_amount(client, token_dispatcher, db_session):
    from app.models import Order, OrderStatus

    h = auth_headers(token_dispatcher)
    cust_id = _mk_customer(client, h)
    ids = []
    for i in (1, 2):
        o = _mk_order(
            client,
            h,
            address_detail=f"滚动探针路 {i} 号",
            lines=[{"product_name_snapshot": "探针货", "quantity": 1, "unit_price": "5000", "line_total": "5000"}],
        )
        _set_status(db_session, o["id"], OrderStatus.DELIVERED)
        ids.append(o["id"])

    body = {
        "customer_id": cust_id,
        "received_at": "2026-09-19",
        "settle_mode": "rolling",
        "method": "cash",
        "order_ids": ids,
    }
    # 金额与两张单合计（10000）不一致 → 必须拒绝，且**订单不许被标已收**
    r = client.post("/api/v1/ledger/receipts", json={**body, "amount": 1}, headers=h)
    assert r.status_code == 400, f"金额对不上却接受了：{r.status_code} {r.text}"
    db_session.expire_all()
    unpaid = db_session.query(Order).filter(Order.id.in_(ids), Order.paid.is_(False)).count()
    assert unpaid == 2, "被拒绝的收款却把订单标成了已收款（差额被静默抹掉）"

    # 金额对得上时照常成功（守卫不能把正常用法挡住）
    r = client.post("/api/v1/ledger/receipts", json={**body, "amount": 10000}, headers=h)
    assert r.status_code in (200, 201), r.text


# --------------------------------- R12-A1 导出下载端点真的能下载
def test_export_download_returns_the_file(client, token_dispatcher, token_shipper, db_session):
    """真的下载一次（原来这里读 `job.download_url`——模型上没这个属性 → 必然 500）。"""
    import io
    import zipfile
    from pathlib import Path as _P

    from app.models import LedgerExportJob, User
    from app.models.export_job import ExportFormat, ExportJobStatus
    from app.services.ledger_export_paths import EXPORT_DIR, export_file_name

    db_session.expire_all()
    shipper = db_session.query(User).filter_by(phone="13800000002").first()
    job = LedgerExportJob(
        created_by_id=shipper.id,
        shipper_id=shipper.id,
        file_format=ExportFormat.EXCEL,
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        status=ExportJobStatus.DONE,
    )
    db_session.add(job)
    db_session.commit()

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    name = export_file_name(shipper.id, job.id, "excel")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
    (_P(EXPORT_DIR) / name).write_bytes(buf.getvalue())
    job.file_path = name
    db_session.commit()

    try:
        r = client.get(f"/api/v1/ledger/export-jobs/{job.id}/download", headers=auth_headers(token_shipper))
        assert r.status_code == 200, f"导出产物下载不了：{r.status_code} {r.text}"
        assert r.content[:2] == b"PK", "下载到的不是 xlsx（zip）内容"
        assert ".xlsx" in (r.headers.get("content-disposition") or ""), r.headers

        # 没登录必须拒绝（这条端点存在的意义就是"带鉴权才给"）
        assert client.get(f"/api/v1/ledger/export-jobs/{job.id}/download").status_code in (401, 403)

        # 别的货主不许下（归属校验）
        from app.models import User as U
        from app.services.auth_service import issue_token

        other = U(phone="13700008888", username="13700008888", password_hash="x", role="shipper", full_name="别人")
        db_session.add(other)
        db_session.commit()
        r2 = client.get(
            f"/api/v1/ledger/export-jobs/{job.id}/download", headers=auth_headers(issue_token(other))
        )
        assert r2.status_code == 403, f"别人能下载这条导出：{r2.status_code}"
    finally:
        (_P(EXPORT_DIR) / name).unlink(missing_ok=True)
