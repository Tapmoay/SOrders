"""在**本地开发库**里造一个已知密码的派单员账号，用于实测。

⚠️ 只对 backend/.env 指向的 SQLite 开发库生效；检测到非 sqlite 会直接拒绝执行。
用法：python _mk_test_dispatcher.py [手机号] [密码]
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

sys.path.insert(0, str(repo_root() / "backend"))

DB = repo_root() / "backend" / "sorders.db"
PHONE = sys.argv[1] if len(sys.argv) > 1 else "13900000001"
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else "test1234"
USERNAME = "aitest_disp"


def main() -> int:
    if not DB.exists():
        print(f"找不到开发库 {DB}")
        return 1
    # 安全护栏：只允许 sqlite 文件（本地开发库）
    with open(DB, "rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            print("拒绝执行：目标不是 SQLite 库")
            return 1

    from passlib.context import CryptContext

    pwd_hash = CryptContext(schemes=["bcrypt"], deprecated="auto").hash(PASSWORD)

    con = sqlite3.connect(DB)
    cur = con.cursor()
    row = cur.execute("SELECT id FROM users WHERE phone=?", (PHONE,)).fetchone()
    now = datetime.now(timezone.utc).isoformat(sep=" ", timespec="seconds")
    if row:
        cur.execute(
            "UPDATE users SET password_hash=?, role='DISPATCHER', is_active=1 WHERE id=?",
            (pwd_hash, row[0]),
        )
        print(f"已更新既有账号 id={row[0]} phone={PHONE} -> 密码重置，角色=DISPATCHER")
    else:
        cur.execute(
            "INSERT INTO users (username, phone, password_hash, full_name, role, is_active, is_member, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (USERNAME, PHONE, pwd_hash, "AI测试派单员", "DISPATCHER", 1, 0, now, now),
        )
        print(f"已创建派单员 id={cur.lastrowid} username={USERNAME} phone={PHONE}")
    con.commit()
    con.close()
    print(f"\n登录用：phone={PHONE}  password={PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
