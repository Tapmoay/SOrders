"""账本 V2 统一账务钩子（单源事实）：送达→两支明细+货损；收款→逐单核销；结算单状态机；开销→资金流水。

约定（REV5 定稿）：
- 客户欠款 = Σledgers(含负向红冲) − Σcash_flows(IN, customer) + Σcash_flows(OUT, REFUND_CUSTOMER, customer)
- 司机未结 = Σdriver_bills(未作废) − Σcash_flows(OUT, driver) + Σcash_flows(IN, REFUND_DRIVER, driver)
- 货损（公司自担）：EXPENSE_LOSS（成本口径）+ ledgers 专用红冲行（amount=0、负成本快照冲回 COGS），客户/营业额零影响。
"""

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.core.business_time import business_date, business_local
from app.models import (
    CashFlow,
    Customer,
    DriverBill,
    DriverSettlement,
    Expense,
    Ledger,
    Order,
    OrderProduct,
    ShipperReceipt,
    User,
)
from app.models.enums import (
    CashFlowBizType,
    CashFlowDirection,
    DriverBillStatus,
    DriverBillType,
    LedgerSource,
    OrderStatus,
    ReceiptSettleMode,
    SettlementStatus,
)
from app.schemas.accounting_v2 import (
    DriverSettlementCreate,
    ExpenseCreate,
    ShipperReceiptCreate,
)
from app.services.order_money import line_receivable, money_map
from app.services.money_text import money_text

#: 送达货损自动生成的那笔开销用哪个分类 —— **就是名册里的那个名字**（原来是枚举 `LOSS`）。
#: 迁移会把老库里的 `loss` 翻成「货损」，所以这里写中文名与名册对得上。
DAMAGE_EXPENSE_CATEGORY = "货损"

from app.services.driver_pay import (
    has_per_order_pay,
    pay_for_order,
    rule_from_snapshot,
)


# ---------- 工具 ----------
def _month_of(dt: datetime | None) -> str:
    """账单归属的月份 = **业务当地月**（东八区），不是 UTC 月。

    2026-09-19 审计 R13-D2：`delivered_at` 存的是 UTC，而「司机运费结算」页/司机绩效/
    账本全都按**当地月**开窗口（`freight_settlement` 会把 `month` 当当地墙上时间再换 UTC）。
    账单月份按 UTC 算时，当地月初 00:00~08:00 送达的单被记到**上一个月**：
    结算页（当地月窗口）看得到它、账单表（UTC 月桶）里没有 → 派单员去建结算单被告知
    「本月无待结算明细」，而 AI 的补单卡会一直算出"还差 X 元"、点确认却一张都生成不了（见 D2 的另一半）。
    """
    d = dt or datetime.now(timezone.utc)
    return business_local(d).strftime("%Y-%m")


def _now() -> datetime:
    return datetime.now(timezone.utc)


    return c.name if c else ""


def resolve_customer_for_order(db: Session, order: Order) -> Customer | None:
    """订单归属客户：registered→按 user_id；temp→按名称（尽力匹配）。"""
    if order.shipper_id is not None:
        return db.scalars(select(Customer).where(Customer.user_id == order.shipper_id)).first()
    name = (order.temp_shipper_name or "").strip()
    if not name:
        return None
    return db.scalars(select(Customer).where(Customer.name == name)).first()


# ---------- ① 送达：司机应付明细（幂等生成） ----------
def generate_piece_bill(db: Session, order: Order, operator_id: int | None = None) -> DriverBill | None:
    """订单送达且有"按单应付" → 生成/复用明细。幂等：order_id+bill_type 唯一。

    ### v3.36：金额不再等于运费
    以前这里是 `amount = order.freight_fee`（计件=全额运费）。现在司机可能挂着计费规则
    （每单固定 / 运费提成 / 商品金额提成 / 固定工资+提成），金额由 `driver_pay.pay_for_order`
    按**订单上的规则快照**算——一处实现，四处（这里、补单、结算页、司机绩效）共用。
    `rule=None`（没挂规则的存量司机）时它仍然返回全额运费，行为一字不变。

    ### 判据也从"用户表里的 billing_mode"换成了"订单快照"
    换成 `driver_pay.has_per_order_pay(order)` 之后，和结算页/补单用的口径**完全一致**：
    快照为空的老单按"有运费就算有应付"处理（以前这里对快照为空的单**不生成**账单，
    而结算页会把同一张单列进待结运费——同一张单两个页面说法不同）。
    """
    if order.status.value != "DELIVERED":
        return None
    if not has_per_order_pay(order):
        return None
    rule = rule_from_snapshot(getattr(order, "driver_rule_snapshot", None))
    pay = pay_for_order(order)
    if pay.total <= 0:
        return None
    existing = db.scalars(
        select(DriverBill).where(
            DriverBill.order_id == order.id,
            DriverBill.bill_type == DriverBillType.PIECE,
        )
    ).first()
    if existing is not None:
        return existing
    # 账单要能**独立**说清"当时按什么算的"：规则名 + 两件金额 + 文字明细都落库。
    # 只留一个裸金额的话，月底对账时没人能复核这个数是怎么来的（改造前的既有缺陷）。
    detail = f"规则「{rule.name}」：" if rule is not None else ""
    bill = DriverBill(
        driver_id=order.driver_id or 0,
        bill_type=DriverBillType.PIECE,
        order_id=order.id,
        month=_month_of(order.delivered_at),
        amount=pay.total,
        status=DriverBillStatus.OPEN,
        note=(detail + _pay_note(pay, rule))[:250] if rule is not None else "订单送达自动生成（运费全额）",
        rule_id=rule.rule_id if rule is not None else None,
        rule_name=rule.name if rule is not None else "",
        piece_amount=pay.piece if rule is not None else None,
        commission_amount=pay.commission if rule is not None else None,
    )
    db.add(bill)
    return bill


