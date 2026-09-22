from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import Order, OrderProduct, Product, User
from app.models.enums import OperationAction, OrderStatus
from app.schemas.order import OrderProductCreate, OrderProductOut, OrderProductUpdate
from app.services.inventory_service import resync_reservations
from app.services.operation_log_service import write_log
from app.services.order_flow import lock_order_row, resolve_line_total

router = APIRouter(prefix="/order-products", tags=["order-products"])


def _check_product_ref(db: Session, product_id: int | None) -> None:
    """行上带的商品编号必须真的在商品库里、且没被删（否则成本快照按 0 记、送达不扣库存）。"""
    if product_id is None:
        return
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(
            status_code=400,
            detail=f"商品编号 {product_id} 不在商品库里。请重新选一个商品，或改成不填编号的手输商品行。",
        )
    if p.is_deleted:
        raise HTTPException(status_code=400, detail=f"商品「{p.name}」已经删除了，请重新选一个。")


def _resync_stock_if_assigned(db: Session, order: Order, operator_id: int) -> int:
    """订单行变更后把**预占**重算（只对已经派过单的单做）。

    ⛔ 判据"派过单没有"**不能看有没有 RESERVED 流水**（2026-09-19 审计第十七轮，
    这是一条"越修越错"的判据）：

    `auto_stock_out` 是**逐行**写的，而行的商品要能解析出 `product_id` 才写
    （手输商品名、或商品库里有多个同名 → `_resolve_product` 返回 None → 那一行**一条流水都没有**，
    这是设计如此，见 `inventory_service` 的模块注释）。于是：

    手输商品名下单 → 派单（这条流水没写）→ 派单员在明细里把该行改成库里的商品
    → 老判据查到 0 条 RESERVED，直接 `return 0` → **预占永远补不回来**
    → 送达时 `auto_stock_commit` 只遍历 RESERVED，那一件货**一件都不扣**。

    本机只读复核（2026-09-19）：在途未删订单里"有商品编号却零预占"的 (单,商品) 对 **21** 个，
    `GET /inventory/summary` 的「在途占用」与在途订单行有 **9** 个商品对不上（合计至少 72 件）；
    而 `note='订单行变更后重算预占'` 的流水**一行都没有** —— 说明这个守卫从来没放行过。

    正确的判据是**订单自己的状态**：已经派过单（`dispatched_at` 有值，或状态已过 DISPATCHED）
    就说明"这一刻库里已经为该单占过位"，改完行必须重算；没派过的单不需要动
    （那时还没预占，送达前若再派单会按当时的行一次性预占）。
    """
    if order.dispatched_at is None:
        return 0
    # ⚠️ **终态的单一条预占都不许补**（2026-09-23 第 6 轮）：这一列的判据原来是
    #    "派过单没有"，而 `dispatched_at` 在送达后**不会清掉**（撤回才会清，见 `recall_dispatch`）。
    #    于是"已送达的单被改了明细"（并发窗口里够得着，见 `_locked_editable_order`）会走到这里，
    #    按新行补出 RESERVED 流水 —— 那张单的货早就 `auto_stock_commit` 扣过了，
    #    这些流水没有任何人会消费，只会在「在途占用」里**永久**挂着（用户按它决定要不要补货）。
    #    状态判据与上面那道门同源（`_order_allows_line_edit`），这里再钉一次：门是给人看的，
    #    这一行是给"万一还有人从别的路径调进来"兜底的。
    if not _order_allows_line_edit(order):
        return 0
    # 重算期间把订单行锁住（MySQL 上是 `SELECT … FOR UPDATE`，SQLite 忽略）：
    # `resync_reservations` 是"按当前行算目标值 → 与本单现有 RESERVED 流水对账 → 补差额"，
    # 两个并发的行编辑会各自读到同一份"现有值"、各写同一个差额 → 预占翻倍 → 送达**多扣**。
    # 锁住订单行之后两次编辑串行，第二个人读到的是第一个人写完的流水。
    db.execute(select(Order.id).where(Order.id == order.id).with_for_update())
    return resync_reservations(db, order, operator_id)


