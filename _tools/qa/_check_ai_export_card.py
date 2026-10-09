"""AI 助手「导出文件卡」的形状（台账 L-61 / CHG-0095）—— 用户点名的那三块。

## 用户要的是什么（2026-10-09，ref m00002，语音转写逐字）
    更改一下 ai 的那个导出表格的样式啊，也不说表格吧。光是有些文件如果将它导出来，
    他给一些文件的话是以这样子的形式出现的上面是信息，然后最下面就是有个单独的卡片，
    那个卡片就是我已经画好了，就是文件，然后那个有个左边是有个那个框那是个文件图标，
    然后呢中间，那些横杠了那些就是对应的信息啊，这个文件的信息，然后呢，最后，
    这一右边的那个小框那就是一个下载的图标按钮，我们点击那它就会直接下载下来，
    或者说啊，还有一个按钮叫做就是分享也就是它有 2 个按钮。
    第一个是呃下载第 2，个是分享。啊这个 2 个按钮不要 ****的太近啊
⇒ 四条主张：① 左＝**带框的文件图标**；② 中＝文件信息；③ 右＝**下载 ＋ 分享两颗**图标按钮；
④ 两颗之间**要留间距**（"不要靠的太近"）。

## 为什么这条必须有机器的判据（每一处坏了都不报错、不崩、单测也不会红）
1. **两颗又变回一颗**：旧版就是 `when` 四选一只画一颗（点过 [下载] 之后换成 [分享]）。
   把它改回去 —— 编译过、跑得动、单测全绿，只是用户画的那张图又不对了。
2. **靠藏起来表达"点不动"**：`if (enabled) IconButton { … }` 这种写法谁都看不出错，
   但"这里到底有几颗按钮"就随时会变；本单的口径是**一直都在，只灰不藏**。
3. **哪个能点判在界面上**：把 `!state.busy && saved == null` 抄进 `AiChatScreen`，
   纯函数就变成了摆设；两处判据一旦漂开，"点不动的按钮看着点得动"就是这么来的。
4. **两颗贴在一起**：`Spacer` 被删掉或改成 0.dp —— 布局照样成立，
   代价是用户点"分享"时点到"下载"（这里的误触后果是文件被发到别处）。
5. **可点区域缩水**：`Modifier.size(44.dp)` 被改成 24.dp，视觉上"更精致"，
   但设计规范那条"≥ 44×44px"没了，老人手指点不准。
6. **左框退化成裸图标**：`.background(...)` / `.border(...)` 被删掉，
   "带框"就没了 —— 而用户那句话里的第一个词就是"框"。
7. **分享在重下期间还亮着**：`busy` 没被算进 `shareEnabled`。这条最隐蔽：
   真机上是"文件在手机上、正在被新一版覆盖"，用户分享到的可能是上一版那份表，
   界面上没有任何异常。
8. **判据自己空转**：清单指向不存在的文件、纯函数被搬走、CHG 文档缺节、反验脚本失踪。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
上面这些**没有一条是类型属性**：`enabled = true` 与 `enabled = false` 同型；
`Spacer(Modifier.width(12.dp))` 删掉之后仍然是一段合法的 Compose 代码；
"IconButton 有没有被包在 `if` 里"根本不是类型能表达的事。
可用性那一半已经抽成纯函数并用 `AiExportCardTest` 钉住了（20 档），
但"**界面照着画**"这一半（两颗都在、左框在、间距在、尺寸在）只能落在源码结构上，
再配反向验证 `_reverse_verify_ai_export_card.py`（逐条弄坏一次，看它真的变红）。

静默空转保护：MIN_KT = 100（目录被搬走 / 一个 .kt 都没扫到也必须红）。

## 判据
1. `ai/AiExportCard.kt`：`exportCardActions` 三条判据（busy 压过一切 / 存好了下载退灰 /
   分享要 saved＋shareable），外加 `exportProgressNote`、`exportDownloadLabel`、
   `exportCardSubtitle`、`exportSavedLabel`、`exportStatusLine`（后两个是 CHG-0097 加的：
   用户第二次点名「太长了……只表示一保存做个简单的」）；
2. `ui/ai/AiChatScreen.kt` 的 `ExportFileRow`：带框文件图标（44dp、MoneyOrange）＋ 文件信息
   （名字 / 哪张表哪一段 / **一句**"现在怎么了"，⛔ 里面不许再出现文件路径）＋ **两颗**
   IconButton（FileDownload / Share，各 44dp，`exportActionGap` 隔开，enabled 只来自
   `exportCardActions`）；
3. ⛔ 界面里不许再出现"自己判 busy/saved 决定画不画按钮"的旧写法（点了就没了的那种）；
4. 单测 `AiExportCardTest` 钉住各档（含"重下期间两颗都不亮""存好之后不写路径"）；
5. 设计系统文档 §4.25d ＋ §4.25e ＋ 变更单九节（CHG-0095 / CHG-0097 两份）＋ 登记簿 ＋ 工作声明齐；
6. 反验脚本在。

用法：python _tools/qa/_check_ai_export_card.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = AND / "ui/ai/AiChatScreen.kt"
CARD = AND / "ai/AiExportCard.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiExportCardTest.kt"
DOC = ROOT / "docs/changes/CHG-0095.md"
DOC2 = ROOT / "docs/changes/CHG-0097.md"
REG = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_ai_export_card.py"
COLOR_KT = AND / "ui/theme/Color.kt"

#: 全仓至少要有这么多 .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_KT = 100

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

#: 两颗按钮的可点区域与间距（逐字，`AiChatScreen.kt` 顶部常量）。
BTN_SIZE = "private val ExportActionButtonSize = 44.dp"
GAP = "private val ExportActionGap = 12.dp"
ICON_BOX = "private val ExportIconBoxSize = 44.dp"


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

    def present(self, label: str, text: str, pattern: str, uniq: bool = False) -> None:
        """`uniq=True`：这条判据在 `text` 里必须**只命中一处**（见 `exactly_once`）。

        为什么不默认开：本文件里 `contentAlignment = Alignment.Center` 这类常见写法本来就有
        多处合法的，一刀切会把判据变成噪声。所以在**"我以为只此一处"**的那几条上显式开 ——
        开着的判据哪天变成命中多处，会直接 FAIL，提醒你它不再是在检查你以为的那一处。
        """
        m = re.search(pattern, text, re.M)
        if m is None:
            self.ok(label, False, "没找到 " + repr(pattern))
            return
        if uniq and not exactly_once(pattern, text, label):
            self.fails.append(label + " —— 命中了多处，不是在检查你以为的那一处")
            return
        self.ok(label, True)

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text, re.M)
        self.ok(label, m is None, "命中：" + repr(m.group(0)) if m else "")


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数，好让行号还对得上）。

    为什么要这样：本单的"用户原话"就抄在 KDoc 里，里面写着「下载」「分享」「文件图标」
    这些**看起来像代码判据**的字样 —— 判据要抓的是**代码里**还有没有那三块。
    """
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def first_line_span(pattern: str) -> str:
    """正则头一段**行首锚定**的写法：把「前导空白」当成行首。

    ⚠️ 2026-10-09 本单自己踩到的坑（判据是死的，反向验证才抓到）：
    `AiChatScreen.kt` 里 `Icons.Default.Description,` 出现 **3 次**，缩进分别 32 / 32 / 24 空格
    —— 而 **24 空格是 32 空格的前缀**。反向验证用 `"<24空格>Icons.Default.Description,\n"`
    去注入时，`str.replace(old, new, 1)` 命中的是**第 745 行**（32 空格那行的后一段），
    真正该改的第 1645 行原封不动，于是这条判据**照样绿**。
    这里把行首锚成 `(?:^|[^\\S\\n])`，配 `\\s*` 语义上等价，但**含义写明了**：
    这是"行首 + 前导空白"，不是"随便一段空白"。
    """
    return r"(?:^|[^\S\n])" + pattern


