#!/usr/bin/env python
"""红线：**开销单与现金流水必须同时存在，而且只有一份分类口径**（2026-10-09 BUG-0018 / 台账 TB-02）。

## 这条红线治的是什么

测试员 2026-10-09 翻账本时发现：开发库里 `expenses` 有 53 张（¥44560.51），可「账本 / 收支」页上
只看得见 23 张（EXPENSE_* 流水合计 ¥8720.51）—— 剩下 30 张**一分钱都不在现金流水里**。
根因不是算错，而是**少走了一步**：`backend/scripts/seed_demo_data.py:1167` 当年用
`db.add(Expense(...))` 直接造了那 30 笔，**绕过了服务层的记账**（只有
`accounting_service.create_expense` 会写 `cash_flows` OUT）。症状是"页面少了一部分钱"，
而单看任何一处代码都不报错 —— 这正是必须由机器盯着的那类缺陷。

盯住五件事：

1. **分类名 → 现金流水口径只有一张表**（`EXPENSE_BIZ_TYPES`，模块级）：
   记账与存量回填都走 `expense_biz_type()`。抄第二份的症状是"同一张开销单两条口径不同的
   流水"，报表按 `biz_type` 分组求和时对不上，而且两边都不报错。
2. **记一笔开销必定留下一条 OUT**：字段全部取自**已落库的那张开销单**（不是请求体）——
   `direction=OUT` / `party_type="expense"` / `doc_id=expense.id` / `channel="cash"`。
   `db.flush()` 必须在写流水之前（流水要用 `expense.id`）。
3. **播种脚本不许再绕过服务层**：`seed_demo_data.py` 里直接构造 `Expense(` 归零，
   必须 `create_expense(db, ExpenseCreate(...), dispatcher.id)`。
4. **存量回填脚本必须幂等**：已经有流水的开销单一条都不碰；默认**预览**（`dry_run=True`），
   要写库得显式 `--yes`。一次性脚本最坏的失败是"跑第二遍把每笔钱翻倍"。
5. **接线还在**：脚本注册进工程地图、pytest 钉住"记一笔就有流水"与"回填幂等"、
   变更单/登记簿/工作声明按九节写全。

为什么不能只靠"我这次修好了"：这五件事里**没有一件**会在编译、类型检查或功能测试里报错 ——
第 1 条要看着两张表是否走散，第 3 条要看着"有没有人又图省事直接 db.add"，
第 4 条要看着"预览默认值有没有被改成写库"。所以要有注入式反向验证陪着（见文件末尾接线一节）。

R4-BOUNDARY-JUSTIFICATION: 这条判据不下沉到任何一层边界：它查的是**同一次写入的两个落点
（开销单 + 现金流水）有没有一起发生、以及分类口径是不是同一处** —— 这是 service 层
自己的不变式，领域类型/权限模型/后端契约里都没有它的位置（`ExpenseCreate` 不携带现金流水，
权限模型不知道记账，报表契约只看到已经写好的流水）。反向说：把"记账必须同时写流水"
塞进任何一层边界都无处安放 —— 那一层根本不参与记账。

用法：python _tools/qa/_check_expense_cash_flow.py  （--list 打一份人读清单）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_hints import Checker, read, strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
APP = BACKEND / "app"
SCRIPTS = BACKEND / "scripts"
SVC = APP / "services/accounting_service.py"
SEED = SCRIPTS / "seed_demo_data.py"
BACKFILL = SCRIPTS / "backfill_expense_cash_flows.py"
TEST = BACKEND / "tests/test_expense_cash_flow_backfill.py"
MAP_DETAILS = ROOT / "docs/PROJECT_MAP/03_BACKEND_DETAILS.md"
MAP_ARCH = ROOT / "docs/PROJECT_MAP/01_ARCHITECTURE.md"
LEDGER = ROOT / "docs/TEST_BUG_LEDGER.md"
DOC = ROOT / "docs/changes/BUG-0018.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_expense_cash_flow.py"

NL = chr(10)

#: 扫到的后端 .py 下限（目录被改名 / 扫描被写坏时，"一处都没有"与"一处都没扫到"是同一个输出）
MIN_PY = 120
MIN_SVC_CHARS = 20000
MIN_SEED_CHARS = 30000

#: 分类名 → 口径（**只许有这一份**，与 accounting_service.EXPENSE_BIZ_TYPES 逐条对齐）
CATEGORIES = [
    ("加油", "fuel", "EXPENSE_FUEL"),
    ("维修", "repair", "EXPENSE_REPAIR"),
    ("过路", "toll", "EXPENSE_TOLL"),
    ("停车", "parking", "EXPENSE_PARKING"),
    ("罚款", "fine", "EXPENSE_FINE"),
    ("保险", "insurance", "EXPENSE_INSURANCE"),
    ("货损", "loss", "EXPENSE_LOSS"),
    ("其他", "other", "EXPENSE_OTHER"),
]


def scan_py() -> dict[str, str]:
    """backend/app 与 backend/scripts 下的每一个 .py（相对 backend/ 的 posix 路径 → 源码）。"""
    out: dict[str, str] = {}
    for root in (APP, SCRIPTS):
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            out[p.relative_to(BACKEND).as_posix()] = read(p)
    return out


def body_of(src: str, header: str, stop: str = "\ndef ") -> str:
    """截出某个顶层函数/常量之后的一段（header 找不到就返回空串，让断言如实报红）。"""
    i = src.find(header)
    if i < 0:
        return ""
    j = src.find(stop, i + len(header))
    return src[i:] if j < 0 else src[i:j]


def main() -> int:
    if refuse_if_injecting("开销单与现金流水判据"):
        return 1
    c = Checker()

    # ── 0. 反空转 ────────────────────────────────────────────────────────
    c.section("0. 反空转（文件搬走 / 目录改名 / 扫描写坏时先喊）")
    need = [SVC, SEED, BACKFILL, TEST, MAP_DETAILS, MAP_ARCH, LEDGER, DOC, REGISTRY, CLAIM]
    missing = [p.name for p in need if not p.exists()]
    c.ok("十个关键文件都在（记账 + 播种 + 回填 + pytest + 两份工程地图 + 台账 + 变更单 + 登记簿 + 声明块）",
         not missing, "缺：" + str(missing))
    if missing:
        print(NL + "❌ 关键文件都不在，后面的判据没有意义")
        return 1
    files = scan_py()
    c.ok("扫到 backend 下 " + str(len(files)) + " 个 .py（下限 " + str(MIN_PY) + "）",
         len(files) >= MIN_PY, "目录改名了？那样「一处都没有」和「一处都没扫到」是同一个输出")

    svc_raw = read(SVC)
    svc = strip_comments(svc_raw)
    seed = strip_comments(read(SEED))
    backfill = strip_comments(read(BACKFILL))
    test = read(TEST)
    c.ok("accounting_service.py 读到了内容（下限 " + str(MIN_SVC_CHARS) + " 字符）",
         len(svc) >= MIN_SVC_CHARS, "实际 " + str(len(svc)))
    c.ok("seed_demo_data.py 读到了内容（下限 " + str(MIN_SEED_CHARS) + " 字符）",
         len(seed) >= MIN_SEED_CHARS, "实际 " + str(len(seed)))

    # ── 1. 分类 → 口径只有一份 ───────────────────────────────────────────
    c.section("1. 分类名 → 现金流水口径只有一份（记账与回填共用）")
    defs = sum(len(re.findall(r"^EXPENSE_BIZ_TYPES\s*[:=]", s, re.M)) for s in files.values())
    c.ok("EXPENSE_BIZ_TYPES 在整个 backend 里只定义一处", defs == 1, "实际 " + str(defs) + " 处")
    wrong = [cn for cn, en, enum in CATEGORIES
             if not re.search(r'"' + cn + r'"\s*:\s*CashFlowBizType\.' + enum, svc)]
    c.ok("表里 " + str(len(CATEGORIES)) + " 个中文分类名都指向对的口径",
         not wrong, "对不上的：" + str(wrong))
    wrong_en = [en for cn, en, enum in CATEGORIES
                if not re.search(r'"' + en + r'"\s*:\s*CashFlowBizType\.' + enum, svc)]
    c.ok("表里 " + str(len(CATEGORIES)) + " 个老英文键也都在（迁移前后的库都认）",
         not wrong_en, "对不上的：" + str(wrong_en))
    # 全仓不许有第二处"分类名 → 口径"的映射（中文名与 EXPENSE_* 出现在同一行）
    carriers = sorted(rel for rel, s in files.items()
                      if re.search(r'"(加油|维修|过路|停车|罚款|保险|货损)"[^"' + NL + r']{0,40}EXPENSE_',
                                   strip_comments(s)))
    c.ok("全后端只有 accounting_service.py 一处写着「哪个分类算哪个口径」",
         carriers == ["app/services/accounting_service.py"], "实际：" + str(carriers))
    c.ok("expense_biz_type() 只定义一处",
         sum(len(re.findall(r"^def expense_biz_type\(", s, re.M)) for s in files.values()) == 1)
    fn = body_of(svc, "def expense_biz_type(")
    c.ok("认不出的分类落 OTHER（用户新加一个分类不该让这笔开销存不进去）",
         "EXPENSE_BIZ_TYPES.get(" in fn and "CashFlowBizType.EXPENSE_OTHER" in fn)
    c.ok("查表前先 strip（老代码查的是原始请求体，带空格的分类会落错口径）",
         ".strip()" in fn, "函数体：" + fn[:200].replace(NL, " / "))
    c.ok("回填脚本与播种脚本都不许自己写这份映射（CashFlowBizType 一个字都不出现）",
         "CashFlowBizType" not in backfill and "CashFlowBizType" not in seed)

    # ── 2. 记一笔开销必定写一条流水 ──────────────────────────────────────
    c.section("2. 记一笔开销必定留下一条 OUT 流水（字段取自落库的那张单）")
    c.ok("write_expense_cash_flow() 只定义一处",
         sum(len(re.findall(r"^def write_expense_cash_flow\(", s, re.M)) for s in files.values()) == 1)
    wf = body_of(svc, "def write_expense_cash_flow(")
    for label, cond in [
        ("direction=CashFlowDirection.OUT", "direction=CashFlowDirection.OUT" in wf),
        ('party_type="expense"', 'party_type="expense"' in wf),
        ("party_id=expense.id", "party_id=expense.id" in wf),
        ("doc_id=expense.id", "doc_id=expense.id" in wf),
        ("amount=expense.amount", "amount=expense.amount" in wf),
        ("flow_date=expense.exp_date", "flow_date=expense.exp_date" in wf),
        ('channel="cash"', 'channel="cash"' in wf),
        ("biz_type=expense_biz_type(expense.category)", "biz_type=expense_biz_type(expense.category)" in wf),
        ("party_name=str(expense.category)", "party_name=str(expense.category)" in wf),
        ("db.add(flow)", "db.add(flow)" in wf),
    ]:
        c.ok("流水字段：" + label, cond)
    c.ok("写流水用的是**落库的那张单**（不是请求体）：字段全部从 expense. 上取",
         wf.count("body.") == 0, "函数体里出现了 " + str(wf.count("body.")) + " 处 body.")
    ce = body_of(svc, "def create_expense(")
    c.ok("create_expense 末尾调 write_expense_cash_flow（记账不许只写单子）",
         "write_expense_cash_flow(db, e, operator_id=operator_id)" in ce)
    c.ok("create_expense 自己不再拼 cash_flows（CashFlow( 归零）", "CashFlow(" not in ce)
    c.ok("共用函数里只拼一条流水（开销这一路 CashFlow( 恰好 1 处，就在 write_expense_cash_flow 里）",
         wf.count("CashFlow(") == 1,
         "共用函数 " + str(wf.count("CashFlow(")) + " 处；文件里另有 " +
         str(svc.count("CashFlow(") - wf.count("CashFlow(")) + " 处属于别的记账路径（收款/结算等），不归本单管")
    c.ok("db.flush() 在写流水之前（流水要用 expense.id）",
         0 <= ce.find("db.flush()") < ce.find("write_expense_cash_flow("))
    c.ok("认不出的分类不抛异常：create_expense 只对**空分类**抛错",
         'raise ValueError("请选择开销分类")' in ce and ce.count("raise ValueError(") == 1)

    # ── 3. 播种脚本走服务层 ──────────────────────────────────────────────
    c.section("3. 播种脚本不许再绕过记账（直接 db.add 一张开销单归零）")
    c.ok("seed_demo_data.py 里不再直接构造开销单（Expense( 归零）", "Expense(" not in seed)
    c.ok("也不再 db.add(Expense", "db.add(Expense" not in seed)
    c.ok("改走服务层：create_expense(db, ExpenseCreate(...))",
         "create_expense(db, ExpenseCreate(" in seed)
    c.ok("业务函数 import 放在文件中部并带 noqa: E402（脚本既有体例）",
         "from app.services.accounting_service import create_expense  # noqa: E402" in seed
         and "from app.schemas.accounting_v2 import ExpenseCreate  # noqa: E402" in seed)
    c.ok("那 30 笔还在造（这段没被顺手删掉）", "for _ in range(30):" in seed)
    c.ok("收尾那句话说明了流水由谁写", "现金流水由服务层自己写" in seed)
    c.ok("车相关的开销仍然挂车（create_expense 拿到的 vehicle_id 不是写死的 None）",
         "vehicle_id=car.id if car else None" in seed)

    # ── 4. 存量回填脚本：幂等 + 默认预览 ─────────────────────────────────
    c.section("4. 存量回填：幂等，而且默认只预览（--yes 才写库）")
    c.ok("expenses_without_cash_flow() 按 party_type + direction + doc_id 认「已经有流水」",
         'party_type == "expense"' in backfill
         and "CashFlow.direction == CashFlowDirection.OUT" in backfill
         and "CashFlow.doc_id.isnot(None)" in backfill)
    c.ok("回填签名是 backfill_expense_cash_flows(db, *, dry_run: bool = True)",
         "def backfill_expense_cash_flows(db, *, dry_run: bool = True)" in backfill)
    c.ok("预览分支在写库之前（dry_run 先 return）",
         0 <= backfill.find("if dry_run:") < backfill.find("for e in missing:"))
    c.ok("真写库是一条一条走服务层那个共用函数（write_expense_cash_flow(db, e)）",
         "write_expense_cash_flow(db, e)" in backfill)
    c.ok("回填脚本自己不许拼 cash_flows（CashFlow( 归零）", "CashFlow(" not in backfill)
    c.ok("写库之后 commit", backfill.find("db.commit()") > backfill.find("for e in missing:"))
    c.ok("命令行默认预览：--yes 才写（dry_run=not args.yes）",
         'ap.add_argument("--yes", action="store_true"' in backfill
         and "dry_run=not args.yes" in backfill)
    c.ok("docstring 写清了它是「一次性」脚本与用法",
         "一次性" in read(BACKFILL) and "python -m scripts.backfill_expense_cash_flows" in read(BACKFILL))

    # ── 5. pytest 钉住这两件事 ──────────────────────────────────────────
    c.section("5. pytest 钉住「记一笔就有流水」与「回填幂等」")
    n_tests = len(re.findall(r"^def test_", test, re.M))
    c.ok("用例数 " + str(n_tests) + " >= 4", n_tests >= 4)
    c.ok("有一条「幂等」用例", "def test_存量回填幂等" in test)
    # ⚠️ 2026-10-09 反向验证打脸后改强：原来这两条只查「有没有这两个子串」，于是
    #    ① 把幂等那行断言换成「只看条数」，文件里预览用例的 `== before` 还在 ⇒ 判据照样绿；
    #    ② 预览用例的 `dry_run=True` 改成 False，而**用例 docstring 里那句 `dry_run=True`** 还在 ⇒ 照样绿。
    #    现在钉的是**那条断言本身**与**那次调用的实参**（正则要求 `dry_run=True)` 紧跟在调用后面）。
    c.ok("幂等是靠「跑第二遍比对流水 id」证明的（不是只看条数）",
         "assert sorted(f.id for f in _flows_of(db_session, eid)) == before," in test)
    prev = body_of(test, "def test_回填预览不写库(")
    c.ok("既跑了 dry_run=False 也跑了 dry_run=True（预览不写库有独立用例）",
         re.search(r"backfill_expense_cash_flows\(db_session, dry_run=True\)", prev) is not None
         and re.search(r"backfill_expense_cash_flows\(db_session, dry_run=False\)", test) is not None)
    c.ok("记一笔开销那条走的是真 HTTP 入口（client.post）", 'client.post("/api/v1/expenses"' in test)
    c.ok("探针日期远离业务窗口（PROBE_DAY = date(2001, 1, 1)）",
         "PROBE_DAY = date(2001, 1, 1)" in test)
    c.ok("口径函数被直接断言（认不出落 OTHER / 带空格的也认得）",
         "expense_biz_type(" in test and "EXPENSE_OTHER" in test)
    c.ok("按 pytest.ini 的 pythonpath=. 从 scripts 包 import 回填函数",
         "from scripts.backfill_expense_cash_flows import (" in test)

    # ── 6. 接线与文书 ───────────────────────────────────────────────────
    c.section("6. 接线：工程地图 / 反向验证据本 / 变更单 / 登记簿 / 声明块 / 台账")
    c.ok("工程地图的脚本表里登记了回填脚本（03_BACKEND_DETAILS.md）",
         "backfill_expense_cash_flows.py" in read(MAP_DETAILS))
    c.ok("目录注释里也认它（01_ARCHITECTURE.md）", "backfill_expense_cash_flows" in read(MAP_ARCH))
    c.ok("反向验证脚本在（这条红线必须配注入式验证）", REVERSE.exists())
    doc = read(DOC)
    c.ok("变更单 BUG-0018.md 九节齐全",
         all(h in doc for h in ("## ① 六问", "## ② Must Change", "## ③ Boundary", "## ④ Behavior Contract",
                                "## ⑤ Data Contract", "## ⑥ CHG 专章", "## ⑦ 测试", "## ⑧ 证据", "## ⑨ 关闭")))
    c.ok("变更单写清了根因（播种脚本绕过服务层）",
         "seed_demo_data.py:1167" in doc or "绕过" in doc)
    c.ok("登记簿里有这一单", "BUG-0018" in read(REGISTRY))
    c.ok("工作声明里有这一单", "BUG-0018" in read(CLAIM))
    ledger = read(LEDGER)
    row = [ln for ln in ledger.split(NL) if ln.startswith("| **TB-02**") or ln.startswith("| TB-02")]
    c.ok("台账 TB-02 那一行还在，且不再写「已复现」",
         bool(row) and all("已复现" not in ln for ln in row), "那一行：" + str(row[:1]))
    block = ledger[ledger.find("TB-02"):]
    c.ok("台账 TB-02 的详情块写得下根因（播种脚本绕过服务层这条链）",
         "seed_demo_data.py:1167" in ledger or "绕过服务层" in ledger)
    c.ok("详情块里点了那 30 张的指纹（created_at 全一样）",
         "2026-09-20 09:58:27.189947" in block or "created_at" in block)

    print()
    if c.fails:
        print("❌ " + str(len(c.fails)) + " 项不成立（通过 " + str(c.n_ok) + " 项）：")
        for label, detail in c.fails:
            print("   - " + label + (("  → " + detail) if detail else ""))
        return 1
    print("✅ 全部 " + str(c.n_ok) + " 项通过：开销单与现金流水 —— 分类口径只有一张表、"
          "记一笔开销必定留下一条 OUT、播种脚本走服务层、存量回填幂等且默认只预览。")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("开销单 ↔ 现金流水（BUG-0018 / 台账 TB-02）判据覆盖：")
        print("1. 分类 → 口径只有一份：EXPENSE_BIZ_TYPES 全后端只定义一处、8 个中文名与 8 个老英文键")
        print("   逐条对齐、认不出落 OTHER、查表前 strip、回填与播种脚本里 CashFlowBizType 一个字不出现")
        print("2. 记一笔开销必写流水：write_expense_cash_flow 一处、10 个字段逐个钉（OUT/expense/doc_id/")
        print("   cash/expense_biz_type...）、字段全取自落库那张单、db.flush() 在写流水之前")
        print("3. 播种脚本：Expense( 与 db.add(Expense 归零、改走 create_expense + ExpenseCreate、")
        print("   中部 import 带 noqa: E402、那 30 笔还在造")
        print("4. 回填脚本：按 doc_id 认「已有流水」、dry_run 默认 True 先 return、逐条走共用函数、")
        print("   commit、--yes 才写库、docstring 写清一次性与用法")
        print("5. pytest：>= 4 个用例、幂等靠「跑第二遍比 id」证明、预览有独立用例、真走 HTTP 入口、")
        print("   探针日期远离业务窗口")
        print("6. 接线：工程地图两处登记、反向验证脚本在、变更单九节、登记簿、声明块、台账 TB-02 不再写已复现")
        sys.exit(0)
    sys.exit(main())