def _order_allows_line_edit(order: Order) -> bool:
    """派单员修正明细：待派单与已接单（运输中）均可编辑；已送达/已撤销不可。"""
    return order.status in (OrderStatus.PENDING_DISPATCH, OrderStatus.DISPATCHED, OrderStatus.ACCEPTED)


def _locked_editable_order(db: Session, order_id: int) -> Order:
    """**取锁 + 重读**之后再把订单交回给调用方（改明细前的唯一入口）。

    ### 为什么不能直接 `db.get(Order, …)` 再判（2026-09-23 第 6 轮，实测复现）
    三个写端点原来都是「`db.get` 读一份 → `_order_allows_line_edit(order)` → 写」。
    `db.get` 拿的是**身份映射里那份**，它可能是这一轮请求更早（或上一个请求）读到的旧值；
    而司机送达走的是另一条路：条件 UPDATE 抢占 `ACCEPTED → DELIVERED`，
    抢到之后**立刻按当时的订单行写账本**（`ledger_sync`，一行一条、按 `order_product_id` 幂等）。

    并发窗口因此是：

    | 时刻 | 派单员（改明细） | 司机（送达） |
    |---|---|---|
    | T1 | 读到"已接单" ✔ 放行 | |
    | T2 | | 抢占成功 → 订单=已送达、账本按**改前**的行金额写入 |
    | T3 | 写入新的数量/金额（没人再拦） | |

    终态是**「已送达」的单，行金额是新的、账本金额是旧的** —— 两个数各说各的，
    而没有任何地方会报错（收款按账本、毛利按订单行）。这一轮的单测
    `test_stale_status_must_not_let_line_edit_through` 就是先把这一刻摆出来：
    修之前那个 PATCH 返回 **200**。

    修法与派单/接单/送达/撤回那几处**同一个手法**（不新造轮子）：`lock_order_row` 在
    MySQL 上是 `SELECT … FOR UPDATE`（送达那边的 CAS 会与它互斥，谁先谁后都能自洽），
    SQLite 上退化成"重新查一次"，两边都保证**判据挂在库里这一刻的真实值上**。

    ⚠️ 顺序要紧：**先锁再判**。先判后锁的话，从"判完"到"拿到锁"之间那道缝还在。
    """
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=400, detail="订单数据异常")
    order = lock_order_row(db, order)
    if not _order_allows_line_edit(order):
        raise HTTPException(
            status_code=400,
            detail=f"当前订单状态（{order.status.value if hasattr(order.status, 'value') else order.status}）"
                   "不可编辑商品明细；已送达/已撤销的单请用「退货」或让派单员重新开单。",
        )
    return order


@router.get("", response_model=list[OrderProductOut])
def list_order_products(
    order_id: int = Query(..., description="按订单筛选明细"),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_READ_ALL)),
) -> list[OrderProduct]:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    rows = db.scalars(select(OrderProduct).where(OrderProduct.order_id == order_id)).all()
    return list(rows)


@router.post("", response_model=OrderProductOut, status_code=status.HTTP_201_CREATED)
def create_order_product(
    body: OrderProductCreate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_PRODUCT_EDIT)),
) -> OrderProduct:
    if db.get(Order, body.order_id) is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    order = _locked_editable_order(db, body.order_id)
    try:
        lt = resolve_line_total(body.unit_price, body.quantity, body.line_total)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _check_product_ref(db, body.product_id)
    # 单位：客户端给了就用，没给则回退商品库里的单位（人工加的行回退"件"）
    unit = (body.unit or "").strip()
    cost_snapshot = Decimal("0")
    if body.product_id is not None:
        p = db.get(Product, body.product_id)
        if p is not None:
            if not unit:
                unit = (p.unit or "件").strip() or "件"
            # ⚠️ 成本快照必须在这里定格（2026-09-19 审计）：下单路径早就在写
            #    （`order_flow.build_order_products`），而这个"派单员后来加一行"的入口**从来没写** ——
            #    行成本恒为 0，于是：① 报表把这一行算成"0 成本、100% 毛利"（毛利虚高）；
            #    ② 司机对这一行报货损时 `apply_damage_accounting` 判 cost<=0 直接跳过 →
            #    **损失金额永远不落账**，而提示语还把原因说成"请在商品管理里补上成本价"
            #    （商品库里有成本价，缺的是这一行没定格）。
            cost_snapshot = p.cost_price or Decimal("0")
    op = OrderProduct(
        order_id=body.order_id,
        product_id=body.product_id,
        product_name_snapshot=body.product_name_snapshot,
        quantity=body.quantity,
        unit_price=body.unit_price,
        line_total=lt,
        unit_snapshot=(unit or "件")[:32],
        cost_price_snapshot=cost_snapshot,
    )
    db.add(op)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_LINE_ADD,
        change_payload={"line_id": op.id},
    )
    # 行加了 → 预占要跟着加，否则送达时这件货**永远不扣库**（见 resync_reservations 的说明）
    db.flush()
    _resync_stock_if_assigned(db, order, current.id)
    db.commit()
    db.refresh(op)
    return op


