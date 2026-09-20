"""反向验证 `_check_ai_guardrails.py §13` 里那条**新加的**判据：换地址后重新检测要清两种记忆。

## 为什么单独一份
这条判据是 2026-09-21 补的，补它的理由就是"**它以前不存在，所以没人发现**"：
`AiKeyStore.clearStreamOptionsUnsupported` 声明了却从没人调，用户换到支持
`stream_options` 的地址后 App 仍然永远跳过它（拿不到服务端 token 用量），界面上也不解释。
按仓库惯例，新判据必须证明"注入 bug 会红"——否则它和没写一样。

⚠️ 这份脚本 2026-09-21 才建：在那之前，AI 设置页那一节的判据**没有反向验证宿主**
（其它 `_reverse_verify_*.py` 各盯各自的节）。这也是当时那个缺陷能长期存在的间接原因。

用法：python _tools/ai/_reverse_verify_ai_settings.py    # 全部报红 → 退出码 0
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
GUARDRAILS = HERE / "_check_ai_guardrails.py"
VM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiSettingsViewModel.kt"

SECTION = "13."

#: (说明, 注入函数)。注入都改**真代码**（不是注释），且都是"看起来无害"的写法。
CASES: list[tuple[str, object]] = [
    (
        "「重新检测」只清 thinking 记忆（stream_options 那条留在盘上 → 换地址后永远跳过它）",
        lambda s: s.replace(
            "        ai.keyStore.clearThinkingUnsupported(baseUrl)\n"
            "        ai.keyStore.clearStreamOptionsUnsupported(baseUrl)\n",
            "        ai.keyStore.clearThinkingUnsupported(baseUrl)\n",
            1,
        ),
    ),
    (
        "「重新检测」只清 stream_options 记忆（思考开关那条留在盘上 → 换了地址也恢复不了）",
        lambda s: s.replace(
            "        ai.keyStore.clearThinkingUnsupported(baseUrl)\n"
            "        ai.keyStore.clearStreamOptionsUnsupported(baseUrl)\n",
            "        ai.keyStore.clearStreamOptionsUnsupported(baseUrl)\n",
            1,
        ),
    ),
    (
        "「重新检测」被清空（按钮还在，点了什么都不做）",
        lambda s: s.replace(
            "        ai.keyStore.clearThinkingUnsupported(baseUrl)\n"
            "        ai.keyStore.clearStreamOptionsUnsupported(baseUrl)\n",
            "",
            1,
        ),
    ),
]


def run() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(GUARDRAILS)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def section(out: str) -> str:
    """只取 §13 那一段（否则任何别处的失败都会被算成"这条生效了"）。"""
    key = f"== {SECTION}"
    if key not in out:
        return ""
    rest = out.split(key, 1)[1]
    nxt = rest.find("\n== ")
    seg = rest if nxt < 0 else rest[:nxt]
    return seg


def main() -> int:
    fails: list[str] = []

    code, out = run()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时红线就没过\n{out[-1200:]}")
        return 1
    if not section(out):
        print(f"❌ 前提不成立：输出里找不到 §{SECTION} 这一段（红线脚本被改过？）")
        return 1
    print(f"✅ 前提：源码完好时红线是绿的，且 §{SECTION} 存在")

    # ⚠️ 一律按字节读写，并且**记住文件原本的换行风格**：`read_text/write_text` 会做换行转换
    #    （LF↔CRLF），跑一遍就把文件的换行翻掉（内容"还原了"，git 里却多出一个整文件改动）；
    #    而在 CRLF 文件上按 `\n` 写替换串，注入会**静默失效**（第一版就是这么挂的：
    #    三条注入全部报"替换串过期了"，其实是换行对不上）。
    raw = VM.read_bytes()
    crlf = b"\r\n" in raw
    original = raw.decode("utf-8")
    work = original.replace("\r\n", "\n")

    def write(text_lf: str) -> None:
        VM.write_bytes((text_lf.replace("\n", "\r\n") if crlf else text_lf).encode("utf-8"))

    for label, mutate in CASES:
        mutated = mutate(work)  # type: ignore[operator]
        if mutated == work:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            write(mutated)
            code2, out2 = run()
            red = code2 != 0 and "[FAIL]" in section(out2)
        finally:
            VM.write_bytes(raw)
        if red:
            print(f"✅ 注入「{label}」→ §{SECTION} 报红")
        else:
            fails.append(f"{label}：注入之后没有报红 —— 这条判据是空转的")

    same = VM.read_bytes() == raw
    if not same:
        fails.append("还原后与运行前不一致（字节级）")
    else:
        print("✅ 还原后与运行前逐字节一致")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ §{SECTION} 的「换地址后重新检测」判据：{len(CASES)} 条注入全部证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
