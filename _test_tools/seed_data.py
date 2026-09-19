
# -*- coding: utf-8 -*-
"""批量创建测试数据：用户 + 商品"""
import sys, json, time
sys.stdout.reconfigure(encoding='utf-8')
import requests

BASE = 'http://127.0.0.1:8000'

def login(phone, pw='pass12345'):
    r = requests.post(BASE + '/api/v1/auth/login', json={'phone': phone, 'password': pw}, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"login fail {phone}: {r.text[:200]}")
    return r.json()['access_token']

tok = login('13800000001')
H = {'Authorization': f"Bearer {tok}", 'Content-Type': 'application/json'}

created_users = 0
created_products = 0
errors = []

# ---- 创建 60 货主（其中 10 个批发商 member）----
for i in range(1, 61):
    phone = f'1391000{i:04d}'
    try:
        r = requests.post(BASE + '/api/v1/users', headers=H, json={
            'phone': phone, 'username': f'test_shipper_{i:03d}', 'password': 'pass12345',
            'full_name': f'测试货主{i:03d}', 'role': 'shipper',
            'is_member': (i <= 10)
        }, timeout=10)
        if r.status_code == 201:
            created_users += 1
        elif r.status_code == 400 and '已存在' in r.text:
            created_users += 1
        else:
            errors.append(f"user {phone}: {r.status_code} {r.text[:100]}")
    except Exception as e:
        errors.append(f"user {phone}: {e}")

# ---- 创建 50 司机（40 PIECE + 10 SALARY）----
for i in range(1, 51):
    phone = f'1382000{i:04d}'
    billing = 'salary' if i % 5 == 0 else 'piece'
    try:
        r = requests.post(BASE + '/api/v1/users', headers=H, json={
            'phone': phone, 'username': f'test_driver_{i:03d}', 'password': 'pass12345',
            'full_name': f'测试司机{i:03d}', 'role': 'driver',
            'vehicle_type': 'small', 'billing_mode': billing,
            'salary': 4500 if billing == 'salary' else None
        }, timeout=10)
        if r.status_code == 201:
            created_users += 1
        elif r.status_code == 400 and '已存在' in r.text:
            created_users += 1
        else:
            errors.append(f"user {phone}: {r.status_code} {r.text[:100]}")
    except Exception as e:
        errors.append(f"user {phone}: {e}")

print(f"USERS done: +{created_users} (errors {len(errors)})")
for e in errors[:10]: print("  ERR:", e)

# ---- 创建 20 商品 ----
prod_errors = []
for i in range(1, 21):
    try:
        r = requests.post(BASE + '/api/v1/products', headers=H, json={
            'name': f'压测商品{i:02d}', 'default_unit_price': f'{10 + i}.50',
            'cost_price': f'{5 + i}.00', 'unit': '件',
            'stock': 1000 + i * 10, 'low_stock_alert': 100,
            'tier_prices': [
                {'label': '批发一', 'unit_price': f'{9 + i}.00'},
                {'label': '批发二', 'unit_price': f'{8 + i}.00'}
            ]
        }, timeout=10)
        if r.status_code == 201 or r.status_code == 200:
            created_products += 1
        elif r.status_code == 400 and '已存在' in r.text:
            created_products += 1
        else:
            prod_errors.append(f"prod {i}: {r.status_code} {r.text[:100]}")
    except Exception as e:
        prod_errors.append(f"prod {i}: {e}")
print(f"PRODUCTS done: +{created_products} (errors {len(prod_errors)})")
for e in prod_errors[:10]: print("  ERR:", e)

print("TOTAL: users+%d products+%d" % (created_users, created_products))
