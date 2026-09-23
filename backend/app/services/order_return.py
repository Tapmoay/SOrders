"""订单退货（2026-09-20 用户要求）。

## 用户要的是什么

原话：「那个订单管理……我们可以进行一个退货」「可以整单退货，也可以只退其中的
某几个商品或者是一个商品，**他自己勾选**」「如果这个单子已经收了钱的话，做相应的退款……
它会显示"订单已结账"，我们在退货的话，就会**自动的退款**」。

## 一次退货动五样东西（缺一样就是"退了但账不对"）

1. **行级事实** `order_products.returned_quantity += n` —— 退货的底座；
2. **账本红冲** `ledgers(source=RETURN)`：**售价冲减**（`total` 为负）+ **负成本快照**
   （货回来了 → COGS 同步冲回）。同一行多次退货**累加到同一行**（唯一约束
   `(order_product_id, source)` 钉着，见 `LedgerSource.RETURN` 的注释）。
   ⛔ **金额口径**：按行落**四位**（账本是 4 位列，退货要精确冲回卖出去的那笔），
   到分**只在"整次退货"这一层做一次**；这一行的货值只算一处（`_line_amount`），
   "本次退货金额"与账本红冲行必须是同一个数 —— 2026-09-21 修掉原来两边各算一遍、
   四位单价下差 1 分的缺陷（按行取两位再求和 = 24.70，按行落四位再汇总 = 24.69，
   而退现按大的那个付出去）；
3. **库存回补** `inventory_service.restock_returned`（送达时实扣过，货真回来了）；
4. **退现**（只有"这单已经结过账"才发生）：`cash_flows(OUT, biz_type=REFUND_CUSTOMER)`。
   退多少不是拍脑袋 —— 见下面 `_refund_amount` 的三条边界；
5. **状态**：每行都退完 → `orders.status = RETURNED`（已退货）+ `returned_at`。
   只退了一部分 → **留在已送达**，界面靠 `returned_quantity` 打「部分退货」。

## 三条刻意不做的（都要能答上来"为什么"）

· **不复原司机账单**：司机把货送到了、这一趟跑完了，退货是客户与公司之间的事。
  与货损同一个口径（`apply_damage_accounting` 也不动司机应付）。要扣司机钱是另一个决定，
  得由人来做（`driver_bills` 有作废规则），不能由"点一下退货"顺带决定。
· **不动 `orders.paid`**：`paid` 的语义是"这单收过钱没有"，退货不会让"收过"变成"没收过"
  （钱确实进来过，然后又退回去了 —— 那是两条现金流水的事，不是把标记抹掉）。
  欠款口径由 `services/order_money.py` 一处算：`应收 − 已收 + 已退现`。
· **不物理删任何东西**：退货是一笔**新事实**（红冲行 + 回库流水 + 审计日志），
  原订单行、原账本行、原司机账单一个字都不改 —— 所以"退错了"永远查得回来。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.business_time import business_date
from app.models import CashFlow, Ledger, Order, OrderProduct
from app.models.enums import (
    CashFlowBizType,
    CashFlowDirection,
    LedgerSource,
    OperationAction,
    OrderStatus,
)
from app.services.accounting_service import resolve_customer_for_order
from app.services.inventory_service import restock_returned
from app.services.ledger_response import order_shipper_label
from app.services.operation_log_service import write_log
from app.services.order_money import money_of, q2

ZERO = Decimal("0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OrderReturnError(ValueError):
    """退货被业务规则拒绝（接口层翻成 400）。"""


@dataclass
class ReturnItem:
    """一行要退多少（`order_product_id` + 数量）。"""

    order_product_id: int
    quantity: int


@dataclass
class ReturnResult:
    order_no: str
    returned_amount: Decimal
    refund_amount: Decimal
    fully_returned: bool
    restocked_lines: int
    warnings: list[str] = field(default_factory=list)


def _line_amount(op: OrderProduct, qty: int) -> Decimal:
    """本次退掉这一行的**货款**（4 位小数）—— 全流程只有这一处算它。

    ## 为什么必须只有一处（2026-09-21 修的真实缺陷：差 1 分）

    在这之前有两个算法各算一遍：

    | 用在哪 | 规则 | 两行各 `unit_price=12.3456 × 1` |
    |---|---|---|
    | `ReturnResult.returned_amount`（→ 退现 → 响应体 → 站内信） | 按行先取**两位**再求和 | **24.70** |
    | `ledgers(source=RETURN).total`（账本红冲） | 按行落**四位** | 24.6912 → 汇总取两位 **24.69** |

    后果：同一个 `POST /orders/{id}/return` 的响应体里 `returned_amount`(24.70) 与
    `order.returned_amount`(24.69) 不相等，而**两边都不报错**；
    退现（真金白银）按 24.70 付，账上只红冲了 24.69 —— 一分钱对不上账。
    `order_products.unit_price` 是 `Numeric(14,4)`（拆单会算出四位单价），所以这不是理论值。

    ## 口径（账本是真相，只在"整次退货"这一层取两位）

    · **按行落四位**：账本 `total` 就是 4 位列，退货要**精确冲回**卖出去的那笔；
      在这里先取两位的话，卖 12.3456 只冲 12.35，那 0.0044 会永远留在应收里清不掉。
    · **整次退货取两位**：退现是付现金，必须到分；而"到分"这个动作一次就够
      （按行取两位再求和 = 多取了一次，正是上面那 1 分的来源）。
    """
    return ((op.unit_price or ZERO) * Decimal(qty)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def max_returnable(op: OrderProduct) -> int:
    """这一行**最多还能退几件** = 数量 − 货损 − 已退。

    ⚠️ 为什么减掉货损：货损那部分货已经在送达时按成本计进损失账了（`EXPENSE_LOSS`），
       客户手里根本没有那几件 —— 让它也能"退"，就是同一批货既算损失又算回库。
       `damage_quantity` 是司机送达时当场填的，是这份事实的唯一来源。
    """
    return max(0, int(op.quantity or 0) - int(op.damage_quantity or 0) - int(op.returned_quantity or 0))


def _refund_amount(order: Order, db: Session, returned_now: Decimal) -> Decimal:
    """这次退货**该退给客户多少现金**（用户：「已经收了钱的话，做相应的退款」）。

    三条边界，缺一条都会退错钱：
      ① **上限 = 这次退掉的货值**（不可能退得比退的货还多）；
      ② **上限 = 还欠着的"已收"部分** = `已收 − 已退现`。这条是关键：
         客户只付过 300（欠 700）、现在退掉值 400 的货 → 只退 300，
         剩下 100 是他本来就没付的，退了就等于公司倒贴；
      ③ 没收到过钱（`settled == 0`）→ 退 0：应收直接红冲掉就够了
         （这正是用户说的"按道理来说是不会有的，因为我们的收款是按订单来计算的"）。
    """
    m = money_of(db, order)
    already_refundable = max(ZERO, m.settled - m.refunded)
    return q2(min(returned_now, already_refundable))


def _reversal_row(
    db: Session,
    order: Order,
    op: OrderProduct,
    qty: int,
    line_amount: Decimal,
    entry_date,
    customer_id: int | None,
) -> None:
    """写/累加这一行的退货红冲账本行（负数口径：数量、金额、成本快照全为负）。

    累加而不是新插一行：`ledgers` 有唯一约束 `(order_product_id, source)`，
    而"同一行分几次退"是真实场景（先退 2 件、过两天再退 3 件）。

    ⚠️ [line_amount] 由调用方用 `_line_amount` 算好传进来 —— **不许在这里再算一遍**：
       "本次退货金额"与账本红冲必须是同一个数，各算一遍就会差一分（见 `_line_amount`）。
    """
    unit_price = op.unit_price or ZERO
    cost = op.cost_price_snapshot or ZERO
    cost_total = (cost * Decimal(qty)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    row = db.scalars(
        select(Ledger).where(
            Ledger.order_product_id == op.id,
            Ledger.source == LedgerSource.RETURN,
        )
    ).first()
    if row is None:
        db.add(
            Ledger(
                shipper_id=order.shipper_id,
                temp_shipper_name=order.temp_shipper_name if order.shipper_id is None else None,
                customer_id=customer_id,
                entry_date=entry_date,
                product_name=op.product_name_snapshot,
                quantity=-qty,
                unit_price=unit_price,
                total=-line_amount,
                order_id=order.id,
                order_product_id=op.id,
                product_id=op.product_id,
                source=LedgerSource.RETURN,
                note="订单退货红冲（自动）",
                cost_price_snapshot=-cost_total,
            )
        )
        return
    # ⛔ **累加走 SQL 表达式，不许 Python 读改写**（与 `inventory_service.auto_stock_commit`
    #    同一条理由，红线 `_tools/qa/_check_counter_updates.py` 钉着）：两次退货同时提交时，
    #    两边都读到同一个旧值、各自算出新值，后写的把前一次**整段盖掉** ——
    #    货退了两批、账上只红冲了一批，而**谁都不报错**（月底对账才发现，且查不出是哪两次）。
    #    把加法交给数据库，读与写在同一条 UPDATE 里完成。
    db.execute(
        update(Ledger)
        .where(Ledger.id == row.id)
        .values(
            quantity=Ledger.quantity - qty,
            total=Ledger.total - line_amount,
            cost_price_snapshot=Ledger.cost_price_snapshot - cost_total,
            # 日期跟着**最后一次**退货走（红冲行的金额是多次累加的，日期取最早那次会让人
            # 以为"钱是那天退的"；`orders.returned_at` 记的也是最后一次）
            entry_date=entry_date,
            note="订单退货红冲（自动，多次退货累加）",
        )
    )


def return_order(
    db: Session,
    order: Order,
    items: list[ReturnItem],
    *,
    note: str = "",
    operator_id: int,
) -> ReturnResult:
    """退货主流程（调用方负责 `db.commit()`）。

    传 `items` 就是"退货明细"；整单退货由接口层翻成"每一行都退满"，
    ⛔ **不接受 `all=true` 这种开关**：服务层只认数量，`max_returnable` 是唯一的上限来源。
    """
    if order.deleted_at is not None:
        raise OrderReturnError("这张单在回收站里（已删除），不能退货。请先恢复它。")
    if order.status != OrderStatus.DELIVERED:
        raise OrderReturnError(
            "只有「已送达」的订单可以退货"
            f"（这张单现在是「{order.status.value if order.status else '—'}」）。"
            "货还没送到的单请用「撤销」。"
        )
    if not items:
        raise OrderReturnError("请至少勾选一个要退的商品")

    ops = {op.id: op for op in order.order_products}
    seen: set[int] = set()
    for it in items:
        if it.order_product_id in seen:
            raise OrderReturnError("同一行重复勾选了，请刷新后重试")
        seen.add(it.order_product_id)
        op = ops.get(it.order_product_id)
        if op is None:
            raise OrderReturnError("勾选的商品不在这一单里，请刷新后重试")
        if it.quantity <= 0:
            raise OrderReturnError(f"「{op.product_name_snapshot}」的退货数量要大于 0")
        cap = max_returnable(op)
        if it.quantity > cap:
            extra = "（这一行的货损已经计过损失，那部分不能退）" if (op.damage_quantity or 0) > 0 else ""
            raise OrderReturnError(
                f"「{op.product_name_snapshot}」最多只能退 {cap} {op.unit_snapshot or '件'}"
                f"（下单 {op.quantity}、已退 {op.returned_quantity or 0}），你填了 {it.quantity}{extra}"
            )

    entry_date = business_date(datetime.now(timezone.utc)) or order.order_date
    cust = resolve_customer_for_order(db, order)
    warnings: list[str] = []
    returned_raw = ZERO
    lines: list[tuple[OrderProduct, int]] = []

    for it in items:
        op = ops[it.order_product_id]
        qty = it.quantity
        # ⚠️ 这一行的货值只在这里算一次，**同一个数**既进"本次退货金额"又进账本红冲行
        #    （各算一遍就会差一分 —— 见 `_line_amount` 的表）。
        line_amount = _line_amount(op, qty)
        returned_raw += line_amount
        # ⛔ 已退数量走 **SQL 表达式**（`returned_quantity = returned_quantity + qty`），
        #    不许 `op.returned_quantity = op.returned_quantity + qty`：两次退货同时提交时，
        #    两边都读到同一个旧值、各自算新值，后写的把前一次盖掉 ——
        #    货退了两批、账上只红冲一批，且谁都不报错
        #    （红线 `_tools/qa/_check_counter_updates.py` 钉着，与 `auto_stock_commit` 同一条理由）。
        #
        # ⚠️⚠️ **上限也必须写进同一条 SQL**（2026-09-23 并发实测抓到的真缺陷，动钱）：
        #    上面那个 `if it.quantity > cap:` 是**读-判断-写**，而并发退货的窗口正好卡在这里 ——
        #    3 个请求各自读到 `returned_quantity=0`、各自通过上限检查，然后三条 SQL 表达式各自 +1。
        #    实测（`_tools/perf/_concurrency_probe.py`）：**一件货退成 3 件**
        #    （`returned_quantity=3` 而 `quantity=1`）、账本红冲 −45 元（货值只有 15 元）、
        #    现金流水多出 3 笔退款 —— 也就是说"SQL 表达式"只解决了**丢更新**，
        #    解决不了"总量越过上限"。而这张单的状态没有变（部分退货仍是 DELIVERED），
        #    所以订单级的 CAS 拦不住它，必须在这一行上判。
        #    判据：**改到 1 行的人继续**；改不到 = 可退数量刚刚被另一笔退货用掉了。
        res = db.execute(
            update(OrderProduct)
            .where(
                OrderProduct.id == op.id,
                func.coalesce(OrderProduct.quantity, 0)
                - func.coalesce(OrderProduct.damage_quantity, 0)
                - func.coalesce(OrderProduct.returned_quantity, 0)
                >= qty,
            )
            .values(returned_quantity=func.coalesce(OrderProduct.returned_quantity, 0) + qty)
        )
        if res.rowcount != 1:
            raise OrderReturnError(
                f"「{op.product_name_snapshot}」的可退数量刚刚被另一笔退货用掉了，"
                "请刷新这张单再试（这一次没有退任何东西，也没有退款）"
            )
        lines.append((op, qty))
        _reversal_row(db, order, op, qty, line_amount, entry_date, cust.id if cust else None)

    restocked = restock_returned(db, order, lines, operator_id)
    if restocked < len(lines):
        warnings.append(
            "这一单里有商品的库存**没有回补**：要么它已经不在商品库里（被删/改名），"
            "要么**当时根本没扣过它的库存**（手输商品名的行、出库流水上线前的老单、"
            "以及送到仓库的单 —— 那种单送达时库存是净 0）。"
            "请到「库存管理」核对后手工入库，别照退货数量直接加。"
        )

    # 到分只做一次（按行取两位再求和会与账本红冲差一分，见 `_line_amount`）
    returned_amount = q2(returned_raw)
    refund = _refund_amount(order, db, returned_amount)
    if refund > 0:
        # ⛔ 对象名走**共用口径**（`ledger_response.order_shipper_label`）：注册货主 → 人名/手机号，
        #    临时货主 → 那句称呼。原来这里写的是 `cust.name if cust else (… or "临时货主")`，
        #    而"注册货主但没有客户档案"（生产 34 个货主账号里 2 个）会退成「临时货主」——
        #    同一笔钱在资金收支与账本上两个名字（2026-09-23 真机 E2E 抓到）。
        db.add(
            CashFlow(
                flow_date=entry_date,
                direction=CashFlowDirection.OUT,
                amount=refund,
                party_type="customer",
                party_id=cust.id if cust else None,
                party_name=order_shipper_label(db, order),
                channel="cash",
                biz_type=CashFlowBizType.REFUND_CUSTOMER,
                order_id=order.id,
                note=f"订单退货退款（{order.order_no}）",
                operator_id=operator_id,
            )
        )

    # 「整单退完」= **每一行的数量都退满**（不是"退过一次"，也不是"能退的都退了"）。
    #
    # ⚠️ 判据读的是**库里的真实值**（上面那次更新走的是 SQL 表达式，内存里的 `op` 还是旧的）——
    #    拿内存对象判会漏掉"这一次退的就是最后那几件"，整单退完的单永远不进「已退货」。
    #
    # ⚠️ 带损单刻意**不会**进「已退货」：司机报过货损的那几件不允许退（`max_returnable` 减掉了它们），
    #    而按既有口径**货损的货款客户照付**（`apply_damage_accounting`：损失由公司自担、营收不动）——
    #    所以那张单的应收还剩"货损那几件"的钱，必须继续留在「挂账未收」里被人追。
    #    用"能退的都退了"当判据就会把它标成已退货，而挂账报表的集合是 `status == DELIVERED`
    #    → 那笔钱**从所有催收入口同时消失**（正是这个项目反复在治的"静默抹掉应收"）。
    fresh = db.execute(
        select(OrderProduct.quantity, OrderProduct.returned_quantity).where(
            OrderProduct.order_id == order.id
        )
    ).all()
    fully = bool(fresh) and all(int(r[1] or 0) >= int(r[0] or 0) for r in fresh)
    if fully:
        order.status = OrderStatus.RETURNED
    order.returned_at = _now()

    parts = "、".join(f"{ops[i.order_product_id].product_name_snapshot}×{i.quantity}" for i in items)
    write_log(
        db,
        operator_id=operator_id or 0,
        order_id=order.id,
        action=OperationAction.ORDER_RETURN,
        change_payload={
            "退货": parts,
            "退货金额": str(returned_amount),
            "退款": str(refund),
            "整单退完": fully,
            "备注": (note or "").strip(),
        },
    )
    return ReturnResult(
        order_no=order.order_no,
        returned_amount=returned_amount,
        refund_amount=refund,
        fully_returned=fully,
        restocked_lines=restocked,
        warnings=warnings,
    )
