"""把本地开发库里几个测试账号的密码统一成 **123321**（用户的约定），只对 SQLite 开发库生效。

为什么需要它：探针脚本要登录真后端，而账号密码是用户后来统一改的。
**不要**在这里造新账号或改角色——只把密码对齐，其余字段一律不碰。

用法：python _tools/ai/_reset_probe_passwords.py
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

DB = repo_root() / "backend" / "sorders.db"
if DB.read_bytes()[:16] != b"SQLite format 3\x00":
    raise SystemExit("拒绝执行：目标不是 SQLite 开发库")

PASSWORD = "123321"
# 1=派单员 2=货主 3=司机（模拟器上的三个演示账号）+ 121=AI 测试派单员
IDS = (1, 2, 3, 121)

from passlib.context import CryptContext  # noqa: E402

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto").hash(PASSWORD)
con = sqlite3.connect(DB)
marks = ",".join("?" * len(IDS))
con.execute(f"update users set password_hash=? where id in ({marks})", (pwd, *IDS))
con.commit()
for r in con.execute(f"select id,phone,role from users where id in ({marks})", IDS).fetchall():
    print(r)
print(f"密码已统一为 {PASSWORD}")
