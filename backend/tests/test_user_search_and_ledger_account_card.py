"""按「人」搜索 + 账本账户卡片的两条新出参（2026-09-19，用户点名）。

用户原话：「还有其他的比如说，**司机管理**啊**账户管理**啊。这些也要添加搜索键。
然后这个搜索键可以根据他们的**名称**还有**电话号码**以及**电话号码的后 4 位**进行搜索」。

三件事在这一支里钉住：

| 钉什么 | 为什么必须是测试而不是注释 |
|---|---|
| `GET /users?q=` 按**名字 / 全号 / 后 4 位**都命中，且**不分大小写** | 这条规则有三个消费点（账号名册 / 客户档案 / App 账本仪表盘）。App 侧是 `ignoreCase` 的本地匹配、后端是 SQL `like`——**两边口径分叉的表现是"搜得到/搜不到"**，用户只会觉得系统坏了 |
| 空 `q` **不加任何条件**（不是"搜空串"） | 加了恒真谓词的话，"搜索生效了没有"在 `filters_used` 这类回报里就说不清，而模型会拿它当"我筛过了" |
| 账本账户卡片下发 `phone` / `is_active`，且手机号**不带软删后缀** | 没有 phone → **同名不同人分不开**、按手机号搜不了（需求只做了一半）；带 `_del160` 后缀 → 给用户一个**打不通的号** |
"""
from __future__ import annotations

from decimal import Decimal

from app.models import User
from app.services.auth_service import issue_token
from tests.conftest import auth_headers


