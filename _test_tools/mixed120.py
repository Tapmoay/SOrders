# -*- coding: utf-8 -*-
"""120 用户(3派单员+64货主+53司机) 混合连续正常操作负载
运行在服务器本机: BASE=http://127.0.0.1:8000
用法: python3 mixed120.py [duration_seconds]  缺省 180
"""
import json, urllib.request, urllib.error, threading, time, random, sys
from collections import deque
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE = "http://127.0.0.1:8000"
PASS = "pass12345"
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 180
PACE = 1.0

DISPATCHERS = ["13800000001", "13800000004", "13800000005"]
SHIPPERS = ["1391000%04d" % i for i in range(1, 65)]        # 64 名
DRIVERS = ["1382000%04d" % i for i in range(1, 54)]         # 53 名
NEW_USERS = [
    ("shipper", "13910000061", "压测货主%03d" % 61),
    ("shipper", "13910000062", "压测货主%03d" % 62),
    ("shipper", "13910000063", "压测货主%03d" % 63),
    ("driver",  "13820000051", "压测司机%03d" % 51),
    ("driver",  "13820000052", "压测司机%03d" % 52),
    ("driver",  "13820000053", "压测司机%03d" % 53),
    ("shipper", "13910000064", "压测货主%03d" % 64),
    ("dispatcher", "13800000004", "压测派单员02"),
    ("dispatcher", "13800000005", "压测派单员03"),
]

TODAY = time.strftime("%Y-%m-%d")
MONTH = time.strftime("%Y-%m")

# 1x1 透明 PNG（送达照片用）
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                    "0000000a49444154789c63600000020001a4d345580000000049454e44ae426082")

stats = {}      # op -> {"ok":n, "exp4":n, "bad4":n, "5xx":n, "net":n, "lat":[sec], "det":[]}
slock = threading.Lock()
stop = threading.Event()
product_ids = []            # 可售商品 id
shipper_ids = []            # 货主账号 id (代下单用)
driver_ids = []             # 司机用户 id (派单用)
created_products = [0]
flow = {"orders_created": 0, "orders_acked": 0, "orders_completed": 0,
        "orders_assigned": 0, "biz_rej": 0}
flock = threading.Lock()
fresh_orders = deque()          # 新订单队列(派单员取单源)
fq_lock = threading.Lock()

def record(op, st, dt, expected4=False):
    with slock:
        s = stats.setdefault(op, {"ok": 0, "exp4": 0, "bad4": 0, "5xx": 0, "net": 0, "lat": [], "det": []})
        if st in (200, 201, 204):
            s["ok"] += 1
            s["lat"].append(dt)
        elif st == -1:
            s["net"] += 1
        elif st >= 500:
            s["5xx"] += 1
        elif st in (400, 409, 422) and expected4:
            s["exp4"] += 1
        else:
            s["bad4"] += 1
            if len(s["det"]) < 5:
                s["det"].append("%s %s" % (op, st))

def request(method, path, tok=None, body=None, raw_body=None, ctype="application/json", timeout=18):
    url = BASE + path
    req = urllib.request.Request(url, method=method)
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    if raw_body is not None:
        req.add_header("Content-Type", ctype)
        data = raw_body
    elif body is not None:
        req.add_header("Content-Type", ctype)
        data = json.dumps(body).encode()
    else:
        data = None
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            raw = r.read()
            js = None
            if raw:
                try:
                    js = json.loads(raw)
                except Exception:
                    js = None
            return r.status, js, time.monotonic() - t0
    except urllib.error.HTTPError as e:
        raw = b""
        try:
            raw = e.read()
        except Exception:
            pass
        js = None
        if raw:
            try:
                js = json.loads(raw)
            except Exception:
                js = None
        return e.code, js, time.monotonic() - t0
    except Exception:
        return -1, None, time.monotonic() - t0

def login(phone):
    st, js, _ = request("POST", "/api/v1/auth/login", body={"phone": phone, "password": PASS}, timeout=15)
    return js.get("access_token") if st == 200 and js else None

