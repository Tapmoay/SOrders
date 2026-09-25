#!/usr/bin/env python3
"""_check_traceability.py —— 订单全链路 trace 的**可用性**（进 `_check_all.py` 自动跑）。

### 为什么需要它（第二轮 R2-06 · 指南 §十五）
指南 §十五 要的是：遇到「为什么这笔订单的钱不对？」时能**直接查完整链路**：
订单 → 请求 → 命令 → 状态 → 账本 → 司机账单 → 事件 → 通知。

工具是 `_tools/ops/_trace_order.py`。这一条判据守三件事：

1. ⭐ **链路是真的**：工具声明的每一段（表 + 列）都必须在 `models/**` 里真的存在 ——
   否则那段"链路"是写给人看的，查起来会当场报错；
2. ⭐ **工具真的查了每一段**：源码里必须出现每一段的表名（防"声明了一张表、代码里没查"）；
3. ⛔ **工具是只读的**：不许有落库写法，也不许 import `app.database`
   （那个模块在**导入时**就跑 `bootstrap_schema`：一个排障工具不该在别人的库上跑 DDL）。

⚠️ 判据**不**去连数据库、也不跑那个工具：真值来自源码。
   「真的能查出一张单的链路」由人跑一次（证据留在提交信息/文档里）——
   指南自己也说：检查器只作为验收工具，不是解决方案。

用法：python _tools/qa/_check_traceability.py [--check]
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "_tools/ops"))

MODELS = ROOT / "backend/app/models"
TOOL = ROOT / "_tools/ops/_trace_order.py"

MIN_LINKS = 6
MIN_COLUMNS = 20
WRITE_METHODS = frozenset({"add", "add_all", "commit", "flush", "delete", "rollback", "merge"})
DML_NAMES = frozenset({"update", "delete", "insert"})


def main() -> int:
    check_mode = "--check" in sys.argv[1:]
    import _trace_order  # noqa: PLC0415

    fails: list[str] = []
    passed = 0
    links = _trace_order.LINKS
    src = TOOL.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # 模型里有哪些表、每个表文件里出现过哪些列名（按文件读，够用且不依赖导入）
    tables: dict[str, str] = {}
    # ⚠️ `created_at` / `updated_at` 来自 `TimestampMixin`（base.py），**不在**各个模型文件里 ——
    #    不把那份 mixin 拼进来的话，「orders.created_at 在模型里找不到」会是一条**假红**
    #    （第一版就是这样，判据自己抓到的）。
    base = (MODELS / "base.py").read_text(encoding="utf-8")
    for f in MODELS.rglob("*.py"):
        text = f.read_text(encoding="utf-8") + chr(10) + base
        for m in re.finditer(r"__tablename__ = \"([^\"]+)\"", text):
            tables[m.group(1)] = text

    if len(links) < MIN_LINKS:
        fails.append(f"链路只声明了 {len(links)} 段（<{MIN_LINKS}）—— 工具被掏空了？")
    else:
        passed += 1

    n_cols = 0
    for name, table, cols in links:
        if table not in tables:
            fails.append(f"链路「{name}」声明的表 {table} 在 models 里不存在")
            continue
        for col in [c.strip() for c in cols.split(",") if c.strip()]:
            n_cols += 1
            if not re.search(r"\b" + re.escape(col) + r"\b", tables[table]):
                fails.append(f"链路「{name}」声明的 {table}.{col} 在模型里找不到")
        if table not in src:
            fails.append(f"链路「{name}」声明了 {table}，但工具源码里没查它")
    if n_cols < MIN_COLUMNS:
        fails.append(f"链路一共只声明了 {n_cols} 个列（<{MIN_COLUMNS}）—— 契约太薄")
    else:
        passed += 1

    # 只读：不许落库写法、不许 import app.database
    before = len(fails)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in WRITE_METHODS:
                fails.append(f"排障工具里有落库写法 .{fn.attr}( —— 它必须是只读的")
            elif isinstance(fn, ast.Name) and fn.id in DML_NAMES:
                fails.append(f"排障工具里有 DML 构造器 {fn.id}( —— 它必须是只读的")
        elif isinstance(node, ast.ImportFrom) and "app.database" in (node.module or ""):
            fails.append("排障工具 import 了 app.database —— 那个模块导入即 bootstrap_schema（会在别人库上跑 DDL）")
    if len(fails) == before:
        passed += 1

    print(f"订单全链路 trace：{len(links)} 段链路 / {n_cols} 个列 / 只读")
    if fails:
        for f in sorted(set(fails)):
            print("  ❌ " + f)
        return 1
    if check_mode:
        print("  ✅ 全部通过")
    else:
        print(f"  ✅ {passed} 组判据全部通过：每一段链路的表与列都在模型里、工具真的查了它们、而且全程只读。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
