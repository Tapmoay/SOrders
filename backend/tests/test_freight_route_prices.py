"""运费价目挂**路线** + 多条价目 + 绑司机（2026-09-19 用户要求）。

用户原话：
> 「它是**根据路线**来创建的…先要创建一个路线，然后才能根据这个路线来创建一个模板」；
> 「同一个路线，我们可以配置**多个价格**，比如价格一价格二价格三，都可以修改」；
> 「这个价格是会**跟司机绑定**的…相同的路线不同的司机可能给不同的价格，所以下单的时候
>   就不需要选择那个价格模板了，因为我们只要选了司机他是自动跟上的」。

盯四件事：
1. 挂路线之后，模板上的起点/终点是**路线那一条的快照**（不是调用方随手打的字）；
2. 没有路线也没有起点/终点 → **400**（不许再回到"随手打两段字就是一个模板"）；
3. **一个司机在同一条路线上只能属于一档**（否则"选司机自动带价"没有唯一答案）；
4. 改价（fee）与改绑（driver_ids）都能单独做，且缺省不动。
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ShipperAddress, User
from tests.conftest import auth_headers


def _route(db: Session, *, owner: User, origin: str, dest: str) -> ShipperAddress:
    row = ShipperAddress(
        shipper_id=owner.id, receiver_name="", phone="",
        origin_address=origin, detail_address=dest, image_urls="[]",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _drivers(db: Session) -> list[User]:
    return db.query(User).filter(User.role == "driver").limit(3).all()


def test_create_template_snapshots_route(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """挂路线建的价目：起点/终点来自**路线**，价目名与司机绑定都存下来了。"""
    r = _route(db_session, owner=users["dispatcher"], origin="北京顺义仓", dest="朝阳大悦城")
    ds = _drivers(db_session)
    assert ds, "本机库里得有司机才能测绑定"
    resp = client.post(
        "/api/v1/freight-templates",
        headers=auth_headers(token_dispatcher),
        json={
            "name": "顺义→朝阳",
            "route_id": r.id,
            "price_name": "小车价",
            "fee": "260.00",
            "driver_ids": [d.id for d in ds[:2]],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["route_id"] == r.id
    # 起点/终点是**快照**：即使调用方传了别的文字，也以路线那一条为准
    assert body["from_place"] == "北京顺义仓" and body["to_place"] == "朝阳大悦城"
    assert body["price_name"] == "小车价"
    assert sorted(body["driver_ids"]) == sorted(d.id for d in ds[:2])
    # 列表里也带着绑定（界面不用再逐条问）
    listed = client.get("/api/v1/freight-templates", headers=auth_headers(token_dispatcher)).json()
    row = next(t for t in listed if t["id"] == body["id"])
    assert sorted(row["driver_ids"]) == sorted(d.id for d in ds[:2])


def test_create_without_route_or_places_is_rejected(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """既不给路线、也不给起点/终点 → 400：不许再回到"随手打两段字就是一个模板"。"""
    resp = client.post(
        "/api/v1/freight-templates",
        headers=auth_headers(token_dispatcher),
        json={"name": "没路线", "fee": "100"},
    )
    assert resp.status_code == 400
    assert "路线" in resp.json()["detail"]


def test_same_driver_cannot_be_in_two_prices_of_one_route(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """**同一个司机在一条路线上只能属于一档** —— 否则派单自动带价没有唯一答案。"""
    r = _route(db_session, owner=users["dispatcher"], origin="A仓", dest="B点")
    d = _drivers(db_session)[0]
    h = auth_headers(token_dispatcher)
    first = client.post("/api/v1/freight-templates", headers=h, json={
        "name": "顺义→朝阳", "route_id": r.id, "price_name": "小车价",
        "fee": "200", "driver_ids": [d.id],
    })
    assert first.status_code == 201, first.text

    # 同一路线的**另一档**再绑同一个司机 → 拒绝，并把"已经在哪一档"说清楚
    second = client.post("/api/v1/freight-templates", headers=h, json={
        "name": "顺义→朝阳", "route_id": r.id, "price_name": "大车价",
        "fee": "360", "driver_ids": [d.id],
    })
    assert second.status_code == 400
    assert "小车价" in second.json()["detail"]

    # **换一条路线**就没问题（"一条路线上一档"管的只是同一条路线）
    other = _route(db_session, owner=users["dispatcher"], origin="C仓", dest="D点")
    third = client.post("/api/v1/freight-templates", headers=h, json={
        "name": "C→D", "route_id": other.id, "price_name": "小车价",
        "fee": "150", "driver_ids": [d.id],
    })
    assert third.status_code == 201, third.text


def test_update_can_change_price_and_rebind(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """改价与改绑各管各的：只传 fee 不动司机；只传 driver_ids 不动金额。"""
    r = _route(db_session, owner=users["dispatcher"], origin="E仓", dest="F点")
    ds = _drivers(db_session)
    h = auth_headers(token_dispatcher)
    created = client.post("/api/v1/freight-templates", headers=h, json={
        "name": "E→F", "route_id": r.id, "price_name": "回程价",
        "fee": "180", "driver_ids": [ds[0].id],
    }).json()

    only_fee = client.put(f"/api/v1/freight-templates/{created['id']}", headers=h,
                          json={"fee": "199.50"})
    assert only_fee.status_code == 200, only_fee.text
    assert only_fee.json()["fee"] == "199.50"
    assert only_fee.json()["driver_ids"] == [ds[0].id], "只改价不该动司机绑定"

    # 只改绑（这里用"全部解绑"验语义：`[]` = 清空，`None` = 不动）
    rebind = client.put(f"/api/v1/freight-templates/{created['id']}", headers=h,
                        json={"driver_ids": []})
    assert rebind.status_code == 200, rebind.text
    assert rebind.json()["driver_ids"] == []
    assert rebind.json()["fee"] == "199.50", "只改绑不该动金额"
