# -*- coding: utf-8 -*-
"""SOrders 并发压测引擎 v1.1 — 修正货主读自己订单"""
import sys, json, time, asyncio, random, statistics, os, argparse
sys.stdout.reconfigure(encoding='utf-8')
import aiohttp

BASE = "http://127.0.0.1:8000"
SHIPPERS = [f"1391000{i:04d}" for i in range(1, 61)]
DRIVERS = [f"1382000{i:04d}" for i in range(1, 51)]

ap = argparse.ArgumentParser()
ap.add_argument("users", type=int)
ap.add_argument("duration", type=int, default=60)
ap.add_argument("prefix", default="run1")
ap.add_argument("--burn", type=int, default=0, help="预热秒数")
args = ap.parse_args()

class Stats:
    def __init__(self):
        self.ok = {}
        self.lat = []
        self.start = None
    def record(self, name, status_code, dur, ok_expected=(200, 201)):
        ok = status_code in ok_expected
        k = name if ok else f"{name}::{status_code}"
        self.ok[k] = self.ok.get(k, 0) + 1
        self.lat.append((dur, ok))

async def raw(sess, method, path, h=None, body=None):
    t0 = time.perf_counter()
    try:
        async with sess.request(method, BASE + path, headers=h or {}, json=body, timeout=aiohttp.ClientTimeout(total=10)) as r:
            txt = await r.text()
            return r.status, time.perf_counter() - t0, txt
    except asyncio.TimeoutError:
        return 999, time.perf_counter() - t0, ""
    except Exception:
        return -1, time.perf_counter() - t0, ""

async def login(sess, phone):
    s, d, txt = await raw(sess, "POST", "/api/v1/auth/login", body={"phone": phone, "password": "pass12345"})
    if s != 200: return None
    try: return json.loads(txt).get("access_token")
    except Exception: return None

async def shipper_worker(sess, stats, phone, stop_evt):
    tok = await login(sess, phone)
    if not tok:
        stats.ok["shipper/login_fail"] = stats.ok.get("shipper/login_fail", 0) + 1
        return
    h = {"Authorization": f"Bearer {tok}"}
    my_orders = []
    while not stop_evt.is_set():
        action = random.choice(["list_orders", "create_order", "get_detail", "list_products"])
        if action == "list_orders":
            s, d, _ = await raw(sess, "GET", "/api/v1/orders", h=h)
            stats.record("shipper/list_orders", s, d)
        elif action == "create_order":
            body = {"lines": [{"product_id": random.randint(1, 8), "product_name_snapshot": "商品S", "quantity": random.randint(1, 10), "unit_price": f"{random.randint(5, 50)}.00"}], "address_detail": "并发压测地址", "contact_boss_phone": phone}
            s, d, txt = await raw(sess, "POST", "/api/v1/orders", h=h, body=body)
            stats.record("shipper/create_order", s, d, ok_expected=(201,))
            if s == 201:
                try: my_orders.append(json.loads(txt).get("id"))
                except Exception: pass
        elif action == "get_detail" and my_orders:
            oid = random.choice(my_orders[-20:])
            s, d, _ = await raw(sess, "GET", f"/api/v1/orders/{oid}", h=h)
            stats.record("shipper/get_detail", s, d)
        else:
            s, d, _ = await raw(sess, "GET", "/api/v1/products", h=h)
            stats.record("shipper/list_products", s, d)
        await asyncio.sleep(random.uniform(0.5, 2.5))

async def driver_worker(sess, stats, phone, stop_evt):
    tok = await login(sess, phone)
    if not tok:
        stats.ok["driver/login_fail"] = stats.ok.get("driver/login_fail", 0) + 1
        return
    h = {"Authorization": f"Bearer {tok}"}
    while not stop_evt.is_set():
        action = random.choice(["list_tasks", "ack_or_complete"])
        if action == "list_tasks":
            s, d, _ = await raw(sess, "GET", "/api/v1/orders", h=h)
            stats.record("driver/list_tasks", s, d)
        else:
            s, d, txt = await raw(sess, "GET", "/api/v1/orders", h=h)
            if s == 200:
                try: orders = json.loads(txt)
                except: orders = []
                cands = [o for o in (orders if isinstance(orders, list) else []) if o.get("status") in ("DISPATCHED", "ACCEPTED")]
                if cands and random.random() < 0.4:
                    oid = cands[0]["id"]
                    if cands[0]["status"] == "DISPATCHED":
                        s2, d2, _ = await raw(sess, "POST", f"/api/v1/orders/{oid}/driver-ack", h=h, body={})
                        stats.record("driver/driver_ack", s2, d2)
                    elif random.random() < 0.6:
                        s2, d2, _ = await raw(sess, "POST", f"/api/v1/orders/{oid}/complete", h=h, body={"payment": "cash"})
                        stats.record("driver/complete", s2, d2)
        await asyncio.sleep(random.uniform(1.0, 3.0))

