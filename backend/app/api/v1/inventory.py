"""库存管理（派单员）：出入库流水自动维护商品库存。"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.business_time import business_range_utc
from app.core.pagination import finish_page
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import parse_date_range, require_permission
from app.models import InventoryMovement, Product, User
from app.models.enums import OperationAction
from app.schemas.inventory import MovementCreate, MovementOut
from app.services import cost_history
from app.services.cost_history import record_cost
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/movements", response_model=list[MovementOut])
def list_movements(
    response: Response,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    product_id: int | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    date_from: str | None = Query(None, description="YYYY-MM-DD（含当天）"),
    date_to: str | None = Query(None, description="YYYY-MM-DD（含当天）"),
) -> list[InventoryMovement]:
    # 多取一行判截断（2026-09-19 外部完整检查 R2-3）：这条端点原来**既不回报截断、
    # 缺省又只有 100 条**，于是更早的流水在 App 里静默消失 —— 用户会据此得出"这批货没入过库"。
    q = (
        select(InventoryMovement)
        .order_by(InventoryMovement.id.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    if product_id is not None:
        q = q.where(InventoryMovement.product_id == product_id)
    if date_from or date_to:
        # ⚠️ **必须过 `business_range_utc`**：`date_from/date_to` 是**业务当地日**（东八区），
        #    而 `inventory_movements.created_at` 存的是 **UTC naive**（`core/business_time.py`）。
        #    第一版直接拿 `parse_date_range` 的当地零点去比 —— 于是「查 9-21」实际取到的是
        #    **北京 9-21 08:00 ~ 9-22 08:00**：当天头 8 小时的流水查不到、次日头 8 小时的多进来，
        #    而界面上只是"少了几条"，看不出来是时区错（与审计 R12-M11 同族）。
        #    只给一侧时用另一侧补齐来算区间，但**只加被请求的那一侧**（开区间语义不变）。
        df, dt = parse_date_range(date_from, date_to)
        lo, hi = business_range_utc((df or dt).date(), (dt or df).date())
        if df is not None:
            q = q.where(InventoryMovement.created_at >= lo)
        if dt is not None:
            q = q.where(InventoryMovement.created_at < hi)
    return finish_page(list(db.scalars(q)), limit, response)


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
    # 进货价只在**入库**时有意义：出库带价是"一个不会生效的参数"，宁可报错也不要收下
    # （本项目最贵的一类坑就是"接受但静默无效"：界面填了、库里什么都没有）。
    if body.unit_cost is not None and body.change < 0:
        raise HTTPException(status_code=400, detail="进货价只在入库时填；出库不用填成本价")
    product = db.get(Product, body.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    cost_before = product.cost_price
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
        # ⛔ 这一行是"毛利能不能算准"的关键：进货价必须**落在流水上**。
        #    以前只拿去改商品的 `cost_price`，流水里什么都没留 ——
        #    于是毛利只能用"最新一次进货价"当成本（进货价一涨、旧库存毛利就偏低）。
        #    现在 `services/cost_basis.py` 拿这一列算加权平均进货价。
        unit_cost=Decimal(body.unit_cost) if body.unit_cost is not None else None,
    )
    db.add(row)
    # 成本价（选填）：填了就走**唯一写入口** `record_cost` —— 它同时更新
    # `products.cost_price` 与成本价生效区间表（用户 2026-09-19 要的"成本价时间轴"）。
    # ⛔ 不许在这里写 `product.cost_price = …`：那样价格变了、区间表没变，
    #    "这段时间的成本价是多少"从此对不上账，而且**界面上完全看不出来**。
    # ⚠️ 与库存加减在**同一个事务**里提交：不会出现"货进了、成本没改"或反过来。
    if body.unit_cost is not None:
        db.flush()  # 要 row.id 才能把"这条价是哪批货带进来的"记进区间表
        record_cost(
            db,
            product,
            body.unit_cost,
            source=cost_history.SOURCE_PURCHASE,
            operator_id=current.id,
            movement_id=row.id,
        )
    cost_changed = body.unit_cost is not None and Decimal(body.unit_cost) != cost_before
    # ⚠️ 库存调整**必须留痕**：它和改价是同一类事（改了钱/货的账，月底对不上要能回查）。
    #    这一条以前漏了——审计页上永远看不到谁把库存改了多少。
    #    与流水在**同一个事务**里提交，不会出现"货动了、日志没写"。
    payload: dict = {
        "product_id": product.id,
        "name": product.name,
        "change": body.change,
        "stock_after": new_stock,
        "note": body.note.strip(),
    }
    # 成本价变了就一起记（旧价→新价）：不然"这个月毛利怎么变了"在审计页上查不到原因
    if cost_changed:
        payload["cost_before"] = str(cost_before)
        payload["cost_after"] = str(product.cost_price)
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.INVENTORY_ADJUST,
        change_payload=payload,
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
            # 分类随行下发（2026-09-19）：库存页现在是"左边分类、右边商品"（用户要求与商品管理
            # 版式一致），左边的分类导航条与"这个商品属于哪一类"必须和其他页面**同一份判据**。
            # 这行以前没有，安卓侧只能再去拉一次全量商品列表自己 join —— 多一次请求，
            # 而且商品列表要是少了一个（比如刚下架），那一行就会静默变成「未分类」。
            "category": p.category or "",
        }
        for p in rows
    ]
