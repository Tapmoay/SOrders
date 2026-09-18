import json, urllib.request, urllib.error, threading, time, random, sys
BASE = "http://127.0.0.1:8000"

def post(path, body, tok=None, timeout=20):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    if tok: req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return -1

def get(path, tok=None, timeout=20):
    req = urllib.request.Request(BASE + path)
    if tok: req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return -1

def login(phone):
    try:
        req = urllib.request.Request(BASE + "/api/v1/auth/login", data=json.dumps({"phone": phone, "password": "pass12345"}).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("access_token")
    except Exception:
        return None

N_USERS = int(sys.argv[1]) if len(sys.argv) > 1 else 110
DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 60
PREFIX = sys.argv[3] if len(sys.argv) > 3 else "srv"

SHIPPERS = ["1391000%04d" % i for i in range(1, 61)]
DRIVERS = ["1382000%04d" % i for i in range(1, 51)]

stats = {"ok": {}, "lat": []}
stlock = threading.Lock()
stopevt = threading.Event()

def record(name, st, dur):
    with stlock:
        k = name if st in (200, 201) else name + "::" + str(st)
        stats["ok"][k] = stats["ok"].get(k, 0) + 1
        stats["lat"].append((dur, st in (200, 201)))

def shipper_worker(idx, phone):
    tok = login(phone)
    if not tok:
        record("shipper/login_fail", -1, 0)
        return
    while not stopevt.is_set():
        r = random.random()
        t0 = time.time()
        if r < 0.25:
            st = get("/api/v1/orders", tok)
            record("shipper/list_orders", st, time.time() - t0)
        elif r < 0.45:
            body = {"lines": [{"product_id": random.randint(1, 20), "product_name_snapshot": "压测", "quantity": random.randint(1, 5), "unit_price": "%d.00" % random.randint(5, 50)}], "address_detail": "压测地址", "contact_boss_phone": phone}
            st = post("/api/v1/orders", body, tok)
            record("shipper/create_order", st, time.time() - t0)
        elif r < 0.6:
            st = get("/api/v1/products", tok)
            record("shipper/products", st, time.time() - t0)
        elif r < 0.8:
            st = get("/api/v1/ledger/entries?from=2026-09-01&to=2026-09-30", tok)
            record("shipper/ledger", st, time.time() - t0)
        else:
            st = post("/api/v1/orders", {"lines": [{"product_id": 1, "product_name_snapshot": "压测", "quantity": 1, "unit_price": "10.00"}], "address_detail": "压测", "contact_boss_phone": phone}, tok)
            record("shipper/create_order2", st, time.time() - t0)
        time.sleep(random.uniform(0.5, 2.5))

def driver_worker(idx, phone):
    tok = login(phone)
    if not tok:
        record("driver/login_fail", -1, 0)
        return
    while not stopevt.is_set():
        t0 = time.time()
        st = get("/api/v1/orders", tok)
        record("driver/list", st, time.time() - t0)
        time.sleep(random.uniform(1.0, 3.0))

def dispatcher_worker():
    tok = login("13800000001")
    while not stopevt.is_set():
        t0 = time.time()
        r = random.random()
        if r < 0.3:
            st = get("/api/v1/orders?status=PENDING_DISPATCH", tok)
            record("disp/pool", st, time.time() - t0)
        elif r < 0.5:
            st = get("/api/v1/reports/turnover?mode=day&date=2026-09-04", tok)
            record("disp/reports", st, time.time() - t0)
        elif r < 0.7:
            st = get("/api/v1/orders", tok)
            record("disp/orders", st, time.time() - t0)
        else:
            st = get("/api/v1/users?limit=100", tok)
            record("disp/users", st, time.time() - t0)
        time.sleep(random.uniform(0.8, 2.0))

n_ship = int(N_USERS * 0.40)
n_drv = N_USERS - n_ship - 1
print("[%s] %d并发 = 派单员1 + 货主%d + 司机%d (服务器本机)" % (PREFIX, N_USERS, n_ship, n_drv), flush=True)
threads = []
for i in range(n_ship):
    threads.append(threading.Thread(target=shipper_worker, args=(i, SHIPPERS[i % len(SHIPPERS)])))
for i in range(n_drv):
    threads.append(threading.Thread(target=driver_worker, args=(i, DRIVERS[i % len(DRIVERS)])))
threads.append(threading.Thread(target=dispatcher_worker))
for t in threads: t.start()

t0 = time.time()
try:
    while time.time() - t0 < DURATION:
        time.sleep(1)
finally:
    stopevt.set()
    time.sleep(2)
    for t in threads: t.join(timeout=1)

elapsed = time.time() - t0
total = sum(stats["ok"].values())
okc = sum(v for k, v in stats["ok"].items() if "::" not in k)
errc = total - okc
print("===== [%s] %d并发 %ds =====" % (PREFIX, N_USERS, DURATION), flush=True)
print("总请求: %d | 成功: %d | 失败: %d | 错误率: %.2f%%" % (total, okc, errc, errc/total*100 if total else 0), flush=True)
print("RPS: %.1f" % (total/elapsed if elapsed else 0), flush=True)
for k in sorted(stats["ok"].keys()):
    print("  %s: %d" % (k, stats["ok"][k]), flush=True)
lat_ok = sorted(d for d, ok in stats["lat"] if ok)
if lat_ok:
    n = len(lat_ok)
    print("延迟: p50=%dms p95=%dms p99=%dms" % (lat_ok[int(n*0.5)]*1000, lat_ok[int(n*0.95)]*1000, lat_ok[int(n*0.99)]*1000), flush=True)