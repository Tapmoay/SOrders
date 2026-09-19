"""库存管理（派单员）：出入库流水自动维护商品库存。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import parse_date_range, require_permission
from app.models import InventoryMovement, Product, User
from app.models.enums import OperationAction
from app.schemas.inventory import MovementCreate, MovementOut
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/movements", response_model=list[MovementOut])
def list_movements(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    product_id: int | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    date_from: str | None = Query(None, description="YYYY-MM-DD（含当天）"),
    date_to: str | None = Query(None, description="YYYY-MM-DD（含当天）"),
) -> list[InventoryMovement]:
    q = select(InventoryMovement).order_by(InventoryMovement.id.desc()).offset(offset).limit(limit)
    if product_id is not None:
        q = q.where(InventoryMovement.product_id == product_id)
    if date_from or date_to:
        df, dt = parse_date_range(date_from, date_to)
        if df is not None:
            q = q.where(InventoryMovement.created_at >= df)
        if dt is not None:
            q = q.where(InventoryMovement.created_at <= dt)
    return list(db.scalars(q))


@router.post("/movements", response_model=MovementOut, status_code=status.HTTP_201_CREATED)
def create_movement(
    body: MovementCreate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
) -> InventoryMovement:
    """手工出入库：**判据与加减在同一条 SQL 里**（2026-09-19 审计）。

    ⛔ 原来是"读 → 算 → 判 → 写回绝对值"：

        new_stock = (product.stock or 0) + body.change
        if new_stock < 0: raise 库存不足
        product.stock = new_stock

    两个后果都是静默的：
      ① **库存不足拦不住**（典型 TOCTOU）：库存 10，两个人同时出库 8，各自读到 10、
         都算出 2 ≥ 0 → 都放行 → 一共出库 16，账面却是 2；
      ② **lost update**：任何并发的另一笔加减都会被这次"写回绝对值"整段盖掉
         （两个请求同秒扣 3，只剩一次；本机 SQLite 串行所以测不出来，生产 MySQL 必然发生）。

    现在把"够不够"写进 `WHERE`，让数据库在**写入那一刻**再判一次：
    `UPDATE products SET stock = stock + :change WHERE id = :id AND stock + :change >= 0`。
    改到 0 行 = 这一次没抢到（不够扣 / 商品刚被删 / 库存刚被改过），再查一次库**如实说原因**。
    """
    if body.change == 0:
        raise HTTPException(status_code=400, detail="变动数量不能为 0")
    product = db.get(Product, body.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    res = db.execute(
        update(Product)
        .where(
            Product.id == body.product_id,
            func.coalesce(Product.stock, 0) + body.change >= 0,
        )
        .values(stock=func.coalesce(Product.stock, 0) + body.change)
    )
    if res.rowcount != 1:
        # 抢不到的原因必须说清楚：是"不够扣"还是"这一行刚被并发改了"
        db.rollback()
        fresh = db.get(Product, body.product_id)
        if fresh is None:
            raise HTTPException(status_code=404, detail="商品不存在")
        now_stock = fresh.stock or 0
        if now_stock + body.change < 0:
            raise HTTPException(
                status_code=400,
                detail=f"库存不足：当前库存 {now_stock}，出库 {abs(body.change)} 超出",
            )
        raise HTTPException(
            status_code=409,
            detail=f"库存刚刚被别的操作改过（当前 {now_stock}），请刷新后重试",
        )
    # 复核用的权威值：从库里重新读回来（不要拿"算出来的那个数"去写日志）
    db.refresh(product)
    new_stock = product.stock or 0
    row = InventoryMovement(
        product_id=body.product_id,
        change=body.change,
        note=body.note.strip(),
        operator_id=current.id,
        source="MANUAL",
        status="COMMITTED",
    )
    db.add(row)
    # ⚠️ 库存调整**必须留痕**：它和改价是同一类事（改了钱/货的账，月底对不上要能回查）。
    #    这一条以前漏了——审计页上永远看不到谁把库存改了多少。
    #    与流水在**同一个事务**里提交，不会出现"货动了、日志没写"。
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.INVENTORY_ADJUST,
        change_payload={
            "product_id": product.id,
            "name": product.name,
            "change": body.change,
            "stock_after": new_stock,
            "note": body.note.strip(),
        },
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/summary")
def inventory_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    below_alert: bool = Query(False, description="只返回库存已达报警阈值的商品"),
) -> list[dict]:
    """库存概览：商品名 + 当前库存 + 在途占用量（派单中未送达，低库存排前）。"""
    from app.models import Order

    q = select(Product).where(Product.is_active.is_(True)).order_by(Product.stock, Product.id)
    if below_alert:
        # 与 Android InventoryScreen 标红判断一致：阈值 > 0 且 库存 <= 阈值
        q = q.where(Product.low_stock_alert > 0).where(Product.stock <= Product.low_stock_alert)
    rows = db.scalars(q)
    # ⚠️ 「在途占用」必须 join orders（2026-09-19 审计第十七轮）：保留任务物理清理订单时
    #    **不删 `inventory_movements`**（台账 D3 只修了账单那一半），那些 RESERVED 流水会
    #    被永久计入"在途"，于是库存页常年显示一堆早已不存在的在途货 → 用户按它决定"要不要补货"。
    #    同时也排掉软删单（进回收站的单不再是"在途"）。
    reserved_rows = db.execute(
        select(InventoryMovement.product_id, func.sum(InventoryMovement.change))
        .join(Order, Order.id == InventoryMovement.order_id)
        .where(
            InventoryMovement.source == "ORDER",
            InventoryMovement.status == "RESERVED",
            Order.deleted_at.is_(None),
        )
        .group_by(InventoryMovement.product_id)
    ).all()
    reserved_map = {pid: abs(int(total or 0)) for pid, total in reserved_rows}
    return [
        {
            "product_id": p.id,
            "product_name": p.name,
            "stock": p.stock or 0,
            "unit": p.unit or "件",
            "low_stock_alert": p.low_stock_alert or 0,
            "reserved": reserved_map.get(p.id, 0),
        }
        for p in rows
    ]
