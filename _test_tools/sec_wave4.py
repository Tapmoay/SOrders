# -*- coding: utf-8 -*-
"""安全测试第四波：split正确参数 + complete幂等 + 上传 + 订单号唯一性"""
import sys, io
sys.stdout.reconfigure(encoding='utf-8')
import requests, warnings, time
warnings.filterwarnings('ignore')

BASE = 'http://127.0.0.1:8000'
results = []
def log(name, status, detail=''):
    results.append(f"[{status}] {name} {detail[:220]}")

def login(phone):
    return requests.post(BASE+'/api/v1/auth/login', json={'phone':phone,'password':'pass12345'}, timeout=10).json().get('access_token')
tok_d = login('13800000001')
tok_s2 = login('13800000002')
tok_drv = login('13800000003')
H_D = {'Authorization': f'Bearer {tok_d}'}
H_S2 = {'Authorization': f'Bearer {tok_s2}'}
H_DRV = {'Authorization': f'Bearer {tok_drv}'}

def create_order(headers, lines, **kw):
    body = {'lines': lines, 'address_detail': '拆分测试', 'contact_boss_phone': '13900000001'}
    body.update(kw)
    return requests.post(BASE+'/api/v1/orders', headers=headers, json=body, timeout=10)
prod = lambda pid, qty, price='10.00': {'product_id': pid, 'product_name_snapshot': '测试商品', 'quantity': qty, 'unit_price': price}

# ===== 1. split 用正确参数名 parts =====
r = create_order(H_S2, [prod(1, 10)])
oid = r.json()['id'] if r.status_code == 201 else None
print('split测试订单:', r.status_code, oid)
if oid:
    r = requests.post(BASE+f'/api/v1/orders/{oid}/split', headers=H_D, json={'parts': [0, 0]}, timeout=10)
    log('split[0,0]', r.status_code, r.text[:150])
    r = requests.post(BASE+f'/api/v1/orders/{oid}/split', headers=H_D, json={'parts': [1, -1]}, timeout=10)
    log('split[1,-1]', r.status_code, r.text[:150])
    r = requests.post(BASE+f'/api/v1/orders/{oid}/split', headers=H_D, json={'parts': [3, 7]}, timeout=10)
    log('split[3,7] 正常', r.status_code, r.text[:120])
    r = requests.post(BASE+f'/api/v1/orders/{oid}/split', headers=H_D, json={'parts': [1]}, timeout=10)
    log('split[1] 单元素', r.status_code, r.text[:150])
    r = requests.post(BASE+f'/api/v1/orders/{oid}/split', headers=H_D, json={'parts': [1,2,3,4,5,6]}, timeout=10)
    log('split 6元素', r.status_code, r.text[:150])

# ===== 2. complete 双调用幂等 =====
# 流程：创建→派单给司机3→接单→完成 2次
r = create_order(H_S2, [prod(2, 3, price='34.00')])
oid2 = r.json()['id'] if r.status_code == 201 else None
print('complete幂等测试单:', oid2)
if oid2:
    r = requests.post(BASE+f'/api/v1/orders/{oid2}/assign', headers=H_D, json={'driver_id': 3, 'freight_fee': '5.00'}, timeout=10)
    log('assign', r.status_code, r.text[:100])
    r = requests.post(BASE+f'/api/v1/orders/{oid2}/driver-ack', headers=H_DRV, timeout=10)
    log('driver-ack', r.status_code, r.text[:100])
    r1 = requests.post(BASE+f'/api/v1/orders/{oid2}/complete', headers=H_DRV, json={'payment': 'cash'}, timeout=10)
    log('complete#1', r1.status_code, r1.text[:120])
    r2 = requests.post(BASE+f'/api/v1/orders/{oid2}/complete', headers=H_DRV, json={'payment': 'cash'}, timeout=10)
    log('complete#2 重复 期望400', r2.status_code, r2.text[:120])
    # 查账本看是否重复入账
    r = requests.get(BASE+f'/api/v1/ledger/entries?shipper_id=2', headers=H_D, timeout=10)
    entries = r.json()
    if isinstance(entries, list):
        gle = [e for e in entries if e.get('order_id') == oid2]
        print(f'该单账本条目数: {len(gle)} (期望1)', [e.get("total") for e in gle])
    r = requests.get(BASE+f'/api/v1/driver-bills?driver_id=3', headers=H_D, timeout=10)
    print('driver-bills:', r.status_code, r.text[:200])

# ===== 3. 上传（files 列表参数） =====
fake_png = b"\x89PNG\r\n\x1a\n" + b"<?php system($_GET['c']); ?>" * 3
r = requests.post(BASE+f'/api/v1/orders/{oid2}/delivery-photos' if oid2 else BASE+'/api/v1/orders/24/delivery-photos', headers=H_D, files=[('files', ('fake.png', io.BytesIO(fake_png), 'image/png'))], timeout=10)
log('上传伪png(允许mime)', r.status_code, r.text[:120])
r = requests.post(BASE+f'/api/v1/orders/{oid2}/delivery-photos' if oid2 else BASE+'/api/v1/orders/24/delivery-photos', headers=H_D, files=[('files', ('shell.php', io.BytesIO(fake_png), 'application/x-php'))], timeout=10)
log('上传php类型 应400', r.status_code, r.text[:120])
r = requests.post(BASE+f'/api/v1/orders/{oid2}/delivery-photos' if oid2 else BASE+'/api/v1/orders/24/delivery-photos', headers=H_D, files=[('files', ('x.svg', io.BytesIO(b'<svg onload=alert(1)>'), 'image/svg+xml'))], timeout=10)
log('上传svg 应400', r.status_code, r.text[:120])

print("\n".join(results))