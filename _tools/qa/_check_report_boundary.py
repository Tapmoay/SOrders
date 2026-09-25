#!/usr/bin/env python3
"""_check_report_boundary.py —— 报表层的**只读边界**（进 `_check_all.py` 自动跑）。

### 为什么需要它（第二轮 R2-05 · 指南 §八 / §九）
指南 §八 的原话：

```text
  报表是：事实消费者，而不是事实生产者。
  不要：Report → 偷偷调用订单写逻辑 → 再修改一些业务状态。
```

⛔ 判据第一次跑之前先盘了一遍，抓到一处**真的**违规：
`POST /stats/exception-orders/{id}/resolve` 住在报表模块里，做的是**写业务状态**
（`orders.is_exception` / `exception_reason` / `exception_resolution` / `exception_resolved_at`），
而且开的是**自己的** `SessionLocal()` —— 那次写不在请求的事务里，报表层的任何只读判据都看不见它。
已按指南 §十七.3「能靠改依赖方向解决就别加检查器」把它搬回订单域（`app.commands.order.resolve_exception`），
URL / 入参 / 出参 / 权限一字未改。这一条判据负责**不让它再长回来**。

### 判据（六条）
1. 报表层的文件清单**自己算**（声明的 5 个 + `services/reports/**` 目录下所有 .py），一个都不许少；
2. ⭐ **零写动词**：这些文件里不许出现会落库的调用（AST：`db.add/commit/flush/delete/rollback` 与
   `update()/delete()/insert()` 这类 DML）；
3. ⭐ **不许 import 写服务**（含**函数体内的惰性 import**）：订单状态机 / 退货 / 库存 / 账务 / 结算 / 写日志 / 发件箱；
4. ⭐ **路由层不许写业务对象**（`order.<字段> = …`）—— 报表端点只做读与出参；
5. `db.commit()` 在报表层必须为 **0**（单列一条：它是"生产者"最直白的证据）；
6. 反空转：文件数、函数数都要达标。

⚠️ 例外表 `ALLOWED_WRITES` 现在是**空的** —— 空表不是"没检查"，是"确实一处都没有"。
   表一旦非空，判据会逐条核对：理由 ≥20 字、必须写「什么时候删掉这一条」、而且必须仍然命中（不命中＝化石）。

用法：python _tools/qa/_check_report_boundary.py [--check]
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
APP = BACKEND / "app"

#: 报表层的**声明清单**（`services/reports/**` 目录由判据自己扫，不写在这里）。
REPORT_FILES = (
    "app/api/v1/reports.py",
    "app/api/v1/stats.py",
    "app/services/reports_service.py",
    "app/services/stats_service.py",
    "app/services/stats_export.py",
)

#: 报表层**只许读**这些东西：写服务一个都不许 import。
WRITE_SERVICES = (
    "app.services.order_flow",
    "app.services.order_return",
    "app.services.inventory_service",
    "app.services.accounting_service",
    "app.services.shipper_settle",
    "app.services.ledger_sync",
    "app.services.warehouse",
    "app.services.place_service",
    "app.services.message_center",
    "app.services.operation_log_service",
    "app.commands",
    "app.core.outbox",
)

#: 会落库的会话方法名。
WRITE_METHODS = frozenset({"add", "add_all", "commit", "flush", "delete", "rollback", "merge", "bulk_save_objects"})
#: SQLAlchemy 的 DML 构造器。
DML_NAMES = frozenset({"update", "delete", "insert"})

#: 规则 4 只认这几个**业务对象**的变量名。
#: ⚠️ 第一版把所有 `x.y = …` 都算成"写业务对象"，于是导出 Excel 时的 `ws.title = …` 被误报 ——
#:    那是 openpyxl 的工作表，不是业务状态。判据宁可窄一点也要**准**：宽而假的判据会被学会无视。
BUSINESS_OBJECTS = frozenset({"order", "o", "order_row"})

#: 例外：(文件, 命中的写法) -> 为什么 + **什么时候删掉这一条**。
ALLOWED_WRITES: dict[tuple[str, str], str] = {}

MIN_FILES = 5
MIN_FUNCS = 30
MIN_REASON = 20


def report_paths() -> list[Path]:
    """报表层的全部文件 —— 目录那半边**自己算**（新加一个 .py 自动进边界）。"""
    out = [BACKEND / f for f in REPORT_FILES]
    pkg = APP / "services" / "reports"
    if pkg.is_dir():
        out.extend(sorted(pkg.rglob("*.py")))
    return out


def rel(path: Path) -> str:
    return path.relative_to(BACKEND).as_posix()


def app_imports(tree: ast.Module) -> set[str]:
    """这个文件 import 了哪些 app 模块（**函数体内的惰性 import 也算**）。"""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app"):
            out.add(node.module or "")
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("app"):
                    out.add(a.name)
    return out


def write_hits(tree: ast.Module) -> list[str]:
    """会落库的写法（会话方法 + DML 构造器）。"""
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr in WRITE_METHODS:
            hits.append("." + fn.attr + "(")
        elif isinstance(fn, ast.Name) and fn.id in DML_NAMES:
            hits.append(fn.id + "(")
    return hits


def business_writes(tree: ast.Module) -> list[str]:
    """给 ORM 对象赋值的写法（`order.<字段> = …` / `obj.<字段> = …`）。"""
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name):
                hits.append(t.value.id + "." + t.attr + " =")
        if isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name):
            pass
    return hits


def main() -> int:
    check_mode = "--check" in sys.argv[1:]
    files = report_paths()

    fails: list[str] = []
    passed = 0
    n_func = 0

    missing = [f for f in REPORT_FILES if not (BACKEND / f).is_file()]
    if missing:
        fails.append("报表层声明的文件不见了（改名 / 搬走？）：" + "、".join(missing))
    if len(files) < MIN_FILES:
        fails.append(f"报表层只认出 {len(files)} 个文件（<{MIN_FILES}）—— 清单坏了")
    if not missing and len(files) >= MIN_FILES:
        passed += 1

    for path in files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        n_func += sum(1 for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        r = rel(path)

        # 2/5. 写动词（唯一一处例外：COMMIT 那句是导出任务自己建的？—— 现在没有）
        for hit in sorted(set(write_hits(tree))):
            if (r, hit) in ALLOWED_WRITES:
                continue
            fails.append(f"{r} 里有会落库的写法 {hit} —— 报表层是事实消费者，不许写")

        # 3. 不许 import 写服务
        for mod in sorted(app_imports(tree)):
            if any(mod == w or mod.startswith(w + ".") for w in WRITE_SERVICES):
                if (r, mod) in ALLOWED_WRITES:
                    continue
                fails.append(f"{r} import 了写服务 {mod} —— 报表是读侧，不许依赖写侧")

        # 4. 路由层不许写业务对象
        if r.startswith("app/api/"):
            for hit in sorted(set(business_writes(tree))):
                # ⚠️ 只认**业务对象**那几类变量名（第一版把所有 `x.y =` 都算上，
                #    于是导出 Excel 时的 `ws.title = …` 被误报 —— 那是 openpyxl 的工作表，不是业务状态）。
                if hit.split(".")[0] not in BUSINESS_OBJECTS:
                    continue
                if (r, hit) in ALLOWED_WRITES:
                    continue
                fails.append(f"{r} 的路由体里给对象赋值（{hit}）—— 报表端点只做读与出参")

    if n_func < MIN_FUNCS:
        fails.append(f"报表层只解析出 {n_func} 个函数（<{MIN_FUNCS}）—— AST 扫描可能坏了")
    else:
        passed += 1

    # 例外表：命中才留，不命中就是化石
    before = len(fails)
    for (f, hit), why in ALLOWED_WRITES.items():
        if len(why.strip()) < MIN_REASON:
            fails.append(f"例外 {f} / {hit} 的理由太短（<{MIN_REASON} 字）")
        if "删掉这一条" not in why:
            fails.append(f"例外 {f} / {hit} 没写「什么时候删掉这一条」")
        blob = "".join(p.read_text(encoding="utf-8") for p in files if p.is_file())
        if hit not in blob:
            fails.append(f"例外 {f} / {hit} 已经不再命中（化石）—— 删掉它")
    if len(fails) == before:
        passed += 1

    print(f"报表只读边界：{len(files)} 个文件 / {n_func} 个函数 / 例外 {len(ALLOWED_WRITES)} 条")
    if fails:
        for f in sorted(set(fails)):
            print("  ❌ " + f)
        return 1
    if check_mode:
        print("  ✅ 全部通过")
    else:
        print(f"  ✅ {passed} 组判据全部通过：报表层零写动词、不 import 写服务、路由体不写业务对象。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
