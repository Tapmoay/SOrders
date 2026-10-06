"""看得见的字（BUG-0009）：`??????` 这种**写进来时就已经坏掉**的值，只剩拦在入口一条路。

用户口径（2026-10-03）：地点卡上那张名字与地址都是六个问号的历史数据要「修编码/校验兜底」。
查下来的结论写在 `app/core/text_guard.py` 的模块 docstring 里（不是显示端、不是我们自己的
代码，是**写进来的那一刻就已经是问号**）。这一份盯四件事：

1. 判据本身：什么该拦、什么**不该**拦（边界同样写在那个 docstring 里）；
2. 四条写入路径真的挂上了闸：我的地点、订单、共享地点库、线路与联系人；
3. 拦下来之后用户看到的是**中文那句话**（422 响应的 `detail`），不是英文结构体；
4. 闸只看**这次送上来的值**：历史脏行改别的字段不会被误伤（否则"改个电话"也得先
   把库里的问号改掉，用户当场无路可走）。

⚠️ 这份用例**不**碰历史数据的清理：清掉 `shipper_locations` id=94 那类脏行要先经用户
   确认（见 `docs/changes/BUG-0009.md`）。
"""

from __future__ import annotations

from app.core import text_guard
from app.models import ShipperLocation
from tests.conftest import auth_headers

#: 建单的最小请求体（用例只换其中一格）
ORDER_BODY = {
    "lines": [
        {"product_name_snapshot": "看得见测试商品", "quantity": 1, "unit_price": "1", "unit": ""}
    ],
    "address_detail": "正常地址 1 号",
    # L-32：下单必须至少一端有联系信息（后端命令层硬拦；与 App 下单页同源）
    "contact_dongjia_name": "收货人甲",
}


def _order_body(**kw) -> dict:
    body = {**ORDER_BODY, "lines": [dict(ORDER_BODY["lines"][0])]}
    body.update(kw)
    return body


