"""核一笔收款是否写进了现金流水（真机验收用）。

用法：python _tools/ai/_check_receipt.py 2
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

DB = repo_root() / "backend/sorders.db"


def main() -> int:
    rid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    c = sqlite3.connect(DB)
    print("收款单：")
    for r in c.execute(
        "SELECT id,customer_id,amount,method,received_at,settle_mode,order_ids,note FROM shipper_receipts ORDER BY id DESC LIMIT 3"
    ):
        print("  ", r)
    print("客户类现金流水：")
    for r in c.execute(
        "SELECT id,flow_date,amount,direction,party_id,order_id,doc_id,biz_type,note FROM cash_flows "
        "WHERE party_type='customer' ORDER BY id DESC LIMIT 5"
    ):
        print("  ", r)
    if rid:
        rows = list(
            c.execute(
                "SELECT id,amount,order_id,note FROM cash_flows WHERE doc_id=? AND party_type='customer'",
                (rid,),
            )
        )
        print(f"\n与收款单 {rid} 关联的现金流水：{rows if rows else '（没有 → 这笔钱不在现金流水里）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
