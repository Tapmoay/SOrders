"""反向验证「工作台一格 → 账本管理入口页 → 账本页看账」那几条红线**真的会红**。

为什么这块要反向验证：这一整块改的是**版式与入口位置**，坏掉的方式全都"不报错、不崩"——
工作台又长出第二张卡片（用户明确否掉的那一版）、6 件事又摆回网格、入口页自己排一遍格子
（两页版式各偏一点）、司机结算又单独占一格、车辆管理从桌面上消失、4 类账各建一个页面。
这些只有机器判据能拦住，而"判据本身是不是在检查"只能靠注入法证明。

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
PRESETS = ANDROID / "ui/common/DatePresets.kt"
PERSON_SCREEN = ANDROID / "ui/dispatcher/LedgerPersonScreen.kt"
LEDGER_HOME = ANDROID / "ui/dispatcher/LedgerHomeScreen.kt"
REPORT_HOME = ANDROID / "ui/dispatcher/ReportHome.kt"
ENTRY_GRID = ANDROID / "ui/common/EntryGrid.kt"
WORKBENCH = ANDROID / "ui/home/WorkbenchScreen.kt"
MODULES = ANDROID / "ui/nav/Modules.kt"
NAVGRAPH = ANDROID / "ui/nav/NavGraph.kt"
COLOR = ANDROID / "ui/theme/Color.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "工作台又长出第二张卡片（用户当天推翻的那一版）",
        WORKBENCH,
        "        item { WelcomeBar(role) }\n",
        "        item { WelcomeBar(role) }\n"
        "        item { EntryGrid(entries = Modules.dispatcherLedgerEntries, onOpen = onOpen, onMove = {}, onDrop = {}) }\n",
        "工作台不再渲染第二张卡片",
    ),
    (
        "6 件事又摆回工作台网格（账本管理这个统一入口白做了）",
        MODULES,
        '        ModuleEntry("订单账", Routes.dispatcherLedger(0), Icons.Default.AccountBalanceWallet, color = MoneyOrange),     // 橙 · 账本本体\n',
        "",
        "正好 6 格",
    ),
    (
        "「账本管理」那一格从网格里消失（入口没了）",
        MODULES,
        '        ModuleEntry("账本管理", Routes.LEDGER_HOME, Icons.Default.AccountBalanceWallet, color = MoneyOrange),           // 橙 · 账本（跨端同色）\n',
        "",
        "「账本管理」回到网格里",
    ),
    (
        "「车辆管理」不放桌面上了（用户明确要求放桌面）",
        MODULES,
        '        ModuleEntry("车辆管理", Routes.DISPATCH_VEHICLES, Icons.Default.DirectionsCar, color = 0xFF48F0F0L),            // 亮青 · 车与车况（用户：「车辆管理直接放在桌面上」）\n',
        "",
        "「车辆管理」在网格里",
    ),
    (
        "「开销管理」又在网格里单独占一格（两个入口＝用户以为丢了东西）",
        MODULES,
        '        ModuleEntry("账本管理", Routes.LEDGER_HOME, Icons.Default.AccountBalanceWallet, color = MoneyOrange),           // 橙 · 账本（跨端同色）\n',
        '        ModuleEntry("账本管理", Routes.LEDGER_HOME, Icons.Default.AccountBalanceWallet, color = MoneyOrange),\n'
        '        ModuleEntry("开销管理", Routes.DISPATCH_EXPENSES, Icons.Default.Receipt, color = 0xFF1565C0L),\n',
        "网格里没有「开销管理」",
    ),
    (
        "「司机结算」又单独占一格（用户点名要合并成一个）",
        MODULES,
        '        ModuleEntry("客户收款", Routes.DISPATCH_RECEIPTS, Icons.Default.Payments, color = 0xFF512DA8L),                 // 深紫\n',
        '        ModuleEntry("客户收款", Routes.DISPATCH_RECEIPTS, Icons.Default.Payments, color = 0xFF512DA8L),\n'
        '        ModuleEntry("司机结算", Routes.DISPATCH_SETTLEMENTS, Icons.Default.Handshake, color = 0xFF7CB342L),\n',
        "6 格里没有「司机结算」",
    ),
    # ---- 第四轮（2026-09-20）：账本页的排版与那两处"直接去掉" ----
    (
        "账本页里又长出一条档位导航（用户刚否掉的「老的导航栏」）",
        SCREEN,
        "                if (vm.tab != 0) {\n                    PersonTriggerRow(\n",
        "                LedgerTabBar(tab = vm.tab, onTab = { })\n"
        "                if (vm.tab != 0) {\n                    PersonTriggerRow(\n",
        "4 页签导航没了",
    ),
    (
        "人员那一行整条消失（用户点名要的「选择人物」这一步）",
        SCREEN,
        "                if (vm.tab != 0) {\n                    PersonTriggerRow(\n",
        "                if (false) {\n                    PersonTriggerRow(\n",
        "人员那一行真的会渲染",
    ),
    # ---- 第五轮（2026-09-20）：图全删、时间换药丸、人换抽屉 ----
    (
        "账本页又画回三张图（用户：「直接去掉就行了…在报表中心看就可以了」）",
        SCREEN,
        "                Box(Modifier.weight(1f).fillMaxHeight()) {\n",
        "                LedgerChartCard(vm)\n"
        "                LineChart(listOf(1f), listOf(\"x\"), Color.Blue)\n"
        "                Box(Modifier.weight(1f).fillMaxHeight()) {\n",
        "账本页不画折线",
    ),
    (
        "时间又变回那一行胶囊（用户：「太复杂了…换一种崭新形式」）",
        SCREEN,
        "                        DatePresetPill(\n",
        "                        DatePresetRow(selected = vm.preset, customFrom = null, customTo = null, onPick = { })\n"
        "                        DatePresetPill(\n",
        "账本页不再铺那一行日期胶囊",
    ),
    (
        "时间与人变成同一种形态（用户：「不要选择一样的展现形式」）",
        SCREEN,
        "                        DatePresetPill(\n",
        "                        DatePresetRow(selected = vm.preset, customFrom = null, customTo = null, onPick = { })\n"
        "                        DatePresetPill(\n",
        "账本页不再铺那一行日期胶囊",
    ),
    (
        "选人退回「一排 chip」（用户：「假如司机多的话，那我要选该怎么去选呢？」）",
        SCREEN,
        "        drawerContent = {\n",
        "        drawerContent = { LazyRow { item { Text(\"全部\") } } }\n        drawerContent = {\n",
        "选人不是一排 chip",
    ),
    (
        "抽屉里的搜索改成「筛页面合计」（关掉抽屉后剩下的那个总数对不上账）",
        VM,
        "        val rows = accountRows()\n",
        "        val rows = visibleAccountRows()\n",
        "抽屉里的搜索**不改页面上的合计**",
    ),
    (
        "默认档位退回「本月」（用户要的是「默认今天，没单才退」）",
        VM,
        "    var preset by mutableStateOf(DatePresets.TODAY)\n",
        "    var preset by mutableStateOf(DatePresets.THIS_MONTH)\n",
        "默认档位 = 今天",
    ),
    (
        "退档只退到「昨天」就停（前天有单也看不到）",
        PRESETS,
        "    val AUTO_LADDER = listOf(TODAY, YESTERDAY, BEFORE_YESTERDAY, LAST_7)",
        "    val AUTO_LADDER = listOf(TODAY, YESTERDAY, LAST_7)",
        "退档阶梯四档齐全",
    ),
    (
        "账本页又抄了一份自己的阶梯（两份迟早走散）",
        VM,
        "        for (label in DatePresets.AUTO_LADDER) {\n            if (periodHasData(label)) {",
        "        for (label in listOf(DatePresets.TODAY, DatePresets.YESTERDAY)) {\n            if (periodHasData(label)) {",
        "账本页读的是那一份共享阶梯",
    ),
    (
        "用户手动挑过档位之后，退档还会把他拽回去",
        VM,
        "        if (userPickedPreset) return\n        for (label in AUTO_LADDER) {\n            if (periodHasData(label)) {\n",
        "        for (label in AUTO_LADDER) {\n            if (periodHasData(label)) {\n",
        "**用户自己挑过档位之后永不再自动改**",
    ),
    (
        "用户自己挑过档位之后，点某个人还会被他拽走（抢方向盘）",
        VM,
        "        if (userPickedPreset) return\n        for (label in AUTO_LADDER) {\n            val r = DatePresets.rangeOf(label, LocalDate.now()) ?: continue\n",
        "        for (label in AUTO_LADDER) {\n            val r = DatePresets.rangeOf(label, LocalDate.now()) ?: continue\n",
        "那个人退档与页面退档共用同一个开关",
    ),
    (
        "点开某个人时不再退档（每个人都是空屏）",
        VM,
        "                if (personOrders.isEmpty()) fallbackForPerson(key)\n",
        "",
        "点开某个人、他这一段没单时也退档",
    ),
    (
        "账本页的档位又能被切开（入口页定死的档位形同虚设）",
        VM,
        "    var tab by mutableStateOf(initialTab)\n        private set\n",
        "    var tab by mutableStateOf(initialTab)\n\n    fun selectTab(i: Int) { tab = i }\n",
        "也没有能切档位的方法",
    ),
    (
        "司机结算单入口又挂回账本页（用户：「那个结算，这个也直接去掉」）",
        SCREEN,
        "    initialTab: Int = 0,\n",
        "    onOpenSettlements: () -> Unit = {},\n    initialTab: Int = 0,\n",
        "「司机结算单」入口没了",
    ),
    (
        "批量核销在「全部人」那一层也能点（收的钱会记到某个人的档案上）",
        VM,
        "        if (personKey == null || tab == 1) return\n",
        "",
        "批量核销**必须先选中某个人**",
    ),
    (
        "批量核销的金额改成界面上自己把行金额加起来（与后端逐单校验对不上）",
        VM,
        "        centsToMoney(settleAllTargets().sumOf { orderArrearsCents(it) })",
        "        centsToMoney(settleAllTargets().sumOf { orderReceivableCents(it) })",
        "批量金额 = 各单欠款之和",
    ),
    (
        "两个核销弹层各写一份收款方式（单张加了「挂账结清」批量没加）",
        PERSON_SCREEN,
        "private fun SettleMethodChips(vm: DispatcherLedgerViewModel) {\n",
        "private fun SettleMethodChips(vm: DispatcherLedgerViewModel) {\n"
        "    Text(\"收款方式（抄的第二份）\", style = MaterialTheme.typography.titleSmall)\n"
        "}\n\n"
        "private fun SettleMethodChips(vm: DispatcherLedgerViewModel) {\n",
        "收款方式定义处数正常",
    ),
    (
        "入口页自己排一遍格子（两页版式各偏一点）",
        LEDGER_HOME,
        "            entries = Modules.ledgerHomeEntries.map {",
        "            entries = emptyList<com.tapmoay.sorders.ui.common.EntryCard>().also { _ ->\n"
        "                androidx.compose.foundation.lazy.grid.LazyVerticalGrid(\n"
        "                    columns = androidx.compose.foundation.lazy.grid.GridCells.Fixed(2), modifier = Modifier) {}\n"
        "            }?.let { Modules.ledgerHomeEntries.map {",
        "两个入口页都不自己排格子",
    ),
    (
        "报表中心不再用共用版式（各写一份）",
        REPORT_HOME,
        "        EntryCardGrid(\n",
        "        androidx.compose.foundation.lazy.grid.LazyVerticalGrid(\n"
        "            columns = androidx.compose.foundation.lazy.grid.GridCells.Fixed(2), modifier = Modifier) {}\n"
        "        EntryCardGrid(\n",
        "两个入口页都不自己排格子",
    ),
    (
        "4 类账各建一个页面（不再走同一条带参数的路由）",
        MODULES,
        "        ModuleEntry(\"货主账\", Routes.dispatcherLedger(2), Icons.Default.PeopleAlt, color = 0xFF00695CL),               // 深青 · 货主欠多少\n",
        "        ModuleEntry(\"货主账\", Routes.SHIPPER_LEDGER, Icons.Default.PeopleAlt, color = 0xFF00695CL),\n",
        "4 类账走**同一条带参数的路由**",
    ),
    (
        "入口页的路由没注册（点「账本管理」什么都不发生）",
        NAVGRAPH,
        "        composable(Routes.LEDGER_HOME) {\n",
        "        composable(\"dispatcher/ledger/home-unused\") {\n",
        "入口页在 NavGraph 注册了",
    ),
    (
        "车辆管理那一格换成「太深」的色（用户否过这一类）",
        MODULES,
        "color = 0xFF48F0F0L),            // 亮青 · 车与车况",
        "color = 0xFF4E342EL),            // 深棕",
        "没有新增「太深/太沉」的格子",
    ),
    (
        "账本页又把 4 个工具入口画回自己头上（8 件事又回账本页顶部）",
        SCREEN,
        "    initialTab: Int = 0,\n",
        "    onOpenReceipts: () -> Unit = {},\n    initialTab: Int = 0,\n",
        "账本页不再自己带",
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
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
