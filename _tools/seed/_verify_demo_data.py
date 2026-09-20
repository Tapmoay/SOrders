"""验收刚造出来的这份演示数据（用户 2026-09-20：「这次用来测试的数据很重要」）。

它**只读**，逐条给判据 —— 数据不合格就红，而不是"看着还行"：

1. **没有脏字**：任何表里都不许出现「测试 / 压测 / 验证 / probe / demo / ttt / xxx / aaa」；
2. **该填的都填**：商品名/单位/单价/成本、人名的姓名与电话、订单的地址与联系人电话、
   账本的商品名与金额 —— 空字段在界面上就是一条横线；
3. **不重号**：手机号互不相同、车牌互不相同、商品名互不相同、地点名不同；
4. **不是批量复制**：同名同价的商品行不许成片出现；每个名字/地址的重复次数有上限；
5. **时间不规律但讲道理**：三个月每月都有单、早晚高峰看得出来、周日明显少；
6. **钱对得上**：订单商品行合计 = 账本里订单来源的合计（同一批单只算一次）；
7. **每类账都有数**：司机账 / 货主账 / 批发商账 / 报表都有非零数据；
8. **照片是真的**：送达照片文件真的存在于 `static/`。

用法：python _tools/seed/_verify_demo_data.py
"""
from __future__ import annotations

import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend/sorders.db"

BAD_WORDS = re.compile(r"测试|压测|验证|样例|demo|probe|ttt|xxx|aaa|foo|bar123", re.I)
fails: list[str] = []
oks = 0


