"""orders 路由的其余部分：创建 / 派单 / 送达 / 收款 / 退货 / 撤回 / 图片。

2026-09-24（整改阶段 4）**纯搬迁**：查询组（列表 / 待派计数 / 详情）搬到了 `orders_query.py`，
三模块共用的 router 与助手搬到了 `orders_common.py`。
除代码组织外**一个字没改** —— 端点集合 / 入参 / 出参 / 权限 / 状态机 / 数据库全不变，
证据：`_tools/qa/_api_contract_snapshot.py --diff before-orders-move now` 契约零差异。
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload
from app.api.v1.arrears import find_or_create_unit
from app.core.business_time import local_stamp, utc_now_naive
from app.core.rbac import Permission, role_has_permission, user_role_key
from app.core.upload_read import MAX_IMAGE_BYTES, read_limited
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import ArrearsUnit, Order, User
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
    DeliveryPhotoUploadOut,
    DriverNoteBody,
    OrderAssignBody,
    OrderFreightBody,
    OrderSplitBody,
    OrderBatchAssignBody,
    OrderBatchAssignOut,
    OrderChargeBody,
    OrderCompleteBody,
    OrderCreate,
    OrderExceptionBody,
    OrderOut,
    OrderRecallBody,
    OrderReturnBody,
    OrderReturnOut,
    OrderUpdate,
)
from app.schemas.place import OrderNavigationBody
from app.schemas.product_visibility import product_visible_to
from app.services.auth_service import new_order_no
from app.services.operation_log_service import write_log
from app.services.order_flow import split_order
from app.services.order_flow import (
    assign_driver,
    build_order_products,
    cancel_pending,
    complete_delivery,
    ensure_order_date,
    lock_order_row,
    recall_dispatch,
)
from app.services.order_money import money_map
from app.services.accounting_service import BillAlreadySettledError, resync_open_piece_bill
from app.services.order_response import enrich_order_out, load_order_for_response
from app.services.order_return import OrderReturnError, ReturnItem, return_order
from app.services import order_return_request as return_request_svc
from app.services import usage_service
from app.services.shipper_contact_service import upsert_boss_contact
from app.services import place_service
# ⚠️ 付款家族（_already_collected / _apply_complete_payment / …）2026-09-24 阶段 4 搬去了
# `orders_payment.py`；**完成订单时要写那笔钱**，所以这里要把它引回来（跨模块 import，无环）。
from app.api.v1.orders_payment import _apply_complete_payment_logged, _reject_if_already_collected
from app.api.v1.orders_common import (
    UPLOAD_DIR, ALLOWED_IMAGE_CT, _bg_dispatcher_pending_pool, _bg_freight_updated,
    _bg_ledger_updated_shipper, _bg_notify_cancel, _bg_notify_delivered, _bg_notify_driver_ack,
    _bg_notify_navigation_filled, _bg_notify_new_order, _bg_notify_order_edited,
    _bg_notify_return_request_closed, _bg_push_assigned, _bg_push_revoked,
    _bg_push_shipper_recalled, _get_order_scoped, _order_not_deleted_or_404,
    _save_delivery_uploads,
)

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
            db.commit()
            results.append(BatchAssignResultItem(order_id=oid, success=True, detail=None))
            background_tasks.add_task(_bg_push_assigned, body.driver_id, oid)
        except ValueError as e:
            db.rollback()
            results.append(BatchAssignResultItem(order_id=oid, success=False, detail=str(e)))
    if any(r.success for r in results):
        background_tasks.add_task(_bg_dispatcher_pending_pool)
    return OrderBatchAssignOut(results=results)




@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cancelled_order(
    order_id: int,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    """软删除订单 → 进入隔离区 30 天（用户不可见；派单员可恢复；到期物理清理）。
    货主：本人 已送达/已撤销/异常 订单；派单员：任意状态（含待派单）。"""
    order = _get_order_scoped(order_id, current, db)
    role = user_role_key(current)
    if role not in (UserRole.SHIPPER.value, UserRole.DISPATCHER.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作")
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
    role = user_role_key(current)
    target_shipper_id: int | None
    order_temp_shipper_name: str | None = None
    #: 这一单**为谁下的**（临时货主 / 未指定时是 None）。
    #: 「下单人」的兜底要用它 —— 见下面那一段注释（用户 2026-09-22 的口径）。
    target_shipper: User | None = None
    if role == UserRole.SHIPPER.value:
        if body.shipper_id is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="货主下单无需指定货主")
        target_shipper_id = current.id
        target_shipper = current
    elif role == UserRole.DISPATCHER.value:
        if body.shipper_id is not None:
            su = db.get(User, body.shipper_id)
            if su is None or user_role_key(su) != UserRole.SHIPPER.value:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的货主")
            target_shipper_id = body.shipper_id
            target_shipper = su
        elif body.temp_shipper_name:
            target_shipper_id = None
            order_temp_shipper_name = body.temp_shipper_name
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="代理下单请选择货主或填写临时货主姓名",
            )
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前角色不能创建订单")

    # ── 「下单人」= 这一单的**货主**（用户 2026-09-22：「派单员，他是**代理下单**啊，所以他
    #    **不能填写自己的名称和电话号码**，他要填的是**自动填选的是货主的**……他**选择货主之后**，
    #    他写的货主的信息就会**自动地填入进去**，也就是名称和电话号码」）────────────────────
    # App 在"选中货主"那一刻就把这两栏填好了（判据 `OrdererPrefill.kt::ordererContactFor`），
    # 这里补的是**没带上**的那几个调用方：老版本 App、以及 AI 下单（动作的 `name_boss` /
    # `phone_boss` 本来就是可选参数）。⛔ **只在两栏都空的时候补**：派单员手写的"下单人是王老板"
    # （接电话的人不是账号持有人）是真实场景，一个字都不许改；而**只空一栏**时也不补 ——
    # 名称与电话是**同一个人**的两个字段，拆开拼（名字写王老板、电话却是货主账号那个号）
    # 会造出一个"张冠李戴"的下单人，界面上看不出来。
    # ⛔ **货主自己下单不走这一段**（`target_shipper.id == current.id`）：那一路客户端填的就是
    # 他自己的账号资料，与这里同源 —— 补一遍只会把"客户端明明填了空"这种状态悄悄盖掉。
    boss_name = body.contact_boss_name.strip()
    boss_phone = body.contact_boss_phone.strip()
    if target_shipper is not None and target_shipper.id != current.id:
        if not boss_name and not boss_phone:
            boss_name = (target_shipper.full_name or "").strip()
            boss_phone = (target_shipper.phone or "").strip()

    # 白名单（v3.43）：货主自己下单时，**不许**把看不到的商品塞进单里。
    # 为什么必须在这一层挡：选品页把商品藏起来只是"看不到"，
    # 接口照收就等于**看起来限制了、其实没有**（这种洞在界面上完全看不出来）。
    # 派单员代下单不受这条限制：他不是被限制的那个人，而且他看得到全部商品。
    bad = [
        (i + 1, ln.product_id)
        for i, ln in enumerate(body.lines)
        if not product_visible_to(db, current, ln.product_id)
    ]
    if bad:
        idx = "、".join(f"第 {i} 行" for i, _ in bad)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{idx}的商品不在你的可选范围内。请重新从商品目录里选一个。",
        )

    # 行金额/商品编号的判据在 build_order_products 里（**唯一一处**）：
    # 行金额由服务端按"单价×数量"算，商品编号必须在库里且没被删——被拒时要说清是第几行。
    try:
        lines = build_order_products(db, body.lines)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    od = ensure_order_date(body.order_date)
    order = Order(
        order_no=new_order_no(),
        status=OrderStatus.PENDING_DISPATCH,
        shipper_id=target_shipper_id,
        temp_shipper_name=order_temp_shipper_name,
        order_date=od,
        delivery_description=body.delivery_description,
        address_detail=body.address_detail,
        address_lat=body.address_lat,
        address_lng=body.address_lng,
        contact_dongjia_phone=body.contact_dongjia_phone,
        contact_boss_phone=boss_phone,
        contact_dongjia_name=body.contact_dongjia_name.strip(),
        contact_boss_name=boss_name,
        remark=body.remark,
        order_products=lines,
    )
    db.add(order)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_CREATE,
        change_payload={"order_no": order.order_no},
    )
    # 下单时把这一单的收货地址收进「我的地点」（用户 2026-09-20：「只要用户下单他会选择地点，
    # 这个时候，我们就自动地把它添加到地点库当中」）。
    # 代理下单**两边都记**（下单人 + 这单的货主）：地点库按登录人隔离，只记一边的话，
    # 另一边的人下次还得重新找这个地址。判据与去重全在 `place_service.remember_order_address`。
    saved = place_service.remember_order_address(
        db,
        owner_ids=[current.id, target_shipper_id],
        name=body.address_detail,
        detail_address=body.address_detail,
        lat=float(body.address_lat) if body.address_lat is not None else None,
        lng=float(body.address_lng) if body.address_lng is not None else None,
    )
    # 真的**新建**了才留痕：并进已有那条时什么都没变，多写一行日志只会让审计页变吵。
    # 写的是 PLACE_AUTO_ADDED（与"常用共享地点自动进我的地点"同一个动作码），
    # 这样"我的地点库里怎么多出一条"在操作日志里**只有一个地方**要查。
    for owner_id in saved["created_for"]:
        write_log(
            db,
            operator_id=current.id,
            order_id=order.id,
            action=OperationAction.PLACE_AUTO_ADDED,
            change_payload={
                "place_name": (body.address_detail or "").strip(),
                "owner_id": owner_id,
                "has_coords": body.address_lat is not None and body.address_lng is not None,
                "note": "下单时把收货地址自动加进「我的地点」（判据见 place_service.remember_order_address）",
            },
        )
    if target_shipper_id is not None and boss_phone:
        # 名字一起带上：这位下单人会在货主的联系人里出现，只有号码没有名字的话
        # 货主下次看到的就是一条"来源不明的联系人"（`upsert_boss_contact` 只在原本没名字时补）。
        # ⚠️ 用的是**兜底之后**的 `boss_*`（不是 `body.contact_boss_*`）：代理下单没带下单人时，
        #    这里记的就该是那位货主的姓名/电话 —— 与订单上写的是同一个人。
        # ⛔ "下单人就是货主自己"时由 `upsert_boss_contact` 挡掉（别让他出现在自己的联系人里）。
        upsert_boss_contact(db, target_shipper_id, boss_phone, boss_name)
    # ---- 「常用的排前面」的计数（用户 2026-09-22 定的统一列表排序规则）--------------
    # 记的是**这一单真用上了哪些库里的行**：选中的联系人 / 线路 / 我的地点 / 每一个商品，
    # 代理下单时还有这位货主。排序规则本身（常用度 → 先创建的在前）在
    # `services/usage_service.with_popularity`，**唯一一处**。
    # ⚠️ 只记"我这单用过的"，不是"点开看过"：这样列表往前靠的东西，都是**真的用过**的。
    for kind, target in (
        (usage_service.KIND_CONTACT, body.contact_id),
        (usage_service.KIND_ADDRESS, body.address_id),
        (usage_service.KIND_LOCATION, body.location_id),
    ):
        usage_service.record_usage(db, user=current, kind=kind, target_id=target)
    # 货主得是**派单员挑的**才算"常用货主"：货主自己给自己下单时 `target_shipper_id == current.id`，
    # 记下来只会让他自己那张"人"的计数自增（他对人列表没兴趣，也不该影响别人看到的排序）——
    # 实测抓到的多余一行 `kind=user, target=自己`（2026-09-22）。
    if target_shipper_id is not None and target_shipper_id != current.id:
        usage_service.record_usage(
            db, user=current, kind=usage_service.KIND_USER, target_id=target_shipper_id
        )
    for ln in body.lines:
        usage_service.record_usage(db, user=current, kind=usage_service.KIND_PRODUCT, target_id=ln.product_id)
    db.commit()
    background_tasks.add_task(_bg_dispatcher_pending_pool)
    background_tasks.add_task(_bg_notify_new_order, order.id)
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单保存失败")
    return enrich_order_out(full, db, current)


@router.patch("/{order_id}", response_model=OrderOut)
def update_order(
    order_id: int,
    body: OrderUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_EDIT)),
) -> OrderOut:
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # ⚠️ 先锁再判（2026-09-23 第 6 轮）：上面那份是**可能过期**的对象，
    #    而"判完到写之间"正是司机送达/撤销能挤进来的窗口（同 `order_products` 那一处）。
    order = lock_order_row(db, order)
    if order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED):
        raise HTTPException(status_code=400, detail="订单已结束，不可再编辑")
    before = {
        "delivery_description": order.delivery_description,
        "address_detail": order.address_detail,
        "remark": order.remark,
    }
    if body.delivery_description is not None:
        order.delivery_description = body.delivery_description
    if body.address_detail is not None:
        order.address_detail = body.address_detail
    if body.address_lat is not None:
        order.address_lat = body.address_lat
    if body.address_lng is not None:
        order.address_lng = body.address_lng
    if body.contact_dongjia_phone is not None:
        order.contact_dongjia_phone = body.contact_dongjia_phone
    if body.contact_boss_phone is not None:
        order.contact_boss_phone = body.contact_boss_phone
    if body.contact_dongjia_name is not None:
        order.contact_dongjia_name = body.contact_dongjia_name
    if body.contact_boss_name is not None:
        order.contact_boss_name = body.contact_boss_name
    if body.remark is not None:
        order.remark = body.remark
    if body.internal_notes is not None:
        order.internal_notes = body.internal_notes
    after = {
        "delivery_description": order.delivery_description,
        "address_detail": order.address_detail,
        "remark": order.remark,
    }
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_UPDATE,
        change_payload={"before": before, "after": after},
    )
    db.commit()
    # ⚠️ **改单必须推**（2026-09-24 第 20 轮并行渗透 C12-3）：这条路径原来一个推送都不发
    #    （同文件的派单 `:1440`、送达 `:1681`、撤销 `:1725`、撤回 `:1965` 都排了推送）。
    #    而它改的是**地址 / 收货人与下单人的电话 / 配送说明** —— 这条路径在
    #    「已派单 / 已接单」时是允许的（上面的状态门只挡终态），也就是说它**就是给在途的单用的**：
    #    客户在电话里改了地址 → 派单员改完 → 司机那一页还是旧地址，且断线重连也补不回
    #    （重连只回补通知表、不带订单负载）。司机拿着旧地址跑一趟的成本是真实发生的。
    if order.driver_id:
        background_tasks.add_task(_bg_notify_order_edited, order.driver_id, order.id)
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


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
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> OrderOut:
    """派单员：从隔离区恢复订单（软删除后 30 天内可恢复）。"""
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅派单员可恢复")
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








@router.post("/{order_id}/complete-with-upload", response_model=OrderOut)
async def complete_order_with_upload(
    order_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_COMPLETE_DRIVER)),
    files: list[UploadFile] = File(...),
    driver_remark: str = Form(""),
    payment: str = Form(""),
    damage_items: str = Form("[]"),
    damage_note: str = Form(""),
) -> OrderOut:
    # ⛔ **归属与状态必须在落盘之前判完**（2026-09-19 全项目报告 P1-11，中）：
    #    本端点原来取到单就直接 `_save_delivery_uploads`，把"是不是你的单 / 状态对不对"
    #    留给后面的 `complete_delivery` —— 后果有两条，都不是理论：
    #      · **任意司机的令牌可以对任意 `order_id` 写文件**到匿名可读的公开静态目录
    #        （`/static/uploads/delivery/<order_id>/…`）：拒绝发生在文件已经落盘之后；
    #      · `order_id` 不存在时 `order` 是 None → `complete_delivery(db, None, …)` 抛
    #        `AttributeError`（**不是** ValueError，下面的 `except ValueError` 接不住）→ **500**。
    #    三道门照抄同文件 `upload_delivery_photos`（同一条链上它是做对的那一个：先判后写）。
    order = _order_not_deleted_or_404(
        db.scalars(
            select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
        ).first()
    )
    if user_role_key(current) != UserRole.DRIVER.value or order.driver_id != current.id:
        raise HTTPException(status_code=403, detail="无权操作")
    if order.status != OrderStatus.ACCEPTED:
        raise HTTPException(status_code=400, detail="仅「已接单」订单可上传凭证")
    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")
    urls = await _save_delivery_uploads(order_id, files)
    try:
        items = _parse_damage_items(damage_items)
        complete_delivery(db, order, current, urls, driver_remark, items, damage_note.strip())
        # 收款方式也放进同一个 try：明确要现金而派单没勾选时要**整单回滚**（不能只送达到一半）
        _apply_complete_payment_logged(db, order, payment.strip() or None, current.id)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    background_tasks.add_task(_bg_notify_delivered, order.id)
    if order.shipper_id is not None:
        background_tasks.add_task(_bg_ledger_updated_shipper, order.shipper_id)
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/driver-ack", response_model=OrderOut)
def driver_ack_view(
    order_id: int,
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> OrderOut:
    if user_role_key(current) != UserRole.DRIVER.value:
        raise HTTPException(status_code=403, detail="无权操作")
    order = _get_order_scoped(order_id, current, db)
    if order.status != OrderStatus.DISPATCHED:
        raise HTTPException(status_code=400, detail="仅「已派单」订单可确认接单")
    # ⚠️ 条件 UPDATE 占位（2026-09-19 审计）：这是**司机手滑点两下**最容易撞上的一处
    #    （派单员同一时刻可能在撤销/撤回）。原来是无条件赋值，与撤销并发时能把已经撤销的单
    #    覆盖回 ACCEPTED —— 而撤销那一步已经把预占释放了，于是单子复活但**库存永远不扣**
    #    （送达时 `auto_stock_commit` 找不到 RESERVED 行）。作业同 assign/complete。
    claimed = db.execute(
        update(Order)
        .where(
            Order.id == order.id,
            Order.status == OrderStatus.DISPATCHED,
            Order.driver_id == current.id,   # 只有被派的那个人能接（_get_order_scoped 已挡，这里再钉一次）
            Order.deleted_at.is_(None),
        )
        .values(status=OrderStatus.ACCEPTED, driver_acknowledged_at=datetime.now(timezone.utc))
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="这张单刚刚被改过（可能已被撤销/撤回/别人接过），请刷新后看看当前状态",
        )
    db.refresh(order)
    sid = order.shipper_id
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    if sid is not None:
        background_tasks.add_task(_bg_notify_driver_ack, sid, order.id)
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/driver-note", response_model=OrderOut)
def driver_append_internal_note(
    order_id: int,
    body: DriverNoteBody,
    current: User = Depends(require_permission(Permission.ORDER_INTERNAL_NOTE)),
    db: Session = Depends(get_db),
) -> OrderOut:
    role = user_role_key(current)
    if role not in (UserRole.DRIVER.value, UserRole.DISPATCHER.value):
        raise HTTPException(status_code=403, detail="无权操作")
    order = _order_not_deleted_or_404(db.scalars(select(Order).where(Order.id == order_id)).first())
    # ⚠️ **先取锁再改这一段文本**（2026-09-23 第 8 轮）：这一行是"读出来 → 拼一段 → 写回去"
    #    （`internal_notes` 是**累计文本**，不是单值字段）。两个并发追加（司机与派单员各写一条，
    #    或同一个人两个设备）会各自读到同一份旧文本、各自拼一段再写回 → **后写的那一段把前一段
    #    整条吃掉**，而两边都收到 200。这条红线（`_check_status_gate_locking.py` 的"多写入点必须同源"）
    #    把 `internal_notes` 盘出来时才看见：另一个写入点 `assign_driver` 早就锁了，这里漏了。
    order = lock_order_row(db, order)
    if role == UserRole.DRIVER.value:
        if order.driver_id != current.id:
            raise HTTPException(status_code=403, detail="无权操作")
        # ⛔ 时间戳按**业务当地时刻**印（`local_stamp` 的唯一实现）：
        #    这里原来是 `datetime.now(timezone.utc).strftime(...)` —— 当地 09-21 07:10 写的备注
        #    在单子上印成 `[司机 09-20 23:10]`（连日期都跨），而这段文本一旦写进
        #    `internal_notes` 就**再也改不了**（累计文本、历史不可追溯）——
        #    用户拿它跟司机对时间时，两边说的不是同一天（2026-09-23 第 18 轮并行渗透 A2-3）。
        prefix = f"[司机 {local_stamp()}] "
    else:
        prefix = f"[派单 {local_stamp()}] "
    order.internal_notes = (order.internal_notes or "").strip()
    if order.internal_notes:
        order.internal_notes += "\n"
    order.internal_notes += prefix + body.note.strip()
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/navigation", response_model=OrderOut)
def fill_order_navigation(
    order_id: int,
    body: OrderNavigationBody,
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> OrderOut:
    """**司机到场后给这单补上导航信息**（订单原本没有坐标时才能补）。

    ## 为什么会需要这个接口
    下单时收货地址常常只有一行文字（"XX 路口进来第三家"），没有坐标；而**知道坐标的人
    恰恰是到过现场的司机**。以前这个坐标没有任何地方可以放：订单的经纬度只有
    `PATCH /orders/{id}` 一个入口（不带独立按钮），司机的 App 里更没有入口 ——
    于是同一个地方被问一百遍。这个接口把司机的那一次现场定位变成**三个人受益**：

    1. **这一单**：`orders.address_lat/lng` 补上，`nav_source='driver'`（货主端能看到
       "司机已帮你补上导航信息"，这句话必须是真的，所以来源要落库）；
    2. **这个货主**：写进他自己的地点库（`shipper_locations`），下次下单直接可选；
    3. **所有人**：写进**全局共享地点库**（`places`），同一个位置的下一单直接拉过来。

    ## 三条硬约束
    - **只补不改**：订单已经有坐标时一律 400。司机到的地方不一定就是收货点
      （卸货口、隔壁仓），让他覆盖掉一个货主确认过的坐标，是把"有坐标"变成"有错坐标"，
      而错坐标的危害比没有坐标更大（导航会把人带错，且看不出来）。
    - **只有这单的司机或派单员**能补（`_get_order_scoped` 已经按角色卡过）。
    - **合并半径 1 米**（`place_service.MERGE_METERS`）：相近坐标并入同一条而不是新建。
      "这次到底是新建还是并入"记在 `operation_logs.change_payload` 里（`merged_into_existing_place`）
      —— 出参保持 `OrderOut`（和其它订单动作一致，客户端拿到后整单刷新），
      所以**不在这里编造一个界面上的字段**；用户看到的结论两种情况下是同一句：
      "这个位置的坐标已经进库，下次能直接选"。
    """
    role = user_role_key(current)
    if role not in (UserRole.DRIVER.value, UserRole.DISPATCHER.value):
        raise HTTPException(status_code=403, detail="仅司机或派单员可以补导航信息")
    order = _get_order_scoped(order_id, current, db)
    # ⚠️ **先取锁再判"要不要补"**（2026-09-23 第 8 轮）：下面那道门是"还没有坐标才让补"，
    #    而它读的是手边这份对象；`PATCH /orders/{id}`（改地址，已取锁）与它写的是**同一组字段**
    #    （`address_detail` / `address_lat` / `address_lng`）。不同源时口径宽的那一个就是漏洞：
    #    派单员刚把地址改对、司机这一下补录又把它盖回他现场选的那个点。
    order = lock_order_row(db, order)
    if order.deleted_at is not None:
        raise HTTPException(status_code=400, detail="这张订单在回收站里，不能补导航信息")
    if order.address_lat is not None and order.address_lng is not None:
        raise HTTPException(
            status_code=400,
            detail="这张订单已经有导航信息了，不需要补录（避免把正确的坐标改成错的）",
        )
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="已撤销的订单不需要补导航信息")

    lat = float(body.address_lat)
    lng = float(body.address_lng)
    # 地点名：优先用司机填的，其次用订单原有的文字地址（避免库里一排空白名字）
    place_name = (body.name or "").strip() or (order.address_detail or "").strip()
    detail = (body.detail_address or "").strip() or (order.address_detail or "").strip()
    # ⚠️ 名字与地址**不能都是空**：这张单会往**全库共享**的地点库里写一条，
    #    而共享库是全库共用的一张表 —— 一条无名无址的记录在每个人的「共享地点」
    #    列表里都显示成「未命名地点」+ 空地址，谁也认不出是哪儿。
    #    （2026-09-19 起删除改成了软删、只有派单员能删，所以现在"清得掉"了；
    #    但入口挡掉仍然更好：进来一条就是**所有人**都看见了一条。）
    #    这里挡在入口，并给一句能照着做的中文（"起个名字"比"参数不合法"有用得多）。
    if not place_name and not detail:
        raise HTTPException(
            status_code=400,
            detail="请给这个位置起个名字（或填一下地址）再提交 —— "
            "共享库里只有坐标的话，别人下次认不出是哪儿，而且这条记录删不掉",
        )

    place, merged = place_service.upsert_place(
        db,
        lat=lat,
        lng=lng,
        name=place_name,
        detail_address=detail,
        source="driver" if role == UserRole.DRIVER.value else "dispatcher",
        created_by=current.id,
        order_id=order.id,
    )

    order.address_lat = body.address_lat
    order.address_lng = body.address_lng
    order.nav_source = "driver" if role == UserRole.DRIVER.value else "dispatcher"
    if detail:
        order.address_detail = detail

    shipper_location_created = False
    if order.shipper_id is not None:
        _, shipper_location_created = place_service.ensure_shipper_location(
            db,
            shipper_id=order.shipper_id,
            name=place_name,
            detail_address=detail,
            lat=lat,
            lng=lng,
        )

    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.ORDER_NAVIGATION_FILL,
        change_payload={
            "order_no": order.order_no,
            "address_lat": str(body.address_lat),
            "address_lng": str(body.address_lng),
            "place_id": place.id,
            "place_name": place.name,
            # 这两个布尔量是"到底发生了什么"的原始记录：
            # 并入已有坐标 vs 新建、货主地点库有没有真的多一条。
            "merged_into_existing_place": merged,
            "shipper_location_created": shipper_location_created,
            "shipper_id": order.shipper_id,
        },
    )
    db.commit()

    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    if order.shipper_id is not None:
        background_tasks.add_task(
            _bg_notify_navigation_filled, order.shipper_id, order.id, place_name
        )
    return enrich_order_out(full, db, current)


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
    db.commit()
    background_tasks.add_task(_bg_push_assigned, body.driver_id, order.id)
    background_tasks.add_task(_bg_dispatcher_pending_pool)
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
    db.commit()
    for c in created:
        background_tasks.add_task(_bg_notify_new_order, c.id)
    background_tasks.add_task(_bg_dispatcher_pending_pool)
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
    db.commit()
    background_tasks.add_task(_bg_freight_updated, order.id)
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    return enrich_order_out(full, db, current)


def _parse_damage_items(raw: str) -> list:
    """解析 multipart Form 的 damage_items JSON（[{order_product_id, quantity}]）。"""
    import json as _json

    if not raw or not raw.strip():
        return []
    try:
        data = _json.loads(raw)
    except Exception:
        raise ValueError("货损数据格式错误")
    if not isinstance(data, list):
        raise ValueError("货损数据格式错误")
    out = []
    for it in data:
        out.append(type("DmgItem", (), {"order_product_id": int(it.get("order_product_id")), "quantity": int(it.get("quantity", 0))})())
    return out








@router.post("/{order_id}/complete", response_model=OrderOut)
def complete_order(
    order_id: int,
    body: OrderCompleteBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_COMPLETE_DRIVER)),
) -> OrderOut:
    order = _order_not_deleted_or_404(
        db.scalars(select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)).first()
    )
    try:
        complete_delivery(db, order, current, body.delivery_photo_urls, body.driver_remark, body.damage_items, body.damage_note)
        # 收款方式也放进同一个 try：明确要现金而派单没勾选时要**整单回滚**（不能只送达到一半）
        _apply_complete_payment_logged(db, order, body.payment, current.id)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    background_tasks.add_task(_bg_notify_delivered, order.id)
    if order.shipper_id is not None:
        background_tasks.add_task(_bg_ledger_updated_shipper, order.shipper_id)
    return enrich_order_out(full, db, current)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: int,
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> OrderOut:
    # ⛔ 隔离区（回收站）里的单**不许撤销**（2026-09-24 第 24 轮并行渗透 03-F1）：
    #    这是第 5 条写路径，而 R13-D1 当年只补了送达/上传凭证/追加备注/派单四条。
    #    漏掉它的后果是**两个角色两种答案**：货主 `GET /orders/{id}` 是 404、
    #    `?deleted_only=true` 是 403（他在界面上根本看不到这张单），
    #    可是同一个 id 发 `POST /cancel` 却会成功 —— 一张他看不见的单被改成「已撤销」，
    #    还会推一条「已撤销」通知给他（点进去 404）。本机库内实测有 22 行
    #    `deleted_at IS NOT NULL AND shipper_id=2 AND status IN (待派单, 已派单)` 满足这个前提。
    #    用 `_order_not_deleted_or_404` 与那四条写路径同一个判据、同一句答复。
    order = _order_not_deleted_or_404(
        db.scalars(select(Order).where(Order.id == order_id)).first()
    )
    role = user_role_key(current)
    if role == UserRole.SHIPPER.value:
        if order.shipper_id is None or order.shipper_id != current.id:
            raise HTTPException(status_code=403, detail="无权操作")
    elif role == UserRole.DISPATCHER.value:
        _reject_if_already_collected(db, order, "改回挂账")
    else:
        raise HTTPException(status_code=403, detail="无权操作")

    if order.status not in (OrderStatus.PENDING_DISPATCH, OrderStatus.DISPATCHED):
        raise HTTPException(status_code=400, detail="仅「待派单/已派单（司机未接单）」订单可撤销")

    if role == UserRole.SHIPPER.value:
        if not role_has_permission(role, Permission.ORDER_CANCEL_SHIPPER):
            raise HTTPException(status_code=403, detail="无权操作")
    else:
        if not role_has_permission(role, Permission.ORDER_CANCEL_DISPATCHER):
            raise HTTPException(status_code=403, detail="无权操作")

    try:
        cancel_pending(db, order, current)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    sid = order.shipper_id
    oid = order.id
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    if sid is not None:
        background_tasks.add_task(_bg_notify_cancel, sid, oid)
    if order.driver_id is not None:
        background_tasks.add_task(_bg_notify_cancel, order.driver_id, oid)
    background_tasks.add_task(_bg_dispatcher_pending_pool)
    return enrich_order_out(full, db, current)


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
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise HTTPException(status_code=500, detail="订单数据异常")
    if sid is not None:
        background_tasks.add_task(_bg_ledger_updated_shipper, sid)
    if closed_id is not None:
        # 告诉货主"你那张申请被直接办掉了、实退多少"（差异也在这里如实写出来）
        background_tasks.add_task(
            _bg_notify_return_request_closed,
            closed_id,
            str(result.returned_amount),
            closed_note,
        )
    return OrderReturnOut(
        order_no=result.order_no,
        returned_amount=result.returned_amount,
        refund_amount=result.refund_amount,
        fully_returned=result.fully_returned,
        restocked_lines=result.restocked_lines,
        warnings=result.warnings,
        order=enrich_order_out(full, db, current),
    )










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
    db.commit()
    if old_driver_id:
        background_tasks.add_task(_bg_push_revoked, old_driver_id, order_id, body.reason)
    if shipper_id is not None:
        background_tasks.add_task(_bg_push_shipper_recalled, shipper_id, order_id)
    background_tasks.add_task(_bg_dispatcher_pending_pool)
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