async def dispatcher_worker(sess, stats, stop_evt):
    tok = await login(sess, "13800000001")
    h = {"Authorization": f"Bearer {tok}"}
    while not stop_evt.is_set():
        action = random.choice(["pool", "orders", "assign", "reports", "ledger", "users"])
        if action == "pool":
            s, d, _ = await raw(sess, "GET", "/api/v1/orders?status=PENDING_DISPATCH", h=h)
            stats.record("dispatcher/pool", s, d)
        elif action == "orders":
            s, d, _ = await raw(sess, "GET", "/api/v1/orders", h=h)
            stats.record("dispatcher/orders", s, d)
        elif action == "assign":
            s, d, txt = await raw(sess, "GET", "/api/v1/orders?status=PENDING_DISPATCH", h=h)
            if s == 200:
                try: pend = json.loads(txt)
                except: pend = []
                if isinstance(pend, list) and pend:
                    s2, d2, _ = await raw(sess, "POST", f"/api/v1/orders/{pend[0]['id']}/assign", h=h, body={"driver_id": random.randint(3, 50), "freight_fee": "5.00"})
                    stats.record("dispatcher/assign", s2, d2)
        elif action == "reports":
            s, d, _ = await raw(sess, "GET", "/api/v1/reports/turnover?mode=day&date=2026-09-04", h=h)
            stats.record("dispatcher/reports", s, d)
        elif action == "ledger":
            s, d, _ = await raw(sess, "GET", "/api/v1/ledger/entries?shipper_id=2&from=2026-09-01&to=2026-09-30", h=h)
            stats.record("dispatcher/ledger", s, d)
        else:
            s, d, _ = await raw(sess, "GET", "/api/v1/users?limit=100", h=h)
            stats.record("dispatcher/users", s, d)
        await asyncio.sleep(random.uniform(0.8, 2.0))

async def main():
    stats = Stats()
    stop_evt = asyncio.Event()
    conn = aiohttp.TCPConnector(limit=0, limit_per_host=0, ssl=False, force_close=False)
    async with aiohttp.ClientSession(connector=conn) as sess:
        n_shipper = int(N_USERS * 0.40)
        n_driver = N_USERS - n_shipper - 1
        print(f"[{args.prefix}] 配置: 派单员1 + 货主{n_shipper} + 司机{n_driver} = {N_USERS}", flush=True)
        tasks = [asyncio.create_task(shipper_worker(sess, stats, SHIPPERS[i % len(SHIPPERS)], stop_evt)) for i in range(n_shipper)]
        tasks += [asyncio.create_task(driver_worker(sess, stats, DRIVERS[i % len(DRIVERS)], stop_evt)) for i in range(n_driver)]
        tasks.append(asyncio.create_task(dispatcher_worker(sess, stats, stop_evt)))
        t0 = time.perf_counter()
        await asyncio.sleep(DURATION)
        stop_evt.set()
        await asyncio.sleep(2)
        for t in tasks: t.cancel()
        elapsed = time.perf_counter() - t0
        total = sum(stats.ok.values())
        ok_count = sum(v for k, v in stats.ok.items() if "::" not in k)
        err_count = total - ok_count
        print(f"\n===== [{args.prefix}] {N_USERS}并发 {DURATION}s =====", flush=True)
        print(f"总请求: {total} | 成功: {ok_count} | 失败: {err_count} | 错误率: {err_count/total*100:.2f}%" if total else "无请求", flush=True)
        print(f"RPS: {total/elapsed if elapsed else 0:.1f}", flush=True)
        print("\n端点明细:", flush=True)
        for k in sorted(stats.ok.keys()):
            print(f"  {k}: {stats.ok[k]}", flush=True)
        if stats.lat:
            lat_ok = sorted(d for d, ok in stats.lat if ok)
            if lat_ok:
                n = len(lat_ok)
                print(f"延迟(成功): p50={lat_ok[int(n*0.5)]*1000:.0f}ms p95={lat_ok[int(n*0.95)]*1000:.0f}ms p99={lat_ok[int(n*0.99)]*1000:.0f}ms", flush=True)

N_USERS = args.users; DURATION = args.duration
asyncio.run(main())