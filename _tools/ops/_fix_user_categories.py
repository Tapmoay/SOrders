# -*- coding: utf-8 -*-
"""把 users.category 按身份重算一遍（自动分类的**一次性回填**）。

用户 2026-10-11 的口径：分类是身份的投影，不该由人挑。
本脚本只做一件事：按 `services/user_category.py::auto_category` 的规则把每一行的 category 纠正过来，
并打印 改前 → 改后（分类错了的那几行一眼可见）。

用法：`python -X utf8 _tools/ops/_fix_user_categories.py [--apply]`（不给 --apply 只报告）。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.user_category import auto_category  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只报告）")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = db.query(User).order_by(User.id).all()
        changed = 0
        for u in rows:
            want = auto_category(u.role, u.is_member, u.vehicle_type)
            if (u.category or "") != want:
                changed += 1
                print("  #%s %s 身份=%s%s 分类：%r → %r" % (
                    u.id, u.full_name or u.phone, getattr(u.role, "value", u.role),
                    "（高级货主）" if u.is_member else "",
                    u.category or "", want))
                if args.apply:
                    u.category = want
        if args.apply:
            db.commit()
        print("共 %d 个账号，需纠正 %d 个%s" % (len(rows), changed, "" if args.apply else "（未写库，加 --apply 才写）"))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())