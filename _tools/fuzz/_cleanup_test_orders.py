"""清掉 fuzz 工具建出来的**测试订单及其派生行**（账单/账本/流水/库存/收款引用）。

## 为什么要清
`_fuzz_replay.py` 为了测"重复送达会不会变成两笔"，必须真的把单推到已送达——
于是每跑一轮就留下：1 张测试单 + 1 条司机账单（open）+ 1 条账本行（+现金流水/库存流水）。
累计跑了 10 轮 → 司机 3 名下多出 **39 条 open 账单、约 2580 元"待结"**。
这些钱不存在，但会出现在"司机待结运费"和账本/报表里（软删订单不会带走它们）。

## 判据（机器算出来的标记，不是"我记得那几个 id"）
工具建的测试单，`delivery_description` 里都有固定前缀：
`重放试验A/B`、`并发送达`、`核销试验`、`重复派单`、`删单试验`、`IDOR试验单`，
或 `temp_shipper_name` 形如 `xxx客户-fz…`。只清带这些标记的行。

## 与 App 语义的差别（写清楚，别当成惯例）
App 删单是**软删**（订单进 30 天隔离区，账本按 3 年保留）。这里是**硬删**：
因为这些行是工具造出来的假业务，留在库里只会让每一次对账检查都变噪音。
动数据前先备份。用法：`python _tools/fuzz/_cleanup_test_orders.py [--apply]`
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

#: 工具建的测试单的标记（前缀匹配 delivery_description）
MARKERS = ("重放试验A", "重放试验B", "并发送达", "核销试验", "重复派单", "删单试验", "IDOR试验单")

WHERE = "(" + " or ".join(f"delivery_description like '{m}%'" for m in MARKERS) + \
        " or temp_shipper_name like '%客户-fz%')"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    orders = [r["id"] for r in conn.execute(f"select id from orders where {WHERE}")]
    print(f"带工具标记的测试单：{len(orders)} 张 {orders[:10]}{'…' if len(orders) > 10 else ''}")
    if not orders:
        return 0

    qs = ",".join("?" * len(orders))
    plan: list[tuple[str, str, int]] = []
    for table, col in (
        ("driver_bills", "order_id"),
        ("ledgers", "order_id"),
        ("cash_flows", "order_id"),
        ("inventory_movements", "order_id"),
        ("order_products", "order_id"),
        ("expenses", "order_id"),
        ("notifications", "order_id"),
    ):
        try:
            n = conn.execute(f"select count(*) from {table} where {col} in ({qs})", orders).fetchone()[0]
        except sqlite3.Error:
            continue
        if n:
            plan.append((table, col, n))
    # 收款单里 order_ids 是 JSON 数组：只删"整个都指向测试单"的那些，别误伤真实收款
    receipts = [
        r["id"] for r in conn.execute("select id, order_ids from shipper_receipts where order_ids is not null")
        if set(__import__("json").loads(r["order_ids"])) <= set(orders)
    ]
    print("\n计划删除：")
    for table, col, n in plan:
        print(f"  {table}.{col}: {n} 行")
    if receipts:
        print(f"  shipper_receipts（只绑测试单的）: {len(receipts)} 行 {receipts[:5]}")
    print(f"  orders 本身: {len(orders)} 行")

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
            for table, col, _n in plan:
                w.execute(f"delete from {table} where {col} in ({qs})", orders)
            for rid in receipts:
                w.execute("delete from shipper_receipts where id=?", (rid,))
            w.execute(f"delete from orders where id in ({qs})", orders)
        left = w.execute(f"select count(*) from orders where {WHERE}").fetchone()[0]
        bills = w.execute("select count(*) from driver_bills where status='open'").fetchone()[0]
        print(f"执行完成：标记订单剩余 {left} 张；全库 open 账单 {bills} 条")
    finally:
        w.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
