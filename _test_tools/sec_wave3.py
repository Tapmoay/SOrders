# -*- coding: utf-8 -*-
"""安全测试第三波：精确对象级越权 + 极端输入验证"""
import sys, json, io
sys.stdout.reconfigure(encoding='utf-8')
import requests, warnings
warnings.filterwarnings('ignore')

BASE = 'http://127.0.0.1:8000'
results = []
def log(name, status, detail=''):
    results.append(f"[{status}] {name} {detail[:200]}")

def login(phone):
    return requests.post(BASE+'/api/v1/auth/login', json={'phone':phone,'password':'pass12345'}, timeout=10).json().get('access_token')

tok_d = login('13800000001')  # 派单员 id=1
tok_s2 = login('13800000002')  # 货主 id=2
tok_s3 = login('13910000003')  # 测试货主 id=? (test_shipper_003)
H_D = {'Authorization': f'Bearer {tok_d}'}
H_S2 = {'Authorization': f'Bearer {tok_s2}'}
H_S3 = {'Authorization': f'Bearer {tok_s3}'}

# ===== 1. 精确越权：货主2读货主3的订单（货主3先行下单） =====
# 先用货主3（如果是新用户直接下单）
def create_order(headers, shipper_id=None):
    body = {'lines': [{'product_id': 1, 'quantity': 1}], 'address_detail': '越权测试地址', 'contact_boss_phone': '13900000001'}
    if shipper_id: body['shipper_id'] = shipper_id
    return requests.post(BASE+'/api/v1/orders', headers=headers, json=body, timeout=10)

r3 = create_order(H_S3)
log('1a 货主3下单', r3.status_code, r3.text[:120])
oid3 = None
if r3.status_code == 201:
    oid3 = r3.json().get('id')
    log('1a2 货主3订单id', oid3)
    # 货主2读取货主3订单详情
    r = requests.get(BASE+f'/api/v1/orders/{oid3}', headers=H_S2, timeout=10)
    log('1b 货主2读货主3订单 应403', r.status_code, r.text[:100])
    # 货主2取消货主3订单
    r = requests.post(BASE+f'/api/v1/orders/{oid3}/cancel', headers=H_S2, timeout=10)
    log('1c 货主2撤销货主3订单 应403/400', r.status_code, r.text[:100])
    # 货主2用shipper_id=3的id直接下单（伪造归属）
    r = create_order(H_S2, shipper_id=3)
    log('1d 货主2伪造shipper_id=3下单', r.status_code, r.text[:150])

# ===== 2. 派单员给货主3的单改运费、assign等正常 =====
# ===== 3. 极端输入：拆分 0/0 =====
if oid3:
    r = requests.post(BASE+f'/api/v1/orders/{oid3}/split', headers=H_D, json={'splits': [{'quantity': 0}, {'quantity': 0}]}, timeout=10)
    log('2a split 0,0', r.status_code, r.text[:150])
    r = requests.post(BASE+f'/api/v1/orders/{oid3}/split', headers=H_D, json={'splits': [{'quantity': 1}, {'quantity': -1}]}, timeout=10)
    log('2b split 1,-1', r.status_code, r.text[:150])
    r = requests.post(BASE+f'/api/v1/orders/{oid3}/split', headers=H_D, json={'splits': [{'quantity': 999999999}]}, timeout=10)
    log('2c split 999999999', r.status_code, r.text[:150])

# ===== 4. 金额边界：负数/零/极大 =====
# 货主2下单 单价-1
r = requests.post(BASE+'/api/v1/orders', headers=H_S2, json={'lines': [{'product_id': 1, 'quantity': 1, 'unit_price': '-1.00'}], 'address_detail': '负价测试'}, timeout=10)
log('3a 下单负数单价-1', r.status_code, r.text[:150])
r = requests.post(BASE+'/api/v1/orders', headers=H_S2, json={'lines': [{'product_id': 1, 'quantity': 0}], 'address_detail': '零数量测试'}, timeout=10)
log('3b 下单数量0', r.status_code, r.text[:150])
r = requests.post(BASE+'/api/v1/orders', headers=H_S2, json={'lines': [{'product_id': 1, 'quantity': 9999999}], 'address_detail': '巨量测试'}, timeout=10)
log('3c 下单数量9999999', r.status_code, r.text[:150])
r = requests.post(BASE+'/api/v1/orders', headers=H_S2, json={'lines': [{'product_id': 1, 'quantity': 1, 'unit_price': '9999999999.99'}], 'address_detail': '巨价测试'}, timeout=10)
log('3d 下单巨价', r.status_code, r.text[:150])

# ===== 5. 超长字段 =====
r = requests.post(BASE+'/api/v1/orders', headers=H_S2, json={'lines': [{'product_id': 1, 'quantity': 1}], 'address_detail': 'A'*100000}, timeout=10)
log('4a 地址10万字符', r.status_code, r.text[:150])

print('\n'.join(results))