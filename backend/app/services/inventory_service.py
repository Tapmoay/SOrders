"""库存自动联动：订单派送自动出库 → 送达最终确认 → 撤销/撤回自动回库。

规则（与业务约定一致）：
- 订单派送（DISPATCHED）→ 预占用：仅生成 RESERVED 流水（change=-qty），库存界面显示「-N」，
  **实际库存不动**。
- 订单送达（DELIVERED）→ 此时才真正减库存（RESERVED→COMMITTED，stock -= qty）。
- 订单撤销/撤回派单（CANCELLED / 撤回）→ 释放占用：原流水转 RELEASED，补一条 +qty
  「订单撤销自动回库」流水；实际库存不动（从未实扣）。
- 商品解析：优先明细行绑定 product_id；缺绑定时按「活跃商品唯一同名」兜底匹配；
  无同名/多同名 → 跳过（不占用）。
- 库存不足不拦截（先出后补），库存允许为负并在流水上如实记录。
"""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import InventoryMovement, Order, OrderProduct, Product


def _order_rows(db: Session, order: Order) -> list:
    products = getattr(order, "order_products", None) or []
    if products:
        return products
    return list(db.scalars(select(OrderProduct).where(OrderProduct.order_id == order.id)))


def _match_product_by_name(db: Session, name: str) -> Product | None:
    """按商品名唯一定位活跃商品（下单手输商品名时的自动出库兜底）；多个同名/无同名→不扣。"""
    n = (name or "").strip()
    if not n:
        return None
    rows = list(
        db.scalars(
            select(Product).where(Product.is_active.is_(True), Product.name == n)
        )
    )
    return rows[0] if len(rows) == 1 else None


def _resolve_product(db: Session, op) -> Product | None:
    """明细行商品解析：优先显式绑定；缺绑定按名称唯一匹配兜底。"""
    if op.product_id is not None:
        return db.get(Product, op.product_id)
    return _match_product_by_name(db, getattr(op, "product_name_snapshot", None))


def auto_stock_out(db: Session, order: Order, operator_id: int) -> int:
    """订单派送自动出库（预占）：不动实际库存，仅生成 RESERVED 占用流水，库存界面显示「-N」；
    真正减库存发生在订单送达（auto_stock_commit）。返回生成流水条数。"""
    n = 0
    for op in _order_rows(db, order):
        prod = _resolve_product(db, op)
        if prod is None:
            continue
        db.add(
            InventoryMovement(
                product_id=prod.id,
                change=-op.quantity,
                note="订单派送自动出库",
                operator_id=operator_id,
                source="ORDER",
                order_id=order.id,
                status="RESERVED",
            )
        )
        n += 1
    return n


def auto_stock_commit(db: Session, order: Order) -> int:
    """订单送达：此时才真正减库存（预占用转实扣，RESERVED → COMMITTED）。返回更新条数。

    ⛔ **库存只能用 SQL 表达式自减，不许 Python 读改写**（2026-09-19 审计，核心循环）：

        prod = db.get(Product, m.product_id)
        prod.stock = (prod.stock or 0) + m.change     # ← 典型 lost update

    两个请求同时扣同一个商品（两张不同的单同时送达、或"送达 × 派单员手工出库"）时，
    两边都先读到同一个旧值、各自算出新值、后写的人把前一个人的减扣**整段盖掉**：
    库存 100、两单各扣 3 → 最终是 97 而不是 94，而且**谁都不会报错**（账面上只少了一件货，
    月底盘库才发现，且没有任何一处日志能指出是哪两次操作）。
    本机 SQLite 写是串行的，**这个缝隙在本机测不出来** —— 所以修法不能靠"本地跑一遍看看"。

    现在把加法交给数据库自己做（`stock = stock + change`），读与写在同一条 UPDATE 里完成，
    行锁由数据库保证（MySQL/InnoDB 会对被更新的行加锁，两个请求自然串行）。
    这与 `order_flow` 里那批"条件 UPDATE 占位"是同一个思路：**让改到行的人才能继续**。
    """
    rows = list(
        db.scalars(
            select(InventoryMovement).where(
                InventoryMovement.order_id == order.id,
                InventoryMovement.source == "ORDER",
                InventoryMovement.status == "RESERVED",
            )
        )
    )
    for m in rows:
        db.execute(
            update(Product)
            .where(Product.id == m.product_id)
            .values(stock=func.coalesce(Product.stock, 0) + m.change)
        )
        m.status = "COMMITTED"
    return len(rows)


