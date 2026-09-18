"""文本入参的长度上界 + **错误信息必须是中文**（2026-09-18 用户要求「文本长度做一个限制」）。

### 这一份钉的是什么
1. **太长要拒**：8000 字的长文本不能照收（本地 SQLite 会收，生产 MySQL 是 `Data too long`）；
2. **拒绝的理由要看得懂**：422 的 `detail` 必须是一句中文，说清"哪个字段、最多多少字"
   —— Pydantic 默认给的是 `{"detail":[{"type":"string_too_long",…}]}` 这种英文结构体，
   手机界面（`core/ApiClient.kt::parseDetail`）与 AI 都会把它摆给用户；
3. **判据锚效果**：被拒之后**库里那一行不许变**（"先写后报错"是最坏的一种）；
4. **边界要能过**：刚好等于上限的值必须被接受——否则"限制"就成了"把功能关掉"。
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers

ENGLISH_MARKERS = ("String should", "Field required", "Input should", "List should", "value is not")


def _detail(r) -> str:
    body = r.json()
    d = body.get("detail")
    assert isinstance(d, str), f"422 的 detail 应该是一句中文，实际是 {type(d).__name__}：{r.text[:200]}"
    return d


def _assert_chinese(r, must_contain: str) -> str:
    d = _detail(r)
    assert any("\u4e00" <= ch <= "\u9fff" for ch in d), f"错误信息里没有中文：{d}"
    assert not any(m in d for m in ENGLISH_MARKERS), f"错误信息里还有英文原文：{d}"
    assert must_contain in d, f"期望包含「{must_contain}」，实际：{d}"
    return d


def _new_order(client: TestClient, tok: str) -> int:
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(tok),
        json={"lines": [{"product_name_snapshot": "长度边界货", "quantity": 1, "unit_price": "9"}]},
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


@pytest.mark.dispatcher
@pytest.mark.shipper
@pytest.mark.fast
def test_文本超长被拒且给出中文字段与上限(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """三条最有代表性的长文本路径：备注（TEXT）、送货说明（String(512)）、多图（条数）。"""
    oid = _new_order(client, token_shipper)
    h = auth_headers(token_dispatcher)

    # ① 备注是 TEXT 列：上限是**业务**上限（4000），不是"数据库说多少就多少"
    r = client.patch(f"/api/v1/orders/{oid}", headers=h, json={"remark": "长" * 4001})
    assert r.status_code == 422, r.text
    _assert_chinese(r, "最多 4000 个字")

    # ② 送货说明是 String(512)：超了在生产 MySQL 就是 Data too long
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={"lines": [{"product_name_snapshot": "长度边界货", "quantity": 1}],
              "delivery_description": "x" * 513},
    )
    assert r.status_code == 422, r.text
    _assert_chinese(r, "最多 512 个字")

    # ③ 多图：列是 TEXT(JSON)，不设上限就能塞任意多张
    r = client.post(
        "/api/v1/shipper/addresses",
        headers=auth_headers(token_shipper),
        json={"receiver_name": "边界", "detail_address": "某地",
              "image_urls": [f"/static/uploads/x/{i}.jpg" for i in range(10)]},
    )
    assert r.status_code == 422, r.text
    _assert_chinese(r, "最多 9 项")


@pytest.mark.dispatcher
@pytest.mark.fast
def test_超长输入一条都不许落库(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """效果断言：被拒之后库里那一行的备注**一个字都没变**（防"先写后报错"）。"""
    oid = _new_order(client, token_shipper)
    h = auth_headers(token_dispatcher)
    assert client.patch(f"/api/v1/orders/{oid}", headers=h, json={"remark": "原始备注"}).status_code == 200

    r = client.patch(f"/api/v1/orders/{oid}", headers=h, json={"remark": "长" * 9000})
    assert r.status_code == 422, r.text

    got = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert got["remark"] == "原始备注", f"被拒之后备注被改了：{got['remark'][:40]}"


@pytest.mark.dispatcher
@pytest.mark.fast
def test_边长值被接受(
    client: TestClient, token_shipper: str, token_dispatcher: str
) -> None:
    """反向对照：**刚好到上限的值必须能过**（否则"限制"变成"功能没了"）。"""
    oid = _new_order(client, token_shipper)
    h = auth_headers(token_dispatcher)
    r = client.patch(f"/api/v1/orders/{oid}", headers=h, json={"remark": "字" * 4000})
    assert r.status_code == 200, r.text
    assert len(r.json()["remark"]) == 4000


@pytest.mark.dispatcher
@pytest.mark.fast
def test_其它校验失败也是中文(
    client: TestClient, token_dispatcher: str, token_shipper: str
) -> None:
    """不止"太长"：必填缺失、类型不对、日期写错、枚举越界，都不许把英文甩给用户。"""
    h = auth_headers(token_dispatcher)

    # 必填缺失（Pydantic 原文：Field required）
    r = client.post("/api/v1/driver-bills/generate", headers=h, json={})
    assert r.status_code == 422, r.text
    _assert_chinese(r, "必填")

    # 月份写成数字（原来是英文 string_type；现在是那句能照着改的中文）
    r = client.post("/api/v1/driver-bills/generate", headers=h, json={"month": 202609})
    assert r.status_code == 422, r.text
    _assert_chinese(r, "月份要写成")

    # 枚举/日期
    r = client.post(
        "/api/v1/expenses",
        headers=h,
        json={"exp_date": "不是日期", "category": "fuel", "amount": "10"},
    )
    assert r.status_code == 422, r.text
    _assert_chinese(r, "日期")

    # 收款动作只认三档（pattern 是 ^(confirm|pay|cancel)$ → 把可选项**翻成中文**列出来）
    r = client.patch(
        f"/api/v1/driver-settlements/999999",
        headers=h,
        json={"action": "乱填"},
    )
    assert r.status_code == 422, r.text
    _assert_chinese(r, "只能是 确认 / 付款 / 作废")

    # 原始错误数组仍然留着（排障要用），但界面只读 detail
    body = r.json()
    assert isinstance(body.get("errors"), list) and body["errors"], "排障用的 errors 丢了"
