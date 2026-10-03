"""反向验证 BUG-0007（结算单金额与明细同源）那批修复**真的在检查**。

2026-10-03 用户点名：结账单的数字和明细对不上必须查明原因（这是钱的事）。
修法是「取数收成一处 + 建单当刻锁定 bill_ids + 手工改额记 adjustment + 作废解锁去掉门闩」，
这份脚本逐条把修复撤回，证明对应的检查（判据脚本 / 回归用例）会红。

| 注入 | 应该红的检查 |
|---|---|
| 确认时不再认 bill_ids（等于改回按月重取） | 判据 / 混着单号明细与孤儿明细 那条用例 |
| 建单不记 bill_ids（锁了个空清单） | 同上 |
| 构造结算单时漏传 bill_ids | 同上 |
| 明细少了不报错（gone 分支失效） | 确认前明细被抢走 那条用例 |
| 手工改额不记差额 | 手工改额记差额 那条用例 |
| 确认的恒等式去掉 adjustment | 同上 |
| 付款的恒等式去掉 adjustment | 同上 |
| 作废解锁重新挂上 settle_type / order_ids 门闩 | 作废解锁不再看_order_ids 那条用例 |
| 迁移少搬 adjustment 一列 / 版本号对不上 | 判据 |
| 自愈副本的门闩去掉 / 模型少一列 / 出参少一个字段 | 判据 |
| 回归用例掉数 / 登记表或文档里换成别的 ID | 判据 |

⚠️ 快照/还原按**字节**做（仓库里有 CRLF 文件），跑完逐字节核对。

用法：python _tools/qa/_reverse_verify_settlement_single_source.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
JUDGE = ROOT / "_tools/qa/_check_settlement_single_source.py"

ACCT = "backend/app/services/accounting_service.py"
MODEL = "backend/app/models/driver_settlement.py"
SCHEMA = "backend/app/schemas/accounting_v2.py"
API = "backend/app/api/v1/driver_settlements.py"
BOOT = "backend/app/core/schema_bootstrap.py"
MIG = "backend/app/migrations/017_settlement_bill_ids.py"
KTEST = "backend/tests/test_settlement_single_source.py"
DOC = "docs/changes/BUG-0007.md"
REG = "docs/changes/README.md"

MIXED = f"{KTEST}::test_混着单号明细与孤儿明细_确认不再少算"
STOLEN = f"{KTEST}::test_确认前明细被抢走就明确报错"
MANUAL = f"{KTEST}::test_手工改额记差额_确认与付款都认它"
UNLOCK = f"{KTEST}::test_作废解锁不再看_order_ids"

#: (说明, 相对路径, 注入, 期望变红的 node；`CHECK:` 前缀 = 跑判据脚本并找那条 [FAIL])
CASES: list[tuple[str, str, object, str]] = [
    (
        "确认时不再认 bill_ids（等于改回按月重取：孤儿又取不到了）",
        ACCT,
        lambda s: s.replace("recorded = [int(x) for x in (s.bill_ids or [])]", "recorded = []", 1),
        MIXED,
    ),
    (
        "建单不记 bill_ids（锁定了一份空清单）",
        ACCT,
        lambda s: s.replace("bill_ids = [b.id for b in bills]", "bill_ids = []", 1),
        MIXED,
    ),
    (
        "构造结算单时漏传 bill_ids（模型有列、接口不写）",
        ACCT,
        lambda s: s.replace("        bill_ids=bill_ids,\n", "", 1),
        MIXED,
    ),
    (
        "明细少了不报错（锁定的明细被抢走也照样确认）",
        ACCT,
        lambda s: s.replace("        if gone:", "        if False and gone:", 1),
        STOLEN,
    ),
    (
        "手工改额不记差额（改过额的单又变成永远确认不了）",
        ACCT,
        lambda s: s.replace("        adjustment = Decimal(body.amount) - amount", "        adjustment = Decimal(\"0\")", 1),
        MANUAL,
    ),
    (
        "确认的恒等式去掉 adjustment",
        ACCT,
        lambda s: s.replace("if Decimal(s.amount) != locked_total + adjustment:", "if Decimal(s.amount) != locked_total:", 1),
        MANUAL,
    ),
    (
        "付款的恒等式去掉 adjustment",
        ACCT,
        lambda s: s.replace(
            "if Decimal(s.amount) != live_total + Decimal(s.adjustment or Decimal(\"0\")):",
            "if Decimal(s.amount) != live_total:",
            1,
        ),
        MANUAL,
    ),
    (
        "作废解锁重新挂上 settle_type / order_ids 门闩（孤儿单又解不开）",
        ACCT,
        lambda s: s.replace(
            "    bills = list(\n",
            "    bills = [] if not (s.settle_type == DriverBillType.PIECE and s.order_ids) else list(\n",
            1,
        ),
        UNLOCK,
    ),
    (
        "迁移的版本号与编号对不上",
        MIG,
        lambda s: s.replace("VERSION = 17", "VERSION = 18", 1),
        "CHECK:正式搬迁走迁移",
    ),
    (
        "迁移少搬 adjustment 一列（老库永远没有它）",
        MIG,
        lambda s: s.replace('"adjustment": "adjustment DECIMAL(12,2) NOT NULL DEFAULT 0",\n', "", 1),
        "CHECK:迁移里两列都定义了",
    ),
    (
        "自愈副本的门闩去掉（老库补列再也不跑）",
        BOOT,
        lambda s: s.replace('if "driver_settlements" in insp.get_table_names():', "if False:", 1),
        "CHECK:老库兜底副本",
    ),
    (
        "模型少一列（bill_ids 不落库）",
        MODEL,
        lambda s: s.replace("    bill_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)\n", "", 1),
        "CHECK:模型两张脸",
    ),
    (
        "出参少一个字段（adjustment 客户端拿不到）",
        SCHEMA,
        lambda s: s.replace('    adjustment: Decimal = Decimal("0")\n', "", 1),
        "CHECK:出参带上它们",
    ),
    (
        "列表出参少一个字段",
        API,
        lambda s: s.replace('"adjustment": r.adjustment,\n', "", 1),
        "CHECK:列表出参也带上",
    ),
    (
        "回归用例掉到 7 条（少一条就没人钉了）",
        KTEST,
        lambda s: s.replace("def test_作废解锁不再看_order_ids(", "def _test_作废解锁不再看_order_ids(", 1),
        "CHECK:回归用例",
    ),
    (
        "登记表里换成别的 ID",
        REG,
        lambda s: s.replace("| `BUG-0007` |", "| `BUG-XXXX` |", 1),
        "CHECK:改动登记表",
    ),
    (
        "改动文档里不提 adjustment（根因与修法写不清）",
        DOC,
        lambda s: s.replace("adjustment", "adjx"),
        "CHECK:文档写清了根因与修法",
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


def run_judge() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(JUDGE)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_judge()
    if code != 0:
        print("❌ 前提不成立：源码完好时判据脚本就没过")
        print(out[-1500:])
        return 1
    code, out = run_test("tests/test_settlement_single_source.py")
    if code != 0:
        print("❌ 前提不成立：源码完好时回归用例就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时判据脚本与 8 条回归用例都是绿的")

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
            if node.startswith("CHECK:"):
                jcode, jout = run_judge()
                expect = node.split(":", 1)[1]
                hit = jcode != 0 and any("[FAIL]" in ln and expect in ln for ln in jout.splitlines())
            else:
                tcode, _tout = run_test(node)
                hit = tcode != 0
        finally:
            path.write_bytes(originals[rel])
        kind = "判据" if node.startswith("CHECK:") else "回归测试"
        if hit:
            print(f"  [OK] {label} → {kind}报红")
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
    print(f"✅ {len(CASES)} 条注入都证明 BUG-0007 的修复真的被钉住了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
