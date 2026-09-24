"""退货申请：货主提交/撤回，派单员查看/驳回/办理（2026-09-21 用户要求）。

## 一个流程、两组端点、两种权限

| 端点 | 谁 | 权限点 | 它动什么 |
| --- | --- | --- | --- |
| `POST /return-requests` | 货主 | `ORDER_RETURN_REQUEST` | **只写申请单** |
| `GET /return-requests/mine` | 货主 | `ORDER_RETURN_REQUEST` | 读 |
| `POST /return-requests/{id}/withdraw` | 货主 | `ORDER_RETURN_REQUEST` | 状态改「已撤回」 |
| `GET /return-requests` | 派单员 | `ORDER_RETURN` | 读（待办列表） |
| `POST /return-requests/{id}/reject` | 派单员 | `ORDER_RETURN` | 状态改「已驳回」 |
| `POST /return-requests/{id}/fulfill` | 派单员 | `ORDER_RETURN` | ★ **真的退货**（账本/库存/退现/订单状态） |

⛔ 用户原话：「批发商只是一个申请，**派单员才是实际性的操作**。派单员进行完了之后，
整个才进行库存才会发生一个改变和变动」。所以**前三个端点里一行库存代码都不许有**
（有红线 `_tools/qa/_check_return_request.py` 盯着这一条）。

## 为什么端点按角色分开而不是"一个端点内部判角色"

`_tools/ai/_gen_ai_read_catalog.py` 是从**权限点**反推"谁能读这张表"的；
一个端点同时伺候两个角色，反推出来的角色集合就会多一个（AI 侧跟着获得越权读取能力）。
拆开之后每个端点的角色集合都是确定的，AI 读能力清单自动就是对的。

## ⚠️ 光有权限点**挡不住派单员**（2026-09-22 补）

`require_permission` 里有一句「派单员为最高业务权限……一律放行」（`core/rbac.py`），
所以上面那三个"货主自己那一半"的端点，**派单员实际是能调到的**：
`GET /return-requests/mine` 对他返回 `200 + 空列表`（他名下没有申请）。

实测（本机 2026-09-22，三个角色各打一遍）：

| 角色 | `GET /mine` | `POST /return-requests` |
| --- | --- | --- |
| 货主 | 200（自己的申请） | 400「这不是你的订单」（那不是他的单） |
| 派单员 | **200 空列表** ← 声明说"不可用"，实际通 | 400「这不是你的订单」 |
| 司机 | 403 | 403 |

**不影响任何数与判断**（不泄露、不给错数），但它让
`_tools/ai/_probe_read_roles.py` **永远红着**一条（"声明不可用 / 实际 200"）——
而"永远红的检查 ＝ 没有检查"是这个仓库明确定成最坏的一类。更麻烦的是它埋了个陷阱：
下一个人为了让检查变绿，最省事的做法是把读目录改成"派单员可用"，
那会给派单员的 AI 多出一个**必然没用**的读动作（他从没当过货主，永远答"没有"）。

所以：**三个"货主那一半"的端点一律显式加 `require_roles(UserRole.SHIPPER)`**，
并保留权限点（读能力目录仍从权限点推导，两边从此一致）。
扛这件事的红线是 `_tools/qa/_check_return_request.py` 的 §4c。
"""

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.pagination import finish_page
from app.core.rbac import Permission
from app.database import get_db
from app.deps import CurrentUser, require_permission, require_roles
from app.models import Order, OrderReturnRequest, ReturnRequestStatus, User
from app.models.enums import UserRole
from app.schemas.order import OrderReturnOut
from app.schemas.return_request import (
    ReturnRequestCreateBody,
    ReturnRequestFulfillOut,
    ReturnRequestLineOut,
    ReturnRequestListOut,
    ReturnRequestOut,
    ReturnRequestRejectBody,
)
from app.core import outbox
from app.services import order_return_request as svc
from app.services.order_return import OrderReturnError, ReturnItem

