# -*- coding: utf-8 -*-
"""数据归属判据（R4-03）：**一个数据实体 / 一张表只有一个 Owner**。

R4-BOUNDARY-JUSTIFICATION: 指南 §14 说这是「最危险的坑之一」，因为它**在代码上完全看不出来**：

> 很多系统表面模块化：pricing/ notification/ report/，但是 pricing 直接改 orders、
> report 直接改 ledgers、notification 直接改 users —— **那模块化就是假的**。

每个文件自己看都合法：它 import 了 Session、写了一行 UPDATE，语法正确、事务正确、测试通过。
错的只有一件事 —— **它写的不是它拥有的表**。而"谁拥有哪张表"只存在于整张图里，
不存在于任何单个文件里。所以这一条只能是对账式的。

## 判据（六组）

1. **扩展认领的表不许碰核心事实表** —— 核心表的清单**从边界图算**
   （`docs/R4_CORE_EXTENSION_MAP.md` 里 class=CORE 的 owns），⛔ 不从本文档抄；
2. **扩展认领的表之间不许重叠**（一个事实两个主人）；
3. **扩展代码里一条写语句都没有**（指南 §31 坑 4：Extension 直接改 Core 表）；
4. **扩展碰不到账本那一路**（指南 §31 坑 5，最高危的一类：calculate 完直接 UPDATE ledger）；
5. **历史快照必须存在**（指南 §25 C 类 / §31 坑 9：删除扩展之后历史要解释得通）——
   本项目靠 `orders.driver_rule_snapshot` 与 `order_products.cost_price_snapshot` 这两列，
   所以判据直接去模型里找它们，找不到就报红；
6. **静默空转保护**：核心表数 / 快照列数 都有下限。

用法：python _tools/qa/_check_data_ownership.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ai"))
from _airepo import refuse_if_injecting, repo_root  # noqa: E402
from _check_core_extension_boundary import parse_blocks  # noqa: E402  —— 边界图的唯一解析实现

ROOT = repo_root()
APP = ROOT / "backend" / "app"
EXTENSIONS = APP / "extensions"
MAP = ROOT / "docs" / "R4_CORE_EXTENSION_MAP.md"
MODELS = APP / "models"

#: 写语句与 ORM 写动词（指南 §31 坑 4）。扩展**一个都不许有**。
WRITE_SMELLS = ("db.add(", ".commit(", "db.commit", "session.add(", ".flush(",
                "INSERT INTO", "UPDATE ", "DELETE FROM", "insert(", "update(", "delete(")
#: 账本那一路（指南 §31 坑 5：最高危的一类）。
LEDGER_SMELLS = ("ledgers", "cash_flows", "shipper_receipts", "shipper_settlements",
                 "accounting_service", "ledger_sync", "post_delivery_accounting")
#: 让历史与扩展解耦的两列（指南 §25 C 类）。
SNAPSHOT_COLUMNS = (("order.py", "driver_rule_snapshot"), ("order.py", "cost_price_snapshot"))

MIN_CORE_TABLES = 25
MIN_SNAPSHOTS = 2


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + label)
        else:
            self.fails.append(label + (" —— " + detail if detail else ""))
            print("  [FAIL] " + label + (" —— " + detail if detail else ""))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def code_only(path: Path) -> str:
    """代码（去掉注释与文档字符串）—— 否则"不许写 ledger"这句说明会把自己判红。"""
    try:
        tree = ast.parse(read(path))
    except SyntaxError:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:]
    try:
        return ast.unparse(tree)
    except Exception:  # noqa: BLE001
        return ""


def model_tables() -> set[str]:
    import re

    out: set[str] = set()
    for f in sorted(MODELS.rglob("*.py")):
        out.update(re.findall('__tablename__\\s*=\\s*["\\\']([^"\\\']+)["\\\']', read(f)))
    return out


def core_tables_from_map() -> set[str]:
    """边界图里 class=CORE 的 owns —— ⛔ 核心表的清单从**图**算，不从这里抄。"""
    out: set[str] = set()
    for b in parse_blocks(read(MAP)):
        if b.get("class") != "CORE":
            continue
        for t in [x.strip() for x in b.get("owns", "-").split(",")]:
            if t and t != "-":
                out.add(t)
    return out


def extension_dirs() -> list[Path]:
    if not EXTENSIONS.exists():
        return []
    return sorted(d for d in EXTENSIONS.iterdir() if d.is_dir() and d.name != "__pycache__")


def manifest_of(d: Path):
    import importlib

    try:
        return getattr(importlib.import_module("app.extensions." + d.name + ".manifest"), "MANIFEST", None)
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    if refuse_if_injecting("数据归属检查"):
        return 1
    exts = extension_dirs()
    core_tables = core_tables_from_map()
    all_tables = model_tables()

    c = Checker()
    print("== 1. 核心事实表：从边界图算，不从本文档抄 ==")
    c.ok("边界图里 class=CORE 的表有 " + str(len(core_tables)) + " 张（≥" + str(MIN_CORE_TABLES) + "）",
         len(core_tables) >= MIN_CORE_TABLES, "核心表太少 —— 边界图被掏空还是解析坏了？")
    c.ok("核心表都在模型里真实存在（防化石）", core_tables <= all_tables,
         "图上有、模型里没有：" + str(sorted(core_tables - all_tables)[:5]))
    print("  模型共 " + str(len(all_tables)) + " 张表，其中核心 " + str(len(core_tables)) + " 张")

    print()
    print("== 2. 扩展认领的表不许碰核心事实表 ==")
    claimed: dict[str, str] = {}
    clashes: list[str] = []
    for d in exts:
        m = manifest_of(d)
        if m is None:
            continue
        for t in getattr(m, "owns_tables", ()):
            if t in core_tables:
                clashes.append(d.name + " 认领了核心表 " + t)
            if t in claimed:
                clashes.append("表 " + t + " 被 " + claimed[t] + " 与 " + d.name + " 同时认领")
            claimed[t] = d.name
    c.ok("没有扩展把核心事实表写进 owns_tables（指南 §14）", not clashes, str(clashes[:3]))
    c.ok("扩展认领的表互不重叠", len(claimed) == len(set(claimed)), "重叠：" + str(sorted(claimed)[:3]))
    print("  扩展认领的表 " + str(len(claimed)) + " 张")

    print()
    print("== 3/4. 扩展代码里没有写语句、也碰不到账本 ==")
    ext_files = ([f for f in sorted(EXTENSIONS.rglob("*.py")) if "__pycache__" not in f.parts]
                 if EXTENSIONS.exists() else [])
    writes: list[str] = []
    ledger: list[str] = []
    for f in ext_files:
        code = code_only(f)
        tag = str(f.relative_to(APP)).replace(chr(92), "/")
        for smell in WRITE_SMELLS:
            if smell in code:
                writes.append(tag + " 里有 " + smell)
        for smell in LEDGER_SMELLS:
            if smell in code:
                ledger.append(tag + " 里有 " + smell)
    c.ok("扩展代码里**一条写语句都没有**（只能 calculate，事实交给核心事务）",
         not writes, str(writes[:3]))
    c.ok("扩展碰不到账本那一路（ledgers / cash_flows / 结算服务）", not ledger, str(ledger[:3]))

    print()
    print("== 5. 历史快照必须存在（删除扩展之后历史要解释得通）==")
    missing: list[str] = []
    found = 0
    for fname, column in SNAPSHOT_COLUMNS:
        text = read(MODELS / fname)
        if column in text:
            found += 1
        else:
            missing.append(fname + " 里找不到 " + column)
    c.ok("核对过 " + str(found) + "/" + str(len(SNAPSHOT_COLUMNS)) + " 个历史快照列（≥" + str(MIN_SNAPSHOTS) + "）",
         found >= MIN_SNAPSHOTS, str(missing))
    c.ok("订单的钱与计费规则在派单那一刻就被**定格**（扩展/规则后来变了也不回头改历史单）",
         not missing, str(missing))

    print()
    print("== 6. 静默空转保护 ==")
    c.ok("核心表数 / 快照列数 两项下限都达标",
         len(core_tables) >= MIN_CORE_TABLES and found >= MIN_SNAPSHOTS)
    if not exts:
        print("  [--]   现在扩展数为 0：第 2/3/4 组只证了「没有越界」这一半。")

    print()
    print("=" * 60)
    if c.fails:
        print("❌ " + str(len(c.fails)) + " 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print("✅ 全部 " + str(c.passes) + " 项通过：核心事实表 " + str(len(core_tables))
          + " 张没有被扩展染指，历史快照齐全。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())