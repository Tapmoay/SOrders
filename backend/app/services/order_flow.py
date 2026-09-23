from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import InvalidRequestError as SaInvalidRequest
from sqlalchemy.orm import Session

from app.core.business_time import business_today, local_stamp
from app.core.rbac import user_role_key
from app.models import Order, User
from app.models.order import OrderProduct
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.services.accounting_service import post_delivery_accounting
from app.services.driver_pay import (
    ZERO,
    dispatch_mode,
    has_per_order_pay,
    money,
    override_problem,
    rule_of_user,
    rule_to_snapshot,
)

#: 客户端行金额与「单价×数量」允许的差（一分）：只用来吸收客户端的四舍五入，
#: 不是"可以随便差一点"。见 [resolve_line_total]。
LINE_TOTAL_TOLERANCE = Decimal("0.01")
from app.services.inventory_service import auto_stock_commit, auto_stock_out, auto_stock_release
from app.services.warehouse import auto_warehouse_inbound, warehouse_for_order
from app.services.ledger_sync import sync_ledger_from_delivered_order
from app.services.operation_log_service import write_log


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dec_for_json(x: Any) -> Any:
    if x is None:
        return None
    if isinstance(x, Decimal):
        return str(x)
    return x


def order_snapshot_for_log(db: Session, order: Order) -> dict[str, Any]:
    """撤回派单等场景写入操作日志的订单快照（派单前状态）。"""
    shipper = db.get(User, order.shipper_id) if order.shipper_id is not None else None
    driver = db.get(User, order.driver_id) if order.driver_id else None
    lines: list[dict[str, Any]] = []
    for op in order.order_products:
        lines.append(
            {
                "product_name_snapshot": op.product_name_snapshot,
                "quantity": op.quantity,
                "unit_price": str(op.unit_price),
                "line_total": str(op.line_total),
            }
        )
    st = order.status.value if hasattr(order.status, "value") else str(order.status)
    return {
        "order_no": order.order_no,
        "status": st,
        "shipper_id": order.shipper_id,
        "shipper_name": (shipper.full_name or shipper.phone) if shipper else None,
        "driver_id": order.driver_id,
        "driver_name": (driver.full_name or driver.phone) if driver else None,
        "delivery_description": order.delivery_description,
        "address_detail": order.address_detail,
        "address_lat": _dec_for_json(order.address_lat),
        "address_lng": _dec_for_json(order.address_lng),
        "contact_dongjia_phone": order.contact_dongjia_phone,
        "contact_boss_phone": order.contact_boss_phone,
        "remark": order.remark,
        "internal_notes": order.internal_notes,
        "dispatched_at": order.dispatched_at.isoformat() if order.dispatched_at else None,
        "order_products": lines,
    }


def lock_order_row(db: Session, order: Order) -> Order:
    """把这个订单行**锁住并读到最新值**，返回**可用的那个对象**（并发保护，v3.39）。

    ### 为什么需要它
    这一系列状态跃迁（派单/接单/送达/撤回/撤销）全是"**读状态 → 判断 → 写**"，
    中间没有任何锁：两个请求同时打到同一张单上（司机手滑点两下、网络重试、
    派单员两台设备），两边都能通过 `status != PENDING_DISPATCH` 那道检查，
    然后**各自往下走**——订单被派给两个人、同一张单生成两条司机账单、
    同一张单被核销两次，都是这么来的。

    `with_for_update()` 在 MySQL 上是 `SELECT … FOR UPDATE`（行锁，第二个请求会等第一个提交，
    提交后再读就是新状态，于是判据生效）；SQLite 不支持行锁，SQLAlchemy 会**忽略**它
    （本地开发行为不变，测试照跑）。

    ### ⚠️ 为什么不能只写一行 `db.refresh(order, with_for_update=True)`
    第一版就是那一行，结果在**并发重复提交**下自己变成 500（2026-09-18 重放测试实测）：
    `sqlalchemy.exc.InvalidRequestError: Could not refresh instance '<Order at 0x…>'`
    —— 另一个请求刚把这行改到终态（或让本会话里那份实例失效）时，`refresh` 取不回那一行。

    "锁不住"和"崩"是两件事：这里必须**退化成重新查一次**，并且把查到的对象**返回**给调用方，
    让调用方基于最新状态继续判（`order` 那份旧对象不能再用了）。
    """
    try:
        db.refresh(order, with_for_update=True)
        return order
    except SaInvalidRequest:
        fresh = db.scalars(
            select(Order).where(Order.id == order.id).with_for_update()
        ).first()
        if fresh is None:
            # 走到这里说明这一行在并发期间真的没了（另一个请求删/撤了它）。
            # 与模块里其他错误一致地抛 ValueError，由 API 层转成中文提示。
            raise ValueError("订单不存在或已被删除")
        return fresh


