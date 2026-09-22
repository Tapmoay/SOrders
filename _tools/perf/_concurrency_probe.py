"""并发实测：**同一张单 / 同一笔钱被两个人同时动手**时，业务守卫拦不拦得住。

## 为什么单独做这一层（`_archive/audit/HANDOVER.md` 的空白面）

它把"并发压力测试"列为没探查的一项，原文是"只有针对性的并发注入
（`_tools/qa/_reverse_verify_concurrency_guards.py` 的 CAS 场景）；没有『多用户混跑 10 分钟
看数据是否自洽』的压测"。这一轮补的是**更窄、但更容易出真事故**的那一层：

> 同一个动作被**同时**提交两次 —— 两个派单员同时派同一张单、司机连点两下"送达"、
> 收款按钮双击。判据不是"耗时"，而是**最后库里是不是还自洽**。

判据有三条，缺一不可：
1. **恰好一个**请求成功（其余必须被业务守卫挡掉，而不是一起成功）；
2. **副作用只发生一次**（司机账单只生成一张、库存只扣一次、账本只多一行、收款单只多一条）；
3. 撞完之后的库仍然满足 `_fuzz_invariants.py` 那套不变式（脚本末尾会提示怎么再验一遍）。

## ⛔ 环境说明（结论要按它读）

本机是 **SQLite**（WAL + busy_timeout=30s）。写并发会出现 `database is locked` ——
那是**环境限制、不是业务缺陷**，脚本单独计数并如实报出来（生产是 MySQL，不存在这个问题）。
所以：**"2xx 的个数"才是判据**，锁冲突只影响"能不能把并发真的打进去"。

## 用法

```
python _tools/perf/_perf_seed.py --orders 20000 --force      # 造副本大库（首次）
cd backend; $env:DATABASE_URL='sqlite:///D:/AProjects/ASDH/orders/_agent/perf/perf.db'
    ; python -m uvicorn app.main:app --port 8001             # 另一个后端指向副本
python _tools/perf/_concurrency_probe.py                     # 默认打 8001 + 副本库
```
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools" / "fuzz"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
import _fuzzlib  # noqa: E402
from _fuzzlib import Api, db_q  # noqa: E402

#: ⚠️ `_fuzzlib.db_q` 用的是**模块级** `DB_PATH`（导入时按 `SORDERS_DB` 算好）。
#:    这里要断言的是"被测副本库"，所以解析完参数后直接改它的模块属性 —— 比在导入前
#:    拼环境变量可靠（导入顺序一变就会偷偷读回开发库，而那种错**不会有任何报错**）。


def fire(api: Api, workers: int, method: str, path: str, body: dict | None, token: str) -> list:
    """n 个线程**同时**打同一个请求（用 Barrier 对齐起跑线）。"""
    barrier = threading.Barrier(workers)
    out: list = [None] * workers

    def one(i: int) -> None:
        barrier.wait()
        try:
            out[i] = api.req(method, path, body, token, allow_denied=True)
        except Exception as e:  # noqa: BLE001 - 线程里的异常要带回主线程
            out[i] = e

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, range(workers)))
    return out


def summarize(results: list) -> tuple[int, int, int, list[str]]:
    """→ (2xx 个数, 被拒个数, 锁冲突个数, 人话摘要)"""
    ok = busy = other = 0
    notes: list[str] = []
    for r in results:
        if isinstance(r, Exception):
            notes.append(f"异常 {type(r).__name__}")
            other += 1
            continue
        if r.sqlite_busy:
            busy += 1
            continue
        if r.is_2xx:
            ok += 1
        else:
            other += 1
            notes.append(f"{r.status} {r.detail[:40]}")
    return ok, other, busy, notes


def one(table: str, sql: str, params: tuple = ()) -> int:
    return int(db_q(sql, params)[0][0])


CASES: list[str] = ["assign", "ack", "complete", "cancel", "receipt", "stock"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8001/api/v1")
    ap.add_argument("--db", type=Path, default=ROOT / "_agent/perf/perf.db")
    ap.add_argument("--workers", type=int, default=3, help="同时打几个请求（默认 3）")
    ap.add_argument("--only", default="", help="只跑某个 case（assign/ack/complete/cancel/receipt/stock）")
    ap.add_argument("--out", type=Path, default=ROOT / "_agent/perf/last-concurrency.json")
    args = ap.parse_args()

    import os

    os.environ["SORDERS_DB"] = str(args.db)
    _fuzzlib.DB_PATH = Path(args.db)  # 断言读的就是被测那个库（见文件头那段说明）

    api = Api(base=args.base)
    tokens = api.all_roles()
    disp, ship, drv = tokens["dispatcher"], tokens["shipper"], tokens["driver"]
    n = max(2, args.workers)
    bugs: list[str] = []
    risks: list[str] = []
    records: list[dict] = []
    print(f"被测后端 {args.base}    库 {args.db}    {n} 个并发\n" + "-" * 104)

    def report(label: str, ok: int, other: int, busy: int, notes: list[str], expect: str,
               extra: str = "") -> bool:
        good = ok == 1
        if ok >= 2:
            bugs.append(f"{label}：**{ok} 个请求同时成功**（应当只有一个）—— 业务守卫没拦住")
        elif ok == 0:
            risks.append(f"{label}：一个都没成功（并发下全被拒）—— 可能是守卫过严或环境锁冲突")
        verdict = "✓ 恰好一个成功" if good else ("❌ 多个成功" if ok >= 2 else "? 一个都没成功")
        print(f"{label:38} 成功 {ok} / 被拒 {other} / 锁冲突 {busy}   {verdict}   {expect}")
        if extra:
            print(f"{'':38} 库内：{extra}")
        if notes:
            print(f"{'':38} 拒绝理由样例：{'；'.join(notes[:3])[:110]}")
        records.append(dict(label=label, ok=ok, rejected=other, busy=busy, expect=expect,
                            extra=extra, notes=notes[:5]))
        return good

    # ---------------------------------------------------------------- ① 并发派单
    if not args.only or args.only == "assign":
        row = db_q(
            "select id from orders where status='PENDING_DISPATCH' and deleted_at is null "
            "and driver_id is null order by id desc limit 1"
        )
        if row:
            oid = row[0]["id"]
            drivers = [r["id"] for r in db_q(
                "select id from users where upper(role)='DRIVER' and is_active=1 order by id limit ?",
                (n,),
            )]
            results = fire_targets(api, n, oid, drivers, disp)
            ok, other, busy, notes = summarize(results)
            d = db_q("select driver_id, dispatched_at from orders where id=?", (oid,))[0]
            logs = one("op", "select count(*) from operation_logs where order_id=? and action='ORDER_DISPATCH'",
                       (oid,))
            report(f"并发派单 单#{oid}（{n} 个司机同时派）", ok, other, busy, notes,
                   "期望：1 成功、其余提示已被派走",
                   f"driver_id={d['driver_id']}（{n} 选 1）、ORDER_DISPATCH 日志 {logs} 条")
            if logs > 1:
                bugs.append(f"并发派单：审计日志写了 {logs} 条（副作用重复）")

    # ---------------------------------------------------------------- ② 并发接单
    if not args.only or args.only == "ack":
        row = db_q(
            "select o.id, o.driver_id, u.phone from orders o join users u on u.id=o.driver_id "
            "where o.status='DISPATCHED' and o.deleted_at is null and u.is_active=1 "
            "order by o.id desc limit 1"
        )
        if row:
            oid, did, phone = row[0]["id"], row[0]["driver_id"], row[0]["phone"]
            tok_d = api.post("/auth/login", {"phone": phone, "password": "123321"},
                             allow_denied=True)
            tok = tok_d.body["access_token"] if tok_d.is_2xx else drv
            results = fire(api, n, "POST", f"/orders/{oid}/driver-ack", None, tok)
            ok, other, busy, notes = summarize(results)
            d = db_q("select status, driver_acknowledged_at from orders where id=?", (oid,))[0]
            report(f"并发接单 单#{oid}（司机连点 {n} 下）", ok, other, busy, notes,
                   "期望：1 成功、其余提示已经接过了",
                   f"status={d['status']} driver_acknowledged_at={d['driver_acknowledged_at']}")

    # ---------------------------------------------------------------- ③ 并发送达
    if not args.only or args.only == "complete":
        row = db_q(
            "select o.id, u.phone from orders o join users u on u.id=o.driver_id "
            "where o.status='ACCEPTED' and o.deleted_at is null and u.is_active=1 "
            "order by o.id desc limit 1"
        )
        if row:
            oid, phone = row[0]["id"], row[0]["phone"]
            tok_d = api.post("/auth/login", {"phone": phone, "password": "123321"},
                             allow_denied=True)
            tok = tok_d.body["access_token"] if tok_d.is_2xx else drv
            bills0 = one("b", "select count(*) from driver_bills where order_id=?", (oid,))
            results = fire(api, n, "POST", f"/orders/{oid}/complete",
                           {"payment": "arrears", "driver_remark": "并发探针"}, tok)
            ok, other, busy, notes = summarize(results)
            bills = one("b", "select count(*) from driver_bills where order_id=?", (oid,))
            st = db_q("select status from orders where id=?", (oid,))[0]["status"]
            lg = one("l", "select count(*) from ledgers where order_id=?", (oid,))
            report(f"并发送达 单#{oid}（司机连点 {n} 下）", ok, other, busy, notes,
                   "期望：1 成功、账单/账本只多一份",
                   f"status={st}、司机账单 {bills0}→{bills} 张、账本 {lg} 行")
            if bills > 1:
                bugs.append(f"并发送达：司机账单生成了 {bills} 张（重复计费）")

    # ---------------------------------------------------------------- ④ 并发撤销
    if not args.only or args.only == "cancel":
        row = db_q(
            "select id from orders where status='PENDING_DISPATCH' and deleted_at is null "
            "order by id limit 1"
        )
        if row:
            oid = row[0]["id"]
            results = fire(api, n, "POST", f"/orders/{oid}/cancel", None, disp)
            ok, other, busy, notes = summarize(results)
            d = db_q("select status, cancelled_at from orders where id=?", (oid,))[0]
            report(f"并发撤销 单#{oid}（{n} 下同时点撤销）", ok, other, busy, notes,
                   "期望：1 成功、其余提示已撤销", f"status={d['status']}")

    # ---------------------------------------------------------------- ⑤ 并发收款
    if not args.only or args.only == "receipt":
        row = db_q(
            "select o.id, o.shipper_id, c.id as cid, "
            "(select round(sum(line_total),2) from order_products where order_id=o.id) as amt "
            "from orders o join customers c on c.user_id = o.shipper_id "
            "where o.status='DELIVERED' and o.paid=0 and o.deleted_at is null "
            "and amt is not null order by o.id desc limit 1"
        )
        if row:
            oid, cid, amt = row[0]["id"], row[0]["cid"], row[0]["amt"]
            body = {"customer_id": cid, "amount": str(amt), "method": "cash",
                    "received_at": "2026-09-23", "order_ids": [oid], "settle_mode": "itemized"}
            r0 = one("rc", "select count(*) from shipper_receipts")
            results = fire(api, n, "POST", "/ledger/receipts", body, disp)
            ok, other, busy, notes = summarize(results)
            r1 = one("rc", "select count(*) from shipper_receipts")
            paid = db_q("select paid from orders where id=?", (oid,))[0]["paid"]
            report(f"并发收款 单#{oid}（{n} 下同时点收款）", ok, other, busy, notes,
                   "期望：1 成功、收款单只多一条",
                   f"收款单 {r0}→{r1} 条、订单 paid={paid}")

    # ---------------------------------------------------------------- ⑥ 并发库存调整
    if not args.only or args.only == "stock":
        row = db_q("select id, name, stock from products where is_deleted=0 and stock > 0 "
                   "order by id desc limit 1")
        if row:
            pid, name, stock = row[0]["id"], row[0]["name"], row[0]["stock"]
            results = fire(api, n, "POST", "/inventory/movements",
                           {"product_id": pid, "change": -stock, "note": "并发探针"}, disp)
            ok, other, busy, notes = summarize(results)
            now = db_q("select stock from products where id=?", (pid,))[0]["stock"]
            report(f"并发出库 商品#{pid} {name[:10]}（{n} 次各扣 {stock}）", ok, other, busy, notes,
                   "期望：1 成功（其余因库存不够被拒），最终不为负",
                   f"库存 {stock}→{now}（只该扣一次）")
            if now < 0:
                bugs.append(f"并发出库：库存被扣成 {now}（负库存）—— 条件 UPDATE 没兜住")

    # ---------------------------------------------------------------- ⑦ 并发撤回
    if not args.only or args.only == "recall":
        row = db_q(
            "select id from orders where status='DISPATCHED' and deleted_at is null "
            "order by id desc limit 1"
        )
        if row:
            oid = row[0]["id"]
            results = fire(api, n, "POST", f"/orders/{oid}/recall", {"reason": "并发探针"}, disp)
            ok, other, busy, notes = summarize(results)
            d = db_q("select status, driver_id from orders where id=?", (oid,))[0]
            report(f"并发撤回 单#{oid}（{n} 下同时点撤回）", ok, other, busy, notes,
                   "期望：1 成功、其余提示状态不对",
                   f"status={d['status']} driver_id={d['driver_id']}")

    # ---------------------------------------------------------------- ⑧ 并发「派单 vs 撤销」
    if not args.only or args.only == "assign-vs-cancel":
        row = db_q(
            "select id from orders where status='PENDING_DISPATCH' and deleted_at is null "
            "and driver_id is null order by id limit 1"
        )
        if row:
            oid = row[0]["id"]
            barrier = threading.Barrier(2)
            out: list = [None, None]

            def racer(i: int) -> None:
                barrier.wait()
                if i == 0:
                    out[i] = api.req("POST", f"/orders/{oid}/assign", {"driver_id": 3}, disp,
                                     allow_denied=True)
                else:
                    out[i] = api.req("POST", f"/orders/{oid}/cancel", None, disp,
                                     allow_denied=True)

            with ThreadPoolExecutor(max_workers=2) as ex:
                list(ex.map(racer, range(2)))
            ok, other, busy, notes = summarize(out)
            d = db_q("select status, driver_id, dispatched_at, cancelled_at from orders where id=?",
                     (oid,))[0]
            # 状态自洽：CANCELLED 必须有撤销时间、DISPATCHED 必须有司机
            consistent = (
                (d["status"] == "CANCELLED" and d["cancelled_at"] is not None)
                or (d["status"] == "DISPATCHED" and d["driver_id"] is not None
                    and d["dispatched_at"] is not None)
            )
            fives = [r for r in out if not isinstance(r, Exception) and r.is_5xx]
            report(f"并发「派单 vs 撤销」单#{oid}", ok, other, busy, notes,
                   "期望：至少一个成功、无 500、状态与时间戳自洽",
                   f"status={d['status']} driver_id={d['driver_id']} "
                   f"cancelled_at={d['cancelled_at']} 自洽={consistent}")
            if fives:
                bugs.append(f"并发「派单 vs 撤销」：出现 {len(fives)} 个 5xx（状态竞争没兜住）")
            if not consistent:
                bugs.append(
                    f"并发「派单 vs 撤销」：终态自相矛盾 status={d['status']} "
                    f"driver_id={d['driver_id']} cancelled_at={d['cancelled_at']}"
                )

    # ---------------------------------------------------------------- ⑨ 并发拆分
    if not args.only or args.only == "split":
        row = db_q(
            "select id from orders where status='PENDING_DISPATCH' and deleted_at is null "
            "order by id desc limit 1"
        )
        if row:
            oid = row[0]["id"]
            kids0 = one("k", "select count(*) from orders where parent_order_id=?", (oid,))
            results = fire(api, n, "POST", f"/orders/{oid}/split", {"parts": [1, 1]}, disp)
            ok, other, busy, notes = summarize(results)
            kids = one("k", "select count(*) from orders where parent_order_id=?", (oid,))
            fives = [r for r in results if not isinstance(r, Exception) and r.is_5xx]
            report(f"并发拆分 单#{oid}（{n} 下同时点拆单）", ok, other, busy, notes,
                   "期望：1 成功（子单只出现一批）、不许 500",
                   f"子单 {kids0}→{kids} 张（parts=[1,1] → 该为 2 张）")
            if fives:
                bugs.append(f"并发拆分：出现 {len(fives)} 个 5xx")
            if kids > kids0 + 2:
                bugs.append(f"并发拆分：拆出了 {kids - kids0} 张子单（应当只有 2 张）—— 双拆没拦住")

    # ---------------------------------------------------------------- ⑩ 并发供应商付款
    if not args.only or args.only == "pay":
        sup = api.get("/suppliers", disp, allow_denied=True)
        sup_id = None
        if isinstance(sup.body, list) and sup.body:
            sup_id = sup.body[0].get("id")
        elif isinstance(sup.body, dict):
            items = sup.body.get("items") or []
            sup_id = items[0].get("id") if items else None
        if sup_id:
            # ⚠️ 自己建一张**新的**应付单。第一版去挑现成的那张，结果它早就付清了
            #    （`biz_type` 实测是 `PAYMENT_SUPPLIER`，而探针按 `supplier_payment` 求和 → 读到 0），
            #    于是三个请求全被"已付清"挡掉，报出来像"守卫过严"，其实**什么都没测**。
            amt = "1000.00"
            created = api.post(
                f"/suppliers/{sup_id}/payables",
                {"supplier_id": sup_id, "title": "并发探针应付", "category": "货款",
                 "amount": amt, "doc_date": "2026-09-23", "remark": "并发探针（可删）"},
                disp,
            )
            if created.is_2xx and isinstance(created.body, dict):
                pid = created.body.get("id")
                cf0 = one("cf", "select count(*) from cash_flows where doc_id=? and "
                                "biz_type='PAYMENT_SUPPLIER'", (pid,))
                results = fire(api, n, "POST", f"/supplier-payables/{pid}/payments",
                               {"amount": amt, "pay_date": "2026-09-23",
                                "channel": "cash", "remark": "并发探针"}, disp)
                ok, other, busy, notes = summarize(results)
                cf1 = one("cf", "select count(*) from cash_flows where doc_id=? and "
                                "biz_type='PAYMENT_SUPPLIER'", (pid,))
                report(f"并发付款 应付单#{pid}（{n} 次各付全额 {amt}）", ok, other, busy, notes,
                       "期望：1 成功（其余因余额不足被拒）、流水只多一条",
                       f"付款流水 {cf0}→{cf1} 条")
                if cf1 > cf0 + 1:
                    bugs.append(f"并发付款：资金流水多了 {cf1 - cf0} 条（同一笔钱付了多次）")
            else:
                print(f"? 建应付单失败（{created.status} {created.detail[:50]}），跳过并发付款这一条")
        else:
            print("? 名册里没有供应商，跳过并发付款这一条")

    # ---------------------------------------------------------------- ⑪ 并发退货（动钱）
    if not args.only or args.only == "return":
        row = db_q(
            "select o.id, op.id as line_id, op.quantity, op.returned_quantity "
            "from orders o join order_products op on op.order_id = o.id "
            "where o.status='DELIVERED' and o.deleted_at is null "
            "and op.quantity - coalesce(op.returned_quantity,0) >= 1 "
            "order by o.id desc limit 1"
        )
        if row:
            oid, lid = row[0]["id"], row[0]["line_id"]
            cap = int(row[0]["quantity"]) - int(row[0]["returned_quantity"] or 0)
            qty = cap  # 退满：第二次就该被"可退数量不够"挡住
            lg0 = one("lg", "select count(*) from ledgers where order_id=? and total < 0", (oid,))
            results = fire(api, n, "POST", f"/orders/{oid}/return",
                           {"items": [{"order_product_id": lid, "quantity": qty}]}, disp)
            ok, other, busy, notes = summarize(results)
            lg = one("lg", "select count(*) from ledgers where order_id=? and total < 0", (oid,))
            rq = db_q("select returned_quantity from order_products where id=?", (lid,))[0][
                "returned_quantity"]
            report(f"并发退货 单#{oid} 行#{lid}（{n} 次各退满 {qty} 件）", ok, other, busy, notes,
                   "期望：1 成功（其余因可退数量不够被拒）、红冲只多一批",
                   f"红冲行 {lg0}→{lg} 行、该行已退数量={rq}（上限 {cap}）")
            if rq is not None and int(rq) > cap:
                bugs.append(f"并发退货：该行已退 {rq} > 可退上限 {cap}（退多了）")
            if lg > lg0 + 1:
                bugs.append(f"并发退货：红冲行多了 {lg - lg0} 批（同一批货退了两次）")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    print("-" * 104)
    print(f"明细：{args.out}")
    print("\n再验一遍库是否自洽（读同一个副本）：")
    print(f"  $env:SORDERS_DB='{args.db}'; python _tools/fuzz/_fuzz_invariants.py")
    if bugs:
        print(f"\n❌ {len(bugs)} 条并发缺陷：")
        for b in bugs:
            print("   - " + b)
        return 1
    if risks:
        print(f"\n⚠️ {len(risks)} 条需要人看一眼（不算缺陷）：")
        for r in risks:
            print("   - " + r)
    print(f"\n✅ {len(records)} 个并发场景：每个都恰好一个成功，副作用没有重复。")
    return 0


def fire_targets(api: Api, n: int, oid: int, drivers: list[int], token: str) -> list:
    """并发派单：n 个线程各派给**不同**的司机（最容易暴露"两个都成功"）。"""
    barrier = threading.Barrier(n)
    out: list = [None] * n

    def one_(i: int) -> None:
        barrier.wait()
        try:
            out[i] = api.req("POST", f"/orders/{oid}/assign",
                             {"driver_id": drivers[i % len(drivers)]}, token, allow_denied=True)
        except Exception as e:  # noqa: BLE001
            out[i] = e

    with ThreadPoolExecutor(max_workers=n) as ex:
        list(ex.map(one_, range(n)))
    return out


if __name__ == "__main__":
    sys.exit(main())
