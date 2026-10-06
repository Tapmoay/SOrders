"""商品分类名册 / 商品可见白名单 / 常用地点自动进库（v3.43，2026-09-18）。

这一份盯的是三句用户原话能不能被证明：
1. 「派单端可以创建商品分类，甚至可以更改商品分类的显示顺序」；
2. 「派单员可以指定他只只能看到哪些商品」；
3. 「常点的那个共享地点，有人经常点了，它就会自动移到他自己的地点库当中」。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    Place,
    Product,
    ProductCategory,
    ShipperLocation,
    User,
    UserProductVisibility,
)
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
    v = r.json()
    assert v["scope"] == "custom" and v["product_ids"] == [keep["id"]]
    # L-23：出参多了分类与排除两维（这一条只勾了单品，那三个必须是空的）
    assert v["category_names"] == [] and v["hidden_product_ids"] == []
    assert v["hidden_category_names"] == []

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
    """`custom` 但一个都没勾 → 拒绝（那等于让他什么都看不到，而界面会显示"已设置"）。

    L-23 之后判据从"勾了几个"改成"**他到底能看见几个**"：分类算进来以后，
    "只选了分类不勾单品"是完全合法的（下面那条用例盯的就是它）。
    """
    r = client.put(
        f"/api/v1/users/{users['shipper'].id}/product-visibility",
        json={"scope": "custom", "product_ids": []},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 400
    assert "一个商品都看不到" in r.json()["detail"]


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
            # L-32：下单必须至少一端有联系信息（后端命令层硬拦；与 App 下单页同源）
            "contact_dongjia_name": "收货人甲",
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
            # L-32：下单必须至少一端有联系信息（上面那次拦在可见范围上，这次要真的建成单）
            "contact_dongjia_name": "收货人甲",
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


# -------------------------------------------- ②b 分类授权 / 单独关掉（L-23，CHG-0062）


def _seen_ids(client, token) -> set[int]:
    """这个身份在选品页能看到的商品编号（`limit` 拉满，别被分页截断）。"""
    rows = client.get("/api/v1/products?limit=500", headers=auth_headers(token)).json()
    return {x["id"] for x in rows}


def test_visibility_category_covers_products_added_later(
    client, token_dispatcher, token_shipper, users
):
    """按分类授权：**以后**加进这一类的商品自动可见（不是把现在的编号抄一份）。

    用户 2026-10-06 原话：「假如以后有其他商品增加到这个分类，它自动是显示的」。
    做成快照也能让当刻的界面对，但以后每加一个商品都要回来重配一次 —— 而**没人会记得**，
    表现出来是"我明明授权了这个分类，新商品却看不到"。所以这条用例的重头戏是最后一步：
    配完之后**再加**一个商品。

    不改会怎样：`resolve_visible_product_ids` 里"按分类名现查"那句被换成把当时这一类下的
    编号写进明细（当刻看起来完全一样、上面那些断言也照过），后加的商品就永久看不见。
    """
    h = auth_headers(token_dispatcher)
    old = _mk_product(client, token_dispatcher, "分类授权-原有", category="分类授权类")
    other = _mk_product(client, token_dispatcher, "分类授权-别的类", category="分类授权别的类")

    r = client.put(
        f"/api/v1/users/{users['shipper'].id}/product-visibility",
        json={"scope": "custom", "category_names": ["分类授权类"]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["category_names"] == ["分类授权类"]
    assert v["product_ids"] == [], "只授权分类时不该把现有编号也写进去（写进去就成快照了）"

    got = _seen_ids(client, token_shipper)
    assert old["id"] in got
    assert other["id"] not in got, "没授权的分类不该看到"

    late = _mk_product(client, token_dispatcher, "分类授权-后加", category="分类授权类")
    assert late["id"] in _seen_ids(client, token_shipper), "配完之后加进这一类的商品必须自动可见"


def test_visibility_denies_one_product_inside_an_allowed_category(
    client, token_dispatcher, token_shipper, users
):
    """整类给他看，但**单独关掉其中一个**（all 档与 custom 档都要能关）。

    用户 2026-10-06 原话：「这个分类是要全部显示的，但是某个商品我们不让它显示，
    就把它直接关闭……以后其他新商品增加到这个分类，他也会正常显示」。
    后半句的意思是：关掉的是**那个商品**，不是这一类 —— 所以关掉之后新加进这一类的
    商品照样要可见（分类那一行的 deny 才是"整类都别给他看"）。
    """
    h = auth_headers(token_dispatcher)
    uid = users["shipper"].id
    a = _mk_product(client, token_dispatcher, "整类-甲", category="整类类")
    b = _mk_product(client, token_dispatcher, "整类-乙", category="整类类")
    far = _mk_product(client, token_dispatcher, "整类-别的类", category="整类别的类")

    # ① all 档：全给他看，只关掉甲
    r = client.put(
        f"/api/v1/users/{uid}/product-visibility",
        json={"scope": "all", "hidden_product_ids": [a["id"]]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["hidden_product_ids"] == [a["id"]]
    got = _seen_ids(client, token_shipper)
    assert a["id"] not in got and b["id"] in got and far["id"] in got

    # ② custom 档：这一类全给 + 关掉甲（"这一类给你看，就这一个不给"）
    r = client.put(
        f"/api/v1/users/{uid}/product-visibility",
        json={
            "scope": "custom",
            "category_names": ["整类类"],
            "hidden_product_ids": [a["id"]],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    got = _seen_ids(client, token_shipper)
    assert b["id"] in got and a["id"] not in got
    assert far["id"] not in got, "custom 档里没授权的分类不该出现"

    # ③ 关掉的是**商品**不是分类：后加进这一类的商品仍然可见
    late = _mk_product(client, token_dispatcher, "整类-后加", category="整类类")
    assert late["id"] in _seen_ids(client, token_shipper)

    # 反向对照：派单员照样看得到被关掉的那个（关的是"给不给他看"，不是把商品下架）
    allrows = client.get("/api/v1/products?limit=500", headers=h).json()
    assert a["id"] in {x["id"] for x in allrows}


def test_visibility_category_with_no_products_is_rejected(client, token_dispatcher, users):
    """授权的分类**现在一个在架商品都没有** → 拒绝（配完他打开选品页就是空的）。

    这是 L-23 的自决：分类名本身合法、以后加进这一类的商品也确实会可见，
    但"你现在打开是空的"才是当刻的事实 —— 与"custom 一个都没勾"同一个理由
    （界面显示"已设置"、人却看不到任何商品，然后来报"商品都不见了"）。
    `replace_visibility` 那条"分类名不做存在性校验"管的是名册里没有、但**有商品**挂着的
    名字（老数据）；这里管的是"配完看不见东西"，两件事。
    """
    r = client.put(
        f"/api/v1/users/{users['shipper'].id}/product-visibility",
        json={"scope": "custom", "category_names": ["这个类还没有商品"]},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 400, r.text
    assert "一个商品都看不到" in r.json()["detail"]


def test_visibility_all_scope_hiding_everything_is_rejected(
    client, token_dispatcher, users, db_session
):
    """`all` 档把**每一个在架商品**都关掉 → 拒绝（结果同样是"打开是空的"）。

    ⚠️ 必须从库里取**全部**在架编号：`GET /api/v1/products` 只给一页（默认 200 条），
    拿它去关的话剩下的商品还是可见的 —— 闸门不会触发，用例会假绿。
    """
    all_ids = list(
        db_session.scalars(select(Product.id).where(Product.is_deleted.is_(False))).all()
    )
    assert all_ids, "库里得有在架商品，这条用例才有意义"
    uid = users["shipper"].id
    h = auth_headers(token_dispatcher)

    r = client.put(
        f"/api/v1/users/{uid}/product-visibility",
        json={"scope": "all", "hidden_product_ids": all_ids},
        headers=h,
    )
    assert r.status_code == 400, r.text
    assert "关光了" in r.json()["detail"]

    # 反向对照：少关一个就存得下（否则这条"拦"可能只是"一律拦"）
    ok = client.put(
        f"/api/v1/users/{uid}/product-visibility",
        json={"scope": "all", "hidden_product_ids": all_ids[:-1]},
        headers=h,
    )
    assert ok.status_code == 200, ok.text


def test_category_rename_carries_visibility_rows_over(
    client, token_dispatcher, token_shipper, users, db_session
):
    """分类改名时，挂在它名下的**可见范围行**要一起改名（授权与排除两个方向）。

    两个后果都是"界面上看不出来"的那种：
    - 授权方向：那一行指向一个不存在的旧名字 ⇒ 货主凭空少一批商品；
    - 排除方向：本来关掉的商品**全部重新出现**，而且不报错。
    """
    h = auth_headers(token_dispatcher)
    uid = users["shipper"].id
    # ⚠️ 分类名（连带商品名）带一个**本次运行独有**的尾巴：测试库在一次运行里是累积的，
    #    `.test_dbs/` 里还可能留着上一次被中断的库（文件名带 PID，PID 会被系统回收）。
    #    固定名字一旦撞上残留行，红的是"改名没级联"这种**看起来像产品缺陷**的断言 ——
    #    本次收尾就踩过一次（单文件跑绿、全量跑红，红点还每次都换）。
    tail = uuid.uuid4().hex[:6]
    old_cat, new_cat = f"改名旧类-{tail}", f"改名新类-{tail}"
    old_deny, new_deny = f"改名排除旧类-{tail}", f"改名排除新类-{tail}"

    def find_id(name: str) -> int:
        cats = client.get("/api/v1/product-categories", headers=h).json()
        hits = [c["id"] for c in cats if c["name"] == name]
        assert len(hits) == 1, ("分类名册里应该有且只有一行", name, cats)
        return hits[0]

    def rename(old: str, new: str) -> None:
        r = client.patch(
            f"/api/v1/product-categories/{find_id(old)}", json={"name": new}, headers=h
        )
        assert r.status_code == 200, r.text
        # 先钉住"改名真的落到了这一行"：这一步不成立时，下面那条断言会长成
        # "级联没生效"（同一个误导在收尾排查里出现过一次，查了很久）。
        assert r.json()["name"] == new, r.text

    # ① custom：整类授权 + 单独关掉一个
    keep = _mk_product(client, token_dispatcher, f"改名-可见-{tail}", category=old_cat)
    deny = _mk_product(client, token_dispatcher, f"改名-关掉-{tail}", category=old_cat)
    r = client.put(
        f"/api/v1/users/{uid}/product-visibility",
        json={
            "scope": "custom",
            "category_names": [old_cat],
            "hidden_product_ids": [deny["id"]],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text

    rename(old_cat, new_cat)
    v = client.get(f"/api/v1/users/{uid}/product-visibility", headers=h).json()
    assert v["category_names"] == [new_cat], (
        "授权行要跟着改名",
        v,
        # 顺手把名册带上：这条断言真正想说的是"那一行指向的名字还在不在"，只报可见
        # 范围看不出是"级联没生效"还是"改名根本没落到这一行"。
        [c["name"] for c in client.get("/api/v1/product-categories", headers=h).json()],
    )
    assert v["hidden_product_ids"] == [deny["id"]], "单独关掉的那个商品不受改名影响"
    assert v["hidden_category_names"] == []
    got = _seen_ids(client, token_shipper)
    assert keep["id"] in got and deny["id"] not in got

    # ② all + 整类排除：改名之后这一类**还得是关着的**
    blocked = _mk_product(client, token_dispatcher, f"改名-整类关-{tail}", category=old_deny)
    r = client.put(
        f"/api/v1/users/{uid}/product-visibility",
        json={"scope": "all", "hidden_category_names": [old_deny]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert blocked["id"] not in _seen_ids(client, token_shipper)

    rename(old_deny, new_deny)
    v = client.get(f"/api/v1/users/{uid}/product-visibility", headers=h).json()
    assert v["hidden_category_names"] == [new_deny], (v, [old_deny, new_deny])
    assert blocked["id"] not in _seen_ids(client, token_shipper), "改名不能把关掉的一类放出来"


def test_rename_visibility_merges_rows_that_collide(users, db_session):
    """`_rename_visibility_category` 的三种撞车都要合并掉（唯一索引 (user_id, category_name, mode)）。

    ⚠️ 今天**从接口进不来**这条路径：闸门②要求"配完看得见商品"，而任何有商品的分类
    都会被自动补进名册（于是改名撞名会被 409 挡下）。能造出这种形状的只有手写进库的
    历史数据、或者将来放宽闸门 —— 但一旦撞上就是 IntegrityError：整次改名失败，
    用户只看到一句"服务器错误"，而分类名还停在旧的。
    """
    from app.api.v1.product_categories import _rename_visibility_category
    from app.models.product_visibility import MODE_ALLOW, MODE_DENY

    shipper, driver, dispatcher = users["shipper"], users["driver"], users["dispatcher"]
    for uid, name, mode in (
        (shipper.id, "旧类", MODE_ALLOW),  # 同模式旧新两行都在 → 并成一行
        (shipper.id, "新类", MODE_ALLOW),
        (driver.id, "旧类", MODE_ALLOW),  # 授权旧名 + 排除新名 → 只留排除
        (driver.id, "新类", MODE_DENY),
        (dispatcher.id, "旧类", MODE_DENY),  # 排除旧名 + 授权新名 → 只留排除
        (dispatcher.id, "新类", MODE_ALLOW),
    ):
        db_session.add(UserProductVisibility(user_id=uid, category_name=name, mode=mode))
    db_session.commit()

    counts = _rename_visibility_category(db_session, "旧类", "新类")
    db_session.commit()

    left = {
        (r.user_id, r.category_name, r.mode)
        for r in db_session.scalars(select(UserProductVisibility)).all()
    }
    assert left == {
        (shipper.id, "新类", MODE_ALLOW),
        (driver.id, "新类", MODE_DENY),
        (dispatcher.id, "新类", MODE_DENY),
    }, "撞车之后每个用户每个方向只该剩一行，而且**排除优先**"
    # 计数逐项对得上：
    # - renamed 2 = driver 的「旧类授权」（搬过去叫新类）+ dispatcher 的「旧类排除」；
    # - merged 1 = shipper 的「旧类授权」被删掉（新类上已经有一行授权了）；
    # - dropped 2 = driver 的「新类授权」（刚搬过来的那行，撞上他自己的新类排除）+
    #   dispatcher 的「新类授权」（原来就在）。
    assert counts == {"rows_renamed": 2, "rows_merged": 1, "allow_rows_dropped": 2}


def test_migration_024_makes_product_id_nullable_on_old_db(tmp_path):
    """⚠️ 老库的 `product_id` 还是 NOT NULL：迁移 024 必须把它改成可空，否则分类行一写就 500。

    这条用例**故意不用 conftest 的测试库** —— 那是 `create_all` 建出来的新形状，
    `product_id` 本来就可空，老库的毛病在它上面永远看不见（2026-10-06 真库探针才撞出来：
    `NOT NULL constraint failed: user_product_visibility.product_id`）。
    所以这里手工建一张 024 之前的表，再单独跑 024 的 `upgrade()`。
    """
    import importlib.util

    from sqlalchemy import create_engine, inspect, text

    from app.migrations import MIGRATIONS_DIR

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}", future=True)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE user_product_visibility ("
            " id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, product_id INTEGER NOT NULL,"
            " created_at DATETIME, updated_at DATETIME)"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX uq_user_product_visibility"
            " ON user_product_visibility (user_id, product_id)"
        ))
        conn.execute(text(
            "INSERT INTO user_product_visibility (id, user_id, product_id, created_at, updated_at)"
            " VALUES (1, 2, 7, '2026-10-06 00:00:00', '2026-10-06 00:00:00')"
        ))

    path = MIGRATIONS_DIR / "024_product_visibility_targets.py"
    spec = importlib.util.spec_from_file_location("mig024_for_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.upgrade(engine)

    cols = {c["name"]: c["nullable"] for c in inspect(engine).get_columns("user_product_visibility")}
    assert cols["product_id"] is True, cols
    with engine.begin() as conn:
        # 老行一字未动，并且被读成"单品授权行"
        row = conn.execute(text(
            "SELECT product_id, category_name, mode FROM user_product_visibility WHERE id = 1"
        )).one()
        assert tuple(row) == (7, None, "allow"), tuple(row)
        # ⭐ 这一句才是本条用例的目的：分类行（product_id 为 NULL）现在写得进去了
        conn.execute(text(
            "INSERT INTO user_product_visibility (user_id, product_id, category_name, mode, created_at, updated_at)"
            " VALUES (2, NULL, '水果', 'allow', '2026-10-06 00:00:00', '2026-10-06 00:00:00')"
        ))
        conn.execute(text(
            "INSERT INTO user_product_visibility (user_id, product_id, category_name, mode, created_at, updated_at)"
            " VALUES (2, NULL, '水果', 'deny', '2026-10-06 00:00:00', '2026-10-06 00:00:00')"
        ))
    # 迁移必须能重跑（README 硬要求）：第二遍是安静的空转
    mod.upgrade(engine)
    assert _upv_index_names(engine) >= {"uq_upv_category"}, _upv_index_names(engine)


def _upv_index_names(engine) -> set[str]:
    """重建之后 `uq_upv_category` 这个**名字**还在不在（重建最容易把它弄丢）。"""
    from sqlalchemy import inspect

    return {i["name"] for i in inspect(engine).get_indexes("user_product_visibility")}


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
