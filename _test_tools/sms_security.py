# -*- coding: utf-8 -*-
"""SMS验证码安全: 暴力/回显/弱密码/bcrypt"""
import sys, time
sys.stdout.reconfigure(encoding='utf-8')
import requests

BASE = 'http://127.0.0.1:8000'

# 1. SMS 连续发送（是否有频率限制）
codes = []
for i in range(5):
    r = requests.post(BASE + "/api/v1/auth/sms/send", json={"phone": "13800000001"}, timeout=10)
    j = r.json()
    codes.append(j.get("code"))
    time.sleep(0.3)
print("连续5次SMS code:", codes)

# 2. 错误code注册
r = requests.post(BASE + "/api/v1/auth/register", json={"phone": "13955550001", "username": "sms_test", "password": "pass12345", "full_name": "SMS测试", "verification_code": "000000"}, timeout=10)
print("错误code注册:", r.status_code, r.text[:150])

# 3. 无code注册
r = requests.post(BASE + "/api/v1/auth/register", json={"phone": "13955550002", "username": "sms_test2", "password": "pass12345"}, timeout=10)
print("无code注册:", r.status_code, r.text[:150])

# 4. 弱密码注册
r = requests.post(BASE + "/api/v1/auth/register", json={"phone": "13955550003", "username": "sms_test3", "password": "123", "full_name": "X", "verification_code": "123456"}, timeout=10)
print("弱密码注册:", r.status_code, r.text[:150])

# 5. bcrypt hash 检查
import sqlite3
conn = sqlite3.connect("D:/AProjects/ASDH/orders/backend/sorders.db")
cur = conn.cursor()
cur.execute("SELECT password_hash FROM users WHERE id=1")
h = cur.fetchone()[0]
print("密码hash类型:", h[:7], "| bcrypt:", h.startswith("$2"))
conn.close()