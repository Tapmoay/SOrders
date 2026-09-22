"""造一个**大库**用来量性能（容量/耗时这一类空白面的第一步）。

## 为什么要有它

`_archive/audit/HANDOVER.md` 的「我没有探查的范围」第一条就是**性能与容量**：
"`GET /orders` 万级积压、报表在 3 年数据下的耗时、导出任务的并发与内存 —— 一次都没测过"。
本机开发库只有几百张单，量不出任何东西；生产库又只能只读地看、不方便压。

所以这个脚本把**开发库复制一份**，在副本上按比例放大数据量（订单 / 订单行 / 账本 / 流水 /
站内信），产出的库专门给 `_perf_probe.py` 量耗时用。

## 数据是按**后端自己的不变式**造的

⚠️ 这不是随便塞行：造完立刻用 `_tools/fuzz/_fuzz_invariants.py` 对副本跑一遍
（`SORDERS_DB=<副本>`），它专门查"库里这些行自相矛盾吗"——
造数造出矛盾数据的话，先红灯的是造数脚本，而不是被测代码。
所以这里守住：状态与时间戳配套、`line_total = 单价 × 数量（到分）`、
已送达的单才写账本（且账本按行对齐订单行金额）、已 `paid` 的单有对应收款流水。

## 用法

```
python _tools/perf/_perf_seed.py                      # 默认 2 万单
python _tools/perf/_perf_seed.py --orders 60000       # 更大
python _tools/perf/_perf_seed.py --out _agent/perf/perf.db --force
```

⛔ **只写 `_agent/` 下的副本**（该目录被 .gitignore 忽略）。脚本会拒绝往 `backend/sorders.db` 写。
"""
from __future__ import annotations

import argparse
import io
import random
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
SRC_DB = ROOT / "backend" / "sorders.db"
OUT_DIR = ROOT / "_agent" / "perf"
DEFAULT_OUT = OUT_DIR / "perf.db"

#: 状态的分布：与真实使用接近（大部分单最终会送达，少数撤销/在途）。
STATUS_MIX = (
    ["DELIVERED"] * 62 + ["DISPATCHED"] * 12 + ["ACCEPTED"] * 8
    + ["PENDING_DISPATCH"] * 12 + ["CANCELLED"] * 6
)


def cols(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"pragma table_info({table})")]


