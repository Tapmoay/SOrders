"""打真后端验「税账 / 发票台账」这条路（FEAT-0014 / L3）。

### 为什么必须打真库
税账这一块**没有一个数字是请求里带进来的**：税额是后端按税率现算的、税汇是一段窗口的
聚合、删单闸是"先看有没有活着的进项票再决定动不动库存"。HTTP 200 只证明"请求被接受了"：
  · 税额到底算没算、算成几分，只有读 invoices.tax_amount 才知道（票面金额 ÷ 是否含税，
    错一位就是「净额 100、税额 3、合计 103 却记成 103 → 106」这种账）；
  · 删单闸看的是"票还在不在"，而**退库存**发生在闸门后面 —— 闸门若是写在退库存之后，
    返回 400 时库存已经退回去了，界面上看不出来，下次进货就对不上账（本轮要钉的静默坑）；
  · 税汇是**整段窗口**的聚合，别的票也会进来，所以每条断言都必须是「前后差值」而不是绝对值。
这些都不是单测能证伪的：单测走 TestClient + 自己的库，看不见真迁移、真库、真端点。

### 它验什么（11 条，每条都读库 / 读另一条接口，不靠响应体里那句"看起来对"）
1. 登记进项票 ⇒ 库里 tax_amount 由后端按税率算出、invoice_purchase_orders 关联行落库、
   同一次提交里 net + tax == amount（自洽）
2. 进项票不挂采购单 / 挂的不是同一家供应商 / 挂不存在的单 / 进项票填了客户 / 未税票带税额
   ⇒ 400，且**库里没有半成品**（不留票头、不留关联行、不留日志）
3. 同方向同票号重复登记 ⇒ 409；空票号可以登记多张（唯一索引 (direction, no_key) 不拦 NULL）；
   同一个号跨方向（销项 vs 进项）互不冲突
4. 未税票（tax_rate 为空）⇒ 进 untaxed_count/untaxed_amount、**不进** tax_amount，counts_in_tax False
5. 作废 ⇒ 退出税汇（count 与 tax_amount 减回去、voided_count +1），但明细里还看得见；
   作废后那张采购单就能删，库存退回去、恒等式不破
6. 删进回收站的票退出税汇，恢复后原样回来；**回收站里的票仍占号**（再登记同号 ⇒ 409 且文案指向回收站）
7. 采购单删单闸：挂着没作废的进项票时 DELETE /purchase-orders/{id} ⇒ 400，
   **且采购单还在、库存没先退回去**；把票作废之后删单才 204
8. 税账窗口按 invoice_date（含两端）：窗外那一天的票一分钱都不进税汇
9. 利润表：tax_total = 分类名带「税」的开销之和，这些笔**不再**出现在 operating_expenses
   （不双扣），operating_profit 与恒等式不变；vat_output/vat_input/vat_payable 来自税汇且**不进** operating_profit
10. /reports/tax-summary 的 by_rate：销项在前、税率从高到低；每格合计 == 该侧合计；
    vat_payable == output.tax_amount − input.tax_amount
11. 留痕：operation_logs 里六个动作码 TAX_INVOICE_CREATE/UPDATE/ISSUE/VOID/DELETE/RESTORE 都真的落了行

### 隔离
探针自己建供应商 A/B、客户、商品（名字都带「探针」前缀）与它自己的采购单 / 发票 / 开销，
票号统一带 PRB- 前缀；跑完（缺省）按名字与票号前缀把这些表里属于它的行硬删掉：
invoices / invoice_purchase_orders / invoice_ledgers / inventory_movements / product_cost_history /
supplier_payables / purchase_orders / purchase_order_items / products / suppliers / customers /
cash_flows / expenses / expense_categories / operation_logs。
⛔ 不碰任何真实商品、真实供应商、真实票据的既有数据。

用法：
    python _tools/qa/_probe_tax_invoices.py            # 跑一遍并还原（默认）
    python _tools/qa/_probe_tax_invoices.py --keep     # 不还原，留现场给人看
证据：_tmp/ev/32x-tax-*.json（每次跑覆盖）
"""
import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
BASE = "http://127.0.0.1:8000/api/v1"
HEALTH = "http://127.0.0.1:8000/health"
DB = ROOT / "backend/sorders.db"
EV = ROOT / "_tmp/ev"
PHONE, PASSWORD = "13800000001", "pass12345"  # 开发库测试号（backend/scripts/reset_dev_passwords.py）

RUN = time.strftime("%m%d%H%M%S")
NO_PREFIX = "PRB-"                      # 票号前缀：还原时按它认探针的票
SUP_A, SUP_B = "探针税账供应商A-" + RUN, "探针税账供应商B-" + RUN
CUS = "探针税账客户-" + RUN
PRODUCT = "探针税账商品-" + RUN
EXP_CAT = "探针税金及附加"
EXP_NOTE = "探针：税账探针的开销（FEAT-0014）"
REMARK = "探针：税账探针的进货单（FEAT-0014）"
TODAY = time.strftime("%Y-%m-%d")

SIX_ACTIONS = ["TAX_INVOICE_CREATE", "TAX_INVOICE_UPDATE", "TAX_INVOICE_ISSUE",
               "TAX_INVOICE_VOID", "TAX_INVOICE_DELETE", "TAX_INVOICE_RESTORE"]

BAD: list[str] = []
TOTAL = [0]     # 断言总条数（只在收尾打印时用）
# 键就是真实表名（还原后用它们逐表核对"是不是真的删干净了"）
SEEN: dict[str, set] = {"invoices": set(), "purchase_orders": set(), "inventory_movements": set(),
                        "supplier_payables": set(), "products": set(), "suppliers": set(),
                        "customers": set(), "expenses": set(), "purchase_order_items": set()}


def call(method: str, path: str, token: str | None = None, body=None):
    """打真后端。path 以 http 开头就当绝对地址用（/health 不在 /api/v1 下面）。"""
    url = path if path.startswith("http") else BASE + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "ignore")
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:300]
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def rows(sql: str, args=()):
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


def check(label: str, cond: bool, detail) -> None:
    TOTAL[0] += 1
    print("  [%s] %s —— %s" % ("OK" if cond else "FAIL", label, detail))
    if not cond:
        BAD.append(label)


def ev(name: str, payload) -> None:
    EV.mkdir(parents=True, exist_ok=True)
    p = EV / name
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("  → 证据 %s" % p.relative_to(ROOT))


def m(v):
    """金额一律按字符串读（响应里是两位小数字符串，库里是 float/Decimal）。"""
    return None if v is None else Decimal(str(v))


def dd(now, before):
    """差值：税汇是整段窗口的聚合，别的票也在里面，只有差值是我们这张票的。"""
    return m(now) - m(before)


def detail_of(body) -> str:
    if isinstance(body, dict):
        return str(body.get("detail") or body)
    return str(body)


# ---------------------------------------------------------------- 库上的事实