def _pay_note(pay, rule) -> str:
    """账单上那行"怎么算出来的"（例：`每单 300.00 + 运费 1000.00 的 8% = 80.00`）。

    ⚠️ 比例必须用 `pay.rate_used`（**这一次实际用的**），不能用 `rule.commission_rate`：
    派单员可以对这一单单独定比例，用规则里的默认值会印出一句**算术上不成立**的话
    （真机 E2E 抓到过：运费 1000 的 5.00% = 80.00，而 5% 其实是 50）——
    账单是钱，说明里出现算不通的数字，等于这张账单没法复核。
    """
    parts: list[str] = []
    if pay.piece > 0:
        cn = "每件" if getattr(rule, "piece_unit", "order") == "item" else "每单"
        mark = "（这一单单独定的）" if getattr(pay, "piece_overridden", False) else ""
        parts.append(f"{cn} {pay.piece}{mark}")
    if pay.commission > 0:
        base_cn = {"freight": "运费", "goods": "商品金额"}.get(getattr(rule, "commission_base", ""), "基数")
        rate = getattr(pay, "rate_used", None) or getattr(rule, "commission_rate", 0)
        mark = "（这一单单独定的）" if getattr(pay, "rate_overridden", False) else ""
        parts.append(f"{base_cn} {pay.basis} 的 {rate}%{mark} = {pay.commission}")
    parts.append(f"合计 {pay.total}")
    return " + ".join(parts)


# ---------- ② 送达：货损（公司自担）记账 ----------
def apply_damage_accounting(db: Session, order: Order, operator_id: int | None = None) -> list[str]:
    """商品行级货损 → ①EXPENSE_LOSS(成本×数量) ②ledgers 专用红冲行(amount=0, 负成本快照)。
    货损成本=该行 cost_price_snapshot×damage_quantity；客户欠款/营业额零影响（客户全额付款）。

    ### 返回值 = 必须让人看到的"没记成"清单（不要把司机报的货损抹掉）
    以前没有成本快照时这里会把 `damage_quantity` **置回 0**（注释写"提示在接口层"，
    而接口层从来没有提示）——后果是司机在送达界面填的货损**凭空消失**：
    接口返回成功、订单上货损变成 0、也没有任何地方提示过。
    现在：**保留司机填的数量**，只是"这笔成本没进账"，并把这个事实作为返回值的
    一句话交出去（调用方写进操作日志，报表中心的「异常与审计」看得到）。
    """
    warnings: list[str] = []
    for op in order.order_products:
        qty = op.damage_quantity or 0
        if qty <= 0:
            continue
        cost = op.cost_price_snapshot or Decimal("0")
        # ⚠️ 进位方式必须与**全项目**一致：`driver_pay.money()` 用的是 ROUND_HALF_UP，
        #    而 `.quantize(Decimal("0.01"))` 的默认是 ROUND_HALF_EVEN → 成本价正好落在半分上时
        #    （如 12.3450）两处会差 1 分（2026-09-19 审计第十七轮，纯静态：本机 437 个商品
        #    里恰好没有一个命中，所以它从没被发现，但"钱的算法只许一处"是硬规矩）。
        cost_amt = (cost * Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if cost_amt <= 0:
            # 数量**留着**（那是司机报的事实），只是没有成本价就算不出损失金额
            warnings.append(
                f"{order.order_no} 的「{op.product_name_snapshot}」报了货损 {qty} 件，"
                f"但这个商品没有成本价快照，损失金额按 0 计、没有进开销账。"
                f"要按成本计损失，请在「商品管理」里补上成本价（只对之后新下的单生效）。"
            )
            continue
        # 货损开销的日期用**业务当地日**（2026-09-19 审计 R12-M11，理由同账本行）
        dod = business_date(order.delivered_at) or order.order_date
        exp = Expense(
            exp_date=dod,
            category=DAMAGE_EXPENSE_CATEGORY,
            amount=cost_amt,
            driver_id=order.driver_id,
            order_id=order.id,
            note=f"送达货损 {qty} 件 × 成本 {cost}（{order.order_no}）",
            operator_id=operator_id,
        )
        db.add(exp)
        db.flush()
        db.add(
            CashFlow(
                flow_date=dod,
                direction=CashFlowDirection.OUT,
                amount=cost_amt,
                party_type="expense",
                party_id=exp.id,
                party_name="货损",
                channel="cash",
                biz_type=CashFlowBizType.EXPENSE_LOSS,
                order_id=order.id,
                doc_id=exp.id,
                note=exp.note,
                operator_id=operator_id,
            )
        )
        # ledgers 专用红冲行：amount=0，负成本快照冲回 COGS（不影响营业额/欠款）
        cust = resolve_customer_for_order(db, order)
        db.add(
            Ledger(
                shipper_id=order.shipper_id,
                temp_shipper_name=order.temp_shipper_name if order.shipper_id is None else None,
                customer_id=cust.id if cust else None,
                entry_date=dod,
                product_name=op.product_name_snapshot,
                quantity=qty,
                unit_price=Decimal("0"),
                total=Decimal("0"),
                order_id=order.id,
                order_product_id=op.id,
                product_id=op.product_id,
                source=LedgerSource.REFUND,
                note=f"送达货损成本冲回（自动）{qty} 件",
                cost_price_snapshot=-(cost * Decimal(qty)).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                ),
            )
        )
    return warnings


