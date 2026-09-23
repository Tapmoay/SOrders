"""「我的账本」顶上那段**收支统计**（2026-09-22 用户要求：账本的统计对货主与批发商也做）。

## 这份测试真正要钉住的是什么

不是"端点能算"，而是三件**不报错但会算错**的事：

1. **不许受列表截断影响**：这一页的订单列表是带 limit 的一页，统计要是从那一页加出来的，
   单子一多它就**偏小**（期① 审计里"客户端求和少算 62%"是同一个形状）。
   所以 `test_统计不受列表截断影响` 用 `limit=1` 拉列表、同时断言统计里的单数是**全量**。
2. **两个方向不许串**：下游那本账（批发商自己记的核销）**一个字节都不写**公司那本
   —— 所以核销之后"我该付的"三个数**一分钱都不许动**。
3. **窗口与列表同集合**：按**送达日**开窗（不是下单日），否则会出现
   「8-31 下单、9-1 送达」的单在列表里、却不在合计里。

## ⚠️ 每个用例都用**自己那个下游货主**筛一遍
测试库在**同一次运行里是累积的**（别的用例也下了单）。所以每条断言都带
`customer_name/customer_phone`（每个用例一个唯一名字），否则"应付 == 100"会被上一批单顶成 240。
"""
from __future__ import annotations

import pytest

from tests.conftest import auth_headers

BASE = "/api/v1/shipper-ledger/summary"


@pytest.fixture
def member(users, db_session):
    """把开发货主账号变成**批发商**（他才有下游那本账）。"""
    u = users["shipper"]
    u.is_member = True
    db_session.commit()
    return u


#: 用例之间避免互相污染：每个用例用自己那个货主名 + 电话筛。
_NAME_SEQ = {"n": 0}


def _next_customer(tag: str) -> tuple[str, str]:
    _NAME_SEQ["n"] += 1
    n = _NAME_SEQ["n"]
    return f"统计{tag}{n}", f"1350000{n:04d}"


def _delivered_order(
    client,
    h,
    users,
    *,
    disp_h,
    dongjia: str,
    dongjia_phone: str,
    lines: list[dict] | None = None,
    pay: str = "arrears",
    collect_cash: bool = False,
) -> int:
    """造一张**已送达**的订单（缺省两行：白菜 2×10=20、萝卜 3×20=60 = 80）。"""
    body_lines = lines or [
        {"product_name_snapshot": "白菜", "quantity": 2, "unit_price": "10"},
        {"product_name_snapshot": "萝卜", "quantity": 3, "unit_price": "20"},
    ]
    r = client.post(
        "/api/v1/orders",
        json={
            # ⚠️ **不传 `shipper_id`**：这是**他自己**下单（货主给自己下单无需指定货主，传了反而 400）。
            "lines": body_lines,
            "address_detail": "统计测试地址",
            "contact_dongjia_name": dongjia,
            "contact_dongjia_phone": dongjia_phone,
            "contact_boss_name": "永盛食品",
            "contact_boss_phone": "13800000002",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])

    dtok = client.post(
        "/api/v1/auth/login", json={"phone": users["driver"].phone, "password": "pass12345"}
    ).json()["access_token"]
    # ⚠️ 派单那一步是**派单员**的权限（货主自己的 token 会被 403）
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        json={
            "driver_id": users["driver"].id,
            "freight_fee": "20",
            # 现场收现金要先在派单时勾「收取现金」（否则司机端只能挂账）
            "collect_cash": collect_cash,
        },
        headers=disp_h,
    ).status_code == 200
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(dtok)).status_code == 200
    done = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/ledger-stats.jpg"], "payment": pay},
        headers=auth_headers(dtok),
    )
    assert done.status_code == 200, done.text
    return oid


def _summary(client, h, **params) -> dict:
    r = client.get(BASE, headers=h, params={k: v for k, v in params.items() if v is not None})
    assert r.status_code == 200, r.text
    return r.json()


