"""订单域的命令层（应用层）—— 第二轮整改 R2-02。

## 这一层要解决什么
方向指南（`docs/ARCHITECTURE_RECTIFICATION_R2.md`）第二节把第二轮的形状定成：

```text
Route → Command → Order Application Logic → Order Domain Rule → Persistence
```

| 层 | 住在哪 | 只负责 |
|---|---|---|
| Route | `api/v1/**` | HTTP：认证、参数、响应、状态码 |
| **Command** | **本模块** | 把这个业务动作**组织起来**：取单 → 判前置 → 调领域规则 → 落库 → 产生事件 |
| DomainRule | `services/order_flow.py` 等 | 这个动作**在什么条件下合法**（状态跃迁的唯一写入口） |
| Persistence | `models/**` + `Session` | 数据怎么存 |

⛔ 指南同一条里也踩了刹车：「**不要为了唯一入口而建立一个巨大万能函数**」——
所以这里是**一个个具名命令**（`create_order` / `update_order` / …），不是一个
`command(name, payload, ctx, anything)` 的超级函数。每条命令的前置条件与结果各写各的。

## 为什么本层不 import fastapi
它抛 `CommandError`（一句人话 + 一个 HTTP 状态），由路由翻译成 `HTTPException`。
理由不是洁癖：这一层要被**三个入口**共用 —— HTTP 路由、后台任务、将来的 AI 服务端化 ——
其中两个没有 HTTP 响应可写。**错误文案与状态码必须一字不变**（指南 §17.5「重构必须保持行为等价」）：
`CommandError` 只搬运，不发明。

## 与领域规则的分工（一个例子）
`update_order` 判的是「**这张单现在能不能改**」（应用层的前置条件）；
而「送达之后一律不许改」这类**状态机**的规则在 `services/order_flow.py`，由它一处说了算。
本层的每个状态相关的判断都写成注释里那句「与 order_flow 同源」，避免两处各判一遍。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import outbox
from app.core.business_time import local_stamp, utc_now_naive
from app.core.command_id import traced_command
from app.core.rbac import user_role_key
from app.models import Order, User
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.models.order import OrderProduct
from app.schemas.order import OrderCreate, OrderUpdate
from app.schemas.product_visibility import product_visible_to
from app.services import place_service, usage_service
from app.services.auth_service import new_order_no
from app.services.driver_pay import money
from app.services.inventory_service import resync_reservations
from app.services.operation_log_service import write_log
from app.services.order_contact import (
    CONTACT_INFO_REQUIRED,
    contact_info_missing,
    merged_contact_info,
)
from app.services.order_flow import (
    assign_driver,
    build_order_products,
    cancel_pending,
    ensure_order_date,
    lock_order_row,
)
from app.services.order_response import load_order_for_response
from app.services.shipper_contact_service import upsert_boss_contact


class CommandError(Exception):
    """命令层唯一会往外抛的东西：**一句人话 + 一个 HTTP 状态**。

    ⚠️ 路由那边的翻译必须**原样**透出这两个值（`status_code` 与 `detail`），
    否则"纯搬迁"就变了响应契约 —— 本仓库在阶段 4 用 `_api_contract_snapshot.py --diff`
    逐字比过搬迁前后的契约，本模块沿用同一把尺。
    """

    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@traced_command("order.create")
def create_order(db: Session, *, actor: User, body: OrderCreate) -> Order:
    """`POST /orders` 的应用层：下单 → 落库 → 记地点/常用度 → 入队事件。

    返回**已经装好关联的 Order**（调用方直接拿去做出参）；出参整形不在这层做。

    ⚠️ 本函数是从 `api/v1/orders_lifecycle.py::create_order` **原样搬进来**的
    （第二轮 R2-02）。搬运的判据：URL / 入参 / 出参 / 权限 / 状态机 / 数据库全不变；
    唯一的差别是错误从 `HTTPException(status_code, detail)` 换成
    `CommandError(detail, status_code)` —— 由路由翻回去，线上看到的字一模一样。
    """
    role = user_role_key(actor)
    target_shipper_id: int | None
    order_temp_shipper_name: str | None = None
    #: 这一单**为谁下的**（临时货主 / 未指定时是 None）。
    #: 「下单人」的兜底要用它 —— 见下面那一段注释（用户 2026-09-22 的口径）。
    target_shipper: User | None = None
    if role == UserRole.SHIPPER.value:
        if body.shipper_id is not None:
            raise CommandError("货主下单无需指定货主")
        target_shipper_id = actor.id
        target_shipper = actor
    elif role == UserRole.DISPATCHER.value:
        if body.shipper_id is not None:
            su = db.get(User, body.shipper_id)
            if su is None or user_role_key(su) != UserRole.SHIPPER.value:
                raise CommandError("无效的货主")
            target_shipper_id = body.shipper_id
            target_shipper = su
        elif body.temp_shipper_name:
            target_shipper_id = None
            order_temp_shipper_name = body.temp_shipper_name
        else:
            raise CommandError("代理下单请选择货主或填写临时货主姓名")
    else:
        raise CommandError("当前角色不能创建订单", 403)

    # ── 「下单人」= 这一单的**货主**（用户 2026-09-22：「派单员，他是**代理下单**啊，所以他
    #    **不能填写自己的名称和电话号码**，他要填的是**自动填选的是货主的**……他**选择货主之后**，
    #    他写的货主的信息就会**自动地填入进去**，也就是名称和电话号码」）────────────────────
    # App 在"选中货主"那一刻就把这两栏填好了（判据 `OrdererPrefill.kt::ordererContactFor`），
    # 这里补的是**没带上**的那几个调用方：老版本 App、以及 AI 下单（动作的 `name_boss` /
    # `phone_boss` 本来就是可选参数）。⛔ **只在两栏都空的时候补**：派单员手写的"下单人是王老板"
    # （接电话的人不是账号持有人）是真实场景，一个字都不许改；而**只空一栏**时也不补 ——
    # 名称与电话是**同一个人**的两个字段，拆开拼（名字写王老板、电话却是货主账号那个号）
    # 会造出一个"张冠李戴"的下单人，界面上看不出来。
    # ⛔ **货主自己下单不走这一段**（`target_shipper.id == actor.id`）：那一路客户端填的就是
    # 他自己的账号资料，与这里同源 —— 补一遍只会把"客户端明明填了空"这种状态悄悄盖掉。
    boss_name = body.contact_boss_name.strip()
    boss_phone = body.contact_boss_phone.strip()
    if target_shipper is not None and target_shipper.id != actor.id:
        if not boss_name and not boss_phone:
            boss_name = (target_shipper.full_name or "").strip()
            boss_phone = (target_shipper.phone or "").strip()

    # L-32：下单时「收货人 / 下单人」四个联系字段**不能全空**（用户口述「无主账是不可能存在的」，
    # m01242 定稿"干脆后端也拦一下，保险一点"）。
    # ⚠️ 位置必须在上面那段「下单人＝货主」兜底**之后**：兜底会替派单员补上下单人，
    #    在兜底之前算会把"派单员选中货主"的**合格单**误拒（这也是⛔不许写进 Pydantic 的原因：
    #    `schemas/order.py::_shipper_xor_temp` 跑在兜底之前）。
    if contact_info_missing(
        {
            "contact_dongjia_name": body.contact_dongjia_name,
            "contact_dongjia_phone": body.contact_dongjia_phone,
            "contact_boss_name": boss_name,
            "contact_boss_phone": boss_phone,
        }
    ):
        raise CommandError(CONTACT_INFO_REQUIRED)

    # 白名单（v3.43）：货主自己下单时，**不许**把看不到的商品塞进单里。
    # 为什么必须在这一层挡：选品页把商品藏起来只是"看不到"，
    # 接口照收就等于**看起来限制了、其实没有**（这种洞在界面上完全看不出来）。
    # 派单员代下单不受这条限制：他不是被限制的那个人，而且他看得到全部商品。
    bad = [
        (i + 1, ln.product_id)
        for i, ln in enumerate(body.lines)
        if not product_visible_to(db, actor, ln.product_id)
    ]
    if bad:
        idx = "、".join(f"第 {i} 行" for i, _ in bad)
        raise CommandError(
            f"{idx}的商品不在你的可选范围内。请重新从商品目录里选一个。"
        )

    # 行金额/商品编号的判据在 build_order_products 里（**唯一一处**）：
    # 行金额由服务端按"单价×数量"算，商品编号必须在库里且没被删——被拒时要说清是第几行。
    try:
        lines = build_order_products(db, body.lines)
    except ValueError as e:
        raise CommandError(str(e)) from e
    od = ensure_order_date(body.order_date)
    order = Order(
        order_no=new_order_no(),
        # ⛔ 初始状态写在这里、不写在路由里（第二轮 R2-02 的退出条件之一：
        #    「API 不直接改变 order.status」）。它是**构造期**的状态，不是跃迁 ——
        #    跃迁一律在 `services/order_flow.py` 的条件 UPDATE 里。
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
        operator_id=actor.id,
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
        owner_ids=[actor.id, target_shipper_id],
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
            operator_id=actor.id,
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
        usage_service.record_usage(db, user=actor, kind=kind, target_id=target)
    # 货主得是**派单员挑的**才算"常用货主"：货主自己给自己下单时 `target_shipper_id == actor.id`，
    # 记下来只会让他自己那张"人"的计数自增（他对人列表没兴趣，也不该影响别人看到的排序）——
    # 实测抓到的多余一行 `kind=user, target=自己`（2026-09-22）。
    if target_shipper_id is not None and target_shipper_id != actor.id:
        usage_service.record_usage(
            db, user=actor, kind=usage_service.KIND_USER, target_id=target_shipper_id
        )
    for ln in body.lines:
        usage_service.record_usage(db, user=actor, kind=usage_service.KIND_PRODUCT, target_id=ln.product_id)
    outbox.enqueue(db, "orders.pending_pool_changed", {})
    outbox.enqueue(db, "orders.created", {"order_id": order.id})
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise CommandError("订单保存失败", 500)
    return full



@traced_command("order.exception")
def resolve_exception(db: Session, *, actor: User, order_id: int, note: str) -> Order:
    """`POST /stats/exception-orders/{id}/resolve` 的应用层：把一条异常标记成**已解决**。

    ### 为什么它属于订单域、不属于报表域（第二轮 R2-05）
    这个端点住在 `/stats/` 下面，于是它的实现也一直写在 `api/v1/stats.py` 里 ——
    而它做的是**写业务状态**（`orders.is_exception` / `exception_reason` /
    `exception_resolution` / `exception_resolved_at`）。方向指南 §八 的原话是：

    > 报表是：**事实消费者，而不是事实生产者**。

    它同时还开了一个**自己的** `SessionLocal()`（不是请求那个 db）：
    于是这次写不在请求的事务里，而报表层的任何只读判据都看不见它。
    现在写逻辑在订单域（命令层），路由只负责 HTTP —— **URL / 入参 / 出参 / 权限一字未改**。

    ⚠️ 行为逐字保持不变，包括那个 `datetime.now(timezone.utc)`：
    ⛔ 本项目的口径是「库里一律 UTC **naive**」（`core/business_time.py`），这里是 tz-aware ——
    与审计 R14-9 同族。**本轮是搬迁，不改语义**；那一处单独立项（改它会让历史值与新值形状不同）。
    """
    from datetime import datetime, timezone

    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise CommandError("未找到对应记录", 404)
    # ⚠️ 这里原本是 `order.is_exception = True` ——「解除异常」把标记又设回了异常。
    # 后果不是脏数据，而是**用户点了没反应**：异常列表按 `Order.is_exception.is_(True)` 筛，
    # 解除之后单子仍然留在列表里（App 的报表中心 → 异常与审计那个按钮就是这个端点）。
    # 解除语义 = 清掉标记 + 记下解决说明与时间；异常历史仍可从那两个字段回查。
    order.is_exception = False
    order.exception_reason = order.exception_reason or "异常订单"
    order.exception_resolution = note or order.exception_resolution
    order.exception_resolved_at = datetime.now(timezone.utc)
    # 解除异常也要留痕（2026-09-19 审计）：它改的是报表「异常与审计」的口径，
    # 而这一页本身就是给人查「谁处理了哪条异常」用的 —— 没有日志，等于这一页查不到自己。
    write_log(
        db,
        operator_id=actor.id if actor is not None else None,
        order_id=order.id,
        action=OperationAction.ORDER_EXCEPTION,
        change_payload={
            "resolved": True,
            "note": note,
            "order_no": order.order_no,
        },
    )
    db.commit()
    return order

#: 货主 / 批发商那一扇门（`PATCH /orders/{id}/contact`，台账 L-27）**能补**的字段。
#: 顺序 = 入参顺序 = 审计日志 `before`/`after` 里的顺序。
CONTACT_FIELDS: tuple[str, ...] = (
    "contact_dongjia_name",
    "contact_boss_name",
    "contact_dongjia_phone",
    "contact_boss_phone",
)

#: 只有**派单员**能改的字段 → 出错时用的中文名（按顺序取第一个非 None 的）。
#: ⛔ 这张表是货主那一扇门的守卫用的，也就是 `ORDER_EDIT_CONTACT` 与 `ORDER_EDIT`
#:    两个权限点的**分界线本身**：少写一行的后果不是"少一层校验"，而是货主能改地址、
#:    能改内部备注 —— 那是把派单员的编辑权原地让出去（见 `core/rbac.py` 里那段理由）。
#: ⚠️ 判据会拿 `OrderUpdate.model_fields` **自算**这两个集合的补集（`_tools/qa/_check_order_contact_edit.py`），
#:    所以这里漏一个字段是红的，不是"忘了"。
DISPATCHER_ONLY_FIELDS: tuple[tuple[str, str], ...] = (
    ("delivery_description", "配送说明"),
    ("address_detail", "送货地址"),
    ("address_lat", "送货地址坐标"),
    ("address_lng", "送货地址坐标"),
    ("remark", "订单备注"),
    ("internal_notes", "内部备注"),
)

#: 派单员那一扇门在审计日志里记的字段 —— **就是原来那三项，一个字没动**
#: （R2-02 搬运时的行为要冻住：日志的形状变了，读日志的人会发现对不上）。
DISPATCHER_TRACKED_FIELDS: tuple[str, ...] = (
    "delivery_description",
    "address_detail",
    "remark",
)


@traced_command("order.edit")
def update_order(
    db: Session, *, actor: User, order_id: int, body: OrderUpdate, contact_only: bool = False
) -> Order:
    """`PATCH /orders/{id}` 的应用层：改单（地址 / 收货人电话 / 配送说明 / 内部备注）。

    ⚠️ 与 `api/v1/orders_lifecycle.py::update_order` **行为逐字一致**（第二轮 R2-02 搬运）。

    `contact_only=True` 是**货主 / 批发商那一扇门**（`PATCH /orders/{id}/contact`，台账 L-27）：
    只许补联系信息（下面那道守卫），且**终态的单也能补**（见状态门处的理由）。
    """
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise CommandError("未找到对应记录", 404)
    # ⚠️ 先锁再判（2026-09-23 第 6 轮）：上面那份是**可能过期**的对象，
    #    而"判完到写之间"正是司机送达/撤销能挤进来的窗口（同 `order_products` 那一处）。
    order = lock_order_row(db, order)
    # 终态的门：整张单不再可改（地址 / 收货人与下单人电话之外的一切都动不了了）。
    finished = order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED)
    if contact_only:
        # ⛔ 下面两道守卫就是两个权限点的**分界线**：漏掉后一道的后果不是"少一层校验"，
        #    而是货主那一扇门等于整张单的编辑权（地址、内部备注、别人名下的单）。
        if all(getattr(body, f, None) is None for f in CONTACT_FIELDS):
            raise CommandError("没有要补的联系信息", 400)
        for field, label in DISPATCHER_ONLY_FIELDS:
            if getattr(body, field, None) is not None:
                raise CommandError(f"联系信息以外的内容要派单员才能改（{label}）", 403)
        # ⛔ 这一扇门**不过下面那道终态门**（台账 L-28）：风险提示盯的恰恰是"账上认不出人"的
        #    **存量**单，而存量单绝大多数已经送达/结束 —— 这条门如果连补名字都挡，"去补联系信息"
        #    就是一个点不动的死胡同（403），账本里的「未指定货主」永远消不掉。
        #    联系信息不是业务状态：它不改金额、不改库存、不改状态机（本函数只写这四个字段）。
        # ⚠️ 写成 `elif` 而不是把 `not contact_only` 并进上面那个 `if`：
        #    `_tools/qa/_check_client_contract.py` 按 `if order.status in (…): raise` 这个
        #    **字面形状**解析"哪些状态不可改"，`_tools/qa/_check_order_commands.py` 也靠同一形状
        #    对账前置状态 —— 形状一散，那两条红线就静默失效（不报错，只是永远绿）。
    elif order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED):
        raise CommandError("订单已结束，不可再编辑")
    # L-32：改单也要保证"四个联系字段不全空" —— 按**合并后的结果**判（`body` 里 None = 不改，
    # 所以拿库里的现值和请求体叠一次）：把最后一个联系方式删掉会被当场拒，只改其中一项不受影响。
    # ⚠️ 位置在字段赋值之前：这时还没动 ORM 字段，抛异常即整条回滚，不会留下"改了一半"的单。
    if contact_info_missing(merged_contact_info(order, body)):
        raise CommandError(CONTACT_INFO_REQUIRED)
    # 审计日志记哪几个字段：派单员那条路仍记原来那三项（行为冻结），货主那条路记他真能动
    # 的那四项 —— 否则日志里会出现"改了，但 change_payload 一个字都没记"。
    tracked = CONTACT_FIELDS if contact_only else DISPATCHER_TRACKED_FIELDS
    before = {f: getattr(order, f) for f in tracked}
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
    after = {f: getattr(order, f) for f in tracked}
    write_log(
        db,
        operator_id=actor.id,
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
    # ⚠️ 补联系信息那条路只在**单还没结束**时推：终态的单司机早就跑完了，补一个名字推过去
    #    只是噪音（他不会再跑这一趟）；而在途的单必须推 —— 他手上那个电话可能已经换了。
    if order.driver_id and not (contact_only and finished):
        outbox.enqueue(db, "orders.edited", {"driver_id": order.driver_id, "order_id": order.id})
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise CommandError("订单数据异常", 500)
    return full

# ========================================================================================
# 命令 order.transfer：派单期跨货主转货（CHG-0042）
#
# 为什么这一节住在 commands/order.py，而不是自己开一个 services/order_transfer.py：
#   _tools/qa/_check_order_commands.py:177 规定「订单域命令的实现只能落在
#   services/order_flow.py 或 commands.order」—— 订单域不许长出第三个家。
#   本节只负责把动作组织起来（取单 → 判前置 → 建/找目标单 → 搬明细 → 记日志 → 入队事件），
#   状态跃迁仍然只在 services/order_flow.py 里发生（作废源单借 cancel_pending）。
#
# 派单期**跨货主转货**（CHG-0042）：把一张订单里的货挪到**另一个货主**名下。
#
# ## 这个能力治的是什么（用户 2026-10-05 原话）
# 「假如 A 老板下了 50 单货、B 老板下了 40 单货，然后一起由一个司机直接发车，但 B 老板非常着急，
# 所以派单员决定将 A 的 50 单货中的 30 单货和 40 单货**合并**在一起变成 70 单货给 B 老板，
# 有时候可能是**全部货都直接给这个老板**；也有时候会把 A 的 50 单货**拆成 20 单和 30 单**，
# 另外 30 单给另一个老板 C。」
#
# 三种形状都在这里：① 部分转出（50 → 20 + 30）；② 整单转出（全部货换个货主）；
# ③ 转入时**并入**目标货主已经在途的那张单（40 + 30 = 70 —— 司机只拿一张送货单、账也只落一笔）。
#
# ## 为什么不复用既有的「拆分订单」（`services.order_flow.split_order`）
# `split_order` 拆的是**同一个货主**的货（单号加 `-1`/`-2` 后缀），货主一个都不动。
# 转货动的是**货归谁**：它决定账本行落给谁（`accounting_service` 按 `order.shipper_id` 落账）、
# 决定「已送达」通知发给谁、决定司机手上那张送货单写谁的名字。
# 两者事实不同、审计读法也不同 —— 所以是独立命令 `order.transfer` + 独立动作码 `ORDER_TRANSFER`。
# （复用 `ORDER_SPLIT` 会把「拆成两份」读成「货换主了」，反过来也一样。）
#
# ## 三条硬规矩（都是 `_tools/qa/` 的判据逼出来的，动这个文件前先读它们）
# 1. ⛔ **本模块不许写订单状态** —— `_check_status_gate_locking.py` 的 `ALLOWED_STATUS_WRITERS`
#    只有 `services/order_flow.py`。被搬空的源单要作废，一律调既有的
#    `services.order_flow.cancel_pending`：状态写入、库存释放、`ORDER_CANCEL` 审计都留在那条
#    既有链路上（⛔ 不要在这里再写一遍「撤销」）。
# 2. ⛔ **`api/` 层不许构造订单**（`_check_order_commands.py` 判据 9）—— 目标单在本模块里建，
#    构造期状态只用 `OrderStatus.PENDING_DISPATCH`（`order.create` / `order.recall` 的 to_state）。
# 3. ⛔ **本文件里只许有一处「某变量 + status + in + 元组」的写法**，且**恰好**列出
#    DELIVERED / CANCELLED / RETURNED：注册表里 `order.transfer` 的 `to_state=""`（转货本身
#    不改源单的状态，只在把货搬空时才借 `cancel_pending` 作废），判据 10 从 `def transfer_lines(`
#    截到文件末尾、把那里头的状态并成「挡掉的状态集」，要求
#    `from_states == OrderStatus 全集 − 挡掉的状态集`。⇒ 辅助函数一律写在 `transfer_lines` **之前**；
#    别处要判状态请用 `is not` / `not in` 的写法（那两种不会被那条正则认成「挡板」）。
#
# ========================================================================================


IN_TRAFFIC_STATUSES: tuple[OrderStatus, ...] = (
    OrderStatus.PENDING_DISPATCH,
    OrderStatus.DISPATCHED,
    OrderStatus.ACCEPTED,
)

#: 「货已经在这位司机手上」的两个状态（CHG-0043）：转货时按这一条决定新单跟不跟原司机。
#: ⛔ 写成模块级常量而不是函数里的一次 `status in (...)`：`_check_order_transfer.py` 判据 2 用
#:    「本函数里 `order.status in (` 恰好一处」来钉住那道**挡板**（它定义了 from_states 的补集），
#:    函数体里再出现同形状的表达式，读者与判据都会分不清哪一处是挡板、哪一处只是读一眼状态。
DRIVER_HOLDING_STATUSES: tuple[OrderStatus, ...] = (
    OrderStatus.DISPATCHED,
    OrderStatus.ACCEPTED,
)


@dataclass(frozen=True)
class TransferResult:
    """转货的结果（**事实**，不是给界面直接渲染的文案）。"""

    #: 货**现在**在哪张单上：新开的那张，或者并进去的那张。
    order: Order
    #: 源单（可能已经按「撤销」作废 —— 见 `source_cancelled`）。
    source: Order
    #: True = 目标货主原本没有在途的单，这次**新开**了一张；False = **并入**了既有的一张。
    created_target: bool
    #: True = 源单的货被这次操作**搬空**、已调 `cancel_pending` 作废。
    source_cancelled: bool
    #: 搬走的明细**行数**（不是件数：件数跨单位求和没有意义，只用于提示语）。
    moved_lines: int
    #: 新开的那张单**跟上了源单的司机**时，这位司机的显示名字；没跟= None（CHG-0043）。
    followed_driver_name: str | None = None
    #: 本来要跟、但没跟成的原因（一句人话，给界面如实说）；没这个打算或已经跟上 = None。
    follow_skipped_reason: str | None = None


def _stamp() -> str:
    """`[转货 10-05 16:39]` 里那段时间戳。

    ⛔ 必须走 `business_time`：库里存 UTC naive、界面看的是 +8，自己 `datetime.now()`
    印出来的「转货时间」会差 8 小时（`_check_single_source.py` 也禁止后端自己算日期）。
    """
    return local_stamp(utc_now_naive())


def _user_label(user: User) -> str:
    """账号在界面/审计里显示的名字：姓名 → 账号名 → #id。"""
    return (user.full_name or "").strip() or (user.username or "").strip() or f"#{user.id}"


