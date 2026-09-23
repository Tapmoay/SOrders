from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.rbac import user_role_key
from app.models import Order, User
from app.models.enums import OrderStatus, UserRole
from app.schemas.order import OrderOut
from app.services.driver_pay import has_per_order_pay, order_mode
from app.services.order_money import OrderMoney, money_map, money_of
from app.services.soft_delete import dialable_phone


def apply_driver_view_gating(data: dict, order: Order) -> None:
    """司机视角门控（列表/详情共用）：
    1) 剥离订单明细的货款（单价/小计，司机无需看到货主货款）；
    2) 运费仅「有按单应付」的单可见，否则置 None。

    判据是**订单**上的模式（`driver_pay.has_per_order_pay`：快照优先，老单按钱那一侧的口径补），
    所以这里刻意**不接收司机对象** —— 司机换车型/换规则不影响历史订单，
    而"这一单他到底按不按单拿钱"只该有一个答案（账单怎么算，界面就怎么显示）。
    """
    per_order = has_per_order_pay(order)
    for lp in data.get("order_products", []):
        lp["unit_price"] = None
        lp["line_total"] = None
    # ⛔ 这一单的**五个钱**一起归一（2026-09-24 第 24 轮；第 22 轮 F7-1 的一半 + 本轮 08 区 D1）：
    #    上面刚把每行的 `line_total` 置空（"司机无需看到货主货款"），可是
    #    ① 本轮新加的 `goods_amount` 就是那些行之和 → 不剥等于换个地方又发一遍；
    #    ② `arrears_amount`（欠款）**同样是货款**：一张没收款、没退货的单，
    #       欠款恰好等于货款全额（本轮实测：司机能读到的 19 张单里 17 张如此，
    #       例如 2×30+3×20 的单 `arrears_amount=120.00`，与派单员的 `goods_amount` 一个数）；
    #       `settled_amount` / `returned_amount` 同理能反推出货款。
    #    所以司机视角下：`goods_amount` = None（客户端本来就是可空 String），
    #    另外四个 **= 0**（`OrderDto` 里它们是非空 `String`，发 `null` 会让客户端反序列化失败
    #    —— 那个"发 null"的口子是给 `unit_price`/`line_total`/`freight_fee` 留的）。
    #    ⚠️ 这里 0 的语义是「这一块不给你」，不是"真的没欠"；司机端界面与逻辑对这五个数
    #    **零引用**（`grep -rn "arrearsAmount\|settledAmount\|returnedAmount\|refundedAmount"
    #    android/app/src/main/java/com/tapmoay/sorders/ui/` 只命中派单员/货主页，
    #    订单详情里那排「现场支付/挂账」按钮在 `if (role == Role.DISPATCHER)` 里面）。
    #    接单/送达/收现金都不需要它：司机那三个数字（该收多少现金）界面上从来没显示过
    #    （`OrderDetailScreen.kt` 的 "收取现金（N 张）" 只有张数）。
    data["goods_amount"] = None
    data["settled_amount"] = Decimal("0")
    data["returned_amount"] = Decimal("0")
    data["refunded_amount"] = Decimal("0")
    data["arrears_amount"] = Decimal("0")
    data["freight_visible"] = per_order
    if not per_order:
        data["freight_fee"] = None


