# -*- coding: utf-8 -*-
"""安全测试第三波：精确对象级越权 + 极端输入验证 (修复payload)"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests, warnings
warnings.filterwarnings('ignore')

BASE = 'http://127.0.0.1:8000'
results = []
def log(name, status, detail=''):
    results.append(f"[{status}] {name} {detail[:200]}")

def login(phone):
    return requests.post(BASE+'/api/v1/auth/login', json={'phone':phone,'password':'pass12345'}, timeout=10).json().get('access_token')

tok_d = login('13800000001')
tok_s2 = login('13800000002')
tok_s3 = login('13910000003')
H_D = {'Authorization': f'Bearer {tok_d}'}
H_S2 = {'Authorization': f'Bearer {tok_s2}'}
H_S3 = {'Authorization': f'Bearer {tok_s3}'}

def create_order(headers, lines, **kw):
    body = {'lines': lines, 'address_detail': '越权测试地址', 'contact_boss_phone': '13900000001'}
    body.update(kw)
    return requests.post(BASE+'/api/v1/orders', headers=headers, json=body, timeout=10)

prod = lambda pid, qty, price='10.00', name='测试商品': {'product_id': pid, 'product_name_snapshot': name, 'quantity': qty, 'unit_price': price}

# ===== 1. 货主3下单 =====
r3 = create_order(H_S3, [prod(1, 2)])
log('1a 货主3下单', r3.status_code)
oid3 = r3.json().get('id') if r3.status_code == 201 else None
if oid3:
    print('货主3订单id:', oid3)
    r = requests.get(BASE+f'/api/v1/orders/{oid3}', headers=H_S2, timeout=10)
    log('1b 货主2读货主3订单 应403', r.status_code, r.text[:100])
    r = requests.post(BASE+f'/api/v1/orders/{oid3}/cancel', headers=H_S2, timeout=10)
    log('1c 货主2撤销货主3订单', r.status_code, r.text[:100])
    r = create_order(H_S2, [prod(1, 1)], shipper_id=3)
    log('1d 货主2伪造shipper_id=3下单', r.status_code, r.text[:150])
else:
    print('1a fail:', r3.text[:200])

# ===== 2. 拆分极端值（需要先派单/已接单？看接口前置条件） =====
# 用已有DELIVERED订单24试split（应被拒）— 前提是接口允许
# 新建一个订单并立刻尝试拆分
r = create_order(H_S3, [prod(1, 5)])
if r.status_code == 201:
    oid = r.json()['id']
    print('新订单id for split:', oid)
    r = requests.post(BASE+f'/api/v1/orders/{oid}/split', headers=H_D, json={'splits': [0, 0]}, timeout=10)
    log('2a split [0,0] 期望422', r.status_code, r.text[:150])
    r = requests.post(BASE+f'/api/v1/orders/{oid}/split', headers=H_D, json={'splits': [1, -1]}, timeout=10)
    log('2b split [1,-1] 期望422', r.status_code, r.text[:150])
    r = requests.post(BASE+f'/api/v1/orders/{oid}/split', headers=H_D, json={'splits': [2, 3]}, timeout=10)
    log('2c split [2,3] 正常', r.status_code, r.text[:150])

# ===== 3. 金额边界 =====
# 负单价（schema unit_price 无 ge=0）
r = create_order(H_S2, [prod(1, 1, price='-1.00')])
log('3a 负数单价-1', r.status_code, r.text[:150])
# 负总价 line_total
r = create_order(H_S2, [{'product_id': 1, 'product_name_snapshot': 'X', 'quantity': 1, 'unit_price': '10.00', 'line_total': '-5.00'}])
log('3b 负数line_total', r.status_code, r.text[:150])
# 零价
r = create_order(H_S2, [prod(1, 1, price='0.00')])
log('3c 零单价', r.status_code)
# 极大价
r = create_order(H_S2, [prod(1, 1, price='999999999999.99')])
log('3d 极大单价', r.status_code, r.text[:100])

print("\n".join(results))