"""反向验证「账本口径必须与报表同一句」（R13-R6）那批修复**真的在检查**。

| 注入 | 应该红的检查 |
|---|---|
| 账本列表/账户汇总又不排隔离区 | `test_ledger_accounts_exclude_orders_in_the_recycle_bin` |
| 账本导出又不排隔离区 | `test_ledger_export_also_excludes_recycled_orders` |
| 客户经营导出又不排隔离区 | `test_ledger_and_turnover_agree_after_deleting_an_order`（口径对不上时报红） |
| 收款单又落未去重的 order_ids | `test_receipt_stores_deduped_order_ids` |
| 可见性判据写反（把"在回收站"当成可见） | 前两条 |

用法：python _tools/qa/_reverse_verify_round20.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
LEDGER = "backend/app/api/v1/ledger.py"
EXPORT = "backend/app/services/ledger_export.py"
SCOPE = "backend/app/services/ledger_scope.py"
ACCT = "backend/app/services/accounting_service.py"
GUARDS = "tests/test_audit_round20_ledger_scope.py"

CASES: list[tuple[str, str, object, str]] = [
    (
        "账本列表/账户汇总又不排隔离区订单",
        LEDGER,
        lambda s: s.replace("    q = visible_ledger_select()  # 同上：隔离区订单的账不算（R13-R6）\n", "    q = select(Ledger)\n", 1),
        f"{GUARDS}::test_ledger_accounts_exclude_orders_in_the_recycle_bin",
    ),
    (
        "账本导出又不排隔离区订单",
        EXPORT,
        lambda s: s.replace(
            "        # 隔离区（软删）订单的那份账不算（R13-R6）：与报表侧同一句\n        visible_ledger_select()\n",
            "        select(Ledger)\n",
            1,
        ),
        f"{GUARDS}::test_ledger_export_also_excludes_recycled_orders",
    ),
    (
        "可见性判据写反（把『在回收站』当成可见）",
        SCOPE,
        lambda s: s.replace(
            "            ~exists(order_row.where(Order.deleted_at.isnot(None))),\n",
            "            exists(order_row.where(Order.deleted_at.isnot(None))),\n",
            1,
        ),
        f"{GUARDS}::test_ledger_accounts_exclude_orders_in_the_recycle_bin",
    ),
    (
        "自动账本行不再要求订单已送达（漂移出来的行又会被算进账本）",
        SCOPE,
        lambda s: s.replace(
            "                exists(order_row.where(Order.status == OrderStatus.DELIVERED)),\n",
            "                exists(order_row),\n",
            1,
        ),
        f"{GUARDS}::test_auto_ledger_rows_for_undelivered_orders_are_not_counted",
    ),
    (
        "收款单又落未去重的 order_ids",
        ACCT,
        lambda s: s.replace("        order_ids=order_ids or None,\n", "        order_ids=body.order_ids,\n", 1),
        f"{GUARDS}::test_receipt_stores_deduped_order_ids",
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


def run_test(node: str) -> int:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "--no-header"],
        cwd=str(ROOT / "backend"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode


def main() -> int:
    fails: list[str] = []
    if run_test("tests/test_audit_round20_ledger_scope.py") != 0:
        print("❌ 前提不成立：源码完好时 round20 的回归测试就没过")
        return 1
    print("✅ 前提：源码完好时 round20 的回归测试是绿的")

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
            red = run_test(node) != 0
        finally:
            path.write_bytes(originals[rel])
        if red:
            print(f"  [OK] {label} → 回归测试报红")
        else:
            fails.append(f"{label}：注入之后**测试仍然通过**（修复没有被钉住）")
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
    print(f"✅ {len(CASES)} 条注入都证明这批修复真的被钉住了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
