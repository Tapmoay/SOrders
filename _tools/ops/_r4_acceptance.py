# -*- coding: utf-8 -*-
"""R4-08 的**最终架构验收**：五条判据逐条拿证据，⛔ 不看"模块数量增加了多少"。

## 指南 §41 那五条（原话）

1. 新增扩展**不会污染 Core**
2. 替换扩展**不会修改 Core**
3. 删除扩展**不会破坏 Core**
4. 扩展依赖**全部可见**
5. **历史核心事实不会因为扩展删除而失效**

## 这一页怎么判（⛔ 一律拿"跑出来的东西"，不拿散文）

| 判据 | 证据 |
| --- | --- |
| 1 新增 | `_r4_add_drill.py --check`：区间内核心改 **0 行**、既有扩展模块改 **0 个** |
| 2 替换 | `_r4_replace_drill.py --check`：同一张订单换数据就换算法，核心 0 行 |
| 2b 兼容 | `_r4_compat_drill.py --check`：v1 实现经适配器照常跑、v2 实现可加入，核心 0 行 |
| 3 删除 | `_tools/ops/r4_drill_records/remove-drill.json`：四步（停用/卸载/删代码/数据）逐条 OK |
| 4 依赖可见 | `_check_extension_dependencies.py --graph` + `_check_core_extension_boundary.py`（表/事件/域全有归属） |
| 5 历史不失效 | `_check_data_ownership.py`（扩展不认领核心表 + 快照列在）+ 删除演练的"47 张表逐名一致" |

用法：python _tools/ops/_r4_acceptance.py --check
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / "_tools" / "ops" / "r4_drill_records"

#: (判据, 怎么跑, 期望) —— 全部是**可复现的命令**，⛔ 没有一条是"我看过了"。
DRILLS = (
    ("1 新增扩展不污染 Core", ["_tools/ops/_r4_add_drill.py", "--check"]),
    ("2 替换扩展不修改 Core", ["_tools/ops/_r4_replace_drill.py", "--check"]),
    ("2b 契约升级（v1 -> v2）核心不改", ["_tools/ops/_r4_compat_drill.py", "--check"]),
    ("4 扩展依赖全部可见（依赖图生成得出来）", ["_tools/ops/_r4_drill_graph.py"]),
)
CHECKERS = (
    ("4 扩展依赖全部可见（四条防火墙规则）", "_tools/qa/_check_extension_dependencies.py"),
    ("4 表 / 事件 / 域全有归属", "_tools/qa/_check_core_extension_boundary.py"),
    ("5 历史核心事实不因扩展删除而失效", "_tools/qa/_check_data_ownership.py"),
    ("清单契约三方一致 + 禁止动态加载", "_tools/qa/_check_extension_manifest.py"),
    ("契约只有声明没有实现 + 钱的口径对账", "_tools/qa/_check_extension_contracts.py"),
)


def run(args: list[str]) -> tuple[int, str]:
    r = subprocess.run([sys.executable, *args], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def last_line(out: str) -> str:
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[-1] if lines else "（没有输出）"


def main() -> int:
    fails: list[str] = []
    print("== R4 最终架构验收：五条判据逐条拿证据 ==")
    print()

    for label, args in DRILLS:
        code, out = run(args)
        print("  [" + ("OK" if code == 0 else "FAIL") + "] " + label)
        print("         " + last_line(out)[:150])
        if code != 0:
            fails.append(label)

    print()
    print("== 检查器（判据本身，进全量静态检查）==")
    for label, rel in CHECKERS:
        code, out = run([rel])
        print("  [" + ("OK" if code == 0 else "FAIL") + "] " + label)
        print("         " + last_line(out)[:150])
        if code != 0:
            fails.append(label)

    print()
    print("== 3 删除扩展不破坏 Core（读演练记录，⛔ 不重跑那 4 分钟）==")
    record = RECORDS / "remove-drill.json"
    if not record.exists():
        print("  [FAIL] 找不到 " + str(record.relative_to(ROOT)) + " —— 先跑一次 Remove 演练")
        fails.append("3 删除扩展不破坏 Core")
    else:
        data = json.loads(record.read_text(encoding="utf-8"))
        steps = data.get("steps", [])
        bad = [s for s in steps if s.get("verdict") != "OK"]
        print("  [" + ("OK" if not bad else "FAIL") + "] 删除演练 " + str(data.get("ran_at", "?"))
              + "：" + str(len(steps) - len(bad)) + "/" + str(len(steps)) + " 步 OK")
        for s in bad:
            print("         FAIL " + str(s.get("step")) + " —— " + str(s.get("detail"))[:120])
        if bad or not steps:
            fails.append("3 删除扩展不破坏 Core")

    print()
    print("=" * 60)
    if fails:
        print("❌ R4 验收不通过：" + str(len(fails)) + " 条")
        for f in fails:
            print("   - " + f)
        return 1
    print("✅ 五条判据全部成立（证据是上面每一条自己跑出来的输出，不是散文）：")
    print("   1 新增不污染 Core｜2 替换不改 Core（含契约 v1->v2）｜3 删除不破坏 Core")
    print("   4 依赖全部可见｜5 历史核心事实不因扩展删除而失效")
    print()
    print("   ⛔ 指南 §41 明确：看的**不是**「模块数量增加了多少」。")
    print("   ⛔ 这三条（Add / Replace / Remove）在本轮**都是实际演练**，不是静态概念。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())