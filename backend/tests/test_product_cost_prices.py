"""商品的**多个成本价**（FEAT-0025，用户 2026-10-11 派单）。

## 用户要的是什么（原话）
> 「我们是可以设置多个成本价的，AI 也都可以调。只不过我们一般情况下是默认按一个成本价，
>   也就是真实成本价，按那个来计算的，一般订单都是按那个来计算的。当然，我们有时候计算的
>   时候还有第二个成本价 —— 这个成本价可能是加了其他东西、或者比如说有补贴啊等等之后的
>   成本价。所以一定要有多个成本价啊。」

真机上 AI 当时回的是「系统里每个商品只有一个成本价……只能留一个」—— 这组用例钉的就是
「不再只有一个」，而且**默认口径一个字都没变**。

## ⛔ 这组里最重要的是最后两条（钱的口径）
默认那个口径依旧是 `products.cost_price`（真实成本价）：订单行的 `cost_price_snapshot`、
毛利报表的成本基数（`services/cost_basis.py`）都**只认它**。附加口径
（"返点后成本" / "补贴后成本"…）一个字节都不参与金额计算 ——
`test_order_cost_snapshot_ignores_extra_cost_prices` 与
`test_extra_cost_prices_never_enter_the_cost_history` 就是钉这件事的：
谁把"默认按第二个算"做出来，这两条必须先红。
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import OperationLog, OrderProduct, Product, ProductCostHistory, ProductCostPrice
from app.models.enums import OperationAction
from tests.conftest import auth_headers

BASE = "/api/v1/products"
DEFAULT_NAME = "真实成本价"


def _uniq(prefix: str) -> str:
    """商品名带上这个（商品名没有唯一约束，但用例之间会互相看见对方的行）。"""
    from uuid import uuid4

    return f"{prefix}-{uuid4().hex[:8]}"


def _mk_product(client, h, name: str, cost: str = "4", price: str = "10") -> int:
    r = client.post(
        BASE,
        json={"name": name, "default_unit_price": price, "cost_price": cost, "stock": 100},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _add(client, h, pid: int, name: str, amount: str):
    return client.post(
        f"{BASE}/{pid}/cost-prices", json={"name": name, "cost_price": amount}, headers=h
    )


def _rows(client, h, pid: int, **params) -> list[dict]:
    r = client.get(f"{BASE}/cost-prices", params={"product_id": pid, **params}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _by_name(rows: list[dict], name: str) -> dict | None:
    return next((x for x in rows if x["name"] == name), None)


def _max_log_id(db) -> int:
    return int(db.scalar(select(func.max(OperationLog.id))) or 0)


def _mk_order(client, h, shipper_id: int, pid: int, qty: int = 1, price: str = "100") -> dict:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [
                {
                    "product_id": pid,
                    "product_name_snapshot": "多成本价探针货",
                    "quantity": qty,
                    "unit_price": price,
                    "line_total": str(Decimal(price) * qty),
                }
            ],
            "address_detail": "多成本价探针地址",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------- 列表与默认口径
@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_first_row_is_the_synthetic_default(client, db_session, token_dispatcher):
    """列表第一条永远是**默认口径**（真实成本价），而且它不在表里。

    为什么合成而不是在库里也存一行：存了就有两份真值，而"订单与毛利按哪个算"只允许一个答案。
    """
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("默认口径探针"), cost="4")

    rows = _rows(client, h, pid)
    assert len(rows) == 1, f"新商品的成本价列表应当只有默认那一条：{rows}"
    first = rows[0]
    assert first["is_default"] is True
    assert first["name"] == DEFAULT_NAME
    assert Decimal(str(first["cost_price"])) == Decimal("4")
    assert "订单与毛利按它算" in first["note"], first["note"]
    assert first["sort_order"] < 0, "默认那条要排在所有附加口径之前"

    # ⛔ 表里不许有一条叫"真实成本价"的行（否则它就成了第二份真值）
    db_session.expire_all()
    same = db_session.scalars(
        select(ProductCostPrice).where(
            ProductCostPrice.product_id == pid, ProductCostPrice.name == DEFAULT_NAME
        )
    ).all()
    assert same == [], f"默认口径不许落进 product_cost_prices：{same}"
    # 而且它的金额就是 products.cost_price
    assert str(db_session.get(Product, pid).cost_price) == "4.0000"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_multiple_cost_prices_are_independent(client, db_session, token_dispatcher):
    """一个商品可以有**多个**成本价，各改各的、互不影响（用户要的正是"不再只能留一个"）。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("多口径探针"), cost="4")

    r1 = _add(client, h, pid, "返点后成本", "3.8")
    assert r1.status_code == 201, r1.text
    r2 = _add(client, h, pid, "补贴后成本", "3.2")
    assert r2.status_code == 201, r2.text
    r3 = _add(client, h, pid, "含运费成本", "4.5")
    assert r3.status_code == 201, r3.text
    ids = {r1.json()["id"], r2.json()["id"], r3.json()["id"]}
    assert len(ids) == 3

    rows = _rows(client, h, pid)
    assert len(rows) == 4, f"默认那条 + 三条附加口径：{rows}"

    # 只改其中一条
    r = client.patch(f"{BASE}/cost-prices/{r2.json()['id']}", json={"cost_price": "2.9"}, headers=h)
    assert r.status_code == 200, r.text
    rows = _rows(client, h, pid)
    assert Decimal(str(_by_name(rows, "补贴后成本")["cost_price"])) == Decimal("2.9")
    assert Decimal(str(_by_name(rows, "返点后成本")["cost_price"])) == Decimal("3.8")
    assert Decimal(str(_by_name(rows, "含运费成本")["cost_price"])) == Decimal("4.5")
    assert _by_name(rows, "补贴后成本")["id"] == r2.json()["id"], "改价不许换成另一行"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_ai_sets_a_second_cost_price_by_name(client, token_dispatcher):
    """**AI 设第二个成本价**（用户抱怨的那件事）：按名字 upsert —— 有就改、没有就建。

    建出来是 201、改的是 200（客户端据此知道是"新增"还是"改了已有的"）。
    """
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("AI设第二个探针"), cost="4")

    first = _add(client, h, pid, "补贴后成本", "3.2")
    assert first.status_code == 201, first.text
    again = _add(client, h, pid, "补贴后成本", "3.5")
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"], "同名再设一次必须改那一行，不是插新行"
    assert Decimal(str(again.json()["cost_price"])) == Decimal("3.5")

    rows = _rows(client, h, pid)
    assert len(rows) == 2, f"只该有默认 + 一条附加：{rows}"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_duplicate_name_never_creates_two_rows(client, token_dispatcher):
    """同名不许出现两条（唯一约束 + upsert 两条腿一起保证）。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("同名校验探针"), cost="4")
    for amount in ("1", "2", "3"):
        r = _add(client, h, pid, "返点后成本", amount)
        assert r.status_code in (200, 201), r.text
    rows = [x for x in _rows(client, h, pid) if x["name"] == "返点后成本"]
    assert len(rows) == 1, f"同名出现多条：{rows}"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_default_name_is_rejected_with_409(client, token_dispatcher):
    """⛔ 附加口径不许叫"真实成本价" —— 那是 products.cost_price，改它只有一条路。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("占用默认名探针"), cost="4")
    r = _add(client, h, pid, DEFAULT_NAME, "9")
    assert r.status_code == 409, r.text
    assert DEFAULT_NAME in r.json()["detail"]


