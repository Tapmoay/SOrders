"""商品**显示顺序**（`products.sort_order`，2026-09-21 加的）。

## 为什么这条必须有回归测试
这一列的口径里藏着一个**反直觉**的坑，而它已经真的踩过一次（本轮实测抓到的）：

- `sort_order` 默认 **0 = 没排过**（老库补列之后所有商品都是 0）；
- 而 0/1/2… 是"第几位"，所以**只写 `ORDER BY sort_order ASC` 的话 0 会排在 1 前面** ——
  用户在「商品排序」页点「置顶」（写 1）反而把它沉到所有没排过的商品**后面**，
  界面上看就是"点了置顶，它不见了"（实测：置顶之后前三个变成 36/35/33，被置顶的 34 直接掉出前三）。

修法是列表的 `ORDER BY` 里加一个 CASE：**排过的一律在前，没排过的按 id 倒序殿后**。
本文件把三件事钉住：
1. 全是 0 时顺序 = `is_active desc, id desc`（**与加这一列之前一字不差**，老库补列不改变任何可见行为）；
2. 写了 1 的那个**真的排到第一**（置顶语义）；
3. 把 1 改回 0 之后**回到原来的位置**（用户可以反悔）。
"""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Product
from tests.conftest import auth_headers


def _make(db: Session, name: str, price: str = "10.0000") -> Product:
    p = Product(name=name, default_unit_price=price, cost_price="0", unit="件", category="")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _ids(client: TestClient, headers: dict[str, str]) -> list[int]:
    r = client.get("/api/v1/products?include_inactive=true", headers=headers)
    assert r.status_code == 200, r.text
    return [row["id"] for row in r.json()]


def test_sort_order_0_means_unranked_and_falls_back_to_usage_then_id(
    client: TestClient, db_session: Session, token_dispatcher: str
) -> None:
    h = auth_headers(token_dispatcher)
    """全是 0（= 没排过）时：**常用度 → 先创建的在前**（id 升序）。

    ⚠️ 2026-09-22 改：原来是"新的在前"（id 倒序），那是加 sort_order 之前的老行为。
    同一天定的**统一排序规则**是「谁的常用度高谁在前；一样高时**先创建的在前**」——
    用户原话：「新建的在最前面**只有第一天**的时候有效」。这一条测的就是那个兜底档。
    """
    a = _make(db_session, "排序测试A")
    b = _make(db_session, "排序测试B")
    c = _make(db_session, "排序测试C")

    ids = _ids(client, h)
    mine = [i for i in ids if i in {a.id, b.id, c.id}]
    assert mine == [a.id, b.id, c.id], "没排过也没被用过时，按 id 升序（先创建的在前）"


def test_top_puts_it_first_and_0_restores(
    client: TestClient, db_session: Session, token_dispatcher: str
) -> None:
    h = auth_headers(token_dispatcher)
    """写 1 = 置顶（**必须真的到第一**）；改回 0 = 回到原来的位置。"""
    a = _make(db_session, "排序测试A2")
    b = _make(db_session, "排序测试B2")
    c = _make(db_session, "排序测试C2")
    baseline = _ids(client, h)

    # 把最后建的那个（本来排最前）置顶 —— 它本来就在前面，所以换**中间那个**来验证
    r = client.patch(f"/api/v1/products/{b.id}", json={"sort_order": 1}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["sort_order"] == 1

    ids = _ids(client, h)
    assert ids[0] == b.id, f"置顶之后它必须排第一，实际前三个：{ids[:3]}"

    # 反悔：改回 0 → 顺序回到基线（那三个仍然按 id 倒序）
    client.patch(f"/api/v1/products/{b.id}", json={"sort_order": 0}, headers=h)
    assert _ids(client, h) == baseline, "改回 0 之后顺序要回到基线"


def test_sort_order_is_part_of_the_product_out(
    client: TestClient, db_session: Session, token_dispatcher: str
) -> None:
    h = auth_headers(token_dispatcher)
    """出参要带 `sort_order`（排序页读它判断"这一行要不要写"，缺字段会每次都重写一遍）。"""
    p = _make(db_session, "排序测试D")
    r = client.get(f"/api/v1/products/{p.id}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["sort_order"] == 0
