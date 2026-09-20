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

**第四轮（2026-09-20，当前这一版）**：他看了账本页的真机，把**页内那条 4 页签导航**否掉了，
并把整页排版定下来：

> 最上面的 4 个去掉，那是**老的导航栏**，那个导航栏去掉。所以整个排版是**先是搜索**，
> 然后再是**时间**，最后在下面再就是**选择司机**；先选择司机，下面的数据才会出来，
> **不过默认是全部**。然后他会按照司机对**下面的图**进行匹配和订单匹配，
> **包括其他的货主以及批发商都是一样的**。那个结算，这个也**直接去掉**。

同轮还定了批量核销的口径：「如果是今天，那就是今天的**所有订单**……就可以**直接点这个合计
将它核销掉**，相当于一个**可控的批量处理**。但是如果是**全部**（所有人）的话，那个合计
**不能**批量核销，只能下到每个司机/货主才能批量核销」。

所以现在账本页是：**一类账一页**（档位由入口页那一格定），从上到下
**搜索 → 日期档位 → 人（默认「全部」）→ 图 → 数据**；司机结算单的入口不在这一页了
（功能还在，走工作台那一格）。

## 这条规则会被写坏成什么样（都不是假想）

| 写坏的方式 | 表现 |
|---|---|
| 工作台又长出第二张卡片 | 用户明确否掉的那一版；同一批东西分两块，来回找 |
| 6 件事又摆回工作台网格 | 工作台变成一屏 20+ 格，"账本管理"这个统一入口就白做了 |
| 入口页自己排一遍格子（不用共用版式） | 两页图标大小/圆角/行距各偏一点，一眼看出是两个时代做的 |
| 车辆管理不出现在工作台 | 用户：「车辆管理直接放在桌面上就行了」 |
| 开销管理两边都放 | 两个入口 = 用户以为丢了东西 |
| 4 类账各建一个页面 | 同一套数据四份实现，改一处漏三处 |
| **账本页里又长出一条档位导航** | 用户第四轮刚否掉的那一条（"老的导航栏"）；同一类账两个入口 |
| **排版顺序被打乱**（时间跑到搜索上面、人跑到数据下面…） | 用户口述的顺序就是他每天用的顺序；顺序一变他得重新找 |
| **选人栏没了 / 默认不是「全部」** | 「先选择司机，下面的数据才会出来，不过默认是全部」 |
| **「全部人」那一层也能批量核销** | 收款单绑的是某个客户的档案 → 收的钱会记到错的人头上 |
| **两个核销弹层各写一份收款方式** | 单张加了「挂账结清」、批量没加 → 用户只能当现金收（钱的性质变了） |
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
5. **账本页一类账一页**：没有 `LedgerTabBar`、没有能切档位的方法；档位由构造参数 `initialTab`
   定死（`private set`）；顶栏标题写这一类账的名字。
6. **排版顺序**（源码里这几处的先后）：搜索 → 日期档位 → 人 → 图；选人栏默认「全部」。
7. **司机结算**：账本页与 NavGraph 都不再有 `onOpenSettlements`，但 `Routes.FREIGHT_SETTLEMENT`
   仍然存在、仍然注册、网格里仍然有那一格（防"顺手把功能删了"）。
8. **批量核销**：只有选中某个人时才给（`personKey == null` 直接返回）；金额 = 各单欠款之和；
   一笔收款带全部 `order_ids`；弹层里逐单列出来；收款方式与客户档案警告各只有一份。
9. **日期档位与图表同源**：`DatePresets.rangeOf` 唯一实现、`Canvas(` 只许在 `Charts.kt`、
   账本页不许 `moneyToDouble(`。
