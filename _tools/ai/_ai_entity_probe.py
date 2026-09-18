import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402
"""从本地 sorders.db 抽取真实实体名（只读），用于构造 P0 的"自然语言→实体"歧义测试集。
只打印名称与计数，不打印电话/地址等个人信息。
"""
import sqlite3
from pathlib import Path

DB = repo_root() / "backend" / "sorders.db"


def main() -> None:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    print("=== shipper_contacts 列 ===")
    print([r[1] for r in cur.execute("PRAGMA table_info(shipper_contacts)")])

    print("\n=== 联系人姓名（最多 40，看是否有同姓/同名歧义）===")
    for r in cur.execute(
        "SELECT name, COUNT(*) FROM shipper_contacts WHERE name IS NOT NULL AND name<>'' "
        "GROUP BY name ORDER BY COUNT(*) DESC, name LIMIT 40"
    ):
        print(f"   {r[0]:<12} x{r[1]}")

    print("\n=== 商品名（全部）===")
    for r in cur.execute(
        "SELECT id, name, stock FROM products ORDER BY id"
    ):
        print(f"   id={r[0]:<4} {r[1]:<30} stock={r[2]}")

    print("\n=== 司机（role=driver，最多 20，含姓名与车型）===")
    cols = [r[1] for r in cur.execute("PRAGMA table_info(users)")]
    print("   users 列:", ",".join(cols))
    for r in cur.execute(
        "SELECT id, full_name, phone, vehicle_type, billing_mode FROM users "
        "WHERE role='driver' ORDER BY id LIMIT 20"
    ):
        phone = str(r[2] or "")
        masked = phone[:3] + "****" + phone[-2:] if len(phone) >= 6 else "***"
        print(f"   id={r[0]:<4} {str(r[1]):<10} {masked}  车型={r[3]} 计费={r[4]}")

    print("\n=== 货主/批发商（前 15）===")
    for r in cur.execute(
        "SELECT id, full_name, is_member FROM users WHERE role='shipper' ORDER BY id LIMIT 15"
    ):
        print(f"   id={r[0]:<4} {str(r[1]):<12} member={r[2]}")

    print("\n=== 待派订单里出现的地址关键词（前 15，仅取前 12 字）===")
    for r in cur.execute(
        "SELECT address_detail, COUNT(*) FROM orders WHERE status='PENDING_DISPATCH' "
        "AND address_detail IS NOT NULL AND address_detail<>'' "
        "GROUP BY address_detail ORDER BY COUNT(*) DESC LIMIT 15"
    ):
        print(f"   {str(r[0])[:12]:<14} x{r[1]}")

    con.close()


if __name__ == "__main__":
    main()
