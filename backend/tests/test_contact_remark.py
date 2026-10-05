"""联系人备注（L-10，CHG-0048）：一行自由文本，**只有自己看得见**，选人时会带进地点备注。

## 这条改动来自用户原话
「还有我们那个叫什么联系人，他也是要**有备注**的哈，我们联系人可以备注的；以及我们那个**地点**
的时候，如果选择对应的联系人，**对应的备注也会写上去**的，当然，**这个备注是可以改的**……
而此备注**只有自己才能看见**」

## 七件必须真的成立的事
1. 建联系人时写的备注**存得住、回得来**。
2. 没写备注时，出参与库里都是**空串**（不是 NULL、更不是字面量 "null"）—— 与
   `shipper_locations.remark` 逐字同形，客户端 `ContactDto.remark` 是非空 `String`。
3. `POST /contacts` 是 **upsert**（按号认人，见 CHG-0010）：这次没提备注**不能**把老备注抹掉。
   「清掉备注」只有 `PATCH {"remark": ""}` 一条路（空串 = 明确清掉）。
4. `PATCH` **不带 `remark` 键 = 不动它** —— 编辑界面的保存是「整份回传」，少回一项就静默清掉。
5. 长度边界：256 字放行、257 字 422（上限由 `ContactCreate.remark` / `ContactUpdate.remark`
   的 `max_length=256` 给，与地点备注**同一个数** —— 带过去不该被截断）。
6. 前后空白先 strip（"   " 存成空串，不是三个空格）。
7. **只有自己看得见**：另一个账号既看不到这条备注、也改不动 / 删不动这行联系人（404）。

## ⛔ 这条用例证不了什么
- 不证客户端把备注**带进地点备注栏**、也不证「那一栏随后归用户自己改」——
  那是 `AddressViewModel.applyPickedContact` 与界面的行为（静态判据 `_tools/qa/_check_contact_remark.py` 管）。
- 不证共享地点库（`places`）里没有备注 —— 那是模型层的事（同上，静态判据管）。
- 不证订单出参 / 派单侧看不到备注 —— 同上，是 `ContactOut` 的引用面问题，不是行为问题。
"""
from __future__ import annotations

import uuid

from app.models.shipper import ShipperContact


def _name() -> str:
    """每次现算一个不重名的联系人名（端点内部 commit，写死的名字会互相干扰）。"""
    return f"备注-{uuid.uuid4().hex[:8]}"


def _mobile() -> str:
    """现算一个合法且不重号的手机号（users.phone / uq_shipper_contact_phone 都有唯一约束）。"""
    return "138" + str(uuid.uuid4().int)[:8]


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mk(client, headers, *, name=None, phone=None, remark=None) -> dict:
    """建一条联系人；**`None` = 这个键整个不发**（与"发了空串"是两件不同的事）。"""
    payload: dict[str, object] = {}
    if name is not None:
        payload["display_name"] = name
    if phone is not None:
        payload["phone"] = phone
    if remark is not None:
        payload["remark"] = remark
    r = client.post("/api/v1/shipper/contacts", json=payload, headers=headers)
    assert r.status_code == 201, (payload, r.status_code, r.text[:300])
    return r.json()


def test_remark_is_stored_and_returned(client, token_shipper, db_session):
    """建联系人时写的备注 → 201 出参带回，且**真的落库**（不是只在响应里）。"""
    h = _hdr(token_shipper)
    text = "老王，晚上八点以后在家，白天放门卫"
    got = _mk(client, h, name=_name(), phone=_mobile(), remark=text)
    assert got["remark"] == text, got

    db_session.expire_all()
    row = db_session.get(ShipperContact, got["id"])
    assert row is not None and row.remark == text, (got["id"], getattr(row, "remark", "<无此行>"))


def test_missing_remark_is_empty_string_not_null(client, token_shipper, db_session):
    """完全没提备注 → 出参与库里都是**空串**。

    ⛔ 出参归一成空串是有意的：客户端 `ContactDto.remark` 是非空 `String`，
    Gson 把 null 塞进去会得到字面量 "null"（与 `phone` 空号同一条理由，见 CHG-0010）。
    列本身也是 `NOT NULL DEFAULT ''`（迁移 023）—— 与 `shipper_locations.remark` 逐字同形。
    """
    h = _hdr(token_shipper)
    got = _mk(client, h, name=_name(), phone=_mobile())
    assert got["remark"] == "", got

    db_session.expire_all()
    row = db_session.get(ShipperContact, got["id"])
    assert row is not None and row.remark == "", (got["id"], getattr(row, "remark", "<无此行>"))


