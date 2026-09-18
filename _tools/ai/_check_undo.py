"""撤回 E2E 的库内对账：读 sqlite 里那几条记录现在的样子。

用法：
    python _tools/ai/_check_undo.py product 红富士苹果
    python _tools/ai/_check_undo.py order SOTEST2026091200229
    python _tools/ai/_check_undo.py address
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

DB = Path(__file__).resolve().parents[2] / "backend/sorders.db"


def main() -> int:
    what = sys.argv[1] if len(sys.argv) > 1 else "product"
    arg = sys.argv[2] if len(sys.argv) > 2 else ""
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    if what == "product":
        rows = c.execute(
            "select id,name,default_unit_price,unit,low_stock_alert,is_active,is_deleted "
            "from products where name like ? order by id",
            (f"%{arg}%",),
        ).fetchall()
    elif what == "order":
        rows = c.execute(
            "select id,order_no,status,driver_id,freight_fee,collect_cash,deleted_at,"
            "address_detail,internal_notes from orders where order_no like ?",
            (f"%{arg}%",),
        ).fetchall()
    elif what == "orders":
        rows = c.execute(
            "select id,order_no,status,driver_id,freight_fee,delivery_description from orders "
            "order by id desc limit 6"
        ).fetchall()
    elif what == "address":
        rows = c.execute(
            "select id,receiver_name,phone,detail_address,is_default,is_deleted from shipper_addresses order by id"
        ).fetchall()
    elif what == "user":
        rows = c.execute(
            "select id,username,phone,full_name,is_active,is_deleted from users where username like ? or full_name like ?",
            (f"%{arg}%", f"%{arg}%"),
        ).fetchall()
    else:
        print(f"不认识 {what}")
        return 2
    for r in rows:
        print(" | ".join(f"{k}={r[k]}" for k in r.keys()))
    if not rows:
        print("（没有记录）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
