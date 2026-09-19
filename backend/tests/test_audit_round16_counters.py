"""第十六轮审计的回归测试：**库存与计数列必须由数据库自增**（lost update / TOCTOU）。

这一批缺陷的共同形状是"读 → 算 → 写回绝对值"：

```python
prod = db.get(Product, m.product_id)
prod.stock = (prod.stock or 0) + m.change      # ① 丢更新
new_stock = (product.stock or 0) + body.change # ② 先判后写（拦不住库存不足）
if new_stock < 0: raise 库存不足
product.stock = new_stock
```

后果都是**静默**的：库存 100、两单各扣 3 → 最终 97 而不是 94；库存 10、两人同时出库 8 →
都放行、一共出库 16。谁都不报错，月底盘库才发现，而日志里指不出是哪两次操作。

### 为什么本机（SQLite）也能测出来
SQLite 的写是串行的，"两个请求同时"在测试里没法真的并发。但这里的失效机制**不一定需要真并发**：
只要"读出旧值"与"写回绝对值"之间隔着**另一次已提交的修改**，绝对值的写入就会把它盖掉。
所以测试这样构造（确定性、无 flaky）：

1. 本会话把商品读进 identity map（`db.get`）→ 会话里现在握着**旧值**；
2. 另开一个会话（模拟另一个 worker / 另一个请求）做一次原子加减并提交；
3. 再走被测的那条路径（`auto_stock_commit` / `POST /inventory/movements`）；
4. 断言最终库存把**两次**修改都算上。

老写法在第 3 步会把旧值 + 本次差量写回去（第 2 步那次整段消失），断言立刻红。

⚠️ **必须把 `db.get(...)` 的结果绑到一个变量上，否则这条测试是假的**（2026-09-19 实测）：
SQLAlchemy 的 identity map 存的是**弱引用**，返回值没人引用时立刻可被 GC 回收 →
identity map 里那一条消失 → 被测代码重新 SELECT 拿到的是**新值** → 老写法照样通过
（第一版就是这么漏的：注入"读改写"回源码之后测试仍然全绿）。
所以每条测试都要 `stale = db.get(...)` 再 `assert stale.<col> == 旧值`，把"读到的旧值"钉住。
真实并发下不需要 identity map：两个 worker 各自 SELECT 到同一个旧值，机制完全相同。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import update

from tests.conftest import auth_headers


def _mk_product(db_session, name: str, stock: int) -> int:
    from app.models import Product

    p = Product(name=name, unit="件", default_unit_price=Decimal("10.00"), stock=stock, is_active=True)
    db_session.add(p)
    db_session.commit()
    return p.id


def _mk_reserved(db_session, order_id: int, product_id: int, qty: int) -> None:
    """一张单的 RESERVED 预占流水（`auto_stock_commit` 就是按它扣库的）。"""
    from app.models import InventoryMovement

    db_session.add(
        InventoryMovement(
            product_id=product_id,
            change=-qty,
            note="探针预占",
            operator_id=1,
            source="ORDER",
            order_id=order_id,
            status="RESERVED",
        )
    )
    db_session.commit()


def _mk_order(db_session, shipper_id: int | None, no: str):
    from app.models import Order
    from app.models.enums import OrderStatus

    o = Order(
        order_no=no,
        shipper_id=shipper_id,
        status=OrderStatus.DELIVERED,
        order_date=date(2026, 9, 10),  # NOT NULL：订单业务日
    )
    db_session.add(o)
    db_session.commit()
    return o


def _other_session():
    """另一个"请求"用的会话（同一个测试库，绕开本会话的 identity map）。"""
    from tests.conftest import get_test_session_factory

    return get_test_session_factory()()


# --------------------------------------------------------------- ① 送达扣库存
def test_delivery_deduction_does_not_clobber_a_concurrent_stock_change(client, users, db_session):
    """并发送达 / 送达 × 手工出库：两次减扣都必须算上（老写法会把前一次整段盖掉）。"""
    from app.models import Product
    from app.services.inventory_service import auto_stock_commit

    pid = _mk_product(db_session, "丢更新探针货", 100)
    order = _mk_order(db_session, users["shipper"].id, "SOSTOCKK1")
    _mk_reserved(db_session, order.id, pid, 3)

    # ① 本会话先把商品读进 identity map —— 之后它一直握着这份**旧值**（stock=100）
    stale = db_session.get(Product, pid)
    assert stale.stock == 100

    # ② 另一个"请求"先扣了 4（原子加减）并提交
    other = _other_session()
    try:
        other.execute(update(Product).where(Product.id == pid).values(stock=Product.stock - 4))
        other.commit()
    finally:
        other.close()

    # ③ 走送达扣减这条路径
    db_session.refresh(order)  # 让 order 带上 order_products 关联由服务自己查
    auto_stock_commit(db_session, order)
    db_session.commit()
    db_session.expire_all()

    final = db_session.get(Product, pid).stock
    assert final == 100 - 4 - 3, (
        f"库存是 {final}，应当是 93 —— 那次并发的 -4 被这次『写回绝对值』盖掉了（lost update）"
    )


# --------------------------------------------------------------- ② 手工出库
def test_manual_outflow_guard_is_atomic_not_check_then_act(client, token_dispatcher, users, db_session):
    """库存不足的判据必须在**写入那一刻**成立：并发把库存抽走后，这一笔必须被拒。"""
    from app.models import Product

    h = auth_headers(token_dispatcher)
    pid = _mk_product(db_session, "TOCTOU 探针货", 10)

    # 本会话先读一次并**把结果钉住**（identity map 是弱引用，不绑变量会被 GC 掉 →
    # 被测代码就会重新读到新值，这条测试随即变成恒绿；见模块文档的 ⚠️）
    stale = db_session.get(Product, pid)
    assert stale.stock == 10
    other = _other_session()
    try:
        other.execute(update(Product).where(Product.id == pid).values(stock=Product.stock - 8))
        other.commit()
    finally:
        other.close()

    # 出库 5：真实库存只剩 2 → 必须拒绝（老写法读到旧的 10 → 算出 5 ≥ 0 → 放行）
    r = client.post(
        "/api/v1/inventory/movements",
        json={"product_id": pid, "change": -5, "note": "探针出库"},
        headers=h,
    )
    assert r.status_code == 400, f"库存不足却放行了：{r.status_code} {r.text[:200]}"
    assert "库存不足" in r.text, f"报错要说人话：{r.text[:200]}"

    db_session.expire_all()
    assert db_session.get(Product, pid).stock == 2, "被拒绝的出库却改了库存"


def test_manual_inflow_and_outflow_use_atomic_math(client, token_dispatcher, users, db_session):
    """正常路径照常工作（守卫不许把正常用法一起挡住）+ 日志里的 stock_after 是权威值。"""
    from app.models import OperationLog, Product

    h = auth_headers(token_dispatcher)
    pid = _mk_product(db_session, "原子加减探针货", 20)

    # 同样把读到的旧值钉住（否则这条测试对"写回绝对值"这种老写法是恒绿的）
    stale = db_session.get(Product, pid)
    assert stale.stock == 20
    other = _other_session()
    try:
        other.execute(update(Product).where(Product.id == pid).values(stock=Product.stock + 5))
        other.commit()
    finally:
        other.close()

    r = client.post(
        "/api/v1/inventory/movements",
        json={"product_id": pid, "change": -6, "note": "探针出库"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text

    db_session.expire_all()
    assert db_session.get(Product, pid).stock == 19, "两次修改没有都算上（20+5-6=19）"

    log = (
        db_session.query(OperationLog)
        .filter(OperationLog.action == "INVENTORY_ADJUST")
        .order_by(OperationLog.id.desc())
        .first()
    )
    assert log is not None, "库存调整没留痕"
    # 日志把 payload 摊平成 JSON **文本**存（列名是 `change_content`，不是 `change_payload`）
    import json

    payload = json.loads(log.change_content or "{}")
    assert payload.get("stock_after") == 19, f"日志里的 stock_after 不是权威值：{payload}"


# --------------------------------------------------------------- ③ 地点使用计数
def test_place_usage_counter_is_incremented_by_the_database(db_session, users):
    """同一地点被反复沿用：计数必须每次 +1（老写法在并发下会少加）。"""
    from app.models import Place, PlaceUserUsage
    from app.services.place_service import note_place_use  # noqa: F401  (导入失败时明确报错)

    # ⚠️ 坐标必须**离别的测试远一点**：`places` 是**全库共享**的一张表，而
    #    `upsert_place` 的合并判据是"1 米内 / 同名 30 米内"——2026-09-19 实测踩到：
    #    这里原来用 (30.1, 120.2)，与 `test_place_library.py::test_places_visible_to_all_roles`
    #    的坐标**一模一样** → 那个测试的 POST 被并进这一行（名字不同、`_fill_blank` 不改名）
    #    → 它按 `q=共享测试点` 查到 0 行而失败（单独跑那个文件却全绿，只有全量跑才暴露）。
    place = Place(
        name="计数探针点", detail_address="某路口", lat=Decimal("27.9876543"), lng=Decimal("113.1234567")
    )
    db_session.add(place)
    db_session.commit()

    row = PlaceUserUsage(user_id=users["shipper"].id, place_id=place.id, use_count=1)
    db_session.add(row)
    db_session.commit()

    # 本会话握着旧值，另一个请求先 +1
    stale = db_session.get(PlaceUserUsage, row.id)
    assert stale.use_count == 1
    other = _other_session()
    try:
        other.execute(
            update(PlaceUserUsage)
            .where(PlaceUserUsage.id == row.id)
            .values(use_count=PlaceUserUsage.use_count + 1)
        )
        other.commit()
    finally:
        other.close()

    db_session.execute(
        update(PlaceUserUsage)
        .where(PlaceUserUsage.id == row.id)
        .values(use_count=PlaceUserUsage.use_count + 1)
    )
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(PlaceUserUsage, row.id).use_count == 3, "两次 +1 有一次被盖掉了"
