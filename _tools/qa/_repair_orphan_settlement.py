"""修掉「已确认/已付款、却没有任何明细」的结算单（本地开发库；带备份、只删得干净的）。

## 这些行是什么
`driver_settlements` 里状态是 confirmed/paid，但 `settled_doc_id` 指回来的
`driver_bills` **一条都没有**。后果不是显示问题：账上多了一笔"已付出去"的钱，
却没有任何应付款能解释它付的是什么，月底对不了账。

## 它们从哪来（2026-09-18 查清）
App 的三条路都堵着：建单要当月待结明细、确认要"金额 == 明细合计"、付款要状态是已确认。
库里那 1 张（#2，司机 152 = `SOTEST_d00`，352 元）是**造数工具直接写库**造的：
`_tools/ai/_seed_test_data.py` 原来只 INSERT 结算单本身（`status=paid`、`order_ids=[]`），
既没有 `driver_bills` 也没有付款流水。⇒ 已把造数工具改成"先明细、再结算单、再付款流水"。
产品侧同时补了一道闸：`pay_settlement` 付款前会再核一遍明细还在不在、对不对得上。

## 处置规则（本脚本只做安全的那一种）
- **没有任何付款流水** → 这一行只是"假的已付"，直接删掉（它没连着任何钱）。
- **有付款流水** → **不删**，只报出来：那种情况要先决定"这笔钱退回来还是补明细"，
  删掉结算单会让流水指向一张不存在的单（比现在更糟）。

用法：
    python _tools/qa/_repair_orphan_settlement.py            # 只看（dry-run）
    python _tools/qa/_repair_orphan_settlement.py --apply    # 备份后执行
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "sorders.db"

ORPHANS = """
select s.id, s.driver_id, s.month, s.amount, s.status, s.note,
       (select count(*) from driver_bills b where b.settled_doc_id = s.id) n_bills,
       (select count(*) from cash_flows c where c.doc_id = s.id and c.biz_type like 'PAYMENT%') n_pay
  from driver_settlements s
 where s.status in ('confirmed', 'paid')
   and not exists (select 1 from driver_bills b where b.settled_doc_id = s.id)
 order by s.id
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(ORPHANS).fetchall()
    print(f"「已确认/已付款但没有明细」的结算单：{len(rows)} 张")
    for r in rows:
        tag = "可删（没有付款流水）" if r["n_pay"] == 0 else "⚠️ 有付款流水，**不删**（要先决定钱怎么退）"
        print(f"  #{r['id']} 司机 {r['driver_id']} {r['month']} {r['status']} {r['amount']} 元 "
              f"备注「{r['note']}」 → {tag}")
    con.close()

    doomed = [r["id"] for r in rows if r["n_pay"] == 0]
    kept = [r["id"] for r in rows if r["n_pay"]]
    if not doomed:
        print("\n没有「删得干净」的行。")
    if kept:
        print(f"\n留下待人工决定：{kept}")
    if not args.apply or not doomed:
        print("\n（dry-run；要执行加 --apply）" if not args.apply else "")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    copy = DB.with_name(f"sorders.db.repair-orphan-{stamp}")
    shutil.copy2(DB, copy)
    print(f"\n已备份 → {copy.name}")

    w = sqlite3.connect(str(DB))
    try:
        with w:
            for sid in doomed:
                w.execute("delete from driver_settlements where id = ?", (sid,))
        left = w.execute(ORPHANS).fetchall()
        print(f"执行完成：删了 {len(doomed)} 张 {doomed}；剩下的同类行 {len(left)} 张")
    finally:
        w.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
