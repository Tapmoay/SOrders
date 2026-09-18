import subprocess
import sys
# 找到 MySQL 配置文件
r = subprocess.run(["grep", "-rn", "max_connections", "/etc/my.cnf", "/etc/my.cnf.d/", "/etc/mysql/"], capture_output=True, text=True)
print("grep:", r.stdout.strip()[:500] or r.stderr.strip()[:300])

r2 = subprocess.run(["mysql", "-usorders", "-psorders123", "-e", "SHOW VARIABLES LIKE 'max_connections'"], capture_output=True, text=True)
print("current:", r2.stdout.strip() or r2.stderr.strip()[:200])