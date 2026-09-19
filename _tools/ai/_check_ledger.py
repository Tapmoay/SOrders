"""看一条账本流水 + 它关联订单的商品行（验证"改账本会回写订单"这条警告是否属实）。

用法：python _tools/ai/_check_ledger.py 373
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

DB = repo_root() / "backend/sorders.db"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python _tools/ai/_check_ledger.py <ledger_id>")
        return 2
    lid = int(sys.argv[1])
    c = sqlite3.connect(DB)
    row = list(c.execute("SELECT id,entry_date,product_name,total,source,note,order_id FROM ledgers WHERE id=?", (lid,)))
    print("账本行:", row)
    if not row or row[0][6] is None:
        print("（这行不来自订单，没有回写对象）")
        return 0
    oid = row[0][6]
    print("关联订单:", list(c.execute("SELECT id,order_no,status FROM orders WHERE id=?", (oid,))))
    print("订单商品行:", list(c.execute(
        "SELECT id,product_name_snapshot,quantity,unit_price,line_total FROM order_products WHERE order_id=?", (oid,))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
