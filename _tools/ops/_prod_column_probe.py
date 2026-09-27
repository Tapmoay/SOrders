# -*- coding: utf-8 -*-
"""只读：生产库 orders 表上到底有没有 freight_rule_snapshot 这一列（R4-11 发布验收用）。

为什么要有它：健康检查报的「迁移版本 9」是**版本表**上的事实；而发布要证的是
**那一列真的在表上**。两件事只差一步，但正是这一步最容易出岔子
（迁移记了账、DDL 却没落地 —— 本项目为这件事专门有一条「失败不记账」的判据）。

⛔ 只读；生产事实只走 _prodssh 那一处；口令从生产 .env 现读、**绝不打印**。

用法：python _tools/ops/_prod_column_probe.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prodssh  # noqa: E402

TABLE = "orders"
COLUMN = "freight_rule_snapshot"


def main() -> int:
    env = _prodssh.read_env()
    url = env.get("DATABASE_URL", "")
    m = re.match(r"mysql\+?pymysql://([^:]+):([^@]+)@([^:/]+):?(\d+)?/(\w+)", url)
    if not m:
        print("读不出 DATABASE_URL 的形状（⛔ 不打印它）")
        return 1
    user, pwd, host, port, db = m.group(1), m.group(2), m.group(3), m.group(4) or "3306", m.group(5)
    prefix = ("cd " + _prodssh.BACKEND_DIR + " && MYSQL_PWD=" + pwd + " mysql -u" + user
              + " -h" + host + " -P" + port + " -N -B -e ")
    q1 = ("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='" + db
          + "' AND table_name='" + TABLE + "' AND column_name='" + COLUMN + "';")
    q2 = ("SELECT IFNULL(MAX(version), -1) FROM schema_versions;")
    q3 = ("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='" + db
          + "' AND table_name='" + TABLE + "';")
    got = _prodssh.ssh_lines(prefix + "\"" + q1 + "\" " + db
                             + " ; " + prefix + "\"" + q3 + "\" " + db
                             + " ; " + prefix + "\"" + q2 + "\" " + db)
    vals = [ln for ln in got if ln.strip()]
    if len(vals) < 3:
        print("读不到（生产 ssh 或 mysql 出问题了）：" + repr(vals))
        return 1
    print("生产 " + TABLE + "." + COLUMN + " 列数 = " + vals[0] + "（1 = 在）")
    print("生产 " + TABLE + " 总列数 = " + vals[1])
    print("生产 schema_versions 最高版本 = " + vals[2])
    return 0 if vals[0] == "1" else 1


if __name__ == "__main__":
    sys.exit(main())
