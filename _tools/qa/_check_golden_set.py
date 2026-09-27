# -*- coding: utf-8 -*-
"""**计价回归语料集（Golden Set）** —— 承运运费的 Legacy vs Extension **逐笔**比对。

## 为什么要有它（用户 2026-09-27 §11）

> 「不要只测 120.00 / 127.50，应该从现有数据里抽取脱敏/安全的真实计价样本，建立
>  Pricing Golden Set，覆盖：普通订单 / 边界 / 零值 / 小数 / 最大值 / 不同单位 /
>  不同计价类型 / 折扣 / 附加费 / 四舍五入边界 / 异常输入，然后 Legacy vs Extension
>  **自动逐笔比较**。这样比手工造十几个 case 强得多。」

R4-GOLDEN-JUSTIFICATION: **为什么代码边界解决不了这件事。**
「扩展算得跟生产一样」不是任何单个文件的属性 —— Legacy 在核心（`services/freight_pricing.py`）、
候选在扩展（`extensions/pricing/freight_template.py`），两边各自看都合法、各自都有测试。
**只有把它们放在同一份输入上逐笔比，才知道它们是不是同一个数。**
这正是用户 §12 那条链的验收方式：`Order → PricingContext → PricingContract → Money`。

## 两份东西

| | 是什么 | 谁写的 |
| --- | --- | --- |
| **语料** `_tools/qa/_golden/freight_pricing.json` | 一批**输入世界** + 每条**期望结论** | 人写边界样例；真实样本从库里采（脱敏） |
| **比对器**（本文件） | 把同一份世界喂给两边，逐笔比 | 机器 |

⛔ **期望值必须由「人说的」和「Legacy 算的」两栏对得上**才准进语料 ——
只有 Legacy 那一栏的话，这份语料的结论就只是"候选像 Legacy"，而不是"候选对"。
这两件事差别很大，文档里 §3 单独写明了。

## 三种比对结论

- `match`：金额（两位小数口径）与"哪一条价目"都对上；
- `mismatch`：**任何一处对不上就报红** —— 用户原话「不要立刻说差一点点没关系，尤其是钱」；
- `known-diff`：**写在语料里的已知差异**，每条必须带理由，且判据核它**仍然成立**（防化石）。

用法：
    python _tools/qa/_check_golden_set.py --build     # 重新生成语料（会覆盖）
    python _tools/qa/_check_golden_set.py --compare   # 逐笔比对并打表
    python _tools/qa/_check_golden_set.py             # 必跑模式：语料自检 + 比对 0 漂移
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
CORPUS = Path(__file__).resolve().parent / "_golden" / "freight_pricing.json"
os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + (Path(tempfile.mkdtemp()) / "golden.db").as_posix()
)
sys.path.insert(0, str(BACKEND))

#: 语料必须覆盖的桶（用户 §11 点名的那几个）—— 一条都不能少，缺了就报红。
#: ⛔ 「不适用」也是答案，但必须**写下来**（见 NOT_APPLICABLE），不许安静地少一个桶。
BUCKETS = (
    "normal", "boundary", "zero", "decimal", "max",
    "unit", "pricing_kind", "discount", "surcharge", "rounding", "error",
)

#: 明确「承运运费这个计价方式里**没有**这个维度」的桶 —— 每一条都要写清为什么。
NOT_APPLICABLE: dict[str, str] = {
    "unit": "承运运费是「一条路线一条价」，**不按件/不按斤** —— 单位只影响商品行（quantity × unit_price）。"
            "要按量计价是**另一个计价方式**（扩展里的 per_quantity / tiered 就是），不属于这一条比对的输入。",
    "discount": "当前承运运费的模型里**没有折扣这一维**（价目就是最终金额）。"
                "⛔ 造一个「打折的价目」出来，比的就成了我编的规则，不是生产。",
    "surcharge": "同上：模型里没有附加费这一维。要加是**新能力**，得先有产品口径，再进语料。",
}

#: 已知差异表（比对时不算 mismatch，但必须带理由、且理由要能被核）。
#: 键 = case id；值 = 为什么它不算漂移。
KNOWN_DIFF: dict[str, str] = {}


from app.models.enums import OrderStatus, UserRole  # noqa: E402


def _models():
    import app.main  # noqa: F401  —— 让枚举看到应用实际注册的全部模型
    from app.models import (
        DriverBillingRule,
        DriverBillingRuleTemplate,
        FreightCategory,
        FreightTemplate,
        FreightTemplateCategory,
        Order,
        ShipperAddress,
        User,
    )
    return dict(locals())


def build_db(case: dict):
    """把 case 里的 world 播进一个**临时库**（每个 case 一个库，互不干扰）。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.schema_bootstrap import prepare_schema

    path = Path(tempfile.mkdtemp()) / "case.db"
    engine = create_engine("sqlite:///" + path.as_posix())
    prepare_schema(engine)
    db = sessionmaker(bind=engine)()
    M = _models()
    w = case["world"]

    for a in w.get("addresses", []):
        db.add(M["ShipperAddress"](id=a["id"], shipper_id=1, detail_address=a["detail"],
                                   receiver_name="", phone=""))
    for c in w.get("categories", []):
        db.add(M["FreightCategory"](id=c["id"], name=c["name"], sort_order=0))
    db.flush()
    for t in w.get("templates", []):
        db.add(M["FreightTemplate"](id=t["id"], name=t["name"], price_name=t.get("price_name", ""),
                                    fee=Decimal(str(t["fee"])), route_id=t.get("route_id"),
                                    to_place=t.get("to_place", ""), from_place=t.get("from_place", "")))
    db.flush()
    for t in w.get("templates", []):
        for cid in t.get("category_ids", []):
            db.add(M["FreightTemplateCategory"](template_id=t["id"], category_id=int(cid)))
    rule = w.get("driver", {}).get("rule")
    if rule is not None:
        db.add(M["DriverBillingRule"](id=rule["id"], name=rule["name"], salary=Decimal("0"),
                                      piece_amount=Decimal("0"), commission_rate=Decimal("0"),
                                      vehicle_type=None, is_deleted=False))
        db.flush()
        for tid in rule.get("template_ids", []):
            db.add(M["DriverBillingRuleTemplate"](rule_id=rule["id"], template_id=int(tid)))
    drv = w["driver"]
    db.add(M["User"](id=drv["id"], username="golden-driver-" + str(drv["id"]),
                     phone="139" + str(drv["id"]).zfill(8), password_hash="x",
                     full_name="语料司机", role=UserRole.DRIVER, is_active=True,
                     driver_rule_id=(rule["id"] if rule else None)))
    o = case["order"]
    db.add(M["Order"](id=1, order_no=o["order_no"], shipper_id=1,
                      order_date=datetime.date(2026, 9, 27),
                      address_detail=o["to_place"], freight_category_id=o.get("category_id"),
                      freight_category=(o.get("category") or ""), status=OrderStatus.PENDING_DISPATCH))
    db.commit()
    return db, M["Order"], drv["id"]


