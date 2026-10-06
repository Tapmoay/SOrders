# -*- coding: utf-8 -*-
"""AI 回答的「重要信息用特殊样式」这条红线（2026-10-06，台账 L-24 / CHG-0060）。

## 用户原话
> 「我让他去查订单，他返回只有一个订单……并没有按表格的形式进行展示，还是以文字的形式，
>   这样子很难有可读性」（m00731）
> 「这重要的信息用特殊样式这些样式都可以选择。而如果**信息越重要越要用特殊的颜色**进行搞」（m00779）
> 「我们这个样式**不能随便乱搞** —— 比如说联系人的话，可能就使用统一的样式，
>   什么**数字**、**账本信息**，我们都属于**统一的样式**」（m00779）
> 「这关于特定的表格模板暂时也不需要搞」「其实我们不给模板的话，其实 AI 做得更好」（m00779）
> 「（英文键 → 中文标签）可以啊可以啊……其实也不需要做的很复杂，因为它只是一个信息、
>   重要信息的展示而已，也就是在应用到 AI 的时候才会有，它只展示信息」（m00812）

## 为什么这件事必须有机器的判据
样式这条需求**没有编译期约束**：模型照样能答、界面照样能画，只是"重要的那行没颜色"或
"颜色各写各的"。而这次选的落法（**加粗归模型、颜色归界面**）恰好把风险集中在几个
"一份"和几个"默认值"上，任何一处被下一个人顺手改掉，病就回来：
- 让模型自己写颜色标记 ⇒ 同类信息必然不统一（今天红、明天橙），还常年付提示词 token；
- 判定表散到界面各页各写一份 ⇒ 同一句话在两个页面两种颜色；
- 颜色新造一批十六进制 ⇒ 与设计系统那套语义色脱钩，暗色主题下必然出对比度事故；
- 把颜色也刷到表格单元格上 ⇒ 表格是"中性白卡、不跟随气泡"的既有裁定，一刷就花；
- 给用户自己的消息（蓝底白字）上色 ⇒ 深色字压深蓝底，看不清；
- 「无异常」被当成「异常」⇒ 用户看到红色去核账，其实什么都没发生（**误导**，比丑严重）；
- 上限（条数 / 种类）被拿掉 ⇒ 满屏彩色等于没有重点，正好是用户说的"乱搞"。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。"哪一行算重要信息"是展示层判断：
后端出参里没有"重要"这个字段，模型也没被允许写颜色标记，数据库更不知道用户在看什么。
它守的是三件跨文件的口径 —— **判定表只有一份**（ai/AiAnswerTone.kt）、
**颜色只借设计系统的语义色**（ui/theme/Color.kt 的别名 token）、
**加粗与颜色分工固定**（模型只加粗、界面只上色）；任意少一件，这次的需求就只做了一半。

用法：
    python _tools/qa/_check_ai_answer_style.py
    python _tools/qa/_check_ai_answer_style.py --list
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from _airepo import refuse_if_injecting  # noqa: E402
from _check_product_card_single_source import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
TESTDIR = ROOT / "android/app/src/test/java/com/tapmoay/sorders"

TONE = AND / "ai/AiAnswerTone.kt"
LABELS = AND / "ai/AiFieldLabels.kt"
MARKDOWN = AND / "ai/AiMarkdown.kt"
ROW = AND / "ai/AiRowShaper.kt"
STYLE = AND / "ai/AiAnswerStyle.kt"
LOOP = AND / "ai/AiAgentLoop.kt"
RICH = AND / "ui/ai/AiRichText.kt"
CHAT = AND / "ui/ai/AiChatScreen.kt"
COLOR = AND / "ui/theme/Color.kt"
DOC = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

TONE_TEST = TESTDIR / "ai/AiAnswerToneTest.kt"
LABEL_TEST = TESTDIR / "ai/AiFieldLabelsTest.kt"
STYLE_TEST = TESTDIR / "ai/AiAnswerStyleTest.kt"
ROW_TEST = TESTDIR / "ai/AiRowShaperTest.kt"

REVERSE = "_tools/qa/_reverse_verify_ai_answer_style.py"

#: 本刀的立项与收口（判据自己盯住它 —— 文档烂掉了没人说话）
CHG_ID = "CHG-0060"
CHG_DOC = ROOT / "docs/changes/CHG-0060.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

#: 九节标题逐字（光数圈码会被正文里的「①」蒙混过去）
CHG_SECTIONS = (
    "## ① 六问",
    "## ② Must Change / Must Not Change",
    "## ③ Boundary",
    "## ④ Behavior Contract",
    "## ⑤ Data Contract",
    "## ⑥ CHG 专章",
    "## ⑦ 测试",
    "## ⑧ 证据",
    "## ⑨ 关闭",
)

#: 四档颜色 —— 只允许是**既有语义色的别名**（⛔ 一个新色都不许造）
TONES = (
    ("AiToneDanger", "DangerRed"),
    ("AiToneMoney", "MoneyOrange"),
    ("AiToneWarn", "WarningAmber"),
    ("AiToneOk", "SuccessGreen"),
)

#: 认识 AiAnswerTone 的界面文件（**只有这些** —— 判定表散出去就必然不统一）
OWNERS = ("AiAnswerTone.kt", "AiRichText.kt")

#: 扫到的界面文件数下限（防目录改名/搬走之后「一个文件都没扫到」也算过）
MIN_UI_FILES = 100

#: 抽出来的函数体字符数下限（抽取失效比判据腐烂更危险 —— 那会变成一条永远绿的检查）
BODY_FLOOR = 80


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def subs(text: str, needle: str) -> int:
    """子串出现次数。

    ⚠️ 这里**故意用纯字符串**而不是正则：锚点里全是 ( ) . [ ] 这类正则元字符
    （如 `AiAnswerTone.apply(` ），当正则用会静默匹配到别的东西，判据就成了假的。
    """
    return text.count(needle)


def first(text: str, needle: str) -> int:
    """needle 首次出现的位置（取不到返回一个很大的数 —— 让"谁在前"的比较判红）。"""
    i = text.find(needle)
    return i if i >= 0 else 10 ** 9


def after(text: str, needle: str, span: int) -> str:
    i = text.find(needle)
    return text[i : i + span] if i >= 0 else ""


def fn_body(src: str, sig: str) -> str:
    """sig 那个函数的**函数体**（按大括号配对，不是按行猜）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    b = src.find("{", i)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[b : j + 1]
    return ""


