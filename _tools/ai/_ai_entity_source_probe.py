import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402
"""核对：客户名到底该从哪张表解析？只读，不打印电话/地址。"""
import sqlite3
from pathlib import Path

DB = repo_root() / "backend" / "sorders.db"


def main() -> None:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    print("=== users.role 的真实取值 ===")
    for r in cur.execute("SELECT DISTINCT role FROM users ORDER BY role"):
        print(f"   {r[0]!r}")

    print("\n=== 派单员 ===")
    for r in cur.execute(
        "SELECT id, full_name FROM users WHERE role IN ('dispatcher','DISPATCHER') LIMIT 10"
    ):
        print(f"   id={r[0]:<4} {r[1]}")

    print("\n=== shipper_contacts 全量（id, owner, display_name）===")
    for r in cur.execute("SELECT id, shipper_id, display_name FROM shipper_contacts ORDER BY id LIMIT 25"):
        print(f"   id={r[0]:<4} owner={r[1]:<4} display={r[2]!r}")

    print("\n=== 订单里的客户标识 ===")
    print("   temp_shipper_name 分布（前 12）:")
    for r in cur.execute(
        "SELECT temp_shipper_name, COUNT(*) FROM orders "
        "WHERE temp_shipper_name IS NOT NULL AND temp_shipper_name<>'' "
        "GROUP BY temp_shipper_name ORDER BY COUNT(*) DESC LIMIT 12"
    ):
        print(f"      {str(r[0]):<18} x{r[1]}")
    r = cur.execute(
        "SELECT SUM(CASE WHEN shipper_id IS NULL THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN temp_shipper_name IS NOT NULL AND temp_shipper_name<>'' THEN 1 ELSE 0 END), "
        "COUNT(*) FROM orders"
    ).fetchone()
    print(f"   shipper_id 为空 {r[0]} / 有临时名 {r[1]} / 总 {r[2]}")

    print("\n=== 订单上的联系人字段是否可当实体名用 ===")
    r = cur.execute(
        "SELECT SUM(CASE WHEN contact_boss_phone IS NOT NULL AND contact_boss_phone<>'' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN delivery_description IS NOT NULL AND delivery_description<>'' THEN 1 ELSE 0 END), "
        "COUNT(*) FROM orders"
    ).fetchone()
    print(f"   有老板电话 {r[0]} / 有送货说明 {r[1]} / 总 {r[2]}")

    print("\n=== 商品名能否直接匹配 ===")
    for r in cur.execute("SELECT id, name FROM products ORDER BY id LIMIT 12"):
        print(f"   id={r[0]:<4} {r[1]}")

    con.close()


if __name__ == "__main__":
    main()
