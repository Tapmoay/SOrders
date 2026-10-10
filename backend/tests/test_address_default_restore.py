"""常用地址「删掉再恢复」要把**默认标记**还回来（测试台账 TA-14 → BUG-0032）。

## 为什么要有这一条

DELETE /shipper/addresses/{id} 会顺手把 is_default 清成 false —— 这是**故意**的：
默认标记不能留在一条列表里看不见的记录上（见 services/soft_delete.ensure_alive
里 R11-F4 的说明）。但恢复端点当时**只把 is_deleted 放回去**，默认标记就永久丢了：

    删之前是默认地址 → 恢复回来不是默认 → 用户得手动再设一次

第 4 轮测试（方向 A · 软删与恢复入口一致性普查）实测 diff = {"is_default": [1, 0]}，
而同批其它八类实体恢复后 diff 全是 {}。

## 钉住的三件事

| 判据 | 不钉住会怎样 |
|---|---|
| 恢复时若这段期间没人当默认 → 把默认还回去 | 用户每次删掉默认地址再恢复，都得再点一次「设为默认」 |
| 恢复时若别人已经当了默认 → **不抢** | 会把用户删除期间做的选择悄悄改掉（比丢标记更糟） |
| 删除时仍然把默认清掉 | 默认标记留在看不见的行上，下单页取默认地址可能取到一条已删的（R11-F4 老洞） |
"""
from __future__ import annotations

from tests.conftest import auth_headers

ADDR = {
    "name": "TA14 收货点",
    "address": "惠风东三路 40 号",
    "contact_name": "小张",
    "contact_phone": "13512345678",
}


def _create(client, h, name: str, is_default: bool) -> int:
    body = dict(ADDR, name=name, is_default=is_default)
    r = client.post("/api/v1/shipper/addresses", headers=h, json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_restore_puts_default_back_when_nobody_claimed_it(client, token_shipper):
    h = auth_headers(token_shipper)
    a = _create(client, h, "TA14-默认点", True)

    assert client.delete(f"/api/v1/shipper/addresses/{a}", headers=h).status_code == 204
    rows = {r["id"]: r for r in client.get("/api/v1/shipper/addresses", headers=h).json()}
    assert a not in rows, "删掉的地址不该还在列表里"

    r = client.post(f"/api/v1/shipper/addresses/{a}/restore", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["is_default"] is True, "恢复后默认标记没还回来（TA-14）"

    rows = {r["id"]: r for r in client.get("/api/v1/shipper/addresses", headers=h).json()}
    assert rows[a]["is_default"] is True
    assert rows[a]["id"] == a  # 同一条记录原样回来（具体字段名由 AddressOut 决定）


def test_restore_does_not_steal_someone_elses_default(client, token_shipper):
    h = auth_headers(token_shipper)
    a = _create(client, h, "TA14-原默认", True)
    b = _create(client, h, "TA14-后来的", False)

    client.delete(f"/api/v1/shipper/addresses/{a}", headers=h)
    assert client.post(f"/api/v1/shipper/addresses/{b}/set-default", headers=h).status_code == 200

    r = client.post(f"/api/v1/shipper/addresses/{a}/restore", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["is_default"] is False, "恢复把别人后来的默认抢了（比丢标记更糟）"

    rows = {r["id"]: r for r in client.get("/api/v1/shipper/addresses", headers=h).json()}
    assert rows[b]["is_default"] is True
    assert rows[a]["is_default"] is False


def test_deleted_address_never_keeps_the_default_flag(client, token_shipper, db_session):
    """删除那一刻默认标记仍要清掉（R11-F4：不能留在看不见的行上）。"""
    from app.models import ShipperAddress

    h = auth_headers(token_shipper)
    a = _create(client, h, "TA14-删前默认", True)
    client.delete(f"/api/v1/shipper/addresses/{a}", headers=h)

    row = db_session.get(ShipperAddress, a)
    db_session.refresh(row)
    assert row.is_deleted is True
    assert row.is_default is False, "删除后默认标记没清（R11-F4 老洞会回来）"
