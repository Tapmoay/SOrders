#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反向验证：`_tools/qa/_check_ai_chat_green.py` 里那些红线**真的在检查**吗？

机器判据最怕的不是写错，是**写得太松**：正则退化成「全文里还有这几个字就行」、
阈值被放宽到「怎么都过」、判据被搬到别的脚本之后原地留了个空壳 —— 三种情况都
**不报错、不崩溃、照样全绿**，而屏幕上已经读不清了。

这个脚本用「把源码改坏 → 判据必须变红」来证明每一条判据都是活的，30 条注入按
判据的七节分组：

  1. **值被微调**（①~⑥）：把 `#4B8C5E` 调亮一点、把两档调成一样、把强调档调暗到
     能压白字、把它换成蓝的/偏青的绿 —— 这些都是"改色的人觉得更好看"的那一类改动，
     屏幕上看不出差别，但老年用户读不清。判据必须逐条抓住。
  2. **病根复发**（⑦⑧⑭）：`AiAccent` 被写回 `Color(ThemeGreen)`。
     ⚠️ 这一条**不会报错**：CHG-0091 就是这么埋的雷，CHG-0101 换主色时 AI 页
     毫无防备地一起变红棕，用户才来说那句话。所以它必须有注入证明。
  3. **四处实心各自退化**（⑨~⑬）：新对话 / 去设置 / 发送键 / 分段控件。
     ⚠️ 逐处点名，不是"数一数有几处深档" —— 计数型判据会漏掉"一处退化成强调档、
     另一处补一个深档进来"这种换位。
  4. **AI 这一片又变回一半绿一半蓝**（⑮~⑲）：设置页、操作流水页各自的收敛被撤掉。
  5. **误伤主操作色与品牌渐变**（⑳~㉓）：有人"顺手让 AI 页变绿"把 `ThemeGreen` 也改了，
     或者把 `MgrGreen` 覆盖成 AI 绿 —— 用户亲手画的深红棕就没了。
  6. **配套的判据自己烂掉**（㉔~㉚）：单测的值没钉、反验表成了空壳、变更单没写
     Blast Radius、用户那句话被删、登记簿那一行被撤、设计系统那一节被改名。

## R4-BOUNDARY-JUSTIFICATION: 为什么这条红线只能在这儿守

色值是裸 ARGB `Long` / `Color`，**类型系统里没有「白字压上去必须 ≥4.5:1」
这种类型** —— 编译器、detekt、Kotlin 的检查都不可能表达它。它甚至不是
"值的集合"上的性质，而是**算完对比度之后**才成立的性质，所以只能在
`AiChatGreenTest.kt`（跑起来）与本判据脚本（不跑也能查）两处守。
反向验证则证明这两处**没有一个是摆设**。

本脚本**只读写工作区里的文件**，不编译、不跑 UI、不连设备；每条注入跑完立刻按字节还原。

用法：
    python _tools/qa/_reverse_verify_ai_chat_green.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_ai_chat_green.py"

COLOR = "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Color.kt"
CHAT = "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiChatScreen.kt"
SET = "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiSettingsScreen.kt"
OPS = "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiOperationsScreen.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ui/theme/AiChatGreenTest.kt"
DESIGN = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
DOC = "docs/changes/CHG-0104.md"
REG = "docs/changes/README.md"
ME = "_tools/qa/_reverse_verify_ai_chat_green.py"


def sub(old: str, new: str, idx: int = 0, expect: int | None = None):
    """把第 `idx` 处（0 起）`old` 换成 `new`。

    ⚠️ 为什么要 `idx`：`str.replace(old, new, 1)` 认的是第一处**子串**，而 `old` 经常被
    更长的行包含（本单踩到的形状：`containerColor = Color(AiChatGreenDeep),` 在
    `AiChatScreen.kt` 里出现 **2** 次 —— 「新对话」是同一行带 `contentColor`、
    「去设置」是换行的那种；不点名就会改错一处，而判据照样绿 —— 注入就成了自欺）。
    """
    def run(text: str) -> str:
        n = text.count(old)
        if n == 0:
            raise AssertionError("注入点不在了：" + repr(old[:80]))
        if expect is not None and n != expect:
            raise AssertionError("注入点命中 %d 次（期望 %d）：%r" % (n, expect, old[:80]))
        pos = -1
        for _ in range(idx + 1):
            pos = text.find(old, pos + 1)
        if pos < 0:
            raise AssertionError("第 %d 处不存在：%r" % (idx, old[:80]))
        return text[:pos] + new + text[pos + len(old):]
    return run


