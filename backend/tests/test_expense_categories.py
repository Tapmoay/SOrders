"""开销分类名册（`/expense-categories`）：改名级联、删除有挂账拒绝、排序整份提交、新分类自动补名册。

这一套规矩与商品分类名册**同一套**（`test_product_categories.py` 是它的对照）。
为什么开销这边也要有：用户 2026-09-20 要「开销分类……也有个分类管理」——
分类以前是**写死的枚举**（fuel/repair/…），店家加一个"违章罚款"就得改代码。
"""

from __future__ import annotations

from tests.conftest import auth_headers


def _mk_expense(client, headers, category: str, amount: str = "100.00", note: str = ""):
    return client.post(
        "/api/v1/expenses",
        headers=headers,
        json={"exp_date": "2026-09-20", "category": category, "amount": amount, "note": note},
    )


def test_新分类会自动补进名册(client, token_dispatcher):
    """在一个名册里没有的分类下记一笔开销 → 它自动进名册（排到最后）。

    否则用户得先建分类再记开销（两步做完才能用），而他手里正拿着那张发票。
    """
    h = auth_headers(token_dispatcher)
    before = client.get("/api/v1/expense-categories", headers=h).json()
    name = "装卸费-探针"
    assert name not in [c["name"] for c in before]

    r = _mk_expense(client, h, name)
    assert r.status_code in (200, 201), r.text

    after = client.get("/api/v1/expense-categories", headers=h).json()
    row = next((c for c in after if c["name"] == name), None)
    assert row is not None, f"新分类没进名册：{[c['name'] for c in after]}"
    assert row["expense_count"] == 1
    assert row["sort_order"] >= max(c["sort_order"] for c in after if c["id"] != row["id"])


def test_改名级联改掉挂着的开销(client, token_dispatcher):
    """改分类名 → 同一事务里把那些开销的 category 也改掉（不级联就会"我的开销不见了"）。"""
    h = auth_headers(token_dispatcher)
    name = "改名探针-旧"
    assert _mk_expense(client, h, name, "66.00").status_code in (200, 201)
    cats = client.get("/api/v1/expense-categories", headers=h).json()
    cid = next(c["id"] for c in cats if c["name"] == name)

    new_name = "改名探针-新"
    r = client.patch(f"/api/v1/expense-categories/{cid}", headers=h, json={"name": new_name})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == new_name

    rows = client.get("/api/v1/expenses", headers=h, params={"category": new_name}).json()
    assert len(rows) == 1 and rows[0]["amount"] == "66.00", rows
    # 旧名字下已经没有东西了（级联是"改"不是"复制"）
    assert client.get("/api/v1/expenses", headers=h, params={"category": name}).json() == []


def test_还有开销挂着的分类不许删(client, token_dispatcher):
    """删除有名下开销的分类 → 400 且告诉他还有几笔（不"顺手把开销改成别的分类"）。"""
    h = auth_headers(token_dispatcher)
    name = "删除探针"
    assert _mk_expense(client, h, name, "18.00").status_code in (200, 201)
    cats = client.get("/api/v1/expense-categories", headers=h).json()
    cid = next(c["id"] for c in cats if c["name"] == name)

    r = client.delete(f"/api/v1/expense-categories/{cid}", headers=h)
    assert r.status_code == 400, r.text
    assert "1 笔" in r.json()["detail"], r.json()["detail"]

    # 空分类可以删
    created = client.post("/api/v1/expense-categories", headers=h, json={"name": "空分类探针"})
    assert created.status_code in (200, 201), created.text
    assert client.delete(f"/api/v1/expense-categories/{created.json()['id']}", headers=h).status_code == 204


def test_排序必须整份提交(client, token_dispatcher):
    """只传一部分 → 400 并点名少了哪些（"没提到的排哪儿"没有答案，按保持原序实现两端都会错）。"""
    h = auth_headers(token_dispatcher)
    cats = client.get("/api/v1/expense-categories", headers=h).json()
    assert len(cats) >= 2, cats

    partial = client.post(
        "/api/v1/expense-categories/reorder", headers=h, json={"ids": [cats[0]["id"]]}
    )
    assert partial.status_code == 400, partial.text
    assert "少了" in partial.json()["detail"], partial.json()["detail"]

    # 整份倒过来 → 200，且顺序真的反了
    ids = [c["id"] for c in reversed(cats)]
    r = client.post("/api/v1/expense-categories/reorder", headers=h, json={"ids": ids})
    assert r.status_code == 200, r.text
    assert [c["id"] for c in r.json()] == ids


def test_主要关联可改_卡片按它突出(client, token_dispatcher):
    """`link_kind`（卡片突出哪一项）是**每个分类自己带的**：用户点名不许一刀切。"""
    h = auth_headers(token_dispatcher)
    created = client.post(
        "/api/v1/expense-categories", headers=h, json={"name": "关联探针", "link_kind": "vehicle"}
    )
    assert created.status_code in (200, 201), created.text
    assert created.json()["link_kind"] == "vehicle"

    cid = created.json()["id"]
    patched = client.patch(f"/api/v1/expense-categories/{cid}", headers=h, json={"link_kind": "order"})
    assert patched.status_code == 200 and patched.json()["link_kind"] == "order"

    bad = client.patch(f"/api/v1/expense-categories/{cid}", headers=h, json={"link_kind": "随便写的"})
    assert bad.status_code == 422, bad.text


def test_名册外的分类名不会让开销消失(client, token_dispatcher, db_session):
    """直接把开销写进库里、绕开接口（名册里没有它）→ 列表仍然要能看到这笔钱。

    ⚠️ 这是本项目反复出现过的一类错：**"不在名册里"被当成"不存在"**，
    于是钱在库里、界面上没有，而且谁都不报错。
    """
    h = auth_headers(token_dispatcher)
    from datetime import date
    from decimal import Decimal

    from app.models import Expense

    db_session.add(
        Expense(exp_date=date(2026, 9, 20), category="库里直接写的分类", amount=Decimal("5.00"))
    )
    db_session.commit()

    rows = client.get("/api/v1/expenses", headers=h).json()
    assert any(r["category"] == "库里直接写的分类" for r in rows), rows[:3]
    cats = client.get("/api/v1/expense-categories", headers=h).json()
    extra = next((c for c in cats if c["name"] == "库里直接写的分类"), None)
    assert extra is not None, "名册外的分类要兜底出现在列表末尾（否则界面上的分类栏里点不到它）"
    assert extra["id"] == 0 and extra["expense_count"] == 1
