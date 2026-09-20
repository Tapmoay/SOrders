"""下单/补录上传的**位置照片**要自动进「我的地点」（2026-09-20 用户要求）。

用户原话：
> 还有一个就是照片，他下单的时候，如果我上交了照片的话…那个跟地点是一样是自动保存在库里的。
> 还有一个就是司机他也可以去上交补交照片，如果他到了地方没有照片的话，他也可以补。

这一份盯三句话：
1. 下单时传的位置图 → 货主的「我的地点」那一条上就有它（下次下单选到这个位置，图已经在库里）；
2. **司机**也能传（他到现场才拍得出"这个门口长什么样"），而且图进**货主**的库；
3. 不是这单的司机仍然传不了（别把放行写成"所有司机都能改任何单"）。
"""

from __future__ import annotations

import base64
import io

from sqlalchemy import select

from app.models import Place, ShipperLocation
from tests.conftest import auth_headers

# 1x1 的合法 PNG —— 上传端点会 sniff 类型，不能拿假字节糊弄
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)

SPOT_PHOTO = (22.9400000, 114.4400000)


def _create_order(client, token, shipper_id, **kw):
    body = {
        "lines": [
            {
                "product_name_snapshot": kw.pop("product_name", "照片测试商品"),
                "quantity": 1,
                "unit_price": "1",
                "unit": "",
            }
        ],
        "address_detail": kw.pop("address_detail", "照片测试地址"),
        "shipper_id": shipper_id,
    }
    body.update(kw)
    r = client.post("/api/v1/orders", json=body, headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()


def _upload(client, token, order_id):
    return client.post(
        f"/api/v1/orders/{order_id}/address-image",
        files={"file": ("pos.png", io.BytesIO(PNG), "image/png")},
        headers=auth_headers(token),
    )


def _loc(db_session, shipper_id, name):
    return db_session.scalars(
        select(ShipperLocation).where(
            ShipperLocation.shipper_id == shipper_id, ShipperLocation.name == name
        )
    ).all()


def test_order_photo_lands_in_my_locations(client, token_shipper, users, db_session):
    """下单时传的位置图，会挂到货主「我的地点」那一条上。"""
    name = "照片进库-某仓库"
    lat, lng = SPOT_PHOTO
    created = _create_order(
        client, token_shipper, None, address_detail=name, address_lat=str(lat), address_lng=str(lng)
    )
    r = _upload(client, token_shipper, created["id"])
    assert r.status_code == 200, r.text

    rows = _loc(db_session, users["shipper"].id, name)
    assert len(rows) == 1, rows
    assert rows[0].image_urls not in (None, "", "[]"), rows[0].image_urls
    assert rows[0].image_url, "首图字段必须与 image_urls 同源（`LocationOut` 靠它兼容旧客户端）"
    url = rows[0].image_url
    assert rows[0].image_urls.count(url) == 1, "同一张图只该挂一次"


def test_driver_can_upload_place_photo(client, token_dispatcher, token_driver, users, db_session):
    """**司机**也能补照片（原来 403），而且图进**货主**的库。

    用户：「司机他也可以去上交补交照片，如果他到了地方没有照片的话，他也可以补」。
    """
    name = "照片进库-司机补的"
    created = _create_order(client, token_dispatcher, users["shipper"].id, address_detail=name)
    r = client.post(
        f"/api/v1/orders/{created['id']}/assign",
        json={"driver_id": users["driver"].id},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text

    up = _upload(client, token_driver, created["id"])
    assert up.status_code == 200, up.text

    rows = _loc(db_session, users["shipper"].id, name)
    assert len(rows) == 1, rows
    assert rows[0].image_urls not in (None, "", "[]"), "司机拍的图该进货主的「我的地点」"


def test_unrelated_driver_cannot_upload(client, token_dispatcher, token_driver, users, db_session):
    """**不是这单的**司机仍然传不了（放行只能放"这单的司机"）。"""
    name = "照片进库-不是我送的"
    created = _create_order(client, token_dispatcher, users["shipper"].id, address_detail=name)
    up = _upload(client, token_driver, created["id"])
    assert up.status_code == 403, up.text
    rows = _loc(db_session, users["shipper"].id, name)
    assert rows and rows[0].image_urls in (None, "", "[]"), "被拒的请求不该动库"


# --------------------------------------------------- 共享库也要有图（2026-09-20 用户追加）
#
# 用户原话：「可以共享库也加上图片」。
# 三条规矩：① 只挂到**已经存在**的共享点上（不为照片新建共享点 —— 那张表全库共用）；
#          ② 「设为共享」把私人的图带过去；③ 「撤销」把共享的图带回来。


def _shared(db_session, name):
    return db_session.scalars(select(Place).where(Place.name == name)).all()


def test_photo_attaches_to_existing_shared_place(client, token_dispatcher, users, db_session):
    """共享库里已经有同一个点时，上传的位置图也挂到**那一条**上（不新建点）。"""
    lat, lng = 22.9500000, 114.4500000
    name = "照片进共享-已有坐标"
    # 先由派单员手工建一个共享点（唯一合法的新建入口）
    r = client.post(
        "/api/v1/places",
        json={"name": name, "address_lat": str(lat), "address_lng": str(lng)},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    before = len(_shared(db_session, name))
    assert before == 1

    created = _create_order(
        client,
        token_dispatcher,
        users["shipper"].id,
        address_detail=name,
        address_lat=str(lat),
        address_lng=str(lng),
    )
    assert _upload(client, token_dispatcher, created["id"]).status_code == 200

    rows = _shared(db_session, name)
    assert len(rows) == 1, f"不该为照片新建共享点：{len(rows)} 条"
    assert rows[0].image_urls not in (None, "", "[]"), "共享库那条也该有这张图"


def test_share_location_carries_photos_into_shared_library(
    client, token_dispatcher, token_shipper, users, db_session
):
    """「设为共享」把「我的地点」那条的照片一起带进共享库；撤销时再带回来。"""
    from app.models import ShipperLocation  # 局部导入：本文件其余用例不用它

    name = "照片跟随-设为共享"
    lat, lng = 22.9600000, 114.4600000
    # 用**派单员**代理下单：这一条会落在**他自己的**「我的地点」里（"两边都记"那条规矩），
    # 而"设为共享"只允许共享**自己库里**的地点（`POST /shipper/locations/{id}/share`）。
    created = _create_order(
        client,
        token_dispatcher,
        users["shipper"].id,
        address_detail=name,
        address_lat=str(lat),
        address_lng=str(lng),
    )
    assert _upload(client, token_dispatcher, created["id"]).status_code == 200
    loc = db_session.scalars(
        select(ShipperLocation).where(
            ShipperLocation.shipper_id == users["dispatcher"].id, ShipperLocation.name == name
        )
    ).first()
    assert loc is not None and loc.image_urls not in (None, "", "[]")

    # 派单员把它设为共享
    r = client.post(
        f"/api/v1/shipper/locations/{loc.id}/share", headers=auth_headers(token_dispatcher)
    )
    assert r.status_code in (200, 201), r.text
    rows = _shared(db_session, name)
    assert len(rows) == 1, rows
    assert rows[0].image_urls not in (None, "", "[]"), "设为共享时照片要跟着走"

    # 再撤销：图回到操作人（派单员）自己的「我的地点」
    place_id = rows[0].id
    r2 = client.post(f"/api/v1/places/{place_id}/demote", headers=auth_headers(token_dispatcher))
    assert r2.status_code == 200, r2.text
    back = db_session.scalars(
        select(ShipperLocation).where(
            ShipperLocation.shipper_id == users["dispatcher"].id, ShipperLocation.name == name
        )
    ).first()
    assert back is not None and back.image_urls not in (None, "", "[]"), "撤销时照片要带回来"


def test_places_list_exposes_image_urls(client, token_dispatcher, db_session):
    """列表接口必须把 `image_urls` 出出去（否则界面拿不到图，等于存了没人看得见）。"""
    name = "照片进共享-出参"
    r = client.post(
        "/api/v1/places",
        json={
            "name": name,
            "address_lat": "22.9700000",
            "address_lng": "114.4700000",
        },
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    rows = client.get("/api/v1/places?limit=200", headers=auth_headers(token_dispatcher)).json()
    hit = [x for x in rows if x["id"] == pid]
    assert hit and "image_urls" in hit[0], hit[:1]
    assert hit[0]["image_urls"] == [], "没图时是空列表，不是 null（旧数据 NULL 也要归一）"
