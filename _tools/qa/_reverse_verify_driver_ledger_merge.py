"""反验：把 CHG-0075 那本判据（`_check_driver_ledger_merge.py`）的每一根钉子逐个敲松，它必须每次都红。

用法：`python _tools/qa/_reverse_verify_driver_ledger_merge.py`

规矩与另外两本反验一样：
1. 先确认源码完好时那本判据是绿的（否则这本脚本没有意义）；
2. 一次只改一处（`count == 1` 才动手，改不到就 `[SKIP]` 并计失败）；
3. 跑判据，**要求它红**；跑完 `finally` 把文件按字节写回，并读回来逐字节比对；
4. 全部跑完再验一次「还原之后判据重新变绿」，然后打印 `N/N`。

（2026-10-07 CHG-0075；变更单 docs/changes/CHG-0075.md）
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 判据会打 ✅/❌：控制台/管道按 GBK 编码时直接 UnicodeEncodeError（看着跑过了其实没验）。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
CHECK = ROOT / "_tools" / "qa" / "_check_driver_ledger_merge.py"
MODULES = ANDROID / "ui" / "nav" / "Modules.kt"
NAVGRAPH = ANDROID / "ui" / "nav" / "NavGraph.kt"
LEDGER_VM = ANDROID / "ui" / "dispatcher" / "DispatcherLedgerViewModel.kt"
SETTLEMENT_SCREEN = ANDROID / "ui" / "dispatcher" / "FreightSettlementScreen.kt"
SETTLEMENT_VM = ANDROID / "ui" / "dispatcher" / "FreightSettlementViewModel.kt"

# (说明, 目标文件, 原文, 替换成) —— 每一处都对应判据里的一条红线。
CASES: list[tuple[str, Path, str, str]] = [
    (
        "工作台那格「司机运费结算」又长回来（两个入口 = 两种时间口径，两边都看着对）",
        MODULES,
        'ModuleEntry("账本管理", Routes.LEDGER_HOME, Icons.Default.AccountBalanceWallet, color = MoneyOrange),',
        'ModuleEntry("账本管理", Routes.LEDGER_HOME, Icons.Default.AccountBalanceWallet, color = MoneyOrange),\n        ModuleEntry("司机运费结算", Routes.FREIGHT_SETTLEMENT, Icons.Default.Payments, color = 0xFFFF7544L),',
    ),
    (
        "入口页那格退回「司机账」（= 账本页第 4 档，同一件事又有两个地方）",
        MODULES,
        'ModuleEntry("司机账 · 运费结算", Routes.FREIGHT_SETTLEMENT, Icons.Default.LocalShipping, color = 0xFF208F37L),',
        'ModuleEntry("司机账", Routes.dispatcherLedger(1), Icons.Default.LocalShipping, color = 0xFF208F37L),',
    ),
    (
        "批发商账退回第 4 档（越界的 tab 又能从入口进来）",
        MODULES,
        'ModuleEntry("批发商账", Routes.dispatcherLedger(2), Icons.Default.Storefront, color = 0xFF8F7215L),',
        'ModuleEntry("批发商账", Routes.dispatcherLedger(3), Icons.Default.Storefront, color = 0xFF8F7215L),',
    ),
    (
        "越界的 deep link 不再落回订单账（标题写订单账、页面走账户汇总）",
        LEDGER_VM,
        "var tab by mutableStateOf(if (initialTab in 0..2) initialTab else 0)",
        "var tab by mutableStateOf(initialTab)",
    ),
    (
        "账本页 VM 又把司机那一档的取数长回来",
        LEDGER_VM,
        "    fun load() {",
        "    fun driverOrdersOf(key: String) = emptyList<Any>()\n\n    fun load() {",
    ),
    (
        "账本页 VM 又挂上「司机结算单」那种入口",
        LEDGER_VM,
        "    fun load() {",
        "    fun onOpenSettlements() {}\n\n    fun load() {",
    ),
    (
        "批量核销门又算上货主/批发商那一层（订单账那层没有「某个人的合计」）",
        LEDGER_VM,
        "if (personKey == null || tab == 0) return",
        "if (personKey == null || tab == 1) return",
    ),
    (
        "结算页的默认档自己拼一个月份（回到「两边都看着对」）",
        SETTLEMENT_VM,
        "var preset by mutableStateOf(DatePresets.THIS_MONTH)",
        'var preset by mutableStateOf("2026-10")',
    ),
    (
        "宽边界的下界抄成第二份（改一处漏一处）",
        SETTLEMENT_VM,
        "val from = rangeFrom ?: DatePresets.WIDE_FROM",
        'val from = rangeFrom ?: "2000-01-01"',
    ),
    (
        "宽边界的上界抄成第二份",
        SETTLEMENT_VM,
        "val to = rangeTo ?: DatePresets.WIDE_TO",
        'val to = rangeTo ?: "2099-12-31"',
    ),
    (
        "取数回流到按月的 freightSettlement(month)",
        SETTLEMENT_VM,
        "container.repo.freightSettlementRange(",
        "container.repo.freightSettlement(",
    ),
    (
        "结算页把 2026-09-22 那版年月网格装回来",
        SETTLEMENT_SCREEN,
        "    DateFilterDialogs(",
        "    MonthPickerSheet(month = vm.preset, onPick = {}, onCustom = {}, onDismiss = {})\n    DateFilterDialogs(",
    ),
    (
        "明细退回「点一下跳订单详情页」",
        SETTLEMENT_SCREEN,
        "vm.toggleOrderDetail(o.orderId)",
        "onOpenOrder(o.orderId)",
    ),
    (
        "展开块不再跟着 VM 的展开态（永远显示加载中）",
        SETTLEMENT_SCREEN,
        "loading = vm.expandedOrderLoading",
        "loading = false",
    ),
    (
        "「司机结算（按月）」那一行不再挂在页面上（孤儿页又没人进得去）",
        SETTLEMENT_SCREEN,
        "SettlementSheetsRow(onOpenSettlements)",
        "",
    ),
    (
        "入口页那格与结算页标题不同名（同一件事写的字符串不一样）",
        SETTLEMENT_SCREEN,
        'title = "司机账 · 运费结算",',
        'title = "司机运费结算",',
    ),
    (
        "NavGraph 不再把那个出口接到孤儿路由上",
        NAVGRAPH,
        "                onOpenSettlements = { navController.navigate(Routes.DISPATCH_SETTLEMENTS) },\n",
        "",
    ),
    (
        "结算页长出核销（把「该给他多少」和「他欠我多少」混成一个口径）",
        SETTLEMENT_VM,
        "    fun load() {",
        "    fun openSettleAll() {\n    }\n\n    fun load() {",
    ),
    (
        "司机应得那一列换成货主运费（两个数合成一个）",
        SETTLEMENT_SCREEN,
        "formatMoney(o.payTotal)",
        'formatMoney(o.freightFee ?: "0")',
    ),
    (
        "待定价那一行不再是「待定价」（用户点名要保留的那类功能）",
        SETTLEMENT_SCREEN,
        '"运费 待定价"',
        '"运费 --"',
    ),
]


def run_check() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这本判据应当是绿的，实测是红的")
        print(out[-2000:])
        return 2
    print("✅ 前提：源码完好时这一节红线是绿的")

    missed: list[str] = []
    for label, path, old, new in CASES:
        raw = path.read_bytes()
        original = raw.decode("utf-8")
        crlf = "\r\n" in original
        text = original.replace("\r\n", "\n")
        n = text.count(old)
        if n != 1:
            print(f"[SKIP] {label} —— 锚点在 {path.name} 里命中 {n} 次（期望 1 次）")
            missed.append(label)
            continue
        mutated = text.replace(old, new, 1)
        try:
            path.write_text(mutated if not crlf else mutated.replace("\n", "\r\n"), encoding="utf-8", newline="")
            code2, out2 = run_check()
        finally:
            path.write_bytes(raw)
        if path.read_bytes() != raw:
            print(f"[FATAL] {path.name} 没有逐字节还原，停下")
            return 2
        if code2 == 0:
            print(f"[MISS] {label} —— 注入之后判据还是绿的")
            missed.append(label)
            continue
        hit = next((ln.strip() for ln in out2.splitlines() if "[FAIL]" in ln), "")
        print(f"[OK]   {label}")
        if hit:
            print(f"        → {hit[:120]}")

    code3, _ = run_check()
    if code3 != 0:
        print("❌ 收尾自证失败：还原之后判据不是绿的")
        return 2
    total = len(CASES)
    if missed:
        print(f"❌ {total - len(missed)}/{total} 成立，没抓到的：{len(missed)} 种")
        for label in missed:
            print(f"   - {label}")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
