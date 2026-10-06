"""派单员给订单打折（CHG-0071 / 台账 L-34）—— **让价**，钱落到每一行上。

用户原话（ref m01280）：「商品可以打折，就是**订单**它可以给订单进行打折」（入口只有派单员改单，
货主 / 批发商下单**不能**打折）；`percent` 减百分比 / `amount` 抹零两种表达都要（ref m01347）；
理由选填但要进操作日志与订单详情（ref m13365）。

## 这一层只做三件事：门 + 审计 + 出参

1. **门**：`Permission.ORDER_EDIT`（与改单同一把钥匙）+ 「这张单还能改吗」（`LINE_EDITABLE_STATUSES`，
   判据只有一处，与改明细 / 账本页共用；这里 import 不复写）。
2. **审计**：打折 / 取消折扣各写一条 `write_log`（动作码 `ORDER_DISCOUNT` / `ORDER_DISCOUNT_CLEAR`）——
   一次让价会改写每一行的金额（收款 / 账本 / 营业额 / 毛利全跟着变），审计页必须分得出
   「改了个电话」和「少了 200 元」。
3. **出参**：`load_order_for_response` + `enrich_order_out`（与其余订单端点同一个装配口径）。

⛔ 算钱一个字节都不在这里：算法只有一处 `services/order_discount.py`（契约 Figure `order_discount`）。

⚠️ 本模块**自己声明 router**（前缀写在这里），与 orders 家族其余 7 个模块同一个原因：
   `scripts/gen_endpoint_index.py` 与 `_tools/ai/_gen_ai_read_catalog.py` 都按「本文件里有
   `router = APIRouter(prefix=…)`」算 URL 前缀 —— 把它搬进 `orders_common.py` 会让端点整批消失。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

# ⚠️ 从 order_products 借两样（`ledger.py` 也是这么 import 的，不复制第二份判据）：
#    · `LINE_EDITABLE_STATUSES`：可编辑状态**只有这一处**（Python 判据与那条条件 UPDATE 共用它）；
#    · `_notify_driver_lines_changed`：明细改动要通知经手那张单的司机（CHG-0040）——
#      打折同样改了每一行的金额（司机现场要收的钱跟着变），所以走同一条通知。
from app.api.v1.order_products import LINE_EDITABLE_STATUSES, _notify_driver_lines_changed
from app.api.v1.orders_common import _get_order_scoped
from app.core.business_time import utc_now_naive
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import Order, User
from app.models.enums import OperationAction
from app.schemas.order import OrderDiscountBody, OrderOut
from app.services.operation_log_service import write_log
from app.services.order_discount import (
    OrderDiscountError,
    apply_discount,
    clear_discount,
    has_discount,
)
from app.services.order_flow import lock_order_row
from app.services.order_response import enrich_order_out, load_order_for_response

router = APIRouter(prefix="/orders", tags=["orders"])


def _editable_order_for_discount(order_id: int, current: User, db: Session) -> Order:
    """打折 / 取消折扣前的**唯一入口**：先锁、再判、最后抢一次原子占位。

    与 `order_products._locked_editable_order` 同一手法（那边把三个改明细端点踩过的坑
    写成了长注释）：
      · **先锁再判** —— 先判后锁的话，从"判完"到"拿到锁"之间那道缝还在；
      · `lock_order_row` 在 **SQLite 上退化成"重新查一次"**，读到的仍是本事务开始那一刻的
        快照 ⇒ 再加一条**与数据库无关**的条件 UPDATE 占位（`updated_at` 必须真的会变，
        写同一个值会被算成 0 行，而按 0 行出局＝把正常打折也挡了）。
    ⛔ 判据 `LINE_EDITABLE_STATUSES` 只有一处（`order_products.py`）—— 这里不复制。
    """
    order = lock_order_row(db, _get_order_scoped(order_id, current, db))
    if order.status not in LINE_EDITABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"当前订单状态（{order.status.value if hasattr(order.status, 'value') else order.status}）"
                   "不能打折；已送达 / 已撤销 / 已退货的单请先让货主重开一张。",
        )
    claimed = db.execute(
        update(Order)
        .where(
            Order.id == order.id,
            Order.status.in_(LINE_EDITABLE_STATUSES),
            Order.deleted_at.is_(None),
        )
        .values(updated_at=utc_now_naive())
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="这张单刚刚被改过（可能已送达 / 已撤销），请刷新后看看当前状态再打折。",
        )
    return order


def _respond(db: Session, order: Order, current: User) -> OrderOut:
    """提交之后按全库统一的装配口径把订单交回去（与其余订单端点逐字同形）。"""
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/discount", response_model=OrderOut)
def apply_order_discount(
    order_id: int,
    body: OrderDiscountBody,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderOut:
    """给这一单打个折（**幂等替换**：再打一次＝按新值重算，不叠加）。

    `body.line_ids` 空 = 整单打折；给了 id = 只打这几行（勾选打折）。
    ⚠️ 勾到「不参与打折」的商品 ⇒ `order_discount` 抛错 ⇒ 这里 **400 拒绝**（不静默过滤：
    静默跳过会让派单员以为打了折，而钱一分没少）。
    """
    order = _editable_order_for_discount(order_id, current, db)
    reason = (body.reason or "").strip() or None
    try:
        plan = apply_discount(
            db,
            order=order,
            kind=body.kind,
            value=body.value,
            line_ids=body.line_ids,
            reason=reason,
            actor_id=current.id,
        )
    except OrderDiscountError as exc:
        # ⚠️ 服务里可能已经改过几行的 `line_total`（先撤旧折扣再算新的）—— 出错必须回滚，
        #    否则同一个事务里后面对得上不上就说不清了。
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_DISCOUNT,
        change_payload={
            "kind": plan.kind,
            "value": str(plan.value),
            "amount": str(plan.amount),
            "line_ids": plan.line_ids,
            "reason": reason,
        },
    )
    _notify_driver_lines_changed(db, order)
    db.commit()
    return _respond(db, order, current)


@router.delete("/{order_id}/discount", response_model=OrderOut)
def clear_order_discount(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderOut:
    """取消折扣：每一行按快照里的 `before` **精确还原**（⛔ 不去猜"单价 × 数量"）。

    本来就没折扣 ⇒ **400**：不是幂等的"无事发生"。理由是审计 —— 放行的话每次误点都会
    落一条「取消了折扣」（没有任何东西被取消），审计页上反而分不出真假。
    """
    order = _editable_order_for_discount(order_id, current, db)
    if not has_discount(order):
        raise HTTPException(status_code=400, detail="这一单本来就没有折扣。")
    restored = clear_discount(db, order=order)
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_DISCOUNT_CLEAR,
        change_payload={"restored_line_ids": restored},
    )
    _notify_driver_lines_changed(db, order)
    db.commit()
    return _respond(db, order, current)
