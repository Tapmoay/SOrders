# -*- coding: utf-8 -*-
"""承运运费的**唯一组装点**（Composition Root）—— 指南 §8（R4-20）。

## 指南 §8 的原话

> 「Shadow 连续稳定后，再让少量真实业务进入：Order → Pricing Extension → Money Core。
>  但这里有一个原则：**必须在核心的唯一组装点切换**。
>  不要在 orders.py / driver_pay.py / accounting_service.py 分别加 if extension_enabled，
>  否则你刚刚建立的 R4 又开始腐烂。」
>
>     Core → Pricing Contract → Selected Implementation
>              ├─ LegacyPricing
>              └─ ExtensionPricing

所以：**业务代码里一个 `if 开关` 都不许有**。要换算法只改这一页。

## 两条路（它们**都**经过这里）

| kind | 算什么 | 今天谁在用 |
| --- | --- | --- |
| `legacy_client` | 金额由派单界面带过来（界面上的数来自 `GET /freight-templates/quote`），核心只记事实 | 生产今天跑的 |
| `freight_template` | 核心读事实（`freight_snapshot_of`）→ `PricingContext` → **契约** → 扩展算 → Money | R4-20 起的 Canary |

## ⛔ 三条不许（每一条都对应一个会出事的方向）

1. **不许在业务里加开关**：三条写入点、账单、结算页一个 `if canary` 都不许有 —— 它们只调这里。
2. **不许让契约算不出来就失败**：算不出来就**退回旧路并如实记下来**，
   来源凭据是记录、不是前置条件（同 `_derived_quote_rule` 那条理由）。
3. **不许偷偷改金额**：Canary 里契约算出来的数与派单员给的不一样时，
   ⛔ **以人为准**，但**两个数都写进来源凭据** —— 换"算钱的源"是 ⑧ Full Cutover 的事，
   不是这一格的事（用户 §14：风险 A「记录事实失败」与风险 B「金额变化」不许一起发）。
4. **不许让比例变化改掉**已经形成的**计价决策**（用户 2026-09-27 的 ⑧-a 出口条件 ③
   CANARY_DECISION_FREEZE）：同一张单会被问很多次（派单 / 改价 / 补录），
   而 Canary 比例在观察期间**一定会被调**。已经定过来源的单，后续写入必须沿用那一个来源，
   ⛔ 不许拿当前比例重新抽签 —— 否则「历史单的金额凭什么」会随配置一起变。
   ⚠️ ⑧-b Full Cutover 的回滚规则（新决策走 Legacy / 已有决策保持原来源）**也靠这条**。

## 指南 §9：同一订单不能在运行过程中换算法

这一页的 `policy_for` 是**纯函数**（按订单编号分桶），所以：
· 同一次派单里重复问 → 同一个答案；
· 而且真正防住"换算法"的是**金额只算一次、写完就是核心事实**（`order_money.record_freight_decision`）——
  策略以后再变，也不会去改写任何已经落库的金额。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

#: 今天那条路：金额由派单界面带过来。
KIND_LEGACY = "legacy_client"
#: 走契约那条路：装进上下文的是**核心读出来的事实**，算钱的是扩展。
KIND_CONTRACT = "freight_template"

#: 分桶用的模数（⛔ 固定 100，改它等于把"同一单永远同一策略"这条重新洗牌）。
BUCKETS = 100


def canary_percent() -> int:
    """走契约的订单比例（0..100）。⛔ 缺省 0 = **关**。"""
    from app.config import get_settings

    try:
        n = int(getattr(get_settings(), "freight_pricing_canary_percent", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, n))


def policy_for(order_id: int | None, percent: int | None = None, *,
               frozen: str | None = None) -> str:
    """这张单走哪条路 —— ⛔ **纯函数**，只由订单编号、比例、以及**它已经定过的来源**决定。

    ⛔ 为什么不用"随机"也不用"这次请求带什么"：那样同一张单会在两次调用之间换算法，
    而派单、改价、补录会**分别**问一次 —— 三次答案不同时，界面上和库里的数就对不上了。

    ## ⭐ 冻结优先于比例（⑧-a 出口条件 ③ CANARY_DECISION_FREEZE）

    `frozen` = 这张单**已经形成过**的那一次计价决策的来源
    （由 `services.order_money.freight_kind_of` 读出来）。它有**最高优先级**：

        比例 0   → 形成 legacy_client   → 比例调到 100 → 这张单**仍然是** legacy_client
        比例 100 → 形成 freight_template → 比例调回 0  → 这张单**仍然是** freight_template

    ⚠️ 为什么必须这样（而不是"每次都按当前比例来"）：比例在观察期里会被调很多次，
    而**同一张单会被问很多次**。不冻结的话，调一次比例，这一单的「钱凭什么」就换一次 ——
    而这条不变量一旦破了，⑧-b 的回滚就再也说不清
    （"昨天 Extension 127.50、今天 Legacy 120.00"那个场景）。
    """
    if frozen in (KIND_LEGACY, KIND_CONTRACT):
        # ⛔ 先看冻结：⛔ 不许把它挪到下面（那样比例 0 / 100 会越过冻结改掉来源）。
        return frozen
    pct = canary_percent() if percent is None else max(0, min(100, int(percent)))
    if pct <= 0:
        return KIND_LEGACY
    if pct >= 100:
        return KIND_CONTRACT
    if order_id is None:
        return KIND_LEGACY
    return KIND_CONTRACT if (int(order_id) % BUCKETS) < pct else KIND_LEGACY


#: 契约这一支**为什么没算出来** —— 机器可读的原因码，写进快照的 `pricing.reason`。
#:
#: ⭐ 为什么必须分开（R4-21 生产观察实测逼出来的）：
#: 第一版只有一句笼统的"契约没算出结论（缺料或多条价目）"。在生产上拿到那句话之后，
#: **我必须去查库才知道到底是哪一种** —— 而这两件事的修法完全不同：
#: "这个司机没配规则"是**配置问题**，"同一档多条价目"是**配置歧义**。
#: 凭据的用途就是"不用查库也能说清为什么"，所以原因必须分开、而且要机器可读
#: （运维可以直接 `GROUP BY` 出"生产上最常卡在哪一步"）。
REASON_OK = "ok"                          # 走通了（这一支不算"没算出来"）
REASON_NO_CANDIDATES = "no_candidates"   # 这个司机没挂规则 / 规则一条价目都没勾
REASON_NO_MATCH = "no_match"             # 有候选，但这条路线 / 这一类里没有可用的价目
REASON_AMBIGUOUS = "ambiguous"           # 同一档多条 —— **不猜**
REASON_NO_RESOLVER = "no_resolver"       # 装配根没接解析器（例如脚本里只 import 了这个模块）
REASON_ERROR = "error"                   # 契约自己抛了别的错

#: 原因码 → 给人看的一句话（界面/审计直接显示，⛔ 不要自己另编）。
REASON_TEXT: dict[str, str] = {
    REASON_OK: "金额由契约（算价扩展）算出来的",
    REASON_NO_CANDIDATES: "这个司机没有可用价目：他还没挂计费规则，或者规则里一条价目都没勾",
    REASON_NO_MATCH: "这条路线 + 这一类货上没有可用的价目（价目表里没有，或分类对不上）",
    REASON_AMBIGUOUS: "同一档里有多条同样优先的价目 —— 不猜，请自己挑一条",
    REASON_NO_RESOLVER: "算价扩展没有装配（装配根没接解析器）",
    REASON_ERROR: "算价扩展在算这一单时抛了错（详见服务端日志）",
}


@dataclass(frozen=True)
class ContractQuote:
    """走契约算一次的结果 —— 算不出来时**必须带原因码**（见 REASON_* 那段说明）。"""

    ok: bool
    fee: str | None = None
    rule: dict | None = None
    reason: str = ""
    detail: str = ""

    @property
    def text(self) -> str:
        return REASON_TEXT.get(self.reason, self.reason)


# ---------------------------------------------------------------------------
# ⭐ **这一次决策是怎么来的**（R4-36）—— 用户 2026-09-27 点名的那个语义坑：
#
# > 「当前字段 pricing.kind 同时承担了两个不同概念：
# >   ① 订单最终采用了谁作为价格来源；② Contract 有没有成功算出价格。」
#
# 于是 kind=legacy_client + reason=ok 同时盖住了三种完全不同的情形，排障时**分不出来**
# （这正是生产上 T0/T1/T2 无法辨识的根源）。
#
# ⇒ 拆成两个正交的概念：
#   · kind（= 来源）：**金额最终由谁产生** —— legacy_client / freight_template；
#   · resolution（= 这一次怎么走到那一步的）：下面四个取值。
#
# ⛔ resolution **不是** reason 的替代：reason 说的是「契约为什么没算出来」
#    （no_candidates / no_match / ambiguous / …），resolution 说的是「这一次走的是哪条路」。
#    两个一起看，才既知道走没走、又知道为什么没走通。
# ---------------------------------------------------------------------------
#: 走了契约，而且**算出来了** —— 金额来自扩展。
RESOLUTION_CONTRACT = "contract"
#: 走了契约，但**没算出来**，如实退回旧路（金额仍以派单员为准）。
RESOLUTION_FALLBACK = "fallback"
#: 这一次**没被抽中**（比例关着、或这一单不在桶里）—— 压根没去问契约。
RESOLUTION_NOT_IN_CANARY = "not_in_canary"
#: 这一次**没有重新抽签**：这张单已经定过来源，沿用它（⑧-a 出口条件 ③ 的冻结）。
RESOLUTION_FROZEN = "frozen"

#: 四个取值的全集（⛔ 加取值必须来这里报到 —— 判据会按它核对）。
RESOLUTIONS: tuple[str, ...] = (
    RESOLUTION_CONTRACT, RESOLUTION_FALLBACK, RESOLUTION_NOT_IN_CANARY, RESOLUTION_FROZEN,
)


@dataclass(frozen=True)
class FreightDecision:
    """这一次承运运费**是怎么定的** —— 三个问题一次说清。

    · 走哪条路（`kind`）；
    · 契约算出来是多少（`quoted_fee`，没走契约就是 None）；
    · 它和派单员给的那个数一样吗（`agreed` / `override`）。

    ⚠️ `override=True` **不是错误**：派单员本来就允许改价（那是既有功能）。
    它只是"这一次的金额来自人，不是来自价目表"这件事**被记下来了**。
    """

    kind: str
    rule: dict | None = None
    quoted_fee: str | None = None
    agreed: bool | None = None
    override: bool = False
    #: 机器可读的"为什么"（REASON_*）—— 走通和没走通都有值，⛔ 不许是空串。
    reason: str = ""
    #: ⭐ 这一次决策**走的是哪条路**（RESOLUTION_*）—— 与 kind（来源）正交，见上面那段说明。
    #: ⛔ 缺省空串只留给"老调用方"；组装点自己的每一条 return 都必须给值（判据盯着）。
    resolution: str = ""
    note: str = ""


def _decimals(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# **依赖倒置**：核心不认识具体扩展，只认一个"谁来把上下文算成 Money"的槽位。
#
# ⛔ 为什么不能直接 `from app.extensions.pricing import resolve_v2`（第一版就是这么写的，
#    当场被 `_check_core_extension_boundary.py` 判红：「核心反向依赖了具体扩展」）：
#    那样一来"核心 → 具体扩展"这条边就长出来了，而 R4 的防火墙只有一条边：**核心 → 契约**。
#    换一个算价扩展（甚至一个都不装）不该让核心改代码。
#
# ⭐ 谁来填这个槽位：**装配根**（`app/main.py`）—— 与它挂扩展路由、发现扩展清单是同一件事。
#    ⛔ 槽位空着时 `contract_quote` 返回 None ⇒ 组装点**如实退回旧路**（不是崩、
#    也不是假装算过）。
# ---------------------------------------------------------------------------
_RESOLVER = None
#: 装配根登记时给的一个**可读身份**（短名字，⛔ 非敏感）—— 用途只有一个：
#: ⑧-a 出口条件 ②「两个实例的 effective config 一致」要能**对账**，
#: 而不是靠"我记得两个都改了"。
_RESOLVER_ID = ""


def register_pricing_resolver(fn, *, identity: str = "") -> None:
    """**只许装配根调**：把"上下文 → PricingContractV2"这一跳接进来。

    `identity` = 这次装的是谁（一个短名字，写进 /health 的指纹里给运维对账）。
    ⛔ 传 None 表示**没有装配**：`pricing_fingerprint()` 会如实说「未装配」，
    ⛔ 不是留着上一次的名字骗人。
    """
    global _RESOLVER, _RESOLVER_ID
    _RESOLVER = fn
    _RESOLVER_ID = (identity or "") if fn is not None else ""


def pricing_resolver():
    """当前的解析器；没人注册时返回 None（⇒ 契约那一路整体降级为旧路）。"""
    return _RESOLVER


def pricing_fingerprint() -> dict:
    """这一次进程**实际生效**的算价配置 —— ⑧-a 出口条件 ②（两个实例一致）靠它。

    ⭐ 「写进环境变量了」与「生产实际上就是这么跑的」是**两个不同的问题**：
    前者看 .env，后者只能问**每一个正在跑的进程**。滚动发布期间
    「A=30、B=0」那种状态在 .env 上**完全看不出来** —— 只有逐个实例问才看得见。

    ⛔ 只放**非敏感**的两样：一个 0..100 的整数、一个我们自己起的短名字。
    ⛔ 这个函数会被 /health 直接吐出去，所以它**永远**不许长出口令 / 连接串 / 密钥。
    """
    if _RESOLVER is None:
        return {"canary_percent": canary_percent(), "resolver": "(未装配)"}
    return {"canary_percent": canary_percent(),
            "resolver": _RESOLVER_ID or "(已装配，未命名)"}


def _no_candidates_reason(db, driver_id: int | None) -> str:
    """候选集为什么是空的 —— **同一处实现**（`driver_template_ids`）给出的中文原因。"""
    if driver_id is None:
        return "这一单还没有司机 —— 运费是按「他的规则勾了哪几条价目」来的，先指派司机"
    from app.services.freight_pricing import driver_template_ids

    _ids, why = driver_template_ids(db, int(driver_id))
    return why or "这个司机的规则勾了价目，但候选集仍然是空的"


def contract_quote(db, order, *, driver_id: int | None) -> ContractQuote:
    """走契约算一遍 → (金额文本, 价目身份)；算不出来返回 None。

    ⛔ 全程只读；⛔ 不许抛（调用方在钱路上，见模块头第 2 条）。
    """
    from app.core.contracts.pricing import AmbiguousPricingRule, NoPricingRule, PricingContext
    from app.services.freight_pricing import freight_snapshot_of, quote_for
    from app.services.order_money import rule_ref_of_candidate

    resolver = _RESOLVER
    if resolver is None:
        # 装配根没接（例如脚本/测试里只 import 了这个模块）—— 如实退回旧路，⛔ 不猜。
        return ContractQuote(ok=False, reason=REASON_NO_RESOLVER)

    try:
        snapshot = freight_snapshot_of(db, order, driver_id=driver_id)
    except Exception as exc:  # noqa: BLE001
        return ContractQuote(ok=False, reason=REASON_ERROR,
                             detail=type(exc).__name__ + ": " + str(exc)[:120])

    if not snapshot.get("templates"):
        # ⭐ 生产上最常见的就是这一支（**价目表压根没配**）—— 它必须自己说清楚，
        #    不能和"同一档多条"混成同一句话：那两种的修法完全不同（一个去配置、一个去挑一条）。
        return ContractQuote(ok=False, reason=REASON_NO_CANDIDATES,
                             detail=_no_candidates_reason(db, driver_id))

    snapshot["pricing_kind"] = KIND_CONTRACT
    ctx = PricingContext(
        order_id=getattr(order, "id", None), order_no=order.order_no or "",
        category=order.freight_category or "",
        to_place=(order.address_detail or "").strip(),
        driver_id=driver_id, rule_snapshot=snapshot,
    )
    try:
        result = resolver(ctx).price(ctx)
    except AmbiguousPricingRule as exc:
        return ContractQuote(ok=False, reason=REASON_AMBIGUOUS, detail=str(exc)[:200])
    except NoPricingRule as exc:
        return ContractQuote(ok=False, reason=REASON_NO_MATCH, detail=str(exc)[:200])
    except Exception as exc:  # noqa: BLE001 —— 见模块头第 2 条：算不出来就退回旧路
        return ContractQuote(ok=False, reason=REASON_ERROR,
                             detail=type(exc).__name__ + ": " + str(exc)[:120])

    # 价目身份仍然从**核心的匹配**拿（契约给的是 Money；"哪一条价目"是核心的事实）
    ref: dict | None = None
    try:
        quote = quote_for(db, order, driver_id=driver_id)
        ref = rule_ref_of_candidate(quote.matched, origin="derived") if quote.matched else None
    except Exception:  # noqa: BLE001
        ref = None
    return ContractQuote(ok=True, fee=result.money.as_text(), rule=ref or {}, reason=REASON_OK)


def decide(db, order, *, driver_id: int | None, claimed_fee=None) -> FreightDecision:
    """**唯一组装点**：这一单的承运运费走哪条路、契约算出多少、和人给的一样不一样。

    `claimed_fee` = 派单员（或界面）带过来的金额；`None` = 这次没有金额（例如只补分类）。
    """
    from app.services.freight_pricing import quote_for
    from app.services.order_money import freight_kind_of, rule_ref_of_candidate

    # ⭐ 已经定过来源的单**沿用**那一个（⑧-a 出口条件 ③）—— ⛔ 不拿当前比例重新抽签。
    frozen = freight_kind_of(order)
    kind = policy_for(getattr(order, "id", None), frozen=frozen)
    # 两条路都要在快照里留下"是哪一条价目" —— 那是**核心的事实**，与走哪条路无关。
    try:
        quote = quote_for(db, order, driver_id=driver_id)
        rule = rule_ref_of_candidate(quote.matched, origin="derived") if quote.matched else None
    except Exception:  # noqa: BLE001
        rule = None

    if kind != KIND_CONTRACT or claimed_fee is None:
        # 没走契约那一支：`reason` 如实写`没走`（不是失败，是这一次不在 canary 桶里 / 没有金额）。
        # ⭐ 但**"没走"有两种**（R4-36 拆开的正是这一处）：
        #    这张单**已经定过来源、这一次是沿用**（frozen）≠ 这一次**没被抽中**（not_in_canary）。
        #    ⛔ 不拆的话，生产上"冻结住了"与"没抽中"写出来一模一样，冻结就永远验不了。
        return FreightDecision(
            kind=KIND_LEGACY, rule=rule, reason=REASON_OK,
            resolution=(RESOLUTION_FROZEN if frozen == KIND_LEGACY
                        else RESOLUTION_NOT_IN_CANARY),
        )

    got = contract_quote(db, order, driver_id=driver_id)
    if not got.ok:
        # ⛔ 退回旧路**必须说清是哪一种**（原因码 + 一句人话 + 细节），否则运维还得去查库。
        return FreightDecision(
            kind=KIND_LEGACY, rule=rule, reason=got.reason,
            resolution=RESOLUTION_FALLBACK,
            note="契约没算出结论【" + got.reason + "】" + got.text
                 + ("　细节：" + got.detail if got.detail else "")
                 + " —— 按旧路记，金额以派单员为准",
        )
    fee_text = got.fee or ""
    agreed = _decimals(claimed_fee) == Decimal(fee_text)
    return FreightDecision(
        kind=KIND_CONTRACT,
        rule=(got.rule or rule),
        quoted_fee=fee_text,
        agreed=agreed,
        override=not agreed,
        reason=REASON_OK,
        resolution=RESOLUTION_CONTRACT,
        note="" if agreed else ("价目算出来是 " + fee_text + "，派单员定的是 "
                                + str(_decimals(claimed_fee)) + " —— ⛔ 以人为准，但两个数都留下"),
    )