def invoice_row(iid: int):
    return one(
        "select id,direction,invoice_no,no_key,invoice_date,amount,tax_rate,tax_amount,status,"
        "supplier_id,customer_id,is_deleted,deleted_at from invoices where id=?", (iid,))


def links_of(iid: int) -> list[list]:
    return rows("select id,invoice_id,purchase_order_id from invoice_purchase_orders "
                "where invoice_id=? order by id", (iid,))


def link_count(oid: int) -> int:
    return count("select count(*) from invoice_purchase_orders where purchase_order_id=?", (oid,))


def stock(pid: int) -> int:
    return int(one("select stock from products where id=?", (pid,))[0])


def moves(pid: int) -> list[list]:
    return rows("select id,change,unit_cost,status,source,note from inventory_movements "
                "where product_id=? order by id", (pid,))


def sum_change(pid: int) -> int:
    return int(one("select coalesce(sum(change),0) from inventory_movements where product_id=?", (pid,))[0])


def identity(pid: int) -> dict:
    return {"stock": stock(pid), "sum_change": sum_change(pid), "identity_ok": stock(pid) == sum_change(pid)}


def order_row(oid: int):
    return one("select id,supplier_id,doc_date,remark,payable_id,is_deleted from purchase_orders where id=?", (oid,))


def payable_row(pid_: int):
    return one("select id,supplier_id,title,amount,is_deleted from supplier_payables where id=?", (pid_,))


def items_of(oid: int) -> list[list]:
    return rows("select id,product_id,quantity,unit_cost,movement_id,is_void from purchase_order_items "
                "where order_id=? order by id", (oid,))


def log_floor() -> int:
    return count("select coalesce(max(id),0) from operation_logs")


def tax_logs(floor: int) -> list[list]:
    return rows("select id,action,change_content from operation_logs "
                "where id>? and action like 'TAX_INVOICE%' order by id", (floor,))


# ---------------------------------------------------------------- 两个报表

def tax(token: str, start: str, end: str):
    return call("GET", "/reports/tax-summary?mode=month&date=%s&date_from=%s&date_to=%s"
                % (start, start, end), token)


def profit(token: str, day: str):
    return call("GET", "/reports/profit?mode=day&date=%s" % day, token)


def side(b: dict, k: str) -> dict:
    return {f: m(b.get(k, {}).get(f)) for f in
            ("count", "amount", "net_amount", "tax_amount", "untaxed_count", "untaxed_amount")}


def deltas(now: dict, before: dict, k: str) -> dict:
    a, b = side(now, k), side(before, k)
    return {f: a[f] - b[f] for f in a}


def rows_by_id(payload: dict) -> dict:
    return {int(r["id"]): r for r in (payload.get("invoices") or [])}


# ---------------------------------------------------------------- 还原（只删探针自己造的行）

def drop_probe() -> dict:
    """按名字 / 票号前缀找探针自己造的行，硬删。⛔ 判据里没有一条能命中真实数据。"""
    con = sqlite3.connect(DB)
    removed: dict[str, int] = {}
    try:
        pids = [r[0] for r in con.execute("select id from products where name like '探针税账商品-%'")]
        sups = [r[0] for r in con.execute("select id from suppliers where name like '探针税账供应商%'")]
        cuss = [r[0] for r in con.execute("select id from customers where name like '探针税账客户-%'")]
        exps = [r[0] for r in con.execute("select id from expenses where category=?", (EXP_CAT,))]

        oids: set[int] = set()
        for pid in pids:
            oids |= {r[0] for r in con.execute(
                "select distinct order_id from purchase_order_items where product_id=?", (pid,))}
        for sid in sups:
            oids |= {r[0] for r in con.execute("select id from purchase_orders where supplier_id=?", (sid,))}
        oids |= {r[0] for r in con.execute("select id from purchase_orders where remark=?", (REMARK,))}
        oids = {int(x) for x in oids}

        iids: set[int] = {r[0] for r in con.execute("select id from invoices where invoice_no like ?", (NO_PREFIX + "%",))}
        for col, ids in (("supplier_id", sups), ("customer_id", cuss)):
            if ids:
                q = ",".join("?" * len(ids))
                iids |= {r[0] for r in con.execute("select id from invoices where %s in (%s)" % (col, q), ids)}
        if oids:
            q = ",".join("?" * len(oids))
            iids |= {r[0] for r in con.execute(
                "select invoice_id from invoice_purchase_orders where purchase_order_id in (%s)" % q, list(oids))}
        iids = {int(x) for x in iids}

        def dele(table: str, col: str, ids, extra: str = "") -> None:
            """删探针自己造的行。extra 是必须同时成立的额外条件 —— 用来钉死「同一列在别的
            party 下指向别的主键」的撞号：cash_flows.doc_id 就是这种列（付款指向应付单、
            开销指向开销单、收款指向收款单），只按数值删就会删到别人的行。"""
            ids = [int(x) for x in ids]
            if not ids:
                return
            q = ",".join("?" * len(ids))
            sql = "delete from %s where %s in (%s)" % (table, col, q)
            if extra:
                sql += " and " + extra
            cur = con.execute(sql, ids)
            removed[table] = removed.get(table, 0) + int(cur.rowcount or 0)

        if iids:
            dele("invoice_purchase_orders", "invoice_id", iids)
            dele("invoice_ledgers", "invoice_id", iids)
            dele("invoices", "id", iids)
        if oids:
            pays = [r[0] for r in con.execute(
                "select payable_id from purchase_orders where id in (%s)" % ",".join("?" * len(oids)), list(oids))]
            pays = [int(p) for p in pays if p]
            if pays:
                # 付款流水：doc_id 指向应付单，但同一列在收款/开销下指向别的表的主键，
                # 所以必须连 biz_type/party_type 一起认，否则会删到别人的行（本探针踩过一次）。
                dele("cash_flows", "doc_id", pays, "biz_type='PAYMENT_SUPPLIER' and party_type='supplier'")
                dele("supplier_payables", "id", pays)
            iids2 = {r[0] for r in con.execute(
                "select invoice_id from invoice_purchase_orders where purchase_order_id in (%s)"
                % ",".join("?" * len(oids)), list(oids))}
            if iids2:
                dele("invoice_purchase_orders", "invoice_id", iids2)
                dele("invoice_ledgers", "invoice_id", iids2)
                dele("invoices", "id", iids2)
            dele("invoice_purchase_orders", "purchase_order_id", oids)
            dele("purchase_order_items", "order_id", oids)
            dele("purchase_orders", "id", oids)
        if exps:
            # 开销也会写一条流水：同样要把 party_type 认上，别按 doc_id 数值误伤
            dele("cash_flows", "doc_id", exps, "party_type='expense' and biz_type like 'EXPENSE%'")
        dele("expenses", "id", exps)
        cur = con.execute("delete from expense_categories where name=?", (EXP_CAT,))
        removed["expense_categories"] = int(cur.rowcount or 0)
        for pid in pids:
            dele("inventory_movements", "product_id", [pid])
            dele("product_cost_history", "product_id", [pid])
            dele("products", "id", [pid])
        dele("suppliers", "id", sups)
        dele("customers", "id", cuss)
        cur = con.execute("delete from operation_logs where action like 'TAX_INVOICE%' and change_content like ?",
                          ("%" + NO_PREFIX + "%",))
        removed["operation_logs(税票)"] = int(cur.rowcount or 0)
        cur = con.execute("delete from operation_logs where change_content like ?", ("%" + REMARK + "%",))
        removed["operation_logs(采购单)"] = int(cur.rowcount or 0)
        cur = con.execute("delete from operation_logs where action='EXPENSE_CREATE' and change_content like ?",
                          ("%" + EXP_CAT + "%",))
        removed["operation_logs(开销)"] = int(cur.rowcount or 0)
        con.commit()
    finally:
        con.close()
    return {k: v for k, v in removed.items() if v}


