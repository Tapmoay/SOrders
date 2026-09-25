#!/usr/bin/env python3
"""_check_money_dependency.py —— 钱的**依赖方向**（进 `_check_all.py` 自动跑）。

### 为什么需要它（第二轮 R2-03 · 指南 §五）
第一轮已经把「钱只有一处实现」做成了机器判据（`_check_money_contract.py`）。
指南 §五 说第二轮要做的**不是**继续加钱的接口，而是：

> 第二轮真正要做的是：**验证依赖图**，而不是继续增加钱的接口。

它画的目标形状是：

```text
  Reports / Ledger / Settlement / AI / Order  ──▶  money_contract  ──▶  Money implementation
```

并且点名了要禁止的形状：

```text
  A → money_contract → B;  B → accounting → C;  C → order_money → A       ← 环
```

### 判据（八条）
1. **任何模块都不许 import `app.api`**，例外只有 `main.py` 与 `api/**` 自己
   （前者是应用装配，后者是同层互相引用）—— 这条**0 例外**；
2. **钱模块**（口径层 + 落库层 + 契约）一条 `app.api` 都不许有；
3. **钱模块不许 import 报表层** —— 报表是事实消费者，钱不许反向依赖它；
4. **口径层不许 import 落库层**（纯算术不许依赖"会写库/会改状态"的东西）；
5. **口径层只许 import**：标准库/三方、`app.models.*`、`app.core.*`、本层；
   白名单之外每一条都必须写进下面的 `ALLOWED` 表（带理由与"什么时候删掉"）；
6. **契约的转出目标必须是钱模块**（`money_contract.REEXPORTS` 指到别处＝契约变成了别人的门面）；
7. **名单里的文件必须真实存在**（改名/搬迁后名单不许留着旧路径）；
8. 反空转：扫到的模块数、边数、钱模块数都要达标。

⚠️ 这一条只做**静态 import 图**：它证明的是"依赖方向"，不是运行期调用。
运行期那条（谁真的调了谁）在 `_check_business_transactions.py` 里按调用图核。

用法：python _tools/qa/_check_money_dependency.py [--check]
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend/app"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _domain_map as dm  # noqa: E402

#: 钱的口径层：**纯算术**，不落库、不改状态、不认识 HTTP。
TIER0 = (
    "app/services/order_money.py",
    "app/services/money_text.py",
    "app/services/driver_pay.py",
    "app/services/shipper_settle.py",
    "app/services/cost_basis.py",
)

#: 钱的落库层：会写库 / 会改状态机，因此**允许**依赖订单域与领域服务。
TIER1 = (
    "app/services/accounting_service.py",
    "app/services/order_return.py",
    "app/services/ledger_sync.py",
    "app/services/supplier_service.py",
    "app/services/ledger_scope.py",
    "app/services/ledger_response.py",
)

CONTRACT = "app/services/money_contract.py"
MONEY = TIER0 + TIER1 + (CONTRACT,)

#: 报表层：**事实消费者**，任何钱模块都不许依赖它（指南 §八）。
REPORTING = (
    "app/services/reports_service.py",
    "app/services/stats_service.py",
    "app/services/stats_export.py",
)

#: 口径层允许 import 的**路径前缀**（注意是文件路径，不是点分模块名 —— 第一版写成点分，
#: 于是 `app/models/Order.py` 一条都匹配不上，把 17 条正常依赖全报成了违规）。
TIER0_ALLOWED_PATHS = ("app/models/", "app/core/")

#: 规则的例外：(触发它的模块, 被 import 的模块) -> 为什么 + **什么时候删掉这一条**。
#: ⛔ 现在是**空的** —— 空表不是"没检查"，是"确实一条例外都没有"；
#:    表一旦非空，判据会逐条核对"这条例外还命中吗"（不命中＝化石，报红）。
ALLOWED: dict[tuple[str, str], str] = {}

MIN_MODULES = 180
MIN_EDGES = 300
MIN_MONEY_MODULES = 10


def rel(path: Path) -> str:
    return path.relative_to(ROOT / "backend").as_posix()


#: `dotted_to_rel` 的口径在 `_domain_map.py` **一处** —— R2-03 起两张依赖图（钱的方向、事务的调用图）
#: 共用它。⛔ 各写一份的话，一处改了另一处不改，两张图的节点集就会悄悄不一样。
dotted_to_rel = dm.dotted_to_rel


def app_imports(path: Path) -> set[str]:
    """这个文件 import 了哪些 `app.*` 模块（**惰性/函数内 import 也算**）。

    ⚠️ 必须走 AST 而不是正则：本仓库大量 import 写在函数体里（惰性 import 是为了避开环），
    按行正则扫会漏掉它们 —— 而"服务层反向 import 路由"那一条恰恰就是函数内 import。
    """
    out: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("app"):
                    out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                continue  # 本仓库没有相对 import
            if mod.startswith("app"):
                out.add(mod)
                for a in node.names:
                    out.add(mod + "." + a.name)
    return out


def build_graph() -> tuple[dict[str, set[str]], int]:
    """相对路径 → 它真实依赖的模块相对路径集合。"""
    files = sorted(APP.rglob("*.py"))
    raw = {rel(f): app_imports(f) for f in files}
    graph: dict[str, set[str]] = {}
    edges = 0
    for src, names in raw.items():
        targets: set[str] = set()
        for n in names:
            t = dotted_to_rel(n)
            if t and t != src:
                targets.add(t)
        graph[src] = targets
        edges += len(targets)
    return graph, edges


def main() -> int:
    check_mode = "--check" in sys.argv[1:]
    graph, edges = build_graph()

    fails: list[str] = []
    passed = 0

    # ---- 7. 名单里的文件必须真实存在 ----------------
    for f in MONEY + REPORTING:
        if not (ROOT / "backend" / f).is_file():
            fails.append(f"名单里的 {f} 不存在（改名 / 搬走了？名单不许留旧路径）")
    if not fails:
        passed += 1

    # ---- 8. 反空转 ----------------
    if len(graph) < MIN_MODULES:
        fails.append(f"只扫到 {len(graph)} 个模块（<{MIN_MODULES}）—— 扫描坏了")
    else:
        passed += 1
    if edges < MIN_EDGES:
        fails.append(f"只数到 {edges} 条内部依赖（<{MIN_EDGES}）—— 扫描坏了")
    else:
        passed += 1
    missing = [f for f in MONEY if f not in graph]
    if len(MONEY) - len(missing) < MIN_MONEY_MODULES:
        fails.append(f"钱模块只认出 {len(MONEY) - len(missing)} 个（<{MIN_MONEY_MODULES}）")
    else:
        passed += 1

    def violates(src: str, tgt: str) -> bool:
        return (src, tgt) not in ALLOWED

    # ---- 1. 任何模块都不许 import app.api（例外：main.py 与 api/** 自己）----------------
    bad: list[str] = []
    for src, tgts in sorted(graph.items()):
        if src.startswith("app/api/") or src == "app/main.py":
            continue
        for t in sorted(tgts):
            if t.startswith("app/api/") and violates(src, t):
                bad.append(f"{src} → {t}")
    if bad:
        fails.append("这些模块**反向 import 了 HTTP 路由层**（`services → api` 是倒置的依赖方向，"
                     "指南 §十七.3：能靠改依赖方向解决就别加检查器）：" + "；".join(bad))
    else:
        passed += 1

    # ---- 2. 钱模块一条 app.api 都不许有 ----------------
    bad = []
    for src in MONEY:
        for t in sorted(graph.get(src, set())):
            if t.startswith("app/api/"):
                bad.append(f"{src} → {t}")
    if bad:
        fails.append("钱模块依赖了 HTTP 层：" + "；".join(bad))
    else:
        passed += 1

    # ---- 3. 钱模块不许 import 报表层 ----------------
    bad = []
    for src in MONEY:
        for t in sorted(graph.get(src, set())):
            if t in REPORTING and violates(src, t):
                bad.append(f"{src} → {t}")
    if bad:
        fails.append("钱模块依赖了**报表层**（报表是事实消费者，钱不许反向依赖它）：" + "；".join(bad))
    else:
        passed += 1

    # ---- 4. 口径层不许 import 落库层 ----------------
    bad = []
    for src in TIER0:
        for t in sorted(graph.get(src, set())):
            if t in TIER1 and violates(src, t):
                bad.append(f"{src} → {t}")
    if bad:
        fails.append("纯算术的口径层依赖了落库层（会转成环）：" + "；".join(bad))
    else:
        passed += 1

    # ---- 5. 口径层只许 import 白名单 ----------------
    bad = []
    for src in TIER0:
        for t in sorted(graph.get(src, set())):
            if t.startswith(TIER0_ALLOWED_PATHS) or t in TIER0:
                continue  # 领域模型 / 时间基准 / 同层 —— 这是口径层该认识的全部
            if violates(src, t):
                bad.append(f"{src} → {t}")
    if bad:
        fails.append("口径层 import 了白名单之外的东西（要么改依赖方向，要么在 ALLOWED 里写理由）："
                     + "；".join(bad))
    else:
        passed += 1

    # ---- 6. 契约的转出目标必须是钱模块 ----------------
    sys.path.insert(0, str(ROOT / "backend"))
    from app.services.money_contract import REEXPORTS  # noqa: PLC0415

    money_set = set(MONEY)
    bad = []
    for sym, (mod, name) in sorted(REEXPORTS.items()):
        target = dotted_to_rel(mod)
        if target is None:
            bad.append(f"{sym} → {mod}（模块不存在）")
        elif target not in money_set:
            bad.append(f"{sym} → {target}（**不是钱模块**）")
    if bad:
        fails.append("契约转出的符号指到了钱模块之外：" + "；".join(bad))
    else:
        passed += 1

    # ---- 例外表：命中才留，不命中就是化石 ----------------
    before = len(fails)
    for (src, tgt), why in ALLOWED.items():
        if len(why.strip()) < 20:
            fails.append(f"例外 {src} → {tgt} 的理由太短（<20 字）")
        if "删掉这一条" not in why:
            fails.append(f"例外 {src} → {tgt} 没写「什么时候删掉这一条」")
        if tgt not in graph.get(src, set()):
            fails.append(f"例外 {src} → {tgt} 已经不再命中（化石）—— 删掉它")
    if len(fails) == before:
        passed += 1

    print(f"钱依赖图：{len(graph)} 个模块 / {edges} 条内部依赖 / 钱模块 {len(MONEY)} 个 / "
          f"例外 {len(ALLOWED)} 条")
    if fails:
        for f in fails:
            print("  ❌ " + f)
        return 1
    if check_mode:
        print("  ✅ 全部通过")
    else:
        print(f"  ✅ {passed} 组判据全部通过：钱的口径层只认 models/core 与同层、"
              "落库层不碰 HTTP 与报表、契约只转出钱模块、没有任何人反向 import 路由。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
