# -*- coding: utf-8 -*-
"""反向验证「AI 回答的重要信息」这条红线**真的会红**（2026-10-06，台账 L-24 / CHG-0060）。

## 为什么这条要反向验证
它的判据大多是「某段代码/提示词里必须出现某个零件、某一种口径」，这类判据有三种典型失效方式：

1. **判据变成空转**：判定表被改名/搬走、或者判据清单指向一个不存在的文件之后，
   它会安静地全绿 —— 本脚本把 TONE 常量指向不存在的文件，必须报红。
2. **只认名字不认形状**：名字还在、语义已经不对。比如开关不再往下传
   （`line.annotated(toned)` 变成写死 false）、渲染器默认把上色关掉、
   认不出来的键不再原样返回（宁可猜一个错标签）—— 文件里那个标识符一个都没少，
   整文件扫的话照样绿。
3. **口径被单方面改掉**：提示词 9.1/9.2 或结尾那条被删、单测里那条反例被换掉、
   设计规范那一段被改成别的名字 —— 这几条各自都"看起来还在"，只有分别注入才知道判据认不认。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过「注入把 bug 留在源码里」）。

R4-BOUNDARY-JUSTIFICATION: 本脚本只读写工作区里的 15 个文件（注入后按字节还原），
不编译、不跑 UI、不连后端 —— 它证明的是「这条红线自己不会说谎」，不是功能本身。

用法：python _tools/qa/_reverse_verify_ai_answer_style.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_ai_answer_style.py"
CHECK_REL = "_tools/qa/_check_ai_answer_style.py"

AND = "android/app/src/main/java/com/tapmoay/sorders/"
TONE = AND + "ai/AiAnswerTone.kt"
LABELS = AND + "ai/AiFieldLabels.kt"
ROW = AND + "ai/AiRowShaper.kt"
STYLE = AND + "ai/AiAnswerStyle.kt"
LOOP = AND + "ai/AiAgentLoop.kt"
RICH = AND + "ui/ai/AiRichText.kt"
CHAT = AND + "ui/ai/AiChatScreen.kt"
SKILLS = AND + "ai/AiAnswerSkills.kt"
SHAPE = AND + "ai/AiAnswerShape.kt"
TONE_TEST = "android/app/src/test/java/com/tapmoay/sorders/ai/AiAnswerToneTest.kt"
DOC = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
CHG_DOC = "docs/changes/CHG-0060.md"
CHG_REG = "docs/changes/README.md"
CHG_CLAIM = "docs/AI_WORK_CLAIM.md"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 判定表被摘掉两档（钱 / 提醒 / 正常只剩一半 ⇒ 上色成了随机）",
        TONE,
        lambda s: s.replace(
            "enum class AnswerTone { MONEY, DANGER, WARN, OK }",
            "enum class AnswerTone { MONEY, WARN }",
            1,
        ),
        "四档",
    ),
    (
        "② 条数上限被改大（整篇都在染色 ＝ 没染）",
        TONE,
        lambda s: s.replace("    const val MAX_TONED: Int = 12", "    const val MAX_TONED: Int = 1200", 1),
        "MAX_TONED",
    ),
    (
        "③ 种类上限被改大（一条回答四种颜色，重点不成重点）",
        TONE,
        lambda s: s.replace("    const val MAX_KINDS: Int = 2", "    const val MAX_KINDS: Int = 9", 1),
        "MAX_KINDS",
    ),
    (
        "④ 「无异常 / 没有异常 / 无风险」那条被删（红色砸在什么都没发生的人头上）",
        TONE,
        lambda s: s.replace(
            '    private val NOT_DANGER = listOf("无异常", "没有异常", "无风险", "已恢复")',
            '    private val NOT_DANGER = listOf("已恢复")',
            1,
        ),
        "不是坏消息",
    ),
    (
        "⑤ 开关不再往下传（行块写死 false ⇒ 助手气泡一个颜色都没有）",
        RICH,
        lambda s: s.replace("    val annotated = line.annotated(toned)", "    val annotated = line.annotated(false)", 1),
        "开关传下去",
    ),
    (
        "⑥ 渲染器默认把上色关掉（默认值一改，全 App 回答都回到黑白）",
        RICH,
        lambda s: s.replace("    toned: Boolean = true,", "    toned: Boolean = false,", 1),
        "默认给助手气泡上色",
    ),
    (
        "⑦ 用户气泡那行被写死成 true（蓝底白字上再上色，看不清）",
        CHAT,
        lambda s: s.replace("toned = !isUser,", "toned = true,", 1),
        "不上色",
    ),
    (
        "⑧ 认不出来的键不再原样返回（宁可猜一个错标签 —— 这是误导）",
        LABELS,
        lambda s: s.replace(
            "    fun of(key: String): String = LABELS[key] ?: key",
            '    fun of(key: String): String = LABELS[key] ?: ""',
            1,
        ),
        "原样返回",
    ),
    (
        "⑨ 换标签挪到名字兜底**之前**（name / shipper_name 这类键就认不出来了）",
        ROW,
        lambda s: s.replace(
            "        AiFieldLabels.apply(normalizeNames(stripAndFlatten(row, allowCost)))",
            "        normalizeNames(AiFieldLabels.apply(stripAndFlatten(row, allowCost)))",
            1,
        ),
        "最后一步",
    ),
    (
        "⑩ 提示词 9.2（颜色归界面）那一行被删（模型又开始自己发明颜色）",
        STYLE,
        lambda s: s.replace('        appendLine("9.2 **颜色由界面按类别自动上，你不用写任何颜色标记**：")\n', "", 1),
        "颜色由界面",
    ),
    (
        "⑪ 结尾那条被删（只改开头不改结尾 —— 模型会「读过去」）",
        LOOP,
        lambda s: s.replace(
            '            appendLine("   颜色由界面自己上，你不用写任何颜色标记；要强调就把那个值 **加粗**，一条回答最多 3 处。")\n',
            "",
            1,
        ),
        "结尾第 2 条",
    ),
    (
        "⑫ 单测里「无异常」那条反例被换掉（谁把这四个字删了都没人说话）",
        TONE_TEST,
        lambda s: s.replace("无异常", "一切正常"),
        "AiAnswerToneTest",
    ),
    (
        "⑬ 判据清单指向不存在的文件（红线变成空转）",
        CHECK_REL,
        lambda s: s.replace(
            'TONE = AND / "ai/AiAnswerTone.kt"',
            'TONE = AND / "ai/AiAnswerToneGone.kt"',
            1,
        ),
        "四档",
    ),
    (
        "⑭ 反向验证脚本自己不见了（新红线没配反向验证）",
        CHECK_REL,
        lambda s: s.replace(
            'REVERSE = "_tools/qa/_reverse_verify_ai_answer_style.py"',
            'REVERSE = "_tools/qa/_reverse_verify_ai_answer_style_gone.py"',
            1,
        ),
        "反向验证",
    ),
    (
        "⑮ 设计规范那一段被改成别的名字（下一个人还会给模型塞一套颜色标记）",
        DOC,
        lambda s: s.replace("AiAnswerTone", "AiAnswerHue"),
        "设计规范",
    ),
    (
        "⑯ CHG 文档少一节（收口文档烂掉了没人说话）",
        CHG_DOC,
        lambda s: s.replace("## ⑨ 关闭", "## 九 关闭", 1),
        "文档九节齐全",
    ),
    (
        "⑰ 登记簿那一行被挪走（别人不知道这个 ID 用掉了）",
        CHG_REG,
        lambda s: s.replace("| `CHG-0060` | CHG |", "| `CHG-0061` | CHG |", 1),
        "登记簿",
    ),
    (
        "⑱ 工作声明里那条被改名（这条活干完了却查不到）",
        CHG_CLAIM,
        lambda s: s.replace("CHG-0060 AI 回答里的", "CHG-0061 AI 回答里的", 1),
        "工作声明",
    ),
    (
        "⑲ 呈现技能没拼进提示词（写了没人用 —— 模型还是照旧写成散行）",
        LOOP,
        lambda s: s.replace("            append(AiAnswerSkills.RULES)\n", "", 1),
        "技能拼进了 system prompt",
    ),
    (
        "⑳ 形状表里「问题单独一行放最后」那条被删（截图里问题就是和信息连在一句里的）",
        SKILLS,
        lambda s: s.replace("**单独一行、放在最后**；⛔ 不要塞进字段行里", "**放最后**", 1),
        "单独一行、放在最后",
    ),
    (
        "㉑ 兜底自己写一份冒号切分（两份判定迟早走散：同一句话在确认卡里是表、在回答里是散行）",
        SHAPE,
        lambda s: s.replace(
            "        val pair = AiCardTable.asPair(text) ?: return null",
            "        val i = text.indexOfFirst { it == '：' || it == ':' }\n"
            "        val pair = if (i > 0) AiCardTable.Row.Pair(text.substring(0, i), text.substring(i + 1)) else null\n"
            "        if (pair == null) return null",
            1,
        ),
        "复用",
    ),
    (
        "㉒ 兜底不再限定块类型（标题、编号步骤、模型自己写的表全被吸进表）",
        SHAPE,
        lambda s: s.replace(
            "        if (line.kind != AiMarkdown.Block.Kind.TEXT && line.kind != AiMarkdown.Block.Kind.BULLET) return null\n",
            "",
            1,
        ),
        "只吸普通文本",
    ),
    (
        "㉓ 渲染器改回「无表头直接 return」（兜底补出来的表整块消失）",
        RICH,
        lambda s: s.replace(
            "    val hasHeader = table.header.any { it.isNotBlank() }\n"
            "    if (!hasHeader && table.body.isEmpty()) return",
            "        if (table.header.isEmpty()) return",
            1,
        ),
        "无表头的表",
    ),
    (
        "㉔ 值上限被放宽成 2400（整句话也能进单元格，表格被撑成一团）",
        SHAPE,
        lambda s: s.replace("    const val MAX_VALUE_WIDTH: Int = 24", "    const val MAX_VALUE_WIDTH: Int = 2400", 1),
        "MAX_VALUE_WIDTH",
    ),
    (
        "㉕ 顺序调成「先上色、再补形状」（染色名额花在即将变成表格的行上）",
        RICH,
        lambda s: s.replace(
            "        val shaped = if (toned) AiAnswerShape.apply(parsed) else parsed\n"
            "        if (toned) AiAnswerTone.apply(shaped) else shaped",
            "        val tinted = if (toned) AiAnswerTone.apply(parsed) else parsed\n"
            "        val shaped = if (toned) AiAnswerShape.apply(tinted) else tinted",
            1,
        ),
        "顺序：先补形状",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        # 按行尾归一后再替换（Windows 上 Kotlin 文件可能是 CRLF），写回时按原样还原
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated.replace("\r\n", "\n")
            if crlf:
                out_txt = out_txt.replace("\n", "\r\n")
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print(f"  [OK] {label} → 报红")
        else:
            fails.append(f"{label}：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print(f"  [MISS] {label} → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