def still_there() -> dict:
    """还原之后，探针自己记下的那些 id 还剩下几条（应该全是 0）。"""
    out = {}
    for table, ids in SEEN.items():
        if not ids:
            continue
        q = ",".join("?" * len(ids))
        out[table] = count("select count(*) from %s where id in (%s)" % (table, q), list(ids))
    out["票号前缀 %s" % NO_PREFIX] = count("select count(*) from invoices where invoice_no like ?", (NO_PREFIX + "%",))
    out["探针商品名"] = count("select count(*) from products where name like '探针税账商品-%'")
    out["探针供应商名"] = count("select count(*) from suppliers where name like '探针税账供应商%'")
    out["探针客户名"] = count("select count(*) from customers where name like '探针税账客户-%'")
    out["探针开销分类"] = count("select count(*) from expenses where category=?", (EXP_CAT,))
    return out


# ---------------------------------------------------------------- 主流程

def fail(msg: str, keep: bool) -> int:
    print()
    print("❌ %s" % msg)
    if keep:
        print("   （--keep：现场保留，没有还原）")
    else:
        print("   还原：%s" % (drop_probe() or "没有可删的行"))
    return 1


def main() -> int:  # noqa: C901 —— 探针就是一条直线走完 11 条，拆函数反而看不清
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="跑完不还原，留现场给人看")
    a = ap.parse_args()
    keep = a.keep

    print("=== FEAT-0014 税账 / 发票台账 探针（打真后端） ===")
    print("仓库根：%s" % ROOT)
    print("后端  ：%s   库：%s" % (BASE, DB))
    print("本轮  ：%s（票号前缀 %s；主数据名字都带「探针」）" % (RUN, NO_PREFIX))

    st, health = call("GET", HEALTH)
    if st != 200:
        print()
        print("❌ 后端没起来（GET /health = %s）—— 先起 uvicorn 再跑本探针；探针这一步什么都没动。" % st)
        return 1
    check("前置：后端活着（GET /health = 200）", st == 200, health)

    st, tok = call("POST", "/auth/login", None, {"phone": PHONE, "password": PASSWORD})
    if st != 200 or not (tok or {}).get("access_token"):
        print()
        print("❌ 登录失败（%s / %s）：%s" % (st, PHONE, tok))
        return 1
    token = tok["access_token"]
    _st, me = call("GET", "/users/me", token)
    uid = int((me or {}).get("id") or 0)

    old = drop_probe()
    if old:
        print("  （顺手清掉上次的残留：%s）" % old)
    floor = log_floor()

    # ------------------------------------------------------------ 铺底
    print()
    print("=== 铺底：供应商 A/B、客户、商品、三张采购单 ===")
    st, s1b = call("POST", "/suppliers", token,
                   {"name": SUP_A, "contact_name": "探针联系人", "phone": "13900000001"})
    if st not in (200, 201):
        return fail("建供应商 A 失败：%s %s" % (st, s1b), keep)
    s1 = int(s1b["id"])
    SEEN["suppliers"].add(s1)

    st, s2b = call("POST", "/suppliers", token,
                   {"name": SUP_B, "contact_name": "探针联系人", "phone": "13900000002"})
    if st not in (200, 201):
        return fail("建供应商 B 失败：%s %s" % (st, s2b), keep)
    s2 = int(s2b["id"])
    SEEN["suppliers"].add(s2)

    st, cb = call("POST", "/customers", token, {"name": CUS, "user_id": uid})
    if st not in (200, 201):
        return fail("建客户失败：%s %s" % (st, cb), keep)
    cid = int(cb["id"])
    SEEN["customers"].add(cid)

    st, pb = call("POST", "/products", token, {"name": PRODUCT, "unit": "件", "default_unit_price": "15.00",
                                               "cost_price": "12.50", "stock": 0, "category": "探针"})
    if st not in (200, 201):
        return fail("建商品失败：%s %s" % (st, pb), keep)
    pid = int(pb["id"])
    SEEN["products"].add(pid)
    stock0 = stock(pid)
    print("  供应商 %s/%s、客户 %s、商品 %s（初始库存 %s）" % (s1, s2, cid, pid, stock0))

    def new_po(sid: int, qty: int, unit_cost: str):
        st_, b_ = call("POST", "/purchase-orders", token, {
            "supplier_id": sid, "doc_date": TODAY, "remark": REMARK,
            "items": [{"product_id": pid, "quantity": qty, "unit_cost": unit_cost}]})
        if st_ != 201:
            return None, (st_, b_)
        SEEN["purchase_orders"].add(int(b_["id"]))
        if b_.get("payable_id"):
            SEEN["supplier_payables"].add(int(b_["payable_id"]))
        for it in items_of(int(b_["id"])):
            SEEN["purchase_order_items"].add(int(it[0]))
            if it[4]:
                SEEN["inventory_movements"].add(int(it[4]))
        return b_, None

    po1, err = new_po(s1, 10, "12.50")          # 125.00
    if err:
        return fail("建采购单 1 失败：%s" % (err,), keep)
    po2, err = new_po(s1, 6, "20.00")           # 120.00
    if err:
        return fail("建采购单 2 失败：%s" % (err,), keep)
    po3, err = new_po(s1, 4, "10.00")           # 40.00
    if err:
        return fail("建采购单 3 失败：%s" % (err,), keep)
    o1, o2, o3 = int(po1["id"]), int(po2["id"]), int(po3["id"])
    mv3 = {int(it[4]) for it in items_of(o3) if it[4]}
    stock_full = stock(pid)
    ev("320-tax-baseline.json", {"supplier_a": s1, "supplier_b": s2, "customer": cid, "product": pid,
                                 "orders": [po1, po2, po3], "stock_after_3_orders": stock_full,
                                 "identity": identity(pid), "log_floor": floor, "run": RUN})
    check("铺底：三张采购单入库 ⇒ 库存 = 0 + 10 + 6 + 4",
          stock_full == stock0 + 20 and identity(pid)["identity_ok"],
          "库存=%s 恒等式=%s" % (stock_full, identity(pid)))

    def new_inv(no: str, direction: str, amount: str, rate, *, inv_date=None, supplier=None,
                customer=None, pos=None, tax_amount=None):
        body = {"direction": direction, "invoice_no": no, "invoice_date": inv_date or TODAY,
                "amount": amount, "note": "探针（FEAT-0014）"}
        if rate is not None:
            body["tax_rate"] = rate
        if tax_amount is not None:
            body["tax_amount"] = tax_amount
        if supplier is not None:
            body["supplier_id"] = supplier
        if customer is not None:
            body["customer_id"] = customer
        if pos:
            body["purchase_order_ids"] = pos
        st_, b_ = call("POST", "/invoices", token, body)
        if st_ in (200, 201) and isinstance(b_, dict) and b_.get("id"):
            SEEN["invoices"].add(int(b_["id"]))
        return st_, b_

    # ------------------------------------------------------------ ①
    print()
    print("=== ① 登记进项票：税额后端算、关联行落库、net + tax == amount ===")
    no1 = NO_PREFIX + RUN + "-IN1"
    t0 = tax(token, TODAY, TODAY)
    st, inv1 = new_inv(no1, "INPUT", "103.00", "3.00", supplier=s1, pos=[o1])
    if st not in (200, 201):
        return fail("① 登记进项票失败：%s %s" % (st, inv1), keep)
    i1 = int(inv1["id"])
    r1 = invoice_row(i1)
    l1 = links_of(i1)
    t1 = tax(token, TODAY, TODAY)
    d1 = deltas(t1[1], t0[1], "input")
    _st, det1 = call("GET", "/invoices/%d" % i1, token)
    ev("321-tax-create.json", {"status": st, "response": inv1, "db_row": r1, "links": l1, "detail": det1,
                               "tax_before": t0[1], "tax_after_input": t1[1]["input"],
                               "vat_before": t0[1]["vat_payable"], "vat_after": t1[1]["vat_payable"],
                               "input_delta": d1})
    check("① 票头落库：status=REGISTERED / 税率 3.00 / 金额 103.00",
          bool(r1) and r1[8] == "REGISTERED" and m(r1[6]) == m("3.00") and m(r1[5]) == m("103.00"),
          "库里=%s" % (r1,))
    check("① 税额度后端按 3% 现算（提交里没带 tax_amount）", bool(r1) and m(r1[7]) == m("3.00"),
          "库里 tax_amount=%s，期望 3.00（103.00 − 100.00）" % (r1[7] if r1 else None))
    check("① 自洽：价税合计 − 税额 == 净额 100.00",
          bool(r1) and (m(r1[5]) - m(r1[7])) == m("100.00"),
          "合计=%s − 税额=%s = %s" % (r1[5], r1[7], m(r1[5]) - m(r1[7])))
    check("① 关联行 invoice_purchase_orders 落库（指向那张采购单）",
          len(l1) == 1 and int(l1[0][2]) == o1, l1)
    check("① 详情接口 purchase_order_ids 对得上（读另一条接口对照）",
          bool(det1) and [int(x) for x in det1.get("purchase_order_ids", [])] == [o1],
          (det1 or {}).get("purchase_order_ids"))
    check("① 税汇 input：count +1 / amount +103.00 / net +100.00 / tax +3.00",
          d1["count"] == 1 and d1["amount"] == m("103.00") and d1["net_amount"] == m("100.00")
          and d1["tax_amount"] == m("3.00"), d1)
    check("① 进项可抵：vat_payable 减 3.00",
          dd(t1[1]["vat_payable"], t0[1]["vat_payable"]) == m("-3.00"),
          "%s → %s" % (t0[1]["vat_payable"], t1[1]["vat_payable"]))
    row1 = rows_by_id(t1[1]).get(i1)
    check("① 税账明细里 counts_in_tax=True、票面税额 3.00",
          bool(row1) and row1["counts_in_tax"] is True and m(row1["tax_amount"]) == m("3.00"), row1)

    # ------------------------------------------------------------ ②
    print()
    print("=== ② 五种坏提交都要 400，且库里不留半成品 ===")
    inv_before = count("select count(*) from invoices where invoice_no like ?", (NO_PREFIX + "%",))
    link_before = link_count(o1)
    logs_before = len(tax_logs(floor))
    cases = [
        ("进项票不挂采购单", new_inv(NO_PREFIX + RUN + "-BAD1", "INPUT", "103.00", "3.00", supplier=s1), "采购单"),
        ("挂的采购单是别家供应商的", new_inv(NO_PREFIX + RUN + "-BAD2", "INPUT", "103.00", "3.00",
                                            supplier=s2, pos=[o1]), "同一家"),
        ("挂不存在的采购单", new_inv(NO_PREFIX + RUN + "-BAD3", "INPUT", "103.00", "3.00",
                                    supplier=s1, pos=[999999999]), "不存在"),
        ("进项票填了客户", new_inv(NO_PREFIX + RUN + "-BAD4", "INPUT", "103.00", "3.00",
                                  supplier=s1, customer=cid, pos=[o1]), "客户"),
        ("未税票却带了税额", new_inv(NO_PREFIX + RUN + "-BAD5", "INPUT", "103.00", None,
                                    supplier=s1, pos=[o1], tax_amount="3.00"), "税率"),
    ]
    rec = []
    for label, (st_, b_), kw in cases:
        det = detail_of(b_)
        rec.append({"case": label, "status": st_, "detail": det})
        check("② %s ⇒ 400 且文案点出原因" % label, st_ == 400 and kw in det,
              "status=%s detail=%s" % (st_, det[:160]))
    inv_after = count("select count(*) from invoices where invoice_no like ?", (NO_PREFIX + "%",))
    logs_after = len(tax_logs(floor))
    ev("322-tax-rejected.json", {"cases": rec, "invoices_before": inv_before, "invoices_after": inv_after,
                                 "links_on_po1_before": link_before, "links_on_po1_after": link_count(o1),
                                 "tax_logs_before": logs_before, "tax_logs_after": logs_after,
                                 "bad_numbers_in_db": count(
                                     "select count(*) from invoices where invoice_no like ?",
                                     (NO_PREFIX + RUN + "-BAD%",))})
    check("② 没有半成品：票头数一条不涨", inv_after == inv_before,
          "%s → %s" % (inv_before, inv_after))
    check("② 没有半成品：关联行一条不涨", link_count(o1) == link_before,
          "%s → %s" % (link_before, link_count(o1)))
    check("② 没有半成品：TAX_INVOICE_CREATE 日志一条没多写", logs_after == logs_before,
          "%s → %s" % (logs_before, logs_after))
    bad_left = count("select count(*) from invoices where invoice_no like ?", (NO_PREFIX + RUN + "-BAD%",))
    check("② 五个坏票号在库里都查不到", bad_left == 0, "库里还有 %s 条" % bad_left)

    # ------------------------------------------------------------ ③
    print()
    print("=== ③ 重复票号 409；空票号可多张；跨方向不冲突 ===")
    st, dup = new_inv(no1, "INPUT", "103.00", "3.00", supplier=s1, pos=[o1])
    det_dup = detail_of(dup)
    check("③ 同方向同票号再登记 ⇒ 409 且文案带票号", st == 409 and no1 in det_dup,
          "status=%s detail=%s" % (st, det_dup[:160]))
    st_a, b_a = new_inv("", "INPUT", "200.00", None, supplier=s1, pos=[o1])
    st_b, b_b = new_inv("", "INPUT", "200.00", None, supplier=s1, pos=[o1])
    row_a = invoice_row(int(b_a["id"])) if st_a in (200, 201) else None
    row_b = invoice_row(int(b_b["id"])) if st_b in (200, 201) else None
    check("③ 空票号能登记多张（唯一索引 (direction, no_key) 不拦 NULL）",
          bool(row_a) and bool(row_b) and int(b_a["id"]) != int(b_b["id"])
          and row_a[3] is None and row_b[3] is None,
          "两张 id=%s/%s，no_key=%s/%s，票号=%r/%r" % (b_a.get("id"), b_b.get("id"),
                                                      row_a[3] if row_a else None,
                                                      row_b[3] if row_b else None,
                                                      row_a[2] if row_a else None,
                                                      row_b[2] if row_b else None))
    st, out_same = new_inv(no1, "OUTPUT", "103.00", "3.00", customer=cid)
    check("③ 同一个号换个方向不冲突（唯一索引按 (direction, no_key)）",
          st in (200, 201) and int(out_same["id"]) != i1,
          "status=%s 销项 id=%s（进项那张是 %s）" % (st, (out_same or {}).get("id"), i1))
    ev("323-tax-duplicate.json", {"duplicate": {"status": st, "detail": det_dup},
                                  "blank_a": row_a, "blank_b": row_b,
                                  "blank_status": [st_a, st_b],
                                  "same_no_other_direction": {"status": st, "response": out_same}})

    # ------------------------------------------------------------ ④
    print()
    print("=== ④ 未税票：进 untaxed_*、不进 tax_amount ===")
    t0 = tax(token, TODAY, TODAY)
    st, inv4 = new_inv(NO_PREFIX + RUN + "-UNTAX", "INPUT", "500.00", None, supplier=s1, pos=[o1])
    if st not in (200, 201):
        return fail("④ 登记未税票失败：%s %s" % (st, inv4), keep)
    i4 = int(inv4["id"])
    r4 = invoice_row(i4)
    t1 = tax(token, TODAY, TODAY)
    d4 = deltas(t1[1], t0[1], "input")
    _st, det4 = call("GET", "/invoices/%d" % i4, token)
    row4 = rows_by_id(t1[1]).get(i4)
    zero_buckets = [b for b in (t1[1].get("by_rate") or []) if m(b["tax_rate"]) == 0]
    ev("324-tax-untaxed.json", {"status": st, "response": inv4, "db_row": r4, "detail": det4,
                                "tax_before_input": t0[1]["input"], "tax_after_input": t1[1]["input"],
                                "input_delta": d4, "detail_row": row4, "zero_rate_buckets": zero_buckets})
    check("④ 库里 tax_rate 与 tax_amount 都是 NULL（未税就是没税）",
          bool(r4) and r4[6] is None and r4[7] is None, "tax_rate=%s tax_amount=%s" % (r4[6], r4[7]))
    check("④ 税汇：untaxed_count +1 / untaxed_amount +500.00",
          d4["untaxed_count"] == 1 and d4["untaxed_amount"] == m("500.00"), d4)
    check("④ 税汇：count / amount / net_amount / tax_amount 一格没动",
          d4["count"] == 0 and d4["amount"] == 0 and d4["net_amount"] == 0 and d4["tax_amount"] == 0, d4)
    check("④ 明细行 counts_in_tax=False 且票面税额为空",
          bool(row4) and row4["counts_in_tax"] is False and not row4.get("tax_amount"), row4)
    check("④ 详情接口同样 counts_in_tax=False",
          bool(det4) and det4.get("counts_in_tax") is False, (det4 or {}).get("counts_in_tax"))
    check("④ by_rate 里没有 0 税率的小格（未税票不进税率分格）", not zero_buckets, zero_buckets)

    # ------------------------------------------------------------ ⑤
    print()
    print("=== ⑤ 作废：退出税汇、明细还在、采购单随即可删 ===")
    t0 = tax(token, TODAY, TODAY)
    st, inv5 = new_inv(NO_PREFIX + RUN + "-VOID1", "INPUT", "113.00", "13.00", supplier=s1, pos=[o2])
    if st not in (200, 201):
        return fail("⑤ 登记 13% 进项票失败：%s %s" % (st, inv5), keep)
    i5 = int(inv5["id"])
    r5 = invoice_row(i5)
    t1 = tax(token, TODAY, TODAY)
    check("⑤ 前置：13% 的票税额 13.00 且进了税汇",
          bool(r5) and m(r5[7]) == m("13.00") and deltas(t1[1], t0[1], "input")["tax_amount"] == m("13.00"),
          "tax_amount=%s 差值=%s" % (r5[7], deltas(t1[1], t0[1], "input")["tax_amount"]))
    st, v5 = call("POST", "/invoices/%d/void" % i5, token)
    if st != 200:
        return fail("⑤ 作废失败：%s %s" % (st, v5), keep)
    t2 = tax(token, TODAY, TODAY)
    d5 = deltas(t2[1], t0[1], "input")
    row5 = rows_by_id(t2[1]).get(i5)
    check("⑤ 作废后退出税汇：count/amount/net/tax 全部回到作废前",
          d5["count"] == 0 and d5["amount"] == 0 and d5["net_amount"] == 0 and d5["tax_amount"] == 0, d5)
    check("⑤ voided_count +1", dd(t2[1]["voided_count"], t0[1]["voided_count"]) == 1,
          "%s → %s" % (t0[1]["voided_count"], t2[1]["voided_count"]))
    check("⑤ 明细里还看得见：status=VOIDED、票面税额还是 13.00、counts_in_tax=False",
          bool(row5) and row5["status"] == "VOIDED" and m(row5["tax_amount"]) == m("13.00")
          and row5["counts_in_tax"] is False, row5)
    check("⑤ 库里 status=VOIDED 且没进回收站",
          invoice_row(i5)[8] == "VOIDED" and invoice_row(i5)[11] == 0, invoice_row(i5))
    before5 = identity(pid)
    st, dl5 = call("DELETE", "/purchase-orders/%d" % o2, token)
    after5 = identity(pid)
    ev("325-tax-void.json", {"invoice": r5, "void_response": v5, "tax_before_input": t0[1]["input"],
                             "tax_after_input": t2[1]["input"], "input_delta": d5,
                             "voided_count": [t0[1]["voided_count"], t2[1]["voided_count"]],
                             "detail_row": row5, "po_delete": {"status": st, "body": dl5},
                             "identity_before": before5, "identity_after": after5,
                             "order_row": order_row(o2)})
    check("⑤ 作废后那张采购单就能删（204）且库存退回 6 件",
          st == 204 and after5["stock"] == before5["stock"] - 6 and after5["identity_ok"],
          "删单 status=%s 库存 %s → %s 恒等式=%s" % (st, before5["stock"], after5["stock"], after5["identity_ok"]))

    # ------------------------------------------------------------ ⑥
    print()
    print("=== ⑥ 回收站：退出税汇、仍占号、恢复后原样回来 ===")
    t0 = tax(token, TODAY, TODAY)
    no6 = NO_PREFIX + RUN + "-TRASH"
    st, inv6 = new_inv(no6, "INPUT", "206.00", "3.00", supplier=s1, pos=[o1])
    if st not in (200, 201):
        return fail("⑥ 登记待删的票失败：%s %s" % (st, inv6), keep)
    i6 = int(inv6["id"])
    t1 = tax(token, TODAY, TODAY)
    check("⑥ 前置：这张票进了税汇（+6.00）",
          deltas(t1[1], t0[1], "input")["tax_amount"] == m("6.00"),
          deltas(t1[1], t0[1], "input"))
    st, dl6 = call("DELETE", "/invoices/%d" % i6, token)
    t2 = tax(token, TODAY, TODAY)
    d6 = deltas(t2[1], t0[1], "input")
    check("⑥ 删进回收站 ⇒ 204", st == 204, "%s %s" % (st, dl6))
    check("⑥ 回收站里的票退出税汇（差值回到 0）", d6["count"] == 0 and d6["tax_amount"] == 0, d6)
    check("⑥ 税账明细里不再出现它", i6 not in rows_by_id(t2[1]), sorted(rows_by_id(t2[1])))
    _st, det6 = call("GET", "/invoices/%d" % i6, token)
    check("⑥ 详情仍查得到且 is_deleted=True", bool(det6) and det6.get("is_deleted") is True,
          (det6 or {}).get("is_deleted"))
    st, dup6 = new_inv(no6, "INPUT", "206.00", "3.00", supplier=s1, pos=[o1])
    det6s = detail_of(dup6)
    check("⑥ 回收站里的票仍占号：再登记同号 ⇒ 409 且文案指向回收站",
          st == 409 and "回收站" in det6s, "status=%s detail=%s" % (st, det6s[:200]))
    st, rs6 = call("POST", "/invoices/%d/restore" % i6, token)
    t3 = tax(token, TODAY, TODAY)
    d6r = deltas(t3[1], t0[1], "input")
    ev("326-tax-trash.json", {"invoice": invoice_row(i6), "delete": {"status": st, "body": dl6},
                              "tax_after_create": t1[1]["input"], "tax_after_delete": t2[1]["input"],
                              "tax_after_restore": t3[1]["input"], "delta_delete": d6, "delta_restore": d6r,
                              "detail_hidden": i6 not in rows_by_id(t2[1]), "detail": det6,
                              "dup_in_trash": {"status": st, "detail": det6s},
                              "restore": rs6})
    check("⑥ 恢复 ⇒ 200、is_deleted 回 False、counts_in_tax 回 True",
          st == 200 and bool(rs6) and rs6.get("is_deleted") is False and rs6.get("counts_in_tax") is True,
          rs6)
    check("⑥ 恢复后税汇原样回来（count +1 / tax +6.00）",
          d6r["count"] == 1 and d6r["tax_amount"] == m("6.00"), d6r)
    check("⑥ 库里 deleted_at 清空", invoice_row(i6)[12] is None, invoice_row(i6))

    # ------------------------------------------------------------ ⑦
    print()
    print("=== ⑦ 采购单删单闸：挂着活票 ⇒ 400 且库存不许先退 ===")
    before7 = identity(pid)
    st, inv7 = new_inv(NO_PREFIX + RUN + "-GATE", "INPUT", "103.00", "3.00", supplier=s1, pos=[o3])
    if st not in (200, 201):
        return fail("⑦ 登记挂单票失败：%s %s" % (st, inv7), keep)
    i7 = int(inv7["id"])
    pay3 = int(order_row(o3)[4]) if order_row(o3)[4] else None
    mid_mv = [x for x in moves(pid) if x[0] in mv3]
    st, dl7 = call("DELETE", "/purchase-orders/%d" % o3, token)
    det7 = detail_of(dl7)
    mid = identity(pid)
    mid_mv2 = [x for x in moves(pid) if x[0] in mv3]
    mid_pay = payable_row(pay3) if pay3 else None
    check("⑦ 挂着没作废的进项票 ⇒ 400 且文案点名进项票",
          st == 400 and "进项票" in det7, "status=%s detail=%s" % (st, det7[:200]))
    check("⑦ 采购单还在（没被软删）", order_row(o3)[5] == 0, order_row(o3))
    check("⑦ **库存没有先退回去**（400 时一个字节都不动）",
          mid["stock"] == before7["stock"] and mid["identity_ok"] and mid["sum_change"] == before7["sum_change"],
          "before=%s after=%s" % (before7, mid))
    check("⑦ 那一行的流水还是活的（change 没清零、status 不是 VOID）",
          bool(mid_mv2) and all(int(x[1]) != 0 and x[3] != "VOID" for x in mid_mv2),
          "拦下前=%s 拦下后=%s" % (mid_mv, mid_mv2))
    check("⑦ 应付单也还在（没进回收站）", bool(mid_pay) and mid_pay[4] == 0, mid_pay)
    st, v7 = call("POST", "/invoices/%d/void" % i7, token)
    st_del, dl7b = call("DELETE", "/purchase-orders/%d" % o3, token)
    after7 = identity(pid)
    late_mv = [x for x in moves(pid) if x[0] in mv3]
    ev("327-tax-po-gate.json", {"invoice": invoice_row(i7), "blocked": {"status": st, "detail": det7},
                                "order_after_block": order_row(o3), "payable_after_block": mid_pay,
                                "moves_after_block": mid_mv2,
                                "identity_before": before7, "identity_after_block": mid, "identity_after_delete": after7,
                                "void": {"status": st, "body": v7},
                                "delete_after_void": {"status": st_del, "body": dl7b},
                                "moves_after_delete": late_mv, "order_after_delete": order_row(o3)})
    check("⑦ 把票作废之后删单才 204", st_del == 204, "%s %s" % (st_del, dl7b))
    check("⑦ 删单后库存退回 4 件、恒等式不破",
          after7["stock"] == before7["stock"] - 4 and after7["identity_ok"],
          "before=%s after=%s" % (before7, after7))
    check("⑦ 删单后那一行流水才算没发生过（change=0 / unit_cost 空 / status=VOID）",
          bool(late_mv) and all(int(x[1]) == 0 and x[2] is None and x[3] == "VOID" for x in late_mv), late_mv)

    # ------------------------------------------------------------ ⑧
    print()
    print("=== ⑧ 税账窗口按 invoice_date（含两端） ===")
    wa, wb, wc = ("2020-06-01", "2020-06-30"), ("2020-05-01", "2020-05-31"), ("2020-05-01", "2020-07-31")
    a0, b0, c0 = tax(token, *wa), tax(token, *wb), tax(token, *wc)
    st, e1 = new_inv(NO_PREFIX + RUN + "-WIN1", "INPUT", "103.00", "3.00", inv_date="2020-06-01", supplier=s1, pos=[o1])
    st2, e2 = new_inv(NO_PREFIX + RUN + "-WIN2", "INPUT", "103.00", "3.00", inv_date="2020-06-30", supplier=s1, pos=[o1])
    st3, e3 = new_inv(NO_PREFIX + RUN + "-WIN3", "INPUT", "103.00", "3.00", inv_date="2020-07-01", supplier=s1, pos=[o1])
    if any(x not in (200, 201) for x in (st, st2, st3)):
        return fail("⑧ 登记窗口票失败：%s / %s / %s" % (st, st2, st3), keep)
    a1, b1, c1 = tax(token, *wa), tax(token, *wb), tax(token, *wc)
    da, db_, dc = deltas(a1[1], a0[1], "input"), deltas(b1[1], b0[1], "input"), deltas(c1[1], c0[1], "input")
    ids_a = set(rows_by_id(a1[1]))
    ev("328-tax-window.json", {"window_june": {"span": wa, "label": a1[1].get("label"), "delta": da,
                                               "ids_in_detail": sorted(ids_a)},
                               "window_may": {"span": wb, "delta": db_},
                               "window_widened": {"span": wc, "delta": dc},
                               "invoices": [e1, e2, e3]})
    check("⑧ 两端都含：6-01 与 6-30 各进 3.00（count 2 / tax 6.00）",
          da["count"] == 2 and da["tax_amount"] == m("6.00"), da)
    check("⑧ 明细里两端那两张在、窗外（7-01）那张不在",
          {int(e1["id"]), int(e2["id"])} <= ids_a and int(e3["id"]) not in ids_a,
          "在=%s 窗外那张=%s" % (sorted(ids_a), e3["id"]))
    check("⑧ 相邻窗口（5 月）一分钱不受影响", db_["count"] == 0 and db_["tax_amount"] == 0, db_)
    check("⑧ 窗口放宽到 5–7 月：三张都进来（count 3 / tax 9.00）",
          dc["count"] == 3 and dc["tax_amount"] == m("9.00"), dc)

    # ------------------------------------------------------------ ⑨
    print()
    print("=== ⑨ 利润表：税类开销不双扣、vat 不进营业利润 ===")
    p0 = profit(token, TODAY)
    if p0[0] != 200:
        return fail("⑨ 读利润表失败：%s %s" % (p0[0], p0[1]), keep)
    st, exp = call("POST", "/expenses", token, {"exp_date": TODAY, "category": EXP_CAT,
                                                "amount": "77.77", "note": EXP_NOTE})
    if st != 200:
        return fail("⑨ 记一笔税金开销失败：%s %s" % (st, exp), keep)
    eid = int(exp["id"])
    SEEN["expenses"].add(eid)
    p1 = profit(token, TODAY)
    P0, P1 = p0[1], p1[1]
    _st, t9 = tax(token, TODAY, TODAY)
    tax_rows = [r for r in (P1.get("tax_expenses") or []) if r.get("category") == EXP_CAT]
    op_cats = [r.get("category") for r in (P1.get("operating_expenses") or [])]
    ident = (m(P1["gross_profit"]) - m(P1["delivery_cost"]) - m(P1["operating_expense_total"])
             - m(P1["depreciation_total"]) - m(P1["tax_total"]))
    vat = m(P1["vat_payable"])
    ev("329-tax-profit.json", {"expense": exp, "profit_before": P0, "profit_after": P1,
                               "tax_total_before_after": [P0["tax_total"], P1["tax_total"]],
                               "operating_expense_total": [P0["operating_expense_total"], P1["operating_expense_total"]],
                               "operating_profit": [P0["operating_profit"], P1["operating_profit"]],
                               "tax_rows": tax_rows, "operating_categories": op_cats,
                               "identity_left": str(ident), "identity_right": P1["operating_profit"],
                               "tax_summary_same_window": {"output": t9["output"], "input": t9["input"],
                                                           "vat_payable": t9["vat_payable"]}})
    check("⑨ tax_total 增加 77.77（分类名带「税」）",
          dd(P1["tax_total"], P0["tax_total"]) == m("77.77"),
          "%s → %s" % (P0["tax_total"], P1["tax_total"]))
    check("⑨ tax_expenses 里就是这一笔", bool(tax_rows) and m(tax_rows[0]["amount"]) == m("77.77"), tax_rows)
    check("⑨ 这笔**不再**出现在 operating_expenses（不双扣）", EXP_CAT not in op_cats, op_cats)
    check("⑨ operating_expense_total 一动没动",
          dd(P1["operating_expense_total"], P0["operating_expense_total"]) == 0,
          "%s → %s" % (P0["operating_expense_total"], P1["operating_expense_total"]))
    check("⑨ operating_profit 少 77.77", dd(P1["operating_profit"], P0["operating_profit"]) == m("-77.77"),
          "%s → %s" % (P0["operating_profit"], P1["operating_profit"]))
    check("⑨ 恒等式：operating_profit == 毛利 − 运费 − 开销 − 折旧 − 税",
          ident == m(P1["operating_profit"]), "左边=%s 右边=%s" % (ident, P1["operating_profit"]))
    check("⑨ vat_output / vat_input / vat_payable 与税汇同窗口一致",
          m(P1["vat_output"]) == m(t9["output"]["tax_amount"]) and m(P1["vat_input"]) == m(t9["input"]["tax_amount"])
          and m(P1["vat_payable"]) == m(t9["vat_payable"]),
          "利润表=%s/%s/%s 税汇=%s/%s/%s" % (P1["vat_output"], P1["vat_input"], P1["vat_payable"],
                                            t9["output"]["tax_amount"], t9["input"]["tax_amount"],
                                            t9["vat_payable"]))
    check("⑨ vat_payable 不进 operating_profit（本期有税额才证得动）",
          vat != 0 and (ident - vat) != m(P1["operating_profit"]),
          "vat_payable=%s；若连它一起扣，左边会变成 %s（≠ %s）" % (vat, ident - vat, P1["operating_profit"]))

    # ------------------------------------------------------------ ⑩
    print()
    print("=== ⑩ tax-summary：by_rate 排序与合计、vat_payable 恒等式 ===")
    # 先让两个方向各凑出 ≥2 个税率格：只有一格时「税率从高到低」是平凡真，证不了排序。
    po9, err9 = new_po(s1, 2, "10.00")                       # 20.00
    if err9:
        return fail("⑩ 前置采购单失败：%s" % (err9,), keep)
    o9 = int(po9["id"])
    st, out13 = new_inv(NO_PREFIX + RUN + "-OUT13", "OUTPUT", "113.00", "13.00", customer=cid)
    if st not in (200, 201):
        return fail("⑩ 前置销项 13% 票失败：%s %s" % (st, out13), keep)
    st, in9 = new_inv(NO_PREFIX + RUN + "-IN9", "INPUT", "109.00", "9.00", supplier=s1, pos=[o9])
    if st not in (200, 201):
        return fail("⑩ 前置进项 9% 票失败：%s %s" % (st, in9), keep)
    _st, T = tax(token, TODAY, TODAY)
    by = T.get("by_rate") or []
    dirs = [str(b["direction"]) for b in by]
    rates: dict[str, list] = {}
    for b in by:
        rates.setdefault(str(b["direction"]), []).append(m(b["tax_rate"]))
    mono = all(all(v[i] >= v[i + 1] for i in range(len(v) - 1)) for v in rates.values())
    sums, ok_sum = {}, True
    for k in ("output", "input"):
        sub = [b for b in by if str(b["direction"]).lower() == k]
        c = sum(int(b["count"]) for b in sub)
        t = sum((m(b["tax_amount"]) for b in sub), Decimal("0"))
        sums[k] = {"buckets": len(sub), "count": c, "tax_amount": str(t),
                   "side_count": T[k]["count"], "side_tax_amount": str(T[k]["tax_amount"])}
        ok_sum = ok_sum and c == int(T[k]["count"]) and t == m(T[k]["tax_amount"])
    ev("329-tax-by-rate.json", {"label": T.get("label"), "span": [T.get("date_from"), T.get("date_to")],
                                "by_rate": by, "output": T["output"], "input": T["input"],
                                "vat_payable": T["vat_payable"], "notes": T.get("notes"),
                                "bucket_sums": sums,
                                "identity": str(m(T["vat_payable"])),
                                "output_minus_input": str(m(T["output"]["tax_amount"]) - m(T["input"]["tax_amount"]))})
    check("⑩ 前置：两个方向各 ≥2 个税率格（否则下面的排序判据是平凡真）",
          len(rates.get("OUTPUT", [])) >= 2 and len(rates.get("INPUT", [])) >= 2,
          {k: [str(x) for x in v] for k, v in rates.items()})
    check("⑩ by_rate 销项在前、进项在后",
          dirs == sorted(dirs, key=lambda x: 0 if x.upper() == "OUTPUT" else 1), dirs)
    check("⑩ 每个方向内税率从高到低", mono, {k: [str(x) for x in v] for k, v in rates.items()})
    check("⑩ 每格合计 == 该侧合计（count 与 tax_amount）", ok_sum, sums)
    check("⑩ vat_payable == output.tax_amount − input.tax_amount",
          m(T["vat_payable"]) == m(T["output"]["tax_amount"]) - m(T["input"]["tax_amount"]),
          "%s == %s − %s" % (T["vat_payable"], T["output"]["tax_amount"], T["input"]["tax_amount"]))

    # ------------------------------------------------------------ ⑪
    print()
    print("=== ⑪ 留痕：六个动作码都真的落了行 ===")
    t0 = tax(token, TODAY, TODAY)
    st, up1 = call("PATCH", "/invoices/%d" % i1, token, {"amount": "123.60"})
    r1b = invoice_row(i1)
    t1 = tax(token, TODAY, TODAY)
    check("⑪ 改金额 ⇒ 税额按税率重算（123.60 含 3% ⇒ 3.60）",
          st == 200 and bool(r1b) and m(r1b[7]) == m("3.60"),
          "status=%s 库里 tax_amount=%s" % (st, r1b[7] if r1b else None))
    check("⑪ 税汇跟着动 +0.60",
          dd(t1[1]["input"]["tax_amount"], t0[1]["input"]["tax_amount"]) == m("0.60"),
          "%s → %s" % (t0[1]["input"]["tax_amount"], t1[1]["input"]["tax_amount"]))
    st, iss4 = call("POST", "/invoices/%d/issue" % i4, token)
    check("⑪ 开具 ⇒ ISSUED（未税票，不影响税汇）",
          st == 200 and bool(iss4) and iss4.get("status") == "ISSUED", "%s %s" % (st, iss4))
    logs = tax_logs(floor)
    got: dict[str, int] = {}
    for _id, act, _c in logs:
        got[str(act)] = got.get(str(act), 0) + 1
    missing = [x for x in SIX_ACTIONS if x not in got]
    ev("329-tax-audit.json", {"counts": got, "missing": missing, "total": len(logs),
                              "update_response": up1, "update_row": r1b, "issue_response": iss4,
                              "logs": logs})
    check("⑪ 六个动作码都落了行（CREATE/UPDATE/ISSUE/VOID/DELETE/RESTORE）", not missing,
          "缺=%s 实到=%s" % (missing, got))
    check("⑪ 日志条数与真实动作数对得上（本轮 ≥ 11 条）", len(logs) >= 11, "共 %s 条" % len(logs))

    # ------------------------------------------------------------ 还原
    print()
    print("=== 还原：只删探针自己造的行 ===")
    ids = {k: sorted(v) for k, v in SEEN.items()}
    if keep:
        print("  --keep：保留现场")
        ev("329-tax-cleanup.json", {"kept": True, "ids": ids})
    else:
        removed = drop_probe()
        left = still_there()
        ev("329-tax-cleanup.json", {"removed": removed, "left": left, "ids": ids})
        check("清理：探针数据已硬删干净（票头/关联行/流水/单据/主数据/日志）",
              sum(left.values()) == 0, "删了 %s；表里还剩 %s" % (removed or "无", left))
        over = {t: (removed.get(t, 0), len(SEEN.get(t, ())))
                for t in SEEN if removed.get(t, 0) > len(SEEN.get(t, ()))}
        check("清理：每张表删掉的行数都不超过本探针自己造的条数（防越界删到别人的行）",
              not over, over or "逐表都比过：删 ≤ 造")
        check("清理：资金流水只删了本探针开销写的那一条（doc_id 在别的 party 下指向别的主键）",
              removed.get("cash_flows", 0) <= 1,
              "cash_flows 删了 %s 条（探针自己只写了 1 条开销流水）" % removed.get("cash_flows", 0))

    print()
    if BAD:
        print("❌ 税账探针没全绿：%d 条没通过" % len(BAD))
        for x in BAD:
            print("   · %s" % x)
        return 1
    print("✅ 税账探针全绿：登记/税额自洽、坏提交不留渣、唯一号、未税、作废、回收站占号、"
          "删单闸不退库存、窗口含两端、利润不双扣、税率分格、六个动作码留痕（共 %d 条断言）" % TOTAL[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

