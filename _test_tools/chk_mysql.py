"""查服务器上 MySQL 的 max_connections（一次性排查脚本，当时在生产机上跑）。

⚠️ **这一版把口令从源码里拿掉了**：原来写的是 `mysql -usorders -p<真实口令>`，
而它被提交进了一个**公开仓库**——口令从此视为已泄露，必须**在服务器上换掉**
（换掉之后这个脚本照常能用，因为口令改从环境变量读）。

用法（在服务器上）：
    MYSQL_PWD='...' python chk_mysql.py
    # 或者更省事：把口令写进 ~/.my.cnf（600 权限），脚本什么都不用带
"""
import os
import subprocess

# 找到 MySQL 配置文件
r = subprocess.run(
    ["grep", "-rn", "max_connections", "/etc/my.cnf", "/etc/my.cnf.d/", "/etc/mysql/"],
    capture_output=True,
    text=True,
)
print("grep:", r.stdout.strip()[:500] or r.stderr.strip()[:300])

# ⚠️ 口令只从环境变量来，**不许再写回源码**（`_tools/qa/_check_secrets.py` 会扫）
pwd = os.environ.get("MYSQL_PWD")
if not pwd:
    print("跳过连接检查：没设 MYSQL_PWD（口令不进源码，见文件头的说明）")
    raise SystemExit(0)

r2 = subprocess.run(
    ["mysql", "-usorders", "-e", "SHOW VARIABLES LIKE 'max_connections'"],
    capture_output=True,
    text=True,
    env={**os.environ, "MYSQL_PWD": pwd},
)
print("current:", r2.stdout.strip() or r2.stderr.strip()[:200])
