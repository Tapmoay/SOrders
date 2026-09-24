#!/usr/bin/env python3
"""_drill_local.py —— 在本机一条命令触发**生产机上的恢复演练**，并把结论带回来。

它只是"遥控器"：真正的演练逻辑在生产机的 _drill.sh 里（那边才有库、有 venv、有服务）。
这样分工的理由：演练必须在生产环境跑（同版本 MySQL、同份 .env、同份代码），
但人不一定坐在服务器前面 —— 遥控器让这件事变成一条命令，而不是一次"有空再做"。

用法：
    python _tools/backup/_drill_local.py                 # 用最新一份备份演练
    python _tools/backup/_drill_local.py --skip-boot     # 只验库内不变式（快）
    python _tools/backup/_drill_local.py --keep          # 保留演练库，排查用
    python _tools/backup/_drill_local.py --backup /opt/sorders-backup/weekly/20260924T031500Z
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools" / "ops"))
import _prodssh  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")           # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="遥控生产机上跑一次恢复演练")
    ap.add_argument("--backup", help="指定备份目录（缺省＝最新一份可用备份）")
    ap.add_argument("--skip-boot", action="store_true", help="只验库内不变式")
    ap.add_argument("--keep", action="store_true", help="保留演练库/日志（排查用）")
    ap.add_argument("--verify-migrations", action="store_true",
                    help="顺带在**真 MySQL** 上验一次仓库里这份 app/migrations（生产代码不动）")
    args = ap.parse_args(argv)

    env_prefix = ""
    if args.verify_migrations:
        # 把仓库里这份 migrations 送到生产机的一个临时目录；演练时它会覆盖到
        # "生产代码的一份拷贝"上再跑（见 _drill.sh ②b）—— 目的是让**方言相关**的建表语句
        # （MySQL 那版带 COMMENT/CHAR(64)）在真 MySQL 8 上过一遍，而不只是本机的 SQLite。
        src = ROOT / "backend" / "app" / "migrations"
        remote = _prodssh.BACKUP_ROOT + "/drill-migrations"
        _prodssh.ssh_script(f"rm -rf {remote} && mkdir -p {remote}")
        _prodssh.scp_to(src, remote, recursive=True)
        _prodssh.ssh_script(f"rm -rf {remote}/migrations/__pycache__")
        env_prefix = f"MIGRATIONS_SRC={remote}/migrations "
        print("已上传仓库里的 app/migrations 到 " + remote + "（演练时在真 MySQL 上验一次）")

    cmd = "bash " + _prodssh.BACKUP_ROOT + "/bin/_drill.sh"
    if args.backup:
        cmd += " --backup " + args.backup
    if args.skip_boot:
        cmd += " --skip-boot"
    if args.keep:
        cmd += " --keep"

    print("遥控生产机演练：" + env_prefix + cmd)
    print("（演练会恢复一份完整备份并真的起一个隔离实例，通常 1~3 分钟）")
    print("")
    try:
        r = _prodssh.ssh_script(env_prefix + cmd, timeout=1800)
    except _prodssh.ProdShellError as e:
        print(str(e))
        return 1
    out = r.stdout.decode("utf-8", "replace")
    print(out)
    m = re.search(r"^DRILL=(.+)$", out, re.M)
    if not m:
        print("⛔ 演练输出里没有 DRILL= 结论行 —— 按失败处理（结论必须机器可判）")
        return 2
    verdict = m.group(1).strip()
    print("演练结论：" + verdict)
    return 0 if verdict.startswith("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