def auto_stock_release(db: Session, order: Order, operator_id: int) -> int:
    """订单撤销/撤回派单：释放预占用（不动实际库存——派单时未真正扣减），
    原流水转 RELEASED 并补一条「订单撤销自动回库」流水。返回释放条数。"""
    n = 0
    rows = list(
        db.scalars(
            select(InventoryMovement).where(
                InventoryMovement.order_id == order.id,
                InventoryMovement.source == "ORDER",
                InventoryMovement.status == "RESERVED",
            )
        )
    )
    for m in rows:
        m.status = "RELEASED"
        db.add(
            InventoryMovement(
                product_id=m.product_id,
                change=-m.change,
                note="订单撤销自动回库",
                operator_id=operator_id,
                source="ORDER",
                order_id=order.id,
                status="RELEASED",
            )
        )
        n += 1
    return n


def restock_returned(db: Session, order: Order, lines: list[tuple[OrderProduct, int]], operator_id: int) -> int:
    """订单**退货**：把退回来的货加回库存（返回写了几条流水）。

    ⚠️ 退货为什么必须动库存：送达那一刻 `auto_stock_commit` 已经把货**实扣**掉了
    （`stock -= qty`），退货是货真的回到仓库 —— 不回补的话库存**永久少一批货**，
    而且盘库时找不出原因（订单、账本、司机账单三处都是"退了"，只有库存还停在当时）。

    ⚠️ 加库存走 SQL 表达式自减（`stock = stock + change`），与 `auto_stock_commit`
    同一条理由：Python 读改写会在并发下丢掉别人的加减，且**两边都不报错**（见那里的长注释）。

    ⚠️ 判据是"送到客户手里的好货"：`lines` 里的数量由调用方（`order_return`）按
    `quantity − damage_quantity` 上限校验过 —— **货损那部分不许回补**，
    它已经在送达时按成本计进损失账了，再回补就是同一批货算两遍。
    """
    n = 0
    for op, qty in lines:
        if qty <= 0:
            continue
        prod = _resolve_product(db, op)
        if prod is None:
            # 商品已删/改名 → 回补不了。**如实跳过**（调用方把这一条写进返回值的提示里），
            # 不许把数量记到别的商品头上。
            continue
        db.execute(
            update(Product).where(Product.id == prod.id).values(stock=func.coalesce(Product.stock, 0) + qty)
        )
        db.add(
            InventoryMovement(
                product_id=prod.id,
                change=qty,
                note="订单退货回库",
                operator_id=operator_id,
                source="ORDER",
                order_id=order.id,
                # 与 RESERVED/COMMITTED/RELEASED 同一套状态词：RETURNED = 退货回库
                status="RETURNED",
            )
        )
        n += 1
    return n


def resync_reservations(db: Session, order: Order, operator_id: int) -> int:
    """订单**行变了之后**把预占重算到与当前订单行一致（返回补写的流水条数）。

    ## 为什么必须有这个函数（2026-09-19 审计，生产同样成立）
    预占是在**派单那一刻**按当时的订单行生成的（`auto_stock_out`），而实扣发生在送达时、
    且 `auto_stock_commit` 是**按流水**扣的（`prod.stock += m.change`），**从不读订单行**。
    两边一旦分叉，库存就永久错账，而且全程 200、没有任何报错：
      · 派单后把某行数量 2 改成 5 → 实扣 2（订单写 5）；
      · 派单后**加一行** → 新行没有预占流水 → 这件货**永远不扣库**；
      · 派单后**删一行** → 流水还在 → 照扣一件不存在的货；
      · 派单后**换商品** → 扣到旧商品头上、新商品不扣。
    `_order_allows_line_edit` 是**故意**允许"待派单/派单中/已接单"改行的（司机还没出发时
    改数量是真实需求），所以修法不是禁止改行，而是改完把预占补齐。

    ## 判据（按商品逐一对账，而不是只看总数）
    对每个商品：`目标预占 = -Σ该商品的订单行数量`，`现有预占 = Σ该单 RESERVED 流水的 change`；
    差额补一条 RESERVED 流水。按商品对账才能处理"换商品/加行/删行"这三种形状。
    """
    ordered: dict[int, int] = {}
    for op in _order_rows(db, order):
        prod = _resolve_product(db, op)
        if prod is None:
            continue
        ordered[prod.id] = ordered.get(prod.id, 0) + int(op.quantity or 0)

    reserved: dict[int, int] = {}
    rows = list(
        db.scalars(
            select(InventoryMovement).where(
                InventoryMovement.order_id == order.id,
                InventoryMovement.source == "ORDER",
                InventoryMovement.status == "RESERVED",
            )
        )
    )
    for m in rows:
        reserved[m.product_id] = reserved.get(m.product_id, 0) + int(m.change or 0)

    written = 0
    for pid in sorted(set(ordered) | set(reserved)):
        want = -ordered.get(pid, 0)
        have = reserved.get(pid, 0)
        delta = want - have
        if delta == 0:
            continue
        db.add(
            InventoryMovement(
                product_id=pid,
                change=delta,
                note="订单行变更后重算预占",
                operator_id=operator_id,
                source="ORDER",
                order_id=order.id,
                status="RESERVED",
            )
        )
        written += 1
    return written
