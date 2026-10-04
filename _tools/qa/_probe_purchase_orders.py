"""打真后端验「采购与进货价闭环」这条路（FEAT-0013 / L3）。

### 为什么必须打真库
这一轮改的三处事实（库存 / 成本价 / 供应商欠款）在**同一个事务**里写，而且改单是
**改写既有流水**。HTTP 200 只能证明"请求被接受了"：三处数字是否同时对得上、
失败时有没有留半成品，只有对库才证伪得了。本轮已经踩过两个静默坑，探针就是它们的复验手段：
  · 撤掉唯一一行带价进货后，商品成本价被记成 **0**（报表读成「成本是 0」= 毛利虚高）
  · 写请求返回 400 之后，半成品改动留在会话里，被**下一个请求**的 commit 带进库
    （「已付款单删不掉」这条：删单返回 400、库存却已经退回去了）

### 它验什么（每条都读库，不读响应体里那句"看起来对"）
1. 建单 ⇒ 库存 +量、成本价 = 进货价、应付 = 量 × 价（三处同一次提交写完）
2. 改单 ⇒ **改写那一条流水**（不是又记一笔）、库存与应付跟着改（同一张应付，不新建）
3. 撤行 ⇒ 流水 change=0 / unit_cost=NULL / status=VOID、库存退回去、**成本价不抹成 0**
4. 失败请求（同单同商品 400）不留半成品：库存 / 流水条数 / 成本价 / 应付一字未动
5. 撤销整张单 ⇒ 三处一起退、默认列表看不见、include_deleted=true 看得见、应付一起进回收站
6. 恢复 ⇒ 原样回来（流水回到 COMMITTED、库存 / 成本价 / 应付都回来）
7. **已付款的单删不掉** ⇒ 400 且库存**没有**先退回去；撤销那笔付款之后就能删
8. 成本覆盖报表：revenue_uncovered == revenue_total − revenue_covered、口径说明里没有 markdown 星号

### 隔离
探针自己建一个商品（下面 PROBE_PRODUCT）与它自己的单；跑完（缺省）把这几张表里属于它的
行硬删掉：purchase_order_items / purchase_orders / inventory_movements / product_cost_history /
supplier_payables / cash_flows / products。⛔ 不碰任何真实商品、真实供应商的既有数据。

用法：
    python _tools/qa/_probe_purchase_orders.py            # 跑一遍并还原（默认）
    python _tools/qa/_probe_purchase_orders.py --keep     # 不还原，留现场给人看
证据：_tmp/ev/3xx-*.json（每次跑覆盖）
"""
import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
BASE = "http://127.0.0.1:8000/api/v1"
DB = ROOT / "backend/sorders.db"
EV = ROOT / "_tmp/ev"
PHONE, PASSWORD = "13800000001", "pass12345"  # 开发库那三个测试号（backend/scripts/reset_dev_passwords.py）
PROBE_PRODUCT = "探针商品-采购闭环"
PROBE_REMARK = "探针：采购与进货价闭环（FEAT-0013）"

BAD: list[str] = []


