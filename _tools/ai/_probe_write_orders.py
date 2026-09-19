"""E2E 侦察：找出可用于验证「派单」动作的真实数据。只读，不改任何东西。"""
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else "sorders.db"
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

print("=== 待派单（PENDING_DISPATCH）订单 ===")
rows = c.execute(
    "SELECT id, order_no, status, shipper_id, temp_shipper_name, address_detail, driver_id "
    "FROM orders WHERE status='PENDING_DISPATCH' ORDER BY id DESC LIMIT 8"
).fetchall()
for r in rows:
    print(dict(r))
if not rows:
    print("(没有待派单的订单)")

print()
print("=== 派单中（DISPATCHED）订单（用于测撤回）===")
for r in c.execute(
    "SELECT id, order_no, status, driver_id FROM orders WHERE status='DISPATCHED' ORDER BY id DESC LIMIT 5"
):
    print(dict(r))

print()
print("=== 司机 ===")
# ⚠️ 这里必须用大写：`users.role` 是 SQLAlchemy 的 `Enum(UserRole)`，
# 它把**枚举名**（DRIVER）存进库，而 API 返回的是**枚举值**（driver）。
# 直接读库时按 'driver' 过滤会一条都查不到——这不是 bug，是两种表示法的区别。
for r in c.execute(
    "SELECT id, username, full_name, role, is_active FROM users WHERE role='DRIVER' ORDER BY id LIMIT 10"
):
    print(dict(r))

print()
print("=== 挂账单位 ===")
for r in c.execute("SELECT id, name FROM arrears_units LIMIT 6"):
    print(dict(r))

print()
print("=== 商品（前 6）===")
for r in c.execute("SELECT id, name FROM products LIMIT 6"):
    print(dict(r))

print()
print("=== 各状态订单计数 ===")
for r in c.execute("SELECT status, COUNT(*) AS n FROM orders GROUP BY status"):
    print(dict(r))