def test_upsert_without_remark_keeps_the_old_one(client, token_shipper):
    """同号再建一次（upsert）、这次没提备注 → **老备注还在**。

    POST 是 upsert（按号认人）。界面上"新建"时备注栏是空的，如果空串被当成"改成没备注"，
    用户在别处补过的那行说明就会**静默消失**。清空只有 PATCH 一条路。
    """
    h = _hdr(token_shipper)
    phone = _mobile()
    first = _mk(client, h, name=_name(), phone=phone, remark="原来的备注")
    again = _mk(client, h, name=_name(), phone=phone)  # ⛔ 整个 remark 键都不发
    assert again["id"] == first["id"], (first, again)
    assert again["remark"] == "原来的备注", again

    # 反过来：这次真的给了备注 → 覆盖（用户确实敲了新内容）
    third = _mk(client, h, name=_name(), phone=phone, remark="换一行")
    assert third["id"] == first["id"], (first, third)
    assert third["remark"] == "换一行", third


def test_patch_can_set_and_clear_remark(client, token_shipper, db_session):
    """PATCH 是唯一能**清掉**备注的地方：空串 = 明确清掉（与地点备注同一条语义）。"""
    h = _hdr(token_shipper)
    cid = _mk(client, h, name=_name(), phone=_mobile(), remark="先这么写")["id"]

    r = client.patch(f"/api/v1/shipper/contacts/{cid}", json={"remark": "改成这样"}, headers=h)
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert r.json()["remark"] == "改成这样", r.json()

    r2 = client.patch(f"/api/v1/shipper/contacts/{cid}", json={"remark": ""}, headers=h)
    assert r2.status_code == 200, (r2.status_code, r2.text[:300])
    assert r2.json()["remark"] == "", r2.json()

    db_session.expire_all()
    row = db_session.get(ShipperContact, cid)
    assert row is not None and row.remark == "", getattr(row, "remark", "<无此行>")


def test_patch_without_remark_key_does_not_touch_it(client, token_shipper):
    """PATCH 不带 `remark` 键（只改称呼）→ 备注**一个字都不动**。

    编辑联系人走的是「整份回传」：少回一项就静默清掉，用户在界面上完全看不出来。
    """
    h = _hdr(token_shipper)
    cid = _mk(client, h, name=_name(), phone=_mobile(), remark="别动我")["id"]

    r = client.patch(f"/api/v1/shipper/contacts/{cid}", json={"display_name": "改个称呼"}, headers=h)
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert r.json()["remark"] == "别动我", r.json()


def test_remark_is_stripped_and_length_is_capped(client, token_shipper):
    """空白先 strip；256 字放行、257 字 422（上限与地点备注**同一个数**）。"""
    h = _hdr(token_shipper)
    phone = _mobile()

    blank = _mk(client, h, name=_name(), phone=phone, remark="   ")
    assert blank["remark"] == "", blank

    edge = _mk(client, h, name=_name(), phone=_mobile(), remark="备" * 256)
    assert edge["remark"] == "备" * 256, len(edge["remark"])

    over = client.post(
        "/api/v1/shipper/contacts",
        json={"display_name": _name(), "phone": phone, "remark": "备" * 257},
        headers=h,
    )
    assert over.status_code == 422, (over.status_code, over.text[:300])


def test_only_the_owner_can_see_and_change_it(client, token_shipper, token_dispatcher, db_session):
    """备注**只有自己看得见**：另一个账号既看不到、也改不动 / 删不动这行联系人（404）。

    用一段随机串当备注，好让"看得到"这件事可以被**搜出来**断言：列表响应里根本不该出现它。
    """
    mine = _hdr(token_shipper)
    other = _hdr(token_dispatcher)
    marker = f"私事-{uuid.uuid4().hex[:10]}"
    cid = _mk(client, mine, name=_name(), phone=_mobile(), remark=marker)["id"]

    listing = client.get("/api/v1/shipper/contacts", headers=other)
    assert listing.status_code == 200, (listing.status_code, listing.text[:200])
    assert marker not in listing.text, "另一个账号的联系人列表里出现了我的备注"
    assert all(item["id"] != cid for item in listing.json()), "另一个账号看到了我的联系人"

    patched = client.patch(
        f"/api/v1/shipper/contacts/{cid}", json={"remark": "被改了"}, headers=other
    )
    assert patched.status_code == 404, (patched.status_code, patched.text[:200])
    deleted = client.delete(f"/api/v1/shipper/contacts/{cid}", headers=other)
    assert deleted.status_code == 404, (deleted.status_code, deleted.text[:200])

    # 两下都没生效：备注还是原来那行，人还在（没有软删）
    db_session.expire_all()
    row = db_session.get(ShipperContact, cid)
    assert row is not None and row.remark == marker, getattr(row, "remark", "<无此行>")
    assert row.is_deleted is False, row.is_deleted