# --------------------------------------------------------------- 软删 / 恢复
@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_soft_delete_hides_the_row_and_restore_brings_it_back_verbatim(client, db_session, token_dispatcher):
    """删 = 软删（行还在、可恢复）；恢复要**逐字段原样**放回来。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("软删恢复探针"), cost="4")
    created = _add(client, h, pid, "补贴后成本", "3.2").json()
    row_id = created["id"]

    assert client.delete(f"{BASE}/cost-prices/{row_id}", headers=h).status_code == 204
    db_session.expire_all()
    stored = db_session.get(ProductCostPrice, row_id)
    assert stored is not None and stored.is_deleted is True, "必须是软删（行还在）"
    assert stored.deleted_at is not None

    # 普通列表看不见它；回收站能看见（回收站里不合成默认那条）
    assert _by_name(_rows(client, h, pid), "补贴后成本") is None
    bin_rows = _rows(client, h, pid, deleted_only=True)
    assert [x["name"] for x in bin_rows] == ["补贴后成本"], bin_rows
    assert all(x["is_default"] is False for x in bin_rows)

    r = client.post(f"{BASE}/cost-prices/{row_id}/restore", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == row_id, "恢复的是原来那一行，不是新建一行"
    back = _by_name(_rows(client, h, pid), "补贴后成本")
    assert back is not None
    assert Decimal(str(back["cost_price"])) == Decimal(str(created["cost_price"]))
    assert back["sort_order"] == created["sort_order"], "顺序也要原样回来"


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_restore_a_live_row_is_rejected(client, token_dispatcher):
    """没被删的行"恢复"是误操作：必须 400（否则卡片看着成功、其实什么都没发生）。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("误恢复探针"), cost="4")
    row_id = _add(client, h, pid, "返点后成本", "3.8").json()["id"]
    r = client.post(f"{BASE}/cost-prices/{row_id}/restore", headers=h)
    assert r.status_code == 400, r.text


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_deleted_name_blocks_rename_and_is_revived_by_upsert(client, token_dispatcher):
    """回收站里那条占着名字：改名撞上它要 409（并说清怎么处理），而 upsert 同名就**复活**它。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("回收站同名探针"), cost="4")
    old = _add(client, h, pid, "返点后成本", "3.8").json()
    other = _add(client, h, pid, "补贴后成本", "3.2").json()
    assert client.delete(f"{BASE}/cost-prices/{old['id']}", headers=h).status_code == 204

    r = client.patch(f"{BASE}/cost-prices/{other['id']}", json={"name": "返点后成本"}, headers=h)
    assert r.status_code == 409, r.text
    assert "回收站" in r.json()["detail"], r.json()["detail"]

    revived = _add(client, h, pid, "返点后成本", "3.6")
    assert revived.status_code == 200, revived.text
    assert revived.json()["id"] == old["id"], "同名必须复活原来那一行（唯一约束让它没有第二种做法）"
    assert _by_name(_rows(client, h, pid, deleted_only=True), "返点后成本") is None


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_rename_conflict_between_live_rows_is_rejected(client, token_dispatcher):
    """两条活着的口径不许重名：含糊地合并会让用户以为改错了行。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("活行重名探针"), cost="4")
    a = _add(client, h, pid, "返点后成本", "3.8").json()
    _add(client, h, pid, "补贴后成本", "3.2")
    r = client.patch(f"{BASE}/cost-prices/{a['id']}", json={"name": "补贴后成本"}, headers=h)
    assert r.status_code == 409, r.text
    assert "已经有一条" in r.json()["detail"], r.json()["detail"]


