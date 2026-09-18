
import sys, traceback
sys.stdout.reconfigure(encoding='utf-8')
# 先登录拿 token
import requests
BASE = 'http://127.0.0.1:8000'
tok = requests.post(BASE + '/api/v1/auth/login', json={'phone':'13800000001','password':'pass12345'}, timeout=10).json()['access_token']
print('token ok', tok[:16])

# 用 TestClient 复现（与线上同一 app 逻辑，但捕获 traceback）
from fastapi.testclient import TestClient
from app.main import create_fastapi_app
app = create_fastapi_app()
client = TestClient(app)
import time
phone = f'1398{int(time.time())%1000000:06d}'
r = client.post('/api/v1/users', headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'}, json={
    'phone': phone, 'username': f'tc_{phone[-5:]}', 'password': 'pass12345',
    'full_name': 'TC复现', 'role': 'shipper'
})
print('TestClient status:', r.status_code)
print('body:', r.text[:500])
