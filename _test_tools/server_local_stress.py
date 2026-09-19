import json, urllib.request, urllib.error, threading, time, random
BASE = "http://127.0.0.1:8000"

def post(path, body, tok=None, timeout=15):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    if tok: req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except Exception as e:
        return -1

# 登录60个用户
toks = []
for i in range(1, 61):
    st, d = 0, None
    req = urllib.request.Request(BASE + "/api/v1/auth/login", data=json.dumps({"phone": f"1391000{i:04d}", "password": "pass12345"}).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read())
            toks.append(d.get("access_token"))
    except Exception as e:
        toks.append(None)
print("login ok:", sum(1 for t in toks if t), "/60", flush=True)

def worker(n, results):
    tok = toks[n % len(toks)]
    ok = 0
    for j in range(3):
        body = {"lines": [{"product_id": random.randint(1, 20), "product_name_snapshot": "本机压测", "quantity": random.randint(1, 5), "unit_price": "10.00"}], "address_detail": f"本机压测{n}", "contact_boss_phone": f"1391000{n:04d}"}
        st = post("/api/v1/orders", body, tok)
        if st == 201: ok += 1
    results[n] = ok

# 50 线程并发
results = [0] * 50
threads = [threading.Thread(target=worker, args=(i, results)) for i in range(50)]
t0 = time.time()
for t in threads: t.start()
for t in threads: t.join()
dur = time.time() - t0
print(f"50线程本机压测: ok={sum(results)}/150, 耗时{dur:.1f}s", flush=True)