# --------------------------------------------------------------- 部分更新 / 权限 / 路由
@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_partial_update_touches_only_the_named_field(client, token_dispatcher):
    """部分更新：只动请求里真的出现的字段；一个字段都没点名就 400。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("部分更新探针"), cost="4")
    row = _add(client, h, pid, "返点后成本", "3.8").json()

    r = client.patch(f"{BASE}/cost-prices/{row['id']}", json={"sort_order": 5}, headers=h)
    assert r.status_code == 200, r.text
    after = _by_name(_rows(client, h, pid), "返点后成本")
    assert after["sort_order"] == 5
    assert after["name"] == "返点后成本"
    assert Decimal(str(after["cost_price"])) == Decimal("3.8"), "只改顺序不许动金额"

    r = client.patch(f"{BASE}/cost-prices/{row['id']}", json={}, headers=h)
    assert r.status_code == 400, r.text


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_only_dispatcher_can_read_or_write_cost_prices(client, users, token_shipper):
    """成本是内部数：货主连商品详情里的 cost_price 都拿不到，这里更不能给。"""
    h = auth_headers(token_shipper)
    assert client.get(f"{BASE}/cost-prices", headers=h).status_code == 403
    assert (
        client.post(
            f"{BASE}/1/cost-prices", json={"name": "偷看", "cost_price": "1"}, headers=h
        ).status_code
        == 403
    )


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_cost_prices_route_is_not_swallowed_by_product_id(client, token_dispatcher):
    """路由顺序：`GET /products/cost-prices` 必须声明在 `/{product_id}` 之前。

    反了的话 Starlette 会拿 "cost-prices" 去转 int → **422**（看起来像参数填错了），
    这与 `/cost-history` 是同一个坑（`_tools/qa/_check_cost_history.py` 盯着那一条）。
    """
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("路由顺序探针"), cost="4")
    _add(client, h, pid, "返点后成本", "3.8")

    r = client.get(f"{BASE}/cost-prices", params={"product_id": pid}, headers=h)
    assert r.status_code == 200, f"路由被 /{{product_id}} 接住了？{r.status_code} {r.text}"

    # 不传 product_id：只回附加口径（默认那条属于某个具体商品，不在这里凭空合成）
    r2 = client.get(f"{BASE}/cost-prices", headers=h)
    assert r2.status_code == 200, r2.text
    assert all(x["is_default"] is False for x in r2.json())
    assert any(x["name"] == "返点后成本" for x in r2.json())


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_deleted_product_hides_its_cost_prices(client, token_dispatcher):
    """商品进了回收站：它的成本价也按"查不到"处理（否则会从回收站里漏出进价）。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("回收站商品探针"), cost="4")
    _add(client, h, pid, "返点后成本", "3.8")
    assert client.delete(f"{BASE}/{pid}", headers=h).status_code == 204
    r = client.get(f"{BASE}/cost-prices", params={"product_id": pid}, headers=h)
    assert r.status_code == 404, r.text