def sub_all(old: str, new: str):
    """把**每一处** `old` 都换掉。

    ⚠️ 为什么要这个：用户那句「它就像微信一样」在变更单里**不止一处**（顶部目标那一块 ＋
    判据/证据里各引一次）。只换第一处的话，判据看的那一处原样还在 ⇒ 判据照样绿，
    注入就成了自欺。
    """
    def run(text: str) -> str:
        if old not in text:
            raise AssertionError("注入点不在了：" + repr(old[:80]))
        return text.replace(old, new)
    return run


CASES: list[tuple[str, str, object, str]] = [
    # ---------------- 1. 两个值被"微调"（改色的人觉得更好看的那一类） ----------------
    ("① 强调档被调亮一档（白字更读不清了）",
     COLOR, sub("val AiChatGreen = 0xFF4B8C5EL", "val AiChatGreen = 0xFF5B9C6EL"),
     "读出来就是 #4B8C5E"),
    ("② 实心档被调成与强调档同一个值（两档合并了）",
     COLOR, sub("val AiChatGreenDeep = 0xFF3D734DL", "val AiChatGreenDeep = 0xFF4B8C5EL"),
     "两档明度差"),
    ("③ 实心档被调亮到白字读不清（AA 破了）",
     COLOR, sub("val AiChatGreenDeep = 0xFF3D734DL", "val AiChatGreenDeep = 0xFF6FA87FL"),
     "白字压实心档"),
    ("④ 强调档被调暗到居然能压白字（那两档就可以合并了）",
     COLOR, sub("val AiChatGreen = 0xFF4B8C5EL", "val AiChatGreen = 0xFF2F5C3CL"),
     "白字压强调档"),
    ("⑤ 强调档被换成蓝色（不再是绿）",
     COLOR, sub("val AiChatGreen = 0xFF4B8C5EL", "val AiChatGreen = 0xFF4B6E8CL"),
     "色相落在绿带"),
    ("⑥ 强调档被换成偏黄的另一个绿（离微信的色相家族远了）",
     COLOR, sub("val AiChatGreen = 0xFF4B8C5EL", "val AiChatGreen = 0xFF6E9E3EL"),
     "与微信品牌绿"),

    # ---------------- 2. 病根复发：AiAccent 又跟着主题色跑 ----------------
    ("⑦ AiAccent 被写回 Color(ThemeGreen)（CHG-0091 那个雷复发）",
     CHAT, sub("private val AiAccent = Color(AiChatGreen)",
               "private val AiAccent = Color(ThemeGreen)"),
     "AiAccent = Color(AiChatGreen)"),
    ("⑧ AiAccent 被写回 Google 蓝（AI 页那份独立主色没了）",
     CHAT, sub("private val AiAccent = Color(AiChatGreen)",
               "private val AiAccent = Color(AiBlue)"),
     "AiAccent = Color(AiChatGreen)"),
    ("⑭ 代码里又冒出一处 Color(ThemeGreen)（说明文字之外的真引用）",
     CHAT, sub("private val AiAccent = Color(AiChatGreen)",
               "private val AiAccent = Color(AiChatGreen)\n"
               "private val AiLegacyAccent = Color(ThemeGreen)"),
     "代码里没有"),

    # ---------------- 2b. 用户自己那一句气泡（同一类病：隔着主题借别人的色） ----------------
    ("⑭b 用户气泡又隔着主题借全 App 主操作色（CHG-0101 那个雷的另一种形状）",
     CHAT, sub("isUser -> Color(AiChatGreenDeep)",
               "isUser -> MaterialTheme.colorScheme.primary"),
     "用户气泡读 AI 页自己的深档"),
    ("⑭c 用户气泡改用强调档（白字只有 4.03:1，读不清）",
     CHAT, sub("isUser -> Color(AiChatGreenDeep)",
               "isUser -> Color(AiChatGreen)"),
     "用户气泡读 AI 页自己的深档"),

    # ---------------- 3. 四处实心各自退化（逐处点名，不许靠计数蒙） ----------------
    ("⑨「新对话」按钮改回强调档（白字只有 4.03:1）",
     CHAT, sub("containerColor = Color(AiChatGreenDeep), contentColor = Color.White),",
               "containerColor = AiAccent, contentColor = Color.White),"),
     "新对话按钮"),
    ("⑩「去设置」按钮改回强调档（同上）",
     CHAT, sub("containerColor = Color(AiChatGreenDeep),",
               "containerColor = AiAccent,", idx=1, expect=2),
     "去设置按钮"),
    ("⑪ 发送键改回 Color(ThemeGreenDeep)（隔着文件跟着订单卡的确认接单跑）",
     CHAT, sub("else -> SolidColor(Color(AiChatGreenDeep))",
               "else -> SolidColor(Color(ThemeGreenDeep))"),
     "实心处「发送键」"),
    ("⑫ 思考强度分段控件改回强调档（选中态是**文字**，坐不住了）",
     CHAT, sub("accent = Color(AiChatGreenDeep),", "accent = AiAccent,"),
     "思考强度分段控件"),
    ("⑬ 发送键的失效态被删掉（可发/不可发看不出来了）",
     CHAT, sub("!canSend -> SolidColor(AiAccent.copy(alpha = 0.45f))",
               "!canSend -> SolidColor(AiChatGreenDeep)"),
     "发送键的失效态"),

    # ---------------- 4. AI 这一片又变回「一半绿一半蓝」 ----------------
    ("⑮ 设置页强调色改回主题色（同一片表面又不同源了）",
     SET, sub("    val accent = Color(AiChatGreen)", "    val accent = Color(ThemeGreen)"),
     "设置页强调色"),
    ("⑯ 设置页「保存」按钮改回强调档（实心 + 白字坐不住）",
     SET, sub("                        containerColor = Color(AiChatGreenDeep),",
              "                        containerColor = accent,"),
     "保存」按钮走深档"),
    ("⑰ 设置页分段控件改回强调档",
     SET, sub("                        accent = Color(AiChatGreenDeep),",
              "                        accent = Color(AiChatGreen),"),
     "设置页分段控件走深档"),
    ("⑱ 操作流水页改回 Google 蓝（齿轮点进来的两页一绿一蓝）",
     OPS, sub("tint = Color(AiChatGreen))", "tint = Color(AiBlue))"),
     "操作流水页代码里没有"),
    ("⑲ 操作流水页分段控件改成强调档",
     OPS, sub("accent = Color(AiChatGreenDeep),", "accent = Color(AiChatGreen),"),
     "操作流水页分段控件走深档"),

    # ---------------- 5. 误伤主操作色与 AI 品牌渐变 ----------------
    ("⑳ 有人「顺手让 AI 页变绿」把 ThemeGreen 也改了",
     COLOR, sub("val ThemeGreen = 0xFF006C43", "val ThemeGreen = 0xFF4B8C5EL"),
     "主操作色还在用户画的那一族里"),
    ("㉑ 深一档被改成老色相那版的绿（订单卡的确认接单跟着变）",
     COLOR, sub("val ThemeGreenDeep = 0xFF00532EL", "val ThemeGreenDeep = 0xFF0E7A50L"),
     "深一档还是"),
    ("㉒ AI 品牌渐变的 AiPink 被动过（用户从没让动）",
     COLOR, sub("val AiPink = 0xFFD96570L", "val AiPink = 0xFF4B8C5EL"),
     "AiPink"),
    ("㉓ 有人拿 AiChatGreen 的值覆盖了 MgrGreen（删了别人的 token）",
     COLOR, sub("val MgrGreen = 0xFF00AC6E", "val MgrGreen = 0xFF4B8C5EL"),
     "覆盖一个已有 token"),

    # ---------------- 6. 配套的判据自己烂掉 ----------------
    ("㉔ 单测里强调档的值没钉住（被改了）",
     TEST, sub("0xFF4B8C5EL", "0xFF5B9C6EL"),
     "单测钉住了强调档的值"),
    ("㉕ 单测里实心档的值没钉住（被改了）",
     TEST, sub("0xFF3D734DL", "0xFF2A5236L"),
     "单测钉住了实心档的值"),
    ("㉖ 反验脚本的注入表被换成空壳",
     ME, sub("CASES: list[tuple[str, str, object, str]] = [",
             "CASESX: list[tuple[str, str, object, str]] = [", expect=2),
     "注入表 CASES"),
    ("㉗ 变更单没写 Blast Radius",
     DOC, sub("- **Blast Radius**：L0", "- **Blast Radius**：L9"),
     "Blast Radius"),
    ("㉘ 用户那句「它就像微信一样」被从变更单里删掉（后来人看不出为什么要绿）",
     DOC, sub_all("它就像微信一样", "跟微信差不多"),
     "它就像微信一样"),
    ("㉙ 登记簿里 CHG-0104 那一行被撤掉",
     REG, lambda t: "\n".join(ln for ln in t.split("\n")
                              if not ln.startswith("| `CHG-0104` |")),
     "登记簿"),
    ("㉚ 设计系统里这一节的编号被改掉（§4.25j 找不到）",
     DESIGN, sub("### 4.25j ", "### 4.25x "),
     "4.25j"),
]


