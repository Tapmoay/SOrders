"""订单详情「司机」那一行的手机号：**要能直接拨出去**（2026-09-22）。

## 由来
用户 2026-09-22：「加一个功能就是在订单详情的界面当中**可以拨打司机电话**……这个功能显示
**只会在派单端里**，其他人是没有的，也就是点击一个**拨号按钮**，它**自动弹到那个拨号界面**，
然后可以拨号打电话给司机」。

App 侧加的是 `ui/order/OrderDetailScreen.kt::DriverRow` 里那颗按钮，它拨的是**后端下发的**
`driver_phone`。于是这条出参多了一个用户看得见的要求：**它必须是一个拨得出去的号**。

## 为什么原来下发的可能不是
`DELETE /users/{id}` 是软删（`services/soft_delete.py::del_suffix`：`13800001234` →
`13800001234_del160`，为的是把号码释放给新账号用），而**这个司机早先拉过的单仍然挂着他的
`driver_id`** —— `services/order_response.py::enrich_order_out` 原来直接取 `du.phone`，
于是把那个带后缀的串印在详情页上。同一处理已在两处做过
（`api/v1/ledger.py`、`api/v1/freight_settlement.py`），这里是第三个消费点。

## 这条判据为什么必须是测试
`13800001234_del160` 在界面上**看不出来是"删除功能"干的** —— 它读起来只像一个存脏了的号码，
而它偏偏位于一颗**拨号按钮**底下：用户按下去才知道打不通，那时人已经不在手机旁边了。
反向的写法（"顺手把 driver_phone 置 None"）同样会被这里拦下：`None` 等于这一行**没有号码**。
"""
from __future__ import annotations

from app.models import User
from tests.conftest import auth_headers


def _make_user(client, h, phone: str, name: str, role: str = "driver") -> int:
    r = client.post(
        "/api/v1/users",
        json={
            "phone": phone,
            "password": "pass12345",
            "full_name": name,
            "role": role,
            "billing_mode": "PIECE",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _one_order(client, h, shipper_id: int) -> int:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [
                {
                    "product_name_snapshot": "司机电话探针商品",
                    "quantity": 1,
                    "unit_price": "100",
                    "line_total": "100",
                }
            ],
            "address_detail": "司机电话探针地址",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _assign(client, h, order_id: int, driver_id: int) -> None:
    r = client.post(
        f"/api/v1/orders/{order_id}/assign",
        json={"driver_id": driver_id, "freight_fee": "100"},
        headers=h,
    )
    assert r.status_code == 200, r.text


def _detail(client, h, order_id: int) -> dict:
    r = client.get(f"/api/v1/orders/{order_id}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_司机账号进了回收站_订单详情下发的号码仍然拨得出去(client, token_dispatcher, users, db_session):
    """软删司机之后，他历史订单上的 `driver_phone` 要**去尾**再下发。

    ⚠️ 用**新造的司机**，不动夹具里那个：夹具是会话级的（测试库最后才 drop），
       删掉夹具司机 = 后面所有用例的前提被改掉（这条教训在
       `test_user_search_and_ledger_account_card.py` 里已经吃过一次）。
    """
    h = auth_headers(token_dispatcher)
    did = _make_user(client, h, "13900009999", "电话探针司机")
    oid = _one_order(client, h, users["shipper"].id)
    _assign(client, h, oid, did)

    # ① 前提：没删之前就是个正常号码（否则下面的断言可能是在"证明本来就对"）
    before = _detail(client, h, oid)
    assert before["driver_phone"] == "13900009999", f"派单之后应下发完整号码：{before['driver_phone']!r}"
    assert before["driver_name"] == "电话探针司机"

    # ② 走**真实的删除端点**造状态（不是手改字段 —— 手改证明不了"删除会加后缀"这件事）
    r = client.delete(f"/api/v1/users/{did}", headers=h)
    assert r.status_code in (200, 204), r.text
    db_session.expire_all()
    raw = db_session.get(User, did)
    assert raw is not None, "软删不该把那一行删掉（历史订单还要靠它认人）"
    assert str(raw.phone).endswith(f"_del{did}"), (
        f"删除端点应给手机号加软删后缀，实际 {raw.phone!r} —— 若这里已经不这么做了，"
        "本用例的前提变了，要重新想『订单上那个号码怎么保证能拨』"
    )

    # ③ 正题：详情页拿到的必须是**能拨的号**，不是库里的原样值
    after = _detail(client, h, oid)
    assert after["driver_phone"] == "13900009999", f"软删后缀没去干净：{after['driver_phone']!r}"
    assert after["driver_name"] == "电话探针司机", "去尾不该把名字也弄没"
