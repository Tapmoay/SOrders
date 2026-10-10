"""商品的**回收站**：删掉的商品要能从界面上找回来（测试台账 TA-11 / TA-03 → BUG-0035）。

## 这一条在钉什么

商品删除的确认弹窗一直承诺「列表顶端的『回收站』里可以把它恢复回来」（`ProductFormScreen.kt:325/412`、
`ProductBatchScreen.kt:290`），而 `GET /api/v1/products` **恒过滤 `is_deleted=false`** ——
客户端即便画了那个入口也**取不到任何已删商品**（所以那个入口直到 BUG-0035 都不存在）。

这一轮给这个只读端点加了两个**查询参数**（不是新端点）：

| 参数 | 语义 | 不变的红线 |
|---|---|---|
| `deleted_only=true` | 只回回收站里的（按删除时间倒序） | ⛔ 不许再套 `is_active` 过滤——删除会强制 `is_active=False`，套上去回收站恒空 |
| `include_deleted=true` | 连回收站一起看（已删的排在最后） | 活着的仍然只留在售的 |
| 两个都不带（缺省） | 与加参数之前**逐字一致**：一个已删商品都不回 | 选品页 / 改行 / 货主下单目录 / AI 读通道全走它 |

## 为什么要读库里的行
`ProductOut` **不下发** `is_deleted` / `deleted_at`（它们是内部标记），只看接口出参数不出
「它到底还在不在回收站里」。所以每一档都拿 `db_session.get(Product, pid)` 对一次账。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Product
from tests.conftest import auth_headers


def _create(client: TestClient, token: str, name: str, **extra) -> dict:
    body = {"name": name, "default_unit_price": "10", "name_color": None}
    body.update(extra)
    r = client.post("/api/v1/products", json=body, headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()


def _delete(client: TestClient, token: str, pid: int) -> None:
    r = client.delete(f"/api/v1/products/{pid}", headers=auth_headers(token))
    assert r.status_code == 204, r.text


def _list(client: TestClient, token: str, **params) -> list[dict]:
    r = client.get("/api/v1/products", params=params or None, headers=auth_headers(token))
    assert r.status_code == 200, r.text
    return r.json()


def _ids(rows: list[dict]) -> list[int]:
    return [int(x["id"]) for x in rows]


def _row(db: Session, pid: int) -> Product:
    db.expire_all()  # 接口那边的改动要重新从库里读（身份映射里可能是旧对象）
    row = db.get(Product, pid)
    assert row is not None
    return row


@pytest.mark.dispatcher
def test_deleted_product_leaves_default_list_and_shows_up_in_bin(
    client: TestClient, token_dispatcher: str, db_session: Session
) -> None:
    """缺省查询看不见它，`deleted_only=true` 只回它 —— 并且它此刻是**下架**的。"""
    p = _create(client, token_dispatcher, "BUG35-回收站里的商品")
    pid = int(p["id"])
    assert pid in _ids(_list(client, token_dispatcher)), "刚建的商品应该在缺省列表里"

    _delete(client, token_dispatcher, pid)

    # ⛔ 删除那条路会强制下架 —— 回收站分支若跟着套 is_active 过滤，这一条就会变成「回收站是空的」
    assert _row(db_session, pid).is_active is False, "删除应当强制下架（前提变了，下面的断言要重看）"
    assert pid not in _ids(_list(client, token_dispatcher)), "缺省查询一个已删商品都不该回"

    bin_ids = _ids(_list(client, token_dispatcher, deleted_only="true"))
    assert bin_ids == [pid], f"回收站应当只有它，实际 {bin_ids}"


@pytest.mark.dispatcher
def test_bin_lists_deleted_only_and_newest_delete_first(
    client: TestClient, token_dispatcher: str
) -> None:
    """回收站里**只有已删的**，而且刚删的在最上面（用户要找的就是它）。"""
    a = _create(client, token_dispatcher, "BUG35-先删的")
    b = _create(client, token_dispatcher, "BUG35-后删的")
    alive = _create(client, token_dispatcher, "BUG35-还活着的")

    _delete(client, token_dispatcher, int(a["id"]))
    _delete(client, token_dispatcher, int(b["id"]))

    bin_ids = _ids(_list(client, token_dispatcher, deleted_only="true"))
    assert int(alive["id"]) not in bin_ids, "回收站里混进了活着的商品"
    # ⚠️ 断言**相对顺序**而不是整表相等：同一个测试库在整轮里是共用的，
    #    别的用例删过的商品也会躺在回收站里（那是正确行为，不是脏数据）。
    assert int(a["id"]) in bin_ids and int(b["id"]) in bin_ids, f"两条都该在回收站里：{bin_ids}"
    assert bin_ids.index(int(b["id"])) < bin_ids.index(int(a["id"])), (
        f"回收站没有按删除时间倒序（后删的应当在前）：{bin_ids}"
    )


@pytest.mark.dispatcher
def test_include_deleted_keeps_alive_rows_and_puts_deleted_last(
    client: TestClient, token_dispatcher: str
) -> None:
    """`include_deleted=true` = 连回收站一起看，已删的**殿后**（不是插在在售商品中间）。"""
    alive = _create(client, token_dispatcher, "BUG35-一起看的活商品")
    dead = _create(client, token_dispatcher, "BUG35-一起看的已删商品")
    _delete(client, token_dispatcher, int(dead["id"]))

    rows = _ids(_list(client, token_dispatcher, include_deleted="true"))
    assert int(alive["id"]) in rows and int(dead["id"]) in rows, f"两行都该在：{rows}"
    assert rows[-1] == int(dead["id"]), f"已删的应当排在最后：{rows}"
    assert int(dead["id"]) not in _ids(_list(client, token_dispatcher)), "不带参数时不该看得见它"


@pytest.mark.dispatcher
def test_bin_is_a_read_only_view_and_never_touches_rows(
    client: TestClient, token_dispatcher: str, db_session: Session
) -> None:
    """回收站是**纯读**：看一眼不改任何一行的字段与软删标记。"""
    p = _create(client, token_dispatcher, "BUG35-只看不动")
    pid = int(p["id"])
    _delete(client, token_dispatcher, pid)
    before = _row(db_session, pid)
    snapshot = (before.is_deleted, before.is_active, before.deleted_at, before.name, before.stock)

    _list(client, token_dispatcher, deleted_only="true")
    _list(client, token_dispatcher, include_deleted="true")

    after = _row(db_session, pid)
    assert (after.is_deleted, after.is_active, after.deleted_at, after.name, after.stock) == snapshot, (
        "拉一次回收站就改了库里的行 —— 它必须是只读的"
    )


@pytest.mark.dispatcher
def test_bin_returns_only_rows_that_are_really_deleted(
    client: TestClient, token_dispatcher: str, db_session: Session
) -> None:
    """回收站 = 200 + 列表，而且**每一行**在库里都是真的 `is_deleted=True`。

    ⚠️ 这一条不假设「回收站是空的 / 只有我这几行」：同一个测试库整轮共用，
    别的用例删过的商品躺在里面是正确行为。要钉的是**只列已删的**这条不变量，
    以及「缺省查询与回收站**没有任何交集**」。
    """
    rows = _list(client, token_dispatcher, deleted_only="true")
    assert isinstance(rows, list), "回收站应当永远是 200 + 列表（空的也是 []，不是 404）"
    for x in rows:
        assert _row(db_session, int(x["id"])).is_deleted is True, (
            f"回收站里出现了没被删的商品：{x['id']} {x['name']}"
        )
    bin_ids = set(_ids(rows))
    alive_ids = set(_ids(_list(client, token_dispatcher)))
    assert not (bin_ids & alive_ids), f"同一件商品同时出现在两个视图里：{bin_ids & alive_ids}"


@pytest.mark.dispatcher
def test_restore_brings_the_row_back_exactly(
    client: TestClient, token_dispatcher: str, db_session: Session
) -> None:
    """删→（缺省查不到 / 回收站查得到）→恢复→（缺省查得到 / 回收站里没了），且字段逐项原样。"""
    before = _create(
        client,
        token_dispatcher,
        "BUG35-原样恢复",
        unit="箱",
        category="BUG35-分类",
        stock=37,
        low_stock_alert=5,
        cost_price="6.5",
        no_discount=True,
    )
    pid = int(before["id"])
    _delete(client, token_dispatcher, pid)
    assert pid not in _ids(_list(client, token_dispatcher))
    assert pid in _ids(_list(client, token_dispatcher, deleted_only="true"))

    r = client.post(f"/api/v1/products/{pid}/restore", headers=auth_headers(token_dispatcher))
    assert r.status_code == 200, r.text
    after = r.json()

    assert after == before, "恢复回来的商品与删之前不是同一行字段（逐项对比）"
    assert _row(db_session, pid).is_deleted is False, "恢复后不该还在回收站里"
    assert pid in _ids(_list(client, token_dispatcher)), "恢复后缺省列表里应当又能看到它"
    assert pid not in _ids(_list(client, token_dispatcher, deleted_only="true")), (
        "恢复后它还留在回收站里 —— 用户会以为恢复没生效"
    )


@pytest.mark.shipper
def test_non_manager_cannot_open_the_bin(client: TestClient, token_shipper: str) -> None:
    """货主没有 product:manage ⇒ 两个参数都 403（**不静默降级成「回收站是空的」**）。"""
    for params in ({"deleted_only": "true"}, {"include_deleted": "true"}):
        r = client.get("/api/v1/products", params=params, headers=auth_headers(token_shipper))
        assert r.status_code == 403, f"{params} 应当 403，实际 {r.status_code}"
        assert "回收站" in r.json()["detail"], r.text
    # 缺省查询照旧（老客户端不带参数，一个字都没变）
    assert client.get("/api/v1/products", headers=auth_headers(token_shipper)).status_code == 200
