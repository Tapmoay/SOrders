"""开发环境：将三个测试手机号的密码重置为 pass12345，并保证 username 与 phone 一致（便于登录）。

用法（在 backend 目录下）:
  python scripts/reset_dev_passwords.py

若登录仍提示「用户名或密码错误」，先执行本脚本再试。
"""

from __future__ import annotations

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
PLAIN = "pass12345"


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