def _note_with(old: str | None, line: str) -> str:
    """在既有内部备注后面**追一行**（⛔ 不覆盖 —— 那一栏里躺着派单员的原话）。

    分隔符与 `order_flow.assign_driver` / `split_order` 一致（`chr(10)`）；
    原备注为空时不留下开头那个空行。
    """
    head = (old or "").strip()
    return (head + chr(10) + line) if head else line


def _shipper_label(db: Session, shipper_id: int | None, temp_name: str | None) -> str:
    """货主在界面上、在审计里显示的名字：临时货主用填的那个名字，真货主用账号姓名。"""
    name = (temp_name or "").strip()
    if name:
        return name
    if shipper_id is not None:
        user = db.get(User, shipper_id)
        if user is not None:
            return _user_label(user)
    return "未指定货主"

def _resolve_target_shipper(
    db: Session, target_shipper_id: int | None, temp_name: str | None
) -> tuple[int | None, str | None, str]:
    """把「转给谁」的两个入参校验成 `(shipper_id, temp_name, 显示名)`。

    判据与 `commands/order.py::create_order` 的代理下单**同一条**：真货主必须在库里、
    角色就是货主，而且账号还活着 —— 转给一个司机/派单员的账号，货就落进一个不会收货、
    也不会出现在货主账本里的名字下。
    """
    temp = (temp_name or "").strip() or None
    if target_shipper_id is None:
        if not temp:
            raise CommandError("请选择要转给哪位货主（或填一个临时货主姓名）")
        return None, temp, temp
    user = db.get(User, target_shipper_id)
    if user is None or user_role_key(user) != UserRole.SHIPPER.value:
        raise CommandError("无效的货主")
    if not getattr(user, "is_active", True):
        raise CommandError("这个货主账号已停用，不能把货转给他；请先恢复账号或换一位货主")
    # 两个都给了：以**真货主**为准（`create_order` 也是这个口径：选了货主就不看临时名字）。
    return int(user.id), None, _user_label(user)


