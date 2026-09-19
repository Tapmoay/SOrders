
# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests, traceback
BASE = 'http://127.0.0.1:8000'
tok = requests.post(BASE + '/api/v1/auth/login', json={'phone':'13800000001','password':'pass12345'}, timeout=10).json()['access_token']
H = {'Authorization': f"Bearer {tok}", 'Content-Type': 'application/json'}

# 1. 建一个最小用户试试
r = requests.post(BASE + '/api/v1/users', headers=H, json={
    'phone': '13990000001', 'username': 'test_min', 'password': 'pass12345',
    'full_name': '最小测试', 'role': 'shipper'
}, timeout=10)
print('MINIMAL:', r.status_code, r.text[:300])

# 2. 复现原 payload
r2 = requests.post(BASE + '/api/v1/users', headers=H, json={
    'phone': '13910000001', 'username': 'test_shipper_001', 'password': 'pass12345',
    'full_name': '测试货主001', 'role': 'shipper', 'is_member': True
}, timeout=10)
print('FULL:', r2.status_code, r2.text[:300])
