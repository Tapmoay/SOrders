"""反向验证 `_tools/qa/_check_freight_settlement_ui.py`（红线：结算页 = 抽屉选人 + 顶栏月份）。

## 为什么必须做

这条判据守的事**坏起来一条报错都不会有**：
把 `MasterRail` 那套左栏装回来、把抽屉再抄一份到结算页、把"月份"退回我们常用的那列档位清单、
换窗口时悄悄回落到第一位司机 —— 这四种改法**都能编译、都能跑、界面都"看着正常"**。
用户拿到的只有"怎么又变回去了"，而检查如果只会查"文件里有没有这个词"，它一条都抓不住。

所以逐条**注入真缺陷**，每条都必须让判据报红；跑完逐字节还原并再验一次绿。

用法：python _tools/qa/_reverse_verify_freight_settlement_ui.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_freight_settlement_ui.py"

ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
PICKER = ANDROID / "ui/common/PersonPicker.kt"
SCREEN = ANDROID / "ui/dispatcher/FreightSettlementScreen.kt"
VM = ANDROID / "ui/dispatcher/FreightSettlementViewModel.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

#: (说明, 目标文件, 替换函数) —— 每条都必须让判据报红
CASES: list[tuple[str, Path, object]] = [
    # ---- ① 选人的零件只有一份 ----
    (
        "结算页把抽屉**又抄了一份**（同一个形态两个实现，改一处漏一处）",
        SCREEN,
        lambda s: s.replace(
            "private val Accent = 0xFFFF8A65L",
            "private fun PersonDrawer(x: Int) {}\n\nprivate val Accent = 0xFFFF8A65L",
            1,
        ),
    ),
    (
        "抽屉里那个搜索框换成自己画的（不再走共用的 SearchField）",
        PICKER,
        lambda s: s.replace("SearchField(value = query, onValueChange = onQueryChange)", "BasicTextField(query)", 1),
    ),
    (
        "零件里自己写一份按人匹配（规则开始分叉）",
        PICKER,
        lambda s: s.replace(
            "        SearchField(value = query, onValueChange = onQueryChange)",
            '        val hit = query.trim().isEmpty() || options.any { it.title.contains(query) }\n'
            "        SearchField(value = query, onValueChange = onQueryChange)",
            1,
        ),
    ),
    (
        "抽屉里的名单不再能滚（人一多就选不到后面的人）",
        PICKER,
        lambda s: s.replace("LazyColumn(Modifier.weight(1f))", "Column(Modifier.weight(1f))", 1),
    ),
    # ---- ② 结算页的形状 ----
    (
        "把「商品管理那套」左栏装回来（用户点名否掉过的那一版）",
        SCREEN,
        lambda s: s.replace(
            "                when {\n                    vm.loading && groups.isEmpty() -> LoadingBox()",
            "                MasterRail(items = emptyList(), selectedKey = \"\", onSelect = {}, accent = Color(Accent))\n"
            "                when {\n                    vm.loading && groups.isEmpty() -> LoadingBox()",
            1,
        ),
    ),
    (
        "页内那行月份药丸装回来（时间挪到顶栏之后不该还有一行）",
        SCREEN,
        lambda s: s.replace(
            "                when {\n                    vm.loading && groups.isEmpty() -> LoadingBox()",
            "                MonthPills(vm)\n                when {\n                    vm.loading && groups.isEmpty() -> LoadingBox()",
            1,
        ),
    ),
    (
        "页面上的「选人」那一行被拿掉（人就没地方选了）",
        SCREEN,
        lambda s: s.replace("                PersonTriggerRow(\n", "                // PersonTriggerRow(\n", 1),
    ),
    (
        "抽屉不再挂在 ModalDrawerSheet 上（变成正文里一个方块）",
        SCREEN,
        lambda s: s.replace("            ModalDrawerSheet {\n", "", 1),
    ),
    (
        "VM 里又把「药丸换月份」那个方法加回去（下一个人就会再做一个页内时间控件）",
        VM,
        lambda s: s.replace("    fun selectDriver(key: String) {", "    fun shiftMonth(delta: Int) {}\n\n    fun selectDriver(key: String) {", 1),
    ),
    # ---- ③ 时间是顶栏药丸 → 年月网格 ----
    (
        "药丸从顶栏拿掉（时间控件不在右上角了）",
        SCREEN,
        lambda s: s.replace("DatePresetPill(label = vm.periodLabel, onClick = { showMonths = true })", 'Text("本月")', 1),
    ),
    (
        "点开的是我们平常那列**档位清单**（「按月的选择形式」当场失效）",
        SCREEN,
        lambda s: s.replace("        MonthPickerSheet(\n", "        DatePresetDialog(\n", 1),
    ),
    (
        "月份网格里不再有年份左右翻（跨年只能一个月一个月点）",
        SCREEN,
        lambda s: s.replace("{ year -= 1 }", "{ }", 1),
    ),
    (
        "换月份改成页面自己赋值（绕过 VM 那个入口）",
        SCREEN,
        lambda s: s.replace("vm.pickMonth(m)", "vm.month = m", 1),
    ),
    (
        "「自定义区间」在改版里被丢掉（2026-09-20 用户明确要过的那条路）",
        SCREEN,
        lambda s: s.replace("                showMonths = false\n                showRange = true", "                showMonths = false", 1),
    ),
    (
        "区间弹层不再挂上（那一行点了没反应）",
        SCREEN,
        lambda s: s.replace("        DateRangeDialog(\n", "        // DateRangeDialog(\n", 1),
    ),
    # ---- ④ 选中态：空串 = 全部；换窗口不悄悄换人 ----
    (
        "选中态初值不再是「全部」",
        VM,
        lambda s: s.replace('var selectedKey by mutableStateOf("")', 'var selectedKey by mutableStateOf("d|0")', 1),
    ),
    (
        "页面把空串当成「某个人」（不再是「全部（N 位司机）」）",
        SCREEN,
        lambda s: s.replace('vm.selectedKey.isBlank() -> "全部（"', 'vm.selectedKey.isBlank() -> "（"', 1),
    ),
    (
        "「他没有单」那一支被删掉（页面会空着，用户不知道是没数据还是选错了人）",
        SCREEN,
        lambda s: s.replace("vm.selectedKey.isNotBlank() && selected == null ->", "false ->", 1),
    ),
    (
        "名字不再记下来（换到他没有单的月份时，界面说不出他是谁）",
        VM,
        lambda s: s.replace('var selectedName by mutableStateOf("")', 'private val selectedNameUnused = ""', 1),
    ),
    (
        "又把「选不到就取第一个」的回落写法装回来（悄悄换人）",
        SCREEN,
        lambda s: s.replace(
            "    val selected = groups.firstOrNull { driverKey(it) == vm.selectedKey }",
            "    val selected = groups.firstOrNull { driverKey(it) == vm.selectedKey }\n"
            "        ?: visible.firstOrNull()",
            1,
        ),
    ),
    # ---- ⑤ 钱的口径 ----
    (
        "明细行取错那个钱（拿货主运费当「他该拿多少」）",
        SCREEN,
        lambda s: s.replace("formatMoney(o.payTotal)", 'formatMoney(o.freightFee ?: "0")', 1),
    ),
    (
        "抽屉里的名单不再写「¥… · N 单」（挑人时看不到谁多少钱）",
        SCREEN,
        lambda s: s.replace('"¥" + formatMoney(g.total.toString()) + " · " + g.count + " 单",', "", 1),
    ),
    # ---- ⑥ 文档 ----
    (
        "设计规范里那条落地面被删掉（文档过期比没有文档更糟）",
        DESIGN,
        # ⚠️ 不复用 `count=1`：这一节号在 §4.6 与控件表里也各被引用了一次，
        #    只换第一处的话判据照样绿 —— 那样这条注入就是空转的（第一次跑就是这么被抓出来的）。
        lambda s: s.replace("§4.15 第 8 条", "§4.15 第 X 条"),
    ),
]


def run(path: Path) -> int:
    p = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return p.returncode


def main() -> int:
    before = {str(p): p.read_text(encoding="utf-8") for _, p, _ in CASES}
    if run(CHECK) != 0:
        print("❌ 前提不成立：源码完好时这条判据就没过（先让 _check_freight_settlement_ui.py 变绿）")
        return 1
    print("✅ 前提：源码完好时判据是绿的")

    fails: list[str] = []
    for label, path, mutate in CASES:
        original_bytes = path.read_bytes()
        original = original_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code = run(CHECK)
        finally:
            path.write_bytes(original_bytes)
        if code != 0:
            print(f"✅ 注入「{label}」→ 报红")
        else:
            fails.append(f"{label}：注入之后没有报红 —— 这条判据是空转的")

    # 收尾自证：所有文件都还原了（注入式验证最容易留下的坑是"改坏了自己不知道"）
    for k, v in before.items():
        if Path(k).read_text(encoding="utf-8") != v:
            fails.append(f"收尾没还原：{k}")
    if run(CHECK) != 0:
        fails.append("还原之后判据仍然红（有文件没被改回来）")

    if fails:
        print("\n❌ 反向验证没通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ {len(CASES)}/{len(CASES)} 种破坏方式全部被抓到，且源码已还原。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
