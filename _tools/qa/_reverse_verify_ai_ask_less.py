#!/usr/bin/env python
"""反向验证：**故意把 CHG-0120 的几件事一件一件弄坏**，每次 `_check_ai_ask_less.py` 都必须当场报红。

为什么非得有它：「AI 少问、按默认值直接执行」这件事**坏掉的方式全是安静的** ——
把那段提示词从 systemPrompt 里摘掉、把「能推断就别问」删了、把「一次问全」删了、
把安全底线删了、把某条默认值改成别的口径、把出处指向一个不存在的文件……
**没有一条会报错**，用户看到的是「AI 又开始一轮一轮地问」。
所以每一条都必须能在一个**写在别处的判据**上当场变红；红不了就说明那条判据是空转的。

⚠️ 注入点选在**判据真正读的地方**（提示词正文 / 接线那一行 / 文档的出处列 / 文档地图那一行 / 单测），
不是选在"看起来相关"的地方。每条注入跑完都**逐字节还原**（末尾再核对一遍）。

R4-BOUNDARY-JUSTIFICATION: 这份脚本只改**给模型看的那段文字与它的接线**（Kotlin 提示词常量、
`docs/AI_DEFAULTS.md`、`docs/PROJECT_MAP/INDEX.md` 的一行、单测文件），不碰后端契约、领域类型、
权限模型、数据库 —— 它验证的判据本身也在同一层（"同一句口径写在哪、谁读它"）。
把这条口径下沉成 API 参数或领域对象治不了它要防的病（两处口径分叉），这条边界是**故意的**。

用法：python _tools/qa/_reverse_verify_ai_ask_less.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_ai_ask_less.py"

ROLE_REL = "android/app/src/main/java/com/tapmoay/sorders/ai/AiRolePrompt.kt"
LOOP_REL = "android/app/src/main/java/com/tapmoay/sorders/ai/AiAgentLoop.kt"
KT_REL = "android/app/src/test/java/com/tapmoay/sorders/ai/AiAskLessTest.kt"
DOC_REL = "docs/AI_DEFAULTS.md"
INDEX_REL = "docs/PROJECT_MAP/INDEX.md"


def kill(s: str, old: str, n: int = 1) -> str:
    """删掉 `old`。找不到就当场抛 —— 静默跳过等于这条注入根本不存在。"""
    if s.count(old) < n:
        raise AssertionError("注入锚点找不到：" + old[:80])
    return s.replace(old, "", n)


#: (人读的说明, 改哪个文件, 怎么改, 判据变红时必须出现的那句话)
CASES = [
    (
        "把提示词里那句拼装删掉（清单还在文件里，但没进 systemPrompt）",
        LOOP_REL,
        lambda s: kill(s, "            append(AiDefaults.RULES)"),
        "把 `append(AiDefaults.RULES)` 加回去",
    ),
    (
        "把「能按默认值推断出来的，不要问」删掉",
        ROLE_REL,
        lambda s: kill(s, "能按下面这张单子推断出来的，不要问"),
        "把「能按下面这张单子推断出来的，不要问」加回",
    ),
    (
        "把「真要问，就一次问全」删掉（用户最烦的一轮问一个又回来了）",
        ROLE_REL,
        lambda s: kill(s, "真要问，就一次问全"),
        "把「真要问，就一次问全」加回",
    ),
    (
        "把安全底线删掉（「绝不许替他决定」）",
        LOOP_REL,
        lambda s: kill(s, "**你不知道的事就去问，绝不许替他决定。**"),
        "原来的「你不知道的事就去问，绝不许替他决定」不许删",
    ),
    (
        "把清单里某条默认值改成别的口径（成本价 → 返点后成本）",
        ROLE_REL,
        lambda s: s.replace("那一格填**进货成本**", "那一格填**返点后成本**", 1),
        "把「成本价那一格 = 进货成本」这一条加回",
    ),
    (
        "把文档里某条出处指向一个不存在的文件",
        DOC_REL,
        lambda s: s.replace("backend/app/services/cost_history.py", "backend/app/services/cost_history_v2.py", 1),
        "出处那条指向的文件不存在",
    ),
    (
        "把文档地图里那一行删掉（文档变孤儿）",
        INDEX_REL,
        lambda s: kill(s, "[**../AI_DEFAULTS.md**](../AI_DEFAULTS.md)"),
        "把指向 ../AI_DEFAULTS.md 的那一行加回 docs/PROJECT_MAP/INDEX.md",
    ),
    (
        "把单测用例删到 0 个（口径没有测试钉着）",
        KT_REL,
        lambda s: s.replace("@Test", "// @Test"),
        "单测少于 6 例",
    ),
    (
        "把提示词里的密码改成手抄字面量（同一个数开始有两处）",
        ROLE_REL,
        lambda s: s.replace("${AccountRules.DEFAULT_INITIAL_PASSWORD}", "123321"),
        "提示词里的密码必须引用 AccountRules.DEFAULT_INITIAL_PASSWORD",
    ),
]


def run_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    print("== 0. 前提：源码完好时判据必须是绿的 ==")
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时判据就是红的 —— 先把它修绿再谈反向验证。")
        print(out[-3000:])
        return 2
    print("✅ 判据在完好源码上全绿")

    originals: dict[str, bytes] = {}
    ok = 0
    print("\n== 注入 %d 条：每条都必须让判据当场变红 ==" % len(CASES))
    try:
        for i, (label, rel, mutate, expect) in enumerate(CASES, 1):
            path = ROOT / rel
            original = originals.setdefault(rel, path.read_bytes())
            crlf = b"\r\n" in original
            text = original.decode("utf-8")
            mutated = mutate(text)
            if mutated == text:
                print("❌ [%d/%d] %s：注入没有改变任何字节（等于没注入）" % (i, len(CASES), label))
                return 1
            data = mutated.encode("utf-8")
            if crlf:
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            path.write_bytes(data)
            try:
                code2, out2 = run_check()
                hit = code2 != 0 and expect in out2
                print(("✅" if hit else "❌") + " [%d/%d] %s —— %s"
                      % (i, len(CASES), label,
                         "判据变红，且命中了那句话" if hit
                         else "判据没红 / 没命中那句话（exit=%d）" % code2))
                if not hit:
                    print(out2[-2500:])
                    return 1
                ok += 1
            finally:
                path.write_bytes(original)
    finally:
        for rel, original in originals.items():
            path = ROOT / rel
            if path.read_bytes() != original:
                path.write_bytes(original)
                print("⚠️  %s 没有逐字节还原，已强制还原" % rel)

    dirty = [rel for rel, original in originals.items() if (ROOT / rel).read_bytes() != original]
    print("\n逐字节还原核对：改了 %d 个文件，脏 = %d" % (len(originals), len(dirty)))
    if dirty or ok != len(CASES):
        print("❌ 反向验证不完整（通过 %d/%d）" % (ok, len(CASES)))
        return 1
    print("✅ 反向验证通过：%d/%d 条注入全部被抓，且源码逐字节还原。" % (ok, len(CASES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