def assign_driver(
    db: Session,
    order: Order,
    driver: User,
    operator: User,
    internal_note: str | None = None,
    piece_override=None,
    rate_override=None,
) -> None:
    # 先锁行再判状态：并发派单会两个请求都通过下面那道检查，把同一张单派给两个人。
    # ⚠️ 用返回的对象（锁行失败时它会退化成"重新查一次"的那个新对象，手上的 order 可能已失效）
    order = lock_order_row(db, order)
    if order.status != OrderStatus.PENDING_DISPATCH:
        raise ValueError("仅「待派单」状态可派单")
    # ⚠️ 隔离区（已进回收站）的单不许派（2026-09-19 审计 R13-D1 同族）：
    #    派了会给司机推「新派单」，而司机点进去是 404（读侧对非派单员一律"订单不存在"），
    #    撤回派单又会因为它的 CAS 要求 `deleted_at is None` 而失败——这张单只能靠 restore 解开。
    if order.deleted_at is not None:
        raise ValueError("这一单已被删除（在回收站里），不能派单；请先恢复它。")
    if user_role_key(driver) != UserRole.DRIVER.value:
        raise ValueError("派单目标须为司机账号")
    # ⚠️ **必须校 is_active**（2026-09-19 审计）。这是全后端唯一一处派单写入，也是唯一的闸：
    #    人工派单界面（`DispatcherPoolViewModel` 的 `filter { it.isActive }`）是**客户端**过滤的，
    #    而 AI 的司机名册（`AppRepository.drivers()`）没有过滤——所以"把单派给已离职的王师傅"
    #    在 AI 路径上是走得通的，卡片还长得完全合理（后端给的 paySummary 看不出账号已停用）。
    #    后果不是报错，而是**静默卡死**：`deps.py` 与 socket 握手都会拦 is_active=False 的登录、
    #    消息也只推给 active 收件人 → 司机登不进来、收不到推送、这单永远停在「派单中」，
    #    不在待派池里、没人能完成它，只能靠人工发现后撤回派单。
    if not getattr(driver, "is_active", True):
        raise ValueError("这个司机账号已停用（离职或被删除），不能派单；请先恢复账号或换一位司机")
    # 逐单覆盖值先验：**填了不生效**（司机没挂规则、规则里没有提成项）要在这里拦掉，
    # 不能收下再默默按规则算——先验再做，失败时订单一个字段都没动过（批量派单靠这个回滚）。
    rule = rule_of_user(driver)
    problem = override_problem(rule, piece_override=piece_override, rate_override=rate_override)
    if problem:
        raise ValueError(problem)

    # ---- 原子占位：把「待派单 → 派单中」这件事**只让一个请求做成** ----
    # 与 `complete_delivery` 同一条理由：SQLite 不认 `FOR UPDATE`，
    # 两个并发派单会各自通过上面的状态检查，把同一张单派给两个司机。
    claimed = db.execute(
        update(Order)
        .where(
            Order.id == order.id,
            Order.status == OrderStatus.PENDING_DISPATCH,
            # 隔离区的单不许派（同上）：判完到写之间被删掉的话，这里再挡一次
            Order.deleted_at.is_(None),
        )
        .values(status=OrderStatus.DISPATCHED, driver_id=driver.id, dispatched_at=_now())
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise ValueError("这一单已经被派过了（重复提交或两个人在同时派单），请刷新后查看")
    db.refresh(order)

    order.status = OrderStatus.DISPATCHED
    order.driver_id = driver.id
    order.dispatched_at = _now()
    # 司机计费方式快照：司机换类型后，历史订单可见性仍按派单当时判定
    #
    # ⚠️ 语义（v3.36 起明确）：**这张单司机按不按单拿钱**。PIECE = 有按单应付、SALARY = 只拿月薪。
    #    所以它不再等于"用户表里那个 billing_mode"——司机挂了计费规则时由规则决定（见 driver_pay.snapshot_mode）。
    #    快照**两份**都要定格：模式（给可见性/结算页筛选用）+ 规则参数（给金额用）。
    #    规则后来被改了，已经派出去的单不能跟着变——这是"账单是钱"的底线。
    order.driver_billing_mode_snapshot = dispatch_mode(
        driver, piece_override=piece_override, rate_override=rate_override
    )
    order.driver_rule_snapshot = rule_to_snapshot(rule)
    # 派单员对这一单单独定的数（v3.37）：和快照同一处落库，免得"快照说按单付钱、
    # 金额却没人写"这种半截状态。None = 这一单不特殊，用规则里的值。
    #
    # ⚠️ **无条件赋值**（2026-09-19 审计 R12-M1）：原来写成 `if piece_override is not None:`，
    #    于是"这次没单独定钱"**不会清掉上一次定过的数**——撤回派单再派给别人时，
    #    上一个司机的金额会原样跟着新司机走（账单按上一个司机的数字算，note 还印着
    #    「（这一单单独定的）」，看起来像有人故意定的）。字段自己的注释就写着
    #    "None = 这一单不特殊"，实现必须与这句话一致：**没给就是不特殊**。
    order.driver_piece_amount = piece_override
    order.driver_commission_rate = rate_override
    order.driver_acknowledged_at = None
    auto_stock_out(db, order, operator.id)
    if internal_note and internal_note.strip():
        # ⛔ 时间戳按**业务当地时刻**印（`local_stamp` 唯一实现）：原来 `_now()` 是 UTC，
        #    当地 09-21 07:10 派单写的备注在单子上印成 `[派单指派 09-20 23:10]` ——
        #    而这段文本写进 `internal_notes` 后不可改（2026-09-23 第 18 轮 A2-3）。
        prefix = f"[派单指派 {local_stamp(_now())}] "
        order.internal_notes = (order.internal_notes or "").strip()
        if order.internal_notes:
            order.internal_notes += "\n"
        order.internal_notes += prefix + internal_note.strip()
    write_log(
        db,
        operator_id=operator.id,
        order_id=order.id,
        action=OperationAction.ORDER_DISPATCH,
        change_payload={"driver_id": driver.id, "internal_note": (internal_note or "").strip() or None},
    )




def allocate_split_quantities(qty: int, parts: list[int]) -> list[int]:
    """把 [qty] 件按 [parts] 比例分给 N 份，**保证合计恒等于 qty**（最大余数法）。

    单独抽成函数是为了能单测（`tests/test_split_quantities.py`）——
    这段算法藏在 `split_order` 里的时候，"3 件拆 2 单变 4 件"这种错没有任何东西会拦住它。

    @raises ValueError 比例里有 0 或负数、或只有一份
    """
    if len(parts) < 2:
        raise ValueError("请至少拆分为 2 单")
    if any(p <= 0 for p in parts):
        raise ValueError("每份比例必须大于 0")
    total_w = sum(parts)
    n = len(parts)
    if qty <= 0:
        return [0] * n
    # 份数比件数还多：前面的单各拿 1 件，后面的单拿 0 件（合计仍等于 qty）
    if qty < n:
        return [1] * qty + [0] * (n - qty)
    raw = [qty * w / total_w for w in parts]
    base = [int(x) for x in raw]
    rest = qty - sum(base)
    # 余数按"小数部分大的先补"，平票时按份的顺序（= 余数归首份）
    order_by_frac = sorted(range(n), key=lambda i: (-(raw[i] - base[i]), i))
    for i in order_by_frac[:rest]:
        base[i] += 1
    # 取整后可能出现 0 件的一份（比例悬殊时）→ 从件数最多的那份挪一件过来，
    # 否则那个子单是一张空单（没有商品行、金额为 0，用户会以为系统出错）
    for i in range(n):
        if base[i] == 0:
            donor = max(range(n), key=lambda j: base[j])
            if base[donor] > 1:
                base[donor] -= 1
                base[i] += 1
    assert sum(base) == qty, f"拆分件数合计 {sum(base)} != 原数量 {qty}（算法错了）"
    return base


def split_order(
    db: Session,
    order: Order,
    parts: list[int],
    operator: User,
) -> list[Order]:
    """待派单拆分为 N 个子单（parts 为各份比例，数量按比例拆分，余数归首份）；
    原单撤销留痕并可追溯。返回新建子单列表。

    ### 件数分配：**最后一单拿剩下的**，不是各自四舍五入
    以前每一单都算 `max(1, round(数量 × 本份比例))`，于是**各单四舍五入的误差会累加**，
    合计和原单对不上（数学上必然发生，不是偶发）：
    - 3 件拆 2 单（各 1/2）→ round(1.5)=2 + 2 = **4 件**（凭空多一件）；
    - 100 件拆 3 单（各 1/3）→ 33+33+33 = **99 件**（少一件）；
    - 1 件拆 2 单 → max(1, round(0.5))=1 + 1 = **2 件**（一件货变两件）。
    多出来/少掉的货会一路带进 `line_total`、库存流水和账本，而"件数对不上"这件事
    **在拆分界面上看不出来**（卡片只显示比例）。

    现在的算法是标准的"最大余数法"：先按比例取整份，再把差额补给前几单，
    保证**每个商品行的合计恒等于原数量**（单测钉住了 3 拆 2、100 拆 3、1 拆 2 这三种情形）。
    """
    if order.status != OrderStatus.PENDING_DISPATCH:
        raise ValueError("仅「待派单」订单可拆分")
    if len(parts) < 2:
        raise ValueError("请至少拆分为 2 单")
    if any(p <= 0 for p in parts):
        raise ValueError("每份比例必须大于 0（全是 0 的话没法按比例分）")
    total_w = sum(parts)
    if total_w <= 0:
        raise ValueError("比例合计必须大于 0")
    lines = list(order.order_products)
    if not lines:
        raise ValueError("订单无商品明细，无法拆分")

    # ⚠️ **原子占位**（2026-09-23 并发实测补；与 `assign_driver` / `cancel_pending` /
    #    `recall_dispatch` / `complete_delivery` 同一手法）。
    #
    #    这里原来是本文件里**最后一处**"先读状态、再无条件赋值"的跃迁：
    #    并发实测（`_tools/perf/_concurrency_probe.py`）拿 3 个线程同时点拆单，
    #    结果是"1 个成功 + 1 个 409 + 1 个 400"——第二个请求之所以没拆成，
    #    靠的不是状态机，而是子单 `order_no` 的**唯一约束**兜底，报出来的话是
    #    「已经有一条一模一样的记录了（同名/同号/同电话不能重复），请换一个再试」：
    #    用户只是双击了一下按钮，却被告知"重名了、换一个"。
    #    更要紧的是：唯一约束只挡得住**同一批子单号**的重复，它挡不住任何"以后新增的
    #    拆分副作用"（比如先扣库存再建子单的顺序一变，第一次的副作用就留下来了）。
    #    所以抢占必须发生在**建子单之前**：抢不到 = 已经有人拆/派/撤了，报一句人话。
    claimed = db.execute(
        update(Order)
        .where(
            Order.id == order.id,
            Order.status == OrderStatus.PENDING_DISPATCH,
            Order.deleted_at.is_(None),
        )
        .values(status=OrderStatus.CANCELLED, cancelled_at=_now())
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise ValueError("这张单刚刚被别的操作改过（可能已被派单/撤销/拆分），请刷新后再试")
    db.refresh(order)

    # 逐行预先算好"这一行的 N 份各多少件"，保证合计 == 原数量
    alloc: list[list[int]] = [allocate_split_quantities(int(lp.quantity or 0), parts) for lp in lines]

    created: list[Order] = []
    for idx, wgt in enumerate(parts):
        child = Order(
            order_no=order.order_no + "-" + str(idx + 1),
            status=OrderStatus.PENDING_DISPATCH,
            shipper_id=order.shipper_id,
            temp_shipper_name=order.temp_shipper_name,
            order_date=order.order_date,
            delivery_description=order.delivery_description,
            address_detail=order.address_detail,
            address_lat=order.address_lat,
            address_lng=order.address_lng,
            address_image_url=order.address_image_url,
            contact_dongjia_phone=order.contact_dongjia_phone,
            contact_boss_phone=order.contact_boss_phone,
            remark=order.remark,
            internal_notes=f"[拆分 {idx + 1}/{len(parts)}] 由 {order.order_no} 拆分",
            driver_remark=order.driver_remark,
            payment_method=order.payment_method,
            arrears_unit_id=order.arrears_unit_id,
            arrears_unit_name=order.arrears_unit_name,
            parent_order_id=order.id,
        )
        for li, lp in enumerate(lines):
            qty = alloc[li][idx]
            if qty <= 0:
                # 0 件的商品行不建（建了就是一张"有行无货"的子单，
                # 金额 0、库存 0，只会让子单看起来像坏了）
                continue
            child.order_products.append(
                OrderProduct(
                    product_id=lp.product_id,
                    product_name_snapshot=lp.product_name_snapshot,
                    quantity=qty,
                    unit_price=lp.unit_price,
                    line_total=lp.unit_price * qty,
                    # 成本快照要跟着拆：不带的话子单的毛利按 0 成本算（虚高）
                    cost_price_snapshot=lp.cost_price_snapshot,
                    # 单位也要跟着拆：漏了它子单上就是"3 件"（而父单是"3 箱"），
                    # 司机照着件数点货，数量对不上又查不出为什么
                    unit_snapshot=(lp.unit_snapshot or "")[:32],
                )
            )
        db.add(child)
        created.append(child)
    # ⚠️ 状态与 `cancelled_at` **已经由上面那次条件 UPDATE 写好**（不要再赋值一次：
    #    多一处无条件赋值就多一条绕过占位的路，而且 `_now()` 会写成第二个时刻）。
    auto_stock_release(db, order, operator.id)
    order.internal_notes = (order.internal_notes or "").strip() + chr(10) + "[拆分] 已拆分为 " + str(len(parts)) + " 单"
    write_log(
        db,
        operator_id=operator.id,
        order_id=order.id,
        action=OperationAction.ORDER_SPLIT,
        change_payload={"parts": parts, "children": [c.order_no for c in created]},
    )
    db.flush()
    return created



def complete_delivery(
    db: Session,
    order: Order,
    driver: User,
    delivery_photo_urls: list[str],
    driver_remark: str = "",
    damage_items: list | None = None,
    damage_note: str = "",
) -> None:
    """将订单置为已送达；同步货主账本（与明细行幂等）并执行账务钩子（司机应付明细+货损记账）。

    damage_items: [{order_product_id, quantity}] 商品行级货损（选填，公司自担）；damage_note 订单级备注。
    """
    # 先锁行再判状态：司机手滑点两下/网络重试时，两个请求都会通过下面那道检查，
    # 各自往下走 → **同一张单生成两条司机账单**（钱）。
    order = lock_order_row(db, order)
    # ⚠️ **隔离区（已进回收站）的单不许送达**（2026-09-19 审计 R13-D1）：
    #    读侧对所有非派单员是 404（`orders.py` 的 `_get_order_scoped`：「订单不存在」），
    #    而送达这条写路径原来**完全不看 `deleted_at`** —— 司机端手上那一页还停在旧数据时
    #    点「送达」，接口返回 200：库存照扣、账本照入、**司机应付账单照生成**，
    #    而这张单在司机/货主/派单员的普通查询里全都不存在（只有 `deleted_only=true` 看得到）。
    #    30 天后它被物理清理，那笔 OPEN 应付随之作废（R12-H4 现在至少会发一条通知）——
    #    但司机这一趟是白跑的，而全程没有任何界面提示过这张单已经不存在。
    #    判据与同一批状态跃迁里做对了的几处同源：driver-ack / 撤销 / 撤回 的 CAS 都带 `deleted_at is None`。
    if order.deleted_at is not None:
        raise ValueError("这一单已经被删掉了（在回收站里），不能送达。请让派单员确认这一单的归属。")
    if order.status != OrderStatus.ACCEPTED:
        raise ValueError("仅「已接单」订单可完成配送")
    if order.driver_id != driver.id:
        raise ValueError("非本单指派司机，无法操作")
    if not delivery_photo_urls:
        # 免拍照只给"这张单不按单拿钱"的（工资制）单，判据与账单一处：`driver_pay.has_per_order_pay`
        # （快照优先，老单按钱那一侧的口径补）。原来这里按司机**现在**的车型/计费兜底 ——
        # 同一张老单会"免了拍照、却在按单给他结账"。
        if not has_per_order_pay(order):
            raise ValueError("请至少上传一张送达照片")
    # ⛔ 照片必须是**本系统送达上传端点**的产物（2026-09-19 全项目报告 L-14，低）：
    #    上面只判了"列表非空"，于是 `["x"]` 就算履行了拍照义务 —— 而这条义务的意义是
    #    "送到时留证"，随手编一个字符串就绕过去了。判据取上传端点唯一的产物形状
    #    （`orders.py::_save_delivery_uploads` → `/static/uploads/delivery/{order_id}/{uuid}.{ext}`）。
    #    两条送达路径都经过这里：`complete-with-upload` 的 URL 本来就是服务端生成的，
    #    旧 H5 / API 调用方走 `POST /orders/{id}/delivery-photos` 拿到的也是这个形状。
    #    ⚠️ 刻意**不**校验"文件是否存在 / 是否属于本单"：那要把文件系统拉进业务层，
    #    而且会让 15 份用假 URL 的测试夹具与历史数据一起被牵连，与这条的危害不成比例。
    bad_photos = [u for u in delivery_photo_urls if not str(u).startswith("/static/uploads/delivery/")]
    if bad_photos:
        raise ValueError("送达照片必须是本系统上传的凭证：请用「拍照送达」重新上传后再提交")

    # ---- 原子占位：把「已接单 → 已送达」这件事**只让一个请求做成** ----
    #
    # ⚠️ 为什么光有 `with_for_update()` 不够（2026-09-18 实测复现）：
    # SQLite **不支持 `SELECT … FOR UPDATE`**，SQLAlchemy 会把它忽略掉。
    # 本地两个并发 `complete` 于是都读到 ACCEPTED、都往下走，
    # 结果**同一张单生成了两条 60 元的司机账单**（钱付两次）。
    # MySQL 上行锁能挡住，但"只在生产有效"的保护等于本地测不出来。
    #
    # 改成**条件 UPDATE**（compare-and-set）：`WHERE status='ACCEPTED'` 由数据库
    # 在写入时再判一次，SQLite / MySQL 都一样原子。改到 0 行的人立刻出局。
    claimed = db.execute(
        update(Order)
        .where(
            Order.id == order.id,
            Order.status == OrderStatus.ACCEPTED,
            # 同上：CAS 里也要带这一条，否则"判完到写之间被删掉"仍会落成一张看不见的已送达单
            Order.deleted_at.is_(None),
        )
        .values(status=OrderStatus.DELIVERED, delivered_at=_now())
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise ValueError("这一单已经被处理过了（重复提交或两个人在同时操作），请刷新后查看")
    db.refresh(order)  # 让内存对象与库一致（后面还要读它的状态/行）

    order.status = OrderStatus.DELIVERED
    order.delivery_photo_urls = delivery_photo_urls
    order.driver_remark = driver_remark
    order.delivered_at = _now()
    write_log(
        db,
        operator_id=driver.id,
        order_id=order.id,
        action=OperationAction.ORDER_COMPLETE,
        change_payload={"photos": len(delivery_photo_urls)},
    )
    sync_ledger_from_delivered_order(db, order)
    auto_stock_commit(db, order)
    # ---- 到仓入库：**独立的一条线**（用户 2026-09-19：「再开一条计算线，这条线是独立算的…
    #      入库就正常入；直到那个订单完成了之后它才会减库存」）----
    #
    # ⛔ 它与上面那行 `auto_stock_commit` **各算各的**：那条是"订单把货扣掉"，这条是
    #    "货进了仓库"。所以这里**不撤销预占、也不改扣减** —— 想改的是另一条决策。
    # 判据（"这一单是不是送到仓库的"）在 `services/warehouse.py`，只有一处实现。
    wh = warehouse_for_order(db, order)
    if wh is not None:
        # 记在订单备注里了吗？没有 —— 用一条操作日志留痕（审计页能查到"谁的单入了哪个仓"）。
        write_log(
            db,
            operator_id=driver.id,
            order_id=order.id,
            action=OperationAction.ORDER_COMPLETE,
            change_payload={
                "warehouse_inbound": wh.name or wh.detail_address,
                "warehouse_id": wh.id,
            },
        )
        inbound = auto_warehouse_inbound(db, order, driver.id)
        if inbound["skipped"]:
            # ⛔ **没入库的那几行必须说出来**：商品在商品管理里找不到（或同名不唯一）时
            #    这一行不会入库，而用户看到的是"已送达" —— 不说的话他会以为货已经进库了。
            write_log(
                db,
                operator_id=driver.id,
                order_id=order.id,
                action=OperationAction.ORDER_COMPLETE,
                change_payload={"warehouse_inbound_skipped": inbound["skipped"]},
            )
    # 货损录入（选填）：写商品行/订单备注，随后统一账务钩子
    from decimal import Decimal as _Dec

    if damage_items:
        for item in damage_items:
            op = next((x for x in order.order_products if x.id == item.order_product_id), None)
            if op is None:
                raise ValueError("货损商品行不存在")
            qty = int(item.quantity or 0)
            if qty < 0:
                raise ValueError("货损数量不能为负")
            if qty > op.quantity:
                raise ValueError(f"货损数量超过该行数量（{op.quantity}）")
            op.damage_quantity = qty
        order.damage_note = (damage_note or "").strip()
    # 账务钩子：PIECE 应付明细 + 货损 LOSS/COGS 冲回（幂等）
    warnings = post_delivery_accounting(db, order, operator_id=driver.id)
    # 「没记成」的必须留痕：司机报的货损在没有成本价时算不出金额，
    # 以前是**把数量直接抹成 0**（用户什么都看不到）。现在数量留着，
    # 事实写进操作日志——报表中心「异常与审计」里查得到。
    for w in warnings:
        write_log(
            db,
            operator_id=driver.id,
            order_id=order.id,
            action=OperationAction.ORDER_COMPLETE,
            change_payload={"damage_not_booked": w},
        )


def cancel_pending(
    db: Session,
    order: Order,
    operator: User,
) -> None:
    # ⚠️ 条件 UPDATE 占位（2026-09-19 审计）：原来这里是"读状态 → 判断 → 赋值"，
    #    中间没有锁也没有 CAS，而这个状态跃迁与**司机的接单/送达**是并发的
    #    （派单员两台设备、或司机在别人撤销的同时点接单）。真实后果：
    #      · 撤销 × 接单：撤销把行写成 CANCELLED 并释放了预占，接单又把行覆盖回 ACCEPTED
    #        → 单子"复活"但预占已经没了 → 送达时 `auto_stock_commit` 查不到 RESERVED **库存永远不扣**；
    #      · 已送达的单被打回（撤回 × 送达）会让同一批货扣两次。
    #    作业同 `assign_driver`/`complete_delivery`：把跃迁本身变成"改到行的人才能继续"。
    allowed = (OrderStatus.PENDING_DISPATCH, OrderStatus.DISPATCHED)
    if order.status not in allowed:
        raise ValueError("仅「待派单/已派单（司机未接单）」订单可按此流程撤销")
    claimed = db.execute(
        update(Order)
        .where(Order.id == order.id, Order.status.in_(allowed), Order.deleted_at.is_(None))
        .values(status=OrderStatus.CANCELLED, cancelled_at=_now())
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise ValueError("这张单刚刚被别的操作改过（可能已被接单/送达/撤销），请刷新后重试")
    db.refresh(order)
    auto_stock_release(db, order, operator.id)
    write_log(
        db,
        operator_id=operator.id,
        order_id=order.id,
        action=OperationAction.ORDER_CANCEL,
        change_payload={"by": "shipper_or_dispatcher"},
    )


def recall_dispatch(
    db: Session,
    order: Order,
    operator: User,
    reason: str,
) -> None:
    allowed = (OrderStatus.DISPATCHED, OrderStatus.ACCEPTED)
    if order.status not in allowed:
        raise ValueError("仅「已派单/已接单」订单可撤回派单")
    snapshot = order_snapshot_for_log(db, order)
    recalled_driver_id = order.driver_id
    # ⚠️ 条件 UPDATE 占位（2026-09-19 审计，理由同 `cancel_pending`）：
    #    撤回 × 送达并发时，撤回的无条件赋值会把**已送达**的单覆盖回「待派单 + 无司机」，
    #    于是同一张单能被再派一次、库存与货损各记两次（唯一索引只挡得住账单那一处）。
    claimed = db.execute(
        update(Order)
        .where(Order.id == order.id, Order.status.in_(allowed), Order.deleted_at.is_(None))
        .values(
            status=OrderStatus.PENDING_DISPATCH,
            driver_id=None,
            dispatched_at=None,
            driver_acknowledged_at=None,
            # ⚠️ 逐单覆盖值必须**一起清掉**（2026-09-19 审计 R12-M1）：它们是"给**这个**司机
            #    单独定的数"，撤回之后这张单没有司机了。不清的话，下一次派给别人时
            #    `assign_driver` 读到的是上一个司机的数字 → 账单按**上一个司机**算钱
            #    （实测口径：这单运费 1000、残留覆盖 300+8% → 账单 380，而新司机的规则只该 350）。
            driver_piece_amount=None,
            driver_commission_rate=None,
        )
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise ValueError("这张单刚刚被别的操作改过（可能已送达/已撤销），请刷新后再撤回")
    db.refresh(order)
    auto_stock_release(db, order, operator.id)
    write_log(
        db,
        operator_id=operator.id,
        order_id=order.id,
        action=OperationAction.ORDER_RECALL,
        change_payload={
            "reason": reason,
            "recalled_driver_id": recalled_driver_id,
            "order_snapshot": snapshot,
            "recalled_at": _now().isoformat(),
        },
    )


def ensure_order_date(d: date | None) -> date:
    """订单业务日期：客户端没传时用**业务当地日**（不是进程本地日）。

    ⛔ `date.today()` 取的是**服务器/容器的本地日期**。部署时区一旦不是东八区
    （生产是 systemd 直接跑 uvicorn，容器化后更常见 UTC），兜底出来的"单据日期"
    就和报表、账单、单号差一天 —— 而且只在"客户端没传日期"这条路径上出现（R14-9 同族）。
    """
    return d or business_today()


def resolve_line_total(unit_price, quantity, given=None, *, index: int | None = None) -> Decimal:
    """行的金额 = **单价 × 数量**（服务端算），返回要落库的那个数。

    ### 为什么不能信客户端给的 line_total（v3.39 探针实测）
    `POST /orders` 与 `POST /order-products` 原来都是"客户端给了就用客户端的"，
    于是可以落一行 `数量 3 × 单价 10.00` 而 `行金额 = 1.00` 的单：接口 200、界面照常显示，
    而**账本、营业额、毛利都按行金额入账**——两个数从此各说各的，且没有任何地方会报错。

    客户端仍然可以传 line_total（老版本会传），但只当"核对"用：
    对得上（容差一分，覆盖客户端二进制浮点/四舍五入）就**以算出来的为准**，
    对不上就抛 ValueError（调用方转 400 并说清差多少），由调用方决定是拒绝还是提示。

    ⚠️ 拆单（`split_order`）与账本回写（`ledger_sync`）**不走这里**：
    拆单自己按比例算行金额，账本回写是"钱已经变了、把订单行对齐过去"，都不是下单语义。
    """
    up = money(unit_price)
    qty = Decimal(int(quantity))
    # ⚠️ 先乘、再按"分"四舍五入。反过来（先把单价收到分再乘）会放大误差：
    #    单价 3.3333 × 3 = 9.9999 → 分位是 10.00，而先收单价会得到 3.33 × 3 = 9.99。
    computed = money(Decimal(str(unit_price)) * qty)
    if given is None:
        return computed
    g = money(given)
    if g == ZERO:
        # 客户端把"没填"序列化成了 0：按算出来的算（0 件赠品行本来就该是 0）
        return computed
    if abs(g - computed) > LINE_TOTAL_TOLERANCE:
        where = f"第 {index + 1} 行" if index is not None else "这一行"
        raise ValueError(
            f"{where}的金额和「单价×数量」对不上：{up} × {qty} = {computed}，收到的是 {g}。"
            "行金额由服务端按单价×数量算，客户端不用自己算（两边算必然有一天不一致）。"
        )
    return computed


def build_order_products(
    db: Session,
    lines: list[Any],
) -> list:
    """按下单行构建 OrderProduct；商品成本快照在下单时定格（货损/毛利率按此时成本）。"""
    from app.models import OrderProduct, Product

    out = []
    for idx, line in enumerate(lines):
        # ⚠️ 顺序要紧：先算行金额（可能抛 ValueError → 调用方转 400），再碰任何状态。
        lt = resolve_line_total(
            line.unit_price, line.quantity, getattr(line, "line_total", None), index=idx
        )
        qty = line.quantity
        up = line.unit_price
        pid = getattr(line, "product_id", None)
        cost_snap = Decimal("0")
        # 单位：客户端可以逐行改（选品弹窗里的"数量 + 单位"），留空则用商品库里的单位。
        # 这是**展示信息**，不参与任何金额计算 —— 但必须存下来，否则界面上选了"3 箱"、
        # 订单和送货单上还是"3 件"（司机照着"件"数货）。
        unit = (getattr(line, "unit", "") or "").strip()
        if pid is not None:
            prod = db.get(Product, pid)
            if prod is None:
                # 商品编号对不上商品库：可能是客户端拿着旧目录下的单。
                # 收下它 = 成本快照按 0 记（毛利虚高）+ 送达时不扣库存，两样都不报错。
                raise ValueError(
                    f"第 {idx + 1} 行的商品已经不在商品库里（编号 {pid}）。"
                    "请重新从商品目录里选一个，或者改成手输的自定义商品（不填商品编号）。"
                )
            if prod.is_deleted:
                raise ValueError(
                    f"第 {idx + 1} 行的商品「{prod.name}」已经删除了。请重新选一个商品。"
                )
            cost_snap = prod.cost_price or Decimal("0")
            if not unit:
                unit = (prod.unit or "件").strip()
        if not unit:
            unit = "件"
        out.append(
            OrderProduct(
                product_id=pid,
                product_name_snapshot=line.product_name_snapshot,
                quantity=qty,
                unit_price=up,
                line_total=lt,
                cost_price_snapshot=cost_snap,
                unit_snapshot=unit[:32],
            )
        )
    return out