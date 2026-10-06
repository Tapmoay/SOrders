"""台账 L-32：下单 / 改单时「收货人 或 下单人」四个联系字段**不能全空**（用户 m01132/m01242）。

用户原话（台账 `_tmp/USER_BUG_LEDGER_20261006.md` 的 L-32 段）：
> 「这个**是不可能存在**的 —— **无主账是不可能存在的**……我们在**下单的时候也会做个限制：
> 两个必须选一个，必须要有一个是有信息的**。」
> 「然后**干脆后端也拦一下**吧，就是**保险一点**。」

这一份盯的是**后端命令层的硬拦**（三重拦截的第二重；第一重在下单页、第三重在 AI 的规范里）：
判据只有一处实现（`app/services/order_contact.py::contact_info_missing`），四个落点都调它 ——
`create_order` / `update_order`（按**合并后的结果**判）/ `_create_target_order` /
`order_flow.split_order`（"继承后仍为空 ⇒ 拦"）。

⛔ 不做数据库约束（存量空单会被迁移炸掉）；存量空单照旧由 L-28 的异常单流程让人补。
"""

from __future__ import annotations

from app.models import Order
from app.models.enums import OrderStatus
from app.services.order_contact import CONTACT_INFO_REQUIRED
from tests.conftest import auth_headers


def _payload(**over) -> dict:
    payload: dict = {
        "lines": [
            {
                "product_name_snapshot": "联系信息必填测试货",
                "quantity": 2,
                "unit_price": "5",
                "line_total": "10",
            }
        ],
        "address_detail": "联系信息必填测试地址",
    }
    payload.update(over)
    return payload


def _post(client, token: str, **over):
    return client.post("/api/v1/orders", json=_payload(**over), headers=auth_headers(token))


def test_货主自己下单四个联系字段全空时被拒(client, token_shipper) -> None:
    """货主自己下单**不走**「下单人＝货主」兜底那一段 ⇒ 全空就是全空，当场拒。"""
    r = _post(client, token_shipper)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == CONTACT_INFO_REQUIRED


def test_全空格不算填了(client, token_shipper) -> None:
    """口径与账本 SQL 的 `nullif(trim(...))` 一致：全是空格 = 空。"""
    r = _post(client, token_shipper, contact_dongjia_name="   ", contact_boss_phone=" ")
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == CONTACT_INFO_REQUIRED


def test_只填收货人姓名就能下单(client, token_shipper) -> None:
    r = _post(client, token_shipper, contact_dongjia_name="收货人甲")
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["contact_dongjia_name"] == "收货人甲"
    # ⛔ 顺带钉住"后端不替他补下单人"（与 test_order_boss_contact.py 同一条口径）
    assert out["contact_boss_name"] == ""
    assert out["contact_boss_phone"] == ""


def test_只填下单人电话就能下单(client, token_shipper) -> None:
    r = _post(client, token_shipper, contact_boss_phone="13900002222")
    assert r.status_code == 201, r.text
    assert r.json()["contact_boss_phone"] == "13900002222"


def test_派单员代理下单仍由货主账号兜底(client, users, token_dispatcher) -> None:
    """判据在**兜底之后**跑 ⇒ 老版本 App / AI 下单不带这两栏也能建单（这是刻意的）。"""
    shipper = users["shipper"]
    r = _post(client, token_dispatcher, shipper_id=shipper.id)
    assert r.status_code == 201, r.text
    assert r.json()["contact_boss_name"] == shipper.full_name
    assert r.json()["contact_boss_phone"] == shipper.phone


def test_临时货主全空时被拒(client, token_dispatcher) -> None:
    """临时货主没有账号资料可兜底 ⇒ 联系信息只能由下单的人给。"""
    r = _post(client, token_dispatcher, temp_shipper_name="老王")
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == CONTACT_INFO_REQUIRED


def test_改单把最后一个联系方式改空会被拒(client, token_dispatcher, token_shipper) -> None:
    oid = int(_post(client, token_shipper, contact_dongjia_name="收货人甲").json()["id"])
    h = auth_headers(token_dispatcher)

    # ① 想把唯一的那个名字改空 ⇒ 拒（按**合并后的结果**判，不是只看请求体）
    r = client.patch(f"/api/v1/orders/{oid}", json={"contact_dongjia_name": ""}, headers=h)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == CONTACT_INFO_REQUIRED

    # ② 只改另一项（补一个电话）不受影响
    r2 = client.patch(f"/api/v1/orders/{oid}", json={"contact_dongjia_phone": "13900002222"}, headers=h)
    assert r2.status_code == 200, r2.text
    assert r2.json()["contact_dongjia_phone"] == "13900002222"

    # ③ 有了电话之后，再把这个名字改空是**允许**的（这一条证明判的是合并结果，不是"不许清空字段"）
    r3 = client.patch(f"/api/v1/orders/{oid}", json={"contact_dongjia_name": ""}, headers=h)
    assert r3.status_code == 200, r3.text
    assert r3.json()["contact_dongjia_name"] == ""


def test_拆单时父单四个字段全空会被拦(client, db_session, users, token_dispatcher) -> None:
    """存量空单不能再繁殖：拆单是最典型的繁殖路径（每张子单都继承父单的联系字段）。"""
    h = auth_headers(token_dispatcher)
    oid = int(
        _post(client, token_dispatcher, shipper_id=users["shipper"].id, contact_dongjia_name="收货人甲").json()["id"]
    )
    # 手工把它改回"校验上线之前的存量形状"（现在建不出这种单了）
    db_session.expire_all()
    row = db_session.get(Order, oid)
    assert row is not None
    row.contact_dongjia_name = ""
    row.contact_dongjia_phone = ""
    row.contact_boss_name = ""
    row.contact_boss_phone = ""
    db_session.commit()

    r = client.post(f"/api/v1/orders/{oid}/split", json={"parts": [1, 1]}, headers=h)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == CONTACT_INFO_REQUIRED

    db_session.expire_all()
    assert db_session.get(Order, oid).status == OrderStatus.PENDING_DISPATCH.value, (
        "拦的位置必须在**原子占位之前**：否则父单已经被改成 CANCELLED，用户看到的是'拆失败但单没了'"
    )


def test_拆单子单继承父单的两个名字(client, token_dispatcher, token_shipper) -> None:
    """⛔ 修的是一个真缺陷：子单原来只抄两个电话，两个**名字**一个都不抄 ⇒ 拆单会凭空丢掉归属。"""
    oid = int(
        _post(
            client,
            token_shipper,
            contact_dongjia_name="收货人甲",
            contact_boss_name="下单人乙",
        ).json()["id"]
    )
    r = client.post(
        f"/api/v1/orders/{oid}/split", json={"parts": [1, 1]}, headers=auth_headers(token_dispatcher)
    )
    assert r.status_code in (200, 201), r.text
    children = r.json()
    assert len(children) == 2
    for child in children:
        assert child["contact_dongjia_name"] == "收货人甲", child
        assert child["contact_boss_name"] == "下单人乙", child
