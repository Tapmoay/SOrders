"""整套配色换成用户三张参考图那一套：低饱和、暖底、不再刺眼。

## 用户要的是什么
**口径（ref m02474）**：「按照它的配色方案进行一下修改以及我给你的那个照片」
**（ref m02545）**：「这是新任务吼也就是改我途中给你发的那些样式」
**（ref m02683，硬约束）**：「继续继续，但**我不希望整体太过于灰**啊」

三张图分别是：① 七色语义色板 ＋ 四条设计要点；② 派单端工作台 21 格宫格（每格一个低饱和身份色）；
③ 待派单池的订单卡（商品块 #B5726B / 确认接单 #8B4A4A / 已派单徽标暖金）。

### 从图里读出来的七个语义色（逐字）
主操作（确认接单）`#8B4A4A` / 商品订单 `#B5726B` / 成功完成 `#567A5F` / 提醒重要 `#C8A56A`
（图上写作 `xC8A56A`，是作者的笔误）/ 普通信息 `#6B7F99` / 禁用辅助 `#9B8F88` / 背景 `#F7F6F3`。

### 图三点名的四条设计要点（这是"为什么"）
① 关键任务不使用过亮颜色（商品订单与确认接单同属红棕、靠明度与饱和度分层）；
② 图标使用低饱和语义色（"避免高亮和过度饱和，**保护老年用户的视觉舒适度**"）；
③ 统一的视觉风格（低饱和、柔和、易读，简洁稳重统一）；
④ 兼顾可用性与辨识度（形状、图标、文案与色彩组合出层级，避免视觉刺激）。

## 为什么这条必须有机器的判据（每一处坏了都不报错、不崩、测试也不会红）
1. **旧色悄悄回来**：`0xFF00A870`（旧主色绿）与它的十几个兄弟在**用色处硬编码**着 ——
   全仓实测 **159 处、27 个文件**。有人复制粘贴一段旧代码、或者从旧分支 cherry-pick 一行，
   编译过、单测过、页面照常渲染，只是那一块又变回刺眼的高饱和色。
   ⚠️ 这类"只换 token、不动硬编码"是**最容易漏的一半**：token 换了以后，
   硬编码的那些**看起来仍然是"某个具体色"**，没有任何工具会说它错了。
2. **主操作色退回绿或蓝**：`ThemeGreen` / `NavBlue`（别名 16 处引用）/ `InfoBlue` 一断，
   全 App 的主色就回去了，而且 `NavBlue = ThemeGreen` 这个别名关系还在，编译全绿。
3. **`Color.kt` 里出现 `Color(0x…)` 形式**：语义色 token 必须是**裸 ARGB Long**
   （`Color.kt` 自己写明：写成 `Color(0x…)` 会让同一 Row 里两种类型对不上，**编译不过**）。
4. **饱和度过低＝整片发灰**：用户点的是"低饱和"，但同一句话里还有「我不希望整体太过于灰」——
   这两条是**一对**。地板写死在单测里（`SAT_FLOOR`），谁把它往上提到 22%/30%，
   就是在"用尺子改设计"、逼每一格偏离用户画的色；谁把它删掉，发灰就没人拦。
5. **主操作色上的白字读不清**：`#8B4A4A` 上的白字对比度 **6.61:1**（过 AA 的 4.5），
   这是全套里唯一稳过的一条 —— 有人把主色提亮一点点（"看着更精神"），
   对比度就掉到 4.5 以下，而界面照常渲染、没有任何工具会说他。
6. **账本入口页 7 格撞色**：这一页是**唯一被单测真的量了两两距离 ≥60** 的两处之一
   （`ui/nav/ModulesEntryTest.kt:210`）。7 个格子的色现在是**裸字面量**（不是 token），
   改一格就可能让两格距离掉到 60 以下 —— 判据在 `_check_ledger_dashboard.py` 与那条单测里，
   本条只做交叉引用。
7. **文档与代码两份口径**：`06_DESIGN_SYSTEM.md` §2 那张语义色总表是**人读的唯一入口**。
   代码换完表不换，下一个人按文档改就会把旧色写回来（CHG-0091 那一轮就是这么错的）。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
上面 7 条**没有一条是类型属性**：`Color` 与 `Color` 之间没有类型差
（`#8B4A4A` 与 `#00A870` 同型、同构造、同渲染路径），`Long` 与 `Long` 之间更没有。
编译器只认"这是个颜色"，不认"这是不是用户画的那个颜色"；单测要拦住它就得**把色值抄第二份**
（那正是本判据在做的事，抄在判据里而不是抄在实现里）。所以判据只能落在**源码文本**上：
"哪个 token 等于哪个值""这个旧值还有没有人在用""用色处是不是还硬编码着"，
再配反向验证 `_reverse_verify_low_sat_palette.py`（把每一条分别弄坏一次，看它真的变红）。

静默空转保护：`MIN_KT = 100`（目录被搬走 / 一个 .kt 都没扫到就红，不许"扫了 0 个也全绿"）。

## 判据
0. 反空转：扫到的 `.kt` 数量 ≥ `MIN_KT`；`ui/**/*.kt` 里硬编码色的**总数**在一个宽区间内
   （防"正则失配 → 一处都扫不到 → 下面每一节都空绿"）；
1. `Color.kt`：七个语义色对应的 token 全是**用户图里那套新值**；`ThemeGreen` / `NavBlue` / `InfoBlue`
   三者的别名关系还在；语义色 token **不是** `Color(0x…)` 形式；
2. **全仓 `ui/**/*.kt` 里不许再出现任何一个旧 token 值**（`Color.kt` 自己除外——
   它的 KDoc 里写着"原来是 #00A870"这类历史，那是**注释**，判据只看代码）；
   例外白名单只有一条：报表现金流的深蓝（见 `ALLOW_OLD`）；
3. **用色处的硬编码必须已经跟着换**：新值的硬编码出现次数 ≥ 一个下限，
   且 `#FF9500` / `#00B578` / `#00A2C7` 这几个大户**一处都不许留**；
4. 单测 `ui/theme/ThemePaletteTest.kt` 在，且 `SAT_FLOOR = 0.15`
   （**既拦发灰、又不许被抬高**）+ 主操作色白字对比度 ≥ 4.5 那一条也在；
5. 相交判据还在：`_check_ledger_dashboard.py` 的 7 格 ≥60、`ModulesEntryTest` 的账本入口页那一条、
   `_check_green_theme.py` 的主色与商品胶囊、`_check_warm_surface_palette.py` 的暖砂白四层；
6. 用户口径留档：`docs/changes/CHG-0101.md` 里 m02474 / m02545 / m02683 三条原话与图三的
   七个色值都在；`06_DESIGN_SYSTEM.md` 的语义色总表已经是新值（旧值一处不留）；
7. 配套：反验脚本 `_reverse_verify_low_sat_palette.py` 在，且 `CHG-0101` 在变更单与登记簿里。

用法：python _tools/qa/_check_low_sat_palette.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
COLOR = AND / "ui/theme/Color.kt"
MODULES = AND / "ui/nav/Modules.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/theme/ThemePaletteTest.kt"
DOC = ROOT / "docs/changes/CHG-0101.md"
REG = ROOT / "docs/changes/README.md"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_low_sat_palette.py"

#: 全仓至少要有这么多 .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_KT = 100

#: 硬编码色总处数的宽区间 —— 只拦"正则突然失配"，不拦正常增减。
HARD_MIN, HARD_MAX = 120, 900

#: 用户图一/图三那七个语义色（`Color.kt` 里对应的 token 必须等于这些值）。
#: ⚠️ "背景 #F7F6F3" 落在 `BackgroundLight`；"禁用辅助 #9B8F88" 落在 `AccountBrown`
#:    （那一格是暖灰棕，CHG-0101 从 #8D6E63 换成了 #97897F，同一族）。
SEMANTIC = {
    "ThemeGreen": "0xFF8B4A4A",        # 主操作（确认接单）
    "MgrGreen": "0xFF59A570",          # 成功 / 完成 / 代理下单（H 档）
    "WarningAmber": "0xFFC8A56A",      # 提醒 / 重要
    "ShipperTeal": "0xFF529EBF",       # 普通 / 信息 / 地址与联系人（H 档）
    "AccountBrown": "0xFFA2763D",      # 禁用 / 辅助 / 账户管理（H 档：赭石，⛔ 不再是灰）
}

#: 主操作色那一族（Primary 四件套）：浅底 / 深字必须同族。
PRIMARY_KIT = {
    "Primary": "Color(0xFF8B4A4A)",
    "PrimaryContainer": "Color(0xFFF0E2DC)",
    "OnPrimaryContainer": "Color(0xFF3A2420)",
}

#: 页面底那四层暖砂白。
SURFACE = {
    "BackgroundLight": "0xFFF7F6F3",
    "SurfaceVariantLight": "0xFFF1EFEA",
    "SurfaceContainer": "0xFFEFECE6",
    "SurfaceContainerHigh": "0xFFE4E0D9",
}

#: 其余**换过值**的 token —— 一个一个钉住。
#:
#: 为什么必须逐个钉（2026-10-10 反向验证抓出来的真窟窿，在本表之前**判据是死的**）：
#: 本单一共换了 **45 个** token 的值，可上面 `SEMANTIC` / `PRIMARY_KIT` / `SURFACE` 只覆盖了
#: 12 个。把 `val MoneyOrange = 0xFFC9855A` 改回旧橙 `0xFFFF9500`，判据**一声不响**
#: —— 界面不会报错、编译不会报错、`ThemePaletteTest` 也没钉它，只是账本那一族悄悄变回旧的。
#: 45 个换一个漏一个，正是本单最容易出的错；所以这张表就是"45 个"这三个字的机器判据。
#:
#: ⚠️ 与 `Color.kt` 一致：正则统一用 `[^\n]*$` 收尾，**别去钉 `\b` 或 `L`**
#:    （那个文件里 token 的写法本来就不一致：有的带 `L`、有的不带、有的写成 `Color(0x…)`）。
IDENTITY = {
    "ThemeGreenDeep": "0xFF6E3636",        # 数量块那档深红棕（CHG-0091 起是 #0E7A50）
    "ProductRowTint": "0xFFF0E2DC",        # 商品行浅底
    "OnProductRowTint": "0xFF3A2420",      # 商品行上的字
    "ProgressYellow": "0xFF8D8340",        # 订单管理 / 派单中
    "MemberGold": "0xFFB98E4A",            # 批发商管理
    "ProductPurple": "0xFFB084CE",         # 商品管理
    "InventoryTeal": "0xFF3F8F81",         # 货主管理
    "MoneyOrange": "0xFFBA6F45",           # 账本管理 / 收款
    "ArrearsTangerine": "0xFFC26357",      # 挂账单位
    "ReportIndigo": "0xFF8075C0",          # 报表中心
    "MessageRed": "0xFFDE7C81",            # 消息中心
    "DriverLime": "0xFF72863F",            # 司机管理
    "OnDriverLime": "0xFF33380F",          # 橄榄底上的字
    "OnArrearsTangerine": "0xFFFFF3EE",    # 砖红底上的字
    "OriginTeal": "0xFF6BA6AE",            # 线路起点
    "DestOrange": "0xFFB98E4A",            # 线路终点（与 MemberGold 同值）
    "CashOut": "0xFF5C7590",               # 支出那档雾蓝
    "QuickPriceGreen": "0xFF678C6E",       # 商品卡「改价」
    "UnitConvRose": "0xFF9C6E8E",          # 单位换算
    "SuccessGreen": "0xFF59A570",          # 成功 / 正常
    "DangerRed": "0xFFB65C4E",             # 危险 / 异常
    "SecondaryContainer": "Color(0xFFE7E3D8)",
    "OnSecondaryContainer": "Color(0xFF33380F)",
    "Tertiary": "Color(0xFFBA6F45)",
    "ErrorLight": "Color(0xFFB65C4E)",
    "ErrorContainerLight": "Color(0xFFF7E4E0)",
    "Success": "Color(0xFF59A570)",
    "OnBackgroundLight": "Color(0xFF2B2724)",
    "OnSurfaceVariantLight": "Color(0xFF4A443E)",
    "SurfaceContainerLow": "Color(0xFFEAE7E1)",
    "OutlineLight": "Color(0xFF8A827B)",
    "OutlineVariantLight": "Color(0xFFD5CFC6)",
}

#: 换色前那些**不许再出现在任何 `ui/**/*.kt` 的代码里**的旧 token 值
#: （由 `_tmp/probe_token_diff.py` 从 `git show HEAD:…/Color.kt` 与工作副本对账生成，40 个）。
#: ⚠️ 与 `Color.kt` 现在任何一个 token 的值都**不重合** —— 这是本表能当红线的前提。
OLD_VALUES = {
    "00A2C7", "00A56E", "00A870", "00A8A8", "00B578", "00BCD4", "0B3D2E", "0B4A32",
    "0E7A50", "10331F", "1565C0", "17181C", "2B1200", "3A3F00", "3B404A", "5B9E74",
    "6950F5", "7A7F8C", "8455E6", "8D6E63", "9C27B0", "CDDC39", "CFD4E0", "D2F2E3",
    "D6F2E4", "E6F7EE", "E9E7E3", "EDEFF4", "EFEEEB", "F3F2EF", "F57F17", "F5A623",
    "FBFBFA", "FF4D4F", "FF5252", "FF6B2C", "FF9500", "FF9F1C", "FFB300", "FFECEC",
    # ⚠️ 下面这三个**不是 `Color.kt` 的 token**，是 `Modules.kt` 里逐格写死的模块身份色
    #    （`_tmp/probe_token_diff.py` 只对账 token，所以它们本来不在表里）。反向验证抓出来的
    #    真窟窿：把「车辆管理」改回 `0xFF48F0F0L` 那个亮青，第 2 节一声不响
    #    —— 因为它压根不在黑名单里。模块身份色也是"换掉的颜色"，同样一处都不许回来。
    "48F0F0",   # 车辆管理（旧的亮青，换成了 #87B7B9 → #4AA6A8）
    "8EC714",   # 计费规则（旧荧光黄绿，换成了 #8E9463 → #939F4E）
    "3949AB",   # 预订单（旧靛蓝，换成了 #617190 → #7A98D8）
    # ⚠️ 下面这 29 个是 **CHG-0101 那一整套**（2026-10-10 CHG-0102 换掉的那批）。
    #    它们是"用户看过之后仍然否掉的一半"：用户 2026-10-10 说
    #    「太灰了一点……我们应该叫做明度。他们并不是完全都是一致的只是在一个区间内」
    #    —— 那套的毛病是同屏彩度差 7 倍（账户管理 C*=8.1 / 消息中心 C*=58.4）。
    #    ⛔ 把其中任何一个改回去，都是把这套配色退回"有的灰有的艳"。
    "567A5F",   # 成功/完成 雾绿 → #59A570
    "6B8FA6",   # 信息 雾蓝 → #529EBF
    "C8B270",   # 订单管理 卡其 → #8D8340
    "9AA35F",   # 司机管理 橄榄 → #72863F
    "6F9A93",   # 货主管理 雾青 → #3F8F81
    "C9A15E",   # 批发商管理 浅金 → #B98E4A（线路终点同值）
    "8A7BB0",   # 商品管理 雾紫 → #B084CE
    "C9855A",   # 账本管理 焦糖 → #BA6F45
    "BE5F4A",   # 挂账单位 砖红 → #C26357
    "7A7CA8",   # 报表中心 雾靛 → #8075C0
    "CA454E",   # 消息中心 砖红 → #DE7C81
    "97897F",   # 账户管理 灰棕 → #A2763D（这就是"最灰那一格"，C* 只有 8.1）
    "617190",   # 预订单 雾靛 → #7A98D8
    "A16A5F",   # 退货申请 砖红 → #D97C65
    "A98F76",   # 发票台账 卡其 → #CF8855
    "6A8F99",   # 库存管理 雾青 → #278A9D
    "87B7B9",   # 车辆管理 浅青 → #4AA6A8
    "7A899D",   # 运费模板 雾蓝灰 → #5387B1
    "8E9463",   # 计费规则 橄榄 → #939F4E
    "CA8658",   # 账本页 订单账 → #C78A4F
    "4D7053",   # 账本页 司机账 → #4A8A4E
    "689780",   # 账本页 货主账 → #5BA592
    "B8860B",   # 账本页 批发商账 → #8A7339
    "7B5AA6",   # 账本页 客户收款 → #9C8AD7
    "416D99",   # 账本页 收支 → #537BC6
    "AD1457",   # 账本页 供应商/应付 → #CB6587
    "C7B270",   # 货主端 我的订单 → #8D7A3C
    "D58539",   # 货主端 我的账本 → #C29750
    "B7766F",   # 货主端 退货申请 → #BC5A58
    "885B90",   # 货主端 下游定价 → #A76BAF
}

#: 例外白名单：`旧值 -> {允许还留在这些文件里}`。
#: 现在**一条都没有** —— 换色时把最后一处（`ui/common/ProductCardKit.kt` 的商品名兜底色
#: `#1565C0`）也一起换掉了。留着这个结构是为了将来真要放行时有地方写、并且要写清理由。
ALLOW_OLD: dict[str, set[str]] = {}

#: 换色后这些值必须**出现过**（用色处的硬编码已经跟着换了的证据）。
NEW_MUST_APPEAR = {
    "59A570": 20,   # 成功/完成 草绿（报表、AI 操作、状态徽标…）
    "C26357": 10,   # 挂账/欠款 陶土红
    "BA6F45": 10,   # 账本/金额 焦糖
    "529EBF": 8,    # 信息 晴蓝
}

#: 换色后这几个大户**一处都不许留**（它们是最刺眼的几个，也是最容易漏的）。
NEW_MUST_GONE = ["FF9500", "00B578", "00A2C7", "FFB300", "00BCD4", "00A8A8",
                 "567A5F", "CA454E", "97897F", "C9855A"]

#: 单测里那个饱和度地板：既拦"发灰"（太低），也不许被抬高（用尺子改设计）。
SAT_FLOOR = "0.15"
SAT_FLOOR_MIN, SAT_FLOOR_MAX = 0.12, 0.20
# 反验脚本的注入条数下限（现在是 52 条）。⛔ 别往下调 —— 那是"这条红线被拆过多少刀"。
MIN_INJECTIONS = 45

#: `SEMANTIC` + `PRIMARY_KIT` + `SURFACE` + `IDENTITY` 至少得钉住这么多换过值的 token。
#: 本单实际换了 **45 个**，四张表合计 44（`OnPrimary` 是纯白、没换，所以是 44 不是 45）。
MIN_PINNED = 40


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
        m = re.search(pattern, text, re.M)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text, re.M)
        self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")

    def section(self, title: str) -> None:
        print(f"\n== {title} ==")


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数，好让行号还对得上）。

    为什么必须这样：本单的"用户原话/为什么"全写在注释里，其中就抄着
    `0xFF00A870`、`#FF9500` 这些**看起来就是代码**的字样 ——
    判据抓的是**代码里**还有没有人在用它，不是"文档里提没提过"。
    """
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


