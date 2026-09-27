# -*- coding: utf-8 -*-
"""**契约支路的分支矩阵**（R4-25）：把每一种「配歪了」都演一遍，看它自己说不说得清。

## 为什么还要这一轮（R4-24 已经证了「能算出来」）

R4-24 只走通了**一条直线**：一个司机、一份规则、一条价目、地址正好对上。
而 ⑧ Full Cutover 要面对的是**用户会怎么配** —— 人配出来的东西一定是斜的：
没挂规则、勾了价目但路线不对、分类对不上、同一档两条、地址空着。
这五种在代码里**都有分支**，而 R4-24 一条都没在真实数据上验过。

⛔ 后果是**不对称**的，这才是必须逐条演戏的原因：

| 配错的样子 | 会发生什么 | 危险吗 |
| --- | --- | --- |
| 没配好（没规则 / 没勾价目） | 退回旧路，派单员照常填金额 | 没损失 |
| **配歪了却算出一个数** | 界面上的价格**静默变成另一个数** | 本项目最恨的那类错 |

所以第二类要**逐条证伪**：歪配置必须退回旧路并说清是哪一种，⛔ 绝不许猜出一个数来。

## ⛔ 它只肯跑在演练库上

这个脚本要**改配置行**（改司机挂哪份规则、规则勾哪几条价目、订单的地址与分类，
还会新建两条演练用价目）。所以它开跑第一件事就是检查库名里有没有 drill，
没有就拒绝启动 —— 免得哪天 DATABASE_URL 指错了地方，
**把生产上真实司机的规则改了**。

## 用法（在**生产机**上跑，因为演练库在那台机器上）

    bash: export DATABASE_URL=<演练库> FREIGHT_PRICING_CANARY_PERCENT=100
          /opt/SOrders/backend/.venv/bin/python /tmp/_pricing_contract_branches.py
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

sys.path.insert(0, "/opt/SOrders/backend")

from sqlalchemy import select, text  # noqa: E402

from app.core import pricing_runtime as pr  # noqa: E402
from app.core.pricing_runtime import (  # noqa: E402
    KIND_CONTRACT,
    KIND_LEGACY,
    contract_quote,
    decide,
    policy_for,
    register_pricing_resolver,
)
from app.database import SessionLocal  # noqa: E402
from app.models import DriverBillingRule, FreightTemplate, Order, ShipperAddress, User  # noqa: E402

RESULTS: list = []


def check(name: str, got, want) -> bool:
    ok = got == want
    RESULTS.append((ok, name))
    print(("  [OK] " if ok else "  [!!] ") + name + " -> " + str(got)
          + ("" if ok else "   (期望 " + str(want) + ")"))
    return ok


def has(name: str, hay, needle: str) -> bool:
    ok = needle in (hay or "")
    RESULTS.append((ok, name))
    print(("  [OK] " if ok else "  [!!] ") + name + " -> "
          + ("含「" + needle + "」" if ok else "不含！原文：" + str(hay)))
    return ok


def q(db, sql: str, **kw):
    return db.execute(text(sql), kw)


def one(db, sql: str, **kw):
    r = db.execute(text(sql), kw).fetchone()
    return None if r is None else r[0]


def set_rule_templates(db, rule_id: int, tpl_ids) -> None:
    q(db, "DELETE FROM driver_billing_rule_templates WHERE rule_id=:r", r=rule_id)
    for t in tpl_ids:
        q(db, "INSERT INTO driver_billing_rule_templates (rule_id, template_id, created_at, updated_at) "
              "VALUES (:r, :t, NOW(), NOW())", r=rule_id, t=t)
    db.commit()
    # ⛔ 必须 expire：核心那一步是 db.get(User, …)，走的是**会话的身份映射缓存**。
    #    不 expire 的话 raw UPDATE 写了库、读回来还是旧值 —— 第一版就是栽在这上面。
    db.expire_all()


def set_driver_rule(db, driver_id: int, rule_id) -> None:
    q(db, "UPDATE users SET driver_rule_id=:r WHERE id=:d", r=rule_id, d=driver_id)
    db.commit()
    db.expire_all()   # 同上：不 expire 就读到缓存里的旧规则


def set_order(db, order_id: int, *, address=None, touch_category=False, category_id=None) -> None:
    if address is not None:
        q(db, "UPDATE orders SET address_detail=:a WHERE id=:i", a=address, i=order_id)
    if touch_category:
        q(db, "UPDATE orders SET freight_category_id=:c, freight_category=NULL WHERE id=:i",
          c=category_id, i=order_id)
    db.commit()
    db.expire_all()


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if "drill" not in url.lower():
        print("[!!] 这个脚本只肯跑在演练库上（库名里要有 drill）—— 当前：" + url.split("@")[-1])
        return 2

    from app.extensions.pricing import resolve_v2

    db = SessionLocal()
    print("== 0. 底座 ==")
    print("   库：" + url.split("@")[-1])
    print("   canary 比例（env）：" + str(pr.canary_percent()) + "%")
    print("   订单 " + str(one(db, "SELECT COUNT(*) FROM orders"))
          + " / 价目 " + str(one(db, "SELECT COUNT(*) FROM freight_templates WHERE is_deleted=0"))
          + " / 规则勾价目 " + str(one(db, "SELECT COUNT(*) FROM driver_billing_rule_templates"))
          + " / 运费分类 " + str(one(db, "SELECT COUNT(*) FROM freight_categories")))

    orders_before = one(db, "SELECT COUNT(*) FROM orders")
    snaps_before = one(db, "SELECT COUNT(*) FROM orders WHERE freight_rule_snapshot IS NOT NULL")

    tpl = db.scalars(select(FreightTemplate).where(
        FreightTemplate.is_deleted.is_(False), FreightTemplate.route_id.isnot(None),
    ).order_by(FreightTemplate.id)).first()
    if tpl is None:
        print("[!!] 副本里没有一条带路线的价目，矩阵搭不起来")
        return 1
    route = db.get(ShipperAddress, tpl.route_id)
    route_addr = (route.detail_address or "").strip() if route else ""
    to_place = (tpl.to_place or "").strip()
    anchor = to_place or route_addr
    if not anchor:
        print("[!!] 这条价目既没有 to_place 也没有线路终点，锚不出「路线对得上」那一支")
        return 1

    order = db.scalars(select(Order).where(Order.deleted_at.is_(None)).order_by(Order.id)).first()
    driver = db.scalars(select(User).where(User.role == "DRIVER").order_by(User.id)).first()
    if driver is None:
        driver = db.scalars(select(User).order_by(User.id)).first()
    if order is None or driver is None:
        print("[!!] 副本里没有可用的订单或司机")
        return 1

    rule = db.scalars(select(DriverBillingRule).where(
        DriverBillingRule.is_deleted.is_(False)).order_by(DriverBillingRule.id)).first()
    if rule is None:
        rule = DriverBillingRule(name="演练用规则（R4-25）")
        db.add(rule)
        db.commit()
        print("   （副本里一份规则都没有，建了一份演练用的）")

    print("   锚点：价目 #" + str(tpl.id) + "「" + (tpl.name or "") + "」fee=" + str(tpl.fee)
          + " / 线路地址=" + (route_addr or "（无）") + " / to_place=" + (to_place or "（无）"))
    print("        订单 #" + str(order.id) + " " + str(order.order_no)
          + " / 司机 #" + str(driver.id) + " / 规则 #" + str(rule.id) + "「" + (rule.name or "") + "」")

    set_order(db, order.id, address=anchor)
    q(db, "UPDATE orders SET driver_id=:d WHERE id=:i", d=driver.id, i=order.id)
    db.commit()
    db.refresh(order)

    # ================= B7：装配根没接 =================
    print("== B7 装配根没接解析器（脚本里只 import 了这个模块）==")
    register_pricing_resolver(None)
    got = contract_quote(db, order, driver_id=driver.id)
    check("B7 原因码", got.reason, "no_resolver")
    check("B7 没算出数", got.fee, None)

    register_pricing_resolver(resolve_v2)

    # ================= B1 / B2：没配好 =================
    print("== B1 司机根本没挂规则 ==")
    set_driver_rule(db, driver.id, None)
    got = contract_quote(db, order, driver_id=driver.id)
    check("B1 原因码", got.reason, "no_candidates")
    has("B1 说清了是这一种", got.detail, "还没挂计费规则")

    print("== B2 挂了规则但一条价目都没勾 ==")
    set_driver_rule(db, driver.id, rule.id)
    set_rule_templates(db, rule.id, [])
    got = contract_quote(db, order, driver_id=driver.id)
    check("B2 原因码", got.reason, "no_candidates")
    has("B2 与 B1 是**两句不同的话**", got.detail, "还没勾价目")

    # ================= B3：配对了 =================
    print("== B3 配对（路线 + 司机都刚好的那一条）==")
    set_rule_templates(db, rule.id, [int(tpl.id)])
    set_order(db, order.id, touch_category=True, category_id=None)
    db.refresh(order)
    got = contract_quote(db, order, driver_id=driver.id)
    check("B3 原因码", got.reason, "ok")
    check("B3 金额 = 那条价目自己写的数", got.fee,
          str(Decimal(str(tpl.fee)).quantize(Decimal("0.01"))))
    check("B3 凭据认得出是哪一条价目", (got.rule or {}).get("template_id"), int(tpl.id))

    # ================= B4：路线对不上 =================
    print("== B4 勾了价目，但这一单的地址不在那条线路上 ==")
    set_order(db, order.id, address="演练用——这条地址哪条线路都不属于")
    db.refresh(order)
    got = contract_quote(db, order, driver_id=driver.id)
    check("B4 原因码", got.reason, "no_match")
    check("B4 没算出数", got.fee, None)
    has("B4 说清了修法", got.detail, "这条路线")

    # ================= B8：连地址都没有 =================
    print("== B8 这一单没有送货地址 ==")
    set_order(db, order.id, address="")
    db.refresh(order)
    got = contract_quote(db, order, driver_id=driver.id)
    check("B8 原因码", got.reason, "no_match")
    has("B8 与 B4 是**两句不同的话**", got.detail, "没有送货地址")

    # ================= B5：分类对不上 =================
    print("== B5 路线对上了，但分类不是这一类的 ==")
    set_order(db, order.id, address=anchor)
    db.refresh(order)
    q(db, "DELETE FROM freight_template_categories WHERE template_id=:t", t=int(tpl.id))
    db.commit()
    # 生产副本里 freight_categories 实测是 **0 行** —— 所以这里**建两条演练用的分类**，
    # 演的是真正那一支（价目挂了甲类、单子却是乙类），而不是退而求其次演"单子没分类"。
    def ensure_category(tag: str) -> int:
        got_id = one(db, "SELECT id FROM freight_categories WHERE name=:n", n=tag)
        if got_id:
            return int(got_id)
        q(db, "INSERT INTO freight_categories (name, sort_order, created_at, updated_at) "
              "VALUES (:n, 0, NOW(), NOW())", n=tag)
        db.commit()
        return int(one(db, "SELECT id FROM freight_categories WHERE name=:n", n=tag))

    cat_on = ensure_category("演练用分类甲（R4-25）")
    cat_off = ensure_category("演练用分类乙（R4-25）")
    q(db, "INSERT INTO freight_template_categories (template_id, category_id, created_at, updated_at) "
          "VALUES (:t, :c, NOW(), NOW())", t=int(tpl.id), c=cat_on)
    db.commit()
    set_order(db, order.id, touch_category=True, category_id=cat_off)
    got = contract_quote(db, order, driver_id=driver.id)
    check("B5 原因码", got.reason, "no_match")
    has("B5 说清了修法", got.detail, "都不是这一类")

    print("== B5b 价目挂了分类、单子**没有**分类（这一维不参与筛选）==")
    set_order(db, order.id, touch_category=True, category_id=None)
    got = contract_quote(db, order, driver_id=driver.id)
    check("B5b 照样算得出来（⛔ 不许因为没分类就报「没有价目」）", got.reason, "ok")

    # ================= B6：同一档两条 =================
    print("== B6 同一路线同一档有两条价目（⛔ 不许猜）==")
    q(db, "DELETE FROM freight_template_categories WHERE template_id=:t", t=int(tpl.id))
    db.commit()
    set_order(db, order.id, touch_category=True, category_id=None)
    db.refresh(order)

    twin = db.scalars(select(FreightTemplate).where(
        FreightTemplate.id != tpl.id, FreightTemplate.is_deleted.is_(False),
        FreightTemplate.to_place == (tpl.to_place or ""),
    ).order_by(FreightTemplate.id)).first()
    if twin is None:
        twin = FreightTemplate(
            name="演练用第二档（R4-25）", route_id=tpl.route_id,
            from_place=tpl.from_place or "", to_place=tpl.to_place or "",
            price_name="演练第二档", fee=Decimal("99.00"),
        )
        db.add(twin)
        db.commit()
        print("   （副本里没有第二条同线路价目，建了一条演练用的 #" + str(twin.id) + "）")
    set_rule_templates(db, rule.id, [int(tpl.id), int(twin.id)])
    got = contract_quote(db, order, driver_id=driver.id)
    check("B6 原因码（⛔ 不是随便挑一条）", got.reason, "ambiguous")
    check("B6 没算出数", got.fee, None)
    has("B6 把候选清单列出来让人自己挑", got.detail, "请自己挑一条")

    # ================= B9：扩展自己抛错 =================
    print("== B9 扩展在算这一单时抛了别的错 ==")
    register_pricing_resolver(
        lambda ctx: (_ for _ in ()).throw(RuntimeError("演练：故意让扩展抛错")))
    got = contract_quote(db, order, driver_id=driver.id)
    check("B9 原因码", got.reason, "error")
    has("B9 带上了异常类型（供排查）", got.detail, "RuntimeError")
    register_pricing_resolver(resolve_v2)

    # ================= N：组装点本身 =================
    print("== N1 走契约 + 界面给的数 == 契约算的数 ==")
    # ⚠️ 顺序有讲究：先把规则与那一档的关联解开，否则删价目会撞外键（第一版就撞了）。
    set_rule_templates(db, rule.id, [int(tpl.id)])
    q(db, "DELETE FROM freight_templates WHERE id=:t AND name LIKE :p",
      t=int(twin.id), p="演练用第二档%")
    db.commit()
    db.expire_all()
    fee = str(Decimal(str(tpl.fee)).quantize(Decimal("0.01")))
    d1 = decide(db, order, driver_id=driver.id, claimed_fee=fee)
    check("N1 kind", d1.kind, KIND_CONTRACT)
    check("N1 agreed", d1.agreed, True)
    check("N1 override（一致就不该标成「人改过」）", d1.override, False)

    print("== N2 走契约 + 派单员改过价 ==")
    d2 = decide(db, order, driver_id=driver.id, claimed_fee=str(Decimal(fee) + Decimal("10")))
    check("N2 kind", d2.kind, KIND_CONTRACT)
    check("N2 agreed", d2.agreed, False)
    check("N2 override", d2.override, True)
    has("N2 两个数都留下（契约那个）", d2.note, fee)
    has("N2 两个数都留下（人那个）", d2.note, str(Decimal(fee) + Decimal("10")))
    has("N2 说清了以谁为准", d2.note, "以人为准")

    print("== N3 canary=0 时：⛔ 一个扩展都不许调 ==")
    calls = []

    def spy(ctx):
        calls.append(ctx.order_id)
        return resolve_v2(ctx)

    register_pricing_resolver(spy)
    orig = pr.canary_percent
    pr.canary_percent = lambda: 0
    try:
        d3 = decide(db, order, driver_id=driver.id, claimed_fee=fee)
        check("N3 kind（0% 时全走旧路）", d3.kind, KIND_LEGACY)
        check("N3 扩展被调用的次数（⛔ 必须是 0）", len(calls), 0)
        check("N3 旧路也照样记下「是哪条价目」", (d3.rule or {}).get("template_id"), int(tpl.id))

        print("== N4 canary=100 时：扩展被调用，且同一单永远同一策略 ==")
        pr.canary_percent = lambda: 100
        calls.clear()
        decide(db, order, driver_id=driver.id, claimed_fee=fee)
        check("N4 扩展被调用的次数", len(calls), 1)
        check("N4 policy_for 是纯函数（同一单问三次同一个答案）",
              len({policy_for(order.id), policy_for(order.id), policy_for(order.id)}), 1)
        check("N4 100% 时任意单都走契约", policy_for(1) == KIND_CONTRACT and policy_for(99) == KIND_CONTRACT, True)
    finally:
        pr.canary_percent = orig
        register_pricing_resolver(resolve_v2)

    print("== N5 这次调用根本没有金额（例如只补分类）==")
    d5 = decide(db, order, driver_id=driver.id, claimed_fee=None)
    check("N5 没金额时不产生「金额来自哪里」这个事实（如实记旧路）", d5.kind, KIND_LEGACY)

    # ================= N6：全程不写库 =================
    print("== N6 整轮矩阵没有写库 ==")
    db.expire_all()
    orders_after = one(db, "SELECT COUNT(*) FROM orders")
    snaps_after = one(db, "SELECT COUNT(*) FROM orders WHERE freight_rule_snapshot IS NOT NULL")
    check("N6 订单行数不变", orders_after, orders_before)
    check("N6 带来源凭据的订单数不变（⛔ 演练不产生任何定价决定）", snaps_after, snaps_before)

    bad = [n for ok, n in RESULTS if not ok]
    print("")
    print("=" * 60)
    print("矩阵跑完：" + str(len(RESULTS)) + " 条断言，通过 " + str(len(RESULTS) - len(bad))
          + "，失败 " + str(len(bad)))
    for n in bad:
        print("   [!!] " + n)
    db.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
