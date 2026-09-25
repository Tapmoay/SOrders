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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import outbox
from app.core.rbac import user_role_key
from app.models import Order, User
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.schemas.order import OrderCreate, OrderUpdate
from app.schemas.product_visibility import product_visible_to
from app.services import place_service, usage_service
from app.services.auth_service import new_order_no
from app.services.operation_log_service import write_log
from app.services.order_flow import build_order_products, ensure_order_date, lock_order_row
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

def update_order(db: Session, *, actor: User, order_id: int, body: OrderUpdate) -> Order:
    """`PATCH /orders/{id}` 的应用层：改单（地址 / 收货人电话 / 配送说明 / 内部备注）。

    ⚠️ 与 `api/v1/orders_lifecycle.py::update_order` **行为逐字一致**（第二轮 R2-02 搬运）。
    """
    order = db.scalars(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise CommandError("未找到对应记录", 404)
    # ⚠️ 先锁再判（2026-09-23 第 6 轮）：上面那份是**可能过期**的对象，
    #    而"判完到写之间"正是司机送达/撤销能挤进来的窗口（同 `order_products` 那一处）。
    order = lock_order_row(db, order)
    if order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED):
        raise CommandError("订单已结束，不可再编辑")
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
    if order.driver_id:
        outbox.enqueue(db, "orders.edited", {"driver_id": order.driver_id, "order_id": order.id})
    db.commit()
    full = load_order_for_response(db, order.id)
    if full is None:
        raise CommandError("订单数据异常", 500)
    return full