# 文档里"这个值是历史"的标记词。⛔ 这不是放松判据 —— 设计系统**必须**留下沿革
# （不然 CHG-0091 那条"为什么曾经是绿"的来龙去脉就没了，下一个人会以为一直是红棕）；
# 抓的是"旧的**现在时**说明"：一行里写着旧色、却没有任何一个字交代它是过去的。
STALE_MARKERS = ("前是", "旧", "原来是", "换成", "历史", "CHG-009", "CHG-010", "2.9:1", "太亮")


def stale_marked(text: str, values: tuple[str, ...]) -> list[str]:
    """返回"写着旧色、又没交代它是过去"的那些行（`文档:行号 原文`）。"""
    out: list[str] = []
    for ln_no, line in enumerate(text.split("\n"), 1):
        if any(v in line for v in values) and not any(mk in line for mk in STALE_MARKERS):
            out.append(f":{ln_no} {line.strip()[:90]}")
    return out


def hard_colors() -> dict[str, list[str]]:
    """`ui/**/*.kt`（排除 `Color.kt`）代码里出现过的硬编码 ARGB -> 出处列表。"""
    hits: dict[str, list[str]] = {}
    pat = re.compile(r"0xFF([0-9A-Fa-f]{6})")
    for kt in sorted(AND.rglob("*.kt")):
        if kt == COLOR:
            continue
        rel = kt.relative_to(AND).as_posix()
        for ln_no, line in enumerate(code_only(read(kt)).split("\n"), 1):
            for m in pat.finditer(line):
                hits.setdefault(m.group(1).upper(), []).append(f"{rel}:{ln_no}")
    return hits


