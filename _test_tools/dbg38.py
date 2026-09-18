# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests
BASE = 'http://127.0.0.1:8000'
def login(phone):
    return requests.post(BASE+'/api/v1/auth/login', json={'phone':phone,'password':'pass12345'}, timeout=10).json().get('access_token')
H_D = {'Authorization': f'Bearer {login("13800000001")}'}
H_DRV = {'Authorization': f'Bearer {login("13800000003")}'}
# 打印订单38当前状态
r = requests.get(BASE+'/api/v1/orders/38', headers=H_D, timeout=10)
print('订单38:', r.status_code, r.text[:400])
# 重新 assign（幂等？）
r = requests.post(BASE+'/api/v1/orders/38/assign', headers=H_D, json={'driver_id': 3, 'freight_fee': '5.00'}, timeout=10)
print('assign:', r.status_code, r.text[:300])
r2 = requests.post(BASE+'/api/v1/orders/38/driver-ack', headers=H_DRV, timeout=10)
print('ack:', r2.status_code, r2.text[:300])