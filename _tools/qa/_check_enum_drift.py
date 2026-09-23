"""红线：**枚举列不许漂移** —— 取值清单只能有一份，且必须从模型生成（2026-09-23 第 10 轮）。

## 由来（真有事故，而且这一轮又抓到两处"过期清单"）

MySQL 里往枚举列写一个**不在枚举里**的值，是**直接报错**。老库那一列可能停在更早的取值集合上，
于是"新加了一个状态/来源"就变成线上 500 —— 2026-09-04 那两次生产事故正是这个形状：
`orders.status` 缺 `DISPATCHED`（派单 100% 500）、`ledgers.source` 缺 `REFUND`（货损完成 500）。
当时的修法是在 `schema_bootstrap` 里手写 `ALTER TABLE … MODIFY COLUMN … ENUM(…)`。

**本判据立起来的那一轮就抓到了两处过期的字面量**：同一个文件里手写了**四**句，
其中两句是旧的（`orders.status` 少 `RETURNED`、`ledgers.source` 少 `RETURN`）。
它们谁都不报错：老库 4 态启动时先被旧那句改成 5 态、再被后面那句补到 6 态，结果碰巧是对的 ——
**但删掉/挪动后面那句，列就会被改成缺值的版本**，而真正的报错发生在几天后某个人点"退回"的那一刻。

## 判据（清单**全部自己算**，不手写"查哪些列"）

1. **枚举列清单**从 SQLAlchemy metadata 盘（`Base.metadata` 里所有 `Enum` 型列）+ 数量下限
   —— 盘空了要先报错，不能安静通过；
2. **bootstrap 里不许再出现手写的 `MODIFY COLUMN … ENUM(…)` 字面量**（走 AST 取字符串常量，
   ⛔ 文档字符串与注释不算代码：它们不执行，藏在里面不会有事）；
3. **自愈循环必须覆盖模型里每一个枚举列**（`_enum_columns()` 是唯一清单，循环里调 `enum_repair_ddl`）；
4. **生成出来的 DDL 必须真的是模型那一份取值**（逐列调用生成器，断言每个取值都在、列序一致、
   `NULL/NOT NULL` 跟着模型的 `nullable`）—— 这条是"清单真的来自模型"的运行时证据；
5. **线上库那一侧在探针里**：本脚本只看代码，所以额外断言
   `_tools/qa/_probe_prod_readonly.py` 里**真的有**"代码 ↔ 线上 `COLUMN_TYPE`"的对账
   —— 否则会出现"两边都以为对方在查线上库"，而老库缺值恰恰只在线上。

配套（都不需要人记得）：
- 文本层：`backend/tests/test_enum_repair_ddl.py`（逐列 + `orders.status` 那句全文）；
- 真机层：`_tools/qa/_probe_prod_readonly.py --validate-ddl`（在生产 MySQL 的临时表上造
  "旧枚举 + 已有数据"，跑生成出来的 DDL，验新值写得进、老数据不丢）。

⚠️ 注入式反向验证（改坏 → 本脚本必须红）：`_tools/qa/_reverse_verify_enum_drift.py`。

用法：python _tools/qa/_check_enum_drift.py
"""
from __future__ import annotations

import ast
import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
BOOTSTRAP = BACKEND / "app" / "core" / "schema_bootstrap.py"
PROBE = ROOT / "_tools" / "qa" / "_probe_prod_readonly.py"

sys.path.insert(0, str(BACKEND))
import app.models  # noqa: E402,F401  —— 导入真正的 app，让盘点看到"应用实际注册的"全部模型
from app.core.schema_bootstrap import _enum_columns, enum_repair_ddl  # noqa: E402
from app.models.base import Base  # noqa: E402
from sqlalchemy import Enum as SAEnum  # noqa: E402

#: 盘到的枚举列数量下限（当前 5）。防"metadata 没导进来 → 一条都不查还全绿"。
MIN_ENUM_COLUMNS = 5
#: 历史上真的缺过值、真的 500 过的那两列（它们必须落在自愈覆盖里）。
HISTORICAL = {
    ("orders", "status"): "RETURNED",
    ("ledgers", "source"): "RETURN",
}
#: 探针里那段"代码 ↔ 线上库"对账的锚点（判据 ⑤）。
PROBE_ANCHOR = "def enum_drift_section("

#: `ALTER TABLE <t> MODIFY COLUMN <c> ENUM('A','B',…)`（**代码里**出现的 = 又抄了一份清单）
HARDCODED_RE = re.compile(
    r"ALTER\s+TABLE\s+`?(\w+)`?\s+MODIFY\s+COLUMN\s+`?(\w+)`?\s+ENUM\s*\(([^)]*)\)",
    re.IGNORECASE,
)

