"""开销单 ↔ 现金流水（BUG-0018 / 台账 TB-02）判据的反向验证：逐条注入「看起来没问题」的坏改法，确认判据真的会红。

## 为什么必须有这一份
`_check_expense_cash_flow.py` 全是静态形状判据（读源码、比对字符串），没有一条会在编译或功能测试里报错。
静态判据最危险的失效方式不是「写错」，而是**空转**：正则写宽了、窗口挪了、文件改名了 —— 它照样打印 [OK]，
而其实什么都没查。唯一能证伪「空转」的办法就是**故意做出它要抓的那种错，看它会不会红** ——
本单要抓的那种错尤其隐蔽：少写一条流水，任何一处代码都不报错（`Expense` 表有行、`CashFlow` 表没有行）。

## 为什么「跳过」也算失败
每条注入都要求原文在该文件里**恰好出现一次**（`count(old) == 1`）：多于一次说明锚点不唯一（可能改错地方），
零次说明源码已经变了、这条注入**根本没生效** —— 后者若静默放过，就会出现「判据没红、但也没人改过代码」的假绿。

## 为什么不用 CREATIONS / DELETIONS
本脚本覆盖的判据全都钉在**显式文件路径**上（没有一处清单是 glob 出来的），挪走文件不会让判据变红，只会让检查
脚本自己读不到文件而崩 —— 崩了就没有 [FAIL] 行，而本脚本的判据恰恰是「期望的检查名出现在 [FAIL] 行里」。

用法：
    python _tools/qa/_reverse_verify_expense_cash_flow.py
    python _tools/qa/_reverse_verify_expense_cash_flow.py --dry   # 只验锚点还在不在，一个字节都不改
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_expense_cash_flow.py"

# (说明, 相对路径, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    # ① 口径表抄第二份到播种脚本（记账与脚本各一份，迟早走散）
    (
        "口径表抄第二份到播种脚本（记账与脚本各一份，迟早走散）",
        "backend/scripts/seed_demo_data.py",
        "    VEHICLE_CATEGORIES = (\"加油\", \"维修\", \"过路\", \"停车\", \"罚款\", \"保险\")",
        "EXPENSE_BIZ_TYPES = {\"加油\": \"EXPENSE_FUEL\"}  # 图省事抄一份\n    VEHICLE_CATEGORIES = (\"加油\", \"维修\", \"过路\", \"停车\", \"罚款\", \"保险\")",
        "EXPENSE_BIZ_TYPES 在整个 backend 里只定义一处",
    ),
    # ② 中文分类名指向错口径（加油→其他）
    (
        "中文分类名指向错口径（加油→其他）",
        "backend/app/services/accounting_service.py",
        "    \"加油\": CashFlowBizType.EXPENSE_FUEL, \"fuel\": CashFlowBizType.EXPENSE_FUEL,",
        "    \"加油\": CashFlowBizType.EXPENSE_OTHER, \"fuel\": CashFlowBizType.EXPENSE_FUEL,",
        "8 个中文分类名都指向对的口径",
    ),
    # ③ 老英文键从表里删掉（迁移前后的库里还有老键）
    (
        "老英文键从表里删掉（迁移前后的库里还有老键）",
        "backend/app/services/accounting_service.py",
        "    \"其他\": CashFlowBizType.EXPENSE_OTHER, \"other\": CashFlowBizType.EXPENSE_OTHER,\n",
        "    \"其他\": CashFlowBizType.EXPENSE_OTHER,\n",
        "8 个老英文键也都在",
    ),
    # ④ 查表前不 strip（" 加油 " 会落错口径）
    (
        "查表前不 strip（\" 加油 \" 会落错口径）",
        "backend/app/services/accounting_service.py",
        "    return EXPENSE_BIZ_TYPES.get(str(category).strip(), CashFlowBizType.EXPENSE_OTHER)",
        "    return EXPENSE_BIZ_TYPES.get(str(category), CashFlowBizType.EXPENSE_OTHER)",
        "查表前先 strip",
    ),
    # ⑤ 认不出的分类改成抛 KeyError（新分类下记不进开销）
    (
        "认不出的分类改成抛 KeyError（新分类下记不进开销）",
        "backend/app/services/accounting_service.py",
        "    return EXPENSE_BIZ_TYPES.get(str(category).strip(), CashFlowBizType.EXPENSE_OTHER)",
        "    return EXPENSE_BIZ_TYPES[str(category).strip()]",
        "认不出的分类落 OTHER",
    ),
    # ⑥ 回填脚本自己 import 口径枚举（= 抄了第二份映射）
    (
        "回填脚本自己 import 口径枚举（= 抄了第二份映射）",
        "backend/scripts/backfill_expense_cash_flows.py",
        "from app.services.accounting_service import write_expense_cash_flow",
        "from app.models.enums import CashFlowBizType  # 顺手抄一份\nfrom app.services.accounting_service import write_expense_cash_flow",
        "回填脚本与播种脚本都不许自己写这份映射",
    ),
    # ⑦ 写流水改成从请求体取字段（记账与回填就此走散）
    (
        "写流水改成从请求体取字段（记账与回填就此走散）",
        "backend/app/services/accounting_service.py",
        "    flow = CashFlow(\n        flow_date=expense.exp_date,",
        "    _ = body.amount  # 图省事：从请求体取\n    flow = CashFlow(\n        flow_date=expense.exp_date,",
        "字段全部从 expense. 上取",
    ),
    # ⑧ 流水漏掉 doc_id（回填认不出自己写过，会重复补）
    (
        "流水漏掉 doc_id（回填认不出自己写过，会重复补）",
        "backend/app/services/accounting_service.py",
        "        doc_id=expense.id,\n",
        "",
        "流水字段：doc_id=expense.id",
    ),
    # ⑨ 开销流水写成 IN（钱的方向反了）
    (
        "开销流水写成 IN（钱的方向反了）",
        "backend/app/services/accounting_service.py",
        "        flow_date=expense.exp_date,\n        direction=CashFlowDirection.OUT,",
        "        flow_date=expense.exp_date,\n        direction=CashFlowDirection.IN,",
        "流水字段：direction=CashFlowDirection.OUT",
    ),
    # ⑩ 记账不再写流水（只建单 —— 这次修的正是这件事）
    (
        "记账不再写流水（只建单 —— 这次修的正是这件事）",
        "backend/app/services/accounting_service.py",
        "    write_expense_cash_flow(db, e, operator_id=operator_id)\n    return e",
        "    return e",
        "create_expense 末尾调 write_expense_cash_flow",
    ),
    # ⑪ flush 挪到写流水之后（流水拿不到 expense.id）
    (
        "flush 挪到写流水之后（流水拿不到 expense.id）",
        "backend/app/services/accounting_service.py",
        "    db.add(e)\n    db.flush()\n    # 分类名 → 现金流水口径的映射",
        "    db.add(e)\n    # 分类名 → 现金流水口径的映射",
        "db.flush() 在写流水之前",
    ),
    # ⑫ 共用函数复制成两份（一处改了另一处不会跟着改）
    (
        "共用函数复制成两份（一处改了另一处不会跟着改）",
        "backend/scripts/backfill_expense_cash_flows.py",
        "def expenses_without_cash_flow(db) -> list[Expense]:",
        "def write_expense_cash_flow(db, expense, operator_id=None):  # 抄一份\n    return None\n\n\ndef expenses_without_cash_flow(db) -> list[Expense]:",
        "write_expense_cash_flow() 只定义一处",
    ),
    # ⑬ 播种脚本改回直接 db.add 开销单（绕过记账）
    (
        "播种脚本改回直接 db.add 开销单（绕过记账）",
        "backend/scripts/seed_demo_data.py",
        "        create_expense(db, ExpenseCreate(",
        "        db.add(Expense(",
        "不再直接构造开销单",
    ),
    # ⑭ 中部 import 不带 noqa: E402（脚本既有体例）
    (
        "中部 import 不带 noqa: E402（脚本既有体例）",
        "backend/scripts/seed_demo_data.py",
        "from app.services.accounting_service import create_expense  # noqa: E402",
        "from app.services.accounting_service import create_expense",
        "业务函数 import 放在文件中部并带 noqa: E402",
    ),
    # ⑮ 那 30 笔被顺手删掉（看着像"修好了"）
    (
        "那 30 笔被顺手删掉（看着像\"修好了\"）",
        "backend/scripts/seed_demo_data.py",
        "    for _ in range(30):",
        "    for _ in range(0):",
        "那 30 笔还在造",
    ),
    # ⑯ 收尾那句话改回旧说法（看不出流水由谁写）
    (
        "收尾那句话改回旧说法（看不出流水由谁写）",
        "backend/scripts/seed_demo_data.py",
        "（现金流水由服务层自己写）",
        "（直接写库造出来的）",
        "收尾那句话说明了流水由谁写",
    ),
    # ⑰ 回填签名默认改成写库（预览成了摆设）
    (
        "回填签名默认改成写库（预览成了摆设）",
        "backend/scripts/backfill_expense_cash_flows.py",
        "def backfill_expense_cash_flows(db, *, dry_run: bool = True) -> tuple[int, int]:",
        "def backfill_expense_cash_flows(db, *, dry_run: bool = False) -> tuple[int, int]:",
        "回填签名是 backfill_expense_cash_flows",
    ),
    # ⑱ 预览分支挪到写库之后（预览也会改库）
    (
        "预览分支挪到写库之后（预览也会改库）",
        "backend/scripts/backfill_expense_cash_flows.py",
        "    if dry_run:\n        return len(missing), total - len(missing)\n    for e in missing:\n        write_expense_cash_flow(db, e)\n    db.commit()",
        "    for e in missing:\n        write_expense_cash_flow(db, e)\n    db.commit()\n    if dry_run:\n        return len(missing), total - len(missing)",
        "预览分支在写库之前",
    ),
    # ⑲ 幂等条件放宽（不再认 doc_id）
    (
        "幂等条件放宽（不再认 doc_id）",
        "backend/scripts/backfill_expense_cash_flows.py",
        "                CashFlow.doc_id.isnot(None),\n",
        "",
        "按 party_type + direction + doc_id 认",
    ),
    # ⑳ 回填自己拼一条流水（不经共用函数）
    (
        "回填自己拼一条流水（不经共用函数）",
        "backend/scripts/backfill_expense_cash_flows.py",
        "        write_expense_cash_flow(db, e)",
        "        db.add(CashFlow(party_type=\"expense\", doc_id=e.id))",
        "回填脚本自己不许拼 cash_flows",
    ),
    # ⑴ --yes 不再是唯一的写库开关
    (
        "--yes 不再是唯一的写库开关",
        "backend/scripts/backfill_expense_cash_flows.py",
        "        n, had = backfill_expense_cash_flows(db, dry_run=not args.yes)",
        "        n, had = backfill_expense_cash_flows(db, dry_run=False)",
        "命令行默认预览：--yes 才写",
    ),
    # ⑵ pytest 删掉幂等那条用例
    (
        "pytest 删掉幂等那条用例",
        "backend/tests/test_expense_cash_flow_backfill.py",
        "def test_存量回填幂等_已经有流水的一张都不碰(db_session):",
        "def _disabled_存量回填幂等(db_session):",
        "有一条「幂等」用例",
    ),
    # ⑶ 幂等只看条数、不比流水 id
    (
        "幂等只看条数、不比流水 id",
        "backend/tests/test_expense_cash_flow_backfill.py",
        "        assert sorted(f.id for f in _flows_of(db_session, eid)) == before, \\",
        "        assert len(_flows_of(db_session, eid)) >= 1, \\",
        "幂等是靠「跑第二遍比对流水 id」证明的",
    ),
    # ⑷ 预览那条用例改成写库（预览不再被钉住）
    (
        "预览那条用例改成写库（预览不再被钉住）",
        "backend/tests/test_expense_cash_flow_backfill.py",
        "        n, _had = backfill_expense_cash_flows(db_session, dry_run=True)",
        "        n, _had = backfill_expense_cash_flows(db_session, dry_run=False)",
        "既跑了 dry_run=False 也跑了 dry_run=True",
    ),
    # ⑸ 记一笔那条不再走 HTTP 入口（假造一张单）
    (
        "记一笔那条不再走 HTTP 入口（假造一张单）",
        "backend/tests/test_expense_cash_flow_backfill.py",
        "    r = client.post(\"/api/v1/expenses\", headers=h,",
        "    r = type(\"R\", (), {\"status_code\": 201, \"json\": lambda self: {\"id\": 1}})()  # 直接插库",
        "记一笔开销那条走的是真 HTTP 入口",
    ),
    # ⑹ 探针日期挪进业务窗口（会和报表用例互相污染）
    (
        "探针日期挪进业务窗口（会和报表用例互相污染）",
        "backend/tests/test_expense_cash_flow_backfill.py",
        "PROBE_DAY = date(2001, 1, 1)",
        "PROBE_DAY = date(2026, 10, 9)",
        "探针日期远离业务窗口",
    ),
    # ⑺ 口径函数不再被直接断言
    (
        "口径函数不再被直接断言",
        "backend/tests/test_expense_cash_flow_backfill.py",
        "    assert expense_biz_type(\"装卸费-探针\") == CashFlowBizType.EXPENSE_OTHER\n    assert expense_biz_type(\"fuel\") == CashFlowBizType.EXPENSE_FUEL\n    assert expense_biz_type(\" 加油 \") == CashFlowBizType.EXPENSE_FUEL\n    assert expense_biz_type(\"\") == CashFlowBizType.EXPENSE_OTHER",
        "    assert True  # 口径函数不测了",
        "口径函数被直接断言",
    ),
    # ⑻ 不再从 scripts 包 import 回填函数（走不到实现）
    (
        "不再从 scripts 包 import 回填函数（走不到实现）",
        "backend/tests/test_expense_cash_flow_backfill.py",
        "from scripts.backfill_expense_cash_flows import (",
        "from app.services.accounting_service import (  # 图省事",
        "按 pytest.ini 的 pythonpath=. 从 scripts 包 import 回填函数",
    ),
]


def read_src(rel: str) -> tuple[str, bool]:
    """读成 LF 文本 + 记住原来是不是 CRLF（写回时要一模一样）。"""
    raw = (ROOT / rel).read_bytes()
    crlf = b"\r\n" in raw
    return raw.decode("utf-8").replace("\r\n", "\n"), crlf


def write_src(rel: str, text: str, crlf: bool) -> bytes:
    out = text.replace("\n", "\r\n") if crlf else text
    data = out.encode("utf-8")
    (ROOT / rel).write_bytes(data)
    return data


def restore_src(rel: str, text: str, crlf: bool, expect: bytes) -> None:
    """写回后**重新读回逐字节比**：还原不干净就必须立刻停，绝不能让后面的注入跑在脏源码上。"""
    write_src(rel, text, crlf)
    back = (ROOT / rel).read_bytes()
    if back != expect:
        print("  [FATAL] 还原后字节不一致：{}".format(rel))
        raise SystemExit(2)


def run_check() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def fails_of(out: str) -> list[str]:
    """收集失败行。

    ⚠️ 踩过：判据当场标红用的是 `[!!]`（共享的 `_check_hints.Checker` 的记号），末尾再以
    「- 检查名」列一遍；而另一个检查脚本（`_check_ai_operation_log.py`）用的是 `[FAIL]`。
    只认 `[FAIL]` 的话，这里会把每一条注入都判成「红了但不是这条（实际红 0 条）」——
    反向验证就整体空转（2026-10-09 实测：28 条全 MISS）。三种记号都要收。
    """
    got: list[str] = []
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith(("[FAIL]", "[!!]")) or (s.startswith("- ") and len(s) > 2):
            got.append(s)
    return got


def verdict(expect: str, proc: subprocess.CompletedProcess[str]) -> tuple[bool, str]:
    fails = fails_of((proc.stdout or "") + (proc.stderr or ""))
    hit = next((ln for ln in fails if expect in ln), None)
    if proc.returncode != 0 and hit is not None:
        return True, hit
    if proc.returncode == 0:
        return False, "判据**没红**（退出码 0）—— 这条检查是空转的"
    return False, "红了但不是这条（实际红 {} 条）：{}".format(len(fails), " / ".join(fails[:4]))


def dry_run() -> int:
    """只验锚点：每条注入的原文是否在该文件里恰好出现一次（一个字节都不改）。"""
    print("\n== 锚点体检（--dry，不改任何文件） ==")
    bad = 0
    for label, rel, old, _new, expect in MUTATIONS:
        text, _crlf = read_src(rel)
        n = text.count(old)
        if n == 1:
            print("  [OK]   {:<34} {}".format(label, rel))
        else:
            bad += 1
            print("  [BAD]  {:<34} {} —— 原文出现 {} 次（期望 1 次）；期望判据：{}".format(label, rel, n, expect))
    print("\n" + "=" * 60)
    if bad:
        print("❌ {} 条锚点对不上，先修锚点再跑正式注入。".format(bad))
        return 1
    print("✅ {} 条锚点全部唯一命中。".format(len(MUTATIONS)))
    return 0


def main() -> int:
    if "--dry" in sys.argv:
        return dry_run()

    total = len(MUTATIONS) + 1  # +1 = 末尾「还原后判据重新全绿」
    bad = 0

    print("\n== 0. 前提：源码完好时判据必须全绿 ==")
    proc = run_check()
    if proc.returncode != 0:
        print("  [FATAL] 源码当前状态判据就是红的，先修好再来做反向验证：")
        for ln in fails_of((proc.stdout or "") + (proc.stderr or ""))[:10]:
            print("    " + ln)
        return 2
    last = [ln for ln in (proc.stdout or "").splitlines() if "全部" in ln and "通过" in ln]
    print("  [OK]   " + (last[-1].strip() if last else "判据退出码 0"))

    print("\n== 1. 逐条注入（每条跑完立刻还原） ==")
    touched: set[str] = set()
    for i, (label, rel, old, new, expect) in enumerate(MUTATIONS, start=1):
        text, crlf = read_src(rel)
        n = text.count(old)
        if n != 1:
            bad += 1
            print("  [SKIP] {}/{} {} —— 原文出现 {} 次（期望 1 次）：{}".format(i, len(MUTATIONS), label, n, rel))
            continue
        before = (ROOT / rel).read_bytes()
        try:
            write_src(rel, text.replace(old, new, 1), crlf)
            got = run_check()
            ok, detail = verdict(expect, got)
        finally:
            restore_src(rel, text, crlf, before)
        if (ROOT / rel).read_bytes() == before:
            touched.add(rel)
        if ok:
            print("  [OK]   {}/{} {} —— {}".format(i, len(MUTATIONS), label, detail))
        else:
            bad += 1
            print("  [MISS] {}/{} {} —— {}".format(i, len(MUTATIONS), label, detail))

    print("\n== 2. 收尾：全部还原之后判据必须重新全绿 ==")
    proc = run_check()
    if proc.returncode == 0:
        last = [ln for ln in (proc.stdout or "").splitlines() if "全部" in ln and "通过" in ln]
        print("  [OK]   " + (last[-1].strip() if last else "判据退出码 0（还原干净）"))
        print("  [OK]   {} 个被碰过的文件与运行前逐字节一致：{}".format(len(touched), "、".join(sorted(touched))))
    else:
        bad += 1
        print("  [MISS] 还原之后判据仍然是红的 —— 有文件没还原干净：")
        for ln in fails_of((proc.stdout or "") + (proc.stderr or ""))[:10]:
            print("    " + ln)

    print("\n" + "=" * 60)
    if bad:
        print("❌ {}/{} 条不成立（注入没让判据变红，或锚点对不上）。".format(bad, total))
        return 1
    print("✅ {}/{} 全部成立：{} 条注入各自让对应判据变红，还原后判据重新全绿。".format(total, total, len(MUTATIONS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())