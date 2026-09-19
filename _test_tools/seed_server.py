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

ok = 0; err = 0
# 60 货主
for i in range(1, 61):
    phone = f"1391000{i:04d}"
    st, d = post("/api/v1/users", {"phone": phone, "username": f"test_shipper_{i:03d}", "password": "pass12345", "full_name": f"压测货主{i:03d}", "role": "shipper", "is_member": (i <= 10)}, tok)
    if st == 201: ok += 1
    else: err += 1; print("shipper err", phone, st, d if isinstance(d, str) else "")

# 50 司机
for i in range(1, 51):
    phone = f"1382000{i:04d}"
    billing = "salary" if i % 5 == 0 else "piece"
    st, d = post("/api/v1/users", {"phone": phone, "username": f"test_driver_{i:03d}", "password": "pass12345", "full_name": f"压测司机{i:03d}", "role": "driver", "vehicle_type": "small", "billing_mode": billing}, tok)
    if st == 201: ok += 1
    else: err += 1; print("driver err", phone, st, d if isinstance(d, str) else "")

print(f"DONE: ok={ok} err={err}")