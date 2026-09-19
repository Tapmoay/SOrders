"""外围域两处"看不见的不一致"（2026-09-19 审计 G3 / G6）。

## G3：软删行还能被改
删除是「伪装删除」（行还在库里、只是打上 `is_deleted`）。地址/联系人/地点的 PATCH 端点
原来**不查这个标记** → 返回 200、改一条**用户已经看不见的记录**：界面上什么都没变，
用户以为自己改的是另一条；而那条数据下次恢复出来时已经是被改过的。

## G6：删挂账单位留下孤儿引用
删除前只数了"订单里有没有用"，没数 `customers.arrears_unit_id` 与
`shipper_receipts.arrears_unit_id` —— 两列都是裸 Integer（没有外键），数据库不拦、界面看不出。
删完之后客户档案上挂着一个不存在的挂账单位。
"""
from __future__ import annotations

from tests.conftest import auth_headers


def test_deleted_contact_cannot_be_updated(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    r = client.post("/api/v1/shipper/contacts", json={"name": "软删探针", "phone": "13900001111"}, headers=h)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]

    assert client.delete(f"/api/v1/shipper/contacts/{cid}", headers=h).status_code in (200, 204)

    again = client.patch(f"/api/v1/shipper/contacts/{cid}", json={"name": "改个名"}, headers=h)
    assert again.status_code == 400, f"回收站里的联系人不能再被改（实际 {again.status_code}）"


def test_deleted_address_cannot_be_updated(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    r = client.post(
        "/api/v1/shipper/addresses",
        json={"receiver_name": "软删探针", "phone": "13900002222", "detail_address": "探针地址"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    aid = r.json()["id"]
    assert client.delete(f"/api/v1/shipper/addresses/{aid}", headers=h).status_code in (200, 204)

    again = client.patch(f"/api/v1/shipper/addresses/{aid}", json={"detail_address": "改一下"}, headers=h)
    assert again.status_code == 400, f"回收站里的线路不能再被改（实际 {again.status_code}）"


def test_deleted_location_cannot_be_updated(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    r = client.post("/api/v1/shipper/locations", json={"name": "软删探针地点"}, headers=h)
    if r.status_code not in (200, 201):
        assert r.status_code in (400, 422), r.text
        return
    lid = r.json()["id"]
    assert client.delete(f"/api/v1/shipper/locations/{lid}", headers=h).status_code in (200, 204)
    again = client.patch(f"/api/v1/shipper/locations/{lid}", json={"name": "改个名"}, headers=h)
    assert again.status_code == 400, f"回收站里的地点不能再被改（实际 {again.status_code}）"


def test_arrears_unit_in_use_by_customer_cannot_be_deleted(client, users, token_dispatcher):
    """有客户档案挂在这个单位上 → 不许删（否则客户档案里留下一个不存在的单位）。"""
    h = auth_headers(token_dispatcher)
    unit = client.post("/api/v1/arrears-units", json={"name": "孤儿探针单位"}, headers=h)
    assert unit.status_code in (200, 201), unit.text
    uid = unit.json()["id"]

    cust = client.post(
        "/api/v1/customers",
        # ⚠️ 不能带 `user_id`：后端对同一个 user_id 会**复用已有客户档案**
        #    （`create_customer` 里 `if body.user_id is not None: … return dup`），
        #    于是这次 POST 返回的是别处建过的那个档案（arrears_unit_id 为空），
        #    单位上其实没有任何引用 → 删除成功。第一次写这条测试就踩了这个坑。
        json={"name": "孤儿探针客户", "kind": "tmp", "phone": "13900009999", "arrears_unit_id": uid},
        headers=h,
    )
    assert cust.status_code in (200, 201), cust.text
    assert cust.json().get("arrears_unit_id") == uid, "探针前提：客户档案要真的挂在这个单位上"

    d = client.delete(f"/api/v1/arrears-units/{uid}", headers=h)
    assert d.status_code == 400, f"还被客户档案引用的单位不能删（实际 {d.status_code}）"
    assert "客户" in d.json()["detail"]
