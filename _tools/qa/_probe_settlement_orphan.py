"""查「已付款但没有明细」的结算单：它当年挂的是哪几条明细、什么时候没的（只读）。

判据（机器算出来的）：对每一张状态为 confirmed/paid 的结算单，
`settled_doc_id == 该单` 的 `driver_bills` 行数必须 > 0，且金额合计 == 结算单金额。
少一条就是「付了钱、账上没有对应明细」——月底没法复核这笔钱付的是什么。

用法：
    python _tools/qa/_probe_settlement_orphan.py            # 只查当前库
    python _tools/qa/_probe_settlement_orphan.py --history   # 再把 backend/*.db* 备份一起翻
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
LIVE = BACKEND / "sorders.db"

SQL_BAD = """
select s.id, s.driver_id, s.settle_type, s.month, s.amount, s.status, s.note,
       count(b.id) as n_bills, coalesce(sum(b.amount), 0) as bills_sum
  from driver_settlements s
  left join driver_bills b on b.settled_doc_id = s.id
 where s.status in ('confirmed', 'paid')
 group by s.id
having count(b.id) = 0 or coalesce(sum(b.amount), 0) <> s.amount
 order by s.id
"""


def open_ro(p: Path) -> sqlite3.Connection | None:
    """只读打开（含 WAL 里的已提交数据）。备份文件用 immutable 免得连带生成 -wal。"""
    immutable = "" if p == LIVE else "&immutable=1"
    try:
        c = sqlite3.connect(f"file:{p}?mode=ro{immutable}", uri=True)
        c.row_factory = sqlite3.Row
        c.execute("select count(*) from driver_settlements").fetchone()
        return c
    except sqlite3.Error:
        return None


def dump(p: Path) -> None:
    c = open_ro(p)
    if c is None:
        print(f"  跳过（不是本项目的库）：{p.name}")
        return
    bad = c.execute(SQL_BAD).fetchall()
    print(f"\n=== {p.name} ===")
    if not bad:
        print("  ✅ 没有「已确认/已付款但明细缺失或金额对不上」的结算单")
    for r in bad:
        print(f"  ⚠️ 结算单 #{r['id']} 司机 {r['driver_id']} {r['month']} {r['status']} "
              f"金额 {r['amount']} 明细 {r['n_bills']} 条合计 {r['bills_sum']} 备注「{r['note']}」")
    c.close()


def trace_settlement(settle_id: int, driver_id: int) -> None:
    """把这张单的明细在各备份里逐份找一遍（哪一版还在、哪一版开始没了）。"""
    files = sorted(
        [LIVE] + [p for p in BACKEND.glob("sorders.db.*") if p.suffix not in (".db",)],
        key=lambda p: p.name,
    )
    print(f"\n=== 结算单 #{settle_id}（司机 {driver_id}）的明细在各版本库里的存在情况 ===")
    for p in files:
        c = open_ro(p)
        if c is None:
            continue
        try:
            rows = c.execute(
                "select id, order_id, bill_type, month, amount, status from driver_bills "
                "where settled_doc_id = ?",
                (settle_id,),
            ).fetchall()
            # 这张单的司机当月 PIECE 明细（可能是"被删掉前"的样子）
            cand = c.execute(
                "select id, order_id, amount, status, settled_doc_id from driver_bills "
                "where driver_id = ? and bill_type = 'piece' and month = '2026-09' "
                "order by id",
                (driver_id,),
            ).fetchall()
            flag = "❌ 0 条" if not rows else f"{len(rows)} 条"
            print(f"  {p.name:44} 挂在本单下 {flag}；该司机 2026-09 PIECE 明细 {len(cand)} 条 "
                  f"{[(r['id'], r['order_id'], str(r['amount']), r['status'], r['settled_doc_id']) for r in cand][:8]}")
        except sqlite3.Error as e:
            print(f"  {p.name:44} 查询失败：{e}")
        finally:
            c.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", action="store_true", help="连备份库一起查")
    ap.add_argument("--trace", type=int, default=0, help="追某张结算单的明细在各版本里的存在情况")
    args = ap.parse_args()

    print("== 已确认/已付款的结算单 vs 明细 ==")
    dump(LIVE)
    if args.history:
        for p in sorted(BACKEND.glob("sorders.db.*")):
            dump(p)
    if args.trace:
        with open_ro(LIVE) as c:
            row = c.execute("select driver_id from driver_settlements where id = ?", (args.trace,)).fetchone()
        trace_settlement(args.trace, row["driver_id"] if row else 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
