"""日期窗口必须按**业务当地日**取，不能按 UTC 零点 —— 三处静默差 8 小时的判据（2026-09-21 修）。

## 缺陷长什么样
`deps.py::parse_date_range` 返回的是"当地日的零点 / 当日末刻"，**它不做时区换算**；
而库里的时间列存的是 **UTC naive**（`core/business_time.py`）。三个调用点直接拿它去比时间戳列：

| 调用点 | 比的列 |
|---|---|
| `orders.py::list_orders` 的 `stmt` 路径（派单员 + 搜索词） | `orders.created_at` |
| `orders.py::list_orders` 的 `q` 路径（其余角色） | `orders.created_at` |
| `inventory.py::list_movements` | `inventory_movements.created_at` |

后果：「查 9-21」实际取到的是**北京 9-21 08:00 ~ 9-22 08:00** —— 当天头 8 小时的记录查不到、
次日头 8 小时的多进来。界面上只是"少了几单/几条"，用户只会以为那天真的没有
（与审计 R12-M11 同族：当地 00:00~08:00 的记录会掉出窗口）。

## 判据为什么"能红"（而不是永远绿）
三行数据按下单时刻（**业务当地**）分别落在窗口的前一天深夜 / 当天 / 次日凌晨，窗口取
`2026-01-05` 这一天：

| 名字 | 业务当地 | 存库（UTC） | 换算了才在窗口内？ |
|---|---|---|---|
| `EARLY` | 01-05 03:00 | 01-04 19:00 | ✅ 只有换算过才算进来 |
| `MID` | 01-05 15:00 | 01-05 07:00 | 两种口径都在 |
| `LATE` | 01-06 03:00 | 01-05 19:00 | ❌ 只有**没**换算才会被算进来 |

所以「返回集合恰好 = {EARLY, MID}」在修之前**必然红**（那时得到 {MID, LATE}）。
下面每条用例都额外把"按旧口径（UTC 零点）会取到谁"算一遍并断言两个集合**不同** ——
这样它证明的是"确实换算了"，而不是"碰巧没有数据"。

窗口取一个**过去**的日期：库里其他用例造的行都是"现在"，不会污染"集合恰好等于谁"这种断言。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select, update
from starlette.testclient import TestClient

from tests.conftest import auth_headers

#: 窗口那一天（业务当地）。三个时刻按上表造。
WINDOW = "2026-01-05"
#: 窗口的 UTC 边界（= 旧口径会用的边界；"两集合不同"那条断言要靠它）
UTC_MIDNIGHT = datetime(2026, 1, 5, 0, 0, 0)

EARLY = datetime(2026, 1, 4, 19, 0, 0)      # 北京 01-05 03:00
MID = datetime(2026, 1, 5, 7, 0, 0)         # 北京 01-05 15:00
LATE = datetime(2026, 1, 5, 19, 0, 0)       # 北京 01-06 03:00


def _mk_order(client: TestClient, token_dispatcher: str, shipper_id: int, desc: str) -> int:
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": shipper_id,
            "lines": [{"product_name_snapshot": "日期窗口探针", "quantity": 1, "unit_price": "10"}],
            "address_detail": desc,
            "delivery_description": desc,
        },
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _mk_movement(client: TestClient, h: dict[str, str], product_id: int, note: str) -> int:
    r = client.post(
        "/api/v1/inventory/movements",
        json={"product_id": product_id, "change": 1, "note": note},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _force_created_at(db_session, model, row_id: int, when: datetime) -> None:
    """把某一行的 `created_at` 改成指定时刻（模拟"这单是那天那个点下的"）。

    ⚠️ 走 bulk `update` 之后要 `expire_all()`：否则会话的 identity map 里还是旧值，
    而这条用例恰恰是在验"数据库按哪段时间筛"。
    """
    db_session.execute(update(model).where(model.id == row_id).values(created_at=when))
    db_session.commit()
    db_session.expire_all()


def _ids_in_utc_window(db_session, model, ids: set[int]) -> set[int]:
    """按**旧口径**（UTC 零点 ~ 当日末刻）取一遍，只回我这几行。

    它存在的意义是让"换算了"这件事**可观测**：两个集合必须不同，否则这条判据是空转。
    """
    rows = db_session.execute(
        select(model.id).where(
            model.id.in_(ids),
            model.created_at >= UTC_MIDNIGHT,
            model.created_at < datetime(2026, 1, 6, 0, 0, 0),
        )
    ).all()
    return {r[0] for r in rows}


@pytest.mark.dispatcher
@pytest.mark.orders
@pytest.mark.fast
@pytest.mark.regression
def test_order_list_date_window_is_business_day(
    client: TestClient, db_session, users: dict, token_dispatcher: str
) -> None:
    """订单列表（`q` 路径）的 `date_from/date_to` 按**业务当地日**取。"""
    from app.models import Order

    early = _mk_order(client, token_dispatcher, users["shipper"].id, "日期窗口-凌晨单")
    mid = _mk_order(client, token_dispatcher, users["shipper"].id, "日期窗口-当天单")
    late = _mk_order(client, token_dispatcher, users["shipper"].id, "日期窗口-次日凌晨单")
    for oid, when in ((early, EARLY), (mid, MID), (late, LATE)):
        _force_created_at(db_session, Order, oid, when)

    r = client.get(
        "/api/v1/orders",
        params={"date_from": WINDOW, "date_to": WINDOW, "limit": 500},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    got = {o["id"] for o in r.json()}

    old = _ids_in_utc_window(db_session, Order, {early, mid, late})
    assert old == {mid, late}, f"旧口径（UTC 零点）应当取到 MID+LATE，实际 {old}"
    assert got != old, "两种口径取到的集合一样 → 这条判据证明不了'确实换算了'"
    assert got == {early, mid}, (
        f"窗口 {WINDOW}（业务当地）应当恰好取到 EARLY+MID，实际 {got}；"
        f"若拿到 LATE 说明还在按 UTC 零点比（这就是差 8 小时那个缺陷）"
    )


@pytest.mark.dispatcher
@pytest.mark.orders
@pytest.mark.fast
@pytest.mark.regression
def test_order_search_path_date_window_is_business_day(
    client: TestClient, db_session, users: dict, token_dispatcher: str
) -> None:
    """**带 `q` 的派单员路径**（另一条查询构造路径）同样要换算。

    这个端点有两条互不相干的构造路径（`stmt` / `q`），日期窗口各写一遍 ——
    只修一条的后果是"派单员带搜索词查某天少几单"，而另一条路径看起来全对。
    """
    from app.models import Order

    early = _mk_order(client, token_dispatcher, users["shipper"].id, "搜索路径-凌晨单")
    mid = _mk_order(client, token_dispatcher, users["shipper"].id, "搜索路径-当天单")
    late = _mk_order(client, token_dispatcher, users["shipper"].id, "搜索路径-次日凌晨单")
    for oid, when in ((early, EARLY), (mid, MID), (late, LATE)):
        _force_created_at(db_session, Order, oid, when)

    r = client.get(
        "/api/v1/orders",
        # ⚠️ 搜索词必须与下面那三张单的 `address_detail` 前缀一致（这一条路径是"派单员 + q"），
        #    否则命中 0 张，这条用例就变成"空集合 == 空集合"的假绿。
        params={"q": "搜索路径", "date_from": WINDOW, "date_to": WINDOW, "limit": 500},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text

    def _rows() -> set[int]:
        # 这一条路径带 `q`，所以只认我自己造的这几行（别把别的用例的单算进来）
        return {o["id"] for o in r.json() if o["id"] in {early, mid, late}}

    assert _rows() == {early, mid}, (
        f"带 q 的路径在窗口 {WINDOW} 应当恰好取到 EARLY+MID，实际 {_rows()}；"
        f"拿到 LATE = 这条路径漏了换算"
    )


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_inventory_movements_date_window_is_business_day(
    client: TestClient, db_session, users: dict, token_dispatcher: str
) -> None:
    """库存流水的 `date_from/date_to` 同样按业务当地日取。"""
    from app.models import InventoryMovement

    h = auth_headers(token_dispatcher)
    rp = client.post(
        "/api/v1/products",
        json={"name": "日期窗口探针商品", "default_unit_price": "9", "unit": "件", "stock": 0},
        headers=h,
    )
    assert rp.status_code == 201, rp.text
    pid = rp.json()["id"]

    early = _mk_movement(client, h, pid, "日期窗口-凌晨流水")
    mid = _mk_movement(client, h, pid, "日期窗口-当天流水")
    late = _mk_movement(client, h, pid, "日期窗口-次日凌晨流水")
    for mid_id, when in ((early, EARLY), (mid, MID), (late, LATE)):
        _force_created_at(db_session, InventoryMovement, mid_id, when)

    r = client.get(
        "/api/v1/inventory/movements",
        params={"date_from": WINDOW, "date_to": WINDOW, "limit": 500},
        headers=h,
    )
    assert r.status_code == 200, r.text
    got = {m["id"] for m in r.json() if m["id"] in {early, mid, late}}

    old = _ids_in_utc_window(db_session, InventoryMovement, {early, mid, late})
    assert old == {mid, late}, f"旧口径应当取到 MID+LATE，实际 {old}"
    assert got != old, "两种口径取到的集合一样 → 判据空转"
    assert got == {early, mid}, (
        f"库存流水窗口 {WINDOW} 应当恰好取到 EARLY+MID，实际 {got}；"
        f"拿到 LATE 说明还在按 UTC 零点比"
    )
