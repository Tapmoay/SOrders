"""线路分类名册（`/route-categories`，2026-10-04）：改名级联、有线路挂着拒绝删、排序整份提交、
按人分区、以及「建线路时顺手建分类」。

用户 2026-10-04 原话：

> 「**干脆给线路联系人以及地点，这3个的界面玩个框了框的位置加一个分类显示**，它目前，
>  全部的话，就显示，全部如果是其他分类就显示…它就会弹出一个在左侧来」

联系人（迁移 012）与地点（`place_categories`）早就有名册，**线路这一档以前没有** ——
这一份是第三份，规矩与那两份逐条同形，所以这里盯的还是三件不说就会踩的事：
1. **归属那一格是字符串**（`shipper_addresses.category`），不是名册 id —— 名册删了/改名了，
   数据不能跟着消失，改名要**级联**（连回收站里那些一起改）；
2. **按人分区**：货主（含批发商）和派单员各有一份名册，别人的分类编号既看不到也改不动；
3. **司机没有线路库**：整组端点对他 403（与 `/shipper/addresses` 同一个角色门）。

⚠️ 另外钉一条**与联系人不同**的地方：`/shipper/addresses` **不是 upsert**
（`/shipper/contacts` 才是："同号即同一人"）。同一个号码可以有多条线路（收货人不同、
或者同一个收货人送两个地方），所以第二条**不会**并进第一条、也**不会**动第一条的分类。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import RouteCategory, ShipperAddress
from tests.conftest import auth_headers


def _mk_route(client, headers, *, name: str, phone: str = "", category: str = "", detail: str = ""):
    """建一条常用线路（`POST /shipper/addresses` **每次都建新的一条**，不是 upsert）。"""
    return client.post(
        "/api/v1/shipper/addresses",
        headers=headers,
        json={
            "receiver_name": name,
            "phone": phone,
            "detail_address": detail or f"{name}的地址",
            "category": category,
        },
    )


def _roster(client, headers) -> list[dict]:
    return client.get("/api/v1/route-categories", headers=headers).json()


def _find(client, headers, name: str) -> dict | None:
    return next((c for c in _roster(client, headers) if c["name"] == name), None)


def test_建线路时顺手建分类并进名册(client, token_dispatcher):
    """在名册里没有的分类下建线路 → 分类自动进名册（排到最后），条数是 1。

    否则用户得先建分类、再建线路（两步做完才能用），而他手里正拿着那张名片。
    """
    h = auth_headers(token_dispatcher)
    name = "探针-顺手建线路分类"
    assert _find(client, h, name) is None, "探针名撞上上一轮跑剩下的了，换个名字"

    r = _mk_route(client, h, name="顺手建分类甲", phone="13700009101", category=name)
    assert r.status_code == 201, r.text
    # 线路自己带着这一格（空串 = 未分类，与联系人/地点那一格同一个口径）
    assert r.json()["category"] == name

    row = _find(client, h, name)
    assert row is not None, f"分类没进名册：{[c['name'] for c in _roster(client, h)]}"
    assert row["address_count"] == 1
    # 排到最后（名册里的行比大小；GET 只返回名册行，所以直接取最大即可）
    others = [c["sort_order"] for c in _roster(client, h) if c["id"] != row["id"]]
    assert not others or row["sort_order"] >= max(others)


def test_改线路分类也会顺手补名册(client, token_dispatcher):
    """把已有线路改成一个新分类名 → 同样进名册（编辑路径与新建路径同一条规矩）。"""
    h = auth_headers(token_dispatcher)
    name = "探针-改出来线路分类"
    r = _mk_route(client, h, name="改分类乙", phone="13700009102")
    assert r.status_code == 201, r.text
    assert r.json()["category"] == ""

    aid = r.json()["id"]
    patched = client.patch(
        f"/api/v1/shipper/addresses/{aid}", headers=h, json={"category": name}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["category"] == name
    assert _find(client, h, name) is not None


def test_改名级联改掉挂着的线路(client, db_session: Session, token_dispatcher):
    """改分类名 → 同一事务里把那些线路的 category 也改掉（不级联 = "我的线路不见了"）。

    ⚠️ 连**回收站里**那条一起改：软删的行仍然带着老分类名，只改活着的会让
    「恢复」之后那条掉进一个已经不存在（或已被别人占用）的分类里。
    """
    h = auth_headers(token_dispatcher)
    old = "探针-线路改名前"
    new = "探针-线路改名后"
    a = _mk_route(client, h, name="线路改名甲", phone="13700009103", category=old)
    b = _mk_route(client, h, name="线路改名乙", phone="13700009104", category=old)
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)
    # 乙进回收站（这条只在库层面看得到）
    assert client.delete(f"/api/v1/shipper/addresses/{b.json()['id']}", headers=h).status_code == 204

    row = _find(client, h, old)
    assert row is not None, _roster(client, h)
    r = client.patch(f"/api/v1/route-categories/{row['id']}", headers=h, json={"name": new})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == new

    db_session.expire_all()
    live = db_session.get(ShipperAddress, a.json()["id"])
    gone = db_session.get(ShipperAddress, b.json()["id"])
    assert live.category == new, "活着的线路没跟着改名"
    assert gone.category == new, "回收站里那条没跟着改名（恢复后会掉进一个不存在的分类）"
    # 老名字下已经没有了（级联是"改"不是"复制"）
    assert db_session.query(ShipperAddress).filter(ShipperAddress.category == old).count() == 0
    assert _find(client, h, old) is None


def test_还有线路挂着的分类不许删(client, token_dispatcher):
    """删除有名下线路的分类 → 400 并告诉他还有几条（不"顺手把它们改成未分类"）。"""
    h = auth_headers(token_dispatcher)
    name = "探针-线路删除保护"
    made = _mk_route(client, h, name="删除保护甲", phone="13700009105", category=name)
    assert made.status_code == 201, made.text
    row = _find(client, h, name)
    assert row is not None and row["address_count"] == 1

    r = client.delete(f"/api/v1/route-categories/{row['id']}", headers=h)
    assert r.status_code == 400, r.text
    assert "1 条" in r.json()["detail"], r.json()["detail"]
    # 拒绝之后分类**原样还在**（先删再验的写法会在这里留下一片"未分类"）
    assert _find(client, h, name) is not None

    # 把线路挪走（清成未分类）之后就能删了
    assert client.patch(
        f"/api/v1/shipper/addresses/{made.json()['id']}", headers=h, json={"category": ""}
    ).status_code == 200
    assert client.delete(f"/api/v1/route-categories/{row['id']}", headers=h).status_code == 204
    assert _find(client, h, name) is None


def test_排序必须整份提交(client, token_dispatcher):
    """只传一部分 → 400 并点名少了几个；整份倒过来 → 真的按这个顺序返回。"""
    h = auth_headers(token_dispatcher)
    cats = _roster(client, h)
    assert len(cats) >= 2, cats
    ids = [c["id"] for c in cats]

    partial = client.post("/api/v1/route-categories/reorder", headers=h, json={"ids": ids[:1]})
    assert partial.status_code == 400, partial.text
    assert "少了" in partial.json()["detail"], partial.json()["detail"]

    dup = client.post(
        "/api/v1/route-categories/reorder", headers=h, json={"ids": [ids[0], ids[0]]}
    )
    assert dup.status_code == 400 and "重复" in dup.json()["detail"], dup.text

    reversed_ids = list(reversed(ids))
    ok = client.post(
        "/api/v1/route-categories/reorder", headers=h, json={"ids": reversed_ids}
    )
    assert ok.status_code == 200, ok.text
    assert [c["id"] for c in ok.json()] == reversed_ids
    assert [c["id"] for c in _roster(client, h)] == reversed_ids


def test_重名分类被拒绝(client, token_dispatcher):
    """同一个用户下不能有两个同名分类（名册是"名字 → 顺序"的表，重名就无法回答谁排前）。"""
    h = auth_headers(token_dispatcher)
    name = "探针-线路重名"
    first = client.post("/api/v1/route-categories", headers=h, json={"name": name})
    assert first.status_code in (200, 201), first.text
    again = client.post("/api/v1/route-categories", headers=h, json={"name": name})
    assert again.status_code == 409, again.text
    assert "已经存在" in again.json()["detail"], again.json()["detail"]


def test_分类名去空格且超过32字被拒绝(client, token_dispatcher):
    """两端的口径要对齐：分类名两端都 strip，**超过 32 字一律 422**（不悄悄截断）。

    ⚠️ 「悄悄截断」在这里是最坏的选择：名册里存的是「前 32 字」，而用户在界面上看到的是
    自己敲的那 40 个字 —— 他下次按原名去找，找不到。后端那道 `_clean_category(…)[:32]`
    是**兜底**（给别的调用方），不是给人看的判据；接口这一层由 schema 先挡住。
    """
    h = auth_headers(token_dispatcher)
    row = client.post("/api/v1/route-categories", headers=h, json={"name": "  探针-线路去空格  "})
    assert row.status_code in (200, 201), row.text
    assert row.json()["name"] == "探针-线路去空格"

    too_long = "探" * 40
    bad = client.post("/api/v1/route-categories", headers=h, json={"name": too_long})
    assert bad.status_code == 422, bad.text

    # 同一把尺子也架在线路的分类那一格上（AddressCreate.category 的 max_length）
    r = _mk_route(client, h, name="长分类甲", phone="13700009106", category=too_long)
    assert r.status_code == 422, r.text


def test_货主和派单员各管各的名册(client, token_dispatcher, token_shipper):
    """按人分区：货主建的分类不进派单员的名册；派单员拿货主的分类编号去改 → 404。

    ⚠️ 是 **404 不是 403**：`category_order.py` 明写「不许区分"编号不存在"与"这行不是你的"」，
    否则这个编号存不存在会变成一条可以探测的信息。
    """
    hd = auth_headers(token_dispatcher)
    hs = auth_headers(token_shipper)
    name = "探针-线路只属于货主"
    made = client.post("/api/v1/route-categories", headers=hs, json={"name": name})
    assert made.status_code in (200, 201), made.text
    cid = made.json()["id"]

    assert _find(client, hs, name) is not None
    assert _find(client, hd, name) is None, "货主的分类漏进了派单员的名册"

    assert client.patch(
        f"/api/v1/route-categories/{cid}", headers=hd, json={"name": "偷改"}
    ).status_code == 404
    assert client.delete(f"/api/v1/route-categories/{cid}", headers=hd).status_code == 404
    # 被挡下之后还是原名
    assert _find(client, hs, name) is not None


def test_司机整组端点都被挡住(client, token_driver):
    """司机没有线路库（`ShipperOrDispatcher`）—— 读和写一起挡住，不是只挡写。"""
    h = auth_headers(token_driver)
    assert client.get("/api/v1/route-categories", headers=h).status_code == 403
    assert client.post(
        "/api/v1/route-categories", headers=h, json={"name": "司机想建线路分类"}
    ).status_code == 403
    assert client.post(
        "/api/v1/route-categories/reorder", headers=h, json={"ids": [1]}
    ).status_code == 403


def test_同号线路不会并成一条(client, token_dispatcher):
    """`/shipper/addresses` **不是 upsert**（与 `/shipper/contacts` 的差别，写在这里免得被"顺手统一"）。

    同一个号码可以有多条线路（同一个收货人送两个地方），所以第二条得**新建一行**，
    而且**不许动**第一条的分类。
    """
    h = auth_headers(token_dispatcher)
    cat = "探针-线路不去重"
    phone = "13700009107"
    first = _mk_route(client, h, name="不去重甲", phone=phone, category=cat, detail="甲地址")
    assert first.status_code == 201, first.text

    again = _mk_route(client, h, name="不去重甲", phone=phone, detail="乙地址")
    assert again.status_code == 201, again.text
    assert again.json()["id"] != first.json()["id"], "同号的第二条被并进了第一条（线路不是 upsert）"
    assert again.json()["category"] == "", "第二条自己没带分类"

    rows = client.get("/api/v1/shipper/addresses", headers=h).json()
    keep = next(r for r in rows if r["id"] == first.json()["id"])
    assert keep["category"] == cat, "新建的第二条把第一条的分类抹掉了"


def test_线路列表带回分类字段而不是null(client, db_session: Session, token_dispatcher):
    """`AddressOut.category` 是**字符串**（空串 = 未分类），⛔ 不是 null。

    老库里的行（迁移 013 之前建的）落进来就是空串 —— 客户端 Gson 会把 null 当字符串 "null"，
    左侧抽屉那一格就会多出一个叫「null」的分类。
    """
    h = auth_headers(token_dispatcher)
    other = db_session.query(ShipperAddress).filter(ShipperAddress.category == "").first()
    if other is None:
        made = _mk_route(client, h, name="未分类甲", phone="13700009108")
        assert made.status_code == 201, made.text
        target_id = made.json()["id"]
    else:
        target_id = other.id

    rows = client.get("/api/v1/shipper/addresses", headers=h).json()
    row = next((r for r in rows if r["id"] == target_id), None)
    assert row is not None, "自己名下的线路在列表里看不到"
    assert row["category"] == ""


def test_分类名不能是纯空格(client, token_dispatcher):
    """纯空格的分类名建不出来（否则名册里会出现一行**点不中、也删不掉**的空白）。"""
    h = auth_headers(token_dispatcher)
    r = client.post("/api/v1/route-categories", headers=h, json={"name": "   "})
    assert r.status_code == 422, r.text


def test_名册行数上限(client, db_session: Session, token_dispatcher, users: dict):
    """名册不会无限长：超过 200 个先让他清理（判据直接摆到边界，不靠"建 200 个"跑一遍）。"""
    from app.api.v1.route_categories import MAX_CATEGORIES

    h = auth_headers(token_dispatcher)
    owner_id = users["dispatcher"].id
    before = db_session.query(RouteCategory).filter(RouteCategory.shipper_id == owner_id).count()
    filler = [name for name in ("探针-线路占位A", "探针-线路占位B")]
    try:
        for name in filler:
            if _find(client, h, name) is None:
                assert client.post(
                    "/api/v1/route-categories", headers=h, json={"name": name}
                ).status_code in (200, 201)
        # 把这一位用户的名册凑到上限（不建 200 次，直接补库）
        need = MAX_CATEGORIES - db_session.query(RouteCategory).filter(
            RouteCategory.shipper_id == owner_id
        ).count()
        for i in range(need):
            db_session.add(
                RouteCategory(shipper_id=owner_id, name=f"探针-线路填充{i:03d}", sort_order=1000 + i)
            )
        db_session.commit()

        r = client.post("/api/v1/route-categories", headers=h, json={"name": "探针-线路第201个"})
        assert r.status_code == 400, r.text
        assert str(MAX_CATEGORIES) in r.json()["detail"], r.json()["detail"]
    finally:
        db_session.query(RouteCategory).filter(
            RouteCategory.shipper_id == owner_id,
            RouteCategory.name.like("探针-线路填充%"),
        ).delete(synchronize_session=False)
        for name in filler:
            row = _find(client, h, name)
            if row is not None:
                client.delete(f"/api/v1/route-categories/{row['id']}", headers=h)
        db_session.commit()
        after = db_session.query(RouteCategory).filter(
            RouteCategory.shipper_id == owner_id
        ).count()
        assert after <= before + 2, f"用例没把自己建的填充行清干净：{before} → {after}"