def call(method: str, path: str, token: str | None = None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
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


def check(label: str, cond: bool, detail) -> None:
    print("  [%s] %s —— %s" % ("OK" if cond else "FAIL", label, detail))
    if not cond:
        BAD.append(label)


def ev(name: str, payload) -> None:
    EV.mkdir(parents=True, exist_ok=True)
    p = EV / name
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("  → 证据 %s" % p.relative_to(ROOT))


# ---------------------------------------------------------------- 库上的三处事实

def stock(pid: int) -> int:
    return int(one("select stock from products where id=?", (pid,))[0])


def cost(pid: int) -> Decimal:
    return Decimal(str(one("select cost_price from products where id=?", (pid,))[0]))


def moves(pid: int) -> list[list]:
    return rows(
        "select id,change,unit_cost,status,source,note from inventory_movements "
        "where product_id=? order by id", (pid,))


def sum_change(pid: int) -> int:
    return int(one("select coalesce(sum(change),0) from inventory_movements where product_id=?", (pid,))[0])


def payable(pid_: int):
    return one("select id,supplier_id,title,category,amount,is_deleted from supplier_payables where id=?", (pid_,))


def identity(pid: int) -> dict:
    return {"stock": stock(pid), "sum_change": sum_change(pid), "identity_ok": stock(pid) == sum_change(pid)}


def snapshot(pid: int) -> dict:
    return {
        "product_id": pid,
        "stock": stock(pid),
        "cost_price": str(cost(pid)),
        "sum_change": sum_change(pid),
        "moves": moves(pid),
        "cost_history": rows(
            "select id,cost_price,source,effective_to,movement_id from product_cost_history "
            "where product_id=? order by id", (pid,)),
    }


def order_row(oid: int):
    return one("select id,supplier_id,doc_date,remark,payable_id,is_deleted from purchase_orders where id=?", (oid,))


def items_of(oid: int) -> list[list]:
    return rows(
        "select id,product_id,quantity,unit_cost,movement_id,is_void from purchase_order_items "
        "where order_id=? order by id", (oid,))


def audit_actions() -> list[str]:
    return [r[0] for r in rows(
        "select action from operation_logs where action like 'PURCHASE_ORDER%' order by id")]


# ---------------------------------------------------------------- 还原（只删探针自己造的行）

def drop_probe() -> dict:
    con = sqlite3.connect(DB)
    removed: dict[str, int] = {}
    try:
        pids = [r[0] for r in con.execute("select id from products where name=?", (PROBE_PRODUCT,))]
        for pid in pids:
            oids = [r[0] for r in con.execute(
                "select distinct order_id from purchase_order_items where product_id=?", (pid,))]
            pays: list[int] = []
            for oid in oids:
                r = con.execute("select payable_id from purchase_orders where id=?", (oid,)).fetchone()
                if r and r[0]:
                    pays.append(int(r[0]))
            # 付款是资金流水（cash_flows），挂单据那一列叫 doc_id（不是 payable_id）
            flows = [r[0] for r in con.execute(
                "select id from cash_flows where doc_id in (%s) and biz_type='PAYMENT_SUPPLIER'"
                % ",".join("?" * len(pays)), pays)] if pays else []
            if flows:
                con.execute("delete from cash_flows where id in (%s)" % ",".join("?" * len(flows)), flows)
            if pays:
                con.execute("delete from supplier_payables where id in (%s)" % ",".join("?" * len(pays)), pays)
            if oids:
                con.execute("delete from purchase_order_items where order_id in (%s)" % ",".join("?" * len(oids)), oids)
                con.execute("delete from purchase_orders where id in (%s)" % ",".join("?" * len(oids)), oids)
            con.execute("delete from inventory_movements where product_id=?", (pid,))
            con.execute("delete from product_cost_history where product_id=?", (pid,))
            con.execute("delete from products where id=?", (pid,))
            removed = {"products": 1, "orders": len(oids), "payables": len(pays), "flows": len(flows)}
        con.commit()
    finally:
        con.close()
    return removed


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="跑完不还原，留现场给人看")
    a = ap.parse_args()

    st, tok = call("POST", "/auth/login", body={"phone": PHONE, "password": PASSWORD})
    if st != 200:
        print("❌ 登录失败（本地后端在跑吗？）：%s %s" % (st, tok))
        return 1
    token = tok["access_token"]
    today = date.today().isoformat()

    sup = one("select id,name from suppliers where is_deleted=0 order by id limit 1")
    if sup is None:
        print("❌ 库里没有可用的供应商")
        return 1
    sid, sname = int(sup[0]), sup[1]
    print("== 起始：供应商 #%s %s；先清掉上次没还原的探针数据 %s" % (sid, sname, drop_probe()))

    st, body = call("POST", "/products", token, {
        "name": PROBE_PRODUCT, "unit": "箱", "default_unit_price": "0",
        "cost_price": "0", "stock": 0, "category": "探针"})
    if st not in (200, 201):
        print("❌ 探针商品建不出来：%s %s" % (st, body))
        return 1
    pid = int(body["id"])
    log_start = len(audit_actions())
    pid0, stock0, cost0 = pid, stock(pid), cost(pid)
    base = snapshot(pid)
    ev("300-po-baseline.json", {"supplier": {"id": sid, "name": sname}, "baseline": base})
    check("起始：新商品的库存 0 且没有任何流水", stock0 == 0 and base["sum_change"] == 0, base)

    # ---- ① 建单：三件事一次写完 ----
    st, o = call("POST", "/purchase-orders", token, {
        "supplier_id": sid, "doc_date": today, "remark": PROBE_REMARK,
        "items": [{"product_id": pid, "quantity": 5, "unit_cost": "12.50"}]})
    oid = o.get("id") if isinstance(o, dict) else None
    if oid is None:
        print("❌ 建单失败：%s %s" % (st, o))
        drop_probe()
        return 1
    mv = moves(pid)
    pay = payable(int(o["payable_id"]))
    step1 = {"status": st, "order": o, "inventory_movements": mv, "payable": pay, "identity": identity(pid)}
    ev("310-po-create.json", step1)
    check("建单 201", st == 201, st)
    check("库存 +5（与流水同一次提交）", stock(pid) == stock0 + 5, stock(pid))
    check("成本价 = 进货价 12.50", cost(pid) == Decimal("12.50"), cost(pid))
    check("一条流水：change=5 / unit_cost=12.50 / status=COMMITTED / source=PURCHASE",
          len(mv) == 1 and mv[0][1] == 5 and str(mv[0][2]) in ("12.5", "12.50")
          and mv[0][3] == "COMMITTED" and mv[0][4] == "PURCHASE", mv)
    check("流水备注能指回这张单（采购单 #N）", ("采购单 #%s" % oid) in (mv[0][5] or ""), mv[0][5])
    check("应付：货款 / 62.50 / 标题带单号 / 挂在同一个供应商 / 没进回收站",
          pay is not None and pay[1] == sid and pay[3] == "货款"
          and Decimal(str(pay[4])) == Decimal("62.50") and ("采购单 #%s" % oid) in pay[2]
          and not pay[5], pay)
    check("出参合计是两位小数字符串 62.50", o.get("total") == "62.50", o.get("total"))
    check("列表按住供应商筛得到它", any(r.get("id") == oid for r in (
        call("GET", "/purchase-orders?supplier_id=%s" % sid, token)[1] or [])), "GET /purchase-orders")
    check("恒等式 Σ(change) == stock", identity(pid)["identity_ok"], identity(pid))

    # ---- ② 改单：改的是那一条流水，不是又记一笔 ----
    item_id = items_of(oid)[0][0]
    mv_id = mv[0][0]
    st, o2 = call("PATCH", "/purchase-orders/%s" % oid, token, {
        "items": [{"id": item_id, "product_id": pid, "quantity": 8, "unit_cost": "13.00"}]})
    mv2 = moves(pid)
    pay2 = payable(int(o["payable_id"]))
    ev("320-po-update.json", {"status": st, "order": o2, "inventory_movements": mv2, "payable": pay2,
                              "items": items_of(oid), "identity": identity(pid)})
    check("改单 200 且合计变成 104.00", st == 200 and o2.get("total") == "104.00", "%s %s" % (st, o2.get("total")))
    check("★ 没有又记一笔：仍然只有 1 条流水、且是同一条 id", len(mv2) == 1 and mv2[0][0] == mv_id, mv2)
    check("那条流水被改写成 change=8 / unit_cost=13.00", mv2[0][1] == 8 and Decimal(str(mv2[0][2])) == Decimal("13"),
          mv2[0])
    check("库存变成 +8", stock(pid) == stock0 + 8, stock(pid))
    check("成本价跟着变成 13.00", cost(pid) == Decimal("13.00"), cost(pid))
    check("★ 应付是同一张（没新建）且金额改成 104.00",
          pay2[0] == pay[0] and Decimal(str(pay2[4])) == Decimal("104.00"), pay2)
    check("恒等式 Σ(change) == stock", identity(pid)["identity_ok"], identity(pid))

    # ---- ③ 撤行：流水摆成「没发生过」，但成本价不许被抹成 0 ----
    st, o3 = call("PATCH", "/purchase-orders/%s" % oid, token, {"items": []})
    mv3, it3 = moves(pid), items_of(oid)
    ev("330-po-void-line.json", {"status": st, "order": o3, "inventory_movements": mv3, "items": it3,
                                 "product": {"stock": stock(pid), "cost_price": str(cost(pid))},
                                 "identity": identity(pid)})
    check("撤行 200，行还留在单子上（撤掉的量与原价能对证）",
          len(it3) == 1 and it3[0][5] == 1 and it3[0][2] == 8, it3)
    check("流水：change=0 / unit_cost=NULL / status=VOID",
          mv3[0][1] == 0 and mv3[0][2] is None and mv3[0][3] == "VOID", mv3[0])
    check("库存退回起点", stock(pid) == stock0, stock(pid))
    check("★ 成本价没有被抹成 0（0 会被报表读成「成本是 0」= 毛利虚高）", cost(pid) != Decimal("0"), cost(pid))
    check("成本价停在上一次的价 13.00（没有任何还活着的带价入库时不乱改）",
          cost(pid) == Decimal("13.00"), cost(pid))
    check("应付跟着归零（单子还在、金额 0.00）",
          Decimal(str(payable(int(o["payable_id"]))[4])) == Decimal("0"), payable(int(o["payable_id"])))
    check("恒等式 Σ(change) == stock", identity(pid)["identity_ok"], identity(pid))

    # ---- ④ 失败请求不留半成品：同一张单里同一个商品两次 → 400 ----
    before_dup = {"stock": stock(pid), "moves": len(moves(pid)), "cost": str(cost(pid)),
                  "payable": str(payable(int(o["payable_id"]))[4]),
                  "orders": len(rows("select id from purchase_orders"))}
    st, b4 = call("POST", "/purchase-orders", token, {
        "supplier_id": sid, "doc_date": today, "remark": PROBE_REMARK,
        "items": [{"product_id": pid, "quantity": 3, "unit_cost": "9.00"},
                  {"product_id": pid, "quantity": 4, "unit_cost": "9.00"}]})
    after_dup = {"stock": stock(pid), "moves": len(moves(pid)), "cost": str(cost(pid)),
                 "payable": str(payable(int(o["payable_id"]))[4]),
                 "orders": len(rows("select id from purchase_orders"))}
    ev("340-po-dup-rejected.json", {"status": st, "body": b4, "before": before_dup, "after": after_dup})
    check("同单同商品 → 400", st == 400, "%s %s" % (st, b4))
    check("★ 400 之后一字未动（库存 / 流水条数 / 成本价 / 应付 / 单数）", before_dup == after_dup,
          "%s → %s" % (before_dup, after_dup))

    # ---- ⑤ 重新加一行，然后撤销整张单 ----
    st, o5 = call("PATCH", "/purchase-orders/%s" % oid, token, {
        "items": [{"product_id": pid, "quantity": 6, "unit_cost": "11.00"}]})
    mv5 = moves(pid)
    ev("350-po-readd-line.json", {"status": st, "order": o5, "inventory_movements": mv5,
                                  "identity": identity(pid)})
    check("重新加一行 200 且合计 66.00", st == 200 and o5.get("total") == "66.00", o5.get("total"))
    check("新增的那一行有自己的流水（现在是 2 条：1 条 VOID + 1 条 COMMITTED）",
          len(mv5) == 2 and mv5[1][1] == 6 and Decimal(str(mv5[1][2])) == Decimal("11"), mv5)
    check("库存 +6、成本价 11.00", stock(pid) == stock0 + 6 and cost(pid) == Decimal("11.00"),
          "%s / %s" % (stock(pid), cost(pid)))

    st, _ = call("DELETE", "/purchase-orders/%s" % oid, token)
    mv6, pay6 = moves(pid), payable(int(o["payable_id"]))
    live = call("GET", "/purchase-orders?supplier_id=%s" % sid, token)[1] or []
    dead = call("GET", "/purchase-orders?supplier_id=%s&include_deleted=true" % sid, token)[1] or []
    pay_list = call("GET", "/supplier-payables?supplier_id=%s" % sid, token)[1] or []
    ev("360-po-delete.json", {"status": st, "order_row": order_row(oid), "inventory_movements": mv6,
                              "payable": pay6, "list_default": live, "list_include_deleted": dead,
                              "supplier_payables": pay_list, "identity": identity(pid)})
    check("撤销返回 204", st == 204, st)
    check("两条流水都摆成「没发生过」（change=0 / unit_cost=NULL / VOID）",
          all(r[1] == 0 and r[2] is None and r[3] == "VOID" for r in mv6), mv6)
    check("库存回到起点", stock(pid) == stock0, stock(pid))
    check("成本价仍不是 0（11.00 留着）", cost(pid) == Decimal("11.00"), cost(pid))
    check("默认列表里看不见它", oid not in [r["id"] for r in live], [r["id"] for r in live][:5])
    check("include_deleted=true 看得见且 is_deleted=true",
          any(r["id"] == oid and r["is_deleted"] for r in dead), "dead=%s" % len(dead))
    check("应付一起进了回收站（供应商页看不见它）",
          pay6[5] == 1 and o["payable_id"] not in [r["id"] for r in pay_list], pay6)
    check("恒等式 Σ(change) == stock", identity(pid)["identity_ok"], identity(pid))

    # ---- ⑥ 恢复：原样回来 ----
    st, o7 = call("POST", "/purchase-orders/%s/restore" % oid, token)
    mv7, pay7 = moves(pid), payable(int(o["payable_id"]))
    ev("370-po-restore.json", {"status": st, "order": o7, "order_row": order_row(oid),
                               "inventory_movements": mv7, "payable": pay7, "identity": identity(pid)})
    check("恢复 200 且 is_deleted=false", st == 200 and o7.get("is_deleted") is False, "%s %s" % (st, o7.get("is_deleted")))
    check("库存回来 +6", stock(pid) == stock0 + 6, stock(pid))
    check("成本价回到 11.00", cost(pid) == Decimal("11.00"), cost(pid))
    check("那一条流水回到 COMMITTED / change=6 / unit_cost=11.00",
          mv7[1][1] == 6 and Decimal(str(mv7[1][2])) == Decimal("11") and mv7[1][3] == "COMMITTED", mv7[1])
    check("应付恢复了且金额 66.00",
          pay7[5] == 0 and Decimal(str(pay7[4])) == Decimal("66.00"), pay7)
    check("恒等式 Σ(change) == stock", identity(pid)["identity_ok"], identity(pid))

    # ---- ⑦ 已付款的单删不掉，而且**库存不能先退回去** ----
    st, flow = call("POST", "/supplier-payables/%s/payments" % o["payable_id"], token,
                    {"amount": "10.00", "pay_date": today, "channel": "cash", "remark": PROBE_REMARK})
    st_del, b_del = call("DELETE", "/purchase-orders/%s" % oid, token)
    mid = {"stock": stock(pid), "moves": moves(pid), "order": order_row(oid),
           "payable": payable(int(o["payable_id"]))}
    ev("380-po-paid-delete-rejected.json", {"payment_status": st, "payment": flow,
                                            "delete_status": st_del, "delete_body": b_del, "mid_state": mid,
                                            "identity": identity(pid)})
    check("先给它记一笔 10.00 的付款", st == 201, "%s %s" % (st, flow))
    check("★ 已经付过钱的单删不掉 → 400", st_del == 400, "%s %s" % (st_del, b_del))
    check("★ 而且库存**没有**先退回去（2026-10-04 修的就是这条）", stock(pid) == stock0 + 6, stock(pid))
    check("流水仍是活的、单子还在", mid["moves"][1][3] == "COMMITTED" and mid["order"][5] == 0, mid["order"])

    st, _ = call("DELETE", "/supplier-payments/%s" % (flow.get("id") if isinstance(flow, dict) else None), token)
    st_del2, _ = call("DELETE", "/purchase-orders/%s" % oid, token)
    ev("385-po-delete-after-void-payment.json", {"void_payment_status": st, "delete_status": st_del2,
                                                 "order_row": order_row(oid), "identity": identity(pid)})
    check("把那笔付款撤销之后就能删单（204）", st == 204 and st_del2 == 204, "%s / %s" % (st, st_del2))

    st, o9 = call("POST", "/purchase-orders/%s/restore" % oid, token)
    check("最后再恢复一次（留一个健康状态）", st == 200 and stock(pid) == stock0 + 6, "%s" % st)

    # ---- ⑧ 成本覆盖报表：恒等式与口径说明 ----
    st, rep = call("GET", "/reports/cost-coverage?mode=month&date=%s" % today, token)
    ev("390-cost-coverage.json", {"status": st, "report": rep})
    if st != 200 or not isinstance(rep, dict):
        check("成本覆盖报表能取到（200）", False, "%s %s" % (st, rep))
    else:
        rt, rc, ru = (Decimal(str(rep["revenue_total"])), Decimal(str(rep["revenue_covered"])),
                      Decimal(str(rep["revenue_uncovered"])))
        check("成本覆盖报表 200", True, rep.get("period_label"))
        check("恒等式 revenue_uncovered == revenue_total − revenue_covered", ru == rt - rc,
              "%s == %s − %s" % (ru, rt, rc))
        check("算得出成本的行数 ≤ 总行数", int(rep["covered_lines"]) <= int(rep["total_lines"]),
              "%s / %s" % (rep["covered_lines"], rep["total_lines"]))
        check("口径说明里没有 markdown 星号（界面直接显示纯文本）",
              not any("*" in n for n in rep["notes"]), rep["notes"][:1])
        check("★ 刚进过货的商品不在「从来没记过进货价」清单里",
              pid not in [p["product_id"] for p in rep["missing_purchase_price"]],
              rep["missing_purchase_price_count"])

    # ---- ⑨ 留痕：四个动作码都要出现 ----
    acts = audit_actions()[log_start:]
    ev("395-po-audit.json", {"actions": acts})
    check("四个动作码都留了痕（建 / 改 / 删 / 恢复）",
          {"PURCHASE_ORDER_CREATE", "PURCHASE_ORDER_UPDATE", "PURCHASE_ORDER_DELETE",
           "PURCHASE_ORDER_RESTORE"} <= set(acts), sorted(set(acts)))

    # ---- ⑩ 还原 ----
    if a.keep:
        print("== --keep：不还原（探针商品 #%s、单 #%s 留在库里）" % (pid, oid))
        ev("399-po-cleanup.json", {"kept": True, "product_id": pid, "order_id": oid})
    else:
        removed = drop_probe()
        gone = one("select id from products where id=?", (pid,)) is None
        left = {"orders": len(rows("select id from purchase_orders where id=?", (oid,))),
                "moves": len(moves(pid)), "payables": len(rows(
                    "select id from supplier_payables where id=?", (o["payable_id"],)))}
        ev("399-po-cleanup.json", {"removed": removed, "product_gone": gone, "left": left})
        check("还原：探针商品与它的单 / 流水 / 应付 / 成本区间都清掉了",
              gone and left == {"orders": 0, "moves": 0, "payables": 0}, left)

    print("=" * 60)
    if BAD:
        print("❌ %d 项不成立：" % len(BAD))
        for b in BAD:
            print("   · %s" % b)
        return 1
    print("✅ 全部断言通过（采购与进货价闭环：库存 / 成本价 / 应付三处一致）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
