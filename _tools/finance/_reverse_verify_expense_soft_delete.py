#!/usr/bin/env python3
"""反向验证 _tools/finance/_check_expense_soft_delete.py 真的会红（BUG-0034 / 台账 TA-16）。

## 为什么是这一份
这一单的判据是「接线型」的（某处必须有某个写法、某处不许再有某个写法；「从 expenses 取数」
的清单由脚本自己扫出来）。接线型判据最典型的失效方式是**锚点悄悄失配**：过滤被删掉一行、
软删被改成物理删、中文名被摘掉、恢复改成"按出参重建一条" —— 判据都必须当场红，而且红的
必须是**那一条**判据变红（片段要真的落在某个 [!!] 行里），不是随便红一条。

## 19 种破坏（每一种都必须让判据当场红，且报出对应那条标签）

| # | 注入 | 现实里谁会这么改 |
| --- | --- | --- |
| ① | 模型不再继承 SoftDeleteMixin | 「列已经加过了，模型上写不写无所谓」 |
| ② | bootstrap 里 is_deleted 的 DDL 丢掉 NOT NULL DEFAULT 0 | 抄漏了默认值（回填前 NULL 会整行漏掉） |
| ③ | 回填改成留 NULL | 「NULL 就是没删过嘛」——历史开销会整体从账上消失 |
| ④ | 恢复时顺手规整一下分类 | 一行"顺手"，字段就漂了（不再是原样放回） |
| ⑤ | 列表改回「恒过滤未撤销」 | 忘了 deleted_only 这一档，回收站永远空 |
| ⑥ | 恢复只摘开销单、不摘流水上的标记 | 开销回来了、收支页里那笔钱还是不算 |
| ⑦ | 利润表的期间费用去掉过滤 | 「报表那点差异没人看得出来」 |
| ⑧ | 分类名册的在用笔数去掉过滤 | 名册说 1 笔、点进去列表是空的 |
| ⑨ | 撤销改成物理删（db.delete） | 「软删还得加列，直接删干净」 |
| ⑩ | ReportCenter 的 EXPENSE_DELETE 中文名摘掉 | 新增审计码忘了加中文名 |
| ⑪ | 安卓 DTO 不再解析 is_deleted / deleted_at | 后端加了字段、客户端没接 |
| ⑫ | Apis.kt 的 @DELETE 注解被注释掉 | 「先把危险的入口收起来」 |
| ⑬ | 开销页那一档不再传 deleted_only | 档位画了、参数没接上（点进去还是那批行） |
| ⑭ | 单测的等式放宽成 >= 0 | 断言越写越松，两边差多少都算过 |
| ⑮ | 覆盖率里那条书面理由被挪走 | 「端点做完了，理由表里那条可以删了」 |
| ⑯ | 台账 TA-16 的状态改回「已复现」 | 修完忘了更新台账 |
| ⑰ | 声明页里核心改动的路径被写坏 | 路径抄错一个字符（判据只认确切那一条） |
| ⑱ | 变更单头部的 ID 行被改掉 | 复制模板忘了改 ID |
| ⑲ | 变更单索引里的链接被摘掉 | 少那个链接 _check_dev_spec.py 会红 |

⚠️ 与仓库里其它 _reverse_verify_*.py 同一套纪律：按字节备份 / 还原、跑完逐文件核对哈希、
全程不碰 git checkout --（那会在真有改动时抹掉工作）。
⚠️ 跑之前先确认没人正在改这些文件（先看 git status）：注入期间它们会被重写又逐字节写回。

用法：python _tools/finance/_reverse_verify_expense_soft_delete.py
      python _tools/finance/_reverse_verify_expense_soft_delete.py --list
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/finance/_check_expense_soft_delete.py"

AND = "android/app/src/main/java/com/tapmoay/sorders"
API = "backend/app/api/v1/expenses.py"
CATS = "backend/app/api/v1/expense_categories.py"
MODEL = "backend/app/models/expense.py"
BOOT = "backend/app/core/schema_bootstrap.py"
PROFIT = "backend/app/services/reports/profit_query.py"
TEST = "backend/tests/test_expense_soft_delete.py"
COVERAGE = "_tools/ai/_write_coverage.py"
LEDGER = "docs/TEST_BUG_LEDGER.md"
CHANGE = "docs/changes/BUG-0034.md"
CHANGE_IDX = "docs/changes/README.md"
CLAIM = "docs/AI_WORK_CLAIM.md"
DTO = AND + "/data/remote/dto/Dtos.kt"
APIS = AND + "/data/remote/api/Apis.kt"
SCREEN = AND + "/ui/dispatcher/ExpensesScreen.kt"
RC = AND + "/ui/dispatcher/ReportCenter.kt"

#: (说明, 文件, 原文, 替换成, 期望出现在失败清单里的标签片段, 命中次数)
CASES: list[tuple[str, str, str, str, str, int | str]] = [
    (
        "① 模型不再继承 SoftDeleteMixin（列在库里、模型上不认）",
        MODEL,
        "class Expense(Base, TimestampMixin, SoftDeleteMixin):\n",
        "class Expense(Base, TimestampMixin):\n",
        "Expense 继承了 SoftDeleteMixin", 1,
    ),
    (
        "② bootstrap 里 is_deleted 的 DDL 丢掉 NOT NULL DEFAULT 0（抄漏了默认值）",
        BOOT,
        '        expense_cols = {c["name"] for c in insp.get_columns("expenses")}\n'
        "        with engine.begin() as conn:\n"
        '            for col, ddl_type in (("is_deleted", "BOOLEAN NOT NULL DEFAULT 0"), ("deleted_at", "DATETIME")):\n',
        '        expense_cols = {c["name"] for c in insp.get_columns("expenses")}\n'
        "        with engine.begin() as conn:\n"
        '            for col, ddl_type in (("is_deleted", "BOOLEAN"), ("deleted_at", "DATETIME")):\n',
        "补列 is_deleted BOOLEAN NOT NULL DEFAULT 0", 1,
    ),
    (
        "③ 回填改成留 NULL（历史开销会整体从账上消失）",
        BOOT,
        'conn.execute(text("UPDATE expenses SET is_deleted = 0 WHERE is_deleted IS NULL"))',
        'conn.execute(text("UPDATE expenses SET is_deleted = NULL WHERE is_deleted IS NULL"))',
        "回填写成 SET is_deleted = 0（不是留 NULL）", 1,
    ),
    (
        "④ 恢复时顺手规整一下分类（一个字段漂了，就不是原样放回）",
        API,
        "    e.is_deleted = False\n    e.deleted_at = None\n    write_log(\n",
        "    e.category = str(e.category).strip()\n    e.is_deleted = False\n    e.deleted_at = None\n    write_log(\n",
        "restore_expense 除了两个标记列之外不给任何字段赋值", 1,
    ),
    (
        "⑤ 列表改回「恒过滤未撤销」（deleted_only 那一档永远是空的）",
        API,
        "    stmt = stmt.where(Expense.is_deleted.is_(deleted_only))\n",
        "    stmt = stmt.where(Expense.is_deleted.is_(False))\n",
        "列表本体是「二选一档」", 1,
    ),
    (
        "⑥ 恢复只摘开销单、不摘流水上的标记（收支页里那笔钱还是不算）",
        API,
        "    flows = _expense_flows(db, e.id)\n"
        "    for f in flows:\n"
        "        f.is_deleted = False\n"
        "        f.deleted_at = None\n"
        "    e.is_deleted = False\n",
        "    flows = _expense_flows(db, e.id)\n"
        "    e.is_deleted = False\n",
        "恢复把两处标记都摘掉", 1,
    ),
    (
        "⑦ 利润表的期间费用去掉过滤（这笔钱撤销了、合计里还在算）",
        PROFIT,
        "            Expense.is_deleted.is_(False),\n",
        "",
        "利润表的期间费用 过滤了已撤销", 1,
    ),
    (
        "⑧ 分类名册的在用笔数去掉过滤（名册说 1 笔、点进去列表是空的）",
        CATS,
        "        select(Expense.category, func.count(Expense.id))\n"
        "        .where(Expense.is_deleted.is_(False))\n"
        "        .group_by(Expense.category)\n"
        '    ).all()\n    return {(str(getattr(name, "value", name) or "")).strip(): n for name, n in rows if str(name or "").strip()}\n',
        "        select(Expense.category, func.count(Expense.id))\n"
        "        .group_by(Expense.category)\n"
        '    ).all()\n    return {(str(getattr(name, "value", name) or "")).strip(): n for name, n in rows if str(name or "").strip()}\n',
        "个取数函数都带 is_deleted 过滤", 1,
    ),
    (
        "⑨ 撤销改成物理删（历史直接从账上抹掉）",
        API,
        "    e.is_deleted = True\n",
        "    db.delete(e)\n",
        "这个文件里没有 db.delete(", 1,
    ),
    (
        "⑩ ReportCenter 里 EXPENSE_DELETE 的中文名摘掉（审计页显示原始码）",
        RC,
        '    "EXPENSE_DELETE" -> "撤销一笔开销"\n',
        '    "EXPENSE_DELETE" -> "EXPENSE_DELETE"\n',
        "ReportCenter.kt::actionLabel 有 EXPENSE_DELETE 的中文名", 1,
    ),
    (
        "⑪ 安卓 DTO 不再解析 is_deleted / deleted_at（后端加了、客户端没接）",
        DTO,
        "     *    不会把一笔正常的开销误画成已撤销。\n"
        "     */\n"
        '    @SerialName("is_deleted") val isDeleted: Boolean = false,\n'
        '    @SerialName("deleted_at") val deletedAt: String? = null,\n',
        "     *    不会把一笔正常的开销误画成已撤销。\n     */\n",
        "ExpenseDto 解析 is_deleted", 1,
    ),
    (
        "⑫ Apis.kt 的 @DELETE 注解被注释掉（客户端收起了撤销的入口）",
        APIS,
        '    @DELETE("expenses/{expenseId}")\n    suspend fun deleteExpense(@Path("expenseId") expenseId: Long)\n',
        '    // @DELETE("expenses/{expenseId}")\n    suspend fun deleteExpense(@Path("expenseId") expenseId: Long)\n',
        'Apis.kt 有 @DELETE("expenses/{expenseId}")', 1,
    ),
    (
        "⑬ 开销页那一档不再传 deleted_only（档位画了、参数没接上）",
        SCREEN,
        "                    deletedOnly = showDeleted,\n",
        "                    deletedOnly = false,\n",
        "那一档真的把 deleted_only 传下去", 1,
    ),
    (
        "⑭ 单测的等式放宽成 >= 0（差多少都算过）",
        TEST,
        "        assert b - after[name] == amount, (\n",
        "        assert b - after[name] >= 0, (\n",
        "单测钉着「删前 − 这一笔 = 删后」的等式", 1,
    ),
    (
        "⑮ 覆盖率里那条书面理由被挪走（端点做完了，理由表里那条删了）",
        COVERAGE,
        '    ("DELETE", "expenses/{}"): (\n',
        '    ("DELETE", "expenses/:id"): (\n',
        '_write_coverage.py 的 EXCLUDED 里有 ("DELETE", "expenses/{}") 的书面理由', 1,
    ),
    (
        "⑯ 台账 TA-16 的状态改回「已复现」（修完忘了更新台账）",
        LEDGER,
        "记错一笔永久留在账上 | 堵死 | ",
        "记错一笔永久留在账上 | 堵死 | 已复现 | ",
        "台账 TA-16 那一行的状态不再是「已复现」", 1,
    ),
    (
        "⑰ 声明页里核心改动的路径被写坏（schema_bootstrap_OLD.py）",
        CLAIM,
        "核心改动：backend/app/core/schema_bootstrap.py",
        "核心改动：backend/app/core/schema_bootstrap_OLD.py",
        "AI_WORK_CLAIM.md 声明了核心改动（schema_bootstrap）", "all",
    ),
    (
        "⑱ 变更单头部的 ID 行被改掉（复制模板忘了改）",
        CHANGE,
        "- **ID**：BUG-0034",
        "- **ID**：BUG-0000",
        "变更单头部有 - **ID**：BUG-0034", 1,
    ),
    (
        "⑲ 变更单索引里的链接被摘掉（少这个链接 _check_dev_spec.py 红）",
        CHANGE_IDX,
        "](BUG-0034.md)",
        "](BUG-0034)",
        "docs/changes/README.md 里那一行带 ](BUG-0034.md) 链接", 1,
    ),
]


class Sandbox:
    """按字节记账的注入台：每条注入都从最初那份字节重来，末尾逐字节还原并读回校验。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}
        self.digests: dict[Path, str] = {}

    def _snapshot(self, path: Path) -> None:
        if path not in self.saved:
            raw = path.read_bytes()
            self.saved[path] = raw
            self.digests[path] = hashlib.sha256(raw).hexdigest()

    def apply(self, rel: str, old: str, new: str, count: int | str = 1) -> None:
        path = ROOT / rel
        if not path.is_file():
            raise ValueError("文件不在：" + rel)
        self._snapshot(path)
        raw = self.saved[path]
        crlf = b"\r\n" in raw  # 本仓库混着 CRLF/LF：按原样还原，不猜
        text = raw.decode("utf-8").replace("\r\n", "\n")
        found = text.count(old)
        if count == "all":
            if found < 1:
                raise ValueError("锚点一处都没命中：" + rel)
            text = text.replace(old, new)
        else:
            if found != 1:
                raise ValueError(f"锚点命中 {found} 次（要求 1 次）：" + rel)
            text = text.replace(old, new, 1)
        out = text.replace("\n", "\r\n") if crlf else text
        path.write_bytes(out.encode("utf-8"))

    def restore(self) -> None:
        for path, raw in self.saved.items():
            path.write_bytes(raw)

    def verify(self) -> list[str]:
        bad: list[str] = []
        for path, digest in self.digests.items():
            now = hashlib.sha256(path.read_bytes()).hexdigest()
            if now != digest:
                bad.append(path.relative_to(ROOT).as_posix())
        return bad


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列注入表，不改任何文件")
    args = ap.parse_args()
    if args.list:
        for i, case in enumerate(CASES, 1):
            print(f"{i:>2}. {case[0]}")
        return 0

    lock_reverse_verify()
    sb = Sandbox()
    total = bad = 0
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：判据本来就是红的，先把它修绿再做反验。")
            print("\n".join(out.splitlines()[-12:]))
            return 1
        green = [ln for ln in out.splitlines() if ln.startswith("✅")]
        print("前提：判据当前是绿的 —— " + (green[-1] if green else "（没有读到汇总行）"))
        print("")
        for case in CASES:
            why, rel, old, new, want, count = case
            total += 1
            sb.restore()
            try:
                sb.apply(rel, old, new, count)
            except ValueError as ex:
                bad += 1
                print(f"  ❌ 注入失败：{why} —— {ex}")
                continue
            code, out = run_check()
            red_lines = [ln.strip() for ln in out.splitlines() if ln.startswith("  [!!]")]
            # 片段必须落在**某一条真的报红**的判据行里（不是随便哪一行提到这几个字）
            if code != 0 and any(want in ln for ln in red_lines):
                print(f"  ✅ 红了：{why}")
            else:
                bad += 1
                print(f"  ❌ 没红 / 红错了判据：{why}")
                print("     判据实际报的：" + ("；".join(red_lines[:4]) if red_lines else "（一条都没报）"))
    finally:
        sb.restore()
        unlock_reverse_verify()

    left = sb.verify()
    print("")
    if left:
        bad += 1
        print("❌ 没有逐字节还原：" + "、".join(left))
    print("=" * 60)
    if bad:
        print(f"❌ {total - bad}/{total} 成立（{bad} 条不成立）")
        return 1
    print(f"✅ {total}/{total} 都红了：每一种弄坏都被判据当场抓住，源码已逐字节还原。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
