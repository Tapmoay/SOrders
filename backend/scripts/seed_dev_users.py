"""开发环境：写入与 tests/conftest 一致的测试账号（若手机号已存在则跳过）。"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许从 backend/ 根目录运行: python scripts/seed_dev_users.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

import app.models  # noqa: F401 — register models
from app.core.security import hash_password
from app.database import SessionLocal
from app.models import User
from app.models.enums import UserRole

DEV_USERS: list[tuple[str, str, str, UserRole]] = [
    ("13800000001", "pass12345", "Dispatcher", UserRole.DISPATCHER),
    ("13800000002", "pass12345", "Shipper", UserRole.SHIPPER),
    ("13800000003", "pass12345", "Driver", UserRole.DRIVER),
]


def main() -> None:
    pw = hash_password("pass12345")
    db = SessionLocal()
    try:
        for phone, _pwd, full_name, role in DEV_USERS:
            exists = db.scalars(select(User).where(User.phone == phone)).first()
            if exists:
                print(f"skip (exists): {phone} {role.value}")
                continue
            db.add(
                User(
                    username=phone,
                    phone=phone,
                    password_hash=pw,
                    full_name=full_name,
                    role=role,
                )
            )
            print(f"created: {phone} ({role.value})")
        db.commit()
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
