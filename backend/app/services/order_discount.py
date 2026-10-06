"""订单打折（CHG-0071 / 台账 L-34）—— **全项目唯一一份折扣算法**。

## 用户要的是什么（原话逐字见 docs/changes/CHG-0071.md）

> 「我们要加个新功能就是商品可以打折，就是订单它可以给订单进行打折，
>   然后我们对应的商品是可以固定价格的，就是不参与打折。」（ref m01280）

四条裁定（ref m01347）：入口只有**派单员改单**（`Permission.ORDER_EDIT`）；两种表达
（百分比 / 抹零）；商品级的「不参与打折」= **算折扣时跳过它**（⛔ 不是"价格不能变"，
改价 / 专属价 / price_rules 照常生效）；范围两档（整单 / 只勾其中几行）。
理由选填但要留痕；**退货按折后实付退**（ref m13365）。

## 为什么钱一定要摊到行上

收款 / 账本 / 营业额 / 毛利全按 `order_products.line_total` 算、
`goods_amount = Σ line_total`（`services/order_money.py`）。只记一个整单折扣而不动行，
这条恒等式当场就破（`tests/test_order_return.py` 钉着它）。所以这里做的是
**把折后的值写进每一行的 `line_total`**；`orders` 上那七列只是"当时打了什么折"的快照。

## 五条口径（每条都有代价，写下来免得下次改回去）

1. **幂等替换，不叠加**：再打一次折 = 先把上一份按快照里的 `before` 还原，再按新的算。
   ⛔ 不还原就再乘一遍 —— 两次 10% 会变成 19%。
2. **`before` 是"我们改之前那一行是多少"**，不是"单价 × 数量"：生产库里存在
   `line_total ≠ 单价×数量` 的历史行（`order_money.line_receivable` 的 docstring 记着），
   靠乘法反推会在取消折扣时改错账。
3. **摊分到分**：总优惠额按各行的金额占比摊（先向下取整到分，余数给小数部分最大的行）。
   两条硬约束 —— Σ 摊出来的 = 优惠额（差一分就与 `goods_amount` 对不上）；
   任何一行**最多减到 0**（⛔ 不许出现负的行金额）。
4. **勾了「不参与打折」的行**：派单员显式勾到它 ⇒ **400 拒绝**（⛔ 不静默过滤 ——
   "他以为打了折、其实没打"是最坏的一种成功）；整单折扣时**自动跳过**它。
5. **改单之后重算**：`api/v1/order_products.py` 改完数量 / 单价后调
   `reapply_after_line_change`，只重算**参与过折扣的那些行**；没折扣的单一个字节都不动。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.models import Order, OrderProduct, Product
from app.services.order_money import ZERO, q2

#: 两种折扣方式（用户口径 m01347：两种表达都要）。
KIND_PERCENT = "percent"
KIND_AMOUNT = "amount"
KINDS: tuple[str, ...] = (KIND_PERCENT, KIND_AMOUNT)

CENT = Decimal("0.01")
HUNDRED = Decimal("100")


class OrderDiscountError(ValueError):
    """这次打折不能做（原因文案直接给派单员看；端点把它转成 400）。"""


@dataclass(frozen=True)
class DiscountSpread:
    """一行：打折前是多少、打完是多少（`after` 会被写进 `order_products.line_total`）。"""

    line_id: int
    name: str
    before: Decimal
    after: Decimal

    @property
    def saved(self) -> Decimal:
        """这一行便宜了多少（正数）。"""
        return q2(self.before - self.after)


@dataclass(frozen=True)
class DiscountPlan:
    """一次折扣算完的结果（纯函数产物，还没写库）。"""

    kind: str
    value: Decimal
    amount: Decimal
    scope_total: Decimal
    spread: tuple[DiscountSpread, ...]

    @property
    def line_ids(self) -> list[int]:
        return [s.line_id for s in self.spread]


def has_discount(order: Order) -> bool:
    """这一单现在有没有折扣（七列同生共死，以 `discount_kind` 为准）。"""
    return bool(str(order.discount_kind or "").strip())


def discount_lines(order: Order) -> list[dict[str, Any]]:
    """这张单**当前这份折扣**的行快照（老数据 / 坏数据一律当空，不让它把详情页带崩）。"""
    raw = order.discount_lines
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            lid = int(item.get("line_id"))
        except (TypeError, ValueError):
            continue
        out.append({"line_id": lid, "before": item.get("before"), "after": item.get("after")})
    return out


def discount_line_ids(order: Order) -> list[int]:
    """参与这份折扣的行 id（空 = 当时整单参与）。"""
    return [item["line_id"] for item in discount_lines(order)]


def _previous_before(order: Order) -> dict[int, Decimal]:
    """这份折扣**打下去之前**每一行是多少 —— 取消 / 换折扣时按它精确还原。"""
    out: dict[int, Decimal] = {}
    for item in discount_lines(order):
        if item["before"] is None:
            continue
        out[item["line_id"]] = q2(Decimal(str(item["before"])))
    return out


def _current_amount(op: OrderProduct) -> Decimal:
    """这一行**此刻**是多少（调用前上一份折扣已经撤掉，所以它就是"打折前"）。"""
    if op.line_total is not None:
        return q2(Decimal(op.line_total))
    return q2(Decimal(op.unit_price or ZERO) * Decimal(int(op.quantity or 0)))


def _scope_lines(lines: list[OrderProduct], line_ids: list[int] | None) -> list[OrderProduct]:
    """选出参与折扣的行：`line_ids` 空 / None = 整单（用户口径：两档都要）。"""
    if not lines:
        raise OrderDiscountError("这张单一件货都没有，打不了折。")
    if not line_ids:
        return list(lines)
    by_id = {op.id: op for op in lines}
    picked: list[OrderProduct] = []
    seen: set[int] = set()
    unknown: list[int] = []
    for raw in line_ids:
        try:
            lid = int(raw)
        except (TypeError, ValueError):
            unknown.append(raw)  # type: ignore[arg-type]
            continue
        if lid in seen:
            continue
        seen.add(lid)
        op = by_id.get(lid)
        if op is None:
            unknown.append(lid)
        else:
            picked.append(op)
    if unknown:
        raise OrderDiscountError(f"这些行不属于这张订单：{unknown}。请刷新后重新勾选。")
    return picked


def _spread(total: Decimal, amount: Decimal, parts: list[tuple[int, Decimal]]) -> dict[int, Decimal]:
    """把 `amount` 按各行的金额占比摊到每一行（分位；余数给小数部分最大的那几行）。

    ⛔ 为什么必须摊：钱落在**行**上（见模块注释），"整单减 5 元"也得真的变成
    "第一行少 1.37、第二行少 1.63"。摊不出来就和 `goods_amount` 对不上账。
    """
    out: dict[int, Decimal] = {lid: ZERO for lid, _ in parts}
    if not parts or amount <= ZERO or total <= ZERO:
        return out
    cents_left = int((q2(amount) * HUNDRED).to_integral_value(rounding=ROUND_DOWN))
    remainders: list[tuple[Decimal, int, Decimal]] = []
    for lid, base in parts:
        exact = q2(amount) * base / total
        cents = int((exact * HUNDRED).to_integral_value(rounding=ROUND_DOWN))
        out[lid] = Decimal(cents) / HUNDRED
        cents_left -= cents
        remainders.append((exact - out[lid], lid, base))
    # 余数（不到一行一分）给小数部分最大的行；理论上不超过"行数 − 1"分。
    remainders.sort(key=lambda t: t[0], reverse=True)
    for _, lid, base in remainders:
        if cents_left <= 0:
            break
        if out[lid] + CENT <= base:
            out[lid] = out[lid] + CENT
            cents_left -= 1
    if cents_left > 0:
        # 兜底：真到了这里说明"向下取整之和"与 amount 的差超过了一行一分 ——
        # 宁可拒绝这次打折，也不写一个和 goods_amount 对不上的数（账要对得上）。
        raise OrderDiscountError("这次折扣摊到每一行时对不上整数分，请把折扣值改成整数分再试。")
    return out


def plan_discount(
    lines: list[OrderProduct],
    *,
    kind: str,
    value: Decimal | str | int,
    line_ids: list[int] | None = None,
    no_discount_names: dict[int, str] | None = None,
) -> DiscountPlan:
    """算出"打这个折，每一行应该变成多少"（**纯函数**，不碰数据库 —— 单测直接调它）。

    `no_discount_names`：`{商品id: 商品名}`，商品档案里勾了「不参与打折」的那些。
    """
    kind_norm = str(kind or "").strip().lower()
    if kind_norm not in KINDS:
        raise OrderDiscountError("折扣方式只有两种：按百分比减（percent）与抹零（amount）。")
    v = q2(Decimal(str(value)))
    if v <= ZERO:
        raise OrderDiscountError("折扣值要大于 0。")
    if kind_norm == KIND_PERCENT and v >= HUNDRED:
        raise OrderDiscountError("百分比折扣要小于 100%（那等于白送，请改用「抹零」抵掉整单金额）。")

    picked = _scope_lines(lines, line_ids)
    names = no_discount_names or {}
    if line_ids:
        # 派单员**显式勾了**这几行 ⇒ 不许静默过滤：
        # 「他以为打了折、其实没打」是最坏的一种成功（口径 m01347）。
        blocked = [op for op in picked if op.product_id in names]
        if blocked:
            who = "、".join(sorted({str(names[op.product_id]) for op in blocked}))
            raise OrderDiscountError(
                f"「{who}」在商品档案里勾了「不参与打折」—— 请把这几行从勾选里去掉，"
                "或先去商品档案取消那个勾。"
            )
    else:
        # 整单折扣：**自动跳过**勾了「不参与打折」的商品（用户口径 m01347：
        # 商品级勾选的语义就是"算折扣时跳过它"）—— 跳过是静默的，因为用户没有"勾"它。
        picked = [op for op in picked if op.product_id not in names]
        if not picked:
            raise OrderDiscountError("这张单的商品都勾了「不参与打折」，没有可优惠的钱。")

    pairs = [(op, _current_amount(op)) for op in picked]
    scope_total = q2(sum((amount for _, amount in pairs), ZERO))
    if scope_total <= ZERO:
        raise OrderDiscountError("勾选的这些行金额都是 0，没有可优惠的钱。")

    amount = q2(scope_total * v / HUNDRED) if kind_norm == KIND_PERCENT else q2(v)
    if amount <= ZERO:
        raise OrderDiscountError(f"这个折扣算下来一分钱都不用少（{scope_total} × {v}% 不到 1 分）—— 请把折扣值写大一点。")
    if amount > scope_total:
        raise OrderDiscountError(
            f"抹零 {amount} 比参与行的合计 {scope_total} 还多 —— 优惠最多只能把货款抹到 0。"
            "请把金额改小，或先取消折扣再改单。"
        )

    shares = _spread(scope_total, amount, [(op.id, a) for op, a in pairs])
    spread = tuple(
        DiscountSpread(
            line_id=op.id,
            name=str(op.product_name_snapshot or ""),
            before=amount_before,
            after=q2(amount_before - shares[op.id]),
        )
        for op, amount_before in pairs
    )
    return DiscountPlan(kind=kind_norm, value=v, amount=amount, scope_total=scope_total, spread=spread)


def _load_lines(db: Session, order: Order) -> list[OrderProduct]:
    return list(
        db.scalars(
            select(OrderProduct).where(OrderProduct.order_id == order.id).order_by(OrderProduct.id)
        )
    )


def _no_discount_names(db: Session, lines: list[OrderProduct]) -> dict[int, str]:
    """这一单用到的商品里，勾了「不参与打折」的那几个（只查真正用到的那几个 id）。"""
    ids = sorted({int(op.product_id) for op in lines if op.product_id})
    if not ids:
        return {}
    rows = db.scalars(
        select(Product).where(Product.id.in_(ids), Product.no_discount.is_(True))
    ).all()
    return {int(p.id): str(p.name) for p in rows}


def _dump(plan: DiscountPlan) -> list[dict[str, Any]]:
    """快照存字符串：NUMERIC 的精度（4 位）在 JSON 里不该被 float 改写。"""
    return [
        {"line_id": s.line_id, "before": str(s.before), "after": str(s.after)}
        for s in plan.spread
    ]


def _restore(order: Order, lines: list[OrderProduct]) -> list[int]:
    """把快照里那份折扣从行上撤掉（只动快照列过的行），返回被还原的行 id。"""
    prev = _previous_before(order)
    if not prev:
        return []
    restored: list[int] = []
    for op in lines:
        amount = prev.get(int(op.id))
        if amount is None:
            continue
        op.line_total = amount
        restored.append(int(op.id))
    return restored


def _write_lines(lines: list[OrderProduct], plan: DiscountPlan) -> None:
    by_id = {int(op.id): op for op in lines}
    for item in plan.spread:
        op = by_id.get(item.line_id)
        if op is not None:
            op.line_total = item.after


def apply_discount(
    db: Session,
    *,
    order: Order,
    kind: str,
    value: Decimal | str | int,
    line_ids: list[int] | None = None,
    reason: str | None = None,
    actor_id: int | None = None,
) -> DiscountPlan:
    """给这张单打一个折（**幂等替换**：先把上一份撤掉，再按新的算一遍）。"""
    lines = _load_lines(db, order)
    if not lines:
        raise OrderDiscountError("这张单一件货都没有，打不了折。")
    _restore(order, lines)
    plan = plan_discount(
        lines,
        kind=kind,
        value=value,
        line_ids=line_ids,
        no_discount_names=_no_discount_names(db, lines),
    )
    _write_lines(lines, plan)
    note = str(reason or "").strip()
    order.discount_kind = plan.kind
    order.discount_value = plan.value
    order.discount_amount = plan.amount
    order.discount_lines = _dump(plan)
    order.discount_reason = note[:255] or None
    order.discount_by_id = actor_id
    order.discount_at = utc_now_naive()
    db.flush()
    return plan


def clear_discount(db: Session, *, order: Order) -> list[int]:
    """取消折扣：每一行按快照里的 `before` **精确还原**（⛔ 不去猜"单价 × 数量"）。"""
    lines = _load_lines(db, order)
    restored = _restore(order, lines)
    order.discount_kind = None
    order.discount_value = None
    order.discount_amount = None
    order.discount_lines = None
    order.discount_reason = None
    order.discount_by_id = None
    order.discount_at = None
    db.flush()
    return restored


def reapply_after_line_change(
    db: Session, *, order: Order, edited_line: OrderProduct | None = None
) -> DiscountPlan | None:
    """改了一行的数量 / 单价之后，把这一单的折扣重算一遍（只重算参与过折扣的行）。

    ⛔ 没有折扣的单直接返回 None —— 绝大多数改单走的就是这条路，一个字节都不动。
    ⚠️ `edited_line`：刚被改过的那一行**保持它现在的值**（调用方已经用
    `order_flow.resolve_line_total` 算好了），折扣只能作用在它现在的金额上。
    """
    if not has_discount(order):
        return None
    snapshot_ids = discount_line_ids(order)
    if edited_line is not None and snapshot_ids and int(edited_line.id) not in snapshot_ids:
        # 改的不是参与折扣的行 —— 折扣一个字节都不用动。
        return None
    lines = _load_lines(db, order)
    if not lines:
        return None
    alive = {int(op.id) for op in lines}
    scope_ids: list[int] | None
    if snapshot_ids:
        scope_ids = [lid for lid in snapshot_ids if lid in alive]
        if not scope_ids:
            # 参与过折扣的行**全被删光了** ⇒ 折扣已经没有作用对象：连快照一起清掉
            # （不清的话详情页会一直显示"减了 X 元"，而行上一分钱都没少）。
            order.discount_kind = None
            order.discount_value = None
            order.discount_amount = None
            order.discount_lines = None
            order.discount_reason = None
            order.discount_by_id = None
            order.discount_at = None
            db.flush()
            return None
    else:
        # 快照坏了 / 老数据没有逐行快照 ⇒ 退回"整单"口径（line_ids=None）
        scope_ids = None
    edited_id = int(edited_line.id) if edited_line is not None else None
    prev = _previous_before(order)
    for op in lines:
        amount = prev.get(int(op.id))
        if amount is None or int(op.id) == edited_id:
            continue
        op.line_total = amount
    try:
        plan = plan_discount(
            lines,
            kind=str(order.discount_kind),
            value=order.discount_value if order.discount_value is not None else ZERO,
            line_ids=scope_ids,
            no_discount_names=_no_discount_names(db, lines),
        )
    except OrderDiscountError as exc:
        raise OrderDiscountError(
            f"这张单还挂着折扣（{order.discount_kind} / {order.discount_value}），"
            f"改完之后对不上了：{exc} 请先取消折扣再改这一单。"
        ) from exc
    _write_lines(lines, plan)
    order.discount_amount = plan.amount
    order.discount_lines = _dump(plan)
    db.flush()
    return plan