def template(con: sqlite3.Connection, table: str) -> dict:
    row = con.execute(f"select * from {table} limit 1").fetchone()
    if row is None:
        raise SystemExit(f"❌ {table} 是空的 —— 先跑开发库（backend/scripts/seed_demo_data.py）再造数")
    return dict(zip(cols(con, table), row))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orders", type=int, default=20000, help="要造多少张订单（在原有基础上追加）")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--force", action="store_true", help="副本已存在时重建")
    ap.add_argument("--seed", type=int, default=20260923, help="随机种子（可复现）")
    args = ap.parse_args()

    out = args.out if args.out.is_absolute() else ROOT / args.out
    if SRC_DB.resolve() == out.resolve() or out.resolve() == (ROOT / "backend" / "sorders.db").resolve():
        raise SystemExit("❌ 不许直接往开发库写：--out 指到别处（默认 _agent/perf/perf.db）")
    if out.exists() and not args.force:
        print(f"副本已存在：{out}（要重建加 --force）")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC_DB, out)
    print(f"已复制开发库 → {out}（{out.stat().st_size / 1024 / 1024:.1f}MB）")

    rnd = random.Random(args.seed)
    con = sqlite3.connect(out)
    con.execute("pragma journal_mode=WAL")
    con.execute("pragma synchronous=OFF")  # 造数阶段：快，不追持久性（副本而已）

    shippers = [r[0] for r in con.execute("select id from users where upper(role)='SHIPPER'")]
    drivers = [
        r[0]
        for r in con.execute("select id from users where upper(role)='DRIVER' and is_active=1")
    ]
    products = [
        dict(zip(("id", "name", "price", "unit", "cost"), r))
        for r in con.execute(
            "select id, name, default_unit_price, unit, coalesce(cost_price, 0) "
            "from products where is_deleted=0 order by id"
        )
    ]
    if not (shippers and drivers and products):
        raise SystemExit("❌ 开发库里缺货主/司机/商品，先把演示数据造全")

    o_tpl = template(con, "orders")
    l_tpl = template(con, "order_products")
    lg_tpl = template(con, "ledgers")
    cf_tpl = template(con, "cash_flows")
    nt_tpl = template(con, "notifications")
    im_tpl = template(con, "inventory_movements")

    o_cols = cols(con, "orders")
    l_cols = cols(con, "order_products")
    lg_cols = cols(con, "ledgers")
    cf_cols = cols(con, "cash_flows")
    nt_cols = cols(con, "notifications")
    im_cols = cols(con, "inventory_movements")

    base_id = con.execute("select coalesce(max(id),0) from orders").fetchone()[0]
    now = datetime(2026, 9, 23, 4, 0, 0)  # 固定"今天"，让 18 个月的窗口可复现

    order_rows, line_rows, lg_rows, cf_rows, nt_rows, im_rows = [], [], [], [], [], []
    line_id = con.execute("select coalesce(max(id),0) from order_products").fetchone()[0]
    lg_id = con.execute("select coalesce(max(id),0) from ledgers").fetchone()[0]

    for i in range(args.orders):
        oid = base_id + i + 1
        status = STATUS_MIX[i % len(STATUS_MIX)]
        created = now - timedelta(days=rnd.randint(0, 540), minutes=rnd.randint(0, 1439))
        o = dict(o_tpl)
        o.update(
            id=oid,
            order_no=f"SO{created:%Y%m%d}{oid:09d}",
            shipper_id=shippers[i % len(shippers)],
            status=status,
            created_at=created.strftime("%Y-%m-%d %H:%M:%S.%f"),
            updated_at=(created + timedelta(hours=rnd.randint(1, 72))).strftime(
                "%Y-%m-%d %H:%M:%S.%f"
            ),
            paid=(status == "DELIVERED" and i % 3 == 0),
            remark=f"性能样本单 {i}" if i % 50 == 0 else "",
        )
        driver_id = None if status == "PENDING_DISPATCH" else drivers[i % len(drivers)]
        o["driver_id"] = driver_id
        o["dispatched_at"] = (
            None if status == "PENDING_DISPATCH"
            else (created + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S.%f")
        )
        o["accepted_at"] = (
            (created + timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S.%f")
            if status in ("ACCEPTED", "DELIVERED", "CANCELLED") and driver_id else None
        )
        o["delivered_at"] = (
            (created + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S.%f")
            if status == "DELIVERED" else None
        )
        o["cancelled_at"] = (
            (created + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S.%f")
            if status == "CANCELLED" else None
        )
        o["deleted_at"] = None
        o["freight_fee"] = (
            None if i % 7 == 0 else f"{rnd.choice([30, 45, 60, 80, 120, 150])}.00"
        )
        order_rows.append(tuple(o.get(c) for c in o_cols))

        n_lines = 1 + (i % 3)
        order_total = 0.0
        order_qty = 0
        picked = [products[(i * 3 + k) % len(products)] for k in range(n_lines)]
        for k, p in enumerate(picked):
            line_id += 1
            qty = 1 + rnd.randint(0, 9)
            order_qty += qty
            price = float(p["price"] or 10)
            total = round(price * qty, 2)
            order_total += total
            ln = dict(l_tpl)
            ln.update(
                id=line_id,
                order_id=oid,
                product_id=p["id"],
                product_name_snapshot=p["name"],
                unit=p["unit"] or "件",
                quantity=qty,
                unit_price=f"{price:.4f}",
                line_total=f"{total:.4f}",
                cost_price_snapshot=p["cost"] or 0,
                returned_quantity=0,
            )
            line_rows.append(tuple(ln.get(c) for c in l_cols))

            # 已送达的单才写账本（与应用的写法一致：账本按订单行对齐）
            if status == "DELIVERED":
                lg_id += 1
                lg = dict(lg_tpl)
                lg.update(
                    id=lg_id,
                    shipper_id=o["shipper_id"],
                    entry_date=created.date().isoformat(),
                    product_name=p["name"],
                    quantity=qty,
                    unit_price=f"{price:.4f}",
                    total=f"{total:.4f}",
                    order_id=oid,
                    order_product_id=line_id,
                    product_id=p["id"],
                    source="ORDER",
                    note="",
                    created_at=o["created_at"],
                    updated_at=o["updated_at"],
                    cost_price_snapshot=p["cost"] or 0,
                )
                lg_rows.append(tuple(lg.get(c) for c in lg_cols))

        # 已收款的单补一条现金流水（"已 paid 就得有流水"这条不变式的正向写法）
        if o["paid"]:
            cf = dict(cf_tpl)
            cf.update(
                id=None,
                biz_type=cf_tpl.get("biz_type") or "ORDER",
                direction="in",
                amount=f"{order_total:.2f}",
                order_id=oid,
                occurred_at=o["delivered_at"],
                created_at=o["delivered_at"],
                note="性能样本",
            )
            cf_rows.append(tuple(cf.get(c) for c in cf_cols if c != "id"))

        if i % 4 == 0:
            nt = dict(nt_tpl)
            nt.update(
                id=None,
                recipient_id=o["shipper_id"],
                title=f"性能样本通知 {i}",
                content="这是一条造出来的站内信，用来量列表与未读数的耗时。",
                read_at=None if i % 8 == 0 else o["created_at"],
                created_at=o["created_at"],
                updated_at=o["created_at"],
            )
            nt_rows.append(tuple(nt.get(c) for c in nt_cols if c != "id"))

        if status == "DELIVERED" and i % 5 == 0:
            im = dict(im_tpl)
            im.update(
                id=None,
                product_id=picked[0]["id"],
                order_id=oid,
                # ⚠️ 必须等于"这张单全部商品数量之和"的相反数 —— 第一版写死 -1，
                #    立刻被 `_fuzz_invariants.py` 抓出来（2502/2602 行对不上）。
                #    这正是造数脚本要先过不变式的原因：数据不自洽的话，
                #    后面量出来的耗时与"这库到底像不像真的"都不可信。
                change=-order_qty,
                source="ORDER",
                status="COMMITTED",
                created_at=o["delivered_at"],
            )
            im_rows.append(tuple(im.get(c) for c in im_cols if c != "id"))

    def ins(table: str, table_cols: list[str], rows: list[tuple]) -> None:
        if not rows:
            return
        ph = ",".join("?" * len(table_cols))
        names = ",".join(f'"{c}"' for c in table_cols)
        con.executemany(f'insert into "{table}" ({names}) values ({ph})', rows)

    ins("orders", o_cols, order_rows)
    ins("order_products", l_cols, line_rows)
    ins("ledgers", lg_cols, lg_rows)
    ins("cash_flows", [c for c in cf_cols if c != "id"], cf_rows)
    ins("notifications", [c for c in nt_cols if c != "id"], nt_rows)
    ins("inventory_movements", [c for c in im_cols if c != "id"], im_rows)
    con.commit()
    con.execute("analyze")
    con.commit()

    counts = {
        t: con.execute(f"select count(*) from {t}").fetchone()[0]
        for t in ("orders", "order_products", "ledgers", "cash_flows", "notifications",
                  "inventory_movements")
    }
    con.close()
    size = out.stat().st_size / 1024 / 1024
    print(f"造完：{counts}")
    print(f"库大小 {size:.1f}MB → {out}")
    print("\n下一步（先验数据自洽，再量耗时）：")
    print(f"  $env:SORDERS_DB='{out}'; python _tools/fuzz/_fuzz_invariants.py")
    print(f"  $env:DATABASE_URL='sqlite:///{out.as_posix()}'; "
          "cd backend; python -m uvicorn app.main:app --port 8001")
    print("  python _tools/perf/_perf_probe.py --base http://127.0.0.1:8001")
    return 0


if __name__ == "__main__":
    sys.exit(main())
