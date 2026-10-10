# -*- coding: utf-8 -*-
r"""AI 助手那一页的单色强调由 Google 蓝改成主题绿（CHG-0093），一条条被真的破坏一次。

一条红线要能被「真的破坏一次」证明它在检查：下面每一条注入都只改一处，然后要求
_tools/qa/_check_ai_accent_green.py 报红，而且报的是**这一条**（关键词比对）。
跑完按字节还原，再逐字节核对 —— 一个字节都不许留在工作区。

这一组破坏方式的来路都是真实会发生的改法：强调色悄悄退回 Google 蓝、设置页没跟上
（那是**另一处**定义）、发送键退回与三颗图标同色（用户点名要的"稍微的区别"被抹掉）、
两档区别被抹平（"看不清"那个老毛病）、`onClick` / `enabled` / 尺寸被"顺手整理"、
以及**越权**去动品牌三段渐变（它的两个消费者与那三个 token）。
⛔ 锚点一律写文件里的真实长相；缩进敏感的地方用 re.sub，免得数空格数错。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_ai_accent_green.py"

SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiChatScreen.kt"
SETTINGS = "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiSettingsScreen.kt"
BRAND = "android/app/src/main/java/com/tapmoay/sorders/ui/theme/AiBrand.kt"
HOME = "android/app/src/main/java/com/tapmoay/sorders/ui/home/RoleHomeScreen.kt"

NL = chr(10)

#: 注入：只把**颜色的身份**退回去（换一个同样合法的颜色），类型/编译全都照样通过。
CASES: list[tuple[str, str, object, str]] = [
    (
        "强调色退回 Google 蓝（这一页 25 个消费点一起变回蓝）",
        SCREEN,
        lambda s: s.replace("private val AiAccent = Color(AiChatGreen)",
                            "private val AiAccent = Color(AiBlue)", 1),
        "AiAccent = AI 页自己的绿",
    ),
    (
        "import 又回到 AiBlue（用途已经没了，留着的就是死 import）",
        SCREEN,
        lambda s: s.replace("import com.tapmoay.sorders.ui.theme.AiChatGreen" + NL,
                            "import com.tapmoay.sorders.ui.theme.AiBlue" + NL, 1),
        "import 了 AiChatGreen",
    ),
    (
        "发送键那一档要用的 AiChatGreenDeep 没 import（编译前先红）",
        SCREEN,
        lambda s: s.replace("import com.tapmoay.sorders.ui.theme.AiChatGreenDeep" + NL, "", 1),
        "import 了 AiChatGreenDeep",
    ),
    (
        "强调色又绑回全 App 主操作色 ThemeGreen（CHG-0101 那个雷复发：别人换主色它就跟着跑）",
        SCREEN,
        lambda s: s.replace("private val AiAccent = Color(AiChatGreen)",
                            "private val AiAccent = Color(ThemeGreen)", 1),
        "AiAccent 没有再绑回 ThemeGreen",
    ),
    (
        "顶栏「历史」那颗不再读强调色（三颗里漏一颗＝还是旧色）",
        SCREEN,
        lambda s: re.sub(r'Icons\.Default\.History,\s*\n\s*contentDescription = "历史对话",\s*\n\s*tint = AiAccent,',
                         'Icons.Default.History,' + NL
                         + '                                contentDescription = "历史对话",' + NL
                         + '                                tint = MaterialTheme.colorScheme.onSurface,',
                         s, count=1),
        "顶栏：历史",
    ),
    (
        "顶栏「新对话」那颗的 onClick 被顺手改坏（新对话不再开新对话）",
        SCREEN,
        lambda s: s.replace("onClick = { vm.newChat() },",
                            "onClick = { vm.newChat(); showModelSheet = true },", 1),
        "新对话那颗仍是 vm.newChat()",
    ),
    (
        "顶栏「设置」那颗不再读强调色",
        SCREEN,
        lambda s: re.sub(r'Icons\.Default\.Settings,\s*\n\s*contentDescription = "设置",\s*\n\s*tint = AiAccent,',
                         'Icons.Default.Settings,' + NL
                         + '                                contentDescription = "设置",' + NL
                         + '                                tint = MaterialTheme.colorScheme.onSurface,',
                         s, count=1),
        "顶栏：设置",
    ),
    (
        "输入行 ⊕ 的着色少了「发送中退成灰」那一档（发送中还在招手让你点）",
        SCREEN,
        lambda s: s.replace("tint = if (sending) MaterialTheme.colorScheme.outline else AiAccent,",
                            "tint = AiAccent,", 1),
        "⊕ 的着色",
    ),
    (
        "输入行 ⊕ 变成发送中也能点（附件面板能在发送中途弹出来）",
        SCREEN,
        lambda s: s.replace("IconButton(onClick = onTogglePanel, enabled = !sending)",
                            "IconButton(onClick = onTogglePanel, enabled = true)", 1),
        "⊕ 仍是「发送中不可点」",
    ),
    (
        "发送键退回与三颗图标同色（用户点名要的「稍微的区别」被抹掉）",
        SCREEN,
        lambda s: s.replace("else -> SolidColor(Color(AiChatGreenDeep))",
                            "else -> SolidColor(AiAccent)", 1),
        "可发送 = 深一档",
    ),
    (
        "发送键两档区别被抹平：空格子也画实心深绿（「可发/不可发」彻底看不出来）",
        SCREEN,
        lambda s: s.replace("!canSend -> SolidColor(AiAccent.copy(alpha = 0.45f))",
                            "!canSend -> SolidColor(Color(ThemeGreenDeep))", 1),
        "不可发送 = 淡绿",
    ),
    (
        "发送键「发送中」不再是单色红（危险动作跟主题绿混在一起）",
        SCREEN,
        lambda s: s.replace("sending -> SolidColor(MaterialTheme.colorScheme.error)",
                            "sending -> SolidColor(Color(ThemeGreenDeep))", 1),
        "发送中 = 单色红",
    ),
    (
        "发送键的 onClick 少了 onStop（发送中按它不再中断，只按得动 onSend）",
        SCREEN,
        lambda s: s.replace("onClick = { if (sending) onStop() else if (canSend) onSend() },",
                            "onClick = { if (canSend) onSend() },", 1),
        "onClick：发送中＝停止",
    ),
    (
        "发送键尺寸被改小：52dp → 40dp（老人友好那条可点区域跟着缩）",
        SCREEN,
        lambda s: s.replace("modifier = Modifier.size(52.dp)," + NL + "                shape = CircleShape,",
                            "modifier = Modifier.size(40.dp)," + NL + "                shape = CircleShape,", 1),
        "仍是 52dp 圆形",
    ),
    (
        "发送键不再切 Stop 图标（发送中看不出能中断）",
        SCREEN,
        lambda s: s.replace("imageVector = if (sending) Icons.Default.Stop else Icons.Default.ArrowUpward,",
                            "imageVector = Icons.Default.ArrowUpward,", 1),
        "图标仍是 Stop ↔ ArrowUpward",
    ),
    (
        "AI 设置页那一处强调色没跟上（同一片表面一半绿一半蓝）",
        SETTINGS,
        lambda s: s.replace("val accent = Color(AiChatGreen)", "val accent = Color(AiBlue)", 1),
        "accent = AI 页自己的绿",
    ),
    (
        "设置页 SegmentedPicker 的 accent 单独退回蓝（两处不同源）",
        SETTINGS,
        lambda s: s.replace("accent = Color(AiChatGreenDeep),", "accent = Color(AiBlue),", 1),
        "SegmentedPicker 的 accent 同源",
    ),
    (
        "越权动品牌三段渐变：AiBrand 的三色被顺手刷成绿（那是「AI 品牌徽章」，本单不许动）",
        BRAND,
        lambda s: s.replace("listOf(Color(AiBlue), Color(AiPurple), Color(AiPink))",
                            "listOf(Color(ThemeGreen), Color(ThemeGreenDeep), Color(ThemeGreen))", 1),
        "AiBrand：三色顺序仍是 蓝→紫→粉",
    ),
    (
        "工作台那颗 AI 圆钮的渐变被换成单色（消费者被改）",
        HOME,
        lambda s: s.replace(".background(aiBrandBrush(), CircleShape)",
                            ".background(Color(ThemeGreen), CircleShape)", 1),
        "消费者①：工作台 AI 圆钮仍用渐变",
    ),
    (
        "聊天页空状态星标的渐变被换成单色（另一个消费者被改）",
        SCREEN,
        lambda s: s.replace(".background(aiBrandBrush(), RoundedCornerShape",
                            ".background(Color(ThemeGreen), RoundedCornerShape", 1),
        "消费者②：聊天页空状态星标仍用渐变",
    ),
    (
        "聊天页里又冒出一处 AiBlue（全仓扫描那一节要抓住的那一条漏网）",
        SCREEN,
        lambda s: re.sub(r"tint = AiAccent, modifier = Modifier\.size\(16\.dp\)\)",
                         "tint = Color(AiBlue), modifier = Modifier.size(16.dp))",
                         s, count=1),
        "ui/ai 整目录一处 AiBlue 都不剩",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-2000:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    fails: list[str] = []

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", NL)
        mutated = mutate(plain)
        if mutated == plain:
            print(f"  [SKIP] {label}：注入没生效（锚点变了，请更新本脚本）")
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            continue
        text = mutated.replace(NL, "\r\n") if crlf else mutated
        try:
            path.write_bytes(text.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        if code != 0 and (not expect or expect in out):
            print(f"  [OK]   {label} → 报红")
        else:
            print(f"  [MISS] {label}（退出码 {code}，期望关键词「{expect}」）")
            fails.append(f"{label}（退出码 {code}，期望关键词「{expect}」）")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    for rel in dirty:
        (ROOT / rel).write_bytes(originals[rel])
        print(f"  [!!]   {rel} 没还原干净，已强制写回")
        fails.append(f"{rel} 没还原干净")

    print("=" * 60)
    if fails:
        print(f"❌ 反向验证不通过：{len(fails)} 条")
        for f in fails:
            print(f"   - {f}")
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
