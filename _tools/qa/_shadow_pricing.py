# -*- coding: utf-8 -*-
"""**Shadow 定价对照**（R4-17）：同一张真订单，两条路各算一遍，逐笔比。

## 用户 §7 的原话

> 「影子阶段必须证明的不是『跑过』，而是『**没有漂移**』……至少要统计：
>  total / matched / mismatched / error / unsupported。我建议最终要求：
>  expected-equivalent orders: mismatch = 0, calculation error = 0。」
> 「**Shadow 模式下绝对不能写 Ledger。** 只做 calculate / compare / record。」

## 两条路

| | 算什么 | 怎么算 |
| --- | --- | --- |
| **Legacy** | 生产今天真的在跑的那一版 | `services/freight_pricing.quote_for(db, order, driver_id)` |
| **Extension** | R4-16 的候选实现 | `freight_snapshot_of(...)` → `PricingContext` → `extensions/pricing/freight_template.py` |

⭐ 两边读的是**同一份事实**：快照由**核心**导出（`freight_snapshot_of`，与 `quote_for`
共用 `driver_template_ids` / `route_ids_of` / `candidate_templates`）。
⛔ 不是对照脚本自己照着读一遍 —— 那样的"对照"是两个算法在比，不是同一个算法两条路。

## ⛔ 「没写库」是被**证**出来的，不是被承诺的

跑之前跑之后各数一遍 `orders / ledgers / cash_flows / outbox_events / driver_bills` 的行数，
**必须一模一样**；不等就报红。另外对照本身只做 `SELECT`（没有任何 `add`/`flush`/`commit`）。

用法：
    python _tools/qa/_shadow_pricing.py --check                # 本机：种子世界自检（进必跑组）
    python _tools/qa/_shadow_pricing.py --orders --limit 500 --json out.json
        # 对一个**真库**里的真订单跑（只读）—— DATABASE_URL 指哪就打哪
"""
from __future__ import annotations

import argparse
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
COUNTED = ("orders", "ledgers", "cash_flows", "outbox_events", "driver_bills")
sys.path.insert(0, str(BACKEND))

#: 只读对照里**只许**出现这些语句开头（防"顺手写了一下"）。数不清就看不出漂移。
_READONLY_HINT = "本对照是只读的：快照由核心导出，扩展只做纯计算"


def _counts(db) -> dict:
    from sqlalchemy import text

    out = {}
    for t in COUNTED:
        try:
            out[t] = int(db.execute(text("SELECT COUNT(*) FROM " + t)).scalar() or 0)
        except Exception:  # noqa: BLE001 —— 表不存在（极老的库）就当 0，⛔ 不抛
            out[t] = -1
    return out


def outcome_of(legacy_quote=None, result=None, exc: Exception | None = None) -> dict:
    """两条路的结论归一成同一形状 —— ⛔ 只比"算出哪一条、多少钱、是不是不猜"，不比文案。"""
    from app.core.contracts.pricing import AmbiguousPricingRule, NoPricingRule

    if exc is not None:
        if isinstance(exc, AmbiguousPricingRule):
            return {"kind": "ambiguous",
                    "ids": sorted(int(m) for m in re.findall(r"#(\d+)", " ".join(exc.candidates)))}
        if isinstance(exc, NoPricingRule):
            return {"kind": "none", "ids": []}
        return {"kind": "error", "ids": [], "why": type(exc).__name__ + ": " + str(exc)[:160]}
    if legacy_quote is not None:
        q = legacy_quote
        if q.matched is not None:
            return {"kind": "matched", "fee": str(Decimal(q.matched.fee).quantize(Decimal("0.01"))),
                    "ids": [int(q.matched.template_id)]}
        if q.ambiguous:
            return {"kind": "ambiguous", "ids": sorted(int(c.template_id) for c in q.ambiguous)}
        return {"kind": "none", "ids": []}
    return {"kind": "matched", "fee": result.money.as_text(),
            "ids": sorted(int(m) for m in re.findall(r"#(\d+)", result.rule_name))}


def compare_one(db, order, *, kind: str = "freight_template") -> dict:
    """一张订单 → (legacy 结论, extension 结论)。⛔ 全程只读。"""
    from app.core.contracts.pricing import PricingContext
    from app.extensions.pricing import resolve_v2
    from app.services.freight_pricing import freight_snapshot_of, quote_for

    driver_id = getattr(order, "driver_id", None)
    legacy = outcome_of(legacy_quote=quote_for(db, order, driver_id=driver_id))
    snapshot = freight_snapshot_of(db, order, driver_id=driver_id)
    snapshot["pricing_kind"] = kind
    ctx = PricingContext(
        order_id=int(order.id), order_no=order.order_no or "",
        category=order.freight_category or "", to_place=(order.address_detail or "").strip(),
        driver_id=driver_id, rule_snapshot=snapshot,
    )
    try:
        # ⛔ 走的是**契约**（resolve_v2 → 适配器/原生），不是直接摸实现：
        #    这一段就是用户 §12 要的那条链 Order -> PricingContext -> Contract -> Money。
        result = resolve_v2(ctx).price(ctx)
        ext = outcome_of(result=result)
    except Exception as exc:  # noqa: BLE001 —— 错误也是一种结论，要计数
        ext = outcome_of(exc=exc)
    return legacy, ext


