"""反向验证：**写覆盖率必须自己算端点清单**（2026-09-19 修的那条假绿）。

## 为什么要单独一份
`_write_coverage.py` 原来读 `docs/ai/write-endpoints.json` —— 一份**签入的**、
只能靠人记得重跑 `_dump_write_endpoints.py` 才更新的快照。实测它停在 2026-09-18 21:57，
之后新加的写端点（`place-categories` 五个 + `auth/logout`）**一个都没进那张表**，
于是这条"AI 写能力覆盖率"红线报「0 个真缺口」——**假绿**，
而它守的正是"用户新加的功能 AI 能不能做"这条硬要求。

修法：清单改成**调 `_dump_write_endpoints.handlers()` 现算**。
本脚本注入"源码里多了一个写端点"，判据必须报出来 —— 这一条正是"清单是不是活的"的判据。

用法：python _tools/ai/_reverse_verify_coverage_input.py
"""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "ai" / "_write_coverage.py"
TARGET = ROOT / "backend" / "app" / "api" / "v1" / "places.py"

#: 一段**真的**会被端点解析器认出来的路由 + 处理函数（形状与真端点一致）。
INJECTED = '''

@router.post("/__probe_new_write_endpoint")
def __probe_new_write_endpoint(body: dict) -> dict:
    """反向验证用的探针端点：它只存在于注入期间。"""
    return {"ok": True}
'''


def run_check() -> int:
    p = subprocess.run(
        [sys.executable, str(CHECK), "--check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    return p.returncode


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    if run_check() != 0:
        print("❌ 前提不成立：源码完好时覆盖率就没过")
        return 1
    print("✅ 前提：源码完好时覆盖率是绿的")

    fails: list[str] = []
    try:
        TARGET.write_text(original + INJECTED, encoding="utf-8", newline="")
        code = run_check()
    finally:
        TARGET.write_text(original, encoding="utf-8", newline="")

    if code != 0:
        print("✅ 注入「多了一个写端点」→ 覆盖率报红（清单是活的）")
    else:
        fails.append(
            "注入一个新写端点之后覆盖率**没有报红** —— 端点清单又变成静态的了（假绿会回来）"
        )

    if TARGET.read_text(encoding="utf-8") != original:
        fails.append("收尾没还原 places.py")
    if run_check() != 0:
        fails.append("还原之后覆盖率仍然红")

    if fails:
        print("\n❌ 反向验证没通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print("\n✅ 1/1 通过，且源码已还原。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
