import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402
"""只读探查本地 SQLite 库，判断能否拿真实数据做 AI 工具选型的 P0 验证。不写任何数据。"""
import sqlite3
import sys
from pathlib import Path

TABLES = [
    "orders", "order_products", "users", "ledgers", "products",
    "shipper_contacts", "shipper_addresses", "shipper_locations",
    "customers", "vehicles", "arrears_units", "price_rules",
]

def main() -> int:
    root = repo_root() / "backend"
    for db in ["sorders.db", "sorders_wal_test.db", "app.db"]:
        p = root / db
        if not p.exists():
            print(f"== {db}: 不存在")
            continue
        try:
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            cur = con.cursor()
            names = [r[0] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )]
            print(f"== {db}  表数={len(names)}  大小={p.stat().st_size}")
            for t in TABLES:
                if t not in names:
                    continue
                try:
                    n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    print(f"   {t:22} {n:>8}")
                except Exception as e:  # noqa: BLE001
                    print(f"   {t:22} ERR {e}")
            # 抽样看看订单长什么样（不含个人信息）
            if "orders" in names:
                cols = [r[1] for r in cur.execute("PRAGMA table_info(orders)")]
                print("   orders 列:", ",".join(cols))
                row = cur.execute(
                    "SELECT status, COUNT(*) FROM orders GROUP BY status"
                ).fetchall()
                print("   状态分布:", row)
            con.close()
        except Exception as e:  # noqa: BLE001
            print(f"== {db}: 打开失败 {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