def enrich_order_out(
    order: Order, db: Session, viewer: User | None = None, money: OrderMoney | None = None
) -> OrderOut:
    """出参装配。**列表请传 `money`**（用 `money_map` 一次算好一页的钱）。

    ⚠️ 不传 `money` 时这里会为**这一张**单发 4 条分组查询（`money_of`）。
       单张详情无所谓，但列表里逐单调用就是 4×N 条 SQL —— 而
       `enrich_order_out` 本来已经在逐单 `db.get(User, …)` 了（同类问题的实测代价
       见 `ledger_response.py`：85,474 行 → 27.75 秒）。所以列表端点走批次。
    """
    data = OrderOut.model_validate(order).model_dump()
    if order.driver_id:
        du = db.get(User, order.driver_id)
        if du:
            # ⚠️ **去软删后缀**：`DELETE /users/{id}` 会把 `phone` 改写成 `原值_del{id}`
            #    （`services/soft_delete.py::del_suffix`，为了把号码释放给新账号用），
            #    而这个司机早先拉过的单还挂着他的 `driver_id` —— 直接下发就是把
            #    `13800001234_del160` 印在订单详情上，而详情页那一行现在带**拨号按钮**
            #    （2026-09-22 用户要的"拨打司机电话"）：拿去拨就是一个打不通的号。
            #    同一处理已在两处做过（`api/v1/ledger.py`、`api/v1/freight_settlement.py`），
            #    这里是第三个消费点 —— 口径只有一处：`soft_delete.dialable_phone`。
            #    ⚠️ 2026-09-24 第 20 轮（D9-F3）：**活账号带后缀 = 那号码已经不是他的**
            #    （恢复时撞号，`users.restore_user` 保留后缀）→ 那种账号**不给号码**，
            #    否则拨号键会把派单员接到抢走这个号的另一个人那里。
            data["driver_phone"] = dialable_phone(du)
            data["driver_name"] = du.full_name or ""
            data["driver_billing_mode"] = order_mode(order)
    su = db.get(User, order.shipper_id) if order.shipper_id is not None else None
    if su is not None:
        data["shipper_name"] = su.full_name or su.phone or ""
    else:
        tn = (order.temp_shipper_name or "").strip()
        data["shipper_name"] = tn or None
    data["is_new_for_driver"] = bool(
        order.status in (OrderStatus.DISPATCHED, OrderStatus.ACCEPTED)
        and order.driver_id is not None
        and order.driver_acknowledged_at is None
    )
    # 这一单的钱：口径只有 `services/order_money.py` 一处（退货红冲、部分核销、现场收现金
    # 三件事都在这三个数里体现，客户端不许自己再加一遍）
    m = money or money_of(db, order)
    # 订单金额（Σ 商品行 line_total）：界面上的「订单金额」就是它，而在这之前**出参里没有它**
    # —— 客户端自己 Σ、AI 拿不到（第 22 轮 F7-1：问"这单多少钱"只能拿 arrears 顶替 → 答成 0 元）。
    data["goods_amount"] = m.total
    data["returned_amount"] = m.returned
    data["settled_amount"] = m.settled
    data["refunded_amount"] = m.refunded
    data["arrears_amount"] = m.arrears
    if viewer is not None:
        role = user_role_key(viewer)
        if role == UserRole.SHIPPER.value:
            data["internal_notes"] = ""
            # ⛔ **货主不该看到「公司付给司机多少」**（2026-09-23 第 17 轮并行渗透抓到）：
            #    原来这里把 `freight_visible` 置 True，而 `freight_fee` / `driver_billing_mode`
            #    照旧原样下发 —— 实测货主读自己的单与派单员**逐字节相同**。
            #    界面上这一块本来就是**派单员专属**（`ui/order/OrderDetailScreen.kt:970-971`
            #    按 `role == DISPATCHER` 判），AI 的行格式化也把它原样带出去
            #    （`ai/AiResources.kt`）—— 也就是说：界面上藏住了、接口与 AI 都没藏。
            #    这是**公司的成本**（他卖货给客户，运费是公司付给司机的钱），露出去了等于把毛利给了客户。
            #    口径与司机视角那条**同一个位置**（[apply_driver_view_gating]）：都是"这一块不该给他"。
            data["freight_visible"] = False
            data["freight_fee"] = None
            data["driver_billing_mode"] = None
        elif role == UserRole.DISPATCHER.value:
            data["freight_visible"] = True
        elif role == UserRole.DRIVER.value and order.driver_id is not None:
            # 司机视角统一门控：剥离货款；运费按**这一单**的模式（快照优先，老单与账单同口径）
            apply_driver_view_gating(data, order)
    return OrderOut(**data)


def load_order_for_response(db: Session, order_id: int) -> Order | None:
    return db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
