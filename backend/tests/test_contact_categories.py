"""联系人分类名册（`/contact-categories`，FEAT-0007）：改名级联、有联系人挂着拒绝删、排序整份提交、
按人分区、以及「建联系人时顺手建分类」。

这一套规矩与**地点分类**（`place_categories`）是同一套 —— 用户 2026-10-03 原话：

> 「我们的联系人好像是可以做分类的吧，同样以**左边为分类右边为列表**的形式展示出来。
>  如果没有分类功能的话，则添加新的分类功能」
> 「**对分类管理的话啊，就像我们的复用地点管理一样**」
> 「这个不只是派单人员，他拥有其他的账户也是拥有比如说**货主批发商**」

所以这里盯的是三件不说就会踩的事：
1. **归属那一格是字符串**（`shipper_contacts.category`），不是名册 id —— 名册删了/改名了，
   数据不能跟着消失，改名要**级联**（连回收站里那些一起改）；
2. **按人分区**：货主（含批发商）和派单员各有一份名册，别人的分类编号既看不到也改不动；
3. **司机没有联系人库**：整组端点对他 403（与 `/shipper/contacts` 同一个角色门）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ContactCategory, ShipperContact
from tests.conftest import auth_headers


def _mk_contact(client, headers, *, name: str, phone: str = "", category: str = ""):
    """建一个联系人（POST /shipper/contacts 是 upsert：同号/同名同空号会并进已有那条）。"""
    return client.post(
        "/api/v1/shipper/contacts",
        headers=headers,
        json={"display_name": name, "phone": phone, "category": category},
    )


def _roster(client, headers) -> list[dict]:
    return client.get("/api/v1/contact-categories", headers=headers).json()


def _find(client, headers, name: str) -> dict | None:
    return next((c for c in _roster(client, headers) if c["name"] == name), None)


def test_建联系人时顺手建分类并进名册(client, token_dispatcher):
    """在名册里没有的分类下建联系人 → 分类自动进名册（排到最后），人数是 1。

    否则用户得先建分类、再建联系人（两步做完才能用），而他手里正拿着那张名片。
    """
    h = auth_headers(token_dispatcher)
    name = "探针-顺手建分类"
    assert _find(client, h, name) is None, "探针名撞上上一轮跑剩下的了，换个名字"

    r = _mk_contact(client, h, name="顺手建分类甲", phone="13700009001", category=name)
    assert r.status_code == 201, r.text
    # 联系人自己带着这一格（空串 = 未分类，与地点那一格同一个口径）
    assert r.json()["category"] == name

    row = _find(client, h, name)
    assert row is not None, f"分类没进名册：{[c['name'] for c in _roster(client, h)]}"
    assert row["contact_count"] == 1
    # 排到最后（名册里的行比大小；GET 只返回名册行，所以直接取最大即可）
    others = [c["sort_order"] for c in _roster(client, h) if c["id"] != row["id"]]
    assert not others or row["sort_order"] >= max(others)


def test_改联系人分类也会顺手补名册(client, token_dispatcher):
    """把已有联系人改成一个新分类名 → 同样进名册（编辑路径与新建路径同一条规矩）。"""
    h = auth_headers(token_dispatcher)
    name = "探针-改出来分类"
    r = _mk_contact(client, h, name="改分类乙", phone="13700009002")
    assert r.status_code == 201, r.text
    assert r.json()["category"] == ""

    cid = r.json()["id"]
    patched = client.patch(
        f"/api/v1/shipper/contacts/{cid}", headers=h, json={"category": name}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["category"] == name
    assert _find(client, h, name) is not None


def test_改名级联改掉挂着的联系人(client, db_session: Session, token_dispatcher):
    """改分类名 → 同一事务里把那些联系人的 category 也改掉（不级联 = "我的联系人不见了"）。

    ⚠️ 连**回收站里**那条一起改：软删的行仍然带着老分类名，只改活着的会让
    「恢复」之后这个人掉进一个已经不存在（或已被别人占用）的分类里。
    """
    h = auth_headers(token_dispatcher)
    old = "探针-改名前"
    new = "探针-改名后"
    a = _mk_contact(client, h, name="改名甲", phone="13700009003", category=old)
    b = _mk_contact(client, h, name="改名乙", phone="13700009004", category=old)
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)
    # 乙进回收站（这条只在库层面看得到）
    assert client.delete(f"/api/v1/shipper/contacts/{b.json()['id']}", headers=h).status_code == 204

    row = _find(client, h, old)
    assert row is not None, _roster(client, h)
    r = client.patch(f"/api/v1/contact-categories/{row['id']}", headers=h, json={"name": new})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == new

    db_session.expire_all()
    live = db_session.get(ShipperContact, a.json()["id"])
    gone = db_session.get(ShipperContact, b.json()["id"])
    assert live.category == new, "活着的联系人没跟着改名"
    assert gone.category == new, "回收站里那条没跟着改名（恢复后会掉进一个不存在的分类）"
    # 老名字下已经没有人了（级联是"改"不是"复制"）
    assert db_session.query(ShipperContact).filter(ShipperContact.category == old).count() == 0
    assert _find(client, h, old) is None


def test_还有联系人挂着的分类不许删(client, token_dispatcher):
    """删除有名下联系人的分类 → 400 并告诉他还有几位（不"顺手把他们改成未分类"）。"""
    h = auth_headers(token_dispatcher)
    name = "探针-删除保护"
    made = _mk_contact(client, h, name="删除保护甲", phone="13700009005", category=name)
    assert made.status_code == 201, made.text
    row = _find(client, h, name)
    assert row is not None and row["contact_count"] == 1

    r = client.delete(f"/api/v1/contact-categories/{row['id']}", headers=h)
    assert r.status_code == 400, r.text
    assert "1 位" in r.json()["detail"], r.json()["detail"]
    # 拒绝之后分类**原样还在**（先删再验的写法会在这里留下一片"未分类"）
    assert _find(client, h, name) is not None

    # 把人挪走（清成未分类）之后就能删了
    assert client.patch(
        f"/api/v1/shipper/contacts/{made.json()['id']}", headers=h, json={"category": ""}
    ).status_code == 200
    assert client.delete(f"/api/v1/contact-categories/{row['id']}", headers=h).status_code == 204
    assert _find(client, h, name) is None


def test_排序必须整份提交(client, token_dispatcher):
    """只传一部分 → 400 并点名少了几个；整份倒过来 → 真的按这个顺序返回。"""
    h = auth_headers(token_dispatcher)
    cats = _roster(client, h)
    assert len(cats) >= 2, cats
    ids = [c["id"] for c in cats]

    partial = client.post("/api/v1/contact-categories/reorder", headers=h, json={"ids": ids[:1]})
    assert partial.status_code == 400, partial.text
    assert "少了" in partial.json()["detail"], partial.json()["detail"]

    dup = client.post(
        "/api/v1/contact-categories/reorder", headers=h, json={"ids": [ids[0], ids[0]]}
    )
    assert dup.status_code == 400 and "重复" in dup.json()["detail"], dup.text

    reversed_ids = list(reversed(ids))
    ok = client.post(
        "/api/v1/contact-categories/reorder", headers=h, json={"ids": reversed_ids}
    )
    assert ok.status_code == 200, ok.text
    assert [c["id"] for c in ok.json()] == reversed_ids
    assert [c["id"] for c in _roster(client, h)] == reversed_ids


def test_重名分类被拒绝(client, token_dispatcher):
    """同一个用户下不能有两个同名分类（名册是"名字 → 顺序"的表，重名就无法回答谁排前）。"""
    h = auth_headers(token_dispatcher)
    name = "探针-重名"
    first = client.post("/api/v1/contact-categories", headers=h, json={"name": name})
    assert first.status_code in (200, 201), first.text
    again = client.post("/api/v1/contact-categories", headers=h, json={"name": name})
    assert again.status_code == 409, again.text
    assert "已经存在" in again.json()["detail"], again.json()["detail"]


def test_分类名去空格且超过32字被拒绝(client, token_dispatcher):
    """两端的口径要对齐：分类名两端都 strip，**超过 32 字一律 422**（不悄悄截断）。

    ⚠️ 「悄悄截断」在这里是最坏的选择：名册里存的是「前 32 字」，而用户在界面上看到的是
    自己敲的那 40 个字 —— 他下次按原名去找，找不到（与手机号那条「宁可报错也不静默改写
    用户输入」同一条纪律）。后端那道 `_clean_category(…)[:32]` 是**兜底**（给别的调用方），
    不是给人看的判据；接口这一层由 schema 先挡住。
    """
    h = auth_headers(token_dispatcher)
    row = client.post("/api/v1/contact-categories", headers=h, json={"name": "  探针-去空格  "})
    assert row.status_code in (200, 201), row.text
    assert row.json()["name"] == "探针-去空格"

    too_long = "探" * 40
    bad = client.post("/api/v1/contact-categories", headers=h, json={"name": too_long})
    assert bad.status_code == 422, bad.text

    # 同一把尺子也架在联系人的分类那一格上（ContactCreate.category 的 max_length）
    r = _mk_contact(client, h, name="长分类甲", phone="13700009006", category=too_long)
    assert r.status_code == 422, r.text


def test_货主和派单员各管各的名册(client, token_dispatcher, token_shipper):
    """按人分区：货主建的分类不进派单员的名册；派单员拿货主的分类编号去改 → 404。

    ⚠️ 是 **404 不是 403**：`category_order.py` 明写「不许区分"编号不存在"与"这行不是你的"」，
    否则这个编号存不存在会变成一条可以探测的信息。
    """
    hd = auth_headers(token_dispatcher)
    hs = auth_headers(token_shipper)
    name = "探针-只属于货主"
    made = client.post("/api/v1/contact-categories", headers=hs, json={"name": name})
    assert made.status_code in (200, 201), made.text
    cid = made.json()["id"]

    assert _find(client, hs, name) is not None
    assert _find(client, hd, name) is None, "货主的分类漏进了派单员的名册"

    assert client.patch(
        f"/api/v1/contact-categories/{cid}", headers=hd, json={"name": "偷改"}
    ).status_code == 404
    assert client.delete(f"/api/v1/contact-categories/{cid}", headers=hd).status_code == 404
    # 被挡下之后还是原名
    assert _find(client, hs, name) is not None


def test_司机整组端点都被挡住(client, token_driver):
    """司机没有联系人库（`ShipperOrDispatcher`）—— 读和写一起挡住，不是只挡写。"""
    h = auth_headers(token_driver)
    assert client.get("/api/v1/contact-categories", headers=h).status_code == 403
    assert client.post(
        "/api/v1/contact-categories", headers=h, json={"name": "司机想建"}
    ).status_code == 403
    assert client.post(
        "/api/v1/contact-categories/reorder", headers=h, json={"ids": [1]}
    ).status_code == 403


def test_upsert没带分类不会抹掉老分类(client, token_dispatcher):
    """`POST /shipper/contacts` 是按号认人的 upsert：这次没提分类，不等于"改成未分类"。

    界面上「再存一次同一个号码」是很常见的动作（改个称呼），
    顺手把人家分好的类抹掉，用户只会觉得"分类自己丢了"。
    """
    h = auth_headers(token_dispatcher)
    cat = "探针-upsert保护"
    phone = "13700009007"
    first = _mk_contact(client, h, name="upsert甲", phone=phone, category=cat)
    assert first.status_code == 201, first.text

    again = _mk_contact(client, h, name="upsert甲改名", phone=phone)  # 这次不带分类
    assert again.status_code == 201, again.text
    assert again.json()["id"] == first.json()["id"], "同号没有被当成同一个人（建重复了）"
    assert again.json()["display_name"] == "upsert甲改名"
    assert again.json()["category"] == cat, "没带分类的那次把老分类抹掉了"


def test_联系人列表带回分类字段而不是null(client, db_session: Session, token_dispatcher):
    """`ContactOut.category` 是**字符串**（空串 = 未分类），⛔ 不是 null。

    老库里的行（迁移 012 之前建的）落进来就是空串；`phone` 走的是另一条归一化
    （数据库里是 NULL、JSON 里是 ""），两者别混 —— 客户端 Gson 会把 null 当字符串 "null"。
    """
    h = auth_headers(token_dispatcher)
    other = db_session.query(ShipperContact).filter(ShipperContact.category == "").first()
    if other is None:
        made = _mk_contact(client, h, name="未分类甲", phone="13700009008")
        assert made.status_code == 201, made.text
        target_id = made.json()["id"]
    else:
        target_id = other.id

    rows = client.get("/api/v1/shipper/contacts", headers=h).json()
    row = next((r for r in rows if r["id"] == target_id), None)
    assert row is not None, "自己名下的联系人在列表里看不到"
    assert row["category"] == ""


def test_分类名不能是纯空格(client, token_dispatcher):
    """纯空格的分类名建不出来（否则名册里会出现一行**点不中、也删不掉**的空白）。"""
    h = auth_headers(token_dispatcher)
    r = client.post("/api/v1/contact-categories", headers=h, json={"name": "   "})
    assert r.status_code == 422, r.text


def test_名册行数上限(client, db_session: Session, token_dispatcher, users: dict):
    """名册不会无限长：超过 200 个先让他清理（判据直接摆到边界，不靠"建 200 个"跑一遍）。"""
    from app.api.v1.contact_categories import MAX_CATEGORIES

    h = auth_headers(token_dispatcher)
    owner_id = users["dispatcher"].id
    before = db_session.query(ContactCategory).filter(ContactCategory.shipper_id == owner_id).count()
    filler = [name for name in ("探针-占位A", "探针-占位B")]
    try:
        for name in filler:
            if _find(client, h, name) is None:
                assert client.post(
                    "/api/v1/contact-categories", headers=h, json={"name": name}
                ).status_code in (200, 201)
        # 把这一位用户的名册凑到上限（不建 200 次，直接补库）
        need = MAX_CATEGORIES - db_session.query(ContactCategory).filter(
            ContactCategory.shipper_id == owner_id
        ).count()
        for i in range(need):
            db_session.add(
                ContactCategory(shipper_id=owner_id, name=f"探针-填充{i:03d}", sort_order=1000 + i)
            )
        db_session.commit()

        r = client.post("/api/v1/contact-categories", headers=h, json={"name": "探针-第201个"})
        assert r.status_code == 400, r.text
        assert str(MAX_CATEGORIES) in r.json()["detail"], r.json()["detail"]
    finally:
        db_session.query(ContactCategory).filter(
            ContactCategory.shipper_id == owner_id,
            ContactCategory.name.like("探针-填充%"),
        ).delete(synchronize_session=False)
        for name in filler:
            row = _find(client, h, name)
            if row is not None:
                client.delete(f"/api/v1/contact-categories/{row['id']}", headers=h)
        db_session.commit()
        after = db_session.query(ContactCategory).filter(
            ContactCategory.shipper_id == owner_id
        ).count()
        assert after <= before + 2, f"用例没把自己建的填充行清干净：{before} → {after}"
