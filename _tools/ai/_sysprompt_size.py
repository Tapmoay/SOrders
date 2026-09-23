"""量一量系统提示词到底有多大（只读源码，不跑 App）。

systemPrompt 每构建一次就**整段重发一次**，所以它的大小直接决定"接着对话贵不贵"。
口径：只数源码里的字符串字面量（含中文），按 AiContext.estimateTokens 换算。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
UI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/ai"

# systemPrompt 的正文在 AiAgentLoop 里，另两块文案分别抽到了这两个文件
TARGETS = [
    (AI / "AiAgentLoop.kt", "systemPrompt"),
    (AI / "AiRolePrompt.kt", None),
    (AI / "AiAnswerStyle.kt", None),
]

LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')


def est(text: str) -> int:
    cjk = sum(1 for ch in text if ord(ch) >= 0x2E80)
    return cjk + (len(text) - cjk + 3) // 4


def body_of(path: Path, fn: str | None) -> str:
    src = path.read_text(encoding="utf-8")
    if fn is None:
        return src
    start = src.index(f"private fun {fn}(")
    depth, i = 0, src.index("{", start)
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    return src[i:]


def dir_literals(folder: Path, pattern: str) -> int:
    """一个目录下若干文件的字符串字面量总量（不区分函数，只看文案规模）。"""
    text = ""
    for f in sorted(folder.glob(pattern)):
        text += "".join(m.group(1) for m in LITERAL.finditer(f.read_text(encoding="utf-8")))
    return est(text)


total = 0
print("系统提示词各段的估算大小：")
for path, fn in TARGETS:
    if not path.exists():
        print(f"  ⚠️ 缺文件：{path}")
        continue
    text = "".join(m.group(1) for m in LITERAL.finditer(body_of(path, fn)))
    n = est(text)
    total += n
    print(f"  {path.name:<20} {len(text):>6} 字符 ≈ {n:>5} token")
print(f"  {'合计':<20} {'':>6}        ≈ {total:>5} token（每轮都重发一遍）")
print()
# tools 参数（工具清单）与 system 是两条独立通道，但**同样每轮重发**：
#   read_data 的说明由 AiReadCatalog 按角色生成，preview_write 的说明由 AiWrites 生成。
reads = dir_literals(AI, "AiReadCatalog.kt")
writes = dir_literals(AI, "AiWrite*.kt")
print("工具清单（tools 参数，每轮重发）：")
print(f"  AiReadCatalog.kt      ≈ {reads:>5} token（按角色裁出来的只读表说明）")
print(f"  AiWrite*.kt           ≈ {writes:>5} token（写动作清单与参数说明）")
print(f"  每轮固定开销合计      ≈ {total + reads + writes:>5} token（还没算你的对话历史）")
print()
# ⛔ 2026-09-24 第 22 轮 F1 实测：上面这三个数**是高估**，别拿它做成本判断。
#    原因是 `dir_literals` 扫的是 `AiWrite*.kt` **20 个文件里的全部字符串字面量** ——
#    卡片文案、报错话术、提示语全算进去了，而真正进提示词的只有
#    `AiWrites.describeForModel()` 拼出来的那一份（其余是运行时才拼给人看的）。
#    实测（派单员、全部工具开启）真实值 ≈20384 token，本脚本报 ≈55813（**高估 2.7 倍**）。
#    要真实数字请看 Android 单测 `AiWritePromptTest`：它渲染**真实的那份字符串**并打印字符数
#    （2026-09-24 实测：整份 20766 字符，其中本轮新带上的参数约束 1846 字符）。
print("⚠️ 上面是**粗估且偏高**（把 20 个文件里的全部字面量都算了进去）——")
print("   真实值以 Android 单测 `AiWritePromptTest` 打印的为准（它渲染的是真正发给模型的那份字）。")
print()
print("对照：AiContext 走固定预算（见 AiContext.kt 里 v3.34 那条注释），本脚本的「压缩阈值」一行已过时。")
