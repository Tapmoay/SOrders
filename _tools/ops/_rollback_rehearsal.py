# -*- coding: utf-8 -*-
"""回滚演练（R4-11 发布记录用）：**旧代码跑在带新列的库上** —— 只用一次，用完就删。

为什么要它：发布记录里说"回滚 = 回退代码 + 保留这一列"，那是一句**断言**。
用户 2026-09-27 的 ③ 要的是 **rollback evidence**，所以这里把断言跑成事实：

  ① 新代码把临时库迁到版本 9（freight_rule_snapshot 列出现）
  ② **旧代码**（上一个发布点）对着同一个库跑自己的 prepare_schema + 读一张订单
  ③ 旧代码不许报错 —— 报错就说明"保留这一列"这个承诺是假的

用法：python _tools/ops/_rollback_rehearsal.py <旧代码的工作树路径> <临时库路径> <阶段:new|old>

先建旧代码的工作树：
    git worktree add --detach <临时目录>/old <上一个发布点>
跑完记得收：
    git worktree remove --force <临时目录>/old
"""
import os
import sys
import tempfile
from pathlib import Path

stage = sys.argv[3]
# ⛔ root 一律**从脚本位置算**（它住在 _tools/ops/ ⇒ 仓库根是 parents[2]），
#    别去猜"调用时 cwd 在哪"——「新代码」那一趟指的就是本仓库。
if stage == "new":
    root = Path(__file__).resolve().parents[2]
else:
    root = Path(sys.argv[1])                                        # 旧代码工作树（git worktree）
db = Path(sys.argv[2]).as_posix()
os.environ["DATABASE_URL"] = "sqlite:///" + db
sys.path.insert(0, str(root / "backend"))
os.chdir(str(root / "backend"))

from app.database import SessionLocal, engine            # noqa: E402
from app.core.schema_bootstrap import prepare_schema     # noqa: E402

prepare_schema(engine)

import sqlite3                                           # noqa: E402

con = sqlite3.connect(db)
cols = {r[1]: r for r in con.execute("PRAGMA table_info(orders)").fetchall()}
has = "freight_rule_snapshot" in cols
if has:
    name, ctype, notnull, dflt = cols["freight_rule_snapshot"][1], cols["freight_rule_snapshot"][2], cols["freight_rule_snapshot"][3], cols["freight_rule_snapshot"][4]
    print(f"[{stage}] 列在：{name} / 类型={ctype} / NOT NULL={notnull} / 默认值={dflt!r}")
else:
    print(f"[{stage}] 列**不在**（orders 共 {len(cols)} 列）")

from app.models import Order                             # noqa: E402

db_s = SessionLocal()
try:
    n = db_s.query(Order).count()
    print(f"[{stage}] 旧口径的 Order 查询跑通：{n} 行")
finally:
    db_s.close()
print(f"[{stage}] OK")