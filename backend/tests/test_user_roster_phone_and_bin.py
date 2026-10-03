"""名册出参里的「能拨的号码」与「回收站」（2026-10-03 真机 E2E 的 P1 / P2）。

## 抓到的形状
派单员在「账户管理」和「司机管理」里看到的"号码"是这样一串：

    13923111638_del62    13679159502_del75    13379655420_del88 …

那是删号的实现痕迹（delete_user 把号码/用户名加上 _del{id} 后缀让给新账号）。
后端**早就有**唯一的显示口径 —— services/soft_delete.py::dialable_phone（账本仪表盘、
运费结算、订单详情三处都在用），只有 api/v1/users.py 的列表出参把落库值原样端了出去。

## 判据（本文件的四条）
1. phone **不动**：表单回显用的是它（AccountManageViewModel 的 draftPhone），
   把去后缀的值端出去、再原样存回来 = 把一个已经释放给别人的号码写回这个账号；
2. phone_display 是**给人看/给人拨**的那个号：活号原样 / 软删去后缀 /
   **活着却带后缀（恢复时撞号）→ None**（那个号已经是别人的了）；
3. is_deleted 只表示**现在在回收站里**（= 号码带后缀 **且** is_active 为 False）：
   删号会顺手把 is_active 置 False，只看 is_active 的话「回收站」和「停用」长得一模一样，
   而这两件事的动作不同（回收站 → 恢复；停用 → 启用）;
4. 列表**照旧返回**回收站里的行：筛选是界面的事，后端不替用户藏数据
   （藏了之后「删除过的账号还能不能找回来」就变成一个只有 AI 知道答案的问题）。
"""

from __future__ import annotations

import uuid

from app.models import User
from tests.conftest import auth_headers


def _mk_driver(db_session, phone: str) -> User:
    u = User(
        phone=phone,
        full_name="名册显示探针司机",
        username=phone,
        password_hash="x",
        role="DRIVER",
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


def _row_of(client, headers, uid: int, phone: str) -> dict:
    """从名册列表里捞出这一行（名字/号码搜索是同一个口径，用号码找就行）。"""
    r = client.get("/api/v1/users", headers=headers, params={"q": phone, "limit": 500})
    assert r.status_code == 200, r.text
    rows = [x for x in r.json() if x["id"] == uid]
    assert rows, (
        f"名册里找不到账号 #{uid}（q={phone} 命中 {len(r.json())} 行）—— "
        "回收站里的账号也是数据，后端不许替界面把它藏起来"
    )
    return rows[0]


def test_回收站账号的名册号码不再带_del后缀(client, db_session, users, token_dispatcher):
    """P1 的本体：13923111638_del62 这种东西一个都不许端给用户看。"""
    h = auth_headers(token_dispatcher)
    phone = "139" + uuid.uuid4().hex[:8]
    a = _mk_driver(db_session, phone)
    aid = a.id
    assert client.delete(f"/api/v1/users/{aid}", headers=h).status_code in (200, 204)

    db_session.expire_all()
    row = _row_of(client, h, aid, phone)
    assert row["phone"].endswith(f"_del{aid}"), (
        f"落库的号码被改了（{row['phone']!r}）：phone 是**表单回显**用的那个值，"
        "去后缀端出去、再原样存回来会把这个号从新主人手里抢走"
    )
    assert row["phone_display"] == phone, (
        f"回收站账号的显示号码是 {row['phone_display']!r}，应当是去掉后缀的 {phone!r}"
    )
    assert row["is_deleted"] is True, (
        "回收站账号的 is_deleted 是 False —— 界面据此决定给「恢复」还是给「启用」，"
        "给错了就是按一下 400（后端对回收站账号的「启用」是拒绝的）"
    )


def test_恢复时撞号的账号不给号码(client, db_session, users, token_dispatcher):
    """这一条是 dialable_phone 存在的理由：宁可没有号码，也不能给一个错的号码。"""
    h = auth_headers(token_dispatcher)
    phone = "137" + uuid.uuid4().hex[:8]
    a = _mk_driver(db_session, phone)
    aid = a.id
    assert client.delete(f"/api/v1/users/{aid}", headers=h).status_code in (200, 204)
    b = _mk_driver(db_session, phone)          # 号码被新账号抢走
    assert client.post(f"/api/v1/users/{aid}/restore", headers=h).status_code == 200

    db_session.expire_all()
    row = _row_of(client, h, aid, phone)
    assert row["phone_display"] is None, (
        f"恢复回来的账号（号码已经是 #{b.id} 的了）下发了 {row['phone_display']!r} —— "
        "名册卡上那颗拨号键会打给一个与它毫无关系的人"
    )
    assert row["is_deleted"] is False, (
        "人已经恢复回来了（is_active=True），却还被标成「在回收站里」："
        "界面会给他一个按不出结果的「恢复」"
    )


def test_停用的账号不算回收站(client, db_session, users, token_dispatcher):
    """反向对照：停用 != 删除。停用账号的号码是好的，卡片照常显示、照常能拨。"""
    h = auth_headers(token_dispatcher)
    phone = "136" + uuid.uuid4().hex[:8]
    a = _mk_driver(db_session, phone)
    aid = a.id
    r = client.patch(f"/api/v1/users/{aid}", headers=h, json={"is_active": False})
    assert r.status_code == 200, r.text

    db_session.expire_all()
    row = _row_of(client, h, aid, phone)
    assert row["phone"] == phone
    assert row["phone_display"] == phone, "停用账号的号码被藏起来了：他并没有被删除"
    assert row["is_deleted"] is False, "停用被当成了删除（界面上会多出一个「恢复」）"


def test_在用账号的显示号码就是自己的号码(client, db_session, users, token_dispatcher):
    """最常见的那条路：两个字段与 phone 一致，别把正常账号也弄出个 None 来。"""
    h = auth_headers(token_dispatcher)
    d = users["driver"]
    row = _row_of(client, h, d.id, d.phone)
    assert row["phone"] == d.phone
    assert row["phone_display"] == d.phone
    assert row["is_deleted"] is False
