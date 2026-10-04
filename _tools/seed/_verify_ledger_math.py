# -*- coding: utf-8 -*-
"""报表中心「独立重算对账」探针：**绕开报表服务**，直接从原始行重算，与**真接口**逐项比。

为什么要有这个脚本（GOV-0005）
------------------------------
用户 2026-10-05：「伪造一份真实的数据…看是否真的能表达整个公司的经营状态是怎样的，
甚至可以看看有没有出现账算错的问题」。造数脚本把开发库补成一份可对账的账本之后，
需要一个**不信任报表服务**的尺子：同一条口径用另一条路算一遍，两边对不上就是算错了。

三条规矩
--------
1. **只用 SQLite 原始表 + HTTP 接口**，不 import 任何 app.services（否则就是拿被测对象
   自己给自己打分）。日期换算（东八区业务日）、加权平均进货价、应收/已收/欠款、
   折旧、账龄分档、额度判定都在这里**重新实现一遍**（按口径说明书，不是按实现抄）。
2. 差值分三类，混在一起看等于没看：
   - **OK**：两边相等（容差 1 分，金额列）；
   - **口径**：两边本来就不该相等，差值可解释（例：司机账单 vs 逐单应付、现金流水 vs 已收）；
   - **错**：同一件事两个数（真缺陷，另立 BUG）。脚本末尾单独列「算错清单」。
3. 退 0 = 没有第三类；退 1 = 有。CI 里可以直接用退出码。

用法（仓库根目录）
------------------
    python _tools/seed/_verify_ledger_math.py
    python _tools/seed/_verify_ledger_math.py --window prev
    python _tools/seed/_verify_ledger_math.py --base http://127.0.0.1:8000 --db backend/sorders.db
    python _tools/seed/_verify_ledger_math.py --json out.json

配套：造数脚本 backend/scripts/seed_ops_gap.py（先造数，再跑这个对账）。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BUSINESS_TZ = timezone(timedelta(hours=8))
D = Decimal
CENT = D("0.01")


def dec(v) -> Decimal:
    """SQLite 的聚合返回值可能是 float / int / str，一律走 str 转，别让二进制噪声进来。"""
    if v is None:
        return D("0")
    return v if isinstance(v, Decimal) else D(str(v))


def q2(v) -> Decimal:
    return dec(v).quantize(CENT, rounding=ROUND_HALF_UP)


def q4(v) -> Decimal:
    return dec(v).quantize(D("0.0001"), rounding=ROUND_HALF_UP)


def business_today() -> date:
    """东八区的今天（与 app/core/business_time.py::business_today 同一口径）。"""
    return (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)).date()


def money(v) -> str:
    return "{:>13,}".format(q2(v))


class Db:
    """只读打开的 SQLite（开发库 backend/sorders.db）。"""

    def __init__(self, path: str) -> None:
        self.c = sqlite3.connect("file:" + path + "?mode=ro", uri=True)
        self.c.row_factory = sqlite3.Row

    def rows(self, sql: str, **p):
        return self.c.execute(sql, p).fetchall()

    def one(self, sql: str, **p):
        r = self.c.execute(sql, p).fetchone()
        return r

    def scalar(self, sql: str, default=D("0"), **p):
        r = self.c.execute(sql, p).fetchone()
        return dec(r[0]) if r and r[0] is not None else default

    def close(self) -> None:
        self.c.close()


class Api:
    """打真接口（报表中心用的就是这几个端点，一个不多一个不少）。"""

    def __init__(self, base: str, phone: str, password: str) -> None:
        self.base = base.rstrip("/")
        body = json.dumps({"phone": phone, "password": password}).encode()
        req = urllib.request.Request(self.base + "/api/v1/auth/login", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        st, raw = self._send(req)
        if st != 200:
            raise SystemExit("登录失败：HTTP " + str(st) + " " + raw[:200])
        self.token = json.loads(raw)["access_token"]

    def _send(self, req):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def get(self, path: str):
        req = urllib.request.Request(self.base + "/api/v1" + path)
        req.add_header("Authorization", "Bearer " + self.token)
        st, raw = self._send(req)
        if st != 200:
            raise SystemExit("接口 " + path + " 失败：HTTP " + str(st) + " " + raw[:200])
        return json.loads(raw)

    def report(self, name: str, a: date, b: date, extra: str = ""):
        p = ("/reports/" + name + "?mode=day&date=" + b.isoformat()
             + "&date_from=" + a.isoformat() + "&date_to=" + b.isoformat() + extra)
        return self.get(p)


class Report:
    """一根收集线：每条对账一行，最后统一打印。"""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.section = ""

    def head(self, title: str) -> None:
        self.section = title
        print("")
        print("| " + title)

    def ck(self, label: str, indep, api, tol=CENT, kind_note: str = "", quiet: bool = False) -> None:
        iv, av = dec(indep), dec(api)
        diff = iv - av
        ok = abs(diff) <= tol
        self.rows.append({"section": self.section, "label": label, "indep": iv, "api": av,
                          "diff": diff, "kind": "OK" if ok else ("口径" if kind_note else "错"),
                          "note": kind_note})
        if ok and quiet:
            return
        mark = "OK " if ok else ("~~ " if kind_note else "!! ")
        line = "|   " + mark + label + "：重算 " + money(iv) + " vs 接口 " + money(av)
        if not ok:
            line += "  差 " + money(diff)
        if kind_note:
            line += "  (" + kind_note + ")"
        print(line)

    def bad(self, label: str, note: str) -> None:
        """记一条「真错」：不是两边数值不等，而是口径自相矛盾（同一笔钱被算两次之类）。"""
        self.rows.append({"section": self.section, "label": label, "indep": D("0"), "api": D("0"),
                          "diff": D("0"), "kind": "错", "note": note})
        print("|   !! " + label + "：" + note)

    def errs(self) -> list[dict]:
        return [r for r in self.rows if r["kind"] == "错"]


def sql_days(col: str) -> str:
    """把 UTC naive 时间列换算成东八区业务日（与 BusinessDate 判据同一条 SQL 口径）。"""
    return "date(" + col + ", '+8 hours')"


# =====================================================================
# 重算：营业（营业额 / 已收 / 欠款 / 商品成本 / 货损）
# =====================================================================
def _order_money(db: Db, o: sqlite3.Row) -> tuple[Decimal, Decimal, Decimal]:
    """返回 (应收, 已收, 已退) —— 四个判据逐条对齐 order_money.money_map：

    - 总额 = Σ order_products.line_total（**不是** 单价 × 数量，历史折扣在 line_total 里）；
    - 退货红冲 = Σ ledgers.total（source='RETURN'，存的是负数）取负号；
    - 应收 = 总额 − 退货；已收 = 该单进账流水之和（一条都没有时按 paid 兜底成**总额**）；
    - 已退 = 该单 direction=out **且 biz_type=REFUND_CUSTOMER** 的流水（⛔ 不能把任何出账
      都算成退款：货损开销单也挂着 order_id，会把 24.51 从已收里扣掉）；
    - 欠款 = 应收 − 已收 + 已退。"""
    total = q2(db.scalar(
        "select coalesce(sum(line_total), 0) from order_products where order_id = :o", o=o["id"]))
    ret = q2(-db.scalar(
        "select coalesce(sum(total), 0) from ledgers where order_id = :o and source = 'RETURN'",
        o=o["id"]))
    rcv = q2(total - ret)
    got = db.scalar(
        "select coalesce(sum(amount), 0) from cash_flows"
        " where order_id = :o and is_deleted = 0 and lower(direction) = 'in'", o=o["id"])
    settled = q2(got if got > 0 else (total if o["paid"] else D("0")))
    refunded = q2(db.scalar(
        "select coalesce(sum(amount), 0) from cash_flows where order_id = :o and is_deleted = 0"
        " and lower(direction) = 'out' and biz_type = 'REFUND_CUSTOMER'", o=o["id"]))
    return rcv, settled, refunded


def delivered_orders(db: Db, a: date, b: date) -> list:
    return db.rows(
        "select id, order_no, shipper_id, temp_shipper_name, arrears_unit_id, arrears_unit_name,"
        " payment_method, paid, delivered_at"
        " from orders where status = 'DELIVERED' and delivered_at is not null and deleted_at is null"
        " and " + sql_days("delivered_at") + " between :a and :b order by delivered_at, id",
        a=a.isoformat(), b=b.isoformat())


def day_start_utc(d: date) -> str:
    """业务日 d 的 0 点（东八区）换算成库里存的 UTC naive 时刻（前一天 16:00）。"""
    return (datetime.combine(d, datetime.min.time()) - timedelta(hours=8)).isoformat(sep=" ")


def weighted_avg(db: Db, until: date, since: date | None) -> dict:
    """**独立实现**的本期/累计加权平均进货价（change > 0 且 unit_cost 非空的入库流水）。

    与 cost_basis.py 同一口径：上界 = until 次日 0 点（东八区）；本期模式再压下界。
    """
    lo = ""
    if since is not None:
        lo = " and datetime(created_at) >= datetime(:lo)"
    rows = db.rows(
        "select product_id, sum(change) as qty, sum(change * unit_cost) as amount"
        " from inventory_movements where change > 0 and unit_cost is not null"
        " and datetime(created_at) < datetime(:hi)" + lo + " group by product_id",
        hi=day_start_utc(until + timedelta(days=1)),
        **({"lo": day_start_utc(since)} if since is not None else {}))
    out = {}
    for r in rows:
        qty = dec(r["qty"])
        if qty > 0:
            out[r["product_id"]] = q4(dec(r["amount"]) / qty)
    return out


def basis_of(period: dict, cumulative: dict, pid, snapshot) -> tuple[Decimal, str]:
    if pid is not None:
        if pid in period:
            return period[pid], "avg"
        if pid in cumulative:
            return cumulative[pid], "avg"
    return dec(snapshot or 0), "snapshot"


def recompute_sales(db: Db, a: date, b: date) -> dict:
    period = weighted_avg(db, b, a)
    cumulative = weighted_avg(db, b, None)
    orders = delivered_orders(db, a, b)
    amount = D("0")
    collected = D("0")
    arrears = D("0")
    lines = 0
    covered_lines = 0
    avg_lines = 0
    snap_lines = 0
    cost_total = D("0")
    covered_amount = D("0")
    damage_qty = 0
    damage_amount = D("0")
    damage_in_cogs = D("0")  # 货损件数被算进 COGS 的那部分（双算的 COGS 一侧）
    per_product: dict[str, dict] = {}
    per_order: dict[int, dict] = {}

    for o in orders:
        rcv, settled, refunded = _order_money(db, o)
        amount += rcv
        collected += settled - refunded
        arrears += rcv - settled + refunded
        per_order[o["id"]] = {"rcv": rcv, "net": settled - refunded}
        lps = db.rows("select * from order_products where order_id = :o order by id", o=o["id"])
        for lp in lps:
            qty = int(lp["quantity"] or 0)
            ret = int(lp["returned_quantity"] or 0)
            dmg = int(lp["damage_quantity"] or 0)
            net_qty = qty - ret
            if net_qty <= 0 and dmg <= 0:
                continue
            lines += 1
            cost, src = basis_of(period, cumulative, lp["product_id"], lp["cost_price_snapshot"])
            line_rcv = q2(dec(lp["unit_price"]) * max(net_qty, 0))
            if cost > 0:
                covered_lines += 1
                if src == "avg":
                    avg_lines += 1
                else:
                    snap_lines += 1
                cost_total += cost * D(max(net_qty, 0))
                covered_amount += line_rcv
                damage_in_cogs += cost * D(dmg)
            if dmg > 0:
                damage_qty += dmg
                damage_amount += dec(lp["cost_price_snapshot"]) * D(dmg)
            key = (lp["product_name_snapshot"] or "") + "|" + str(lp["product_id"])
            g = per_product.setdefault(key, {
                "product_id": lp["product_id"], "name": lp["product_name_snapshot"],
                "qty": 0, "amount": D("0"), "cost": D("0"), "damage_qty": 0,
                "damage_amount": D("0"), "lines": 0, "covered": 0,
                "covered_amount": D("0")})
            g["qty"] += net_qty
            g["amount"] += line_rcv
            g["lines"] += 1
            if cost > 0:
                g["covered"] += 1
                g["cost"] += cost * D(max(net_qty, 0))
                g["covered_amount"] += line_rcv
            if dmg > 0:
                g["damage_qty"] += dmg
                g["damage_amount"] += dec(lp["cost_price_snapshot"]) * D(dmg)

    return {
        "orders": len(orders),
        "amount": q2(amount),
        "collected": q2(collected),
        "arrears": q2(arrears),
        "lines": lines,
        "covered_lines": covered_lines,
        "avg_lines": avg_lines,
        "snap_lines": snap_lines,
        "cost_total": q2(cost_total),
        "covered_amount": q2(covered_amount),
        "damage_qty": damage_qty,
        "damage_amount": q2(damage_amount),
        "damage_in_cogs": q2(damage_in_cogs),
        "per_product": per_product,
        "per_order": per_order,
        "period_priced": len(period),
        "cum_priced": len(cumulative),
    }


def recompute_cancelled(db: Db, a: date, b: date) -> int:
    return int(db.scalar(
        "select count(*) from orders where status = 'CANCELLED' and cancelled_at is not null"
        " and deleted_at is null and " + sql_days("cancelled_at") + " between :a and :b",
        a=a.isoformat(), b=b.isoformat()))


# =====================================================================
# 重算：期间费用 / 折旧 / 税金
# =====================================================================
def recompute_expenses(db: Db, a: date, b: date) -> dict:
    rows = db.rows(
        "select coalesce(nullif(trim(category), ''), '未分类') as cat, sum(amount) as amt, count(*) as n"
        " from expenses where exp_date between :a and :b group by cat", a=a.isoformat(), b=b.isoformat())
    per = {r["cat"]: q2(r["amt"]) for r in rows}
    return {"per_category": per, "total": q2(sum(per.values(), D("0"))),
            "count": sum(int(r["n"]) for r in rows)}


def monthly_depreciation(purchase_price, purchase_date, life_years, residual_rate) -> Decimal:
    pp = dec(purchase_price or 0)
    ly = dec(life_years or 0)
    if pp <= 0 or ly <= 0 or not purchase_date:
        return D("0")
    rr = dec(residual_rate or 0)
    return q2(pp * (D("1") - rr) / (ly * D("12")))


def _days_in_month(y: int, m: int) -> int:
    nxt = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    return (nxt - date(y, m, 1)).days


def depreciation_of(v, a: date, b: date) -> Decimal:
    """**独立实现**：月折旧额 × 各自然月与窗口交集天数 ÷ 当月天数（购置日当天起算）。"""
    if not v["purchase_date"]:
        return D("0")
    try:
        pd = date.fromisoformat(str(v["purchase_date"])[:10])
    except ValueError:
        return D("0")
    monthly = monthly_depreciation(v["purchase_price"], v["purchase_date"],
                                   v["useful_life_years"], v["residual_rate"])
    if monthly <= 0:
        return D("0")
    total = D("0")
    y, m = a.year, a.month
    while (y, m) <= (b.year, b.month):
        dim = _days_in_month(y, m)
        m0 = date(y, m, 1)
        m1 = date(y, m, dim)
        lo = max(m0, a, pd)
        hi = min(m1, b)
        if hi >= lo:
            total += monthly * D((hi - lo).days + 1) / D(dim)
        m = 1 if m == 12 else m + 1
        y = y + 1 if m == 1 else y
    return q2(total)


def recompute_depreciation(db: Db, a: date, b: date) -> dict:
    vehicles = db.rows("select * from vehicles order by id")
    per = {}
    covered = 0
    uncovered = []
    for v in vehicles:
        amt = depreciation_of(v, a, b)
        per[v["id"]] = amt
        if amt > 0:
            covered += 1
        else:
            miss = []
            if not v["purchase_price"]:
                miss.append("没录购置价")
            if not v["purchase_date"]:
                miss.append("没录购置日期")
            if not v["useful_life_years"]:
                miss.append("没录使用年限")
            if miss:
                uncovered.append({"plate_no": v["plate_no"], "reasons": miss})
    monthly_total = sum((monthly_depreciation(v["purchase_price"], v["purchase_date"],
                                              v["useful_life_years"], v["residual_rate"])
                         for v in vehicles), D("0"))
    return {"per_vehicle": per, "total": q2(sum(per.values(), D("0"))),
            "monthly_total": q2(monthly_total), "covered": covered,
            "uncovered": uncovered, "count": len(vehicles)}


def recompute_taxes(db: Db, a: date, b: date) -> dict:
    rows = db.rows(
        "select direction, invoice_no, amount, tax_rate, tax_amount, status"
        " from invoices where is_deleted = 0 and invoice_date between :a and :b"
        " order by invoice_date, id", a=a.isoformat(), b=b.isoformat())
    out = {"output": {"count": 0, "amount": D("0"), "tax": D("0"), "net": D("0")},
           "input": {"count": 0, "amount": D("0"), "tax": D("0"), "net": D("0")},
           "untaxed": {"output": [0, D("0")], "input": [0, D("0")]},
           "voided": 0, "by_rate": {}}
    for r in rows:
        if (r["status"] or "").upper() == "VOIDED":
            out["voided"] += 1
            continue
        side = "output" if (r["direction"] or "").lower() == "output" else "input"
        amt = q2(r["amount"])
        if r["tax_rate"] is None:
            out["untaxed"][side][0] += 1
            out["untaxed"][side][1] += amt
            continue
        tax = q2(r["tax_amount"])
        out[side]["count"] += 1
        out[side]["amount"] += amt
        out[side]["tax"] += tax
        out[side]["net"] += amt - tax
        key = side + "|" + str(q2(r["tax_rate"]))
        g = out["by_rate"].setdefault(key, {"count": 0, "amount": D("0"), "tax": D("0")})
        g["count"] += 1
        g["amount"] += amt
        g["tax"] += tax
    out["vat_payable"] = q2(out["output"]["tax"] - out["input"]["tax"])
    for side in ("output", "input"):
        out[side]["amount"] = q2(out[side]["amount"])
        out[side]["tax"] = q2(out[side]["tax"])
        out[side]["net"] = q2(out[side]["net"])
    return out


# =====================================================================
# 重算：客户余额（时点账 / 账龄 / 额度）
# =====================================================================
BUCKET_KEYS = ["0_30", "31_60", "61_90", "over_90"]


def bucket_of(days: int) -> str:
    if days <= 30:
        return "0_30"
    if days <= 60:
        return "31_60"
    if days <= 90:
        return "61_90"
    return "over_90"


def debtor_of(o: sqlite3.Row) -> tuple[str, object, str]:
    """分组判据（与 balance_query._debtor_of 同一份口径，独立写一遍）。"""
    if o["arrears_unit_id"]:
        return "unit", o["arrears_unit_id"], ""
    nm = (o["arrears_unit_name"] or "").strip()
    if nm:
        return "unit_name", nm, ""
    if o["shipper_id"]:
        return "shipper", o["shipper_id"], ""
    nm = (o["temp_shipper_name"] or "").strip()
    if nm:
        return "temp", nm, ""
    return "unknown", "", "未填货主"


def recompute_balances(db: Db, as_of: date) -> dict:
    orders = db.rows(
        "select id, order_no, shipper_id, temp_shipper_name, arrears_unit_id, arrears_unit_name,"
        " payment_method, paid, delivered_at from orders"
        " where status = 'DELIVERED' and delivered_at is not null and deleted_at is null"
        " and " + sql_days("delivered_at") + " <= :a order by delivered_at, id", a=as_of.isoformat())
    ids = [o["id"] for o in orders]
    anchors = {}
    if ids:
        marks = ",".join("?" * len(ids))
        for r in db.c.execute(
                "select order_id, min(entry_date) as d from ledgers"
                " where order_id in (" + marks + ") and source in ('ORDER', 'MANUAL')"
                " group by order_id", ids).fetchall():
            anchors[r["order_id"]] = r["d"]
    groups: dict = {}
    order_rows = []
    for o in orders:
        rcv, settled, refunded = _order_money(db, o)
        amount = q2(rcv - settled + refunded)
        if amount == 0:
            continue
        kind, key, label = debtor_of(o)
        ds = (datetime.fromisoformat(str(o["delivered_at"])) + timedelta(hours=8)).date()
        anchor = date.fromisoformat(str(anchors[o["id"]])[:10]) if o["id"] in anchors else ds
        days = max((as_of - anchor).days, 0)
        gk = (kind, key)
        g = groups.setdefault(gk, {"kind": kind, "key": key, "name": "", "balance": D("0"),
                                   "prepaid": D("0"), "orders": 0, "oldest": 0,
                                   "buckets": {k: D("0") for k in BUCKET_KEYS}})
        if kind == "unit":
            u = db.one("select name, credit_limit from arrears_units where id = :i", i=key)
            g["name"] = (u["name"] if u else ("挂账单位#" + str(key)))
            g["limit"] = dec(u["credit_limit"]) if (u and u["credit_limit"] is not None) else None
        elif kind == "unit_name":
            g["name"] = str(key)
        elif kind == "shipper":
            # 与 balance_query._user_label(users.get(o.shipper_id)) 同源：orders.shipper_id 直接指
            # users.id（不是 customers.user_id —— 走客户档案 join 会整片名字错位，实测过）。
            u = db.one("select full_name, phone from users where id = :i", i=key)
            nm2 = ((u["full_name"] or "").strip() or (u["phone"] or "").strip()) if u else ""
            g["name"] = nm2 or ("货主#" + str(key))
        elif kind == "temp":
            g["name"] = str(key)
        else:
            g["name"] = "未填货主"
        g["orders"] += 1
        g["balance"] += amount
        if amount > 0:
            g["buckets"][bucket_of(days)] += amount
            g["oldest"] = max(g["oldest"], days)
        else:
            g["prepaid"] += -amount
        order_rows.append({"order_id": o["id"], "order_no": o["order_no"], "name": g["name"],
                           "amount": amount, "days": days, "bucket": bucket_of(days)})
    rows = sorted(groups.values(), key=lambda g: (-g["balance"], g["name"]))
    over = 0
    for g in rows:
        used = g["balance"] if g["balance"] > 0 else D("0")
        g["credit_used"] = q2(used)
        lim = g.get("limit")
        g["credit_available"] = q2(lim - used) if lim is not None else None
        g["over_limit"] = bool(lim is not None and used > lim)
        if g["over_limit"]:
            over += 1
    totals = {
        "balance": q2(sum((g["balance"] for g in rows), D("0"))),
        "prepaid": q2(sum((g["prepaid"] for g in rows), D("0"))),
        "debtor_count": len(rows),
        "order_count": sum(g["orders"] for g in rows),
        "over_limit_count": over,
        "no_unit_balance": q2(sum((g["balance"] for g in rows if g["kind"] != "unit"), D("0"))),
        "no_unit_count": sum(1 for g in rows if g["kind"] != "unit"),
        "buckets": {k: q2(sum((g["buckets"][k] for g in rows), D("0"))) for k in BUCKET_KEYS},
    }
    return {"rows": rows, "totals": totals, "orders": order_rows}


# =====================================================================
# 重算：现金流水 / 库存 / 应付 / 司机账单
# =====================================================================
def recompute_cash(db: Db, a: date, b: date) -> dict:
    rows = db.rows(
        "select lower(direction) as dir, biz_type, amount from cash_flows"
        " where is_deleted = 0 and flow_date between :a and :b", a=a.isoformat(), b=b.isoformat())
    income = expense = D("0")
    n = 0
    by_biz: dict = {}
    null_amount = 0
    for r in rows:
        n += 1
        if r["amount"] is None:
            null_amount += 1
        amt = dec(r["amount"])
        g = by_biz.setdefault(str(r["dir"]) + "|" + str(r["biz_type"]), [D("0"), 0])
        g[0] += amt
        g[1] += 1
        if r["dir"] == "in":
            income += amt
        else:
            expense += amt
    return {"income": q2(income), "expense": q2(expense), "net": q2(income - expense),
            "count": n, "by_biz": by_biz, "null_amount": null_amount}


def recompute_inventory(db: Db) -> dict:
    kinds = int(db.scalar(
        "select count(*) from products where is_deleted = 0 and coalesce(stock, 0) > 0"))
    qty = dec(db.scalar(
        "select coalesce(sum(stock), 0) from products where is_deleted = 0 and coalesce(stock, 0) > 0"))
    value = dec(db.scalar(
        "select coalesce(sum(stock * cost_price), 0) from products"
        " where is_deleted = 0 and coalesce(stock, 0) > 0"))
    never = db.rows(
        "select p.id, p.name, p.stock, p.cost_price from products p"
        " where p.is_deleted = 0 and p.id not in (select distinct product_id from inventory_movements"
        " where change > 0 and unit_cost is not null) order by p.name")
    return {"kinds": kinds, "qty": q2(qty), "value": q2(value), "never_priced": never}


def recompute_payables(db: Db) -> dict:
    due = q2(db.scalar("select coalesce(sum(amount), 0) from supplier_payables where is_deleted = 0"))
    rows = db.rows(
        "select sp.id, sp.amount, coalesce((select sum(cf.amount) from cash_flows cf"
        " where cf.party_type = 'supplier' and lower(cf.direction) = 'out'"
        " and cf.biz_type = 'PAYMENT_SUPPLIER' and cf.is_deleted = 0 and cf.doc_id = sp.id), 0) as paid"
        " from supplier_payables sp where sp.is_deleted = 0 order by sp.id")
    paid = D("0")
    unpaid = D("0")
    for r in rows:
        paid += q2(r["paid"])
        unpaid += q2(dec(r["amount"]) - q2(r["paid"]))
    return {"due": due, "paid": q2(paid), "unpaid": q2(unpaid), "count": len(rows)}


def _settlement_table(db: Db) -> str | None:
    r = db.one("select name from sqlite_master where type = 'table'"
               " and name in ('driver_settlements', 'settlements')")
    return r["name"] if r else None


def recompute_driver_bills(db: Db, a: date, b: date) -> dict:
    """逐单应付的**旁证**：driver_bills（送达时生成）按订单送达日归窗口。"""
    rows = db.rows(
        "select b.driver_id, b.order_id, b.amount, b.bill_type, b.status as bill_status from driver_bills b"
        " join orders o on o.id = b.order_id"
        " where o.status = 'DELIVERED' and o.deleted_at is null"
        " and " + sql_days("o.delivered_at") + " between :a and :b", a=a.isoformat(), b=b.isoformat())
    per_driver: dict = {}
    open_per_driver: dict = {}
    total = D("0")
    for r in rows:
        amt = dec(r["amount"])
        total += amt
        per_driver[r["driver_id"]] = per_driver.get(r["driver_id"], D("0")) + amt
        if str(r["bill_status"] or "") == "open":
            # 窗口内**还没结**的账单：这是「本期还欠他多少」的真值，页面按另一个口径算。
            open_per_driver[r["driver_id"]] = open_per_driver.get(r["driver_id"], D("0")) + amt
    settled: dict = {}
    table = _settlement_table(db)
    if table:
        for r in db.rows("select driver_id, sum(amount) as amt from " + table
                         + " where status = 'PAID' group by driver_id"):
            settled[r["driver_id"]] = q2(r["amt"])
    return {"total": q2(total), "per_driver": {k: q2(v) for k, v in per_driver.items()},
            "open_per_driver": {k: q2(v) for k, v in open_per_driver.items()},
            "settled_all_time": settled, "bills": len(rows), "table": table}


def recompute_drivers(db: Db, a: date, b: date) -> dict:
    rows = db.rows(
        "select driver_id, count(*) as n from orders where status = 'DELIVERED'"
        " and delivered_at is not null and deleted_at is null and driver_id is not null"
        " and " + sql_days("delivered_at") + " between :a and :b group by driver_id",
        a=a.isoformat(), b=b.isoformat())
    return {r["driver_id"]: int(r["n"]) for r in rows}


def recompute_vehicle_expenses(db: Db, a: date, b: date) -> dict:
    rows = db.rows(
        "select vehicle_id, sum(amount) as amt from expenses where vehicle_id is not null"
        " and exp_date between :a and :b group by vehicle_id", a=a.isoformat(), b=b.isoformat())
    return {r["vehicle_id"]: q2(r["amt"]) for r in rows}


def _ts(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def auto_exception_reason(o: sqlite3.Row, now: datetime):
    """自动异常规则（与 stats_service.auto_exception_reason 同一份判据，独立写一遍）。"""
    if o["exception_resolved_at"]:
        return None
    st = o["status"]
    if st == "CANCELLED":
        return "已撤销/撤回订单"
    if st == "PENDING_DISPATCH":
        ct = _ts(o["created_at"]) or _ts(o["updated_at"])
        if ct is not None and now - ct > timedelta(hours=4):
            return "待派超时（超过4小时未派单）"
        return None
    if st in ("DISPATCHED", "ACCEPTED"):
        eb = _ts(o["expected_deliver_before"])
        if eb is not None and eb < now:
            return "超时未送（超过预计送达时间）"
        return None
    if st == "DELIVERED":
        eb = _ts(o["expected_deliver_before"])
        dl = _ts(o["delivered_at"])
        if eb is not None and dl is not None and dl > eb:
            return "逾期送达（超过预计送达时间）"
        return None
    return None


def recompute_exceptions(db: Db, a: date, b: date) -> dict:
    """运营分析·异常单：**按 order_date 筛窗口**（不是送达日），再加自动规则捞出来的那批。

    ⚠️ 这里踩过一次：最初按送达日筛，只对上 6 条而接口给 60 条。接口的窗口列是
    `Order.order_date`（stats_service.exception_orders :405-406），且 is_exception=0 的单
    还要再过一遍 auto_exception_reason（:437-473）才会被追加进来。
    """
    rows = db.rows(
        "select id, status, is_exception, exception_resolved_at, created_at, updated_at,"
        " expected_deliver_before, delivered_at from orders"
        " where deleted_at is null and order_date between :a and :b order by id",
        a=a.isoformat(), b=b.isoformat())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    explicit = [r for r in rows if r["is_exception"]]
    auto = [r for r in rows if not r["is_exception"] and auto_exception_reason(r, now)]
    return {"total": len(explicit) + len(auto), "explicit": len(explicit), "auto": len(auto)}


def recompute_arrears_summary(db: Db, a: date, b: date) -> dict:
    """独立重算「挂账单位汇总」（arrears_query.build_arrears_summary 的口径）。

    ⚠️ 与 customer-balances 不是一回事：这里是**区间账**（送达日落在窗口内），初筛只认
    `paid=0`，再按 `arrears_unit_name` 的**文本**分组（`arrears_unit_id` 不参与）——
    名字为空的那批归到「未分配挂账单位」。时点余额读 `customer-balances.totals.balance`，
    本表要跟这个函数比，别拿时点余额去套（第一版就是这么错的：5,566.30 vs 737.60）。
    """
    orders = db.rows(
        "select id, order_no, shipper_id, temp_shipper_name, arrears_unit_id, arrears_unit_name,"
        " payment_method, paid, delivered_at from orders"
        " where status = 'DELIVERED' and delivered_at is not null and deleted_at is null"
        " and ifnull(paid, 0) = 0"
        " and " + sql_days("delivered_at") + " between :a and :b order by delivered_at, id",
        a=a.isoformat(), b=b.isoformat())
    groups: dict = {}
    count = 0
    total = D("0")
    for o in orders:
        rcv, settled, refunded = _order_money(db, o)
        amount = q2(rcv - settled + refunded)
        if amount == 0:
            continue
        name = (o["arrears_unit_name"] or "").strip() or "未分配挂账单位"
        g = groups.setdefault(name, {"name": name, "amount": D("0"), "count": 0})
        g["amount"] += amount
        g["count"] += 1
        count += 1
        total += amount
    return {"rows": sorted(groups.values(), key=lambda g: -g["amount"]),
            "count": count, "amount": q2(total), "orders": len(orders)}


def close_orders_probe(db: Db):
    """采购入库流水的时间戳诊断：补录历史采购单会让「本期加权均价」永远取不到。"""
    total = int(db.scalar("select count(*) from inventory_movements where source = 'PURCHASE'"
                          " and change > 0 and unit_cost is not null"))
    late = db.rows(
        "select po.doc_date, " + sql_days("im.created_at") + " as created_day, count(*) as n"
        " from inventory_movements im join purchase_order_items poi on poi.movement_id = im.id"
        " join purchase_orders po on po.id = poi.order_id"
        " where im.change > 0 and im.unit_cost is not null"
        " group by po.doc_date, created_day having created_day > po.doc_date order by po.doc_date")
    back = sum(int(r["n"]) for r in late)
    return {"priced_inbound": total, "backdated": back, "detail": late}


# =====================================================================
# 对账：一个窗口里的五张表 + 各个下钻节点
# =====================================================================
def _num(d, *names, default=D("0")):
    if not isinstance(d, dict):
        return default
    for n in names:
        if d.get(n) is not None:
            return dec(d[n])
    return default


def check_window(db: Db, api: Api, rep: Report, label: str, a: date, b: date) -> dict:
    print("")
    print("#" * 74)
    print("# 窗口：" + label + "   " + a.isoformat() + " ~ " + b.isoformat())
    print("#" * 74)

    s = recompute_sales(db, a, b)
    bills = recompute_driver_bills(db, a, b)
    exp = recompute_expenses(db, a, b)
    dep = recompute_depreciation(db, a, b)
    tax = recompute_taxes(db, a, b)
    veh_exp = recompute_vehicle_expenses(db, a, b)
    inv = recompute_inventory(db)
    pay = recompute_payables(db)
    drv = recompute_drivers(db, a, b)

    tax_exp = q2(sum((exp["per_category"][c] for c in exp["per_category"] if "税" in c), D("0")))
    op_exp = q2(exp["total"] - tax_exp)

    # ---------------- 一、营业纵览 ----------------
    rep.head("一、营业纵览（GET /reports/turnover）")
    t = api.report("turnover", a, b)
    rep.ck("营业额", s["amount"], t["total_amount"])
    rep.ck("送达单数", D(s["orders"]), _num(t, "total_orders"), tol=D("0"))
    rep.ck("已收（按订单归集）", s["collected"], t["collected"])
    rep.ck("欠款", s["arrears"], t["arrears_total"])
    rep.ck("成本行数", D(s["lines"]), _num(t, "total_lines"), tol=D("0"))
    rep.ck("有价行数", D(s["covered_lines"]), _num(t, "cost_covered_lines"), tol=D("0"))
    rep.ck("其中·本期均价", D(s["avg_lines"]), _num(t, "cost_avg_lines"), tol=D("0"))
    rep.ck("其中·订单快照", D(s["snap_lines"]), _num(t, "cost_snapshot_lines"), tol=D("0"))
    rep.ck("商品成本", s["cost_total"], t["cost_total"])
    rep.ck("已覆盖收入", s["covered_amount"], t["cost_covered_amount"])
    rep.ck("货损件数", D(s["damage_qty"]), _num(t, "damage_qty"), tol=D("0"))
    rep.ck("货损金额", s["damage_amount"], t["damage_amount"])
    rep.ck("撤销单数", D(recompute_cancelled(db, a, b)), _num(t, "cancelled_orders"), tol=D("0"))
    rep.ck("司机运费（账单旁证）", bills["total"], t["total_freight"],
           kind_note="旁证：driver_bills 按送达日归集")

    # ---------------- 二、利润表 ----------------
    rep.head("二、利润表（GET /reports/profit）")
    p = api.report("profit", a, b)
    rep.ck("营业额", s["amount"], p["revenue_total"])
    rep.ck("已覆盖收入", s["covered_amount"], p["revenue_covered"])
    rep.ck("未覆盖收入", s["amount"] - s["covered_amount"], p["revenue_uncovered"])
    rep.ck("商品成本", s["cost_total"], p["cost_total"])
    rep.ck("毛利 = 已覆盖收入 − 商品成本", s["covered_amount"] - s["cost_total"], p["gross_profit"])
    rep.ck("期间费用（不含税类）", op_exp, p["operating_expense_total"])
    rep.ck("税金及附加（费用里含「税」的分类）", tax_exp, p["tax_total"])
    rep.ck("配送成本（司机应得）", bills["total"], p["delivery_cost"])
    rep.ck("折旧合计", dep["total"], p["depreciation_total"])
    rep.ck("每月固定折旧", dep["monthly_total"], p["depreciation_monthly_total"])
    rep.ck("折旧有价车数", D(dep["covered"]), _num(p, "depreciation_vehicle_count"), tol=D("0"))
    rep.ck("折旧未覆盖车数", D(len(dep["uncovered"])), _num(p, "depreciation_uncovered_count"), tol=D("0"))
    rep.ck("营业利润", s["covered_amount"] - s["cost_total"] - bills["total"] - op_exp - dep["total"] - tax_exp,
           p["operating_profit"])
    rep.ck("增值税·销项", tax["output"]["tax"], p["vat_output"])
    rep.ck("增值税·进项", tax["input"]["tax"], p["vat_input"])
    rep.ck("增值税·应交", tax["vat_payable"], p["vat_payable"])
    api_exp = {str(r.get("category") or r.get("name") or ""): _num(r, "amount")
               for r in (p.get("operating_expenses") or [])}
    for cat, amt in sorted(exp["per_category"].items(), key=lambda kv: -kv[1]):
        rep.ck("期间费用明细·" + cat, amt, api_exp.get(cat, D("0")), quiet=True)
    for cat in api_exp:
        if cat not in exp["per_category"]:
            rep.ck("期间费用明细·" + cat + "（接口有、库里没有）", D("0"), api_exp[cat])

    # ---------------- 三、商品经营 ----------------
    rep.head("三、商品经营（GET /reports/products）")
    pr = api.report("products", a, b)
    items = pr.get("items") or []
    if items:
        print("|   info items[0] 键：" + ", ".join(sorted(items[0].keys())))
    api_by_name = {}
    for it in items:
        nm = str(it.get("product_name") or it.get("name") or "")
        api_by_name[nm] = it
    rep.ck("商品表·数量合计", D(sum(g["qty"] for g in s["per_product"].values())), _num(pr, "total_qty"), tol=D("0"))
    rep.ck("商品表·金额合计", q2(sum((g["amount"] for g in s["per_product"].values()), D("0"))),
           _num(pr, "total_amount"))
    rep.ck("商品表·成本合计", s["cost_total"], _num(pr, "cost_total"))
    rep.ck("商品表·货损件数", D(s["damage_qty"]), _num(pr, "damage_qty"), tol=D("0"))
    top = sorted(s["per_product"].values(), key=lambda g: -g["amount"])[:6]
    for g in top:
        it = api_by_name.get(str(g["name"]))
        if it is None:
            rep.ck("商品·" + str(g["name"]) + "（接口里没有这个商品）", g["amount"], D("0"))
            continue
        rep.ck("商品·" + str(g["name"]) + "·金额", g["amount"],
               _num(it, "amount", "total_amount", "line_total"), quiet=True)
        rep.ck("商品·" + str(g["name"]) + "·数量", D(g["qty"]),
               _num(it, "quantity", "qty", "total_qty"), tol=D("0"), quiet=True)
        rep.ck("商品·" + str(g["name"]) + "·成本", g["cost"],
               _num(it, "cost_total", "cost"), quiet=True)

    # ---------------- 四、车辆成本 ----------------
    rep.head("四、车辆成本（GET /reports/vehicle-cost）")
    vc = api.report("vehicle-cost", a, b)
    per = {int(r["vehicle_id"]): r for r in (vc.get("per_vehicle") or [])}
    veh_rows = db.rows("select id, plate_no, driver_id from vehicles order by id")
    my_veh = {}
    for v in veh_rows:
        dcost = bills["per_driver"].get(v["driver_id"], D("0")) if v["driver_id"] else D("0")
        my_veh[int(v["id"])] = {"plate": v["plate_no"], "expense": veh_exp.get(v["id"], D("0")),
                                "delivery": dcost, "dep": dep["per_vehicle"].get(v["id"], D("0"))}
        my_veh[int(v["id"])]["total"] = (my_veh[int(v["id"])]["expense"]
                                         + my_veh[int(v["id"])]["delivery"]
                                         + my_veh[int(v["id"])]["dep"])
    rep.ck("车辆成本·车辆数", D(len(veh_rows)), _num(vc, "vehicle_count"), tol=D("0"))
    rep.ck("车辆成本·折旧合计", dep["total"], _num(vc, "depreciation_total"))
    rep.ck("车辆成本·每月固定折旧", dep["monthly_total"], _num(vc, "depreciation_monthly_total"))
    rep.ck("车辆成本·费用合计", q2(sum((r["expense"] for r in my_veh.values()), D("0"))),
           _num(vc, "expense_total"))
    rep.ck("车辆成本·配送成本合计", q2(sum((r["delivery"] for r in my_veh.values()), D("0"))),
           _num(vc, "delivery_cost_total"))
    rep.ck("车辆成本·总成本", q2(sum((r["total"] for r in my_veh.values()), D("0"))), _num(vc, "total_cost"))
    rep.ck("车辆成本·逐车相加 == 合计",
           q2(sum((_num(per.get(k, {}), "total_cost") for k in my_veh), D("0"))), _num(vc, "total_cost"))
    rep.ck("车辆成本·配送成本 vs 全部司机应得", bills["total"], _num(vc, "delivery_cost_total"),
           kind_note="口径：司机没挂车的应得不在车表里，本来就不等")
    for k, mine in my_veh.items():
        row = per.get(k)
        if row is None:
            rep.ck("车辆·" + str(mine["plate"]) + "（接口里没有这台车）", mine["total"], D("0"))
            continue
        plate = str(mine["plate"])
        rep.ck("车辆·" + plate + "·折旧", mine["dep"], _num(row, "depreciation"), quiet=True)
        rep.ck("车辆·" + plate + "·开销", mine["expense"], _num(row, "expense_total"), quiet=True)
        rep.ck("车辆·" + plate + "·司机应得", mine["delivery"], _num(row, "delivery_cost"), quiet=True)
        rep.ck("车辆·" + plate + "·合计", mine["total"], _num(row, "total_cost"), quiet=True)

    # ---------------- 五、成本覆盖率 ----------------
    rep.head("五、成本覆盖率（GET /reports/cost-coverage）")
    cc = api.report("cost-coverage", a, b)
    rep.ck("营业额", s["amount"], _num(cc, "revenue_total"))
    rep.ck("已覆盖收入", s["covered_amount"], _num(cc, "revenue_covered"))
    rep.ck("未覆盖收入", s["amount"] - s["covered_amount"], _num(cc, "revenue_uncovered"))
    rep.ck("成本行数", D(s["lines"]), _num(cc, "total_lines"), tol=D("0"))
    rep.ck("有价行数", D(s["covered_lines"]), _num(cc, "covered_lines"), tol=D("0"))
    rep.ck("从没记过进货价的商品数", D(len(inv["never_priced"])), _num(cc, "missing_purchase_price_count"), tol=D("0"))
    api_missing = {str(r.get("name") or r.get("product_name") or "")
                   for r in (cc.get("missing_purchase_price") or [])}
    my_missing = {str(r["name"]) for r in inv["never_priced"]}
    if api_missing != my_missing:
        print("|   !! 名册不一致：接口多 " + str(sorted(api_missing - my_missing))
              + " / 库多 " + str(sorted(my_missing - api_missing)))
        rep.rows.append({"section": rep.section, "label": "从没记过进货价的商品名册",
                         "indep": D(len(my_missing)), "api": D(len(api_missing)),
                         "diff": D(len(my_missing) - len(api_missing)), "kind": "错", "note": ""})

    # ---------------- 六、税汇 ----------------
    rep.head("六、发票与税汇（GET /reports/tax-summary）")
    ts = api.report("tax-summary", a, b)
    for side in ("output", "input"):
        apiside = ts.get(side) or {}
        if side == "output" and apiside:
            print("|   info " + side + " 键：" + ", ".join(sorted(apiside.keys())))
        rep.ck(side + "·票数", D(tax[side]["count"]), _num(apiside, "count"), tol=D("0"))
        rep.ck(side + "·金额", tax[side]["amount"], _num(apiside, "amount"))
        rep.ck(side + "·税额", tax[side]["tax"], _num(apiside, "tax_amount"))
        rep.ck(side + "·不含税", tax[side]["net"], _num(apiside, "net_amount"))
        rep.ck(side + "·无税率票数", D(tax["untaxed"][side][0]), _num(apiside, "untaxed_count"), tol=D("0"))
        rep.ck(side + "·无税率金额", tax["untaxed"][side][1], _num(apiside, "untaxed_amount"))
    rep.ck("作废票数", D(tax["voided"]), _num(ts, "voided_count"), tol=D("0"))
    rep.ck("应交增值税 = 销项 − 进项", tax["vat_payable"], _num(ts, "vat_payable"))
    api_rate = {}
    for r in (ts.get("by_rate") or []):
        key = str(r.get("direction", "")).lower() + "|" + str(q2(r.get("tax_rate", 0)))
        api_rate[key] = r
    for key, mine in tax["by_rate"].items():
        r = api_rate.get(key)
        if r is None:
            rep.ck("税率档 " + key + "（接口里没有）", mine["tax"], D("0"))
            continue
        rep.ck("税率档 " + key + "·税额", mine["tax"], _num(r, "tax_amount"), quiet=True)
        rep.ck("税率档 " + key + "·票数", D(mine["count"]), _num(r, "count"), tol=D("0"), quiet=True)
    rep.ck("逐票明细条数", D(tax["output"]["count"] + tax["input"]["count"] + tax["untaxed"]["output"][0]
                            + tax["untaxed"]["input"][0] + tax["voided"]), D(len(ts.get("invoices") or [])), tol=D("0"))

    # ---------------- 七、资产负债表 ----------------
    rep.head("七、资产负债表（别人欠我 / 库存 / 我欠司机 / 我欠供应商）")
    cb = api.report("customer-balances", a, b, "&include_orders=true")
    as_of = date.fromisoformat(str(cb["as_of"]))
    b2 = recompute_balances(db, as_of)
    tot = cb.get("totals") or {}
    print("|   info as_of=" + as_of.isoformat() + "  totals 键：" + ", ".join(sorted(tot.keys())))
    rep.ck("别人欠我（余额合计）", b2["totals"]["balance"], _num(tot, "balance"))
    rep.ck("预收合计", b2["totals"]["prepaid"], _num(tot, "prepaid"))
    rep.ck("欠款户数", D(b2["totals"]["debtor_count"]), _num(tot, "debtor_count"), tol=D("0"))
    rep.ck("欠款单数", D(b2["totals"]["order_count"]), _num(tot, "order_count"), tol=D("0"))
    rep.ck("超限户数", D(b2["totals"]["over_limit_count"]), _num(tot, "over_limit_count"), tol=D("0"))
    rep.ck("无挂账单位的欠款", b2["totals"]["no_unit_balance"], _num(tot, "no_unit_balance"))
    rep.ck("无挂账单位的户数", D(b2["totals"]["no_unit_count"]), _num(tot, "no_unit_count"), tol=D("0"))
    api_buckets = tot.get("buckets") or {}
    for k in BUCKET_KEYS:
        rep.ck("账龄桶 " + k, b2["totals"]["buckets"][k], _num(api_buckets, k), quiet=True)
    api_rows = {}
    for r in (cb.get("rows") or []):
        api_rows[(str(r.get("kind")), str(r.get("name")))] = r
    for g in b2["rows"]:
        r = api_rows.get((g["kind"], g["name"]))
        if r is None:
            rep.ck("欠款户·" + g["name"] + "（接口里没有这一行）", g["balance"], D("0"))
            continue
        rep.ck("欠款户·" + g["name"] + "·余额", g["balance"], _num(r, "balance"), quiet=True)
        rep.ck("欠款户·" + g["name"] + "·单数", D(g["orders"]), _num(r, "order_count"), tol=D("0"), quiet=True)
        rep.ck("欠款户·" + g["name"] + "·最久天数", D(g["oldest"]), _num(r, "oldest_days"), tol=D("0"), quiet=True)
        if g["kind"] == "unit":
            lim = g.get("limit")
            rep.ck("欠款户·" + g["name"] + "·额度",
                   lim if lim is not None else D("0"),
                   _num(r, "limit") if r.get("limit") is not None else D("0"), quiet=True)
            rep.ck("欠款户·" + g["name"] + "·可用额度", g["credit_available"] or D("0"),
                   _num(r, "credit_available"), quiet=True)
            rep.ck("欠款户·" + g["name"] + "·超限", D(1 if g["over_limit"] else 0),
                   D(1 if r.get("over_limit") else 0), tol=D("0"), quiet=True)
    ar = api.get("/reports/arrears-summary?date_from=" + a.isoformat() + "&date_to=" + b.isoformat())
    ars = recompute_arrears_summary(db, a, b)
    print("|   info 挂账单位汇总口径：窗口内送达 + paid=0 初筛 + 按 arrears_unit_name 文本分组（不是时点余额）")
    rep.ck("挂账单位汇总·行数", D(len(ars["rows"])), D(len(ar)), tol=D("0"))
    rep.ck("挂账单位汇总·金额合计", ars["amount"], q2(sum((_num(r, "amount") for r in ar), D("0"))))
    rep.ck("挂账单位汇总·单数合计", D(ars["count"]), D(sum(int(_num(r, "count")) for r in ar)), tol=D("0"))
    api_ar = {str(r.get("name") or ""): r for r in ar}
    for g in ars["rows"]:
        r = api_ar.get(g["name"])
        if r is None:
            rep.ck("挂账单位·" + g["name"] + "（接口里没有这一行）", g["amount"], D("0"))
            continue
        rep.ck("挂账单位·" + g["name"] + "·金额", g["amount"], _num(r, "amount"), quiet=True)
        rep.ck("挂账单位·" + g["name"] + "·单数", D(g["count"]), _num(r, "count"), tol=D("0"), quiet=True)
    for nm in api_ar:
        if not any(g["name"] == nm for g in ars["rows"]):
            rep.ck("挂账单位·" + nm + "（重算里没有）", D("0"), _num(api_ar[nm], "amount"))
    invapi = api.get("/inventory/summary")
    api_kinds = sum(1 for r in invapi if dec(r.get("stock")) > 0)
    rep.ck("库存品种数", D(inv["kinds"]), D(api_kinds), tol=D("0"))
    print("|   info 库存金额（按 cost_price 计）：重算 " + money(inv["value"]))
    pv = api.get("/supplier-payables")
    rep.ck("我欠供应商", pay["unpaid"], q2(sum((_num(r, "unpaid") for r in pv), D("0"))))
    rep.ck("应付合计", pay["due"], q2(sum((_num(r, "amount") for r in pv), D("0"))))
    rep.ck("已付合计", pay["paid"], q2(sum((_num(r, "paid") for r in pv), D("0"))))

    # ---------------- 八、现金流量表与运营分析表 ----------------
    rep.head("八、现金流量表 + 运营分析表（司机 / 异常单）")
    cash = recompute_cash(db, a, b)
    cs = api.get("/cash-flows/summary?date_from=" + a.isoformat() + "&date_to=" + b.isoformat())
    rep.ck("现金·流入", cash["income"], _num(cs, "income"))
    rep.ck("现金·流出", cash["expense"], _num(cs, "expense"))
    rep.ck("现金·净额", cash["net"], _num(cs, "net"))
    rep.ck("现金·笔数", D(cash["count"]), _num(cs, "count"), tol=D("0"))
    cbk = api.get("/cash-flows/breakdown?date_from=" + a.isoformat() + "&date_to=" + b.isoformat())
    for k, v in sorted(cash["by_biz"].items(), key=lambda kv: -kv[1][0]):
        d0, biz = k.split("|", 1)
        bucket = "income" if d0 == "in" else "expense"
        rows_here = [r for r in (cbk.get(bucket) or []) if str(r.get("biz_type")) == biz]
        mine = v[0] if d0 == "in" else v[0]
        got = q2(sum((_num(r, "amount") for r in rows_here), D("0")))
        rep.ck("现金明细 " + d0 + "·" + biz, mine, got, quiet=True)
    dp = api.get("/stats/driver-performance?date_from=" + a.isoformat() + "&date_to=" + b.isoformat())
    api_drv = {int(r["driver_id"]): r for r in (dp.get("drivers") or [])}
    rep.ck("司机绩效·行数", D(len(drv)), D(len(api_drv)), tol=D("0"))
    for did, n in drv.items():
        r = api_drv.get(did)
        nm = (str(r.get("driver_name")) if r else "") + "#" + str(did)
        rep.ck("司机·" + nm + "·送达单数", D(n), _num(r or {}, "completed_count"), tol=D("0"), quiet=True)
        fw = bills["per_driver"].get(did, D("0")) - bills["settled_all_time"].get(did, D("0"))
        mine_owed = q2(fw if fw > 0 else D("0"))
        api_owed = _num(r or {}, "freight_owed") if (r or {}).get("freight_owed") is not None else D("0")
        rep.ck("司机·" + nm + "·待结运费", mine_owed, api_owed,
               kind_note="口径：已结按全时段结算单扣减", quiet=True)
        open_amt = bills["open_per_driver"].get(did, D("0"))
        if open_amt > api_owed + CENT:
            rep.bad("司机·" + nm + "·待结运费被历史付款抵掉",
                    "窗口内还没结的账单 " + money(open_amt) + "，页面显示 " + money(api_owed)
                    + "（页面口径 = 本期应得 − **全时段**已付结算单，老结算单会抵掉本期应付）")
    exa = b - timedelta(days=29)
    ex = api.get("/stats/exception-orders?date_from=" + exa.isoformat() + "&date_to=" + b.isoformat())
    exc = recompute_exceptions(db, exa, b)
    rep.ck("异常单条数（近 30 天）", D(exc["total"]), D(len(ex)), tol=D("0"))
    print("|   info 其中：库里标了异常的 " + str(exc["explicit"]) + " 条 + 自动规则捞出的 "
          + str(exc["auto"]) + " 条（窗口列是 order_date，不是送达日）")

    # ---------------- 九、口径自相矛盾（真错） ----------------
    rep.head("九、口径自相矛盾（同一笔钱在两处出现）")
    dmg_exp = exp["per_category"].get("货损", D("0"))
    if dmg_exp:
        rep.bad("货损：同一笔损失在商品成本与期间费用里各算一次",
                "坏掉那几件仍留在「商品成本」里（净数量不减货损，COGS 一侧多留 "
                + money(s["damage_in_cogs"]) + "），开销单又按成本快照记了一笔 "
                + money(dmg_exp) + " → 营业利润被多扣 " + money(dmg_exp))

    return {"sales": s, "bills": bills, "exp": exp, "dep": dep, "tax": tax,
            "balances": b2, "cash": cash, "inventory": inv, "payables": pay, "drivers": drv}


# =====================================================================
# 主流程
# =====================================================================
def build_windows(today: date):
    """三个窗口：上周（整周）/ 本月到今天 / 上月（整月）—— 都是 App 真会传的区间形状。"""
    this_monday = today - timedelta(days=today.weekday())
    prev_monday = this_monday - timedelta(days=7)
    last_end = date(today.year, today.month, 1) - timedelta(days=1)
    last_start = date(last_end.year, last_end.month, 1)
    return [
        ("上周（整周）", prev_monday, prev_monday + timedelta(days=6), "prev"),
        ("本月到今天", date(today.year, today.month, 1), today, "this"),
        ("上月（整月）", last_start, last_end, "lastmonth"),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="报表中心独立重算对账探针（GOV-0005）")
    ap.add_argument("--db", default="backend/sorders.db", help="开发库 SQLite 路径")
    ap.add_argument("--base", default="http://127.0.0.1:8000", help="后端地址")
    ap.add_argument("--phone", default="13800000001")
    ap.add_argument("--password", default="pass12345")
    ap.add_argument("--window", default="all", choices=["all", "prev", "this", "lastmonth"])
    ap.add_argument("--json", default="", help="把逐项结果写到这个 JSON 文件")
    args = ap.parse_args()

    today = business_today()
    db = Db(args.db)
    api = Api(args.base, args.phone, args.password)
    rep = Report()

    print("=" * 74)
    print("报表中心·独立重算对账（绕开报表服务，直接读原始表重算）")
    print("  开发库   ：" + args.db)
    print("  后端     ：" + args.base)
    print("  业务今天 ：" + today.isoformat() + "（东八区）")
    print("=" * 74)

    wins = [w for w in build_windows(today) if args.window in ("all", w[3])]
    results = {}
    for label, a, b, key in wins:
        results[key] = check_window(db, api, rep, label, a, b)

    # ---------------- 附：补录采购单的时间戳诊断 ----------------
    rep.head("附、补录历史采购单的时间戳诊断（影响「本期加权均价」能不能取到）")
    diag = close_orders_probe(db)
    print("|   info 有价入库流水（source=PURCHASE 且 change>0 且有单价）：" + str(diag["priced_inbound"]) + " 条")
    print("|   info 其中「流水生成日 晚于 采购单日期」的：" + str(diag["backdated"]) + " 条")
    for r in diag["detail"]:
        print("|      采购单日期 " + str(r["doc_date"]) + " → 流水生成日 " + str(r["created_day"])
              + "（" + str(r["n"]) + " 条）")
    if diag["backdated"]:
        rep.bad("补录历史采购单：入库流水的时间戳是「录单那一刻」而不是采购单日期",
                str(diag["backdated"]) + " 条入库流水的业务日晚于采购单日期 → 这些进货价在采购单"
                "那一天所属的窗口里取不到「本期加权均价」，毛利会静默退回订单快照那一级"
                "（purchase_service 写 inventory_movements 用的是此刻）")

    # ---------------- 算错清单 ----------------
    errs = rep.errs()
    print("")
    print("=" * 74)
    print("算错清单（同一件事两个数）")
    print("=" * 74)
    if not errs:
        print("  没有。全部对账项通过或属可解释的口径差。")
    else:
        for r in errs:
            print("  !! " + r["section"] + " / " + r["label"]
                  + "：重算 " + money(r["indep"]) + " vs 接口 " + money(r["api"])
                  + "  差 " + money(r["diff"]) + ("  " + r["note"] if r["note"] else ""))
    kinds = {"OK": 0, "口径": 0, "错": 0}
    for r in rep.rows:
        kinds[r["kind"]] += 1
    print("")
    print("对账项合计：" + str(len(rep.rows)) + " 项 —— 相等 " + str(kinds["OK"])
          + " / 口径差 " + str(kinds["口径"]) + " / 算错 " + str(kinds["错"]))
    if results:
        last = results[wins[-1][3]]
        print("")
        print("同型缺陷金额（只看最后一个窗口的明细）：")
        print("  货损件数的成本被留在商品成本里（COGS 一侧）：" + money(last["sales"]["damage_in_cogs"]))
        print("  同一批货损又在期间费用里记了一笔（开销一侧）："
              + money(last["exp"]["per_category"].get("货损", D("0"))))
    print("=" * 74)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"today": today.isoformat(),
                       "windows": {w[3]: {"from": w[1].isoformat(), "to": w[2].isoformat()} for w in wins},
                       "checks": [{"section": r["section"], "label": r["label"],
                                   "indep": str(r["indep"]), "api": str(r["api"]),
                                   "diff": str(r["diff"]), "kind": r["kind"], "note": r["note"]}
                                  for r in rep.rows],
                       "backdated_purchase_inbound": diag["backdated"]}, fh,
                      ensure_ascii=False, indent=1)
        print("逐项结果已写入 " + args.json)

    db.close()
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