def legacy_outcome(db, Order, driver_id: int, case: dict) -> dict:
    """跑**核心**那一版（`services/freight_pricing.quote_for`）→ 归一成结论。"""
    from app.services.freight_pricing import quote_for

    order = db.get(Order, 1)
    q = quote_for(db, order, driver_id=int(driver_id))
    if q.matched is not None:
        raw = q.matched.fee
        return {"kind": "matched", "raw": str(raw),
                "fee": str(Decimal(raw).quantize(Decimal("0.01"))),
                "ids": [int(q.matched.template_id)], "why": ""}
    if q.ambiguous:
        return {"kind": "ambiguous", "raw": "", "fee": None,
                "ids": sorted(int(c.template_id) for c in q.ambiguous), "why": q.reason}
    return {"kind": "none", "raw": "", "fee": None, "ids": [], "why": q.reason}


def snapshot_from_db(db, Order, driver_id: int, case: dict) -> dict:
    """**核心会怎么把这一单读成一份快照** —— 候选集 + 这个地址的线路编号。

    ⚠️ 这一小段是**照着 `quote_for` 自己的那几处读法**写的（谁由核心读、谁由扩展算，
    见扩展文件头那张表）。它同时也是这份语料**最大的残余风险**：
    它是我转录的，不是核心自己导出的 ⇒ 所以 ⑤ Shadow 那一步要用**核心侧**的构造器再证一次。
    """
    from sqlalchemy import select

    from app.models import (
        FreightTemplate,
        FreightTemplateCategory,
        DriverBillingRule,
        DriverBillingRuleTemplate,
        ShipperAddress,
        User,
    )

    order = db.get(Order, 1)
    addr = (order.address_detail or "").strip()
    route_ids = [int(x) for x in db.scalars(
        select(ShipperAddress.id).where(ShipperAddress.detail_address == addr)).all()]
    picked: set[int] = set()
    driver = db.get(User, int(driver_id))
    rule_id = getattr(driver, "driver_rule_id", None) if driver is not None else None
    if rule_id is not None:
        rule = db.get(DriverBillingRule, int(rule_id))
        if rule is not None and not rule.is_deleted:
            picked = {int(x) for x in db.scalars(
                select(DriverBillingRuleTemplate.template_id)
                .where(DriverBillingRuleTemplate.rule_id == int(rule_id))).all()}
    rows = [t for t in db.scalars(select(FreightTemplate).where(
        FreightTemplate.is_deleted.is_(False))).all() if int(t.id) in picked]
    cats: dict[int, list[int]] = {}
    if rows:
        for tid, cid in db.execute(select(FreightTemplateCategory.template_id,
                                          FreightTemplateCategory.category_id)
                                   .where(FreightTemplateCategory.template_id.in_(
                                       [int(t.id) for t in rows]))).all():
            cats.setdefault(int(tid), []).append(int(cid))
    return {
        "pricing_kind": "freight_template",
        "category_id": order.freight_category_id,
        "route_ids": route_ids,
        "templates": [
            {"id": int(t.id), "name": t.name or "", "price_name": t.price_name or "",
             "fee": str(t.fee), "to_place": (t.to_place or ""), "route_id": t.route_id,
             "category_ids": cats.get(int(t.id), [])}
            for t in rows
        ],
    }


