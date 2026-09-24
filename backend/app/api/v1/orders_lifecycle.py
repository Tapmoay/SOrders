"""订单生命周期（创建 / 编辑 / 异常标记 / 回收站恢复 / 删除）（orders_lifecycle）—— 2026-09-24 整改阶段 4 **纯搬迁**的产物。

从 `api/v1/orders.py` 原样搬来的 5 个函数（create_order,update_order,patch_order_exception,restore_order,delete_cancelled_order）。
除代码组织外**一个字没改** —— URL / 入参 / 出参 / 权限 / 状态机 / 数据库全不变；
证据：`_tools/qa/_api_contract_snapshot.py --diff <搬之前> <搬之后>` 契约零差异。

⚠️ 本模块**自己声明** `router`：按文件解析的 AST 工具（端点索引 / AI 能力表）靠这一行算 URL 前缀。
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.core.business_time import utc_now_naive
from app.core.rbac import Permission, role_has_permission, user_role_key
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import Order, User
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.schemas.order import OrderCreate, OrderExceptionBody, OrderOut, OrderUpdate
from app.schemas.product_visibility import product_visible_to
from app.services.auth_service import new_order_no
from app.services.operation_log_service import write_log
from app.services.order_flow import build_order_products, ensure_order_date, lock_order_row
from app.services.order_response import enrich_order_out, load_order_for_response
from app.services import usage_service
from app.services.shipper_contact_service import upsert_boss_contact
from app.services import place_service
from app.api.v1.orders_common import (
    _get_order_scoped,
)
from app.core import outbox

router = APIRouter(prefix="/orders", tags=["orders"])


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
    outbox.enqueue(db, "orders.pending_pool_changed", {})
    outbox.enqueue(db, "orders.created", {"order_id": order.id})
    db.commit()
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
    # ⚠️ **改单必须推**（2026-09-24 第 20 轮并行渗透 C12-3）：这条路径原来一个推送都不发
    #    （同文件的派单 `:1440`、送达 `:1681`、撤销 `:1725`、撤回 `:1965` 都排了推送）。
    #    而它改的是**地址 / 收货人与下单人的电话 / 配送说明** —— 这条路径在
    #    「已派单 / 已接单」时是允许的（上面的状态门只挡终态），也就是说它**就是给在途的单用的**：
    #    客户在电话里改了地址 → 派单员改完 → 司机那一页还是旧地址，且断线重连也补不回
    #    （重连只回补通知表、不带订单负载）。司机拿着旧地址跑一趟的成本是真实发生的。
    #    ⚠️ 事件与这次改单**同一个事务**（放在 commit 之前）：改单没成，司机就不该收到「地址变了」。
    if order.driver_id:
        outbox.enqueue(db, "orders.edited", {"driver_id": order.driver_id, "order_id": order.id})
    db.commit()
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