def _orderer_contact(db: Session, shipper_id: int | None, temp_name: str | None) -> tuple[str, str]:
    """新单上那两栏「下单人」（姓名 / 电话）。

    口径与 `commands/order.py::create_order` 的代理下单兜底**同一条**：没带下单人时，
    填的就是**这一单的货主**的账号资料 —— 转了货却把「下单人」留空，司机到了收货点
    连该打给谁都不知道。
    """
    if shipper_id is not None:
        user = db.get(User, shipper_id)
        if user is not None:
            return (user.full_name or "").strip(), (user.phone or "").strip()
    return (temp_name or "").strip(), ""


def _resync_stock_if_assigned(db: Session, order: Order, operator_id: int) -> int:
    """派单**之后**行变了才需要重算预占（没派单的单还没有预占流水）。

    与 `api/v1/order_products.py::_resync_stock_if_assigned` 是**同一道门、同一段逻辑** ——
    ⛔ 不能直接 import 那个函数：`services` 不许 import `api`（依赖方向是单向的）。
    那边改门的时候这边要跟着看（预占按商品对账，判据在 `inventory_service.resync_reservations`）。
    """
    if order.dispatched_at is None:
        return 0
    db.execute(select(Order.id).where(Order.id == order.id).with_for_update())
    return resync_reservations(db, order, operator_id)


