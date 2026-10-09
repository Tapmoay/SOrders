"""反向验证 `_check_low_sat_palette.py`（台账 L-64 / CHG-0101）。

## 这个脚本在防什么

判据脚本最典型的三种失效方式，都不是"跑起来报错"，而是**跑起来全绿**：

1. **判据空转**：清单写的是 `ui/theme/Color.kt`，但那个 token 早被搬走/改名 ——
   `read()` 照样读得到文件、正则照样在别处命中，于是"通过"。本脚本把源码**真的改坏一次**，
   看它到底会不会变红；不会变红，就说明那条判据其实什么也没在检查。
2. **只认名字不认形状**：写 `c.present("主色是红的", color, r"BA6F45")` ——
   文件里任何一处（哪怕是一句注释、另一个 token 的注释）带这几个字符都算过。
   所以下面每一条注入都是**语义上真的退化了**（色值退回旧绿 / 21 格里又冒出旧亮青 /
   地板被抬到用户嫌灰的那一档 / 例外白名单里塞进一个死人），而不是改个无关变量名。
3. **口径被单方面改掉**：用户 2026-10-10 说的「按照它的配色方案进行一下修改」与
   「我不希望整体太过于灰啊」是**原话**，`SAT_FLOOR = 0.15` 那条线是从参考图**量出来**的
   （最低 11% / 中位 31%）。哪天有人把出处注释删了、或者把地板抬到 22%/30%，
   判据第 4 节必须红 —— 这里就注入"删掉出处"和"把地板抬上去"。

## R4-BOUNDARY-JUSTIFICATION: 为什么这里不能靠编译或单测

下面这些注入里**没有一条**能让 `gradle` 或 `ThemePaletteTest` 变红：

- 把某个 token 的色值从 `#8B4A4A` 改回 `#00A870` —— 合法 Kotlin，Compose 照画；
  `ThemePaletteTest` 只钉了 `ThemeGreen` 那**一个** token，`MgrGreen` / `ShipperTeal` /
  `WarningAmber` 这些改回旧色它**一声不响**。而那正是本单最容易出的错：
  45 个 token 换值，漏一个不会有任何东西报错，只是屏幕上有两块颜色一旧一新。
- 往 `ui/nav/Modules.kt` 的某一格里塞回旧亮青 `0xFF00BCD4L` —— 编译过、跑得动；
  21 格的"两两距离"根本不量这一组（`ModulesEntryTest` 只量账本入口页 7 格与货主端 8 格），
  而饱和度地板是 15%，旧亮青的饱和度很高、**照样过**。于是它只能靠本单第 2 节那条
  "40 个旧值一处都不许留"来守 —— 那条是活的还是死的，只能靠这里注入来证明。
- 往 `ALLOW_OLD` 白名单里塞一个没人再用的值 —— 判据不会红（它只会更"宽松"）。
  所以第 2 节末尾专门有一条"白名单不许变成死条目"，下面有一条注入专门打它。

类型系统能表达"这里要一个 Long"，表达不了"这个 Long 必须是用户画的那个色"。
色值是**数据**，不是形状；能在数据上守的那一半交给 `ThemePaletteTest`（它跑得动 Android 的
资源与 `Modules` 对象），另一半（跨文件、跨 45 个 token、跨 21 格、以及"地板不许被抬高"）
只能靠这里的注入来证明判据活着。

## 怎么保证不伤到工作区

只读写本仓库工作区里的文件，**不编译、不跑 UI、不连网**。
每个被注入的文件在动手前按**字节**快照，每条注入跑完**立刻**还原，
`try/finally` 兜底（CRLF/LF 差别也还原回去），最后再逐字节核对一遍、
并重跑一次判据确认"还原之后仍然是绿的"。

用法：python _tools/qa/_reverse_verify_low_sat_palette.py
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_low_sat_palette.py"

#: 被注入的四个文件（相对仓库根，路径与判据脚本里的常量一一对应）。
COLOR = "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Color.kt"
MODULES = "android/app/src/main/java/com/tapmoay/sorders/ui/nav/Modules.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ui/theme/ThemePaletteTest.kt"
DOC = "docs/changes/CHG-0101.md"
REG = "docs/changes/README.md"
DESIGN = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = "_tools/qa/_reverse_verify_low_sat_palette.py"
ME = "_tools/qa/_check_low_sat_palette.py"


def sub(old: str, new: str, idx: int = 0, expect: int | None = None):
    """造一个"把这处改坏"的函数；找不到就说清楚是哪一处，别静默跳过。

    `idx`：改**第几处**命中（0 起）。为什么需要它（2026-10-09 CHG-0095 实测的坑）：
    `str.replace(old, new, 1)` 认的是**第一处子串**，而 `old` 常常会**被更长的行包含** ——
    于是"注入到第 1645 行"其实改的是第 745 行。**判据照样绿，你还以为红线守住了。**

    `expect`：命中次数必须**正好等于**这个数（默认不检查）。
    """

    def f(t: str) -> str:
        n = t.count(old)
        if n == 0:
            raise AssertionError("注入点不在了：" + repr(old[:80]))
        if expect is not None and n != expect:
            raise AssertionError(
                "注入点命中 %d 处，本行钉的是 %d 处：%r" % (n, expect, old[:80])
            )
        if not 0 <= idx < n:
            raise AssertionError("idx=%d 越界（只有 %d 处）：%r" % (idx, n, old[:80]))
        pos = -1
        for _ in range(idx + 1):
            pos = t.index(old, pos + 1)
        return t[:pos] + new + t[pos + len(old):]

    return f


def sub_all(old: str, new: str, least: int = 2):
    """造一个"把**所有**命中都改坏"的函数。

    为什么需要它（2026-10-09 反向验证抓出来的第 45 条）：判据问的是"变更单里写着图三的 `#B5726B`"，
    而 `#B5726B` 在变更单里**合法地出现两次**（① 用户口径那段 ＋ ⑥ After 段）。只改第一处的话，
    第二处照样把判据撑成绿的 —— 于是"这条注入证明不了这条判据"。

    `least`：命中次数必须**不少于**这个数（少于就说明注入点已经腐烂，得先去看判据还在不在）。
    """

    def f(t: str) -> str:
        n = t.count(old)
        if n < least:
            raise AssertionError(
                "注入点只命中 %d 处（本行至少要 %d 处）：%r" % (n, least, old[:80])
            )
        return t.replace(old, new)

    return f


#: (说明, 相对路径, 注入函数, 期望在红线输出里出现的关键词)
CASES: list[tuple[str, str, object, str]] = [
    # ---- 1. Color.kt：45 个 token 换值，漏一个不会有任何东西报错 ----
    (
        "主操作色退回 CHG-0091 那个绿（白字对比度当场从 6.61:1 掉回 2.9:1）",
        COLOR,
        sub("val ThemeGreen = 0xFF8B4A4A", "val ThemeGreen = 0xFF00A870"),
        "ThemeGreen = #8B4A4A",
    ),
    (
        "别名 NavBlue 不再指向主操作色（全仓 16 处调用点会跟着变）",
        COLOR,
        sub("val NavBlue = ThemeGreen", "val NavBlue = 0xFF1E6FFF"),
        "NavBlue 是 ThemeGreen 的别名",
    ),
    (
        "别名 InfoBlue 不再是主色的别名（同一个色又出现两个名字）",
        COLOR,
        sub("val InfoBlue = ThemeGreen", "val InfoBlue = Color(0xFF1E6FFF)"),
        "InfoBlue 也跟着走",
    ),
    (
        "别名被写成 `Color(0x…)`（用色处类型对不上，实测编译不过）",
        COLOR,
        sub("val NavBlue = ThemeGreen", "val NavBlue = Color(0xFF8B4A4A)"),
        "语义色 token 不是 `Color(0x…)` 形式",
    ),
    (
        "成功色退回旧的值",
        COLOR,
        sub("val MgrGreen = 0xFF59A570", "val MgrGreen = 0xFF00B578"),
        "MgrGreen = 0xFF59A570",
    ),
    (
        "客服/货主那格的 token 退回旧色",
        COLOR,
        sub("val ShipperTeal = 0xFF529EBF", "val ShipperTeal = 0xFF00A2C7"),
        "ShipperTeal = 0xFF529EBF",
    ),
    (
        "账本色退回旧橙（判据里那个 40 值黑名单的一员）",
        COLOR,
        sub("val MoneyOrange = 0xFFBA6F45", "val MoneyOrange = 0xFFFF9500"),
        "MoneyOrange = 0xFFBA6F45",
    ),
    (
        "提醒色退回旧琥珀",
        COLOR,
        sub("val WarningAmber = 0xFFC8A56A", "val WarningAmber = 0xFFFF9F1C"),
        "WarningAmber = 0xFFC8A56A",
    ),
    (
        "账本入口页卡其那格退回旧黄（那 40 个旧值之一）",
        COLOR,
        sub("val ProgressYellow = 0xFF8D8340", "val ProgressYellow = 0xFFFFB300"),
        "ProgressYellow = 0xFF8D8340",
    ),
    (
        "消息红退回旧的红",
        COLOR,
        sub("val MessageRed = 0xFFDE7C81", "val MessageRed = 0xFFFF4D4F"),
        "MessageRed = 0xFFDE7C81",
    ),
    (
        "账户管理那格退回旧棕（参考图最灰那格，但那是用户自己画的值）",
        COLOR,
        sub("val AccountBrown = 0xFFA2763D", "val AccountBrown = 0xFF8D6E63"),
        "AccountBrown = 0xFFA2763D",
    ),
    (
        "商品行底色退回 CHG-0091 那个极浅绿",
        COLOR,
        sub("val ProductRowTint = 0xFFF0E2DCL", "val ProductRowTint = 0xFFE6F7EEL"),
        "ProductRowTint = 0xFFF0E2DC",
    ),
    (
        "商品行上的字退回墨绿",
        COLOR,
        sub("val OnProductRowTint = 0xFF3A2420L", "val OnProductRowTint = 0xFF10331FL"),
        "OnProductRowTint = 0xFF3A2420",
    ),
    (
        "数量块那档深色退回 CHG-0091 的深绿",
        COLOR,
        sub("val ThemeGreenDeep = 0xFF6E3636L", "val ThemeGreenDeep = 0xFF0E7A50L"),
        "ThemeGreenDeep = 0xFF6E3636",
    ),
    (
        "危险红退回旧的亮红",
        COLOR,
        sub("val DangerRed = 0xFFB65C4E", "val DangerRed = 0xFFFF5252"),
        "DangerRed = 0xFFB65C4E",
    ),
    (
        "线路起点退回旧亮青",
        COLOR,
        sub("val OriginTeal = 0xFF6BA6AEL", "val OriginTeal = 0xFF00BCD4L"),
        "OriginTeal = 0xFF6BA6AE",
    ),
    (
        "线路终点退回旧金",
        COLOR,
        sub("val DestOrange = 0xFFB98E4A", "val DestOrange = 0xFFF5A623"),
        "DestOrange = 0xFFB98E4A",
    ),
    (
        "支出那档退回旧蓝",
        COLOR,
        sub("val CashOut = 0xFF5C7590L", "val CashOut = 0xFF1565C0L"),
        "CashOut = 0xFF5C7590",
    ),
    # ---- 2. 主题四件套与背景分层 ----
    (
        "主按钮底色退回绿的（`Primary` 跟 `ThemeGreen` 是两处，漏一处只有一半界面换色）",
        COLOR,
        sub("val Primary = Color(0xFF8B4A4A)", "val Primary = Color(0xFF00A870)"),
        "Primary = Color(0xFF8B4A4A)",
    ),
    (
        "主色上的字那一档没跟着换",
        COLOR,
        sub("val OnPrimaryContainer = Color(0xFF3A2420)", "val OnPrimaryContainer = Color(0xFF0B4A32)"),
        "OnPrimaryContainer = Color(0xFF3A2420)",
    ),
    (
        "商品胶囊底那一档没跟着换",
        COLOR,
        sub("val PrimaryContainer = Color(0xFFF0E2DC)", "val PrimaryContainer = Color(0xFFD6F2E4)"),
        "PrimaryContainer = Color(0xFFF0E2DC)",
    ),
    (
        "次级容器退回 CHG-0091 那个浅绿",
        COLOR,
        sub("val SecondaryContainer = Color(0xFFE7E3D8)", "val SecondaryContainer = Color(0xFFD2F2E3)"),
        "SecondaryContainer = Color(0xFFE7E3D8)",
    ),
    (
        "强调色（账本/收款）退回旧橙",
        COLOR,
        sub("val Tertiary = Color(0xFFBA6F45)", "val Tertiary = Color(0xFFF57F17)"),
        "Tertiary = Color(0xFFBA6F45)",
    ),
    (
        "错误色退回旧的红",
        COLOR,
        sub("val ErrorLight = Color(0xFFB65C4E)", "val ErrorLight = Color(0xFFFF4D4F)"),
        "ErrorLight = Color(0xFFB65C4E)",
    ),
    (
        "页面底退回 CHG-0091 那个冷白（暖砂白那四层是用户图三的「背景」 #F7F6F3）",
        COLOR,
        sub("val BackgroundLight = Color(0xFFF7F6F3)", "val BackgroundLight = Color(0xFFFBFBFA)"),
        "BackgroundLight = Color(0xFFF7F6F3)",
    ),
    (
        "卡片层退回旧的那一档",
        COLOR,
        sub("val SurfaceContainerHigh = Color(0xFFE4E0D9)", "val SurfaceContainerHigh = Color(0xFFE9E7E3)"),
        "SurfaceContainerHigh = Color(0xFFE4E0D9)",
    ),
    # ---- 3. Modules.kt：21 格里的裸字面量 ----
    (
        "派单端某一格又冒出旧亮青（那一组不量两两距离，只有「旧值一处不留」能拦住）",
        MODULES,
        sub('color = 0xFF4AA6A8L),', 'color = 0xFF48F0F0L),', expect=1),
        "个旧 token 值一处都不许留",
    ),
    (
        "货主端某一格也退回旧亮青",
        MODULES,
        sub('color = 0xFFBC5A58L),', 'color = 0xFF00BCD4L),', expect=1),
        "个旧 token 值一处都不许留",
    ),
    (
        "账本入口页首格退回旧橙（那 7 格真的量两两距离，旧橙也会一起把距离挤坏）",
        MODULES,
        sub('color = 0xFFC78A4FL),', 'color = 0xFFFF9500L),', expect=1),
        "个旧 token 值一处都不许留",
    ),
    (
        "派单端某一格退回旧黄绿",
        MODULES,
        sub('color = 0xFF939F4EL),', 'color = 0xFF8EC714L),', expect=1),
        "个旧 token 值一处都不许留",
    ),
    (
        "货主端「下单」那格被换成跟主色一样的值（两格撞色，饱和度量不出来）",
        MODULES,
        sub('color = 0xFF59A570L),', 'color = 0xFF8B4A4AL),', expect=1),
        "新值 0xFF59A570 至少被硬编码",
    ),
    # ---- 4. 地板：m02683「不要太灰」那条线的出处与上下界 ----
    (
        "地板被抬到用户嫌灰的那一档（30%）—— 那就是「用尺子改设计」",
        TEST,
        sub("private val SAT_FLOOR = 0.15", "private val SAT_FLOOR = 0.30"),
        "SAT_FLOOR = 0.3 落在 0.12~0.2",
    ),
    (
        "地板被抬到 22%（实测：这一档「账户管理」#A2763D 当场判红）",
        TEST,
        sub("private val SAT_FLOOR = 0.15", "private val SAT_FLOOR = 0.22"),
        "SAT_FLOOR = 0.22 落在 0.12~0.2",
    ),
    (
        "地板被往下调到 0.10（放行发灰，用户否过一次的那一档）",
        TEST,
        sub("private val SAT_FLOOR = 0.15", "private val SAT_FLOOR = 0.10"),
        "SAT_FLOOR = 0.1 落在 0.12~0.2",
    ),
    (
        "地板的出处注释被删掉（那条线就成了拍脑袋的数字）",
        TEST,
        sub("最低 11% / 中位 31% / 最高 52%", "三个数字"),
        "地板的注释里留着",
    ),
    (
        "对比度那条被放松（白字压在主色上读不清也是「不报错」的）",
        TEST,
        sub("ratio >= 4.5", "ratio >= 2.0"),
        "白字对比度那一条还在",
    ),
    (
        "对比度那行不是按白字算的（换成了别的基准）",
        TEST,
        sub("(1.0 + 0.05) / (lum(ThemeGreen) + 0.05)", "(1.0 + 0.05) / (lum(OnPrimary) + 0.05)"),
        "对比度是按白字算的",
    ),
    (
        "被推翻的「不低于 30%」又被写回单测里",
        TEST,
        sub(
            "fun `派单端工作台那 21 格，饱和度也都不低于 15%`() {",
            "fun `派单端工作台那 21 格，饱和度也都不低于 30%`() {",
        ),
        "没有把「不低于 30%」写回去",
    ),
    # ---- 5. 例外白名单：只增不减的东西最容易腐烂 ----
    (
        "白名单里塞进一个没人在用的值（死人条目：看上去有例外，其实已经不受保护）",
        ME,
        sub("ALLOW_OLD: dict[str, set[str]] = {}", 'ALLOW_OLD: dict[str, set[str]] = {"00A870": {"ui/common/Components.kt"}}'),
        "例外白名单 00A870 的 ui/common/Components.kt 确实还在用它",
    ),
    # ---- 6. 相交判据：本单不允许把别人量过的线绕过去 ----
    (
        "账本入口页那条两两 ≥60 的判据被搬走（本单只剩交叉引用，没有第二份实现）",
        "_tools/qa/_check_ledger_dashboard.py",
        sub("格配色两两距离 ≥60", "格配色分开一点"),
        "账本入口页 7 格那条判据还在",
    ),
    (
        "「主色与商品胶囊」那条判据被搬走",
        "_tools/qa/_check_green_theme.py",
        # ⚠️ 判据脚本里的锚点是**行首无缩进**的 `GREEN_TOKENS = {`。注入串要按**字面**找，
        #    所以不能把 `^` 写进来（`sub` 是 `str.replace`，不认正则）—— 用两侧换行夹住它。
        sub("\nGREEN_TOKENS = {\n", "\nGREENISH = {\n", expect=1),
        "主色与商品胶囊那条判据还在",
    ),
    (
        "暖砂白四层那条判据被搬走",
        "_tools/qa/_check_warm_surface_palette.py",
        sub("\nNEAR_WHITE = {\n", "\nLIGHTISH = {\n", expect=1),
        "暖砂白四层那条判据还在",
    ),
    (
        "单测里真的量两两距离那一条被改名（判据只按名字找它）",
        "android/app/src/test/java/com/tapmoay/sorders/ui/nav/ModulesEntryTest.kt",
        sub("账本管理入口页 7 格两两颜色分得开", "账本管理入口页那 7 格的取色"),
        "单测里账本入口页那一条还在",
    ),
    # ---- 7. 用户口径与文书 ----
    (
        "变更单里用户那句「不要太灰」被删掉（本单最硬的约束就没了出处）",
        DOC,
        sub("我不希望整体太过于灰", "整体还行吧"),
        "变更单里留了 m02683 的原话",
    ),
    (
        "变更单里用户给的那套语义色被删掉一个（图三七个色是一组）",
        DOC,
        # ⚠️ `#B5726B` 在变更单里出现**两次**（①「他要的是…」那段 ＋ ⑥ After 段），
        #    只改第一处的话第二处照样把判据撑绿 ⇒ 必须**两处都改**（`sub_all`）。
        sub_all("#B5726B", "#B5726C", least=2),
        "变更单里写着图三的 #B5726B",
    ),
    (
        "变更单里连用户的原话 ref 都删了",
        DOC,
        sub("按照它的配色方案进行一下修改", "按要求改一下"),
        "变更单里留了 m02474 的原话",
    ),
    (
        "登记簿里的 CHG-0101 那一行被删掉（目录与登记簿必须一一对应）",
        REG,
        sub("| `CHG-0101` | CHG |", "| （待补） | CHG |"),
        "登记簿里有 CHG-0101",
    ),
    (
        "设计系统里那句「这一节就是 §4.25g」被删掉（判据按这段锚它）",
        DESIGN,
        sub("**这一节就是 §4.25g**", "**本节完**"),
        "设计系统里新增了 §4.25g",
    ),
    (
        "设计系统里旧绿被写成了一句**现在时**的说明（沿革句里出现是对的，现在是错的）",
        DESIGN,
        sub("ThemeGreen=**#8B4A4A 深红棕**（CHG-0101 起", "ThemeGreen=**#00A870 深绿**（旧版"),
        "设计系统里那两个旧值只在",
    ),
    (
        "设计系统里新主色被整个删掉（那张表还是旧的绿）",
        DESIGN,
        # ⚠️ `06_DESIGN_SYSTEM.md:26` 那一行是**两格一行、且没有反引号**：
        #    `| 派单作业 / 主操作 | 深红棕 #8B4A4A | NavBlue || 代理下单 / 已完成 | 雾绿 #59A570 | MgrGreen |`
        sub("| 派单作业 / 主操作 | 深红棕 #8B4A4A |",
            "| 派单作业 / 主操作 | 深绿 #00A870（尚未换） |"),
        "设计系统那张语义色总表已经是新主色 #8B4A4A",
    ),
    (
        "变更单的 Blast Radius 被改大（本单不碰数据、不碰钱）",
        DOC,
        sub("**Blast Radius**：L0", "**Blast Radius**：L2"),
        "变更单的 Blast Radius 写着 L0",
    ),
    (
        "反验脚本自己不见了（这条红线从此没人拆过）",
        REVERSE,
        # ⚠️ 目标是**反验脚本自己**（`REVERSE`），不是判据脚本（`ME`）—— 判据第 7 节查的是
        #    「`_reverse_verify_low_sat_palette.py` 在不在」＋「注入表够不够厚」。原先误写成 `ME`，
        #    而判据脚本里压根没有 `CASES: …` 这一行 ⇒ 注入点直接找不到（反向验证抓出来的 D 类）。
        # ⚠️ `expect=2`：这一行字面在**本脚本自己**里出现了两次（第 97 行的真声明 ＋ 本行的注入串），
        #    而 `replace(old, new, 1)` 命中的是第一处（真声明），正是要改的那一处。
        sub("CASES: list[tuple[str, str, object, str]] = [", "CASES = []\n_OLD = [", expect=2),
        "反验脚本里有注入表",
    ),
]


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    print("== 0. 先确认源码完好时判据是绿的（否则下面的注入说明不了任何事） ==")
    rc, out = run_check()
    if rc != 0:
        print(out)
        print("  [FAIL] 源码本来就红的 —— 先把 `_check_low_sat_palette.py` 修绿再跑本脚本")
        return 1
    print("  [OK]   源码完好时判据全绿（%d 条注入才有意义）" % len(CASES))

    paths = sorted({c[1] for c in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in paths}

    bad: list[str] = []
    try:
        for i, (label, rel, mutate, keyword) in enumerate(CASES, 1):
            raw = originals[rel]
            crlf = b"\r\n" in raw
            text = raw.decode("utf-8").replace("\r\n", "\n")
            try:
                mutated = mutate(text)  # type: ignore[operator]
            except AssertionError as e:
                bad.append("第 %d 条（注入点找不到）：%s" % (i, e))
                print("  [FAIL] %d. %s —— %s" % (i, label, e))
                continue
            blob = mutated.encode("utf-8")
            if crlf:
                blob = blob.replace(b"\n", b"\r\n")
            (ROOT / rel).write_bytes(blob)

            rc, out = run_check()
            (ROOT / rel).write_bytes(raw)  # 立刻还原，别让下一次注入叠在上一次上

            hit_red = rc != 0
            hit_kw = keyword in out
            # 关键词对不上时退一步：**确认这一条注入确实踩红了某条判据**（输出里有 `[FAIL]`）。
            # 为什么要这条退路（2026-10-09 CHG-0095 实测）：一处注入常常**同时踩红好几条**判据
            # —— 此时红线是红的、也确实为这条注入而红，只是顶在最前面的那条不是 CASES 里
            # 写的那一句。仍然**不放过**"判据还是绿的"。
            hit_any_fail = "[FAIL]" in out
            if hit_red and (hit_kw or hit_any_fail):
                if hit_kw:
                    print("  [OK]   %d. %s" % (i, label))
                else:
                    print("  [OK]   %d. %s（判据红了；顶在最前面那条不是本行写的那一句）" % (i, label))
            else:
                why = []
                if not hit_red:
                    why.append("判据还是绿的（这条判据其实是死的）")
                if not hit_kw:
                    why.append("红了但不是这一条（没出现 %r）" % keyword)
                bad.append("第 %d 条：%s —— %s" % (i, label, "；".join(why)))
                print("  [FAIL] %d. %s —— %s" % (i, label, "；".join(why)))
    finally:
        for rel, raw in originals.items():
            (ROOT / rel).write_bytes(raw)

    print("\n== 还原检查 ==")
    dirty = [rel for rel, raw in originals.items() if (ROOT / rel).read_bytes() != raw]
    if dirty:
        bad.append("还原不干净：" + " / ".join(dirty))
        print("  [FAIL] 这些文件没还原回去：" + " / ".join(dirty))
    else:
        print("  [OK]   %d 个被注入的文件逐字节一致" % len(originals))

    print("\n== 收尾：还原之后判据仍是绿的 ==")
    rc, out = run_check()
    if rc != 0:
        print(out)
        bad.append("还原之后判据变红了 —— 说明有注入没还干净")
        print("  [FAIL] 还原之后判据不是绿的")
    else:
        print("  [OK]   还原之后判据全绿")

    print("\n" + "=" * 60)
    if bad:
        print("❌ %d/%d 条注入没有被判据抓住：" % (len(bad), len(CASES)))
        for b in bad:
            print("   - " + b)
        return 1
    print("✅ %d 条注入都证明这条红线真的在检查。" % len(CASES))
    print("   45 个 token、21 格模块色、40 个旧值、15% 地板 —— 弄坏任何一处，判据都会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
