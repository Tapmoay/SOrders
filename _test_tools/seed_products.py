import json, urllib.request, urllib.error
BASE = "http://127.0.0.1:8000"

def post(path, body, tok=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    if tok: req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]

st, d = post("/api/v1/auth/login", {"phone": "13800000001", "password": "pass12345"})
tok = d.get("access_token")
print("login:", st)

ok = 0; err = []
for i in range(1, 21):
    st, d = post("/api/v1/products", {"name": f"测试商品{i:02d}", "default_unit_price": f"{10 + i}.50", "cost_price": f"{5 + i}.00", "unit": "件", "stock": 10000, "low_stock_alert": 100}, tok)
    if st == 201: ok += 1
    else: err.append((i, st, d if isinstance(d, str) else ""))

print(f"products: ok={ok} err={len(err)}")
for e in err[:5]: print("err", e)

# 验证
req = urllib.request.Request(BASE + "/api/v1/products?limit=30", headers={"Authorization": f"Bearer {tok}"})
with urllib.request.urlopen(req, timeout=10) as resp:
    prods = json.loads(resp.read())
print("total products:", len(prods), "ids:", [p["id"] for p in prods[:5]])