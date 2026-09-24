#!/usr/bin/env python3
"""_prodssh.py —— 与生产机通信的**唯一一处**（主机 / 密钥 / 路径常量都在这里）。

### 为什么单独成文件
报告（docs/ARCHITECTURE_RECTIFICATION.md §18 规则 5）要求"任何自动化工具都必须自己可验证"；
而本项目已经反复栽在"同一个事实写两遍"上（端点表、权限表、检查清单）。
生产主机名、SSH 密钥路径、仓库目录、上传目录、备份根目录一旦散落在 backup / baseline / deploy
三处，改一次要改三处 —— 而**漏掉的那一处会在半夜做恢复的时候才暴露**。

所以：**凡是"生产上是什么"的常量，只在这里写一次**，其余脚本一律 import。

### 三条纪律（照 AGENTS.md）
1. ⛔ **口令不进源码**（仓库是公开的）：数据库口令从生产 .env 的 DATABASE_URL 现读，
   read_env() 拿到的口令**只用于拼子进程环境变量，绝不打印**；masked_db_url() 是唯一
   可以进日志的形态。_tools/qa/_check_secrets.py 会在自检里拦"命令行内联口令"。
2. ⛔ **默认只读**：本文件不做任何隐式改动的默认——写操作由调用方（备份/演练/回滚）自己声明。
3. ⛔ **不吞错误**：ssh 失败要抛 ProdShellError（带 exit code + stderr 尾部），
   不许"命令失败但脚本继续往下走" —— 备份脚本静默失败等于没有备份。
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

# ---------------------------------------------------------------- 生产事实（唯一一处）
PROD_HOST = os.environ.get("SORDERS_PROD_HOST", "8.145.40.22")
PROD_USER = os.environ.get("SORDERS_PROD_USER", "root")
SSH_KEY = Path(os.environ.get("SORDERS_SSH_KEY", str(Path.home() / ".ssh" / "id_ed25519_sorders")))

APP_DIR = "/opt/SOrders"
BACKEND_DIR = f"{APP_DIR}/backend"
ENV_FILE = f"{APP_DIR}/.env"
UPLOADS_DIR = f"{BACKEND_DIR}/uploads"
VENV_PY = f"{BACKEND_DIR}/.venv/bin/python"
SERVICE = "sorders-api"

DB_NAME = "sorders"
BACKUP_ROOT = os.environ.get("SORDERS_BACKUP_ROOT", "/opt/sorders-backup")
#: 演练用的临时库前缀：**必须**能一眼看出是演练库，否则有人会把它当生产库连上去。
DRILL_DB_PREFIX = "sorders_drill_"

SSH_COMMON = [
    "-i", str(SSH_KEY),
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "ConnectTimeout=15",
]


class ProdShellError(RuntimeError):
    """ssh 段失败。带 exit code 与 stderr 尾部——排障时最需要的就是这两样。"""


def ssh_script(script: str, *, timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess:
    """把一段 bash 脚本送到生产机上以 bash -s 执行（stdin 传输，**不做字符串拼接**）。

    为什么用 stdin 而不是 ssh host "…"：本项目的脚本里有大量中文注释与引号，
    经 Windows 的 subprocess → ssh → 远端 bash 三层转义后必然出错
    （AGENTS.md 记着同形状的坑：PowerShell 往返把中文写坏）。stdin 只有一层，且是字节透传。
    """
    r = subprocess.run(
        ["ssh", *SSH_COMMON, f"{PROD_USER}@{PROD_HOST}", "bash -s"],
        input=script.encode("utf-8"),
        capture_output=True, timeout=timeout,
    )
    if check and r.returncode != 0:
        raise ProdShellError(
            f"生产机脚本失败（exit {r.returncode}）：\n"
            f"--- stdout 尾部 ---\n{_tail(r.stdout)}\n--- stderr 尾部 ---\n{_tail(r.stderr)}")
    return r


def ssh_lines(script: str, *, timeout: int = 300) -> list[str]:
    """跑一段只打印结果的脚本，返回非空行（去掉首尾空白）。"""
    r = ssh_script(script, timeout=timeout)
    return [ln.strip() for ln in r.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]


def scp_from(remote: str, local: Path, *, timeout: int = 900) -> Path:
    """从生产机取文件到本机（备份产物落到本地留档时用）。"""
    local.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["scp", *SSH_COMMON, f"{PROD_USER}@{PROD_HOST}:{remote}", str(local)],
        capture_output=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise ProdShellError(f"scp 失败（exit {r.returncode}）：{_tail(r.stderr)}")
    return local


def scp_to(local: Path, remote: str, *, recursive: bool = False, timeout: int = 900) -> None:
    """把本机文件（或目录，recursive=True）送到生产机（备份脚本本体 / 演练用的代码副本）。"""
    r = subprocess.run(
        ["scp", *(["-r"] if recursive else []), *SSH_COMMON, str(local), f"{PROD_USER}@{PROD_HOST}:{remote}"],
        capture_output=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise ProdShellError(f"scp 失败（exit {r.returncode}）：{_tail(r.stderr)}")


# ---------------------------------------------------------------- .env / 数据库口令
def read_env() -> dict[str, str]:
    """读生产 .env 的键值（**只读键名与结构，值一律不外传**）。

    ⚠️ 返回的 dict 里含真实口令，**不要 print 它**。要进日志用 masked_db_url()。
    ⛔ 不把它写进任何文件：备份产物里也不需要口令（恢复时从当时的 .env 读）。
    """
    r = ssh_script(f"cat {shlex.quote(ENV_FILE)}")
    out: dict[str, str] = {}
    for ln in r.stdout.decode("utf-8", "replace").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def parse_db_url(url: str) -> dict[str, str]:
    """拆 mysql+pymysql://user:pw@host:port/db。

    为什么不直接用 SQLAlchemy 的 make_url：本脚本要能在**没装后端依赖**的机器上跑
    （恢复演练经常是在一台干净的跳板机上做的），所以不引入依赖。
    """
    _scheme, rest = url.split("://", 1)
    creds, hostpart = rest.split("@", 1)
    user, _, password = creds.partition(":")
    hostport, _, db = hostpart.partition("/")
    host, _, port = hostport.partition(":")
    return {"scheme": _scheme, "user": user, "password": password,
            "host": host or "127.0.0.1", "port": port or "3306", "db": db or DB_NAME}


def masked_db_url(url: str) -> str:
    """可以进日志/文档的形态：口令换成 ***。"""
    try:
        p = parse_db_url(url)
    except Exception:                                     # noqa: BLE001 —— 畸形 URL 也别把原文打出来
        return "<DATABASE_URL 解析失败>"
    return f"{p['scheme']}://{p['user']}:***@{p['host']}:{p['port']}/{p['db']}"


def _tail(b: bytes, n: int = 4000) -> str:
    s = b.decode("utf-8", "replace")
    return s[-n:] if len(s) > n else s


# ---------------------------------------------------------------- 只读事实采集（基线用）
#: 模板占位符 @SERVICE@ / @DB@ / @UPLOADS@ / @BACKUP_ROOT@ —— 用 **raw 字符串 + replace**
#: 而不是 f-string：脚本里有大量 awk 的 {} 与 shell 的 ${}，f-string 会把它们全当表达式。
_FACTS_TEMPLATE = r"""set +e
emit() { printf '%s=%s\n' "$1" "$2"; }
emit host "$(hostname)"
emit date "$(date -Is)"
emit uptime_days "$(awk '{print int($1/86400)}' /proc/uptime)"
emit os "$(. /etc/os-release; echo $PRETTY_NAME)"
emit kernel "$(uname -r)"
emit cpu "$(nproc)"
emit mem_mb "$(awk '/MemTotal/{printf "%d", $2/1024}' /proc/meminfo)"

