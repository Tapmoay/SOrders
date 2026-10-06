"""一张订单的**钱**只有这一份算法：应收 / 已收 / 已退 / 欠款。

## 为什么必须只有一处实现（2026-09-20）

在这之前，"这张单还欠多少"是靠 `orders.paid` 一个布尔 + 现场把 `order_products.line_total`
加起来**在四个地方各算一遍**（营业纵览、挂账单位报表、订单出参、账本页）。那时它是安全的 ——
因为核销只有一种形态：**整单核销**，`paid` 一翻就是"全收"或"全没收"，四处算出来的数必然一致。

本轮加进来的两件事把这个前提打破了：

1. **按商品核销**（用户：「点击订单点击核销……也可以按商品进行核销」）——
   一张单可以只收一部分钱，`paid` 仍然是 False，而"欠多少"已经不是整单金额了；
2. **退货红冲**（用户：「可以整单退货，也可以只退其中的某几个商品」）——
   应收会被 `ledgers` 上的负金额红冲行**减掉**，而 `order_products.line_total` 不会变
   （那是"当时卖了多少"，不是"现在该收多少"）。

两者叠加之后，四处各算一遍必然出现"同一个客户，报表说欠 700、账本页说欠 1000"，
而且**两边都不报错**。所以这里把口径钉成一处，四个消费点全部改成调它：

## 口径（唯一一份，改这里就是改全局）

    total       = Σ 商品行 line_total          （当时卖了多少，不随退货变）
    returned    = Σ |ledgers.source=RETURN 的 total|（已退金额，正数）
    receivable  = total − returned             （**应收**：营业额看的也是这个数）
    settled     = 已收：Σ(cash_flows IN, 本单) ；现场收现金（`paid` 且没有流水）按 total 计
    refunded    = Σ(cash_flows OUT 且 biz_type=REFUND_CUSTOMER, 本单)（已退给客户的现金）
    arrears     = receivable − settled + refunded   （**欠款**；< 0 = 预收）

两边恒等式（验算见 `tests/test_order_return.py`）：
`receivable == (settled − refunded) + arrears`，也就是「应收 = 净已收 + 欠款」。

## 两个必须记住的坑

· **现场收现金没有现金流水**（`orders.py::_apply_complete_payment` 只翻 `paid`），
  所以 `settled` 不能只看流水 —— 只看流水会把"司机现场收的现金"当成没收到，
  这张单会永远留在催收名单里，而且收款人手里明明有钱。
· **`cash_flows` 里挂在本单上的 OUT 不都是退款**：货损成本（`EXPENSE_LOSS`）也带 `order_id`。
  退款的判据只有 `biz_type == REFUND_CUSTOMER` 一条，用"所有 OUT"会把货损当成退给客户的钱。
"""

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.models import CashFlow, Ledger, Order, OrderProduct
from app.models.enums import CashFlowBizType, LedgerSource

ZERO = Decimal("0")


def q2(v: Decimal) -> Decimal:
    """全项目统一两位小数（与 `driver_pay.money()` 同一个进位方式，见那里的注释）。"""
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class OrderMoney:
    """一张订单的钱。所有字段都已经是"可以直接显示"的两位小数。"""

    total: Decimal
    returned: Decimal
    receivable: Decimal
    settled: Decimal
    refunded: Decimal
    arrears: Decimal
    fully_returned: bool

    @property
    def net_collected(self) -> Decimal:
        """净已收 = 已收 − 已退现。与 [arrears] 相加必然等于 [receivable]。"""
        return q2(self.settled - self.refunded)


def _group_sum(db: Session, key_col, value_col, *where) -> dict[int, Decimal]:
    """按 `order_id` 分组求和（一次查询解决一张列表，避免逐单发 SQL）。

    ⚠️ `value_col` 传**列对象**、不传 `func.sum(...)`：传聚合表达式进来会变成
       `sum(sum(x))`，SQLite 直接报 `misuse of aggregate function sum()`
       （第一版就是这么写的，跑测试当场红）。
    """
    stmt = select(key_col, func.sum(value_col)).where(key_col.isnot(None), *where).group_by(key_col)
    return {int(k): Decimal(v or 0) for k, v in db.execute(stmt).all()}


