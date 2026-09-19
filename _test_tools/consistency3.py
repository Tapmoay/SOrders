# -*- coding: utf-8 -*-
"""主库账本一致性 + 负金额明细"""
import sys, sqlite3
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect("D:/AProjects/ASDH/orders/backend/sorders.db")
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM ledgers WHERE source='order'")
lo = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM orders WHERE status='DELIVERED'")
dv = cur.fetchone()[0]
print(f"账本ORDER源: {lo} | 已送达单: {dv} | 差: {dv - lo}")

print("=== 负金额明细 ===")
cur.execute("SELECT id, order_id, product_name_snapshot, quantity, unit_price, line_total FROM order_products WHERE unit_price < 0 OR line_total < 0")
for row in cur.fetchall(): print(" ", row)

print("=== ledgers 表结构 ===")
cur.execute("PRAGMA table_info(ledgers)")
print([c[1] for c in cur.fetchall()])
conn.close()