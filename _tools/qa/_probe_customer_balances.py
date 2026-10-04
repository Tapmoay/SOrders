"""FEAT-0015 第五期「应收账龄与客户信用」真库探针（只读报表 + 额度写侧）。

### 为什么必须打真库
这一期的两个东西都是「看起来对、其实差一个口径」的类型，单测与假库都抓不住：

1. **账龄锚点是「最早一笔记账日」，不是送达日**：真库里一张单可能有多笔账本行
   （送达自动入账一行；红冲 RETURN 只冲金额、手工 MANUAL 行不挂订单）。
   只有真库才有这些真实的行组合，才验得出「改最早那笔 ⇒ 桶变；只改后面那笔 ⇒ 桶不变」。
2. **预收要直插流水**：没有「多收客户的钱」这个端点（收款端点的金额必须等于订单应收），
   所以预收只能像 backend/tests/test_customer_balances.py 那样直接写 cash_flows。
3. **额度改一次留一次痕**：真库里有 1700+ 条历史 operation_logs，只有真库能确认
   「ARREARS_UNIT_CREDIT_LIMIT 的 payload 是**文本**（\"1000.00\"）而不是 JSON 数字」——
   这正是审计页能照着回查的前提。
4. **报表里还有 400 多张真实送达单**：本探针所有金额断言都用**差值口径**
   （造单前读基线，造完再读），并用 include_orders=true 的 orders[].order_id
   **按单号认自己的行**，绝不按名字猜行——真库里有别人的同名行、有真实挂账单位。

### 它验什么（八组，共 150 余条；每条都读库或读另一条接口，不靠响应体里那句「看起来对」）
① 一行一个债务人：四种凭证（挂账单位 / 单位名快照 / 货主 / 临时货主 / 未填货主）逐条核 kind；
   单位行带 customer_names；不填货主那行必须叫「未填货主」而不是「未分配挂账单位」；
   单位改名 ⇒ 行名跟着变；单位 id 被清掉 ⇒ 靠 arrears_unit_name 快照认人（kind=unit_name）。
② 正欠款进四桶（0/1/30/31/60/61/90/91 天边界逐个核）、负数/零不进桶、预收单列 prepaid；
   已收款单不进报表。
③ 锚点 = 最早一笔记账日：插一条 45 天前的账 ⇒ 天数/桶跟着变；只改送达那笔 ⇒ 不变；
   RETURN 红冲行不参与锚点。
④ 恒等式与到分：逐行 balance == Σ四桶 − prepaid；totals == Σ行；报文里所有金额串两位小数。
⑤ 报表日是时点：昨天口径看不见今天送达的单（与开场基线逐分相等）；未来日期被夹回今天；
   日期顺序反 ⇒ 400；非法日期 ⇒ 422。
⑥ 跨口径对拍：/reports/turnover 的 arrears_total 与 /reports/customer-balances 的
   totals.balance 在**差值**上相等，且这个差值等于我这批单的手算值。
⑦ 额度三态与留痕：NULL（不限）/ 1000.00 / 0 三态出参语义不同；改一次留一次痕、
   同值重发不留第二条、清空留 null 痕；超限只是提示（照样下单、照样送达）。
⑧ 逐单明细与导出：include_orders=true 时每行 orders 的
   票号/送达日/应收/已收/欠款/账龄起点/天数/桶/货主名 与库 + order_money 口径逐个对账；
   导出端点（kind=customer-balances）的 xlsx 里含探针单位那一行、含「不限额」与「超了」。

### 隔离（只碰自己造的行）
本探针造的所有行都带专属前缀 `探针CB-` + 本轮 RUN 时间戳：
挂账单位 4 个、客户 1 个、货主账号 1 个（软删）、订单十余张（全部走真端点：
POST /orders → /assign → /driver-ack → /charge → /complete）。
端点没有口子的三处用 sqlite3 直写，且只写自己造的 order_id / 单位：
  (a) 预收流水（cash_flows，direction='in' + biz_type='RECEIPT_PREPAID'）；
  (b) 锚点 fixture（ledgers 直插一行 45 天前的 ORDER 行与一行早期的 RETURN 行）；
  (c) 改 ledgers.entry_date 造 0/1/30/31/60/61/90/91 天边界；清掉自己那一单的
      temp_shipper_name / arrears_unit_id 造「未填货主」与「单位名快照」两种凭证。
跑完（默认）按前缀硬删：cash_flows / ledgers / driver_bills / inventory_movements /
operation_logs / order_products → orders → arrears_units → customers，
再按 id 精确删 notifications / usage_counters / 额度留痕日志，最后软删探针账号。
⛔ 不 DELETE/UPDATE 任何非探针行（真库里有真实业务数据）。

用法：
  python -u _tools/qa/_probe_customer_balances.py            # 跑完还原（默认）
  python -u _tools/qa/_probe_customer_balances.py --keep     # 留现场
证据（每组的报表原文 + 清理台账）落在 _tmp/ev/customer_balances_<RUN>_*.json。
"""

from __future__ import annotations

import argparse
import io
import json
import random
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
BASE = "http://127.0.0.1:8000/api/v1"
HEALTH = "http://127.0.0.1:8000/health"
DB = ROOT / "backend/sorders.db"
EV = ROOT / "_tmp/ev"
PHONE, PASSWORD = "13800000001", "pass12345"  # 开发库测试号 backend/scripts/reset_dev_passwords.py
DRIVER_PHONE = "13800000003"
RUN = time.strftime("%m%d%H%M%S")
TAG = "探针CB-"
CST = timezone(timedelta(hours=8))
BUCKET_KEYS = ("0_30", "31_60", "61_90", "over_90")
UNKNOWN_NAME = "未填货主"
TURNOVER_UNKNOWN = "未分配挂账单位"

BAD: list[str] = []
TOTAL = [0]
C: dict[str, Any] = {"orders": {}, "created_users": []}
SEEN: dict[str, set[int]] = {
    t: set()
    for t in (
        "orders",
        "order_products",
        "ledgers",
        "cash_flows",
        "driver_bills",
        "inventory_movements",
        "operation_logs",
        "notifications",
        "arrears_units",
        "customers",
        "usage_counters",
    )
}


class Abort(Exception):
    """探针中途造不出前置数据时直接收工（照实报，不硬凑）。"""


# --------------------------------------------------------------------------
# 基础设施（照 _tools/qa/_probe_tax_invoices.py 的骨架）
# --------------------------------------------------------------------------
def today_cst() -> date:
    return datetime.now(CST).date()


def q2(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def bucket_of(days: int) -> str:
    if days <= 30:
        return "0_30"
    if days <= 60:
        return "31_60"
    if days <= 90:
        return "61_90"
    return "over_90"


def _fetch(method: str, path: str, token: str | None = None, body: Any = None):
    url = path if path.startswith("http") else BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)
    except Exception as e:  # noqa: BLE001
        return -1, str(e).encode("utf-8"), {}


def call(method: str, path: str, token: str | None = None, body: Any = None):
    st, raw, _ = _fetch(method, path, token, body)
    txt = raw.decode("utf-8", "replace")
    try:
        return st, (json.loads(txt) if txt.strip() else None)
    except Exception:  # noqa: BLE001
        return st, txt[:400]