# ---- 服务 ----
emit service_state "$(systemctl is-active @SERVICE@)"
emit service_since "$(systemctl show @SERVICE@ -p ActiveEnterTimestamp --value)"
emit service_restarts "$(systemctl show @SERVICE@ -p NRestarts --value)"
emit service_hash "$(systemctl cat @SERVICE@ 2>/dev/null | sha256sum | cut -c1-16)"
emit api_health "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
emit api_health_body "$(curl -s http://127.0.0.1:8000/health | head -c 200)"
emit api_paths "$(curl -s http://127.0.0.1:8000/openapi.json | python3 -c 'import sys,json;print(len(json.load(sys.stdin).get("paths",{})))' 2>/dev/null)"

# ---- 数据库 ----
emit mysql_version "$(mysql --version | sed 's/.*Distrib //;s/,.*//')"
emit db_tables "$(mysql -N -B -e "select count(*) from information_schema.tables where table_schema='@DB@';" 2>/dev/null)"
emit db_size_mb "$(mysql -N -B -e "select round(sum(data_length+index_length)/1024/1024,1) from information_schema.tables where table_schema='@DB@';" 2>/dev/null)"
emit db_orders "$(mysql -N -B -e "select count(*) from @DB@.orders;" 2>/dev/null)"
emit db_ledgers "$(mysql -N -B -e "select count(*) from @DB@.ledgers;" 2>/dev/null)"
emit db_users "$(mysql -N -B -e "select count(*) from @DB@.users;" 2>/dev/null)"
emit db_products "$(mysql -N -B -e "select count(*) from @DB@.products;" 2>/dev/null)"
emit db_tables_list "$(mysql -N -B -e "select table_name from information_schema.tables where table_schema='@DB@' order by table_name;" 2>/dev/null | tr '\n' ',')"