def test_普通货主只有支出侧_三个数自洽(client, token_shipper, token_dispatcher, users, db_session):
    """应付 = 已付 + 还欠（订单出参那个恒等式的同一套数）；普通货主收入侧恒为 0。"""
    # ⚠️ 开发货主账号被别的用例（`member` fixture）提成过批发商，**用例之间共用一张库** ——
    #    这条断言依赖"他此刻是普通货主"，所以必须自己显式退回，不能靠"我的文件排在前面"
    #    （2026-09-23 第 16 轮：新加的文件名字母序更靠前，这条就红了 —— 判据本身是对的）。
    users["shipper"].is_member = False
    db_session.commit()
    h = auth_headers(token_shipper)
    disp_h = auth_headers(token_dispatcher)
    name, phone = _next_customer("A")
    oid = _delivered_order(client, h, users, disp_h=disp_h, dongjia=name, dongjia_phone=phone)
    s = _summary(client, h, customer_name=name, customer_phone=phone)
    assert s["is_member"] is False
    # 收入侧：他是给自己下单，系统里没有他的进账
    assert (s["receivable"], s["received"], s["unreceived"], s["settlements"]) == ("0.00", "0.00", "0.00", 0)
    # 支出侧：**货款 80**（运费不进他与公司之间的账，见端点 docstring）− 已付（0）＝ 还欠
    assert s["payable"] == "80.00"
    assert s["paid"] == "0.00"
    assert s["unpaid"] == "80.00"
    assert s["orders"] == 1
    # 与**订单出参**里那个数同源（同一份 `order_money`）
    order = client.get(f"/api/v1/orders?limit=1", headers=h).json()
    assert order[0]["id"] == oid
    assert str(order[0]["arrears_amount"]) == "80.00"


def test_统计不受列表截断影响(client, token_shipper, token_dispatcher, users):
    """⛔ 这张卡存在的**全部理由**：列表只取一页时，统计仍然是全量。"""
    h = auth_headers(token_shipper)
    disp_h = auth_headers(token_dispatcher)
    name, phone = _next_customer("B")
    _delivered_order(client, h, users, disp_h=disp_h, dongjia=name, dongjia_phone=phone)
    _delivered_order(client, h, users, disp_h=disp_h, dongjia=name, dongjia_phone=phone)
    listed = client.get("/api/v1/orders?limit=1", headers=h)
    assert listed.status_code == 200
    assert len(listed.json()) == 1, "列表被限制成 1 条（这正是客户端求和会偏小的场景）"
    s = _summary(client, h, customer_name=name, customer_phone=phone)
    assert s["orders"] == 2, "统计必须是窗口内的**全量**单数，不是取到的那一页"
    assert s["payable"] == "160.00", "两单各 80（货款），统计要都算上"


def test_批发商_收入侧是下游那本账(client, token_shipper, token_dispatcher, users, member):
    """核销之后「已收」涨、「待收」落，而「我该付的」**一分钱都不动**（两本账不许串）。"""
    h = auth_headers(token_shipper)
    disp_h = auth_headers(token_dispatcher)
    name, phone = _next_customer("C")
    oid = _delivered_order(client, h, users, disp_h=disp_h, dongjia=name, dongjia_phone=phone)
    before = _summary(client, h, customer_name=name, customer_phone=phone)
    assert before["is_member"] is True
    assert before["receivable"] == "80.00"      # 货款（不含运费）
    assert before["received"] == "0.00"
    assert before["unreceived"] == "80.00"
    assert before["settlements"] == 0
    payable_before = (before["payable"], before["paid"], before["unpaid"])

    r = client.post(
        "/api/v1/shipper-ledger/settlements",
        json={"order_id": oid, "method": "cash"},
        headers=h,
    )
    assert r.status_code == 201, r.text

    after = _summary(client, h, customer_name=name, customer_phone=phone)
    assert after["received"] == "80.00"
    assert after["unreceived"] == "0.00"
    assert after["settlements"] == 1
    assert (after["payable"], after["paid"], after["unpaid"]) == payable_before, (
        "核销只记在批发商自己那一本账上，公司那边的三个数不许动"
    )


