"""AI 助手的「执行过程」默认折叠、点开才逐条看（台账 L-60 / CHG-0094）—— 用户点名的那一处。

## 用户要的是什么（2026-10-09，ref m35906）
用户发来「AI 助手」聊天页截图，**红框圈住**的是气泡上方那一串「🔧 正在查…／✓ … → 返回 N 条」：
    还有这个部分它是自动的收缩的，也就是说默认情况下，是收收缩的就像思考过程一样，
    不过，我们也可以点开进行查看不然，它步骤太多的话，使得整个界面太过冗余了
⇒ 两条主张：① 默认**折叠成一行**（像思考过程）；② **点得开**（折叠不等于把过程删掉）。

## 为什么这条必须有机器的判据（每一处坏了都不报错、不崩、单测也不会红）
1. **默认值一改就全摊开**：`mutableStateOf(false)` → `mutableStateOf(true)`，编译、运行、
   全量单测都照样绿，只是用户抱怨的那一屏又回来了。
2. **折叠只是"看着像"**：`if (expanded)` 那层壳被删掉，标题行照样画、步骤也照样画 ——
   整块变成一个"点不动的展开条"，谁都不会报错。
3. **点不开**：整块的 `clickable` 被去掉（或挪到只有文字那一小块），折叠块就成了死块。
4. **滚动一趟就丢状态**：LazyColumn 会销毁滚出屏幕的气泡；`rememberSaveable` 被换回
   `remember`，展开态在滚动中丢失 —— 没有异常、没有日志。
5. **标题不再说人话**：三档文案（收起 / 进行中 / 几步）任何一档被删、改死数字、或顺序调反，
   用户要么不知道点得开、要么不知道还在等；它是纯函数，改错了也没有别的判据会喊。
6. **「进行中」挂到每一条历史消息上**：调用点直接把全局 `sending` 传下去（不跟"最后一条"求合取），
   屏幕上每条旧消息都变成「执行过程 · 进行中」—— 这正是"看不出哪条在跑"的形状。
7. **顺手把思考过程也改了**：那一块（`ReasoningSection`）本单刻意不动；它的默认折叠、
   两句文案、"它还在这里被调用"都是正面证据（单测钉不住 Compose 的这一层）。
8. **判据自己空转**：清单指向不存在的文件、反验脚本失踪、CHG 文档缺节、登记簿 / 工作声明被改名。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
上面这些**没有一条是类型属性**：`true` 与 `false` 同型，`remember` 与 `rememberSaveable`
同型，`if (expanded) { … }` 删掉一层壳仍然合法；「默认折叠 / 整块可点 / 滚动记得住」是**行为**，
类型系统与单测都拦不住（本单新增的单测只钉标题文案，钉不住 Compose 的那三件事）。
所以判据只能落在源码结构上，再配反向验证 `_reverse_verify_ai_trace_collapse.py`（逐条弄坏一次，
看它真的变红）。

静默空转保护：MIN_KT = 100（目录被搬走 / 一个 .kt 都没扫到也必须红）。

## 判据
1. `ui/ai/AiTraceHeader.kt`：纯函数 `traceHeaderLabel(lineCount, running, expanded)`，
   四档文案逐字，且 when 分支顺序是 **expanded > running > lineCount**；
2. `ui/ai/AiChatScreen.kt` 的 `ToolTraceStrip`：默认 `false` + `rememberSaveable(stateKey)`、
   整块 `clickable`、步骤只在 `if (expanded)` 里画、标题来自纯函数、chevron 在标题行右端；
3. 调用点：`ToolTraceStrip(lines = m.toolTrace, running = sending, stateKey = index)`，
   且 `sending` 传的是「最后一条 + 全局忙」的合取（不是全局 `vm.sending`）；
4. 单测 `AiTraceHeaderTest` 钉住四档（含"0 条"与"展开优先"）；
5. 思考过程那一块**一个字没动**（正面证据）；
6. 文书齐（`CHG-0094.md` 九节 ＋ 登记簿 ＋ 工作声明）＋ 反验脚本在。

用法：python _tools/qa/_check_ai_trace_collapse.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
AI_DIR = AND / "ui/ai"
SCREEN = AI_DIR / "AiChatScreen.kt"
HEADER = AI_DIR / "AiTraceHeader.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/ai/AiTraceHeaderTest.kt"
DOC = ROOT / "docs/changes/CHG-0094.md"
REG = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_ai_trace_collapse.py"

#: 全仓至少要有这么多 .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_KT = 100

#: 标题行与每条步骤左边那道细色条（两处都必须是它）。
BAR = "Box(Modifier.size(width = 3.dp, height = 16.dp).background(AiAccent, RoundedCornerShape(2.dp)))"

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

    为什么要这样：本单的"用户原话"就抄在注释里，里面写着「点开进行查看」「折叠」这些
    **看起来像代码判据**的字样 —— 判据要抓的是**代码里**还有没有那三件事。
    """
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit("找不到文件：" + str(p) + "（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def main() -> int:
    c = Checker()
    screen = read(SCREEN)
    header = read(HEADER)
    test = read(TEST)
    screen_code = code_only(screen)
    header_code = code_only(header)

    kt = sorted(AND.rglob("*.kt"))

    print("== 0. 反空转：扫描本身得是活的 ==")
    c.ok("扫到 %d 个 .kt（下限 %d）" % (len(kt), MIN_KT), len(kt) >= MIN_KT)
    c.ok("扫到聊天的那个 .kt", SCREEN.name in {p.name for p in kt})

    print("\n== 1. 标题文案：一个纯函数管三档，顺序是 展开 > 进行中 > 条数 ==")
    c.present(
        "签名与四档逐字（顺序也在这一条里钉住：展开时那句说的是“点下去会发生什么”）",
        header_code,
        r'internal fun traceHeaderLabel\(lineCount: Int, running: Boolean, expanded: Boolean\): String = when \{\s*\n'
        r'\s*expanded -> "收起执行过程"\s*\n'
        r'\s*running -> "执行过程 · 进行中"\s*\n'
        r'\s*lineCount > 0 -> "查看执行过程 · " \+ lineCount \+ " 条"\s*\n'
        r'\s*else -> "查看执行过程"\s*\n\}',
    )
    c.absent(
        "⛔ 条数不是写死的数字（写死之后十步和两步长得一样）",
        header_code,
        r'"查看执行过程 · \d+ 条"',
    )
    c.present("KDoc 里写了优先级（下一个人改之前先读到）", header, r"\*\*展开 > 进行中 > 条数\*\*")
    c.present("KDoc 里说了进行中为什么不带条数（每一步都会 +1，跳字是噪声）", header, r"不带条数")

    print("\n== 2. 折叠块：默认收起、整块可点、步骤只在展开时画 ==")
    c.present(
        "签名：lines ＋ running ＋ stateKey",
        screen_code,
        r"private fun ToolTraceStrip\(lines: List<String>, running: Boolean, stateKey: Any\?\) \{",
    )
    c.present(
        "默认**折叠** ＋ rememberSaveable(键)：滚动一趟回来还在",
        screen_code,
        r"var expanded by rememberSaveable\(stateKey\) \{ mutableStateOf\(false\) \}",
    )
    c.absent(
        "⛔ 默认不许是展开的（改一个 true 就把用户抱怨的那一屏还回来了）",
        screen_code,
        r"var expanded by rememberSaveable\(stateKey\) \{ mutableStateOf\(true\) \}",
    )
    c.present(
        "整块可点（点标题、点空白、点色条都算）",
        screen_code,
        r"\.clickable \{ expanded = !expanded \}\s*\n\s*\.padding\(horizontal = 10\.dp, vertical = 6\.dp\)",
    )
    c.present(
        "步骤只在 if (expanded) 里画（折叠就是真的不画，不是盖住）",
        screen_code,
        r"if \(expanded\) \{\s*\n\s*lines\.forEach \{ line ->",
    )
    c.present(
        "标题来自纯函数（条数传的是 lines.size，不是另算一个数）",
        screen_code,
        r"text = traceHeaderLabel\(lines\.size, running, expanded\),",
    )
    c.present(
        "chevron 在标题行**右端**（标题与步骤行左对齐，长步骤不丢宽度）",
        screen_code,
        r"text = traceHeaderLabel\(lines\.size, running, expanded\),[\s\S]{0,500}?"
        r"Icon\(\s*\n\s*imageVector = if \(expanded\) Icons\.Default\.ExpandLess else Icons\.Default\.ExpandMore,\s*\n"
        r"\s*contentDescription = null,",
    )
    c.ok(
        "两道细色条都还在（标题行一条 ＋ 每条步骤一条）",
        screen_code.count(BAR) == 2,
        "数到 %d 处" % screen_code.count(BAR),
    )
    c.absent("⛔ 旧的一参调用没残留（残留就是有人只改了一半）", screen_code, r"ToolTraceStrip\(m\.toolTrace\)")

    print("\n== 3. 调用点：「进行中」只属于最后一条消息 ==")
    c.present(
        "三个实参：lines / running / stateKey=下标",
        screen_code,
        r"ToolTraceStrip\(lines = m\.toolTrace, running = sending, stateKey = index\)",
    )
    c.present(
        "sending = 全局忙 **且** 这是最后一条（不这么写，历史消息会一起变进行中）",
        screen_code,
        r"m = vm\.messages\[i\],\s*\n\s*index = i,\s*\n(?:\s*\n)*\s*sending = vm\.sending && i == vm\.messages\.lastIndex,",
    )
    c.absent(
        "⛔ 调用点没有把全局 vm.sending 直接传下去",
        screen_code,
        r"m = vm\.messages\[i\],\s*\n\s*index = i,\s*\n(?:\s*\n)*\s*sending = vm\.sending,",
    )

    print("\n== 4. 单测：四档都钉住了（界面侧改错文案会红） ==")
    c.present("有「跑完了 · 几步」这一档", test, r"折叠着跑完了_写查看加条数")
    c.present("有「进行中 · 不带条数」这一档", test, r"折叠着还在跑_写进行中_不带条数")
    c.present("有「展开时说收起」这一档", test, r"展开着_写的是点下去会发生什么_收起")
    c.present("有「一条都没有」这一档（空标题会变成一个看不懂的灰条）", test, r"一条都没有_也不许留一个空标题")
    for literal in ['"查看执行过程 · 6 条"', '"执行过程 · 进行中"', '"收起执行过程"', '"查看执行过程"']:
        c.present("逐字断言 " + literal, test, re.escape(literal))

    print("\n== 5. 思考过程那一块：本单一个字没动（正面证据） ==")
    c.present("ReasoningSection 还在", screen_code, r"private fun ReasoningSection\(reasoning: String\) \{")
    c.present(
        "它的默认折叠还是普通 remember（没被顺手改成 saveable / true）",
        screen_code,
        r"private fun ReasoningSection\(reasoning: String\) \{\s*\n\s*var expanded by remember \{ mutableStateOf\(false\) \}",
    )
    c.present(
        "两句文案还在",
        screen_code,
        r'text = if \(expanded\) "收起思考过程" else "查看思考过程",',
    )
    c.present("它还在被调用", screen_code, r"ReasoningSection\(m\.reasoning\)")

    print("\n== 6. 用户口径留档（下一个人知道为什么给这一串加了个盖子） ==")
    c.present("KDoc 里留了用户原话的 ref " + "`m35906`", screen, "ref `m35906`")
    c.present("KDoc 里留了那句「使得整个界面太过冗余了」", screen, r"使得整个界面太过冗余了")
    c.present("KDoc 里留了台账编号 L-60", screen, r"台账 L-60 / CHG-0094")

    print("\n== 7. 文书与反向验证 ==")
    doc = read(DOC)
    missing = [s for s in SECTIONS if s not in doc]
    c.ok("CHG-0094.md 九节齐全", not missing, "缺：" + " / ".join(missing))
    c.present("登记簿里有 CHG-0094 这一行", read(REG), r"CHG-0094")
    c.present("工作声明里记了这条活", read(CLAIM), r"CHG-0094")
    c.ok("反验脚本在：" + REVERSE.name, REVERSE.exists())

    print("\n" + "=" * 60)
    if c.fails:
        print("❌ %d/%d 项没通过：" % (len(c.fails), c.passes + len(c.fails)))
        for f in c.fails:
            print("   - " + f)
        return 1
    print("✅ 全部 %d 项通过：「执行过程」默认折成一行（标题写着几步 / 进行中），点一下逐条展开，" % c.passes)
    print("   展开态跟着消息下标走；思考过程那一块一个字没动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