#: `Modules.kt` 里那几张"图标宫格"表，以及每张表**至少**该有几格。
#: `ledgerHomeEntries` / `shipperEntries` 的 ≥60 由 `ModulesEntryTest` 真量（本单不重复实现），
#: 这里只补它**量不到**的那两件事：① 宫格里不许两格一模一样；② 格子里读的是 token 还是字面量。
MODULE_TABLES = {
    "dispatcherEntries": 19,
    "ledgerHomeEntries": 7,
    "shipperEntries": 8,
    "driverEntries": 2,
}

#: 每张宫格里**裸字面量**的那几格，就是用户图二上量出来的身份色 —— 逐个钉住。
#: ⚠️ 为什么不靠 `NEW_MUST_APPEAR` 的计数下限：`567A5F` 全仓 59 处、下限设 20，
#:    把货主端「下单」那一格改掉计数只掉到 58，**照样过**（反向验证抓出来的 C 类）。
#:    身份色必须"点名到格"，不能只数总数。
#: 用 token 名上色的格子不在这里（它们由 `MODULE_TOKEN_COLORS` 管）。
MODULE_LITERALS = {
    "dispatcherEntries": {
        "7A98D8",  # 预订单
        "D97C65",  # 退货申请
        "A2763D",  # 账户管理
        "CF8855",  # 发票台账
        "278A9D",  # 库存管理
        "4AA6A8",  # 车辆管理
        "5387B1",  # 运费模板
        "939F4E",  # 计费规则
    },
    "ledgerHomeEntries": {
        "C78A4F",  # 订单账
        "4A8A4E",  # 司机账 · 运费结算
        "5BA592",  # 货主账
        "8A7339",  # 批发商账
        "9C8AD7",  # 客户收款
        "537BC6",  # 收支
        "CB6587",  # 供应商 / 应付
    },
    "shipperEntries": {
        "8D7A3C",  # 我的订单
        "59A570",  # 下单
        "529EBF",  # 地址与联系人
        "C29750",  # 我的账本
        "DE7C81",  # 消息中心
        "BC5A58",  # 退货申请
        "A76BAF",  # 下游定价
    },
    "driverEntries": set(),  # 两格都读 token（MgrGreen / MoneyOrange）
}

