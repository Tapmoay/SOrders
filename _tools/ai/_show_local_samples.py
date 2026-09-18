"""查本机测试库里可用的样本（待派单订单 / 司机），做真机 E2E 前先看有哪些料。

用法：python _tools/ai/_show_local_samples.py
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
    print("待派单（可用来试派单/拆单/改单）：")
    for r in c.execute(
        "SELECT id, order_no, status, driver_id, freight_fee FROM orders "
        "WHERE status='PENDING_DISPATCH' AND deleted_at IS NULL ORDER BY id DESC LIMIT 6"
    ):
        print("  ", r)
    print("司机：")
    for r in c.execute("SELECT id, full_name, role FROM users WHERE role='DRIVER' LIMIT 5"):
        print("  ", r)
    print("异常单（可用来试解除异常）：")
    for r in c.execute("SELECT id, order_no FROM orders WHERE is_exception=1 LIMIT 5"):
        print("  ", r)
    print("客户（记收款要用名字定位）：")
    for r in c.execute("SELECT id, name, kind, is_member FROM customers LIMIT 8"):
        print("  ", r)
    print("最近的账本流水（改/删要用摘要+日期+金额定位）：")
    for r in c.execute(
        "SELECT id, entry_date, product_name, total, source, note FROM ledgers "
        "ORDER BY id DESC LIMIT 8"
    ):
        print("  ", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