def _make_user(client, h, phone: str, name: str, role: str = "shipper") -> int:
    r = client.post(
        "/api/v1/users",
        json={"phone": phone, "password": "pass12345", "full_name": name, "role": role},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _search(client, h, q: str) -> list[dict]:
    r = client.get("/api/v1/users", params={"q": q, "limit": 500}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- 搜索规则


def test_users_q_matches_name_full_phone_and_last_four(client, token_dispatcher):
    """姓名 / 全号 / **后 4 位** 三种写法都要命中同一个账号。"""
    h = auth_headers(token_dispatcher)
    uid = _make_user(client, h, "13900005678", "搜索探针甲")

    for q in ("搜索探针甲", "搜索探针", "13900005678", "5678"):
        ids = [int(u["id"]) for u in _search(client, h, q)]
        assert uid in ids, f"用「{q}」搜不到刚刚建的账号（命中 {ids}）"

    # 反例：号码里没有这一段就**不许**命中（否则"后 4 位搜索"等于恒真）
    ids = [int(u["id"]) for u in _search(client, h, "5679")]
    assert uid not in ids, "「5679」不该命中 13900005678 —— 子串匹配写成了别的东西"


def test_users_q_is_case_insensitive(client, token_dispatcher):
    """大小写不分：本地开发库（SQLite）与生产库（MySQL）必须给同一个答案。

    MySQL 的 `like` 默认不分大小写、SQLite **区分** —— 不在谓词里显式 `lower()`，
    同一个查询在两个库上返回不同的行（`_del` 软删账号、英文名都会踩到）。
    """
    h = auth_headers(token_dispatcher)
    uid = _make_user(client, h, "13900005679", "Search Probe")

    for q in ("search probe", "SEARCH PROBE", "Search Probe"):
        ids = [int(u["id"]) for u in _search(client, h, q)]
        assert uid in ids, f"用「{q}」搜不到「Search Probe」"


def test_users_q_blank_returns_everyone(client, token_dispatcher, users):
    """空 `q` = **不加条件**（不是"搜空串"）。"""
    h = auth_headers(token_dispatcher)
    everyone = _search(client, h, "")
    assert len(everyone) >= 3, "空搜索应返回全部账号"

    only_one = [u for u in _search(client, h, "13800000002")]
    assert len(only_one) == 1, f"按手机号全号搜应只命中一个，实际 {len(only_one)}"


def test_customers_q_uses_the_same_rule(client, token_dispatcher):
    """客户档案与账号名册**同一份谓词**（散着写就会一个能按后 4 位搜、一个不能）。"""
    h = auth_headers(token_dispatcher)
    r = client.post(
        "/api/v1/customers",
        json={"name": "客户搜索探针", "phone": "13700004321", "kind": "tmp"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    cid = int(r.json()["id"])

    for q in ("客户搜索探针", "13700004321", "4321"):
        r = client.get("/api/v1/customers", params={"q": q}, headers=h)
        assert r.status_code == 200, r.text
        ids = [int(c["id"]) for c in r.json()]
        assert cid in ids, f"客户档案用「{q}」搜不到（命中 {ids}）"


# ---------------------------------------------------------------- 账本账户卡片


def _deliver(client, h_dispatcher, h_driver, order_id: int, driver_id: int, freight: str = "100") -> None:
    r = client.post(
        f"/api/v1/orders/{order_id}/assign",
        json={"driver_id": driver_id, "freight_fee": freight},
        headers=h_dispatcher,
    )
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/orders/{order_id}/driver-ack", headers=h_driver).status_code == 200
    r = client.post(
        f"/api/v1/orders/{order_id}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/probe.jpg"]},
        headers=h_driver,
    )
    assert r.status_code == 200, r.text


def _one_order(client, h, shipper_id: int, price: str = "500") -> int:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [
                {
                    "product_name_snapshot": "搜索探针商品",
                    "quantity": 1,
                    "unit_price": price,
                    "line_total": price,
                }
            ],
            "address_detail": "搜索探针地址",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_ledger_accounts_carry_phone_and_active(
    client, token_dispatcher, token_driver, users, db_session
):
    """账本账户卡片必须带上**能拨的手机号** + 账号还能不能登录。"""
    h = auth_headers(token_dispatcher)
    hd = auth_headers(token_driver)
    oid = _one_order(client, h, users["shipper"].id)
    _deliver(client, h, hd, oid, users["driver"].id)

    r = client.get("/api/v1/ledger/accounts", params={"kind": "shipper"}, headers=h)
    assert r.status_code == 200, r.text
    hit = [a for a in r.json() if int(a.get("id") or 0) == users["shipper"].id]
    assert hit, "送达之后账本里应该有这个货主"
    row = hit[0]
    assert row["phone"] == "13800000002", f"手机号没下发或不对：{row.get('phone')!r}"
    assert row["is_active"] is True, "在用账号应报 is_active=True"


def test_ledger_accounts_phone_has_no_soft_delete_suffix(
    client, token_dispatcher, token_driver, users
):
    """软删账号的手机号要**去尾**再下发 —— 给用户看一个 `_del160` 结尾的号等于给个打不通的号。

    ⚠️ 走**真实的删除端点**造状态，不手改夹具里的账号：
       夹具是会话级的（测试库最后才 drop），手改 + commit 会把后面所有用例的前提改掉
       —— 这一版最初就是那么写的，下一个用例里 `users["shipper"]` 直接变成 None。
    """
    h = auth_headers(token_dispatcher)
    hd = auth_headers(token_driver)
    uid = _make_user(client, h, "13900007777", "软删探针")
    oid = _one_order(client, h, uid)
    _deliver(client, h, hd, oid, users["driver"].id)

    r = client.delete(f"/api/v1/users/{uid}", headers=h)
    assert r.status_code in (200, 204), r.text

    r = client.get("/api/v1/ledger/accounts", params={"kind": "shipper"}, headers=h)
    assert r.status_code == 200, r.text
    hit = [a for a in r.json() if int(a.get("id") or 0) == uid]
    assert hit, "删掉账号不该把它的历史账一起抹掉（这一页要能看到他）"
    assert hit[0]["phone"] == "13900007777", f"软删后缀没去干净：{hit[0]['phone']!r}"
    assert hit[0]["is_active"] is False, "已删除的账号必须如实报 false"


def test_freight_settlement_group_carries_driver_phone(
    client, token_dispatcher, users, db_session
):
    """司机账那一栏同样要能按手机号认人（只有名字的话同名司机分不开）。

    ⚠️ 结算页只列**按单计费**（PIECE）的司机，所以这里**新造一个** PIECE 司机，
       不去改夹具司机的 `billing_mode`（理由同上：夹具是会话级的，改了会污染后面所有用例）。
    """
    h = auth_headers(token_dispatcher)
    r = client.post(
        "/api/v1/users",
        json={
            "phone": "13900008888",
            "password": "pass12345",
            "full_name": "结算探针司机",
            "role": "driver",
            "billing_mode": "PIECE",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    driver_id = int(r.json()["id"])
    # 接单/送达必须由**被派的那个司机本人**来做（用夹具司机的令牌会 403：不是他的单）
    hd = auth_headers(issue_token(db_session.get(User, driver_id)))

    oid = _one_order(client, h, users["shipper"].id, price="500")
    _deliver(client, h, hd, oid, driver_id, freight="120")

    r = client.get(
        "/api/v1/freight-settlement",
        params={"from": "2000-01-01T00:00:00", "to": "2100-01-01T00:00:00"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    groups = r.json()["groups"]
    hit = [g for g in groups if int(g["driver_id"]) == driver_id]
    assert hit, f"刚才那一单没进结算页：{groups}"
    assert hit[0]["driver_phone"] == "13900008888", f"司机手机号没下发：{hit[0].get('driver_phone')!r}"
    assert Decimal(str(hit[0]["total"])) > 0
