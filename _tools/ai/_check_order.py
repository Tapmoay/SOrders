"""核对一张订单的当前状态（真机 E2E 之后用来在库里对账）。

用法：python _tools/ai/_check_order.py SOTEST2026091400227
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
        print("用法：python _tools/ai/_check_order.py <订单号前缀或完整单号>")
        return 2
    like = sys.argv[1] + "%"
    c = sqlite3.connect(DB)
    rows = list(
        c.execute(
            "SELECT id, order_no, status, driver_id, parent_order_id, is_exception, "
            "remark, exception_resolution, delivered_at, updated_at "
            "FROM orders WHERE order_no LIKE ? ORDER BY id",
            (like,),
        )
    )
    for r in rows:
        print(
            f"id={r[0]} {r[1]} status={r[2]} driver={r[3]} parent={r[4]} "
            f"异常={r[5]} 备注={r[6]!r} 解决={r[7]!r} 更新={r[9]}"
        )
    if not rows:
        print("没找到这一单")
    return 0


if __name__ == "__main__":
    sys.exit(main())
