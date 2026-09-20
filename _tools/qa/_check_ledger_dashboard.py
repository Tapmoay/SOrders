"""红线：账本那套「工作台一张卡片 + 账本页看账」的版式与同源规则（2026-09-20 用户点名）。

## 由来（用户原话，两轮）

第一轮要做成两栏：

> 我们对派单员的账本管理做一个大改改成这样子，就是类似于商品管理的那样，左边我们有个条行囊…

做完他看了真机，**推翻了**，改成现在这样：

> 算了，这样子不行，干脆就在工作台里做 2 个卡片…卡片中间有一个提示词…就叫账本管理，
> 然后将账本管理的所有的 8 个模块全部拆成类似于工作台现在的一个图标的形式，放在一个卡片。

于是定下来：
· **工作台第二张卡片**「账本管理」＝那 8 件事（4 类账 + 4 个工具），一格一个图标；
· **账本页只管看账**：4 类账页签 → 日期档位 → 三种图（折线/条形/扇形）→ 明细。

## 这条规则会被写坏成什么样（都不是假想）

| 写坏的方式 | 表现 |
|---|---|
| 8 件事又回账本页顶部（页签 + 工具按钮） | 用户明确否掉的那一版；而且"账本管理"那一格点进去只是默认档位 |
| 8 件事在两个地方各写一份 | 加了第 9 件只改一处 → 两个入口不一致（用户以为丢了） |
| 4 类账各建一个页面 | 同一套数据四份实现，改一处漏三处 |
| 日期档位各页各写一份 | 账本页的"本月"与筛选条的"本月"差几天，两边都看着对 |
| 图表自己再聚合一遍 | 图上一个数、合计另一个数，同一屏两个数、谁都不报错 |
| 账户类硬凑一条按天折线 | 明细被截断时曲线比合计小 |
| 图例配色太近 | 两块分不开，图只能靠图例反查 —— 图等于白画 |
| 两张卡片的图标撞色 | 同一个屏幕上两块一样的方块，用户以为复制错了 |

## 判据（清单**全部从源码算**，不手写要检查的文件名）

1. **账本页只管看账**：有 4 类账页签（`LedgerTabBar`）；**没有**左栏、**没有**那 4 个工具入口。
2. **工作台第二张卡片**：`WorkbenchScreen` 里渲染 `Modules.dispatcherLedgerEntries`，
   标题是「账本管理」，图标格只有一份实现（`WorkbenchTile`）。
3. **8 格清单只有一份**（`Modules.dispatcherLedgerEntries`）：正好 8 条、4 类账走
   `Routes.dispatcherLedger(tab)`（**一条带参数的路由**，不是四个页面）、4 个工具各自有页面；
   `dispatcherEntries`（上面那张卡片）里**不许**再有「账本管理」那一格。
4. **日期档位只有一处实现**（`ui/common/DatePresets.kt` + `DatePresetRow`），账本页与筛选条都调它。
5. **三种图都用共享组件**（`LineChart` / `BarChart` / `PieChart` / `SegmentedStatusTabs`）；
   `Canvas(` 只允许出现在 `ui/common/Charts.kt`（例外写在 `CANVAS_ALLOW`，每条带理由）。
6. **图与合计同源**：账本页不许出现 `moneyToDouble(`（页面自己求和＝第二份口径）；
   取数只许来自 `LedgerCharts.kt` 的纯函数。
7. **扇形环心 = 切片之和**。
8. 反空转：8 格、配色数、认出的文件数低于下限就报错，而不是安静地什么都不查。

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
WORKBENCH = ANDROID / "ui/home/WorkbenchScreen.kt"
MODULES = ANDROID / "ui/nav/Modules.kt"
ROUTES = ANDROID / "ui/nav/Routes.kt"
CHARTS = ANDROID / "ui/common/Charts.kt"
COMPONENTS = ANDROID / "ui/common/Components.kt"
PRESETS = ANDROID / "ui/common/DatePresets.kt"
COLOR = ANDROID / "ui/theme/Color.kt"

#: 允许直接用 `Canvas(` 的地方 → 理由（键必须命中一个**真文件**，防化石）。
CANVAS_ALLOW = {
    "ui/common/Charts.kt": "图表唯一的实现处（折线/条形/扇形都在这里）",
    "util/Watermark.kt": "导出图片上的水印，不是图表",
}

#: 工作台那张卡片里的 8 格（顺序即显示顺序）
LEDGER_TILES = ["订单账", "司机账", "货主账", "批发商账", "客户收款", "司机结算", "开销管理", "车辆台账"]


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
    workbench = read(WORKBENCH)
    modules = read(MODULES)
    routes = read(ROUTES)
    components = read(COMPONENTS)
    presets = read(PRESETS)

    # ---- ① 账本页只管看账 ----
    c.present("账本页有 4 类账页签", screen, r"LedgerTabBar\(")
    c.present("4 类账页签列出了订单/司机/货主/批发商", screen, r'"订单账"[\s\S]*?"批发商账"')
    c.absent("账本页不再有左栏（那一版被用户否掉了）", screen, r"MasterRail\(|LedgerRailEntries")
    for gone in ("onOpenReceipts", "onOpenSettlements", "onOpenExpenses", "onOpenVehicles"):
        c.absent(f"账本页不再自己带「{gone}」入口（那 4 件已经搬到工作台卡片）", screen, gone)

    # ---- ② 工作台第二张卡片 ----
    c.present("工作台渲染第二张卡片（账本那 8 格）", workbench, r"Modules\.dispatcherLedgerEntries")
    c.present("卡片标题就是「账本管理」", workbench, r'"账本管理"')
    c.present("图标格只有一份实现（WorkbenchTile）", workbench, r"private fun WorkbenchTile\(")
    n_tile = len(re.findall(r"WorkbenchTile\(", workbench))
    c.ok(f"图标格实现处数正常（定义 1 + 调用 1，实测 {n_tile}）", n_tile == 2, f"实际 {n_tile}（抄了第二份？）")
    c.present("卡片是按 4 列切的（与工作台同一列数）", workbench, r"chunked\(GRID_COLUMNS\)")
    c.present("末行补空位（不补会把最后一行的图标拉宽）", workbench, r"repeat\(GRID_COLUMNS - row\.size\)")

    # ---- ③ 8 格清单只有一份 ----
    block = re.search(r"val dispatcherLedgerEntries[\s\S]*?\n    \)\n", modules)
    c.ok("取到 8 格清单（取不到这条检查就是空转）", block is not None and len(block.group(0)) > 200)
    if block:
        body = block.group(0)
        labels = re.findall(r'ModuleEntry\("([^"]+)"', body)
        c.ok(f"正好 8 格（实测 {len(labels)}）", labels == LEDGER_TILES, f"实际 {labels}")
        c.ok(
            "4 类账走**同一条带参数的路由**（不是四个页面）",
            len(re.findall(r"Routes\.dispatcherLedger\(", body)) == 4,
            "少于 4 条",
        )
        for r in ("Routes.DISPATCH_RECEIPTS", "Routes.DISPATCH_SETTLEMENTS", "Routes.DISPATCH_EXPENSES", "Routes.DISPATCH_VEHICLES"):
            c.present(f"4 个工具之一走 {r}", body, re.escape(r))
        icons = re.findall(r"Icons\.Default\.(\w+)", body)
        c.ok(f"8 个图标互不相同（实测 {len(set(icons))} 种）", len(set(icons)) == len(icons) == 8, f"{icons}")
    c.present("路由函数 dispatcherLedger(tab) 存在", routes, r"fun dispatcherLedger\(tab: Int\)")
    c.present("账本页按 ?tab= 直达某一类账", read(ANDROID / "ui/nav/NavGraph.kt"), r"DISPATCH_LEDGER \+ \"\?tab=\{tab\}\"")
    # 上面那张卡片里不许再有「账本管理」那一格（两个入口 = 用户以为丢了东西）
    grid = re.search(r"val dispatcherEntries[\s\S]*?\n    \)\n", modules)
    c.ok("取到主网格清单", grid is not None)
    if grid:
        c.absent("主网格里不再有「账本管理」那一格", grid.group(0), r'"账本管理"')

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
    print(f"✅ 全部 {c.passes} 项通过：工作台第二张卡片装那 8 件事，账本页只管看账，且数与图同源。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
