"""一次性修复：把 `POST /price-rules/batch` 被 fuzz 误改的 2880 条专属价还原。

## 事故经过（2026-09-17 23:02 UTC / 09-18 07:02 本地）
契约模糊测试 `_fuzz_contract.py` 把"超长数字"(10^20) 喂给
`POST /price-rules/batch` 的 `value` 字段 —— 该端点**没有任何上限校验**，
于是把 20 个批发商 × 144 个商品 = **2880 行全部改成了 1e20**，
其中 2822 行是这一下**凭空新建**出来的（原本不存在这条专属价）。

教训有两条，分开记：
1. **工具侧**：批量/全量端点（batch/bulk/sync/generate/apply）必须默认进 `DENY`。
   "接口只改我建的数据"这个假设，对批量端点根本不成立。
2. **产品侧**：`POST /price-rules/batch` 接受 1e20 这种价格、且没有"影响多少行"的确认，
   这是真实缺陷（生产 MySQL 上 `Numeric(14,4)` 会直接报错/截断）。

## 还原依据（按可信度排序，逐行标注用了哪一种）
| 来源 | 能还原 | 说明 |
|---|---|---|
| `sorders.db.bak-20260915` | 27 行 | 09-03 建的那批，价格原样保存 |
| `operation_logs` 的 `before` | 19 行 | 批量调价逐条日志（只记了前 200 条里的这些） |
| `products.default_unit_price` | 其余 12 行 | **无法还原**，取商品默认价——语义上等于"没有专属价"，不会算错钱，但不是原价 |

用法：
```
python _tools/fuzz/_repair_price_rules_batch.py            # 只打印计划（dry-run）
python _tools/fuzz/_repair_price_rules_batch.py --apply    # 备份 DB 后执行
```
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fuzzlib import DB_PATH, ROOT  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BACKUP = ROOT / "backend" / "sorders.db.bak-20260915"
FAULT_AFTER = "2026-09-17 23:02:00"     # 本次批量写入的 created_at 下界（UTC）
FAULT_BEFORE = "2026-09-17 23:03:00"


def rows(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return list(conn.execute(sql, args))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的执行（默认只打印计划）")
    args = ap.parse_args()

    live = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    live.row_factory = sqlite3.Row

    all_rows = rows(live, "select id, shipper_id, product_id, special_unit_price, is_deleted, created_at "
                          "from price_rules order by id")
    bred = [r for r in all_rows if FAULT_AFTER <= r["created_at"] < FAULT_BEFORE]
    pre = [r for r in all_rows if r["created_at"] < FAULT_AFTER]
    print(f"专属价共 {len(all_rows)} 行：本次批量新建 {len(bred)} 行 / 之前就存在 {len(pre)} 行")
    if len(all_rows) != len(bred) + len(pre):
        print("⚠️ 有行的 created_at 落在故障窗口之后，脚本不处理它们（请人工确认）")

    # --- 来源①：09-15 备份（读得到就多一份底气）
    from_backup: dict[tuple[int, int], tuple[str, int]] = {}
    if BACKUP.is_file():
        bk = sqlite3.connect(f"file:{BACKUP}?mode=ro", uri=True)
        bk.row_factory = sqlite3.Row
        # 老的备份里 price_rules 还没有 is_deleted 列（软删是后来加的）——按列存在与否取
        cols = {r["name"] for r in rows(bk, "pragma table_info(price_rules)")}
        del_col = "is_deleted" if "is_deleted" in cols else "0 as is_deleted"
        for r in rows(bk, f"select shipper_id, product_id, special_unit_price, {del_col} from price_rules"):
            from_backup[(r["shipper_id"], r["product_id"])] = (str(r["special_unit_price"]), r["is_deleted"])
    print(f"来源① 备份 {BACKUP.name}：{len(from_backup)} 行")

    # --- 来源②：批量调价的逐条日志（存的是名字，要换回 id）
    name2shipper = {r["full_name"]: r["id"] for r in rows(live, "select id, full_name from users") if r["full_name"]}
    name2shipper.update({r["username"]: r["id"] for r in rows(live, "select id, username from users")})
    name2product = {}
    for r in rows(live, "select id, name from products"):
        name2product.setdefault(r["name"], []).append(r["id"])
    from_log: dict[tuple[int, int], str] = {}
    ambiguous = 0
    for r in rows(live, "select change_content from operation_logs where action='PRICE_RULE_UPSERT'"):
        try:
            d = json.loads(r["change_content"])
        except Exception:
            continue
        if d.get("scope") != "batch" or not d.get("before"):
            continue
        sid = name2shipper.get(d.get("shipper"))
        pids = name2product.get(d.get("product") or "", [])
        if sid is None or len(pids) != 1:
            ambiguous += 1
            continue
        from_log[(sid, pids[0])] = str(d["before"])
    print(f"来源② 调价日志 before：{len(from_log)} 行（名字对不上/重名跳过 {ambiguous} 条）")

    # --- 来源③：商品默认价（兜底，语义="没有专属价"）
    default_price = {r["id"]: str(r["default_unit_price"]) for r in rows(live, "select id, default_unit_price from products")}

    plan: list[tuple[str, str, int | tuple[int, int], str]] = []
    stat = {"备份": 0, "日志": 0, "默认价": 0, "删除新建": 0}
    for r in pre:
        key = (r["shipper_id"], r["product_id"])
        if key in from_backup:
            val, was_deleted = from_backup[key]
            stat["备份"] += 1
            plan.append(("update", val, r["id"], f"备份 09-15；原 is_deleted={was_deleted}"))
        elif key in from_log:
            stat["日志"] += 1
            plan.append(("update", from_log[key], r["id"], "调价日志 before"))
        else:
            stat["默认价"] += 1
            plan.append(("update", default_price.get(r["product_id"], "0"), r["id"], "→ 商品默认价（原价不可考）"))
    for r in bred:
        stat["删除新建"] += 1
        plan.append(("delete", "", r["id"], f"本次批量新建（created_at={r['created_at']}）"))

    print("\n还原计划：")
    for k, v in stat.items():
        print(f"  {k}: {v} 行")
    print("\n前 8 条：")
    for op, val, rid, why in plan[:8]:
        print(f"  {op:6} id={rid:<6} {val or '':<12} {why}")

    if not args.apply:
        print("\n（dry-run，未改动任何数据；加 --apply 执行）")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    copy = DB_PATH.with_name(f"sorders.db.repair-{stamp}")
    shutil.copy2(DB_PATH, copy)
    print(f"\n已备份 → {copy.name}")

    conn = sqlite3.connect(str(DB_PATH))
    try:
        with conn:  # 单事务：要么全成，要么全不动
            for op, val, rid, why in plan:
                if op == "delete":
                    conn.execute("delete from price_rules where id=?", (rid,))
                else:
                    conn.execute(
                        "update price_rules set special_unit_price=?, is_deleted=0 where id=?", (val, rid)
                    )
        left = conn.execute("select count(*) from price_rules").fetchone()[0]
        absurd = conn.execute(
            "select count(*) from price_rules where cast(special_unit_price as real) >= 1000000"
        ).fetchone()[0]
        print(f"执行完成：专属价现在 {left} 行，其中价格异常(≥1e6) {absurd} 行")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