fails: list[str] = []
passes = 0


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def code_strings(path: Path) -> list[str]:
    """取一个 .py 里所有**会执行的**字符串常量（AST；文档字符串与注释都不算）。

    ⚠️ 为什么不直接 `re.search` 整个文件：`schema_bootstrap.py` 里满是中文注释
    （"orders.status 枚举补 RETURNED（已退货）"），正则会把注释里的例子当成真 DDL ——
    那正是"判据看着在查、其实在查注释"。文档字符串同理：它不执行，藏在里面不会有事。
    """
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def main() -> int:
    # ---- ① 枚举列清单（自己盘，带下限）----
    print("① 枚举列清单（从 SQLAlchemy metadata 盘出来，不手写）")
    counted = sorted(Base.metadata.tables.items())
    model_cols: list[tuple[str, object]] = [
        (tname, col)
        for tname, table in counted
        for col in table.columns
        if isinstance(col.type, SAEnum)
    ]
    ok(f"盘到 {len(model_cols)} 个枚举列（下限 {MIN_ENUM_COLUMNS}）",
       len(model_cols) >= MIN_ENUM_COLUMNS,
       "盘空了说明 metadata 没导入成功 —— 那样本脚本会一条都不查却全绿")
    for tname, col in model_cols:
        print(f"      · {tname}.{col.name}（{len(col.type.enums)} 个取值）")

    # ---- ② 不许再有手写的 ENUM 字面量 ----
    print("\n② bootstrap 里不许再有手写的 `MODIFY COLUMN … ENUM(…)` 清单")
    hard: list[str] = []
    for s in code_strings(BOOTSTRAP):
        for m in HARDCODED_RE.finditer(s):
            hard.append(f"{m.group(1)}.{m.group(2)}")
    ok("一句手写的 ENUM 清单都没有（取值只从模型生成）", not hard,
       f"又抄了一份清单：{hard} —— 这正是 2026-09-23 抓到两处过期清单的形状")

    # ---- ③ 自愈循环必须覆盖每一个枚举列 ----
    print("\n③ 自愈循环必须覆盖模型里每一个枚举列")
    boot = io.open(BOOTSTRAP, encoding="utf-8", errors="replace").read()
    ok("有 `_enum_columns()` 这个唯一清单", "def _enum_columns(" in boot)
    ok("循环里遍历它（`for … in _enum_columns():`）",
       re.search(r"for\s+\w+,\s*\w+\s+in\s+_enum_columns\(\)\s*:", boot) is not None)
    ok("循环里调生成器（不是自己拼 DDL）",
       "conn.execute(text(enum_repair_ddl(" in boot)
    ok("自愈只在 MySQL 分支跑（SQLite 没有 ENUM）",
       re.search(r'if dialect == "mysql":[\s\S]{0,4000}?_enum_columns\(\)', boot) is not None)
    covered = {t for t, _ in _enum_columns()}
    counted_tables = {t for t, _ in model_cols}
    ok(f"`_enum_columns()` 覆盖 {len(covered)} 张表（盘点出来的表都在里面）",
       counted_tables == covered,
       f"盘点 {sorted(counted_tables)} vs 自愈 {sorted(covered)}")

    # ---- ④ 生成出来的 DDL 必须是模型那一份取值 ----
    print("\n④ 生成器必须真的用模型里的取值（逐列调用它，看 DDL 文本）")
    for tname, col in model_cols:
        ddl = enum_repair_ddl(tname, col)
        values = [str(v) for v in col.type.enums]
        missing = [v for v in values if f"'{v}'" not in ddl]
        want_null = "NULL" if col.nullable else "NOT NULL"
        shape_ok = (
            ddl.startswith(f"ALTER TABLE `{tname}` MODIFY COLUMN `{col.name}` ENUM(")
            and ddl.rstrip().endswith(want_null)
        )
        ok(f"`{tname}.{col.name}` 的 DDL 含全部 {len(values)} 个取值且形状正确"
           + ("（含 NOT NULL）" if not col.nullable else ""),
           not missing and shape_ok,
           (f"缺 {missing}" if missing else "") + ("" if shape_ok else f" 形状不对：{ddl}"))
    for (t, c), must_have in HISTORICAL.items():
        col = next((x for tt, x in model_cols if tt == t and x.name == c), None)
        ddl = enum_repair_ddl(t, col) if col is not None else ""
        ok(f"历史事故那一列 `{t}.{c}` 的 DDL 里有 `{must_have}`（当年缺的就是它）",
           f"'{must_have}'" in ddl, "生成器没有把这一列算进去？")

    # ---- ⑤ 线上库那一侧在探针里 ----
    print("\n⑤ 线上库那一侧：本脚本只看代码，断言探针里真的有对账那一段")
    probe = io.open(PROBE, encoding="utf-8", errors="replace").read()
    ok(f"`{PROBE.name}` 里有 `{PROBE_ANCHOR}`（代码 ↔ 线上库 COLUMN_TYPE 对账）",
       PROBE_ANCHOR in probe,
       "没有它的话，两边都以为对方在查线上库 —— 而老库缺值正是只会在线上出现的那一类")

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {passes} 项通过：{len(model_cols)} 个枚举列的取值只有一份（模型），"
          f"bootstrap 的补全 DDL 由它生成，线上那一侧由探针盯着。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