# ---- redis ----
emit redis_version "$(redis-cli -h 127.0.0.1 -p 6379 info server 2>/dev/null | awk -F: '/redis_version/{print $2}' | tr -d '\r')"
emit redis_maxmemory "$(redis-cli -h 127.0.0.1 -p 6379 config get maxmemory 2>/dev/null | tail -1)"
emit redis_requirepass_len "$(redis-cli -h 127.0.0.1 -p 6379 config get requirepass 2>/dev/null | tail -1 | wc -c)"

# ---- nginx / 证书 ----
emit nginx_version "$(nginx -v 2>&1 | sed 's#nginx version: ##')"
emit nginx_config_hash "$(nginx -T 2>/dev/null | sha256sum | cut -c1-32)"
for c in /etc/nginx/ssl/sorders-ip-chain.crt /etc/letsencrypt/live/sorders.top/fullchain.pem /etc/letsencrypt/live/sorders.top-0001/fullchain.pem; do
  if [ -f "$c" ]; then
    name=$(basename "$(dirname "$c")")
    emit "cert_${name}_end" "$(openssl x509 -in "$c" -noout -enddate 2>/dev/null | cut -d= -f2)"
    emit "cert_${name}_days_left" "$(openssl x509 -in "$c" -noout -enddate 2>/dev/null | cut -d= -f2 | xargs -I{} date -d {} +%s | awk -v n=$(date +%s) '{print int(($1-n)/86400)}')"
  fi
done

# ---- 磁盘 / 上传 / 备份 ----
emit disk_total "$(df -h / | awk 'NR==2{print $2}')"
emit disk_used "$(df -h / | awk 'NR==2{print $3}')"
emit disk_avail "$(df -h / | awk 'NR==2{print $4}')"
emit disk_pct "$(df -h / | awk 'NR==2{print $5}')"
emit uploads_size "$(du -sh @UPLOADS@ 2>/dev/null | cut -f1)"
emit uploads_files "$(find @UPLOADS@ -type f 2>/dev/null | wc -l)"
emit backup_root_size "$(du -sh @BACKUP_ROOT@ 2>/dev/null | cut -f1)"
emit backup_db_count "$(find @BACKUP_ROOT@ -name '*.sql.gz' 2>/dev/null | wc -l)"

# ---- 代码 ----
emit repo_commit "$(cd /opt/SOrders && git rev-parse HEAD 2>/dev/null)"
emit repo_branch "$(cd /opt/SOrders && git branch --show-current 2>/dev/null)"
emit repo_dirty "$(cd /opt/SOrders && git status --short 2>/dev/null | wc -l)"
emit repo_commit_date "$(cd /opt/SOrders && git log -1 --format=%cI 2>/dev/null)"

# ---- 定时任务 ----
emit crontab "$(crontab -l 2>/dev/null | grep -v '^#' | tr '\n' ';')"
"""


def prod_facts_script() -> str:
    """**只读**的生产事实采集脚本（基线用）。

    刻意全只读：这条路径会在"想起来了就跑一下"的场景里被反复执行，
    一旦它顺手写点什么，就再也没人敢跑了。输出格式是稳定的 key=value，
    解析方（_tools/baseline/_capture_baseline.py）只认这个格式。
    """
    return (_FACTS_TEMPLATE
            .replace("@SERVICE@", SERVICE)
            .replace("@DB@", DB_NAME)
            .replace("@UPLOADS@", UPLOADS_DIR)
            .replace("@BACKUP_ROOT@", BACKUP_ROOT))
