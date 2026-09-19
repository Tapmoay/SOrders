"""反向验证第十八轮（账本与收款）那批修复**真的在检查**。

| 注入 | 应该红的检查 |
|---|---|
| 送达又把已收款的单抹回未收 | `test_delivery_does_not_reset_an_already_collected_order` |
| 已收款时司机报「收现金」又放行 | `test_delivery_with_cash_is_refused_when_already_collected` |
| 收款校验又去掉「已撤销」这道门槛 | `test_cancelled_order_cannot_be_collected` |
| 回写又把 REFUND 行算进去（改备注清零订单行） | `test_editing_a_refund_note_does_not_zero_the_order_line` |
| 红冲行又不受"订单已结束"约束 | `test_refund_row_detail_edit_is_refused_when_order_closed` |
| 账本行又可以改挂到别的订单 | `test_ledger_entry_cannot_be_repointed_to_another_order` |
| 导出金额又用银行家舍入 | `test_export_money_uses_half_up_like_the_rest_of_the_project` |

⚠️ 快照/还原按**字节**做，跑完逐字节核对。

用法：python _tools/qa/_reverse_verify_round19.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
ORDERS = "backend/app/api/v1/orders.py"
LEDGER = "backend/app/api/v1/ledger.py"
SYNC = "backend/app/services/ledger_sync.py"
ACCT = "backend/app/services/accounting_service.py"
REPORTS = "backend/app/api/v1/reports.py"
GUARDS = "tests/test_audit_round19_ledger_receipts.py"

CASES: list[tuple[str, str, object, str]] = [
    (
        "送达又把『已经收过款』的单抹回未收（同一笔钱能被收两次）",
        ORDERS,
        lambda s: s.replace(
            "    if _already_collected(db, order):\n"
            "        if payment == \"cash\":\n"
            "            raise ValueError(\n"
            "                \"这一单已经收过款了，司机再收一次现金就是重复收款。\"\n"
            "                \"请让派单员核对「客户收款」里这张单的记录；确认钱确实没收到的，\"\n"
            "                \"先处理掉那笔收款再送达。\"\n"
            "            )\n",
            "    if False:\n"
            "        if payment == \"cash\":\n"
            "            raise ValueError(\"探针注入\")\n",
            1,
        ),
        f"{GUARDS}::test_delivery_does_not_reset_an_already_collected_order",
    ),
    (
        "已收款时司机报『收现金』又放行（重复收款）",
        ORDERS,
        lambda s: s.replace(
            "    if _already_collected(db, order):\n",
            "    if False:\n",
            1,
        ),
        f"{GUARDS}::test_delivery_with_cash_is_refused_when_already_collected",
    ),
    (
        "收款校验又去掉『已撤销』这道门槛",
        ACCT,
        lambda s: s.replace(
            "            if (o.status or \"\").upper() == OrderStatus.CANCELLED.value:\n", "            if False:\n", 1
        ),
        f"{GUARDS}::test_cancelled_order_cannot_be_collected",
    ),
    (
        "回写又把 REFUND 行算进去（改一条红冲备注就把订单行清零）",
        SYNC,
        lambda s: s.replace(
            "    if ledger.source != LedgerSource.ORDER:\n        return\n",
            "    if ledger.source == LedgerSource.MANUAL:\n        return\n",
            1,
        ),
        f"{GUARDS}::test_editing_a_refund_note_does_not_zero_the_order_line",
    ),
    (
        "红冲行也允许改明细（F2 那条洞会从备注扩到数量/单价/金额）",
        LEDGER,
        lambda s: s.replace(
            "    detail_editable = row.source in (LedgerSource.MANUAL, LedgerSource.ORDER)\n",
            "    detail_editable = row.source in (LedgerSource.MANUAL, LedgerSource.ORDER, LedgerSource.REFUND)\n",
            1,
        ),
        f"{GUARDS}::test_refund_row_detail_edit_is_refused_when_order_closed",
    ),
    (
        "账本行又可以改挂到别的订单（回写落到那张单上）",
        LEDGER,
        lambda s: s.replace(
            "        if \"order_id\" in raw and raw[\"order_id\"] != row.order_id:\n",
            "        if False:\n",
            1,
        ).replace(
            "        if \"product_id\" in raw:\n            row.product_id = raw[\"product_id\"]\n",
            "        if \"order_id\" in raw:\n            row.order_id = raw[\"order_id\"]\n"
            "        if \"product_id\" in raw:\n            row.product_id = raw[\"product_id\"]\n",
            1,
        ),
        f"{GUARDS}::test_ledger_entry_cannot_be_repointed_to_another_order",
    ),
    (
        "导出金额又用银行家舍入（与全项目 HALF_UP 差 1 分）",
        REPORTS,
        lambda s: s.replace(
            '    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))',
            '    return float(Decimal(str(v)).quantize(Decimal("0.01")))',
            1,
        ),
        f"{GUARDS}::test_export_money_uses_half_up_like_the_rest_of_the_project",
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
    if run_test("tests/test_audit_round19_ledger_receipts.py") != 0:
        print("❌ 前提不成立：源码完好时 round19 的回归测试就没过")
        return 1
    print("✅ 前提：源码完好时 round19 的回归测试是绿的")

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
    print(f"✅ {len(CASES)} 条注入都证明第十八轮这批修复真的被钉住了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
