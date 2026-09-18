import json, urllib.request, urllib.error, threading, time, random
BASE = "http://127.0.0.1:8000"

def login(phone):
    req = urllib.request.Request(BASE + "/api/v1/auth/login", data=json.dumps({"phone": phone, "password": "pass12345"}).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read()).get("access_token")

tok = login("13800000001")
print("login ok", tok[:20], flush=True)

def get(path, tok):
    req = urllib.request.Request(BASE + path)
    req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return -1

results = [0] * 30
def worker(n):
    ok = 0
    for j in range(20):
        st = get("/api/v1/orders", tok)
        if st == 200: ok += 1
    results[n] = ok

threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
t0 = time.time()
for t in threads: t.start()
for t in threads: t.join()
dur = time.time() - t0
print(f"30线程x20次纯读orders: ok={sum(results)}/600 耗时{dur:.1f}s RPS={sum(results)/dur:.1f}", flush=True)