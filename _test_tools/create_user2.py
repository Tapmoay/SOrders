import json, urllib.request
BASE = "http://127.0.0.1:8000"

def post(path, body, tok=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    if tok: req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]

st, d = post("/api/v1/auth/login", {"phone": "13800000001", "password": "pass12345"})
print("login:", st)
tok = d.get("access_token") if isinstance(d, dict) else None

st, d = post("/api/v1/users", {"phone": "13820000001", "username": "test_driver_01", "password": "pass12345", "full_name": "压测司机1", "role": "driver", "vehicle_type": "small", "billing_mode": "piece"}, tok)
print("create driver:", st, d if isinstance(d, str) else {k: d.get(k) for k in ["id", "role", "billing_mode"]})

st, d = post("/api/v1/users", {"phone": "13910000001", "username": "test_shipper_01", "password": "pass12345", "full_name": "压测货主1", "role": "shipper"}, tok)
print("create shipper:", st, d if isinstance(d, str) else {k: d.get(k) for k in ["id", "role", "is_member"]})