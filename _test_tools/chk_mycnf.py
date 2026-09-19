import subprocess
# 查看 my.cnf 存在性
r = subprocess.run(["ls", "-la", "/etc/my.cnf"], capture_output=True, text=True)
print(r.stdout.strip() or r.stderr.strip())

# 如果 my.cnf 存在，检查是否有 [mysqld] 段；没有就添加
r2 = subprocess.run(["grep", "-c", "max_connections", "/etc/my.cnf"], capture_output=True, text=True)
print("has max_connections:", r2.stdout.strip())