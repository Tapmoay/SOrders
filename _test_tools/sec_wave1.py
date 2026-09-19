# -*- coding: utf-8 -*-
"""安全测试第一波：认证与越权"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8')
import requests, warnings
warnings.filterwarnings('ignore')

BASE = 'http://127.0.0.1:8000'
results = []

def log(name, status, detail=''):
    results.append(f"[{status}] {name} {detail[:180]}")

# --- 0. 准备 tokens ---
tok_d = requests.post(BASE+'/api/v1/auth/login', json={'phone':'13800000001','password':'pass12345'}, timeout=10).json()['access_token']
tok_s = requests.post(BASE+'/api/v1/auth/login', json={'phone':'13800000002','password':'pass12345'}, timeout=10).json()['access_token']
tok_drv = requests.post(BASE+'/api/v1/auth/login', json={'phone':'13800000003','password':'pass12345'}, timeout=10).json()['access_token']
H_D = {'Authorization': f'Bearer {tok_d}'}
H_S = {'Authorization': f'Bearer {tok_s}'}
H_DRV = {'Authorization': f'Bearer {tok_drv}'}

# --- 1. 无 token 访问受保护接口 ---
for path in ['/api/v1/orders', '/api/v1/products', '/api/v1/users', '/api/v1/ledger/entries', '/api/v1/reports/turnover?mode=day&date=2026-09-04', '/api/v1/notifications/unread-count']:
    r = requests.get(BASE+path, timeout=10)
    log(f'NOTOKEN GET {path}', r.status_code)

# --- 2. 伪造 token ---
r = requests.get(BASE+'/api/v1/orders', headers={'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwicm9sZSI6ImRpc3BhdGNoZXIifQ.fake'}, timeout=10)
log('FORGED TOKEN', r.status_code)

# --- 3. 弱口令 ---
for pw in ['admin', '123456', '13800000001', 'pass12345']:
    r = requests.post(BASE+'/api/v1/auth/login', json={'phone':'13800000001','password':pw}, timeout=10)
    log(f'LOGIN weakpw={pw}', r.status_code)

# --- 4. 货主越权访问管理接口 ---
for path in ['/api/v1/users', '/api/v1/users?role=driver', '/api/v1/reports/turnover?mode=day&date=2026-09-04']:
    r = requests.get(BASE+path, headers=H_S, timeout=10)
    log(f'SHIPPER->{path} 应403', r.status_code)

# --- 5. 司机越权 ---
for path in ['/api/v1/users', '/api/v1/reports/turnover?mode=day&date=2026-09-04', '/api/v1/ledger/entries', '/api/v1/products']:
    r = requests.get(BASE+path, headers=H_DRV, timeout=10)
    log(f'DRIVER->{path} 应403', r.status_code)

# --- 6. 货主查订单（应只自己） ---
r = requests.get(BASE+'/api/v1/orders', headers=H_S, timeout=10)
try:
    data = r.json()
    if isinstance(data, list):
        shipper_ids = set(o.get('shipper_id') for o in data)
        print('SHIPPER /orders count:', len(data), 'shipper_ids:', shipper_ids)
except Exception: pass
log('SHIPPER GET /orders', r.status_code)

# --- 7. 货主访问他人用户详情 ---
r = requests.get(BASE+'/api/v1/users/3', headers=H_S, timeout=10)
log('SHIPPER->GET /users/3 应403', r.status_code)

# --- 8. health ---
r = requests.get(BASE+'/health', timeout=10)
log('HEALTH no token', r.status_code)

# --- 9. 注册开放 ---
r = requests.post(BASE+'/api/v1/auth/register', json={'phone':'13977777777','username':'regtest9','password':'pass12345','full_name':'注册测试'}, timeout=10)
log('REGISTER 开放?', r.status_code, r.text[:120])

# --- 10. 短信 ---
r = requests.post(BASE+'/api/v1/auth/sms/send', json={'phone':'13800000001'}, timeout=10)
log('SMS SEND', r.status_code, r.text[:200])

print('\n'.join(results))