#: `Modules.kt` 里用 token 名给格子上色的那几个（其余格子是裸字面量）。
#: ⚠️ 只有 token 名对不上字面量时才需要人来看 —— 这是本单"身份色落地"的机器判据。
MODULE_TOKEN_COLORS = {
    "MgrGreen": "59A570",
    "ShipperTeal": "529EBF",
    "ProgressYellow": "8D8340",
    "DriverLime": "72863F",
    "InventoryTeal": "3F8F81",
    "MemberGold": "B98E4A",
    "ProductPurple": "B084CE",
    "MoneyOrange": "BA6F45",
    "ArrearsTangerine": "C26357",
    "MessageRed": "DE7C81",
    "AccountBrown": "A2763D",
    "ReportIndigo": "8075C0",
    # AI 那一格是**品牌色**，用户点名保留（不属于这两单那套低饱和语义色）。
    "AiBlue": "4285F4",
}

def parse_module_tables(text: str) -> dict[str, list[tuple[str, str]]]:
    """`Modules.kt` -> `{表名: [(格子名, 颜色原文), …]}`。

    ⚠️ 这里**故意不用正则**，全部用字符串操作（`find` / `split` / `partition`）。
    表头长这样 —— `    val dispatcherEntries: List<ModuleEntry> = listOf(`，表体是"一行一格"。

    ⛔ **别把表头写成 `"val dispatcherEntries = listOf("`** —— 那行里 `val` 与 `=` 之间还有
    `: List<ModuleEntry>` 这个**类型标注**，所以那个 marker 根本不可能命中（踩过：
    `dispatcherEntries` 数出 0 格，而 `val` / `dispatcherEntries` / `=` / `listOf(` 四个碎片
    单独查全都在）。正确切法是按 **`" = listOf("`** 切，再回头认切出来那截的**最后一个词**
    是不是表名（`"    val dispatcherEntries: List<ModuleEntry>"` -> `ModuleEntry>` 不是表名 ⇒
    再往前取到 `": List<"` 之前的那一段）。

    ⚠️ 另一个坑：`Modules.kt` 是 **CRLF** 行尾（`read()` 会归一成 LF，但探针直接
    `read_bytes().decode()` 时行尾会带 `\r`，`in` 判据会假红）。
    """
    heads: list[tuple[str, int]] = []
    for name in MODULE_TABLES:
        marker = "val " + name
        pos = text.find(marker)
        while pos >= 0:
            # 这个词后面必须紧跟 `:` 或 ` = `（别命中 `val orderTemplatesEntriesX` 之类）
            nxt = text[pos + len(marker):pos + len(marker) + 1]
            after = text[pos + len(marker):pos + len(marker) + 3]
            if nxt == ":" or after == " = ":
                heads.append((name, pos))
                break
            pos = text.find(marker, pos + 1)
    heads.sort(key=lambda h: h[1])

    out: dict[str, list[tuple[str, str]]] = {}
    for i, (name, start) in enumerate(heads):
        # 表的结尾＝下一个**四空格缩进的 `val `**（＝同层下一个属性的声明行）或文件末尾。
        # ⛔ 别只找"下一个**模块表**" —— `driverEntries` 之后还有
        #    `    val ENTRY_CAPABILITY: Map<String, String> = mapOf(` 之类的声明，中间夹着
        #    别的 `ModuleEntry(`（`bottomTabs(role)` 那一带），会把司机端 2 格数成 5 格（踩过）。
        # ⛔ 也**别用 `re.search(r"^    val \w+ = listOf\(", …)`** —— 在这台机器上，带 `\w`
        #    的正则去匹配从这个大文件里切出来的中文串会**恒返回 None**（玩具串上却正常，
        #    原因没查清）。这里一律走字符串操作。
        end = len(text)
        base = start + 1
        for off in range(len(text) - base):
            if text[base + off] != "\n":
                continue
            if text.startswith("    val ", base + off + 1):
                end = base + off
                break
        rows: list[tuple[str, str]] = []
        label = ""
        # ⚠️ 格子有**两种写法**，都得认：
        #   ① 一行一个：`ModuleEntry("挂账单位", Routes.ARREARS_UNITS, …, color = ArrearsTangerine),`
        #   ② 多行具名参数（`报表中心` / `司机账 · 运费结算` 那几格）：
        #      `ModuleEntry(` / `    label = "报表中心",` / `    color = ReportIndigo,  // …` / `),`
        #   一开始只认 ①，`dispatcherEntries` 就数出 18 格（少了「报表中心」那一格）—— 判据会假红。
        for line in text[start:end].split("\n"):
            s = line.strip()
            if s.startswith("ModuleEntry("):
                # 写法①：格子名就在这一行的第一对引号里
                label = ""
                q1 = s.find('"')
                if q1 >= 0:
                    q2 = s.find('"', q1 + 1)
                    if q2 > q1:
                        label = s[q1 + 1:q2]
            elif s.startswith(")"):
                label = ""
                continue
            # 写法②：多行具名参数，格子名在 `label = "…"` 那一行
            if label == "" and 'label = "' in s:
                q1 = s.find('label = "')
                q2 = s.find('"', q1 + 9)
                if q2 > q1:
                    label = s[q1 + 9:q2]
            if "color = " in s:
                _, _, tail = s.partition("color = ")
                cut = len(tail)
                for ch in (")", ",", "/"):
                    j = tail.find(ch)
                    if j >= 0:
                        cut = min(cut, j)
                rows.append((label, tail[:cut].strip()))
                label = ""
        out[name] = rows
    return out


