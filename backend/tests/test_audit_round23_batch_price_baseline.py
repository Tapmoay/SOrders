"""回归测试：批量调价的**百分比基准**必须是"当前生效价"（2026-09-19 审计「声明式 CRUD」专项，高）。

## 缺陷形状
`POST /price-rules/batch` 的 `adjust`（涨/降百分之几）基准读的是 `pr.special_unit_price`，
而**查那一行时故意不过滤 `is_deleted`**（唯一约束要求复用软删行）。于是一条**软删的**专属价
成了基准 —— 但它对谁都不生效（列表过滤它、下单页拿不到它、客户实际按默认价成交）：

```
默认价 20，某批发商的专属价曾是 40（已删除）
「给这个批发商的这个商品降 15%」→
   AI 卡片（按可见价算）：20.00 → 17.00
   库里实际写入：         40.00 × 85% = 34.00     ← 在一份看不见的价上打折
```

用户唯一能核对的依据就是卡上那个数，所以这不是"差几毛"，是**对不上账**。

判据：软删规则不参与基准；`adjust` 之后的价格必须等于「**默认价** × (100+百分比)/100」，
并且那条规则要**复活**（`GET /price-rules` 里能看见新价）。
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from tests.conftest import auth_headers


def _mk_member(client, h, phone: str) -> int:
    r = client.post(
        "/api/v1/users",
        json={
            "phone": phone,
            "password": "pass12345",
            "full_name": "基准探针批发商",
            "role": "shipper",
            "is_member": True,
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _mk_product(client, h, name: str, default_price: str) -> int:
    r = client.post(
        "/api/v1/products",
        json={"name": name, "default_unit_price": default_price, "unit": "件"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def test_percent_adjust_ignores_a_soft_deleted_baseline(client, token_dispatcher, db_session):
    from app.models import PriceRule

    h = auth_headers(token_dispatcher)
    sid = _mk_member(client, h, "13900001001")
    pid = _mk_product(client, h, "基准探针商品A", "20")

    # ① 先给它一个"谈过的价" 40，再**删掉**（软删：行还在，价还在）
    r = client.post(
        "/api/v1/price-rules",
        json={"shipper_id": sid, "product_id": pid, "special_unit_price": "40"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    rid = int(r.json()["id"])
    assert client.delete(f"/api/v1/price-rules/{rid}", headers=h).status_code in (200, 204)

    db_session.expire_all()
    row = db_session.get(PriceRule, rid)
    assert row is not None and row.is_deleted is True, "前提不成立：规则没有被软删"
    assert Decimal(str(row.special_unit_price)) == Decimal("40"), "前提不成立：软删后价没了"

    # ② 降 15%：基准必须是**当前生效价**（默认价 20），不是那份看不见的 40
    r = client.post(
        "/api/v1/price-rules/batch",
        json={
            "shipper_ids": [sid],
            "product_ids": [pid],
            "mode": "adjust",
            "adjust_percent": "-15",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1, f"应当改了 1 条，实际 {body}"

    db_session.expire_all()
    row = db_session.get(PriceRule, rid)
    got = Decimal(str(row.special_unit_price))
    assert got == Decimal("17.00"), (
        f"降价基准用错了：期望 默认价 20 × 85% = 17.00，实际 {got}"
        "（34.00 = 软删的旧价 40 × 85% —— 在一份看不见的价上打折，"
        "而 AI 确认卡上写的是 17.00）"
    )
    assert row.is_deleted is False, "批量调价命中的软删行必须一起复活，否则列表里看不到新价"

    # ③ 列表里真的能看到它（复活的判据）
    r = client.get(f"/api/v1/price-rules?shipper_id={sid}", headers=h)
    assert r.status_code == 200, r.text
    assert any(int(x["id"]) == rid for x in r.json()), "复活后列表里应当能看到这条规则"


def test_percent_adjust_still_uses_a_live_special_price(client, token_dispatcher, db_session):
    """守卫不许把正常用法一起改掉：**生效中**的专属价仍然是基准。"""
    from app.models import PriceRule

    h = auth_headers(token_dispatcher)
    sid = _mk_member(client, h, "13900001002")
    pid = _mk_product(client, h, "基准探针商品B", "20")

    r = client.post(
        "/api/v1/price-rules",
        json={"shipper_id": sid, "product_id": pid, "special_unit_price": "40"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    rid = int(r.json()["id"])

    r = client.post(
        "/api/v1/price-rules/batch",
        json={
            "shipper_ids": [sid],
            "product_ids": [pid],
            "mode": "adjust",
            "adjust_percent": "-15",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    got = Decimal(str(db_session.get(PriceRule, rid).special_unit_price))
    assert got == Decimal("34.00"), f"生效中的专属价 40 × 85% = 34.00，实际 {got}"
