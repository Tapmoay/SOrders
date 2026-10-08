"""开发环境：把三个测试手机号的口令重置成同一个值，并保证 username 与 phone 一致（便于登录）。

用法（在 backend 目录下）:
  python scripts/reset_dev_passwords.py                       # 用仓库口径 pass12345
  SORDERS_DEV_PASSWORD=123321 python scripts/reset_dev_passwords.py   # 本机开发库现用 123321

口令的**唯一真相**是环境变量 `SORDERS_DEV_PASSWORD`，缺省 `pass12345`
（与 `scripts/seed_dev_users.py`、`backend/tests/conftest.py`、README 的测试账号表一致 ——
一份库里三个脚本不该给出两个口令）。
⛔ 不要把本机在用的口令写死回源码里：这台机器的开发库 2026-10-08 起被改成 `123321`
（三个测试号 + 王大力），所以本机要用上面第二条命令。

若登录仍提示「用户名或密码错误」，先执行本脚本再试。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.security import hash_password
from app.database import SessionLocal
from app.models import User
from app.models.enums import UserRole

PHONES: list[tuple[str, str, UserRole]] = [
    ("13800000001", "Dispatcher", UserRole.DISPATCHER),
    ("13800000002", "Shipper", UserRole.SHIPPER),
    ("13800000003", "Driver", UserRole.DRIVER),
]
PLAIN = os.environ.get("SORDERS_DEV_PASSWORD", "pass12345")


def main() -> None:
    h = hash_password(PLAIN)
    db = SessionLocal()
    try:
        for phone, full_name, role in PHONES:
            u = db.scalars(select(User).where(User.phone == phone)).first()
            if u is None:
                db.add(
                    User(
                        username=phone,
                        phone=phone,
                        password_hash=h,
                        full_name=full_name,
                        role=role,
                    )
                )
                print(f"created: {phone} ({role.value}) password={PLAIN}")
            else:
                u.password_hash = h
                u.username = phone
                u.full_name = full_name or u.full_name
                u.role = role
                u.is_active = True
                print(f"reset: {phone} ({role.value}) password={PLAIN}")
        db.commit()
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
