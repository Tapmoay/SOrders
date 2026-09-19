"""反向验证 §11d（名单要拉得全 + 「不啰嗦」不许被过度执行）。

## 为什么这一节必须配反向验证
它守的是一个**真 bug 的复发**，而复发之后**不报错、也不崩**：
用户看到的是 AI 客气地说「只看了前 20 个，剩下的要接着看跟我说一声」——
看起来像"功能就这样"，其实是我们在 App 侧把后端已经给的行丢掉了。

- `MAX_ROWS` 改回 50 → 97 个货主 / 62 个司机 / 161 个账号**物理上列不全**，界面毫无异常；
- 不把 `limit` 传给后端 → 后端按自己的默认（`/users` 是 100）截，我们调多大上限都没用；
- 删掉 `truncated_note` → 模型又只会说"被截断了"，不知道该去重查、更不知道不该让用户"说继续"；
- 把「不啰嗦」的边界段删掉 → 模型把"少说过程"执行成"少说话"，**该提醒的风险一起省掉**。

用法：`python _reverse_verify_read_caps.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
TOOLS = AI / "AiTools.kt"
READSVC = AI / "AiReadService.kt"
LOOP = AI / "AiAgentLoop.kt"
STYLE = AI / "AiAnswerStyle.kt"

LIMIT_FWD = "if (declared.containsKey(A_LIMIT)) query[A_LIMIT] = limit.toString()"

CASES: list[tuple[str, Path, object]] = [
    (
        "MAX_ROWS 改回 50（97 个货主永远列不全）",
        TOOLS,
        lambda s: s.replace("const val MAX_ROWS = 200", "const val MAX_ROWS = 50", 1),
    ),
    (
        "不把 limit 传给后端（后端按自己的默认截，调多大都没用）",
        READSVC,
        lambda s: s.replace(LIMIT_FWD, "// 不传了", 1),
    ),
    (
        "截断时不告诉模型该怎么办（只留一个 truncated 标志）",
        READSVC,
        lambda s: s.replace('"truncated_note",', '"truncated_note_unused",', 1),
    ),
    (
        "提示词退回旧文案（只教说实话、没教去取全）",
        LOOP,
        lambda s: s.replace(
            "用户要「全部/所有/名单」时，一次就取够",
            "工具返回的行可能被截断，那就说明只看了前 N 条",
            1,
        ),
    ),
    (
        "禁止把「继续看」推给用户那句被删掉",
        LOOP,
        lambda s: s.replace("不要只给前几条然后让他「跟我说一声再看」", "（删）", 1),
    ),
    (
        "「不啰嗦」的边界段被删（该提醒的风险一起省掉）",
        STYLE,
        lambda s: s.replace("「不啰嗦」不等于「什么都不说」", "（删）", 1),
    ),
    (
        "判断标准被删（模型只能靠猜哪些该说）",
        STYLE,
        lambda s: s.replace("这句话会不会改变用户下一步怎么做？会，就必须说", "（删）", 1),
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(HERE / "_check_ai_guardrails.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def section(out: str) -> str:
    """只取 §11d 那一段。段内失败标记是 `[FAIL]`（`❌` 只在最后汇总里）。"""
    if "== 11d." not in out:
        return ""
    rest = out.split("== 11d.", 1)[1]
    nxt = rest.find("\n== ")
    return rest if nxt < 0 else rest[:nxt]


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0 or not section(out):
        print(f"❌ 前提不成立：源码完好时 §11d 就没过（code={code}）\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时检查是绿的，且 §11d 存在")

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
        if code == 0 or "[FAIL]" not in section(out):
            fails.append(f"{label}：注入后 §11d 没有报红（code={code}）——判据是空转的")
        else:
            print(f"✅ 注入「{label}」→ §11d 报红")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ §11d 的 {len(CASES)} 条注入全部证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