def _collect_moves(
    db: Session, source: Order, lines: list[tuple[int, int]]
) -> list[tuple[OrderProduct, int]]:
    """校验「搬哪几行、各搬多少」并取出这些行（⛔ 一切以**库里现在的**数量为准）。

    界面上的数量可能是几分钟前读的（另一个人刚改过这一单），所以：
      · 行不属于这一单 → 拒绝（防串单）；
      · 要搬的数量 < 1，或大于这一行**现在**的数量 → 拒绝，并把现在的数量写进答复
        （「这一行现在只有 4 件」比「参数错误」有用得多）。
    """
    rows = {
        int(op.id): op
        for op in db.scalars(select(OrderProduct).where(OrderProduct.order_id == source.id))
    }
    if not rows:
        raise CommandError("这一单没有商品明细，没有可转的货")
    moves: list[tuple[OrderProduct, int]] = []
    seen: set[int] = set()
    for line_id, qty in lines:
        key = int(line_id)
        op = rows.get(key)
        if op is None:
            raise CommandError("要转的明细行不属于这一单，请刷新后重试")
        if key in seen:
            raise CommandError("同一行明细出现了两次，请刷新后重试")
        seen.add(key)
        want = int(qty)
        have = int(op.quantity or 0)
        if want < 1:
            raise CommandError("转货数量至少 1 件")
        if want > have:
            raise CommandError(
                f"「{op.product_name_snapshot}」这一行现在只有 {have}{op.unit_snapshot or ''}，"
                f"转不出 {want}；请刷新后按现在的数量再转"
            )
        moves.append((op, want))
    if not moves:
        raise CommandError("请选择要转出的商品行")
    return moves

