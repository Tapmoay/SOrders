"""派单与定价（批量派单 / 派单 / 撤回 / 拆单 / 定价 / 改运费）（orders_assignment）—— 2026-09-24 整改阶段 4 **纯搬迁**的产物。

从 `api/v1/orders.py` 原样搬来的 7 个函数（_template_category_ids,batch_assign_orders,price_freight,assign_order,split_order_endpoint,update_order_freight,recall_order）。
除代码组织外**一个字没改** —— URL / 入参 / 出参 / 权限 / 状态机 / 数据库全不变；
证据：`_tools/qa/_api_contract_snapshot.py --diff <搬之前> <搬之后>` 契约零差异。

⚠️ 本模块**自己声明** `router`：按文件解析的 AST 工具（端点索引 / AI 能力表）靠这一行算 URL 前缀。
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.core.rbac import Permission, user_role_key
from app.database import get_db
from app.deps import require_permission
from app.models import Order, User
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.models import (
    DriverBillingRuleTemplate,
    FreightCategory,
    FreightTemplate,
    FreightTemplateCategory,
    ShipperAddress,
)
from app.schemas.order import (
    OrderFreightPriceBody,
    BatchAssignResultItem,
    OrderAssignBody,
    OrderFreightBody,
    OrderSplitBody,
    OrderBatchAssignBody,
    OrderBatchAssignOut,
    OrderOut,
    OrderRecallBody,
)
from app.services.operation_log_service import write_log
from app.services.order_flow import split_order
from app.services.order_flow import assign_driver, lock_order_row, recall_dispatch
from app.services.accounting_service import BillAlreadySettledError, resync_open_piece_bill
from app.services.order_response import enrich_order_out, load_order_for_response
from app.services import usage_service
from app.core import outbox

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/batch-assign", response_model=OrderBatchAssignOut)
def batch_assign_orders(
    body: OrderBatchAssignBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> OrderBatchAssignOut:
    driver = db.get(User, body.driver_id)
    if driver is None:
        raise HTTPException(status_code=400, detail="未找到该司机")
    if user_role_key(driver) != UserRole.DRIVER.value:
        raise HTTPException(status_code=400, detail="派单目标须为司机账号")
    results: list[BatchAssignResultItem] = []
    seen: set[int] = set()
    for oid in body.order_ids:
        if oid in seen:
            continue
        seen.add(oid)
        try:
            order = db.scalars(
                select(Order).options(selectinload(Order.order_products)).where(Order.id == oid)
            ).first()
            if order is None:
                results.append(BatchAssignResultItem(order_id=oid, success=False, detail="未找到订单"))
                continue
            assign_driver(db, order, driver, current, body.internal_note)
            if body.collect_cash is not None:
                order.collect_cash = body.collect_cash
            # ⚠️ 派单推送走**事务发件箱**（整改报告 §10）：事件与这次 commit **同一个事务** ——
            #    以前是 commit 之后再 add_task，后台任务挂了这条推送就永远没了，而库里一切正常。
            outbox.enqueue(db, "orders.assigned", {"driver_id": body.driver_id, "order_id": oid})
            # 池变化跟着**这一单**的事务走（原来在循环之后补一次 —— 那时已经出了事务，丢了就没了）
            outbox.enqueue(db, "orders.pending_pool_changed", {})
            db.commit()
            results.append(BatchAssignResultItem(order_id=oid, success=True, detail=None))
        except ValueError as e:
            db.rollback()
            results.append(BatchAssignResultItem(order_id=oid, success=False, detail=str(e)))
    return OrderBatchAssignOut(results=results)


@router.post("/{order_id}/price-freight", response_model=OrderOut)
def price_freight(
    order_id: int,
    body: OrderFreightPriceBody,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> OrderOut:
    """派单员**手动定价**：没匹配到价目的单，由人给一个数。

    用户 2026-09-21：「这个定价完之后，同理，他会**新增对应的地点/路线和对应的运费模板**，
    并且放到那个分类当中去，就是绑定那个分类」——所以带上 `save_template` 时，
    这一次定价会**沉淀**成：①（必要时）一条线路；② 一条绑了这个分类的价目。

    ⛔ 沉淀**只新建/更新价目**，绝不动别的单：改价目只影响"以后派的单"
    （已经派出去的单记的是当时的运费，不是引用）。
    """
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # ⚠️ 先锁再判（2026-09-23 第 6 轮）：手边这份 order 可能是**旧状态**，
    #    而下面那道门 + 写运费是"读状态 → 判断 → 写"，并发下会看运气（同 `order_products`）。
    order = lock_order_row(db, order)
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="这一单已经撤销了，不用再定价")
    # ⛔ **已送达/已退货的单只能"补上还没定的那个数"，不能再改价**（2026-09-23 第 6 轮）：
    #    这条口径本来就在隔壁那个端点（`update_order_freight`：「已送达/已撤销/已退货后锁定 ——
    #    事后改运费不会动账单（改了个寂寞），而界面上会显示一个与账单不一致的数」），
    #    但**同一个字段有两个写入端点、两套状态规则** → 那道锁在这里被绕过去了。
    #    而"忘了定价就送达"是真实顺序（送达那一刻 `post_delivery_accounting` 已经按当时的运费
    #    生成了一张应付明细），所以这条路上**必须留一个口子**——只是这个口子只许**填空白**，
    #    不许改已经定过的数；填完之后那张还没结算的明细由 `resync_open_piece_bill` 跟着改。
    finished = order.status in (OrderStatus.DELIVERED, OrderStatus.RETURNED)
    if finished and order.freight_fee is not None:
        raise HTTPException(
            status_code=400,
            detail="这一单已经送达/已退货，而且已经定过运费了。已送达的单运费是锁定的"
                   "（事后改运费不会动司机账单，只会在两个页面上显示两个数）；"
                   "确实要改就先处理司机结算那边。",
        )

    before = {
        "freight_fee": str(order.freight_fee) if order.freight_fee is not None else None,
        "freight_category_id": order.freight_category_id,
        "freight_category": order.freight_category or "",
    }
    # 分类：给了就用它（并把名字快照写下来），没给就清空（"这一类不适用"）
    cat_name = ""
    if body.category_id is not None:
        cat = db.get(FreightCategory, body.category_id)
        if cat is None:
            raise HTTPException(status_code=400, detail="这个运费分类不存在")
        cat_name = cat.name
    order.freight_fee = body.freight_fee
    order.freight_category_id = body.category_id
    order.freight_category = cat_name

    saved: dict = {}
    if body.save_template:
        # ① 路线：优先用现成的一条（同一终点、且是当前派单员的），没有就建一条
        route = None
        if body.save_template:
            route = db.scalars(
                select(ShipperAddress).where(
                    ShipperAddress.shipper_id == current.id,
                    ShipperAddress.detail_address == (order.address_detail or "").strip(),
                    ShipperAddress.is_deleted.is_(False),
                )
            ).first()
        if route is None:
            route = ShipperAddress(
                shipper_id=current.id,
                receiver_name=(order.contact_dongjia_name or "").strip()[:64],
                phone=(order.contact_dongjia_phone or "").strip()[:32],
                detail_address=(order.address_detail or "").strip()[:512],
                remark="由手动定价自动沉淀",
            )
            db.add(route)
            db.flush()
            saved["route_created"] = route.id
        # ② 价目：这条路线上"同一套分类"已经有一条就改价，否则新建
        want_cats = {body.category_id} if body.category_id is not None else set()
        existing = None
        for t in db.scalars(
            select(FreightTemplate).where(
                FreightTemplate.route_id == route.id,
                FreightTemplate.is_deleted.is_(False),
            )
        ).all():
            mine = set(_template_category_ids(db, t.id))
            if mine == want_cats:
                existing = t
                break
        if existing is not None:
            existing.fee = body.freight_fee
            if body.price_name.strip():
                existing.price_name = body.price_name.strip()[:32]
            saved["template_updated"] = existing.id
            tmpl = existing
        else:
            tmpl = FreightTemplate(
                name=(body.template_name.strip() or (route.detail_address or "手动定价")[:120]),
                route_id=route.id,
                from_place=(route.origin_address or "").strip()[:128],
                to_place=(route.detail_address or "").strip()[:128],
                price_name=body.price_name.strip()[:32],
                fee=body.freight_fee,
                remark="由手动定价自动沉淀",
                created_by=current.id,
            )
            db.add(tmpl)
            db.flush()
            saved["template_created"] = tmpl.id
        if body.category_id is not None:
            db.add(FreightTemplateCategory(template_id=tmpl.id, category_id=body.category_id))
        # ⛔ 价目**不绑司机**（2026-09-21 用户：「运费模板不会去匹配车型也不会匹配司机……
        #    这一目录就归这个计费规则」）。所以"下次自动带价"要落到**规则**上：
        #    这一单的司机有规则 → 把新价目**勾进他的规则**（没有就如实说，不偷偷造规则）。
        driver = db.get(User, order.driver_id) if order.driver_id is not None else None
        rule_id = getattr(driver, "driver_rule_id", None) if driver is not None else None
        if rule_id is not None:
            linked = db.scalars(
                select(DriverBillingRuleTemplate).where(
                    DriverBillingRuleTemplate.rule_id == int(rule_id),
                    DriverBillingRuleTemplate.template_id == tmpl.id,
                )
            ).first()
            if linked is None:
                db.add(DriverBillingRuleTemplate(rule_id=int(rule_id), template_id=tmpl.id))
                saved["rule_linked"] = int(rule_id)
        else:
            saved["rule_not_linked"] = "这一单的司机还没挂计费规则，价目已存好但要有人在他的规则里勾上才会自动带价"
        db.flush()

    # ⚠️ 送达之后才补上运费 → 那张**还没结算**的司机应付明细必须跟着改（2026-09-23 第 6 轮，
    #    实测分叉：明细 300 而结算页/绩效页按新运费重算成 350，两个数都不报错）。
    #    已进过结算单的（SETTLED）→ 拒绝这次定价：钱已经定死，改了只会三处对不上。
    bill_resync: dict | None = None
    if order.status == OrderStatus.DELIVERED:
        try:
            bill_resync = resync_open_piece_bill(db, order, current.id)
        except BillAlreadySettledError as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e)) from e
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_FREIGHT_PRICE,
        change_payload={
            "before": before,
            "after": {
                "freight_fee": str(order.freight_fee),
                "freight_category_id": order.freight_category_id,
                "freight_category": order.freight_category or "",
            },
            "saved": saved,
            # 有它才能回答"这张账单的金额为什么变了"（明细行本身不另写一条日志，理由见
            # `resync_open_piece_bill` 的说明）
            **({"driver_bill": bill_resync} if bill_resync else {}),
        },
    )
    db.commit()

    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/assign", response_model=OrderOut)
def assign_order(
    order_id: int,
    body: OrderAssignBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> OrderOut:
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    driver = db.get(User, body.driver_id)
    if driver is None:
        raise HTTPException(status_code=400, detail="未找到该司机")
    try:
        # 逐单覆盖值（派单员对这一单单独定的金额/比例）跟着一起进 assign_driver——
        # 它与模式快照、规则快照是**同一件事的三个字段**，分开写会出现半截状态。
        assign_driver(
            db,
            order,
            driver,
            current,
            body.internal_note,
            piece_override=body.driver_piece_amount,
            rate_override=body.driver_commission_rate,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # ⛔ **没传运费 ≠ 把运费清空**（2026-09-19 审计 H3，高）：
    #    这里原来是无条件 `order.freight_fee = body.freight_fee`，而 `OrderAssignBody.freight_fee`
    #    的缺省是 `None` —— 于是"派单时没填运费"会把订单上**原有的运费清成 NULL**：
    #      · 司机计费规则为空时，司机应得 = `freight_fee`（`driver_pay` 的 PIECE 分支）→ **¥0.00**；
    #      · 而 `post_delivery_accounting` 里 `if pay.total <= 0: return None` →
    #        **连账单都不生成、不报错、不留痕** —— 司机这一趟白跑，账面上查不到任何异常。
    #    老 H5 的单条派单弹层没有运费输入框（批量派单那条路径不碰 freight_fee）→ 同一屏两个按钮
    #    两个结果：单条派单 = 司机拿 0 元，批量派单 = 运费还在。本机旁证：132 张 `freight_fee`
    #    为 NULL 的已送达单，`driver_bills` **0 条**。
    #    口径与紧邻的 `collect_cash` 一致（它有 `is not None` 守卫）：**没传就是不改**。
    #    要真的清掉运费得显式传一个值（现在不允许传 null —— 清运费属于改单，走订单编辑）。
    if body.freight_fee is not None:
        order.freight_fee = body.freight_fee
    if body.collect_cash is not None:
        order.collect_cash = body.collect_cash
    # 派单记一次「这个派单员常用这位司机」（2026-09-22 统一规则：挑人的列表也按常用度排）。
    # ⚠️ 记在**派单员**名下（`current`）：常用度是"**我**挑谁挑得多"，与司机本人的行为无关。
    usage_service.record_usage(db, user=current, kind=usage_service.KIND_USER, target_id=body.driver_id)
    # ⚠️ 派单推送走**事务发件箱**（整改报告 §10）：与下面这次 commit 同一个事务。
    #    题外话：这里**刻意不去重**（不传 dedupe_key）—— 派单是"再派一次就该再响一次"，
    #    而重复投递由客户端兜着（App 侧按 order_id 有 60 秒去重窗口，见 core/NewOrderAlert.kt）。
    outbox.enqueue(db, "orders.assigned", {"driver_id": body.driver_id, "order_id": order.id})
    outbox.enqueue(db, "orders.pending_pool_changed", {})
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/split", response_model=list[OrderOut])
def split_order_endpoint(
    order_id: int,
    body: OrderSplitBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> list[OrderOut]:
    """把待派单拆分为 N 个子单（按比例拆分件数），分别派单。"""
    order = db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    try:
        created = split_order(db, order, body.parts, current)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.flush()   # 先拿到子单的编号（事件只带编号）
    outbox.enqueue(db, "orders.pending_pool_changed", {})
    for c in created:
        outbox.enqueue(db, "orders.created", {"order_id": c.id})
    db.commit()
    return [enrich_order_out(c, db, current) for c in created]


@router.post("/{order_id}/freight", response_model=OrderOut)
def update_order_freight(
    order_id: int,
    body: OrderFreightBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> OrderOut:
    """派单员补录/修改司机运费（送达/撤销/退货后锁定；传 null 清空回待定）。"""
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # ⚠️ 先锁再判（2026-09-23 第 6 轮，理由见 `order_products._locked_editable_order`）：
    #    这里的判据是"已送达/已撤销/已退货就不许改运费"，而判完到写之间正好是送达能挤进来的窗口；
    #    挤进来之后订单运费变了、司机账单却没跟着变 —— 又回到"同一笔钱两个数"。
    order = lock_order_row(db, order)
    # 已退货也算"这单结束了"：司机账单在送达那一刻就按当时的规则快照生成好了，
    # 事后改运费不会动账单（改了个寂寞），而界面上会显示一个与账单不一致的数。
    if order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED):
        raise HTTPException(status_code=400, detail="已送达或已撤销的订单不可修改运费")
    old = order.freight_fee
    order.freight_fee = body.freight_fee
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_FREIGHT,
        change_payload={
            "freight_fee": {
                "before": str(old) if old is not None else None,
                "after": str(body.freight_fee) if body.freight_fee is not None else None,
            }
        },
    )
    outbox.enqueue(db, "orders.freight_updated", {"order_id": order.id})
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/recall", response_model=OrderOut)
def recall_order(
    order_id: int,
    body: OrderRecallBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_RECALL)),
) -> OrderOut:
    order = db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    shipper_id = order.shipper_id
    old_driver_id = order.driver_id
    try:
        recall_dispatch(db, order, current, body.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # ⚠️ 三条事件与这次撤回**同一个事务**（撤回失败就一条都不发）：
    #    司机「派单被撤回」/ 货主「这单被召回了」/ 派单员的待派池变了。
    if old_driver_id:
        outbox.enqueue(db, "orders.revoked", {"driver_id": old_driver_id, "order_id": order_id, "reason": body.reason})
    if shipper_id is not None:
        outbox.enqueue(db, "orders.recalled", {"shipper_id": shipper_id, "order_id": order_id})
    outbox.enqueue(db, "orders.pending_pool_changed", {})
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


def _template_category_ids(db: Session, template_id: int) -> list[int]:
    """一条价目挂的分类编号（沉淀时用来判断"这条路线上是不是已经有一条同类的价目"）。"""
    return list(
        db.scalars(
            select(FreightTemplateCategory.category_id).where(
                FreightTemplateCategory.template_id == template_id
            )
        ).all()
    )
