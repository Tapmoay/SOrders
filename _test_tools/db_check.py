
import sys
sys.stdout.reconfigure(encoding='utf-8')
import sqlite3
conn = sqlite3.connect('D:/AProjects/ASDH/orders/backend/sorders.db')
cur = conn.cursor()
cur.execute("PRAGMA table_info(users)")
cols = cur.fetchall()
print("USERS COLUMNS:", [(c[1], c[2]) for c in cols])
cur.execute("SELECT id, phone, username, role, is_member, billing_mode, salary, created_at FROM users ORDER BY id DESC LIMIT 8")
for row in cur.fetchall():
    print(row)
conn.close()