# ---------- ③ 送达：总钩子（先 bill 后货损） ----------
def post_delivery_accounting(db: Session, order: Order, operator_id: int | None = None) -> list[str]:
    """送达之后的两件事，返回**"没记成"清单**（见 [apply_damage_accounting]）。"""
    generate_piece_bill(db, order, operator_id)
    return apply_damage_accounting(db, order, operator_id)


# ---------- ④ 客户收款单：逐单核销 ----------
def create_receipt(db: Session, body: ShipperReceiptCreate, operator_id: int | None) -> ShipperReceipt:
    cust = db.get(Customer, body.customer_id)
    if cust is None:
        raise ValueError("客户档案不存在")
    per_order: dict[int, Decimal] = {}
    # ⚠️ 归属 / 存在 / 已收款这三道校验必须对**两种 settle_mode 都生效**（2026-09-19 审计）。
    #    原来整段校验写在 `if ITEMIZED:` 里面，而上面 `ShipperReceiptCreate` 并没有禁止
    #    「rolling + order_ids」这个组合 —— 于是滚动收款带着 order_ids 进来时：
    #      ① 不校验归属 → 可以把**任意货主的任意订单**标成已收款；
    #      ② 不校验 paid → 可以**无限重复**调用；
    #      ③ `per_order` 是空的，下面按 `body.amount` 给**每个** order_id 各写一条**全额**流水
    #         （10 个 order_ids × 1000 元 = 10 条 1000 元的流入，而收款单只有 1000）。
    #    这道洞两个库里都没有任何测试覆盖（实测 rolling 行数 = 0，纯靠代码读出来）。
    order_ids = sorted({int(x) for x in (body.order_ids or [])})
    # **按商品核销**（2026-09-20 用户要求：「点击订单点击核销……也可以按商品进行核销」）：
    # 只收点名的这几行的钱。留空 = 整单核销（老语义一字不变）。
    line_ids = sorted({int(x) for x in (body.order_product_ids or [])})
    if line_ids and not order_ids:
        raise ValueError("「按商品核销」要同时说明这几个商品属于哪张订单（order_ids 不能为空）")
    if order_ids:
        locked = {
            o.id: o
            for o in db.scalars(
                select(Order)
                .options(selectinload(Order.order_products))
                .where(Order.id.in_(order_ids))
                .with_for_update()
            )
        }
        picked: dict[int, list[OrderProduct]] = {}
        if line_ids:
            rows = list(db.scalars(select(OrderProduct).where(OrderProduct.id.in_(line_ids))))
            found = {op.id for op in rows}
            if any(i not in found for i in line_ids):
                raise ValueError("勾选的商品行已经不在了（被删掉了），请刷新订单后重试")
            for op in rows:
                if op.order_id not in locked:
                    raise ValueError("勾选的商品不在所选的订单里，请刷新后重试")
                picked.setdefault(op.order_id, []).append(op)
            if any(oid not in picked for oid in order_ids):
                raise ValueError("有一张被选中的订单一件商品都没勾，请去掉它，或把商品勾上")
        # ⚠️ 钱的口径**只有一处**：`order_money`（退货红冲 / 已收 / 已退现都在里面）。
        #    `lock=True` 是并发防重：现金流水走加锁读，后到的请求会看到前一个已提交的收款。
        #    （REPEATABLE READ 下普通 SELECT 读的是事务开始时的快照 → 两个并发核销会双双通过
        #      "没有超过欠款"的校验，各收一笔，**收成两倍的钱**。）
        money = money_map(db, list(locked.values()), lock=True)
        for oid in order_ids:
            o = locked.get(oid)
            if o is None:
                raise ValueError(f"订单 {oid} 不存在")
            if o.shipper_id is None:
                raise ValueError(f"订单 {o.order_no} 无客户归属（临时货主收款需先关联客户档案）")
            if o.shipper_id != cust.user_id:
                raise ValueError(f"订单 {o.order_no} 不属于该客户")
            # ⛔ **已撤销 / 已退货 / 已进回收站**的单不许收款（2026-09-19 审计 F1 + 2026-09-20 退货）。
            #    这三道校验（存在/归属/已收款）原来**唯独没有状态**：本机就有一批
            #    **已撤销**的单挂着逐单核销的收款单 + 现金流水（73 张 / ¥2,900）。
            #    一手交钱一手交货的单被撤销了（客户不要了、改派了），钱却记在它头上 ——
            #    客户的"已收"虚高、而真正该收的那张单还是欠着；撤销时谁也没被告知这一笔。
            #    预收（还没派/还没送就先收钱）是**产品口径**（见待拍板清单第 2 条），
            #    所以这里只挡"单已经作废"，不挡"单还没送达"。
            if o.deleted_at is not None:
                raise ValueError(
                    f"订单 {o.order_no} 已经删除（在回收站里），不能再对它收款。"
                    "请先恢复这张单，或改用不绑单的滚动收款。"
                )
            if (o.status or "").upper() == OrderStatus.CANCELLED.value:
                raise ValueError(
                    f"订单 {o.order_no} 已经撤销了，不能再对它收款。"
                    "如果是提前收的款，请用不绑单的滚动收款记这一笔；"
                    "要让这张单重新可收，得先把它恢复成有效单据。"
                )
            if (o.status or "").upper() == OrderStatus.RETURNED.value:
                raise ValueError(
                    f"订单 {o.order_no} 已经退货了，货款已经红冲掉、不用再收。"
                    "如果只退了其中一部分，剩下的那部分仍然留在「已送达」的单上可以收。"
                )
            m = money[oid]
            if o.paid or m.arrears <= 0:
                how = {
                    "cash": "司机送达时收的现金",
                    "arrears": "已挂账结清",
                }.get((o.payment_method or "").lower(), "之前已经核销过")
                raise ValueError(
                    f"订单 {o.order_no} 已经收过款了（{how}），不能重复收款。"
                    "如果是补差额，请改用「滚动收款」。"
                )
            # 这次对这一单核销多少：
            # · 按商品核销 = 点名那几行的**应收**合计（行级算法只有 `line_receivable` 一份）；
            # · 整单核销 = 这一单**还欠的钱**（`m.arrears`）。
            # ⚠️ 整单核销这里**改过两次**，两次都是"按一个比欠款大的数收钱"：
            #    ① 第一版是"把各行 `line_total` 全加起来" —— 退过货的单上那个数比该收的多
            #       （退货红冲只动账本、不动行金额）；
            #    ② 第二版改成 `m.receivable`——对**按商品核销过一部分**的单仍然偏大：
            #       一张 1000 的单收过 300 之后（`paid=False`、欠 700），后端算出 1000，
            #       而客户端按欠款发 700 → 两边金额对不上（400「收款金额与所选订单合计不一致」，
            #       其实客户端是对的），这种单从此**再也收不动**；要是金额凑巧对上了，
            #       就是**多收 300**。
            #    整单核销的语义本来就是"把这一单的钱收清"，那就是欠款。
            part = (
                sum((line_receivable(op) for op in picked[oid]), Decimal("0"))
                if line_ids
                else m.arrears
            )
            part = part.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if part <= 0:
                raise ValueError(f"订单 {o.order_no} 没有可以核销的金额（这一单已经全部退货了）")
            if part > m.arrears:
                raise ValueError(
                    # 这句话会原样弹给用户（收款被拒的理由）→ 金额过 `money_text` 去尾零；
                    # 判据仍是上面那行 `part > m.arrears`（`Decimal`），一个字都没动。
                    f"订单 {o.order_no} 这次要核销 {money_text(part)} 元，但它只欠 {money_text(m.arrears)} 元"
                    "（差额来自已经收过的部分或退掉的货），不能超额收款。"
                )
            per_order[oid] = part
    if body.settle_mode == ReceiptSettleMode.ITEMIZED:
        if not body.order_ids:
            raise ValueError("逐单核销需绑定订单")
        total = sum(per_order.values(), Decimal("0"))
        if Decimal(body.amount) != total:
            raise ValueError(f"收款金额 {body.amount} 与所选订单合计 {total} 不一致（逐单核销需全额）")
        # 原子占位：**只有"这次收完就结清"的单**才去抢 `paid`（并发下只有一个请求改得到）。
        # ⚠️ 按商品核销**不是**"结清"：钱没付完，`paid` 必须留在 False ——
        #    翻成 True 这张单就会从「挂账未收」名单里消失，而它还欠着一半。
        #    这种单的并发由上面的行锁 + 加锁读兜住（第二次请求会算出"还欠 700"）。
        settling = [oid for oid in order_ids if per_order[oid] >= money[oid].arrears]
        if settling:
            claimed = db.execute(
                update(Order)
                .where(Order.id.in_(settling), Order.paid.is_(False))
                .values(
                    paid=True,
                    payment_method="cash" if body.method in ("cash", "transfer", "wechat") else "arrears",
                )
            )
            if claimed.rowcount != len(settling):
                db.rollback()
                raise ValueError("这些订单里有刚刚被别的收款记录核销掉的，请刷新订单后重试")
    elif order_ids:
        # 滚动收款**绑了单**（App 与 AI 都不会这么发：它们绑单时一律走 itemized）。
        # ⚠️ 这里原来**无条件**把这批单标成已收款，却不校验金额（2026-09-19 审计 R12-M4）：
        #    传 `amount=1` + 两张合计 10000 的单 → 两张单从所有"欠款/挂账未收"口径里消失，
        #    而资金只记了 1 元 —— **9999 元应收被静默抹掉**，客户不必再付、也没人知道。
        #    逐单核销那条分支一直有这道校验，同一个端点两种语义宽严不一。
        #    现在两边同一条底线：**绑了单就得对得上**；"先收一笔钱、以后再说"请用不绑单的滚动收款。
        total = sum(per_order.values(), Decimal("0"))
        if Decimal(body.amount) != total:
            raise ValueError(
                f"收款金额 {body.amount} 与所选订单合计 {total} 不一致。"
                "绑了订单就必须逐单对得上；如果只是先收一笔钱（以后再说冲哪几张单），"
                "请把订单留空，用滚动收款。"
            )
        # 并发下两张收款单抢同一批订单：走条件 UPDATE 占位（与逐单核销同一条理由）。
        claimed = db.execute(
            update(Order)
            .where(Order.id.in_(order_ids), Order.paid.is_(False))
            .values(
                paid=True,
                payment_method="cash" if body.method in ("cash", "transfer", "wechat") else "arrears",
            )
        )
        if claimed.rowcount != len(order_ids):
            db.rollback()
            raise ValueError("这些订单里有刚刚被别的收款记录核销掉的，请刷新订单后重试")
    receipt = ShipperReceipt(
        customer_id=body.customer_id,
        amount=body.amount,
        method=body.method,
        received_at=body.received_at,
        # ⚠️ 落库存的是上面**去重并排序**过的那一份（`order_ids`），不是 `body.order_ids`
        #    （2026-09-19 审计 F9）：`[5,5]` 能过校验（去重后只有一张单、金额也对得上），
        #    却会让收款记录里显示两条同样的订单 —— 对账的人会以为收了两次。
        order_ids=order_ids or None,
        settle_mode=body.settle_mode,
        arrears_unit_id=body.arrears_unit_id,
        note=body.note,
        operator_id=operator_id,
    )
    db.add(receipt)
    db.flush()
    biz = CashFlowBizType.RECEIPT_CASH
    if body.method == "transfer":
        biz = CashFlowBizType.RECEIPT_TRANSFER
    elif body.method == "wechat":
        biz = CashFlowBizType.RECEIPT_TRANSFER
    elif body.method == "arrears_settle":
        biz = CashFlowBizType.RECEIPT_ARREARS
    common = {
        "flow_date": body.received_at,
        "direction": CashFlowDirection.IN,
        "party_type": "customer",
        "party_id": cust.id,
        "party_name": cust.name,
        "channel": "wechat" if body.method == "wechat" else ("bank" if body.method == "transfer" else "cash"),
        "biz_type": biz,
        "doc_id": receipt.id,
        "operator_id": operator_id,
    }
    if body.settle_mode == ReceiptSettleMode.ITEMIZED:
        # 逐单核销：**逐单**写金额，每张单写自己那一份，合计等于收款总额
        # （`reports.py` 的资金收支按流水逐条求和）。
        # `cash_flows.amount` 是 NOT NULL，所以这里绝不能写 None——
        # 以前多张单的核销写的是 None，收款直接 500（IntegrityError），钱一分都没落库。
        for oid, part in per_order.items():
            db.add(CashFlow(order_id=oid, amount=part, note=f"客户收款（逐单核销，收款单 #{receipt.id}）", **common))
    else:
        # 滚动收款：**一笔钱就是一笔流水**（不绑单）。
        # ⚠️ 2026-09-19 审计：原来这里也走 `for oid in order_ids` 的循环、且金额一律写
        #    `body.amount` —— 于是"滚动收款 + 10 个 order_ids"会写出 **10 条全额流水**
        #    （收款单只有 1000，账上却记了 10000 流入）。滚动收款的语义本来就是
        #    "收到一笔钱、不指定它冲哪几张单"，所以正确的形状是一笔、金额 = 实收。
        db.add(CashFlow(order_id=None, amount=body.amount, note=f"客户收款（滚动，收款单 #{receipt.id}）", **common))
    return receipt