router = APIRouter(prefix="/return-requests", tags=["return-requests"])

#: 中文名在**后端**给出（前端各自映射一套，就会出现"后端加了状态、某个端显示原始码"）。
_STATUS_LABEL = {
    ReturnRequestStatus.PENDING.value: "待派单员处理",
    ReturnRequestStatus.DONE.value: "已办理（退货已完成）",
    ReturnRequestStatus.REJECTED.value: "已驳回",
    ReturnRequestStatus.WITHDRAWN.value: "已撤回",
    # 派单员在订单管理里**直接退了货** → 这张申请自动关闭（2026-09-21 用户拍板）。
    # 中文名与 `DONE` 刻意不同：一个是"照这张申请办的"，一个是"另一条路把事做完了"，
    # 两者的实退数量**不一定**相同（差异写在审计与那条站内信里）。
    ReturnRequestStatus.CLOSED.value: "已关闭（派单员已直接退货）",
}


#: ⚠️ 这里原来的三个 `_bg_notify_*` 助手（通知派单员 / 驳回 / 办理完成）已经**搬进事务发件箱**
#: （整改报告 §10）：事件只带申请编号与金额，处理器按编号重取那一条再推 —— 见 `main.py::_outbox_deliver`。


def _name_map(db: Session, ids: set[int]) -> dict[int, str]:
    """`id → 显示名`。⚠️ `User` 上**没有** `name` 字段（是 `full_name`，空则退回 `phone`）——
       与 `message_center._user_label` 同一条口径，免得同一个人的名字在两处不一样。
    """
    clean = {i for i in ids if i}
    if not clean:
        return {}
    rows = db.execute(
        select(User.id, User.full_name, User.phone).where(User.id.in_(clean))
    ).all()
    return {
        int(r[0]): ((r[1] or "").strip() or (r[2] or "").strip())
        for r in rows
    }


def _order_no_map(db: Session, ids: set[int]) -> dict[int, str]:
    clean = {i for i in ids if i}
    if not clean:
        return {}
    rows = db.execute(select(Order.id, Order.order_no).where(Order.id.in_(clean))).all()
    return {int(r[0]): (r[1] or "") for r in rows}


def _to_out(
    req: OrderReturnRequest,
    *,
    order_no: str,
    shipper_name: str,
    handler_name: str,
) -> ReturnRequestOut:
    return ReturnRequestOut(
        id=req.id,
        order_id=req.order_id,
        order_no=order_no,
        shipper_id=req.shipper_id,
        shipper_name=shipper_name,
        status=req.status,
        status_label=_STATUS_LABEL.get(req.status, req.status),
        note=req.note or "",
        reject_reason=req.reject_reason or "",
        lines=[
            ReturnRequestLineOut(
                order_product_id=ln.order_product_id,
                product_name=ln.product_name,
                quantity=ln.quantity,
            )
            for ln in req.lines
        ],
        created_at=req.created_at,
        handled_at=req.handled_at,
        handled_by=req.handled_by,
        handled_by_name=handler_name,
        source=req.source or "app",
    )


def _build_out(db: Session, reqs: list[OrderReturnRequest]) -> list[ReturnRequestOut]:
    """一次装配一页（名字/单号各一条 IN 查询，与条数无关）。"""
    if not reqs:
        return []
    users = _name_map(db, {r.shipper_id for r in reqs} | {r.handled_by or 0 for r in reqs})
    orders = _order_no_map(db, {r.order_id for r in reqs})
    return [
        _to_out(
            r,
            order_no=orders.get(r.order_id, ""),
            shipper_name=users.get(r.shipper_id, ""),
            handler_name=users.get(r.handled_by or 0, ""),
        )
        for r in reqs
    ]


def _load_request(db: Session, request_id: int, *, lock: bool = False) -> OrderReturnRequest:
    q = select(OrderReturnRequest).where(OrderReturnRequest.id == request_id)
    if lock:
        # 与收款/退货同一条理由：两个派单员同时点「办理」会各自通过"还是待处理"的校验，
        # 两边都去执行退货 —— 数量锁死之后这里的后果是**退两次同样的货**。
        q = q.with_for_update()
    req = db.scalars(q).first()
    if req is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return req


