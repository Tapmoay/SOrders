"""联系人手机号**选填**（CHG-0010）：新建联系人不必填号，但姓名与电话至少要有一个。

## 这条改动来自用户原话
「新建联系人的时候不需要必填手机号」「在下单的时候用户或者说是货主批发商以及派单员是可以不
这个手机号的，一旦补上去了，他就自动的做一份保存」—— 于是有两件事必须一起钉住：

1. **不填号也能建**：门市、工厂、只见过一次面的司机，很多真的只有名字。
2. **补上号就存回去**：下单时补的那个号会 `PATCH` 回档案（客户端 `savePickedContactPhone`），
   所以"给一条原本没号的联系人补号"这条路径必须真的通。

## 为什么库里存 NULL 而不是空串（本文件最重要的一条）
`shipper_contacts` 上有 `uq_shipper_contact_phone (shipper_id, phone)`。SQLite / MySQL 的唯一
索引里**空串是一个真值**（两条空串相撞 → 第二条 409/500），而 **NULL 不参与唯一性比较**
（一个货主可以有很多条"没填号"的联系人）。所以列改成可空、没填就存 NULL ——
`test_two_contacts_without_phone_can_coexist` 就是这条选择的**行为证据**：
谁哪天把"存 NULL"改成"存空串"，那条用例立刻红。

## 下限：姓名和电话**至少填一个**
两个都空存下来是一条谁也认不出的记录（列表里显示「未命名」、点开也没有电话），
而且删起来都没法跟用户确认是哪一条。所以 Create / Update 都拦，文案与客户端
`InputRules.contactIdentityError` 一字不差。

## 顺带钉住的软删边界
删除时那句 `del_suffix(c.phone, ...)` 会造一个假号码（`138****_del12`）把真号释放出来给下一条用。
**没填号的行必须跳过这一手**：给它编一个 `_del{id}` 等于凭空写一个号码进"电话"列。
恢复那条路也一样（原来是 `c.phone.endswith(...)`，遇到 NULL 直接 AttributeError → 500）。
"""
from __future__ import annotations

import uuid

from app.models.shipper import ShipperContact

#: Create / Update 两侧都拦的那句话（客户端 `InputRules.contactIdentityError` 用的是同一句）。
IDENTITY_MESSAGE = "联系人的姓名和手机号至少填一个"


def _name() -> str:
    """每次现算一个不重名的联系人名（端点内部 commit，写死的名字会互相干扰）。"""
    return f"选填手机号-{uuid.uuid4().hex[:8]}"


def _mobile() -> str:
    """现算一个合法且不重号的手机号（`users.phone` / `uq_shipper_contact_phone` 都有唯一约束）。"""
    return "137" + str(uuid.uuid4().int)[:8]