def _is_inflow(direction: object) -> bool:
    """是不是"钱进来"。`direction` 两种库里都存小写（`in`/`out`），老数据可能带大写。"""
    return str(getattr(direction, "value", direction) or "").lower() == "in"


def _is_customer_refund(direction: object, biz: object) -> bool:
    """是不是"退给客户的现金"。**只看 `REFUND_CUSTOMER`** —— 货损成本流水也挂 `order_id`。"""
    if str(getattr(direction, "value", direction) or "").lower() != "out":
        return False
    return str(getattr(biz, "value", biz) or "") == CashFlowBizType.REFUND_CUSTOMER.value


def line_unit_price(op: OrderProduct) -> Decimal:
    """这一行**真正卖的单价**（4 位小数）—— 打过折的行返回折后单价。

    行金额与「单价 × 数量」一致（绝大多数行）⇒ 原样返回 `unit_price`，一个字节都不动；
    不一致 ⇒ 返回 **行金额 ÷ 数量**（这一行是被打过折的：`line_total` 被写成了折后值，
    见 `services/order_discount.py` 与 CHG-0071）。

    为什么要有它：退货的红冲（`order_return._line_amount`）与"这一行还能收多少"
    （`line_receivable`）都得按**客户当时实付的单价**算 —— 用 `unit_price` 的话，
    打过折的单退了货会按原价退，退得比收的多（用户口径 ref m13365：「退货按折后实付退」）。
    """
    qty = Decimal(int(op.quantity or 0))
    unit = Decimal(op.unit_price or ZERO)
    total = Decimal(op.line_total) if op.line_total is not None else unit * qty
    if qty <= 0:
        return unit.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if total == q2(unit * qty):
        return unit.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return (total / qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def line_receivable(op: OrderProduct) -> Decimal:
    """**这一行现在还能收多少** = 行金额 − 折后单价 × 已退数量。

    这是"按商品核销"的金额来源，也是整单核销的金额来源（整单 = 所有行的和）：
    两者必须是同一个算法，否则会出现"整单核销要 700、按商品加起来要 1000"
    —— 而两个数都印在同一张核销弹层上。

    为什么不用 `quantity − returned_quantity` 直接乘单价：`line_total` 在生产库里有
    历史折扣（不等于 `单价×数量`），按行存下来的 `line_total` 才是当时真正卖的价。

    退掉的那部分按 `line_unit_price`（折后单价）冲，⛔ 不是 `unit_price`：客户实付多少就退多少。
    """
    total = op.line_total if op.line_total is not None else (op.unit_price or ZERO) * Decimal(op.quantity or 0)
    returned = line_unit_price(op) * Decimal(int(op.returned_quantity or 0))
    return q2(Decimal(total) - returned)


def money_map(db: Session, orders: list[Order], *, lock: bool = False) -> dict[int, OrderMoney]:
    """一批订单的钱（**4 条分组查询，与订单条数无关**）。

    ⚠️ 不许改成"逐单 `money_of`"：订单列表一页 300 条就是 1200 条 SQL，
       而 `enrich_order_out` 本来就已经在逐单 `db.get` 了（`ledger_response` 那条注释
       记着同类问题的实测代价：85,474 行 → 27.75 秒）。

    `lock=True` = **收款的防重算**要用的那一档（`accounting_service.create_receipt`）：
    现金流水改成**加锁读**（`SELECT … FOR UPDATE`）并在 Python 里用同一套判据汇总。
    为什么非这样不可：MySQL 的 REPEATABLE READ 下，普通 SELECT 读的是事务**开始时**的快照 ——
    两个并发核销各自读到"还欠 1000"，就都能通过"这次核销不许超过欠款"的校验，
    结果收了两倍的钱（**而这正是本项目最贵的一类错**）。加锁读永远读到最新已提交值，
    且后到的那个请求会一直等到前一个提交后才继续 —— 于是它看到的是"还欠 300"。
    """
    ids = [o.id for o in orders]
    if not ids:
        return {}

    totals = _group_sum(
        db, OrderProduct.order_id, OrderProduct.line_total, OrderProduct.order_id.in_(ids)
    )
    # 退货红冲行存的是**负数**（红冲），取负号变回"已退金额"这个正数口径
    returned = _group_sum(
        db,
        Ledger.order_id,
        Ledger.total,
        Ledger.order_id.in_(ids),
        Ledger.source == LedgerSource.RETURN,
    )
    if lock:
        inflow: dict[int, Decimal] = {}
        refund: dict[int, Decimal] = {}
        flow_rows = db.execute(
            select(CashFlow.order_id, CashFlow.direction, CashFlow.biz_type, CashFlow.amount)
            .where(CashFlow.order_id.in_(ids), CashFlow.is_deleted.is_(False))
            .with_for_update()
        ).all()
        for oid, direction, biz, amount in flow_rows:
            if _is_inflow(direction):
                inflow[oid] = inflow.get(oid, ZERO) + Decimal(amount or 0)
            elif _is_customer_refund(direction, biz):
                refund[oid] = refund.get(oid, ZERO) + Decimal(amount or 0)
    else:
        inflow = _group_sum(
            db,
            CashFlow.order_id,
            CashFlow.amount,
            CashFlow.order_id.in_(ids),
            func.lower(CashFlow.direction) == "in",
            # ⛔ 已撤销的流水不参与任何金额（2026-09-22 `cash_flows` 加了软删之后）。
            #    今天能走到这里的流水都是订单上的（`order_id` 非空），而"撤销"目前只发生在
            #    供应商付款（`order_id` 恒为空）上 —— 也就是说这一句**今天不影响任何数**。
            #    留着它的理由是"读取处一律带这一句"这条不变量：留例外就要有一张例外名单，
            #    而例外名单一定会腐烂（本项目栽过 6 次）。哪天订单收款也能撤，这里就已经对了。
            CashFlow.is_deleted.is_(False),
        )
        refund = _group_sum(
            db,
            CashFlow.order_id,
            CashFlow.amount,
            CashFlow.order_id.in_(ids),
            func.lower(CashFlow.direction) == "out",
            CashFlow.biz_type == CashFlowBizType.REFUND_CUSTOMER,
            CashFlow.is_deleted.is_(False),
        )

    out: dict[int, OrderMoney] = {}
    for o in orders:
        total = q2(totals.get(o.id, ZERO))
        ret = q2(-returned.get(o.id, ZERO))
        receivable = q2(total - ret)
        got = inflow.get(o.id, ZERO)
        # 现场收现金：`paid=True` 却**一条流水都没有**（见模块头注释）。
        # ⚠️ 判据必须是"有没有流水"，不能写成 `max(got, total if paid else 0)`：
        #    退过货的单的应收比 `total` 小，收款是按应收收的（流水 60 < total 100），
        #    取 max 会把已收算成 100 → 欠款变 −40（"预收 40"），而钱其实一分不差。
        settled = q2(got if got > ZERO else (total if o.paid else ZERO))
        refunded = q2(refund.get(o.id, ZERO))
        out[o.id] = OrderMoney(
            total=total,
            returned=ret,
            receivable=receivable,
            settled=settled,
            refunded=refunded,
            arrears=q2(receivable - settled + refunded),
            # 整单退完的判据：退掉的金额已经把应收冲平（而不是"退过一次"）
            fully_returned=bool(ret > 0 and ret >= total),
        )
    return out


def money_of(db: Session, order: Order, *, lock: bool = False) -> OrderMoney:
    """单张订单的钱（**列表请用 [money_map]**，别在循环里调它）。"""
    return money_map(db, [order], lock=lock)[order.id]


# ---------------------------------------------------------------------------
# 承运运费的**来源凭据**（freight provenance）—— R4-11
#
# 用户 2026-09-27 拍板（§6）：历史承运运费缺少 provenance ——「金额有、分类有，
# **没记是哪一条价目产生的**」，也没有记按哪一版契约算的。所以从这一版起：
#
#     一笔承运运费 = 金额 + **它凭什么**
#
# ## 三条不变量（这一段存在的全部理由）
#
# 1. **同一处写**：`orders.freight_fee` **只许在本文件里被赋值**（判据扫全仓）。
#    写它的那条路必须**同时**写 `freight_rule_snapshot` —— 同一事务、同一个决定。
#    ⛔ 不许出现"改了金额没改快照""改了快照金额没动""先改金额、事后再异步补来源"。
# 2. **同生共死**：`freight_fee is None` ⟺ `freight_rule_snapshot is None`（新数据）。
#    ⛔ **老数据（R4-11 之前落库的）不补** —— 那时候确实没有记来源，
#    拿今天的价目表倒推历史 = **伪造历史事实**（用户原话：「千万不要猜着补快照」）。
# 3. **每次写金额 = 一次新的定价决定**：快照描述的是"**当前这个金额**凭什么"，
#    所以重新定价 / 改分类 / 事后补录时**整份替换**，既不合并也不追加。
#    改动历史不在这里 —— 它在 `operation_logs`（`ORDER_FREIGHT` / `ORDER_FREIGHT_PRICE`）。
#
# ## 快照里有什么（少一样就回答不了"这个数凭什么"）
#
# | 键 | 回答什么 |
# | --- | --- |
# | `source` | 这一次是**怎么产生的**（手动定价 / 派单定价 / 事后补录） |
# | `rule` | 用了**哪一条价目**（含它当时的金额 + "这条是怎么拿到的"）—— 空 = 没有价目 |
# | `pricing.kind` | 用了**什么计价方式**（R4-05 那个数据级选择器） |
# | `pricing.contract` | 属于**哪一版计价契约**（用 R4-02 的身份规范：name + version） |
# | `category` | 这一单按**哪一类货**算的 |
# | `fee` | 这次决定算出来的**金额**（必须等于 `orders.freight_fee`） |
# | `at` | 决定时刻（UTC naive，与全库时间口径一致） |
#
# ⚠️ 生产今天跑的**不是** PricingContract 扩展（那是 R4 的演练产物），而是核心的价目匹配
#    （`services/freight_pricing.quote_for`）—— 所以这里**如实**写
#    `kind="freight_template"` + `contract={"name": "FreightPricingCore", ...}`。
#    ⛔ 编一个 "PricingContract v1" 写上去就是**记假事实**：那会让以后的读者以为这一笔是扩展算的。
#    扩展真的接上生产钱路时（R4-P2），这两个值必须**一起**改 —— 那正是它们存在的意义。
# ---------------------------------------------------------------------------

#: 这一次运费是**怎么产生的**（写进快照，不是给人看的枚举名 —— 界面别直接显示它）。
FREIGHT_SOURCE_MANUAL = "manual"    # 派单员手动定价（没匹配到价目那条路）
FREIGHT_SOURCE_ASSIGN = "assign"    # 派单时带上了运费
FREIGHT_SOURCE_ADJUST = "adjust"    # 事后补录 / 修改运费

#: ⭐ 2026-09-27（R4-20 Canary）：**每一条路各自带着它的契约身份**。
#: 在此之前这里只有一个常量 —— 那时生产跑的是核心的价目匹配，所以写
#: `FreightPricingCore`；而 Canary 之后，一部分单的金额**真的是 PricingContract 算出来的**，
#: 两件事必须分得开：⛔ 一份快照不许同时说两种话。
#:
#: | kind | 谁算的 | 契约身份 |
#: | --- | --- | --- |
#: | `legacy_client` | 核心的价目匹配（金额由派单界面带过来） | `FreightPricingCore v1` |
#: | `freight_template` | 算价扩展 `extensions/pricing/freight_template.py` | `PricingContract v2` |
FREIGHT_KIND_CONTRACTS: dict[str, dict] = {
    "legacy_client": {"name": "FreightPricingCore", "version": 1},
    "freight_template": {"name": "PricingContract", "version": 2},
}

#: 缺省按哪条路记（没走组装点的老调用方用这个）—— 与上面那张表同一份真相。
FREIGHT_PRICING_KIND = "freight_template"
FREIGHT_PRICING_CONTRACT_NAME = "FreightPricingCore"
FREIGHT_PRICING_CONTRACT_VERSION = 1

#: 快照自己的版本（将来加字段时用它区分"这份快照按哪一版格式写的"）。
FREIGHT_PROVENANCE_V = 1


def freight_provenance_of(order) -> dict:
    """订单上那份**承运运费来源凭据**（没记过就返回 `{}`）。

    ⛔ 坏掉的快照当"没有"（返回 `{}`），**不抛** —— 与 `driver_pay.rule_from_snapshot` 同一条口径：
    一份脏 JSON 不该让订单详情整页 500。
    """
    raw = getattr(order, "freight_rule_snapshot", None)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def freight_kind_of(order) -> str | None:
    """这张单**已经定过的计价来源**（没定过 / 快照坏了 / 认不出的取值 → None）。

    ⭐ 为什么单独成一个函数（用户 2026-09-27 拍板的 ⑧-a 出口条件 ③ CANARY_DECISION_FREEZE）：

        「第一次形成有效计价决策后：pricing.kind / contract / implementation
          必须成为该订单该次计价事实的既定来源。
          后续写入不得重新依据当前 canary_percent 改变已经形成的 Pricing Decision。」

    同一张单会被**问很多次**（派单 / 改价 / 补录各问一次），而 Canary 比例在观察期间
    一定会被调（0 → 30 → 100）。比例一调，历史单的来源就跟着变一次 ——
    那正是指南 §9 说的「同一订单不能在运行过程中换算法」，只是换了个入口进来。
    ⇒ 所以"已经定过的那一个"必须能被读回来，而且**只有这一处**会去读它。

    ⛔ 认不出的取值当"没定过"：与 freight_provenance_of 对坏快照的口径一致
    （宁可退回"没有"，也不拿一个不认识的 kind 去冻结后面所有写入）。
    """
    kind = (freight_provenance_of(order).get("pricing") or {}).get("kind")
    return kind if kind in FREIGHT_KIND_CONTRACTS else None


def rule_ref_of(
    *,
    origin: str,
    template_id,
    template_name: str = "",
    price_name: str = "",
    route: str = "",
    fee=None,
) -> dict:
    """价目的身份 → 快照里的 `rule` 那一格。

    `origin` 必须如实说清这条价目是**怎么拿到的**：
    · `"saved"`   = 这一次定价真的写/改了一条价目（手动定价 + 沉淀那条路）；
    · `"derived"` = **服务端在那一刻按同一个匹配算法复算出来的**（派单 / 补录时客户端没带价目）。
    ⛔ 两种都不能省：少了它，"这条价目到底是谁挑的"就说不清了。

    `fee` 记的是**那一刻**这条价目的金额 —— 价目后来被改价时，
    这一格就是"当时凭什么"的唯一凭据（历史单不引用活价目）。
    """
    return {
        "template_id": int(template_id) if template_id is not None else None,
        "template_name": template_name or "",
        "price_name": price_name or "",
        "route": route or "",
        "fee": None if fee is None else str(q2(fee)),
        "origin": origin,
    }


def rule_ref_of_candidate(candidate, *, origin: str) -> dict:
    """`services/freight_pricing.Candidate`（一次匹配的结论）→ 快照里的 `rule`。"""
    return rule_ref_of(
        origin=origin,
        template_id=getattr(candidate, "template_id", None),
        template_name=getattr(candidate, "name", "") or "",
        price_name=getattr(candidate, "price_name", "") or "",
        route=getattr(candidate, "route", "") or "",
        fee=getattr(candidate, "fee", None),
    )


def rule_ref_of_template(t, *, origin: str) -> dict:
    """一条**价目行**（`models.freight_template.FreightTemplate`）→ 快照里的 `rule`。

    ⛔ 刻意不 import 那个模型：这里只按属性取值，免得"钱的口径"这个模块
    因为一个只读的身份转换而多背一条模型依赖。
    """
    f = (getattr(t, "from_place", "") or "").strip()
    o = (getattr(t, "to_place", "") or "").strip()
    return rule_ref_of(
        origin=origin,
        template_id=getattr(t, "id", None),
        template_name=getattr(t, "name", "") or "",
        price_name=getattr(t, "price_name", "") or "",
        route=(f + " → " + o) if f else o,
        fee=getattr(t, "fee", None),
    )


def record_freight_decision(
    order,
    *,
    source: str,
    fee,
    category_id: int | None = None,
    category_name: str = "",
    rule: dict | None = None,
    kind: str | None = None,
    agreed: bool | None = None,
    override: bool = False,
    reason: str = "",
    note: str = "",
    resolution: str = "",
) -> None:
    """**写承运运费的唯一入口**：金额、分类与它的来源凭据一起落。

    `kind` / `agreed` / `override` / `note` 由**唯一组装点**（`core/pricing_runtime.decide`）
    带过来 —— 这一层不认识"哪条路"，它只负责把那个事实**原样写进快照**。

    ⛔ 全仓库不许在别处写 `order.freight_fee` —— 判据 `_check_pricing_provenance.py`
    扫全仓的 `.freight_fee =` 赋值，只允许出现在本文件里。
    （理由与 `driver_pay` 那条一样：口径一旦有两个写入口，迟早会出现
      "账单 120、订单 135" 这种**两边都不报错**的分叉。）

    `fee=None` = 把这一笔清掉（回到"运费待定"）：那时凭据**一起清空** —— 不变量 2。
    """
    fee2 = None if fee is None else q2(Decimal(fee))
    order.freight_fee = fee2
    order.freight_category_id = category_id
    order.freight_category = (category_name or "")[:32]
    if fee2 is None:
        order.freight_rule_snapshot = None
        return
    payload = {
        "v": FREIGHT_PROVENANCE_V,
        "at": utc_now_naive().isoformat(timespec="seconds"),
        "source": source,
        "fee": str(fee2),
        "category": {"id": category_id, "name": category_name or ""},
        "rule": rule or None,
        "pricing": {
            "kind": kind or FREIGHT_PRICING_KIND,
            "contract": dict(FREIGHT_KIND_CONTRACTS.get(
                kind or FREIGHT_PRICING_KIND,
                {"name": FREIGHT_PRICING_CONTRACT_NAME,
                 "version": FREIGHT_PRICING_CONTRACT_VERSION},
            )),
            # ⚠️ 只在**走了契约**时才有这两个键（旧路没有"算得一样不一样"这回事）。
            #    `override=True` 不是错误：派单员本来就允许改价，这里只是把
            #    "这次的钱来自人、不是来自价目表"这件事记下来。
            # ✅ **机器可读的"为什么"**（走通 / 没走通都有值）：运维可以直接 GROUP BY 出
            #    "生产上最常卡在哪一步"，而不用去读中文。⛔ 有它就别再去解析 note 那串人话。
            **({"reason": reason} if reason else {}),
            # ⭐ **这一次走的是哪条路**（R4-36）：与 kind（来源）正交。
            #    ⛔ 少了它，legacy_client + reason=ok 同时盖住「没抽中」与「已冻结沿用旧路」，
            #    排障时分不出来（这正是生产上 T0/T1/T2 无法辨识的根源）。
            #    取值全集与含义在 core/pricing_runtime.RESOLUTIONS —— ⛔ 不在这里另立一套。
            **({"resolution": resolution} if resolution else {}),
            **({"agreed": bool(agreed), "override": bool(override)} if agreed is not None else {}),
            **({"note": note} if note else {}),
        },
    }
    order.freight_rule_snapshot = json.dumps(payload, ensure_ascii=False)
