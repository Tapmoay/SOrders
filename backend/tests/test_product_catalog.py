"""商品分类名册 / 商品可见白名单 / 常用地点自动进库（v3.43，2026-09-18）。

这一份盯的是三句用户原话能不能被证明：
1. 「派单端可以创建商品分类，甚至可以更改商品分类的显示顺序」；
2. 「派单员可以指定他只只能看到哪些商品」；
3. 「常点的那个共享地点，有人经常点了，它就会自动移到他自己的地点库当中」。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Place, ProductCategory, ShipperLocation, User, UserProductVisibility
from app.services import place_service
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_visibility(db_session):
    """每个用例跑完把「商品可见范围」恢复成默认（all）。

    ## 为什么必须有（不加会怎样，实测）
    测试库是**整个会话共用**的一个文件，而接口调用会 `db.commit()` ——
    所以"把货主设成 custom"这件事会**留在库里**。
    后果不是本文件出错，而是**别的文件里 7 个毫不相干的用例一起红**
    （凡是"以货主身份下单"的都会突然 400：商品不在可选范围内）。
    这种"我改了共享状态、坏在别人身上"的失败最难查 —— 报错的地方和原因隔了三个文件。
    """
    yield
    db_session.rollback()
    for u in db_session.query(User).all():
        u.product_scope = "all"
    db_session.execute(UserProductVisibility.__table__.delete())
    db_session.commit()


def _mk_product(client, token, name: str, category: str = "", price: str = "10"):
    r = client.post(
        "/api/v1/products",
        json={"name": name, "default_unit_price": price, "category": category},
        headers=auth_headers(token),
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- ① 分类名册


def test_new_category_from_product_is_added_to_roster(client, token_dispatcher, db_session):
    """新建商品时带了一个名册里没有的分类名 → **自动补进名册**。

    不补的话派单员要"先建分类、再建商品"两步；而且名册外的分类在下单页只能排到最后，
    用户会以为"我刚建的分类怎么跑最后去了"。
    """
    _mk_product(client, token_dispatcher, "测试-自动补名册", category="自动补测试类")
    rows = db_session.scalars(
        select(ProductCategory).where(ProductCategory.name == "自动补测试类")
    ).all()
    assert len(rows) == 1, "商品上带的分类名必须自动进名册"
    assert rows[0].sort_order > 0, "自动补的分类要排在最后（不是 0）"


def test_category_rename_cascades_to_products(client, token_dispatcher, db_session):
    """**改名要级联**：改完名，挂在这一类下的商品跟着改过去。

    不级联的后果不是报错，是"所有商品变成未分类"——而且界面上完全看不出来，
    要等下单时发现左侧少了一整类才知道。
    """
    h = auth_headers(token_dispatcher)
    p = _mk_product(client, token_dispatcher, "测试-级联改名", category="级联旧名")
    cat = db_session.scalars(
        select(ProductCategory).where(ProductCategory.name == "级联旧名")
    ).one()
    r = client.patch(f"/api/v1/product-categories/{cat.id}", json={"name": "级联新名"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "级联新名"

    got = client.get(f"/api/v1/products/{p['id']}", headers=h).json()
    assert got["category"] == "级联新名", "改名必须级联到商品上（否则商品全变未分类）"


def test_category_delete_refused_while_products_use_it(client, token_dispatcher, db_session):
    """还有商品挂着时**拒绝删除**，并且要告诉用户有几个。

    不"顺手把商品改成未分类"：用户点的是"删掉这个分类"，不是"把 N 个商品的分类清掉"，
    而且清完在界面上看不出来。
    """
    h = auth_headers(token_dispatcher)
    _mk_product(client, token_dispatcher, "测试-删分类用", category="在用分类")
    cat = db_session.scalars(select(ProductCategory).where(ProductCategory.name == "在用分类")).one()
    r = client.delete(f"/api/v1/product-categories/{cat.id}", headers=h)
    assert r.status_code == 400
    assert "还有 1 个商品" in r.json()["detail"], r.json()["detail"]

    # 反向对照：把商品挪走之后**必须能删**（否则这条"拒绝"可能只是"一律拒绝"）
    p = client.get("/api/v1/products", params={"include_inactive": True}, headers=h).json()
    pid = next(x["id"] for x in p if x["name"] == "测试-删分类用")
    client.patch(f"/api/v1/products/{pid}", json={"category": ""}, headers=h)
    r2 = client.delete(f"/api/v1/product-categories/{cat.id}", headers=h)
    assert r2.status_code == 204, r2.text


def test_reorder_requires_full_list(client, token_dispatcher):
    """顺序必须**整份**提交：只传一部分要被拒绝，并点名少了哪些。

    按"没提到的保持原序"实现的话，两端各错一次而且用户看不出来。
    """
    h = auth_headers(token_dispatcher)
    a = client.post("/api/v1/product-categories", json={"name": "排序A"}, headers=h).json()
    b = client.post("/api/v1/product-categories", json={"name": "排序B"}, headers=h).json()
    c = client.post("/api/v1/product-categories", json={"name": "排序C"}, headers=h).json()

    r = client.post("/api/v1/product-categories/reorder", json={"ids": [c["id"], a["id"]]}, headers=h)
    assert r.status_code == 400, r.text
    assert "少了" in r.json()["detail"]

    full = client.get("/api/v1/product-categories", headers=h).json()
    ids = [c["id"], a["id"]] + [x["id"] for x in full if x["id"] not in (a["id"], c["id"])]
    ok = client.post("/api/v1/product-categories/reorder", json={"ids": ids}, headers=h)
    assert ok.status_code == 200, ok.text
    assert [x["id"] for x in ok.json()][:2] == [c["id"], a["id"]], "提交的顺序要原样生效"
    assert b["id"] in ids


def test_categories_are_readable_by_every_role(client, token_dispatcher, token_shipper, token_driver):
    """名册**三种角色都能读** —— 下单页要用它排左侧那一列。"""
    client.post("/api/v1/product-categories", json={"name": "大家都能读"}, headers=auth_headers(token_dispatcher))
    for token in (token_shipper, token_driver):
        rows = client.get("/api/v1/product-categories", headers=auth_headers(token)).json()
        assert any(x["name"] == "大家都能读" for x in rows)


def test_overlong_category_name_is_rejected_not_truncated(client, token_dispatcher):
    """超长分类名要**拒绝**（422 + 中文），不许**悄悄截断**。

    这条是 2026-09-18 契约模糊测试抓到的：第一版在 before 校验器里 `[:32]`，
    于是 8000 字的名字返回 **201**、存进去的是前 32 个字 ——
    用户以为起了个长名字，实际是另一串，而且没有任何提示。
    超长是**用户能自助修好**的错误，前提是告诉他；悄悄改掉就不是了。
    """
    r = client.post(
        "/api/v1/product-categories",
        json={"name": "超" * 200},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 422, r.text
    assert "分类" in r.json()["detail"] or "名称" in r.json()["detail"]


# ---------------------------------------------------------------- ② 可见白名单


def test_visibility_defaults_to_all(client, token_shipper, users):
    """**默认不限制**：没有任何配置的货主看得到全部商品。

    这条是防迁移事故的：默认当成"白名单为空 = 什么都看不到"的话，
    上线那一刻所有老货主的选品页会当场变空。
    """
    v = client.get(
        f"/api/v1/users/{users['shipper'].id}/product-visibility",
        headers=auth_headers(token_shipper),
    ).json()
    assert v["scope"] == "all" and v["product_ids"] == []
    rows = client.get("/api/v1/products", headers=auth_headers(token_shipper)).json()
    assert len(rows) > 0, "默认应当看得到商品"


def test_visibility_whitelist_hides_other_products(client, token_dispatcher, token_shipper, users):
    """`custom` 之后：**只看到勾选的那些**，而且是"看不到"不是"点进去 403"。"""
    h = auth_headers(token_dispatcher)
    keep = _mk_product(client, token_dispatcher, "白名单-可见", category="白名单类")
    hide = _mk_product(client, token_dispatcher, "白名单-隐藏", category="白名单类")

    r = client.put(
        f"/api/v1/users/{users['shipper'].id}/product-visibility",
        json={"scope": "custom", "product_ids": [keep["id"]]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"scope": "custom", "product_ids": [keep["id"]]}

    rows = client.get("/api/v1/products", headers=auth_headers(token_shipper)).json()
    ids = {x["id"] for x in rows}
    assert keep["id"] in ids
    assert hide["id"] not in ids, "白名单外的商品不该出现在目录里"

    # 详情：按"不存在"回（回 403 等于告诉他"有个你看不到的商品"）
    assert client.get(f"/api/v1/products/{hide['id']}", headers=auth_headers(token_shipper)).status_code == 404

    # **反向对照**：派单员不受这条限制（否则改错了没人能改回来）
    allrows = client.get("/api/v1/products", headers=h).json()
    assert hide["id"] in {x["id"] for x in allrows}, "派单员必须仍然看得到全部商品"


def test_custom_scope_without_products_is_rejected(client, token_dispatcher, users):
    """`custom` 但一个都没勾 → 拒绝（那等于让他什么都看不到，而界面会显示"已设置"）。"""
    r = client.put(
        f"/api/v1/users/{users['shipper'].id}/product-visibility",
        json={"scope": "custom", "product_ids": []},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 400
    assert "一个都没勾" in r.json()["detail"]


def test_visibility_only_for_shippers(client, token_dispatcher, users):
    """对司机设可见范围 → 拒绝（司机根本没有商品目录，设了只会让人以为生效了）。"""
    r = client.put(
        f"/api/v1/users/{users['driver'].id}/product-visibility",
        json={"scope": "custom", "product_ids": [1]},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 400
    assert "只对货主" in r.json()["detail"]


def test_order_rejects_hidden_product(client, token_dispatcher, token_shipper, users):
    """**下单时也拦隐藏商品**：只在选品页藏起来 = 看起来限制了、其实没有。"""
    h = auth_headers(token_dispatcher)
    hide = _mk_product(client, token_dispatcher, "白名单-下单拦", category="白名单类")
    client.put(
        f"/api/v1/users/{users['shipper'].id}/product-visibility",
        json={"scope": "custom", "product_ids": [hide["id"] + 100000]},
        headers=h,
    )
    # 上面那次只勾了一个不存在的编号 → 后端会拒绝，所以改成一个真实可见的
    other = _mk_product(client, token_dispatcher, "白名单-下单可见", category="白名单类")
    client.put(
        f"/api/v1/users/{users['shipper'].id}/product-visibility",
        json={"scope": "custom", "product_ids": [other["id"]]},
        headers=h,
    )
    r = client.post(
        "/api/v1/orders",
        json={
            "lines": [
                {
                    "product_id": hide["id"],
                    "product_name_snapshot": "白名单-下单拦",
                    "quantity": 1,
                    "unit_price": "10",
                }
            ]
        },
        headers=auth_headers(token_shipper),
    )
    assert r.status_code == 400, r.text
    assert "不在你的可选范围内" in r.json()["detail"]

    # 反向对照：可见的那个商品**必须能下单**（否则这条"拦"可能只是"一律拦"）
    ok = client.post(
        "/api/v1/orders",
        json={
            "lines": [
                {
                    "product_id": other["id"],
                    "product_name_snapshot": "白名单-下单可见",
                    "quantity": 1,
                    "unit_price": "10",
                }
            ]
        },
        headers=auth_headers(token_shipper),
    )
    assert ok.status_code == 201, ok.text


def test_visibility_rows_are_replaced_not_appended(client, token_dispatcher, users):
    """整份替换语义：第二次设置要把第一次的明细清掉（不是叠加）。"""
    h = auth_headers(token_dispatcher)
    a = _mk_product(client, token_dispatcher, "替换A", category="白名单类")
    b = _mk_product(client, token_dispatcher, "替换B", category="白名单类")
    uid = users["shipper"].id
    client.put(
        f"/api/v1/users/{uid}/product-visibility",
        json={"scope": "custom", "product_ids": [a["id"]]},
        headers=h,
    )
    v = client.put(
        f"/api/v1/users/{uid}/product-visibility",
        json={"scope": "custom", "product_ids": [b["id"]]},
        headers=h,
    ).json()
    assert v["product_ids"] == [b["id"]], "必须是替换而不是追加"


# ---------------------------------------------------------------- ③ 常用地点


def _mk_place(client, token, name: str, lat: float, lng: float):
    r = client.post(
        "/api/v1/places",
        json={"name": name, "address_lat": str(lat), "address_lng": str(lng)},
        headers=auth_headers(token),
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_first_use_does_not_auto_add(client, token_shipper, users, db_session):
    """第 **1** 次用：只记数，**不**动用户自己的地点库。"""
    p = _mk_place(client, token_shipper, "常用点A", 22.7000000, 114.2000000)
    r = client.post(f"/api/v1/places/{p['id']}/use", headers=auth_headers(token_shipper)).json()
    assert r["use_count"] == 1 and r["auto_added"] is False
    locs = db_session.scalars(
        select(ShipperLocation).where(
            ShipperLocation.shipper_id == users["shipper"].id,
            ShipperLocation.name == "常用点A",
        )
    ).all()
    assert locs == [], "第一次不该动他自己的地点库"


def test_second_use_auto_adds_shared_place(client, token_shipper, users, db_session):
    """第 **2** 次用 → 自动进他自己的「我的地点」，并且**只说一次**。"""
    p = _mk_place(client, token_shipper, "常用点B", 22.7100000, 114.2100000)
    h = auth_headers(token_shipper)
    client.post(f"/api/v1/places/{p['id']}/use", headers=h)
    r2 = client.post(f"/api/v1/places/{p['id']}/use", headers=h).json()
    assert r2["use_count"] == 2
    assert r2["auto_added"] is True, "第 2 次必须自动收进我的地点"

    locs = db_session.scalars(
        select(ShipperLocation).where(
            ShipperLocation.shipper_id == users["shipper"].id,
            ShipperLocation.name == "常用点B",
        )
    ).all()
    assert len(locs) == 1, "应当恰好加了一条"

    r3 = client.post(f"/api/v1/places/{p['id']}/use", headers=h).json()
    assert r3["use_count"] == 3
    assert r3["auto_added"] is False, "只加一次 —— 第 3 次不该再报「刚加进去」"
    locs2 = db_session.scalars(
        select(ShipperLocation).where(
            ShipperLocation.shipper_id == users["shipper"].id,
            ShipperLocation.name == "常用点B",
        )
    ).all()
    assert len(locs2) == 1, "不该重复加"


def test_usage_is_counted_per_person(client, token_dispatcher, token_shipper, users, db_session):
    """用量按**人**算：别人用多少次都不算我头上。

    用全库 `places.use_count` 做触发条件的话，一个热闹的地点会涌进**所有人**的列表 ——
    那不是"你常用的"，是"别人常去的"。
    """
    p = _mk_place(client, token_dispatcher, "常用点C", 22.7200000, 114.2200000)
    hd = auth_headers(token_dispatcher)
    hs = auth_headers(token_shipper)
    # 派单员用 5 次
    for _ in range(5):
        r = client.post(f"/api/v1/places/{p['id']}/use", headers=hd).json()
    assert r["use_count"] == 5
    # 货主第一次用：他的计数必须是 1（不是 6）
    rs = client.post(f"/api/v1/places/{p['id']}/use", headers=hs).json()
    assert rs["use_count"] == 1, "计数必须按人分开"
    assert rs["auto_added"] is False, "货主才第 1 次，不该被别人的使用次数带进他的库"


def test_auto_add_is_logged(client, token_shipper, token_dispatcher, users, db_session):
    """自动帮他加了库要**留痕**：他下次看到多出一条来源不明的记录，得能查出来是谁加的。"""
    p = _mk_place(client, token_shipper, "常用点D", 22.7300000, 114.2300000)
    h = auth_headers(token_shipper)
    client.post(f"/api/v1/places/{p['id']}/use", headers=h)
    client.post(f"/api/v1/places/{p['id']}/use", headers=h)
    logs = client.get("/api/v1/operation-logs", headers=auth_headers(token_dispatcher)).json()
    rows = logs if isinstance(logs, list) else logs.get("items", [])
    assert any(x.get("action") == "PLACE_AUTO_ADDED" for x in rows), [
        x.get("action") for x in rows[:20]
    ]


def test_threshold_constant_is_the_only_one():
    """阈值只有一处实现（散开写的话"第几次算常用"会各处说法不一）。"""
    assert place_service.AUTO_ADD_AFTER == 2