# ---------- ⑤ 司机结算单状态机 ----------
def create_settlement(db: Session, body: DriverSettlementCreate, operator_id: int | None) -> DriverSettlement:
    driver = db.get(User, body.driver_id)
    if driver is None:
        raise ValueError("司机不存在")
    if body.settle_type == DriverBillType.PIECE:
        # ⛔ 已进回收站（软删）订单的 OPEN 账单**不许被结算单收走**（2026-09-19 审计第十七轮）。
        #    这一段原来只按"司机 + 类型 + 月份 + OPEN"取明细，**根本不 join orders**，
        #    而运费结算页与报表都排除了软删单（`freight_settlement.py`、
        #    `reports.py::load_delivered` 都带 `Order.deleted_at.is_(None)`）→ 两边各自都错：
        #      · 账单表会比页面**多**出这些单的应付（本机实测：2026-09 已软删单的 PIECE 账单
        #        38 张 ¥1130.00），结算单会把它们一起收走并**真付款**；
        #      · 本机已有既成事实：结算单 #3（¥880、已付）的 order_ids 里就含一张已软删的订单
        #        （先删单 13:55、后付款 14:50）。
        #    口径统一到"页面看得见的单才结得掉"：软删单的账单留给保留任务作废（`data_retention`
        #    在物理清理时会把它们翻成 CANCELLED 并通知司机与派单员）。
        bills = list(
            db.scalars(
                select(DriverBill)
                .outerjoin(Order, Order.id == DriverBill.order_id)
                .where(
                    DriverBill.driver_id == body.driver_id,
                    DriverBill.bill_type == DriverBillType.PIECE,
                    DriverBill.month == body.month,
                    DriverBill.status == DriverBillStatus.OPEN,
                    # 只挡"订单存在且已软删"：`order_id` 为空的历史孤儿账单仍按原样处理
                    # （那是另一条已知问题，见台账 D2，不在本次口径内）
                    or_(DriverBill.order_id.is_(None), Order.deleted_at.is_(None)),
                )
            )
        )
        order_ids = [b.order_id for b in bills if b.order_id]
        amount = sum((b.amount for b in bills), Decimal("0"))
        period_from = date(int(body.month[:4]), int(body.month[5:7]), 1)
        period_to = period_from
    else:
        bills = list(
            db.scalars(
                select(DriverBill).where(
                    DriverBill.driver_id == body.driver_id,
                    DriverBill.bill_type == DriverBillType.SALARY,
                    DriverBill.month == body.month,
                    DriverBill.status == DriverBillStatus.OPEN,
                )
            )
        )
        order_ids = []
        amount = sum((b.amount for b in bills), Decimal("0"))
        period_from = None
        period_to = None
    if not bills:
        raise ValueError(f"{body.month} 无待结算明细（请先生成账单）")
    if body.amount is not None and Decimal(body.amount) != amount:
        amount = Decimal(body.amount)  # 允许手工调整（注记差异）
    s = DriverSettlement(
        driver_id=body.driver_id,
        settle_type=body.settle_type,
        month=body.month,
        period_from=period_from,
        period_to=period_to,
        amount=amount,
        status=SettlementStatus.DRAFT,
        order_ids=order_ids,
        operator_id=operator_id,
        note=body.note,
    )
    db.add(s)
    return s


