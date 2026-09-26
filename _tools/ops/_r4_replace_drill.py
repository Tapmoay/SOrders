# -*- coding: utf-8 -*-
"""R4-05 的 **Replace 演练**：换一种计价方式，核心一行都不改。

## 它证的是什么（指南 §20 / §38）

> 然后替换两种 Pricing implementation。验证：**Core 不动**。

## ⭐ 本项目对"替换"的定义：**不是改代码，是换数据**

每一单在派单那一刻把规则**定格**进 `orders.driver_rule_snapshot`，其中 `pricing_kind`
决定谁认领它。所以"把这单从统一价改成按量计费"这件事的形态是：

    换一个 pricing_kind 的值  ->  换一个实现来算  ->  核心与扩展的代码一个字节都没动

这也是它比"改一行 import"更强的证明：**替换是配置行为，不是开发行为**。

## 四个数（缺一个这条演练就不成立）

1. **Core 修改数 = 0**（区间内核心区改动行数）；
2. **既有扩展模块修改数 = 0**（`backend/app/extensions/pricing/` 下只允许新增，不许修改/删除）；
3. **运行时**：同一张订单，只换规则快照，两个实现给出**不同的、都合法的**结果；
4. **契约用例**：两个实现各跑一遍同一组用例并通过。

用法：
    python _tools/ops/_r4_replace_drill.py --record base    # 落地第一种计价之后
    python _tools/ops/_r4_replace_drill.py --record head    # 落地第二种计价之后
    python _tools/ops/_r4_replace_drill.py --check          # 核四个数（CI 安全，不联网、不碰生产）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "_tools" / "ops" / "r4_drill_records" / "replace-drill.json"
CONTRACT_TEST = "tests/test_pricing_contract.py"

CORE_PATHS = (
    "backend/app/core", "backend/app/services", "backend/app/api", "backend/app/models",
    "backend/app/commands", "backend/app/schemas", "backend/app/deps.py",
    "backend/app/main.py", "backend/app/config.py", "backend/app/database.py",
)
EXTENSION_PATH = "backend/app/extensions/pricing"
MIN_PROVIDERS = 2


def git(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def load() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.exists() else {}


def save(data: dict) -> None:
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(data, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")


def providers_now() -> list[str]:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.extensions.pricing import PROVIDERS

    return [p.name for p in PROVIDERS]


def numstat(rng: str, *paths: str) -> int:
    code, out = git("diff", "--numstat", rng, "--", *paths)
    if code != 0:
        return -1
    total = 0
    for line in out.splitlines():
        parts = line.split(chr(9))
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            total += int(parts[0]) + int(parts[1])
    return total


def changed_extension_files(rng: str) -> list[tuple[str, str]]:
    code, out = git("diff", "--name-status", rng, "--", EXTENSION_PATH)
    if code != 0:
        return []
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        parts = line.split(chr(9))
        if len(parts) >= 2:
            rows.append((parts[0].strip(), parts[1].strip()))
    return rows


def price_with(kind: str) -> tuple[str, str]:
    """同一张订单、同一个数量，只换 pricing_kind —— 返回 (实现的 name, 金额文本)。"""
    from decimal import Decimal

    from app.core.contracts.pricing import PricingContext
    from app.core.contracts.quantity import Quantity
    from app.core.pricing_context import context_of
    from app.extensions.pricing import resolve
    from app.models.order import Order

    order = Order(order_no="SO-RV-REPLACE", driver_id=7, freight_category="建材",
                  address_detail="测试路 1 号", freight_fee=Decimal("88.00"))
    # ⚠️ 两种算法的结果**必须不同**（统一价 120.00 vs 按量 8.50 × 15 = 127.50）：
    #    一样的话就分不出替换有没有生效 —— 第一版两边都写 8.00，当场踩到。
    snapshot = {"pricing_kind": kind, "amount": "120.00", "unit_price": "8.50"}
    base = context_of(order, rule_snapshot=snapshot)
    context = PricingContext(
        order_id=base.order_id, order_no=base.order_no, category=base.category,
        to_place=base.to_place, driver_id=base.driver_id,
        unit_price=Decimal("8.50"), quantity=Quantity(Decimal("15"), "件", "count"),
        rule_snapshot=snapshot,
    )
    provider = resolve(context)
    return provider.name, provider.price(context).money.as_text()


def run_contract_tests() -> tuple[int, str]:
    r = subprocess.run([sys.executable, "-m", "pytest", CONTRACT_TEST, "-q"],
                       cwd=str(ROOT / "backend"), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def do_record(role: str) -> int:
    if role not in ("base", "head"):
        print("--record 只认 base / head")
        return 1
    data = load()
    data[role] = git("rev-parse", "HEAD")[1].strip()
    data[role + "_providers"] = providers_now()
    save(data)
    print("已记录 " + role + " = " + data[role][:12] + "，当时有实现 " + str(data[role + "_providers"]))
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if "--record" in argv:
        i = argv.index("--record")
        return do_record(argv[i + 1] if i + 1 < len(argv) else "")

    data = load()
    base, head = data.get("base"), data.get("head")
    print("== Replace 演练：换一种计价方式，核心一行都不改 ==")
    if not base or not head:
        print("还没记录区间：先跑 --record base（第一种计价落地后）与 --record head（第二种落地后）")
        return 1
    rng = base + ".." + head
    print("  区间：" + base[:12] + ".." + head[:12])
    print("  当时实现：" + str(data.get("base_providers")) + " -> " + str(data.get("head_providers")))
    print()

    fails: list[str] = []
    if git("merge-base", "--is-ancestor", head, "HEAD")[0] != 0:
        fails.append("记录的 head 不是当前 HEAD 的祖先 —— 那条历史不在了")

    core_delta = numstat(rng, *CORE_PATHS)
    print("  1) Core 修改数 = " + str(core_delta) + " 行" + ("  OK" if core_delta == 0 else "  FAIL"))
    if core_delta != 0:
        fails.append("核心被改了 " + str(core_delta) + " 行 —— 这条演练的前提（Core 不动）不成立")

    ext_rows = changed_extension_files(rng)
    modified = [(s, p) for s, p in ext_rows if not s.startswith("A")]
    added = [p for s, p in ext_rows if s.startswith("A")]
    print("  2) 既有扩展模块修改数 = " + str(len(modified)) + " 个"
          + ("  OK" if not modified else "  FAIL " + str(modified)))
    print("     新增文件 " + str(len(added)) + " 个：" + str([Path(p).name for p in added]))
    if modified:
        fails.append("扩展包里已有文件被改了：" + str(modified))
    if not added:
        fails.append("区间里一个新增实现文件都没有 —— 这不是一次 Replace")

    now = providers_now()
    print("  3) 运行时替换（同一张订单，只换规则快照）：")
    if len(now) < MIN_PROVIDERS:
        fails.append("当前实现少于 " + str(MIN_PROVIDERS) + " 个 —— 没有第二个可替换")
    results: dict[str, str] = {}
    for kind in now:
        try:
            who, amount = price_with(kind)
        except Exception as exc:  # noqa: BLE001 —— 演练里先看它会不会算
            print("     " + kind + " -> 算不出来：" + str(exc)[:80])
            continue
        results[kind] = amount
        print("     pricing_kind=" + kind + "  由 " + who + " 算出 " + amount)
    if len(results) < 2:
        fails.append("至少要有两个实现能算同一张订单，现在只有 " + str(len(results)) + " 个")
    elif len(set(results.values())) == 1:
        fails.append("两个实现给了完全相同的数，分不出替换有没有生效：" + str(results))
    else:
        print("     -> 两个实现给出**不同的**结果，而代码一行没改  OK")

    code, out = run_contract_tests()
    tail = [ln.strip() for ln in out.splitlines() if " passed" in ln or " failed" in ln]
    print("  4) 契约用例（每个实现各跑一遍）：" + (tail[-1] if tail else "（没有结果行）")
          + ("  OK" if code == 0 else "  FAIL"))
    if code != 0:
        fails.append("契约用例没过")

    print()
    if fails:
        print("Replace 演练不成立：" + str(len(fails)) + " 条")
        for f in fails:
            print("   - " + f)
        return 1
    print("Replace 演练成立：新增 " + str(len(added)) + " 个实现文件，Core 改 0 行、既有扩展模块改 0 个，")
    print("   同一张订单换一个 pricing_kind 就换了算法 —— 替换是**配置行为**，不是开发行为。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())