# -*- coding: utf-8 -*-
"""恢复司机3数据 + 上传MIME真实验证（造ACCEPTED订单）"""
import sys, io, time
sys.stdout.reconfigure(encoding='utf-8')
import requests, sqlite3

# 1. 恢复司机3
conn = sqlite3.connect("D:/AProjects/ASDH/orders/backend/sorders.db")
cur = conn.cursor()
cur.execute("UPDATE users SET full_name='Driver', vehicle_type='small', billing_mode='piece', salary=NULL WHERE id=3")
conn.commit()
cur.execute("SELECT id, full_name, vehicle_type, billing_mode, salary FROM users WHERE id=3")
print("恢复后 user3:", cur.fetchone())
conn.close()

BASE = 'http://127.0.0.1:8000'
def login(phone):
    return requests.post(BASE+'/api/v1/auth/login', json={'phone':phone,'password':'pass12345'}, timeout=10).json().get('access_token')
tok_d = login('13800000001')
tok_s = login('13800000002')
tok_drv = login('13800000003')
H_D = {'Authorization': f'Bearer {tok_d}'}
H_S = {'Authorization': f'Bearer {tok_s}'}
H_DRV = {'Authorization': f'Bearer {tok_drv}'}

# 2. 造一个ACCEPTED订单给司机3（用于真实验证上传）
r = requests.post(BASE+'/api/v1/orders', headers=H_S, json={'lines': [{'product_id': 1, 'product_name_snapshot': '上传测试商品', 'quantity': 1, 'unit_price': '12.00'}], 'address_detail': '上传测试地址', 'contact_boss_phone': '13800000001'}, timeout=10)
oid = r.json()['id']
print('ACCEPTED测试单:', oid)
requests.post(BASE+f'/api/v1/orders/{oid}/assign', headers=H_D, json={'driver_id': 3, 'freight_fee': '5.00'}, timeout=10)
r = requests.post(BASE+f'/api/v1/orders/{oid}/driver-ack', headers=H_DRV, timeout=10)
print('driver-ack:', r.status_code, r.json().get('status'))

# 3. 上传 MIME 校验（ACCEPTED状态）
fake = b"\x89PNG\r\n\x1a\n" + b"p" * 200
r = requests.post(BASE+f'/api/v1/orders/{oid}/delivery-photos', headers=H_DRV, files=[('files', ('ok.png', io.BytesIO(fake), 'image/png'))], timeout=10)
print('A 真png(内容假): ', r.status_code, r.text[:120])
r = requests.post(BASE+f'/api/v1/orders/{oid}/delivery-photos', headers=H_DRV, files=[('files', ('php.png', io.BytesIO(b'<?php system("id"); ?>'), 'image/png'))], timeout=10)
print('B 伪png+PHP内容: ', r.status_code, r.text[:120])
r = requests.post(BASE+f'/api/v1/orders/{oid}/delivery-photos', headers=H_DRV, files=[('files', ('x.php', io.BytesIO(b'<?php echo 1;'), 'application/x-php'))], timeout=10)
print('C php content-type: ', r.status_code, r.text[:120])
r = requests.post(BASE+f'/api/v1/orders/{oid}/delivery-photos', headers=H_DRV, files=[('files', ('x.svg', io.BytesIO(b'<svg onload=alert(1)>'), 'image/svg+xml'))], timeout=10)
print('D svg: ', r.status_code, r.text[:120])
r = requests.post(BASE+f'/api/v1/orders/{oid}/delivery-photos', headers=H_DRV, files=[('files', ('x.txt', io.BytesIO(b'hello'), 'text/plain'))], timeout=10)
print('E txt: ', r.status_code, r.text[:120])
r = requests.post(BASE+f'/api/v1/orders/{oid}/delivery-photos', headers=H_DRV, files=[('files', ('../evil.png', io.BytesIO(fake), 'image/png'))], timeout=10)
print('F 路径穿越名: ', r.status_code, r.text[:150])