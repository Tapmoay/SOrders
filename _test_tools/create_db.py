# -*- coding: utf-8 -*-
"""创建独立MySQL测试库 sorders_test"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pymysql
conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="", connect_timeout=3)
cur = conn.cursor()
cur.execute("CREATE DATABASE IF NOT EXISTS sorders_test CHARACTER SET utf8mb4")
cur.execute("SHOW DATABASES")
print([r[0] for r in cur.fetchall()])
conn.commit(); conn.close()
print("OK: sorders_test created")