# -*- coding: utf-8 -*-
"""主库完整性与一致性检查"""
import sys, sqlite3
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect("D:/AProjects/ASDH/orders/backend/sorders.db")
cur = conn.cursor()

print("=== 表清单 ===")
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print(tables)

print("=== PRAGMA integrity_check ===")
cur.execute("PRAGMA integrity_check")
print(cur.fetchone())

print("=== 订单/商品/用户计数 ===")
for t in ["orders", "order_products", "products", "users", "ledger", "cash_flows", "notifications", "operation_logs"]:
    if t in tables:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]}")

print("=== 重复 order_no ===")
if "orders" in tables:
    cur.execute("SELECT order_no, COUNT(*) c FROM orders GROUP BY order_no HAVING c > 1 LIMIT 5")
    print(cur.fetchall())

print("=== 负金额检查 ===")
if "order_products" in tables:
    cur.execute("SELECT COUNT(*) FROM order_products WHERE unit_price < 0 OR line_total < 0")
    print(f"负金额行: {cur.fetchone()[0]}")

print("=== 账本ORDER源 vs 已送达单 ===")
if "ledger" in tables and "orders" in tables:
    cur.execute("SELECT COUNT(*) FROM ledger WHERE source='order'")
    lo = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM orders WHERE status='DELIVERED'")
    dv = cur.fetchone()[0]
    print(f"账本ORDER源: {lo} | 已送达: {dv} | 差: {dv - lo}")

conn.close()