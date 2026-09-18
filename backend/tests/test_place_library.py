"""共享地点库 / 导航信息补全 / 商品分类 / 订单行单位（2026-09-18 新增）。

这一份测试盯的是**用户看得见的三句话**能不能被证明：
1. 「司机到场补上的导航信息，货主下次下单能直接选到」；
2. 「坐标相近（1 米）的会被合并成一条，不会越攒越多」；
3. 「选品时选了"3 箱"，订单上就得是 3 箱」。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.models import Order, Place, Product, ShipperLocation
from app.services import place_service
from tests.conftest import auth_headers

# 一个真实坐标（深圳市民中心附近），下面所有偏移都相对它算。
#
# ⚠️ **每个用例用自己的一带纬度**：整个测试会话共用一个 SQLite，
#    如果两个用例落在同一个 1 米圈里，后一个会（正确地）并进前一个建的点 ——
#    于是断言 `first_order_id == 本单`/`use_count == 2` 就会红，而产品行为是对的。
#    分带之后每个用例的世界是干净的，"合并半径"这件事仍然逐用例验。
BASE_LAT = 22.5460000
BASE_LNG = 114.0540000
SPOT_NAV = (22.5500000, 114.0600000)
SPOT_SHARED_2 = (22.5600000, 114.0700000)
SPOT_SAME_PLACE = (22.5700000, 114.0800000)
SPOT_LOGGED = (22.5800000, 114.0900000)
SPOT_PLACES_LIST = (22.5900000, 114.1000000)
# 纬度偏移常量：**阈值两侧各取一个**，用来把 `MERGE_METERS = 1.0` 钉住。
# 只验"1 米内合并"是验不出问题的——把阈值写成 100 米它照样绿。
# 0.0000080° ≈ 0.89 米（必须合并）；0.0000100° ≈ 1.11 米（必须不合并）。
DEG_0_89M_LAT = 0.0000080
DEG_1_11M_LAT = 0.0000100
# 约 100 米（明显是另一个地点）
DEG_100M_LAT = 0.0009000
#: 兼容旧名字（下面若干用例用它表示"同一个点的测量误差"）
DEG_1M_LAT = DEG_0_89M_LAT


def _create_order(client, token, shipper_id, **kw):
    body = {
        "lines": [
            {
                "product_name_snapshot": kw.pop("product_name", "测试商品"),
                "quantity": kw.pop("quantity", 2),
                "unit_price": str(kw.pop("unit_price", "10")),
                "unit": kw.pop("unit", ""),
            }
        ],
        "address_detail": kw.pop("address_detail", "某路口进来第三家"),
        "shipper_id": shipper_id,
    }
    body.update(kw)
    r = client.post("/api/v1/orders", json=body, headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()


def _assign(client, token_dispatcher, order_id, driver_id):
    r = client.post(
        f"/api/v1/orders/{order_id}/assign",
        json={"driver_id": driver_id},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    return r.json()


def _order_without_nav(client, token_dispatcher, shipper_id, detail="某小区 3 号楼"):
    return _create_order(client, token_dispatcher, shipper_id, address_detail=detail)


# ---------------------------------------------------------------- 商品分类


def test_product_category_roundtrip(client, token_dispatcher):
    """分类能建、能改、能在商品目录里读回来（选品页分组全靠它）。"""
    r = client.post(
        "/api/v1/products",
        json={"name": "测试-可乐", "default_unit_price": "3", "category": "  饮料  "},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    # 前后空格必须被 strip：不 strip 的话「饮料」与「饮料  」会是左侧两个分类
    assert r.json()["category"] == "饮料"

    r = client.patch(
        f"/api/v1/products/{pid}", json={"category": "粮油"}, headers=auth_headers(token_dispatcher)
    )
    assert r.status_code == 200 and r.json()["category"] == "粮油"

    rows = client.get("/api/v1/products", headers=auth_headers(token_dispatcher)).json()
    assert any(p["id"] == pid and p["category"] == "粮油" for p in rows)


def test_product_without_category_defaults_to_blank(client, token_dispatcher, db_session):
    """不填分类 = 空串（「未分类」），不是报错 —— 老数据全靠这一档活着。"""
    r = client.post(
        "/api/v1/products",
        json={"name": "测试-无分类", "default_unit_price": "1"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201 and r.json()["category"] == ""
    row = db_session.get(Product, r.json()["id"])
    assert row is not None and row.category == ""


def test_product_category_too_long_is_422_with_chinese(client, token_dispatcher):
    r = client.post(
        "/api/v1/products",
        json={"name": "测试-超长分类", "category": "x" * 40},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 422
    assert "分类" in r.json()["detail"]


# ---------------------------------------------------------------- 订单行单位


def test_order_line_unit_is_snapshotted(client, token_dispatcher, users, db_session):
    """选了「3 箱」→ 订单上就是 3 箱（出参与库里都要对）。"""
    created = _create_order(
        client, token_dispatcher, users["shipper"].id, quantity=3, unit="箱"
    )
    line = created["order_products"][0]
    assert line["unit"] == "箱", line
    row = db_session.get(Order, created["id"])
    assert row is not None
    assert row.order_products[0].unit_snapshot == "箱"


def test_order_line_unit_falls_back_to_product_unit(client, token_dispatcher, users, db_session):
    """不传单位时回退商品库里配的「桶」——不是默认写死「件」。"""
    p = client.post(
        "/api/v1/products",
        json={"name": "测试-散装油", "default_unit_price": "88", "unit": "桶"},
        headers=auth_headers(token_dispatcher),
    ).json()
    created = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [
                {
                    "product_id": p["id"],
                    "product_name_snapshot": "测试-散装油",
                    "quantity": 1,
                    "unit_price": "88",
                }
            ],
        },
        headers=auth_headers(token_dispatcher),
    ).json()
    assert created["order_products"][0]["unit"] == "桶"
    row = db_session.get(Order, created["id"])
    assert row is not None and row.order_products[0].unit_snapshot == "桶"


def test_order_line_unit_can_be_changed_per_line(client, token_dispatcher, users, db_session):
    """派单员改单行单位：要真的写进库（改的是展示文案，不动钱）。"""
    p = client.post(
        "/api/v1/products",
        json={"name": "测试-米", "default_unit_price": "5", "unit": "袋"},
        headers=auth_headers(token_dispatcher),
    ).json()
    created = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [
                {
                    "product_id": p["id"],
                    "product_name_snapshot": "测试-米",
                    "quantity": 2,
                    "unit_price": "5",
                }
            ],
        },
        headers=auth_headers(token_dispatcher),
    ).json()
    lid = created["order_products"][0]["id"]
    r = client.patch(
        f"/api/v1/order-products/{lid}",
        json={"unit": "箱"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200 and r.json()["unit"] == "箱"
    # 单位是展示信息：金额一分不动
    assert Decimal(str(r.json()["line_total"])) == Decimal("10")
    row = db_session.get(Order, created["id"])
    assert row is not None and row.order_products[0].unit_snapshot == "箱"


# ---------------------------------------------------------------- 共享地点库


def test_place_nearby_coordinates_are_merged(client, token_dispatcher, db_session):
    """**用户要求的核心行为**：相差不到 1 米的坐标 → 并入同一条，而不是新建。

    这一段**逐条验证两条规则的边界**（只验"近的会合并"是验不出问题的：
    把阈值写成 100 米它照样绿）：
    1. 同名 + 0.89 米  → 合并；
    2. **异名** + 1.11 米 → 不合并（证明 1 米这条线真的在管"异名"的情况）；
    3. 异名 + 100 米   → 不合并；
    4. **同名** + 100 米 → 不合并（同名不能跨距离乱并）。
    """
    h = auth_headers(token_dispatcher)
    r1 = client.post(
        "/api/v1/places",
        json={"name": "坐标规则点A", "address_lat": BASE_LAT, "address_lng": BASE_LNG},
        headers=h,
    )
    assert r1.status_code == 201 and r1.json()["merged"] is False
    pid = r1.json()["id"]

    r2 = client.post(
        "/api/v1/places",
        json={
            "name": "坐标规则点A",
            "address_lat": BASE_LAT + DEG_0_89M_LAT,
            "address_lng": BASE_LNG,
        },
        headers=h,
    )
    assert r2.status_code == 201
    assert r2.json()["merged"] is True, "0.89 米内的坐标必须并入已有地点"
    assert r2.json()["id"] == pid

    r3 = client.post(
        "/api/v1/places",
        json={
            "name": "坐标规则点B",
            "address_lat": BASE_LAT + DEG_1_11M_LAT,
            "address_lng": BASE_LNG,
        },
        headers=h,
    )
    assert r3.status_code == 201
    assert r3.json()["merged"] is False, "异名且 1.11 米外，不能被并进来"
    assert r3.json()["id"] != pid

    r4 = client.post(
        "/api/v1/places",
        json={
            "name": "坐标规则点C",
            "address_lat": BASE_LAT + DEG_100M_LAT,
            "address_lng": BASE_LNG,
        },
        headers=h,
    )
    assert r4.status_code == 201 and r4.json()["merged"] is False

    r5 = client.post(
        "/api/v1/places",
        json={
            "name": "坐标规则点A",
            # ⚠️ 必须换一个**和 r4 不同的**偏移：同偏移就是同一个坐标（距离 0），
            #    那样测的是"坐标重合合并"，测不到"同名不能跨距离并"
            "address_lat": BASE_LAT + DEG_100M_LAT * 3,
            "address_lng": BASE_LNG,
        },
        headers=h,
    )
    assert r5.status_code == 201, r5.text
    assert r5.json()["merged"] is False, "同名但差 300 米，是两个地方"

    rows = db_session.scalars(select(Place).where(Place.name.like("坐标规则点%"))).all()
    assert len(rows) == 4, [(x.name, float(x.lat)) for x in rows]
    merged_row = next(x for x in rows if x.id == pid)
    assert merged_row.use_count == 2
    # 把两条规则的数字也钉住（1 米是用户给的，30 米是补的，见 place_service 模块注释）
    assert place_service.MERGE_METERS == 1.0
    assert place_service.SAME_NAME_METERS == 30.0
    assert place_service.haversine_m(BASE_LAT, BASE_LNG, BASE_LAT + DEG_0_89M_LAT, BASE_LNG) < 1.0
    assert place_service.haversine_m(BASE_LAT, BASE_LNG, BASE_LAT + DEG_1_11M_LAT, BASE_LNG) > 1.0


def test_same_name_within_gps_drift_is_merged(client, token_dispatcher, db_session):
    """**同名 + 30 米内**也判同一个地点（补的第二条规则，见 place_service 模块注释）。

    为什么必须验它：手机 GPS 实测精度 3~10 米，只按 1 米合并的话真机上
    几乎永远不会触发 —— "合并"看着做了、其实没发生。
    同时验**反面**：同一个 30 米圈里**名字不同**的两个点绝不能并（那是隔壁那家店）。
    """
    h = auth_headers(token_dispatcher)
    lat, lng = SPOT_SHARED_2
    a = client.post(
        "/api/v1/places",
        json={"name": "GPS漂移测试仓", "address_lat": lat, "address_lng": lng},
        headers=h,
    ).json()
    assert a["merged"] is False

    # 相隔约 6.7 米（真实 GPS 漂移量级）、同名 → 并入
    b = client.post(
        "/api/v1/places",
        json={"name": "  GPS 漂移测试仓 ", "address_lat": lat + 0.00006, "address_lng": lng},
        headers=h,
    ).json()
    assert b["merged"] is True, "同名 + 6.7 米内必须并入（否则真机上永远合不了）"
    assert b["id"] == a["id"]

    # 同一个圈里，名字不同 → **不许**并（30 米内一律合并就是把隔壁那家店吃掉）
    c = client.post(
        "/api/v1/places",
        json={"name": "隔壁的店", "address_lat": lat + 0.00006, "address_lng": lng},
        headers=h,
    ).json()
    assert c["merged"] is False, "名字不同的两个点在 30 米内也不能合并"

    rows = db_session.scalars(
        select(Place).where(Place.name.in_(["GPS漂移测试仓", "隔壁的店"]))
    ).all()
    assert len(rows) == 2, [(x.name, float(x.lat)) for x in rows]


def test_places_visible_to_all_roles(client, token_dispatcher, token_shipper, token_driver):
    """共享库必须**三种角色都查得到** —— 这正是"省的每个人都要手动上传一次"的前提。"""
    h = auth_headers(token_dispatcher)
    client.post(
        "/api/v1/places",
        json={"name": "共享测试点", "address_lat": "30.1000000", "address_lng": "120.2000000"},
        headers=h,
    )
    for token in (token_shipper, token_driver, token_dispatcher):
        rows = client.get(
            "/api/v1/places", params={"q": "共享测试点"}, headers=auth_headers(token)
        ).json()
        assert len(rows) == 1, f"{token[:8]} 查不到共享地点"
        assert rows[0]["name"] == "共享测试点"


def test_place_rejects_out_of_range_coordinates(client, token_dispatcher):
    r = client.post(
        "/api/v1/places",
        json={"name": "坏坐标", "address_lat": "500", "address_lng": "120"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 422
    assert "纬度" in r.json()["detail"]


# ---------------------------------------------------------------- 司机补导航


def test_driver_fills_navigation_for_order_without_coords(
    client, token_dispatcher, token_driver, users, db_session
):
    """**端到端**：司机补 → 订单有坐标 → 货主地点库多一条 → 共享库有这条。

    这三件事一次性全都要发生，缺任何一件用户看到的就是"补了但没用"。
    """
    created = _order_without_nav(client, token_dispatcher, users["shipper"].id)
    assert created["address_lat"] is None
    oid = created["id"]
    _assign(client, token_dispatcher, oid, users["driver"].id)

    lat, lng = SPOT_NAV
    r = client.post(
        f"/api/v1/orders/{oid}/navigation",
        json={
            "address_lat": lat,
            "address_lng": lng,
            "name": "某小区 3 号楼",
        },
        headers=auth_headers(token_driver),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(str(body["address_lat"])) == Decimal(str(lat))
    assert body["nav_source"] == "driver"

    # ② 货主自己的地点库：下次下单直接可选
    locs = db_session.scalars(
        select(ShipperLocation).where(ShipperLocation.shipper_id == created["shipper_id"])
    ).all()
    assert any(
        x.name == "某小区 3 号楼" and abs(float(x.address_lat) - lat) < 1e-6 for x in locs
    ), [(x.name, float(x.address_lat)) for x in locs]

    # ③ 共享库：别人也能用
    shared = db_session.scalars(select(Place).where(Place.first_order_id == oid)).all()
    assert len(shared) == 1 and shared[0].source == "driver"

    # ④ 站内信："已存入你的地点库"这句话必须有出处（收件人是货主）
    msgs = client.get(
        "/api/v1/notifications",
        params={"recipient_id": users["shipper"].id},
        headers=auth_headers(token_dispatcher),
    ).json()
    rows = msgs if isinstance(msgs, list) else msgs.get("items", [])
    assert any(m.get("type") == "order.navigation.filled" for m in rows), [
        m.get("type") for m in rows
    ]


def test_navigation_cannot_overwrite_existing_coords(
    client, token_dispatcher, token_driver, users
):
    """已经有坐标的订单拒绝补录 —— 错坐标比没坐标更危险（导航会把人带错且看不出来）。"""
    created = _create_order(
        client,
        token_dispatcher,
        users["shipper"].id,
        address_detail="已带坐标",
        address_lat=str(BASE_LAT),
        address_lng=str(BASE_LNG),
    )
    oid = created["id"]
    _assign(client, token_dispatcher, oid, users["driver"].id)
    r = client.post(
        f"/api/v1/orders/{oid}/navigation",
        json={"address_lat": "30.0", "address_lng": "120.0"},
        headers=auth_headers(token_driver),
    )
    assert r.status_code == 400
    assert "已经有导航信息" in r.json()["detail"]


def test_navigation_rejects_other_drivers_order(
    client, token_dispatcher, token_driver, users, db_session
):
    """**不是这单的司机**不能补 —— 否则任何人都能给别人的单塞坐标。"""
    from app.core.security import hash_password
    from app.models import User

    other = User(
        username="13800009999",
        phone="13800009999",
        password_hash=hash_password("pass12345"),
        full_name="OtherDriver",
        role="driver",  # type: ignore
    )
    db_session.add(other)
    db_session.commit()

    created = _order_without_nav(client, token_dispatcher, users["shipper"].id)
    r = client.post(
        f"/api/v1/orders/{created['id']}/navigation",
        json={"address_lat": BASE_LAT, "address_lng": BASE_LNG},
        headers=auth_headers(token_driver),
    )
    assert r.status_code == 403, r.text


def test_navigation_rejected_for_shipper(client, token_shipper, token_dispatcher, users):
    """货主不能给自己下单的订单"补导航"（这条路径是给到场的人用的）。"""
    created = _order_without_nav(client, token_dispatcher, users["shipper"].id)
    r = client.post(
        f"/api/v1/orders/{created['id']}/navigation",
        json={"address_lat": BASE_LAT, "address_lng": BASE_LNG},
        headers=auth_headers(token_shipper),
    )
    assert r.status_code in (403, 404), r.text


def test_navigation_second_driver_merges_into_same_place(
    client, token_dispatcher, token_driver, users, db_session
):
    """两个司机给**同一个位置**的两张单补录 → 共享库里只有一条（这才是"共同库"的意义）。

    ⚠️ 同时验**货主自己的地点库也只多一条**：两张单是**同一个货主**的，
    补录走的是同一个 `ensure_shipper_location` —— 那里不去重的话，
    货主下次下单会在「我的地点」里看到两条一模一样的记录，而列表上分不出哪条是哪条。
    """
    o1 = _order_without_nav(client, token_dispatcher, users["shipper"].id)
    o2 = _order_without_nav(client, token_dispatcher, users["shipper"].id)
    for oid in (o1["id"], o2["id"]):
        _assign(client, token_dispatcher, oid, users["driver"].id)
    lat, lng = SPOT_SAME_PLACE
    for oid, offset in ((o1["id"], 0.0), (o2["id"], DEG_1M_LAT)):
        r = client.post(
            f"/api/v1/orders/{oid}/navigation",
            json={
                "address_lat": lat + offset,
                "address_lng": lng,
                "name": "同一家仓库",
            },
            headers=auth_headers(token_driver),
        )
        assert r.status_code == 200, r.text

    rows = db_session.scalars(select(Place).where(Place.name == "同一家仓库")).all()
    assert len(rows) == 1, f"同一个位置变成了 {len(rows)} 条：{[float(x.lat) for x in rows]}"
    assert rows[0].use_count >= 2

    locs = db_session.scalars(
        select(ShipperLocation).where(
            ShipperLocation.shipper_id == users["shipper"].id,
            ShipperLocation.name == "同一家仓库",
        )
    ).all()
    assert len(locs) == 1, f"货主地点库该去重，实际 {len(locs)} 条"


def test_blank_name_is_not_stored_when_merging(db_session):
    """**纯空格的名字不许写进库**（2026-09-18 在开发库里真抓到过一条名字是 3 个空格的记录）。

    为什么这条测的是 **service 层**而不是接口：`POST /places` 的 schema 现在会在入口
    就把"无名无址"挡掉（422），所以走接口**到不了** `_fill_blank` 这条路径 ——
    而它恰恰是当初出问题的地方：`if not value` 拦不住 `"   "`（三个空格在 Python 里是真值），
    于是"并入一条还没名字的记录"时把一串空格写了进去。
    新建那条路径本来就 strip 过，所以只测新建是测不出来的。

    （反向验证过：把 `_fill_blank` 还原成不 strip 的版本，这条测试立刻变红。）
    """
    lat, lng = 22.6000000, 114.1200000
    # 第一条：只有地址、没有名字
    p1, merged1 = place_service.upsert_place(
        db_session, lat=lat, lng=lng, name="", detail_address="某仓库", source="shipper"
    )
    assert merged1 is False and p1.name == ""

    # 第二条：同一个点，名字是一串空格 → 走"并入 + 补名字"这条路径
    p2, merged2 = place_service.upsert_place(
        db_session, lat=lat, lng=lng, name="   ", detail_address="  ", source="shipper"
    )
    assert merged2 is True and p2.id == p1.id
    assert p2.name == "", "纯空格的名字必须被当成空，不许写进库"
    assert p2.detail_address == "某仓库", "空值不许把原来的地址覆盖掉"

    # 反向对照：**有内容的**名字仍然要能补进一条没名字的记录
    # （否则上面那条"测试"只要把补名字整个删掉就能过 —— 那就是空转的检查）
    lat2, lng2 = 22.6100000, 114.1300000
    p3, _ = place_service.upsert_place(
        db_session, lat=lat2, lng=lng2, name="", detail_address="某仓库2", source="shipper"
    )
    assert p3.name == ""
    p4, merged4 = place_service.upsert_place(
        db_session, lat=lat2, lng=lng2, name="  有名字  ", detail_address="", source="shipper"
    )
    assert merged4 is True and p4.id == p3.id
    assert p4.name == "有名字", "有内容的名字要补进去，且两侧空格要去掉"

    # 再验一次 `_clean` 的截断顺序（先 strip 再截断）：128 个空格 + 名字，
    # 顺序反了会存下 128 个空格、把真名字截掉
    long = "  " + "x" * 200 + "  "
    p5, _ = place_service.upsert_place(
        db_session, lat=23.0, lng=113.0, name=long, detail_address="", source="shipper"
    )
    assert len(p5.name) == 128 and p5.name.startswith("x"), (len(p5.name), p5.name[:10])


def test_anonymous_place_is_rejected(client, token_dispatcher, db_session):
    """**无名无址的点不许进共享库**（这张表全库共享，而且没有删除接口）。

    为什么必须挡：共享地点库是大家一起看的一张表，**没有任何入口能删一条**。
    于是"只有坐标、没有名字"的记录是**永久的**：它在每个人的列表里都显示成
    「未命名地点」+ 空地址，谁也认不出、谁也清不掉。
    （开发库里真出现过——合同模糊测试往 `POST /places` 打了 5 次空名请求。）
    """
    h = auth_headers(token_dispatcher)
    r = client.post(
        "/api/v1/places",
        json={"name": "", "detail_address": "  ", "address_lat": "31.2000000", "address_lng": "121.4000000"},
        headers=h,
    )
    assert r.status_code == 422, r.text
    assert "名字" in r.json()["detail"]

    # **二选一即可**：只有名字能过、只有地址也能过（"先钉个点、地址回头补"是合理用法）
    ok1 = client.post(
        "/api/v1/places",
        json={"name": "只有名字", "address_lat": "31.2100000", "address_lng": "121.4100000"},
        headers=h,
    )
    assert ok1.status_code == 201, ok1.text
    ok2 = client.post(
        "/api/v1/places",
        json={"detail_address": "只有地址", "address_lat": "31.2200000", "address_lng": "121.4200000"},
        headers=h,
    )
    assert ok2.status_code == 201, ok2.text
    assert db_session.scalars(select(Place).where(Place.lat.between("31.19", "31.23"))).all()


def test_navigation_is_logged(client, token_dispatcher, token_driver, users):
    """补录会往全库共享库里写点，必须留痕（"这个坐标是谁标的"）。"""
    created = _order_without_nav(client, token_dispatcher, users["shipper"].id)
    _assign(client, token_dispatcher, created["id"], users["driver"].id)
    lat, lng = SPOT_LOGGED
    r = client.post(
        f"/api/v1/orders/{created['id']}/navigation",
        json={"address_lat": lat, "address_lng": lng, "name": "留痕测试点"},
        headers=auth_headers(token_driver),
    )
    assert r.status_code == 200
    logs = client.get(
        f"/api/v1/operation-logs?order_id={created['id']}",
        headers=auth_headers(token_dispatcher),
    ).json()
    rows = logs if isinstance(logs, list) else logs.get("items", [])
    assert any(x.get("action") == "ORDER_NAVIGATION_FILL" for x in rows), rows
