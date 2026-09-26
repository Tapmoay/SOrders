"""反向验证 §19（「确认卡已发」必须由代码兜底）。

## 为什么这条特别需要反向验证
这一节的判据守的是**模型说假话**这条路径（`AiCardClaim.looksLikeClaim`），
而它的失效方式全都**不报错**：
- 数卡改成去匹配工具返回里的说明文字 → 说明文字改一个字，兜底就悄悄不生效了；
- `continue` 少写一次 → 代码"看起来有兜底"，实际照样把谎话交付给用户；
- 重做时忘了盖掉屏幕上流出的谎话 → 用户还是先看到"卡已发"。

所以每条都要注入一次，证明检查真的会红。

用法：`python _reverse_verify_card_claim.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LOOP = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiAgentLoop.kt"
TOOLS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiTools.kt"
CLAIM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiCardClaim.kt"

CASES: list[tuple[str, Path, object]] = [
    (
        "数卡改成匹配返回里的说明文字（说明改一个字就静默失效）",
        LOOP,
        lambda s: s.replace(
            '(o?.get("status") as? JsonPrimitive)?.contentOrNull == CARD_OFFERED_STATUS',
            'json.contains("已生成确认卡")',
            1,
        ),
    ),
    (
        "少写 continue（看起来有兜底，实际照样把谎话交付）",
        LOOP,
        lambda s: s.replace(
            "messages += ChatMessage.user(AiCardClaim.NUDGE)\n                            continue",
            "messages += ChatMessage.user(AiCardClaim.NUDGE)",
            1,
        ),
    ),
    (
        "重做前不盖掉屏幕上流出去的谎话",
        LOOP,
        lambda s: s.replace(
            "onEvent(AiEvent.TextDelta(AiCardClaim.CORRECTION, replace = true))",
            "// 不盖了",
            1,
        ),
    ),
    (
        "把 status 常量抄成裸字面量（两处定义 → 改一处静默失效）",
        TOOLS,
        lambda s: s.replace(
            'put("status", CARD_OFFERED_STATUS)',
            'put("status", "awaiting_user_confirmation")',
            1,
        ),
    ),
    (
        "去掉判据里的「已经发出去了」那个信号（只剩卡的字样 = 提问也当成谎话）",
        CLAIM,
        lambda s: s.replace("CARD_WORD.containsMatchIn(line) && CARD_SENT.containsMatchIn(line)", "CARD_WORD.containsMatchIn(line)", 1),
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(HERE / "_check_ai_guardrails.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []

    code, out = run_check()
    if code != 0:
        fails.append(f"前提不成立：源码完好时检查就没过\n{out[-1500:]}")
        print("\n".join(fails))
        return 1
    print("✅ 前提：源码完好时检查是绿的")

    for label, path, mutate in CASES:
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（源码里那段已经变了，请更新本脚本的替换串）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code, out = run_check()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        # R3-07b：还原**当场核对**（不是「看起来还原了」）—— 对不上就记账，别让坏代码留在树里
        if path.read_text(encoding="utf-8") != original:
            fails.append(f"{label}：还原后与快照不一致 —— 注入污染了源码树")
            continue
        sec19 = out.split("== 19.")[-1] if "== 19." in out else ""
        if code == 0 or "❌" not in sec19:
            fails.append(f"{label}：注入后 §19 没有报红（code={code}）——判据是空转的")
        else:
            print(f"✅ 注入「{label}」→ §19 报红")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print("\n✅ §19 的五条判据都证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