def rows(sql: str, args=()) -> list[list]:
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    try:
        return [list(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def one(sql: str, args=()):
    r = rows(sql, args)
    return r[0] if r else None


def count(sql: str, args=()) -> int:
    return int(one(sql, args)[0])


def wsql(sql: str, args=()) -> int:
    """可写连接：只用于本探针自己造的行（端点造不出来的 fixture 与清理）。"""
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        cur = con.execute(sql, args)
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def check(label: str, cond: Any, detail: Any = "") -> bool:
    TOTAL[0] += 1
    ok = bool(cond)
    print("  [%s] %s —— %s" % ("OK" if ok else "FAIL", label, detail))
    if not ok:
        BAD.append(label)
    return ok


def ev(name: str, payload: Any) -> None:
    EV.mkdir(parents=True, exist_ok=True)
    p = EV / ("customer_balances_%s_%s.json" % (RUN, name))
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("  → 证据 %s" % p.relative_to(ROOT))


def m(v):
    return None if v is None else Decimal(str(v))


def dd(now, before):
    return m(now) - m(before)


def detail_of(body) -> str:
    if isinstance(body, dict):
        d = body.get("detail") or body
        return json.dumps(d, ensure_ascii=False)[:300] if isinstance(d, (dict, list)) else str(d)[:300]
    return str(body)[:300]


def flt(d: date) -> str:
    return d.isoformat()


def _biz_date(v) -> str:
    """库里 delivered_at 存的是 **UTC naive**；报表的「送达日」是**业务当地日**（UTC+8）。"""
    if v is None:
        return ""
    if isinstance(v, datetime):
        dt = v
    else:
        s = str(v).strip()
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return s[:10]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CST).date().isoformat()


_ENTS = (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&"))


def _xml_text(s: str) -> str:
    """xlsx 里 openpyxl 把中文写成 XML 数字实体（&#23458;…）：先还原成真字符再查关键词，
    否则「导出里有没有这一行」会因为编码而红，而不是因为逻辑。"""
    s = re.sub(r"&#(\d+);", lambda mo: chr(int(mo.group(1))), s)
    for k, v in _ENTS:
        s = s.replace(k, v)
    return s


# --------------------------------------------------------------------------
# 报表 / 订单 / 主数据
# --------------------------------------------------------------------------
def read_balances(day: str | None = None, include_orders: bool = True, **extra):
    q = {"mode": "day", "date": day or C["as_of"], "include_orders": "true" if include_orders else "false"}
    q.update(extra)
    return call("GET", "/reports/customer-balances?" + urllib.parse.urlencode(q), token=C["tok"])


def read_turnover():
    q = {"mode": "day", "date": C["as_of"], "date_from": "1970-01-01", "date_to": C["as_of"]}
    return call("GET", "/reports/turnover?" + urllib.parse.urlencode(q), token=C["tok"])


def row_of(data, oid):
    """按订单号在报表里认自己的单落在哪一行（真库里有别人的行，按名字猜会撞）。"""
    for row in (data or {}).get("rows", []):
        for item in row.get("orders") or []:
            if int(item.get("order_id", -1)) == int(oid):
                return row, item
    return None, None


def all_order_ids(data) -> set[int]:
    return {
        int(it["order_id"])
        for r in (data or {}).get("rows", [])
        for it in (r.get("orders") or [])
    }


def my_ids() -> set[int]:
    return {int(o["id"]) for o in C["orders"].values()}


def mk_unit(name: str, phone: str = "") -> dict:
    st, r = call("POST", "/arrears-units", token=C["tok"], body={"name": name, "phone": phone})
    if st not in (200, 201) or not isinstance(r, dict):
        raise Abort("建挂账单位 %s ⇒ %s %s" % (name, st, detail_of(r)))
    SEEN["arrears_units"].add(int(r["id"]))
    return {"id": int(r["id"]), "name": r.get("name") or name, "phone": r.get("phone") or ""}


def mk_shipper_user(name: str) -> dict:
    phone = "13" + "".join(random.choice("0123456789") for _ in range(9))
    st, r = call(
        "POST",
        "/users",
        token=C["tok"],
        body={"phone": phone, "password": "123321", "full_name": name, "role": "shipper"},
    )
    if st not in (200, 201) or not isinstance(r, dict):
        raise Abort("建探针货主账号 ⇒ %s %s" % (st, detail_of(r)))
    uid = int(r["id"])
    C["created_users"].append(uid)
    full = (r.get("full_name") or "").strip() or phone
    return {"id": uid, "full_name": full, "phone": phone}


def mk_customer(name: str, *, user_id: int, unit_id: int) -> dict:
    st, r = call(
        "POST",
        "/customers",
        token=C["tok"],
        body={"kind": "registered", "user_id": int(user_id), "name": name, "arrears_unit_id": int(unit_id)},
    )
    if st not in (200, 201) or not isinstance(r, dict):
        raise Abort("建探针客户 ⇒ %s %s" % (st, detail_of(r)))
    if (r.get("name") or "") != name:
        raise Abort("POST /customers 返回的是别人的客户档案（去重命中）：%s" % r.get("name"))
    SEEN["customers"].add(int(r["id"]))
    return r


def mk_order(key: str, *, shipper_id=None, temp=None, amount="100.00", goods=None) -> tuple:
    body: dict[str, Any] = {
        "lines": [{"product_name_snapshot": goods or (TAG + "货-" + RUN), "quantity": 1, "unit_price": amount}],
        "delivery_description": TAG + key + "-" + RUN,
    }
    if shipper_id is not None:
        body["shipper_id"] = int(shipper_id)
    if temp is not None:
        body["temp_shipper_name"] = temp
    st, r = call("POST", "/orders", token=C["tok"], body=body)
    if st != 201 or not isinstance(r, dict):
        return None, "POST /orders ⇒ %s %s" % (st, detail_of(r))
    oid = int(r["id"])
    SEEN["orders"].add(oid)
    rec = {"key": key, "id": oid, "order_no": r.get("order_no"), "amount": Decimal(amount)}
    C["orders"][key] = rec
    return rec, ""


def deliver(key: str, *, unit_id=None, unit_name=None, collect_cash=True, payment="arrears") -> str:
    o = C["orders"][key]
    oid = o["id"]
    st, r = call(
        "POST",
        "/orders/%d/assign" % oid,
        token=C["tok"],
        body={"driver_id": C["driver_id"], "collect_cash": collect_cash, "freight_fee": "60.00"},
    )
    if st != 200:
        return "派单 ⇒ %s %s" % (st, detail_of(r))
    st, r = call("POST", "/orders/%d/driver-ack" % oid, token=C["dtok"])
    if st not in (200, 201, 204):
        return "司机接单 ⇒ %s %s" % (st, detail_of(r))
    if unit_id is not None or unit_name:
        payload: dict[str, Any] = {}
        if unit_id is not None:
            payload["arrears_unit_id"] = int(unit_id)
        if unit_name:
            payload["arrears_unit_name"] = unit_name
        st, r = call("POST", "/orders/%d/charge" % oid, token=C["tok"], body=payload)
        if st != 200:
            return "挂账 ⇒ %s %s" % (st, detail_of(r))
    st, r = call(
        "POST",
        "/orders/%d/complete" % oid,
        token=C["dtok"],
        body={"payment": payment, "delivery_photo_urls": ["/static/uploads/delivery/probe-cb.jpg"]},
    )
    if st not in (200, 201, 204):
        return "送达 ⇒ %s %s" % (st, detail_of(r))
    o["delivered"] = True
    return ""


def make(key: str, **kw) -> str:
    need_keys = {k: kw.pop(k) for k in ("shipper_id", "temp", "amount", "goods") if k in kw}
    o, err = mk_order(key, **need_keys)
    if err:
        return err
    return deliver(key, **kw)


def need(err: str, what: str) -> None:
    if err:
        raise Abort("%s 失败：%s" % (what, err))


def add_ledger_row(oid: int, entry_date: date, source: str, total: str, note: str) -> int:
    """直插一条账本行（端点造不出来：POST /ledger/entries 只许 source=MANUAL 且强制 order_id=None）。
    只插到本探针自己造的订单上；order_product_id=NULL ⇒ 不会撞 uq_ledgers_order_product_source。"""
    o = one("select shipper_id, temp_shipper_name from orders where id=?", (oid,))
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        cur = con.execute(
            "insert into ledgers (shipper_id, temp_shipper_name, entry_date, product_name, quantity, unit_price,"
            " total, order_id, order_product_id, product_id, source, note, cost_price_snapshot, customer_id)"
            " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (o[0], o[1], flt(entry_date), TAG + "锚点账-" + RUN, 1, total, total, oid, None, None, source, note, "0", None),
        )
        con.commit()
        lid = int(cur.lastrowid)
    finally:
        con.close()
    SEEN["ledgers"].add(lid)
    return lid


def add_prepaid_flow(oid: int, amount: str, party_name: str) -> int:
    """直插一条预收流水（direction='in' + biz_type='RECEIPT_PREPAID'）。
    理由：没有任何端点能「多收客户的钱」（收款端点金额必须等于订单应收），
    backend/tests/test_customer_balances.py:212-217 造预收也是直接写库。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        cur = con.execute(
            "insert into cash_flows (flow_date, direction, amount, party_type, party_id, party_name, channel,"
            " biz_type, order_id, doc_id, note, operator_id, created_at, updated_at, is_deleted)"
            " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (C["as_of"], "in", amount, "customer", None, party_name, "transfer", "RECEIPT_PREPAID", oid,
             None, TAG + "预收流水-" + RUN, C["uid"], now, now, 0),
        )
        con.commit()
        fid = int(cur.lastrowid)
    finally:
        con.close()
    SEEN["cash_flows"].add(fid)
    return fid

# --------------------------------------------------------------------------
# ① 一行一个债务人
# --------------------------------------------------------------------------
def g1_debtors() -> None:
    print("\n=== ① 一行一个债务人：四种凭证各造一单（一律按 orders[].order_id 认自己的单） ===")
    u1 = mk_unit(TAG + "欠款单位-" + RUN, phone="13900001111")
    C["u1_name"] = u1["name"]
    s = mk_shipper_user(TAG + "货主-" + RUN)
    C["shipper_uid"], C["shipper_name"], C["shipper_phone"] = s["id"], s["full_name"], s["phone"]
    mk_customer(TAG + "客户-" + RUN, user_id=s["id"], unit_id=u1["id"])
    C["temp_name"] = TAG + "临时货主-" + RUN
    check("①-前置 探针货主账号建好了（role=shipper）", C["shipper_uid"] > 0, "uid=%s phone=%s name=%s" % (s["id"], s["phone"], s["full_name"]))

    need(make("SHIP", shipper_id=s["id"]), "① 货主凭证单")
    need(make("TEMP", temp=C["temp_name"]), "① 临时货主凭证单")
    need(make("UNIT", shipper_id=s["id"], unit_id=u1["id"]), "① 挂账单位凭证单")
    need(make("UNKN", temp=TAG + "待清空货主-" + RUN), "① 未填货主凭证单")
    o_unk = C["orders"]["UNKN"]["id"]
    rc = wsql("update orders set temp_shipper_name=NULL where id=?", (o_unk,))
    check("①-0 库里清掉「未填货主」那一单的临时货主名（端点不许两者都不给，只能这样造）", rc == 1, "rowcount=%s" % rc)
    check(
        "①-0b 库里确实清空了（shipper_id/temp_shipper_name 都为空）",
        one("select shipper_id, temp_shipper_name from orders where id=?", (o_unk,)) == [None, None],
        one("select shipper_id, temp_shipper_name from orders where id=?", (o_unk,)),
    )

    st, data = read_balances()
    ev("g1_debtors", data)
    if st != 200 or not isinstance(data, dict):
        raise Abort("报表读不到：%s %s" % (st, detail_of(data)))
    rows_ = data["rows"]
    r_ship, _ = row_of(data, C["orders"]["SHIP"]["id"])
    r_temp, _ = row_of(data, C["orders"]["TEMP"]["id"])
    r_unit, _ = row_of(data, C["orders"]["UNIT"]["id"])
    r_unk, _ = row_of(data, o_unk)
    check("①-a 货主凭证 ⇒ kind=shipper", bool(r_ship) and r_ship["kind"] == "shipper", r_ship and (r_ship["kind"], r_ship["name"]))
    check("①-b 货主行名 = 探针货主账号 full_name", bool(r_ship) and r_ship["name"] == C["shipper_name"], r_ship and r_ship["name"])
    check("①-c 货主行电话 = 探针货主手机号", bool(r_ship) and r_ship["phone"] == C["shipper_phone"], r_ship and r_ship["phone"])
    check(
        "①-d 临时货主凭证 ⇒ kind=temp 且行名 = 临时货主名",
        bool(r_temp) and r_temp["kind"] == "temp" and r_temp["name"] == C["temp_name"],
        r_temp and (r_temp["kind"], r_temp["name"]),
    )
    check(
        "①-e 挂账单位凭证 ⇒ kind=unit 且 unit_id 对得上",
        bool(r_unit) and r_unit["kind"] == "unit" and r_unit["unit_id"] == u1["id"],
        r_unit and (r_unit["kind"], r_unit.get("unit_id")),
    )
    check("①-f 单位行名 = 单位名", bool(r_unit) and r_unit["name"] == u1["name"], r_unit and r_unit["name"])
    check("①-g 单位行电话 = 单位电话 13900001111", bool(r_unit) and r_unit["phone"] == "13900001111", r_unit and r_unit["phone"])
    check(
        "①-h 不填货主 ⇒ kind=unknown 且行名是「未填货主」",
        bool(r_unk) and r_unk["kind"] == "unknown" and r_unk["name"] == UNKNOWN_NAME,
        r_unk and (r_unk["kind"], r_unk["name"]),
    )
    check(
        "①-i ⛔ 全表没有任何行叫「未分配挂账单位」（那是 turnover 口径，这张表必须叫「未填货主」）",
        all(TURNOVER_UNKNOWN not in (r["name"] or "") for r in rows_),
        [r["name"] for r in rows_ if TURNOVER_UNKNOWN in (r["name"] or "")],
    )
    check(
        "①-j 单位行 customer_names 带出该单位下真实客户名册（本探针客户的 label）",
        bool(r_unit) and C["shipper_name"] in (r_unit.get("customer_names") or []),
        r_unit and r_unit.get("customer_names"),
    )
    check(
        "①-k customer_names 去重且有序（该单位本轮只有 1 个客户）",
        bool(r_unit) and r_unit.get("customer_names") == [C["shipper_name"]],
        r_unit and r_unit.get("customer_names"),
    )
    check(
        "①-l 单位行余额 100.00 / 单数 1（只有挂到它名下的那一单）",
        bool(r_unit) and m(r_unit["balance"]) == Decimal("100.00") and int(r_unit["order_count"]) == 1,
        r_unit and (r_unit["balance"], r_unit["order_count"]),
    )
    four = {C["orders"][k]["id"] for k in ("SHIP", "TEMP", "UNIT", "UNKN")}
    check(
        "①-m 四张凭证单各自只出现在一行里（4 张单 = 4 条明细，没有重复计数）",
        sum(1 for r in rows_ for it in (r.get("orders") or []) if int(it["order_id"]) in four) == 4,
        sum(1 for r in rows_ for it in (r.get("orders") or []) if int(it["order_id"]) in four),
    )

    newname = u1["name"] + "-改名"
    st, resp = call("PATCH", "/arrears-units/%d" % u1["id"], token=C["tok"], body={"name": newname})
    check("①-n PATCH /arrears-units/{id} 改名 ⇒ 200", st == 200, "%s %s" % (st, detail_of(resp)))
    C["u1_new_name"] = newname
    st, data2 = read_balances()
    r2u, _ = row_of(data2, C["orders"]["UNIT"]["id"])
    check(
        "①-o 报表行名跟着单位改名（说明按 unit_id 现查名字，不是报表缓存了旧名）",
        bool(r2u) and r2u["kind"] == "unit" and r2u["name"] == newname,
        r2u and (r2u["kind"], r2u["name"]),
    )

    rc = wsql("update orders set arrears_unit_id=NULL where id=?", (C["orders"]["UNIT"]["id"],))
    check("①-p 库里清掉这一单的 arrears_unit_id（保留挂账时写下的 arrears_unit_name 快照）", rc == 1, "rowcount=%s" % rc)
    snap = one("select arrears_unit_name, arrears_unit_id from orders where id=?", (C["orders"]["UNIT"]["id"],))
    check("①-q 库里这一单的 arrears_unit_name 快照还在（= 挂账那一刻的名字）", snap == [u1["name"], None], snap)
    st, data3 = read_balances()
    r3u, _ = row_of(data3, C["orders"]["UNIT"]["id"])
    check(
        "①-r 单位 id 没了 ⇒ 靠 arrears_unit_name 快照认出 kind=unit_name",
        bool(r3u) and r3u["kind"] == "unit_name",
        r3u and (r3u["kind"], r3u["name"]),
    )
    check("①-s 快照行的名字 = 挂账那一刻的单位名（改名前的旧名）", bool(r3u) and r3u["name"] == u1["name"], r3u and r3u["name"])
    check("①-t 快照行不带 unit_id（单位实体已经认不出来了）", bool(r3u) and r3u.get("unit_id") is None, r3u and r3u.get("unit_id"))
    check("①-u 原来那个 unit 行整行消失（该单位名下已经没有单了）", all(r.get("unit_id") != u1["id"] for r in data3["rows"]), [r["name"] for r in data3["rows"] if r.get("unit_id") == u1["id"]])
    r3s, _ = row_of(data3, C["orders"]["SHIP"]["id"])
    check(
        "①-v 快照行只扛自己那一单：货主行没有被带走（仍 1 单 100.00）",
        bool(r3s) and int(r3s["order_count"]) == 1 and m(r3s["balance"]) == Decimal("100.00"),
        r3s and (r3s["order_count"], r3s["balance"]),
    )


# --------------------------------------------------------------------------
# ② 四桶边界 / 负数与零不进桶 / 预收单列
# --------------------------------------------------------------------------
def g2_buckets() -> None:
    print("\n=== ② 正欠款进四桶、负数与零不进桶、预收单列（SQL 造 0/1/30/31/60/61/90/91 天边界） ===")
    u2 = mk_unit(TAG + "账龄单位-" + RUN, phone="13900002222")
    C["u2"], C["u2_name"] = u2, u2["name"]
    offsets = [0, 1, 30, 31, 60, 61, 90, 91]
    rcs = []
    for off in offsets:
        key = "AGE%d" % off
        need(make(key, shipper_id=C["shipper_uid"], unit_id=u2["id"], amount="100.00"), "② 边界单 %d 天" % off)
        rc = wsql(
            "update ledgers set entry_date=? where order_id=? and source='ORDER'",
            (flt(C["as_of_date"] - timedelta(days=off)), C["orders"][key]["id"]),
        )
        rcs.append(rc)
    check("②-0 八张边界单的 entry_date 各改中 1 行（只动自己单的账本行）", rcs == [1] * len(offsets), rcs)

    need(make("PRE", shipper_id=C["shipper_uid"], unit_id=u2["id"], amount="100.00"), "② 预收单")
    pre_id = C["orders"]["PRE"]["id"]
    fid = add_prepaid_flow(pre_id, "150.00", u2["name"])
    flow = one("select direction, biz_type, amount, order_id from cash_flows where id=?", (fid,))
    check(
        "②-0b 预收流水落库（直插 cash_flows：direction='in' + biz_type='RECEIPT_PREPAID' + 金额到分）",
        flow is not None
        and flow[0] == "in"
        and flow[1] == "RECEIPT_PREPAID"
        and m(flow[2]) == Decimal("150.00")
        and int(flow[3]) == pre_id,
        flow,
    )
    need(make("PAID", temp=TAG + "已收款临时货主-" + RUN, amount="100.00", collect_cash=True, payment="cash"), "② 已收款单")
    paid_id = C["orders"]["PAID"]["id"]

    st, data = read_balances()
    ev("g2_buckets", data)
    if st != 200 or not isinstance(data, dict):
        raise Abort("报表读不到：%s %s" % (st, detail_of(data)))
    r2, _ = row_of(data, C["orders"]["AGE0"]["id"])
    check(
        "②-a 账龄单位那一行认出来了（kind=unit + unit_id 对得上）",
        bool(r2) and r2["kind"] == "unit" and r2["unit_id"] == u2["id"],
        r2 and (r2["kind"], r2.get("unit_id")),
    )
    want = {"0_30": "300.00", "31_60": "200.00", "61_90": "200.00", "over_90": "100.00"}
    for k in BUCKET_KEYS:
        check(
            "②-b 桶 %s = %s（0/1/30 天在 0_30；31/60 在 31_60；61/90 在 61_90；91 在 over_90）" % (k, want[k]),
            bool(r2) and m(r2["buckets"][k]) == Decimal(want[k]),
            r2 and r2["buckets"],
        )
    for off in offsets:
        key = "AGE%d" % off
        _, item = row_of(data, C["orders"][key]["id"])
        check(
            "②-c 单 %d 天：明细 days=%d" % (off, off),
            bool(item) and int(item["days"]) == off,
            item and item["days"],
        )
        check(
            "②-d 单 %d 天：明细 bucket=%s" % (off, bucket_of(off)),
            bool(item) and item["bucket"] == bucket_of(off),
            item and item["bucket"],
        )
    check("②-e oldest_days 取最老那一笔（91 天）", bool(r2) and int(r2["oldest_days"]) == 91, r2 and r2["oldest_days"])
    check(
        "②-f 单位行余额 = 800.00 − 50.00 预收 = 750.00（预收把余额冲掉一半）",
        bool(r2) and m(r2["balance"]) == Decimal("750.00"),
        r2 and r2["balance"],
    )
    check("②-g 单位行「其中预收」= 50.00（只有超收那一单贡献）", bool(r2) and m(r2["prepaid"]) == Decimal("50.00"), r2 and r2["prepaid"])
    check(
        "②-h 四桶合计 = 800.00（预收不从桶里扣：桶只装正欠款）",
        bool(r2) and sum(m(v) for v in r2["buckets"].values()) == Decimal("800.00"),
        bool(r2) and sum(m(v) for v in r2["buckets"].values()),
    )
    _, pre_item = row_of(data, pre_id)
    check("②-i 预收单明细 arrears = 100.00 − 150.00 = −50.00", bool(pre_item) and m(pre_item["arrears"]) == Decimal("-50.00"), pre_item and pre_item["arrears"])
    check("②-j 预收单明细 bucket 是空串（负数不进任何桶）", bool(pre_item) and pre_item["bucket"] == "", pre_item and repr(pre_item["bucket"]))
    check("②-k 已收款单不出现在任何一行的明细里（一分钱不欠的不进报表）", paid_id not in all_order_ids(data), sorted(all_order_ids(data))[:5])
    check(
        "②-l 已收款单的临时货主名也没在报表里冒出空行",
        all(TAG + "已收款" not in (r["name"] or "") for r in data["rows"]),
        [r["name"] for r in data["rows"] if TAG + "已收款" in (r["name"] or "")],
    )
    check(
        "②-m 库里这一单确实是现场收现金（paid=1 / payment_method=cash）",
        one("select paid, payment_method from orders where id=?", (paid_id,)) == [1, "cash"],
        one("select paid, payment_method from orders where id=?", (paid_id,)),
    )
    paid_total = q2(one("select coalesce(sum(line_total),0) from order_products where order_id=?", (paid_id,))[0])
    paid_in = q2(one("select coalesce(sum(amount),0) from cash_flows where order_id=? and direction='in' and is_deleted=0", (paid_id,))[0])
    paid_flag = int(one("select paid from orders where id=?", (paid_id,))[0] or 0)
    settled = paid_in if paid_in else (paid_total if paid_flag else Decimal("0.00"))
    check(
        "②-n 库里这一单没有欠款（order_money 口径：应收 %s = 已收 %s）" % (paid_total, settled),
        settled == paid_total and paid_total == Decimal("100.00"),
        "流水入账=%s / paid=%s" % (paid_in, paid_flag),
    )


# --------------------------------------------------------------------------
# ③ 锚点 = 最早一笔记账日
# --------------------------------------------------------------------------
def g3_anchor() -> None:
    print("\n=== ③ 账龄锚点 = 最早一笔记账日（不是送达日；红冲只冲金额不冲起点） ===")
    oid = C["orders"]["AGE0"]["id"]
    st, data = read_balances()
    _, item = row_of(data, oid)
    check(
        "③-a 起点：这一单 days=0 / bucket=0_30（送达当天入账）",
        bool(item) and int(item["days"]) == 0 and item["bucket"] == "0_30",
        item and (item["days"], item["bucket"], item["anchor"]),
    )
    add_ledger_row(oid, C["as_of_date"] - timedelta(days=45), "ORDER", "0", TAG + "锚点第二笔-" + RUN)
    check("③-b 库里这一单多了第二笔记账（45 天前，金额 0）", count("select count(*) from ledgers where order_id=?", (oid,)) == 2, count("select count(*) from ledgers where order_id=?", (oid,)))
    st, data = read_balances()
    r2, item = row_of(data, oid)
    check("③-c 锚点跟着最早那笔走：days 从 0 变 45", bool(item) and int(item["days"]) == 45, item and (item["days"], item["anchor"]))
    check("③-d 桶跟着变 31_60（同一笔钱换了桶）", bool(item) and item["bucket"] == "31_60", item and item["bucket"])
    check("③-e 单位行的 0_30 桶少了 100（300.00 → 200.00）", bool(r2) and m(r2["buckets"]["0_30"]) == Decimal("200.00"), r2 and r2["buckets"])
    check("③-f 单位行的 31_60 桶多了 100（200.00 → 300.00）", bool(r2) and m(r2["buckets"]["31_60"]) == Decimal("300.00"), r2 and r2["buckets"])
    check("③-g 金额没被这两笔账改动（余额仍是 750.00）", bool(r2) and m(r2["balance"]) == Decimal("750.00"), r2 and r2["balance"])

    rc = wsql(
        "update ledgers set entry_date=? where order_id=? and source='ORDER' and order_product_id is not null",
        (flt(C["as_of_date"] - timedelta(days=10)), oid),
    )
    check("③-h 库里改中的正是「送达那一行」（rowcount=1）", rc == 1, "rowcount=%s" % rc)
    st, data = read_balances()
    _, item = row_of(data, oid)
    check("③-i 只改后面那笔 ⇒ 锚点不变（days 仍 45）：min 而不是 max/last", bool(item) and int(item["days"]) == 45, item and (item["days"], item["anchor"]))
    check("③-j 只改后面那笔 ⇒ 桶不变（仍 31_60）", bool(item) and item["bucket"] == "31_60", item and item["bucket"])
    check(
        "③-k 明细 anchor = 库里 min(entry_date)（order/manual）",
        bool(item) and item["anchor"] == flt(C["as_of_date"] - timedelta(days=45)),
        item and item["anchor"],
    )
    add_ledger_row(oid, C["as_of_date"] - timedelta(days=200), "RETURN", "0", TAG + "红冲锚点-" + RUN)
    st, data = read_balances()
    _, item = row_of(data, oid)
    check("③-l RETURN 红冲行不参与锚点（source 只认 order/manual）：days 仍 45", bool(item) and int(item["days"]) == 45, item and (item["days"], item["anchor"]))
    dbmin = one("select min(entry_date) from ledgers where order_id=? and source in ('ORDER','MANUAL')", (oid,))[0]
    check("③-m 报表说的 anchor 就是库里那句 min(order/manual entry_date)", bool(item) and str(dbmin) == item["anchor"], "%s vs %s" % (dbmin, item and item["anchor"]))
    check(
        "③-n 全库最早的那笔 RETURN 行（200 天前）不会把任何单的天数拉大：报表里没有 200 天的行",
        all(int(r.get("oldest_days") or 0) <= 120 for r in data["rows"]),
        max([int(r.get("oldest_days") or 0) for r in data["rows"]] or [0]),
    )


# --------------------------------------------------------------------------
# ④ 恒等式与到分
# --------------------------------------------------------------------------
def g4_invariants() -> None:
    print("\n=== ④ 恒等式与到分（balance == Σ四桶 − prepaid；totals == Σ行；金额两位小数） ===")
    st, data = read_balances()
    q = {"mode": "day", "date": C["as_of"], "include_orders": "true"}
    _st, raw, _h = _fetch("GET", "/reports/customer-balances?" + urllib.parse.urlencode(q), C["tok"])
    rawtxt = raw.decode("utf-8", "replace")
    if st != 200 or not isinstance(data, dict):
        raise Abort("报表读不到：%s %s" % (st, detail_of(data)))
    rows_, tot = data["rows"], data["totals"]
    bad1 = [r["name"] for r in rows_ if m(r["balance"]) != sum((m(v) for v in r["buckets"].values()), Decimal("0")) - m(r["prepaid"])]
    check(
        "④-a 逐行 balance == Σ四桶 − prepaid（%d 行，0 处不符）" % len(rows_),
        not bad1 and len(rows_) >= 5,
        bad1[:2] or "行数=%d" % len(rows_),
    )
    check(
        "④-b totals.balance == Σ rows.balance",
        m(tot["balance"]) == sum((m(r["balance"]) for r in rows_), Decimal("0")),
        "%s vs %s" % (tot["balance"], sum((m(r["balance"]) for r in rows_), Decimal("0"))),
    )
    check(
        "④-c totals.prepaid == Σ rows.prepaid",
        m(tot["prepaid"]) == sum((m(r["prepaid"]) for r in rows_), Decimal("0")),
        "%s vs %s" % (tot["prepaid"], sum((m(r["prepaid"]) for r in rows_), Decimal("0"))),
    )
    for k in BUCKET_KEYS:
        check(
            "④-d totals.buckets[%s] == Σ rows[%s]" % (k, k),
            m(tot["buckets"][k]) == sum((m(r["buckets"][k]) for r in rows_), Decimal("0")),
            "%s vs %s" % (tot["buckets"][k], sum((m(r["buckets"][k]) for r in rows_), Decimal("0"))),
        )
    check("④-e totals.debtor_count == len(rows)", int(tot["debtor_count"]) == len(rows_), "%s vs %s" % (tot["debtor_count"], len(rows_)))
    check(
        "④-f totals.order_count == Σ rows.order_count",
        int(tot["order_count"]) == sum(int(r["order_count"]) for r in rows_),
        "%s vs %s" % (tot["order_count"], sum(int(r["order_count"]) for r in rows_)),
    )
    check("④-g bucket_keys 就是四桶顺序", data["bucket_keys"] == list(BUCKET_KEYS), data["bucket_keys"])
    check("④-h as_of == 业务日今天（UTC+8）", data["as_of"] == C["as_of"], "%s vs %s" % (data["as_of"], C["as_of"]))
    money = re.findall(r':\s*"(-?\d+\.\d+)"', rawtxt)
    badm = [v for v in money if not re.fullmatch(r"-?\d+\.\d{2}", v)]
    check(
        "④-i 报文里所有金额串都是两位小数（%d 个，0 处不是）" % len(money),
        not badm and len(money) >= 20,
        badm[:3] or "检查了 %d 个金额串" % len(money),
    )
    check("④-j 行数 ≥ 5 才说明这些恒等式不是平凡真", len(rows_) >= 5, len(rows_))
    check(
        "④-k notes 口径说明非空且讲了预收",
        len(data["notes"]) >= 5 and any("预收" in n for n in data["notes"]),
        data["notes"][:3],
    )
    check(
        "④-l totals.no_unit_balance == Σ kind != unit 的行（报表自己给的「没挂单位的那部分」）",
        m(tot["no_unit_balance"]) == sum((m(r["balance"]) for r in rows_ if r["kind"] != "unit"), Decimal("0")),
        "%s vs %s" % (tot["no_unit_balance"], sum((m(r["balance"]) for r in rows_ if r["kind"] != "unit"), Decimal("0"))),
    )
    check(
        "④-m totals.no_unit_count == kind != unit 的行数",
        int(tot["no_unit_count"]) == sum(1 for r in rows_ if r["kind"] != "unit"),
        "%s vs %s" % (tot["no_unit_count"], sum(1 for r in rows_ if r["kind"] != "unit")),
    )
    check(
        "④-n totals.over_limit_count == Σ over_limit",
        int(tot["over_limit_count"]) == sum(1 for r in rows_ if r["over_limit"]),
        "%s vs %s" % (tot["over_limit_count"], sum(1 for r in rows_ if r["over_limit"])),
    )
    check(
        "④-o 行排序：欠款从多到少，同额按名字升序（balance_query.py:209 sort(key=(-balance, name))）",
        all(
            (-m(rows_[i]["balance"]), rows_[i]["name"]) <= (-m(rows_[i + 1]["balance"]), rows_[i + 1]["name"])
            for i in range(len(rows_) - 1)
        ),
        [(r["name"], r["balance"]) for r in rows_[:3]],
    )


# --------------------------------------------------------------------------
# ⑤ 报表日是时点
# --------------------------------------------------------------------------
def g5_point_in_time() -> None:
    print("\n=== ⑤ 报表日是时点（昨天看不见今天送达的单；未来被夹回今天；日期顺序反 ⇒ 400） ===")
    yday = flt(C["as_of_date"] - timedelta(days=1))
    st, data = read_balances(day=yday, include_orders=False)
    ev("g5_yesterday", data)
    check("⑤-a as_of=昨天：200 且 data.as_of 就是昨天", st == 200 and isinstance(data, dict) and data["as_of"] == yday, "%s %s" % (st, data.get("as_of") if isinstance(data, dict) else detail_of(data)))
    check(
        "⑤-b 昨天口径的 totals.balance 与「开场基线（昨天）」逐分相等（今天送达的一批整批看不见）",
        isinstance(data, dict) and m(data["totals"]["balance"]) == m(C["base_yday_balance"]),
        "%s vs 基线 %s（今天口径 %s）" % (data.get("totals", {}).get("balance"), C["base_yday_balance"], C["base_balance"]),
    )
    check(
        "⑤-c 昨天口径的 totals.prepaid 也与基线相等",
        isinstance(data, dict) and m(data["totals"]["prepaid"]) == m(C["base_yday_prepaid"]),
        "%s vs 基线 %s" % (data.get("totals", {}).get("prepaid"), C["base_yday_prepaid"]),
    )
    mine = my_ids()
    check("⑤-d 昨天口径里一张探针单都没有", isinstance(data, dict) and not (all_order_ids(data) & mine), len(mine))
    tmr = flt(C["as_of_date"] + timedelta(days=1))
    st, data = read_balances(day=tmr, include_orders=False)
    check(
        "⑤-e 未来日期不报 400，而是被 as_of = min(span[1], business_today()) 夹回今天"
        "（任务书里「as_of 越过今天 ⇒ 400」在本端点不成立；日期顺序那一关才 400，见 ⑤-f）",
        st == 200 and data.get("as_of") == C["as_of"],
        "HTTP %s / as_of=%s" % (st, data.get("as_of")),
    )
    st, resp = call("GET", "/reports/customer-balances?mode=day&date=%s&date_from=%s&date_to=%s" % (C["as_of"], C["as_of"], yday), token=C["tok"])
    check(
        "⑤-f date_from > date_to ⇒ 400「开始日期不能晚于结束日期」（经 _span → ensure_date_order）",
        st == 400 and "开始日期" in detail_of(resp),
        "%s %s" % (st, detail_of(resp)),
    )
    st, resp = call("GET", "/reports/customer-balances?mode=day&date=2026-13-45", token=C["tok"])
    check("⑤-g 非法日期 ⇒ 422", st == 422, "%s %s" % (st, detail_of(resp)))
    st, resp = call("GET", "/reports/customer-balances?mode=day", token=C["tok"])
    check("⑤-h 缺 date ⇒ 422（date 是必给的锚点）", st == 422, "%s %s" % (st, detail_of(resp)))
    st, resp = call("GET", "/reports/customer-balances?mode=year&date=%s" % C["as_of"], token=C["tok"])
    check("⑤-i 非法 mode ⇒ 422", st == 422, "%s %s" % (st, detail_of(resp)))
    st, data = read_balances(mode="month")
    check("⑤-j mode=month 也把 as_of 夹到今天（不是夹到月末）", st == 200 and data.get("as_of") == C["as_of"], "HTTP %s / as_of=%s" % (st, data.get("as_of") if isinstance(data, dict) else ""))
    st, data = read_balances(mode="week")
    check("⑤-k mode=week 同样夹回今天", st == 200 and data.get("as_of") == C["as_of"], "HTTP %s / as_of=%s" % (st, data.get("as_of") if isinstance(data, dict) else ""))


# --------------------------------------------------------------------------
# ⑥ 跨口径对拍
# --------------------------------------------------------------------------
def g6_turnover() -> None:
    print("\n=== ⑥ 跨口径对拍：/reports/turnover 的 arrears_total vs 本报表 totals.balance（差值口径） ===")
    st, t1 = read_turnover()
    ev("g6_turnover", t1)
    check("⑥-a turnover 200 且带 arrears_total", st == 200 and isinstance(t1, dict) and t1.get("arrears_total") is not None, "%s %s" % (st, detail_of(t1) if not isinstance(t1, dict) else list(t1)[:6]))
    st, data = read_balances(include_orders=False)
    d_turn = dd(t1["arrears_total"], C["t0"])
    d_bal = dd(data["totals"]["balance"], C["base_balance"])
    check(
        "⑥-b Δ(arrears_total) == Δ(totals.balance)（两张报表的欠款口径一致）",
        d_turn == d_bal,
        "turnover Δ=%s / balances Δ=%s" % (d_turn, d_bal),
    )
    owing = [o for o in C["orders"].values() if o["key"] != "PAID"]
    expect = sum((o["amount"] for o in owing if o["key"] != "PRE"), Decimal("0")) - Decimal("50.00")
    check(
        "⑥-c Δ 就等于我这批单的手算值（%d 张欠款单 − 50.00 预收 = %s）" % (len(owing), expect),
        d_bal == expect,
        "Δ=%s / 手算=%s" % (d_bal, expect),
    )
    check("⑥-d turnover 的 arrears_total 也是两位小数串", bool(re.fullmatch(r"-?\d+\.\d{2}", str(t1["arrears_total"]))), t1["arrears_total"])
    st, data = read_balances(include_orders=True)
    mine_now = all_order_ids(data)
    check(
        "⑥-e 我这批单在/不在报表里由余额决定：13 张欠款单全在、已收款那张不在",
        len(mine_now & my_ids()) == len(owing) and C["orders"]["PAID"]["id"] not in mine_now,
        "%d 在 / 期望 %d" % (len(mine_now & my_ids()), len(owing)),
    )
    us = (t1.get("arrears_units") or [])
    check(
        "⑥-f turnover 里那个「%s」桶名不许出现在本报表的行名里（两个口径刻意分开）" % TURNOVER_UNKNOWN,
        all(TURNOVER_UNKNOWN not in (r["name"] or "") for r in data["rows"]),
        [r["name"] for r in data["rows"] if TURNOVER_UNKNOWN in (r["name"] or "")],
    )
    check("⑥-g turnover 的 arrears_units 是 top5 列表（长度 ≤ 5）", isinstance(us, list) and len(us) <= 5, len(us) if isinstance(us, list) else us)


# --------------------------------------------------------------------------
# ⑦ 额度三态与留痕
# --------------------------------------------------------------------------
def g7_credit_limit() -> None:
    print("\n=== ⑦ 额度三态与留痕（NULL=不限 / 数值 / 0 是真零；改一次留一次痕，同值重发不留） ===")
    u3 = mk_unit(TAG + "额度单位-" + RUN, phone="13900003333")
    u4 = mk_unit(TAG + "额度清空单位-" + RUN, phone="13900004444")
    C["u3_name"], C["u4_name"] = u3["name"], u4["name"]
    need(make("LIM1", shipper_id=C["shipper_uid"], unit_id=u3["id"], amount="100.00"), "⑦ 额度单位第一单")
    need(make("CLR1", shipper_id=C["shipper_uid"], unit_id=u4["id"], amount="100.00"), "⑦ 额度清空单位第一单")
    floor = count("select coalesce(max(id),0) from operation_logs")

    def limit_logs(uid: int) -> list[list]:
        return rows(
            "select id, action, change_content from operation_logs"
            " where id>? and action='ARREARS_UNIT_CREDIT_LIMIT' and change_content like ?",
            (floor, '%"unit_id": ' + str(uid) + ",%"),
        )

    def upsert_logs(uid: int) -> int:
        return count(
            "select count(*) from operation_logs where id>? and action='ARREARS_UNIT_UPSERT' and change_content like ?",
            (floor, '%"unit_id": ' + str(uid) + ",%"),
        )

    st, data = read_balances()
    r, _ = row_of(data, C["orders"]["LIM1"]["id"])
    check("⑦-a NULL 额度：出参 limit 是 null（不是 0）", bool(r) and r.get("limit") is None, r and r.get("limit"))
    check("⑦-b NULL 额度：credit_available 也是 null（不限额度时不能给一个「还能赊多少」）", bool(r) and r.get("credit_available") is None, r and r.get("credit_available"))
    check(
        "⑦-c NULL 额度：over_limit=false，credit_used=当前欠款 100.00",
        bool(r) and r.get("over_limit") is False and m(r["credit_used"]) == Decimal("100.00"),
        r and (r.get("over_limit"), r.get("credit_used")),
    )
    check("⑦-d 库里这一行 credit_limit 就是 NULL", one("select credit_limit from arrears_units where id=?", (u3["id"],))[0] is None, one("select credit_limit from arrears_units where id=?", (u3["id"],)))

    st, resp = call("PATCH", "/arrears-units/%d" % u3["id"], token=C["tok"], body={"credit_limit": "1000.00"})
    check("⑦-e PATCH credit_limit=\"1000.00\" ⇒ 200 且出参 limit=1000.00", st == 200 and m(resp.get("credit_limit")) == Decimal("1000.00"), "%s %s" % (st, detail_of(resp)))
    cell = one("select credit_limit from arrears_units where id=?", (u3["id"],))[0]
    check("⑦-f 库里 arrears_units.credit_limit 真的落了 1000.00", m(cell) == Decimal("1000.00"), cell)
    logs = limit_logs(u3["id"])
    check("⑦-g 留痕：ARREARS_UNIT_CREDIT_LIMIT 恰好 1 条", len(logs) == 1, [(x[0], x[1]) for x in logs])
    txt = logs[0][2] if logs else ""
    check(
        "⑦-h 痕里 before/after 是**文本**（\"after\": \"1000.00\"，不是 JSON 数字）——审计页照着回查的前提",
        '"after": "1000.00"' in txt and '"before": null' in txt,
        txt[:220],
    )
    check(
        "⑦-i 痕里 scope=update 且 unit_id 对得上（能认到是哪家单位哪一次改的）",
        '"scope": "update"' in txt and ('"unit_id": %d' % u3["id"]) in txt,
        txt[:220],
    )
    n_before = upsert_logs(u3["id"])
    st, resp = call("PATCH", "/arrears-units/%d" % u3["id"], token=C["tok"], body={"credit_limit": "1000.00"})
    check("⑦-j 同一个数重发 ⇒ 200 但不留第二条额度痕（只在真的变了时记）", st == 200 and len(limit_logs(u3["id"])) == 1, [(x[0], x[1]) for x in limit_logs(u3["id"])])
    check("⑦-k 同值重发时常规字段日志（ARREARS_UNIT_UPSERT）照记，不受影响", upsert_logs(u3["id"]) >= n_before + 1, upsert_logs(u3["id"]))
    st, data = read_balances()
    r, _ = row_of(data, C["orders"]["LIM1"]["id"])
    check(
        "⑦-l 出参 limit=1000.00 / credit_used=100.00 / credit_available=900.00",
        bool(r) and m(r["limit"]) == Decimal("1000.00") and m(r["credit_used"]) == Decimal("100.00") and m(r["credit_available"]) == Decimal("900.00"),
        r and (r.get("limit"), r.get("credit_used"), r.get("credit_available")),
    )
    check("⑦-m 未超限 over_limit=false", bool(r) and r.get("over_limit") is False, r and r.get("over_limit"))

    st, resp = call("PATCH", "/arrears-units/%d" % u3["id"], token=C["tok"], body={"credit_limit": "0"})
    check("⑦-n PATCH credit_limit=0 ⇒ 200 且出参 limit=0.00（0 是真零，与 NULL「不限」是两回事）", st == 200 and m(resp.get("credit_limit")) == Decimal("0.00"), "%s %s" % (st, detail_of(resp)))
    check("⑦-o 库里列是 0.00 而不是 NULL", m(one("select credit_limit from arrears_units where id=?", (u3["id"],))[0]) == Decimal("0.00"), one("select credit_limit from arrears_units where id=?", (u3["id"],))[0])
    check("⑦-p 这次改动留了第 2 条痕（0 与 1000.00 是两次真改动）", len(limit_logs(u3["id"])) == 2, [(x[0], x[1]) for x in limit_logs(u3["id"])])
    st, data = read_balances()
    r, _ = row_of(data, C["orders"]["LIM1"]["id"])
    check(
        "⑦-q 额度 0 时：credit_available = 0.00 − 100.00 = −100.00 且 over_limit=true",
        bool(r) and m(r["credit_available"]) == Decimal("-100.00") and r.get("over_limit") is True,
        r and (r.get("limit"), r.get("credit_available"), r.get("over_limit")),
    )

    o, err = mk_order("LIM2", shipper_id=C["shipper_uid"], amount="100.00")
    check("⑦-r 已经超限（0 额度）照样能下单：POST /orders ⇒ 201", not err, err or "id=%s" % (o and o["id"]))
    if err:
        raise Abort(err)
    err = deliver("LIM2", unit_id=u3["id"])
    check("⑦-s 超限状态下派单/接单/挂账/送达全链路照样通过（额度只是提示，写侧不改任何行为）", not err, err or "已送达+已挂账")
    if err:
        raise Abort(err)
    st, data = read_balances()
    r, _ = row_of(data, C["orders"]["LIM2"]["id"])
    check(
        "⑦-t 超限那行：余额 200.00 > 额度 0.00，over_limit 仍只是一个布尔提示",
        bool(r) and m(r["balance"]) == Decimal("200.00") and r.get("over_limit") is True and m(r["limit"]) == Decimal("0.00"),
        r and (r.get("balance"), r.get("limit"), r.get("over_limit")),
    )
    check(
        "⑦-u 超限没有拦下写侧：库里确实有 2 张单挂在这家单位名下",
        count("select count(*) from orders where arrears_unit_id=?", (u3["id"],)) == 2,
        count("select count(*) from orders where arrears_unit_id=?", (u3["id"],)),
    )

    st, resp = call("PATCH", "/arrears-units/%d" % u4["id"], token=C["tok"], body={"credit_limit": "500.00"})
    check("⑦-v 换一家单位设 500.00 ⇒ 200 且列落值", st == 200 and m(one("select credit_limit from arrears_units where id=?", (u4["id"],))[0]) == Decimal("500.00"), "%s %s" % (st, one("select credit_limit from arrears_units where id=?", (u4["id"],))[0]))
    check("⑦-w 每家单位的额度痕各记各的（u4 恰好 1 条）", len(limit_logs(u4["id"])) == 1, [(x[0], x[1]) for x in limit_logs(u4["id"])])
    st, resp = call("PATCH", "/arrears-units/%d" % u4["id"], token=C["tok"], body={"credit_limit": None})
    check("⑦-x PATCH credit_limit=null ⇒ 200 且出参 limit=null", st == 200 and resp.get("credit_limit") is None, "%s %s" % (st, detail_of(resp)))
    check("⑦-y 库里列被清回 NULL（NULL 与 0 是两回事）", one("select credit_limit from arrears_units where id=?", (u4["id"],))[0] is None, one("select credit_limit from arrears_units where id=?", (u4["id"],)))
    logs4 = limit_logs(u4["id"])
    check(
        "⑦-z 清空也是一次真改动 ⇒ 留第 2 条痕且 after 是 null",
        len(logs4) == 2 and '"after": null' in (logs4[-1][2] or ""),
        [x[2][:80] for x in logs4],
    )
    st, data = read_balances()
    r, _ = row_of(data, C["orders"]["CLR1"]["id"])
    check(
        "⑦-aa 清空后出参又回到不限额度态：limit=null / credit_available=null / over_limit=false",
        bool(r) and r.get("limit") is None and r.get("credit_available") is None and r.get("over_limit") is False,
        r and (r.get("limit"), r.get("credit_available"), r.get("over_limit")),
    )
    st, resp = call("PATCH", "/arrears-units/%d" % u3["id"], token=C["tok"], body={"phone": "13900003399"})
    check(
        "⑦-ab 超限单位照样能改常规字段（额度不是闸）：200 且 phone 变了",
        st == 200 and (resp.get("phone") or "") == "13900003399",
        "%s %s" % (st, resp.get("phone") if isinstance(resp, dict) else detail_of(resp)),
    )
    check("⑦-ac 只改 phone 时不会凭空多出额度痕（额度没变就不记）", len(limit_logs(u3["id"])) == 2, [(x[0], x[1]) for x in limit_logs(u3["id"])])
    st, resp = call("PATCH", "/arrears-units/%d" % u3["id"], token=C["tok"], body={"credit_limit": "-1"})
    check("⑦-ad 负额度 ⇒ 被 schema 挡住（422，不是落库）", st == 422, "%s %s" % (st, detail_of(resp)))
    st, resp = call("PATCH", "/arrears-units/%d" % u3["id"], token=C["tok"], body={"credit_limit": "1000.00"})
    check("⑦-ae 从 0 改回 1000.00 ⇒ 又留一条痕（第 3 条）", st == 200 and len(limit_logs(u3["id"])) == 3, [(x[0], x[1]) for x in limit_logs(u3["id"])])
    st, resp = call("PATCH", "/arrears-units/%d" % u3["id"], token=C["tok"], body={"credit_limit": "0"})
    check("⑦-af 再改回 0（为了让导出里那行是「超了」）⇒ 第 4 条痕 + 列 0.00", st == 200 and len(limit_logs(u3["id"])) == 4 and m(one("select credit_limit from arrears_units where id=?", (u3["id"],))[0]) == Decimal("0.00"), [(x[0], x[1]) for x in limit_logs(u3["id"])])
    ev("g7_limit_logs", {"u3": [x[2] for x in limit_logs(u3["id"])], "u4": [x[2] for x in limit_logs(u4["id"])]})


# --------------------------------------------------------------------------
# ⑧ 逐单明细与导出
# --------------------------------------------------------------------------
def g8_details_and_export() -> None:
    print("\n=== ⑧ 逐单明细与导出（每个字段都与库 / order_money 口径对账） ===")
    st, data = read_balances()
    ev("g8_details", data)
    if st != 200 or not isinstance(data, dict):
        raise Abort("报表读不到：%s %s" % (st, detail_of(data)))
    owing = [o for o in C["orders"].values() if o["key"] != "PAID"]
    found = all_order_ids(data)
    missing = sorted(o["id"] for o in owing if o["id"] not in found)
    check("⑧-a 我造的 %d 张欠款单全都出现在明细里（一张不缺）" % len(owing), not missing, missing[:5])
    keys = ("order_no", "delivered_on", "shipper_name", "receivable", "collected", "arrears", "anchor", "days", "bucket")
    mis: dict[str, list] = {k: [] for k in keys}
    for o in owing:
        _r, it = row_of(data, o["id"])
        if it is None:
            continue
        oid = o["id"]
        orow = one("select order_no from orders where id=?", (oid,))
        total = q2(one("select coalesce(sum(line_total),0) from order_products where order_id=?", (oid,))[0])
        ret = q2(one("select coalesce(sum(abs(total)),0) from ledgers where order_id=? and source='RETURN'", (oid,))[0])
        cin = q2(one("select coalesce(sum(amount),0) from cash_flows where order_id=? and direction='in' and is_deleted=0", (oid,))[0])
        cout = q2(one("select coalesce(sum(amount),0) from cash_flows where order_id=? and direction='out' and is_deleted=0", (oid,))[0])
        recv = q2(total - ret)
        col = q2(cin - cout)
        arr = q2(recv - col)
        delivered_on = _biz_date(one("select delivered_at from orders where id=?", (oid,))[0])
        amin = one("select min(entry_date) from ledgers where order_id=? and source in ('ORDER','MANUAL')", (oid,))
        anchor = str(amin[0]) if amin and amin[0] else delivered_on
        days = max((C["as_of_date"] - date.fromisoformat(anchor)).days, 0)
        bucket = bucket_of(days) if arr > 0 else ""
        exp_label = {"UNKN": "", "TEMP": C["temp_name"]}.get(o["key"], C["shipper_name"])
        if it["order_no"] != orow[0]:
            mis["order_no"].append((o["key"], it["order_no"], orow[0]))
        if it["delivered_on"] != delivered_on:
            mis["delivered_on"].append((o["key"], it["delivered_on"], delivered_on))
        if (it["shipper_name"] or "") != exp_label:
            mis["shipper_name"].append((o["key"], it["shipper_name"], exp_label))
        if m(it["receivable"]) != recv:
            mis["receivable"].append((o["key"], it["receivable"], str(recv)))
        if m(it["collected"]) != col:
            mis["collected"].append((o["key"], it["collected"], str(col)))
        if m(it["arrears"]) != arr:
            mis["arrears"].append((o["key"], it["arrears"], str(arr)))
        if it["anchor"] != anchor:
            mis["anchor"].append((o["key"], it["anchor"], anchor))
        if int(it["days"]) != days:
            mis["days"].append((o["key"], it["days"], days))
        if it["bucket"] != bucket:
            mis["bucket"].append((o["key"], it["bucket"], bucket))
    for k, cn in (
        ("order_no", "票号"),
        ("delivered_on", "送达日"),
        ("shipper_name", "货主名快照"),
        ("receivable", "应收"),
        ("collected", "已收"),
        ("arrears", "欠款"),
        ("anchor", "账龄起点"),
        ("days", "账龄天数"),
        ("bucket", "账龄桶"),
    ):
        check(
            "⑧-b 明细的%s与库/order_money 一致（%d 张单，%d 处不符）" % (cn, len(owing), len(mis[k])),
            not mis[k],
            mis[k][:2] or "9 个字段逐张核过",
        )
    badsum = [
        r["name"]
        for r in data["rows"]
        if r.get("orders") and q2(sum((m(it["arrears"]) for it in r["orders"]), Decimal("0"))) != m(r["balance"])
    ]
    check(
        "⑧-c 每行 orders 里的 arrears 合计 == 该行 balance（明细与汇总自洽，%d 行带明细）" % sum(1 for r in data["rows"] if r.get("orders")),
        not badsum,
        badsum[:2],
    )
    check(
        "⑧-d 每行 orders 的条数 == 该行 order_count",
        all(len(r.get("orders") or []) == int(r["order_count"]) for r in data["rows"]),
        [(r["name"], len(r.get("orders") or []), r["order_count"]) for r in data["rows"] if len(r.get("orders") or []) != int(r["order_count"])][:2],
    )
    check(
        "⑧-e 明细的 bucket 只在正欠款时非空（负数/零的 bucket 是空串）",
        all((it["bucket"] != "") == (m(it["arrears"]) > 0) for r in data["rows"] for it in (r.get("orders") or [])),
        [(it["order_no"], it["arrears"], it["bucket"]) for r in data["rows"] for it in (r.get("orders") or []) if (it["bucket"] != "") != (m(it["arrears"]) > 0)][:2],
    )
    check(
        "⑧-f 同一行内明细按天数从大到小排（最老的欠款排最前）",
        all(
            all(int(r["orders"][i]["days"]) >= int(r["orders"][i + 1]["days"]) for i in range(len(r["orders"]) - 1))
            for r in data["rows"]
            if r.get("orders")
        ),
        [r["name"] for r in data["rows"] if r.get("orders") and any(int(r["orders"][i]["days"]) < int(r["orders"][i + 1]["days"]) for i in range(len(r["orders"]) - 1))][:2],
    )

    st, raw, hdrs = _fetch("GET", "/reports/export?" + urllib.parse.urlencode({"kind": "customer-balances", "mode": "day", "date": C["as_of"]}), C["tok"])
    check("⑧-g 导出端点 200 且产物是 xlsx（PK 头）", st == 200 and raw[:2] == b"PK", "HTTP %s / %s bytes / 头 %s" % (st, len(raw), raw[:4]))
    cd = {k.lower(): v for k, v in hdrs.items()}.get("content-disposition", "")
    want_fn = "customer-balances-report-%s.xlsx" % C["as_of"]
    check("⑧-h 文件名 = %s" % want_fn, want_fn in cd, cd)
    if raw[:2] != b"PK":
        raise Abort("导出不是 xlsx，后面的断言没法做：%s" % raw[:120])
    (EV / ("customer_balances_%s_export.xlsx" % RUN)).write_bytes(raw)
    zf = zipfile.ZipFile(io.BytesIO(raw))
    names = zf.namelist()
    text_all = "".join(_xml_text(zf.read(n).decode("utf-8", "replace")) for n in names if n.endswith(".xml"))
    check("⑧-i 导出里含表头「客户欠款」与 sheet 名", "客户欠款" in text_all, [n for n in names if "workbook" in n or "sheet" in n][:3])
    check("⑧-j 导出里含账龄单位那一行（%s）" % C["u2_name"], C["u2_name"] in text_all, C["u2_name"])
    check("⑧-k 导出里含额度单位那一行（%s）" % C["u3_name"], C["u3_name"] in text_all, C["u3_name"])
    check("⑧-l 导出里含临时货主那一行（%s）" % C["temp_name"], C["temp_name"] in text_all, C["temp_name"])
    check("⑧-m NULL 额度在导出里写成文本「不限额」（不是空白）", "不限额" in text_all, "不限额" in text_all)
    check("⑧-n 超限那一行在导出里标了「超了」", "超了" in text_all, "超了" in text_all)
    check("⑧-o 导出里有「未填货主」这个类型标签", UNKNOWN_NAME in text_all, UNKNOWN_NAME in text_all)
    check(
        "⑧-p ⛔ 导出里不许出现 turnover 口径的「%s」" % TURNOVER_UNKNOWN,
        TURNOVER_UNKNOWN not in text_all,
        TURNOVER_UNKNOWN in text_all,
    )
    check("⑧-q 导出里有四桶行「90 天以上」", "90 天以上" in text_all, "90 天以上" in text_all)
    check("⑧-r 导出里有合计行「合计欠款」", "合计欠款" in text_all, "合计欠款" in text_all)
    check("⑧-s 导出里有「逐单明细」块与我的单号", "逐单明细" in text_all and (C["orders"]["SHIP"]["order_no"] or "") in text_all, C["orders"]["SHIP"]["order_no"])
    check("⑧-t 导出里有「口径说明」块", "口径说明" in text_all, "口径说明" in text_all)
    check("⑧-u 导出文件落在证据目录里可人工复核", (EV / ("customer_balances_%s_export.xlsx" % RUN)).exists(), str(EV / ("customer_balances_%s_export.xlsx" % RUN)))


# --------------------------------------------------------------------------
# 还原（只删自己造的行）与还原自检
# --------------------------------------------------------------------------
def _ids_in(con, sql: str, args) -> list[int]:
    return [int(r[0]) for r in con.execute(sql, args)]


def drop_probe() -> dict:
    """按前缀硬删本探针造的所有行（外键顺序），返回 {表: 删除行数}。

    ⛔ 只删认得出是自己造的行：orders 按 delivery_description 前缀，
    arrears_units/customers 按名字前缀，子表按**自己订单的 order_id**，
    日志按 change_content 带前缀 / target_type='order' + 自己的 order_id，
    通知按 idem_key 里的数字段与自己的 order_id 相交。
    """
    deletes: dict[str, int] = {}
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        oids = _ids_in(con, "select id from orders where delivery_description like ?", (TAG + "%",))
        uids = _ids_in(con, "select id from arrears_units where name like ?", (TAG + "%",))
        cids = _ids_in(con, "select id from customers where name like ?", (TAG + "%",))
        SEEN["orders"].update(oids)
        SEEN["arrears_units"].update(uids)
        SEEN["customers"].update(cids)
        mine_users = [int(u) for u in C["created_users"]] + ([int(C["shipper_uid"])] if C.get("shipper_uid") else [])
        if oids:
            ph = ",".join("?" * len(oids))
            for t in ("order_products", "ledgers", "cash_flows", "driver_bills", "inventory_movements"):
                SEEN[t].update(_ids_in(con, "select id from %s where order_id in (%s)" % (t, ph), oids))
            logs = set(SEEN["operation_logs"])
            logs.update(_ids_in(con, "select id from operation_logs where change_content like ?", ("%" + TAG + "%",)))
            lcols = {r[1] for r in con.execute("pragma table_info(operation_logs)")}
            if {"target_type", "target_id"} <= lcols:
                logs.update(_ids_in(con, "select id from operation_logs where target_type='order' and target_id in (%s)" % ph, oids))
            SEEN["operation_logs"].update(logs)
            notifs = set(SEEN["notifications"])
            oidset = set(oids)
            for nid, k in con.execute("select id, idem_key from notifications where idem_key is not null"):
                if set(int(x) for x in re.findall(r"\d+", k or "")) & oidset:
                    notifs.add(int(nid))
            SEEN["notifications"].update(notifs)
            if mine_users:
                uph = ",".join("?" * len(mine_users))
                SEEN["usage_counters"].update(
                    _ids_in(con, "select id from usage_counters where user_id in (%s)" % uph, mine_users)
                )
        for t, col, ids in (
            ("notifications", "id", sorted(SEEN["notifications"])),
            ("usage_counters", "id", sorted(SEEN["usage_counters"])),
            ("operation_logs", "id", sorted(SEEN["operation_logs"])),
            ("driver_bills", "order_id", oids),
            ("inventory_movements", "order_id", oids),
            ("order_products", "order_id", oids),
            ("ledgers", "order_id", oids),
            ("cash_flows", "order_id", oids),
            ("orders", "id", oids),
            ("arrears_units", "id", uids),
            ("customers", "id", cids),
        ):
            if not ids:
                continue
            ph = ",".join("?" * len(ids))
            cur = con.execute("delete from %s where %s in (%s)" % (t, col, ph), ids)
            if cur.rowcount:
                deletes[t] = deletes.get(t, 0) + cur.rowcount
        cur = con.execute("delete from operation_logs where change_content like ?", ("%" + TAG + "%",))
        if cur.rowcount:
            deletes["operation_logs"] = deletes.get("operation_logs", 0) + cur.rowcount
        con.commit()
    finally:
        con.close()
    return deletes


def still_there() -> dict:
    """还原自检：SEEN 里记过的 id 再回查一遍，外加按前缀/内容计数（防漏网）。"""
    left: dict[str, int] = {}
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    try:
        for t, ids in SEEN.items():
            ids = sorted(int(i) for i in ids if i is not None)
            if not ids:
                continue
            ph = ",".join("?" * len(ids))
            n = int(con.execute("select count(*) from %s where id in (%s)" % (t, ph), ids).fetchone()[0])
            if n:
                left[t + "(按 id 回查)"] = n
        for label, sql, args in (
            ("orders(按备注前缀)", "select count(*) from orders where delivery_description like ?", (TAG + "%",)),
            ("order_products(按商品名前缀)", "select count(*) from order_products where product_name_snapshot like ?", (TAG + "%",)),
            ("ledgers(按备注前缀)", "select count(*) from ledgers where note like ? or product_name like ?", ("%" + TAG + "%", "%" + TAG + "%")),
            ("cash_flows(按备注前缀)", "select count(*) from cash_flows where note like ?", ("%" + TAG + "%",)),
            ("arrears_units(按名字前缀)", "select count(*) from arrears_units where name like ?", (TAG + "%",)),
            ("customers(按名字前缀)", "select count(*) from customers where name like ?", (TAG + "%",)),
            ("operation_logs(按内容前缀)", "select count(*) from operation_logs where change_content like ?", ("%" + TAG + "%",)),
            ("users(按名字前缀)", "select count(*) from users where full_name like ? and is_active=1", (TAG + "%",)),
        ):
            n = int(con.execute(sql, args).fetchone()[0])
            if n:
                left[label] = n
        if C.get("shipper_uid"):
            n = int(con.execute("select count(*) from usage_counters where user_id=?", (C["shipper_uid"],)).fetchone()[0])
            if n:
                left["usage_counters(按探针账号)"] = n
    finally:
        con.close()
    return left


def soft_deleted_users() -> dict:
    """探针账号走真端点软删（DELETE /users/{id}）后的核对：is_active=0 且手机号带 _del 后缀。"""
    left: dict[str, Any] = {}
    for uid in C["created_users"]:
        r = one("select id, full_name, phone, is_active from users where id=?", (uid,))
        if not r:
            left["users.id=%s" % uid] = "行没了"
            continue
        if int(r[3] or 0) != 0 or not str(r[2] or "").endswith("_del%d" % uid):
            left["users.id=%s" % uid] = "is_active=%s phone=%s" % (r[3], r[2])
    return left


def fail(msg: str, keep: bool) -> int:
    print("")
    print("❌ %s" % msg)
    if keep:
        print("   （--keep：现场保留，没有还原）")
    else:
        print("   还原：%s" % (drop_probe() or "没有可删的行"))
    return 1


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="FEAT-0015 第五期真库探针：客户欠款账龄报表 + 挂账单位信用额度")
    ap.add_argument("--keep", action="store_true", help="跑完不还原，留下现场（默认还原并自检）")
    args = ap.parse_args()
    keep = bool(args.keep)
    print("=" * 78)
    print("FEAT-0015 第五期真库探针：GET /reports/customer-balances + PATCH /arrears-units/{id}.credit_limit")
    print("仓库根：%s" % ROOT)
    print("后端与真库：%s ｜ %s" % (BASE, DB.name))
    print("本轮标签：%s%s（所有探针数据都带这个前缀，跑完按它硬删）" % (TAG, RUN))
    print("=" * 78)

    hst, _hbody = call("GET", HEALTH)
    if hst != 200:
        print("❌ 后端没起来（%s ⇒ %s）；先起后端再跑探针（本探针不负责起后端）" % (HEALTH, hst))
        return 1
    st, body = call("POST", "/auth/login", body={"phone": PHONE, "password": PASSWORD})
    tok = body.get("access_token") if isinstance(body, dict) else None
    if st != 200 or not tok:
        print("❌ 派单员登录失败：%s %s" % (st, detail_of(body)))
        return 1
    st, me = call("GET", "/users/me", token=tok)
    if st != 200 or not isinstance(me, dict):
        print("❌ /users/me 失败：%s %s" % (st, detail_of(me)))
        return 1
    st, dbody = call("POST", "/auth/login", body={"phone": DRIVER_PHONE, "password": PASSWORD})
    dtok = dbody.get("access_token") if isinstance(dbody, dict) else None
    if st != 200 or not dtok:
        print("❌ 司机登录失败：%s %s" % (st, detail_of(dbody)))
        return 1
    st, dme = call("GET", "/users/me", token=dtok)
    if st != 200 or not isinstance(dme, dict):
        print("❌ 司机 /users/me 失败：%s %s" % (st, detail_of(dme)))
        return 1
    C["tok"], C["dtok"], C["uid"], C["driver_id"] = tok, dtok, int(me["id"]), int(dme["id"])
    C["as_of"] = today_cst().isoformat()
    C["as_of_date"] = today_cst()
    print("派单员 uid=%s ｜ 司机 id=%s ｜ 业务日 as_of=%s" % (C["uid"], C["driver_id"], C["as_of"]))
    print("开跑前先清一次上轮残留：%s" % (drop_probe() or "没有残留"))
    check("0-a /health 200（打的是已经在跑的真后端）", hst == 200, "%s ⇒ %s" % (HEALTH, hst))
    check("0-b 派单员 token 拿到了（探针全靠真端点造单）", bool(tok) and C["uid"] > 0, "uid=%s" % C["uid"])

    st, data = read_balances(include_orders=False)
    if st != 200 or not isinstance(data, dict):
        print("❌ 报表读不到（后面全部没法验）：%s %s" % (st, detail_of(data)))
        return fail("GET /reports/customer-balances 不可用", keep)
    C["base_balance"] = data["totals"]["balance"]
    C["base_prepaid"] = data["totals"]["prepaid"]
    check("0-c as_of 就是业务日今天（UTC+8），报表没夹错日子", data["as_of"] == C["as_of"], "%s vs %s" % (data["as_of"], C["as_of"]))
    check(
        "0-d 报表只读可用：totals.balance 是两位小数串（开场基线留档）",
        bool(re.fullmatch(r"-?\d+\.\d{2}", str(C["base_balance"]))),
        "balance=%s prepaid=%s rows=%s" % (C["base_balance"], C["base_prepaid"], len(data["rows"])),
    )
    st, y = read_balances(day=flt(C["as_of_date"] - timedelta(days=1)), include_orders=False)
    C["base_yday_balance"] = y["totals"]["balance"] if isinstance(y, dict) and st == 200 else None
    C["base_yday_prepaid"] = y["totals"]["prepaid"] if isinstance(y, dict) and st == 200 else None
    check("0-e 昨天口径也读得到（⑤ 用来证「今天送达的一批整批看不见」）", st == 200 and C["base_yday_balance"] is not None, "%s %s" % (st, C["base_yday_balance"]))
    st, t = read_turnover()
    C["t0"] = t.get("arrears_total") if isinstance(t, dict) and st == 200 else None
    check("0-f turnover 基线可读（⑥ 用差值口径对拍，不受库里 400 多张真实单影响）", st == 200 and C["t0"] is not None, "%s %s" % (st, C["t0"]))
    check("0-g 探针前缀没和真库现有数据撞（库里还没有带这个前缀的单）", count("select count(*) from orders where delivery_description like ?", (TAG + "%",)) == 0, TAG + RUN)

    aborted = None
    for name, fn in (
        ("①", g1_debtors),
        ("②", g2_buckets),
        ("③", g3_anchor),
        ("④", g4_invariants),
        ("⑤", g5_point_in_time),
        ("⑥", g6_turnover),
        ("⑦", g7_credit_limit),
        ("⑧", g8_details_and_export),
    ):
        try:
            fn()
        except Abort as e:
            aborted = "%s 组中断：%s" % (name, e)
            break
        except Exception as e:  # noqa: BLE001 —— 探针要把任何意外记成红，不能半路崩掉留一地数据
            aborted = "%s 组异常：%s: %s" % (name, type(e).__name__, e)
            break
    if aborted:
        BAD.append(aborted)
        print("\n‼️ %s" % aborted)

    if keep:
        print("\n（--keep：现场保留，不还原、也不做还原自检；下次不带 --keep 跑会自动按前缀清掉）")
    else:
        print("\n=== ⑨ 还原与还原自检（只删自己造的行） ===")
        soft = [(uid, call("DELETE", "/users/%d" % uid, token=C["tok"])[0]) for uid in list(C["created_users"])]
        check(
            "⑨-a 探针货主账号走真端点软删（DELETE /users/{id} ⇒ 204 No Content）",
            bool(soft) and all(s in (200, 204) for _u, s in soft),
            soft,
        )
        deletes = drop_probe()
        print("  清理台账：%s" % json.dumps(deletes, ensure_ascii=False))
        ev("cleanup", {"deletes": deletes, "users_soft_deleted": soft})
        left = still_there()
        check("⑨-b 还原自检：自己造的行一条不剩（SEEN 按 id 回查 + 前缀计数 + 通知/用量计数）", not left, left or "干干净净")
        check("⑨-c 探针账号已软删（is_active=0 且手机号带 _del{id} 后缀）", not soft_deleted_users(), soft_deleted_users() or "两个探针账号都是 is_active=0")
        st, data = read_balances(include_orders=False)
        check(
            "⑨-d 收工后 totals.balance 逐分回到开场基线（没把人家的账改坏）",
            st == 200 and m(data["totals"]["balance"]) == m(C["base_balance"]),
            "%s vs 基线 %s" % (data.get("totals", {}).get("balance") if isinstance(data, dict) else detail_of(data), C["base_balance"]),
        )
        check(
            "⑨-e 收工后 totals.prepaid 也回到基线",
            st == 200 and m(data["totals"]["prepaid"]) == m(C["base_prepaid"]),
            "%s vs 基线 %s" % (data.get("totals", {}).get("prepaid") if isinstance(data, dict) else "", C["base_prepaid"]),
        )
        st, t = read_turnover()
        check(
            "⑨-f 收工后 turnover 的 arrears_total 也回到开场值（跨口径双确认没改坏账）",
            st == 200 and m(t["arrears_total"]) == m(C["t0"]),
            "%s vs 开场 %s" % (t.get("arrears_total") if isinstance(t, dict) else detail_of(t), C["t0"]),
        )
        st, y = read_balances(day=flt(C["as_of_date"] - timedelta(days=1)), include_orders=False)
        check(
            "⑨-g 昨天口径也回到基线",
            st == 200 and m(y["totals"]["balance"]) == m(C["base_yday_balance"]),
            "%s vs 基线 %s" % (y.get("totals", {}).get("balance") if isinstance(y, dict) else "", C["base_yday_balance"]),
        )
        check(
            "⑨-h 库里再没有探针前缀的订单/单位/客户（人肉复核也查不到）",
            count("select count(*) from orders where delivery_description like ?", (TAG + "%",)) == 0
            and count("select count(*) from arrears_units where name like ?", (TAG + "%",)) == 0
            and count("select count(*) from customers where name like ?", (TAG + "%",)) == 0,
            "orders=%s units=%s customers=%s"
            % (
                count("select count(*) from orders where delivery_description like ?", (TAG + "%",)),
                count("select count(*) from arrears_units where name like ?", (TAG + "%",)),
                count("select count(*) from customers where name like ?", (TAG + "%",)),
            ),
        )

    print("")
    print("=" * 78)
    print("断言 %d 条 ｜ 红 %d 条 ｜ 造单 %d 张 ｜ 探针标签 %s%s" % (TOTAL[0], len(BAD), len(C["orders"]), TAG, RUN))
    print("证据目录：%s（每组报表原文 + 清理台账；导出 xlsx 也在里面）" % EV.relative_to(ROOT))
    if BAD:
        print("❌ 下面这些没通过：")
        for b in BAD:
            print("  - %s" % b)
        print("（现场%s）" % ("保留（--keep）" if keep else "已按前缀还原"))
        return 1
    print("收工：真后端 + 真 SQLite 库逐条回读核对，全绿。")
    print("✅ 全部 %d 条断言通过" % TOTAL[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