def files_with(needle: str) -> list[str]:
    """界面文件里**代码**含 needle 的那些（注释先剥掉 —— 文档里提一句名字不算又抄一份）。"""
    return sorted(p.name for p in AND.rglob("*.kt") if needle in code(p))


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

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def main() -> int:
    if refuse_if_injecting("AI 回答样式检查"):
        return 1

    c = Checker()
    print("AI 回答「重要信息用特殊样式」：2026-10-06（台账 L-24 / CHG-0060）")

    ui_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(ui_files) >= MIN_UI_FILES,
        f"实际 {len(ui_files)}",
    )

    tone = code(TONE)
    labels = code(LABELS)
    markdown = code(MARKDOWN)
    rich = code(RICH)
    chat = code(CHAT)
    color = code(COLOR)
    row = code(ROW)
    style = code(STYLE)
    loop = code(LOOP)
    doc = read(DOC)

    # ---- 1. 判定表只有一份，且四类齐全 ----
    c.ok(
        "AiAnswerTone.kt 在，四档颜色齐全（钱 / 危险 / 提醒 / 正常）",
        all(f"AnswerTone.{n}" in tone for n in ("MONEY", "DANGER", "WARN", "OK")),
    )
    c.ok(
        "判定表只有一份（认识 AiAnswerTone 的文件恰好这两个：判定表自己 + 渲染器）",
        files_with("AiAnswerTone") == list(OWNERS),
        f"实际：{'、'.join(files_with('AiAnswerTone')) or '一个都没有'}",
    )
    c.ok(
        "判定逻辑是 internal object（外面拿得到枚举，拿不到「哪句算什么色」的规则）",
        "internal object AiAnswerTone" in tone,
    )
    c.ok(
        "枚举是公开的（Span 是公开数据类，internal 类型进不了它的构造参数 —— 编译期硬约束）",
        "enum class AnswerTone { MONEY, DANGER, WARN, OK }" in tone
        and "internal enum class AnswerTone" not in tone,
    )

    # ---- 2. 三条上限（没有上限就是"满屏彩色"，正好是用户说的乱搞）----
    for name, want in (("MAX_TONED", 12), ("MAX_KINDS", 2), ("MAX_CHARS", 16)):
        c.ok(
            f"上限 {name} = {want}",
            # ⚠️ 必须卡词边界：反向验证注入过 "MAX_TONED: Int = 1200" —— 子串匹配照样绿（上限形同虚设）。
            bool(re.search(rf"const val {name}: Int = {want}\b", tone)),
            after(tone, f"const val {name}", 40).strip(),
        )
    c.ok(
        "上限真的被用上（染色前判条数、判种类）",
        "toned >= MAX_TONED" in tone and "kinds.size < MAX_KINDS" in tone,
    )
    c.ok(
        "长句与带句读的片段不上色（值才上色，叙述句不上色）",
        "t.length > MAX_CHARS" in tone and "CLAUSE_MARKS.any { it in t }" in tone,
    )

    # ---- 3. 「无异常」必须先判掉（否则红字误导）----
    c.ok(
        "先判「不是坏消息」：「无异常 / 没有异常 / 无风险 / 已恢复」在表里",
        all(w in tone for w in ("无异常", "没有异常", "无风险", "已恢复")),
    )
    c.ok(
        "而且**排在** 危险词表之前（顺序反了就等于没写）",
        first(tone, "NOT_DANGER.any") < first(tone, "DANGER.any {"),
        "NOT_DANGER 的判定必须早于 DANGER",
    )

    # ---- 4. 表格不掺一脚 ----
    c.ok(
        "表格原样返回（不参与上色）",
        "if (b !is AiMarkdown.Block.Line)" in tone,
        after(tone, "fun apply(", 400),
    )
    c.ok(
        "渲染器的表格分支一个字节没动（还是中性白卡那一份）",
        "is AiMarkdown.Block.Table -> MdTable(b, fontSize = TableFontSize)" in rich,
    )
    c.ok(
        "整条回答只调一次判定（没有第二处染色入口）",
        subs(rich, "AiAnswerTone.apply(") == 1,
        f"实际 {subs(rich, 'AiAnswerTone.apply(')} 处",
    )

    # ---- 5. 行内片段带 tone，且默认不上色 ----
    c.ok(
        "AiMarkdown.Span 带 tone，默认 null（既有构造与单测不受影响）",
        "data class Span(val text: String, val bold: Boolean = false, val tone: AnswerTone? = null)"
        in markdown,
    )
    c.ok(
        "只改 tone 与颜色，text / bold 一个字不改",
        "s.copy(tone = t)" in tone and "copy(text" not in tone,
    )

    # ---- 6. 颜色只借设计系统的语义色 ----
    for alias, base in TONES:
        c.ok(
            f"Color.kt 里 {alias} = {base}（借用既有语义色，不新造色）",
            f"val {alias} = {base}" in color,
            after(color, f"val {alias}", 40).strip(),
        )
    c.ok(
        "渲染器里没有裸十六进制色（Color(0x 一处都不许有）",
        "Color(0x" not in rich,
    )
    c.ok(
        "四档颜色在渲染器里逐档映射到 token",
        all(f"Color({alias})" in rich for alias, _ in TONES),
    )
    c.ok(
        "四档之外没有第五档（when 的 else 分支不许悄悄兜底）",
        "null -> Color.Unspecified" in rich and "else ->" not in fn_body(rich, "private fun toneColor"),
        fn_body(rich, "private fun toneColor")[:120],
    )

    # ---- 7. 渲染器：颜色由界面自动上，用户气泡不上色 ----
    body = fn_body(rich, "fun AiRichText(")
    c.ok(
        f"AiRichText 的函数体抽得出来（≥ {BODY_FLOOR} 字符，防锚点腐烂成空转）",
        len(body) >= BODY_FLOOR,
        f"实际 {len(body)} 字符",
    )
    c.ok(
        "默认给助手气泡上色（toned 默认 true）",
        "toned: Boolean = true," in rich,
    )
    c.ok(
        "上色只在解析之后做一次，且跟着 toned 开关走",
        "val blocks = remember(text, toned) {" in rich
        and "if (toned) AiAnswerTone.apply(parsed) else parsed" in rich,
    )
    c.ok(
        "行块把开关传下去（annotated(toned)）",
        "line.annotated(toned)" in rich and "toned: Boolean," in rich,
    )
    c.ok(
        "用户自己发的消息不上色（蓝底白字，上色会看不清）",
        "toned = !isUser," in chat and "val isUser = m.role == Role.USER" in chat,
        f"调用点 {subs(chat, 'toned = !isUser,')} 处",
    )
    c.ok(
        "只有那一个调用点，且没人把开关写死成 true",
        subs(chat, "toned = ") == 1 and "toned = true" not in chat,
        f"实际 {subs(chat, 'toned = ')} 处",
    )

    # ---- 8. 键名映射：只做一层薄表、只作用在 AI 读回答这一处 ----
    c.ok(
        "标签表只有一份（认识 AiFieldLabels 的文件恰好这两个：定义 + 整形）",
        files_with("AiFieldLabels") == ["AiFieldLabels.kt", "AiRowShaper.kt"],
        f"实际：{'、'.join(files_with('AiFieldLabels')) or '一个都没有'}",
    )
    c.ok(
        "认不出来就原样返回（宁可露英文，也不要猜错标签）",
        "fun of(key: String): String = LABELS[key] ?: key" in labels,
    )
    c.ok(
        "表至少 30 条（太薄等于没做）",
        labels.count(" to \"") >= 30,
        f"实际 {labels.count(' to \"')} 条",
    )
    c.ok(
        "换标签是整形的**最后一步**（跑到 normalizeNames 前面就认不出 name 类字段了）",
        "AiFieldLabels.apply(normalizeNames(stripAndFlatten(row, allowCost)))" in row,
    )

    # ---- 9. 提示词两侧同上（模型只管加粗，颜色交给界面）----
    c.ok(
        "规范里写明了「同一类信息永远用同一套写法」",
        "9.1 **同一类信息永远用同一套写法**" in style and "样式不能随便乱搞" in style,
    )
    c.ok(
        "规范里写明了「颜色由界面自动上，你不用写颜色标记」",
        "9.2 **颜色由界面按类别自动上，你不用写任何颜色标记**" in style,
    )
    c.ok(
        "规范里写明了「只有一条也要分行」（用户那次就是只返回一条、被写成一段话）",
        "**只有一条也要分行**" in style and "标签：值" in style,
    )
    c.ok(
        "既有规则一条没丢（超过 3 项 / 表格最多 4 列 / 只讲结果）",
        "**超过 3 项**" in style
        and "表格**最多 4 列**" in style
        and "只讲结果，不讲过程" in style,
    )
    c.ok(
        "提示词结尾仍然钉着【最后再确认两件事】（反向验证按这四个字注入）",
        'appendLine("【最后再确认两件事】")' in loop,
    )
    c.ok(
        "结尾第 2 条同步改成「有几条写几行」，并说了颜色由界面自己上",
        "2. 结果里有几条就写几行" in loop and "颜色由界面自己上" in loop,
    )

    # ---- 10. 单测 / 规范 / 反向验证都在 ----
    t = read(TONE_TEST)
    c.ok(
        "AiAnswerToneTest 钉着四类、无异常反例、三条上限",
        t.count("@Test") >= 6
        and "AnswerTone.MONEY" in t
        and "无异常" in t
        and "MAX_TONED" in t
        and "CLAUSE" not in t,
        f"@Test {t.count('@Test')} 条",
    )
    lt = read(LABEL_TEST)
    c.ok(
        "AiFieldLabelsTest 钉着「标签两两不同」与「整形出来是中文键」",
        "LABELS.values" in lt and "AiRowShaper.shape(" in lt and "原样返回" in lt,
    )
    c.ok(
        "样式测试仍然读提示词真的那一份（不是复制一份到测试里）",
        "AiAnswerStyle.RULES" in read(STYLE_TEST),
    )
    rt = read(ROW_TEST)
    c.ok(
        "整形测试跟着换成中文键（不然它测的是已经不存在的形状）",
        "货款" in rt and "订单号" in rt,
    )
    c.ok(
        "设计规范里记着这条（否则下一个人还会给模型塞一套颜色标记）",
        "AiAnswerTone" in doc and "重要信息" in doc,
        "06_DESIGN_SYSTEM.md 里没记这条",
    )
    c.ok(
        "这条红线配了反向验证脚本",
        (ROOT / REVERSE).exists(),
        f"找不到 {REVERSE}",
    )

    # ---- 11. 接线：CHG 文档 / 登记簿 / 工作声明 ----
    chg = read(CHG_DOC)
    c.ok(
        "CHG 文档在，且标题就是这一条（文件名 → 正文 ID 一致）",
        bool(chg) and f"{CHG_ID} ·" in chg.splitlines()[0],
        f"找不到 {CHG_DOC.name}，或者第一行标题里没有 {CHG_ID}",
    )
    c.ok(
        "文档九节齐全（docs/changes/CHG-0060.md）",
        all(s in chg for s in CHG_SECTIONS),
        "文档缺节（_check_dev_spec.py 也会红）",
    )
    c.ok(
        "登记簿里有 CHG-0060 这一行（整行，不是一个链接里的字样）",
        bool(re.search(r"^\|\s*[\x60]?CHG-0060[\x60]?\s*\|", read(REGISTRY), re.M)),
        "没登记（别人不知道这个 ID 用掉了）",
    )
    c.ok(
        "工作声明里有 CHG-0060 这一条",
        CHG_ID in read(CLAIM),
        "AI_WORK_CLAIM.md 里没有这一条",
    )

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 判定表只有一份（定义 + 渲染器 + 片段模型三个文件）；枚举公开、规则 internal")
        print("     · 三条上限：最多 12 处 / 最多 2 种颜色 / 只有 ≤16 字的短片段才上色")
        print("     · 「无异常 / 没有异常 / 无风险 / 已恢复」先判，且排在危险词表之前")
        print("     · 表格原样返回、渲染器的表格分支没动、整条回答只有一处染色入口")
        print("     · 颜色只用 Color.kt 里四个语义色的别名；渲染器里没有裸十六进制")
        print("     · 用户气泡不上色（toned = !isUser，全文件只有这一处传开关）")
        print("     · 英文键 → 中文标签只有一份，只用在 AI 读回答这一处，认不出就原样返回")
        print("     · 提示词 9.1 / 9.2 与结尾第 2 条同上；既有规则一条没丢")
        print("     · 新单测 / 整形测试的中文键 / 设计规范 / 反向验证脚本都在")
        print("     · 接线：CHG-0060.md 九节齐全 / 登记簿里一整行 / 工作声明里有这一条")

    return c.report("AI 回答「重要信息用特殊样式」")


if __name__ == "__main__":
    sys.exit(main())
