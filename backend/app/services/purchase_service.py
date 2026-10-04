"""采购单：把「一次进货」写成库存 + 成本价 + 供应商应付三件事（FEAT-0013）。

本模块是这三件事的**唯一写入点**，也是「改单怎么改」这个问题的唯一答案。
形状（三条不变量、两种「不算数」）见 `app/models/purchase.py` 的文件头，这里只讲做法：

```text
create_order    建单：逐行写入库流水（source=PURCHASE）+ 记成本价 → 生成一张应付单（金额 = 合计）
update_order    改单：**整单替换明细** —— 没出现在请求里的行 = 撤掉；改数量改单价都是「改写那条流水」
soft_delete_order  整张单进回收站：逐行把流水摆成「没发生过」 + 应付单一起软删（挂着还算数的进项票时拦下）
restore_order   恢复：逐行原样写回 + 恢复应付单
```

## 四个关键取舍（改这个文件之前先读）

1. **改单改写那条流水，不再记一笔冲销**：见 `app/models/purchase.py` 第 3 条不变量 ——
   冲销行进不了 `cost_basis._weighted_avg` 的分母，旧价会永远留在加权均价里。
2. **库存加减只有 `_apply_stock` 一处**（原子 SQL + `stock + delta >= 0` 条件），
   与 `api/v1/inventory.py::create_movement` 同一套写法：抢不到就如实报，⛔ 不读改写。
3. **应付金额只有 `_sync_payable` 一处写入**，且**不许小于已付**（同
   `schemas/supplier.py::SupplierPayableUpdate` 的规矩）：改单不能把已经付掉的钱改没了。
4. **金额只有 `line_amount` / `total_of` 两处运算**：合计 = 逐行（数量 × 单价，两位小数）相加，
   所以界面上「一行一行的钱加起来 == 合计」永远成立（用户就是拿它对账的）。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Sequence

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.models import (
    InventoryMovement,
    Invoice,
    InvoicePurchaseOrder,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    SupplierPayable,
)
from app.models.enums import InvoiceStatus, OperationAction
from app.services import cost_history
from app.services import supplier_service as svc
from app.services.cost_history import record_cost
from app.services.money_text import money_text
from app.services.operation_log_service import write_log
from app.services.order_money import q2
from app.services.soft_delete import ensure_alive

#: 入库流水的来源。词表见 `app/models/inventory.py`（MANUAL=手工 / ORDER=订单自动 / WAREHOUSE=到仓）。
#  采购单写的流水一律用它 —— 「这一笔是采购进来的」在流水列表里一眼可辨，也让
#  「这个商品有没有记过进货价」这类问题只需要看流水。
SOURCE_PURCHASE = "PURCHASE"
STATUS_COMMITTED = "COMMITTED"
STATUS_VOID = "VOID"

#: 应付单的分类（`schemas/supplier.py::SUPPLIER_PAYABLE_CATEGORIES` 里的第一项）。
PAYABLE_CATEGORY = "货款"

_COST_STEP = Decimal("0.0001")   # 与 products.cost_price / inventory_movements.unit_cost 的精度同阶
_ZERO = Decimal("0.00")


# ---------------------------------------------------------------- 金额（唯一两处运算）


def line_amount(item: PurchaseOrderItem) -> Decimal:
    """一行的金额 = 数量 × 单价（两位小数）。**已撤的行恒为 0**（撤掉的行不进合计）。"""
    if item.is_void:
        return _ZERO
    return q2(Decimal(int(item.quantity or 0)) * Decimal(str(item.unit_cost or 0)))


def total_of(items: Iterable[PurchaseOrderItem]) -> Decimal:
    """单头合计 = Σ 逐行金额。**不落库**（单头没有合计列，见模型文件头第 1 条）。"""
    return q2(sum((line_amount(it) for it in items), _ZERO))


def active_items(order: PurchaseOrder) -> list[PurchaseOrderItem]:
    """还没被撤掉的行。"""
    return [it for it in order.items if not it.is_void]


# ---------------------------------------------------------------- 读


def get_order_or_404(db: Session, order_id: int) -> PurchaseOrder:
    order = db.get(PurchaseOrder, order_id)
    if order is None:
        raise HTTPException(404, detail="采购单不存在")
    return order


def payable_owner_order(db: Session, payable_id: int) -> PurchaseOrder | None:
    """这张应付单是不是某张采购单自动生成的？是的话返回那张单。"""
    return db.scalars(
        select(PurchaseOrder).where(PurchaseOrder.payable_id == payable_id)
    ).first()


def guard_supplier_payable(db: Session, payable: SupplierPayable) -> None:
    """供应商页改/删应付单前的守卫：来自采购单的那张，⛔ 不许在供应商页动。

    为什么必须拦（而不是让它改）：那张应付的金额是**采购单明细的合计**，改了它就等于
    「单据说进了 1000 元的货、欠款写着 800」—— 同一笔欠款两处可改，必然对不上，
    而且下一次改单会把它覆盖回去，用户会看到「我改的数又变回去了」。
    """
    order = payable_owner_order(db, payable.id)
    if order is None:
        return
    raise HTTPException(
        400,
        detail=(
            f"这张应付是采购单 #{order.id} 生成的（金额 = 那张单的明细合计），"
            "不能在这里改或删；要改就去采购单页改那张单 —— 改完这里的金额会跟着变。"
        ),
    )


# ---------------------------------------------------------------- 库存（唯一一处加减）


def _apply_stock(db: Session, product_id: int, delta: int) -> None:
    """把商品的库存加上 `delta`（可为负）。**原子 SQL**：条件写进 WHERE，抢不到就如实报。

    与 `api/v1/inventory.py::create_movement` 同一套写法，理由也一样：
    「先读出来、算一下、再写回去」在两个人同时操作时会把货算丢。
    """
    if delta == 0:
        return
    stmt = update(Product).where(Product.id == product_id)
    if delta < 0:
        # 减库存：库里现存的量必须够（否则这一行的货已经被卖掉/别处用掉了，不能凭空减成负数）
        stmt = stmt.where(func.coalesce(Product.stock, 0) + delta >= 0)
    res = db.execute(stmt.values(stock=func.coalesce(Product.stock, 0) + delta))
    if res.rowcount == 1:
        return
    # 没抢到：整个请求回滚（三件事要么都有、要么都没有），再如实说清楚是哪一种情况
    db.rollback()
    fresh = db.get(Product, product_id)
    if fresh is None:
        raise HTTPException(404, detail="商品不存在")
    now_stock = int(fresh.stock or 0)
    if delta < 0:
        raise HTTPException(
            400,
            detail=(
                f"库存不足：{fresh.name} 现在只有 {now_stock}，这一步要减 {-delta}。"
                "这批货可能已经卖掉了；卖出去了就不能再撤这一行。"
            ),
        )
    raise HTTPException(
        409,
        detail=f"库存刚刚被别的操作改过（{fresh.name} 当前 {now_stock}），请刷新后重试",
    )


# ---------------------------------------------------------------- 明细 / 流水


def _movement_of(db: Session, item: PurchaseOrderItem) -> InventoryMovement:
    mv = db.get(InventoryMovement, item.movement_id) if item.movement_id else None
    if mv is None:
        raise HTTPException(
            409,
            detail="这一行的入库流水不见了（数据异常），这张单暂时改不了；请报障。",
        )
    return mv


def _movement_note(order: PurchaseOrder) -> str:
    return f"采购单 #{order.id}"


def _add_line(
    db: Session,
    order: PurchaseOrder,
    product: Product,
    quantity: int,
    unit_cost: Decimal,
    *,
    operator_id: int | None,
) -> PurchaseOrderItem:
    """加一行：写一条入库流水 + 加库存 + 记成本价。三件事在**同一个事务**里。"""
    mv = InventoryMovement(
        product_id=product.id,
        change=quantity,
        note=_movement_note(order),
        operator_id=operator_id,
        source=SOURCE_PURCHASE,
        status=STATUS_COMMITTED,
        unit_cost=unit_cost,
        order_id=None,
    )
    db.add(mv)
    _apply_stock(db, product.id, quantity)
    db.flush()          # 拿到 mv.id（明细行要绑定它）
    item = PurchaseOrderItem(
        order_id=order.id,
        product_id=product.id,
        quantity=quantity,
        unit_cost=unit_cost,
        movement_id=mv.id,
        is_void=False,
    )
    db.add(item)
    order.items.append(item)
    # 成本价的唯一写入口（它同时更新 products.cost_price 与成本价区间表）
    record_cost(
        db, product, unit_cost,
        source=cost_history.SOURCE_PURCHASE,
        operator_id=operator_id,
        movement_id=mv.id,
    )
    return item


def _set_line(
    db: Session,
    item: PurchaseOrderItem,
    quantity: int,
    unit_cost: Decimal,
    *,
    operator_id: int | None,
) -> None:
    """改一行的数量 / 单价：**改写那条流水**（不是再记一笔冲销，见模型文件头第 3 条）。"""
    mv = _movement_of(db, item)
    old_qty = int(mv.change or 0)
    old_cost = Decimal(str(mv.unit_cost)) if mv.unit_cost is not None else None
    delta = quantity - old_qty
    if delta != 0:
        _apply_stock(db, item.product_id, delta)
    mv.change = quantity
    mv.unit_cost = unit_cost
    mv.status = STATUS_COMMITTED
    item.quantity = quantity
    item.unit_cost = unit_cost
    if old_cost is None or q2(old_cost) != q2(unit_cost):
        product = db.get(Product, item.product_id)
        if product is not None:
            record_cost(
                db, product, unit_cost,
                source=cost_history.SOURCE_PURCHASE,
                operator_id=operator_id,
                movement_id=mv.id,
            )


def _detach_line(db: Session, item: PurchaseOrderItem, *, operator_id: int | None) -> None:
    """把这一行的流水摆成「没发生过」：库存扣回去，流水 change=0 / unit_cost=NULL / status=VOID。

    ⛔ 不碰 `item.is_void` —— 那是「撤行」的意思（`_void_line`），而整张单进回收站只是
    暂时不算数（恢复时这一行要原样回来）。两种状态共用这一个动作，判据是：
    流水脱离 ⟺ item.is_void or order.is_deleted（见模型文件头）。
    """
    mv = _movement_of(db, item)
    qty = int(mv.change or 0)
    if qty != 0:
        _apply_stock(db, item.product_id, -qty)
    mv.change = 0
    mv.unit_cost = None
    mv.status = STATUS_VOID
    _reprice_product(db, item.product_id, operator_id=operator_id)


def _void_line(db: Session, item: PurchaseOrderItem, *, operator_id: int | None) -> None:
    """撤行：这一行不再算数，但**行还留在单子上**（撤掉的量与原价要能对证）。"""
    _detach_line(db, item, operator_id=operator_id)
    item.is_void = True


def _attach_line(db: Session, item: PurchaseOrderItem, *, operator_id: int | None) -> None:
    """恢复一行：按明细行上的数量与单价原样写回库存与流水（整张单从回收站回来时用）。"""
    mv = _movement_of(db, item)
    _apply_stock(db, item.product_id, int(item.quantity or 0))
    mv.change = item.quantity
    mv.unit_cost = item.unit_cost
    mv.status = STATUS_COMMITTED
    product = db.get(Product, item.product_id)
    if product is not None:
        record_cost(
            db, product, item.unit_cost,
            source=cost_history.SOURCE_PURCHASE,
            operator_id=operator_id,
            movement_id=mv.id,
        )


def _reprice_product(db: Session, product_id: int, *, operator_id: int | None) -> None:
    """把商品成本价重算成「最近一次**还活着**的带价入库价」。

    为什么需要它：成本价的唯一写入口 `record_cost` 是**追加式**的（写新价、不删旧价），
    而采购单可以撤行 —— 撤掉的那一批价必须从成本价上退回去，否则「最近一次进货价」
    会一直停在一次已被撤销的进货上。

    ⛔ 没有任何带价入库时**不把成本价抹成 0**：0 会被报表读成「成本是 0」= 毛利虚高，
       比留着旧价错得更贵。这时如实留着上一次的价，等用户补录（报表侧按「没进价」单列）。
    """
    # ⚠️ 先 flush：这一行的「change=0 / unit_cost=NULL」是刚刚在 Python 里改的。
    #    不 flush 的话 SELECT 的 WHERE 按**库里的旧值**判（匹配得上），而拿回来的对象
    #    仍是身份映射里那个 unit_cost=None 的实例 —— `record_cost(…, None)` 会把成本价
    #    **记成 0**（0 会被报表读成「成本是 0」= 毛利虚高）。2026-10-04 实测踩到：
    #    撤掉唯一一行带价进货之后，这个商品的成本价从 4.00 变成了 0.0000。
    db.flush()
    last = db.scalars(
        select(InventoryMovement)
        .where(
            InventoryMovement.product_id == product_id,
            InventoryMovement.change > 0,
            InventoryMovement.unit_cost.isnot(None),
            InventoryMovement.status != STATUS_VOID,
        )
        .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
        .limit(1)
    ).first()
    if last is None or last.unit_cost is None:
        # ⛔ 不拿 None 去调 record_cost：它把 None 当 0（见上面那段）
        return
    product = db.get(Product, product_id)
    if product is None:
        return
    source = (
        cost_history.SOURCE_MANUAL
        if (last.source or "") == "MANUAL"
        else cost_history.SOURCE_PURCHASE
    )
    record_cost(
        db, product, last.unit_cost,
        source=source,
        operator_id=operator_id,
        movement_id=last.id,
    )


# ---------------------------------------------------------------- 明细校验


def _clean_line(db: Session, spec: Any, idx: int) -> tuple[Product, int, Decimal]:
    """一行明细的业务校验（越界一律中文 400，⛔ 不是 422 的结构体）。"""
    product = db.get(Product, spec.product_id)
    if product is None or product.is_deleted:
        raise HTTPException(
            400,
            detail=f"第 {idx} 行的商品找不到（可能已经删了）；刷新商品列表后再选。",
        )
    quantity = int(spec.quantity or 0)
    if quantity <= 0:
        raise HTTPException(
            400,
            detail=f"第 {idx} 行的数量要大于 0（{product.name}）—— 一行 0 件看着像一行货，其实什么都没进。",
        )
    unit_cost = Decimal(str(spec.unit_cost))
    if unit_cost.quantize(_COST_STEP, rounding=ROUND_HALF_UP) != unit_cost:
        raise HTTPException(400, detail=f"第 {idx} 行的进货价最多 4 位小数（{product.name}）。")
    if unit_cost <= 0:
        raise HTTPException(
            400,
            detail=(
                f"第 {idx} 行的进货价要大于 0 元（{product.name}）；"
                "赠品、盘盈这些没花钱的货走「库存调整」，不记进货价（0 元的进货价会让毛利算不出来）。"
            ),
        )
    return product, quantity, unit_cost


def _check_duplicate(seen: dict[int, int], product: Product, idx: int) -> None:
    if product.id in seen:
        raise HTTPException(
            400,
            detail=(
                f"第 {idx} 行与第 {seen[product.id]} 行是同一个商品（{product.name}）："
                "同一张单里一个商品只能有一行。两批价钱不一样就开两张单。"
            ),
        )
    seen[product.id] = idx


# ---------------------------------------------------------------- 应付（唯一一处金额同步）


def _payable_title(order: PurchaseOrder) -> str:
    return f"采购单 #{order.id}"


def _sync_payable(
    db: Session,
    order: PurchaseOrder,
    *,
    total: Decimal,
    supplier: Supplier,
    operator_id: int | None,
) -> SupplierPayable:
    """把这张单自动生成的那张应付单的金额 / 日期 / 供应商对齐到当前明细。

    ⛔ 这是这张应付的**唯一写入点**；供应商页改/删它会被 `guard_supplier_payable` 拦下。
    两条硬规矩：改完的合计**不得小于已付**（钱已经付出去了，改单不能把它改没）；
    已经付过钱的单**不许换供应商**（那些付款是付给原供应商的，换个名字就对不上账了）。
    """
    if order.payable_id is None:
        payable = SupplierPayable(
            supplier_id=order.supplier_id,
            title=_payable_title(order),
            category=PAYABLE_CATEGORY,
            amount=total,
            doc_date=order.doc_date,
            remark=(order.remark or "")[:256],
            operator_id=operator_id,
        )
        db.add(payable)
        db.flush()
        order.payable_id = payable.id
        return payable
    payable = db.get(SupplierPayable, order.payable_id)
    if payable is None:
        raise HTTPException(
            409,
            detail=(
                f"这张采购单自动生成的应付单（#{order.payable_id}）不见了，改不了这张单；请报障。"
            ),
        )
    if payable.is_deleted:
        raise HTTPException(
            400,
            detail=f"这张采购单在回收站里，先生恢复它再改：POST /purchase-orders/{order.id}/restore",
        )
    paid = svc.payable_paid(db, payable.id)
    if total < paid:
        raise HTTPException(
            400,
            detail=(
                f"这张单的应付已经付了 {money_text(paid)} 元，改完的合计只有 {money_text(total)} 元。"
                "要改就先到供应商页把多付的那笔付款撤销掉（或者把数量/单价改回来）。"
            ),
        )
    if payable.supplier_id != order.supplier_id:
        if paid > 0:
            raise HTTPException(
                400,
                detail=(
                    f"这张单的应付已经付过 {money_text(paid)} 元了，不能换供应商："
                    "那些钱是付给原供应商的。要换就先把付款撤销掉。"
                ),
            )
        payable.supplier_id = order.supplier_id
    payable.amount = total
    payable.doc_date = order.doc_date
    payable.remark = (order.remark or "")[:256]
    if payable.title != _payable_title(order):
        payable.title = _payable_title(order)
    return payable


# ---------------------------------------------------------------- 审计快照


def _snapshot(order: PurchaseOrder) -> dict[str, Any]:
    """写进操作日志的「这一刻这张单长什么样」（改前 / 改后各一份）。"""
    return {
        "id": order.id,
        "supplier_id": order.supplier_id,
        "doc_date": order.doc_date.isoformat() if order.doc_date else None,
        "remark": order.remark or "",
        "total": str(total_of(order.items)),
        "payable_id": order.payable_id,
        "items": [
            {
                "id": it.id,
                "product_id": it.product_id,
                "quantity": int(it.quantity or 0),
                "unit_cost": str(it.unit_cost),
                "void": bool(it.is_void),
            }
            for it in order.items
        ],
    }


# ---------------------------------------------------------------- 建单 / 改单 / 删 / 恢复


def create_order(
    db: Session,
    *,
    supplier_id: int,
    doc_date,
    remark: str | None,
    items: Sequence[Any],
    operator_id: int | None,
) -> PurchaseOrder:
    """建单：库存 + 成本价 + 应付，一次提交全部写完（同一个事务，中途任何一步失败都不留痕）。"""
    supplier = svc.get_supplier_or_404(db, supplier_id)
    order = PurchaseOrder(
        supplier_id=supplier.id,
        doc_date=doc_date,
        remark=(remark or "").strip()[:256],
        operator_id=operator_id,
    )
    db.add(order)
    db.flush()          # 先拿到 order.id（明细行与流水的备注都要它）
    seen: dict[int, int] = {}
    for idx, spec in enumerate(items, start=1):
        product, quantity, unit_cost = _clean_line(db, spec, idx)
        _check_duplicate(seen, product, idx)
        _add_line(db, order, product, quantity, unit_cost, operator_id=operator_id)
    _sync_payable(
        db, order,
        total=total_of(order.items),
        supplier=supplier,
        operator_id=operator_id,
    )
    write_log(
        db,
        operator_id=operator_id,
        order_id=None,
        action=OperationAction.PURCHASE_ORDER_CREATE,
        change_payload=_snapshot(order),
    )
    db.commit()
    db.refresh(order)
    return order


def _apply_items(
    db: Session,
    order: PurchaseOrder,
    items: Sequence[Any],
    *,
    operator_id: int | None,
) -> None:
    """改单的明细处理：**整单替换** —— 请求里给了的照它改，没给的（还活着的行）撤掉。

    三种行的处理：
      · 带 id 且这张单上有、没撤过 → 改数量 / 单价（`_set_line`，改写那条流水）
      · 不带 id → 新加一行（`_add_line`）
      · 还活着但没出现在请求里 → 撤掉（`_void_line`，行留在单上，标记 is_void）
    """
    existing = list(order.items)
    by_id = {it.id: it for it in existing}
    seen: dict[int, int] = {}
    keep: set[int] = set()
    specs = list(items)
    # 第一遍：已有的行（先把它们占的商品登记进 seen，新加的行才不会与它们撞车）
    for idx, spec in enumerate(specs, start=1):
        if spec.id is None:
            continue
        item = by_id.get(int(spec.id))
        if item is None:
            raise HTTPException(
                400,
                detail=f"第 {idx} 行指的是这张单上没有的一行（#{spec.id}）；刷新这张单之后重试。",
            )
        if item.is_void:
            raise HTTPException(
                400,
                detail=f"第 {idx} 行已经撤掉了，撤掉的行改不回来；请把它从明细里去掉，或者新加一行。",
            )
        if item.id in keep:
            raise HTTPException(400, detail=f"第 {idx} 行在这张单里出现了两次（#{item.id}）。")
        product, quantity, unit_cost = _clean_line(db, spec, idx)
        _check_duplicate(seen, product, idx)
        keep.add(item.id)
        if quantity != int(item.quantity or 0) or q2(unit_cost) != q2(item.unit_cost):
            _set_line(db, item, quantity, unit_cost, operator_id=operator_id)
    # 第二遍：新加的行
    for idx, spec in enumerate(specs, start=1):
        if spec.id is not None:
            continue
        product, quantity, unit_cost = _clean_line(db, spec, idx)
        _check_duplicate(seen, product, idx)
        _add_line(db, order, product, quantity, unit_cost, operator_id=operator_id)
    # 第三遍：请求里没有的行 = 撤掉
    for item in existing:
        if item.is_void or item.id in keep:
            continue
        _void_line(db, item, operator_id=operator_id)


def update_order(
    db: Session,
    order: PurchaseOrder,
    *,
    supplier_id: int | None,
    doc_date,
    remark: str | None,
    items: Sequence[Any] | None,
    operator_id: int | None,
) -> PurchaseOrder:
    """改单。`items is None` = 只改单头（⛔ 一行都不动）。"""
    ensure_alive(order, "采购单", f"POST /purchase-orders/{order.id}/restore")
    before = _snapshot(order)
    if supplier_id is not None and int(supplier_id) != order.supplier_id:
        supplier = svc.get_supplier_or_404(db, int(supplier_id))
        order.supplier_id = supplier.id
    if doc_date is not None:
        order.doc_date = doc_date
    if remark is not None:
        order.remark = remark.strip()[:256]
    if items is not None:
        _apply_items(db, order, items, operator_id=operator_id)
    supplier = svc.get_supplier_or_404(db, order.supplier_id)
    _sync_payable(
        db, order,
        total=total_of(order.items),
        supplier=supplier,
        operator_id=operator_id,
    )
    write_log(
        db,
        operator_id=operator_id,
        order_id=None,
        action=OperationAction.PURCHASE_ORDER_UPDATE,
        change_payload={"before": before, "after": _snapshot(order)},
    )
    db.commit()
    db.refresh(order)
    return order


def _live_invoices_on(db: Session, order_id: int) -> list[Invoice]:
    """挂在这张采购单上、**还在税汇里算数**的那些进项票（由 FEAT-0014 加的连线）。

    作废的票（VOIDED）与回收站里的票不算 —— 它们本来就不进税汇，挂着也不影响对账。
    """
    return list(
        db.scalars(
            select(Invoice)
            .join(InvoicePurchaseOrder, InvoicePurchaseOrder.invoice_id == Invoice.id)
            .where(
                InvoicePurchaseOrder.purchase_order_id == order_id,
                Invoice.is_deleted.is_(False),
                Invoice.status != InvoiceStatus.VOIDED.value,
            )
            .order_by(Invoice.id)
        )
    )


def _ensure_no_live_invoices(db: Session, order: PurchaseOrder) -> None:
    """挂着还算数的进项票时，**不许删这张采购单**。

    为什么不是「连票一起删掉」：发票是外来的凭证（供应商开给我们的），它的存在不取决于
    我们这张单还在不在 —— 跟着悄悄消失，税汇里就凭空少一笔进项，而账上没有任何痕迹。
    为什么也不是「连票一起作废」：作废是一张票自己的状态（冲红），删单没资格替它决定。
    所以这里只如实拦下，把选择权交回给操作者：先把那些票作废或删掉，再回来删单。
    """
    rows = _live_invoices_on(db, order.id)
    if not rows:
        return
    heads = "、".join(f"#{row.id}" for row in rows[:3])
    more = "" if len(rows) <= 3 else f" 等 {len(rows)} 张"
    raise HTTPException(
        400,
        detail=(
            f"这张采购单上挂着 {len(rows)} 张还没作废的进项票（{heads}{more}）。"
            "删单会让这些票的进项税额凭空少掉，税账就对不上了。"
            "先把那些票作废或删掉，再回来删这张单。"
        ),
    )

def soft_delete_order(db: Session, order: PurchaseOrder, *, operator_id: int | None) -> None:
    """整张单进回收站：逐行把流水摆成「没发生过」+ 应付单一起软删。

    应付单还有没撤销的付款时**删不掉**（`supplier_service.soft_delete_payable` 会如实报
    「还有 N 笔没撤销的付款」）—— 这正是用户要的「已经付过钱的单不能悄悄消失」。
    """
    ensure_alive(order, "采购单", f"POST /purchase-orders/{order.id}/restore")
    # 挂着还算数的进项票就不许删（FEAT-0014：税账的第一道闸）。
    _ensure_no_live_invoices(db, order)
    before = _snapshot(order)
    for item in active_items(order):
        _detach_line(db, item, operator_id=operator_id)
    if order.payable_id is not None:
        payable = db.get(SupplierPayable, order.payable_id)
        if payable is not None and not payable.is_deleted:
            svc.soft_delete_payable(db, payable)
    order.is_deleted = True
    order.deleted_at = utc_now_naive()
    write_log(
        db,
        operator_id=operator_id,
        order_id=None,
        action=OperationAction.PURCHASE_ORDER_DELETE,
        change_payload={"before": before, "after": _snapshot(order)},
    )
    db.commit()


def restore_order(db: Session, order: PurchaseOrder, *, operator_id: int | None) -> PurchaseOrder:
    """从回收站恢复：逐行按明细原样写回（库存 + 成本价），并恢复那张应付单。"""
    if not order.is_deleted:
        raise HTTPException(400, detail="这张采购单不在回收站里，不需要恢复。")
    supplier = svc.get_supplier_or_404(db, order.supplier_id)
    for item in active_items(order):
        _attach_line(db, item, operator_id=operator_id)
    if order.payable_id is not None:
        payable = db.get(SupplierPayable, order.payable_id)
        if payable is not None and payable.is_deleted:
            svc.restore_payable(db, payable)
    order.is_deleted = False
    order.deleted_at = None
    _sync_payable(
        db, order,
        total=total_of(order.items),
        supplier=supplier,
        operator_id=operator_id,
    )
    write_log(
        db,
        operator_id=operator_id,
        order_id=None,
        action=OperationAction.PURCHASE_ORDER_RESTORE,
        change_payload=_snapshot(order),
    )
    db.commit()
    db.refresh(order)
    return order