def multipart(fields, fname, content, ctype):
    boundary = "----SOrdersB" + str(random.randrange(10 ** 8))
    parts = []
    for k, v in fields.items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, str(v))).encode())
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"files\"; filename=\"%s\"\r\n"
                  "Content-Type: %s\r\n\r\n" % (boundary, fname, ctype)).encode())
    parts.append(content + b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode())
    return b"".join(parts), "multipart/form-data; boundary=" + boundary

def order_body(phone, sid=None):
    nlines = random.randint(1, 3)
    lines = []
    for _ in range(nlines):
        pid = random.choice(product_ids)
        lines.append({
            "product_id": pid,
            "product_name_snapshot": "混压商品",
            "quantity": random.randint(1, 8),
            "unit_price": "%.2f" % random.uniform(5, 60),
        })
    b = {
        "lines": lines,
        "delivery_description": "正常送货",
        "address_detail": "测试大道%d号" % random.randint(1, 300),
        "contact_boss_phone": phone,
        "remark": "120混合连续负载",
    }
    if sid is not None:
        b["shipper_id"] = sid
    return b

# ---------------- workers ----------------

def worker_shipper(idx, phone, tok):
    time.sleep(random.uniform(0, 5))
    while not stop.is_set():
        r = random.random()
        if r < 0.50:
            st, js, dt = request("POST", "/api/v1/orders", tok, order_body(phone))
            record("shipper/create_order", st, dt)
            if st == 201 and js:
                with flock:
                    flow["orders_created"] += 1
                with fq_lock:
                    fresh_orders.append(js.get("id"))
        elif r < 0.65:
            st, js, dt = request("GET", "/api/v1/orders", tok)
            record("shipper/list_orders", st, dt)
        elif r < 0.77:
            st, js, dt = request("GET", "/api/v1/ledger/entries?date_from=" + TODAY, tok)
            record("shipper/ledger", st, dt)
        elif r < 0.87:
            st, js, dt = request("GET", "/api/v1/notifications", tok)
            record("shipper/notifications", st, dt)
        elif r < 0.95:
            st, js, dt = request("GET", "/api/v1/products", tok)
            record("shipper/products", st, dt)
        else:
            st, js, dt = request("GET", "/api/v1/orders?status=DELIVERED", tok)
            record("shipper/delivered_query", st, dt)
        time.sleep(random.uniform(0.8, 2.6) * PACE)

def worker_driver(idx, phone, tok):
    time.sleep(random.uniform(2, 7))
    done = set()
    while not stop.is_set():
        r = random.random()
        if r < 0.34:
            st, js, dt = request("GET", "/api/v1/orders", tok)
            record("driver/list_orders", st, dt)
            if st == 200 and isinstance(js, list):
                for o in js:
                    if o.get("id") in done:
                        continue
                    oid = o.get("id")
                    stt = o.get("status")
                    if stt == "DISPATCHED":
                        st2, js2, dt2 = request("POST", "/api/v1/orders/%d/driver-ack" % oid, tok)
                        record("driver/ack", st2, dt2, expected4=True)
                        if st2 == 200:
                            with flock:
                                flow["orders_acked"] += 1
                        # 不加入 done：下次轮询按 ACCEPTED 完成
                    elif stt == "ACCEPTED":
                        pay = "cash" if o.get("collect_cash") and random.random() < 0.6 else "arrears"
                        fields = {"payment": pay, "driver_remark": "正常送达"}
                        if random.random() < 0.05:
                            ops = o.get("order_products") or []
                            for lp in ops[:1]:
                                if (lp.get("quantity") or 1) >= 2:
                                    fields["damage_items"] = json.dumps(
                                        [{"order_product_id": lp.get("id"), "quantity": 1}])
                                    fields["damage_note"] = "混压货损1件"
                                    break
                        raw, ct = multipart(fields, "d.png", PNG, "image/png")
                        st3, js3, dt3 = request("POST", "/api/v1/orders/%d/complete-with-upload" % oid,
                                                tok, raw_body=raw, ctype=ct, timeout=25)
                        record("driver/complete", st3, dt3, expected4=True)
                        if st3 == 200:
                            with flock:
                                flow["orders_completed"] += 1
                        done.add(oid)
        elif r < 0.44:
            st, js, dt = request("GET", "/api/v1/freight-settlement?month=" + MONTH, tok)
            record("driver/freight", st, dt)
        elif r < 0.52:
            st, js, dt = request("GET", "/api/v1/notifications", tok)
            record("driver/notifications", st, dt)
        time.sleep(random.uniform(0.7, 2.4) * PACE)

