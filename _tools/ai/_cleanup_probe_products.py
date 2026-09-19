"""看一眼刚建出来的商品，并把本次验证造出来的那 3 条清掉（只动 SQLite 开发库）。

用法：python _tools/ai/_cleanup_probe_products.py [--keep]
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

DB = repo_root() / "backend" / "sorders.db"
if DB.read_bytes()[:16] != b"SQLite format 3\x00":
    raise SystemExit("拒绝执行：目标不是 SQLite 开发库")

con = sqlite3.connect(DB)
cur = con.cursor()
rows = cur.execute(
    "select id, name, unit, default_unit_price, stock, low_stock_alert, created_at "
    "from products order by id desc limit 6"
).fetchall()
print("最近的商品：")
for r in rows:
    print("  ", r)

if "--keep" in sys.argv:
    print("（--keep：不删）")
    raise SystemExit(0)

# 只删"名字在名单里、且 id 是最大那几条"的（= 刚建出来的重复品），别的行一概不动
names = ("红富士苹果", "海南香蕉", "农夫山泉")
victims = [r[0] for r in rows[:3] if r[1] in names]
if len(victims) != 3:
    print(f"没找到预期的 3 条新商品（找到 {victims}），不做删除")
    raise SystemExit(1)
cur.execute(f"delete from products where id in ({','.join('?' * len(victims))})", victims)
con.commit()
print(f"已删除验证造出来的 {len(victims)} 条商品：{victims}")
