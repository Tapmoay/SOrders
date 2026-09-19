"""重复提交 / 幂等性测试（fuzz #4）：**同一件事做两次，会不会变成两笔**。

## 为什么单独做这一件
"钱多了一笔"这类缺陷不会报错、也不会在界面上显示成异常：司机账单、收款单、库存流水
都是**追加式**的表，重复执行的唯一表现就是"多了一行"。本项目已经出过一次
（同一张单被逐单核销两次 → 两条收款记录 + 两条现金流水），而且 `driver_bills`
**至今没有 `(order_id, bill_type)` 唯一约束**，幂等只靠"先查再插"。

## 判据锚在"效果"上
不看返回码，看**库里多了什么**：比较操作前后的行数/金额（只读查询）。
返回 200 但没多东西 = 幂等成功；返回 400 但多了一行 = **缺陷**。

## 两种打法
- 串行重复：同一个请求连发 N 次（真实用户手抖/网络重试就是这个形态）。
- 并发重复：两个线程同时发（抢跑）。⚠️ 本地是 SQLite（库级写锁），
  并发场景**可能复现不出来**——那样会如实写成"本机复现不出，不代表生产安全"。

## 安全
所有对象由本工具创建（自建订单 + 自建司机账单），批量/全量端点走 DENY 白名单。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fuzzlib import DB_PATH, Api, Report, db_q, money, uniq  # noqa: E402

DRIVER_PHONE = "13800000003"


def counts(order_id: int) -> dict[str, int]:
    """这张单在追加式表里留下了什么（判据只认这个）。"""
    q = {
        "bills": "select count(*) from driver_bills where order_id=?",
        "bills_sum": "select coalesce(sum(amount),0) from driver_bills where order_id=?",
        "movements": "select count(*) from inventory_movements where order_id=?",
        "ledgers": "select count(*) from ledgers where order_id=?",
        "cash": "select count(*) from cash_flows where order_id=?",
        "logs": "select count(*) from operation_logs where order_id=?",
    }
    out: dict[str, int] = {}
    for k, sql in q.items():
        try:
            v = db_q(sql, (order_id,))[0][0]
        except Exception:
            v = -1
        out[k] = int(v if v is not None else 0)
    return out


def status_of(order_id: int) -> tuple[str, bool]:
    r = db_q("select status, paid from orders where id=?", (order_id,))
    return (r[0][0], bool(r[0][1])) if r else ("?", False)


def order_body(tag: str, price: str = "50", qty: int = 2) -> dict:
    """派单员代理下单：**必须**给货主或临时货主（后端 400 会明说），这里用临时货主。"""
    return {
        "lines": [{"product_name_snapshot": uniq(f"{tag}货"), "quantity": qty, "unit_price": price}],
        "delivery_description": uniq(tag),
        "temp_shipper_name": uniq(f"{tag}客户"),
    }


def make_delivered_order(api: Api, rep: Report, tok_disp: str, tok_drv: str, tag: str) -> int | None:
    """建一张单并推到"已送达"（后续重复提交实验都在它身上做）。"""
    o = api.post("/orders", order_body(tag), tok_disp)
    if not o.is_2xx or not isinstance(o.body, dict):
        rep.risk(f"{tag}：下单失败，这一组没做成", o.evidence(200))
        return None
    oid = o.body["id"]
    a = api.post(f"/orders/{oid}/assign", {
        "driver_id": db_q("select id from users where phone=?", (DRIVER_PHONE,))[0][0],
        "freight_fee": "100.00",
        "collect_cash": True,
    }, tok_disp)
    if not a.is_2xx:
        rep.risk(f"{tag}：派单失败，这一组没做成", a.evidence(200))
        return None
    # ⚠️ 接单这一步**必须看返回值**：第一版忽略了它，结果 complete 报「仅已接单订单可完成配送」时
    #    只能看到最后一步失败，看不出是"接单就没成功"（真实发生过，白查了一轮）
    k = api.post(f"/orders/{oid}/driver-ack", None, tok_drv)
    if not k.is_2xx:
        rep.risk(f"{tag}：司机接单失败，这一组没做成", k.evidence(200))
        return None
    c = api.post(f"/orders/{oid}/complete", {"payment": "cash"}, tok_drv)
    if not c.is_2xx:
        rep.risk(f"{tag}：首单送达失败，这一组没做成",
                 f"接单 {k.status} → 送达 {c.evidence(200)}")
        return None
    return oid


def cleanup_derived(rep: Report, order_ids: list[int]) -> None:
    """把工具建的测试单**连同派生行**一起收掉。

    ⚠️ 只软删订单是不够的（第一版就是那样）：司机账单、账本行、现金流水、库存流水
    都是**追加式**的，软删订单不会带走它们——跑了 10 轮就留下 39 条 open 账单、
    约 2580 元挂在司机名下（会出现在"待结运费"里）。这属于"自己建的数据自己清"，
    所以这里硬删：这些行代表的是不存在的业务。
    """
    if not order_ids:
        return
    qs = ",".join("?" * len(order_ids))
    w = sqlite3.connect(str(DB_PATH))
    n = 0
    try:
        with w:
            for table in ("driver_bills", "ledgers", "cash_flows", "inventory_movements",
                          "order_products", "notifications"):
                try:
                    cur = w.execute(f"delete from {table} where order_id in ({qs})", order_ids)
                except sqlite3.OperationalError:
                    continue  # 没有 order_id 列的表（如 notifications）直接跳过
                n += cur.rowcount or 0
            for rid in [r[0] for r in w.execute(
                "select id from shipper_receipts where order_ids is not null"
            )]:
                rows = w.execute("select order_ids from shipper_receipts where id=?", (rid,)).fetchone()
                try:
                    ids = set(json.loads(rows[0]))
                except Exception:
                    continue
                if ids and ids <= set(order_ids):
                    w.execute("delete from shipper_receipts where id=?", (rid,))
                    n += 1
            w.execute(f"delete from orders where id in ({qs})", order_ids)
    finally:
        w.close()
    rep.info(f"已收掉 {len(order_ids)} 张测试单及其派生行（共 {n} 行）",
             "含司机账单/账本/现金流水/库存流水——软删订单不会带走这些追加式记录")


def main() -> int:
    rep = Report("重复提交测试：同一件事做两次，会不会变成两笔", module="_fuzz_replay")
    api = Api()
    tok_disp = api.login("dispatcher")
    tok_drv = api.login("driver")
    tok_shi = api.login("shipper")
    # 提前初始化：某几节没跑成时收尾也要能用（第一版直接 UnboundLocalError）
    oid = oid2 = pid = rid = coid = None

    # ---------------------------------------------------------------- ① 送达重复提交
    rep.section("① 司机送达：重复提交")
    oid = make_delivered_order(api, rep, tok_disp, tok_drv, "重放试验A")
    rep.guard("建出了一张已送达的单（否则这一节等于没测）", bool(oid), "下单/派单/送达链路没走通")
    before = counts(oid)
    second = api.post(f"/orders/{oid}/complete", {"payment": "cash"}, tok_drv)
    third = api.post(f"/orders/{oid}/complete", {"payment": "arrears"}, tok_drv)
    after = counts(oid)
    rep.info("重复送达的返回", f"第二次 {second.status} {second.detail[:60]}｜第三次 {third.status} {third.detail[:60]}")
    for key in ("bills", "movements", "ledgers", "cash"):
        if after[key] > before[key]:
            # 账单/流水多了 = 同一单被记了两次钱
            if key == "movements" and after[key] - before[key] == 1:
                pass
            rep.bug(f"重复送达又多了一笔 {key}（{before[key]} → {after[key]}）",
                    f"单 {oid}：第二次 {second.status}／第三次 {third.status}")
    if after == before:
        rep.ok(f"重复送达没有产生任何新行（{json.dumps(after, ensure_ascii=False)}）")

    # ---------------------------------------------------------------- ② 并发送达
    rep.section("② 司机送达：两个线程同时提交")
    oid2 = make_delivered_order(api, rep, tok_disp, tok_drv, "重放试验B")
    if oid2:
        # 先造一张"可送达"的单：新建 → 派单 → 接单，然后并发 complete
        o = api.post("/orders", order_body("并发送达", price="30", qty=1), tok_disp)
        coid = o.body["id"] if o.is_2xx else None
        if coid:
            api.post(f"/orders/{coid}/assign", {
                "driver_id": db_q("select id from users where phone=?", (DRIVER_PHONE,))[0][0],
                "freight_fee": "60.00", "collect_cash": True,
            }, tok_disp)
            api.post(f"/orders/{coid}/driver-ack", None, tok_drv)
            c_before = counts(coid)
            results: list[int] = []

            def fire() -> None:
                r = api.post(f"/orders/{coid}/complete", {"payment": "cash"}, tok_drv)
                results.append(r.status)

            ts = [threading.Thread(target=fire) for _ in range(2)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            c_after = counts(coid)
            if c_after["bills"] > c_before["bills"] + 1:
                rep.bug("并发送达产生了多张司机账单（抢跑成功）",
                        f"单 {coid}：状态码 {results}，账单 {c_before['bills']} → {c_after['bills']}")
            else:
                rep.ok(f"并发送达只产生一张账单（状态码 {results}，账单 {c_before['bills']} → {c_after['bills']}）")
            busy = [s for s in results if s == 0]
            if busy:
                rep.info("并发时有请求没拿到 HTTP 响应（本地 SQLite 写锁的典型表现）",
                         f"状态码 {results} —— 环境限制，不代表生产安全")

    # ---------------------------------------------------------------- ③ 收款重复核销
    rep.section("③ 逐单核销：同一张单核销两次")
    # ⚠️ 这一节必须用**有账号的货主**下单：收款单的 `customer_id` 指向 customers 档案，
    #    只有 registered 客户（按 user_id 关联）才拿得到 id；临时货主是按名字归属的。
    o = api.post("/orders", {
        "lines": [{"product_name_snapshot": uniq("核销货"), "quantity": 1, "unit_price": "80"}],
        "delivery_description": uniq("核销试验"),
    }, tok_shi)
    rid = o.body["id"] if o.is_2xx else None
    if not rid:
        rep.risk("货主下单失败，核销重复这一节没测到", o.evidence(200))
    else:
        drv_id = db_q("select id from users where phone=?", (DRIVER_PHONE,))[0][0]
        api.post(f"/orders/{rid}/assign", {"driver_id": drv_id, "freight_fee": "20.00",
                                           "collect_cash": False}, tok_disp)
        api.post(f"/orders/{rid}/driver-ack", None, tok_drv)
        api.post(f"/orders/{rid}/complete", {"payment": "arrears"}, tok_drv)   # 挂账
        rows = db_q("select id from customers where user_id = "
                    "(select shipper_id from orders where id=?)", (rid,))
        cust = rows[0][0] if rows else None
        if cust is None:
            rep.risk("这张单没有客户档案，收款核销没法试（accounting_service 按 customer 归属）",
                     f"单 {rid}：customers 里找不到对应的 registered 档案")
        else:
            amount = money(db_q(
                "select coalesce(sum(line_total),0) from order_products where order_id=?", (rid,))[0][0])
            body = {"customer_id": cust, "amount": str(amount), "method": "cash",
                    "received_at": "2026-09-18", "order_ids": [rid], "settle_mode": "itemized"}
            r1 = api.post("/ledger/receipts", body, tok_disp)
            paid_after_first = status_of(rid)[1]
            r2 = api.post("/ledger/receipts", body, tok_disp)
            receipts = db_q("select count(*) from shipper_receipts where customer_id=? and amount=?",
                            (cust, str(amount)))[0][0]
            cash = counts(rid)["cash"]
            if r2.is_2xx and receipts > 1:
                rep.bug("同一张单可以被逐单核销两次（收款记录重复）",
                        f"第一次 {r1.status}／第二次 {r2.status}，该客户+金额的收款单 {receipts} 条，"
                        f"该单现金流水 {cash} 条")
            else:
                rep.ok(f"重复核销被挡住（第二次 {r2.status} {r2.detail[:50]}；收款单 {receipts} 条）")
            if not paid_after_first:
                rep.bug("核销成功但订单没有标记 paid（报表的已收会漏掉这笔）",
                        f"单 {rid} 核销返回 {r1.status}，paid 仍为 False")

    # ---------------------------------------------------------------- ④ 派单重复
    rep.section("④ 派单：重复派同一张单")
    o = api.post("/orders", order_body("重复派单", price="10", qty=1), tok_disp)
    pid = o.body["id"] if o.is_2xx else None
    if pid:
        drv_id = db_q("select id from users where phone=?", (DRIVER_PHONE,))[0][0]
        r1 = api.post(f"/orders/{pid}/assign", {"driver_id": drv_id, "freight_fee": "10.00"}, tok_disp)
        b1 = counts(pid)
        r2 = api.post(f"/orders/{pid}/assign", {"driver_id": drv_id, "freight_fee": "99.00"}, tok_disp)
        b2 = counts(pid)
        st, _ = status_of(pid)
        if r2.is_2xx and st == "DISPATCHED":
            # 第二次也成功 = 覆盖式派单（把运费从 10 改成 99）→ 要看是不是有意为之
            rep.risk("同一张单可以重复派单（第二次会覆盖运费/司机）",
                     f"第一次 {r1.status}／第二次 {r2.status}，运费可能被改成 99.00")
        else:
            rep.ok(f"重复派单被挡（第二次 {r2.status} {r2.detail[:50]}）")
        if b2["logs"] == b1["logs"] and r2.is_2xx:
            rep.risk("重复派单成功但没写操作日志", f"单 {pid}：日志 {b1['logs']} → {b2['logs']}")

    # ---------------------------------------------------------------- ⑤ 建单重复（有意的）
    rep.section("⑤ 建单：同样的请求发两次（设计上应该建两张）")
    body = order_body("重复建单", price="5", qty=1)
    a1 = api.post("/orders", body, tok_disp)
    a2 = api.post("/orders", body, tok_disp)
    if a1.is_2xx and a2.is_2xx and a1.body.get("id") != a2.body.get("id"):
        rep.info("同样的下单请求建出了两张单（无幂等键，靠用户自己确认）",
                 f"{a1.body.get('order_no')} / {a2.body.get('order_no')}")
    for r in (a1, a2):
        if r.is_2xx:
            api.delete(f"/orders/{r.body['id']}", tok_disp)
    created = [x for x in (oid, oid2, pid, rid, coid) if x]
    for oid3 in created:
        api.delete(f"/orders/{oid3}", tok_disp)      # 先按 App 语义软删（留痕）
    cleanup_derived(rep, created)                     # 再硬删派生行（否则账单/流水留在库里）
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
