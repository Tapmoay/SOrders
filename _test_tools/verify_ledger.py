# -*- coding: utf-8 -*-
"""验证账本同步BUG: 送达订单为何不入账本"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests

BASE = 'http://127.0.0.1:8000'
tok = requests.post(BASE+'/api/v1/auth/login', json={'phone':'13800000001','password':'pass12345'}, timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {tok}'}

# 1. 查看已送达订单
r = requests.get(BASE + "/api/v1/orders?status=DELIVERED", headers=H, timeout=10)
orders = r.json()
print(f"已送达订单数: {len(orders)}")

# 2. 查看账本（派单员视角）
r2 = requests.get(BASE + "/api/v1/ledger/entries?shipper_id=2&from=2026-08-01&to=2026-09-30", headers=H, timeout=10)
entries = r2.json() if isinstance(r2.json(), list) else r2.json()
print(f"账本条目数: {len(entries)}")
for e in entries[:5]:
    print(e)

# 3. 手动触发账本同步
r3 = requests.post(BASE + "/api/v1/ledger/sync-from-delivered-orders", headers=H, timeout=15)
print(f"手动同步: {r3.status_code} {r3.text[:200]}")

# 4. 同步后再查账本
r4 = requests.get(BASE + "/api/v1/ledger/entries?shipper_id=2&from=2026-08-01&to=2026-09-30", headers=H, timeout=10)
entries2 = r4.json()
print(f"同步后账本条目数: {len(entries2)}")

# 5. 完整账本（应只含真实业务）
r5 = requests.get(BASE + "/api/v1/ledger/entries", headers=H, timeout=10)
entries5 = r5.json()
print(f"全部账本: {len(entries5)}")