def confirm_settlement(db: Session, s: DriverSettlement, operator_id: int | None) -> DriverSettlement:
    if s.status != SettlementStatus.DRAFT:
        raise ValueError("仅草稿可确认")
    # 原子锁定：仍 OPEN 的所属 bills → SETTLED
    if s.settle_type == DriverBillType.PIECE and s.order_ids:
        bills = list(
            db.scalars(
                select(DriverBill).where(
                    DriverBill.id.in_(
                        select(DriverBill.id).where(
                            DriverBill.order_id.in_(s.order_ids),
                            DriverBill.driver_id == s.driver_id,
                            DriverBill.bill_type == DriverBillType.PIECE,
                            DriverBill.status == DriverBillStatus.OPEN,
                        )
                    )
                )
            )
        )
    else:
        bills = list(
            db.scalars(
                select(DriverBill).where(
                    DriverBill.driver_id == s.driver_id,
                    DriverBill.bill_type == s.settle_type,
                    DriverBill.month == s.month,
                    DriverBill.status == DriverBillStatus.OPEN,
                )
            )
        )
    if not bills:
        raise ValueError("账单已被其他结算单占用或不存在")
    locked_total = sum((b.amount for b in bills), Decimal("0"))
    if Decimal(s.amount) != locked_total:
        raise ValueError(f"结算单金额 {s.amount} 与明细合计 {locked_total} 不一致，请核对")
    for b in bills:
        b.status = DriverBillStatus.SETTLED
        b.settled_doc_id = s.id
    # ⚠️ **条件 UPDATE 占位**（2026-09-19 审计第十七轮，与 `pay_settlement` 同一套）：
    #    上面"读 DRAFT → 判断 → 写"中间没有锁也没有 CAS。`confirm × cancel` 并发时
    #    （派单员两台设备、或手滑点两下）两个请求都读到 DRAFT、各自往下走 →
    #    终态可能出现「结算单 CANCELLED + 明细已 SETTLED」：那批账单既不 OPEN
    #    （`create_settlement` 不再收）也不可付（`pay_settlement` 要 CONFIRMED）→
    #    **司机这笔钱永远结不掉，只能改库**。改到行的人才能继续，SQLite / MySQL 都原子。
    claimed = db.execute(
        update(DriverSettlement)
        .where(DriverSettlement.id == s.id, DriverSettlement.status == SettlementStatus.DRAFT)
        .values(status=SettlementStatus.CONFIRMED)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise ValueError("这张结算单刚刚被别的操作改过（可能已确认/已作废），请刷新后查看")
    db.refresh(s)
    return s


def pay_settlement(db: Session, s: DriverSettlement, method: str, operator_id: int | None) -> DriverSettlement:
    if s.status != SettlementStatus.CONFIRMED:
        raise ValueError("仅已确认结算单可付款")
    # ⚠️ 付款前**再看一眼明细还在不在**（2026-09-18 补，缺陷挖掘的产物）。
    #
    # 确认时已经查过一次，为什么付款还要查：确认与付款是**两次点击**，中间可能隔很久，
    # 而明细行本身可以被别的路径删掉（订单硬删、清理脚本、以后的数据保留策略）。
    # 明细一旦没了，这张单就变成"付出去一笔钱、账上没有任何对应的应付款"——
    # 月底没人能复核这笔钱付的是什么。库里真的出现过这种单：
    # 1 张 352 元的已付结算单、0 条明细（探针见 `_tools/qa/_probe_settlement_orphan.py`）。
    # 钱付出去就撤不回来，所以这道检查必须紧贴付款那一刻，而不是只在确认时查。
    live = list(db.scalars(select(DriverBill).where(DriverBill.settled_doc_id == s.id)))
    if not live:
        raise ValueError("这张结算单已经没有任何明细（明细被删除或解绑），不能付款；请作废后重新结算")
    if any(b.status != DriverBillStatus.SETTLED or b.driver_id != s.driver_id for b in live):
        raise ValueError("这张结算单的明细状态与司机对不上（被别的操作改过），不能付款；请作废后重新结算")
    live_total = sum((b.amount for b in live), Decimal("0"))
    if Decimal(s.amount) != live_total:
        raise ValueError(
            f"结算单金额 {s.amount} 与现存明细合计 {live_total} 不一致，不能付款；请作废后重新结算"
        )
    # ⚠️ **原子占位**（2026-09-19 审计）：上面那几步是"读 → 判断 → 写"，中间没有锁也没有 CAS。
    #    两个并发的"付款"（派单员两台设备、或手滑点两下 + 网络重试）会**都读到 confirmed**、
    #    于是写出**两条** PAYMENT_DRIVER 流水 —— 同一笔付款在账上扣两次（`cash_flows` 没有
    #    (doc_id, biz_type) 唯一约束兜底）。作业方式与派单/送达同一套：把状态跃迁本身变成
    #    "改到行的人才能继续"，SQLite 与 MySQL 上都原子。
    claimed = db.execute(
        update(DriverSettlement)
        .where(DriverSettlement.id == s.id, DriverSettlement.status == SettlementStatus.CONFIRMED)
        .values(status=SettlementStatus.PAID, paid_at=_now(), method=method)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise ValueError("这张结算单刚刚被别的操作付过款了（重复提交或两个人在同时操作），请刷新后查看")
    db.refresh(s)
    db.add(
        CashFlow(
            flow_date=(s.paid_at).date(),
            direction=CashFlowDirection.OUT,
            amount=s.amount,
            party_type="driver",
            party_id=s.driver_id,
            party_name="",
            channel=method,
            biz_type=CashFlowBizType.PAYMENT_DRIVER if s.settle_type == DriverBillType.PIECE else CashFlowBizType.PAYMENT_SALARY,
            doc_id=s.id,
            note=f"司机结算单 #{s.id}（{s.month}）",
            operator_id=operator_id,
        )
    )
    return s


def cancel_settlement(db: Session, s: DriverSettlement, operator_id: int | None) -> DriverSettlement:
    if s.status != SettlementStatus.DRAFT:
        raise ValueError("仅草稿可取消")
    # 同 `confirm_settlement`：作废也要占位（`cancel × confirm` 并发时不许两个都成立）
    claimed = db.execute(
        update(DriverSettlement)
        .where(DriverSettlement.id == s.id, DriverSettlement.status == SettlementStatus.DRAFT)
        .values(status=SettlementStatus.CANCELLED)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise ValueError("这张结算单刚刚被别的操作改过（可能已确认/已作废），请刷新后查看")
    db.refresh(s)
    if s.settle_type == DriverBillType.PIECE and s.order_ids:
        bills = list(
            db.scalars(
                select(DriverBill).where(
                    DriverBill.settled_doc_id == s.id,
                    DriverBill.status == DriverBillStatus.SETTLED,
                )
            )
        )
        for b in bills:
            b.status = DriverBillStatus.OPEN
            b.settled_doc_id = None
    return s


# ---------- ⑥ 开销单 ----------
def create_expense(db: Session, body: ExpenseCreate, operator_id: int | None) -> Expense:
    # 分类**先补进名册**（不在就补到最后）：否则用户在一个新分类下记的开销，
    # 左侧分类栏里没有它 —— 那条记录只能靠"名册外的分类"兜底显示（排序/改名都轮不到它）。
    # ⚠️ 与 `expense_categories.py::ensure_category` 是同一个函数，不抄第二份判据。
    from app.api.v1.expense_categories import ensure_category

    clean = (str(body.category or "")).strip()
    if not clean:
        raise ValueError("请选择开销分类")
    ensure_category(db, clean)
    e = Expense(
        exp_date=body.exp_date,
        category=clean,
        amount=body.amount,
        driver_id=body.driver_id,
        vehicle_id=body.vehicle_id,
        order_id=body.order_id,
        note=body.note,
        operator_id=operator_id,
    )
    db.add(e)
    db.flush()
    # 分类名 → 现金流水口径（报表按它分类汇总）。
    # ⚠️ 中文名与**老英文键**都要认：迁移会把老键翻成中文名，但已经写进流水的老数据
    #    以及别的库（测试库）里可能还是老键；**认不出的落 OTHER**，不抛异常 ——
    #    用户新加一个分类不该让这笔开销存不进去。
    biz_map = {
        "加油": CashFlowBizType.EXPENSE_FUEL, "fuel": CashFlowBizType.EXPENSE_FUEL,
        "维修": CashFlowBizType.EXPENSE_REPAIR, "repair": CashFlowBizType.EXPENSE_REPAIR,
        "过路": CashFlowBizType.EXPENSE_TOLL, "toll": CashFlowBizType.EXPENSE_TOLL,
        "停车": CashFlowBizType.EXPENSE_PARKING, "parking": CashFlowBizType.EXPENSE_PARKING,
        "罚款": CashFlowBizType.EXPENSE_FINE, "fine": CashFlowBizType.EXPENSE_FINE,
        "保险": CashFlowBizType.EXPENSE_INSURANCE, "insurance": CashFlowBizType.EXPENSE_INSURANCE,
        "货损": CashFlowBizType.EXPENSE_LOSS, "loss": CashFlowBizType.EXPENSE_LOSS,
        "其他": CashFlowBizType.EXPENSE_OTHER, "other": CashFlowBizType.EXPENSE_OTHER,
    }
    db.add(
        CashFlow(
            flow_date=body.exp_date,
            direction=CashFlowDirection.OUT,
            amount=body.amount,
            party_type="expense",
            party_id=e.id,
            party_name=str(body.category),
            channel="cash",
            biz_type=biz_map.get(str(body.category), CashFlowBizType.EXPENSE_OTHER),
            order_id=body.order_id,
            doc_id=e.id,
            note=body.note,
            operator_id=operator_id,
        )
    )
    return e
