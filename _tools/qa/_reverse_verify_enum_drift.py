"""反向验证 `_tools/qa/_check_enum_drift.py`（红线：枚举列不许漂移）。

## 为什么必须做

这条判据守的事**坏起来一条报错都不会有**：
- 代码里给枚举**加了一个取值**，而 bootstrap 里那句修复 DDL 没跟着改 → 老库那一列缺这个值 →
  **写它就 500**，而新库（`create_all`）是好的，所以本机怎么测都对；
- 有人"顺手"又抄一份 `MODIFY COLUMN … ENUM(…)` 字面量 → 两份清单总有一天对不上
  （2026-09-23 就是这么抓到两处过期的：`orders.status` 少 `RETURNED`、`ledgers.source` 少 `RETURN`）；
- 生成器被改成"从旧定义抄"或"少一个取值" → 补全之后列还是缺值，等于没修；
- 探针里那段"代码 ↔ 线上库"的对账被删 → 两边都以为对方在查线上库。

所以逐条**注入真缺陷**，每条都必须让判据报红；跑完逐字节还原并再验一次绿。

⚠️ 一条刻意**不做**注入的边界：把字面量挪进**文档字符串或注释**里 —— 那不执行，
本判据按设计不看它们（`code_strings()` 走 AST 跳过 docstring），所以它**不该**报红。

用法：python _tools/qa/_reverse_verify_enum_drift.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_enum_drift.py"
BOOTSTRAP = ROOT / "backend/app/core/schema_bootstrap.py"
PROBE = ROOT / "_tools" / "qa" / "_probe_prod_readonly.py"

CASES: list[tuple[str, Path, object]] = [
    # ---- ② 又抄一份手写清单 ----
    (
        "又抄一份 `MODIFY COLUMN … ENUM(…)` 字面量（两份清单总有一天对不上）",
        BOOTSTRAP,
        lambda s: s.replace(
            "                    conn.execute(text(enum_repair_ddl(table_name, column)))",
            "                    conn.execute(text(\n"
            "                        \"ALTER TABLE orders MODIFY COLUMN status \"\n"
            "                        \"ENUM('PENDING_DISPATCH','DISPATCHED','ACCEPTED','DELIVERED','CANCELLED','RETURNED') NOT NULL\"\n"
            "                    ))",
            1,
        ),
    ),
    # ---- ③ 自愈覆盖 ----
    (
        "自愈只覆盖一部分枚举列（`_enum_columns()[:1]`）",
        BOOTSTRAP,
        lambda s: s.replace("for table_name, column in _enum_columns():",
                            "for table_name, column in _enum_columns()[:1]:", 1),
    ),
    (
        "自愈循环不再遍历那份清单（`for … in []:` —— 谁都不会被补全，且一条报错都没有）",
        BOOTSTRAP,
        lambda s: s.replace("for table_name, column in _enum_columns():",
                            "for table_name, column in []:", 1),
    ),
    # ---- ④ 生成出来的 DDL 必须就是模型那一份 ----
    (
        "生成器漏掉最后一个取值（`enums[:-1]`）—— 补全之后列还是缺值",
        BOOTSTRAP,
        lambda s: s.replace('values = ",".join(f"\'{v}\'" for v in column.type.enums)',
                            'values = ",".join(f"\'{v}\'" for v in column.type.enums[:-1])', 1),
    ),
    (
        "生成器不从模型取取值（写死一份）—— 又变成第二份清单，只是藏进了生成器",
        BOOTSTRAP,
        lambda s: s.replace('values = ",".join(f"\'{v}\'" for v in column.type.enums)',
                            'values = "\'ORDER\',\'MANUAL\'"', 1),
    ),
    (
        "生成器把可空性写死（模型是 NOT NULL、DDL 给 NULL）",
        BOOTSTRAP,
        # ⛔ 2026-09-26 修：这一条注入原来**打错了地方**。同一个表达式在 `schema_bootstrap.py` 里出现
        #    **两次** —— 第一次在 **VARCHAR 宽度补全**那段（`_check_enum_drift.py` 不检查它），
        #    第二次才是 `enum_repair_ddl` 里被检查的那一处。写 `, 1` 只改前一处 ⇒ 判据当然不红，
        #    于是这条反向验证**误报**成「这条判据是空转的」（判据没病，是注入瞄错了）。
        #    改成**全替换**：两处都写死成 NULL，被检查的那一处必然变。
        lambda s: s.replace('"NULL" if column.nullable else "NOT NULL"', '"NULL"'),
    ),
    # ---- ① 清单盘空 ----
    (
        "`_enum_columns()` 盘不到任何列（判据会变成空转）",
        BOOTSTRAP,
        lambda s: s.replace("            if isinstance(col.type, SAEnum):",
                            "            if isinstance(col.type, SAEnum) and False:", 1),
    ),
    # ---- ⑤ 线上那一侧 ----
    (
        "探针里那段「代码 ↔ 线上库 COLUMN_TYPE」对账被改名/删掉",
        PROBE,
        lambda s: s.replace("def enum_drift_section(", "def _enum_drift_section_x(", 1),
    ),
]


def run(path: Path) -> int:
    p = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return p.returncode


def main() -> int:
    before = {str(p): p.read_text(encoding="utf-8") for _, p, _ in CASES}
    if run(CHECK) != 0:
        print("❌ 前提不成立：源码完好时这条判据就没过（先让 _check_enum_drift.py 变绿）")
        return 1
    print("✅ 前提：源码完好时判据是绿的")

    fails: list[str] = []
    for label, path, mutate in CASES:
        original_bytes = path.read_bytes()
        original = original_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code = run(CHECK)
        finally:
            path.write_bytes(original_bytes)
        if code != 0:
            print(f"✅ 注入「{label}」→ 报红")
        else:
            fails.append(f"{label}：注入之后没有报红 —— 这条判据是空转的")

    for k, v in before.items():
        if Path(k).read_text(encoding="utf-8") != v:
            fails.append(f"收尾没还原：{k}")
    if run(CHECK) != 0:
        fails.append("还原之后判据仍然红（有文件没被改回来）")

    if fails:
        print("\n❌ 反向验证没通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ {len(CASES)}/{len(CASES)} 种破坏方式全部被抓到，且源码已还原。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