def run_orders(db, *, limit: int, kind: str = "freight_template") -> dict:
    from sqlalchemy import select

    from app.models import Order

    before = _counts(db)
    rows = list(db.scalars(
        select(Order).where(Order.driver_id.isnot(None)).order_by(Order.id.desc()).limit(int(limit))
    ).all())
    tally = {"total": 0, "matched": 0, "mismatched": 0, "error": 0, "unsupported": 0,
             "skipped_no_driver": 0}
    diffs: list[dict] = []
    for o in rows:
        tally["total"] += 1
        a, b = compare_one(db, o, kind=kind)
        if a.get("kind") == "error" or b.get("kind") == "error":
            tally["error"] += 1
            diffs.append({"order_no": o.order_no, "legacy": a, "extension": b})
        elif a != b:
            tally["mismatched"] += 1
            diffs.append({"order_no": o.order_no, "legacy": a, "extension": b})
        else:
            tally["matched"] += 1
    after = _counts(db)
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "limit": limit,
        "counts_before": before,
        "counts_after": after,
        "wrote_anything": before != after,
        "tally": tally,
        "diffs": diffs[:50],
        "note": _READONLY_HINT,
    }


def seed_self_check_db():
    """`--check` 用的那份**固定世界**（本机、临时库、确定性）。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.schema_bootstrap import prepare_schema
    from app.models import (
        DriverBillingRule, DriverBillingRuleTemplate, FreightCategory, FreightTemplate,
        FreightTemplateCategory, Order, ShipperAddress, User,
    )
    from app.models.enums import OrderStatus, UserRole

    path = Path(tempfile.mkdtemp()) / "shadow_self.db"
    engine = create_engine("sqlite:///" + path.as_posix())
    prepare_schema(engine)
    db = sessionmaker(bind=engine)()
    db.add(ShipperAddress(id=1, shipper_id=1, detail_address="自检路 1 号", receiver_name="", phone=""))
    db.add(FreightCategory(id=3, name="蔬菜"))
    db.flush()
    db.add(FreightTemplate(id=12, name="自检价目", price_name="", fee=Decimal("120.00"),
                           route_id=1, to_place="自检路 1 号", from_place=""))
    db.add(FreightTemplate(id=13, name="同类第二条", price_name="", fee=Decimal("127.50"),
                           route_id=1, to_place="自检路 1 号", from_place=""))
    db.flush()
    db.add(FreightTemplateCategory(template_id=12, category_id=3))
    db.add(FreightTemplateCategory(template_id=13, category_id=3))
    db.add(DriverBillingRule(id=5, name="自检规则", salary=Decimal("0"), piece_amount=Decimal("0"),
                             commission_rate=Decimal("0"), vehicle_type=None, is_deleted=False))
    db.flush()
    db.add(DriverBillingRuleTemplate(rule_id=5, template_id=12))
    db.add(User(id=21, username="shadow-21", phone="13900000021", password_hash="x",
                full_name="自检司机", role=UserRole.DRIVER, is_active=True, driver_rule_id=5))
    db.flush()
    for i, (cat, no) in enumerate([(3, "SO-S-1"), (None, "SO-S-2")], start=1):
        db.add(Order(id=i, order_no=no, shipper_id=1, order_date=datetime.date(2026, 9, 27),
                     address_detail="自检路 1 号", freight_category_id=cat,
                     freight_category=("蔬菜" if cat else ""), driver_id=21,
                     status=OrderStatus.PENDING_DISPATCH))
    db.commit()
    return db


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="本机自检（种子世界，进必跑组）")
    ap.add_argument("--orders", action="store_true", help="对一个真库里的真订单跑（只读）")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--json", help="把结果写到这个文件")
    a = ap.parse_args()

    if a.check:
        db = seed_self_check_db()
        try:
            rep = run_orders(db, limit=50)
        finally:
            db.close()
        t = rep["tally"]
        ok = (t["mismatched"] == 0 and t["error"] == 0 and not rep["wrote_anything"]
              and t["total"] >= 2)
        print(("✅" if ok else "❌")
              + " Shadow 自检（种子世界）：total " + str(t["total"]) + " / matched " + str(t["matched"])
              + " / **mismatched " + str(t["mismatched"]) + "** / error " + str(t["error"])
              + "；写库：" + ("**有**（!）" if rep["wrote_anything"] else "没有"))
        return 0 if ok else 1

    if a.orders:
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            rep = run_orders(db, limit=a.limit)
        finally:
            db.close()
        t = rep["tally"]
        print("Shadow 对照：" + str(a.limit) + " 张上限 → total " + str(t["total"])
              + " / matched " + str(t["matched"]) + " / **mismatched " + str(t["mismatched"])
              + "** / error " + str(t["error"]) + " / unsupported " + str(t["unsupported"]))
        print("写库前 " + json.dumps(rep["counts_before"], ensure_ascii=False))
        print("写库后 " + json.dumps(rep["counts_after"], ensure_ascii=False))
        for d in rep["diffs"][:10]:
            print("  ⛔ " + str(d["order_no"]) + "  legacy=" + json.dumps(d["legacy"], ensure_ascii=False)
                  + "  extension=" + json.dumps(d["extension"], ensure_ascii=False))
        if a.json:
            Path(a.json).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
            print("原始事实：" + a.json)
        return 1 if (t["mismatched"] or t["error"] or rep["wrote_anything"]) else 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
