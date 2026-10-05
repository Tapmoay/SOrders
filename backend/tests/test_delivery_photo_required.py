"""送达一律要照片：所有司机都走同一条「拍照送达」（台账 L-15，2026-10-06 用户 m00354）。

## 用户原话

「挂车……他也要拍照，同样的流程。」（m00354）

## 改之前会发生什么

`order_flow.complete_delivery` 那道照片门从前是「不带照片**且**这一单不按单拿钱」才拒：
工资制（月薪）的单可以不带照片完成 —— 而**挂车默认按单计费**，于是客户端那条
`if (order.freightVisible)` 的分支直接调 `POST /orders/{id}/complete`（空照片列表）就把单完成了：
账照入、库存照扣、司机账单照生成，**只是没有任何送达凭证**。

改之后：空照片列表**一律** 400「请至少上传一张送达照片」，与这一单怎么给司机结账无关。

## 这条测试同时钉住"别多删"

只撤**照片豁免**，不撤计费口径：`has_per_order_pay` / `order_mode` 仍是"钱那一侧"的判据
（按单账单、运费提醒在用）。所以下面既有"两种计费方式的单**都**被拦"，也有
"计费判据本身还在、答案没变" —— 否则很容易把 L-15 执行成把计费方式一起删掉，
而那件事**不会有任何测试报错**（账单只是算错，没人对）。

判据在 `_tools/qa/_check_all_drivers_photo.py`，反向验证 `_tools/qa/_reverse_verify_all_drivers_photo.py`。
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import DriverBill, Order, OrderStatus
from app.services.driver_pay import has_per_order_pay, order_mode
from tests.conftest import auth_headers

#: 合法凭证的形状：必须落在上传端点的产物前缀下（`order_flow.py` 的 L-14 那道门）。
PHOTO = "/static/uploads/delivery/probe.jpg"


# ------------------------------------------------------------------ 公共构造工具
def _mk_order(client, h, **over) -> dict:
    """用**真实接口**建单（照 `test_audit_round12_guards.py` 的写法，不手搓 ORM 行）。"""
    payload = {
        "shipper_id": 2,
        "lines": [
            {"product_name_snapshot": "探针货", "quantity": 1, "unit_price": "100", "line_total": "100"}
        ],
        "address_detail": "拍照门探针路 1 号",
        "freight_fee": "1000",
    }
    payload.update(over)
    r = client.post("/api/v1/orders", json=payload, headers=h)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _mk_driver(client, h, **extra) -> tuple[int, str]:
    """建一个**专用**司机（连同令牌）。`**extra` 直接进建号请求。

    例如 `billing_mode="SALARY", salary="5000"` 造一个工资制（不按单拿钱）司机 ——
    那正是改之前能免拍照的那一档。用专用司机而不是 fixture 里那个：给他挂计费规则会
    污染同一轮其它用例（`test_audit_round12_guards.py` 里有同样的教训）。
    """
    import uuid

    phone = "13" + uuid.uuid4().hex[:9].translate(str.maketrans("abcdef", "012345"))
    body = {"phone": phone, "password": "pass12345", "full_name": "拍照门探针司机", "role": "driver"}
    body.update(extra)
    r = client.post("/api/v1/users", json=body, headers=h)
    assert r.status_code in (200, 201), r.text
    driver_id = int(r.json()["id"])
    r = client.post("/api/v1/auth/login", json={"phone": phone, "password": "pass12345"})
    assert r.status_code == 200, r.text
    return driver_id, r.json()["access_token"]


def _attach_rule(client, h, driver_id: int, piece: str = "100") -> int:
    """挂一份「每单固定」的计费规则 → 这个司机就是按单结账的（改之前他也已经要照片）。"""
    body = {"name": f"拍照门探针规则-{driver_id}", "piece_amount": piece, "remark": "审计探针"}
    r = client.post("/api/v1/driver-billing-rules", json=body, headers=h)
    assert r.status_code in (200, 201), r.text
    rule_id = r.json()["id"]
    r = client.post(
        "/api/v1/driver-billing-rules/attach", json={"driver_id": driver_id, "rule_id": rule_id}, headers=h
    )
    assert r.status_code in (200, 201), r.text
    return rule_id


def _ready_order(client, h, driver_id: int, dtoken: str, **over) -> tuple[int, dict[str, str]]:
    """建单 → 派给这个司机 → 司机接单（走到「已接单」，也就是可送达的那一步）。"""
    o = _mk_order(client, h, **over)
    r = client.post(f"/api/v1/orders/{o['id']}/assign", json={"driver_id": driver_id}, headers=h)
    assert r.status_code in (200, 201), r.text
    hd = auth_headers(dtoken)
    r = client.post(f"/api/v1/orders/{o['id']}/driver-ack", headers=hd)
    assert r.status_code in (200, 201), r.text
    return int(o["id"]), hd


# ---------------------------------------------- 两道门：不带照片一律拒（不看计费方式）
def test_piece_driver_without_photo_is_rejected(client, token_dispatcher, db_session):
    """按单计费的司机：不带照片完成 → 400（改动前后都是拒，这条是"别把门拆了"）。"""
    h = auth_headers(token_dispatcher)
    driver_id, dtoken = _mk_driver(client, h)
    _attach_rule(client, h, driver_id, piece="100")
    oid, hd = _ready_order(client, h, driver_id, dtoken)

    db_session.expire_all()
    row = db_session.get(Order, oid)
    assert order_mode(row) == "PIECE" and has_per_order_pay(row) is True, "前提没造出来：这一单应当是按单结的"

    r = client.post(f"/api/v1/orders/{oid}/complete", json={"payment": "arrears"}, headers=hd)
    assert r.status_code == 400, r.text
    assert "请至少上传一张送达照片" in r.json()["detail"], r.text


def test_salary_driver_without_photo_is_rejected(client, token_dispatcher, db_session):
    """工资制（不按单拿钱）的司机：不带照片完成 → **同样 400**。

    ⛔ 改之前这一条是 200 —— 它就是「挂车可以免拍照」那个口子：
    挂车默认按单计费，界面上那条 `if (order.freightVisible)` 的分支点一下就把单完成了。
    用户 m00354 要撤的正是它，所以这条测试的失败方式就是"那个口子回来了"。
    """
    h = auth_headers(token_dispatcher)
    driver_id, dtoken = _mk_driver(client, h, billing_mode="SALARY", salary="5000")
    oid, hd = _ready_order(client, h, driver_id, dtoken)

    db_session.expire_all()
    row = db_session.get(Order, oid)
    assert order_mode(row) == "SALARY" and has_per_order_pay(row) is False, "前提没造出来：这一单应当不按单结"

    r = client.post(f"/api/v1/orders/{oid}/complete", json={"payment": "arrears"}, headers=hd)
    assert r.status_code == 400, r.text
    assert "请至少上传一张送达照片" in r.json()["detail"], r.text


def test_one_gate_two_billing_modes_same_answer(client, token_dispatcher, db_session):
    """一道门、两种计费方式、同一个答案；同时钉住「计费判据本身没被顺手删掉」。

    为什么把这两件事放在同一条测试里：它们是一对**互相拉扯**的判据 ——
    只测"两种都被拦"，把 `has_per_order_pay` 删掉也能绿（删了它就没人看计费方式了）；
    只测"计费判据还在"，把照片门退回旧口径（看计费方式）也能绿。两条一起才说明
    "撤的是照片豁免、不是计费方式"。
    """
    h = auth_headers(token_dispatcher)
    piece_driver, piece_token = _mk_driver(client, h)
    _attach_rule(client, h, piece_driver, piece="100")
    piece_order, piece_hd = _ready_order(client, h, piece_driver, piece_token)
    salary_driver, salary_token = _mk_driver(client, h, billing_mode="SALARY", salary="5000")
    salary_order, salary_hd = _ready_order(client, h, salary_driver, salary_token)

    db_session.expire_all()
    piece_row = db_session.get(Order, piece_order)
    salary_row = db_session.get(Order, salary_order)
    assert has_per_order_pay(piece_row) is True, "计费判据：按单的单说「按单」"
    assert has_per_order_pay(salary_row) is False, "计费判据：工资制的单说「不按单」"

    for oid, hd, mode in ((piece_order, piece_hd, "PIECE"), (salary_order, salary_hd, "SALARY")):
        r = client.post(f"/api/v1/orders/{oid}/complete", json={"payment": "arrears"}, headers=hd)
        assert r.status_code == 400, f"{mode} 那一单没被拦住：{r.status_code} {r.text}"
        assert "请至少上传一张送达照片" in r.json()["detail"]


# ------------------------------------------- 拒了就是拒了：这一单一个字段都没动过
def test_rejection_changes_nothing(client, token_dispatcher, db_session):
    """400 之后：状态还是「已接单」、没有送达时刻、**也没有多出一条司机账单**。

    为什么这条必须单独写：这道门在 `complete_delivery` 里的位置很靠前，
    但"很靠前"是读代码得出的印象 —— 一旦有人把它挪到状态跃迁或建账单之后，
    界面上、接口文案上**都看不出来**（一样是 400），只有钱变了。
    """
    h = auth_headers(token_dispatcher)
    driver_id, dtoken = _mk_driver(client, h, billing_mode="SALARY", salary="5000")
    oid, hd = _ready_order(client, h, driver_id, dtoken)

    def _bills() -> int:
        return len(list(db_session.scalars(select(DriverBill).where(DriverBill.order_id == oid))))

    db_session.expire_all()
    before_bills = _bills()
    r = client.post(f"/api/v1/orders/{oid}/complete", json={"payment": "arrears"}, headers=hd)
    assert r.status_code == 400, r.text

    db_session.expire_all()
    row = db_session.get(Order, oid)
    assert row.status == OrderStatus.ACCEPTED, f"被拒之后状态变了：{row.status}"
    assert row.delivered_at is None, "被拒之后却留下了送达时刻"
    assert _bills() == before_bills, "被拒之后却生成了司机账单（钱动了）"


# ----------------------------------------------------------- 门不是"一律拒"：带照片照常完成
def test_driver_with_photo_still_completes(client, token_dispatcher, db_session):
    """带一张合法凭证 → 200 且状态到「已送达」（含工资制那一档，它不是"永久不可完成"）。"""
    h = auth_headers(token_dispatcher)
    driver_id, dtoken = _mk_driver(client, h, billing_mode="SALARY", salary="5000")
    oid, hd = _ready_order(client, h, driver_id, dtoken)

    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"payment": "arrears", "delivery_photo_urls": [PHOTO]},
        headers=hd,
    )
    assert r.status_code in (200, 201), r.text

    db_session.expire_all()
    row = db_session.get(Order, oid)
    assert row.status == OrderStatus.DELIVERED, f"带照片却没送到：{row.status}"
    assert row.delivered_at is not None, "送到了却没有送达时刻"


def test_junk_photo_shape_is_still_rejected(client, token_dispatcher, db_session):
    """L-14 那道形状门还在：`["x"]` 这种随手编的字符串不算拍照。"""
    h = auth_headers(token_dispatcher)
    driver_id, dtoken = _mk_driver(client, h)
    _attach_rule(client, h, driver_id, piece="100")
    oid, hd = _ready_order(client, h, driver_id, dtoken)

    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"payment": "arrears", "delivery_photo_urls": ["x"]},
        headers=hd,
    )
    assert r.status_code == 400, r.text
    assert "必须是本系统上传的凭证" in r.json()["detail"], r.text