10. 反空转：6 格、配色数、认出的文件数低于下限就报错，而不是安静地什么都不查。

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
PERSON_SCREEN = ANDROID / "ui/dispatcher/LedgerPersonScreen.kt"
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
    person_screen = read(PERSON_SCREEN)
    ledger_home = read(LEDGER_HOME)
    report_home = read(REPORT_HOME)
    entry_grid = read(ENTRY_GRID)
    workbench = read(WORKBENCH)
    modules = read(MODULES)
    routes = read(ROUTES)
    navgraph = read(NAVGRAPH)
    components = read(COMPONENTS)
    presets = read(PRESETS)

    # ---- ① 账本页：**一类账一页**（页内没有导航），排版 = 搜索 → 时间 → 人 → 图 → 数据 ----
    #
    # 用户 2026-09-20 第四轮（**当前这一版**）：
    #   「最上面的 4 个去掉，那是**老的导航栏**，那个导航栏去掉。所以整个排版是**先是搜索**，
    #     然后再是**时间**，最后在下面再就是**选择司机**；先选择司机，下面的数据才会出来，
    #     **不过默认是全部**。然后他会按照司机对**下面的图**进行匹配和订单匹配，
    #     **包括其他的货主以及批发商都是一样的**」。
    c.absent("页内那条 4 页签导航没了（用户：「最上面的 4 个去掉，那是老的导航栏」）", screen, r"LedgerTabBar")
    c.absent("也没有能切档位的方法（留着它，下一个人就会再给这一页做一个切档位的入口）", vm, r"fun selectTab\(")
    c.present("顶栏标题写的是**这一类账**（页内没导航了，标题是唯一说明在看哪本账的地方）",
              screen, r"Text\(vm\.kindTitle\(\)")
    c.present("档位由入口页定（构造参数 initialTab）",
              vm, r"class DispatcherLedgerViewModel\([\s\S]{0,240}?initialTab: Int = 0")
    c.present("档位进来之后不再变（private set）",
              vm, r"var tab by mutableStateOf\(initialTab\)[\s\S]{0,40}?private set")
    # 排版顺序：判据是源码里这几处的**先后**，不是"某句话在不在文件里"
    marks = [(k, screen.find(v)) for k, v in (
        ("时间", "DatePresetPill("), ("人", "PersonTriggerRow("), ("数据", "LedgerDashboardCard("))]
    c.ok(
        "排版顺序是 时间（顶栏）→ 人员那一行 → 数据（实测 " + "、".join(f"{k}@{i}" for k, i in marks) + "）",
        all(i > 0 for _, i in marks) and [i for _, i in marks] == sorted(i for _, i in marks),
        "顺序不对，或有一处根本没找到",
    )
    c.present("「全部」= 没有选中任何人", vm, r"personKey by mutableStateOf<String\?>\(null\)")
    c.present("选人只走一条路（抽屉与账户行都调 openPerson/selectPersonKey）",
              vm, r"accountRows\(\)\.firstOrNull \{ it\.key == key \}..let \{ openPerson\(it\) \}")
    c.absent("账本页不再有左栏（那一版被用户否掉了）", screen, r"MasterRail\(|LedgerRailEntries")
    for gone in ("onOpenReceipts", "onOpenExpenses", "onOpenVehicles"):
        c.absent(f"账本页不再自己带「{gone}」入口（那几件在账本管理入口页里）", screen, gone)

    # ---- ①d 第五轮：时间用**顶栏药丸**、人用**侧边抽屉**，两者不许是同一个形态 ----
    #
    # 用户原话：「那个时间也太复杂了，换一种**崭新形式**，但是**时间和选择人物不要选择一样的
    # 展现形式**；选择人物我们用那种**侧边栏抽屉**，可以在那里寻找人物，点击人物就可以了」。
    c.present("时间是顶栏一个紧凑药丸", screen, r"DatePresetPill\(")
    c.absent("账本页不再铺那一行日期胶囊（9 档横着铺 = 用户说的「太复杂」）", screen, r"DatePresetRow\(")
    # 2026-09-21 精简轮：五个页面那段「档位清单 + 自定义区间」的接线（约 130 行）收进了
    # `ui/common/Components.kt::DateFilterDialogs`。锚点跟着搬，并且**不放松**：
    # 页面必须真的调用那份共用 host，而"点开是档位清单""自定义要接着开区间弹层"这两条
    # 行为都在 host 里逐条钉住（后者原来是五份副本里最容易写错的一处）。
    c.present("药丸点开是档位清单（走共用的 DateFilterDialogs）", screen, r"DateFilterDialogs\(")
    c.present("那份 host 里确实开着档位清单（行为没搬丢）",
              components, r"fun DateFilterDialogs\([\s\S]{0,1200}?DatePresetDialog\(")
    c.present("「自定义」那一档接着开区间弹层（顺序：先关清单、再开弹层）",
              components, r"if \(label == DatePresets\.CUSTOM\) showCustom = true else onPickPreset\(label\)")
    c.present("药丸只有一份实现（ui/common/Components.kt）", components, r"fun DatePresetPill\(")
    c.present("档位清单也只有一份实现", components, r"fun DatePresetDialog\(")
    c.present("清单里画的是 DatePresets.ROW（档位表不抄第二份）",
              components, r"DatePresets\.ROW \+ DatePresets\.CUSTOM")
    c.present("人是**侧边抽屉**（Material3 的 ModalNavigationDrawer）", screen, r"ModalNavigationDrawer\(")
    # ⚠️ 两条是**反向验证逼出来的**（原来那版判据只查"文件里有没有这个词"，
    #    注入 `if (false) { PersonTriggerRow(...) }` 或"再塞一排 chip 进抽屉"都看不出来）：
    #    · 那一行必须**真的挂在这个条件上**（`vm.tab != 0` 之后紧跟就是它，中间没有别的开关）；
    #    · 选人**不许**退回"一排可横向滑的 chip"（那正是用户否掉的那一版）。
    c.present("人员那一行真的会渲染（条件就是「不是订单账」，没有别的开关）",
              screen, r"if \(vm\.tab != 0\) \{\s*PersonTriggerRow\(")
    c.absent("选人不是一排 chip（横向滑那一版被否过：人多了根本选不过来）", screen, r"LazyRow|FilterChip")
    c.present("抽屉里有自己的搜索框（人多了才找得到）",
              screen, r"fun PersonDrawer\([\s\S]{0,700}?SearchField\(")
    c.present("选中一个人就关抽屉（不留在那儿挡着账）", screen, r"scope\.launch \{ drawer\.close\(\) \}")
    c.present("抽屉里那份名单走唯一实现 UserSearch.filter", vm, r"UserSearch\.filter\(accountRows\(\), query")
    c.present("抽屉里的搜索**不改页面上的合计**（关掉抽屉后那个数必须是所有人）",
              vm, r"fun dashboard\(\)[\s\S]{0,120}?val rows = accountRows\(\)")
    c.absent("合计不再拿「搜索过滤后」的那一份算（那会让用户照着筛过的数去对账）",
             vm, r"val rows = visibleAccountRows\(\)")

    # ---- ①b 司机结算：账本页不再挂入口，但**功能不许丢** ----
    #
    # 用户 2026-09-20 第四轮：「那个结算，这个也直接去掉」。去掉的是**账本页里那个入口**，
    # 不是这个功能 —— 它仍然在（工作台那一格），这条断言就是防"顺手把功能删了"。
    c.absent("司机账里那个「司机结算单」入口没了", screen + vm, r"onOpenSettlements|司机结算单")
    c.absent("NavGraph 也不再为它接线", navgraph, r"onOpenSettlements")
    c.present("司机结算仍然进得去（工作台那一格是它唯一的入口）",
              modules, r'ModuleEntry\("司机运费结算", Routes\.FREIGHT_SETTLEMENT')
    c.present("结算页的路由还在", routes, r'const val FREIGHT_SETTLEMENT =')
    c.present("结算页在 NavGraph 里还注册着", navgraph, r"composable\(Routes\.FREIGHT_SETTLEMENT\)")

    # ---- ①c 批量核销：点合计一次收清（用户：「相当于一个可控的批量处理」）----
    c.present("点合计能批量核销（一笔收款、多张单）", vm, r"fun submitSettleAll\(")
    c.present("批量核销**必须先选中某个人**（用户：「如果是全部的话，那个合计是不能批量核销的」）",
              vm, r"if \(personKey == null \|\| tab == 1\) return")
    c.present("批量金额 = 各单欠款之和（后端算的 arrears_amount，客户端不自己减）",
              vm, r"centsToMoney\(settleAllTargets\(\)\.sumOf \{ orderArrearsCents\(it\) \}\)")
    c.present("一笔收款带上所有选中的单（`order_ids`，不是发 N 个请求）",
              vm, r"orderIds = targets\.map \{ it\.id \}")
    c.present("弹层里逐单列出来（用户说的是「可控」：得看得见收了哪几张）",
              person_screen, r"targets\.take\(LIST_MAX\)")
    c.present("「全部人」那一层不给批量核销（收款单绑的是一个客户的档案）",
              screen, r"批量核销要先选中某个人")
    c.present("收款方式只有一份（两个核销弹层共用）", person_screen, r"private fun SettleMethodChips\(")
    n_methods = len(re.findall(r"fun SettleMethodChips\(", person_screen))
    c.ok(f"收款方式定义处数正常（实测 {n_methods}）", n_methods == 1, "抄了第二份（单张加了「挂账结清」批量没加）")
    c.present("没有客户档案那条警告也只有一份（它是拦得住一次错账的那条）",
              person_screen, r"private fun NoCustomerWarning\(")
    c.present("司机那一层**没有**核销（他那笔钱是「该给他多少」，不是应收）",
              person_screen, r"所以这里没有核销")

    # ---- ② 工作台**只有一张卡片**（用户 2026-09-20 第二轮推翻了卡片版）----
    c.absent("工作台不再渲染第二张卡片", workbench, r"dispatcherLedgerEntries")
    # ---- ②b 2026-09-20 用户第三轮：**去掉卡片外壳** + 「图标可以随意拖动」----
    # 原话：「以前是**没有卡片的**，就是底部卡片是没有样式的。而且以前的图片图标啊，
    #   它是**可以随意拖动**的，就像那个桌面图标一样」。
    c.absent("工作台**没有卡片外壳**了（用户：「以前是没有卡片的」）", workbench, r"WorkbenchCard")
    c.present("图标格只有一份实现（WorkbenchTile）", workbench, r"private fun WorkbenchTile\(")
    n_tile = len(re.findall(r"WorkbenchTile\(", workbench))
    c.ok(f"图标格实现处数正常（定义 1 + 调用 1，实测 {n_tile}）", n_tile == 2, f"实际 {n_tile}（抄了第二份？）")
    c.present("网格是按 4 列切的", workbench, r"chunked\(GRID_COLUMNS\)")
    c.present("末行补空位（不补会把最后一行的图标拉宽）", workbench, r"repeat\(GRID_COLUMNS - row\.size\)")
    # 长按拖动排序：手势、坐标口径、手势的 key、落盘时机 —— 缺一条就是"拖不动 / 拖一次就断 / 顺序丢"
    c.present("长按进入拖动（与桌面图标同一个手势）", workbench, r"detectDragGesturesAfterLongPress")
    c.present(
        "拖动落点用**绝对坐标**算（用位移增量的话，换过一次位置图标就跳开手指）",
        workbench, r"translationX = dragPos\.x - b\.center\.x",
    )
    c.present("手势的 key 只有 route", workbench, r"pointerInput\(entry\.route\)")
    c.absent(
        "手势的 key 里**不许**出现 entries（换一次位置 key 就变 → 手势被取消重建 → 拖一格就断）",
        workbench, r"pointerInput\(entry\.route, entries\)",
    )
    c.present("顺序按**角色**分开存（共用一份 = 切个角色顺序全乱）", workbench, r"remember\(role\.key\)")
    c.present("顺序落盘走唯一一处 store", workbench, r"store\.save\(role\.key, savedKeys\)")
    c.present("**松手才落盘**（拖一次要经过十几格，每换一次写一次盘 = 十几次文件写）", workbench, r"onDrop = \{ store\.save")
    order_kt = read(ANDROID / "core/WorkbenchOrder.kt")
    c.present("顺序算法只有一处（纯逻辑，有单测）", order_kt, r"object WorkbenchOrder")
    c.present(
        "越界拖动原样返回（手指划出网格是常事，不许崩也不许自己落位）",
        order_kt, r"if \(from !in items\.indices \|\| to !in items\.indices\) return items",
    )
    c.present("升级后新加的入口排在最后（而不是凭空消失）", order_kt, r"val rest = entries\.filter \{ key\(it\) !in seen \}")
    c.absent(
        "顺序状态**不是**第二份真相（两处各更新一次 = 升级后少一格而谁都不报错）",
        workbench, r"var ordered by remember",
    )

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
    # ⚠️ 账本页**不用**那一行胶囊了（第五轮换成了顶栏药丸）：它仍然只有一份实现，
    #    但账本页走的是 `DatePresetPill` + `DatePresetDialog`（见 ①d）。这里只钉"区间算法同源"。
    c.present("账本 VM 的档位也调 DatePresets.rangeOf", vm, r"DatePresets\.rangeOf\(")
    for old in ("chartAnchor", "chartMode", r"fun applyMode\(", r"fun setAnchor\(", "ReportTimeNav"):
        c.absent(f"老时间导航「{old}」不许留在账本页/VM", screen + vm, old)

    # ---- ④b 默认档位要落到"有单的那一天"（用户 2026-09-20 第五轮末）----
    #
    # 原话：「这些时间默认是**今天**的，如果今天**没有任何订单**的话，然后再是**昨天**，
    # 以此类推」。所以：初值=今天，打开后异步退档（今天→昨天→前天→近 7 天→全部）。
    c.present("默认档位 = 今天", vm, r"var preset by mutableStateOf\(DatePresets\.TODAY\)")
    # 阶梯**只有一份**（`DatePresets.AUTO_LADDER`）：四档齐全、顺序固定，账本页读它而不是抄一份
    # （抄一份的后果是"账本退到前天、开销退到昨天"这种没人说得清的不一致）
    c.present(
        "退档阶梯四档齐全且顺序固定（今天 → 昨天 → 前天 → 近 7 天）",
        presets,
        r"val AUTO_LADDER = listOf\(TODAY, YESTERDAY, BEFORE_YESTERDAY, LAST_7\)",
    )
    c.present("账本页读的是那一份共享阶梯（不是本地抄的）", vm, r"for \(label in DatePresets\.AUTO_LADDER\)")
    c.absent("账本页不许自己再抄一份阶梯", vm, r"val AUTO_LADDER = listOf\(")
    # ⚠️ 2026-09-21 这两条**按用户报的 bug 重写了**（原来是钉"先按今天拉一次再异步退档"）：
    #    用户原话：「我点击我的账本的时候，它会**闪两下**再跳到「前天」……我在点击账本之前，
    #    它就已经提前盘点好了……其他**派单员那些账本界面**基本上也是这个逻辑，
    #    **闪两下已经不行了**，不美观，且占用性能。」
    #    所以现在的形状是 **先盘点（每档 limit=1 探测）、定下来之后只取一次数**：
    #    `init` 里那句 `switchPreset(DatePresets.TODAY)` 是**被禁掉的**写法 —— 它必然先画一版
    #    今天的空态。两条一起钉：① 不许再出现"先按今天拉一次"；② 必须是 pickWindow 那一条路。
    c.absent(
        "打开时不许先按今天拉一次（那一下就是用户说的「闪两下」）",
        vm,
        r"switchPreset\(DatePresets\.TODAY\)[\s\S]{0,120}?launch \{ pickDefaultPreset\(\) \}",
    )
    c.present(
        "先盘点、再取数（探测完只取一次数）",
        vm,
        r"switchPreset\(DatePresets\.pickWindow\(DatePresets\.AUTO_LADDER\)",
    )
    c.present("盘点期间页面挡住不画（windowSettled 门）",
              screen, r"!vm\.windowSettled -> LoadingBox\(\)")
    c.present("共享的挑窗口函数只有一份实现", presets, r"suspend fun pickWindow\(")
    c.present(
        "退档前先看这一段有没有账（判据与页面取数同源）",
        vm, r"private suspend fun periodHasData\(label: String\)[\s\S]{0,900}?ledgerEntries\(from = f, to = t\)",
    )
    c.present("都没数就退到「全部」（总得给一个看得到全貌的窗口）",
              presets, r"return ALL")
    c.present("**用户自己挑过档位之后永不再自动改**（不许抢方向盘）",
              vm, r"if \(!userPickedPreset\) \{\s*switchPreset\(DatePresets\.pickWindow")
    c.present("手动换档走同一个入口（一份实现）", vm, r"fun applyPreset\(label: String\) \{\s*userPickedPreset = true")
    c.present("点开某个人、他这一段没单时也退档（否则点谁都是空屏）",
              vm, r"if \(personOrders\.isEmpty\(\)\) fallbackForPerson\(key\)")
    c.present("那个人退档与页面退档共用同一个开关（用户表态过就不动）",
              vm, r"private suspend fun fallbackForPerson\(key: String\) \{\s*if \(userPickedPreset\) return")

    # ---- ⑤ 账本页**一张图都不画**（第五轮：图归报表中心）----
    #
    # 用户原话：「那个折线图条形图还有扇形图，我们**直接去掉**就行了啊，其他的都也去掉，
    # 其他的像什么批发商账、货主账，全都去掉这些图，**到时候在报表中心看就可以了**」。
    c.absent("账本页不画折线", screen, r"LineChart\(")
    c.absent("账本页不画条形", screen, r"BarChart\(")
    c.absent("账本页不画扇形", screen, r"PieChart\(")
    c.absent("账本页的图表卡与切换条都删了",
             screen, r"LedgerChartCard\(|LedgerChartSwitch\(|SegmentedStatusTabs\(")
    c.ok("图表取数那一份纯函数文件已删（留着＝没人调的图在库里躺着）",
         not (ANDROID / "ui/dispatcher/LedgerCharts.kt").exists(), "LedgerCharts.kt 还在")
    c.ok("它的单测一起删了",
         not (ANDROID / "src/test/java/com/tapmoay/sorders/ui/dispatcher/LedgerChartsTest.kt").exists())
    c.ok("扇形图与它的配色表也删了（全项目没有第二个调用点）",
         not (ANDROID / "src/test/java/com/tapmoay/sorders/ui/common/PieChartMathTest.kt").exists()
         and "ChartPalette" not in read(COLOR))
    # 图库本身**留着**（报表中心/货主账本/司机端在用）—— 别把这一轮读成"把图删了"
    c.present("共用的折线还留着（报表中心在用）", read(CHARTS), r"fun LineChart\(")
    c.present("共用的条形还留着", read(CHARTS), r"fun BarChart\(")
    c.present("报表中心确实在用它们", read(ANDROID / "ui/dispatcher/ReportCenter.kt"), r"LineChart\(|BarChart\(")
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

    # ---- ⑥ 数与合计同源（图没了，这条只钉"页面不许自己算钱"）----
    c.absent("账本页自己不再求和（页面里出现 moneyToDouble 就是第二份口径）", screen, r"moneyToDouble\(")
    c.present("KPI 那个数取 VM 的 dashboard()", screen, r"val d = vm\.dashboard\(\)")
    c.present("商品统计那一份纯函数还在（第二层的「哪些货欠多少」靠它）",
              read(ANDROID / "ui/dispatcher/LedgerPersonStats.kt"), r"fun productStats\(")

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