def _location(client, token: str, **kw) -> dict:
    body = {"name": kw.pop("name", "看得见地点"), "detail_address": kw.pop("detail_address", "正常地址")}
    body.update(kw)
    r = client.post("/api/v1/shipper/locations", json=body, headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()


# ── 一、判据本身 ───────────────────────────────────────────────────────────


def test_only_marks_is_rejected() -> None:
    """整串只有问号（半角/全角、可夹空白）→ 拒收，那句话里要有"只有问号"。"""
    for bad in ("??????", "?", "？？？", "? ?", "  ??  ", "?？?"):
        msg = text_guard.find(bad, "address_detail")
        assert msg is not None and "只有问号" in msg, repr(bad)


def test_marks_inside_real_text_pass() -> None:
    """正常文字里夹着的问号**放行** —— 收紧成"含连续问号"会拒掉真实表达。"""
    for ok in ("门牌???", "幸福路 1 号？", "?号仓库", "这个门牌我不确定？", "问号?在中间"):
        assert text_guard.find(ok, "address_detail") is None, ok


def test_invisible_chars_are_rejected() -> None:
    """替换符 / 孤立代理项 / 控制字符：这些不可能是人打出来的。"""
    for bad in (
        "\ufffd",
        "a\ufffdb",
        "\ud800",
        "a\ud800b",
        "\x00",
        "a\x01b",
        "a\x0bb",
        "a\x0cb",
        "\x7f",
        "\u009f",
    ):
        msg = text_guard.find(bad, "name")
        assert msg is not None and "看不见的字符" in msg, repr(bad)


def test_normal_whitespace_passes() -> None:
    """制表 / 换行 / 回车 / 纯空白：不是"看不见的字符"，放行（长度与必填归别处管）。"""
    for ok in ("a\tb", "a\nb", "a\rb", " ", "  \n ", "张三", ""):
        assert text_guard.find(ok, "name") is None, repr(ok)
    assert text_guard.find(None, "name") is None


def test_message_speaks_chinese_field_name() -> None:
    """字段名用 `validation_errors.FIELD_CN` 翻成中文；表里查不到就退回字段名本身（不猜）。"""
    assert "送货地址" in text_guard.find("??????", "address_detail")
    assert "联系人姓名" in text_guard.find("??????", "contact_name")
    assert "unknown_field" in text_guard.find("??????", "unknown_field")


def test_ensure_raises_and_ensure_fields_skips_missing() -> None:
    """`ensure` 抛的就是那句话；`ensure_fields` 对没有这个属性的对象按"没填"跳过。"""
    try:
        text_guard.ensure("??????", "name")
    except ValueError as exc:
        assert "只有问号" in str(exc)
    else:  # pragma: no cover - 走到了就是判据失效
        raise AssertionError("ensure 没有拦下整串问号")
    text_guard.ensure_fields(object(), ("name", "detail_address"))


# ── 二、四条写入路径 ───────────────────────────────────────────────────────


def test_create_location_with_only_marks_is_rejected(client, token_shipper) -> None:
    """「我的地点」= 那张出过脏数据的表（`shipper_locations`）：建的时候就要拦住，且**一行都不落库**。"""
    before = client.get("/api/v1/shipper/locations", headers=auth_headers(token_shipper)).json()
    r = client.post(
        "/api/v1/shipper/locations",
        json={"name": "??????", "detail_address": "??????"},
        headers=auth_headers(token_shipper),
    )
    assert r.status_code == 422, r.text
    assert "只有问号" in r.json()["detail"]
    after = client.get("/api/v1/shipper/locations", headers=auth_headers(token_shipper)).json()
    assert len(after) == len(before)


def test_patch_location_to_only_marks_is_rejected(client, token_shipper) -> None:
    """改地点：把名字改成整串问号 → 422，且库里原值**一个字节都没动**。"""
    loc = _location(client, token_shipper, name="正常地点", detail_address="正常地址")
    r = client.patch(
        f"/api/v1/shipper/locations/{loc['id']}",
        json={"name": "??????"},
        headers=auth_headers(token_shipper),
    )
    assert r.status_code == 422, r.text
    rows = client.get("/api/v1/shipper/locations", headers=auth_headers(token_shipper)).json()
    assert next(x for x in rows if x["id"] == loc["id"])["name"] == "正常地点"


def test_location_with_invisible_char_is_rejected(client, token_shipper) -> None:
    """替换符也要拦（客户端把解码失败的字节原样交上来时是这一种，不是问号）。"""
    r = client.post(
        "/api/v1/shipper/locations",
        json={"name": "坏\ufffd名字", "detail_address": "正常地址"},
        headers=auth_headers(token_shipper),
    )
    assert r.status_code == 422, r.text
    assert "看不见的字符" in r.json()["detail"]


def test_create_order_with_only_marks_address_is_rejected(client, token_shipper) -> None:
    """订单：`address_detail` / `contact_dongjia_name` 就是那一单里坏掉的三个字段。"""
    r = client.post(
        "/api/v1/orders", json=_order_body(address_detail="??????"), headers=auth_headers(token_shipper)
    )
    assert r.status_code == 422, r.text
    assert "送货地址" in r.json()["detail"] and "只有问号" in r.json()["detail"]

    r2 = client.post(
        "/api/v1/orders",
        json=_order_body(contact_dongjia_name="?????"),
        headers=auth_headers(token_shipper),
    )
    assert r2.status_code == 422, r2.text
    assert "收货人姓名" in r2.json()["detail"]

    # 正常值照旧能下单（闸不许把正常路也堵上）
    ok = client.post(
        "/api/v1/orders", json=_order_body(address_detail="正常地址 1 号"), headers=auth_headers(token_shipper)
    )
    assert ok.status_code == 201, ok.text


def test_place_library_rejects_only_marks(client, token_dispatcher) -> None:
    """共享地点库：建与改共用一个判词（`place_service.identify_error`）。"""
    r = client.post(
        "/api/v1/places",
        json={"name": "??????", "detail_address": "??????", "address_lat": "23.10", "address_lng": "113.40"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 422, r.text
    assert "只有问号" in r.json()["detail"]

    created = client.post(
        "/api/v1/places",
        json={"name": "看得见共享点", "detail_address": "正常地址", "address_lat": "23.11", "address_lng": "113.41"},
        headers=auth_headers(token_dispatcher),
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    bad = client.patch(f"/api/v1/places/{pid}", json={"name": "??????"}, headers=auth_headers(token_dispatcher))
    assert bad.status_code == 400, bad.text
    assert "只有问号" in bad.json()["detail"]


def test_address_and_contact_reject_only_marks(client, token_shipper) -> None:
    """线路（常用地址）与联系人名册：同一道闸，两条路都挂上。"""
    a = client.post(
        "/api/v1/shipper/addresses",
        json={"receiver_name": "??????", "detail_address": "正常地址"},
        headers=auth_headers(token_shipper),
    )
    assert a.status_code == 422, a.text
    assert "收货人" in a.json()["detail"]

    c = client.post(
        "/api/v1/shipper/contacts",
        json={"display_name": "??????"},
        headers=auth_headers(token_shipper),
    )
    assert c.status_code == 422, c.text
    assert "联系人姓名" in c.json()["detail"]


# ── 三、历史脏行不会被误伤 ─────────────────────────────────────────────────


def test_dirty_row_can_still_be_edited_field_by_field(client, db_session, token_shipper) -> None:
    """库里存着 `??????` 的历史行，**只改别的字段**照样能改（闸只看这次送上来的值）。

    为什么专门钉这一条：`docs/RECTIFICATION_REPORT_E2E.md` §5.1 记着上一次的权衡 ——
    "拦在入口会让『改个电话』也被迫先重选坐标"。历史脏数据要由用户拍板清掉，
    不能顺手把每一次编辑都变成撞墙。
    """
    loc = _location(client, token_shipper, name="历史脏行", detail_address="正常地址")
    row = db_session.get(ShipperLocation, loc["id"])
    row.name = "??????"
    row.detail_address = "??????"
    db_session.commit()

    r = client.patch(
        f"/api/v1/shipper/locations/{loc['id']}",
        json={"remark": "改个备注"},
        headers=auth_headers(token_shipper),
    )
    assert r.status_code == 200, r.text
    assert r.json()["remark"] == "改个备注"
