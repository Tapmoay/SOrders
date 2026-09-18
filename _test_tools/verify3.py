import sys
sys.stdout.reconfigure(encoding='utf-8')
import sqlite3, requests, io

conn = sqlite3.connect("D:/AProjects/ASDH/orders/backend/sorders.db")
cur = conn.cursor()
cur.execute("SELECT id, role, salary, billing_mode, vehicle_type, full_name FROM users WHERE id=3")
print("DB user3:", cur.fetchone())
conn.close()

# 用司机3自己的已送达订单37测上传（37 driver_id=3）
BASE = 'http://127.0.0.1:8000'
tok = requests.post(BASE+'/api/v1/auth/login', json={'phone':'13800000003','password':'pass12345'}, timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {tok}'}
fake = b"\x89PNG\r\n\x1a\n" + b"p" * 100
r = requests.post(BASE+'/api/v1/orders/37/delivery-photos', headers=H, files=[('files', ('ok.png', io.BytesIO(fake), 'image/png'))], timeout=10)
print('司机上传自己订单37 伪png: ', r.status_code, r.text[:150])
r = requests.post(BASE+'/api/v1/orders/37/delivery-photos', headers=H, files=[('files', ('evil.php', io.BytesIO(fake), 'application/x-php'))], timeout=10)
print('司机上传自己订单37 php类型: ', r.status_code, r.text[:150])
r = requests.post(BASE+'/api/v1/orders/37/delivery-photos', headers=H, files=[('files', ('x.svg', io.BytesIO(b'<svg onload=alert(1)>'), 'image/svg+xml'))], timeout=10)
print('司机上传自己订单37 svg: ', r.status_code, r.text[:150])