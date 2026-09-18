"""清掉 fuzz 工具在开发库里留下的残渣（商品/客户/运费模板/挂账单位/车辆/司机账单…）。

原则：
1. **只删"看起来就是 fuzz 建的"那种名字**（`fuzz-*` / 盘号 `fuzz-*` / 账单 month 是 fuzz 串），
   不做"按 id 段删"这种猜法。
2. **先查引用**：有订单/账本/账单引用的行不删，只打印出来人工看。
3. **审计日志不删**：operation_logs 里那些行是"当时确实发生了什么"的记录，删了就没人知道发生过。
4. dry-run 默认，`--apply` 才动数据，动之前自动备份 DB。

用法：
```
python _tools/fuzz/_cleanup_leftovers.py
python _tools/fuzz/_cleanup_leftovers.py --apply
```
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fuzzlib import DB_PATH  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

#: (表, 判定 SQL（机器算出来的，不是"我记得的那几个名字"）, 引用检查 [(引用表, 引用列, 本表主键)], 说明)
TARGETS = [
    ("products", "name like 'fuzz-%'", [("order_products", "product_id", "id"), ("ledgers", "product_id", "id"),
                                        ("price_rules", "product_id", "id"), ("inventory_movements", "product_id", "id")],
     "fuzz 建的商品"),
    ("customers", "name like 'fuzz-%'", [("ledgers", "customer_id", "id"), ("shipper_receipts", "customer_id", "id")],
     "fuzz 建的客户档案"),
    ("freight_templates", "name like 'fuzz-%'", [], "fuzz 建的运费模板"),
    ("arrears_units", "name like 'fuzz-%'", [("orders", "arrears_unit_id", "id")], "fuzz 建的挂账单位"),
    ("vehicles", "plate_no like 'fuzz-%'", [("expenses", "vehicle_id", "id")], "fuzz 建的车"),
    ("driver_billing_rules", "name like 'fuzz-%'", [("users", "billing_rule_id", "id")], "fuzz 建的计费规则"),
    # ⚠️ 这一条的判据**不是**名字像 fuzz，而是"月份不是 YYYY-MM"：账单列表的 month 查询参数
    #    带 `pattern=^\d{4}-\d{2}$`，所以**任何**非该格式的账单在任何界面里都按月份查不到，
    #    也永远进不了结算单——它们是"生成了但结不掉"的幽灵工资单（实测 70 张、合计 34.5 万）。
    ("driver_bills", "month not glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]'", [], "月份格式非法的司机账单"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}

    plan: list[tuple[str, int]] = []
    blocked: list[str] = []
    for table, where, refs, label in TARGETS:
        if table not in tables:
            continue
        try:
            rows = list(conn.execute(f"select id, * from {table} where {where}"))
        except sqlite3.Error as e:
            print(f"  ⚠️ {table}（{label}）: {e}")
            continue
        if not rows:
            continue
        print(f"\n== {table} · {label}：{len(rows)} 行")
        for r in rows:
            hit = []
            for rt, rc, pk in refs:
                if rt not in tables:
                    continue
                try:
                    n = conn.execute(f"select count(*) from {rt} where {rc}=?", (r["id"],)).fetchone()[0]
                except sqlite3.Error:
                    continue
                if n:
                    hit.append(f"{rt}.{rc}={n}")
            if hit:
                blocked.append(f"{table}#{r['id']} 被引用：{', '.join(hit)}")
                print(f"   ⛔ id={r['id']} 有引用，不删（{', '.join(hit)}）")
            else:
                plan.append((table, r["id"]))

    print(f"\n可删 {len(plan)} 行；因被引用而保留 {len(blocked)} 行")
    by_table: dict[str, int] = {}
    for t, _ in plan:
        by_table[t] = by_table.get(t, 0) + 1
    for t, n in sorted(by_table.items()):
        print(f"   {t}: {n}")

    if not args.apply:
        print("\n（dry-run，未改动任何数据；加 --apply 执行）")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    copy = DB_PATH.with_name(f"sorders.db.cleanup-{stamp}")
    shutil.copy2(DB_PATH, copy)
    print(f"\n已备份 → {copy.name}")
    w = sqlite3.connect(str(DB_PATH))
    try:
        with w:
            for t, rid in plan:
                w.execute(f"delete from {t} where id=?", (rid,))
        print("已删除。剩余同类行：")
        for table, where, _refs, label in TARGETS:
            if table in tables:
                n = w.execute(f"select count(*) from {table} where {where}").fetchone()[0]
                if n:
                    print(f"   {table}（{label}）: {n}")
    finally:
        w.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
