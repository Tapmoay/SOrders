"""反向验证第十七轮（钱的流出侧 + 商品毛利口径）那批修复**真的在检查**。

红队审计员（只读）在本机实测出来的每条，都配了一条回归测试或红线断言；
这份脚本逐条把修复**撤回**，证明对应的检查会红。

| 注入 | 应该红的检查 |
|---|---|
| 结算单又收走已软删订单的账单 | `test_soft_deleted_order_bills_are_not_collected_by_a_settlement` |
| 月薪单生成前不锁司机行 | 红线 §25b |
| 确认结算单改回无条件赋值 | 红线 §25b |
| 商品毛利的收入侧改回"全额金额" | `test_product_profit_is_the_same_number_everywhere` |
| 逐行毛利改回 `amount − cost` | 同上（导出那一格） |
| 绩效的计费方式改回"先读 users.billing_mode" | `test_driver_performance_billing_mode_follows_the_rule` |
| 货损进位改回银行家舍入 | `test_damage_amount_rounds_like_the_rest_of_the_project` |
| 保留任务不删库存流水 | `test_retention_purge_deletes_inventory_movements` |
| 「在途占用」不 join orders | `test_inventory_summary_ignores_reservations_of_soft_deleted_orders` |

⚠️ 快照/还原按**字节**做（仓库里有 CRLF 文件），跑完逐字节核对。

用法：python _tools/qa/_reverse_verify_round17.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AI_CHECK = ROOT / "_tools/ai/_check_ai_guardrails.py"

ACCT = "backend/app/services/accounting_service.py"
BILLS = "backend/app/api/v1/driver_bills.py"
REPORTS = "backend/app/api/v1/reports.py"
STATS = "backend/app/services/stats_service.py"
RETENTION = "backend/app/services/data_retention.py"
INV = "backend/app/api/v1/inventory.py"

GUARDS = "tests/test_audit_round17_money.py"

#: (说明, 相对路径, 注入, 期望变红的 node；`REDLINE:` 前缀 = 跑 AI 红线并看 §25b)
CASES: list[tuple[str, str, object, str]] = [
    (
        "结算单又收走已软删订单的账单（先删单后付款）",
        ACCT,
        lambda s: s.replace(
            "                .outerjoin(Order, Order.id == DriverBill.order_id)\n",
            "",
            1,
        ).replace(
            "                    or_(DriverBill.order_id.is_(None), Order.deleted_at.is_(None)),\n",
            "",
            1,
        ),
        f"{GUARDS}::test_soft_deleted_order_bills_are_not_collected_by_a_settlement",
    ),
    (
        "月薪单生成前不锁司机行（并发付两次月薪）",
        BILLS,
        lambda s: s.replace(
            "            db.execute(select(User.id).where(User.id == d.id).with_for_update())\n", "", 1
        ),
        "REDLINE:月薪单生成前锁住司机行",
    ),
    (
        "确认结算单改回无条件赋值（confirm × cancel 并发会写成 CANCELLED+SETTLED）",
        ACCT,
        lambda s: s.replace(
            "    claimed = db.execute(\n"
            "        update(DriverSettlement)\n"
            "        .where(DriverSettlement.id == s.id, DriverSettlement.status == SettlementStatus.DRAFT)\n"
            "        .values(status=SettlementStatus.CONFIRMED)\n"
            "    )\n"
            "    if claimed.rowcount != 1:\n"
            "        db.rollback()\n"
            '        raise ValueError("这张结算单刚刚被别的操作改过（可能已确认/已作废），请刷新后查看")\n'
            "    db.refresh(s)\n",
            "    s.status = SettlementStatus.CONFIRMED\n",
            1,
        ),
        "REDLINE:确认结算单是条件 UPDATE 占位",
    ),
    (
        "商品毛利的收入侧改回『全额金额』（虚高，与营业纵览差一个数）",
        REPORTS,
        lambda s: s.replace(
            '                   _money((data["cost_covered_amount"] or Decimal("0")) - (data["cost_total"] or Decimal("0")))])',
            '                   _money(sum((i.amount for i in data["items"] if (i.cost or Decimal("0")) > 0), Decimal("0"))\n'
            '                          - (data["cost_total"] or Decimal("0")))])',
            1,
        ),
        f"{GUARDS}::test_product_profit_is_the_same_number_everywhere",
    ),
    (
        "逐行毛利改回 `amount − cost`（没有成本的行按 100% 毛利印）",
        REPORTS,
        lambda s: s.replace(
            '            gross = _money(cov - it.cost) if (it.covered_lines or 0) > 0 else "—"',
            "            gross = _money(it.amount - it.cost)",
            1,
        ),
        f"{GUARDS}::test_product_profit_is_the_same_number_everywhere",
    ),
    (
        "绩效的计费方式改回『先读 users.billing_mode』（挂规则的工资制司机被说成工资制）",
        STATS,
        lambda s: s.replace(
            '        du_billing = (snapshot_mode(du) if du is not None else "").upper()',
            '        du_billing = ((du.billing_mode or "") if du is not None else "").upper()',
            1,
        ),
        f"{GUARDS}::test_driver_performance_billing_mode_follows_the_rule",
    ),
    (
        "货损进位改回银行家舍入（与 money() 差 1 分）",
        ACCT,
        lambda s: s.replace(
            '        cost_amt = (cost * Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)',
            '        cost_amt = (cost * Decimal(qty)).quantize(Decimal("0.01"))',
            1,
        ),
        f"{GUARDS}::test_damage_amount_rounds_like_the_rest_of_the_project",
    ),
    (
        "保留任务不删库存流水（在途占用永久残留）",
        RETENTION,
        lambda s: s.replace(
            "    db.execute(delete(InventoryMovement).where(InventoryMovement.order_id.in_(ids)))\n",
            "",
            1,
        ),
        f"{GUARDS}::test_retention_purge_deletes_inventory_movements",
    ),
    (
        "「在途占用」不 join orders（软删单的预占仍算在途）",
        INV,
        lambda s: s.replace("        .join(Order, Order.id == InventoryMovement.order_id)\n", "", 1).replace(
            "            Order.deleted_at.is_(None),\n", "", 1
        ),
        f"{GUARDS}::test_inventory_summary_ignores_reservations_of_soft_deleted_orders",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_test(node: str) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "--no-header"],
        cwd=str(ROOT / "backend"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_redline(expect: str) -> tuple[bool, str]:
    """跑 AI 红线，看 §25b 里那条断言是否报红。"""
    p = subprocess.run(
        [sys.executable, str(AI_CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (p.stdout or "") + (p.stderr or "")
    hit = any("[FAIL]" in ln and expect in ln for ln in out.splitlines())
    return hit, out


def main() -> int:
    fails: list[str] = []
    # 前提：源码完好时红线与回归测试都绿
    code, out = run_test("tests/test_audit_round17_money.py")
    if code != 0:
        print("❌ 前提不成立：源码完好时 round17 的回归测试就没过")
        print(out[-1500:])
        return 1
    p = subprocess.run(
        [sys.executable, str(AI_CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if p.returncode != 0:
        print("❌ 前提不成立：源码完好时 AI 红线没过")
        print(((p.stdout or "") + (p.stderr or ""))[-1200:])
        return 1
    print("✅ 前提：源码完好时回归测试与 AI 红线都是绿的")

    touched = sorted({rel for _l, rel, _m, _n in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    crlfs = {rel: b"\r\n" in originals[rel] for rel in touched}

    for label, rel, mutate, node in CASES:
        path = ROOT / rel
        plain = originals[rel].decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            write_src(path, mutated, crlfs[rel])
            if node.startswith("REDLINE:"):
                hit, _out = run_redline(node.split(":", 1)[1])
            else:
                tcode, _tout = run_test(node)
                hit = tcode != 0
        finally:
            path.write_bytes(originals[rel])
        if hit:
            print(f"  [OK] {label} → {'红线' if node.startswith('REDLINE:') else '回归测试'}报红")
        else:
            fails.append(f"{label}：注入之后**没有任何检查报红**（修复没有被钉住）")
            print(f"  [MISS] {label} → 全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明第十七轮的修复真的被钉住了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
