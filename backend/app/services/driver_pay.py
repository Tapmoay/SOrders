"""司机计费规则 → 钱：**唯一的计算处**。

### 为什么必须有这个文件（而不是在四个地方各算一遍）
"这个司机这一单拿多少"今天散在**四处**：送达生成账单（`services/accounting_service.py`）、
手动补单（`api/v1/driver_bills.py`）、运费结算页（`api/v1/freight_settlement.py`）、
司机绩效（`services/stats_service.py`）。它们现在**恰好**都等于"订单运费"，
所以四处各写一遍也看不出问题；一旦规则能配成"固定工资 + 运费 5% 提成"，
四处里只要有一处没跟上，就会出现"账单说 120、结算页说 500"这种
**两张表对不上、而两边都不报错**的局面。

这个仓库已经因为同一个原因栽过一次：`billing_mode` 的大小写——
同一个司机在账单里算计件、在结算页里看不到（见 `models/user.py::normalize_billing_mode`）。
那次是把"判据"收口成一处，这次是把"算法"收口成一处。

### 规则长什么样（三件，可任意组合）
| 件 | 字段 | 说明 |
| --- | --- | --- |
| ① 固定工资 | `salary` | 元/月，走月度工资单（`driver_bills` 的 SALARY 单） |
| ② 每单固定 | `piece_amount` × `piece_unit` | `order`=每单/每车固定金额；`item`=每件固定金额 |
| ③ 提成 | `commission_base` × `commission_rate` | `freight`=订单运费的百分之几；`goods`=商品金额的百分之几 |

用户 2026-09-18 要的那些说法都能拼出来：
- 普通车司机只拿固定工资 → `salary=8000`
- 普通车司机按车辆提成 → `piece_amount=200`（每车 200）
- 挂车司机计件（一趟货多少钱） → `piece_amount=500`
- 挂车司机固定工资 + 提成 → `salary=6000 + commission_base=freight, commission_rate=5`
- 拿全额运费（改造前的老行为） → `commission_base=freight, commission_rate=100`

### 老账怎么办
`rule=None` 时 `order_pay` 返回**全额运费**——和改造前的算法一字不差。
所以没有挂规则的司机（存量数据）金额不变，历史账单不会被这次改造动到。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

#: 金钱字段的上限（与 `schemas/money.py::MONEY_MAX` 同一个数：列宽 Numeric(12,2)）。
#: 逐单覆盖值的上界判据要用它（见 `override_problem`）。
MONEY_MAX = Decimal("9999999999.99")

ZERO = Decimal("0.00")
_CENT = Decimal("0.01")

# 允许的取值（写错就是静默算错钱，所以只认这几个）
# order_price = 拿**这一单**的钱（金额由派单员在派单时填，逐单不同）——用户 2026-09-18：
# 「每单有多少钱，但每单是不固定的，几百块、几十块，这些单价是由派单员来决定的」
PIECE_UNITS = ("order", "order_price", "item")
COMMISSION_BASES = ("none", "freight", "goods")
# 每单金额怎么定：`uniform` = 所有单统一（规则上的 piece_amount / commission_rate）；
# `category` = **按运费分类**逐类定价（金额在 `driver_billing_rule_categories` 里）。
# 用户 2026-09-21：「按单计费有两种规则：所有单统一价/统一提成，或者按分类匹配」。
PIECE_MODES = ("uniform", "category")
_VEHICLE_TYPES = ("small", "large", "trailer")

PIECE_UNIT_CN = {"order": "单", "order_price": "单（按派单时定的价）", "item": "件"}
COMMISSION_BASE_CN = {"freight": "运费", "goods": "商品金额"}


def money(v) -> Decimal:
    """任何东西 → 两位小数的金额（四舍五入）。None/空串 → 0。"""
    if v is None or v == "":
        return ZERO
    if not isinstance(v, Decimal):
        v = Decimal(str(v))
    return v.quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PayRule:
    """一份解析好的计费规则（不依赖数据库，可单独测试）。"""

    rule_id: int | None = None
    name: str = ""
    salary: Decimal = ZERO
    piece_amount: Decimal = ZERO
    piece_unit: str = "order"
    commission_base: str = "none"
    commission_rate: Decimal = ZERO
    vehicle_type: str | None = None
    # 只对哪些商品抽成（空 = 不限）。用户 2026-09-18：「哪些商品是要抽成的」
    commission_product_ids: tuple[int, ...] = ()
    #: `uniform`（所有单统一）或 `category`（按运费分类）。
    piece_mode: str = "uniform"
    #: 按分类定价表：`(分类编号, 每单金额, 提成比例)`。只在 `piece_mode == "category"` 时有意义。
    by_category: tuple[tuple[int, Decimal, Decimal], ...] = ()

    @property
    def has_salary(self) -> bool:
        return self.salary > 0

    @property
    def by_category_pay(self) -> bool:
        """这份规则的每单金额是按**分类**定的（而不是所有单一个数）。"""
        return self.piece_mode == "category" and bool(self.by_category)

    def category_row(self, category_id) -> tuple[Decimal, Decimal] | None:
        """这一类的（每单金额, 提成比例）；这一类没定价 → None。"""
        if category_id is None:
            return None
        for cid, piece, rate in self.by_category:
            if int(cid) == int(category_id):
                return money(piece), money(rate)
        return None

    @property
    def has_per_order_pay(self) -> bool:
        """这一单有没有"按单应付"（决定要不要生成明细、司机看不看得到运费）。

        ⚠️ **按分类定价时也必须算"有"**：否则派单时模式快照会写成 SALARY，
        `has_per_order_pay(order)` 于是返回 False —— 送达时**连账单都不生成**，
        那笔钱静默消失（这一条是本文件反复强调的同一个坑）。
        """
        if self.by_category_pay:
            return True
        if self.piece_amount > 0:
            return True
        return self.commission_base in ("freight", "goods") and self.commission_rate > 0

    @property
    def pays_nothing(self) -> bool:
        """三件全空 = 这份规则一分钱都不给（创建/修改时会被拒，这里是兜底判据）。"""
        return not self.has_salary and not self.has_per_order_pay

    def describe(self, category_names: dict[int, str] | None = None) -> str:
        """一句话说清它怎么给钱。

        ⚠️ 确认卡、账单说明、司机列表都调它：文案只写一遍，
        否则必然出现"卡片说每单 200、账单按 5% 算"这种前后不一致。

        [category_names] 只在"按分类定价"时有意义（把分类名摆出来，否则用户只知道有几类）。
        """
        parts: list[str] = []
        if self.has_salary:
            parts.append(f"固定工资 {money(self.salary)} 元/月")
        if self.by_category_pay:
            names = category_names or {}
            detail = "、".join(
                f"{names.get(int(cid), '分类' + str(cid))} "
                + (f"{money(piece)} 元/单" if money(piece) > 0 else "")
                + (" · " if money(piece) > 0 and money(rate) > 0 else "")
                + (f"{_plain(rate)}%" if money(rate) > 0 else "")
                for cid, piece, rate in self.by_category
            )
            parts.append(f"按分类定价（{detail}）")
        elif self.piece_amount > 0:
            parts.append(f"每{PIECE_UNIT_CN.get(self.piece_unit, '单')} {money(self.piece_amount)} 元")
        if self.commission_base in ("freight", "goods") and self.commission_rate > 0:
            scope = ""
            if self.commission_base == "goods" and self.commission_product_ids:
                scope = f"（只算 {len(self.commission_product_ids)} 个指定商品）"
            parts.append(
                f"{COMMISSION_BASE_CN[self.commission_base]}的 {_plain(self.commission_rate)}%{scope}"
            )
        return " + ".join(parts) if parts else "不计费"


@dataclass(frozen=True)
class OrderPay:
    """一单的司机应得（拆成件，便于账单/结算页把账摆开给人看）。"""

    piece: Decimal = ZERO
    commission: Decimal = ZERO
    basis: Decimal = ZERO  # 提成基数实际金额（没有提成时是 0）
    # 这一次**实际用了哪个比例**（可能来自派单员对这一单的指定，而不是规则里的默认值）
    rate_used: Decimal = ZERO
    # 这一单的金额/比例是不是派单员单独指定的（账单要写出来，否则事后没人说得清为什么和别人不一样）
    piece_overridden: bool = False
    rate_overridden: bool = False
    #: 规则是"按分类定价"、而这一单**没有分类或那一类没定价** → 这份钱没算出来。
    #: 界面/账单要如实说出来（不是 0 元"算出来是 0"，而是"没定价"）。
    category_unmatched: bool = False

    @property
    def total(self) -> Decimal:
        return money(self.piece + self.commission)


def order_pay(
    rule: PayRule | None,
    *,
    freight_fee=None,
    goods_amount=None,
    quantity: int | None = None,
    piece_override=None,
    rate_override=None,
    category_id=None,
) -> OrderPay:
    """一单司机应得。

    **rule=None = 老账（计件=全额运费），行为与改造前一字不差。**

    ### 两个 override 是"派单员对这一单说了算"（用户 2026-09-18 的原话）
    「他是每单有多少钱，但是每单是不固定的，可能这一单是几百块、那一单是几十块，
    这些单价是由派单员来决定的」——所以每单的钱可以**逐单**给；「提成又是另外一回事了，
    可能设置这一单或者这一类单」——所以比例也可以**逐单**给。
    两个 override 都不是"新发明"：它们就是订单上的两个字段，派单时由派单员填。
    """
    fee = money(freight_fee)
    if rule is None:
        return OrderPay(piece=fee, commission=ZERO, basis=ZERO, rate_used=ZERO)

    # 这一单的"基价"从哪来：按分类定价 → 查这一单的分类；否则用规则上那个统一的数
    category_unmatched = False
    if rule.by_category_pay:
        row = rule.category_row(category_id)
        category_unmatched = row is None
        base_piece, base_rate = row if row is not None else (ZERO, ZERO)
    else:
        base_piece, base_rate = rule.piece_amount, rule.commission_rate

    if piece_override is not None:
        piece = money(piece_override)
        piece_overridden = True
    else:
        piece_overridden = False
        if rule.piece_unit == "order_price":
            # 「拿这一单的钱」——金额由派单员在派单时填（不固定），不是规则里的固定数
            piece = fee
        elif rule.piece_unit == "item":
            piece = base_piece * Decimal(int(quantity or 0))
        else:
            piece = base_piece

    rate = money(rate_override) if rate_override is not None else base_rate
    rate_overridden = rate_override is not None
    basis = ZERO
    if rule.commission_base == "freight":
        basis = fee
    elif rule.commission_base == "goods":
        basis = money(goods_amount)
    commission = basis * rate / Decimal("100")

    return OrderPay(
        piece=money(piece),
        commission=money(commission),
        basis=money(basis),
        rate_used=money(rate),
        piece_overridden=piece_overridden,
        rate_overridden=rate_overridden,
        category_unmatched=category_unmatched,
    )


def rule_of_user(user) -> PayRule | None:
    """司机挂着的规则（没挂 → None）。需要 `user.driver_rule` 已加载/可懒加载。"""
    rule = getattr(user, "driver_rule", None)
    if rule is None:
        return None
    return PayRule(
        rule_id=rule.id,
        name=rule.name or "",
        salary=money(rule.salary),
        piece_amount=money(rule.piece_amount),
        piece_unit=rule.piece_unit or "order",
        commission_base=rule.commission_base or "none",
        commission_rate=money(rule.commission_rate),
        commission_product_ids=tuple(int(x) for x in (getattr(rule, "commission_product_ids", None) or [])),
        vehicle_type=rule.vehicle_type or None,
        piece_mode=str(getattr(rule, "piece_mode", None) or "uniform"),
        by_category=tuple(
            (int(r.category_id), money(r.piece_amount), money(r.commission_rate))
            for r in (getattr(rule, "category_rows", None) or [])
        ),
    )


def pay_summary_for(user, *, include_money: bool = True) -> str:
    """一句话说清这个司机**现在**怎么算钱（司机管理页那一列）。

    `include_money=False` 用于非派单员视角：规则里含工资金额，而"工资仅派单员可见"
    是这个项目既有的一条硬约定（`api/v1/users.py::_to_out` 把 salary 置空）——
    所以那句话也不能带着金额漏出去。
    """
    from app.models.user import resolve_billing_mode

    rule = rule_of_user(user)
    if rule is not None:
        return rule.describe() if include_money else "已挂计费规则"
    mode = resolve_billing_mode(getattr(user, "vehicle_type", None), getattr(user, "billing_mode", None))
    if mode == "PIECE":
        return "按单计费：每单拿该单的运费（未挂规则）"
    sal = money(getattr(user, "salary", None))
    if sal > 0:
        return f"固定工资 {sal} 元/月（未挂规则）" if include_money else "固定工资（未挂规则）"
    return "固定工资（月薪未设置，账单里不会出现他的工资单）"


def monthly_salary_of(user) -> Decimal:
    """这个司机这个月的固定工资（0 = 不给他生成工资单）。

    挂了规则 → 规则说多少就是多少；没挂规则 → 沿用老口径（只有 SALARY 司机才有工资）。
    两边共用一处，是为了让"生成工资单"和"司机列表显示"永远说同一句话。
    """
    from app.models.user import resolve_billing_mode

    rule = rule_of_user(user)
    if rule is not None:
        return money(rule.salary)
    mode = resolve_billing_mode(getattr(user, "vehicle_type", None), getattr(user, "billing_mode", None))
    if mode != "SALARY":
        return ZERO
    return money(getattr(user, "salary", None))


def snapshot_mode(user) -> str:
    """派单时写进 `orders.driver_billing_mode_snapshot` 的值。

    ⚠️ 这个字段的语义在本轮被**明确**成："这张单司机按不按单拿钱"
    （PIECE = 有按单应付；SALARY = 只拿月薪）——因为它现有的每个消费点要的都是这个意思：
    运费对他可不可见（`order_response`）、运费改了要不要提醒他（`message_center`）、
    结算页列不列他（`freight_settlement`）、绩效里算不算他的待结（`stats_service`）。
    语义一旦按"按不按单拿钱"来读，这四处**都不用改**，也不会因为新增规则种类而漏判。
    """
    from app.models.user import resolve_billing_mode

    rule = rule_of_user(user)
    if rule is not None:
        return "PIECE" if rule.has_per_order_pay else "SALARY"
    return resolve_billing_mode(getattr(user, "vehicle_type", None), getattr(user, "billing_mode", None))


def dispatch_mode(user, *, piece_override=None, rate_override=None) -> str:
    """派单那一刻写进订单的模式快照（在 [snapshot_mode] 之上把逐单覆盖算进去）。

    ⚠️ 派单员给这一单单独定了金额 → **这张单就是"有按单应付"**，哪怕司机的规则里
    只有固定工资。理由：`has_per_order_pay` 是送达生成账单的开关，
    模式留在 SALARY 的话，那笔单独定的钱会掉进"工资制司机不生成按单账单"的缝里
    （钱在订单上、账单里没有，两边都不报错）。
    """
    if piece_override is not None or rate_override is not None:
        return "PIECE"
    return snapshot_mode(user)


def order_mode(order) -> str:
    """**这一张单**按什么模式读（PIECE = 有按单应付；SALARY = 只拿月薪）。

    ### 为什么必须只有这一处
    `driver_billing_mode_snapshot` 是 v3.36 才加的列，之前派出去的老单是 NULL ——
    于是"读这张单是什么模式"就多了一问：老单怎么办？老单的答案**早就定过**
    （`has_per_order_pay` 的注释 + `driver_bills` / `freight_settlement` 两处
    `snapshot == 'PIECE' OR snapshot IS NULL` 的筛选）：**有运费就算有**，
    因为那些单本来就出自"按运费全额"的时代。

    但四个展示/门控消费点（`order_response` 的运费可见性、`message_center` 的运费变更提醒、
    `order_flow` 的拍照义务）各自抄了一份兜底 `快照 or resolve_billing_mode(车型, 计费)`——
    那算的是司机**现在**的档案，于是同一张老单会出现
    「账单按单给他结、界面上却看不见运费」或「免了拍照，却在按单付钱」。两边都不报错。
    所以兜底只留这里一处：**钱怎么说，读侧就怎么说**。
    """
    mode = (getattr(order, "driver_billing_mode_snapshot", None) or "").upper()
    if mode:
        return mode
    return "PIECE" if getattr(order, "freight_fee", None) is not None else "SALARY"


def has_per_order_pay(order) -> bool:
    """订单快照说这张单有没有按单应付（老单：PIECE 快照 = 有）。"""
    return order_mode(order) == "PIECE"


def override_problem(rule: PayRule | None, *, piece_override=None, rate_override=None) -> str | None:
    """派单员给这一单单独定的数**能不能真的生效**（不能生效就返回中文原因，None = 没问题）。

    ### 为什么必须有这个函数
    逐单覆盖是常态（用户 2026-09-18：「每单是不固定的…这些单价是由派单员来决定的」），
    而 `order_pay` 遇到下面两种规则时会**照收不误、算出来是另一个数**：

    | 现场 | `order_pay` 的结果 |
    | --- | --- |
    | 司机没挂规则（`rule=None`） | 直接返回**全额运费**，两个覆盖值都没读 |
    | 规则的 `commission_base=none` | `basis=0` → 提成恒为 **0** |

    也就是说派单员填了 300、账单还是按规则算，**两边都不报错**。这种"填了没用"
    比填错更难查：界面上有数字、账单里也有数字，只有对账时才发现两个数没关系。

    ⚠️ 范围检查（负数/超 100%）也放在这里，而不是 schema 的 `ge/le`——
    越界走 Pydantic 会变成 422 + 一段英文结构体，而派单员/AI 需要的是一句能照着改的中文。
    （与 `schemas/driver_billing_rule.py::validate_rule_params` 同一条理由。）
    """
    if piece_override is None and rate_override is None:
        return None
    if rule is None:
        return (
            "这个司机还没挂计费规则，逐单的金额/比例没有地方生效"
            "（先用「计费规则」给他挂一份规则，或者按老口径直接填运费）"
        )
    if money(piece_override) < 0:
        return "这一单的司机金额不能是负数"
    # ⚠️ **上界**（2026-09-19 审计 R12-L6）：原来只有下界，而 `driver_piece_amount` 是
    #    逐单覆盖值里**唯一没有上界**的一个——它被 `schemas/money.py` 的 `NOT_MONEY`
    #    排除在通用容量检查之外（注释说"范围判据在 override_problem"，那句话当时只兑现了一半），
    #    于是 1e20 能被本机 SQLite 原样收下（生产 `Numeric(12,2)` 会 `Out of range` → 500），
    #    送达时还会带着这个数生成账单、结算单、现金流水——一条链全炸。
    #    这里补上界，与 `MoneyInput` 的 MONEY_MAX 同一个数（列宽 Numeric(12,2) 的上限）。
    if money(piece_override) > MONEY_MAX:
        return f"这一单的司机金额不能超过 {MONEY_MAX} 元（金钱字段的上限）"
    if rate_override is not None:
        if rule.commission_base == "none":
            return (
                f"「{rule.name or '这个司机挂的规则'}」里没有提成项，逐单定比例算出来永远是 0"
                "（要按这一单提成，先把规则的提成基数选上：按运费或按商品金额）"
            )
        if money(rate_override) > 100:
            return "这一单的提成比例不能超过 100%"
    return None


def order_goods_amount(order, product_ids: tuple[int, ...] = ()) -> Decimal:
    """订单商品金额（提成基数之一）= 商品行小计的合计。

    `product_ids` 非空时**只算这些商品的行**——"哪些商品是要抽成的"就落在这里。
    手工加的行（没有 product_id）在限定范围时不算：范围是按商品库里的商品定的。
    """
    lines = getattr(order, "order_products", None) or []
    total = ZERO
    for line in lines:
        if product_ids:
            pid = getattr(line, "product_id", None)
            if pid is None or int(pid) not in product_ids:
                continue
        total += money(getattr(line, "line_total", None))
    return money(total)


def order_quantity(order) -> int:
    lines = getattr(order, "order_products", None) or []
    return sum(int(getattr(line, "quantity", 0) or 0) for line in lines)


def pay_for_order(order) -> OrderPay:
    """订单 → 司机应得（用**订单上的规则快照**，不是司机当前的规则）。

    快照的意义和历史账单一致：司机后来换了规则，已经送完的单不能跟着变。
    每单的两个覆盖值（金额/比例）也在这里读——它们本来就是订单上的字段。
    """
    rule = rule_from_snapshot(getattr(order, "driver_rule_snapshot", None))
    scope = rule.commission_product_ids if rule is not None else ()
    return order_pay(
        rule,
        freight_fee=getattr(order, "freight_fee", None),
        goods_amount=order_goods_amount(order, scope),
        quantity=order_quantity(order),
        piece_override=getattr(order, "driver_piece_amount", None),
        rate_override=getattr(order, "driver_commission_rate", None),
        # 这一单属于哪一类货（派单时由匹配到的价目带过来 / 手动定价时指定）
        category_id=getattr(order, "freight_category_id", None),
    )


# ---------------------------------------------------------------- 快照的序列化

def rule_to_snapshot(rule: PayRule | None) -> str | None:
    """规则 → 订单上的快照（JSON 字符串）。None 表示"这单没挂规则"。"""
    if rule is None:
        return None
    return json.dumps(
        {
            "rule_id": rule.rule_id,
            "name": rule.name,
            "salary": str(rule.salary),
            "piece_amount": str(rule.piece_amount),
            "piece_unit": rule.piece_unit,
            "commission_base": rule.commission_base,
            "commission_rate": str(rule.commission_rate),
            "commission_product_ids": list(rule.commission_product_ids),
            "vehicle_type": rule.vehicle_type,
            # 按分类定价的**表**也要进快照：改规则不追溯已派单（这是本文件的口径）
            "piece_mode": rule.piece_mode,
            "by_category": [
                {"category_id": int(cid), "piece_amount": str(money(piece)), "commission_rate": str(money(rate))}
                for cid, piece, rate in rule.by_category
            ],
        },
        ensure_ascii=False,
    )


def rule_from_snapshot(raw: str | None) -> PayRule | None:
    """快照 → 规则。**读不动就返回 None（退回老口径），不许抛异常**——
    一个坏掉的快照不该让送达流程直接 500（那会卡住司机交单）。"""
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    return PayRule(
        rule_id=d.get("rule_id"),
        name=str(d.get("name") or ""),
        salary=money(d.get("salary")),
        piece_amount=money(d.get("piece_amount")),
        piece_unit=str(d.get("piece_unit") or "order"),
        commission_base=str(d.get("commission_base") or "none"),
        commission_rate=money(d.get("commission_rate")),
        commission_product_ids=tuple(int(x) for x in (d.get("commission_product_ids") or [])),
        vehicle_type=(d.get("vehicle_type") or None),
        piece_mode=str(d.get("piece_mode") or "uniform"),
        by_category=tuple(
            (int(r.get("category_id")), money(r.get("piece_amount")), money(r.get("commission_rate")))
            for r in (d.get("by_category") or [])
            if isinstance(r, dict) and r.get("category_id") is not None
        ),
    )


def _plain(v: Decimal) -> str:
    """5.00 → '5'；5.50 → '5.5'（文案里不要出现 '5.00%' 这种机器味）。"""
    s = str(money(v))
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"
