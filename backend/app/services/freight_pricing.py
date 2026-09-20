"""**运价匹配的唯一实现**：这一单该收多少运费（路线 + 分类 + 司机 → 一条价目）。

## 用户 2026-09-21 的原话（这一轮的全部依据）

> 「运费管理它会是有一个**拉取地点库里的路线**，按照地点库的路线进行定价，然后我们可以放到
>  分类当中……然后再计费规则的时候配置按单计费有两种规则：所有单统一价/统一提成，或者按分类匹配。
>  **如果没有匹配到的话，它就会显示没有计费、就会变成没有定价** —— 这个订单就得我们那个派单员
>  **手动去给他定价**。这个定价完之后，同理，他会**新增对应的地点/路线线路和对应的运费模板**，
>  并且放到那个分类当中去，就是**绑定那个分类**。」

## 为什么必须是一处实现

匹配规则散开（派单弹窗算一遍、待定价页算一遍、AI 再算一遍）的后果**不是崩**：
同一单在两个界面上带出两个价，而**两边都不报错**；改一处漏一处时更糟 ——
用户会以为"系统抽风"。所以：算法在这里，界面只显示 [Quote] 里的结论与理由。

## 匹配口径（2026-09-21 定稿：「价目归计费规则」）

用户原话：「运费模板不会去匹配车型也不会匹配司机，匹配车型和匹配司机在**计费规则**中……
这一目录就归这个计费规则，而这个规则在匹配对应的司机」。

所以链子是：**价目（路线 + 分类 + 价格）** →（规则勾选）→ **规则（车型 + 多少钱）** →（挂在司机身上）→ **司机**。
于是匹配分两步：

1. **先按司机过滤**：候选价目 = 这个司机的规则**勾了**的那些（没挂规则 / 一条都没勾 → 没有候选）；
2. 再按**路线**（这单送到哪）与**分类**（这单算哪类货）在候选里挑，优先级与"不猜"的规矩见下。

⛔ 价目**不看车型、不看司机绑定**（那两个字段在价目上已经不用了）：一辆车/一个司机用哪条价目，
是"他的规则勾没勾"决定的。

## 优先级（从高到低，**同一档里多于一条 = 不猜**）

1. 路线相符（价目的 `to_place` 或它挂的那条线路的终点 = 这一单的送货地址）；
2. 分类相符（价目挂了这一单的分类）→ 否则"没挂任何分类的价目"当**通用**兜底；
3. 司机相符（价目绑了这一单的司机）→ 否则"没绑司机的价目"当**通用**兜底。

⛔ **同一档里匹配到多条 → 不猜**：返回 `ambiguous` 与候选清单，让派单员自己挑
（"默默取到另一条"正是本项目最恨的那种静默错误）。这也是为什么价目卡上必须写明
分类与司机 —— 配置歧义要在配置时就看得出来。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    FreightCategory,
    FreightTemplate,
    FreightTemplateCategory,
    ShipperAddress,
)
from app.models.order import Order

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Candidate:
    """一条候选价目（给界面显示"为什么是它"）。"""

    template_id: int
    name: str
    fee: Decimal
    price_name: str = ""
    route: str = ""
    category_names: tuple[str, ...] = ()
    driver_names: tuple[str, ...] = ()


@dataclass
class Quote:
    """这一单的运价结论。`matched` 为 None 时 [reason] 说明**为什么没匹配到**。"""

    matched: Candidate | None = None
    category_id: int | None = None
    category_name: str = ""
    #: 没匹配到时的原因（给用户看的中文；界面直接显示，不要自己编话）
    reason: str = ""
    #: 有多条同样优先级的候选（**不猜**，让派单员挑一条）
    ambiguous: list[Candidate] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.matched is not None


def _route_text(t: FreightTemplate) -> str:
    f, o = (t.from_place or "").strip(), (t.to_place or "").strip()
    return (f + " → " + o) if f else o


def _category_map(db: Session, templates: list[FreightTemplate]) -> dict[int, list[int]]:
    if not templates:
        return {}
    ids = [t.id for t in templates]
    rows = db.execute(
        select(FreightTemplateCategory.template_id, FreightTemplateCategory.category_id).where(
            FreightTemplateCategory.template_id.in_(ids)
        )
    ).all()
    out: dict[int, list[int]] = {}
    for tid, cid in rows:
        out.setdefault(tid, []).append(cid)
    return out


def _to_candidate(
    t: FreightTemplate,
    cat_ids: list[int],
    cat_names: dict[int, str],
) -> Candidate:
    return Candidate(
        template_id=t.id,
        name=t.name,
        fee=t.fee or ZERO,
        price_name=t.price_name or "",
        route=_route_text(t),
        category_names=tuple(cat_names.get(c, f"#{c}") for c in cat_ids),
    )


def quote_for(
    db: Session,
    order: Order,
    *,
    driver_id: int | None = None,
    category_id: int | None = None,
) -> Quote:
    """这一单 + 这个司机（+ 可选分类）→ 运价结论。

    [category_id] 为 None 时用订单上已经定的分类（`order.freight_category_id`）。
    """
    addr = (order.address_detail or "").strip()
    if not addr:
        return Quote(reason="这一单没有送货地址，认不出路线 —— 先在订单里补地址")

    cat_id = category_id if category_id is not None else getattr(order, "freight_category_id", None)

    # ---- ⓪ 先按**这个司机的计费规则**取候选（价目归规则，不归司机/车型）----
    picked_template_ids: set[int] | None = None
    if driver_id is not None:
        from app.models import DriverBillingRule, DriverBillingRuleTemplate, User

        driver = db.get(User, int(driver_id))
        rule_id = getattr(driver, "driver_rule_id", None) if driver is not None else None
        if rule_id is None:
            return Quote(
                reason="这个司机还没挂计费规则 —— 运费是从「他的规则勾了哪几条价目」来的，"
                       "先去工作台「计费规则」给他挂一份、并在里面勾上价目"
            )
        rule = db.get(DriverBillingRule, int(rule_id))
        if rule is None or rule.is_deleted:
            return Quote(reason="这个司机挂的计费规则不在了（或被删了）—— 去「计费规则」里重挂一份")
        picked_template_ids = {
            int(x)
            for x in db.scalars(
                select(DriverBillingRuleTemplate.template_id).where(
                    DriverBillingRuleTemplate.rule_id == int(rule_id)
                )
            ).all()
        }
        if not picked_template_ids:
            return Quote(
                reason=f"「{rule.name}」这份规则还没勾价目 —— 打开它，在「用哪些运费价目」里勾上"
                       "（可以整类全选），这一单才会有运费"
            )

    # ---- ① 路线：价目的终点快照 = 这一单的送货地址；或它挂的那条线路的终点 = 送货地址 ----
    route_ids = set(
        db.scalars(select(ShipperAddress.id).where(ShipperAddress.detail_address == addr)).all()
    )
    stmt = select(FreightTemplate).where(FreightTemplate.is_deleted.is_(False))
    if picked_template_ids is not None:
        stmt = stmt.where(FreightTemplate.id.in_(picked_template_ids))
    templates = list(db.scalars(stmt).all())
    by_route: list[FreightTemplate] = []
    for t in templates:
        if (t.to_place or "").strip() == addr:
            by_route.append(t)
        elif t.route_id is not None and t.route_id in route_ids:
            by_route.append(t)
    if not by_route:
        return Quote(reason="这条路线还没有价目 —— 到「运费模板」里给这条线路加一条价（或在这里定价后自动存下来）")

    cats = _category_map(db, by_route)
    all_cat_ids = {c for v in cats.values() for c in v}
    cat_names = {
        c.id: c.name
        for c in db.scalars(select(FreightCategory).where(FreightCategory.id.in_(all_cat_ids or {0}))).all()
    }

    def rank(t: FreightTemplate) -> tuple[int]:
        """(分类优先) —— 数字小的优先。

        ⛔ 价目**不看车型、也不看司机**：那两个维度在"规则勾价目"那一步就定完了 ——
        候选集本身就是"这个司机的规则勾了的那几条"，所以这里只剩分类这一维。
        ⛔ 也不许把 id 混进排序键当"平手时的排序"：混进来之后"同样优先"永远不成立，
        下面那段"多条候选 → 不猜"的分支就成了**死代码**（测试
        `test_多条同样优先时不猜` 就是这么抓到它的：配了两条同类价目，
        系统照样挑了一条、而且挑得毫无理由）。平手只用来排序，判"是不是平手"必须用这个元组。
        """
        t_cats = cats.get(t.id, [])
        # ⚠️ "不知道这一单是哪一类"时这一维**不参与筛选**（给中性的 1）——
        #    否则待定价那一页（还没定分类）会把带分类的价目全判成不可用，
        #    于是明明有价也报"没有价目"（测试抓到过）。
        cat_hit = 1 if cat_id is None else (0 if int(cat_id) in t_cats else (1 if not t_cats else 2))
        return (cat_hit,)

    ranked = sorted(by_route, key=lambda t: (*rank(t), -t.id))
    usable = [t for t in ranked if rank(t)[0] != 2]
    if not usable:
        if cat_id is not None:
            name = cat_names.get(int(cat_id), getattr(order, "freight_category", "") or "")
            return Quote(
                category_id=int(cat_id),
                category_name=name,
                reason=f"这条路线上的价目都不是「{name or '这一类'}」的 —— 要么给它加一条这类货的价，要么在这里手动定价",
            )
        return Quote(reason="这条路线上的价目都不是这一类的 —— 在这里手动定价，或去「运费模板」补一条、再勾进这份规则")

    best_rank = rank(usable[0])
    same = [t for t in usable if rank(t) == best_rank]
    if len(same) > 1:
        return Quote(
            category_id=int(cat_id) if cat_id is not None else None,
            ambiguous=[_to_candidate(t, cats.get(t.id, []), cat_names) for t in same],
            reason="这条路线 + 这类货下有多条同样优先的价目 —— 请自己挑一条，系统不替你猜",
        )

    t = same[0]
    chosen_cat = int(cat_id) if cat_id is not None else (cats.get(t.id) or [None])[0]
    return Quote(
        matched=_to_candidate(t, cats.get(t.id, []), cat_names),
        category_id=chosen_cat,
        category_name=cat_names.get(int(chosen_cat), "") if chosen_cat is not None else "",
    )
