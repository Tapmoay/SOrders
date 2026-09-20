"""反向验证「账本那套版式与同源」那几条红线**真的会红**。

为什么这块要反向验证：这一整块改的是**版式与取数来源**，坏掉的方式全都"不报错、不崩"——
8 件事又回账本页顶部（用户明确否掉的那一版）、两张卡片撞色、图自己再聚合一遍、
账户类硬凑折线、配色太近。这些只有机器判据能拦住，而"判据本身是不是在检查"只能靠注入法证明。

用法：python _tools/qa/_reverse_verify_ledger_dashboard.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_ledger_dashboard.py"

ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = ANDROID / "ui/dispatcher/DispatcherLedgerScreen.kt"
VM = ANDROID / "ui/dispatcher/DispatcherLedgerViewModel.kt"
DATA = ANDROID / "ui/dispatcher/LedgerCharts.kt"
WORKBENCH = ANDROID / "ui/home/WorkbenchScreen.kt"
MODULES = ANDROID / "ui/nav/Modules.kt"
COMPONENTS = ANDROID / "ui/common/Components.kt"
COLOR = ANDROID / "ui/theme/Color.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "账本页又长出左栏（用户明确否掉的那一版）",
        SCREEN,
        "            LedgerTabBar(tab = vm.tab, onTab = { vm.selectTab(it) })",
        "            LedgerTabBar(tab = vm.tab, onTab = { vm.selectTab(it) })\n"
        "            MasterRail(items = emptyList(), selectedKey = \"\", onSelect = {})",
        "账本页不再有左栏",
    ),
    (
        "账本页又自己带那 4 个工具入口（和工作台卡片重复）",
        SCREEN,
        "    initialTab: Int = 0,",
        "    onOpenReceipts: () -> Unit = {},\n    initialTab: Int = 0,",
        "账本页不再自己带",
    ),
    (
        "工作台不再渲染第二张卡片（8 件事没地方去）",
        WORKBENCH,
        "    val ledgerEntries = if (role == Role.DISPATCHER) Modules.dispatcherLedgerEntries else emptyList()",
        "        val ledgerEntries: List<ModuleEntry> = emptyList()",
        "工作台渲染第二张卡片",
    ),
    (
        "又给账本那张卡片加回标题（用户要求去掉那几个字）",
        WORKBENCH,
        "item { WorkbenchCard(title = null, entries = ledgerEntries, onOpen = onOpen) }",
        'item { WorkbenchCard(title = "账本管理", entries = ledgerEntries, onOpen = onOpen) }',
        "账本那张卡片不带标题",
    ),
    (
        "4 类账各建一个页面（不再走同一条带参数的路由）",
        MODULES,
        "Routes.dispatcherLedger(1)",
        "Routes.DISPATCH_LEDGER",
        "同一条带参数的路由",
    ),
    (
        "8 格里少一格（实测 7 格）",
        MODULES,
        '        ModuleEntry("车辆台账", Routes.DISPATCH_VEHICLES, Icons.Default.DirectionsCar, color = 0xFF4E342EL),           // 深棕\n',
        "",
        "正好 8 格",
    ),
    (
        "主网格里又有「账本管理」那一格（同一个东西两个入口）",
        MODULES,
        "    val dispatcherEntries: List<ModuleEntry> = listOf(\n",
        "    val dispatcherEntries: List<ModuleEntry> = listOf(\n"
        '        ModuleEntry("账本管理", Routes.DISPATCH_LEDGER, Icons.Default.AccountBalanceWallet, color = MoneyOrange),\n',
        "主网格里不再有",
    ),
    (
        "图标格抄了第二份实现（两处迟早长得不一样）",
        WORKBENCH,
        "        item { WorkbenchCard(title = null, entries = entries, onOpen = onOpen) }",
        "        item { WorkbenchTile(entries.first(), onOpen) }\n"
        "        item { WorkbenchCard(title = null, entries = entries, onOpen = onOpen) }",
        "图标格实现处数正常",
    ),
    (
        "末行不补空位（最后一行的图标会被拉宽、与上面不对齐）",
        WORKBENCH,
        "repeat(GRID_COLUMNS - row.size) { Spacer(Modifier.weight(1f)) }",
        "repeat(0) { Spacer(Modifier.weight(1f)) }",
        "末行补空位",
    ),
    (
        "账本 VM 自己算区间（第二份日期口径）",
        VM,
        "        val r = DatePresets.rangeOf(label, LocalDate.now())",
        "        val r: Pair<String, String>? = null",
        "账本 VM 的档位也调 DatePresets.rangeOf",
    ),
    (
        "通用筛选条自己算区间（不再走 DatePresets）",
        COMPONENTS,
        "                val r = DatePresets.rangeOf(p, LocalDate.now())",
        "                val r: Pair<String, String>? = null",
        "筛选条调 DatePresets.rangeOf",
    ),
    (
        "账本页自己再聚合一遍金额（图与合计两份口径）",
        SCREEN,
        "    SectionCard {\n        Text(title, style = MaterialTheme.typography.titleMedium)",
        "    val _secondSource = entries.sumOf { moneyToDouble(it.total) }\n"
        "    SectionCard {\n        Text(title, style = MaterialTheme.typography.titleMedium)",
        "账本页自己不再求和",
    ),
    (
        "账户类也硬凑一条按天折线（明细被截断时就比合计小）",
        DATA,
        "    if (tab == 0 || tab == 1) CHART_TYPES_ALL else listOf(CHART_BAR, CHART_PIE)",
        "    CHART_TYPES_ALL",
        "账户类不给折线",
    ),
    (
        "扇形环心的数从别处塞进来（与图上的块加不起来）",
        SCREEN,
        '                    centerValue = "¥" + formatMoney(rows.sumOf { it.second }.toString()),',
        '                    centerValue = "¥" + formatMoney(vm.total().toString()),',
        "环心那个数由切片求和得出",
    ),
    (
        "页面自己画一张图（绕过共享的图表组件）",
        SCREEN,
        "private fun LedgerTabBar(",
        "private fun _ownChart() { Canvas(Modifier) {} }\nprivate fun LedgerTabBar(",
        "自己画的图只许在 Charts.kt",
    ),
    (
        "扇形配色删到 5 色（不够画 6 块）",
        COLOR,
        "    ShipperTeal,        // #00A2C7 湖蓝\n    0xFF8D6E63L,        // #8D6E63 棕（第七块之后的兜底色）\n",
        "",
        "配色至少 6 色",
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


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1500:]}")
        return 1
    print("✅ 前提：源码完好时这一节红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            code, out = run_check()
            fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            hit = code != 0 and any(expect in ln for ln in fails)
            detail = f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")
        finally:
            write_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    if bad:
        print(f"\n❌ {bad}/{total} 不达标。")
        return 1
    print(f"\n✅ {total}/{total} 都红了：这一节的判据真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