def _load_order_locked(db: Session, order_id: int) -> Order:
    order = db.scalars(
        select(Order)
        .options(selectinload(Order.order_products))
        .where(Order.id == order_id)
        .with_for_update()
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return order


# --------------------------------------------------------------------------- 货主端


#: **货主自己那一半**的三个端点（申请 / 我的申请 / 撤回）都要挂的那道**角色门**。
#:
#: ⚠️ 为什么权限点不够、还要显式卡角色：`require_permission` 对派单员**一律放行**
#:    （`core/rbac.py::role_has_permission` 的头一句），于是派单员实际能调到这三个端点
#:    —— `/mine` 对他返回 200 + 空列表，"声明说不可用、实际通"，`_probe_read_roles.py`
#:    因此永远红着一条（详见模块头那段「光有权限点挡不住派单员」）。
#:
#: ⚠️ 与 `require_permission(Permission.ORDER_RETURN_REQUEST)` **一起用**（不是替换）：
#:    权限点是"申请权在货主那一格"的声明，AI 读能力目录与端点索引都从它推导；
#:    角色门负责把派单员那道超级权限关掉。少任何一半都会分叉。
ShipperOnly = Annotated[User, Depends(require_roles(UserRole.SHIPPER))]


@router.post("", response_model=ReturnRequestOut, status_code=status.HTTP_201_CREATED)
def create_return_request(
    body: ReturnRequestCreateBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_RETURN_REQUEST)),
    _shipper_gate: ShipperOnly = None,  # noqa: RUF013 — FastAPI 依赖，用不到它的值
) -> ReturnRequestOut:
    """**货主申请退货**（数量＝他想退多少，不会真的退）。

    ⛔ 本端点**不写账本、不写库存、不改订单状态** —— 那是派单员办理时的事。
    ⚠️ 取单时就锁住订单行：`pending_for_order` 的"同时只允许一条待处理"是在校验之后写库的，
       两个标签页同时提交会各自通过（各自看不到对方那条），结果一张单挂两张待办申请。
    """
    order = _load_order_locked(db, body.order_id)
    try:
        req = svc.submit(
            db,
            order,
            shipper_id=current.id,
            items=[ReturnItem(order_product_id=i.order_product_id, quantity=i.quantity) for i in body.items],
            note=body.note,
            source="app",
        )
    except svc.ReturnRequestError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    # ⚠️ 事件与这次申请**同一个事务**（整改报告 §10）。旧注释写的是"通知放在提交之后"
    #    （当时的顾虑是"站内信落库失败不该把用户的申请一起回滚掉"）—— 发件箱把这条顾虑解掉了：
    #    入队的只是一行事件（同一个库、同一个事务，没有外部 I/O），真正的站内信由 worker 事后去写，
    #    它失败也只影响那条事件（会重试并留 last_error），不会回滚用户的申请。
    outbox.enqueue(db, "returns.requested", {"request_id": req.id})
    db.commit()
    req = _load_request(db, req.id)
    return _build_out(db, [req])[0]