# --------------------------------------------------------------- ⛔ 钱的口径（本组最重要）
@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_order_cost_snapshot_ignores_extra_cost_prices(client, db_session, users, token_dispatcher):
    """⛔ **订单的成本快照只认真实成本价**：加了"第二个成本价"之后，快照一个数字都不许变。

    毛利报表是按订单行的 `cost_price_snapshot` 算的 —— 这条红了说明有人把附加口径接进了钱的路。
    """
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("订单快照探针"), cost="4")
    order = _mk_order(client, h, users["shipper"].id, pid)

    db_session.expire_all()
    line_id = db_session.scalars(
        select(OrderProduct.id).where(OrderProduct.order_id == order["id"])
    ).first()
    assert str(db_session.get(OrderProduct, line_id).cost_price_snapshot) == "4.0000"

    # 用户场景：进货之后又谈下来一笔返点 → 加一条"返点后成本"
    assert _add(client, h, pid, "返点后成本", "1.5").status_code == 201

    db_session.expire_all()
    assert str(db_session.get(Product, pid).cost_price) == "4.0000", (
        "附加口径不许改 products.cost_price（订单与毛利按它算）"
    )
    assert str(db_session.get(OrderProduct, line_id).cost_price_snapshot) == "4.0000", (
        "附加口径不许改订单行的成本快照（毛利按它算）"
    )
    # 出参上也是 4（派单员看的成本价没被"另一个口径"顶掉）
    detail = client.get(f"{BASE}/{pid}", headers=h).json()
    assert Decimal(str(detail["cost_price"])) == Decimal("4")


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_extra_cost_prices_never_enter_the_cost_history(client, db_session, token_dispatcher):
    """⛔ 附加口径不进成本价时间轴 —— 那条时间轴是"订单当时按多少算"的溯源。

    它只由 `services/cost_history.record_cost` 写（本单一个字都没动它）。
    """
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("成本时间轴探针"), cost="4")
    db_session.expire_all()
    before = db_session.scalars(
        select(ProductCostHistory).where(ProductCostHistory.product_id == pid)
    ).all()
    assert len(before) == 1, f"建商品应当写一段成本价历史：{len(before)}"

    _add(client, h, pid, "补贴后成本", "3.2")
    _add(client, h, pid, "含运费成本", "4.5")
    db_session.expire_all()
    after = db_session.scalars(
        select(ProductCostHistory).where(ProductCostHistory.product_id == pid)
    ).all()
    assert len(after) == 1, f"附加口径不许写进成本价时间轴：{[str(x.cost_price) for x in after]}"
    open_row = next(x for x in after if x.effective_to is None)
    assert str(open_row.cost_price) == "4.0000", "生效中的那段仍然是真实成本价"


# --------------------------------------------------------------- 审计
@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_each_cost_price_action_leaves_an_audit_row(client, db_session, token_dispatcher):
    """四件事各留一条审计（审计页要能回答"谁加了这个口径、谁把它删了"）。"""
    h = auth_headers(token_dispatcher)
    pid = _mk_product(client, h, _uniq("审计探针"), cost="4")
    since = _max_log_id(db_session)

    row_id = _add(client, h, pid, "返点后成本", "3.8").json()["id"]
    assert client.patch(
        f"{BASE}/cost-prices/{row_id}", json={"cost_price": "3.6"}, headers=h
    ).status_code == 200
    assert client.delete(f"{BASE}/cost-prices/{row_id}", headers=h).status_code == 204
    assert client.post(f"{BASE}/cost-prices/{row_id}/restore", headers=h).status_code == 200

    db_session.expire_all()
    rows = db_session.scalars(
        select(OperationLog).where(OperationLog.id > since).order_by(OperationLog.id)
    ).all()
    actions = [str(r.action) for r in rows]
    for want in (
        OperationAction.PRODUCT_COST_PRICE_UPSERT.value,
        OperationAction.PRODUCT_COST_PRICE_UPDATE.value,
        OperationAction.PRODUCT_COST_PRICE_DELETE.value,
        OperationAction.PRODUCT_COST_PRICE_RESTORE.value,
    ):
        assert want in actions, f"缺审计码 {want}：{actions}"
    # ⛔ 这四件事都不许记成 PRODUCT_UPDATE（那会让审计页把"加了个参考口径"看成"改了成本价"）
    assert OperationAction.PRODUCT_UPDATE.value not in actions, actions
