# -*- coding: utf-8 -*-
"""红线：**时间基准只许有一个**（库里一律存 UTC）。

### 为什么（2026-09-19 外部完整检查 C-2）
本项目同时在用**两个时钟**：

| 谁 | 基准 |
|---|---|
| 库端 `NOW()`（`server_default=func.now()`、原生 SQL） | MySQL 会话时区，生产是 **+08:00** |
| Python `utc_now_naive()` | **UTC** |

于是"拿现在去比库里的时间列"在生产上差整整 **8 小时**，而且是**静默**的：
「待派超时 4 小时」实际 12 小时、保留策略与审计窗口整体偏 8 小时。
本机 SQLite 的 `CURRENT_TIMESTAMP` 本来就是 UTC，所以**全部单测与探针都是绿的** ——
这条缺陷就是这么活下来的（报告的原话："本机永远测不出来"）。

### 判据（两条，都是"清单自己算"）
1. **凡声明了 `server_default=func.now()` 的列，必须同时声明 Python 的 `default=`**
   （本轮收敛后的形状：Python 提供值，`server_default` 只给原生 SQL 兜底）；
2. `app/database.py` 必须把 MySQL 会话时区钉成 UTC（`SET time_zone = '+00:00'`）——
   否则第 1 条里那些兜底路径仍然写 +08:00。

配数量判据：第一条至少要认出 3 处（`base.py` 两列 + `operation_logs.created_at`），
认不出来说明解析器失配了，而不是"项目里没有库端时钟了"。

⚠️ 两条判据都**锚在代码形状上**（`cur.execute("SET time_zone` / `def _mysql_session_utc(`），
不锚在"这个名字出现过"上 —— `database.py` 的注释与报错文案里也写着这两个名字，
按名字找的话，把钩子改名之后判据**照样绿**（2026-09-25 反向验证第 ③ 条当场抓到）。
配套反向验证：`python _tools/qa/_reverse_verify_time_base.py`（4 种破坏 5/5）。

用法：python _tools/qa/_check_time_base.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting, repo_root  # noqa: E402

ROOT = repo_root()
MODELS = ROOT / "backend" / "app" / "models"
DATABASE = ROOT / "backend" / "app" / "database.py"

#: 至少要有这么多列在用库端时钟（少于这个数说明解析器坏了）
MIN_DB_CLOCK_COLUMNS = 3

#: 一个 `mapped_column(...)` 调用（可能跨行）
_COLUMN_RE = re.compile(r"mapped_column\(([^()]*(?:\([^()]*\)[^()]*)*)\)")
_DB_CLOCK = "server_default=func.now()"
_PY_DEFAULT = re.compile(r"(?<!server_)\bdefault=")


def main() -> int:
    if refuse_if_injecting("时间基准检查"):
        return 1

    errs: list[str] = []
    found: list[tuple[str, int]] = []

    for path in sorted(MODELS.glob("*.py")):
        src = io.open(path, encoding="utf-8", errors="replace").read()
        for m in _COLUMN_RE.finditer(src):
            body = re.sub(r"\s+", " ", m.group(1))
            if _DB_CLOCK not in body:
                continue
            line = src[: m.start()].count("\n") + 1
            found.append((f"{path.name}:{line}", line))
            if not _PY_DEFAULT.search(body):
                errs.append(
                    f"{path.name}:{line} 这一列由**库端时钟**写（{_DB_CLOCK}），"
                    f"却没有 Python 的 `default=` → 生产 MySQL 上它会是 +08:00，"
                    f"而 Python 写的是 UTC（同一个库里两个基准）。补上 `default=utc_now_naive`。"
                )

    print(f"扫到 {len(found)} 列在用库端时钟：{[n for n, _ in found]}")
    if len(found) < MIN_DB_CLOCK_COLUMNS:
        errs.append(
            f"只认出 {len(found)} 列（下限 {MIN_DB_CLOCK_COLUMNS}）——解析器失配了，"
            f"不是'项目里没有库端时钟了'。修 `_COLUMN_RE`。"
        )

    src_db = io.open(DATABASE, encoding="utf-8", errors="replace").read()
    # ⛔ 两条都必须锚在**代码形状**上，不能锚在一个名字/一句话上：`database.py` 的注释与报错文案里
    #    也写着 `SET time_zone` 与 `_mysql_session_utc`。第一版按名字找，于是把
    #    `def _mysql_session_utc(` 改名之后这两条判据**照样绿**（2026-09-25 反向验证第 ③ 条当场
    #    抓到；「判据被自己的文档满足」这在本项目已经是第 3 次）。
    if 'cur.execute("SET time_zone' not in src_db:
        errs.append(
            "`app/database.py` 没有把 MySQL 会话时区钉成 UTC —— 要的是那一句**代码**"
            "（cur.execute(\"SET time_zone = '+00:00'\")），不是注释里提到过它。"
            "库端 `NOW()` 会是 +08:00，与 Python 写的 UTC 差 8 小时（见 C-2）。"
        )
    if "else:" not in src_db or "def _mysql_session_utc(" not in src_db:
        errs.append(
            "`database.py` 里找不到 MySQL 分支的会话时区钩子 —— 要的是 `def _mysql_session_utc(` "
            "这个**定义**，不是注释里提到过这个名字。"
        )

    if errs:
        print("\n❌ 时间基准检查没通过：\n")
        for e in errs:
            print("  · " + e + "\n")
        return 1
    print(
        f"✅ 时间基准只有一处：{len(found)} 列由 Python 写 UTC（`server_default` 仅兜底），"
        f"且 MySQL 会话时区已钉成 UTC"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
