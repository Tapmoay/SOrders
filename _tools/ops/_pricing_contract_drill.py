# -*- coding: utf-8 -*-
"""**算价契约在真实数据上的接线演练**（R4-24，跑在演练库上）。

## 它回答的问题

R4-21 在生产上观察到的结果只有一支：**退回旧路（no_candidates）** ——
因为生产上 `driver_billing_rule_templates` 是 **0 行**（没有任何规则勾过价目）。
于是"走契约那一支到底成不成立"在生产上**没有数据可证**。

这个演练把同一件事搬到**生产数据的副本**上，只补**一行配置**，然后问组装点：
这一单现在走哪条路？

    Order → PricingContext → PricingContract → Money

⛔ 跑在 **演练库**（`sorders_drill_*`）上，⛔ **不碰生产库、不改生产任何配置**。

## 用法（在**生产机**上跑，因为演练库在那台机器上）

    bash: export DATABASE_URL=<演练库>; /opt/SOrders/backend/.venv/bin/python /tmp/_pricing_contract_drill.py
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/opt/SOrders/backend")

from sqlalchemy import select, text  # noqa: E402

from app.core.pricing_runtime import (  # noqa: E402
    REASON_TEXT,
    contract_quote,
    decide,
    register_pricing_resolver,
)
from app.database import SessionLocal  # noqa: E402
from app.models import DriverBillingRuleTemplate, FreightTemplate, Order, ShipperAddress, User  # noqa: E402


def main() -> int:
    # ⭐ 装配根那一跳：脚本在这里**扮演装配根**（生产上是 app/main.py 干的）。
    from app.extensions.pricing import resolve_v2

    register_pricing_resolver(resolve_v2)

    db = SessionLocal()
    def q(sql, **kw):
        return db.execute(text(sql), kw).fetchall()

    print("== 0. 演练库现状（配置之前）==")
    print("   规则勾价目行数 =", q("SELECT COUNT(*) FROM driver_billing_rule_templates")[0][0])
    print("   价目条数       =", q("SELECT COUNT(*) FROM freight_templates WHERE is_deleted=0")[0][0])

    # ---- 1. 补**一行**配置：让规则 2 勾上价目 2（惠州仲恺 → 深圳龙岗，88.00）----
    db.execute(text("INSERT IGNORE INTO driver_billing_rule_templates (rule_id, template_id, created_at, updated_at) "
                    "VALUES (2, 2, NOW(), NOW())"))
    db.commit()
    print("== 1. 补了一行配置：规则 2 勾上价目 2 ==")
    print("   规则勾价目行数 =", q("SELECT COUNT(*) FROM driver_billing_rule_templates")[0][0])

    # ---- 2. 找一单：司机挂着规则 2、地址正好是价目 2 那条线路的终点 ----
    tpl = db.get(FreightTemplate, 2)
    route = db.get(ShipperAddress, tpl.route_id) if tpl.route_id else None
    addr = (tpl.to_place or "").strip()
    route_addr = (route.detail_address or "").strip() if route else ""
    print("   价目 2：to_place=" + addr + " / route_id=" + str(tpl.route_id)
          + " / 那条线路的终点=" + route_addr + " / fee=" + str(tpl.fee))

    rows = q("SELECT o.id, o.order_no, o.driver_id, o.address_detail FROM orders o "
             "JOIN users u ON u.id = o.driver_id "
             "WHERE u.driver_rule_id = 2 AND o.driver_id IS NOT NULL "
             "AND o.deleted_at IS NULL ORDER BY o.id DESC LIMIT 20")
    picked = None
    for oid, ono, did, addr2 in rows:
        if (addr2 or "").strip() in (addr, route_addr):
            picked = (oid, ono, did, addr2)
            break
    if picked is None:
        print("   ⚠️ 没有现成的单落在这条线路上 —— 直接用司机 " + str(rows[0][2]) + " 那一单改地址来演（**只在演练库**）")
        if not rows:
            print("   ⛔ 连一个挂规则 2 的司机都没有，演练做不下去")
            return 1
        oid, ono, did, _old = rows[0]
        db.execute(text("UPDATE orders SET address_detail = :a WHERE id = :i"), {"a": route_addr or addr, "i": oid})
        db.commit()
        picked = (oid, ono, did, route_addr or addr)
    oid, ono, did, oaddr = picked
    print("== 2. 挑中订单 " + str(ono) + "（id=" + str(oid) + "，司机 " + str(did) + "，地址 " + oaddr + "）==")

    order = db.get(Order, oid)
    got = contract_quote(db, order, driver_id=did)
    print("== 3. 问契约 ==  ok=" + str(got.ok) + "  fee=" + str(got.fee)
          + "  reason=" + got.reason + "（" + REASON_TEXT.get(got.reason, "") + "）")
    if not got.ok:
        print("   ⛔ 契约仍然算不出来 —— 演练不成立")
        return 1

    fee = got.fee
    d1 = decide(db, order, driver_id=did, claimed_fee=fee)
    print("== 4. 界面带的数 == 契约的数（" + str(fee) + "）==")
    print("   kind=" + d1.kind + "  reason=" + d1.reason + "  agreed=" + str(d1.agreed)
          + "  override=" + str(d1.override) + "  rule=" + json.dumps(d1.rule, ensure_ascii=False))

    other = str(float(fee) + 10)
    d2 = decide(db, order, driver_id=did, claimed_fee=other)
    print("== 5. 派单员改过价（" + other + "）==")
    print("   kind=" + d2.kind + "  agreed=" + str(d2.agreed) + "  override=" + str(d2.override))
    print("   note=" + d2.note)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
