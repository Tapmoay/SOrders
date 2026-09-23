"""红线：订单列表（派单员「订单管理」/ 货主「我的订单」）的**档位与卡片布局**不许走样。

## 由来（用户 2026-09-22 口述，逐条对应下面每一节）
> 「尤其是派单员，他上面写的…**近 30 条**这个提示删掉啊，他**占位置**了」；
> 「他如果点**已送达**的话，他会有一个…那个**时间**，我们就**复用我们那些代码和形式**在**右上角**，
>   那个有**预选也可以自定义时间**」；
> 「如果是进来的话，**默认是不会进入「全部」**的，默认是进入**「派单中」**；货主就是**已接单**的，
>   货主他是**默认已接单**的，并且将那个**已接单往前一格排第 2 位置**」；
> 「**货主的那个时间也移到那上面去**」；
> 「新建订单就先**放在下面**吧，放在**底下**」；
> 「**编辑**一定是在**右边**的…**他要一个图标**，**稍微圈一下**；**异常**的话，就放置在**左边**
>   而且**是最左边**…**编辑一定在右边**（惯用手是右手），**相反的操作，就在左边**」；
> 「那个**订单号**啊出现了**错位**…**不要缩小**一点，这样子就好看一点；同时**长按订单号是可以复制**」。

## 这一页在防什么（每一条都对应一种"静默失效"）
1. **时间窗口挂错档**：判据原来是 `selectedTab == 3 || selectedTab == 4` —— 档位顺序一动，
   窗口就挂到别的档上（比如「全部」被按今天过滤），**两边都不报错**，用户只会觉得"单丢了"；
2. **默认档偷偷回到「全部」**：一进页面看到的就不是他要的那一档，而他不会每页都来核对；
3. **药丸藏进列表里**：默认档是"今天"，今天没单时列表本来就是空的 —— 藏在"列表非空"的分支里，
   用户**换不了档**（司机端 2026-09-20 栽过同一个坑）；
4. **截断提示回到顶部**：把第一张单推下去（用户点名"占位置"），或者反过来被**静默删掉**
   （列表被服务端截断时，不说就等于让用户以为"这单不存在"）；
5. **动作左右分错**：编辑跑到左边/破坏性动作跑到右边 —— 这一条是**规范**（"以后也是这样子"），
   不是这一页的临时样式，所以要有判据钉住；
6. **单号又与状态徽章抢一行**：单号是 20 个字符（`SO` + 8 位日期 + 10 位随机数），22sp 下约 240dp，
   同一行再放一个徽章就放不下 → 折行 = 用户说的"错位"（他明确要求**不要缩字号**）；
7. **复制提示静默**：长按了却什么都不发生（Android 13 之前系统不会自己弹），用户会以为功能坏了。

清单**全部自己算**（扫 `ui/**/*.kt` 认档位表与 `DEFAULT_TAB`），不手写文件页码；
每节都带数量下限，注册表腐烂时先红而不是安静地什么都不查。

用法：python _tools/qa/_check_order_list_ui.py
配套：python _tools/qa/_reverse_verify_order_list_ui.py（8 种破坏方式全被抓）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker, read, strip_comments  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
UI = ANDROID / "ui"
COMMON = UI / "common"
DISP_VM = UI / "dispatcher/DispatcherOrdersViewModel.kt"
DISP_SCREEN = UI / "dispatcher/DispatcherOrdersScreen.kt"
SHIP_VM = UI / "shipper/ShipperOrdersViewModel.kt"
SHIP_SCREEN = UI / "shipper/ShipperOrdersScreen.kt"
TABS_KT = COMMON / "OrderTabs.kt"
WINDOW_BASE = COMMON / "OrderWindowViewModel.kt"
CARD_KT = COMMON / "OrderCard.kt"
COMPONENTS_KT = COMMON / "Components.kt"
DETAIL_KT = UI / "order/OrderDetailScreen.kt"

#: 每个档位表的**缺省档**（用户 2026-09-22 点名的那两条）。
#: 值 = (状态码, 中文)。中文也对一遍：只核状态码的话，档位标签被改成别的字照样绿。
EXPECTED_DEFAULT: dict[str, tuple[str, str]] = {
    "DispatcherOrdersViewModel.kt": ("PENDING_DISPATCH", "派单中"),
    "ShipperOrdersViewModel.kt": ("ACCEPTED", "已接单"),
}

#: 档位表（`val XXX_TABS = listOf(...)`）。⚠️ 结尾的 `\n)` 是**顶格**那个右括号 —— 两个表都这么写。
ROSTER_RE = re.compile(r"val\s+(\w+_TABS)\s*=\s*listOf\(([\s\S]*?)\n\)")
TAB_RE = re.compile(r'OrderTab\(\s*(null|"[A-Z_]+")\s*,\s*"([^"]*)"([^)]*)\)')
#: 子类把「本角色的档位表 + 缺省档的**状态名**」交给共用内核（⛔ 不是下标）。
SUPER_RE = re.compile(r":\s*OrderWindowViewModel\(container,\s*(\w+_TABS),\s*\"([A-Z_]+)\"\)")
#: 旧的「只看一个页面」的写法（收编之后不该再有）。
DEFAULT_RE = re.compile(r"private\s+val\s+DEFAULT_TAB\s*=")
#: 旧写法：拿**下标**判"这一档要不要日期窗口"。
INDEX_JUDGE_RE = re.compile(r"\b(?:tab|selectedTab)\s*==\s*\d+\s*\|\|\s*(?:tab|selectedTab)\s*==\s*\d+")


def parse_roster(body: str) -> list[tuple[str | None, str, bool]]:
    out: list[tuple[str | None, str, bool]] = []
    for raw_key, label, rest in TAB_RE.findall(body):
        key = None if raw_key == "null" else raw_key.strip('"')
        # ⚠️ 只认 `rest` 里**有没有** `dated = true` —— 别把"后面没有别的具名参数"写进形状：
        #    第一版的正则要求条目以 `dated = …` 收尾，于是加上 `windowWord = …` 之后
        #    那两档直接从档位表里**消失**了（判据当场红了一片，这正是它该做的）。
        out.append((key, label, re.search(r"dated\s*=\s*true", rest) is not None))
    return out


def all_ui_sources() -> dict[Path, str]:
    return {p: strip_comments(read(p)) for p in sorted(UI.rglob("*.kt"))}


def main() -> int:
    # 别人的反向验证正在跑时**拒绝出结论**：那一刻源码里带着注入的 bug，
    # 报出来的红与你的改动无关（`_tools/ai/_airepo.py` 里写着这条的由来）。
    if refuse_if_injecting("订单列表 UI 检查"):
        return 1

    c = Checker()

    c.section("0. 反空转（文件搬走/被清空时先喊）")
    for p in (DISP_VM, DISP_SCREEN, SHIP_VM, SHIP_SCREEN, TABS_KT, CARD_KT, COMPONENTS_KT, DETAIL_KT, WINDOW_BASE):
        c.ok(f"{p.name} 在", p.exists())
    if c.fails:
        print("\n❌ 关键文件不在，后面的判据没有意义")
        return 1

    srcs = all_ui_sources()
    disp_vm, ship_vm = read(DISP_VM), read(SHIP_VM)
    disp_screen, ship_screen = read(DISP_SCREEN), read(SHIP_SCREEN)
    tabs_kt, card_kt, components = read(TABS_KT), read(CARD_KT), read(COMPONENTS_KT)
    detail = read(DETAIL_KT)

    # ── 档位表：从源码自己算，不手写 "DISPATCH_TABS/SHIPPER_TABS" 两个名字 ──
    # ⚠️ 只认**订单状态**档位表：全库里还有别的 `val XXX_TABS = listOf(`（退货申请那两页），
    #    它们的第一格不是「全部」、也没有 `dated` —— 不加这一道筛，本节会对着退货页报一堆假红
    #    （2026-09-22 第一版就是这么红的）。
    rosters: dict[str, tuple[Path, list[tuple[str | None, str, bool]]]] = {}
    for path, src in srcs.items():
        for name, body in ROSTER_RE.findall(src):
            if "OrderTab(" not in body:
                continue
            rosters[name] = (path, parse_roster(body))
    # 缺省档现在由**子类的构造参数**给共用内核（`OrderWindowViewModel(container, XXX_TABS, "KEY")`）——
    # 从源码自己算出来，不手写 "DISPATCH_TABS/SHIPPER_TABS" 两个名字（2026-09-22 收编后改）。
    defaults: dict[str, tuple[str, str | None]] = {}
    for path, src in srcs.items():
        for name, key in SUPER_RE.findall(src):
            defaults[name] = (path.name, key)

    n_tab_literals = sum(len(re.findall(r"OrderTab\(", s)) for s in srcs.values())
    c.ok(f"从源码认出了 2 个档位表（实际 {len(rosters)}：{sorted(rosters)}）", len(rosters) >= 2)
    c.ok(f"档位条目 >= 12 条（实际 {n_tab_literals}，防正则失配后整节空转）", n_tab_literals >= 12)
    c.ok(f"两个档位表的缺省档都算出来了（{sorted(defaults)}）", len(defaults) >= 2)
    # ⚠️ 只在"档位表**本身**没认出来"时提前收工。`DEFAULT_TAB` 少算一个**不许**让后面整节跳过：
    #    那正好会把"缺省档被写死成下标"这一条最要紧的判据一起跳过 ——
    #    2026-09-22 反向验证第 ③ 条当场抓出来的（原来这里 `if c.fails` 一拦，
    #    等于给"把默认档写成 0"开了一条**只红在反空转上**的后路）。
    if len(rosters) < 2 or n_tab_literals < 12:
        print("\n❌ 档位表没认出来（形状变了？），后面的判据不可信")
        return 1

    c.section("1. 档位模型只有一份（两个页面共用 OrderTab）")
    holders = [p for p, s in srcs.items() if "data class OrderTab" in s]
    c.ok("`data class OrderTab` 全库只有一处定义", len(holders) == 1,
         "出现了 " + str([str(p.relative_to(ROOT)) for p in holders]))
    c.ok("它安家在 ui/common/OrderTabs.kt（两个角色都要 import 它）",
         len(holders) == 1 and holders[0] == TABS_KT)
    c.ok("档位表每一档都写着 `dated = ...`（缺省 false；要日期窗口的必须显式写）",
         all("dated" in s for p, s in srcs.items() if "OrderTab(" in s) and "dated: Boolean = false" in tabs_kt)

    c.section("1b. 每个订单状态都至少落在一个档位里（清单从后端枚举算，2026-09-24 第 19 轮）")
    # ⛔ 为什么必须自己算：`docs/DOMAIN_MODEL.md:22-23` 写着「`DISPATCHED` 不是过渡态，它会停留……
    #    每个客户端都必须有入口列出它，否则『派错司机』这件事既看不见也撤不回」，
    #    而**两个 App 的档位表里都一个 `DISPATCHED` 档都没有**（实测 7 张单在所有具名档位里查不到、
    #    唯一落点「全部」被自动挡钉在"今天"）。当时两条红线都绿着：
    #    `_check_client_contract.py` 认"客户端**认识**这个状态"（详情页里有 `== "DISPATCHED"`），
    #    本节原来只钉缺省档文案 —— **没有任何一条断言"这一档有没有入口"**。
    #    所以这里从 `models/enums.py` 把取值读出来，逐个问两个档位表。
    enum_src = read(ROOT / "backend/app/models/enums.py")
    # 取到下一个 `class` 为止（这个枚举里有注释块与 docstring，长度不固定 —— 写死 600 字会失配）。
    m = re.search(r"class OrderStatus\([\s\S]*?(?=\nclass )", enum_src)
    statuses = re.findall(r'^\s{4}([A-Z_]+)\s*=\s*"', m.group(0), re.M) if m else []
    c.ok(f"从后端枚举算出订单状态 {len(statuses)} 个（下限 5，防正则失配后空转）",
         len(statuses) >= 5, f"实际 {statuses}")
    #: 故意**不进任何档位**的状态 + 为什么（空 = 每一个都必须有档位）。
    NO_TAB_NEEDED: dict[str, str] = {}
    for name, (path, tabs) in sorted(rosters.items()):
        keys = {t[0] for t in tabs}
        orphaned = [s for s in statuses if s not in keys and s not in NO_TAB_NEEDED]
        c.ok(f"{name}：每个订单状态都有档位（{len(statuses)} 个状态，{len(tabs)} 档）",
             not orphaned,
             f"这些状态**一个入口都没有**：{orphaned} —— 它会停留在这一档，"
             f"用户在任何具名档位里都找不到它（'{'、'.join(orphaned)}'）")

    c.section("2. 缺省档 + 「全部」的位置（用户点名的两条）")
    for name, (path, tabs) in sorted(rosters.items()):
        keys = [t[0] for t in tabs]
        c.ok(f"{name}：第 1 格是「全部」（{tabs[0][1] if tabs else '?'}）", bool(tabs) and keys[0] is None and tabs[0][1] == "全部")
        want_key, want_label = EXPECTED_DEFAULT.get(path.name, ("", ""))
        if not want_key:
            c.ok(f"{name}：缺省档登记在 EXPECTED_DEFAULT 里（新增档位表必须登记）", False,
                 f"{path.name} 没登记 —— 新页面请补一条并写清理由")
            continue
        got_key = defaults.get(name, ("", None))[1]
        idx = keys.index(got_key) if got_key in keys else -1
        label = tabs[idx][1] if idx >= 0 else "?"
        c.ok(f"{name}：缺省档 = 「{want_label}」（第 2 格，下标 1）",
             got_key == want_key and label == want_label and idx == 1,
             f"实际 key={got_key} label={label} 下标={idx}")
        c.ok(f"{name}：缺省档**不是**「全部」（用户：「默认是不会进入「全部」的」）", got_key is not None)
        c.ok(f"{name}：缺省档写的是**状态名**（不是 0/1 —— 重排时会静默指错档）",
             bool(re.search(rf"OrderWindowViewModel\(container,\s*{name},\s*\"[A-Z_]+\"\)", read(path))))

    c.section("3. 档位 → 窗口的判据：共用内核 + 跟着档位自己走（不是下标）")
    base_kt = read(WINDOW_BASE)
    c.ok("共用的窗口内核只有一处定义（`ui/common/OrderWindowViewModel.kt`）",
         sum(len(re.findall(r"abstract class OrderWindowViewModel\(", s)) for s in srcs.values()) == 1
         and "abstract class OrderWindowViewModel(" in base_kt)
    c.ok("窗口判据按**档位自己**的标记判、且在内核里（不写下标）",
         "val datedTab: Boolean get() = currentTab.dated" in base_kt)
    subclasses = sorted(p.name for p, s in srcs.items() if SUPER_RE.search(s))
    c.ok(f"两个订单列表都继承了那个内核（识别到 {len(subclasses)} 个：{subclasses}）",
         len(subclasses) >= 2)
    c.ok("没有子类再自己养一份 `DEFAULT_TAB`（缺省档按状态名交给内核）",
         not any(DEFAULT_RE.search(s) for s in srcs.values()))
    for name, (path, tabs) in sorted(rosters.items()):
        super_call = SUPER_RE.search(read(path))
        c.ok(f"{name}：把「表 + 缺省档**状态名**」交给内核（⛔ 不是下标）", super_call is not None)
        c.ok(f"{name}：既有带窗口的档、也有不带的（否则药丸要么永远在、要么永远不在）",
             any(t[2] for t in tabs) and any(not t[2] for t in tabs),
             f"dated={[t[1] for t in tabs if t[2]]}")
        # ── 哪几档带窗口（用户 2026-09-22 把这条说全了）──
        # 「那个只针对…像是**全部、已完成**的（才）要选择时间。对，**全部我们也要有时间的筛选**」
        # 「但是比如说**派单中和已接单他属于正在进行**啊，所以他是**不会有选择时间**」
        by_key = {t[0]: t for t in tabs}
        default_key = defaults.get(name, ("", None))[1]
        c.ok(f"{name}：「全部」**也有**时间筛选（找单最常用的入口，要找的单多半不在今天）",
             by_key.get(None, (None, "", False))[2] is True)
        c.ok(f"{name}：进行中的档（缺省档 = {default_key}）**不按日期筛**（`dated` 必须为 false）",
             by_key.get(default_key, (None, "", True))[2] is False,
             "给「正在进行」套一层日期窗口 = 积压的老单不见了，而界面上一个字都不说")
    offenders = [str(p.relative_to(ROOT)) for p, s in srcs.items() if INDEX_JUDGE_RE.search(s)]
    c.ok("全库没有 `tab == 3 || tab == 4` 这种下标判据了", not offenders, f"还有：{offenders}")

    c.section("3b. 「找订单的自动挡」：进来先找有单的那一段，手动挑过就永不自动改")
    presets_kt = read(COMMON / "DatePresets.kt")
    c.ok("共享的长阶梯只有一处定义（`DatePresets.ORDER_PRESET_LADDER`）",
         sum(len(re.findall(r"val ORDER_PRESET_LADDER = listOf\(", s)) for s in srcs.values()) == 1
         and "val ORDER_PRESET_LADDER = listOf(" in presets_kt)
    c.ok("司机端也读共享的那一条（不再自己养一份 `DRIVER_PRESET_LADDER`）",
         "DatePresets.ORDER_PRESET_LADDER" in read(UI / "driver/DriverOrdersViewModel.kt")
         and not any("DRIVER_PRESET_LADDER" in s for s in srcs.values()))
    c.ok("两条阶梯的差别是**故意的**（短的给「看账」、长的给「找单」）",
         "val AUTO_LADDER = listOf(TODAY, YESTERDAY, BEFORE_YESTERDAY, LAST_7)" in presets_kt
         and "ORDER_PRESET_LADDER" in presets_kt)
    for label, vm_path in (("派单员", DISP_VM), ("货主", SHIP_VM)):
        vm = read(vm_path)
        c.ok(f"{label}：`probeHasData` 真的接了 `repo.orders`（探测与取数同一个端点）",
             re.search(r"override suspend fun probeHasData\(status: String\?, from: String, to: String\)"
                       r": Boolean = try \{[\s\S]{0,600}?\.orders\(", vm) is not None,
             "探测必须与取数同源，否则会退档到一档还是空的")
        c.ok(f"{label}：取数走内核给的窗口（`windowRange()`），不是自己算日期",
             re.search(r"val \(from, to\) = windowRange\(\)", vm) is not None)
    c.ok("自动挡的挑窗口只有一处（内核里调共用 `pickWindow`）",
         "DatePresets.pickWindow(DatePresets.ORDER_PRESET_LADDER)" in base_kt)
    c.ok("手动挑过档位就**永不自动改**（`userPickedPreset = true` 出现在挑档的两条路上）",
         base_kt.count("userPickedPreset = true") >= 2)
    c.ok("盘点期间药丸写「…」（这时的任何档位名都是假话）",
         'datedTab && !windowSettled -> "…"' in base_kt)
    # ⚠️ 下面这一条是**真机当场抓出来的**（2026-09-22）：第一版照司机端抄了"整个页面只挑一次"
    #    （`autoPickedPreset`），于是"先点「全部」（挑到今天）、再点「已送达」"就**不再挑了** ——
    #    「已送达 + 今天没单」停在空列表上，正是用户要避免的画面。司机端能"只挑一次"是因为
    #    它只有一个带窗口的档；这两个页面各有 4 个。
    c.ok("**每次**进带窗口的档位都重新找有单的那一段（且用户手动挑过就不再自动改）",
         re.search(r"if \(currentTab\.dated && !userPickedPreset\)", base_kt) is not None)
    c.ok("没有「只挑一次」那个开关（真机会停在空窗口上）",
         "autoPickedPreset" not in base_kt)
    for label, screen in (("派单员「订单管理」", disp_screen), ("货主「我的订单」", ship_screen)):
        c.ok(f"{label}：盘点期间整页 loading（不许先闪一批上一档的单）",
             "vm.datedTab && !vm.windowSettled -> LoadingBox()" in screen)

    c.section("4. 时间药丸在**顶栏**（不许藏进列表，也不许回到横滑胶囊行）")
    for label, screen in (("派单员「订单管理」", disp_screen), ("货主「我的订单」", ship_screen)):
        c.ok(f"{label}：药丸由 `vm.pillWord` 决定画不画（每一档都画 = 顶栏形态统一）",
             "vm.pillWord?.let { word ->" in screen)
        c.ok(f"{label}：用的是共用那一份 `DatePresetPill`（不自造时间控件）",
             "DatePresetPill(" in screen)
        c.ok(f"{label}：药丸在 `items(` **之前**（顶栏 = 列表之前）",
             screen.find("DatePresetPill(") >= 0 and 0 <= screen.find("DatePresetPill(") < screen.find("items("),
             "排在列表后面就是「列表里的一行」，空列表时根本画不出来")
        c.ok(f"{label}：药丸确实在顶栏的 `actions = {{` 里（不是随便一个 Row）",
             0 <= screen.find("actions = {") < screen.find("DatePresetPill("))
        c.ok(f"{label}：两个弹层走共用的 `DateFilterDialogs`（那条「先关清单再开弹层」的规矩只此一份）",
             "DateFilterDialogs(" in screen)
        c.ok(f"{label}：旧的横滑胶囊行（`DateRangeFilter`）已经摘掉", "DateRangeFilter(" not in screen)
        # 2026-09-22 第三轮：可按日期筛的档**可点**，正在进行那两档**只显示**（用户：「为了美观而
        # 统一…那个图标**无法选择**，他不会有列表，就是只有显示」）。
        c.ok(f"{label}：按 `pillPickable` 分两种画法（可点 / 只显示）",
             "if (vm.pillPickable) {" in screen
             and "DatePresetPill(label = word, onClick = { vm.showDatePresets = true })" in screen
             # ⚠️ 这里要的是「**没有** onClick 的那一次调用」：只断言子串 `DatePresetPill(label = word)`
             #    是不够的 —— 它同时是 `DatePresetPill(label = word, onClick = …)` 的前缀，
             #    于是"给不可点那颗也挂上 onClick"这种改法照样绿（反向验证第 ㉖ 条当场抓出来的）。
             and re.search(r"DatePresetPill\(label = word\)\s*\n", screen) is not None)
        # 带窗口的档默认是「今天」→ 今天没单时列表本来就该是空的。空态不指路，用户只会觉得
        # "这一页坏了"（司机端 2026-09-20 就是这么被困住的：筛空之后没有出路）。
        c.ok(f"{label}：空列表时文案指向右上角那个药丸",
             "点右上角可以换一段时间" in screen)
    n_range_filter_calls = sum(len(re.findall(r"(?<!fun )DateRangeFilter\(", s)) for s in srcs.values())
    c.ok(f"`DateRangeFilter` 还有真实调用者（>=1，实际 {n_range_filter_calls}）—— 别把它变成孤儿控件",
         n_range_filter_calls >= 1)
    c.ok("不可点的那颗药丸**不画 ▾ 箭头**（`DatePresetPill` 按 onClick 是否为空判）",
         "fun DatePresetPill(label: String, onClick: (() -> Unit)? = null" in components
         and re.search(r"if \(onClick != null\) \{\s*\n\s*Icon\(Icons\.Default\.ArrowDropDown", components) is not None,
         "在不能点的东西上画一个「点我」的记号 = 把用户引到一个点了没反应的地方")

    c.section("4b. 「正在进行」那两档的药丸：只显示，而且写的必须是实话")
    preset_words = set(re.findall(r'const val \w+ = "([^"]+)"', presets_kt))
    c.ok(f"从 `DatePresets` 解析出档位词（{len(preset_words)} 个；解析失效时先喊）",
         len(preset_words) >= 8, f"实际 {sorted(preset_words)}")
    tab_consts = dict(re.findall(r'const val (\w+) = "([^"]+)"', tabs_kt))
    frozen: dict[str, str] = {}
    for name, (path, _tabs) in sorted(rosters.items()):
        for m in re.finditer(r'OrderTab\((null|"[A-Z_]+"), "([^"]*)"[^)]*?windowWord = (\w+)\)', read(path)):
            frozen[f"{name}/{m.group(2)}"] = tab_consts.get(m.group(3), m.group(3))
    c.ok(f"认出了「只显示」的那几档（{sorted(frozen)}）", len(frozen) >= 2)
    bad_words = {who: w for who, w in frozen.items() if w in preset_words}
    c.ok("「正在进行」那几档的药丸词都**不是日期档位名**（写「今天」= 屏幕上的一句假话，"
         "而且那颗药丸**点不开**，用户没法点开它去发现）",
         not bad_words, f"有问题的：{bad_words}")
    c.ok("那个词只有一处定义（`ORDER_WINDOW_NO_LIMIT_WORD`）",
         sum(len(re.findall(r"const val ORDER_WINDOW_NO_LIMIT_WORD", s)) for s in srcs.values()) == 1)

    c.section("5. 截断提示挪到列表**最后一行**（不是删掉）")
    c.ok("`ORDER_LIST_LIMIT` 全库只有一处定义（原来两个 VM 各写一份 300）",
         sum(len(re.findall(r"const val ORDER_LIST_LIMIT", s)) for s in srcs.values()) == 1
         and "const val ORDER_LIST_LIMIT" in tabs_kt)
    # 同一句写给用户的话**只能有一份**：这句话里点名的入口（右上角日期筛选、哪几档才有）
    # 以后一定会变，两页各写一份就是"改一处漏一处"，而用户会照着提示去找。
    c.ok("截断提示那句「还能怎么看到更早的」两页共用一份（`ORDER_TRUNCATION_HOW`）",
         sum(len(re.findall(r"const val ORDER_TRUNCATION_HOW", s)) for s in srcs.values()) == 1
         and "const val ORDER_TRUNCATION_HOW" in tabs_kt)
    for label, screen, vm in (
        ("派单员「订单管理」", disp_screen, disp_vm),
        ("货主「我的订单」", ship_screen, ship_vm),
    ):
        c.ok(f"{label}：截断判据还在（`maybeTruncated` 不许被删）", "maybeTruncated" in vm)
        c.ok(f"{label}：截断时**说出来**（走共用的 `TruncationNote`，不自己写措辞）",
             "TruncationNote(" in screen and "limit = ORDER_LIST_LIMIT" in screen
             and "howToSeeMore = ORDER_TRUNCATION_HOW" in screen)
        c.ok(f"{label}：提示在 `items(` **之后**（= 列表最后一行，不再把第一张单推下去）",
             0 <= screen.find("items(") < screen.find("TruncationNote("),
             "回到顶部就是用户点名要删的那个「占位置」的提示")

    c.section("6. 卡片动作分区：左＝反向/警示，右＝编辑")
    c.ok("`OrderCard` 两个槽都在（leading + extra）",
         re.search(r"leading:\s*@Composable\s+RowScope\.\(\)\s*->\s*Unit\s*=\s*\{\}", card_kt) is not None
         and re.search(r"extra:\s*@Composable\s+RowScope\.\(\)\s*->\s*Unit\s*=\s*\{\}", card_kt) is not None)
    c.ok("左槽先画、右槽靠边（`leading()` 在 `Spacer(weight)` 之前）",
         re.search(r"leading\(\)\s*\n\s*Spacer\(Modifier\.weight\(1f\)\)\s*\n\s*extra\(\)", card_kt) is not None)
    c.ok("圈底图标动作控件只有一处定义（`CardActionIcon`）",
         sum(len(re.findall(r"fun CardActionIcon\(", s)) for s in srcs.values()) == 1
         and "fun CardActionIcon(" in components)
    c.ok("它复用了卡片既有的圆底画法（`TintedIcon`），没另画一个圆",
         re.search(r"fun CardActionIcon\([\s\S]{0,900}?TintedIcon\(", components) is not None)
    # 2026-09-22：账户管理页原来自己养了一个 `AccountAction`（圈底图标 **+ 文字**），
    # 与这个控件是同一件事的两份实现 —— 圆底画法本来就共用 `TintedIcon`，差别只在有没有那行字。
    # 收成一个可选参数 `label`，那一页改成**委托**（用户点头：「对账户管理那个你也做了去吧」）。
    acct_screen = read(UI / "dispatcher/AccountManageScreen.kt")
    c.ok("共用控件支持「圈底图标 + 文字」形态（`label` 是可选参数）",
         re.search(r"fun CardActionIcon\([\s\S]{0,600}?label: String\? = null,", components) is not None)
    c.ok("账户管理页那份 `AccountAction` 只是**委托**给共用控件（不再自己画一遍圈底图标）",
         re.search(r"private fun AccountAction\([\s\S]{0,700}?= CardActionIcon\(", acct_screen) is not None
         and "label = label" in acct_screen,
         "两份实现 = 下一次改样式（位置/形态）必然漏掉其中一页")
    c.ok("账户管理页左右分区的原样保留（左＝删除/停用 · 右＝编辑）",
         'AccountAction("删除"' in acct_screen and 'AccountAction("编辑"' in acct_screen)
    # ⚠️ 2026-09-22 真机上还核出一处反例：`运费模板` 的价目卡是「编辑 · 删除」（与规范反着）。
    #    那 2 行我改了，但**没有提交、也没有在这里加判据** —— 那个文件正被另一个会话大改
    #    （对照 HEAD 有 270+ 行在途，而且当时那一版直接编译不过）。理由与现状写在
    #    `FreightTemplatesScreen.kt` 那段注释里；等他们收工后再把「改动 + 判据」一起提交。
    c.ok("派单员页：编辑在右、异常在左（两处圈底图标）",
         disp_screen.count("CardActionIcon(") >= 2)
    c.ok("派单员页：编辑仍走 `vm.openEdit`、异常仍走 `vm.openException`（只是换了外壳）",
         "vm.openEdit(order)" in disp_screen and "vm.openException(order)" in disp_screen)
    c.ok("派单员页：不再用裸 `IconButton` 画编辑/异常（用户：「这个不行啊，他要一个图标」）",
         "IconButton(onClick = { vm.openEdit(" not in disp_screen
         and "IconButton(onClick = { vm.openException(" not in disp_screen)
    c.ok("派单员页：`leading` 在 `extra` **之前**（左＝反向，右＝编辑）",
         0 <= disp_screen.find("leading = {") < disp_screen.find("extra = {"))
    c.ok("货主页：这一页的动作全是反向类 → 全在 `leading`，右边留给「编辑」",
         "leading = {" in ship_screen and "extra = {" not in ship_screen)
    c.ok("货主页：撤销订单仍走 `vm.cancelTarget`、退货申请仍走 `vm.openReturn`",
         "vm.cancelTarget = order" in ship_screen and "vm.openReturn(order)" in ship_screen)

    c.section("7. 订单详情：单号独占一行（不缩字号）+ 长按复制")
    # ⚠️ 单号那句是**跨行**写的（`Text(` 与 `"#" + order.orderNo` 不在同一行），
    #    所以不能用 `detail.find('Text("#" + order.orderNo')` —— 那样永远 -1，
    #    后面三条断言会**全部静默为 False**（第一版就是这么假红的）。
    m_no = re.search(r'Text\(\s*"#" \+ order\.orderNo', detail)
    pos_no = m_no.start() if m_no else -1
    pos_chip = detail.find("OrderStatusChip(order.status)", pos_no if pos_no >= 0 else 0)
    window = detail[pos_no:pos_chip] if pos_no >= 0 and pos_chip > pos_no else ""
    c.ok("单号仍是 `titleLarge`（用户：「**不要缩小**一点」）",
         re.search(r'Text\(\s*"#" \+ order\.orderNo,\s*style = MaterialTheme\.typography\.titleLarge', detail) is not None)
    c.ok("单号那一句能定位到（判据自己先别失配）", bool(window), "正则没命中 = 单号写法变了，先修判据")
    c.ok("单号与状态徽章**不再同一行**（中间隔着「创建于 …」那一行）",
         '"创建于 "' in window,
         "同一个 Row 里塞 20 个字符 + 一个徽章 = 折行，就是用户说的「错位」")
    c.ok("单号上挂了 `combinedClickable`（点击无动作、**长按**才做事）",
         "combinedClickable(" in window)
    c.ok("长按走共用的 `copyTextToClipboard`（不自己写一份剪贴板代码）",
         "copyTextToClipboard(" in window)
    c.ok("复制到剪贴板的实现只有一处（ui/common/Clipboard.kt）",
         sum(len(re.findall(r"fun copyTextToClipboard\(", s)) for s in srcs.values()) == 1
         and "fun copyTextToClipboard(" in read(COMMON / "Clipboard.kt"))
    c.ok("老系统上自己弹一句（Android 13+ 系统会弹，别叠两条）",
         "Build.VERSION.SDK_INT < 33" in read(COMMON / "Clipboard.kt"))

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：两个订单列表的档位/默认档/时间药丸/截断提示/卡片动作分区，"
          f"以及详情页的单号与长按复制，都还钉着。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