def main() -> int:
    c = Checker()
    color = read(COLOR)
    design = read(DESIGN)
    doc = read(DOC)
    reg = read(REG)
    test = read(TEST)
    kt = sorted(AND.rglob("*.kt"))
    hits = hard_colors()
    total_hard = sum(len(v) for v in hits.values())

    print("== 0. 反空转：扫描本身得是活的 ==")
    c.ok(f"扫到 {len(kt)} 个 .kt（下限 {MIN_KT}）", len(kt) >= MIN_KT)
    c.ok(
        f"扫到 {total_hard} 处硬编码色（宽区间 {HARD_MIN}~{HARD_MAX}）",
        HARD_MIN <= total_hard <= HARD_MAX,
        f"实际 {total_hard} 处、{len(hits)} 种 —— 正则失配或目录搬走都会落到区间外",
    )

    print("\n== 1. Color.kt：七个语义色是用户图里那套，别名关系还在 ==")
    # ⚠️ `Color.kt` 里 token 的写法**不一致**：有的带 `L` 后缀、有的不带、有的写成 `Color(0x…)`。
    #    所以正则收尾统一用 `[^\n]*$`，别去钉 `\b` 或 `L`。
    c.present("ThemeGreen = #8B4A4A（用户图三的「主操作（确认接单）」）", color,
              r"^val ThemeGreen = 0xFF8B4A4A[^\n]*$")
    c.present("NavBlue 是 ThemeGreen 的别名（全仓 16 处引用不改调用点）", color,
              r"^val NavBlue = ThemeGreen\b")
    c.present("InfoBlue 也跟着走（否则表里出现同一个色叫两个名 + 一个孤儿蓝）", color,
              r"^val InfoBlue = ThemeGreen\b")
    for name, want in SEMANTIC.items():
        c.present(f"{name} = {want}", color,
                  r"^val " + name + r" = " + re.escape(want) + r"[^\n]*$")
    for name, want in PRIMARY_KIT.items():
        c.present(f"{name} = {want}", color,
                  r"^val " + name + r" = " + re.escape(want) + r"[^\n]*$")
    for name, want in SURFACE.items():
        c.present(f"{name} = {want}（暖砂白那一层）", color,
                  r"^val " + name + r" = Color\(" + re.escape(want) + r"\)")
    # 其余 32 个换过值的 token —— 一个一个钉（`IDENTITY` 的 KDoc 里写了为什么必须逐个钉）。
    for name, want in IDENTITY.items():
        c.present(f"{name} = {want}", color,
                  r"^val " + name + r" = " + re.escape(want) + r"[^\n]*$")
    # 反空转：覆盖数不许缩水。本单换了 **45 个** token 的值，四张表加起来必须够得着这个量级
    # —— 哪天有人嫌麻烦把 `IDENTITY` 删空，上面这一整个循环会一声不响地变成空转。
    covered = len(SEMANTIC) + len(PRIMARY_KIT) + len(SURFACE) + len(IDENTITY)
    c.ok(
        f"钉住的换值 token 有 {covered} 个（下限 {MIN_PINNED}，本单换了 45 个）",
        covered >= MIN_PINNED,
        "四张表加起来太少 —— 有换过值的 token 没人钉，改回旧值判据不会响",
    )
    # 语义色 token 必须是**裸 ARGB Long**：写成 `Color(0x…)` 会让用色处的类型对不上（实测编译不过）。
    # ⚠️ `NavBlue` / `InfoBlue` 也在这条里：它们是**别名**（`= ThemeGreen`），一旦被谁写成
    #    `Color(0xFF…)`，上面那两条 `^val NavBlue = ThemeGreen` 会红、可这一条如果不收它们，
    #    就漏掉了"别名自己变成另一个色"这条退化路径（全仓 16 处调用点会跟着一起变）。
    c.absent("语义色 token 不是 `Color(0x…)` 形式（写了就编译不过）", color,
             r"^val (?:ThemeGreen|NavBlue|InfoBlue|MgrGreen|ShipperTeal|MessageRed|MoneyOrange"
             r"|ProgressYellow|ReportIndigo|ProductPurple|InventoryTeal|ArrearsTangerine) = Color\(")

    print("\n== 2. 全仓不许再出现旧 token 值（代码里；注释不算） ==")
    left: list[str] = []
    for v, places in sorted(hits.items()):
        if v not in OLD_VALUES:
            continue
        allowed = ALLOW_OLD.get(v, set())
        bad = [p for p in places if p.split(":")[0] not in allowed]
        if bad:
            left.append(f"0xFF{v} ×{len(bad)}（{bad[0]}…）")
    c.ok(
        f"{len(OLD_VALUES)} 个旧 token 值一处都不许留（例外白名单 {len(ALLOW_OLD)} 条）",
        not left,
        "还留着：" + "、".join(left[:6]),
    )
    # ⚠️ 例外白名单本身不许腐烂：写进去的文件必须真的还在用那个值。
    for v, files in ALLOW_OLD.items():
        for f in files:
            c.ok(
                f"例外白名单 {v} 的 {f} 确实还在用它（白名单不许变成死条目）",
                any(p.startswith(f + ":") for p in hits.get(v, [])),
                "那个文件已经不用它了 —— 白名单该删",
            )

    print("\n== 3. 用色处的硬编码已经跟着换（本单最容易漏的那一半） ==")
    for v, least in NEW_MUST_APPEAR.items():
        n = len(hits.get(v, []))
        c.ok(f"新值 0xFF{v} 至少被硬编码 {least} 处（实际 {n}）", n >= least,
             f"只出现 {n} 处 —— 用色处没跟着换？")
    for v in NEW_MUST_GONE:
        got = hits.get(v, [])
        c.ok(f"旧大户 0xFF{v} 一处都不留（实际 {len(got)}）", not got,
             "还留着：" + "、".join(got[:3]))

    print("\n== 3b. Modules.kt 的图标宫格：格子还在、表里不许撞色、token 没被偷换 ==")
    # 为什么要单开一节：`ModulesEntryTest` 只对**账本入口页 7 格**和**货主端**真量 ≥60
    # （`:210` / `:104`），派单端那 21 格它只查"完全同色"（`:91`）。反向验证抓出来的窟窿正是
    # 这一块：把货主端「下单」那格从 `0xFF567A5FL` 改成 `0xFF8B4A4AL`（与主色撞色），
    # 第 3 节那条计数下限（`567A5F` ≥20 而实际 59）一声不响 —— 少一处根本掉不出下限。
    modules = read(MODULES)
    tables = parse_module_tables(modules)
    for tname, least in MODULE_TABLES.items():
        rows = tables.get(tname, [])
        c.ok(
            f"`{tname}` 数到 {len(rows)} 格（至少 {least} 格）",
            len(rows) >= least,
            f"只数到 {len(rows)} 格 —— 表被拆了、或者 `ModuleEntry(` 的写法变了",
        )
    for tname in MODULE_TABLES:
        rows = tables.get(tname, [])
        dup: list[str] = []
        seen: dict[str, str] = {}
        for label, raw in rows:
            key = raw if raw.startswith("0xFF") else f"token:{raw}"
            if key in seen:
                dup.append(f"{seen[key]} / {label} 都是 {raw}")
            seen[key] = label
        c.ok(
            f"`{tname}` 里没有两格用同一个颜色（原文相同就算撞）",
            not dup,
            "撞了：" + "、".join(dup[:3]),
        )
    # 用 token 名上色的那几格：token 自己的值不许被偷换（比如把 `MgrGreen` 当别处用）。
    bad_tok: list[str] = []
    for tname, rows in tables.items():
        for label, raw in rows:
            if raw.startswith("0xFF") or raw.startswith("Color("):
                continue
            name = raw.split("(")[0].strip()
            want = MODULE_TOKEN_COLORS.get(name)
            if want is None:
                bad_tok.append(f"{tname}/{label} 用的是没登记的 token `{raw}`")
                continue
            if not re.search(r"^val " + name + r" = 0xFF" + want, color, re.M):
                bad_tok.append(f"{tname}/{label} 的 `{name}` 在 Color.kt 里不是 #{want}")
    c.ok(
        "宫格里用 token 名上色的格子，读的都是本单那套值",
        not bad_tok,
        "；".join(bad_tok[:4]),
    )
    # 裸字面量那几格＝用户图二量出来的**身份色**，逐个点名（光看总数会漏"逐处退化"）。
    for tname, want_set in MODULE_LITERALS.items():
        rows = tables.get(tname, [])
        got_set = {raw[4:10].upper() for _, raw in rows if raw.startswith("0xFF")}
        missing = sorted(want_set - got_set)
        extra = sorted(got_set - want_set)
        c.ok(
            f"`{tname}` 的 {len(want_set)} 个身份色一个不差"
            + (f"（实际 {len(got_set)} 个）" if extra or missing else ""),
            not missing and not extra,
            ("少了：" + "、".join(missing) if missing else "")
            + ("；多了：" + "、".join(extra) if extra else ""),
        )

    print("\n== 4. 饱和度地板：既拦发灰、也不许被抬高 ==")
    m = re.search(r"^[ \t]*private val SAT_FLOOR = ([\d.]+)", test, re.M)
    c.ok("单测里有 SAT_FLOOR 这个地板", m is not None, "找不到 `private val SAT_FLOOR = …`")
    if m:
        v = float(m.group(1))
        c.ok(
            f"SAT_FLOOR = {v} 落在 {SAT_FLOOR_MIN}~{SAT_FLOOR_MAX}（地板本身有出处）",
            SAT_FLOOR_MIN <= v <= SAT_FLOOR_MAX,
            f"实际 {v} —— 往下调＝放行发灰，往上调＝用尺子改设计"
            "（参考图 21 格实测最低 11%、中位 31%；用户给的就是低饱和色）",
        )
        c.ok(
            "地板的注释里留着「为什么是 15%」的出处（量过三组、不是拍脑袋）",
            "11%" in test and "中位 31%" in test,
            "注释里没有参考图的三档实测值",
        )
    c.present("主操作色上的白字对比度那一条还在（>= 4.5）", test,
              r"ratio >= 4\.5")
    c.present("对比度是按白字算的（1.0 / lum(ThemeGreen)）", test,
              r"\(1\.0 \+ 0\.05\) / \(lum\(ThemeGreen\) \+ 0\.05\)")
    # ⚠️ 这里**不能**钉 `饱和度都不低于 30%`：真方法名是
    #    ``fun `派单端工作台那 21 格，饱和度也都不低于 15%`()``，中间那个「也」字
    #    会让「饱和度」与「都不低于」不相邻 ⇒ 反验把 15% 改成 30% 时这条判据**照样是绿的**
    #    （反向验证抓出来的 E 类死判据）。改成只钉「不低于 N%」这一段，且两头留空档。
    c.absent("单测里没有把「不低于 30%」写回去（那是被推翻的地板）", test,
             r"不低于\s*30\s*%")

    print("\n== 5. 相交判据还在（本单不重复实现，只做交叉引用） ==")
    ledger = read(ROOT / "_tools/qa/_check_ledger_dashboard.py")
    green = read(ROOT / "_tools/qa/_check_green_theme.py")
    warm = read(ROOT / "_tools/qa/_check_warm_surface_palette.py")
    modules_test = read(ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/nav/ModulesEntryTest.kt")
    c.present("账本入口页 7 格那条判据还在（≥60 是它真的在量的两处之一）", ledger,
              r"格配色两两距离 ≥60")
    c.present("主色与商品胶囊那条判据还在", green, r"^GREEN_TOKENS = \{")
    c.present("暖砂白四层那条判据还在", warm, r"^NEAR_WHITE = \{")
    c.present("单测里账本入口页那一条还在（真的量了两两 ≥60）", modules_test,
              r"账本管理入口页 7 格")

    print("\n== 6. 用户口径与文档 ==")
    for ref, word in (("m02474", "按照它的配色方案"), ("m02545", "这是新任务"), ("m02683", "太过于灰")):
        c.present(f"变更单里留了 {ref} 的原话（「{word}」）", doc, re.escape(word))
    for hexv in ("8B4A4A", "B5726B", "567A5F", "C8A56A", "6B7F99", "9B8F88", "F7F6F3"):
        c.present(f"变更单里写着图三的 #{hexv}", doc, re.escape(hexv))
    c.present("设计系统那张语义色总表已经是新主色 #8B4A4A", design, r"#8B4A4A")
    # ⚠️ §6 主题那一行必须**点着名字**写新值：`stale_marked` 那条只能抓"没有沿革交代"的行，
    #    而这条行文里本来就带 `CHG-0101 起`（＝一个沿革标记），所以光靠它抓不住
    #    "把这一行换回旧绿"的注入（反向验证抓出来的）。这里补一条正向点名的。
    c.present("设计系统 §6 主题那一行点着名字写的是新主色（ThemeGreen=**#8B4A4A 深红棕**）",
              design, re.escape("ThemeGreen=**#8B4A4A 深红棕**"))
    c.ok(
        "设计系统里那两个旧值只在「历史沿革」句里出现（前是 / 旧 / 换成 / 原来是 / 历史 / CHG-009x）",
        stale_marked(design, ("#00A870", "#FF9500")) == [],
        "这 %d 行像是一句**现在时**的说明却还写着旧色：%s"
        % (len(stale_marked(design, ("#00A870", "#FF9500"))),
           " ｜ ".join(stale_marked(design, ("#00A870", "#FF9500"))[:2])),
    )
    # ⚠️ §4.25g 的收尾句是本节的**锚**（判据按它找这一节）。`§4.25g` 在文件里出现 3 次
    #    （收尾句里两次 ＋ 标题里没有），只查 `§4\.25g` 会被别的副本撑绿（反向验证抓出来的）。
    c.present("设计系统新增的那一节带收尾锚句（**这一节就是 §4.25g**）", design,
              re.escape("**这一节就是 §4.25g**"))
    c.present("登记簿里有 CHG-0101", reg, r"`CHG-0101`")

    print("\n== 7. 配套：反验脚本与文书 ==")
    c.ok("反验脚本在（它负责把上面每一条分别弄坏一次）", REVERSE.exists(),
         f"找不到 {REVERSE.name}")
    # ⚠️ 只查"文件在不在"是个**空转判据**：把它的注入表掏空、文件照样在。
    #    反向验证抓出来的（D 类）：原先把注入打进 `ME`（判据脚本）而不是反验脚本自己，
    #    于是注入点压根找不到。这里补两条 —— 注入表得在、得够厚。
    if REVERSE.exists():
        rev = read(REVERSE)
        # ⚠️ 必须**带前导换行**找：`CASES: …` 这一行字面在反验脚本自己里出现两次（第 97 行的
        #    真声明 ＋ 那条"把 CASES 表头改掉"的注入串）。不带前导换行的话，注入把真声明
        #    改掉之后，注入串里那份**副本**还会把这条判据继续撑成绿的（反向验证抓出来的）。
        c.present("反验脚本里有注入表 `CASES`（不是个空壳）", rev,
                  r"\nCASES: list\[tuple\[str, str, object, str\]\] = \[")
        n_sub = rev.count("        sub(")
        c.ok(f"注入表够厚（{n_sub} 条 `sub(...)`，下限 {MIN_INJECTIONS}）",
             n_sub >= MIN_INJECTIONS,
             f"只有 {n_sub} 条 —— 掏空注入表等于这条红线从此没人拆")
    # ⚠️ Blast Radius 在变更单里出现两次（文件头 ＋ ⑥ Before/After 那一节），所以判据得
    #    **逐个钉**，不能只查"出现过 `**Blast Radius**：L0`" —— 改掉一处另一处还撑着（反向验证抓出来的）。
    c.present("变更单文件头写着 Blast Radius L0（本单不碰数据、不碰钱）", doc,
              r"^- \*\*Blast Radius\*\*：L0")
    c.present("变更单 ⑥ 那一节的 Blast Radius 也写着 L0", doc,
              r"\*\*Blast Radius\*\*：L0 —— 展示层")

    print(f"\n===== 低饱和配色（CHG-0101）=====")
    if c.fails:
        print(f"❌ {len(c.fails)}/{c.passes + len(c.fails)} 项没通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