@router.get("/{line_id}", response_model=OrderProductOut)
def get_order_product(line_id: int, db: Session = Depends(get_db), current: User = Depends(require_permission(Permission.ORDER_READ_ALL))) -> OrderProduct:
    op = db.get(OrderProduct, line_id)
    if op is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return op


@router.patch("/{line_id}", response_model=OrderProductOut)
def update_order_product(
    line_id: int,
    body: OrderProductUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_PRODUCT_EDIT)),
) -> OrderProduct:
    op = db.get(OrderProduct, line_id)
    if op is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    order = db.get(Order, op.order_id)
    if order is None:
        raise HTTPException(status_code=400, detail="订单数据异常")
    # ⚠️ 先锁再判（理由见 `_locked_editable_order`）：手边这份 order 可能是旧状态
    order = _locked_editable_order(db, op.order_id)
    if body.product_id is not None:
        _check_product_ref(db, body.product_id)
    # ⚠️ 只改数量或只改单价时，行金额必须**跟着重算**；两个都给了也要核对一致性
    #    （原来客户端可以塞一个和"单价×数量"无关的 line_total，账本就跟着错）。
    new_up = body.unit_price if body.unit_price is not None else op.unit_price
    new_qty = body.quantity if body.quantity is not None else op.quantity
    if body.line_total is not None or body.quantity is not None or body.unit_price is not None:
        try:
            op.line_total = resolve_line_total(new_up, new_qty, body.line_total)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    if body.product_id is not None:
        op.product_id = body.product_id
        # 换商品必须**同时换成本快照**（2026-09-19 审计）：不换的话这一行仍按旧商品的成本
        # 算毛利/货损（把 50 元成本的货按 10 元记，毛利虚增、货损少记）。
        changed = db.get(Product, body.product_id)
        if changed is not None:
            op.cost_price_snapshot = changed.cost_price or Decimal("0")
    if body.product_name_snapshot is not None:
        op.product_name_snapshot = body.product_name_snapshot
    if body.quantity is not None:
        op.quantity = body.quantity
    if body.unit_price is not None:
        op.unit_price = body.unit_price
    if body.unit is not None:
        op.unit_snapshot = body.unit.strip()[:32]
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_LINE_UPDATE,
        change_payload={"line_id": op.id},
    )
    # 数量/商品改了 → 预占按商品逐一对账补齐（否则送达按旧流水扣库：多扣/少扣/扣错商品）
    db.flush()
    _resync_stock_if_assigned(db, order, current.id)
    db.commit()
    db.refresh(op)
    return op


@router.delete("/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order_product(
    line_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_PRODUCT_EDIT)),
) -> None:
    op = db.get(OrderProduct, line_id)
    if op is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    order = db.get(Order, op.order_id)
    if order is None:
        raise HTTPException(status_code=400, detail="订单数据异常")
    # ⚠️ 先锁再判（理由见 `_locked_editable_order`）
    order = _locked_editable_order(db, op.order_id)
    oid = op.order_id
    db.delete(op)
    if order:
        write_log(
            db,
            operator_id=current.id,
            order_id=oid,
            action=OperationAction.ORDER_LINE_DELETE,
            change_payload={"line_id": line_id},
        )
        # 行删了 → 对应的预占要放掉，否则送达会照扣一件已经不存在的货
        db.flush()
        _resync_stock_if_assigned(db, order, current.id)
    db.commit()