def test_撤销核销之后统计跟着退回去(client, token_shipper, token_dispatcher, users, member):
    h = auth_headers(token_shipper)
    disp_h = auth_headers(token_dispatcher)
    name, phone = _next_customer("D")
    oid = _delivered_order(client, h, users, disp_h=disp_h, dongjia=name, dongjia_phone=phone)
    sid = client.post(
        "/api/v1/shipper-ledger/settlements", json={"order_id": oid, "method": "cash"}, headers=h
    ).json()["id"]
    assert _summary(client, h, customer_name=name, customer_phone=phone)["received"] == "80.00"

    assert client.delete(f"/api/v1/shipper-ledger/settlements/{sid}", headers=h).status_code == 204
    gone = _summary(client, h, customer_name=name, customer_phone=phone)
    assert gone["received"] == "0.00"
    assert gone["unreceived"] == "80.00"
    assert gone["settlements"] == 0

    assert client.post(f"/api/v1/shipper-ledger/settlements/{sid}/restore", headers=h).status_code == 200
    assert _summary(client, h, customer_name=name, customer_phone=phone)["received"] == "80.00"


def test_按货主筛_同名不同电话不许合并(client, token_shipper, token_dispatcher, users, member):
    """归属人的键是**名字 + 电话**：只按名字会把两个"张老板"并成一个（欠款翻倍）。"""
    h = auth_headers(token_shipper)
    disp_h = auth_headers(token_dispatcher)
    _NAME_SEQ["n"] += 1
    n = _NAME_SEQ["n"]
    same_name = f"张老板{n}"
    _delivered_order(client, h, users, disp_h=disp_h, dongjia=same_name, dongjia_phone=f"1350000{n:04d}")
    _delivered_order(client, h, users, disp_h=disp_h, dongjia=same_name, dongjia_phone=f"1350001{n:04d}")
    one = _summary(client, h, customer_name=same_name, customer_phone=f"1350000{n:04d}")
    assert one["orders"] == 1
    assert one["payable"] == "80.00"
    # 只给名字（电话为空）→ 按"名字相同且电话也为空"查，两个张老板都不该被算进来
    both = _summary(client, h, customer_name=same_name)
    assert both["orders"] == 0
    assert both["payable"] == "0.00"


def test_窗口按送达日(client, token_shipper, token_dispatcher, users):
    """窗口是**送达日**：窗口外的单一个都不算（「全部」那一档不传参 = 不加条件）。"""
    h = auth_headers(token_shipper)
    disp_h = auth_headers(token_dispatcher)
    name, phone = _next_customer("E")
    _delivered_order(client, h, users, disp_h=disp_h, dongjia=name, dongjia_phone=phone)
    out = _summary(
        client, h, customer_name=name, customer_phone=phone,
        delivered_from="2000-01-01", delivered_to="2000-01-31",
    )
    assert out["orders"] == 0
    assert _summary(client, h, customer_name=name, customer_phone=phone)["orders"] == 1


def test_回收站里的单不算(client, token_shipper, token_dispatcher, users):
    """软删的单要真实地退出统计（他连列表都进不去，钱却还算在他头上就是两套账）。"""
    h = auth_headers(token_shipper)
    disp_h = auth_headers(token_dispatcher)
    name, phone = _next_customer("F")
    oid = _delivered_order(client, h, users, disp_h=disp_h, dongjia=name, dongjia_phone=phone)
    assert _summary(client, h, customer_name=name, customer_phone=phone)["payable"] == "80.00"
    assert client.delete(f"/api/v1/orders/{oid}", headers=h).status_code in (200, 204)
    after = _summary(client, h, customer_name=name, customer_phone=phone)
    assert after["payable"] == "0.00", "进了回收站的单不该还算进「我该付的」"
    assert after["orders"] == 0


def test_派单员与司机读不到(client, token_dispatcher, token_driver):
    """这是**他自己**那一本账：别人（包括派单员）不该从这里读到他欠多少。"""
    assert client.get(BASE, headers=auth_headers(token_dispatcher)).status_code == 403
    assert client.get(BASE, headers=auth_headers(token_driver)).status_code == 403


def test_已付的口径含现场收现金(client, token_shipper, token_dispatcher, users):
    """`paid` 取的是 `order_money` 的净已收 —— 现场收现金**没有流水**，只有它算得对。"""
    h = auth_headers(token_shipper)
    disp_h = auth_headers(token_dispatcher)
    name, phone = _next_customer("G")
    _delivered_order(
        client, h, users, disp_h=disp_h, dongjia=name, dongjia_phone=phone, pay="cash", collect_cash=True
    )
    s = _summary(client, h, customer_name=name, customer_phone=phone)
    assert s["paid"] == "80.00"
    assert s["unpaid"] == "0.00"
    assert s["cleared_orders"] == 1
