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

from app.models import ShipperLocation
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
