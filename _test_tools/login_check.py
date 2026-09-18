
import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests
BASE = 'http://127.0.0.1:8000'
# 用刚才插入的 test_driver_050 尝试登录
r = requests.post(BASE + '/api/v1/auth/login', json={'phone':'13820000050','password':'pass12345'}, timeout=10)
print('LOGIN test_driver_050:', r.status_code, r.text[:150])
# 用 test_shipper_01 尝试登录（role 大写 SHIPPER 是否有影响）
r2 = requests.post(BASE + '/api/v1/auth/login', json={'phone':'13910000001','password':'pass12345'}, timeout=10)
print('LOGIN test_shipper_001:', r2.status_code, r2.text[:150])
