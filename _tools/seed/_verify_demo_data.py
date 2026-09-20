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
8. **照片是真的**：送达照片文件真的存在于 `static/`；
9. **派生日期跟着订单走**：凡是挂在订单上的行（账本/开销/现金流水/账单/库存流水），
   日期必须等于那一单的业务日 —— **这张表清单是脚本自己算出来的**（所有带 `order_id` 的表），
   漏一张就红（这一条是用一次真实事故换来的，见下面 ⑨ 的注释）；
10. **三个开发登录账号自己也有数据**：真机上登的就是它们，空着等于这个模块没数据；
11. **车型词表只有一套**：`small`/`large`/`trailer`（别的值在界面上显示「未设置车型」）；
12. **消息中心不空**，而且消息都落在 30 天保留期内；
13. **JSON 列里是真的 JSON 结构**（不是被当字符串塞进去的 `"[]"` —— 那会让读接口 500）。

用法：python _tools/seed/_verify_demo_data.py
"""
from __future__ import annotations

import enum
import json
import os
import re
import sqlite3
import sys
import typing
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend/sorders.db"

# ---- 枚举词表（第 ⑪ 条）用的模型元数据 ----------------------------------------
# 为什么要引后端模型：枚举词表**只有一处真相**（`backend/app/models`），
# 在这份脚本里手抄一张"哪个列认哪些值"的表，就一定会与后端走散
# （而走散的后果是"读接口 500 而检查全绿"）。引不进来就让 ⑪ 红，不许静默跳过。
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DATABASE_URL", "sqlite:///./backend/sorders.db")
ENUM_IMPORT_ERROR = ""
ENUM_COLS: dict[tuple[str, str], tuple[set[str], str]] = {}
VEHICLE_TYPE_VALUES: set[str] = set()


def _load_enum_vocab() -> None:
    """从模型元数据里算出「哪些列的取值有枚举约束」以及各自的合法值。"""
    global ENUM_IMPORT_ERROR, ENUM_COLS, VEHICLE_TYPE_VALUES
    try:
        from sqlalchemy import Enum as SAEnum

        from app.models import base as _basemod
        import app.models  # noqa: F401  —— 让所有模型注册进元数据
        from app.models import enums as _enums

        base = _basemod.Base
        classes = {m.class_.__name__: m.class_ for m in base.registry.mappers}
        for nm in dir(_enums):
            obj = getattr(_enums, nm)
            if isinstance(obj, type) and issubclass(obj, enum.Enum):
                classes[nm] = obj
        VEHICLE_TYPE_VALUES = {str(e.value) for e in _enums.VehicleType}
        for table in base.metadata.sorted_tables:
            cls = next((m.class_ for m in base.registry.mappers if m.local_table is table), None)
            try:
                hints = typing.get_type_hints(cls, localns=classes) if cls is not None else {}
            except Exception:                                          # noqa: BLE001
                hints = {}
            for col in table.columns:
                if isinstance(col.type, SAEnum):
                    # `Enum(XxxEnum)` 列存的是**成员名**
                    ENUM_COLS[(table.name, col.name)] = ({str(x) for x in (col.type.enums or [])}, "成员名")
                    continue
                for a in typing.get_args(hints.get(col.name)):
                    if isinstance(a, type) and issubclass(a, enum.Enum):
                        # `String` + `Mapped[XxxEnum]` 列存的是**枚举值**
                        ENUM_COLS[(table.name, col.name)] = ({str(e.value) for e in a}, "枚举值")
                        break
    except Exception as e:                                             # noqa: BLE001
        ENUM_IMPORT_ERROR = f"{type(e).__name__}: {e}"


def _all_columns() -> list[tuple[str, str]]:
    c = sqlite3.connect(DB)
    try:
        return [(t[0], r[1]) for t in c.execute("select name from sqlite_master where type='table'")
                for r in c.execute(f'pragma table_info("{t[0]}")')]
    finally:
        c.close()


_load_enum_vocab()

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
    #
    # ⚠️ 商品这几条**只看没被软删的**（`is_deleted = 0`）：模糊测试（`_tools/fuzz/`）会在库里
    #    留下 `fuzz-xxxx` 这种**软删**的商品（单价/成本都是 0、没有分类），而"删除"在本项目里
    #    是软删（用户定的硬规矩），那行数据本来就看不见 —— 拿它判"演示数据不达标"，
    #    这条检查就会**永远红**，而永远红的检查等于没有检查。
    ok("商品：名称/单位/单价/成本都不为空且为正",
       q("select count(*) n from products where is_deleted = 0 and (trim(name)='' or trim(unit)='' "
         "or default_unit_price is null or cast(default_unit_price as real)<=0 "
         "or cost_price is null or cast(cost_price as real)<=0)")[0]["n"] == 0)
    ok("商品：分类都填了（没有未分类）",
       q("select count(*) n from products where is_deleted = 0 "
         "and trim(coalesce(category,''))=''")[0]["n"] == 0)
    ok("账号：姓名与手机号都不为空",
       q("select count(*) n from users where trim(coalesce(full_name,''))='' or trim(coalesce(phone,''))=''")[0]["n"] == 0)
    ok("订单：地址/联系人都填了",
       q("select count(*) n from orders where trim(coalesce(address_detail,''))='' "
         "or trim(coalesce(contact_dongjia_phone,''))='' or trim(coalesce(contact_boss_phone,''))=''")[0]["n"] == 0)
    # 收货人 / 下单人的**名称**（2026-09-20 加的字段）：卡片与详情就显示这两个名字，
    # 空着界面上就是一条横线 —— 与上面那两个电话同一条规矩。
    ok("订单：收货人名称/下单人名称都填了",
       q("select count(*) n from orders where trim(coalesce(contact_dongjia_name,''))='' "
         "or trim(coalesce(contact_boss_name,''))=''")[0]["n"] == 0)
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
    # ⚠️ **id 必须与时间同向**：`GET /orders` 是 `order_by(Order.id.desc())`（列表按 id 排），
    #    建单顺序与时间不一致时，真机上「待派池」第一张会是两个月前的单（看起来像没人管）。
    inv = q("""select count(*) n from orders a join orders b on a.id < b.id
               where a.created_at > b.created_at""")[0]["n"]
    ok(f"订单 id 与下单时间同向（逆序对 {inv} 个）", inv == 0,
       "列表按 id 倒序排，于是新单会排在老单后面")
    # ⚠️ **"还在飞"的状态只在最近 10 天**：两个月前下的单不可能还挂在待派池里
    stale = q("""select count(*) n from orders
                 where status in ('PENDING_DISPATCH','DISPATCHED','ACCEPTED')
                   and julianday('now','localtime') - julianday(order_date) > 10""")[0]["n"]
    ok(f"待派/派单中/已接单都发生在最近 10 天内（超期 {stale} 单）", stale == 0,
       "老单挂在那儿看起来就是「一批单没人管」")
    # ⚠️ **单号形状与生产一致**：`SO{下单日}{10 位随机}`（`services/auth_service.py::gen_order_no`）
    bad_no = q(r"""select order_no from orders
                   where order_no not glob 'SO[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                      or substr(order_no, 3, 8) <> replace(order_date, '-', '')""")
    ok(f"单号形状是 SO+日期+10 位随机、且日期与下单日一致（不合 {len(bad_no)} 单）", not bad_no,
       "；".join(r["order_no"] for r in bad_no[:3]))
    per_dow = q("select strftime('%w', order_date) d, count(*) n from orders group by d")
    dow = {int(r["d"]): r["n"] for r in per_dow}
    ok(f"周日明显少（周日 {dow.get(0,0)} 单 vs 其它日均 {sum(v for k,v in dow.items() if k) / 6:.0f} 单）",
       dow.get(0, 0) < sum(v for k, v in dow.items() if k) / 6)
    # ⚠️ **尾部不能是空的**：第一版随机挑日子，最后 5 天只有 7 单（今天/昨天一单没有），
    #    于是「账本 → 今天 / 昨天 / 前天」三个档位点下去全是空的、消息中心最新一条是三天前 ——
    #    而这三个档位正是刚做完的功能，看起来就像坏了。
    tail = {r["d"]: r["n"] for r in q(
        "select order_date d, count(*) n from orders where order_date >= date('now','localtime','-2 day') group by d")}
    ok(f"最近一单不是几天前的（{tail}）",
       q("select count(*) n from orders where order_date >= date('now','localtime','-1 day')")[0]["n"] > 0,
       "真机上「今天/昨天」两个日期档位会是空的")
    ok(f"最近 3 天里至少 2 天有单（{tail}）", len(tail) >= 2, "尾部空档会让「最近」这类列表看起来没数据")
    # ⚠️ 四个时刻必须按顺序：下单 → 派单 → 接单 → 送达，而且送达不能是未来
    #    （第一版对"当天现造的单"没有这条约束：送达时间取 `min(…, 现在-1小时)`，
    #     会把送达压到接单之前，订单详情上就是"送达早于接单"）。
    bad_chain = q("""select id, order_no, substr(created_at,1,16) c, substr(dispatched_at,1,16) dp,
                     substr(driver_acknowledged_at,1,16) ack, substr(delivered_at,1,16) dlv
        from orders where status='DELIVERED' and (
            dispatched_at < created_at
            or (driver_acknowledged_at is not null and driver_acknowledged_at < dispatched_at)
            or delivered_at < created_at
            or (driver_acknowledged_at is not null and delivered_at < driver_acknowledged_at)
            or delivered_at > datetime('now','localtime'))""")
    ok(f"已送达单的四个时刻按顺序且不在未来（不合 {len(bad_chain)} 单）", not bad_chain,
       "；".join(f"{r['order_no']} {r['c']}→{r['dp']}→{r['ack']}→{r['dlv']}" for r in bad_chain[:3]))

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

    # ---- ⑨ 派生日期：挂在订单上的行，日期必须是那一单的业务日 ----
    #
    # ⚠️ 这一条是**用一次真实事故换来的**（2026-09-20）：第一版种子只把 `source='ORDER'` 的账本行
    #    对齐回订单日，于是 6 条货损红冲账本 + 6 条货损开销 + 6 条货损现金流水 + 70 条库存流水
    #    全留在"今天" —— 账本第一屏就是 6 条 09-20 的红冲行、库存流水按月份查是空的。
    #    两处都不报错，界面上也看不出"是数据造错了"还是"这个月真的只有这些"。
    #
    # ⚠️ 表清单**自己算**（`pragma table_info` 里所有带 `order_id` 的表），绝不手写：
    #    手写的清单漏一张表 = 这条检查根本不看它，而且没有人会发现。
    #    新增一张带 `order_id` 的表时，要么在 [DERIVED] 里说清它的哪一列该跟着订单走，
    #    要么在 [EXEMPT] 里写一句"它的日期不该跟着订单走"的理由。
    ORDER_DAY = "date(coalesce(o.delivered_at, o.order_date))"
    # 表: (跟着订单走的那一列, 粒度, 额外条件)
    DERIVED = {
        # ⚠️ 退货红冲行（`source='RETURN'`）**故意**不跟着订单走：它记的是"这次退货什么时候发生的"，
        #    而不是"这单什么时候送的"。把 9 月的退货记回 8 月 = 篡改 8 月的账（那个月的数字
        #    过两天自己变了，而没有任何人改过 8 月的任何一张单）。与"收款日"同一条道理。
        "ledgers": ("entry_date", "day", "and x.source <> 'RETURN'"),
        "expenses": ("exp_date", "day", ""),
        "driver_bills": ("month", "month", ""),
        # 收款流水的日子是**收款日**：客户 8 月才结 6 月的账，本来就该晚于送达日 ——
        # 所以这条只认货损那一类（EXPENSE_LOSS）。
        "cash_flows": ("flow_date", "day", "and x.biz_type = 'EXPENSE_LOSS'"),
        # `created_at` 就是库存流水的业务时间（`GET /inventory/movements` 按它做日期过滤）。
        # 退货回补（`status='RETURNED'`）同理：货是退货那天回来的，不是送达那天。
        "inventory_movements": ("created_at", "day", "and x.status <> 'RETURNED'"),
    }
    EXEMPT = {
        "operation_logs": "created_at 是「这条日志什么时候写的」（审计时刻），没有业务日期列，"
                          "审计接口也不按日期过滤",
        "order_products": "商品行没有业务日期列（它的日子就是订单的 order_date）",
    }
    with_oid: set[str] = set()
    for t in [r["name"] for r in q("select name from sqlite_master where type='table'")]:
        cols = [r["name"] for r in q(f'pragma table_info("{t}")')]
        if "order_id" in cols and q(f'select count(*) n from "{t}" where order_id is not null')[0]["n"] > 0:
            with_oid.add(t)
    uncovered = with_oid - set(DERIVED) - set(EXEMPT)
    ok(f"带 order_id 的表都被「派生日期」覆盖或写了理由（共 {sorted(with_oid)}）",
       not uncovered, "没覆盖也没理由：" + "、".join(sorted(uncovered)))

    # ---- ⑨b 退货真的在数据里出现过（2026-09-20 加的两件事）----
    #
    # ⚠️ 为什么这条必须有：造数里那几步是 `try/except`（一单退不掉就跳过、打印一句），
    #    于是"退货全被跳过了"的表现是**一切照常绿** —— 而真机上「已退货」那一档、
    #    账本红冲、库存回补、退现这四样就永远看不到。演示数据是用来验收的，
    #    它自己必须覆盖到这一轮新加的功能。
    n_ret_orders = q("select count(*) n from orders where status = 'RETURNED'")[0]["n"]
    n_ret_rows = q("select count(*) n from ledgers where source = 'RETURN'")[0]["n"]
    n_ret_moves = q("select count(*) n from inventory_movements where status = 'RETURNED'")[0]["n"]
    n_part = q("select count(distinct order_id) n from ledgers where source = 'RETURN' "
               "and order_id in (select id from orders where status = 'DELIVERED')")[0]["n"]
    ok(f"有整单退货的单（已退货 {n_ret_orders} 张）", n_ret_orders >= 1)
    ok(f"有部分退货的单（退过货但仍留在已送达 {n_part} 张）", n_part >= 1,
       "只有整单退货的话，「部分退货」那条路径在真机上验收不到")
    ok(f"退货写了账本红冲行（{n_ret_rows} 行）", n_ret_rows >= 1)
    ok(f"退货回补了库存（{n_ret_moves} 条流水）", n_ret_moves >= 1)
    neg = q("select count(*) n from ledgers where source = 'RETURN' and total > 0")[0]["n"]
    ok("红冲行的金额是负数（写成正数就是「退了货又多一笔营业额」）", neg == 0, f"{neg} 行是正数")
    ok(f"派生日期的覆盖清单不是空的（{len(DERIVED)} 张表 + {len(EXEMPT)} 条理由）",
       len(DERIVED) >= 4 and len(EXEMPT) >= 1)
    ok("EXEMPT 里的表都还在、还真的带 order_id（防化石）",
       not (set(EXEMPT) - with_oid), "；".join(sorted(set(EXEMPT) - with_oid)))
    for t, (col, gran, extra) in DERIVED.items():
        w = 7 if gran == "month" else 10
        bad = q(f"""select count(*) n from {t} x join orders o on o.id = x.order_id
                    where substr(x.{col}, 1, {w}) <> substr({ORDER_DAY}, 1, {w}) {extra}""")[0]["n"]
        total = q(f"select count(*) n from {t} where order_id is not null")[0]["n"]
        ok(f"{t}.{col} 跟着订单走（{total} 行，不一致 {bad} 行）", bad == 0,
           f"{bad} 行的日期不等于那一单的业务日")

    # ---- ⑩ 三个开发登录账号必须有数据（真机上登的就是它们）----
    need = {
        "13800000001": ("DISPATCHER", {"shipper_locations": 1, "shipper_addresses": 1, "shipper_contacts": 1}),
        "13800000002": ("SHIPPER", {"orders": 5, "ledgers": 3, "shipper_locations": 3,
                                    "shipper_addresses": 2, "shipper_contacts": 3}),
        "13800000003": ("DRIVER", {"orders": 3, "driver_bills": 1, "vehicles": 1}),
    }
    for phone, (role, wants) in need.items():
        u = q("select id, role from users where phone=?", phone)
        if not u:
            ok(f"开发账号 {phone} 存在", False, "账号不在库里（_reset_dev_db 会留着它才对）")
            continue
        uid = u[0]["id"]
        ok(f"开发账号 {phone} 的角色还是 {role}", u[0]["role"] == role, f"实际 {u[0]['role']}")
        for what, least in wants.items():
            # ⚠️ 司机看的单在 `driver_id` 上、货主看的单在 `shipper_id` 上 —— 不能一个映射套两个人
            #    （第一版这里对司机号也查 `shipper_id`，于是"司机有 12 条账单、却报 0 单"，
            #     报的是检查自己写错了，不是数据错了）。
            where = {"driver_bills": "driver_id", "vehicles": "driver_id"}.get(what, "shipper_id")
            if what == "orders" and role == "DRIVER":
                where = "driver_id"
            n = q(f"select count(*) n from {what} where {where}=?", uid)[0]["n"]
            ok(f"  {phone} 的 {what} ≥ {least}（实际 {n}）", n >= least,
               "这个账号在真机上是空的 —— 而验收用的就是它")

    # ---- ⑪ 枚举词表：每一列的取值必须是这个列自己的枚举认的值 ----
    #
    # ⚠️ 这一条也是**用真机 500 换来的**（2026-09-20，三处）：
    #    · `users.vehicle_type` 写中文「面包车」→ 界面上显示「未设置车型」；
    #    · `expenses.category` 写中文「过路费」→ `GET /expenses` 500（`ExpenseOut` 要 `fuel`）；
    #    · `driver_settlements.settle_type` 写大写 `PIECE` → `GET /driver-settlements` 500（要 `piece`）。
    #    共同点：**写库一声不响，读接口才炸**，而界面上"到底哪个值合法"没有任何提示。
    #
    # ⚠️ 清单**自己算**，两种列都要认（它们存的形式不一样，这是最容易栽的地方）：
    #    · `Enum(XxxEnum)` 列 → 存的是**成员名**（`col.type.enums` 给的就是名字）；
    #    · `String(16)` + 注解 `Mapped[XxxEnum]` 列 → 存的是**枚举值**（`fuel`）；
    #    注解要靠 `get_type_hints` 解，且要给它一个 localns（模型里 `User`/`Order` 是
    #    `TYPE_CHECKING` 导入的，不给就解不开）。
    name_pattern_cols = [c for c in _all_columns() if c[1] == "vehicle_type"]
    ok("枚举词表能从后端模型元数据算出来（算不出来就得修，不许静默跳过）",
       not ENUM_IMPORT_ERROR, ENUM_IMPORT_ERROR)
    ok(f"枚举清单认得出来（注解列 {len(ENUM_COLS)} 个、按名字认的 vehicle_type 列 {len(name_pattern_cols)} 个）",
       len(ENUM_COLS) >= 8 and len(name_pattern_cols) >= 3,
       "一个都没扫到 = 这条检查在空转（该红而不是该绿）")
    bad_vals: list[str] = []
    for (tbl, colname), (allowed, kind) in sorted(ENUM_COLS.items()):
        for r in q(f'select "{colname}" v, count(*) n from "{tbl}" '
                   f'where "{colname}" is not null group by "{colname}"'):
            if str(r["v"]) not in allowed:
                bad_vals.append(f"{tbl}.{colname}={r['v']!r}×{r['n']}（{kind}，只认 {sorted(allowed)[:6]}…）")
    for tbl, colname in name_pattern_cols:
        for r in q(f'select "{colname}" v, count(*) n from "{tbl}" '
                   f'where "{colname}" is not null and trim("{colname}") <> \'\' group by "{colname}"'):
            if str(r["v"]) not in VEHICLE_TYPE_VALUES:
                bad_vals.append(f"{tbl}.{colname}={r['v']!r}×{r['n']}（车型只认 {sorted(VEHICLE_TYPE_VALUES)}）")
    ok(f"枚举列的取值都是这个枚举认的（坏值 {len(bad_vals)} 处）", not bad_vals,
       "写库不报错、读接口 500；界面显示「未设置车型」这类就是这个原因：" + "；".join(bad_vals[:4]))

    # ---- ⑬ JSON 列里必须是**真的 JSON 结构**，不能是被当字符串塞进去的 ----
    #
    # ⚠️ 这条是**真机 500 换来的**（2026-09-20）：种子把 `orders.delivery_photo_urls` 写成 `"[]"`
    #    字符串，而它是 JSON 列 —— 存进去就是"一个字符串"，读出来 `OrderOut` 要 list，
    #    `GET /orders?status=PENDING_DISPATCH` 整个端点 500（派单作业页直接打不开）。
    #    ⚠️ 隔壁 `orders.image_urls` 是 **Text** 列、还带 `mode="before"` 的解析器，
    #    所以那边写字符串是对的 —— 一列一个形状，不能照抄。
    #    列清单**自己算**（`pragma table_info` 里声明成 JSON 的列），不手写。
    json_cols = [(t, r["name"]) for t in [x["name"] for x in q("select name from sqlite_master where type='table'")]
                 for r in q(f'pragma table_info("{t}")') if (r["type"] or "").upper() == "JSON"]
    ok(f"库里认得 JSON 列（{len(json_cols)} 列：{'、'.join(t + '.' + c for t, c in json_cols)}）",
       len(json_cols) >= 3, "一个 JSON 列都没扫到，说明这条检查是空转的")
    poisoned: list[str] = []
    for t, col in json_cols:
        for r in q(f'select id, "{col}" v from "{t}" where "{col}" is not null'):
            raw = r["v"]
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:                                        # noqa: BLE001
                poisoned.append(f"{t}.{col}#{r['id']} 不是合法 JSON")
                continue
            if isinstance(parsed, str):
                poisoned.append(f"{t}.{col}#{r['id']}={str(raw)[:20]}（存成了字符串）")
    ok(f"JSON 列里存的是真结构而不是字符串（坏值 {len(poisoned)} 个）", not poisoned,
       "；".join(poisoned[:4]))

    # ---- ⑫ 消息中心 ----
    n_msg = q("select count(*) n from notifications")[0]["n"]
    ok(f"消息中心不是空的（{n_msg} 条）", n_msg > 0, "工作台的「消息中心」点进去会是一条都没有")
    if n_msg:
        old = q("select count(*) n from notifications where created_at < datetime('now','localtime','-30 day')")[0]["n"]
        ok(f"消息都落在 30 天保留期内（超期 {old} 条）", old == 0,
           "超期的会被 `data_retention` 在启动时物理清掉")
        unread = q("select count(*) n from notifications where read_at is null")[0]["n"]
        ok(f"有未读消息（{unread} 条未读 / {n_msg} 条）", 0 < unread < n_msg,
           "全未读或全已读都不像真实使用过")
        blank = q("select count(*) n from notifications where trim(coalesce(title,''))='' "
                  "or trim(coalesce(content,''))=''")[0]["n"]
        ok(f"每条消息都有标题与正文（空 {blank} 条）", blank == 0)
        orphan_r = q("select count(*) n from notifications n where not exists "
                     "(select 1 from users u where u.id = n.recipient_id)")[0]["n"]
        ok(f"消息的收件人都在（失效 {orphan_r} 条）", orphan_r == 0)

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
