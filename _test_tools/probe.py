
# -*- coding: utf-8 -*-
"""SOrders 压测/探索 辅助脚本"""
import sys, json, time
sys.stdout.reconfigure(encoding='utf-8')
import requests

BASE = 'http://127.0.0.1:8000'

def login(phone, pw='pass12345'):
    r = requests.post(BASE + '/api/v1/auth/login', json={'phone': phone, 'password': pw}, timeout=5)
    return r.json()

if __name__ == '__main__':
    tok = login('13800000001')
    print('LOGIN_DISPATCHER:', 'OK' if tok.get('access_token') else tok)
    h = {'Authorization': f"Bearer {tok['access_token']}"}
    r = requests.get(BASE + '/api/v1/users?limit=500', headers=h, timeout=5)
    print('USERS status:', r.status_code)
    users = r.json()
    if isinstance(users, list):
        print('COUNT:', len(users))
        for u in users[:40]:
            print(u.get('id'), '|', u.get('phone'), '|', u.get('name'), '|', u.get('role'), '| member:', u.get('is_member'), '| billing:', u.get('billing_mode'))
    else:
        print(users)