def _find_merge_target(
    db: Session, source: Order, *, shipper_id: int | None, temp_name: str | None
) -> Order | None:
    """找**要并进去的那张单**：同一个货主、同一趟货（同一个收货地址）、还在路上、司机一致。

    ⛔ 只有**唯一**一张候选时才并：两张以上说明这趟货本来就有两张单，猜错比不并更麻烦
    （这时新开一张，派单员看得见它出现在待派单池里，要并也来得及）。
    ⛔ **不按 `order_date` 匹配**：那是「哪天下的单」，不是「哪趟货」—— A 昨天下的 50 件
    与 B 今天下的 40 件完全可能同一趟车走（用户 2026-10-05 那个场景就是这样）。
    """
    if not (source.address_detail or "").strip():
        return None
    cands = list(
        db.scalars(
            select(Order)
            .where(
                Order.id != source.id,
                Order.deleted_at.is_(None),
                Order.status.in_(IN_TRAFFIC_STATUSES),
                Order.address_detail == source.address_detail,
            )
            .order_by(Order.id)
        )
    )
    same: list[Order] = []
    for o in cands:
        if shipper_id is not None:
            if o.shipper_id != shipper_id:
                continue
        elif o.shipper_id is not None or (o.temp_shipper_name or "").strip() != (temp_name or ""):
            continue
        # 司机的口径：并进去的单不能挂在**别的**司机名下（那就成了「从别人车上抢货」）。
        # 目标单还没派单（driver_id 为空）时可以并 —— 那正是「B 的单也在等派单」的常态。
        if o.driver_id is not None and o.driver_id != source.driver_id:
            continue
        same.append(o)
    return same[0] if len(same) == 1 else None


def _load_merge_target(
    db: Session,
    source: Order,
    target_order_id: int,
    *,
    shipper_id: int | None,
    temp_name: str | None,
) -> Order:
    """派单员**指名**要并进去的那张单（界面上选出来的）—— 逐条把上面那张自动判据再问一遍。"""
    target = db.scalars(select(Order).where(Order.id == target_order_id)).first()
    if target is None or target.deleted_at is not None:
        raise CommandError("要并入的那张单不存在（可能已被删除）")
    if target.id == source.id:
        raise CommandError("不能把货并进它自己")
    if target.status not in IN_TRAFFIC_STATUSES:
        raise CommandError("要并入的那张单已经送达/撤销/退货了，不能再并货进去")
    if (target.address_detail or "").strip() != (source.address_detail or "").strip():
        raise CommandError("要并入的那张单收货地址与这一单不同，不能并（司机要跑两个地方）")
    if shipper_id is not None:
        if target.shipper_id != shipper_id:
            raise CommandError("要并入的那张单不是这位货主的")
    elif target.shipper_id is not None or (target.temp_shipper_name or "").strip() != (temp_name or ""):
        raise CommandError("要并入的那张单不是这位临时货主的")
    if target.driver_id is not None and target.driver_id != source.driver_id:
        raise CommandError("要并入的那张单已经派给别的司机了，不能并")
    return target


