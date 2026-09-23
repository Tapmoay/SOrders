"""批发商那本账：**同一笔钱不许被记两遍**（第 16 轮抓到的真缺陷）。

## 这一轮抓到的是什么

钱的口径在本项目一共有五处，前四处都治过"同一笔钱被记两遍"：

| 处 | 防重算的写法 |
| --- | --- |
| 订单应收/已收（`order_money`） | 一份实现，四个消费点共用 |
| 司机应付（`driver_pay`） | 一份实现，五个消费点共用 |
| 公司收款（`accounting_service.create_receipt`） | `money_map(..., lock=True)` → `SELECT … FOR UPDATE` |
| 退货红冲（`order_return`） | 可退数量与金额都过判据 |
| **批发商自记账（`shipper_settle`）** | ⛔ **原来一条都没有** —— 本轮补 |

这本账的守卫是「还可核销 = 行应收 − 已核销」，而这个数**是普通 SELECT 读出来的**：

1. **恢复路径（不需要并发，一个人点几下就能造出来）**：
   核销整单 80 → 撤销 → 再核销整单 80 → **把撤掉的那笔恢复回来** →
   两笔都活着，这一单记了 **160**，而它的应收只有 **80**。
   ⚠️ 界面上有「已撤销」区且带恢复入口，所以这条路径是**用户按得到的**；
   而且 `test_shipper_settlement.py::test_revoke_then_restore` 原来断言它 **200 成功**
   —— 缺陷被测试钉成了"设计如此"（这一轮把那条断言一并改对了）。
2. **并发路径**：两个请求同时读到"还可核销 100"，各自记 100（MySQL 的 REPEATABLE READ
   下普通 SELECT 读的是事务开始那一刻的快照）。派单员那份收款早就用加锁读治过，
   注释里写着"**而这正是本项目最贵的一类错**"—— 这本账漏了。

## 判据怎么读
`receivable`（应收）是这张单**现在**该收的钱，`received`（已收）是他自己记的核销。
两条断言缺一不可：**行上的「还可核销」不能为负**（那是超收），
**汇总的「待收」不能为负**（回收站里放回来的那笔一旦超了，就变成"你多收了客户 80"）。
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Update, event, select
from sqlalchemy.orm import Session

from app.models import Order, OperationLog
from app.models.shipper_settlement import ShipperSettlement, ShipperSettlementLine
from app.services.shipper_settle import settled_line_map
from tests.conftest import auth_headers

BASE = "/api/v1/shipper-ledger/settlements"
SUMMARY = "/api/v1/shipper-ledger/summary"


@pytest.fixture
def member(users, db_session):
    """把开发货主账号变成**批发商**（那本账只有批发商能写）。"""
    u = users["shipper"]
    u.is_member = True
    db_session.commit()
    return u


#: 用例之间避免互相污染：每个用例用自己那个下游货主名 + 电话筛汇总。
_SEQ = {"n": 0}


def _customer(tag: str) -> tuple[str, str]:
    _SEQ["n"] += 1
    n = _SEQ["n"]
    return f"核销上限{tag}{n}", f"1370000{n:04d}"


def _delivered_order(client, users, disp_h, *, dongjia: str, dongjia_phone: str) -> int:
    """造一张**已送达**的两行订单：白菜 2×10=20、萝卜 3×20=60（合计 80）。"""
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [
                {"product_name_snapshot": "白菜", "quantity": 2, "unit_price": "10"},
                {"product_name_snapshot": "萝卜", "quantity": 3, "unit_price": "20"},
            ],
            "address_detail": "核销上限测试地址",
            "contact_dongjia_name": dongjia,
            "contact_dongjia_phone": dongjia_phone,
            "contact_boss_name": "永盛食品",
            "contact_boss_phone": "13800000002",
        },
        headers=disp_h,
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    dtok = client.post(
        "/api/v1/auth/login", json={"phone": users["driver"].phone, "password": "pass12345"}
    ).json()["access_token"]
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "20"},
        headers=disp_h,
    ).status_code == 200
    assert (
        client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(dtok)).status_code == 200
    )
    done = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/ceiling.jpg"], "payment": "arrears"},
        headers=auth_headers(dtok),
    )
    assert done.status_code == 200, done.text
    return oid


def _summary(client, h, *, dongjia: str, dongjia_phone: str) -> dict:
    today = date.today().isoformat()
    r = client.get(
        SUMMARY,
        params={
            "delivered_from": today,
            "delivered_to": today,
            "customer_name": dongjia,
            "customer_phone": dongjia_phone,
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _alive_lines(db_session, oid: int) -> list[ShipperSettlementLine]:
    """这一单**此刻活着**的核销行（没撤销的那些）。"""
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(ShipperSettlementLine)
            .join(ShipperSettlement, ShipperSettlement.id == ShipperSettlementLine.settlement_id)
            .where(
                ShipperSettlementLine.order_id == oid,
                ShipperSettlement.is_deleted.is_(False),
            )
        ).all()
    )


def _lines_by_name(client, db_session, oid: int) -> dict[str, int]:
    order = db_session.get(Order, oid)
    assert order is not None
    return {op.product_name_snapshot: int(op.id) for op in order.order_products}


def test_恢复一笔位置已被占用的核销必须被拒(
    client, db_session, users, token_dispatcher, token_shipper, member
):
    """① **一个人点几下就能造出来的超收**：撤销 → 重记 → 再把撤掉的那笔放回来。

    修好之前这条会 200，并且这一单变成"已收 160 / 应收 80" —— 而**两个数都不报错**，
    用户要到自己对账时才发现下游那本账上多了一笔钱。
    """
    h = auth_headers(token_dispatcher)
    dongjia, phone = _customer("恢复")
    oid = _delivered_order(client, users, h, dongjia=dongjia, dongjia_phone=phone)
    ship = auth_headers(token_shipper)

    first = client.post(BASE, json={"order_id": oid}, headers=ship)
    assert first.status_code == 201, first.text
    sid1 = int(first.json()["id"])
    assert first.json()["amount"] == "80.00"

    assert client.delete(f"{BASE}/{sid1}", headers=ship).status_code == 204

    # 撤销之后这一单又能核销了（同一笔钱，第二次记）
    second = client.post(BASE, json={"order_id": oid}, headers=ship)
    assert second.status_code == 201, second.text
    sid2 = int(second.json()["id"])
    assert sid2 != sid1

    # ⛔ 现在把撤掉的那一笔恢复回来：这一行的「还可核销」已经是 0，放回来就是多收 80
    back = client.post(f"{BASE}/{sid1}/restore", headers=ship)
    assert back.status_code == 400, (
        "恢复一笔已经被后面那笔占掉位置的核销必须被拒（实际 "
        f"{back.status_code}）—— 否则同一笔钱被记两遍：已收 160、应收 80"
    )
    assert "还可核销" in back.json()["detail"], back.json()["detail"]

    # 库里也只该活着一笔，而且账面上的"待收"不许变成负数
    alive = _alive_lines(db_session, oid)
    assert len(alive) == 2, f"只该有第二笔那 2 行活着（实际 {len(alive)} 行）"
    assert sum(x.amount for x in alive) == 80
    row = db_session.get(ShipperSettlement, sid1)
    assert row is not None and row.is_deleted is True, "被拒之后这一笔必须还是撤销状态"

    s = _summary(client, ship, dongjia=dongjia, dongjia_phone=phone)
    assert s["receivable"] == "80.00"
    assert s["received"] == "80.00"
    assert s["unreceived"] == "0.00", f"待收不该是负的（实际 {s['unreceived']}）"


def test_还有余量时恢复照旧可以(client, db_session, users, token_dispatcher, token_shipper, member):
    """② **不许误伤**：撤销的那笔只占了「白菜」那 20，撤销之后重新核的是「萝卜」那 60，
    白菜的位置一直空着 → 恢复必须照旧成功。

    这一条是①的反面。用"恢复一律拒绝"这种懒办法，正常用户撤错了想放回来时就被挡住了 ——
    那同样是一个不报错的功能缺失，只是换了一头。
    """
    h = auth_headers(token_dispatcher)
    dongjia, phone = _customer("余量")
    oid = _delivered_order(client, users, h, dongjia=dongjia, dongjia_phone=phone)
    ship = auth_headers(token_shipper)
    ids = _lines_by_name(client, db_session, oid)

    first = client.post(
        BASE,
        json={"order_id": oid, "lines": [{"order_product_id": ids["白菜"], "amount": "20.00"}]},
        headers=ship,
    )
    assert first.status_code == 201, first.text
    sid1 = int(first.json()["id"])
    assert client.delete(f"{BASE}/{sid1}", headers=ship).status_code == 204

    second = client.post(
        BASE,
        json={"order_id": oid, "lines": [{"order_product_id": ids["萝卜"], "amount": "60.00"}]},
        headers=ship,
    )
    assert second.status_code == 201, second.text

    back = client.post(f"{BASE}/{sid1}/restore", headers=ship)
    assert back.status_code == 200, f"白菜那 20 还空着，恢复不该被拒：{back.text}"
    assert back.json()["is_deleted"] is False

    alive = _alive_lines(db_session, oid)
    assert sum(x.amount for x in alive) == 80
    s = _summary(client, ship, dongjia=dongjia, dongjia_phone=phone)
    assert s["received"] == "80.00" and s["unreceived"] == "0.00"


def test_恢复之后不许超过上限_逐行也要判(
    client, db_session, users, token_dispatcher, token_shipper, member
):
    """③ 恢复的判据是**逐行**的，不是"整单还差多少"。

    撤销了一笔萝卜 60，期间又零散收了萝卜 50 —— 恢复那 60 会超（该行只剩 10）。
    按"整单还差 20"放行的话，超收会被摊到**别的行**上，而别的行是别人的账。
    """
    h = auth_headers(token_dispatcher)
    dongjia, phone = _customer("逐行")
    oid = _delivered_order(client, users, h, dongjia=dongjia, dongjia_phone=phone)
    ship = auth_headers(token_shipper)
    ids = _lines_by_name(client, db_session, oid)

    first = client.post(
        BASE,
        json={"order_id": oid, "lines": [{"order_product_id": ids["萝卜"], "amount": "60.00"}]},
        headers=ship,
    )
    assert first.status_code == 201, first.text
    sid1 = int(first.json()["id"])
    assert client.delete(f"{BASE}/{sid1}", headers=ship).status_code == 204

    rest = client.post(
        BASE,
        json={"order_id": oid, "lines": [{"order_product_id": ids["萝卜"], "amount": "50.00"}]},
        headers=ship,
    )
    assert rest.status_code == 201, rest.text

    back = client.post(f"{BASE}/{sid1}/restore", headers=ship)
    assert back.status_code == 400, "这一行只剩 10，放回 60 会超 —— 必须被拒"
    assert "萝卜" in back.json()["detail"], back.json()["detail"]
    assert "还可核销" in back.json()["detail"], back.json()["detail"]

    alive = _alive_lines(db_session, oid)
    assert sum(x.amount for x in alive) == 50, "被拒之后库里不许留下那 60"
    assert all(x.amount <= 50 for x in alive)


def test_撤销与恢复连点两下只算一次(
    client, db_session, users, token_dispatcher, token_shipper, member
):
    """④ 撤销 / 恢复都是"读到没有 → 再写"的形态，必须用**条件 UPDATE**。

    少了它，连点两下（或两个请求同时到）会两边都通过检查：撤销会**写两条审计日志**
    —— 这本账不写 `cash_flows`，审计日志是唯一能回答"这笔核销谁在什么时候记的"的地方，
    多一条就会让人以为撤过两次、或者以为还有第二笔钱；恢复则会两边都去改同一个标记。

    ⚠️ 两条判据缺一不可：
    · **行为**（第二次必须 400、日志只有一条）—— 顺序执行时它挡的是"重复提交"；
    · **机制**（那次改标记是**一条 Core UPDATE**，不是 ORM 在 flush 时按对象状态写回去）
      —— 顺序测试**分不出**这两者（改成 ORM 写回，第二次照样会撞上"已经撤掉了"那道检查），
      所以必须单独钉机制，否则"防并发"这半句是没人验的。
    """
    h = auth_headers(token_dispatcher)
    dongjia, phone = _customer("连点")
    oid = _delivered_order(client, users, h, dongjia=dongjia, dongjia_phone=phone)
    ship = auth_headers(token_shipper)

    sid = int(client.post(BASE, json={"order_id": oid}, headers=ship).json()["id"])

    def _revoke_logs() -> int:
        db_session.expire_all()
        return (
            db_session.query(OperationLog)
            .filter_by(order_id=oid, action="SHIPPER_SETTLE_REVOKE")
            .count()
        )

    def _updates(fn) -> list[str]:
        """跑 `fn`，把它经由 `Session.execute` 发出去的 **UPDATE 语句**收集回来。

        ⚠️ 判据必须用 `isinstance(..., Update)`：`str(stmt)` 里含 "UPDATE" 的不一定是更新
        （`SELECT users.updated_at` 就含），第一版按文本找，抓到的是取当前用户那条 SELECT。
        """
        seen: list = []

        def _cap(state):
            seen.append(state.statement)

        event.listen(Session, "do_orm_execute", _cap)
        try:
            fn()
        finally:
            event.remove(Session, "do_orm_execute", _cap)
        return [str(s) for s in seen if isinstance(s, Update)]

    upd = _updates(lambda: client.delete(f"{BASE}/{sid}", headers=ship))
    assert upd, "撤销必须发一条条件 UPDATE（判据与写入在同一个语句里）"
    assert "shipper_settlements" in upd[0] and "is_deleted" in upd[0], upd[0]

    again = client.delete(f"{BASE}/{sid}", headers=ship)
    assert again.status_code == 400, "第二次撤销必须被拒（不能静默成功）"
    assert _revoke_logs() == 1, "撤销的审计日志只该有一条"

    upd2 = _updates(lambda: client.post(f"{BASE}/{sid}/restore", headers=ship))
    assert upd2 and "shipper_settlements" in upd2[0] and "is_deleted" in upd2[0], upd2
    twice = client.post(f"{BASE}/{sid}/restore", headers=ship)
    assert twice.status_code == 400, "第二次恢复必须被拒（不能静默成功）"

    s = _summary(client, ship, dongjia=dongjia, dongjia_phone=phone)
    assert s["received"] == "80.00" and s["unreceived"] == "0.00"


def test_算还可核销这一步必须能加锁读(db_session, member):
    """⑤ 机制：核销时读「已核销多少」那一条 SQL 必须**能**带上 `FOR UPDATE`。

    这是并发路径的修法所依赖的那一步（MySQL 上第二个请求会等第一个提交，
    再读就是"还可核销 0"）。**不能只看代码里写没写** —— 所以这里拦下真正要执行的那条
    statement，直接看它的 `_for_update_arg`（不看方言：SQLite 会把 `FOR UPDATE` 丢掉，
    所以"看最终 SQL"在本地永远看不出来）。
    """
    seen: list = []

    def _cap(state):
        seen.append(state.statement)

    event.listen(Session, "do_orm_execute", _cap)
    try:
        settled_line_map(db_session, [1], lock=True)
        plain = len(seen)
        settled_line_map(db_session, [1])
    finally:
        event.remove(Session, "do_orm_execute", _cap)

    locked = [s for s in seen if getattr(s, "_for_update_arg", None) is not None]
    assert locked, (
        "lock=True 时那条查询必须真的带 FOR UPDATE（否则并发核销各自读到旧快照，同一笔钱记两遍）"
    )
    assert len(seen) == plain + 1, "两次调用都该真的发出查询（不然上面那条断言是空转）"
    assert getattr(seen[-1], "_for_update_arg", None) is None, "默认那一档不该加锁（读列表不该锁库）"
