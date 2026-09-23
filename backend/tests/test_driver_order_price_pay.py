"""「拿这一单的钱」（`piece_unit="order_price"`）：一份**会算钱**的规则，送达时必须真的生成账单。

## 抓到的形状（2026-09-23 第 18 轮并行渗透 B2-1，高）

`driver_pay.order_pay` 对 `piece_unit="order_price"` 的算法是「这一单拿多少钱 = 这一单的运费」
（`order_price` 的用户口径见 `driver_pay` 模块头：「每单有多少钱，但每单是不固定的，
几百块、几十块，这些单价是由派单员来决定的」），而 `PayRule.has_per_order_pay` 判"这张单有没有
按单应付"时**只看三件**：按分类定价 / 每单金额 > 0 / 提成。`order_price` 三件都不占
（它按定义不能再填固定金额——`validate_rule_params` 明确拦着 "每单拿这一单的钱时不要再填固定每单金额"）
→ **判据为假**。于是派单那一刻：

| 步骤 | 结果 |
| --- | --- |
| `snapshot_mode(司机)` | 写 `SALARY` |
| 送达 `generate_piece_bill` | `has_per_order_pay(order)` 为假 → **直接 return，不生成账单、不报错、不写日志** |
| 同一张单的 `pay_for_order(order)` | 返回 **全额运费**（`pay.piece = fee`）—— 钱在算法里是有的 |

也就是说：**司机白跑，账面上查不到任何异常**。而且 `order_price` 的唯一入口是 AI
（`android/.../ai/AiWriteBasicData.kt`：「拿这一单的钱」→ `order_price`），人工表单里选不到 ——
所以这一条只在"用户让 AI 配一份按单定价的规则"时才会踩到，比看得见的崩溃难查得多。

## 判据（这一族已经在同一个文件里栽过一次）
`has_per_order_pay` 的注释记着**同一个坑的另一个形状**：「按分类定价时也必须算有，否则派单快照
写成 SALARY，送达时连账单都不生成」。本轮把漏掉的第三件（`order_price`）补上，并把这个
"每一件都必须能自己声明有没有按单应付"的形状钉在测试里 —— 加第四件（比如按里程）时，
本文件的第一条用例会提醒你它也得在这里出现。

## 为什么还要一条"账单真的生成了"的端到端用例
只断言 `has_per_order_pay is True` 是**断言了与自己同源的判据**（改坏了它还是绿）。
真正会出事的那一步是 `accounting_service.generate_piece_bill` 的早退，所以这里走
「挂规则 → 派单 → 接单 → 送达」真链路，最后去库里数那张 `driver_bills` 行。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.models import DriverBill, Order
from app.models.enums import DriverBillType
from app.services.driver_pay import PayRule, has_per_order_pay, snapshot_mode
from tests.conftest import auth_headers


def _rule(**kw) -> PayRule:
    base = dict(rule_id=1, name="探针规则", salary=Decimal("0"), piece_amount=Decimal("0"),
                piece_unit="order", commission_base="none", commission_rate=Decimal("0"))
    base.update(kw)
    return PayRule(**base)


# ---------------------------------------------------------------- ① 判据本身

def test_拿这一单的钱_必须有按单应付():
    """`order_price` = 这一单有一笔钱要给 → 判据必须为真（它按定义填不了固定金额）。"""
    r = _rule(piece_unit="order_price")
    assert r.has_per_order_pay is True, "判据为假 → 送达不生成账单（钱静默消失）"
    assert r.pays_nothing is False, "它是一份给钱的规则，不许被当成'一分钱都不给'"


def test_三件之外不许误伤():
    """反向：纯工资规则仍然"没有按单应付"（照它发月度工资单）。

    ⚠️ 这一条是**防改宽**的：把 `has_per_order_pay` 改成恒真是最容易的"修法"，
    而那样一来工资制司机每送一单都会多出一张 0 元按单账单。
    """
    assert _rule(salary=Decimal("6500")).has_per_order_pay is False
    assert _rule(salary=Decimal("6500")).pays_nothing is False      # 有工资 = 不是"不给钱"
    assert _rule().pays_nothing is True                             # 三件全空 = 真不给钱
    assert _rule(piece_amount=Decimal("200")).has_per_order_pay is True
    assert _rule(commission_base="freight", commission_rate=Decimal("5")).has_per_order_pay is True


def test_拿这一单的钱_一句话要说得出钱怎么算():
    """司机管理页那一列读的就是这句话。原来是「不计费」—— 与"他每单拿全额运费"正好相反。"""
    text = _rule(piece_unit="order_price").describe()
    assert "不计费" not in text, f"一份给钱的规则被说成「不计费」：{text}"
    assert "这一单" in text, f"没说清钱从哪来：{text}"


def test_拿这一单的钱_加固定工资也是按单计费():
    """用户 2026-09-18 的用法：固定工资 + 拿这一单的钱（两件同时给）。"""
    r = _rule(salary=Decimal("6000"), piece_unit="order_price")
    assert r.has_per_order_pay is True
    text = r.describe()
    assert "6000" in text and "这一单" in text, text


def test_有比例没基数要说清是哪一件缺():
    """存量数据里有这种行（名字叫「运费提成 8%」而 `commission_base=none`，校验上线前录的）。

    只说「不计费」的话，用户看不出是"没选提成基数"—— 他会以为这份规则本来就不给钱。
    """
    text = _rule(commission_rate=Decimal("8")).describe()
    assert "不计费" in text and "提成基数" in text, f"没说出哪一件缺：{text}"


def test_纯空规则仍然只说四个字():
    """真的什么都不给的规则，别硬凑一句解释。"""
    assert _rule().describe() == "不计费"


# ---------------------------------------------------------------- ② 真链路

def _mk_product(client, h, name: str) -> int:
    r = client.post(
        "/api/v1/products",
        json={"name": name, "default_unit_price": "10", "cost_price": "4", "stock": 100},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _mk_order(client, h, shipper_id: int, pid: int, price: str = "100") -> dict:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [
                {
                    "product_id": pid,
                    "product_name_snapshot": "按单定价探针货",
                    "quantity": 1,
                    "unit_price": price,
                    "line_total": price,
                }
            ],
            "address_detail": "按单定价探针地址",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _attach_order_price_rule(client, h, users) -> int:
    """给测试司机挂一份「拿这一单的钱」的规则，返回规则 id。

    ⚠️ 规则**名字必须唯一**（`POST /driver-billing-rules` 重名 409），而测试库跨用例保留
    （API 会 commit）—— 所以名字带随机段，否则第二个用例就撞 409。
    """
    import uuid

    driver = users["driver"]
    r = client.post(
        "/api/v1/driver-billing-rules",
        json={
            "name": f"探针 · 拿这一单的钱 · {uuid.uuid4().hex[:6]}",
            "vehicle_type": (driver.vehicle_type or None),
            "piece_unit": "order_price",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert "不计费" not in (body.get("summary") or ""), (
        f"规则出参 `summary` 说「不计费」：{body.get('summary')!r} —— 界面会照着它显示"
    )
    rule_id = body["id"]
    r = client.post(
        "/api/v1/driver-billing-rules/attach",
        json={"driver_id": driver.id, "rule_id": rule_id},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return rule_id


def test_拿这一单的钱_派单快照必须写成按单计费(client, db_session, users, token_dispatcher):
    h = auth_headers(token_dispatcher)
    _attach_order_price_rule(client, h, users)
    pid = _mk_product(client, h, "按单定价探针货·快照")
    order = _mk_order(client, h, users["shipper"].id, pid)
    r = client.post(
        f"/api/v1/orders/{order['id']}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "380"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    row = db_session.get(Order, order["id"])
    assert row.driver_billing_mode_snapshot == "PIECE", (
        "「拿这一单的钱」的司机被派单时快照写成了 "
        f"{row.driver_billing_mode_snapshot!r} —— 送达那一步据此决定生不生成账单"
    )


def test_拿这一单的钱_送达必须生成按单账单(client, db_session, users, token_dispatcher, token_driver):
    """端到端：挂规则 → 派单 → 接单 → 送达 → 库里必须有那张 PIECE 账单。"""
    h = auth_headers(token_dispatcher)
    hd = auth_headers(token_driver)
    _attach_order_price_rule(client, h, users)
    pid = _mk_product(client, h, "按单定价探针货·账单")
    order = _mk_order(client, h, users["shipper"].id, pid)
    r = client.post(
        f"/api/v1/orders/{order['id']}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "380"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/orders/{order['id']}/driver-ack", headers=hd).status_code == 200
    r = client.post(
        f"/api/v1/orders/{order['id']}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe-order-price.jpg"]},
        headers=hd,
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    bills = list(
        db_session.scalars(
            select(DriverBill).where(
                DriverBill.order_id == order["id"],
                DriverBill.bill_type == DriverBillType.PIECE,
            )
        ).all()
    )
    assert bills, (
        "「拿这一单的钱」的规则送达后**没有生成按单账单** —— "
        "司机白跑一趟，而订单、账单、结算页、绩效四处都不报错"
    )
    assert Decimal(str(bills[0].amount)) == Decimal("380.00"), (
        f"账单金额 {bills[0].amount} 应当等于这一单的钱（运费 380）"
    )


def test_纯工资规则送达不生成按单账单(client, db_session, users, token_dispatcher, token_driver):
    """反向防改宽：只拿固定工资的司机，送达不许凭空多出一张按单账单。"""
    import uuid

    h = auth_headers(token_dispatcher)
    hd = auth_headers(token_driver)
    r = client.post(
        "/api/v1/driver-billing-rules",
        json={
            "name": f"探针 · 只拿固定工资 · {uuid.uuid4().hex[:6]}",
            "vehicle_type": (users["driver"].vehicle_type or None),
            "salary": "6500",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    r = client.post(
        "/api/v1/driver-billing-rules/attach",
        json={"driver_id": users["driver"].id, "rule_id": r.json()["id"]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    pid = _mk_product(client, h, "按单定价探针货·工资制")
    order = _mk_order(client, h, users["shipper"].id, pid)
    r = client.post(
        f"/api/v1/orders/{order['id']}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "380"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/orders/{order['id']}/driver-ack", headers=hd).status_code == 200
    assert client.post(
        f"/api/v1/orders/{order['id']}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe-salary.jpg"]},
        headers=hd,
    ).status_code == 200

    db_session.expire_all()
    row = db_session.get(Order, order["id"])
    assert has_per_order_pay(row) is False
    assert snapshot_mode(users["driver"]) in ("SALARY", "PIECE"), "判据本身不许抛异常"
    bills = list(
        db_session.scalars(
            select(DriverBill).where(
                DriverBill.order_id == order["id"],
                DriverBill.bill_type == DriverBillType.PIECE,
            )
        ).all()
    )
    assert not bills, "工资制司机（这张单没有按单应付）不许有按单账单"