def exactly_once(pattern: str, code: str, label: str) -> bool:
    """这条判据在源码里必须**只命中一处**。

    为什么要这样：判据全文件找、写得松的时候，"别的行还留着同样的字眼"会把红线撑成绿的
    —— 反向验证里「把失败那一行的错误色换成 outline」当时就抓不到（`colorScheme.error`
    全文有 6 处）。一条判据命中多处，就说明它其实**没在检查你以为的那一处**。
    """
    n = len(re.findall(pattern, code, re.M))
    if n == 1:
        return True
    print("  [FAIL] %s —— 这条判据命中了 %d 处（不是 1 处）：%r" % (label, n, pattern))
    return False


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit("找不到文件：" + str(p) + "（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


ROW_FUN = "private fun ExportFileRow("
#: 这个函数的**下一行**长这样吗？用来找函数体到哪儿结束。
#: Kotlin 顶层声明都在 0 缩进，所以「一个 0 缩进、像声明开头的行」＝下一个函数开始了。
NEXT_DECL = re.compile(
    r"^(?:@|private |internal |public |fun |@Composable)",
    re.M,
)


def slice_row(screen_code: str) -> tuple[str, int, str]:
    """把 `ExportFileRow` 这个函数的**函数体**切出来，返回（函数体, 行号, 切不出来的理由）。

    为什么非要切（2026-10-09 本单自己抓到的教训）：本文件里 `MaterialTheme.colorScheme.error`
    一共出现 **6 次**、`disabledContentColor = …outlineVariant` 出现 **2 次**（下载那颗与分享那颗各一次），
    早先那几条判据是**全文件**找的 —— 于是反向验证里「把失败那一行的错误色换成 outline」
    「把下载那颗的 disabledContentColor 抽掉」这两条注入**照样绿**：别的行还留着同样的字眼。
    切出来之后，"这一处还是不是那个样子"就只由这一段说了算。

    ⛔ 切不出来**不算通过**，也**不许直接 `SystemExit` 静默退出**：理由要返回给调用方，
    由它走 `Checker.ok(...)` 变成一条**看得见的 `[FAIL]`**。
    为什么要这样（2026-10-09 实测）：早先这里是 `raise SystemExit(…)` —— 进程直接退出，
    stdout 里**一条 `[FAIL]` 都没有**（只有 stderr 上一行字），反向验证那边只看到"红了"、
    看不到是哪一条，只能判成"红了但不是这一条"。红线要红得**说得清**。
    """
    lines = screen_code.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.startswith(ROW_FUN):
            start = i
            break
    if start is None:
        return "", 0, "找不到 `private fun ExportFileRow(` —— 它被改名/搬走了？这条判据要跟着改。"
    depth = 0
    seen_brace = False
    for j in range(start, len(lines)):
        line = lines[j]
        depth += line.count("{") - line.count("}")
        if "{" in line:
            seen_brace = True
        if not seen_brace:
            continue
        if depth <= 0:
            return "\n".join(lines[start : j + 1]), start + 1, ""
        if j > start and depth == 0 and NEXT_DECL.match(line):
            return "\n".join(lines[start:j]), start + 1, ""
    return "", 0, "`ExportFileRow` 的函数体找不到收尾（大括号配不平）—— 判据要跟着改。"


def main() -> int:
    c = Checker()
    screen = read(SCREEN)
    card = read(CARD)
    test = read(TEST)
    screen_code = code_only(screen)
    row_code, row_line, row_why = slice_row(screen_code)
    if row_why:
        # ⛔ 不静默退出：切不出来本身就是一条红线（这一段的形状已经不认识了）。
        c.ok("切出了 `ExportFileRow` 这一段的函数体", False, row_why)
        row_code, row_line = screen_code, 0

    kt = sorted(AND.rglob("*.kt"))

    print("== 0. 反空转：扫描本身得是活的 ==")
    c.ok("扫到 %d 个 .kt（下限 %d）" % (len(kt), MIN_KT), len(kt) >= MIN_KT)
    names = {p.name for p in kt}
    c.ok("扫到聊天页那个 .kt", "AiChatScreen.kt" in names)
    c.ok("扫到导出卡纯函数那个 .kt", "AiExportCard.kt" in names)
    c.ok("导出卡那个 .kt 只有一处（没有第二份副本）", len([p for p in kt if p.name == "AiExportCard.kt"]) == 1)

    print("\n== 1. 纯函数：哪一颗点得动，只有一处实现 ==")
    c.present(
        "签名（busy / saved / shareable 三问进，三个答案出）",
        card,
        r"internal fun exportCardActions\(\s*\n\s*busy: Boolean,\s*\n\s*saved: Boolean,\s*\n"
        r"\s*shareable: Boolean,\s*\n\): ExportCardActions = ExportCardActions\(",
    )
    c.present(
        "busy 压过一切：下载这一头（连点 = 连开任务）",
        card,
        r"downloadEnabled = !busy && !saved,",
    )
    c.present(
        "busy 压过一切：分享这一头（重下期间旧文件还挂着，分享出去可能是上一版）",
        card,
        r"shareEnabled = !busy && saved && shareable,",
    )
    c.absent(
        "⛔ 分享不许漏掉 busy（漏了就是「文件正在被覆盖、分享键还亮着」）",
        card,
        r"shareEnabled = saved && shareable,",
    )
    c.present("「文件已经在手机上」单独出来给界面用（写'已保存'那一句）", card, r"downloaded = saved,")
    c.present(
        "进度那句话：账本报的原样用，没话说要有一句顶上去",
        card,
        r"internal fun exportProgressNote\(busy: Boolean, saved: Boolean, progress: String\): String = when \{\s*\n"
        r'\s*!busy -> ""\s*\n'
        r"\s*progress\.isNotBlank\(\) -> progress\s*\n"
        r'\s*saved -> "正在准备文件…"\s*\n'
        r'\s*else -> "正在生成…"\s*\n\}',
    )
    c.present("下载那颗上的字（失败过就写再试一次）", card, r'internal fun exportDownloadLabel\(hasError: Boolean\): String = if \(hasError\) "再试一次" else "下载"')
    c.present(
        "信息区第二行：报表 = 表名 ＋ 区间；账本 = 一句话；认不出就什么都不写",
        card,
        r"internal fun exportCardSubtitle\(recipe: StoredExportRecipe\): String = when \(recipe\.source\) \{",
    )
    c.present("表名走 AiTools.exportTitle（与报表页签、后端 sheet 标题三处逐字相同）", card, r"AiTools\.exportTitle\(recipe\.kind\)")
    c.absent("⛔ 表名不许在卡片里另抄一份映射", card, r'"营业纵览"')
    c.present("KDoc 里留了用户口径的 ref", card, r"ref `m00002`")
    c.present("KDoc 里留了台账编号", card, r"台账 L-61 / CHG-0095")
    # ---- CHG-0097 / 台账 L-62：用户第二次点名「太长了……只表示一保存做个简单的」 ----
    c.present("KDoc 里留了第二次点名的 ref（不然下一个人不知道为什么路径没了）", card, r"ref `m01176`")
    c.present("KDoc 里留了这一次的台账编号", card, r"台账 \*\*L-62\*\* / CHG-0097")
    c.present(
        "「已保存」只有一处定义（就是这三个字，不许在界面里再拼一遍）",
        card,
        r'internal fun exportSavedLabel\(\): String = "已保存"',
        uniq=True,
    )
    c.present(
        "整行收敛到 exportStatusLine（错误 > 已存好 > 正在忙，顺序即判据）",
        card,
        r"internal fun exportStatusLine\(\s*\n"
        r"\s*error: String,\s*\n\s*saved: Boolean,\s*\n\s*busy: Boolean,\s*\n\s*progress: String,\s*\n"
        r"\): String = when \{\s*\n"
        r'\s*error\.isNotBlank\(\) -> "⚠ " \+ error\s*\n'
        r"\s*saved -> exportSavedLabel\(\)\s*\n"
        r"\s*else -> exportProgressNote\(busy = busy, saved = false, progress = progress\)\s*\n\}",
        uniq=True,
    )
    c.absent("⛔ 「已保存到：」这句话不许回来（它后面必然跟着一整条路径）", code_only(card), r"已保存到")
    # ⚠️ 这一条必须去注释之后再找：KDoc 里为了讲清"为什么不写路径"，
    # 正文明写着 `saved.path` 这四个字（`code_only` 只判**代码里**有没有）。
    c.absent("⛔ 卡片上不许再出现「存到哪儿」这档（路径由右边那颗分享负责）", code_only(card), r"saved\.path")

    print("\n== 2. 左：带框的文件图标（用户第一句话就是'框'） ==")
    c.present("图标框尺寸常量", screen_code, re.escape(ICON_BOX))
    c.ok(
        "切出了 `ExportFileRow` 这一段的函数体（第 %d 行起；下面「这一处」的判据只认这一段）" % row_line,
        len(row_code) > 400,
        "只切到 %d 个字符" % len(row_code),
    )
    # 语义色在 ui/theme/Color.kt 里是**裸的 ARGB 值**（用的时候必须包成 Color(...)）。
    # ⚠️ 2026-10-09 晚（CHG-0101 换色）起这些 token 写的是 `0xFFAF7C4D`，
    #    不再带 `L` 后缀 —— 所以这里匹配到 `{8}` 位十六进制就够，别去钉那个后缀。
    # 这条前置判据是给下一个人看的：哪天它变成 Color 了，本节的 Color(...) 判据要跟着改。
    c.ok(
        "前置：MoneyOrange / ThemeGreen 在主题里仍是裸 ARGB（所以下面必须写 Color(...)）",
        re.search(r"val MoneyOrange = 0x[0-9A-Fa-f]{8}\b", read(COLOR_KT)) is not None,
    )
    c.present(
        "一个 44dp 的方框：圆角 ＋ 底色 ＋ 描边（三样缺一就不是'带框'）",
        screen_code,
        r"\.size\(ExportIconBoxSize\)\s*\n\s*\.clip\(RoundedCornerShape\(10\.dp\)\)\s*\n"
        r"\s*\.background\(Color\(MoneyOrange\)\.copy\(alpha = 0\.12f\)\)\s*\n"
        r"\s*\.border\(1\.dp, Color\(MoneyOrange\)\.copy\(alpha = 0\.35f\), RoundedCornerShape\(10\.dp\)\),",
        uniq=True,
    )
    c.present(
        "框里那个图标：文件图标 ＋ 导出语义色（MoneyOrange，与账本/收款/导出同源）",
        row_code,
        # ⛔ 这三行必须**挨着**（先 `Icons.Default.Description,` 再 `contentDescription` 再 `tint`）。
        # 早先写成 `[\s\S]{0,200}?` 跨行乱找 —— 于是把图标换成 `Info` 之后判据照样绿：
        # 200 个字符之内还够得着**下面那颗下载键**的 `tint = Color(MoneyOrange)`。
        first_line_span(
            r"Icons\.Default\.Description,\s*\n\s*contentDescription = null,\s*\n"
            r"\s*modifier = Modifier\.size\(22\.dp\),\s*\n\s*tint = Color\(MoneyOrange\),"
        ),
        uniq=True,
    )
    c.present("框不可点（它只是'这是个文件'的符号，可点的是右边两颗）", screen_code, r"contentAlignment = Alignment\.Center,")

    print("\n== 3. 中：文件信息两行（名字 / 哪张表哪一段）＋ 一句「现在怎么了」 ==")
    c.present(
        "文件名最多两行（长文件名不要被切成一个看不出是什么的样子）",
        screen_code,
        r'recipe\.fileName\.ifBlank \{ "导出文件" \},\s*\n\s*fontSize = MessageTextSize,\s*\n'
        r"\s*fontWeight = FontWeight\.Medium,\s*\n\s*maxLines = 2,",
    )
    c.present("第二行来自纯函数（空就不画，不留一条空行）", screen_code, r"val subtitle = exportCardSubtitle\(recipe\)\s*\n\s*if \(subtitle\.isNotBlank\(\)\) \{")
    c.present(
        "那一句话整行走纯函数（界面里不许再拼一次「错误 > 已存好 > 正在忙」）",
        screen_code,
        r"val note = exportStatusLine\(\s*\n"
        r"\s*error = state\.error,\s*\n\s*saved = saved != null,\s*\n\s*busy = state\.busy,\s*\n"
        r"\s*progress = state\.progress,\s*\n\s*\)",
        uniq=True,
    )
    # ⛔ CHG-0097 / 台账 L-62：用户第二次点名「不要那么长的信息啊，只表示一保存做个简单的」。
    # 这几条 absent 是这一次改动的要害 —— 路径一旦漏回来，卡片立刻又被撑成一大块。
    c.absent("⛔ 状态行里不许再拼「已保存到：」＋路径", code_only(screen_code), r'"已保存到："')
    c.absent("⛔ 卡片上不许再读 saved\.path（界面上没有任何一处该显示完整路径）", row_code, r"saved\.path")
    c.absent(
        "⛔ 那一行不许再给到两行（以前是 maxLines = 2，正是它把卡片撑高的）",
        row_code,
        # 只用「紧跟在 `note,` 之后」这一段来认，不把注释的逐字写进正则 ——
        # 判据钉的是形状，钉注释原文的话，改一个字就会变成假红。
        #
        # ⚠️ `row_code` 过的是 `code_only()`：行注释被拿掉、**只留一个空行占位**。
        #    所以中间那几行既可能是注释（原样看），也可能是一片空白（去注释后看），
        #    两种都得认 —— 只认注释会让这条判据变成死的（反向验证第 32 条就是这么抓出来的）。
        #
        # ⚠️ 窗口是 400 而不是"到函数结尾"：这一段到状态行自己的 `maxLines` 隔着约 400 字符，
        #    而文件名那一行的 `maxLines = 2` **在 `note,` 前面**（偏移更小），所以开多大都不会误伤。
        #    开太小则注入 `maxLines = 2` 之后仍旧匹配不到 —— 那这条判据就是死的。
        r"note,\s*\n(?:\s*(?://[^\n]*)?\n)*\s*[^\n]*\n\s*fontSize = MetaTextSize,\s*\n"
        r"\s*color = [^\n]*\n[\s\S]{0,400}?maxLines = 2,",
    )
    c.present(
        "失败那一行用错误色",
        row_code,
        # ⛔ 认「`color = if (state.error…)` 之后**紧跟着**错误色」这一对。
        # 早先只找 `MaterialTheme.colorScheme.error`（**全文件** 6 处！）——
        # 于是把这一处的错误色换成 outline 之后判据照样绿（别的行还留着同样的字眼）。
        first_line_span(
            r"color = if \(state\.error\.isNotBlank\(\)\) \{\s*\n\s*"
            r"MaterialTheme\.colorScheme\.error\s*\n"
        ),
        uniq=True,
    )
    c.present("存好了给一个绿勾（'已下载'要说得出）", screen_code, r"if \(actions\.downloaded && !state\.busy\) \{[\s\S]{0,200}?Icons\.Default\.Check,")
    c.present("Android 10 以下那句话原样还在（口径 m01865）", screen_code, r"这台手机（Android 10 以下）不能把文件直接发给微信/QQ")

    print("\n== 4. 右：**两颗**图标按钮，各 44dp，中间留间距 ==")
    c.present("按钮尺寸常量", screen_code, re.escape(BTN_SIZE))
    c.present("间距常量", screen_code, re.escape(GAP))
    c.ok(
        "结算出来的动作确实被算了一次（不是画的时候各判一次）",
        screen_code.count("val actions = exportCardActions(") == 1,
        "数到 %d 处" % screen_code.count("val actions = exportCardActions("),
    )
    c.present(
        "下载那颗：onDownload ＋ enabled 来自纯函数 ＋ 44dp ＋ 语义色",
        row_code,
        first_line_span(
            r"IconButton\(\s*\n\s*onClick = onDownload,\s*\n\s*enabled = actions\.downloadEnabled,\s*\n"
            r"\s*modifier = Modifier\.size\(ExportActionButtonSize\),\s*\n\s*"
            r"colors = IconButtonDefaults\.iconButtonColors\(\s*\n\s*"
            r"contentColor = Color\(MoneyOrange\),\s*\n\s*"
            r"disabledContentColor = MaterialTheme\.colorScheme\.outlineVariant,\s*\n"
        ),
        uniq=True,
    )
    c.present(
        "下载那颗的图标与无障碍名（失败时读作'再试一次'）",
        screen_code,
        r"Icons\.Default\.FileDownload,\s*\n\s*contentDescription = exportDownloadLabel\(state\.error\.isNotBlank\(\)\),",
        uniq=True,
    )
    c.present(
        "分享那颗：enabled 来自纯函数 ＋ 44dp ＋ 语义色",
        row_code,
        r"enabled = actions\.shareEnabled,\s*\n"
        r"\s*modifier = Modifier\.size\(ExportActionButtonSize\),\s*\n\s*"
        r"colors = IconButtonDefaults\.iconButtonColors\(\s*\n\s*"
        r"contentColor = AiAccent,\s*\n\s*"
        r"disabledContentColor = MaterialTheme\.colorScheme\.outlineVariant,\s*\n",
        uniq=True,
    )
    c.present(
        "分享那颗的图标（Share，不是文字'分享'）",
        screen_code,
        r"Icons\.Default\.Share,\s*\n\s*contentDescription = \"分享文件\",",
        uniq=True,
    )
    c.ok(
        "两颗按钮之间**确实隔了**那段间距（两颗各一段，共 2 处）",
        row_code.count("Spacer(Modifier.width(ExportActionGap))") == 2,
        "数到 %d 处" % row_code.count("Spacer(Modifier.width(ExportActionGap))"),
    )
    c.absent(
        "⛔ 两颗之间不许用别的方式挨在一起（写死的 0/2dp 之类）",
        row_code,
        r"Spacer\(Modifier\.width\(0\.dp\)\)",
    )
    c.present("分享失败时那句实话还在", row_code, r"没找到能接收文件的 App，文件已经存到「下载 / SOrders报表」。")
    # 下面两条是从前面那两条大判据里**单独拎出来**的（2026-10-09 反向验证第 21/22 条注入了两次
    # 都是"红了但不是这一条"：`contentColor = Color(...)` 全文命中多处，大判据一红就顶掉了它们）。
    # 拎成两条 ＋ 行首锚定 ＋ 只命中一处，注入才指得明是"下载那颗"还是"分享那颗"变了色。
    c.present(
        "下载那颗亮起来是导出语义色（MoneyOrange，同样要包 Color(...)）",
        row_code,
        first_line_span(r"contentColor = Color\(MoneyOrange\),"),
        uniq=True,
    )
    c.present(
        "分享那颗亮起来是 AI 页的强调色（AiAccent，CHG-0104 起不再隔着文件读主操作色）",
        row_code,
        first_line_span(r"contentColor = AiAccent,"),
        uniq=True,
    )

    print("\n== 5. ⛔ 不许退回'点过就没了'的旧写法 ==")
    c.absent(
        "旧版那颗点了就消失的 TextButton('分享')",
        screen_code,
        r'TextButton\(onClick = \{[^}]*shareExportFile[\s\S]{0,200}?Text\("分享"',
    )
    c.absent(
        "旧版那颗点了就消失的 TextButton(下载/再试一次)",
        screen_code,
        r'TextButton\(onClick = onDownload\) \{\s*\n\s*Text\(if \(state\.error\.isBlank\(\)\)',
    )
    c.absent(
        "旧版那种'忙就画转圈、不忙才画按钮'的四选一",
        row_code,
        r"state\.busy -> CircularProgressIndicator\(",
    )
    c.absent(
        "这张卡上不许再有转圈（忙的时候两颗按钮**灰着**，不是换成一颗转圈）",
        row_code,
        r"CircularProgressIndicator",
    )
    c.absent(
        "⛔ 界面里不许自己判'存好了就把下载藏起来'",
        row_code,
        r"if \(actions\.[A-Za-z]+\) \{[\s\S]{0,80}?IconButton",
    )
    # 下面这两条是 2026-10-09 反向验证**第一版没抓住**的两条注入（判据当时是死的）：
    # 旧写法是「忙就把两颗按钮一起藏掉、只留一个转圈」「点过了就把下载那颗藏起来」，
    # 两者都能**编译通过**，而且旧版那两条 `absent` 只认 `when (…) -> …` 的字面形状 ——
    # 换个写法注入进去就抓不到了。这两条认的是**形状**：按钮在不在渲染树里。
    c.absent(
        "⛔ 两颗按钮不许被 `if` 藏掉（点了下载之后下载那颗还得在原处）",
        row_code,
        r"if \([A-Za-z0-9_.]+\) \{?\s*\n?\s*(?:@Composable\s*)?IconButton\(",
    )
    c.absent(
        "⛔ 忙的时候也不许把两颗按钮换成别的东西（两颗永远都在）",
        row_code,
        r"if \(state\.busy\) \{?[\s\S]{0,120}?(?:CircularProgressIndicator|Text\()",
    )

    print("\n== 6. 单测：各档都钉住了（含'重下期间两颗都不亮'） ==")
    c.present("还没点过那一档", test, r"还没点过_下载能点_分享是灰的")
    c.present("忙的时候两颗都不亮", test, r"正在生成_两颗都点不动")
    c.present("存好了：下载退灰、分享亮", test, r"存好了_下载退成灰的_分享亮起来")
    c.present("Android 10 以下分享始终是灰的", test, r"安卓10以下存好了_分享仍然是灰的")
    c.present("重下期间两颗都不亮（本单新增的那一条）", test, r"已经存好了又忙起来_两颗都不许亮")
    c.present("进度那句话的兜底", test, r"忙但没话说_要有一句顶上去")
    c.present("下载那颗上的字", test, r"下载那颗的字_错了就写再试一次")
    c.present("信息区第二行：表名 ＋ 区间", test, r'assertEquals\("营业纵览 · 2026-09-01 ~ 2026-09-30", exportCardSubtitle\(r\)\)')
    c.present("空的时候不许写出一串空点", test, r"报表_一个字段都没有_也不许写出一串空点")
    c.present("认不出的表名原样回", test, r"报表_认不出的表名_原样回而不是猜一个")
    # ---- CHG-0097 / 台账 L-62：状态行那五档 ----
    c.present("存好之后只写「已保存」（CHG-0097 的要害那一条）", test, r"存好之后_卡片上只写已保存_不写路径")
    # ⚠️ 不写 `assertFalse(` 开头：JUnit 是 message 在前、条件在后，
    #    所以真正要钉的是「**有一个** `line.contains("/storage")` 被 assertFalse 管着」。
    #    用 `[\s\S]{0,200}?` 跨过中间那句话（那句话说白了是给人看的，钉死它反而会假红）。
    c.present(
        "存好之后不许出现路径（这一条才是'卡片不再被撑高'的机器判据）",
        test,
        r"assertFalse\([\s\S]{0,200}?line\.contains\(\"/storage\"\)",
    )
    c.present("失败那句原话压过「已保存」", test, r"失败过_后端那句原话要原样说出来_不能被已保存盖掉")
    c.present("忙的时候走进度那句话", test, r"正在忙_走的是进度那句话")
    c.present("什么都没发生就不留一条空行", test, r"什么都没发生_状态行是空的_不留一条空行")
    c.present("「已保存」的字数上限", test, r"存好之后的字数_就是三个字")

    c.ok(
        "单测档数就是 20（这个数在变更单、登记簿、设计系统、代码定位表里都写着，"
        "少一条那些文书立刻对不上）",
        len(re.findall(r"@Test\b", test)) == 20,
        "实际 %d 条" % len(re.findall(r"@Test\b", test)),
    )

    print("\n== 7. 用户口径留档（下一个人知道这张卡为什么长这样） ==")
    c.present("KDoc 里留了那句「这 2 个按钮不要 ****的太近」", screen, r"这 2 个按钮不要 \*\*\*\*的太近")
    c.present("KDoc 里留了「左边是有个那个框那是个文件图标」", screen, r"左边是有个那个框那是个文件图标")
    c.present("KDoc 里留了台账编号 L-61", screen, r"台账 L-61")
    # ---- CHG-0097：第二次点名也要留档，否则下一个人只会看到"路径莫名其妙没了" ----
    c.present("KDoc 里留了第二次点名那句「只表示一保存做个简单的」", screen, r"不要那么长的信息啊，只表示一保存做个简单的")
    c.present("KDoc 里留了台账编号 L-62", screen, r"台账 L-62")

    print("\n== 8. 文书与反向验证 ==")
    doc = read(DOC)
    missing = [s for s in SECTIONS if s not in doc]
    c.ok("CHG-0095.md 九节齐全", not missing, "缺：" + " / ".join(missing))
    c.present("变更单里写了 Blast Radius L0", doc, r"Blast Radius\*\*：L0")
    c.present("登记簿里有 CHG-0095 这一行", read(REG), r"CHG-0095")
    c.present("工作声明里记了这条活", read(CLAIM), r"CHG-0095")
    c.present("设计系统里立了 §4.25d 这一节", read(DESIGN), r"§4\.25d")
    c.ok("反验脚本在：" + REVERSE.name, REVERSE.exists())

    # ---- CHG-0097 / 台账 L-62：这一次改动的文书 ----
    doc2 = read(DOC2)
    missing2 = [s for s in SECTIONS if s not in doc2]
    c.ok("CHG-0097.md 九节齐全", not missing2, "缺：" + " / ".join(missing2))
    c.present("CHG-0097.md 里写了 Blast Radius L0", doc2, r"Blast Radius\*\*：L0")
    c.present("登记簿里有 CHG-0097 这一行", read(REG), r"CHG-0097")
    c.present("工作声明里记了这一次的活", read(CLAIM), r"CHG-0097")
    c.present("设计系统里立了 §4.25e 这一节（'字少'这件事要有据可依）", read(DESIGN), r"§4\.25e")

    print("\n" + "=" * 60)
    if c.fails:
        print("❌ %d/%d 项没通过：" % (len(c.fails), c.passes + len(c.fails)))
        for f in c.fails:
            print("   - " + f)
        return 1
    print("✅ 全部 %d 项通过：导出文件卡是「左带框文件图标 ＋ 中文件信息 ＋ 右下载/分享两颗按钮」，" % c.passes)
    print("   两颗各 44dp、中间隔 12dp，哪一颗点得动只由 ai/AiExportCard.kt 一处说了算。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