def test_create_contact_without_phone(client, token_dispatcher):
    """只填姓名 → 201，且出参的 `phone` 是空串（不是 null）。

    ⛔ 出参归一成空串是有意的：客户端的 `ContactDto.phone` 是非空 `String`，
    Gson 把 null 塞进去会得到字面量 "null"。
    """
    h = {"Authorization": f"Bearer {token_dispatcher}"}
    r = client.post("/api/v1/shipper/contacts", json={"display_name": _name()}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["phone"] == "", r.json()


def test_two_contacts_without_phone_can_coexist(client, token_dispatcher, db_session):
    """两条都没填号 → 都能建起来。

    这是"库里存 NULL"的**行为证据**：两个都存空串的话，第二条会撞
    `uq_shipper_contact_phone (shipper_id, phone)`（用户看到的是莫名其妙的一条 409/500）。
    """
    h = {"Authorization": f"Bearer {token_dispatcher}"}
    ids = []
    for _ in range(2):
        r = client.post("/api/v1/shipper/contacts", json={"display_name": _name()}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["phone"] == "", r.json()
        ids.append(r.json()["id"])

    # 库里那一列必须真是 NULL —— 存空串的话上面就会红，这条是用来在红的时候指出原因的。
    db_session.expire_all()
    for cid in ids:
        row = db_session.get(ShipperContact, cid)
        assert row is not None and row.phone is None, (cid, getattr(row, "phone", "<无此行>"))


def test_create_contact_with_neither_name_nor_phone_is_rejected(client, token_dispatcher):
    """姓名和电话都空 → 400 + 那句中文（不建"谁也认不出"的记录）。"""
    h = {"Authorization": f"Bearer {token_dispatcher}"}
    for payload in ({"display_name": "", "phone": ""}, {"display_name": "   ", "phone": "  "}, {}):
        r = client.post("/api/v1/shipper/contacts", json=payload, headers=h)
        assert r.status_code == 400, (payload, r.status_code, r.text[:200])
        assert IDENTITY_MESSAGE in r.text, r.text[:300]


def test_patch_can_fill_a_missing_phone(client, token_dispatcher):
    """给一条**原本没号**的联系人补上号 → 200 且真的存住了。

    这正是下单页那个"补了号就自动存回档案"（客户端 `savePickedContactPhone`）调的接口 ——
    它要是 400/409，用户补的号就静默丢了。
    """
    h = {"Authorization": f"Bearer {token_dispatcher}"}
    created = client.post("/api/v1/shipper/contacts", json={"display_name": _name()}, headers=h)
    assert created.status_code == 201, created.text
    cid = created.json()["id"]

    phone = _mobile()
    r = client.patch(f"/api/v1/shipper/contacts/{cid}", json={"phone": phone}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == phone, r.json()
    # 名字没给（None = 不改这一项）不能把它清掉
    assert r.json()["display_name"] == created.json()["display_name"], r.json()


def test_patch_clearing_both_fields_is_rejected(client, token_dispatcher):
    """把姓名和电话**同时**清空 → 400（同一条下限，改单也拦）。"""
    h = {"Authorization": f"Bearer {token_dispatcher}"}
    created = client.post(
        "/api/v1/shipper/contacts",
        json={"display_name": _name(), "phone": _mobile()},
        headers=h,
    )
    assert created.status_code == 201, created.text
    cid = created.json()["id"]

    r = client.patch(
        f"/api/v1/shipper/contacts/{cid}",
        json={"display_name": "", "phone": ""},
        headers=h,
    )
    assert r.status_code == 400, (r.status_code, r.text[:200])
    assert IDENTITY_MESSAGE in r.text, r.text[:300]


def test_patch_phone_still_conflicts(client, token_dispatcher):
    """补号补到一个**别人已经在用**的号上 → 409（不能悄悄把两条并成一条）。"""
    h = {"Authorization": f"Bearer {token_dispatcher}"}
    taken = _mobile()
    a = client.post(
        "/api/v1/shipper/contacts", json={"display_name": _name(), "phone": taken}, headers=h
    )
    assert a.status_code == 201, a.text
    b = client.post("/api/v1/shipper/contacts", json={"display_name": _name()}, headers=h)
    assert b.status_code == 201, b.text

    r = client.patch(f"/api/v1/shipper/contacts/{b.json()['id']}", json={"phone": taken}, headers=h)
    assert r.status_code == 409, (r.status_code, r.text[:200])
    assert "该电话已存在已有联系人" in r.text, r.text[:300]


def test_delete_and_restore_contact_without_phone(client, token_dispatcher, db_session):
    """没填号的联系人：删得掉、恢复得回来，而且**不会**被编出一个假号码。

    删除时那句 `del_suffix` 是为了把真号释放给下一条用；这条记录本来就没号，
    给它编一个 `_del{id}` 等于往"电话"列里写一个假号码，恢复时还会读成一个"原来有的号"。
    恢复那条路原来是 `c.phone.endswith(...)` —— NULL 上直接 AttributeError（500）。
    """
    h = {"Authorization": f"Bearer {token_dispatcher}"}
    created = client.post("/api/v1/shipper/contacts", json={"display_name": _name()}, headers=h)
    assert created.status_code == 201, created.text
    cid = created.json()["id"]

    d = client.delete(f"/api/v1/shipper/contacts/{cid}", headers=h)
    assert d.status_code == 204, (d.status_code, d.text[:200])

    db_session.expire_all()
    row = db_session.get(ShipperContact, cid)
    assert row is not None and row.is_deleted is True, cid
    assert row.phone is None, f"删除时给没填号的行编了号码：{row.phone!r}"

    back = client.post(f"/api/v1/shipper/contacts/{cid}/restore", headers=h)
    assert back.status_code == 200, (back.status_code, back.text[:200])
    assert back.json()["phone"] == "", back.json()
