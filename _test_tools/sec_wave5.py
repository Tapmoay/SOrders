# -*- coding: utf-8 -*-
"""验证司机自改工资越权 + 司机上传校验"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests, io

BASE = 'http://127.0.0.1:8000'

def login(phone):
    return requests.post(BASE+'/api/v1/auth/login', json={'phone':phone,'password':'pass12345'}, timeout=10).json().get('access_token')

# 司机 13800000003 (id=3, PIECE)。先看当前 salary
tok_drv = login('13800000003')
H_DRV = {'Authorization': f'Bearer {tok_drv}'}
r = requests.get(BASE+'/api/v1/users/me', headers=H_DRV, timeout=10)
me = r.json()
print('司机当前:', me.get('id'), me.get('role'), 'salary:', me.get('salary'), 'billing:', me.get('billing_mode'))

# 越权1：司机改自己 salary（piECE司机原salary应为None/0）
r = requests.patch(BASE+'/api/v1/users/3', headers=H_DRV, json={'salary': '999999.00'}, timeout=10)
print('司机改自己salary: ', r.status_code, r.text[:200])

# 恢复
r = requests.patch(BASE+'/api/v1/users/3', headers=H_DRV, json={'salary': '0.00'}, timeout=10)
print('恢复0: ', r.status_code)

# 越权2：司机改自己 billing_mode（PIECE→SALARY）影响计费！
r = requests.patch(BASE+'/api/v1/users/3', headers=H_DRV, json={'billing_mode': 'salary'}, timeout=10)
print('司机改billing_mode PIECE→SALARY: ', r.status_code, r.text[:150])
r = requests.patch(BASE+'/api/v1/users/3', headers=H_DRV, json={'billing_mode': 'piece'}, timeout=10)
print('恢复piece: ', r.status_code)

# 越权3：司机改自己 vehicle_type
r = requests.patch(BASE+'/api/v1/users/3', headers=H_DRV, json={'vehicle_type': 'trailer'}, timeout=10)
print('司机改vehicle_type→trailer: ', r.status_code)
r = requests.patch(BASE+'/api/v1/users/3', headers=H_DRV, json={'vehicle_type': 'small'}, timeout=10)
print('恢复small: ', r.status_code)

# 越权4：司机改 full_name（应允许？full_name是个人信息）
r = requests.patch(BASE+'/api/v1/users/3', headers=H_DRV, json={'full_name': '被篡改的司机'}, timeout=10)
print('司机改full_name: ', r.status_code, r.text[:80])

# 上传：用司机token测试 delivery-photos（订单37已DELIVERED，用订单24试试）
fake = b"\x89PNG\r\n\x1a\n" + b"php code" * 10
r = requests.post(BASE+'/api/v1/orders/24/delivery-photos', headers=H_DRV, files=[('files', ('ok.png', io.BytesIO(fake), 'image/png'))], timeout=10)
print('司机上传伪png: ', r.status_code, r.text[:120])
r = requests.post(BASE+'/api/v1/orders/24/delivery-photos', headers=H_DRV, files=[('files', ('evil.php', io.BytesIO(fake), 'application/x-php'))], timeout=10)
print('司机上传php类型: ', r.status_code, r.text[:120])
r = requests.post(BASE+'/api/v1/orders/24/delivery-photos', headers=H_DRV, files=[('files', ('x.svg', io.BytesIO(b'<svg onload=alert(1)>'), 'image/svg+xml'))], timeout=10)
print('司机上传svg: ', r.status_code, r.text[:120])