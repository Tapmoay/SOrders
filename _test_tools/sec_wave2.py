# -*- coding: utf-8 -*-
"""安全测试第二波：对象级越权/注入/敏感字段/上传/边界值"""
import sys, json, io
sys.stdout.reconfigure(encoding='utf-8')
import requests, warnings
warnings.filterwarnings('ignore')

BASE = 'http://127.0.0.1:8000'
results = []
def log(name, status, detail=''):
    results.append(f"[{status}] {name} {detail[:220]}")

tok_d = requests.post(BASE+'/api/v1/auth/login', json={'phone':'13800000001','password':'pass12345'}, timeout=10).json()['access_token']
tok_s = requests.post(BASE+'/api/v1/auth/login', json={'phone':'13800000002','password':'pass12345'}, timeout=10).json()['access_token']
tok_drv = requests.post(BASE+'/api/v1/auth/login', json={'phone':'13800000003','password':'pass12345'}, timeout=10).json()['access_token']
tok_drv2 = requests.post(BASE+'/api/v1/auth/login', json={'phone':'13820000001','password':'pass12345'}, timeout=10).json().get('access_token')
H_D = {'Authorization': f'Bearer {tok_d}'}
H_S = {'Authorization': f'Bearer {tok_s}'}
H_DRV = {'Authorization': f'Bearer {tok_drv}'}
H_DRV2 = {'Authorization': f'Bearer {tok_drv2}'} if tok_drv2 else None

# ========== A. 订单对象级越权 ==========
# 先用货主造一个订单，再由另一货主/司机尝试操作
# 找一个已有关联司机且非13800000003的订单
r = requests.get(BASE+'/api/v1/orders', headers=H_D, timeout=10)
orders = r.json() if isinstance(r.json(), list) else []
assigned_order = None
for o in orders:
    if o.get('status') == 'DELIVERED' and o.get('driver_id') and o.get('driver_id') not in (3,):
        assigned_order = o; break
print('target delivered order:', assigned_order and (assigned_order['id'], assigned_order['driver_id'], assigned_order['status']))

# A1: 货主（13800000002，非该单货主）尝试看/完成/撤销他人订单
if assigned_order:
    oid = assigned_order['id']
    r = requests.get(BASE+f'/api/v1/orders/{oid}', headers=H_S, timeout=10)
    log(f'A1 货主读他人订单{oid}', r.status_code, r.text[:80])
    r = requests.post(BASE+f'/api/v1/orders/{oid}/cancel', headers=H_S, timeout=10)
    log(f'A2 货主撤销他人订单{oid}', r.status_code, r.text[:80])
    r = requests.post(BASE+f'/api/v1/orders/{oid}/complete', headers=H_S, json={'payment':'cash'}, timeout=10)
    log(f'A3 货主完成他人订单{oid}', r.status_code, r.text[:80])

# A4: 司机2查看司机1的订单（列表应只有自己）
if H_DRV2:
    r = requests.get(BASE+'/api/v1/orders', headers=H_DRV2, timeout=10)
    try:
        data = r.json()
        driver_ids = set(o.get('driver_id') for o in data)
        print('DRIVER2 /orders count:', len(data) if isinstance(data, list) else data, 'driver_ids:', driver_ids)
    except Exception:
        log('DRIVER2 GET /orders', r.status_code, r.text[:80])

# A5: 司机访问未指派给自己的订单详情
if assigned_order and H_DRV2:
    r = requests.get(BASE+f'/api/v1/orders/{assigned_order["id"]}', headers=H_DRV2, timeout=10)
    log(f'A5 司机2读司机1订单{assigned_order["id"]}', r.status_code, r.text[:80])

# ========== B. SQL 注入探测 ==========
injections = ["' OR '1'='1", "1; DROP TABLE users--", "1' UNION SELECT * FROM users--", "%27%20OR%201%3D1", "'"]
for inj in injections[:3]:
    r = requests.get(BASE+f'/api/v1/orders?status={inj}', headers=H_D, timeout=10)
    log(f'B SQLi status={inj[:20]}', r.status_code, r.text[:60])
    r = requests.get(BASE+f'/api/v1/users?role={inj}', headers=H_D, timeout=10)
    log(f'B SQLi role={inj[:20]}', r.status_code, r.text[:60])

# ========== C. 敏感字段泄露 ==========
r = requests.get(BASE+'/api/v1/users/1', headers=H_D, timeout=10)
body = r.text
log('C 用户接口含password_hash?', r.status_code, 'HAS hash' if 'password_hash' in body or 'password' in body.lower() else 'NO password field')
for probe in ['password_hash', 'password', 'jwt_secret', 'secret']:
    if probe in body.lower():
        log(f'C LEAK={probe}', r.status_code, body[:150])

# ========== D. 上传验证 ==========
# D1: 假图片（含PHP脚本头）
fake_png = b"\x89PNG\r\n\x1a\n" + b"<?php system($_GET['c']); ?>".ljust(80)
r = requests.post(BASE+'/api/v1/orders/1/delivery-photos', headers=H_D, files={'file': ('evil.php.png', io.BytesIO(fake_png), 'image/png')}, timeout=10)
log('D1 上传伪png', r.status_code, r.text[:100])
# D2: 直接改 content_type 传 .php
r = requests.post(BASE+'/api/v1/orders/1/delivery-photos', headers=H_D, files={'file': ('shell.php', io.BytesIO(fake_png), 'application/x-php')}, timeout=10)
log('D2 上传php content_type', r.status_code, r.text[:100])

print("\n".join(results))