def _create_target_order(
    db: Session,
    source: Order,
    *,
    shipper_id: int | None,
    temp_name: str | None,
    actor: User,
) -> Order:
    """给目标货主**新开一张单**：地址/收货人/备注照抄源单（同一趟货、同一个收货地点）。

    抄什么、不抄什么，判据是「这条信息属于**这趟货**，还是属于**源单的钱与归属**」：
      · 属于这趟货 → 照抄：地址、经纬度、地点图、收货人（姓名+电话）、送货说明、备注、司机备注；
      · 属于源单的钱与归属 → **不抄**：`payment_method` / `paid` / `arrears_unit_*` /
        `collect_cash`（现金还是挂账、挂在哪个单位，是**这一位货主**的口径；`arrears_unit_id`
        是指向而不是快照，把 A 的挂账单位抄到 B 的单上，B 的账就记到 A 的单位头上了）；
        运费与司机计费快照也不抄（`split_order` 的派生单同样不带，派单员派单时再按这位司机的
        规则定价）。
    """
    boss_name, boss_phone = _orderer_contact(db, shipper_id, temp_name)
    # L-32：转货新开单也是"新的一张单"——抄完源单、补上这位货主之后仍全空就拦
    # （台账原话：「继承后仍为空 ⇒ 拦」）。临时货主那一路没有账号资料可补，最容易撞上这条。
    if contact_info_missing(
        {
            "contact_dongjia_name": source.contact_dongjia_name,
            "contact_dongjia_phone": source.contact_dongjia_phone,
            "contact_boss_name": boss_name,
            "contact_boss_phone": boss_phone,
        }
    ):
        raise CommandError(CONTACT_INFO_REQUIRED)
    target = Order(
        order_no=new_order_no(),
        # ⛔ 构造期状态只写在这里（`order.create` / `order.recall` 声明过的 to_state）：
        #    `_check_order_commands.py` 判据 9 只认「某条命令声明过的 to_state」，
        #    而状态跃迁一律在 `order_flow.py` 里 —— 本模块一个字都不写状态。
        status=OrderStatus.PENDING_DISPATCH,
        shipper_id=shipper_id,
        temp_shipper_name=temp_name,
        order_date=source.order_date,
        delivery_description=source.delivery_description,
        address_detail=source.address_detail,
        address_lat=source.address_lat,
        address_lng=source.address_lng,
        address_image_url=source.address_image_url,
        contact_dongjia_name=source.contact_dongjia_name,
        contact_dongjia_phone=source.contact_dongjia_phone,
        contact_boss_name=boss_name,
        contact_boss_phone=boss_phone,
        remark=source.remark,
        driver_remark=source.driver_remark,
        internal_notes=f"[转货 {_stamp()}] 由 {source.order_no} 转入（操作人：{_user_label(actor)}）",
        parent_order_id=source.id,
    )
    db.add(target)
    db.flush()
    return target


def _put_line(db: Session, target: Order, op: OrderProduct, qty: int) -> None:
    """把 `qty` 件搬到目标单上：**同商品同单价同单位同成本**就并进既有那一行，否则追加一行。

    ⛔ 判据里必须带上 `unit_price`（还有单位与成本快照）：单价不同的同一种商品**不许并成一行** ——
    并了就得二选一，而「这一行的单价到底按谁算」在账上再也查不出来（货款按行金额入账）。
    """
    unit = (op.unit_snapshot or "")[:32]
    price = op.unit_price if op.unit_price is not None else Decimal("0")
    for row in target.order_products:
        if (
            row.product_id == op.product_id
            and row.unit_price == op.unit_price
            and (row.unit_snapshot or "") == unit
            and row.cost_price_snapshot == op.cost_price_snapshot
        ):
            # ⛔ 件数**只能由数据库自增**，不许写成 `row.quantity = int(row.quantity or 0) + qty`：
            #    两次转货同时并进同一张单的同一行时，两边都读到同一个旧值、各自算新值，
            #    后写的把前一次转入的件数整段盖掉 —— 货搬过去了两批、账上只记一批，谁都不报错
            #    （红线 `_tools/qa/_check_counter_updates.py` 钉着；与 `auto_stock_commit` 的库存、
            #    退货的 `returned_quantity` 是同一条理由）。
            # ⚠️ 行金额必须由**同一个表达式**算出来（同一件数），分开算会出现
            #    「件数已是新值、金额还按旧件数」的行 —— 而这一行的金额是要进货款账的。
            merged = func.coalesce(OrderProduct.quantity, 0) + qty
            res = db.execute(
                update(OrderProduct)
                .where(OrderProduct.id == row.id)
                .values(
                    quantity=merged,
                    line_total=func.coalesce(OrderProduct.unit_price, 0) * merged,
                )
            )
            if res.rowcount != 1:
                # 行没了（或 id 不对）= 这一次转货的口径已经不作数，宁可整笔退回也不写半张单。
                raise CommandError(
                    f"「{op.product_name_snapshot}」这一行刚刚被另一笔操作改动了，请重新打开这张单再转"
                )
            # 让内存里那一份失效：下面按行重算预占时（`_resync_stock_if_assigned` →
            # `resync_reservations` → `_order_rows`）读的就是 `order.order_products` 这个集合，
            # 不失效它就会拿着**改动前**的件数去算差额、算出 0 来。
            db.expire(row, ["quantity", "line_total"])
            return
    target.order_products.append(
        OrderProduct(
            product_id=op.product_id,
            product_name_snapshot=op.product_name_snapshot,
            quantity=qty,
            unit_price=price,
            line_total=money(price * qty),
            cost_price_snapshot=op.cost_price_snapshot,
            unit_snapshot=unit,
        )
    )