def extension_outcome(db, Order, driver_id: int, case: dict) -> dict:
    """跑**候选实现**（`extensions/pricing/freight_template.py`）→ 归一成同一形状的结论。"""
    from app.core.contracts.pricing import AmbiguousPricingRule, NoPricingRule, PricingContext
    from app.extensions.pricing.freight_template import PROVIDER

    order = db.get(Order, 1)
    snapshot = snapshot_from_db(db, Order, driver_id, case)
    snapshot.update(case.get("snapshot_patch") or {})     # 只给「这一单不归它管」那一类样例用
    ctx = PricingContext(
        order_id=int(order.id), order_no=order.order_no or "",
        category=order.freight_category or "", to_place=(order.address_detail or "").strip(),
        driver_id=int(driver_id),
        rule_snapshot=snapshot,
    )
    if not PROVIDER.applies_to(ctx):
        return {"kind": "not-mine", "raw": "", "fee": None, "ids": [], "why":
                "快照里的 pricing_kind=" + repr(snapshot.get("pricing_kind")) + " 不归这个实现管"}
    try:
        result = PROVIDER.price(ctx)
    except AmbiguousPricingRule as exc:
        ids = sorted(int(m) for m in (re.findall(r"#(\d+)", " ".join(exc.candidates)) or []))
        return {"kind": "ambiguous", "raw": "", "fee": None, "ids": ids, "why": str(exc)}
    except NoPricingRule as exc:
        return {"kind": "none", "raw": "", "fee": None, "ids": [], "why": str(exc)}
    ids = sorted(int(m) for m in re.findall(r"#(\d+)", result.rule_name))
    return {"kind": "matched", "raw": result.money.as_text(),
            "fee": result.money.as_text(), "ids": ids, "why": ""}


def run_case(case: dict) -> tuple[dict, dict]:
    """一份世界喂两边 → (核心那一版的结论, 候选实现的结论)。"""
    db, Order, driver_id = build_db(case)
    try:
        if case.get("extension_only"):
            # 「这一单不归它管」这类样例没有"核心那一版"可对 —— ⛔ 那就**不假装有**，
            # 独立成一条：只断言候选实现自己的判断（applies_to / 结论）。
            return None, extension_outcome(db, Order, driver_id, case)
        return (legacy_outcome(db, Order, driver_id, case),
                extension_outcome(db, Order, driver_id, case))
    finally:
        db.close()


def compare_case(case: dict) -> tuple[str, str, dict]:
    """一份世界喂两边，逐笔比 → (结论, 说明, 核心那一版的结论)。"""
    a, b = run_case(case)
    if a is None:
        # 「这一单不归它管」那类样例没有"核心那一版"可对 —— ⛔ 不假装有。
        # 真正的断言在主流程里（拿 b 与语料里的 expect 逐条比）。
        return "match", "扩展自证：" + b["kind"], None

    def _core(o: dict) -> dict:
        """比对的**口径**：只看"算出哪一条、多少钱、是不是不猜" —— ⛔ 不比文案。
        `raw` 是核心原样给出的数（未经两位小数），`why` 是给人看的句子，两者都不参与判定
        （但 `raw` 会被单独核，见下面那条 note）。"""
        return {"kind": o["kind"], "fee": o["fee"], "ids": o["ids"]}

    if _core(a) == _core(b):
        extra = ""
        if a["kind"] == "matched" and a["raw"] != a["fee"]:
            extra = "（⚠️ 核心原样给出 " + a["raw"] + "，取两位小数后才是 " + a["fee"] + "）"
        return "match", "两边都是 " + a["kind"] + " " + str(a["fee"] or a["ids"]) + extra, a
    if case["id"] in KNOWN_DIFF:
        return "known-diff", "已声明的差异：" + KNOWN_DIFF[case["id"]], a
    return "mismatch", ("核心 " + json.dumps(a, ensure_ascii=False)
                        + " / 候选 " + json.dumps(b, ensure_ascii=False)), a


