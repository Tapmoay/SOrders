"""打印几张关键表的行数（真机 E2E 前后各跑一次，用来证明"真的写进去了"）。

用法：python _tools/ai/_counts.py
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

DB = repo_root() / "backend/sorders.db"


def main() -> int:
    c = sqlite3.connect(DB)

    def one(sql: str) -> int:
        return list(c.execute(sql))[0][0]

    print("账本行数        :", one("SELECT count(1) FROM ledgers"))
    print("账本(手工记的)  :", one("SELECT count(1) FROM ledgers WHERE source='MANUAL'"))
    print("已送达订单      :", one("SELECT count(1) FROM orders WHERE status='DELIVERED'"))
    print("异常单          :", one("SELECT count(1) FROM orders WHERE is_exception=1"))
    print("收款单          :", one("SELECT count(1) FROM shipper_receipts"))
    print("现金流水        :", one("SELECT count(1) FROM cash_flows"))
    print("客户数          :", one("SELECT count(1) FROM customers"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
