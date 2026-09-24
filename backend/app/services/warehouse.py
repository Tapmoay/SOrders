"""**仓库**：认出"这一单是送到仓库的"，并按订单商品行**自动入库**。

用户 2026-09-19 的口径（两句合起来才是完整规则）：

> 「给派单员有一个选择，可以选择一个地点作为仓库。不一定只能选一个，可以选好多个。
>   之后一旦有货物进到他们这个定点，就算入库存 —— 就是一个稍微自动一点的自动入库存功能」。
> 「有一趟货是到这个仓库，**刚好这个货物商品管理里面是有的**，这时候我们就自动地入库」。
> 「你就再开一条计算线，**这条线是独立算的**…这个入库就正常入；直到那个订单完成了之后，
>   它才会减库存」。

## 这条线的边界（改之前先读这三条）

1. ⛔ **它只加不减、也绝不动"预占"**。订单自己那条线（派单预占 → 送达实扣）照旧由
   `inventory_service` 负责，两条线**各算各的** —— 这是用户明确要的"独立计算线"。
   所以**不要**在这里调用 `auto_stock_commit/release`，也不要因为"这一单是入库的"就少扣一件。
2. ⚠️ **净效果要说清**：如果这一单的商品行也解析得出商品，送达会**同时**产生
   −N（订单实扣）与 +N（到仓入库）。两条线都写进了流水，账面上看得到；
   "库存要真的增加"属于**另一条决策**（让这类单不走实扣），没有默认打开。
3. ⛔ **商品在商品管理里找不到的行，跳过并如实报出来**（`skipped`）。
   `_resolve_product` 已经是"有商品编号就用编号；没有则**同名且唯一**才认"的唯一实现 ——
   这不叫猜。**不许**在这里另写一套按名字模糊匹配的兜底：那会把"张冠李戴"的库存
   静悄悄记到另一个商品头上。

## 幂等

同一单只入一次：判据是**这张单已经有没有 `source="WAREHOUSE"` 的流水**。
为什么不挂一个布尔字段在订单上：那条线以后要能重放（补录/回滚），
而"流水本身就是事实"（与仓库/送达两条线一致）。
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import InventoryMovement, Order, Product, ShipperLocation
from app.services.inventory_service import _order_rows, _resolve_product
from app.services.place_service import haversine_m

#: 订单终点与"仓库点"的判定半径（米）。
#
# 为什么不是 `place_service.MERGE_METERS = 1.0`：那是**合并**半径（"这俩是不是同一个地点"，
# 1 米已经算宽了）；这里是**识别**半径 —— 司机/货主选点时常有几十米的漂移（同一个仓库的
# 大门口、停车场、院内），1 米会让"送到仓库"根本认不出来，而认不出来的后果是
# **这一单的货永远不入库**，且界面上完全看不出来。
#
# 为什么是 60 米：一个仓库院子的尺度。再放大会把邻居的厂区吞进来 —— 那是**记错库存**，
# 比"没记上"更糟（没记上还能手工补，记错了要盘库才发现）。
WAREHOUSE_METERS = 60.0


def warehouse_for_order(db: Session, order: Order) -> ShipperLocation | None:
    """这一单的终点是不是某个被标成「仓库」的地点？是就返回那一条。

    两条判据（**都是确定性的，不含"猜"**）：
    1. **坐标**：两边都有坐标时，相距 ≤ [WAREHOUSE_METERS]；
    2. **地址原文**：`order.address_detail` 与仓库的 `detail_address` **完全相同**（strip 后）——
       给"手打了地址但没选点、所以没有坐标"的单留一条路。

    都不成立就返回 None（= 不是送到仓库的单，正常走实扣那条线）。
    """
    rows = list(
        db.scalars(
            select(ShipperLocation).where(
                ShipperLocation.is_warehouse.is_(True),
                ShipperLocation.is_deleted.is_(False),
            )
        )
    )
    if not rows:
        return None

    text = (order.address_detail or "").strip()
    lat, lng = order.address_lat, order.address_lng
    for loc in rows:
        if lat is not None and lng is not None and loc.address_lat is not None and loc.address_lng is not None:
            if haversine_m(float(lat), float(lng), float(loc.address_lat), float(loc.address_lng)) <= WAREHOUSE_METERS:
                return loc
        if text and text == (loc.detail_address or "").strip():
            return loc
    return None


def warehouse_inbound_rows(db: Session, order: Order) -> list[InventoryMovement]:
    """这张单**已经**写过的到仓入库流水（幂等判据的唯一实现）。"""
    return list(
        db.scalars(
            select(InventoryMovement).where(
                InventoryMovement.order_id == order.id,
                InventoryMovement.source == SOURCE,
            )
        )
    )


#: 到仓入库流水的来源标记。与 `ORDER`（订单预占/实扣）**分开**：
#  两条线各自可查、可对账，混在一个 source 里就再也分不出"这 +N 是订单带来的还是到仓带来的"。
SOURCE = "WAREHOUSE"


def auto_warehouse_inbound(db: Session, order: Order, operator_id: int) -> dict:
    """按订单商品行入库（**独立的一条线**，见模块注释）。

    返回 `{"inbound": 条数, "skipped": [商品名…], "already": bool}`：
      · `skipped` 必须原样报给用户 —— "这一行没入库"是**用户要知道的事实**，
        不是可以吞掉的内部细节（它决定他手不手工补一条入库）；
      · `already=True` = 这张单已经入过，这次什么都没做（幂等）。
    """
    if warehouse_inbound_rows(db, order):
        return {"inbound": 0, "skipped": [], "already": True}

    inbound = 0
    skipped: list[str] = []
    for op in _order_rows(db, order):
        # ⛔ 入库数量要**扣掉货损**（2026-09-24 第 29 轮；第 25 轮 02 区 D1）：
        #    原来按整行数量入（`qty = op.quantity`），于是"客户订 10 件、路上坏了 2 件"
        #    这一单会往仓库入 **10** 件 —— 库存虚增 2，而坏掉那 2 件按仓库自己的规矩
        #    （`order_return` 的"货损不回补"）本来就不该算库存。两处口径直接矛盾。
        #    ⚠️ 它还依赖调用顺序：`order_flow` 里的货损录入必须**先**写进
        #    `op.damage_quantity`，这条入库线才读得到（那一处同时改了，见它的注释）。
        qty = int(op.quantity or 0) - int(op.damage_quantity or 0)
        if qty <= 0:
            continue
        prod = _resolve_product(db, op)
        if prod is None:
            skipped.append(op.product_name_snapshot or "(未命名商品行)")
            continue
        # ⛔ 库存只能用 SQL 表达式自增，不许 Python 读改写（理由同 `auto_stock_commit`：
        #    两个请求同时入库同一个商品时，读改写会把对方那一笔整段盖掉且谁都不报错）。
        db.execute(
            update(Product)
            .where(Product.id == prod.id)
            .values(stock=func.coalesce(Product.stock, 0) + qty)
        )
        db.add(
            InventoryMovement(
                product_id=prod.id,
                change=qty,
                note="到仓入库（" + (order.order_no or "") + "）",
                operator_id=operator_id,
                source=SOURCE,
                order_id=order.id,
                status="COMMITTED",
            )
        )
        inbound += 1
    return {"inbound": inbound, "skipped": skipped, "already": False}


__all__ = [
    "WAREHOUSE_METERS",
    "SOURCE",
    "warehouse_for_order",
    "warehouse_inbound_rows",
    "auto_warehouse_inbound",
]