@traced_command("order.transfer")
def transfer_lines(
    db: Session,
    *,
    actor: User,
    order_id: int,
    lines: list[tuple[int, int]],
    target_shipper_id: int | None = None,
    temp_shipper_name: str | None = None,
    merge_into_order_id: int | None = None,
) -> TransferResult:
    """把 `order_id` 那张单上的货转给**另一个货主**（或并进同货主已在途的那张单）。

    `lines` = `[(明细行 id, 要转的数量), …]`；每一行都给满数量就是**整单转出**。

    事务纪律（与 `order_flow` 的每个写操作同一条）：
      1. **先锁再判**（判据 A）：锁放在第一句，判断全在锁之后 —— 先判后锁等于没锁；
      2. 行/数量以**库里的现在值**为准，不等界面；
      3. 派过单的单要**重算预占**（`resync_reservations`）：实扣是按流水走的，
         行变了不补，库存就永久错账（见 `inventory_service.resync_reservations` 的 docstring）。
      4. 源单被搬空 → 调 `cancel_pending` 作废（⛔ 状态写入只在 `order_flow.py` 里）。
      5. **由命令层 commit**（与 `create_order` / `update_order` 同一条：命令层收尾提交，发件箱事件与业务写在同一个事务里）。
    """
    # 取单：判据 A 只要求「取锁早于第一处状态比较」，按 id 取单这一句不比较状态。
    source = db.scalars(select(Order).where(Order.id == order_id)).first()
    if source is None:
        raise CommandError("未找到对应记录", 404)
    # ⛔ 第一句就是锁（判据 A：凡出现 lock_order_row 的函数，取锁必须早于第一处状态比较）。
    order = lock_order_row(db, source)

    if order.deleted_at is not None:
        raise CommandError("这一单在回收站里，不能转货；请先恢复它")

    # ⚠️ 这是本文件**唯一**一处 `status in (…)`：判据 10 从本函数截到文件末尾，把这里列出的状态
    #    并成「挡掉的状态集」，再要求注册表里的 from_states 恰好是剩下的那三个。
    #    已送达 = 货已经算过账（`accounting_service` 按订单行落账）；已撤销/已退货 = 这一单已经结束。
    if order.status in (
        OrderStatus.DELIVERED,
        OrderStatus.CANCELLED,
        OrderStatus.RETURNED,
    ):
        raise CommandError("「已送达 / 已撤销 / 已退货」的单不能再转货：那些货已经算过账或已经退回去了")

    moves = _collect_moves(db, order, lines)
    total_rows = len(db.scalars(select(OrderProduct.id).where(OrderProduct.order_id == order.id)).all())
    empties_source = len(moves) == total_rows and all(int(qty) >= int(op.quantity or 0) for op, qty in moves)

    if empties_source and order.status == OrderStatus.ACCEPTED:
        # 司机已经接单 = 他认下的是"这一单"；把货全搬走等于撤单，而「已接单」的撤销
        # 不在 `cancel_pending` 的门里（那条路只收待派单/已派单未接单）。
        # ⇒ 整单转空这条路对「已接单」关掉：先让派单员把这一单**撤回待派单**（recall），再转。
        raise CommandError(
            "司机已经接单了，整单转空要走「撤回派单」再转（已接单的单不能直接作废）；"
            "也可以只转一部分"
        )

    # 源单是不是**已经派在某位司机手上**（CHG-0043）：是的话，这次转出去的货还在这位司机的车上 ——
    # 换的是货主，不是这一趟活儿。新开的那张单要**跟着他派出去**，而不是回待派单池等派单员再派一次；
    # 否则同一批货会裂成"一张单在司机手上、一张单在池子里"，司机那一侧的送货单也永远对不上。
    # ⚠️ 必须在任何写之前取：整单转空那条路会把源单作废（cancel_pending），作废之后不能再指望读得到。
    follow_driver_id = (
        int(order.driver_id)
        if order.driver_id is not None and order.status in DRIVER_HOLDING_STATUSES
        else None
    )

    shipper_id, temp_name, label = _resolve_target_shipper(db, target_shipper_id, temp_shipper_name)
    if shipper_id is not None and shipper_id == order.shipper_id:
        label = f"{label}（同货主并单）"

    created = False
    if merge_into_order_id is not None:
        target = _load_merge_target(
            db, order, int(merge_into_order_id), shipper_id=shipper_id, temp_name=temp_name
        )
        # 并进去的那张单也要先锁住：两个人同时往同一张单上并货，行与预占都会算重
        # （锁序恒为「源单 → 目标单」，与调用方传进来的源单一致）。
        db.execute(select(Order.id).where(Order.id == target.id).with_for_update())
    else:
        target = _find_merge_target(db, order, shipper_id=shipper_id, temp_name=temp_name)
        if target is None:
            target = _create_target_order(
                db, order, shipper_id=shipper_id, temp_name=temp_name, actor=actor
            )
            created = True
        else:
            db.execute(select(Order.id).where(Order.id == target.id).with_for_update())

    # 审计要用的行快照：**先取**再动行（`db.delete` 之后主键读起来不一定还在）。
    moved_payload: list[dict[str, Any]] = []
    for op, qty in moves:
        price = op.unit_price if op.unit_price is not None else Decimal("0")
        moved_payload.append(
            {
                "line_id": int(op.id),
                "product_id": op.product_id,
                "product_name": op.product_name_snapshot,
                "unit": (op.unit_snapshot or ""),
                "quantity": int(qty),
                "unit_price": str(price),
                "line_total": str(money(price * int(qty))),
            }
        )

    for op, qty in moves:
        _put_line(db, target, op, int(qty))
        have = int(op.quantity or 0)
        if int(qty) >= have:
            db.delete(op)
        else:
            op.quantity = have - int(qty)
            op.line_total = money((op.unit_price or Decimal("0")) * int(op.quantity))

    # ⛔ 行搬完，先把这批改动落盘、并让明细集合失效，再让预占去对账：
    #    resync_reservations 读的是「这一单现在的行」（_order_rows 优先取 relationship），
    #    而本项目的 sessionmaker 是 autoflush=False —— 不 flush 也不 expire 的话，它读到的
    #    是搬走前那份内存缓存（整行搬走的行还留在集合里、数量还是原值），差额算成 0：
    #    源单会**永久占着一批已经不存在的货**，而货已经到了目标单上（那边的占用另算）。
    #    探针实测就是这个形状（源单 p1 的 -10 赖着不动）。
    db.flush()
    db.expire(order, ["order_products"])

    source_cancelled = False
    if empties_source:
        # 货搬空了：源单借既有的「撤销」链路作废 —— 状态、库存、审计都留在 order_flow.py 里。
        cancel_pending(db, order, actor)
        source_cancelled = True

    # 预占重算：源单还剩货（或被搬空但没有派过单）时各自对账一次。
    if not source_cancelled:
        _resync_stock_if_assigned(db, order, actor.id)

    # ── 跟随原司机：新开的那张单直接派给源单的司机（CHG-0043）────────────────────────
    # 什么时候跟：源单在司机手上（follow_driver_id）＋ 这次是**新开**的一张 ＋ 那张新单还没有司机。
    #   · **并入**的那张单不跟：它本来就有自己的司机（`_find_merge_target` 只找"同一位司机、
    #     或者一辆车都还没派的"单）；而"还没派"的那种不能替他做决定 —— 那上面还压着别的货，
    #     派给谁得派单员说了算，转货这一下不该顺手替另一批货挑司机。
    # 为什么必须等**行搬完**再派：预占是在派单那一刻按整张单的现状写的（`auto_stock_out` 按行写净额），
    #   行没搬完就派，写出去的是搬之前的数；反之新单在派单前一条预占流水都没有，所以这里派完，
    #   下面那句 `_resync_stock_if_assigned(target)` 对出来的差额是 0、写不出第二笔占用。
    followed_name: str | None = None
    follow_skipped: str | None = None
    if follow_driver_id is not None and created and target.driver_id is None:
        driver = db.get(User, follow_driver_id)
        problem = ""
        if driver is None:
            problem = "原来那位司机的账号已经找不到了"
        elif user_role_key(driver) != UserRole.DRIVER.value:
            problem = "原来那位司机的账号已经不是司机了"
        elif not driver.is_active:
            problem = "原来那位司机已经停用（离职或被删除）"
        if problem:
            # 跟不上的时候**不拦这笔转货**：货主之间的事实已经成立（货搬过去了），
            # 只把"这一单落在池子里等人派"如实带回去，由界面说清楚。
            follow_skipped = f"{problem}，新单没有跟过去，已放进待派单池，请重新指派一位司机"
        else:
            # ⛔ 这里**故意不拿 SAVEPOINT 兜**（真库探针实测过的坑，2026-10-05）：
            #    `assign_driver` 在"这一单刚刚被别人派走了"那条路上会自己 `db.rollback()`
            #    （order_flow.py:171-173 那条 CAS 分支），而 SQLAlchemy 的 `Session.rollback()`
            #    回滚的是**整笔事务** —— 连 `with db.begin_nested():` 建的那个存档点一起放掉，
            #    并不是"退回到存档点"。包了存档点照样会把这笔转货**已经搬好的行**整段丢掉，
            #    而函数还会接着往下写备注 / 写审计 / 发发件箱并 commit：库里留下一句
            #    "新订单待派单"、那张单却根本不存在（探针 H 实测）。所以这里改成
            #    **失败即整笔失败**：派不出去就抛 CommandError，没有 commit ⇒ 源单没动、
            #    货也没搬，派单员重试即可 —— 宁可什么都没发生，也不许留下半笔账。
            #    三种**可预期**的"跟不上"（账号找不到 / 已经不是司机 / 已停用）在上面就挡掉了，
            #    走优雅降级那条路，不受这里影响。
            try:
                assign_driver(
                    db,
                    target,
                    driver,
                    actor,
                    f"这一趟货本来就在这位司机手上（源单 {order.order_no}），转货后跟随原司机派单",
                )
            except ValueError as e:
                raise CommandError(
                    f"新单没能派给原司机（{e}）；这笔转货没有完成（源单没动、货也没搬），请重试",
                    status_code=409,
                ) from e
            followed_name = _user_label(driver)

    # 目标单的预占对账放在**派单之后**：跟着司机走的新单，它那笔预占正是 `assign_driver` →
    # `auto_stock_out` 在派单那一刻按整张单写下的净额；这里再对一次账，差额应当是 0
    # （对不上就补一笔，`resync_reservations` 自己的口径）。没派单的目标单在这道门上直接 return。
    # ⛔ 对账前必须先 flush（会话是 autoflush=False，见 database.py:110）：`assign_driver` →
    #    `auto_stock_out` 刚写下的那些 RESERVED 流水还在会话里没落盘，而 `resync_reservations`
    #    是拿 SQL 现算"这一单已经占了多少"的 —— 不 flush 它算出来是 0，会照着 want 再写一整笔
    #    （真库探针实测：新单该占 4 件，被写成 8 件）。
    db.flush()
    _resync_stock_if_assigned(db, target, actor.id)

    # 内部备注写在**最后**（在 cancel_pending / resync 之后）：cancel_pending 里有 db.refresh(order)，
    # 而本项目的 sessionmaker 是 autoflush=False —— 先写的备注还没落盘，一次 refresh 就把它整段丢掉
    # （探针实测：整单转空那条路上，源单的「已转出给谁」整句消失）。落在最后，谁也盖不掉。
    order.internal_notes = _note_with(
        order.internal_notes,
        f"[转货 {_stamp()}] 已转出给「{label}」（{target.order_no}）：{len(moves)} 行"
        f"（操作人：{_user_label(actor)}）",
    )
    if not created:
        target.internal_notes = _note_with(
            target.internal_notes,
            f"[转货 {_stamp()}] 已从 {order.order_no} 转入：{len(moves)} 行"
            f"（操作人：{_user_label(actor)}）",
        )

    # 操作日志两行：一条挂在源单上（货出去了）、一条挂在目标单上（货进来了）。
    # 两边的 change_payload 都必须是**可 JSON 序列化**的（金额一律 str —— write_log 走
    # json.dumps，Decimal 直接塞进去会抛）。
    write_log(
        db,
        operator_id=actor.id,
        order_id=order.id,
        action=OperationAction.ORDER_TRANSFER,
        change_payload={
            "direction": "out",
            "target_order_id": int(target.id),
            "target_order_no": target.order_no,
            "target_shipper": label,
            "target_shipper_id": shipper_id,
            "created_target": created,
            "source_cancelled": source_cancelled,
            # 新开的那张单跟没跟上源单的司机（CHG-0043）：这是"这趟货归谁送"的事实，
            # 与"货归谁"记在同一行审计里。
            "followed_driver": followed_name,
            "follow_skipped_reason": follow_skipped,
            "lines": moved_payload,
        },
    )
    write_log(
        db,
        operator_id=actor.id,
        order_id=target.id,
        action=OperationAction.ORDER_TRANSFER,
        change_payload={
            "direction": "in",
            "source_order_id": int(order.id),
            "source_order_no": order.order_no,
            "source_shipper": _shipper_label(db, order.shipper_id, order.temp_shipper_name),
            "source_shipper_id": order.shipper_id,
            "followed_driver": followed_name,
            "follow_skipped_reason": follow_skipped,
            "lines": moved_payload,
        },
    )

    # 发件箱：与业务写**同一个事务**（outbox.enqueue 自己不 commit，由本层最后 commit 一次）。
    outbox.enqueue(db, "orders.pending_pool_changed", {})
    if followed_name is not None:
        # 新单**已经跟着原司机派出去了**（CHG-0043）：对司机来说这是一张**新派单**，
        # 走 orders.assigned（文案是"您有新的派单：SO…，请及时处理"）。
        # ⛔ 不能图省事复用下面那个 orders.edited：它的文案是"订单信息有修改，出车前请核对一遍"，
        #    对一个**从没见过这张单**的司机说这句，他会去找一张自己手上根本没有的单。
        outbox.enqueue(
            db, "orders.assigned", {"driver_id": int(target.driver_id), "order_id": int(target.id)}
        )
    elif created:
        # 新开的单还在池子里等派单 —— 这才是 orders.created 那句"新订单待派单"说得通的情形。
        # （跟着司机走了的单**不发**这一条：它不是待派单，派单员收到通知点进去只会扑空。）
        outbox.enqueue(db, "orders.created", {"order_id": int(target.id)})
    elif target.driver_id is not None:
        # 并进去的单已经派给某位司机了：他手上的送货单多了一项，得告诉他。
        outbox.enqueue(db, "orders.edited", {"driver_id": int(target.driver_id), "order_id": int(target.id)})
    if source_cancelled:
        recipients = [int(u) for u in (order.shipper_id, order.driver_id) if u is not None]
        outbox.enqueue(db, "orders.cancelled", {"user_ids": recipients, "order_id": int(order.id)})
    elif order.driver_id is not None:
        outbox.enqueue(db, "orders.edited", {"driver_id": int(order.driver_id), "order_id": int(order.id)})

    db.commit()
    return TransferResult(
        order=target,
        source=order,
        created_target=created,
        source_cancelled=source_cancelled,
        moved_lines=len(moves),
        followed_driver_name=followed_name,
        follow_skipped_reason=follow_skipped,
    )
