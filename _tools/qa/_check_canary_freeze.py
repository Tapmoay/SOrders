# -*- coding: utf-8 -*-
"""**Canary 决策冻结判据**（R4-26）：已经形成过的计价来源，不许被 canary_percent 改掉。

R4-BOUNDARY-JUSTIFICATION: **代码边界解决不了这件事，因为缺口长在「优先级顺序」上。**

`policy_for` 里那三行（冻结 / 比例 0、100 / 分桶）**每一行单独看都是对的** ——
把冻结那两行挪到比例后面，语法正确、类型正确、单测（如果只测比例）也全绿，
唯一变化的是：比例被调一次，历史单的「钱凭什么」就换一次。
而这条不变量一旦破了，⑧-b 的回滚就再也说不清 —— 所以它只能是对账式的判据。

## 用户 2026-09-27 拍板的出口条件 ③（CANARY_DECISION_FREEZE）

> 「第一次形成有效计价决策后：pricing.kind / contract / implementation
>  必须成为该订单该次计价事实的既定来源。
>  后续写入不得重新依据当前 canary_percent 改变已经形成的 Pricing Decision。」

## 判据（每条都对应一种**具体的**坏法）

1. `policy_for` 认一个 `frozen` 关键字参数；
2. 冻结分支**在**比例逻辑**之前**（这是本判据存在的全部理由 —— 顺序错了它就不再是冻结）；
3. 冻结分支**原样返回**那一个来源（⛔ 不是"重新算一个"）；
4. 比例 0 / 100 那两条 `return` 在冻结**之后**（否则 0 与 100 会越过冻结）；
5. 组装点**恰好一处**调 `policy_for`，且把冻结读出来传进去；
6. 读冻结只有**一处实现**，且只认得出白名单里的取值（认不出 = 当没定过）；
7. 业务代码里**没有第二处**读冻结（⛔ 不许各自去读一个"已经定过什么"）；
8. 那几条**值钱的单测**真的在（用户点名的两个实验 + 三个边界）；
9. 模块头的第 4 条铁律在（文档与代码同源）。

用法：
    python _tools/qa/_check_canary_freeze.py            # 详细
    python _tools/qa/_check_canary_freeze.py --check    # 必跑模式（一行结论）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
RUNTIME = BACKEND / "app" / "core" / "pricing_runtime.py"
ORDER_MONEY = BACKEND / "app" / "services" / "order_money.py"
TESTS = BACKEND / "tests" / "test_pricing_runtime.py"

fails: list[str] = []
passes = 0


def ok(label: str, cond: bool) -> bool:
    global passes
    if cond:
        passes += 1
    else:
        fails.append(label)
    print(("  [OK]   " if cond else "  [FAIL] ") + label)
    return cond


def main() -> int:
    check = "--check" in sys.argv
    for p in (RUNTIME, ORDER_MONEY, TESTS):
        if not p.exists():
            print("❌ 找不到 " + str(p))
            return 1

    rt = RUNTIME.read_text(encoding="utf-8")
    om = ORDER_MONEY.read_text(encoding="utf-8")
    tests = TESTS.read_text(encoding="utf-8")

    if not check:
        print("== 1. 冻结在组装点里，而且**在比例之前** ==")

    ok("policy_for 认一个 frozen 关键字参数",
       "frozen: str | None = None) -> str:" in rt)

    i_def = rt.find("def policy_for(")
    i_frozen = rt.find("if frozen in (KIND_LEGACY, KIND_CONTRACT):", i_def)
    i_pct = rt.find("pct = canary_percent()", i_def)
    ok("找得到 policy_for 的函数体", i_def > 0 and i_frozen > i_def and i_pct > i_def)
    ok("冻结分支**在**比例逻辑之前（顺序反了它就不再是冻结）",
       i_def > 0 and i_frozen > i_def and i_pct > i_frozen)
    ok("冻结分支**原样返回**那一个来源（⛔ 不是重新算一个）",
       i_frozen > 0 and rt[i_frozen:i_frozen + 400].count("return frozen") == 1)

    ok("比例 <= 0 那条 return 在冻结之后（否则 0% 会越过冻结）",
       i_frozen > 0 and rt.find("        return KIND_LEGACY", i_def) > i_frozen)
    ok("比例 >= 100 那条 return 在冻结之后（否则 100% 会越过冻结）",
       i_frozen > 0 and rt.find("        return KIND_CONTRACT", i_def) > i_frozen)

    if not check:
        print("== 2. 组装点**恰好一处**调它，且把冻结传进去 ==")

    decide_body = rt[rt.find("def decide("):] if "def decide(" in rt else ""
    ok("decide 里恰好一处调 policy_for（⛔ 两处就是两个决策点）",
       decide_body.count("policy_for(") == 1)
    ok("那一处把冻结读出来传进去了（frozen=freight_kind_of(order)）",
       "policy_for(getattr(order, \"id\", None), frozen=freight_kind_of(order))" in decide_body)

    if not check:
        print("== 3. 读冻结只有一处实现，且只认白名单 ==")

    ok("freight_kind_of 全仓只有一处定义", om.count("def freight_kind_of(") == 1)
    ok("它只认白名单里的取值（认不出 = 当没定过，⛔ 不拿不认识的 kind 去冻结）",
       "return kind if kind in FREIGHT_KIND_CONTRACTS else None" in om)

    callers = sorted(
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in (BACKEND / "app").rglob("*.py")
        if "freight_kind_of" in p.read_text(encoding="utf-8")
    )
    allowed = {"backend/app/services/order_money.py", "backend/app/core/pricing_runtime.py"}
    extra = [c for c in callers if c not in allowed]
    ok("业务代码里没有第二处读冻结（只有定义处 + 组装点）", not extra)
    if extra:
        print("        ⛔ 多出来的：" + ", ".join(extra))

    if not check:
        print("== 4. 那几条**值钱的单测**真的在 ==")

    needed = [
        ("用户点名的实验 1：先旧路、再把比例开到满 → 仍然是旧路",
         "def test_先形成旧路之后把比例开到满_这次计价仍然是旧路("),
        ("用户点名的实验 2：先契约、再把比例关到零 → 仍然是契约",
         "def test_先形成契约之后把比例关到零_这次计价仍然是契约("),
        ("冻结不许把 Canary 变成永远关着（没定过的单照样按比例）",
         "def test_没定过来源的单仍然按比例抽签("),
        ("认不出的取值当没定过",
         "def test_已经定过的来源只认得出两种取值("),
        ("边界：清空运费 = 新的一次决策，按当时的比例抽签",
         "def test_运费被清空后再定价_按当时的比例重新抽签("),
        ("后果写死：派单前先手动定价会把来源提前冻住",
         "def test_派单前先手动定价会把来源提前冻住_这是有意的("),
    ]
    for label, needle in needed:
        ok(label, needle in tests)

    if not check:
        print("== 5. 文档与代码同源 ==")

    ok("模块头第 4 条铁律在（不许让比例变化改掉已经形成的计价决策）",
       "不许让比例变化改掉" in rt)
    ok("那条铁律点名了 ⑧-a 出口条件 ③ / CANARY_DECISION_FREEZE",
       "CANARY_DECISION_FREEZE" in rt)

    if check:
        print(("✅" if not fails else "❌")
              + " Canary 决策冻结：冻结在比例之前、组装点唯一、读冻结唯一、6 条单测在"
              + ("" if not fails else "；" + str(len(fails)) + " 项不通过"))
    if fails:
        print("")
        print("❌ " + str(len(fails)) + " 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    if not check:
        print("")
        print("✅ 全部 " + str(passes) + " 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())