# -*- coding: utf-8 -*-
"""上传MIME真实验证（订单38 ACCEPTED）"""
import sys, io
sys.stdout.reconfigure(encoding='utf-8')
import requests
BASE = 'http://127.0.0.1:8000'
tok_d = requests.post(BASE+'/api/v1/auth/login', json={'phone':'13800000001','password':'pass12345'}, timeout=10).json()['access_token']
tok_drv = requests.post(BASE+'/api/v1/auth/login', json={'phone':'13800000003','password':'pass12345'}, timeout=10).json()['access_token']
H_D = {'Authorization': f'Bearer {tok_d}'}
H_DRV = {'Authorization': f'Bearer {tok_drv}'}
fake = b"\x89PNG\r\n\x1a\n" + b"p" * 200
# A 真png(内容假但mime对)
r = requests.post(BASE+'/api/v1/orders/38/delivery-photos', headers=H_DRV, files=[('files', ('ok.png', io.BytesIO(fake), 'image/png'))], timeout=10)
print('A png-head-fake: ', r.status_code, r.text[:150])
# B php内容png mime
r = requests.post(BASE+'/api/v1/orders/38/delivery-photos', headers=H_DRV, files=[('files', ('php.png', io.BytesIO(b'<?php system("id"); ?>' * 10), 'image/png'))], timeout=10)
print('B php-in-png: ', r.status_code, r.text[:150])
# C php mime
r = requests.post(BASE+'/api/v1/orders/38/delivery-photos', headers=H_DRV, files=[('files', ('x.php', io.BytesIO(b'<?php echo 1;'), 'application/x-php'))], timeout=10)
print('C php mime: ', r.status_code, r.text[:150])
# D svg
r = requests.post(BASE+'/api/v1/orders/38/delivery-photos', headers=H_DRV, files=[('files', ('x.svg', io.BytesIO(b'<svg onload=alert(1)>'), 'image/svg+xml'))], timeout=10)
print('D svg: ', r.status_code, r.text[:150])
# E txt
r = requests.post(BASE+'/api/v1/orders/38/delivery-photos', headers=H_DRV, files=[('files', ('x.txt', io.BytesIO(b'hello'), 'text/plain'))], timeout=10)
print('E txt: ', r.status_code, r.text[:150])
# F 路径穿越
r = requests.post(BASE+'/api/v1/orders/38/delivery-photos', headers=H_DRV, files=[('files', ('..\\..\\evil.png', io.BytesIO(fake), 'image/png'))], timeout=10)
print('F traversal name: ', r.status_code, r.text[:150])
# G 超大文件(10MB)
r = requests.post(BASE+'/api/v1/orders/38/delivery-photos', headers=H_DRV, files=[('files', ('big.png', io.BytesIO(b'\x89PNG' + b'0' * (10 * 1024 * 1024)), 'image/png'))], timeout=30)
print('G 10MB: ', r.status_code, r.text[:150])
# 查看是否真正保存了
import glob
files = sorted(glob.glob('D:/AProjects/ASDH/orders/backend/uploads/delivery/38/*'))
print('saved files:', files)