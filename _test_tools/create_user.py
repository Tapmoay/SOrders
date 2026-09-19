import requests
BASE = "http://127.0.0.1:8000"
r = requests.post(BASE + "/api/v1/auth/login", json={"phone": "13800000001", "password": "pass12345"}, timeout=10)
tok = r.json().get("access_token")
print("login:", r.status_code)
H = {"Authorization": f"Bearer {tok}"}
# 创建司机用户
r2 = requests.post(BASE + "/api/v1/users", headers=H, json={"phone": "13820000001", "username": "test_driver_01", "password": "pass12345", "full_name": "压测司机1", "role": "driver", "vehicle_type": "small", "billing_mode": "piece"}, timeout=10)
print("create driver:", r2.status_code, r2.text[:200])
# 创建货主用户
r3 = requests.post(BASE + "/api/v1/users", headers=H, json={"phone": "13910000001", "username": "test_shipper_01", "password": "pass12345", "full_name": "压测货主1", "role": "shipper", "is_member": False}, timeout=10)
print("create shipper:", r3.status_code, r3.text[:200])