def worker_disp(idx, phone, tok):
    time.sleep(random.uniform(1, 4))
    n = 0
    while not stop.is_set():
        n += 1
        r = random.random()
        if r < 0.35:
            got = []
            with fq_lock:
                while len(got) < 2 and fresh_orders:
                    oid = fresh_orders.popleft()
                    if oid:
                        got.append(oid)
            for oid in got:
                if not driver_ids:
                    break
                d = random.choice(driver_ids)
                body = {"driver_id": d, "freight_fee": "%.2f" % random.uniform(8, 30),
                        "collect_cash": random.random() < 0.3}
                st2, js2, dt2 = request("POST", "/api/v1/orders/%d/assign" % oid, tok, body)
                record("disp/assign", st2, dt2, expected4=True)
                if st2 == 200:
                    with flock:
                        flow["orders_assigned"] += 1
        elif r < 0.40:
            st, js, dt = request("GET", "/api/v1/reports/turnover?mode=day&date=" + TODAY, tok)
            record("disp/report_turnover", st, dt)
        elif r < 0.48:
            st, js, dt = request("GET", "/api/v1/reports/products?mode=day&date=" + TODAY, tok)
            record("disp/report_products", st, dt)
        elif r < 0.56:
            st, js, dt = request("GET", "/api/v1/stats/driver-performance?date_from=%s&date_to=%s" % (TODAY, TODAY), tok)
            record("disp/stats_driver", st, dt)
        elif r < 0.62:
            st, js, dt = request("GET", "/api/v1/stats/exception-orders?date_from=%s&date_to=%s" % (TODAY, TODAY), tok)
            record("disp/stats_exception", st, dt)
        elif r < 0.68:
            st, js, dt = request("GET", "/api/v1/reports/arrears-summary?date_from=%s&date_to=%s" % (TODAY, TODAY), tok)
            record("disp/arrears", st, dt)
        elif r < 0.74:
            st, js, dt = request("GET", "/api/v1/ledger/entries?date_from=" + TODAY, tok)
            record("disp/ledger", st, dt)
        elif r < 0.80:
            kind = "member" if random.random() < 0.2 else "shipper"
            st, js, dt = request("GET", "/api/v1/ledger/accounts?kind=" + kind, tok)
            record("disp/ledger_accounts", st, dt)
        elif r < 0.85:
            st, js, dt = request("GET", "/api/v1/freight-settlement?month=" + MONTH, tok)
            record("disp/freight_all", st, dt)
        elif r < 0.89:
            created_products[0] += 1
            body = {"name": "混压商品%d" % created_products[0],
                    "default_unit_price": "%.2f" % random.uniform(5, 80),
                    "cost_price": "%.2f" % random.uniform(2, 40),
                    "unit": random.choice(["件", "箱", "桶"]),
                    "stock": 200, "low_stock_alert": 20}
            st, js, dt = request("POST", "/api/v1/products", tok, body)
            record("disp/create_product", st, dt)
            if st == 201 and js:
                with slock:
                    product_ids.append(js.get("id"))
        elif r < 0.95:
            pid = random.choice(product_ids)
            body = {"default_unit_price": "%.2f" % random.uniform(5, 80),
                    "cost_price": "%.2f" % random.uniform(2, 40)}
            st, js, dt = request("PATCH", "/api/v1/products/%d" % pid, tok, body)
            record("disp/patch_price", st, dt)
        elif r < 0.98:
            sid = random.choice(shipper_ids)
            st, js, dt = request("POST", "/api/v1/orders", tok, order_body(phone, sid))
            record("disp/proxy_order", st, dt)
            if st == 201 and js:
                with flock:
                    flow["orders_created"] += 1
                with fq_lock:
                    fresh_orders.append(js.get("id"))
        else:
            st, js, dt = request("GET", "/api/v1/notifications", tok)
            record("disp/notifications", st, dt)
        if n % 120 == 0:
            st, js, dt = request("GET", "/api/v1/reports/export?kind=turnover&mode=day&date=" + TODAY, tok, timeout=60)
            record("disp/export_xlsx", st, dt)
        time.sleep(random.uniform(0.9, 2.4) * PACE)