@router.get("/mine", response_model=ReturnRequestListOut)
def list_my_return_requests(
    response: Response,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_RETURN_REQUEST)),
    _shipper_gate: ShipperOnly = None,  # noqa: RUF013 — FastAPI 依赖，用不到它的值
    order_id: int | None = Query(None, description="只看这一张单的申请"),
    # ⛔ `?status=` 的取值必须**闭集**（2026-09-24 第 27 轮；第 25 轮 09 区 ②）：
    #    原来声明成自由字符串，而过滤只判 `== "pending"` —— 于是模型传 `status=rejected`
    #    （或 done/closed/withdrawn 里任何一个写错的词）时**既不报错也不过滤**：
    #    接口回 200、把**全部**申请（含 done/rejected/withdrawn）当成"被驳回的"喂给模型，
    #    实测 `?status=rejected` 与 `?status=all` 逐字相同（13 条）。用户听到的是一句
    #    "他这些申请都被驳回了" —— 静默错答里最贵的那种（没有任何一层会报错）。
    #    改成 Literal 之后：① 别的取值 FastAPI 直接 422；② **顺带**进 AI 读目录的 enum
    #    （生成器只认 `Literal[...]`，`pattern=` 它读不出来）→ 模型知道合法取值。
    status_filter: Literal["all", "pending", "done", "rejected", "withdrawn"] = Query(
        "all", alias="status", description="all / pending / done / rejected / withdrawn"
    ),
    limit: int = Query(200, ge=1, le=500),
) -> ReturnRequestListOut:
    """**我的**退货申请（货主端列表打标记、看驳回理由、撤回都读它）。

    ⚠️ 一律按 `shipper_id == 当前登录人` 过滤，⛔ 不接受任何"看别人的"参数。
    ⚠️ 取数多取一行交给 `finish_page`（`X-Truncated`）——**"有 limit 却不说"是很贵的一类错**：
       货主看到 200 条会以为"我一共提过这么多"，而真值可能是 260（`core/pagination.py` 开头那张表）。
    """
    q = select(OrderReturnRequest).where(
        OrderReturnRequest.shipper_id == current.id,
        OrderReturnRequest.is_deleted.is_(False),
    )
    if order_id is not None:
        q = q.where(OrderReturnRequest.order_id == order_id)
    if status_filter != "all":
        q = q.where(OrderReturnRequest.status == status_filter)
    rows = list(
        db.scalars(q.order_by(OrderReturnRequest.id.desc()).limit(limit + 1)).unique().all()
    )
    rows = finish_page(rows, limit, response)
    pending = db.scalar(
        select(func.count(OrderReturnRequest.id)).where(
            OrderReturnRequest.shipper_id == current.id,
            OrderReturnRequest.status == ReturnRequestStatus.PENDING.value,
            OrderReturnRequest.is_deleted.is_(False),
        )
    )
    return ReturnRequestListOut(items=_build_out(db, rows), pending_count=int(pending or 0))


@router.post("/{request_id}/withdraw", response_model=ReturnRequestOut)
def withdraw_return_request(
    request_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_RETURN_REQUEST)),
    _shipper_gate: ShipperOnly = None,  # noqa: RUF013 — FastAPI 依赖，用不到它的值
) -> ReturnRequestOut:
    """货主撤回自己的申请（**不是删除**：记录留着，派单员看得到"他提过又撤了"）。"""
    req = _load_request(db, request_id, lock=True)
    try:
        svc.withdraw(db, req, shipper_id=current.id)
    except svc.ReturnRequestError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.commit()
    return _build_out(db, [_load_request(db, request_id)])[0]


# --------------------------------------------------------------------------- 派单端


