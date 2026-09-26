"""反向验证 §22（司机计费规则：钱只算一处、范围只认一处、历史不可追溯）。

## 为什么这一节必须配反向验证
这一节守的是"**同一个事实在多处被算出来**"这件事，而它的失效方式全都**不报错**：

- 账单金额那一行又抄回订单字段（`pay_for_order` 还在调，只是结果没被用）→ 计件司机少拿提成，
  而卡片、结算页、账单**各说各的数**，谁也不知道该信哪个；
- 抽成范围不生效（把 scope 丢掉）→ 说好"只对 A 商品抽成"，实际按整单抽，**多给钱**且没人发现；
- 逐单覆盖不生效 → 派单员为这一单单独定的比例被规则里的默认值盖掉；
- 派单时不写规则快照 → 改一次规则，**历史账单跟着变**（"账单是钱"的底线）；
- 校验放行"拿这一单的钱 + 按运费抽成" → 一次配错就是 100%+X%。

所以每条都注入一次，证明检查真的会红。

用法：`python _reverse_verify_billing.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = repo_root()
PAY = ROOT / "backend/app/services/driver_pay.py"
RULE_SCHEMA = ROOT / "backend/app/schemas/driver_billing_rule.py"
ACCT = ROOT / "backend/app/services/accounting_service.py"
BILLS = ROOT / "backend/app/api/v1/driver_bills.py"
SETTLE = ROOT / "backend/app/api/v1/freight_settlement.py"
STATS = ROOT / "backend/app/services/stats_service.py"
FLOW = ROOT / "backend/app/services/order_flow.py"
Wsvc = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteDataSource.kt"
WHAND = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteOrderHandlers.kt"
AIRES = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiResources.kt"

CASES: list[tuple[str, Path, object]] = [
    (
        "账单金额又抄回订单运费（pay_for_order 成了摆设 → 计件司机少拿提成）",
        ACCT,
        lambda s: s.replace("        amount=pay.total,", "        amount=order.freight_fee,", 1),
    ),
    (
        "补单金额抄回订单运费（同一条单两条路径两个数）",
        BILLS,
        lambda s: s.replace("                amount=pay.total,", "                amount=o.freight_fee,", 1),
    ),
    (
        "结算页合计改回运费（账单说 120、结算页说 500）",
        SETTLE,
        lambda s: s.replace(
            'g["total"] = round(g["total"] + float(pay.total), 2)',
            'g["total"] = round(g["total"] + fee, 2)',
            1,
        ),
    ),
    (
        "绩效的待结改回 Σ 运费（司机看到的钱和账单对不上）",
        STATS,
        lambda s: s.replace("pay_for_order(ode).total for ode in os if has_per_order_pay(ode)",
                            "(ode.freight_fee or Decimal(\"0\")) for ode in os", 1),
    ),
    (
        "抽成范围不生效（说好只对 A 商品抽，实际按整单抽 = 多给钱）",
        PAY,
        lambda s: s.replace("        if product_ids:", "        if False:", 1),
    ),
    (
        "逐单覆盖不生效（派单员为这一单定的比例被规则默认值盖掉）",
        PAY,
        lambda s: s.replace(
            # ⚠️ 锚点 2026-09-21 更新：兜底价从 `rule.commission_rate` 改成了 `base_rate`
            #    （逐单覆盖 + 分类规则的取值链变过）。注入原意不变：**把逐单覆盖丢掉**。
            "    rate = money(rate_override) if rate_override is not None else base_rate",
            "    rate = base_rate",
            1,
        ),
    ),
    (
        "派单时不写规则快照（改一次规则，历史账单跟着变）",
        FLOW,
        lambda s: s.replace("    order.driver_rule_snapshot = rule_to_snapshot(rule)", "", 1),
    ),
    (
        "逐单覆盖值不写进订单（派单员填了 300，账单还是按规则算）",
        FLOW,
        # ⚠️ 锚点跟着实现走（2026-09-19 第十四轮）：这一行现在与比例那行**成对**出现，
        #    而且上面多了 6 行"为什么必须无条件赋值"的说明 —— 只锚 `piece_amount` 那一行
        #    仍然能匹配，但为了让注入的语义（"这两个覆盖值都没写进去"）更贴近原意，
        #    这里把两行一起换掉。
        lambda s: s.replace(
            "    order.driver_piece_amount = piece_override\n"
            "    order.driver_commission_rate = rate_override\n",
            "",
            1,
        ),
    ),
    (
        "覆盖值不做先验（填了不生效也照收：界面上有数字、账单里另一个数）",
        FLOW,
        lambda s: s.replace("    if problem:\n        raise ValueError(problem)\n", "", 1),
    ),
    (
        "逐单定额不算进模式快照（工资制司机的这笔钱不生成账单，静默消失）",
        PAY,
        lambda s: s.replace(
            "    if piece_override is not None or rate_override is not None:\n        return \"PIECE\"",
            "    if False:\n        return \"PIECE\"",
            1,
        ),
    ),
    (
        "派单卡片不再写「他现在的计费规则」（用户看不见规则，闭着眼睛点确认）",
        WHAND,
        lambda s: s.replace('                add("他现在的计费规则：${driver.note?.takeIf { it.isNotBlank() } ?: "没挂规则（按老口径：计件=全额运费）"}")', "                Unit", 1),
    ),
    (
        "AI 的逐单金额只在卡片上写着、不传给后端",
        WHAND,
        lambda s: s.replace('            pieceAmount = payload.str("driver_piece_amount"),', "            pieceAmount = null,", 1),
    ),
    (
        "撤回→反悔不再搬回逐单覆盖值（反悔之后这单的钱悄悄变回默认值）",
        AIRES,
        lambda s: s.replace('                        "driver_piece_amount" to "driver_piece_amount",\n', "", 1),
    ),
    (
        "账单说明印回规则里的默认比例（印出一句算术上不成立的账：5% = 80.00）",
        ACCT,
        lambda s: s.replace(
            'rate = getattr(pay, "rate_used", None) or getattr(rule, "commission_rate", 0)',
            'rate = getattr(rule, "commission_rate", 0)',
            1,
        ),
    ),
    (
        "校验放行「拿这一单的钱 + 按运费抽成」（等于 100%+X%）",
        RULE_SCHEMA,
        lambda s: s.replace('        return "「每单拿这一单的钱」和「按运费抽成」不能同时配（那等于拿 100% 再加提成）；只留一个"', "        pass", 1),
    ),
    (
        "名单解析改成自己挑第一个（认不出来也硬挑一个 = 抽错商品）",
        Wsvc,
        lambda s: s.replace(
            '            .map { AiWriteArgs.strict(it, pool, "商品")!!.id }  // strict 查不到会抛，不会返回 null',
            "            .mapNotNull { q -> pool.firstOrNull { it.label.contains(q) }?.id }",
            1,
        ),
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(HERE / "_check_ai_guardrails.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def section_22(out: str) -> str:
    """只取 §22 那一段（段内失败标记是 `[FAIL]`，不是汇总里的 `❌`）。"""
    if "== 22." not in out:
        return ""
    rest = out.split("== 22.", 1)[1]
    return rest.split("\n" + "=" * 60, 1)[0]


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时检查就没过\n{out[-1200:]}")
        return 1
    if not section_22(out):
        print("❌ 前提不成立：输出里找不到 §22 这一段")
        return 1
    print("✅ 前提：源码完好时检查是绿的，且 §22 存在")

    for label, path, mutate in CASES:
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code, out = run_check()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        # R3-07b：还原**当场核对**（不是「看起来还原了」）—— 对不上就记账，别让坏代码留在树里
        if path.read_text(encoding="utf-8") != original:
            fails.append(f"{label}：还原后与快照不一致 —— 注入污染了源码树")
            continue
        got = section_22(out)
        if code == 0 or "[FAIL]" not in got:
            fails.append(f"{label}：注入后 §22 没有报红（code={code}）——判据是空转的")
        else:
            print(f"✅ 注入「{label}」→ §22 报红")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ §22 的 {len(CASES)} 条注入全部证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