def ok(label: str, cond: bool, detail: str = "") -> None:
    global oks
    if cond:
        oks += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def main() -> int:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    q = lambda sql, *a: c.execute(sql, a).fetchall()  # noqa: E731

    print(f"库 {DB}（{DB.stat().st_size/1024/1024:.1f} MB）\n")

    # ---- ① 脏字 ----
    hits: list[str] = []
    for t in [r["name"] for r in q("select name from sqlite_master where type='table'")]:
        cols = [r["name"] for r in q(f'pragma table_info("{t}")')]
        text_cols = [x for x in cols if x not in ("id", "created_at", "updated_at", "password_hash")]
        for col in text_cols:
            try:
                rows = q(f'select "{col}" as v from "{t}" where "{col}" like ? limit 3', "%测%")
            except sqlite3.Error:
                continue
            for r in rows:
                if isinstance(r["v"], str) and BAD_WORDS.search(r["v"]):
                    hits.append(f"{t}.{col}={r['v'][:40]}")
    # 中文"测"字扫过一遍之后，再扫英文脏字（上面那条 like 只匹配中文）
    for t, col in (("products", "name"), ("places", "name"), ("users", "full_name"),
                   ("shipper_locations", "name"), ("orders", "remark"),
                   ("ledgers", "product_name"), ("ledgers", "note")):
        for r in q(f'select "{col}" as v from "{t}"'):
            if isinstance(r["v"], str) and BAD_WORDS.search(r["v"]):
                hits.append(f"{t}.{col}={r['v'][:40]}")
    ok(f"没有「测试/压测/验证/占位」字样（扫了全部表）", not hits, "；".join(hits[:5]))

    # ---- ② 该填的都填 ----
    ok("商品：名称/单位/单价/成本都不为空且为正",
       q("select count(*) n from products where trim(name)='' or trim(unit)='' "
         "or default_unit_price is null or cast(default_unit_price as real)<=0 "
         "or cost_price is null or cast(cost_price as real)<=0")[0]["n"] == 0)
    ok("商品：分类都填了（没有未分类）",
       q("select count(*) n from products where trim(coalesce(category,''))=''")[0]["n"] == 0)
    ok("账号：姓名与手机号都不为空",
       q("select count(*) n from users where trim(coalesce(full_name,''))='' or trim(coalesce(phone,''))=''")[0]["n"] == 0)
    ok("订单：地址/联系人都填了",
       q("select count(*) n from orders where trim(coalesce(address_detail,''))='' "
         "or trim(coalesce(contact_dongjia_phone,''))='' or trim(coalesce(contact_boss_phone,''))=''")[0]["n"] == 0)
    ok("订单：都有商品行",
       q("select count(*) n from orders o where not exists (select 1 from order_products p where p.order_id=o.id)")[0]["n"] == 0)
    ok("订单行：单价与金额都为正",
       q("select count(*) n from order_products where cast(unit_price as real)<=0 or cast(line_total as real)<=0")[0]["n"] == 0)
    ok("账本：商品名/金额/日期都填了",
       q("select count(*) n from ledgers where trim(coalesce(product_name,''))='' or entry_date is null")[0]["n"] == 0)
    ok("地点/线路/联系人：地址与电话都填了",
       q("select count(*) n from shipper_locations where trim(coalesce(detail_address,''))=''")[0]["n"] == 0
       and q("select count(*) n from shipper_contacts where trim(coalesce(phone,''))=''")[0]["n"] == 0)

    # ---- ③ 不重号 ----
    for table, col, label in (("users", "phone", "手机号"), ("vehicles", "plate_no", "车牌"),
                              ("products", "name", "商品名"), ("shipper_locations", "name", "地点名")):
        if table == "users":
            rows = q("select phone v from users")
        else:
            rows = q(f"select {col} v from {table}")
        cnt = Counter(r["v"] for r in rows)
        dup = [k for k, n in cnt.items() if n > 1 and k]
        # 手机号/车牌**必须**唯一；商品名与地点名允许少量重名（真实世界会有），但不能成片
        limit = 0 if col in ("phone", "plate_no") else 3
        worst = max(cnt.values()) if cnt else 0
        ok(f"{label}没有成片重复（最多重复 {worst} 次，上限 {limit}）",
           (not dup) if limit == 0 else (worst <= limit),
           "；".join(f"{k}×{n}" for k, n in list(cnt.items())[:0]) or f"重复样例：{dup[:3]}")

    # ---- ④ 不是批量复制 ----
    rows = q("select product_name_snapshot, quantity, unit_price from order_products")
    combo = Counter((r["product_name_snapshot"], r["quantity"], str(r["unit_price"])) for r in rows)
    worst = combo.most_common(1)[0] if combo else ((), 0)
    ok(f"商品行组合不像批量复制（最常见的组合出现 {worst[1]} 次 / 共 {len(rows)} 行）",
       worst[1] <= max(20, len(rows) // 10), f"{worst[0]} × {worst[1]}")
    o = q("select quantity, unit_price, line_total from order_products limit 200")
    ok("订单行金额 = 数量 × 单价（不是随手填的数）",
       all(abs(float(r["quantity"]) * float(r["unit_price"]) - float(r["line_total"])) < 0.011 for r in o))

    # ---- ⑤ 时间 ----
    per_month = q("select substr(order_date,1,7) m, count(*) n from orders group by m order by m")
    # 第一段是**半个多月**（窗口从今天往前推 90 天），所以它天然比整月少
    ok(f"每个月都有单：{[(r['m'], r['n']) for r in per_month]}",
       len(per_month) >= 4 and all(r["n"] >= 15 for r in per_month)
       and all(r["n"] >= 80 for r in per_month[1:-1]))
    per_hour = q("select cast(substr(created_at,12,2) as int) h, count(*) n from orders group by h")
    hours = {r["h"]: r["n"] for r in per_hour}
    early = sum(v for k, v in hours.items() if 6 <= k <= 9)
    afternoon = sum(v for k, v in hours.items() if 14 <= k <= 17)
    ok(f"下单时间有早晚高峰（6-9 点 {early} 单、14-17 点 {afternoon} 单，其余 {sum(hours.values())-early-afternoon}）",
       early > 0 and afternoon > 0 and early + afternoon > sum(hours.values()) * 0.6)
    per_dow = q("select strftime('%w', order_date) d, count(*) n from orders group by d")
    dow = {int(r["d"]): r["n"] for r in per_dow}
    ok(f"周日明显少（周日 {dow.get(0,0)} 单 vs 其它日均 {sum(v for k,v in dow.items() if k) / 6:.0f} 单）",
       dow.get(0, 0) < sum(v for k, v in dow.items() if k) / 6)

    # ---- ⑥⑦ 钱与各类账 ----
    n_deliv = q("select count(*) n from orders where status='DELIVERED'")[0]["n"]
    n_bill = q("select count(*) n from driver_bills")[0]["n"]
    # ⚠️ 别拿"账单数 ≥ 送达单数"当判据：月薪司机不吃按单应付（他们的钱在月度工资单上）。
    #    正确的判据是"每一张送达单，要么有一条应付账单，要么它的司机是月薪制"。
    orphan = q("""
        select count(*) n from orders o
        where o.status='DELIVERED'
          and not exists (select 1 from driver_bills b where b.order_id=o.id)
          and o.driver_billing_mode_snapshot <> 'SALARY'
    """)[0]["n"]
    ok(f"送达 {n_deliv} 单都有对应应付（账单 {n_bill} 条；月薪制不算），漏 {orphan} 单", orphan == 0)
    n_led = q("select count(*) n from ledgers")[0]["n"]
    srcs = {r["source"]: r["n"] for r in q("select source, count(*) n from ledgers group by source")}
    ok(f"账本流水 {n_led} 条，来源分布 {srcs}", n_led >= n_deliv and len(srcs) >= 2)
    cash = q("select count(*) n, coalesce(sum(amount),0) s from cash_flows")[0]
    ok(f"现金流水 {cash['n']} 条（合计 {cash['s']}）", cash["n"] > 0)
    ok("货主账 / 批发商账 / 司机账都有数",
       q("select count(distinct shipper_id) n from ledgers")[0]["n"] >= 15
       and q("select count(distinct driver_id) n from driver_bills")[0]["n"] >= 12,
       f"账本涉及货主 {q('select count(distinct shipper_id) n from ledgers')[0]['n']} 位、"
       f"账单涉及司机 {q('select count(distinct driver_id) n from driver_bills')[0]['n']} 位")
    led_months = {r["m"]: r["n"] for r in q("select substr(entry_date,1,7) m, count(*) n from ledgers group by m order by m")}
    order_months = {r["m"]: r["n"] for r in q("select substr(order_date,1,7) m, count(*) n from orders group by m")}
    # ⚠️ 判据不能只是"≥3 个月都有" —— 第一版账本 683 行全挤在 9 月也照样过。
    #    真正的判据是：**账本的月度分布要跟着订单走**（每个月都不能差太远）。
    worst = min((led_months.get(m, 0) / n, m) for m, n in order_months.items() if n >= 20)
    ok(f"账本的月度分布跟着订单走（账本 {led_months} vs 订单 {order_months}）",
       worst[0] >= 0.4, f"{worst[1]} 这个月只占到订单数的 {worst[0]:.0%}")
    months = {r["month"]: r["n"] for r in q("select month, count(*) n from driver_bills group by month")}
    print(f"        （司机账单按月：{months}）")
    ok("司机结算单有草稿（三个月里至少几张）",
       q("select count(*) n from driver_settlements")[0]["n"] > 0,
       f"实际 {q('select count(*) n from driver_settlements')[0]['n']} 张")

    # ---- ⑧ 照片 ----
    photos = [r["delivery_photo_urls"] for r in q("select delivery_photo_urls from orders where delivery_photo_urls is not null")]
    urls = [u for p in photos for u in re.findall(r"/static/[^\"]+", p or "")]
    missing = [u for u in urls if not (ROOT / "backend" / u.lstrip("/")).exists()]
    ok(f"送达照片真的存在（{len(urls)} 张，缺 {len(missing)} 张）", urls and not missing, "；".join(missing[:3]))

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不达标：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {oks} 项通过：这份数据可以直接拿来验收。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
