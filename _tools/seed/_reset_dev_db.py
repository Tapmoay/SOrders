"""把**本机开发库**清空成"只剩登录账号"的干净状态（用户 2026-09-20 要求）。

## 为什么要这一步

本机库里沉积了几轮压测与验证留下的东西：`压测商品01..N`、`ttt`、`325`、
名字里带"验证-"的地点、8214 条通知、5676 条操作日志……这些数据**写得不规范**，
拿它看界面/对数字，看到的是"数据脏"而不是"功能坏"。
用户原话：「将现在所有的测试数据全部做一个清除…因为这些数据很多写都是不规范的，
清洗完之后，我们再重新写一份数据」。

## 它的行为（fail-safe）

1. **先备份**：用 SQLite 自己的 backup API 落一份一致的副本到 `_archive/`（含 WAL 里还没落盘的部分），
   运行前会打印路径与大小；
2. **只删业务数据**：保留登录账号（默认 `13800000001` 派单员 / `13800000002` 货主 / `13800000003` 司机，
   可用 `--keep` 追加），其余用户的**业务引用**（订单/账本/账单…）先清；
3. **默认是 dry-run**：只打印"将删除 N 行"，加 `--yes` 才真的删。

⚠️ 它**只动本机**：`backend/sorders.db` 是开发库（模拟器经 10.0.2.2 打的就是它）。
生产库（`8.145.40.22`）不在它的范围内 —— 那边的清理要单独拍板、单独备份。

用法：
    python _tools/seed/_reset_dev_db.py            # 看看会删什么（不改）
    python _tools/seed/_reset_dev_db.py --yes      # 备份 + 清空
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend/sorders.db"
BACKUP_DIR = ROOT / "_archive"

#: 清空的顺序 = 先子后父（SQLite 默认不校验外键，但这个顺序读起来是对的，也方便将来开外键）
WIPE_ORDER = [
    # 订单与它的派生物
    "order_products", "orders",
    "driver_bills", "driver_settlements",
    "ledgers", "cash_flows", "shipper_receipts", "expenses",
    "ledger_export_jobs",
    # 商品与库存
    "inventory_movements", "product_cost_history", "price_rules", "products", "product_categories",
    "user_product_visibility",
    # 地址与地点库
    "place_user_usage", "places", "place_categories",
    "shipper_locations", "shipper_addresses", "shipper_contacts",
    # 账号附属（客户档案、计费规则、车队、挂靠单位、模板）
    "customers", "driver_billing_rules", "vehicles", "arrears_units",
    "freight_template_drivers", "freight_templates",
    # 消息与日志
    "notifications", "operation_logs",
]

DEFAULT_KEEP = ["13800000001", "13800000002", "13800000003"]


def backup() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    out = BACKUP_DIR / f"backup-sorders-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(DB)
    dst = sqlite3.connect(out)
    with dst:
        src.backup(dst)          # 一致快照（含 WAL），比直接 copy 文件稳
    dst.close()
    src.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="清空本机开发库的业务数据（保留登录账号）")
    ap.add_argument("--yes", action="store_true", help="真的执行（缺省只预览）")
    ap.add_argument("--keep", action="append", default=[], help="额外保留的手机号")
    args = ap.parse_args()
    keep = DEFAULT_KEEP + args.keep

    if not DB.exists():
        print(f"❌ 找不到开发库：{DB}")
        return 1
    c = sqlite3.connect(DB)
    tables = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    plan: list[tuple[str, int]] = []
    for t in WIPE_ORDER:
        if t not in tables:
            continue
        n = c.execute(f'select count(*) from "{t}"').fetchone()[0]
        if n:
            plan.append((t, n))
    users = c.execute("select count(*) from users").fetchone()[0]
    kept = c.execute(
        "select count(*) from users where phone in (%s)" % ",".join("?" * len(keep)), keep
    ).fetchone()[0]
    print(f"库 {DB}（{DB.stat().st_size/1024/1024:.1f} MB）")
    print(f"将清空 {len(plan)} 张表的 {sum(n for _, n in plan)} 行：")
    for t, n in plan:
        print(f"   {n:>7}  {t}")
    print(f"账号：现有 {users} 个，保留 {kept} 个（{', '.join(keep)}），删除其它 {users - kept} 个")

    if not args.yes:
        print("\n（预览模式，什么都没改。加 --yes 执行）")
        return 0

    bak = backup()
    print(f"\n✅ 备份：{bak}（{bak.stat().st_size/1024/1024:.1f} MB）")
    with c:
        for t, _ in plan:
            c.execute(f'delete from "{t}"')
        c.execute(
            "delete from users where phone not in (%s)" % ",".join("?" * len(keep)), keep
        )
    left = {t: c.execute(f'select count(*) from "{t}"').fetchone()[0] for t, _ in plan}
    tail = {t: n for t, n in left.items() if n}
    print("✅ 清空完成；剩下的非零表：", tail or "（业务表全空）")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
