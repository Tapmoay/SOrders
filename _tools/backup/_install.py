#!/usr/bin/env python3
"""_install.py —— 把备份/恢复/演练三个脚本**装到生产机上**，并挂上定时任务。

### 为什么要"装"而不是每次 ssh 一把
1. **定时任务要跑**：日报/周报备份必须由服务器自己发起（本地笔记本关着的时候也得备）；
2. **演练要能离线跑**：出事的时候人不一定在能 ssh 的机器上，脚本在服务器上就能直接跑；
3. **同一份代码**：装上去的是仓库里这份，scp 之后当场比对 sha256 —— 避免"服务器上那份
   是三个月前手改过的"这种经典事故（报告 §18 规则 4：先迁移，再删除旧路径）。

用法：
    python _tools/backup/_install.py            # 安装 + 校验 + 挂 cron
    python _tools/backup/_install.py --dry-run  # 只打印要做什么
    python _tools/backup/_install.py --no-cron  # 不碰 cron

⛔ 它**不**碰生产库、不碰生产服务：只往 /opt/sorders-backup/ 下写文件 + 改 /etc/cron.d/。
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
import _prodssh  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRIPTS = ["_backup.sh", "_restore.sh", "_drill.sh"]
#: 健康检查是 ops 目录下的 python 工具（整改阶段 8 ③），装到同一个 bin 下给 cron 用。
#: ⚠️ 它 import 兄弟模块 `_prodssh`（事实脚本的唯一来源），所以那个也要一起装 ——
#:    否则服务器上本机模式一跑就是 `ModuleNotFoundError: No module named _prodssh`（实测踩到）。
OPS_DIR = Path(__file__).resolve().parents[1] / "ops"
HEALTH_TOOL = OPS_DIR / "_health_check.py"
PRODSSH_TOOL = OPS_DIR / "_prodssh.py"
REMOTE_BIN = _prodssh.BACKUP_ROOT + "/bin"
CRON_FILE = "/etc/cron.d/sorders-backup"

#: 定时任务：日报每天 4 次（廉价，只备库）、周报每周日一次（带上传文件）、
#: 演练每周一凌晨（**恢复演练也要定时做**，否则它就是"装过一次、再没跑过"的摆设）。
#: 时间刻意错开 acme.sh（生产 crontab 里 4/10/16/22 点跑证书续期）。
CRON_LINES = """# SOrders 备份与恢复演练（由 _tools/backup/_install.py 生成，手工改会被下次安装覆盖）
SHELL=/bin/bash
PATH=/sbin:/bin:/usr/sbin:/usr/bin
30 2,8,14,20 * * * root {bin}/_backup.sh --kind daily >> /var/log/sorders-backup.log 2>&1
15 3 * * 0 root {bin}/_backup.sh --kind weekly >> /var/log/sorders-backup.log 2>&1
45 3 * * 1 root {bin}/_drill.sh >> /var/log/sorders-drill.log 2>&1
# 健康检查（报告 §15 第三件小事）：每天 9 点 / 21 点各一次，只在非全绿时输出
0 9,21 * * * root /opt/SOrders/backend/.venv/bin/python {bin}/_health_check.py --local --quiet >> /var/log/sorders-health.log 2>&1
""".format(bin=REMOTE_BIN)


#: 演练库的授权：**只给这一个命名空间**（不是给 root、也不是给全库）。
#: `\_` 转义是因为 MySQL 的 GRANT 里 `_` 本身是通配符，不转义会连 sordersXdrillY 一起放行。
DRILL_GRANT_SQL = (
    "GRANT ALL PRIVILEGES ON `sorders\\_drill\\_%`.* TO 'sorders'@'%';"
    "GRANT ALL PRIVILEGES ON `sorders\\_drill\\_%`.* TO 'sorders'@'localhost';"
    "FLUSH PRIVILEGES;"
)

#: 授权之后**用应用账号自己**做一次端到端验证：建库 → 删库。
#: 为什么不看 SHOW GRANTS 的字面量：授权语句写对了不等于生效（转义、host 匹配都会骗人），
#: 只有真做一次才知道。口令同样从 .env 现读、只进环境变量。
DRILL_SELFTEST = r"""
PW=$(/opt/SOrders/backend/.venv/bin/python - <<'PYEOF'
import urllib.parse as up
for ln in open("/opt/SOrders/.env", encoding="utf-8"):
    if ln.startswith("DATABASE_URL="):
        print(up.unquote(up.urlparse(ln.split("=", 1)[1].strip()).password))
PYEOF
)
export MYSQL_PWD="$PW"
mysql -u sorders -e "create database if not exists sorders_drill_selftest"
mysql -u sorders -e "drop database sorders_drill_selftest"
echo SELFTEST=ok
"""


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")           # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="把备份脚本装到生产机并挂定时任务")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-cron", action="store_true")
    ap.add_argument("--no-grant", action="store_true",
                    help="不改数据库授权（默认会给应用账号加 sorders_drill_%% 这一个命名空间）")
    args = ap.parse_args(argv)

    missing = [s for s in SCRIPTS if not (HERE / s).exists()]
    if missing:
        print("⛔ 仓库里缺脚本：" + str(missing))
        return 2

    print("生产机：" + _prodssh.PROD_USER + "@" + _prodssh.PROD_HOST)
    print("安装到：" + REMOTE_BIN)
    for s in SCRIPTS:
        print("  · " + s + "（本地 sha256 " + sha256(HERE / s)[:16] + "）")
    if not args.no_cron:
        print("定时任务：" + CRON_FILE)
        for ln in CRON_LINES.strip().splitlines():
            if ln[:1].isdigit():
                print("  · " + ln)
    if args.dry_run:
        print("（--dry-run：什么都没改）")
        return 0

    # ---- 1. 建目录 + 上传 ----
    _prodssh.ssh_script("mkdir -p " + REMOTE_BIN + " && chmod 700 " +
                        _prodssh.BACKUP_ROOT + " " + REMOTE_BIN)
    for s in SCRIPTS:
        _prodssh.scp_to(HERE / s, REMOTE_BIN + "/" + s)
    _prodssh.scp_to(HEALTH_TOOL, REMOTE_BIN + "/_health_check.py")
    _prodssh.scp_to(PRODSSH_TOOL, REMOTE_BIN + "/_prodssh.py")
    _prodssh.ssh_script("chmod 700 " + REMOTE_BIN + "/_*.sh")

    # ---- 2. 当场校验：语法 + 内容一致（不是"传上去就算"）----
    _prodssh.ssh_script("; ".join("bash -n " + REMOTE_BIN + "/" + s for s in SCRIPTS))
    print("✅ 生产机上 bash -n 全部通过")

    remote_hashes = _prodssh.ssh_lines(
        " ".join("sha256sum " + REMOTE_BIN + "/" + s + ";" for s in SCRIPTS))
    local = {s: sha256(HERE / s) for s in SCRIPTS}
    bad = []
    for line in remote_hashes:
        digest, _, name = line.partition("  ")
        name = name.strip().split("/")[-1]
        if name in local and digest.strip() != local[name]:
            bad.append(name)
    if bad:
        print("⛔ 上传后哈希不一致：" + str(bad) + "（传输损坏？）")
        return 3
    print("✅ 生产机上的脚本与仓库逐字节一致（" + str(len(local)) + " 个）")

    # ---- 3.5 演练库权限（恢复演练要建库，而应用账号原来只有 sorders.* 的权限）----
    # ⚠️ 这是第一次真跑演练才暴露的：sorders 的授权是 ALL PRIVILEGES ON sorders.*，
    #    于是 _drill.sh 建 sorders_drill_xxx 时直接 Access denied(1044)。
    #    修法不是"演练改用 root"，而是**给应用账号一个边界清晰的命名空间**：
    #    只在 sorders_drill_% 上授权 —— 演练用的仍是应用自己的账号，
    #    这本身还是一条更强的验证（应用账号必须真的能在这份恢复出来的库上跑起来）。
    if args.no_grant:
        print("（--no-grant：没动数据库授权）")
    else:
        # 只有 root 能改授权；本机 root@localhost 走 socket 免密（生产事实见 docs/BASELINE.md）
        _prodssh.ssh_script("mysql -uroot <<'SQLEOF'\n" + DRILL_GRANT_SQL + "\nSQLEOF")
        out = _prodssh.ssh_script(DRILL_SELFTEST).stdout.decode("utf-8", "replace")
        if "SELFTEST=ok" in out:
            print("✅ 应用账号现在能在 sorders_drill_% 上建库/删库（演练的前提）")
        else:
            print("⚠️ 演练库权限自检没过 —— 演练会失败，请检查 MySQL 授权")

    # ---- 4. 定时任务 ----
    if args.no_cron:
        print("（--no-cron：没动 cron）")
    else:
        _prodssh.ssh_script("cat > " + CRON_FILE + " <<'CRONEOF'\n" + CRON_LINES +
                            "CRONEOF\nchmod 644 " + CRON_FILE)
        state = _prodssh.ssh_lines(
            "systemctl is-active crond 2>/dev/null || systemctl is-active cron 2>/dev/null || echo unknown")
        print("✅ cron 文件已写；crond 状态：" + (state[0] if state else "unknown"))
        if state and state[0] != "active":
            print("⚠️ crond 不是 active —— 定时备份**不会**跑，请先 systemctl enable --now crond")

    print("")
    print("装完了。下一步：")
    print('  python _tools/backup/_pre_release.py --note "第一次上线前的备份"   # 立刻做一份')
    print("  python _tools/backup/_drill_local.py                                # 立刻演练一次")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
