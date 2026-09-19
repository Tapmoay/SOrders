"""把 `check_refs` 的失效引用修干净（2026-09-18）。

这批失效**不是**本轮引入的：`check_refs` 已经红了若干轮（最早是删掉验证码模块那轮
留下的 `sms_code.py` 引用），而"永远红的检查 = 没有检查"。

分三类处置，**不靠删引用蒙过去**：
1. 文档里省略了 Android 包根的相对路径 → 在该文档顶部补一行
   `<!-- ref-prefix: android/app/src/main/java/com/tapmoay/sorders/ -->`
   （这个机制是**追加**候选根，不会影响文档里原有的后端路径）；
2. 被 `...` 省略的路径 → 写全；
3. 描述**已经不存在的文件**的历史记录（`sms_code.py`）→ 行内加 `[ignore-ref]`，
   这是"反例引用"的既定豁免方式，比把那段历史删掉更诚实。

用法：python _tools/qa/_fix_stale_doc_refs.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND_PREFIX = "<!-- ref-prefix: android/app/src/main/java/com/tapmoay/sorders/ -->"

#: 需要补 Android 包根前缀的文档（它们成段引用 `core/*.kt` / `theme/*.kt` 这类短路径）
NEED_PREFIX = [
    "docs/INTEGRATIONS.md",
    "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md",
    "docs/APP_UPDATE_AND_RELEASE.md",
    "docs/AI_ASSISTANT_PLAN_V3.md",
]

#: 逐条替换（写全路径 / 加反例标记）
REPLACEMENTS: list[tuple[str, str, str]] = [
    (
        "docs/AI_ASSISTANT_PLAN_V3.md",
        "| `app/src/test/.../AiStreamTest.kt` |",
        "| `android/app/src/test/java/com/tapmoay/sorders/ai/AiStreamTest.kt` |",
    ),
    (
        "docs/AI_ASSISTANT_PLAN_V3.md",
        "| `app/src/test/.../LlmStreamingIntegrationTest.kt` |",
        "| `android/app/src/test/java/com/tapmoay/sorders/ai/LlmStreamingIntegrationTest.kt` |",
    ),
    (
        "docs/AI_ASSISTANT_PLAN_V3.md",
        "| `app/src/test/.../LlmRealEndpointTest.kt` |",
        "| `android/app/src/test/java/com/tapmoay/sorders/ai/LlmRealEndpointTest.kt` |",
    ),
    (
        "docs/AI_ASSISTANT_PLAN_V3.md",
        "| `app/src/test/.../AiMemoryTest.kt` |",
        "| `android/app/src/test/java/com/tapmoay/sorders/ai/AiMemoryTest.kt` |",
    ),
    (
        "docs/AI_ASSISTANT_PLAN_V3.md",
        "`docs/ai/ref-operit-memory.md`",
        "`docs/ai/ref-operit-memory.md` [ignore-ref]（这份对照笔记已删）",
    ),
    (
        "docs/AI_ASSISTANT_PLAN_V3.md",
        "`docs/ai/ai-vertical-agent-plan.md`",
        "`docs/ai/ai-vertical-agent-plan.md` [ignore-ref]（这份草稿已删）",
    ),
    (
        "docs/PROJECT_MAP/03_BACKEND_DETAILS.md",
        "`_sio_test.py`",
        "`_sio_test.py` [ignore-ref]（本机一次性联调脚本，未入库）",
    ),
    (
        "docs/PROJECT_MAP/99_STRESS_TEST_REPORT.md",
        "- **已有正向缓解**：60s/手机号频控 + 5min TTL + 一次性消费（`sms_code.py`）✅",
        "- **已有正向缓解**：60s/手机号频控 + 5min TTL + 一次性消费（`sms_code.py` [ignore-ref]——"
        "**该文件与整套验证码功能已在后续版本整体删除**）✅",
    ),
    (
        "docs/PROJECT_MAP/99_STRESS_TEST_REPORT.md",
        "**整体删除**（连同 `sms_code.py`、",
        "**整体删除**（连同 `sms_code.py` [ignore-ref]、",
    ),
    (
        "docs/AI_ASSISTANT_PLAN_V3.md",
        "| `services/sms_code.py`（整个文件：验证码生成/校验/频控） | 删除 |",
        "| `services/sms_code.py` [ignore-ref]（整个文件：验证码生成/校验/频控） | 删除 |",
    ),
    # 裸文件名（工具解析不到根）：给出真实路径
    (
        "docs/AI_ASSISTANT_PLAN_V3.md",
        "实测（含 `openapi.json` 的 operationId）确认：",
        "实测（含 `backend/openapi.json` 的 operationId）确认：",
    ),
    (
        "docs/AI_ASSISTANT_PLAN_V3.md",
        "`ai_memory.json`",
        "`ai_memory.json` [ignore-ref]（App 数据目录下的运行时文件，不在仓库里）",
    ),
]


def main() -> int:
    bad = 0
    for doc in NEED_PREFIX:
        p = ROOT / doc
        s = io.open(p, encoding="utf-8").read()
        if "ref-prefix: android/app/src/main/java/com/tapmoay/sorders/" in s:
            print(f"  跳过（已有前缀）：{doc}")
            continue
        # ⚠️ 前缀**必须放在文件顶部**：它的语义是"从这一行起生效直到文件结束"，
        #    追加在文末等于一行都不生效（第一版就是这么写的，重跑之后一处都没修好）。
        lines = s.split("\n")
        # 插在第一个标题之后（第 1 行通常是 `# 标题`），标题前不放注释块更符合文档习惯
        insert_at = 1 if lines and lines[0].startswith("#") else 0
        lines.insert(insert_at, "")
        lines.insert(insert_at + 1, AND_PREFIX)
        io.open(p, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
        print(f"  ✓ 补前缀（顶部）：{doc}")

    for doc, old, new in REPLACEMENTS:
        p = ROOT / doc
        s = io.open(p, encoding="utf-8").read()
        if old not in s:
            print(f"  ✗ {doc}：找不到 {old[:50]!r}")
            bad += 1
            continue
        s = s.replace(old, new)
        io.open(p, "w", encoding="utf-8", newline="\n").write(s)
        print(f"  ✓ {doc}：{old[:44]!r} → 已修")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
