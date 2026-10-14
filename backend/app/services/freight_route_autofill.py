"""派单时按**路线**自动带价：同一条路线上的多条价目里挑**最贴近**的那一条（CHG-0129）。

## 用户要的是什么
用户 2026-10-15 口述：「运费模板已经绑定了路线，派单时路线匹配就直接带出钱。」
换句话说：派单抽屉里那一格运费**不该还要人去手选模板** ——
这一单送到哪、这单算哪类货、派的什么车，就足以定下该带哪条价目的钱。

## 与 `freight_pricing.quote_for` 的关系（⚠️ 两条路，语义不同，都留着）
`quote_for` 回答的是「**这个司机**的规则勾了哪几条价目、这条路线 + 这类货命中哪一条」——
同一档里命中多条时它**故意不猜**（返回 `ambiguous` 让派单员自己挑），这是它的既定语义，
`backend/tests/test_freight_pricing.py::test_多条同样优先时不猜` 钉着它，**本文件一个字都不改它**。

本文件回答的是另一个问题：「**这一单的路线**上，几条价目里哪一条最贴近这一单」。
存在的理由只有一个：**同一条路线上本来就允许多条价目**（用户 2026-09-19 原话
「同一个路线，我们可以配置多个价格，比如价格一价格二价格三」），
所以「按路线自动带价」这条路上，**歧义是常态而不是异常**：
在这里也一律回 `ambiguous`，等于这个功能永远带不出钱。⇒ 按下面这套可解释的规则挑一条，
并且**把挑的是谁、凭什么叫最贴近，说给派单员听**（界面显示，不静默）。

## 「最贴近」的判定（优先级从高到低；全是纯函数，见 `score_of` / `closer_order`）
1. **在路线上**（唯二参选条件之一）：① 价目**绑的就是这条路线**（`route_id` 命中，
   即「地址与联系人 → 常用线路」里那一行）优先于 ② 只有终点文字快照对得上
   （老数据 / 那条线路已被删）。两条都不沾的价目**不参选**。
2. **分类**：勾了这一单那一类 > 没限分类（通用）> 勾的是别的类（**直接出局**，
   ⛔ 不许拿别类货的价顶上）> 这一单没有分类（这一维不参与）。
3. **车型**：只用来排序，**不用来筛** —— 对得上 > 没限车型 > 不一致 > 车型未知。
   ⚠️ 为什么只排序：车型写在价目上（`FreightTemplate.vehicle_type`），
   若拿它当筛子，「司机开着大车、价目只写了小车」就会变成**一毛钱都带不出来**；
   而按司机挂的规则那条路本来就不看车型（`freight_pricing` 里连 `vehicle_type`
   这个词都不许出现）。所以这里只在**同等路线、同等分类**的范围内用它分个先后，
   并且界面会把「车型不完全一致」如实写出来。
4. 仍然平手：**最近改过的那条**（`updated_at` 最大）> 编号最大。
   ⛔ 平手时"随便取一条"是这个项目最恨的静默错误 ⇒ `why_text()` 在平手多于一条时
   必须写「同样贴近还有 N 条，按「最近改过」取的」，让派单员看得见这里发生过一次挑选。

## 只读
本文件**一个字节都不写库**（R4-25）：它挑出一条价目、把金额与理由交回调用方；
真正把运费落到订单上仍然是派单那一个写入口（`POST /orders/{id}/assign` 的 `freight_fee`）。
⛔ 也**不碰司机的钱**：价目是**货主运费**，司机应得只有 `services/driver_pay.py` 一处算。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FreightCategory, Order
# ⚠️ 这两个下划线开头的小工具是**复用**（不是抄一份）：路线文字的拼法（`起点 → 终点`）
#    与"价目挂了哪些分类"的口径都只有 freight_pricing 里那一份，
#    各写一份的后果是同一张价目在待定价页与派单抽屉里显示成两条不同的路线。
from app.services.freight_pricing import (  # noqa: PLC2701
    _category_map,
    _route_text,
    candidate_templates,
    route_ids_of,
)

#: 路线这一维：绑定命中 > 文字命中 > 不沾边
ROUTE_BOUND = 2
ROUTE_TEXT = 1
ROUTE_NONE = 0

#: 分类这一维：本类 > 通用（没限分类）> 别的类（出局）> 这一单没分类（不参与）
CAT_HIT = 0
CAT_ANY = 1
CAT_OTHER = 2
CAT_UNKNOWN = 3

#: 车型这一维（**只排序不筛**）：对得上 > 没限车型 > 不一致 > 车型未知
VEH_HIT = 0
VEH_ANY = 1
VEH_OTHER = 2
VEH_UNKNOWN = 3

#: 车型的中文说法 —— ⛔ 只是给人看的文案，不参与任何计算。
#: `api/v1/driver_billing_rules.py` 里那份同词的（`_VEHICLE_CN`）**不能借**：
#: 服务层不许 import app.api（`_tools/qa/_check_money_dependency.py` 第 1 条）。
VEHICLE_CN = {"small": "小型车", "large": "大车", "trailer": "挂车"}


@dataclass(frozen=True)
class TplFact:
    """一条价目里**参与挑选**的那几列（读出来就不会再动库；纯函数只认这个）。"""

    template_id: int
    name: str
    fee: str
    price_name: str = ""
    route: str = ""
    route_id: int | None = None
    to_place: str = ""
    category_ids: tuple[int, ...] = ()
    category_names: tuple[str, ...] = ()
    vehicle_type: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Wish:
    """这一单「想要什么」：送到哪（终点文字 + 命中的线路编号）、哪类货、什么车。"""

    address_detail: str = ""
    route_ids: tuple[int, ...] = ()
    category_id: int | None = None
    category_name: str = ""
    vehicle_type: str = ""


@dataclass(frozen=True)
class Scored:
    """一条价目 + 它在三个维度上的位置（`route_hit` 为 0 的**不参选**）。"""

    fact: TplFact
    route_hit: int
    category_hit: int
    vehicle_hit: int


@dataclass(frozen=True)
class Best:
    """挑选结果。

    - `pick`：挑中的那一条（`None` = 没得带，看 `reason` 那句话）；
    - `ranked`：参与挑选的候选，**已经按「最贴近」排好**（界面要列候选就直接用这个顺序）；
    - `ties`：与 `pick` 在（路线/分类/车型）三维上完全同分的条数（>1 说明发生过一次
      "最近改过优先"，界面必须说出来）；
    - `reason`：没挑到时给用户看的中文（⛔ 不许编一个价顶上）；
    - `category_id` / `category_name`：这一单**按哪一类货**挑的（回给界面，界面对账用）。
    """

    pick: Scored | None = None
    ranked: tuple[Scored, ...] = ()
    ties: int = 0
    reason: str = ""
    category_id: int | None = None
    category_name: str = ""

    @property
    def ok(self) -> bool:
        return self.pick is not None


def route_hit_of(fact: TplFact, wish: Wish) -> int:
    """这条价目在**路线**这一维上有多贴近（0 = 不沾边，**不参选**）。"""
    if fact.route_id is not None and fact.route_id in wish.route_ids:
        return ROUTE_BOUND
    if wish.address_detail and (fact.to_place or "") == wish.address_detail:
        return ROUTE_TEXT
    return ROUTE_NONE


def category_hit_of(fact: TplFact, wish: Wish) -> int:
    """分类这一维：别的类直接出局（`CAT_OTHER`），没限分类＝通用兜底。"""
    if wish.category_id is None:
        return CAT_UNKNOWN
    if not fact.category_ids:
        return CAT_ANY
    if int(wish.category_id) in fact.category_ids:
        return CAT_HIT
    return CAT_OTHER


def vehicle_hit_of(fact: TplFact, wish: Wish) -> int:
    """车型这一维：**只排序，不筛**（见模块 docstring 第 3 条）。"""
    want = (wish.vehicle_type or "").strip()
    if not want:
        return VEH_UNKNOWN
    have = (fact.vehicle_type or "").strip()
    if not have:
        return VEH_ANY
    if have == want:
        return VEH_HIT
    return VEH_OTHER


def score_of(fact: TplFact, wish: Wish) -> Scored:
    return Scored(
        fact=fact,
        route_hit=route_hit_of(fact, wish),
        category_hit=category_hit_of(fact, wish),
        vehicle_hit=vehicle_hit_of(fact, wish),
    )


def key_of(s: Scored) -> tuple[int, int, int]:
    """「最贴近」的排序键（越小越贴近）。⛔ 路线/分类/车型三维，一个都不许少。"""
    return (-s.route_hit, s.category_hit, s.vehicle_hit)


def closer_order(items: list[Scored]) -> list[Scored]:
    """按「最贴近」排好：三维主键 → 最近改过 → 编号大。

    ⚠️ 两步 `sorted`，**后一步稳定排序**：先按"最不重要的两项"（最近改过 + 编号）排，
    再按三维主键排 —— 于是三维全平时，保留的正是"最近改过优先"那个顺序。
    写成一步要在同一个 key 里混升降序（容易读错方向），所以这里分开写。
    """
    ranked = sorted(items, key=lambda s: (s.fact.updated_at, s.fact.template_id), reverse=True)
    ranked.sort(key=key_of)
    return ranked


def pick_closest(facts: list[TplFact], wish: Wish) -> Best:
    """纯函数：给一堆价目与这一单的愿望，挑出**最贴近**的那一条。"""
    def out(**kw) -> Best:
        return Best(category_id=wish.category_id, category_name=wish.category_name, **kw)

    addr = (wish.address_detail or "").strip()
    if not addr and not wish.route_ids:
        return out(reason="这一单没有送货地址，认不出路线 —— 先在订单里补地址")

    on_route = [score_of(f, wish) for f in facts if route_hit_of(f, wish) != ROUTE_NONE]
    if not on_route:
        return out(
            reason="这条路线还没有价目 —— 到「运费模板」里给这条线路加一条价"
            "（或在这里定价后自动存下来）"
        )

    usable = [s for s in on_route if s.category_hit != CAT_OTHER]
    if not usable:
        who = wish.category_name or "这一类"
        return out(
            ranked=tuple(closer_order(on_route)),
            reason=f"这条路线上的价目都不是「{who}」的 —— 要么给它加一条这类货的价，"
            "要么在这里手动定价",
        )

    ranked = closer_order(usable)
    top = ranked[0]
    ties = len([s for s in ranked if key_of(s) == key_of(top)])
    return out(pick=top, ranked=tuple(ranked), ties=ties)


def why_text(best: Best) -> str:
    """「为什么带出的是这个价」—— 一句话，界面**原样显示**（⛔ 界面不许自己编）。"""
    s = best.pick
    if s is None:
        return best.reason
    bits: list[str] = []
    if s.route_hit == ROUTE_BOUND:
        bits.append("价目绑的就是这条路线")
    else:
        bits.append("路线按终点文字对上（这条价目还没绑路线）")
    if s.category_hit == CAT_HIT:
        bits.append("分类对得上")
    elif s.category_hit == CAT_ANY:
        bits.append("这条价目没限分类")
    elif s.category_hit == CAT_UNKNOWN:
        bits.append("这一单没填分类")
    if s.vehicle_hit == VEH_HIT:
        bits.append("车型对得上（" + VEHICLE_CN.get(s.fact.vehicle_type, s.fact.vehicle_type) + "）")
    elif s.vehicle_hit == VEH_ANY:
        bits.append("这条价目没限车型")
    elif s.vehicle_hit == VEH_OTHER:
        bits.append("车型不完全一致（只按路线取）")
    else:
        bits.append("按路线取（车型未知）")
    head = f"这条路线上一共 {len(best.ranked)} 条价目，取的是「{s.fact.name}」"
    if s.fact.price_name:
        head += f"（{s.fact.price_name}）"
    tail = ""
    if best.ties > 1:
        tail = f"；同样贴近还有 {best.ties - 1} 条，按「最近改过」取的"
    return head + "：" + "、".join(bits) + tail


# ------------------------------------------------------------------ 读库（只读）

def _category_names(db: Session, cats: dict[int, list[int]]) -> dict[int, str]:
    """分类编号 → 名字（一次查完，别在循环里查）。"""
    ids = {int(c) for v in cats.values() for c in v}
    if not ids:
        return {}
    rows = db.execute(select(FreightCategory).where(FreightCategory.id.in_(ids))).scalars()
    return {int(c.id): (c.name or "") for c in rows}


def facts_of(db: Session, address_detail: str = "") -> list[TplFact]:
    """这一单可能用得上的价目（**全部未删的**；哪条在路线上由纯函数判）。

    ⚠️ 这里刻意**不按司机/规则过滤**：本文件服务的是"按路线自动带价"，
    与 `quote_for` 的"按司机的规则带价"是两条路（见模块 docstring）。
    `address_detail` 只用于日志/调试语义，筛选交给纯函数。
    """
    templates = candidate_templates(db, None)
    cats = _category_map(db, templates)
    names = _category_names(db, cats)
    out: list[TplFact] = []
    for t in templates:
        cids = tuple(int(c) for c in (cats.get(t.id) or []))
        stamp = t.updated_at or t.created_at
        out.append(
            TplFact(
                template_id=int(t.id),
                name=t.name or "",
                fee=str(t.fee if t.fee is not None else Decimal("0.00")),
                price_name=t.price_name or "",
                route=_route_text(t),
                route_id=int(t.route_id) if t.route_id is not None else None,
                to_place=(t.to_place or "").strip(),
                category_ids=cids,
                category_names=tuple(names[c] for c in cids if names.get(c)),
                vehicle_type=(t.vehicle_type or ""),
                updated_at=stamp.isoformat() if stamp else "",
            )
        )
    return out


def wish_of(
    db: Session,
    order: Order,
    *,
    category_id: int | None = None,
    vehicle_type: str = "",
) -> Wish:
    """这一单「想要什么」（路线编号来自「地址与联系人」里终点同名的那几行）。"""
    addr = (getattr(order, "address_detail", "") or "").strip()
    cat_id = category_id if category_id is not None else getattr(order, "freight_category_id", None)
    cat_name = ""
    if cat_id is not None:
        cat = db.get(FreightCategory, int(cat_id))
        cat_name = (cat.name or "") if cat is not None else ""
    return Wish(
        address_detail=addr,
        route_ids=tuple(sorted(route_ids_of(db, addr))),
        category_id=int(cat_id) if cat_id is not None else None,
        category_name=cat_name,
        vehicle_type=(vehicle_type or "").strip(),
    )


def autofill_for(
    db: Session,
    order: Order,
    *,
    category_id: int | None = None,
    vehicle_type: str = "",
) -> Best:
    """派单那一刻：按这一单的路线挑一条**最贴近**的价目（**只读**，不写任何东西）。"""
    wish = wish_of(db, order, category_id=category_id, vehicle_type=vehicle_type)
    return pick_closest(facts_of(db, wish.address_detail), wish)
