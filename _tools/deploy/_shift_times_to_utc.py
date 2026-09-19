# -*- coding: utf-8 -*-
"""把**存量**的「库端时钟」时间列从 +08:00 墙上时间平移到 UTC（一次性、不可逆）。

## 为什么需要它（2026-09-19 外部完整检查 C-2）
本项目的口径是"库里一律存 UTC"，但历史上有两类写入者：
- **Python** 写 `utc_now_naive()`（UTC）—— 早就对了；
- **库端** `NOW()` 写 `created_at`/`updated_at`/`operation_logs.created_at` —— 生产 MySQL
  的会话时区是 `SYSTEM`（**+08:00**），所以这些列存的是**当地墙上时间**。

代码侧本轮已经收口（Python 提供值 + 会话时区钉成 UTC），但**存量行不会自己变**。
不平移的话，库里会长期混着两种基准：新行 UTC、老行 +08:00 ——
"待派超时 4 小时"对老单仍然是 12 小时，保留策略对老数据的窗口也仍然是偏的。

## 这个脚本改什么（清单**自己算**，不手写表名）
连上库 → 用 `information_schema` 找出**所有带 `created_at` / `updated_at` 的表**
（外加 `operation_logs.created_at`，它不走 `TimestampMixin`）→ 对每一列执行
`UPDATE <表> SET <列> = DATE_SUB(<列>, INTERVAL 8 HOUR)`。

⛔ **只对 MySQL 生效**：本机 SQLite 的 `CURRENT_TIMESTAMP` 本来就是 UTC，不需要也不许平移
（脚本会直接拒绝非 MySQL 连接）。

## 安全设计（这是一次不可逆的数据改动）
1. **默认 dry-run**：只打印"每列多少行、最小/最大值、平移后会变成什么"，一行都不改；
2. `--apply` 才真跑，且**必须先备份**（脚本会打印现成的 `mysqldump` 命令，
   并要求显式传 `--backup-confirmed`）；
3. **幂等保护**：跑成功后在库里写一行标记（`operation_logs` 里 `action='TIME_BASE_SHIFTED_UTC'`），
   之后任何一次执行都会**拒绝再跑**（除非 `--force`，那是给"确实跑错了"的场景留的）；
4. 每列**各自一个事务**，失败即停并报出是哪一列；
5. 时差**不是写死的 8**：脚本先问库 `SELECT TIMEDIFF(NOW(), UTC_TIMESTAMP())`，
   按库自己报的偏差平移（生产是 8 小时，但换台机器/改了时区也不会平移错）。

## 顺序（必须在同一个维护窗口里做完，**服务全程停着**）
```
① 备份：mysqldump（脚本会打印现成命令）
② systemctl stop sorders-api          ← 必须停！见下面的竞态说明
③ 部署收敛后的代码（本仓库 = 分支 new）
④ 立刻跑本脚本 --apply
⑤ systemctl start sorders-api
⑥ 验证：取一行老数据，它的 created_at 应当比"服务器当地墙上时间"早 8 小时
```

⛔ **为什么必须停服务**（第一版写的顺序是"先部署再平移"，那是错的）：
服务一跑起新代码，新写进来的 `created_at` **已经是 UTC**；此时再整体减 8 小时，
就会把这些新行**也减掉 8 小时**（变成 8 小时前）。停服务 = 平移期间没有写入 = 没有歧义。
平移到一半失败也没关系：脚本逐列独立事务，并且**跑完才写幂等标记**，
重跑时它对已经平移过的列会再减一次 —— 所以失败后请按备份恢复再重来，别直接重跑。

用法：
    # 先看一眼（默认就是这一步）：
    MYSQL_PWD=... python _tools/deploy/_shift_times_to_utc.py --dsn 'mysql+pymysql://sorders@127.0.0.1/sorders'
    # 确认后真跑：
    ... --apply --backup-confirmed
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta

from sqlalchemy import create_engine, text

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

MARKER_ACTION = "TIME_BASE_SHIFTED_UTC"

#: 不走 `TimestampMixin`、但也由库端时钟写的列（加在这里要写清理由）
EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("operation_logs", "created_at"),
)


def _columns_to_shift(conn) -> list[tuple[str, str]]:
    """**自己算**清单：所有带 created_at / updated_at 的表 + `EXTRA_COLUMNS`。"""
    rows = conn.execute(
        text(
            "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND COLUMN_NAME IN ('created_at','updated_at') "
            "ORDER BY TABLE_NAME, COLUMN_NAME"
        )
    ).fetchall()
    found = {(str(t), str(c)) for t, c in rows}
    for pair in EXTRA_COLUMNS:
        found.add(pair)
    return sorted(found)


def _server_offset(conn) -> timedelta:
    """库自己报的"本地墙上时间 - UTC"（生产 8 小时）。不许写死。"""
    got = conn.execute(text("SELECT TIMEDIFF(NOW(), UTC_TIMESTAMP())")).scalar()
    if got is None:
        raise SystemExit("❌ 取不到服务器时差（TIMEDIFF 返回空），先查库的时区设置")
    total = got.total_seconds() if hasattr(got, "total_seconds") else None
    if total is None:                      # 某些驱动回字符串 '08:00:00'
        parts = str(got).split(":")
        total = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if abs(total) < 1:
        raise SystemExit("✅ 服务器时区已经是 UTC（时差 0），**不需要平移**，脚本退出。")
    return timedelta(seconds=total)


def _already_done(conn) -> bool:
    try:
        n = conn.execute(
            text("SELECT COUNT(*) FROM operation_logs WHERE action = :a"), {"a": MARKER_ACTION}
        ).scalar()
    except Exception:  # noqa: BLE001 - 表不存在时按"没跑过"
        return False
    return bool(n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True, help="SQLAlchemy DSN（只支持 MySQL）")
    ap.add_argument("--apply", action="store_true", help="真的改数据（默认只 dry-run）")
    ap.add_argument("--backup-confirmed", action="store_true", help="我已备份（--apply 时必须）")
    ap.add_argument("--force", action="store_true", help="已有标记也照跑（只在确认跑错时用）")
    a = ap.parse_args()

    if not a.dsn.startswith("mysql"):
        raise SystemExit("❌ 只支持 MySQL：本机 SQLite 的 CURRENT_TIMESTAMP 本来就是 UTC，平移会改坏数据")

    engine = create_engine(a.dsn)
    with engine.connect() as conn:
        offset = _server_offset(conn)
        cols = _columns_to_shift(conn)
        print(f"服务器时差 = {offset}（库端时间比 UTC 快这么多，这次要把它减掉）")
        print(f"待平移的列 {len(cols)} 个（清单由 information_schema 算出）\n")

        plan = []
        for tbl, col in cols:
            row = conn.execute(
                text(f"SELECT COUNT(*), MIN(`{col}`), MAX(`{col}`) FROM `{tbl}`")  # noqa: S608
            ).fetchone()
            if row is None or not row[0]:
                continue
            plan.append((tbl, col, int(row[0]), row[1], row[2]))

        for tbl, col, n, lo, hi in plan:
            print(f"  {tbl}.{col:12s} {n:8d} 行   {lo} → {hi}")

        if not plan:
            print("\n（没有需要平移的行）")
            return 0

        if _already_done(conn) and not a.force:
            raise SystemExit(
                "\n⛔ 库里已经有平移标记（operation_logs.action='TIME_BASE_SHIFTED_UTC'）——"
                "**拒绝再跑**（再减 8 小时会把数据改坏）。确认确实跑错了才用 --force。"
            )

        if not a.apply:
            print(
                "\n（dry-run，没有改任何数据）\n"
                "真跑之前先备份，例如：\n"
                "  mysqldump -usorders -p --single-transaction --routines sorders "
                "> /root/backup-before-utc-shift-$(date +%Y%m%d-%H%M%S).sql\n"
                "然后：  ... --apply --backup-confirmed"
            )
            return 0

        if not a.backup_confirmed:
            raise SystemExit("\n⛔ --apply 必须同时给 --backup-confirmed（这是一次不可逆的数据改动）")

        for tbl, col, n, _lo, _hi in plan:
            with engine.begin() as tx:
                tx.execute(
                    text(
                        f"UPDATE `{tbl}` SET `{col}` = DATE_SUB(`{col}`, INTERVAL :secs SECOND) "  # noqa: S608
                        f"WHERE `{col}` IS NOT NULL"
                    ),
                    {"secs": int(offset.total_seconds())},
                )
            print(f"✅ 已平移 {tbl}.{col}（{n} 行）")

        with engine.begin() as tx:
            tx.execute(
                text(
                    "INSERT INTO operation_logs (operator_id, action, change_content, created_at) "
                    "SELECT MIN(id), :a, :c, UTC_TIMESTAMP() FROM users"
                ),
                {"a": MARKER_ACTION, "c": f"库端时钟列整体减去 {offset}，使全库时间基准统一为 UTC"},
            )
        print(f"\n✅ 全部完成，并写了幂等标记（{MARKER_ACTION}）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
