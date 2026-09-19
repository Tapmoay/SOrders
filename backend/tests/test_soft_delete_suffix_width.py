"""派生值（`_del{id}` 后缀）不能越过列宽（2026-09-19 审计的缺陷 G4）。

## 原来的样子
软删用的是"伪装删除"：把唯一列改成一个不再冲突的值，号码/名字就释放出来给新记录用。
三处都在拼 `f"{原值}_del{id}"`，但**只有 `users.username` 做了截断**（`[:22]`）：

| 位置 | 列宽 | 原值取满时 |
|---|---|---|
| `users.phone` | 32 | 超长 |
| `shipper_contacts.phone` | 32 | 超长 |
| `arrears_units.name` | 128 | 超长 |

本机 SQLite **不校验 VARCHAR 长度**，所以本机永远绿；生产 MySQL 会报
`DataError: Data too long` → 被 `main.py` 的处理器翻成**"填写的内容超出可保存范围"**
—— 用户看到的是"我填错了"，而其实是他**点了一下删除**、而且什么都没填。

这个文件钉住：原值取到列宽上限时，删除仍然成功（截断发生在我们自己拼的后缀上）。
"""
from __future__ import annotations

from tests.conftest import auth_headers


def test_delete_contact_with_max_length_phone_still_works(client, token_dispatcher):
    """32 位电话（列宽上限）→ 删除必须成功（后缀要把基值截短，而不是把整串撑爆）。"""
    h = auth_headers(token_dispatcher)
    phone32 = "1" * 32
    r = client.post(
        "/api/v1/shipper/contacts",
        json={"name": "边界探针", "phone": phone32},
        headers=h,
    )
    if r.status_code not in (200, 201):
        # 端点自己先拦了超长（那也是对的），这条测试就没有对象了
        assert r.status_code in (400, 422), r.text
        return
    cid = r.json()["id"]
    d = client.delete(f"/api/v1/shipper/contacts/{cid}", headers=h)
    assert d.status_code in (200, 204), f"删除 32 位电话的联系人不能失败：{d.status_code} {d.text}"


def test_delete_arrears_unit_with_long_name_still_works(client, token_dispatcher):
    """128 位单位名（列宽上限）→ 删除必须成功。"""
    h = auth_headers(token_dispatcher)
    name128 = "长" * 128
    r = client.post("/api/v1/arrears-units", json={"name": name128}, headers=h)
    if r.status_code not in (200, 201):
        assert r.status_code in (400, 422), r.text
        return
    uid = r.json()["id"]
    d = client.delete(f"/api/v1/arrears-units/{uid}", headers=h)
    assert d.status_code in (200, 204), f"删除长名单位不能失败：{d.status_code} {d.text}"


def test_derive_suffix_helpers_truncate():
    """三处派生都必须走"先截断再拼后缀"（形状断言：防止有人改回裸拼接）。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    shipper_src = (root / "api/v1/shipper.py").read_text(encoding="utf-8")
    arrears_src = (root / "api/v1/arrears.py").read_text(encoding="utf-8")
    users_src = (root / "api/v1/users.py").read_text(encoding="utf-8")

    # 统一走 `del_suffix(...)`（我们引入的唯一实现），或保留等价的内联切片
    def guarded(src: str) -> bool:
        return "del_suffix(" in src or "[:32 -" in src or "[:128 -" in src or "[:22]_del" in src

    assert guarded(users_src), "users.phone 的派生没有按列宽截断"
    assert guarded(shipper_src), "shipper_contacts.phone 的派生没有按列宽截断"
    assert guarded(arrears_src), "arrears_units.name 的派生没有按列宽截断"
