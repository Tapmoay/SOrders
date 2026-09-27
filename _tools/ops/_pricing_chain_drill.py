# -*- coding: utf-8 -*-
"""**算价链路的接线演练（参数化）**（R4-42）：在**生产数据的副本**上，把某一对 (规则, 价目)
配上去，然后问组装点：这一单现在走哪条路、算出来多少。

## 为什么要有它（而不是等真实派单）

用户 §七 要的是「真实派单 → Canary 命中 → Contract → 金额 → 快照」。
而真实派单**只能等**。在等的时候，这个演练把同一件事搬到**副本**上先跑一遍：
⛔ 它证明不了"生产真的会产生这一笔"，但能证明「**配置一到位，这条链路就通**」——
   如果连副本上都算不出来，那等再久也是白等。

## ⛔ 三条不许

1. ⛔ 只跑在 **演练库**（库名里必须有 drill）—— 它要往库里插那一行配置；
2. ⛔ **不碰生产库、不改生产配置**（生产上那一行是用户 2026-09-27 放行后单独执行的）；
3. ⛔ 不写库存（除了那一行演练配置）：只调只读的 `contract_quote` / `decide`。

用法（在**生产机**上跑，因为演练库在那台机器上）：

    bash: export DATABASE_URL=<演练库> FREIGHT_PRICING_CANARY_PERCENT=100
          /opt/SOrders/backend/.venv/bin/python /tmp/_pricing_chain_drill.py \
              --rule 1 --template 5 --order 20709 --driver 167
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, "/opt/SOrders/backend")

from sqlalchemy import text  # noqa: E402

from app.core.pricing_runtime import REASON_TEXT, contract_quote, decide, register_pricing_resolver  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import FreightTemplate, Order, User  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", type=int, required=True)
    ap.add_argument("--template", type=int, required=True)
    ap.add_argument("--order", type=int, required=True)
    ap.add_argument("--driver", type=int, required=True)
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL", "")
    if "drill" not in url.lower():
        print("[!!] 这个脚本只肯跑在演练库上（库名里要有 drill）—— 当前：" + url.split("@")[-1])
        return 2

    from app.extensions.pricing import resolve_v2
    register_pricing_resolver(resolve_v2, identity="PricingContract v2 @ extensions.pricing")

    db = SessionLocal()
    def q(sql, **kw):
        return db.execute(text(sql), kw)

    print("== 0. 副本现状 ==")
    print("   链接行数 = " + str(q("select count(*) from driver_billing_rule_templates").scalar()))
    # ---- 只补**那一行**（与生产上刚配的那一对完全同形）----
    q("INSERT IGNORE INTO driver_billing_rule_templates (rule_id, template_id, created_at, updated_at) "
      "VALUES (:r, :t, NOW(), NOW())", r=args.rule, t=args.template)
    db.commit()
    db.expire_all()
    print("== 1. 补上那一行：规则 #" + str(args.rule) + " × 价目 #" + str(args.template) + " ==")
    print("   链接行数 = " + str(q("select count(*) from driver_billing_rule_templates").scalar()))

    tpl = db.get(FreightTemplate, args.template)
    order = db.get(Order, args.order)
    driver = db.get(User, args.driver)
    if tpl is None or order is None or driver is None:
        print("[!!] 副本里找不到这一单 / 这个司机 / 这条价目")
        return 1
    print("   价目 #" + str(tpl.id) + "「" + (tpl.name or "") + "」fee=" + str(tpl.fee)
          + " route_id=" + str(tpl.route_id) + " to_place=" + (tpl.to_place or ""))
    print("   订单 #" + str(order.id) + " " + str(order.order_no) + " 状态=" + str(order.status)
          + " 地址=" + str(order.address_detail))
    print("   司机 #" + str(driver.id) + " " + str(driver.full_name)
          + " driver_rule_id=" + str(driver.driver_rule_id))
    if driver.driver_rule_id != args.rule:
        print("[!!] 这个司机挂的不是规则 #" + str(args.rule) + " —— 演练不成立")
        return 1

    got = contract_quote(db, order, driver_id=args.driver)
    print("== 2. 问契约 ==  ok=" + str(got.ok) + "  fee=" + str(got.fee)
          + "  reason=" + got.reason + "（" + REASON_TEXT.get(got.reason, "") + "）")
    if not got.ok:
        print("   [!!] 契约仍然算不出来 —— 这条链路在副本上都不通：" + str(got.detail))
        return 1

    fee = got.fee
    d1 = decide(db, order, driver_id=args.driver, claimed_fee=fee)
    print("== 3. 界面给的数 == 契约算的数（" + str(fee) + "）==")
    print("   kind=" + d1.kind + "  resolution=" + d1.resolution + "  reason=" + d1.reason
          + "  agreed=" + str(d1.agreed) + "  override=" + str(d1.override))
    print("   rule=" + json.dumps(d1.rule, ensure_ascii=False))

    other = str(float(fee) + 10)
    d2 = decide(db, order, driver_id=args.driver, claimed_fee=other)
    print("== 4. 派单员改过价（" + other + "）==")
    print("   kind=" + d2.kind + "  resolution=" + d2.resolution
          + "  agreed=" + str(d2.agreed) + "  override=" + str(d2.override))
    print("   note=" + d2.note)
    print("")
    print("=> 结论：配置一到位，这条链路就通（⛔ 但这只是**副本**，不等于生产已产生这一笔）")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())