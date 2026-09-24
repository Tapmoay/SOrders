"""`python -m app.migrations` —— 迁移的命令行入口（生产上排障/发布时用）。

```bash
python -m app.migrations status      # 当前版本 / 待跑 / 内容变过的
python -m app.migrations upgrade     # 手动把待跑的跑掉（正常由启动自动跑）
python -m app.migrations upgrade --dry-run
python -m app.migrations --json status
```

⚠️ **不 import `app.database`**：那个模块在导入时就 `bootstrap_schema(engine)`（建表 + 全部自愈），
而本命令必须能在"库还没准备好/只想看一眼版本"的时候跑。所以这里自己按 `settings.database_url` 建引擎。
"""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import create_engine

from app.config import get_settings
from app.migrations import migration_status, run_migrations


def _engine(url: str | None):
    # ⚠️ `app.config` 里**没有**模块级 `settings`，只有 `get_settings()`（2026-09-24 实测：
    #    写成 `from app.config import settings` 时这条命令**直接起不来**，而那时它还没被人跑过）。
    return create_engine(url or get_settings().database_url, future=True)


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")           # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="python -m app.migrations", description="数据库迁移版本管理")
    ap.add_argument("command", choices=["status", "upgrade"])
    ap.add_argument("--url", help="数据库 URL（缺省读 settings.database_url）")
    ap.add_argument("--dry-run", action="store_true", help="只列出要跑哪些，不执行")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    engine = _engine(args.url)
    if args.command == "upgrade":
        report = run_migrations(engine, dry_run=args.dry_run)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            for item in report["applied"]:
                print(("（dry-run）将会执行 " if args.dry_run else "已执行 ") +
                      f"{item['version']:03d}_{item['name']}" +
                      (f"（{item['duration_ms']} ms）" if item.get("duration_ms") is not None else ""))
            for v in report["drifted"]:
                print(f"⛔ 版本 {v:03d} 的文件内容与库里记录的不一致（已经跑过的迁移不许再改）")
            if not report["applied"] and not report["drifted"]:
                print("没有待跑的迁移。")
        return 1 if report["drifted"] else 0

    st = migration_status(engine)
    if args.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
    else:
        print(f"当前版本：{st['current']}")
        print(f"已应用：{len(st['applied'])} 条")
        for a in st["applied"]:
            print(f"  ✅ {a['version']:03d} {a['name']}（{a['duration_ms']} ms，{a['checksum'][:12]}）")
        if st["pending"]:
            print(f"待跑：{len(st['pending'])} 条")
            for m in st["pending"]:
                print(f"  ⏳ {m['version']:03d} {m['name']}")
        for d in st["drifted"]:
            print(f"  ⛔ {d['version']:03d} {d['name']}：库里 {d['db_checksum'][:12]} / 文件 {d['file_checksum'][:12]}")
        if st["unknown_in_db"]:
            print(f"  ⚠️ 库里有、仓库里没有的版本号：{st['unknown_in_db']}（有人在别的分支跑过迁移？）")
    # 退出码口径：drifted 与 unknown 都算"需要人看一眼"，但**待跑的不算失败**（启动时会自动跑）
    return 1 if (st["drifted"] or st["unknown_in_db"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
