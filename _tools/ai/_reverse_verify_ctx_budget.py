"""反向验证 §11c（上下文触发点必须是「固定预算」而不是「窗口百分比」）。

## 为什么这一节必须配反向验证
这一节守的是**一个已经发生过的设计错误**，而且它的失效方式全都**不报错、也不崩**：

- 把 `HISTORY_BUDGET_TOKENS` 改回"窗口 × 40%" → 对 1M 窗口的模型等于 419,430 token 才收口，
  折合四百多轮问答，**实际永不触发**（`_tools/ai/_ctx_budget.py` 算过）。表现是
  "整段对话原样发出去"重新变成唯一会执行的路径——没有报错，只是慢慢变慢变贵变不准。
- 把 `fitToBudget` 与 `trimToFit` 的顺序写反 → 先按窗口丢、再按预算降级，
  丢掉的恰好是最该留的结论（"先降级再丢弃"这个收益直接归零）。
- 某条发送路径绕过 `shrunkHistory` → 那条路上的历史完全不收口，而单测只测纯函数，测不到它。
- 后台压缩忘了比对 `generation` → 用户切了对话之后，上一段对话的摘要会落进新对话里，
  污染后面每一次回答（和 `applyPendingEdit` 里清摘要是同一个坑）。
- 降级不留痕 → 模型把半截文字当成完整信息，给出"看起来有依据其实是半截"的结论。

所以每条都注入一次，证明检查真的会红。

用法：`python _reverse_verify_ctx_budget.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CTX = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiContext.kt"
VM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiChatViewModel.kt"

# 发送前收口那一句的原文（顺序的反向注入要用它做锚点）
SHRINK_CALL = 'AiContext.trimToFit("", AiContext.fitToBudget(historyForModel()), window)'

CASES: list[tuple[str, Path, object]] = [
    (
        "预算改回「窗口百分比」（1M 窗口下等于永不触发）",
        CTX,
        lambda s: s.replace(
            "const val HISTORY_BUDGET_TOKENS = 8_000",
            "val HISTORY_BUDGET_TOKENS = (FALLBACK_WINDOW * COMPACT_AT).toInt()",
            1,
        ),
    ),
    (
        "先按窗口硬裁、再按预算降级（顺序写反 = 先丢结论）",
        VM,
        lambda s: s.replace(
            SHRINK_CALL,
            'AiContext.fitToBudget(AiContext.trimToFit("", historyForModel(), window))',
            1,
        ),
    ),
    (
        "某条发送路径绕过收口入口（那条路上历史完全不收口）",
        VM,
        lambda s: s.replace(
            "var history = shrunkHistory(cfg.contextWindow)",
            'var history = AiContext.trimToFit("", historyForModel(), cfg.contextWindow)',
            1,
        ),
    ),
    (
        "压缩回到「发送前同步做」（挡住用户这一轮）",
        VM,
        lambda s: s.replace("private fun scheduleCompaction(cfg: LlmConfig, myGen: Int)", "private fun compactNow(cfg: LlmConfig, myGen: Int)", 1),
    ),
    (
        "后台压缩不比对代号（上一段对话的摘要落进新对话）",
        VM,
        lambda s: s.replace("if (generation != myGen) return@launch\n", "", 1),
    ),
    (
        "降级不留痕（模型把半截当全部）",
        CTX,
        lambda s: s.replace(" + ELIDED_TAIL", "", 1),
    ),
    (
        "最近 N 条也被降级（动了用户正在聊的那几条）",
        CTX,
        lambda s: s.replace(
            "val recent = history.takeLast(keepRecent)",
            "val recent = history.takeLast(keepRecent).map { degrade(it) }",
            1,
        ),
    ),
    (
        "发送/整理优先级反了（查询中会显示成在整理）",
        VM,
        lambda s: s.replace(
            '            sending -> "查询中…"\n            compacting -> "整理上下文…"',
            '            compacting -> "整理上下文…"\n            sending -> "查询中…"',
            1,
        ),
    ),
    (
        "历史用量把系统提示词也算进去（预算的含义直接漂移）",
        CTX,
        lambda s: s.replace("fun estimateHistoryTokens(", "fun estimateAllTokens(", 1),
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


def section_11c(out: str) -> str:
    """只取 §11c 那一段（不取它后面所有内容）——否则后面任何一节红了都会算成"这条生效了"。

    ⚠️ 段内的失败标记是 `[FAIL]`，**不是** `❌`——`❌` 只出现在最后的汇总里。
    第一版按 `❌` 判，结果九条注入全部误报"没变红"（实测踩到）。
    """
    if "== 11c." not in out:
        return ""
    rest = out.split("== 11c.", 1)[1]
    nxt = rest.find("\n== ")
    return rest if nxt < 0 else rest[:nxt]


def main() -> int:
    fails: list[str] = []

    code, out = run_check()
    if code != 0:
        fails.append(f"前提不成立：源码完好时检查就没过\n{out[-1500:]}")
        print("\n".join(fails))
        return 1
    if not section_11c(out):
        fails.append("前提不成立：输出里找不到 §11c 这一段（红线脚本被改过？）")
        print("\n".join(fails))
        return 1
    print("✅ 前提：源码完好时检查是绿的，且 §11c 存在")

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
        got = section_11c(out)
        if code == 0 or "[FAIL]" not in got:
            fails.append(f"{label}：注入后 §11c 没有报红（code={code}）——判据是空转的")
        else:
            print(f"✅ 注入「{label}」→ §11c 报红")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ §11c 的 {len(CASES)} 条注入全部证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
