"""订单生命周期（创建 / 编辑 / 异常标记 / 回收站恢复 / 删除）（orders_lifecycle）—— 2026-09-24 整改阶段 4 **纯搬迁**的产物。

从 `api/v1/orders.py` 原样搬来的 5 个函数（create_order,update_order,patch_order_exception,restore_order,delete_cancelled_order）。
除代码组织外**一个字没改** —— URL / 入参 / 出参 / 权限 / 状态机 / 数据库全不变；
证据：`_tools/qa/_api_contract_snapshot.py --diff <搬之前> <搬之后>` 契约零差异。

⚠️ 本模块**自己声明** `router`：按文件解析的 AST 工具（端点索引 / AI 能力表）靠这一行算 URL 前缀。

📌 **第二轮 R2-02（2026-09-25）**：`create_order` / `update_order` 的**应用逻辑搬进了
`app/commands/order.py`** —— 本文件从此只做 HTTP（认证 / 参数 / 响应 / 状态码）。
为什么：方向指南要的形状是 `Route → Command → Application → DomainRule → Persistence`，
而「这一单为谁下 / 兜底下单人 / 商品白名单 / 能不能改 / 改完要发什么事件」是**业务动作怎么组织**，
不是 HTTP 的事。搬运判据与上一段同：URL / 入参 / 出参 / 权限 / 状态机 / 数据库全不变，
错误文案与状态码逐字一致（`CommandError` 只搬运，不发明）。
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.commands import order as order_commands
from app.core.business_time import utc_now_naive
from app.core.rbac import Permission, role_has_permission, user_role_key
from app.database import get_db
from app.deps import DispatcherUser, require_permission, require_roles
from app.models import Order, User
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.schemas.order import OrderCreate, OrderExceptionBody, OrderOut, OrderUpdate
from app.services.operation_log_service import write_log
from app.services.order_response import enrich_order_out, load_order_for_response
from app.api.v1.orders_common import (
    _get_order_scoped,
)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cancelled_order(
    order_id: int,
    # ⚠️ 2026-09-25 §9 第②步第五域：这道「只有货主/派单员能删」的门从**函数体**搬到**签名**上。
    #    等价（原来非这两种角色 403「无权操作」，现在 403 由入口统一给出），
    #    但端点索引的授权列从此读得出真实授权。
    #    ⛔ 下面 `if role == SHIPPER` 那一支里的**权限点**门（ORDER_DELETE_CANCELLED）
    #    **留在体内**：它只对货主生效，依赖角色分支，签名级表达不了。
    current: Annotated[User, Depends(require_roles(UserRole.SHIPPER, UserRole.DISPATCHER))],
    db: Session = Depends(get_db),
) -> None:
    """软删除订单 → 进入隔离区 30 天（用户不可见；派单员可恢复；到期物理清理）。
    货主：本人 已送达/已撤销/异常 订单；派单员：任意状态（含待派单）。"""
    order = _get_order_scoped(order_id, current, db)
    role = user_role_key(current)
    if role == UserRole.SHIPPER.value:
        if not role_has_permission(role, Permission.ORDER_DELETE_CANCELLED):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作")
        # ⛔ 「异常」**不是**删除通行证（2026-09-19 审计）。原来这里是
        #    `if 状态不在(已撤销, 已送达) and not is_exception:` —— 那个 `and` 让"是异常单"
        #    成了万能钥匙，而括号里那句"进行中的订单请走撤销或撤回"正是它要防的情况：
        #    派单员给一张**已接单在途**的单标了异常（客户催单是日常操作）→ 货主那一页出现
        #    「删除订单」→ 一删，单子进回收站 → 司机端列表里它直接消失（`GET /orders` 对司机
        #    过滤 `deleted_at`）→ **司机拿着打不开的单跑车，到现场发现单子没了、也拿不到钱**。
        #    现在：异常单必须**先撤销/撤回**（把状态变成终态）才能删。
        #
        # ⛔ 2026-09-24 第 20 轮（D12-F3）：**已送达也收掉了** —— 用户 2026-09-21 的规矩是
        #    「他不能删他的订单……除非是那个**已撤销**的订单信息」，而这条当时**只落在 AI 侧**
        #    （`AiWriteOrderLineHandlers.kt` 的 `SHIPPER_AI_DELETABLE = {CANCELLED}`）——
        #    同一个动作在 AI 那里被拒、在界面上放行，两个答案。
        #    为什么必须收：`shipper_ledger` 的「我该付的」按 `deleted_at is None` 聚合
        #    （`shipper_ledger.py:248-253`）—— 货主把自己一张**已送达**的单删掉，
        #    那笔应收就从他那一页消失，派单员按货主账催收永远看不到（钱凭空少一笔）。
        if order.status != OrderStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "货主只能删除**已撤销**的订单。"
                    + (
                        "这是一张已送达的订单：那笔货款已经入账，删掉会让账上看不见它；"
                        "如有异议请联系派单员处理退货。"
                        if order.status == OrderStatus.DELIVERED
                        else "这是一张进行中的订单"
                        + ("（已标异常）" if bool(order.is_exception) else "")
                        + "，请先走撤销或撤回，再删除。"
                    )
                ),
            )
    if order.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="订单已在隔离区，如需恢复请联系派单员")
    # 软删除时间统一用 **UTC naive**（`business_time.utc_now_naive`）：保留任务按 UTC 比
    # `deleted_at < cutoff`，而原来这里是 tz-aware UTC、其它六张表是本地时间 —— 三种基准混用，
    # 30 天隔离期在同一套判据下有的早 8 小时、有的同秒比较还会受字符串形状影响（R14-9 同族）。
    order.deleted_at = utc_now_naive()
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_DELETE,
        change_payload={"order_no": order.order_no},
    )
    db.commit()


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    body: OrderCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_CREATE)),
) -> OrderOut:
    """创建订单，初始状态为派单中（PENDING_DISPATCH）。

    客户端本地「未提交草稿」与已落库订单无关；创建成功后应以响应中的
    ``created_at`` 为准清除草稿状态，避免与派单中订单混淆。
    """
    try:
        order = order_commands.create_order(db, actor=current, body=body)
    except order_commands.CommandError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from None
    return enrich_order_out(order, db, current)


@router.patch("/{order_id}", response_model=OrderOut)
def update_order(
    order_id: int,
    body: OrderUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderOut:
    try:
        order = order_commands.update_order(db, actor=current, order_id=order_id, body=body)
    except order_commands.CommandError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from None
    return enrich_order_out(order, db, current)


@router.patch("/{order_id}/exception", response_model=OrderOut)
def patch_order_exception(
    order_id: int,
    body: OrderExceptionBody,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderOut:
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    order.is_exception = body.is_exception
    order.exception_reason = body.exception_reason or ""
    order.exception_resolution = body.exception_resolution or ""
    # ⚠️ 重新登记异常时必须**清掉上一次的解决时间**（2026-09-19 审计）：
    #    `exception_resolved_at` 一直只有"解决"那条路径写，这里从来不清。
    #    于是"用户重新登记一条异常 → 接口 200、提示"异常已登记"，但列表里它带着旧的解决时间
    #    → 报表的「要处理」按 resolved 过滤 → **它永远不出现在待处理里**（典型的"操作成功但事情没做"），
    #    而且自动异常判定（`stats_service`）看到 resolved_at 非空也不再判它。
    if body.is_exception:
        order.exception_resolved_at = None
        order.exception_resolution = ""
    if body.expected_deliver_before is not None:
        order.expected_deliver_before = body.expected_deliver_before
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_EXCEPTION,
        change_payload={
            "is_exception": body.is_exception,
            "exception_reason": body.exception_reason,
            "exception_resolution": body.exception_resolution,
        },
    )
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/restore", response_model=OrderOut)
def restore_order(
    order_id: int,
    current: DispatcherUser,
    db: Session = Depends(get_db),
) -> OrderOut:
    """派单员：从隔离区恢复订单（软删除后 30 天内可恢复）。"""
    order = db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
    if order is None or order.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不在隔离区")
    order.deleted_at = None
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_RESTORE,
        change_payload={"order_no": order.order_no},
    )
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)