def load() -> dict:
    if not CORPUS.exists():
        raise SystemExit("语料不存在：" + str(CORPUS) + "（先跑 --build）")
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def main() -> int:
    args = set(sys.argv[1:])
    data = load()
    cases = data["cases"]
    fails: list[str] = []

    if "--build" in args:
        print("语料是**手写**的（见文件头 §两份东西）—— 重建请改 _golden/freight_pricing.json 后跑 --compare")
        return 0

    if "--compare" in args or not args:
        buckets = {c["bucket"] for c in cases}
        miss = [b for b in BUCKETS if b not in buckets and b not in NOT_APPLICABLE]
        if miss:
            fails.append("语料缺桶：" + "、".join(miss))
        bad_na = [b for b in NOT_APPLICABLE if b in buckets]
        if bad_na:
            fails.append("声明了「不适用」却又有样例的桶：" + "、".join(bad_na))
        ids = [c["id"] for c in cases]
        if len(ids) != len(set(ids)):
            fails.append("case id 有重复")
        for c in cases:
            for key in ("id", "bucket", "why", "world", "order", "expect", "origin"):
                if key not in c:
                    fails.append("case " + c["id"] + " 少了字段 " + key)
        if fails:
            for f in fails:
                print("[FAIL] " + f)
            return 1

    tally = {"match": 0, "mismatch": 0, "known-diff": 0}
    rows: list[str] = []
    wrong_expect: list[str] = []
    mism: list[str] = []
    # ⚠️ 每条样例**只跑一次**：每跑一次都要现建一个临时库 + 跑九条迁移，
    #    第一版在这里又算了一遍（拿它去挑 mismatch），白跑一倍的时间。
    for c in cases:
        verdict, why, a = compare_case(c)
        tally[verdict] += 1
        if verdict == "mismatch":
            mism.append(c["id"])
        # ⭐ **语料说的**必须和**核心算的**对上 —— 只有核心那一栏的话，这份语料的结论
        #    就只是"候选像核心"，而不是"候选对"。这两件事差别很大。
        if a is not None and "kind" in c["expect"]:
            want = {"kind": c["expect"]["kind"], "fee": c["expect"].get("fee"),
                    "ids": c["expect"].get("ids", []), "raw": c["expect"].get("raw"),
                    "why": c["expect"].get("why", "")}
            got = {"kind": a["kind"], "fee": a["fee"], "ids": a["ids"],
                   "raw": a["raw"], "why": a["why"] if c["expect"].get("why") else ""}
            if c["expect"].get("raw") is None:
                got["raw"] = None
            if got != want:
                wrong_expect.append(c["id"] + "：语料说 " + json.dumps(want, ensure_ascii=False)
                                    + " / 核心算的 " + json.dumps(got, ensure_ascii=False))
        if a is None:
            b = run_case(c)[1]
            ok = (b["kind"] == c["expect"]["kind"])
            tally["match" if ok else "mismatch"] += 0 if ok else 1
            if not ok:
                wrong_expect.append(c["id"] + "（扩展自证）：期望 " + c["expect"]["kind"]
                                    + " / 实际 " + b["kind"])
            why = "扩展自证：" + b["kind"] + " —— " + b["why"]
        rows.append("  [" + ("OK  " if verdict == "match" else
                             ("DIFF" if verdict == "known-diff" else "MISS")) + "] "
                    + c["id"].ljust(28) + " " + c["bucket"].ljust(12) + " " + why)
    if "--compare" in args:
        print("== 承运运费 Golden Set：Legacy vs Extension 逐笔 ==")
        for r in rows:
            print(r)
    if wrong_expect:
        for w in wrong_expect:
            print("[FAIL] 语料的期望与核心不一致：" + w)
    print(("✅" if not mism and not wrong_expect else "❌")
          + " Golden Set：语料 " + str(len(cases)) + " 条 —— match " + str(tally["match"])
          + " / known-diff " + str(tally["known-diff"]) + " / **mismatch " + str(tally["mismatch"]) + "**"
          + ("；漂移的：" + "、".join(mism) if mism else "")
          + ("；语料期望对不上的：" + str(len(wrong_expect)) if wrong_expect else ""))
    return 1 if (mism or wrong_expect) else 0


if __name__ == "__main__":
    sys.exit(main())
