"""货主申请退货 → 派单员实际执行（2026-09-21 用户要求）。

## 这条流程的形状（谁在什么时刻做什么）

```
货主（批发商/普通货主）            派单员
─────────────────────────        ─────────────────────────────
在这张单上点「申请退货」             │   ← 只写 order_return_requests，**什么都不动**
   ↓  提交（数量锁死）               │
                            ──通知──→ 站内信「退货申请待处理」
                                     ↓
                              看申请 → 办理 or 驳回
                                     ↓
                    DONE ←── `services/order_return.py::return_order`
                              ★ 账本红冲 / 库存回补 / 退现 / 订单状态 **全在这一刻**
                    REJECTED ←── 必带理由（货主要知道凭什么被拒）
```

## 三条不变量（改这个文件前先读）

1. **申请阶段一分钱不动、一件货不动**：`submit` 只写两张新表 + 一条审计日志。
   用户原话：「派单员进行完了之后，整个才进行库存才会发生一个改变和变动」。
2. **执行只有一条路径**：`fulfill` **必须**调 `order_return.return_order()`，
   ⛔ 不许在这里自己写红冲/回补/退现 —— 钱的实现有两处，就一定会有一天两边对不上，
   而且**谁都不报错**（这个项目最贵的一类错）。
3. **数量锁死**（用户拍板）：`fulfill` 用的是申请单上那几行数量，**不接受调用方改数量**。
   申请之后余量变了（被别的退货/货损占掉）→ 直接拒绝，让派单员去驳回，
   而不是"按现在还剩多少悄悄退一点"（那就成了账上退的和货主申请的不是一回事）。
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.models import (
    Order,
    OrderProduct,
    OrderReturnRequest,
    OrderReturnRequestLine,
    OperationAction,
    OrderStatus,
    ReturnRequestStatus,
)
from app.services.operation_log_service import write_log
from app.services.money_contract import max_returnable, return_order
from app.services.order_return import (
    OrderReturnError,
    ReturnItem,
    ReturnResult,
)


class ReturnRequestError(ValueError):
    """申请/撤回/驳回被业务规则拒绝（接口层翻成 400）。"""


#: 一张单**同时只允许一条**待处理的申请。为什么不做"多条排队"：
#: 派单员看到三张待办会以为是三次退货，实际它们互斥（退了第一张，第二张的货已经没了）——
#: 让他去逐张驳回，是把系统的规则漏洞变成他的家务活。要改数量就撤回重提。
PENDING = ReturnRequestStatus.PENDING.value


def pending_for_order(db: Session, order_id: int) -> OrderReturnRequest | None:
    """这张单当前待处理的申请（没有则 None）。"""
    return db.scalars(
        select(OrderReturnRequest).where(
            OrderReturnRequest.order_id == order_id,
            OrderReturnRequest.status == PENDING,
            OrderReturnRequest.is_deleted.is_(False),
        )
    ).first()


def _check_operator_is_owner(req: OrderReturnRequest, shipper_id: int) -> None:
    if req.shipper_id != shipper_id:
        # 与"不是自己的单"同一个答复口径：不告诉对方"这张申请存在、但不是你的"
        raise ReturnRequestError("这张退货申请不是你的")


def _check_pending(req: OrderReturnRequest, what: str) -> None:
    if req.is_deleted:
        raise ReturnRequestError(f"这张退货申请已被删除，不能{what}。请先恢复它。")
    if req.status != PENDING:
        label = {
            ReturnRequestStatus.DONE.value: "已经办完了",
            ReturnRequestStatus.REJECTED.value: "已经被驳回了",
            # ⚠️ 措辞要**对两边都成立**：这句话既会回给货主、也会回给派单员
            #    （他点了一张货主已经撤回的申请）。写成"被你自己撤回"在派单员那边是错的，
            #    而他会据此以为是自己点错了 —— 于是反复重试。
            ReturnRequestStatus.WITHDRAWN.value: "已经被申请人撤回了",
            ReturnRequestStatus.CLOSED.value: "已经由派单员直接退了货（自动关闭）",
        }.get(req.status, f"现在不是待处理状态（{req.status}）")
        raise ReturnRequestError(f"这张退货申请{label}，不能{what}")


def _validate_lines(order: Order, items: list[ReturnItem]) -> dict[int, OrderProduct]:
    """逐行校验（与 `return_order` 同一套判据与同一套话术，见下方注释）。"""
    if not items:
        raise ReturnRequestError("请至少勾选一个要退的商品")
    ops = {op.id: op for op in order.order_products}
    seen: set[int] = set()
    for it in items:
        if it.order_product_id in seen:
            raise ReturnRequestError("同一行重复勾选了，请刷新后重试")
        seen.add(it.order_product_id)
        op = ops.get(it.order_product_id)
        if op is None:
            raise ReturnRequestError("勾选的商品不在这一单里，请刷新后重试")
        if it.quantity <= 0:
            raise ReturnRequestError(f"「{op.product_name_snapshot}」的退货数量要大于 0")
        cap = max_returnable(op)
        if it.quantity > cap:
            extra = "（这一行的货损已经计过损失，那部分不能退）" if (op.damage_quantity or 0) > 0 else ""
            raise ReturnRequestError(
                f"「{op.product_name_snapshot}」最多只能退 {cap} {op.unit_snapshot or '件'}"
                f"（下单 {op.quantity}、已退 {op.returned_quantity or 0}），你填了 {it.quantity}{extra}"
            )
    return ops


def submit(
    db: Session,
    order: Order,
    *,
    shipper_id: int,
    items: list[ReturnItem],
    note: str = "",
    source: str = "app",
) -> OrderReturnRequest:
    """货主提交一张退货申请（调用方负责 `db.commit()`）。

    ⛔ 本函数**只写 `order_return_requests` / `order_return_request_lines` 两张表 + 一条审计日志**。
       不写账本、不写库存、不改订单行、不改订单状态 —— 见模块头「三条不变量」第 1 条。
       仓库里有一条红线专门盯着这件事（`_tools/qa/_check_return_request.py`）：
       一旦有人图省事在这里调了 `return_order`，"申请即退货"会**静默**复活。
    """
    if order.deleted_at is not None:
        raise ReturnRequestError("这张单在回收站里（已删除），不能申请退货。请先恢复它。")
    if order.shipper_id is None or order.shipper_id != shipper_id:
        raise ReturnRequestError("这不是你的订单")
    if order.status != OrderStatus.DELIVERED:
        raise ReturnRequestError(
            "只有「已送达」的订单可以申请退货"
            f"（这张单现在是「{order.status.value if order.status else '—'}」）。"
            "货还没送到的单请用「撤销」。"
        )
    if all(max_returnable(op) == 0 for op in order.order_products):
        raise ReturnRequestError("这张单没有可申请退货的商品了（已经全退完，或者剩下的都是货损的）")

    _validate_lines(order, items)

    existed = pending_for_order(db, order.id)
    if existed is not None:
        got = "、".join(f"{ln.product_name}×{ln.quantity}" for ln in existed.lines) or "（明细为空）"
        raise ReturnRequestError(
            f"这张单已经有一张待处理的退货申请了（{got}），"
            "派单员还没处理。要改就先把那一张撤回，再重新申请。"
        )

    req = OrderReturnRequest(
        order_id=order.id,
        shipper_id=shipper_id,
        status=PENDING,
        note=(note or "").strip(),
        source=source,
    )
    db.add(req)
    db.flush()
    ops = {op.id: op for op in order.order_products}
    for it in items:
        db.add(
            OrderReturnRequestLine(
                request_id=req.id,
                order_product_id=it.order_product_id,
                # 存快照：订单商品行是物理增删的，事后可能已经不在了
                product_name=ops[it.order_product_id].product_name_snapshot,
                quantity=it.quantity,
            )
        )
    db.flush()

    parts = "、".join(f"{ops[i.order_product_id].product_name_snapshot}×{i.quantity}" for i in items)
    write_log(
        db,
        operator_id=shipper_id,
        order_id=order.id,
        action=OperationAction.ORDER_RETURN_REQUEST,
        change_payload={
            "申请单号": str(req.id),
            "申请退货": parts,
            "备注": req.note,
            "来源": source,
        },
    )
    return req


def withdraw(db: Session, req: OrderReturnRequest, *, shipper_id: int) -> None:
    """货主撤回自己的申请（调用方负责 `db.commit()`）。

    ⚠️ 撤回**不是删除**（见 `ReturnRequestStatus` 的注释）：记录留着、状态变掉，
       派单员那边看得到"他提过又撤了"。想彻底消失走软删 + 恢复。
    """
    _check_operator_is_owner(req, shipper_id)
    _check_pending(req, "撤回")
    req.status = ReturnRequestStatus.WITHDRAWN.value
    write_log(
        db,
        operator_id=shipper_id,
        order_id=req.order_id,
        action=OperationAction.ORDER_RETURN_REQUEST_WITHDRAW,
        change_payload={"申请单号": str(req.id), "撤回原因": "货主自己撤回"},
    )


def reject(
    db: Session, req: OrderReturnRequest, *, dispatcher_id: int, reason: str
) -> None:
    """派单员驳回，**必带理由**（调用方负责 `db.commit()`）。

    为什么理由必填而不是选填：这是货主唯一能拿到的答复。不填的后果是他只能反复重提，
    而派单员每次都要重新看一遍（这条流程在真实门店里每天都在发生，不是边角场景）。
    """
    text = (reason or "").strip()
    if not text:
        raise ReturnRequestError("驳回要写原因（货主要看到凭什么被驳回）")
    _check_pending(req, "驳回")
    req.status = ReturnRequestStatus.REJECTED.value
    req.reject_reason = text[:256]
    req.handled_by = dispatcher_id
    req.handled_at = utc_now_naive()
    write_log(
        db,
        operator_id=dispatcher_id,
        order_id=req.order_id,
        action=OperationAction.ORDER_RETURN_REQUEST_REJECT,
        change_payload={"申请单号": str(req.id), "驳回原因": req.reject_reason},
    )


@dataclass
class FulfillResult:
    """办理结果：申请单 + 那次真实退货的回参（端点两个都要回给客户端）。"""

    request: OrderReturnRequest
    returned: ReturnResult


def fulfill(db: Session, req: OrderReturnRequest, *, dispatcher_id: int, order: Order) -> FulfillResult:
    """派单员**照这张申请实际退货**（调用方负责 `db.commit()`）。

    ⛔ 数量取自申请单，**不接受调用方传数量**（用户拍板「锁死＝申请多少就退多少」）。
    ⛔ 执行的唯一入口是 `return_order()`：账本红冲、库存回补、退现、订单状态全在它里面。
       ⚠️ 它抛的 `OrderReturnError` 在这里**原样往上抛**（端点统一翻 400）——
          包括"这张单已经不是已送达了""这一行最多只能退 N 件"这些**必须让派单员看到原文**的话，
          换成一句笼统的"办理失败"就等于让他去猜（而他会猜"系统坏了"，然后去手工改库存）。
    """
    _check_pending(req, "办理")
    if order.deleted_at is not None:
        raise ReturnRequestError("这张单在回收站里（已删除），不能退货。请先恢复它，或驳回这张申请。")
    if order.status != OrderStatus.DELIVERED:
        raise ReturnRequestError(
            "这张单现在不是「已送达」"
            f"（是「{order.status.value if order.status else '—'}」），没法按这张申请退货。"
            "请驳回它，并在原因里写清楚。"
        )

    items = [ReturnItem(order_product_id=ln.order_product_id, quantity=ln.quantity) for ln in req.lines]
    # 申请之后余量可能变小（别的退货先办了 / 司机补报了货损）：
    # 这里**必须**重算一次 —— 拿申请时的判断直接执行，会退出去超过下单量的货。
    ops = {op.id: op for op in order.order_products}
    for ln in req.lines:
        op = ops.get(ln.order_product_id)
        if op is None:
            raise ReturnRequestError(
                f"申请里的「{ln.product_name}」已经不在这一单里了（订单被改过）。"
                "请驳回这张申请，让货主重新提。"
            )
        cap = max_returnable(op)
        if ln.quantity > cap:
            raise ReturnRequestError(
                f"申请里的「{ln.product_name}」要退 {ln.quantity} 件，"
                f"但现在只剩 {cap} 件可退（可能已经被别的退货或货损占掉了）。"
                "请驳回这张申请，让货主重新提。"
            )

    note = f"按退货申请 #{req.id} 办理" + (f"：{req.note}" if req.note else "")
    returned = return_order(db, order, items, note=note, operator_id=dispatcher_id)

    req.status = ReturnRequestStatus.DONE.value
    req.handled_by = dispatcher_id
    req.handled_at = utc_now_naive()
    return FulfillResult(request=req, returned=returned)


def close_by_direct_return(
    db: Session,
    order: Order,
    *,
    dispatcher_id: int,
    items: list[ReturnItem],
) -> tuple[OrderReturnRequest, str] | None:
    """派单员**走订单管理那条直连退货**时，把这张单上待处理的申请自动关掉（调用方负责 commit）。

    用户 2026-09-21 拍板：「把规则改成派单员退货之后，**自动取消申请**，然后它对应的数据发生改变，
    状态变成已退货多少多少」。

    ### 为什么是"已关闭"而不是"已办理"
    两条路的**事实不一样**：`fulfill` 的数量**只能**来自申请单；而直连退货是派单员自己勾的 ——
    他可能退 3 件、申请写的是 2 件。标成"已办理"就等于替他说"两边一致"，事后谁都查不出来。
    所以：申请转 `CLOSED`（中文「已关闭（派单员已直接退货）」），
    并把**申请了什么 / 实退什么**逐行对照写进审计与站内信 —— 差异一眼可见，谁都不许盖掉它。

    ### 「退了多少」只有一处口径
    件数/金额一律以**订单与账本**为准（`return_order` 写下去的那一份）。
    ⛔ 本函数不复制、不重算那些数，只记录"这张申请为什么没被办理就结束了"。

    @return `(申请单, 给货主看的对照说明)`；这张单没有待处理申请时返回 None。
    """
    req = pending_for_order(db, order.id)
    if req is None:
        return None

    ops = {op.id: op for op in order.order_products}
    applied = {ln.order_product_id: (ln.product_name, ln.quantity) for ln in req.lines}
    actual = {it.order_product_id: it.quantity for it in items}

    parts_applied = "、".join(f"{n}×{q}" for n, q in applied.values()) or "（未填明细）"
    parts_actual = "、".join(
        f"{ops[i].product_name_snapshot if i in ops else '（已不在单上）'}×{q}"
        for i, q in actual.items()
    ) or "（未填明细）"
    same = {k: v[1] for k, v in applied.items()} == actual
    diff = (
        "与申请的一致"
        if same
        else f"⚠️ 与申请的不一致：申请的是 {parts_applied}，这次实退 {parts_actual}"
    )

    req.status = ReturnRequestStatus.CLOSED.value
    req.handled_by = dispatcher_id
    req.handled_at = utc_now_naive()
    write_log(
        db,
        operator_id=dispatcher_id,
        order_id=order.id,
        action=OperationAction.ORDER_RETURN_REQUEST_CLOSE,
        change_payload={
            "申请单号": str(req.id),
            "申请退货": parts_applied,
            "实际退货": parts_actual,
            "一致": same,
            "说明": "派单员在订单管理里直接退了货，这张申请自动关闭",
        },
    )
    return req, f"申请的是 {parts_applied}，实退 {parts_actual}（{diff}）"


__all__ = [
    "FulfillResult",
    "OrderReturnError",
    "PENDING",
    "ReturnRequestError",
    "close_by_direct_return",
    "fulfill",
    "pending_for_order",
    "reject",
    "submit",
    "withdraw",
]
