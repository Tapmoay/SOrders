"""退货（唯一的执行入口）（orders_return）—— 2026-09-24 整改阶段 4 **纯搬迁**的产物。

从 `api/v1/orders.py` 原样搬来的 1 个函数（return_order_endpoint）。
除代码组织外**一个字没改** —— URL / 入参 / 出参 / 权限 / 状态机 / 数据库全不变；
证据：`_tools/qa/_api_contract_snapshot.py --diff <搬之前> <搬之后>` 契约零差异。

⚠️ 本模块**自己声明** `router`：按文件解析的 AST 工具（端点索引 / AI 能力表）靠这一行算 URL 前缀。
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import Order, User
from app.schemas.order import OrderReturnBody, OrderReturnOut
from app.services.order_response import enrich_order_out, load_order_for_response
from app.services.order_return import OrderReturnError, ReturnItem, return_order
from app.services import order_return_request as return_request_svc
from app.core import outbox

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/{order_id}/return", response_model=OrderReturnOut)
def return_order_endpoint(
    order_id: int,
    body: OrderReturnBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_RETURN)),
) -> OrderReturnOut:
    """**订单退货**（2026-09-20 用户要求）。

    一次调用动五样东西（行级已退数量 / 账本红冲 / 库存回补 / 可能退现 / 订单状态），
    全部在 `services/order_return.py` 一处，本端点只做"取单 → 调服务 → 提交 → 回参"。

    ⚠️ **整单退货不是另一个端点**：客户端把每一行的数量都填满，走同一套行级校验。
       多一条"整单"的路径就多一条能绕过"货损那几件不能退"的路。
    ⚠️ 失败要**整单回滚**（所有变更在一个事务里）：红冲写了一半而库存没回补，
       是最难查的一类账（账上说退了、仓库里货没回来）。
    ⚠️ 取单时就**锁住这一行**（与收款同一条理由）：两个退货请求同时进来会各自通过
       "还能退几件"的校验（`max_returnable` 读的是各自快照里的 `returned_quantity`），
       退出去的量就会超过下单量。加锁之后后到的请求要等前一个提交，算出来的是真实余量。
    """
    order = db.scalars(
        select(Order)
        .options(selectinload(Order.order_products))
        .where(Order.id == order_id)
        .with_for_update()
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # 这一单若挂着一张**待处理的退货申请**：直连退货**照旧允许**，退完把它**自动关掉**
    # （2026-09-21 用户拍板：「把规则改成派单员退货之后，自动取消申请，然后它对应的数据发生改变」）。
    #
    # ⚠️ 这条规则换过一次方向，两次都记在这里，免得下一个人再翻回去：
    #   ① 最初（同日早些时候）我这里是 **400 fail-closed**：申请还挂着时不许直连退货。
    #      理由是真实的 —— 货主申请退 2 件（共 5 件）→ 派单员手工退了 2 件 → 申请仍是待处理 →
    #      他（或另一个派单员）再点「办理」时余量 3 ≥ 2、**校验全部通过** → 同一批货退第二遍。
    #   ② 用户拍板改成"**允许直连 + 自动关闭申请**"。← **现在跑的是这一条**。
    #      所以"同一批货退两遍"那个洞由**关闭申请**来堵：申请一旦不是 pending，
    #      `fulfill` 会被 `_check_pending` 拒（"已经由派单员直接退了货（自动关闭）"）。
    # ⛔ 因此下面这一次 `close_by_direct_return` 调用**不是可选的美化**：删掉它，
    #    ①里的双重退货就会原样复活（红线 `_check_return_request.py` 与它的反向验证钉着）。
    pending_req = return_request_svc.pending_for_order(db, order.id)
    try:
        result = return_order(
            db,
            order,
            [ReturnItem(order_product_id=i.order_product_id, quantity=i.quantity) for i in body.items],
            note=body.note,
            operator_id=current.id,
        )
        closed = None
        closed_note = ""
        if pending_req is not None:
            closed = return_request_svc.close_by_direct_return(
                db,
                order,
                dispatcher_id=current.id,
                items=[ReturnItem(order_product_id=i.order_product_id, quantity=i.quantity) for i in body.items],
            )
            if closed is not None:
                closed_note = closed[1]
                closed = closed[0]
    except OrderReturnError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    sid = order.shipper_id
    oid = order.id
    closed_id = closed.id if closed is not None else None
    # ⚠️ 两条事件与这次退货**同一个事务**（整改报告 §10）：退货没成，账本刷新与"申请被直接办掉"
    #    的通知都不该发出去。
    if sid is not None:
        outbox.enqueue(db, "ledger.updated", {"shipper_id": sid})
    if closed_id is not None:
        outbox.enqueue(
            db,
            "returns.request_closed",
            {
                "request_id": closed_id,
                "returned_amount": str(result.returned_amount),
                "note": closed_note,
            },
        )
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return OrderReturnOut(
        order_no=result.order_no,
        returned_amount=result.returned_amount,
        refund_amount=result.refund_amount,
        fully_returned=result.fully_returned,
        restocked_lines=result.restocked_lines,
        warnings=result.warnings,
        order=enrich_order_out(full, db, current),
    )
