"""红线：账本那套「工作台一格 → 账本管理入口页 → 账本页看账」的版式与同源规则。

## 由来（用户原话，**三轮**，最后一轮推翻了中间那轮）

第一轮要做成两栏：

> 我们对派单员的账本管理做一个大改改成这样子，就是类似于商品管理的那样，左边我们有个条行囊…

他看了真机，**推翻**，改成"工作台两张卡片、第二张装 8 件事"：

> 算了，这样子不行，干脆就在工作台里做 2 个卡片…就叫账本管理，然后将账本管理的所有的
> 8 个模块全部拆成类似于工作台现在的一个图标的形式，放在一个卡片。

**当天他又推翻了那一版**（2026-09-20 第三轮，就是现在这条）：

> 派单员的那个工作台全部改一下，**改回原来的样式**……首先，我们将**司机的账和司机结算**
> 这 2 个东西**合并成一个**；然后订单账本，再加上货主账本以及批发商账，还有客户收款以及
> 开销管理，**合并成一个形式，就叫做账本管理**，这个账本管理**类似于报表中心的形式**；
> 然后车辆台账属于车辆管理，车辆管理直接放在桌面上就行了。

于是定稿：
· **工作台回到单网格**（只有一张卡片）；
· 网格上有「账本管理」一格 → **入口页**（报表中心那种形式）→ 6 件事，其中
  **司机账并入司机结算**、**开销管理并进来**；
· **车辆管理**（= 车辆台账）单独一格放桌面上。

## 这条规则会被写坏成什么样（都不是假想）

| 写坏的方式 | 表现 |
|---|---|
| 工作台又长出第二张卡片 | 用户明确否掉的那一版；同一批东西分两块，来回找 |
| 6 件事又摆回工作台网格 | 工作台变成一屏 20+ 格，"账本管理"这个统一入口就白做了 |
| 入口页自己排一遍格子（不用共用版式） | 两页图标大小/圆角/行距各偏一点，一眼看出是两个时代做的 |
| 司机结算又单独占一格 | 用户点名要"合并成一个" |
| 车辆管理不出现在工作台 | 用户：「车辆管理直接放在桌面上就行了」 |
| 开销管理两边都放 | 两个入口 = 用户以为丢了东西 |
| 4 类账各建一个页面 | 同一套数据四份实现，改一处漏三处 |
| 日期档位 / 图表各页各写一份 | 账本页的"本月"与筛选条的"本月"差几天，两边都看着对 |
| 工作台格子用"深色/灰白" | 用户明确否过（深蓝太跳、兑白太灰）——色只差色相，亮度要跟邻居一样 |
| 入口页硬凑一条按天折线 | 明细被截断时曲线比合计小 |

## 判据（清单**全部从源码算**，不手写要检查的文件名）

1. **工作台只有一张卡片**：不再引用 `dispatcherLedgerEntries`、只调一次 `WorkbenchCard`。
2. **网格两格到位**：「账本管理」→ `Routes.LEDGER_HOME`、「车辆管理」→ `Routes.DISPATCH_VEHICLES`；
   网格里**不许**再出现 开销管理/司机结算/车辆台账/4 类账 这些（它们都在入口页里）；
   网格里写死的色都要在亮度家族带（B 66-100）内。
3. **入口页是报表中心那一套**：两页都调 `EntryCardGrid`，而它**全项目只有一处定义**，
   两个入口页自己都不出现 `LazyVerticalGrid(`。
4. **入口页正好 6 格**（`Modules.ledgerHomeEntries`）：4 类账走同一条带参数路由 + 客户收款 + 开销管理；
   两两配色距离 ≥60。
5. **司机结算只在司机账里**：账本页 `vm.tab == 1` 时有一个「司机结算单」入口，通向结算页；
   入口页 6 格里没有它。
6. **账本页只管看账**：4 页签 + 日期档位 + 三种图；没有左栏、没有那几件工具的入口。
7. **日期档位与图表同源**：`DatePresets.rangeOf` 唯一实现、`Canvas(` 只许在 `Charts.kt`、
   账本页不许 `moneyToDouble(`。
8. 反空转：6 格、配色数、认出的文件数低于下限就报错，而不是安静地什么都不查。

⚠️ 注入式反向验证（改坏 → 本脚本必须红）：`_tools/qa/_reverse_verify_ledger_dashboard.py`。

用法：python _tools/qa/_check_ledger_dashboard.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用兄弟红线里剥 Kotlin 注释的实现，不抄第二份。
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

SCREEN = ANDROID / "ui/dispatcher/DispatcherLedgerScreen.kt"
VM = ANDROID / "ui/dispatcher/DispatcherLedgerViewModel.kt"
CHARTS_DATA = ANDROID / "ui/dispatcher/LedgerCharts.kt"
LEDGER_HOME = ANDROID / "ui/dispatcher/LedgerHomeScreen.kt"
REPORT_HOME = ANDROID / "ui/dispatcher/ReportHome.kt"
ENTRY_GRID = ANDROID / "ui/common/EntryGrid.kt"
WORKBENCH = ANDROID / "ui/home/WorkbenchScreen.kt"
MODULES = ANDROID / "ui/nav/Modules.kt"
ROUTES = ANDROID / "ui/nav/Routes.kt"
NAVGRAPH = ANDROID / "ui/nav/NavGraph.kt"
CHARTS = ANDROID / "ui/common/Charts.kt"
COMPONENTS = ANDROID / "ui/common/Components.kt"
PRESETS = ANDROID / "ui/common/DatePresets.kt"
COLOR = ANDROID / "ui/theme/Color.kt"

#: 允许直接用 `Canvas(` 的地方 → 理由（键必须命中一个**真文件**，防化石）。
CANVAS_ALLOW = {
    "ui/common/Charts.kt": "图表唯一的实现处（折线/条形/扇形都在这里）",
    "util/Watermark.kt": "导出图片上的水印，不是图表",
}

#: 「账本管理」入口页里的 6 格（顺序即显示顺序）。用户 2026-09-20 第二轮定稿：
#: 司机账**并入司机结算**、开销管理**并进来**、车辆台账**搬去工作台**。
LEDGER_TILES = ["订单账", "司机账", "货主账", "批发商账", "客户收款", "开销管理"]

#: 亮度家族带（B 66-100）之外的**既有**格子 → 理由。只用来拦新增的，不回溯判老的。
BAND_EXEMPT = {
    "#8D6E63": "「账户管理」的棕，从第一版就是这样；用户点名的四格是商品/报表/挂账/消息",
}


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return strip_comments(p.read_text(encoding="utf-8"))


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)[:60]!r}" if m else "")


def main() -> int:
    c = Checker()
    screen = read(SCREEN)
    vm = read(VM)
    data = read(CHARTS_DATA)
    ledger_home = read(LEDGER_HOME)
    report_home = read(REPORT_HOME)
    entry_grid = read(ENTRY_GRID)
    workbench = read(WORKBENCH)
    modules = read(MODULES)
    routes = read(ROUTES)
    navgraph = read(NAVGRAPH)
    components = read(COMPONENTS)
    presets = read(PRESETS)

    # ---- ① 账本页只管看账 ----
    c.present("账本页有 4 类账页签", screen, r"LedgerTabBar\(")
    c.present("4 类账页签列出了订单/司机/货主/批发商", screen, r'"订单账"[\s\S]*?"批发商账"')
    c.absent("账本页不再有左栏（那一版被用户否掉了）", screen, r"MasterRail\(|LedgerRailEntries")
    for gone in ("onOpenReceipts", "onOpenExpenses", "onOpenVehicles"):
        c.absent(f"账本页不再自己带「{gone}」入口（那几件在账本管理入口页里）", screen, gone)
    # ⚠️ **司机结算是个例外**：用户 2026-09-20 明说「将司机的账和司机结算这 2 个东西合并成一个」，
    #    合并的落点就是**司机账那一档里的一个入口**（不是网格上第二个图标）。
    c.present("司机账档位里有「司机结算单」入口（两个合并成一个的落点）", screen,
              r'vm\.tab == 1[\s\S]{0,600}?onOpenSettlements')
    c.present("那个入口只在司机账档位出现（不是常驻按钮）", screen, r'if \(vm\.tab == 1\) \{')
    c.present("入口文案写的是「司机结算单」", screen, r'"司机结算单"')
    c.present("点了真的会去结算页（NavGraph 接线）", navgraph, r"onOpenSettlements = \{ navController\.navigate\(Routes\.DISPATCH_SETTLEMENTS\)")

    # ---- ② 工作台**只有一张卡片**（用户 2026-09-20 第二轮推翻了卡片版）----
    c.absent("工作台不再渲染第二张卡片", workbench, r"dispatcherLedgerEntries")
    # `WorkbenchCard(` 会同时命中**定义那一行**，所以正常值是 2（定义 1 + 调用 1）。
    n_cards = len(re.findall(r"WorkbenchCard\(", workbench))
    c.ok(f"工作台只有一处卡片调用（实测 {n_cards} = 定义 1 + 调用 1）", n_cards == 2, f"实际 {n_cards} 处")
    c.present("那一张卡片就是主网格那 16+ 格", workbench, r"WorkbenchCard\(title = null, entries = entries")
    c.present("图标格只有一份实现（WorkbenchTile）", workbench, r"private fun WorkbenchTile\(")
    n_tile = len(re.findall(r"WorkbenchTile\(", workbench))
    c.ok(f"图标格实现处数正常（定义 1 + 调用 1，实测 {n_tile}）", n_tile == 2, f"实际 {n_tile}（抄了第二份？）")
    c.present("卡片是按 4 列切的", workbench, r"chunked\(GRID_COLUMNS\)")
    c.present("末行补空位（不补会把最后一行的图标拉宽）", workbench, r"repeat\(GRID_COLUMNS - row\.size\)")

    # ---- ③ 工作台网格：账本管理一格 + 车辆管理一格 ----
    grid = re.search(r"val dispatcherEntries[\s\S]*?\n    \)\n", modules)
    c.ok("取到主网格清单", grid is not None)
    if grid:
        g = grid.group(0)
        labels = re.findall(r'ModuleEntry\("([^"]+)"', g)
        c.present("「账本管理」回到网格里（指向入口页）", g, r'ModuleEntry\("账本管理", Routes\.LEDGER_HOME')
        c.present("「车辆管理」在网格里（用户：「直接放在桌面上」）", g,
                  r'ModuleEntry\("车辆管理", Routes\.DISPATCH_VEHICLES')
        c.absent("网格里没有「开销管理」（它并进账本管理了）", g, r'"开销管理"')
        c.absent("网格里没有「车辆台账」这个旧名（就是车辆管理）", g, r'"车辆台账"')
        c.absent("网格里没有「司机结算」那一格（并进司机账了）", g, r'"司机结算"')
        for banned in ("订单账", "货主账", "批发商账", "客户收款"):
            c.absent(f"网格里没有「{banned}」（它在账本管理入口页里）", g, rf'"{banned}"')
        # 工作台那一规：**跟邻居一样亮、一样鲜艳，只差色相**（用户 2026-09-20 定的）。
        # ⚠️ 只用来拦**新增**的格子：既有那一个棕（账户管理 #8D6E63，亮度 55%）一直如此，
        #    用户从没点名过它 —— 拿新尺子回溯判既有配色只会让这条检查变成"永远红"。
        bad_band = []
        for hexs in re.findall(r"color = 0xFF([0-9A-Fa-f]{6})L", g):
            r_, g_, b_ = int(hexs[0:2], 16), int(hexs[2:4], 16), int(hexs[4:6], 16)
            v = max(r_, g_, b_) / 255 * 100
            if not (66 <= v <= 100):
                bad_band.append("#" + hexs)
        stray_band = sorted(set(bad_band) - set(BAND_EXEMPT))
        c.ok(f"没有新增「太深/太沉」的格子（既有例外 {len(BAND_EXEMPT)} 个，新增越界 {len(stray_band)} 个）",
             not stray_band, "用户否过这类色：" + "、".join(stray_band))
        c.ok(f"网格里数得出入口（实测 {len(labels)} 格）", len(labels) >= 16, f"实际 {labels}")

    # ---- ④ 账本管理入口页：报表中心那种形式，6 格，且**版式只有一份** ----
    c.present("有「账本管理」入口页", ledger_home, r"fun LedgerHomeScreen\(")
    c.present("入口页用的是**共用**的入口卡版式（不是自己又画一遍）", ledger_home, r"EntryCardGrid\(")
    c.present("标题是「账本管理」", ledger_home, r'AppTopBar\(title = "账本管理"')
    c.present("报表中心也调同一个版式（两页一份实现）", report_home, r"EntryCardGrid\(")
    c.present("入口卡版式只有一处定义", entry_grid, r"fun EntryCardGrid\(")
    n_grid_def = sum(len(re.findall(r"fun EntryCardGrid\(", read(p))) for p in
                     ANDROID.rglob("*.kt"))
    c.ok(f"全项目只有一份入口卡版式（实测 {n_grid_def}）", n_grid_def == 1, "抄了第二份版式")
    n_lazy = len(re.findall(r"LazyVerticalGrid\(", ledger_home + report_home))
    c.ok(f"两个入口页都不自己排格子（实测 {n_lazy} 处 LazyVerticalGrid）", n_lazy == 0,
         "自己排格子 = 第二份版式")
    block = re.search(r"val ledgerHomeEntries[\s\S]*?\n    \)\n", modules)
    c.ok("取到 6 格清单（取不到这条检查就是空转）", block is not None and len(block.group(0)) > 200)
    if block:
        body = block.group(0)
        labels = re.findall(r'ModuleEntry\("([^"]+)"', body)
        c.ok(f"正好 6 格（实测 {len(labels)}）", labels == LEDGER_TILES, f"实际 {labels}")
        c.ok(
            "4 类账走**同一条带参数的路由**（不是四个页面）",
            len(re.findall(r"Routes\.dispatcherLedger\(", body)) == 4,
            "少于 4 条",
        )
        for r in ("Routes.DISPATCH_RECEIPTS", "Routes.DISPATCH_EXPENSES"):
            c.present(f"两个工具之一走 {r}", body, re.escape(r))
        c.absent("6 格里没有「司机结算」（并进司机账了）", body, r'"司机结算"')
        c.absent("6 格里没有「车辆台账」（它去工作台了）", body, r'"车辆台账"')
        icons = re.findall(r"Icons\.Default\.(\w+)", body)
        c.ok(f"6 个图标互不相同（实测 {len(set(icons))} 种）", len(set(icons)) == len(icons) == 6, f"{icons}")
        # 同屏不许撞色：6 格两两 RGB 欧氏距离 ≥60
        cols = [(m[0], m[1]) for m in re.findall(r'ModuleEntry\("([^"]+)"[\s\S]{0,200}?color = (MoneyOrange|0xFF[0-9A-Fa-f]{6}L)', body)]
        hexes = []
        for name, tok in cols:
            h = "FF9500" if tok == "MoneyOrange" else tok[4:10]
            hexes.append((name, h))
        bad_pairs = []
        for i in range(len(hexes)):
            for j in range(i + 1, len(hexes)):
                a, b = hexes[i][1], hexes[j][1]
                d = sum((int(a[k:k + 2], 16) - int(b[k:k + 2], 16)) ** 2 for k in (0, 2, 4)) ** 0.5
                if d < 60:
                    bad_pairs.append(f"{hexes[i][0]}×{hexes[j][0]}={d:.0f}")
        c.ok(f"6 格配色两两距离 ≥60（不合 {len(bad_pairs)} 对）", not bad_pairs, "、".join(bad_pairs))
    c.present("路由函数 dispatcherLedger(tab) 存在", routes, r"fun dispatcherLedger\(tab: Int\)")
    c.present("入口页路由 LEDGER_HOME 存在", routes, r'const val LEDGER_HOME = "dispatcher/ledger/home"')
    c.present("入口页在 NavGraph 注册了", navgraph, r"composable\(Routes\.LEDGER_HOME\)")
    c.present("账本页按 ?tab= 直达某一类账", navgraph, r"DISPATCH_LEDGER \+ \"\?tab=\{tab\}\"")

    # ---- ④ 日期档位：区间算法只有一处，而且真的被调用 ----
    c.present("档位与区间在 DatePresets（唯一实现）", presets, r"fun rangeOf\(")
    c.present("档位表自己算（ROW）", presets, r"val ROW = listOf\(")
    for name in ("ALL", "TODAY", "YESTERDAY", "BEFORE_YESTERDAY", "LAST_7", "LAST_WEEK", "THIS_MONTH", "LAST_MONTH"):
        c.present(f"档位常量 [{name}] 在 DatePresets 里", presets, rf"const val {name} =")
    c.present("筛选条调 DatePresets.rangeOf（不是自己 when 一遍）", components, r"DatePresets\.rangeOf\(")
    c.present("筛选条的胶囊走共用的 DatePresetRow", components, r"DatePresetRow\(")
    c.present("账本页的日期行走同一个 DatePresetRow", screen, r"DatePresetRow\(")
    c.present("账本 VM 的档位也调 DatePresets.rangeOf", vm, r"DatePresets\.rangeOf\(")
    for old in ("chartAnchor", "chartMode", r"fun applyMode\(", r"fun setAnchor\(", "ReportTimeNav"):
        c.absent(f"老时间导航「{old}」不许留在账本页/VM", screen + vm, old)

    # ---- ⑤ 三种图都在、都用共享组件 ----
    c.present("折线图用共享 LineChart", screen, r"LineChart\(")
    c.present("条形图用共享 BarChart", screen, r"BarChart\(")
    c.present("扇形图用共享 PieChart", screen, r"PieChart\(")
    c.present("图的切换条走共用的 SegmentedStatusTabs", screen, r"SegmentedStatusTabs\(")
    canvas_files = [
        str(p.relative_to(ANDROID)).replace("\\", "/")
        for p in ANDROID.rglob("*.kt")
        if re.search(r"(?<![\w.])Canvas\(", strip_comments(p.read_text(encoding="utf-8")))
    ]
    stray = [f for f in canvas_files if f not in CANVAS_ALLOW]
    c.ok(
        f"自己画的图只许在 Charts.kt（实测 {canvas_files}）",
        not stray,
        "这些文件自己画了 Canvas：" + "、".join(stray),
    )
    for f in CANVAS_ALLOW:
        c.ok(f"白名单里的 [{f}] 还存在（防化石）", (ANDROID / f).exists(), "文件没了，请删掉白名单那一行")
    pal = re.search(r"val ChartPalette = listOf\(([\s\S]*?)\n\)", read(COLOR))
    c.ok("扇形配色表存在", pal is not None)
    if pal:
        n = len(re.findall(r"0x[0-9A-Fa-f]{8}L|\b[A-Z]\w+,", pal.group(1)))
        c.ok(f"配色至少 6 色（实测 {n}）", n >= 6, f"实际 {n}")

    # ---- ⑥ 图与合计同源 ----
    for fn in ("fun dailySeries(", "fun topSlices(", "fun orderDailySeries(", "fun orderSourceTotals(",
               "fun driverDailySeries(", "fun driverTotals(", "fun accountTotals(", "fun chartTypesFor("):
        c.present(f"取数纯函数 [{fn}] 在 LedgerCharts.kt", data, re.escape(fn))
    for accessor in ("seriesForChart()", "barsForChart()", "slicesForChart()"):
        c.present(f"账本页的图走 VM 的 {accessor}", screen, re.escape(accessor))
    c.absent("账本页自己不再求和（页面里出现 moneyToDouble 就是第二份口径）", screen, r"moneyToDouble\(")
    c.present("账户类不给折线（数据不支持）", data, r"tab == 0 \|\| tab == 1")

    # ---- ⑦ 扇形环心的数 = 切片之和 ----
    c.present(
        "环心那个数由切片求和得出（不是从别处塞一个合计进来）",
        screen,
        r"centerValue = [\s\S]{0,80}?sumOf",
    )

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：工作台一格 → 账本管理入口页（报表中心形式，6 件事）→ 账本页只管看账，且数与图同源。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
