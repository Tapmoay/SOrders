"""地点绑定的联系人（2026-09-24 用户要求）。

用户原话：「同时再给他添加个功能就是**可以通过地点来绑定联系人**，就大家选择地点之后，
自动填入对应的联系人。…包括这个功能，我们的**派单员**，它也要具有这个功能，
也可以通过**地点或者是线路**去绑定联系人，呃货主他也可以通过线路绑定联系人都是可以的。」

这一份盯四件事（前三件是"用户看得见"的，第四件是删除那一套硬规矩）：
1. 建地点时能带上联系人，读回来还是那两个值；
2. **PATCH 的三档语义**：不传 = 不改、传值 = 改、传空串 = 解绑（三档混淆的后果是
   "改个地点名字，收货人电话凭空没了"）；
3. 电话号码走的是**全项目唯一那条规则**（`app/core/phone.py`，7~12 位数字），
   不是地点这一块自己另写一条；
4. 软删 → 恢复之后联系人还在（用户 2026-09-20 的硬规矩：所有删除都是伪装删除 + 要能恢复）。

⚠️ 与线路（`shipper_addresses.receiver_name` / `phone`）**同一口径：存快照串、不存外键**。
   所以这里刻意**不**建 `shipper_contacts` 记录：名册回答的是"我认识哪些人"，
   地点上这两个字段回答的是"送到这儿通常谁收货"。名册删人/改名都不该动这一份快照。
"""

from __future__ import annotations

from tests.conftest import auth_headers


def _create_location(client, token: str, **kw) -> dict:
    body = {
        "name": kw.pop("name", "老王家仓库"),
        "detail_address": kw.pop("detail_address", "XX 路口进来第三家"),
    }
    body.update(kw)
    r = client.post("/api/v1/shipper/locations", json=body, headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()


def test_location_carries_contact(client, token_shipper):
    """建地点时带上联系人 → 出参带回来，列表里也读得到。"""
    loc = _create_location(
        client, token_shipper, contact_name="王老板", contact_phone="13800001111"
    )
    assert loc["contact_name"] == "王老板"
    assert loc["contact_phone"] == "13800001111"

    rows = client.get("/api/v1/shipper/locations", headers=auth_headers(token_shipper)).json()
    mine = next(x for x in rows if x["id"] == loc["id"])
    assert (mine["contact_name"], mine["contact_phone"]) == ("王老板", "13800001111")


def test_location_without_contact_is_empty_not_missing(client, token_shipper):
    """没绑联系人 = 两个空串（**不是**缺字段）：客户端按"空就不回填"判，缺字段会变成 null 崩在别处。"""
    loc = _create_location(client, token_shipper, name="没绑人的地点")
    assert loc["contact_name"] == ""
    assert loc["contact_phone"] == ""


def test_patch_three_states_of_contact(client, token_shipper):
    """PATCH 的三档：不传 = 不改；传值 = 改；传空串 = 解绑。"""
    loc = _create_location(
        client, token_shipper, name="三档地点", contact_name="王老板", contact_phone="13800001111"
    )
    hid = loc["id"]

    # ① 只改名字 → 联系人原样（不传 ≠ 清空）
    r = client.patch(
        f"/api/v1/shipper/locations/{hid}", json={"name": "改了个名"}, headers=auth_headers(token_shipper)
    )
    assert r.status_code == 200, r.text
    assert (r.json()["contact_name"], r.json()["contact_phone"]) == ("王老板", "13800001111")

    # ② 只改名字那一栏 → 电话原样（两栏各自独立）
    r = client.patch(
        f"/api/v1/shipper/locations/{hid}", json={"contact_name": "李经理"}, headers=auth_headers(token_shipper)
    )
    assert r.status_code == 200, r.text
    assert (r.json()["contact_name"], r.json()["contact_phone"]) == ("李经理", "13800001111")

    # ③ 传空串 → 解绑
    r = client.patch(
        f"/api/v1/shipper/locations/{hid}",
        json={"contact_name": "", "contact_phone": ""},
        headers=auth_headers(token_shipper),
    )
    assert r.status_code == 200, r.text
    assert (r.json()["contact_name"], r.json()["contact_phone"]) == ("", "")


def test_contact_phone_uses_the_one_phone_rule(client, token_shipper):
    """电话格式走 `app/core/phone.py` 唯一那条规则：汉字/字母/太短都不许进库。"""
    for bad in ("abc", "嘿嘿", "12345"):
        r = client.post(
            "/api/v1/shipper/locations",
            json={"name": "坏号码", "contact_phone": bad},
            headers=auth_headers(token_shipper),
        )
        assert r.status_code == 422, f"{bad} 竟然被收下了：{r.status_code} {r.text}"

    # 座机（010 + 8 位 = 11 位、不以 1 开头）**必须放行** —— 那条规则的注释里写了理由
    loc = _create_location(client, token_shipper, name="座机地点", contact_phone="01012345678")
    assert loc["contact_phone"] == "01012345678"


def test_restored_location_keeps_contact(client, token_shipper):
    """软删 → 恢复：联系人跟着回来（伪装删除，恢复时逐字段照搬）。"""
    loc = _create_location(
        client, token_shipper, name="要删的地点", contact_name="王老板", contact_phone="13800001111"
    )
    hid = loc["id"]

    assert client.delete(f"/api/v1/shipper/locations/{hid}", headers=auth_headers(token_shipper)).status_code == 204
    r = client.post(f"/api/v1/shipper/locations/{hid}/restore", headers=auth_headers(token_shipper))
    assert r.status_code == 200, r.text
    assert (r.json()["contact_name"], r.json()["contact_phone"]) == ("王老板", "13800001111")


def test_contact_is_per_user(client, token_shipper, token_dispatcher):
    """地点按登录人隔离：派单员读不到货主那条（两个人各自一份地点库）。"""
    loc = _create_location(
        client, token_shipper, name="货主的地点", contact_name="王老板", contact_phone="13800001111"
    )
    rows = client.get("/api/v1/shipper/locations", headers=auth_headers(token_dispatcher)).json()
    assert all(x["id"] != loc["id"] for x in rows)
