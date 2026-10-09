"""AI 设置页的「能力说明」默认折起来（台账 L-63 / CHG-0098）—— 用户第三次点名的那一处。

## 用户要的是什么（2026-10-09，ref m01649）
用户发来「AI 设置」页截图（那张卡大半屏都是「能查：…」「能改：…」），语音转写逐字：
    顺便把这个做一个折叠和隐藏啊，他那些详情的解释啊，不然太长了很占位子。
⇒ 两条主张：① **默认折叠**（"占位子"指的就是它）；② **不是删掉**（"折叠和隐藏"＝点一下还能看全）。

## 为什么这条必须有机器的判据（每一处坏了都不报错、不崩、单测也不会红）
1. **默认值一改就全摊开**：`mutableStateOf(false)` → `mutableStateOf(true)`，编译、运行、
   全量单测都照样绿，只是用户抱怨的那一屏又回来了。
2. **折叠只是"看着像"**：`if (capacityExpanded)` 那层壳被删掉，标题行照样画、正文也照样画 ——
   整块变成一个"点不动的展开条"，谁都不会报错。
3. **点不开**：那一行的 `clickable` 被去掉（或挪到只有 chevron 那一小块），折叠块就成了死块。
4. **滚动一趟就丢状态**：这一页是整列 `verticalScroll`；`rememberSaveable` 被换回 `remember`，
   展开态在滚动/转屏后丢失 —— 没有异常、没有日志。
5. **标题不再说人话**：四档文案（收起 / 认不出角色 / 一项能改的都没有 / 报数）任何一档被删、
   顺序调反、或写成光秃秃的「展开」，用户点开之前唯一的线索就没了；它是纯函数，改错也没有别的判据会喊。
6. **数字变成手写的**：标题行里的"能查 N 项"只要不是在数那段话，就会跟真实能力走散 ——
   这一页已经因此错过一次（批量调价 v3.21 上线了，这页还写着「改价做不了」）。
7. **把隐私那句一起折了**：`API Key 加密存在本机、不上传；费用你自己承担。` 是这一页
   **最该常显**的一句（CHG-0031 用户点名），它要是被卷进 `if (expanded)` 里，
   折叠态那一格就只剩一个标题 —— 用户最关心的信息反而要"点开才看得到"。
8. **顺手把能力声明本身删了**：那段话同时是模型的 system prompt（`brief()` 读同一处）。
   为了"省地方"改窄它，模型会跟着一起否认自己的能力（v3.7 实测踩过，见 §19.6）。
9. **判据自己空转**：清单指向不存在的文件、反验脚本失踪、CHG 文档缺节、登记簿 / 工作声明被改名。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
上面这些**没有一条是类型属性**：`true` 与 `false` 同型，`remember` 与 `rememberSaveable` 同型，
`if (expanded) { … }` 删掉一层壳仍然合法；「默认折叠 / 那一行可点 / 滚动记得住 / 隐私那句常显」
是**行为**，类型系统与单测都拦不住（本单新增的单测只钉标题文案与计数，钉不住 Compose 的那四件事）。
所以判据只能落在源码结构上，再配反向验证 `_reverse_verify_ai_settings_fold.py`（逐条弄坏一次，
看它真的变红）。

静默空转保护：MIN_KT = 100（目录被搬走 / 一个 .kt 都没扫到也必须红）。

## 判据
1. `ai/AiCapabilitySummary.kt`：`capabilitySummaryCounts` 从那段话里**数**（不手写），
   `capabilitySummaryLabel` 四档逐字、顺序是 **展开 > 认不出 > 全 0 > 报数**；
2. `ui/ai/AiSettingsScreen.kt`：默认 `false` + `rememberSaveable`、那一行整行 `clickable`、
   正文只在 `if (capacityExpanded)` 里画、标题来自纯函数、chevron 在标题行右端；
3. **隐私那句在折叠之外**（`if` 只包住能力清单那一块）；
4. 能力声明**一个字没删**：`AiRolePrompt.settingsSummary` 仍是唯一来源，仍带 `actor` 与 `readModules`；
5. 单测 `AiCapabilitySummaryTest` 钉住报数、收起、认不出角色、全 0、兜底话不数成 1 项；
6. 文书齐（`CHG-0098.md` 九节 ＋ 登记簿 ＋ 工作声明 ＋ 设计系统 §4.25f）＋ 反验脚本在。

用法：python _tools/qa/_check_ai_settings_fold.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
AI_DIR = AND / "ui/ai"
SETTINGS = AI_DIR / "AiSettingsScreen.kt"
CARD = AND / "ai/AiCapabilitySummary.kt"
PROMPT = AND / "ai/AiRolePrompt.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiCapabilitySummaryTest.kt"
DOC = ROOT / "docs/changes/CHG-0098.md"
REG = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_ai_settings_fold.py"

#: 全仓至少要有这么多 .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_KT = 100

#: 用户点名要常显的那一句（CHG-0031）—— 它**不许**被卷进 `if (capacityExpanded)` 里。
PRIVACY = '"API Key 加密存在本机、不上传；费用你自己承担。"'

#: 变更单九节的标题（逐字照 _TEMPLATE.md）。
SECTIONS = [
    "## ① 六问",
    "## ② Must Change / Must Not Change",
    "## ③ Boundary（Core / Extension / Infrastructure / Presentation）",
    "## ④ Behavior Contract",
    "## ⑤ Data Contract",
    "## ⑥ CHG 专章",
    "## ⑦ 测试（四件事都要，缺一件就不算完整）",
    "## ⑧ 证据",
    "## ⑨ 关闭（六格）",
]


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + label)
        else:
            self.fails.append(label + (" —— " + detail if detail else ""))
            print("  [FAIL] " + label + (" —— " + detail if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text, re.M)
        self.ok(label, m is not None, "没找到 " + repr(pattern))

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text, re.M)
        self.ok(label, m is None, "命中：" + repr(m.group(0)) if m else "")


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数，好让行号还对得上）。

    为什么要这样：本单的"用户原话"就抄在注释里，里面写着「折叠」「隐藏」这些
    **看起来像代码判据**的字样 —— 判据要抓的是**代码里**还有没有那几件事。
    """
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit("找不到文件：" + str(p) + "（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def main() -> int:
    c = Checker()
    screen = read(SETTINGS)
    card = read(CARD)
    prompt = read(PROMPT)
    test = read(TEST)
    screen_code = code_only(screen)
    card_code = code_only(card)

    kt = sorted(AND.rglob("*.kt"))

    print("== 0. 反空转：扫描本身得是活的 ==")
    c.ok("扫到 %d 个 .kt（下限 %d）" % (len(kt), MIN_KT), len(kt) >= MIN_KT)
    names = {p.name for p in kt}
    c.ok("扫到设置页那个 .kt", SETTINGS.name in names)
    c.ok("扫到能力计数那个 .kt", CARD.name in names)

    print("\n== 1. 计数与标题：一个纯函数管四档，顺序是 展开 > 认不出 > 全 0 > 报数 ==")
    c.present(
        "签名与四档逐字（顺序也在这一条里钉住：展开时那句说的是“点下去会发生什么”）",
        card_code,
        r"internal fun capabilitySummaryLabel\(counts: AiCapabilitySummary, expanded: Boolean\): String = when \{\s*\n"
        r'\s*expanded -> "收起清单"\s*\n'
        r'\s*!counts\.canWriteKnown -> "能做什么（点开看清单）"\s*\n'
        r'\s*counts\.canRead <= 0 && counts\.canWrite <= 0 -> "能做什么（点开看清单）"\s*\n'
        r'\s*counts\.canWrite <= 0 -> "能查 \$\{counts\.canRead\} 项（点开看清单）"\s*\n'
        r'\s*else -> "能查 \$\{counts\.canRead\} 项 · 能改 \$\{counts\.canWrite\} 项（点开看清单）"\s*\n\}',
    )
    c.absent(
        "⛔ 标题不许退化成光秃秃的「展开」（那等于把“有多少东西”一起藏了）",
        card_code,
        r'-> "展开"',
    )
    c.absent(
        "⛔ 一项能改的都没有时不许报「能改 0 项」（“看起来有、其实没有”是红线）",
        card_code,
        r'能改 0 项',
    )
    c.present(
        "计数是从那段话里数出来的（先找「能改」那一行，再按「、」数）",
        card_code,
        r"val line = summary\.lineSequence\(\)\.firstOrNull \{ it\.startsWith\(\"能改\"\) \}",
    )
    c.present("认不出角色时“能改”记成未知，不报 0", card_code, r"val canWriteKnown: Boolean,")
    c.present(
        "兜底话不算清单里的一项（「暂时没有…」要返回 0）",
        card_code,
        r'if \(body\.startsWith\("暂时没有"\) \|\| body\.startsWith\("没有"\)\) return 0',
    )
    c.present("KDoc 里写了优先级（下一个人改之前先读到）", card, r"\*\*展开 > 认不出 > 全 0 > 报数\*\*|顺序即判据")
    c.present("KDoc 里说了折的是界面、不是那段话（它同时喂给模型）", card, r"折的是\*\*界面\*\*")

    print("\n== 2. 折叠块：默认收起、整行可点、正文只在展开时画 ==")
    c.present(
        "默认**折叠** ＋ rememberSaveable（这一页是整列滚动，remember 会丢）",
        screen_code,
        r"var capacityExpanded by rememberSaveable \{ mutableStateOf\(false\) \}",
    )
    c.absent(
        "⛔ 默认不许是展开的（改一个 true 就把用户抱怨的那一屏还回来了）",
        screen_code,
        r"var capacityExpanded by rememberSaveable \{ mutableStateOf\(true\) \}",
    )
    c.absent(
        "⛔ 折叠态不许退回普通 remember（滚动/转屏一趟就丢）",
        screen_code,
        r"var capacityExpanded by remember \{ mutableStateOf\(",
    )
    c.present(
        "整行可点（点标题、点空白、点 chevron 都算）",
        screen_code,
        r"\.clickable \{ capacityExpanded = !capacityExpanded \}\s*\n\s*\.padding\(vertical = 4\.dp\)",
    )
    c.present(
        "标题来自纯函数（计数与展开态都传进去，不在这儿另算一个数）",
        screen_code,
        r"capabilitySummaryLabel\(\s*\n\s*counts = capabilitySummaryCounts\(capacitySummary\),\s*\n"
        r"\s*expanded = capacityExpanded,",
    )
    c.present(
        "正文只在 if (capacityExpanded) 里画（折叠就是真的不画，不是盖住）",
        screen_code,
        r"if \(capacityExpanded\) \{\s*\n\s*Spacer\(Modifier\.height\(2\.dp\)\)\s*\n\s*Text\(\s*\n\s*capacitySummary,",
    )
    c.present(
        "chevron 在标题行**右端**，且跟着展开态翻向",
        screen_code,
        r"if \(capacityExpanded\) Icons\.Default\.ExpandLess else Icons\.Default\.ExpandMore,",
    )
    c.present(
        "展开态那一行说明白点下去会发生什么（标题占满剩下的宽度，箭头独立在右端）",
        screen_code,
        r"capabilitySummaryLabel\([\s\S]{0,600}?modifier = Modifier\.weight\(1f\),\s*\n\s*\)\s*\n\s*Icon\(",
    )

    print("\n== 3. 隐私那句在折叠之外（用户最关心的信息不许要点开才看得到） ==")
    c.present("隐私与费用那句还在", screen_code, re.escape(PRIVACY))
    c.present(
        "`if (capacityExpanded)` 只包住能力清单那一块（隐私那行在它**前面**）",
        screen_code,
        re.escape(PRIVACY) + r"[\s\S]{0,2200}?if \(capacityExpanded\) \{",
    )
    c.absent(
        "⛔ 隐私那句不许被卷进 `if (capacityExpanded)` 里",
        screen_code,
        r"if \(capacityExpanded\) \{[\s\S]{0,400}?" + re.escape(PRIVACY),
    )
    c.present("能力清单仍来自 `AiRolePrompt.settingsSummary`（唯一的来源）", screen_code, r"AiRolePrompt\.settingsSummary\(")
    c.present("仍带 actor（两个货主的能力不一样，批发商多一本自己的账）", screen_code, r"actor = ai\.currentActor,")
    c.present(
        "仍带 readModules（设置页那几个只读开关）",
        screen_code,
        r"readModules = vm\.readModules\.filter \{ it\.enabled \}\.map \{ it\.module \}\.toSet\(\),",
    )

    print("\n== 4. 能力声明本身：一个字没删（它同时还是模型的 system prompt） ==")
    c.present(
        "`settingsSummary` 还是那两行（能查：… / 能改：…）",
        code_only(prompt),
        r'append\("能查："\)',
    )
    c.present(
        "“能改”那行结尾仍是那句确认卡说明",
        code_only(prompt),
        r"——它只会把改动做成一张确认卡，你点「确认」才会写进系统。",
    )
    c.present(
        "认不出角色那句兜底话原文还在",
        code_only(prompt),
        r"当前没认出你的角色，AI 现在查不到也改不了任何业务数据——去「我的」页面重新登录一次。",
    )
    c.present("`brief()` 仍把它喂给模型（同一处来源，不许各写一份）", code_only(prompt), r"settingsSummary\(")

    print("\n== 5. 单测：四档文案 ＋ 计数都钉住了（纯函数改错会红） ==")
    for name in [
        "派单员_报出来的数字就是那段话里数出来的",
        "折起来那一行要报数_不能只写展开两个字",
        "展开之后那句要写收起_不然点不动第二次",
        "认不出角色_不许报数_只说点开看清单",
        "读开关全关掉_能查那行写的是暂时没有_不许数成一项",
        "一项能改的都没有_不许报能改0项",
        "数出来的项数跟开关联动_关掉一个少一项",
    ]:
        c.present("有这一档：" + name, test, re.escape(name))
    c.ok(
        "单测档数就是 7（这个数在变更单、登记簿、设计系统里都写着，少一条那些文书立刻对不上）",
        len(re.findall(r"@Test\b", test)) == 7,
        "数到 %d 个 @Test" % len(re.findall(r"@Test\b", test)),
    )
    for literal in ['"收起清单"', '"能做什么（点开看清单）"', '"暂时没有"']:
        c.present("逐字断言 " + literal, test, re.escape(literal))
    # ⚠️ 这里**故意不查**"单测里出现没出现写死的项数"：有一条单测正是拿
    #    `canRead = 12, canWrite = 0` 这种**字面构造**去钉边界档的（那是纯函数的输入，
    #    不是从真实能力里抄来的期望值），一并禁掉会把那条好测试判成违规。
    #    "数字从哪来"由第 1 节那两条（`lineSequence().firstOrNull { it.startsWith("能改") }` ＋
    #    "兜底话不算一项"）和下面这条反向证据来钉。
    c.present(
        "单测里有一条是**反证**数字真的跟着开关走（不是手写）",
        test,
        r"数出来的项数跟开关联动_关掉一个少一项",
    )

    print("\n== 6. 用户口径留档（下一个人知道为什么给这一段加了个盖子） ==")
    c.present("KDoc 里留了用户原话的 ref " + "`m01649`", card, "ref `m01649`")
    c.present("KDoc 里留了那句「不然太长了很占位子」", card, r"不然太长了很占位子")
    c.present("KDoc 里留了台账编号 L-63", card, r"台账 L-63")
    c.present("KDoc 里写了 CHG-0098", card, r"CHG-0098")

    print("\n== 7. 文书与反向验证 ==")
    doc = read(DOC)
    missing = [s for s in SECTIONS if s not in doc]
    c.ok("CHG-0098.md 九节齐全", not missing, "缺：" + " / ".join(missing))
    c.present("变更单写了 Blast Radius L0", doc, r"Blast Radius\*\*：L0")
    c.present("登记簿里有 CHG-0098 这一行", read(REG), r"CHG-0098")
    c.present("工作声明里记了这条活", read(CLAIM), r"CHG-0098")
    # ⚠️ 必须锚在**行首的标题**上（`^### 4.25f `），不能只找 `4.25f` 这个子串：
    #    正文里还有一句「**这一节就是 §4.25f**」，只找子串的话，把标题改名成 4.25g
    #    这条判据照样绿（CHG-0098 的反向验证第 20 条就是这么把这条死判据抓出来的）。
    c.present("设计系统里新增了 §4.25f 这一节（按行首标题找，不是找子串）", read(DESIGN), r"^### 4\.25f ")
    c.ok("反验脚本在：" + REVERSE.name, REVERSE.exists())

    print("\n" + "=" * 60)
    if c.fails:
        print("❌ %d/%d 项没通过：" % (len(c.fails), c.passes + len(c.fails)))
        for f in c.fails:
            print("   - " + f)
        return 1
    print("✅ 全部 %d 项通过：AI 设置页的「能力说明」默认折成一行（标题报数：能查 N 项 · 能改 M 项），" % c.passes)
    print("   点一下看全；隐私与费用那句仍在折叠之外；那段话本身一个字没动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