def pct(lo):
    lo = sorted(lo)
    if not lo:
        return 0, 0, 0
    n = len(lo)
    return lo[int(n * 0.5)] * 1000, lo[int(n * 0.95)] * 1000, lo[int(n * 0.99)] * 1000

# ---------------- main ----------------

def main():
    print("[setup] 登录派单员...", flush=True)
    tok_d = login(DISPATCHERS[0])
    if not tok_d:
        print("SETUP FAIL: 派单员登录失败"); return 1

    for role, phone, name in NEW_USERS:
        body = {"phone": phone, "username": name, "password": PASS, "full_name": name, "role": role}
        if role == "driver":
            body.update({"vehicle_type": "small", "billing_mode": "piece"})
        st, js, dt = request("POST", "/api/v1/users", tok_d, body)
        print("[setup] 用户 %s %s -> %s" % (role, phone, st), flush=True)

    st, js, _ = request("GET", "/api/v1/products", tok_d)
    if st == 200 and isinstance(js, list):
        product_ids.extend([p.get("id") for p in js if p.get("id")])
    print("[setup] 商品目录: %d 个 (id %s..%s)" % (len(product_ids), min(product_ids) if product_ids else 0, max(product_ids) if product_ids else 0), flush=True)

    st, js, _ = request("GET", "/api/v1/users?role=shipper&limit=200", tok_d)
    if st == 200 and isinstance(js, list):
        shipper_ids.extend([u.get("id") for u in js])
    print("[setup] 货主账号: %d" % len(shipper_ids), flush=True)

    driver_id_by_phone = {}
    st, js, _ = request("GET", "/api/v1/users?role=driver&limit=300", tok_d)
    if st == 200 and isinstance(js, list):
        driver_id_by_phone = {u.get("phone"): u.get("id") for u in js}
        for ph in DRIVERS:
            if driver_id_by_phone.get(ph):
                driver_ids.append(driver_id_by_phone[ph])
    print("[setup] 司机账号: %d (可用派单 driver_ids=%d)" % (len(driver_id_by_phone), len(driver_ids)), flush=True)

    accounts = []
    okn = 0
    for ph in DISPATCHERS + SHIPPERS + DRIVERS:
        t = login(ph)
        if t:
            okn += 1
        else:
            print("[setup] 登录失败: %s" % ph, flush=True)
        accounts.append((ph, t))
    print("[setup] 预登录: %d/120 成功" % okn, flush=True)
    if okn < 110:
        print("SETUP FAIL: 预登录不足"); return 1

    toks = {ph: t for ph, t in accounts if t}
    T0 = time.strftime("%Y-%m-%d %H:%M:%S")

    threads = []
    si = di = 0
    for ph in SHIPPERS + DRIVERS:
        t = toks.get(ph)
        if not t:
            continue
        if ph in DRIVERS:
            di += 1
            threads.append(threading.Thread(target=worker_driver, args=(di, ph, t), daemon=True))
        else:
            si += 1
            threads.append(threading.Thread(target=worker_shipper, args=(si, ph, t), daemon=True))
    for i, ph in enumerate(DISPATCHERS):
        t = toks.get(ph)
        if t:
            threads.append(threading.Thread(target=worker_disp, args=(i, ph, t), daemon=True))
    print("[run] 启动 %d 工作线程 (%d货主/%d司机/%d派单员), 时长 %ds" % (len(threads), si, di, len(DISPATCHERS), DURATION), flush=True)
    for th in threads:
        th.start()

    t_start = time.monotonic()
    last = 0
    while time.monotonic() - t_start < DURATION:
        time.sleep(10)
        now = int(time.monotonic() - t_start)
        if now - last >= 30:
            last = now
            with slock:
                tot_ok = sum(s["ok"] for s in stats.values())
                tot_5xx = sum(s["5xx"] for s in stats.values())
                tot_bad = sum(s["bad4"] for s in stats.values())
            print("[run] t=%ds ok=%d 5xx=%d bad4xx=%d flow=%s" % (now, tot_ok, tot_5xx, tot_bad, json.dumps(flow)), flush=True)
    stop.set()
    time.sleep(3)
    for th in threads:
        th.join(timeout=2)
    T1 = time.strftime("%Y-%m-%d %H:%M:%S")
    elapsed = time.monotonic() - t_start

    total_ok = sum(s["ok"] for s in stats.values())
    total_exp = sum(s["exp4"] for s in stats.values())
    total_bad = sum(s["bad4"] for s in stats.values())
    total_5xx = sum(s["5xx"] for s in stats.values())
    total_net = sum(s["net"] for s in stats.values())
    total = total_ok + total_exp + total_bad + total_5xx + total_net

    print("=" * 60, flush=True)
    print("[RESULT] 120用户连续负载 %ds | 时段 %s ~ %s" % (elapsed, T0, T1), flush=True)
    print("[RESULT] 总请求 %d | 成功 %d (%.2f%%) | 业务竞态 %d | 意外4xx %d | 5xx %d | 网络失败 %d" %
          (total, total_ok, total_ok * 100.0 / total if total else 0, total_exp, total_bad, total_5xx, total_net), flush=True)
    print("[RESULT] RPS %.1f" % (total / elapsed if elapsed else 0), flush=True)
    all_lat = []
    for k in sorted(stats.keys()):
        s = stats[k]
        p50, p95, p99 = pct(s["lat"])
        if s["ok"] > 0:
            all_lat += s["lat"]
        print("  %-26s ok=%-5d exp4=%-3d bad4=%-3d 5xx=%-3d net=%-3d p50=%dms p95=%dms p99=%dms" %
              (k, s["ok"], s["exp4"], s["bad4"], s["5xx"], s["net"], p50, p95, p99), flush=True)
    p50, p95, p99 = pct(all_lat)
    print("[RESULT] 全量成功延迟 p50=%dms p95=%dms p99=%dms" % (p50, p95, p99), flush=True)
    print("[FLOW] %s" % json.dumps(flow), flush=True)

    tok_v = toks.get(DISPATCHERS[0])
    veri = {}
    for name, path in [
        ("turnover", "/api/v1/reports/turnover?mode=day&date=" + TODAY),
        ("report_products", "/api/v1/reports/products?mode=day&date=" + TODAY),
        ("driver_perf", "/api/v1/stats/driver-performance?date_from=%s&date_to=%s" % (TODAY, TODAY)),
        ("exceptions", "/api/v1/stats/exception-orders?date_from=%s&date_to=%s" % (TODAY, TODAY)),
        ("arrears", "/api/v1/reports/arrears-summary?date_from=%s&date_to=%s" % (TODAY, TODAY)),
        ("freight", "/api/v1/freight-settlement?month=" + MONTH),
        ("ledger_acc", "/api/v1/ledger/accounts?kind=shipper"),
        ("ledger_entries", "/api/v1/ledger/entries?date_from=" + TODAY),
        ("pending", "/api/v1/orders?status=PENDING_DISPATCH&date_from=" + TODAY),
    ]:
        st, js, dt = request("GET", path, tok_v)
        veri[name] = {"status": st, "elapsed": dt, "data": js if st == 200 else None}
        print("[VERIFY] %-18s st=%d %.2fs" % (name, st, dt), flush=True)

    with open("/tmp/mixed120_results.json", "w") as f:
        json.dump({
            "window": [T0, T1], "flow": flow,
            "stats": {k: v for k, v in stats.items()},
            "verify": {k: {"status": v["status"], "elapsed": v["elapsed"],
                           "data": v["data"]} for k, v in veri.items()},
        }, f, ensure_ascii=False, indent=1)
    print("DONE", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
