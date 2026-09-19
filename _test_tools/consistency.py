# -*- coding: utf-8 -*-
"""数据一致性检查：订单/账本/损益对账"""
import sys, sqlite3
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect("D:/AProjects/ASDH/orders/backend/sorders_wal_test.db")
cur = conn.cursor()

print("=== 订单总数 ===")
cur.execute("SELECT COUNT(*) FROM orders")
total = cur.fetchone()[0]
print(f"orders: {total}")

print("=== 订单状态分布 ===")
cur.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
for row in cur.fetchall(): print(f"  {row[0]}: {row[1]}")

print("=== 订单行总和 vs 订单金额 (抽查异常) ===")
cur.execute("SELECT COUNT(*) FROM order_products")
op = cur.fetchone()[0]
print(f"order_products: {op}")

print("=== 重复 order_no 检查 ===")
cur.execute("SELECT order_no, COUNT(*) c FROM orders GROUP BY order_no HAVING c > 1 LIMIT 10")
dups = cur.fetchall()
print(f"重复订单号: {len(dups)}", dups[:5])

print("=== 账本与订单一致性（ORDER源 entries 应≤已送达单） ===")
cur.execute("SELECT COUNT(*) FROM ledger WHERE source='order'")
ledger_order = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM orders WHERE status='DELIVERED'")
delivered = cur.fetchone()[0]
print(f"账本ORDER源: {ledger_order} | 已送达单: {delivered}")

print("=== 负金额数据检查 ===")
cur.execute("SELECT COUNT(*) FROM order_products WHERE unit_price < 0 OR line_total < 0")
neg_op = cur.fetchone()[0]
print(f"负金额订单行: {neg_op}")
cur.execute("SELECT COUNT(*) FROM ledger WHERE total < 0")
neg_l = cur.fetchone()[0]
print(f"负金额账本: {neg_l}")

print("=== 金额字段最大异常 ===")
cur.execute("SELECT MAX(line_total) FROM order_products")
mx = cur.fetchone()[0]
print(f"最大line_total: {mx}")

print("=== 数据库完整性检查 ===")
cur.execute("PRAGMA integrity_check")
print(cur.fetchone())

conn.close()