@router.get("", response_model=ReturnRequestListOut)
def list_return_requests(
    response: Response,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_RETURN)),
    order_id: int | None = Query(None),
    # ⛔ 与 `/mine` 同一条判据（同一个 `?status=` 的两条路必须双门一致）：
    #    默认仍是 `pending`，但取值**闭集** —— 原来自由字符串 + 只判 pending 的写法让
    #    `status=rejected` 静默返回**全部**（第 25 轮 09 区 ② 实测：与 `status=all` 逐字相同）。
    status_filter: Literal["all", "pending", "done", "rejected", "withdrawn"] = Query(
        "pending", alias="status", description="all / pending / done / rejected / withdrawn"
    ),
    limit: int = Query(200, ge=1, le=500),
) -> ReturnRequestListOut:
    """**派单员待办**：谁申请了退货、要退哪几样、各几件、什么时候提的。

    默认只给「待处理」——这一页的用途就是"还有几张没办"；
    要看历史（谁被驳回过）传 `status=all`，或点名某一档（`done`/`rejected`/`withdrawn`）。
    """
    q = select(OrderReturnRequest).where(OrderReturnRequest.is_deleted.is_(False))
    if order_id is not None:
        q = q.where(OrderReturnRequest.order_id == order_id)
    if status_filter != "all":
        q = q.where(OrderReturnRequest.status == status_filter)
    rows = list(
        db.scalars(
            q.order_by(
                # 待处理的一律排在前面，其余按时间倒序（派单员第一眼要看到"还有哪几张没办"）
                (OrderReturnRequest.status != ReturnRequestStatus.PENDING.value),
                OrderReturnRequest.id.desc(),
            ).limit(limit + 1)
        )
        .unique()
        .all()
    )
    rows = finish_page(rows, limit, response)
    pending = db.scalar(
        select(func.count(OrderReturnRequest.id)).where(
            OrderReturnRequest.status == ReturnRequestStatus.PENDING.value,
            OrderReturnRequest.is_deleted.is_(False),
        )
    )
    return ReturnRequestListOut(items=_build_out(db, rows), pending_count=int(pending or 0))


@router.post("/{request_id}/reject", response_model=ReturnRequestOut)
def reject_return_request(
    request_id: int,
    body: ReturnRequestRejectBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_RETURN)),
) -> ReturnRequestOut:
    """派单员驳回（**必带理由**：这是货主唯一能拿到的答复）。"""
    req = _load_request(db, request_id, lock=True)
    try:
        svc.reject(db, req, dispatcher_id=current.id, reason=body.reason)
    except svc.ReturnRequestError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    outbox.enqueue(db, "returns.rejected", {"request_id": request_id})
    db.commit()
    return _build_out(db, [_load_request(db, request_id)])[0]


@router.post("/{request_id}/fulfill", response_model=ReturnRequestFulfillOut)
def fulfill_return_request(
    request_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_RETURN)),
) -> ReturnRequestFulfillOut:
    """**派单员照这张申请实际退货** —— 货主申请的终点，也是库存/账本唯一会发生变动的时刻。

    ⛔ 数量取自申请单（用户拍板「锁死＝申请多少就退多少」），**请求体里没有数量参数**：
       多一个参数就多一条"派单员改了数量"的路，而这条流程的产出物
       恰恰是"谁申请了什么、最后办成了什么"这两句话必须对得上。
    ⛔ 执行的唯一入口是 `services/order_return.py::return_order`（红冲/回补/退现/状态都在里面）。
       出错一律 `db.rollback()`：**申请必须仍然是「待处理」** ——
       把它标成"已办"而实际没退成，是最坏的一种结果（货主以为退了，库存没回来，没人再去看它）。
    """
    req = _load_request(db, request_id, lock=True)
    order = _load_order_locked(db, req.order_id)
    try:
        result = svc.fulfill(db, req, dispatcher_id=current.id, order=order)
    except (svc.ReturnRequestError, OrderReturnError) as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    outbox.enqueue(
        db,
        "returns.done",
        {
            "request_id": request_id,
            "returned_amount": str(result.returned.returned_amount),
            "refund_amount": str(result.returned.refund_amount),
            "fully_returned": bool(result.returned.fully_returned),
        },
    )
    db.commit()
    fresh = _load_request(db, request_id)
    return ReturnRequestFulfillOut(
        request=_build_out(db, [fresh])[0],
        returned=OrderReturnOut(
            order_no=result.returned.order_no,
            returned_amount=result.returned.returned_amount,
            refund_amount=result.returned.refund_amount,
            fully_returned=result.returned.fully_returned,
            restocked_lines=result.returned.restocked_lines,
            warnings=result.returned.warnings,
            # ⚠️ 不回整单对象：这一页的客户端本来就要刷新订单列表（账、库存、状态都变了），
            #    再塞一份 `OrderOut` 进响应只会让"哪一份是新的"变成一个问题。
            order=None,
        ),
    )


__all__ = ["router"]
