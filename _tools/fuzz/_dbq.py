"""本地核查小工具：按标记/关键字查库（只读）。给挖掘过程中的"落库后果"核对用。

用法：
```
python _tools/fuzz/_dbq.py "select id,name,is_deleted from products order by id desc limit 5"
python _tools/fuzz/_dbq.py --tables
python _tools/fuzz/_dbq.py --marks          # 查所有带 fuzz 标记的残留
```
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fuzzlib import DB_PATH  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

MARKS = [
    ("products", "select id,name,is_deleted from products where name like 'fuzz-%' or name like '%-fz%'"),
    ("orders", "select id,order_no,status,temp_shipper_name,delivery_description from orders "
               "where temp_shipper_name like '%fz%' or delivery_description like '%fz%' "
               "or delivery_description like '%fuzz%' or remark like '%fuzz%'"),
    ("ledgers", "select id,order_id,total,source from ledgers where product_name like 'fuzz-%'"),
]


def scan(conn, needle: str) -> None:
    """**机器算出来的**扫描清单：把每张表每个文本列都 LIKE 一遍。

    为什么不用手写的 MARKS 常量：手写清单只覆盖"我想得起来的那几张表"，
    而 fuzz 建出来的残留可能在任何一张表里——第一版就是手写的，漏掉了
    customers/expenses/freight-templates/vehicles 四张表。
    """
    tables = [r[0] for r in conn.execute("select name from sqlite_master where type='table' order by name")]
    total = 0
    for t in tables:
        cols = [r[1] for r in conn.execute(f"pragma table_info({t})")]
        text_cols = [c for c in cols if c not in ("id",)][:60]
        hits = []
        for c in text_cols:
            try:
                n = conn.execute(
                    f"select count(*) from {t} where cast({c} as text) like ?", (f"%{needle}%",)
                ).fetchone()[0]
            except sqlite3.Error:
                continue
            if n:
                hits.append(f"{c}={n}")
        if hits:
            ids = [r[0] for r in conn.execute(
                f"select id from {t} where " + " or ".join(
                    f"cast({h.split('=')[0]} as text) like ?" for h in hits
                ) + " limit 12",
                tuple(f"%{needle}%" for _ in hits),
            )]
            total += sum(int(h.split("=")[1]) for h in hits)
            print(f"  {t:24} {', '.join(hits)}  例: id {ids}")
    print(f"\n命中 {total} 处（表内按列计，含重复计数）")


def connect(path: str) -> sqlite3.Connection:
    """只读连接。

    ⚠️ `--db` 必须真的生效（2026-09-18 修）：这个参数原来只是 `add_argument` 了，
    查询却仍旧走 `db_ro()`（= 默认开发库），于是「查另一份库」的命令**静默地查了开发库**——
    本轮就是靠它才发现的（拿它查试跑副本，结果拿到的是开发库的答案，两边的数字对不上）。
    工具里"看起来能选、其实没接线"的参数比没有这个参数更危险。
    """
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"✗ 找不到数据库 {p}")
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sql", nargs="?", default="")
    ap.add_argument("--tables", action="store_true")
    ap.add_argument("--marks", action="store_true", help="扫 'fuzz' 残留（=--scan fuzz）")
    ap.add_argument("--scan", default="", help="在所有表的文本列里找这个子串")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()

    with connect(args.db) as c:
        if args.tables:
            for (n,) in c.execute("select name from sqlite_master where type='table' order by name"):
                cnt = c.execute(f"select count(*) from {n}").fetchone()[0]
                print(f"{n:36} {cnt}")
            return 0
        if args.marks or args.scan:
            scan(c, args.scan or "fuzz")
            return 0
        if not args.sql:
            ap.error("给一条 SQL，或用 --tables / --marks")
        cur = c.execute(args.sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        if cols:
            print(" | ".join(cols))
            print("-" * 60)
        n = 0
        for row in cur:
            print(" | ".join("" if v is None else str(v) for v in row))
            n += 1
        print(f"\n({n} 行)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