def run_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    rc, out = run_check()
    if rc != 0:
        print("⛔ 源码完好时判据就不是全绿 —— 先把 _check_ai_chat_green.py 修到全绿再来跑反向验证。")
        print(out[-3000:])
        return 1
    print("✅ 前置：源码完好时判据全绿（%s）" % CHECK.name)

    originals = {rel: (ROOT / rel).read_bytes() for rel in
                 {c[1] for c in CASES} | {ME}}
    bad: list[str] = []
    try:
        for i, (title, rel, mutate, keyword) in enumerate(CASES, 1):
            p = ROOT / rel
            raw = originals[rel]
            crlf = b"\r\n" in raw
            text = raw.decode("utf-8").replace("\r\n", "\n")
            try:
                broken = mutate(text)  # type: ignore[operator]
            except AssertionError as e:
                bad.append("%s —— %s" % (title, e))
                print("  [MISS] %s —— %s" % (title, e))
                continue
            blob = broken.replace("\n", "\r\n").encode("utf-8") if crlf else broken.encode("utf-8")
            p.write_bytes(blob)
            try:
                rc2, out2 = run_check()
            finally:
                p.write_bytes(raw)
            hit_red = rc2 != 0
            hit_kw = keyword in out2
            hit_any_fail = "[FAIL]" in out2
            if hit_red and (hit_kw or hit_any_fail):
                print("  [OK]   %s" % title)
            else:
                why = "判据还是绿的" if not hit_red else "红了但不是这一条"
                bad.append("%s —— %s（期望关键词「%s」）" % (title, why, keyword))
                print("  [FAIL] %s —— %s" % (title, why))
    finally:
        dirty = []
        for rel, raw in originals.items():
            if (ROOT / rel).read_bytes() != raw:
                (ROOT / rel).write_bytes(raw)
                dirty.append(rel)
        if dirty:
            print("⚠️ 有文件没还原干净，已强制还原：%s" % ", ".join(dirty))

    rc3, out3 = run_check()
    if rc3 != 0:
        print("⛔ 还原之后判据不是全绿 —— 注入把源码改坏了。")
        print(out3[-2000:])
        return 1

    print("")
    for rel, raw in originals.items():
        assert (ROOT / rel).read_bytes() == raw, rel
    print("✅ 还原检查：%d 个被注入的文件逐字节一致；还原之后判据全绿。" % len(originals))

    if bad:
        print("❌ %d/%d 条注入没有被判据抓住：" % (len(bad), len(CASES)))
        for b in bad:
            print("   - " + b)
        return 1
    print("✅ %d 条注入都证明这条红线真的在检查。" % len(CASES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
