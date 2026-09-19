"""把**探针账号**从开发库里收掉（按 App 的同一套软删语义，不硬删）。

## 为什么要收
`_tools/qa/_probe_core_flows.py` 每跑一次会建 ~11 个账号（「探针司机甲」「并发探针司机乙」
「权限探针货主乙」…），跑十几轮之后库里攒了 158 个。后果不是"占空间"，是**数字被污染**：
- 用户管理 / 司机名册 / 货主名册里全是探针账号，AI 验收时的"30 个货主 / 8 个司机"要重新数；
- 派单、定价、报表这些页面都要在一堆假账号里挑真的。

## 为什么是软删而不是硬删
这些账号**被订单/账单引用**（探针真的走过送达→账单）。硬删会留下指向空号的账单与订单
（本仓库最怕的那种孤儿行）；软删不会。
软删语义**照抄 `api/v1/users.py::delete_user`**：`is_active=False` + 手机号/用户名加 `_del{id}`
后缀（释放号码给新号用）+ 写一条 `operation_logs`。所以恢复也走现成的
`POST /users/{id}/restore`——这里不发明第二套语义。

## 判据（自己算，不靠"我记得那几个 id"）
`full_name` 里带「探针」。两条硬护栏：**不碰管理员账号**、命中数异常（>500）就拒绝执行。

用法：
    python _tools/qa/_cleanup_probe_users.py            # 只看（dry-run）
    python _tools/qa/_cleanup_probe_users.py --apply    # 备份后执行
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "sorders.db"

MARK = "%探针%"
MAX_ROWS = 500

FIND = """
select u.id, u.username, u.phone, u.full_name, u.role, u.is_active,
       (select count(*) from orders o where o.driver_id = u.id or o.shipper_id = u.id) n_orders,
       (select count(*) from driver_bills b where b.driver_id = u.id) n_bills
  from users u
 where u.full_name like ?
 order by u.id
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(FIND, (MARK,)).fetchall()
    live = [r for r in rows if r["is_active"]]
    dispatchers = [r for r in live if str(r["role"]).upper() == "DISPATCHER"]

    print(f"带「探针」标记的账号：{len(rows)} 个（其中在用 {len(live)} 个）")
    by_name: dict[str, int] = {}
    for r in rows:
        by_name[r["full_name"]] = by_name.get(r["full_name"], 0) + 1
    for name, n in sorted(by_name.items(), key=lambda kv: -kv[1])[:12]:
        print(f"   {name}: {n}")
    if dispatchers:
        print(f"\n⛔ 里面有 {len(dispatchers)} 个**管理员**账号，拒绝执行（先人工看一眼）："
              f"{[r['id'] for r in dispatchers]}")
        return 1
    if len(rows) > MAX_ROWS:
        print(f"\n⛔ 命中 {len(rows)} 个（超过上限 {MAX_ROWS}）——判据可能写宽了，拒绝执行")
        return 1

    if live:
        print("\n将被**软删**的（列表里看不见；订单/账单的引用保留不动，可 restore 恢复）：")
        for r in live[:8]:
            print(f"   #{r['id']} {r['full_name']}（{r['role']}）"
                  f"关联订单 {r['n_orders']} / 账单 {r['n_bills']}")
        if len(live) > 8:
            print(f"   …还有 {len(live) - 8} 个")

    if not args.apply:
        print("\n（dry-run，未改动任何数据；加 --apply 执行）")
        return 0
    if not live:
        print("\n没有需要处理的账号。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    copy = DB.with_name(f"sorders.db.cleanup-probe-{stamp}")
    shutil.copy2(DB, copy)
    print(f"\n已备份 → {copy.name}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    w = sqlite3.connect(str(DB))
    try:
        op = w.execute("select id from users where role='DISPATCHER' order by id limit 1").fetchone()
        operator = op[0] if op else None
        with w:
            for r in live:
                w.execute(
                    "update users set is_active = 0, phone = ?, username = ? where id = ?",
                    (f"{r['phone']}_del{r['id']}", f"{str(r['username'])[:22]}_del{r['id']}", r["id"]),
                )
                if operator:
                    w.execute(
                        "insert into operation_logs (operator_id, order_id, action, change_content, created_at)"
                        " values (?,?,?,?,?)",
                        (operator, None, "USER_DELETE",
                         json.dumps({"user_id": r["id"], "username": r["username"], "phone": r["phone"],
                                     "note": "清理探针账号（软删，可 POST /users/{id}/restore 恢复）"},
                                    ensure_ascii=False),
                         now),
                    )
        left = w.execute(
            "select count(*) from users where full_name like ? and is_active = 1", (MARK,)
        ).fetchone()[0]
        print(f"已软删 {len(live)} 个探针账号（含操作日志）；剩余在用 {left} 个")
    finally:
        w.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
