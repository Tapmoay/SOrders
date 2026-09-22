"""代理下单的「下单人」＝**这一单的货主**（用户 2026-09-22 第二轮口述）。

用户原话：
> 「不是说下单吗？下单会**自动填入下单的人的名称和电话号码**，户主和批发商没关系，
> 因为他们是**自己下**嘛。但是这里有一点要注意的就是**派单员，他是代理下单**啊，
> 所以他**不能填写自己的名称和电话号码**，他要填的是**自动填选的是货主的**……
> **选择货主之后，他写的货主的信息就会自动地填入进去**，也就是名称和电话号码。」

App 侧在"选中货主"那一刻就填好了（`ui/shipper/OrdererPrefill.kt`，有 JVM 单测）。
这一份盯的是**后端那半边的兜底**（老版本 App / AI 下单不会带这两栏）：

1. 代理下单**两栏都空** → 用这位货主的姓名 + 电话补上（不是派单员自己）；
2. 代理下单**带了下单人** → 一个字都不改（"下单人是王老板"是真实场景）；
3. 代理下单**只带了一栏** → **不补**：名称与电话是同一个人，拆开拼会张冠李戴；
4. 货主自己下单 → 后端**不补**（那一路客户端填的就是他自己的账号资料）；
5. 「下单人」就是货主本人时，**不许**把他记进他自己的联系人名册（会天天长出一条"我自己"）；
6. 但下单人真的是**别人**（王老板）时，联系人照记（别把上面那条写成"一律不记"）。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Order, ShipperContact
from tests.conftest import auth_headers


def _create_order(client, token, **kw):
    body = {
        "lines": [
            {
                "product_name_snapshot": "下单人测试商品",
                "quantity": 1,
                "unit_price": "1",
                "unit": "",
            }
        ],
        "address_detail": "下单人测试地址",
    }
    body.update(kw)
    r = client.post("/api/v1/orders", json=body, headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()


def _contacts(db_session, shipper_id):
    return db_session.scalars(
        select(ShipperContact).where(ShipperContact.shipper_id == shipper_id)
    ).all()


#: 「下单人是别人」那条用例用的号码。⚠️ 测试库是**文件型**、跨轮不重建（踩过一次
#: `UNIQUE constraint failed`）：先把它清干净，这一条才既确定又能重复跑。
OTHER_PHONE = "13900001111"


def _purge(db_session, shipper_id, phone):
    for row in db_session.scalars(
        select(ShipperContact).where(
            ShipperContact.shipper_id == shipper_id, ShipperContact.phone == phone
        )
    ).all():
        db_session.delete(row)
    db_session.commit()


def test_代理下单没带下单人时用货主的姓名与电话(client, db_session, users, token_dispatcher):
    shipper = users["shipper"]
    out = _create_order(client, token_dispatcher, shipper_id=shipper.id)

    assert out["contact_boss_name"] == shipper.full_name
    assert out["contact_boss_phone"] == shipper.phone
    row = db_session.get(Order, out["id"])
    assert (row.contact_boss_name, row.contact_boss_phone) == (shipper.full_name, shipper.phone)


def test_代理下单带了下单人时一个字都不改(client, users, token_dispatcher):
    out = _create_order(
        client,
        token_dispatcher,
        shipper_id=users["shipper"].id,
        contact_boss_name="王老板",
        contact_boss_phone="13900001111",
    )
    assert out["contact_boss_name"] == "王老板"
    assert out["contact_boss_phone"] == "13900001111"


def test_代理下单只带一栏时不补另一栏(client, users, token_dispatcher):
    """名称与电话是**同一个人**的两个字段 —— 拆开拼会造出一个不存在的下单人。

    只补电话的后果：单子上写着「下单人：王老板 13800000002」，而 13800000002 是**货主账号**
    持有人（另一个人）的号码。派单员按这个名字去核，核出来的是别人。
    """
    only_name = _create_order(
        client, token_dispatcher, shipper_id=users["shipper"].id, contact_boss_name="王老板"
    )
    assert only_name["contact_boss_name"] == "王老板"
    assert only_name["contact_boss_phone"] == ""

    only_phone = _create_order(
        client, token_dispatcher, shipper_id=users["shipper"].id, contact_boss_phone="13900001111"
    )
    assert only_phone["contact_boss_name"] == ""
    assert only_phone["contact_boss_phone"] == "13900001111"


def test_货主自己下单时后端不补下单人(client, users, token_shipper):
    """货主自己下单：客户端填的是他自己的账号资料（同源），后端**不插手**。

    这条同时钉住"兜底别越界"：`target_shipper.id == current.id` 时一个字节都不写，
    否则"客户端明明填了空"会被悄悄盖成"填了货主"——而它到底是不是空的，只有客户端知道。
    """
    out = _create_order(client, token_shipper)
    assert out["contact_boss_name"] == ""
    assert out["contact_boss_phone"] == ""


def test_下单人就是货主本人时不进他自己的联系人名册(client, db_session, users, token_dispatcher):
    """代理下单兜底补出来的"下单人"就是货主自己 → 别把他记成他自己的联系人。

    不挡的后果：这位货主每次被代理下单，联系人名册里就多一条指向**他自己**的记录
    （界面上看不出是怎么来的，删了下次下单还会长出来）。
    """
    shipper = users["shipper"]
    before = len(_contacts(db_session, shipper.id))
    _create_order(client, token_dispatcher, shipper_id=shipper.id)
    assert len(_contacts(db_session, shipper.id)) == before


def test_货主自己下单也不把自己记成联系人(client, db_session, users, token_shipper):
    """货主自己下单时客户端带的就是他自己的号码 —— 同样不许进他自己的联系人名册。"""
    shipper = users["shipper"]
    before = len(_contacts(db_session, shipper.id))
    _create_order(client, token_shipper, contact_boss_name=shipper.full_name, contact_boss_phone=shipper.phone)
    assert len(_contacts(db_session, shipper.id)) == before


def test_下单人真的是别人时联系人照记(client, db_session, users, token_dispatcher):
    """反向对照：上面那条自我保护**不能**写成"一律不记"（那样联系人名册就再也不长了）。"""
    shipper = users["shipper"]
    _purge(db_session, shipper.id, OTHER_PHONE)
    before = len(_contacts(db_session, shipper.id))
    _create_order(
        client,
        token_dispatcher,
        shipper_id=shipper.id,
        contact_boss_name="王老板",
        contact_boss_phone=OTHER_PHONE,
    )
    rows = _contacts(db_session, shipper.id)
    assert len(rows) == before + 1
    assert any(c.phone == OTHER_PHONE and c.display_name == "王老板" for c in rows)
