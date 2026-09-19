"""删掉一行账本流水（模拟"漏入账"），用来验证「补进账本」真的会补。

用法：python _tools/ai/_drop_ledger_row.py 372
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
        print("用法：python _tools/ai/_drop_ledger_row.py <ledger_id>")
        return 2
    lid = int(sys.argv[1])
    c = sqlite3.connect(DB)
    row = list(c.execute("SELECT id,product_name,total,order_id FROM ledgers WHERE id=?", (lid,)))
    print("要删的行:", row)
    c.execute("DELETE FROM ledgers WHERE id=?", (lid,))
    c.commit()
    print("删后账本行数:", list(c.execute("SELECT count(1) FROM ledgers"))[0][0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
