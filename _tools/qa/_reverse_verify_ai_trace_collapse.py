# -*- coding: utf-8 -*-
"""反向验证「AI 助手的执行过程默认折叠」这条红线**真的会红**（2026-10-09，台账 L-60 / CHG-0094）。

## 为什么这条要反向验证
它的判据大多是「源码里必须出现某个零件、某一种口径」＋「思考过程那一块不许被顺手改」，这类判据有三种典型失效方式：

1. **判据变成空转**：判据清单被指向一个不存在的文件、或者反验脚本自己没了，它会安静地全绿 —— 本脚本把 `HEADER` 指向不存在的文件、把 `REVERSE` 也改名，两处都必须报红。
2. **只认名字不认形状**：`ToolTraceStrip` 这个名字还在、语义已经不对。比如默认又变回展开（用户抱怨的那一屏回来了）、`rememberSaveable` 退回普通 `remember`（滚一趟回来展开态就丢）、步骤不再放在 `if (expanded)` 里（折叠只是把它盖住）、chevron 挪到标题行最左端、条数写死成一个数字 —— 整文件扫的话照样绿，只有分别注入才知道判据认不认。
3. **口径被单方面改掉**：标题三档的顺序被调反、单测里「进行中」那一档被删、思考过程被顺手改成默认展开或文案被改、CHG 文档少一节、登记簿 / 工作声明那一条被改名。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过「注入把 bug 留在源码里」）。

R4-BOUNDARY-JUSTIFICATION: 本脚本只读写工作区里的 7 个文件（注入后按字节还原），
不编译、不跑 UI、不连后端 —— 它证明的是「这条红线自己不会说谎」，不是功能本身。

用法：python _tools/qa/_reverse_verify_ai_trace_collapse.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_ai_trace_collapse.py"
CHECK_REL = "_tools/qa/_check_ai_trace_collapse.py"

AND = "android/app/src/main/java/com/tapmoay/sorders/"
SCREEN = AND + "ui/ai/AiChatScreen.kt"
HEADER = AND + "ui/ai/AiTraceHeader.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ui/ai/AiTraceHeaderTest.kt"
CHG_DOC = "docs/changes/CHG-0094.md"
CHG_REG = "docs/changes/README.md"
CHG_CLAIM = "docs/AI_WORK_CLAIM.md"

DEFAULT_FOLD = "var expanded by rememberSaveable(stateKey) { mutableStateOf(false) }"
HEADER_ROW = """            Text(
                text = traceHeaderLabel(lines.size, running, expanded),
                modifier = Modifier.weight(1f),
                fontSize = TraceTextSize,
                lineHeight = 20.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            // 装饰性图标：右边那句标题已经把意思说全了，别让读屏软件念第二遍
            Icon(
                imageVector = if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(16.dp),
            )"""
ICON_FIRST = """            Icon(
                imageVector = if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(16.dp),
            )
            Text(
                text = traceHeaderLabel(lines.size, running, expanded),
                modifier = Modifier.weight(1f),
                fontSize = TraceTextSize,
                lineHeight = 20.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )"""
REASON_FOLD = "private fun ReasoningSection(reasoning: String) {\n    var expanded by remember { mutableStateOf(false) }"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 默认又变回展开（用户抱怨的那一屏回来了）",
        SCREEN,
        lambda s: s.replace(DEFAULT_FOLD, "var expanded by rememberSaveable(stateKey) { mutableStateOf(true) }", 1),
        "默认**折叠**",
    ),
    (
        "② rememberSaveable 退回普通 remember（滚一趟回来展开态就没了）",
        SCREEN,
        lambda s: s.replace(DEFAULT_FOLD, "var expanded by remember { mutableStateOf(false) }", 1),
        "rememberSaveable(键)",
    ),
    (
        "③ 步骤不再放在 if (expanded) 里（折叠只是把它盖住）",
        SCREEN,
        lambda s: s.replace("        if (expanded) {\n            lines.forEach { line ->", "        if (true) {\n            lines.forEach { line ->", 1),
        "折叠就是真的不画",
    ),
    (
        "④ 整块不再可点（点标题没反应）",
        SCREEN,
        lambda s: s.replace(
            "            .background(MaterialTheme.colorScheme.surfaceContainer)\n            .clickable { expanded = !expanded }\n",
            "            .background(MaterialTheme.colorScheme.surfaceContainer)\n",
            1,
        ),
        "整块可点",
    ),
    (
        "⑤ chevron 挪到标题行最左端（标题与步骤行就错开了）",
        SCREEN,
        lambda s: s.replace(HEADER_ROW, ICON_FIRST, 1),
        "chevron 在标题行",
    ),
    (
        "⑥ 标题不再报条数（十步和两步长得一样）",
        HEADER,
        lambda s: s.replace('lineCount > 0 -> "查看执行过程 · " + lineCount + " 条"', 'lineCount > 0 -> "查看执行过程"', 1),
        "签名与四档逐字",
    ),
    (
        "⑦ 把「进行中」那一档删掉（跑的时候和跑完看起来一样）",
        HEADER,
        lambda s: s.replace('    running -> "执行过程 · 进行中"\n', "", 1),
        "签名与四档逐字",
    ),
    (
        "⑧ 把三档顺序调反（展开时那句写着还在跑）",
        HEADER,
        lambda s: s.replace(
            '    expanded -> "收起执行过程"\n    running -> "执行过程 · 进行中"\n',
            '    running -> "执行过程 · 进行中"\n    expanded -> "收起执行过程"\n',
            1,
        ),
        "顺序也在这一条里钉住",
    ),
    (
        "⑨ 条数写死成一个数字",
        HEADER,
        lambda s: s.replace('"查看执行过程 · " + lineCount + " 条"', '"查看执行过程 · 6 条"', 1),
        "条数不是写死的数字",
    ),
    (
        "⑩ 调用点改回把全局 vm.sending 直接传下去（每条历史消息都变进行中）",
        SCREEN,
        lambda s: s.replace("sending = vm.sending && i == vm.messages.lastIndex,", "sending = vm.sending,", 1),
        "全局忙 **且** 这是最后一条",
    ),
    (
        "⑪ 单测里「进行中 · 不带条数」那一档被删",
        TEST,
        lambda s: s.replace("折叠着还在跑_写进行中_不带条数", "折叠着还在跑_写进行中", 1),
        "进行中 · 不带条数",
    ),
    (
        "⑫ 思考过程被顺手改成默认展开",
        SCREEN,
        lambda s: s.replace(REASON_FOLD, REASON_FOLD.replace("mutableStateOf(false)", "mutableStateOf(true)"), 1),
        "它的默认折叠还是普通 remember",
    ),
    (
        "⑬ 思考过程那两句文案被改",
        SCREEN,
        lambda s: s.replace('text = if (expanded) "收起思考过程" else "查看思考过程",', 'text = if (expanded) "收起" else "查看",', 1),
        "两句文案还在",
    ),
    (
        "⑭ 判据清单指向一个不存在的源文件",
        CHECK_REL,
        lambda s: s.replace('HEADER = AI_DIR / "AiTraceHeader.kt"', 'HEADER = AI_DIR / "AiTraceHeaderGone.kt"', 1),
        "找不到文件",
    ),
    (
        "⑮ 反验脚本自己不见了（判据最后一节要抓）",
        CHECK_REL,
        lambda s: s.replace(
            'REVERSE = ROOT / "_tools/qa/_reverse_verify_ai_trace_collapse.py"',
            'REVERSE = ROOT / "_tools/qa/_reverse_verify_ai_trace_collapse_gone.py"',
            1,
        ),
        "反验脚本在",
    ),
    (
        "⑯ CHG 文档少一节（模板九节缺一）",
        CHG_DOC,
        lambda s: s.replace("## ⑨ 关闭（六格）", "## ⑨ 关闭", 1),
        "九节齐全",
    ),
    (
        "⑰ 登记簿里这一行被改名（变更单对不上账）",
        CHG_REG,
        lambda s: s.replace("CHG-0094", "CHG-0095"),
        "登记簿里有 CHG-0094 这一行",
    ),
    (
        "⑱ 工作声明里这一条被改名",
        CHG_CLAIM,
        lambda s: s.replace("CHG-0094", "CHG-0095"),
        "工作声明里记了这条活",
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
