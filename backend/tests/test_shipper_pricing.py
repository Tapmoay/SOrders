"""批发商**自己那层价**（下游定价）：改价不许改历史（CHG-0077 / 台账 L-38）。

## 这一轮要钉住的是什么

用户口径（m13365 第五问）：**改价之后老单一律按下单当时的快照，老单不追改**。
这一句话在代码里落成三件事，缺任何一件都会让历史账单**静默地**变一个数（不报错）：

| 落点 | 坏掉的后果（在场面上看不出来） |
| --- | --- |
| 下单那一刻把价定格到 `order_products.shipper_unit_price` | 批发商改一次价，去年那张单的「他欠我多少」跟着变 |
| 下游应收只读快照、没快照就**逐字退回**订单口径 | 老单（当时没有这一层价）凭空多收或少收一笔 |
| 快照**只填 NULL**（不覆盖已有快照、不写 0） | 「当时没有价」与「当时价格是 0」分不开；改单 / 转单会把当时的价改掉 |

下面每一类用例对应上表的一格，另外钉住三道闸门（批发商身份 ＋ 「管下游的账」那个开关 ＋ 权限点）、
「一个组合只有一行」（软删过的复活、不插新行）、以及「是谁的价」（行级过滤 ＋ 联系人名册）。

## 为什么这些断言要写成"数一个具体数"

这一层的三个数（订单口径 `line_receivable` / 他自己的口径 `line_downstream_receivable` /
价目表上的价）**肉眼看着都像**：都是"这一单该收多少"。只断言"接口 200"的话，
把快照读成订单行单价、或把没价的行写成 0，测试全绿而账单全错 —— 所以这里一律比具体金额。
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Order, OperationLog, ShipperContact, ShipperPrice
from app.models.product import Product
from app.services.order_money import line_downstream_receivable, line_receivable
from app.services.shipper_price import match_contact, snapshot_order_lines
from tests.conftest import auth_headers

BASE = "/api/v1/shipper-prices"
PRODUCTS = "/api/v1/shipper-prices/products"
TOGGLE = "/api/v1/users/me/downstream-ledger"

#: 用例之间不互相污染：每条用例的商品名 / 联系人名 / 客户电话都带一个自己的序号。
_SEQ = {"n": 0}


@pytest.fixture
def member(users, db_session):
    """把开发货主账号变成**批发商**（这一层价只有批发商能定）。"""
    u = users["shipper"]
    u.is_member = True
    db_session.commit()
    return u


def _tag() -> str:
    _SEQ["n"] += 1
    return f"{_SEQ['n']:02d}"


def _product(db_session, *, price: str = "10", name: str | None = None) -> Product:
    p = Product(
        name=name or f"下游定价商品{_tag()}",
        unit="件",
        default_unit_price=Decimal(price),
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _contact(
    db_session, shipper_id: int, *, name: str, phone: str | None = None, deleted: bool = False
) -> ShipperContact:
    c = ShipperContact(shipper_id=shipper_id, display_name=name, phone=phone, is_deleted=deleted)
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    return c


def _order(
    client,
    users,
    h,
    *,
    product: Product,
    qty: int = 3,
    unit_price: str = "10",
    contact_id: int | None = None,
    dongjia: str | None = None,
    phone: str | None = None,
) -> int:
    """派单员代下单（行里**带 product_id** —— 那是"他下过单的商品"进可定价范围的唯一凭据）。"""
    n = _tag()
    body = {
        "shipper_id": users["shipper"].id,
        "lines": [
            {
                "product_id": product.id,
                "product_name_snapshot": product.name,
                "quantity": qty,
                "unit_price": unit_price,
            }
        ],
        "address_detail": "下游定价测试地址",
        "contact_dongjia_name": dongjia or f"下游客户{n}",
        "contact_dongjia_phone": phone or f"1370000{n}00",
        "contact_boss_name": "永盛食品",
        "contact_boss_phone": "13800000002",
    }
    if contact_id is not None:
        body["contact_id"] = contact_id
    r = client.post("/api/v1/orders", json=body, headers=h)
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _line(db_session, oid: int):
    """这一单第一行（从库里重读，别拿建单那一刻的对象）。"""
    db_session.expire_all()
    order = db_session.get(Order, oid)
    assert order is not None
    return order.order_products[0]


def _set(
    client, h, *, product_id: int, unit_price: str, contact_id: int | None = None
) -> dict:
    payload: dict = {"product_id": product_id, "unit_price": unit_price}
    if contact_id is not None:
        payload["contact_id"] = contact_id
    r = client.post(BASE, json=payload, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _rows(db_session, shipper_id: int, product_id: int) -> list[ShipperPrice]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(ShipperPrice).where(
                ShipperPrice.shipper_id == shipper_id, ShipperPrice.product_id == product_id
            )
        ).all()
    )


def test_没定过价时下游应收逐字退回订单口径(
    client, db_session, users, token_dispatcher, token_shipper, member
):
    """① 老单 / 没定过价的单：**一个数都不许变**（这是整件事的安全底线）。

    没有这一条，"加了一格里价"就可能让**所有历史账单**换一个口径 —— 而账单页上
    两个数都印得出来，没人会当场发现。
    """
    disp = auth_headers(token_dispatcher)
    ship = auth_headers(token_shipper)
    p = _product(db_session, price="10")
    oid = _order(client, users, disp, product=p, qty=3, unit_price="10")

    op = _line(db_session, oid)
    assert op.shipper_unit_price is None, "没定过价 ⇒ 留 NULL（写成 0 就与'当时价格是 0'分不开）"
    assert line_downstream_receivable(op) == line_receivable(op) == Decimal("30.00")

    # 定了价：**这张已经下过的单**照旧 —— 价是下单那一刻定的，不是现在这次定的
    _set(client, ship, product_id=p.id, unit_price="8")
    op = _line(db_session, oid)
    assert op.shipper_unit_price is None, "已经下过的单不许被追改（口径⑤ m13365）"
    assert line_downstream_receivable(op) == Decimal("30.00")

    # 新单才用新价：他自己那本账按 8 算，公司那一半还是订单行上的 10
    oid2 = _order(client, users, disp, product=p, qty=3, unit_price="10")
    op2 = _line(db_session, oid2)
    assert op2.shipper_unit_price == Decimal("8.0000")
    assert line_downstream_receivable(op2) == Decimal("24.00")
    assert line_receivable(op2) == Decimal("30.00"), "公司那一半不许被下游价改掉"


def test_专属价覆盖默认价_没认出来的人走默认价(
    client, db_session, users, token_dispatcher, token_shipper, member
):
    """② 三层价各管一层：某人的**专属价** → 商品的**默认价** → 都没设 = **没有价**。"""
    disp = auth_headers(token_dispatcher)
    ship = auth_headers(token_shipper)
    p = _product(db_session, price="10")
    # 先卖过一次（"他下过单的商品"才进得了可定价范围）；那时还没定价 ⇒ 行上留 NULL
    _order(client, users, disp, product=p, qty=1)
    a = _contact(db_session, users["shipper"].id, name=f"甲客户{_tag()}", phone="13900001001")
    b = _contact(db_session, users["shipper"].id, name=f"乙客户{_tag()}", phone="13900001002")

    _set(client, ship, product_id=p.id, unit_price="8")  # 默认价
    _set(client, ship, product_id=p.id, unit_price="6", contact_id=a.id)  # 甲的专属价

    # 点选了甲 ⇒ 6
    op_a = _line(db_session, _order(client, users, disp, product=p, contact_id=a.id))
    assert op_a.shipper_unit_price == Decimal("6.0000")

    # 点选了乙 ⇒ 没有专属价，回落默认价 8
    op_b = _line(db_session, _order(client, users, disp, product=p, contact_id=b.id))
    assert op_b.shipper_unit_price == Decimal("8.0000")

    # 名册里没有的人（名字电话都对不上）⇒ 也走默认价 8（⛔ 不是 0）
    op_stranger = _line(
        db_session, _order(client, users, disp, product=p, dongjia=f"路人{_tag()}", phone="13900099999")
    )
    assert op_stranger.shipper_unit_price == Decimal("8.0000")

    # 价目表页上的三个数：默认价 8、专属价 1 条、供货参考价是商品自己的 10
    listed = client.get(PRODUCTS, headers=ship)
    assert listed.status_code == 200, listed.text
    mine = [x for x in listed.json() if int(x["product_id"]) == p.id]
    assert len(mine) == 1, listed.json()
    assert Decimal(mine[0]["default_unit_price"]) == Decimal("8.0000")
    assert int(mine[0]["contact_price_count"]) == 1
    assert Decimal(mine[0]["supply_unit_price"]) == Decimal("10.0000")

    # 删掉甲的专属价 ⇒ 他回落默认价（老单不动，这里看的是"以后的单")
    rows = _rows(db_session, users["shipper"].id, p.id)
    own = [r for r in rows if r.contact_id == a.id][0]
    assert client.delete(f"{BASE}/{own.id}", headers=ship).status_code == 204
    assert _line(db_session, _order(client, users, disp, product=p, contact_id=a.id)).shipper_unit_price == Decimal("8.0000")


def test_快照只填NULL_改价之后再定格不追改(
    client, db_session, users, token_dispatcher, token_shipper, member
):
    """③ 快照**只填 NULL**：已经带快照的行再定格一次，一个字节都不许动。

    这条守的是"下单之后又走到定格这一句"的所有路径（改数量 / 转单 / 拆单 / 派单员加行）。
    坏法是把 `if op.shipper_unit_price is not None: continue` 那句删掉 —— 表面上"更幂等"了，
    实际上每调一次就把当时的价改一次。
    """
    disp = auth_headers(token_dispatcher)
    ship = auth_headers(token_shipper)
    p = _product(db_session, price="10")
    _order(client, users, disp, product=p, qty=1)  # 先卖过一次（进可定价范围的前提）
    _set(client, ship, product_id=p.id, unit_price="8")
    oid = _order(client, users, disp, product=p, qty=2)
    db_session.expire_all()
    order = db_session.get(Order, oid)
    assert order is not None and order.order_products[0].shipper_unit_price == Decimal("8.0000")

    # 改价之后**再定格一次**这一单：已经带快照 ⇒ 定格 0 行、价还是 8
    _set(client, ship, product_id=p.id, unit_price="12")
    assert snapshot_order_lines(db_session, order, picked_contact_id=None) == 0
    assert order.order_products[0].shipper_unit_price == Decimal("8.0000")

    # 没定过价的商品：定格 0 行，而且**不许写 0**（写 0 就把"当时没有价"变成"当时白送"）
    p2 = _product(db_session, price="10")
    oid2 = _order(client, users, disp, product=p2, qty=2)
    db_session.expire_all()
    order2 = db_session.get(Order, oid2)
    assert order2 is not None
    assert snapshot_order_lines(db_session, order2, picked_contact_id=None) == 0
    assert order2.order_products[0].shipper_unit_price is None


def test_一个组合只有一行_软删过的复活而不是插新行(
    client, db_session, users, token_dispatcher, token_shipper, member
):
    """④ 默认价那一档唯一键**管不住**（NULL 互不相等）⇒ 靠服务层归一；删了再设是**复活**。"""
    disp = auth_headers(token_dispatcher)
    ship = auth_headers(token_shipper)
    p = _product(db_session, price="10")
    _order(client, users, disp, product=p, qty=1)  # 先卖过一次（进可定价范围的前提）
    first = _set(client, ship, product_id=p.id, unit_price="8")
    again = _set(client, ship, product_id=p.id, unit_price="9")
    assert int(again["id"]) == int(first["id"]), "同一个商品的默认价只能有一行"
    assert len(_rows(db_session, users["shipper"].id, p.id)) == 1

    assert client.delete(f"{BASE}/{first['id']}", headers=ship).status_code == 204
    back = _set(client, ship, product_id=p.id, unit_price="11")
    assert int(back["id"]) == int(first["id"]), "命中软删那一行要复活，⛔ 不是插新行（插了直接撞唯一键）"

    rows = _rows(db_session, users["shipper"].id, p.id)
    assert len(rows) == 1
    assert rows[0].is_deleted is False and rows[0].deleted_at is None
    assert rows[0].unit_price == Decimal("11.0000")


def test_连点两下只算一次_审计也只记一条(
    client, db_session, users, token_dispatcher, token_shipper, member
):
    """⑤ 软删 / 恢复都是**条件 UPDATE**：连点两下只成功一次，审计里也只该有一条。

    重复日志不是小事：这本账只有日志能回查，"两条删掉了"会让人以为还有第二条价。
    """
    disp = auth_headers(token_dispatcher)
    ship = auth_headers(token_shipper)
    p = _product(db_session, price="10")
    _order(client, users, disp, product=p, qty=1)  # 先卖过一次（进可定价范围的前提）
    row = _set(client, ship, product_id=p.id, unit_price="8")
    pid = int(row["id"])

    assert client.delete(f"{BASE}/{pid}", headers=ship).status_code == 204
    dup = client.delete(f"{BASE}/{pid}", headers=ship)
    assert dup.status_code == 400, "同一行删两次只该成功一次"
    assert "已经删掉" in dup.json()["detail"]

    assert client.post(f"{BASE}/{pid}/restore", headers=ship).status_code == 200
    dup2 = client.post(f"{BASE}/{pid}/restore", headers=ship)
    assert dup2.status_code == 400, "没被删的行恢复两次也只该成功一次"
    assert "不需要恢复" in dup2.json()["detail"]

    db_session.expire_all()
    logs = [
        json.loads(x.change_content or "{}")
        for x in db_session.scalars(
            select(OperationLog)
            .where(
                OperationLog.action == "SHIPPER_PRICE_UPSERT",
                OperationLog.operator_id == users["shipper"].id,
            )
            .order_by(OperationLog.id)
        ).all()
    ]
    mine = [x for x in logs if p.name in json.dumps(x, ensure_ascii=False)]
    assert [x.get("mode") for x in mine] == ["set", "delete", "restore"], mine


def test_不是批发商和关掉开关的批发商都进不来(
    client, db_session, users, token_shipper
):
    """⑥ 三道闸：普通货主 403（不是批发商）、关了开关的批发商 403（L-39 一起收）。"""
    ship = auth_headers(token_shipper)
    p = _product(db_session, price="10")

    def five() -> list[tuple[str, object]]:
        return [
            ("看价目表", client.get(BASE, headers=ship)),
            ("看可定价商品", client.get(PRODUCTS, headers=ship)),
            ("设价", client.post(BASE, json={"product_id": p.id, "unit_price": "8"}, headers=ship)),
            ("删价", client.delete(f"{BASE}/999999", headers=ship)),
            ("恢复", client.post(f"{BASE}/999999/restore", headers=ship)),
        ]

    for label, resp in five():
        assert resp.status_code == 403, f"{label}：普通货主应当 403（实际 {resp.status_code}）"
        assert "只有批发商" in resp.json()["detail"], label

    users["shipper"].is_member = True
    db_session.commit()
    off = client.patch(TOGGLE, json={"enabled": False}, headers=ship)
    assert off.status_code == 200, off.text
    for label, resp in five():
        assert resp.status_code == 403, f"{label}：关掉开关的批发商应当 403（实际 {resp.status_code}）"
        assert "管下游的账" in resp.json()["detail"], label


def test_商品不在范围_联系人不是自己的_单价非法_三种都当场拒绝(
    client, db_session, users, token_dispatcher, token_shipper, member
):
    """⑦ 宁可当场 400/422，也不写一条"对谁都不生效"的价 —— 而且要一行都不写。"""
    disp = auth_headers(token_dispatcher)
    ship = auth_headers(token_shipper)
    ok = _product(db_session, price="10")
    _order(client, users, disp, product=ok)  # 他下过单 ⇒ 可定价
    out = _product(db_session, price="10")  # 没下过单、也没有派单员给的专属价

    r = client.post(BASE, json={"product_id": out.id, "unit_price": "8"}, headers=ship)
    assert r.status_code == 400, r.text
    assert "不在你可定价的范围里" in r.json()["detail"]

    other = _contact(db_session, users["driver"].id, name=f"别人的人{_tag()}", phone="13600000001")
    r = client.post(
        BASE, json={"product_id": ok.id, "contact_id": other.id, "unit_price": "8"}, headers=ship
    )
    assert r.status_code == 400, r.text
    assert "不属于你" in r.json()["detail"]

    gone = _contact(
        db_session, users["shipper"].id, name=f"删掉的人{_tag()}", phone="13600000002", deleted=True
    )
    r = client.post(
        BASE, json={"product_id": ok.id, "contact_id": gone.id, "unit_price": "8"}, headers=ship
    )
    assert r.status_code == 400, r.text
    assert "回收站" in r.json()["detail"], "要告诉他出路：先到联系人里恢复"

    for bad in ("0", "-1"):
        r = client.post(BASE, json={"product_id": ok.id, "unit_price": bad}, headers=ship)
        assert r.status_code == 422, f"单价 {bad} 要当场拒（gt=0，0 元的价目表行等于白送）"

    assert _rows(db_session, users["shipper"].id, ok.id) == [], "被拒之后一行都不许写"


def test_别人的价看不见也删不掉(client, db_session, users, token_shipper, member):
    """⑧ 行级过滤只有一处（`shipper_id == current.id`）：少了它就是"谁的价都能看 / 都能改"。"""
    ship = auth_headers(token_shipper)
    p = _product(db_session, price="10")
    alien = ShipperPrice(
        shipper_id=users["driver"].id, contact_id=None, product_id=p.id, unit_price=Decimal("3")
    )
    db_session.add(alien)
    db_session.commit()
    db_session.refresh(alien)

    listed = client.get(BASE, headers=ship)
    assert listed.status_code == 200, listed.text
    assert all(int(x["id"]) != alien.id for x in listed.json()), "别人的价不该出现在我的价目表里"
    assert client.delete(f"{BASE}/{alien.id}", headers=ship).status_code == 404
    assert client.post(f"{BASE}/{alien.id}/restore", headers=ship).status_code == 404


def test_联系人四步匹配_点选_电话_姓名唯一_不认(db_session, users):
    """⑨ 下单时"这一单是给谁"的四步（口径②）：点选 → 电话精确 → 姓名**唯一**命中 → 不认。

    第三步多命中时必须**不认**：把同名的两个客户并成一个的后果是
    「他的欠款翻倍、另一个人的欠款不见了」，而两个数都不报错。
    """
    sid = users["shipper"].id
    a = _contact(db_session, sid, name=f"甲{_tag()}", phone="13900000001")
    b = _contact(db_session, sid, name=f"乙{_tag()}", phone="13900000002")
    dup1 = _contact(db_session, sid, name=f"同名{_tag()}", phone="13900000003")
    dup2 = _contact(db_session, sid, name=dup1.display_name, phone="13900000004")
    other = _contact(db_session, users["driver"].id, name=f"外人{_tag()}", phone="13900000005")
    gone = _contact(db_session, sid, name=f"删了{_tag()}", phone="13900000006", deleted=True)

    # ① 点选命中：名字电话都对不上也认点的那一条
    assert match_contact(db_session, shipper_id=sid, picked_contact_id=a.id, name="乱写", phone="13900009999") == a.id
    # ① 点的是**别人的** / 回收站里的 ⇒ 不认，继续往下走
    assert match_contact(db_session, shipper_id=sid, picked_contact_id=other.id, name="", phone="") is None
    assert match_contact(db_session, shipper_id=sid, picked_contact_id=gone.id, name="", phone="") is None
    # ② 电话精确命中
    assert match_contact(db_session, shipper_id=sid, name="乱写", phone=b.phone) == b.id
    # ③ 姓名必须唯一命中；同名的两条 ⇒ 不认
    assert match_contact(db_session, shipper_id=sid, name=a.display_name, phone="") == a.id
    assert match_contact(db_session, shipper_id=sid, name=dup1.display_name, phone="") is None
    assert dup2.id != dup1.id
    # ④ 都没认出来
    assert match_contact(db_session, shipper_id=sid, name="查无此人", phone="13900000000") is None
