# -*- coding: utf-8 -*-
"""探测本地MySQL连接（只读探测+创建测试库）"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pymysql

candidates = [
    dict(host="127.0.0.1", port=3306, user="root", password="root"),
    dict(host="127.0.0.1", port=3306, user="root", password="password"),
    dict(host="127.0.0.1", port=3306, user="root", password="123456"),
    dict(host="127.0.0.1", port=3306, user="root", password=""),
    dict(host="127.0.0.1", port=3306, user="sorders", password="sorders"),
]
for cfg in candidates:
    try:
        conn = pymysql.connect(**cfg, connect_timeout=3)
        cur = conn.cursor()
        cur.execute("SELECT VERSION()")
        ver = cur.fetchone()[0]
        print(f"CONNECT OK: {cfg['user']}@{cfg['host']} mysql={ver}")
        # 列出已有库（只读）
        cur.execute("SHOW DATABASES")
        dbs = [r[0] for r in cur.fetchall()]
        print("DATABASES:", dbs)
        conn.close()
        break
    except Exception as e:
        print(f"FAIL {cfg} : {str(e)[:100]}")