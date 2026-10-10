#!/usr/bin/env python3
"""_tools/finance/_check_expense_soft_delete.py —— 开销的撤销必须是软删、能原样恢复、所有取数处都不再算它（BUG-0034 / 台账 TA-16）。

### 为什么要有它
台账 TA-16 的原文是「开销（expenses）全系统没有任何删除或修改入口：**记错一笔永久留在账上**」
（第 4 轮方向 A 普查实测：DELETE /api/v1/expenses/54 → 404、列表页「删/撤销」零命中、
PRAGMA table_info(expenses) 连软删列都没有）。用户 2026-09-20 定的硬规矩是
「**所有删除一律软删 ＋ 必须有恢复路径 ＋ 界面要有手边的撤销入口**」。

这一单有三处最容易做成"看起来对了"：
1. **撤销做成了物理删** —— 界面上少了一行，看着像成功了，但账的历史没了；
2. **只改了列表那一处过滤** —— 开销从「开销管理」里消失了，利润表/车辆成本表/报表导出
   却还在算它（"这笔钱明明撤销了、合计里还在"），两边都不报错；
3. **恢复是"按出参重建一条"** —— 金额/分类/关联的司机/车辆/订单只要有一个字段漂了，
   重算出来的历史和原来那份就不是一份东西。

### 判据（六组；**凡是"要检查哪些文件/哪些函数"的清单，一律由脚本自己算**）
0. 反空转：关键文件在、扫到的函数数在下限之上（扫描规则坏了要先喊，不许安静地全绿）；
1. 软删列与幂等 DDL：模型挂 SoftDeleteMixin、bootstrap 里 ADD COLUMN + 索引 + **回填 0**、
   重复执行不报错、DDL 在 with engine.begin() 作用域内；
2. 两个端点：DELETE（204，软删，锁行）/ POST restore（200），撤销与恢复**除了两个标记列
   之外一个字段都不许赋值**（逐字段原样靠这条钉着），拒绝重复撤销/重复恢复都带点名文案；
3. 取数处都过滤：**扫出所有「select(...) 里带 Expense」的函数**，每一个都必须带 is_deleted
   （清单是算出来的，不是手写的 —— 漏一处的后果就是某个合计里还在算这笔钱）；
4. 出参与审计：ExpenseOut 两个新字段（默认值保证老后端出参不会把正常开销画成已撤销）、
   两个审计码、两条 write_log、App 侧 actionLabel 的中文名；
5. 安卓手边入口：DTO 两个字段、两个端点、Repo 三个方法、开销页上的「撤销 / 恢复 /
   显示已撤销」三件套 + 既有的危险确认控件（⛔ 恢复不许只藏在 AI 撤回卡里）；
6. 单测与文书：三态 + 「删前 − 这一笔 = 删后」的等式、覆盖率理由两条、台账与变更单接线。

用法：python _tools/finance/_check_expense_soft_delete.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools" / "qa"))
from _check_hints import Checker, read  # noqa: E402

ANDROID = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
API = ROOT / "backend/app/api/v1/expenses.py"
CATS = ROOT / "backend/app/api/v1/expense_categories.py"
MODEL = ROOT / "backend/app/models/expense.py"
BOOT = ROOT / "backend/app/core/schema_bootstrap.py"
ENUMS = ROOT / "backend/app/models/enums.py"
SCHEMA = ROOT / "backend/app/schemas/accounting_v2.py"
PROFIT = ROOT / "backend/app/services/reports/profit_query.py"
VEHICLE = ROOT / "backend/app/services/reports/vehicle_cost_query.py"
REPORTS = ROOT / "backend/app/api/v1/reports.py"
CASHAPI = ROOT / "backend/app/api/v1/cash_flows.py"
BACKFILL = ROOT / "backend/scripts/backfill_expense_cash_flows.py"
TEST = ROOT / "backend/tests/test_expense_soft_delete.py"
COVERAGE = ROOT / "_tools/ai/_write_coverage.py"
LEDGER = ROOT / "docs/TEST_BUG_LEDGER.md"
CHANGE = ROOT / "docs/changes/BUG-0034.md"
CHANGE_IDX = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
DTO = ANDROID / "data/remote/dto/Dtos.kt"
APIS = ANDROID / "data/remote/api/Apis.kt"
REPO = ANDROID / "data/repo/AppRepository.kt"
SCREEN = ANDROID / "ui/dispatcher/ExpensesScreen.kt"
REPORT_CENTER = ANDROID / "ui/dispatcher/ReportCenter.kt"

#: 「凡是从 expenses 取数」的四份业务取数处（列表本体在 API 里，单独断言）。
READ_PLACES = (
    ("分类名册（在用笔数 / 名册外兜底 / 删分类守卫）", CATS),
    ("利润表的期间费用", PROFIT),
    ("车辆成本表的三块开销桶", VEHICLE),
    ("报表导出的「开销分类」块", REPORTS),
)
#: 撤销/恢复两个端点里，除了这两个标记列，**一个字段都不许被赋值**。
FLAG_FIELDS = {"is_deleted", "deleted_at"}
#: 三个关联字段 + 金额 —— 恢复必须原样放回的那几格（出参与单测都按它核对）。
KEPT_FIELDS = ("exp_date", "category", "amount", "driver_id", "vehicle_id", "order_id", "note")
#: 单测的行为契约（名字写死在这里：删一支就等于把那条行为契约删了）。
TEST_NAMES = (
    "test_三态_活着_撤销_恢复",
    "test_撤销不是物理删_行还在且字段一个都没动",
    "test_恢复把每个字段原样放回来",
    "test_撤销之后每一处合计正好少这一笔",
    "test_撤销把它写下的那条资金流水一起打标记",
    "test_两个审计码都真的写进了操作日志",
)
MIN_FILES = 120
MIN_SITES = 8


def py_code(src: str) -> str:
    """剥掉井号注释与三引号文档串（**保留单行字符串字面量**）。

    为什么必须剥：判据里多条是「不许再出现某个写法」，而本次改动的 docstring 里正写着
    旧写法的名字（"expenses 表没有软删列"、db.delete(）。不剥的话，"旧写法不许回来"
    会被自己那段说明误判成红。
    为什么保留单行字符串：CashFlow.party_type == "expense" 这条判据**就长在字符串里**。
    """
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch == "#":
            j = src.find("\n", i)
            if j < 0:
                break
            i = j
            continue
        if src.startswith('"""', i) or src.startswith("'''", i):
            q = src[i:i + 3]
            j = src.find(q, i + 3)
            i = n if j < 0 else j + 3
            continue
        if ch in ('"', "'"):
            q = ch
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == q:
                    break
                j += 1
            out.append(src[i:j + 1])
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def calls_with(seg: str, head: str, token: str) -> list[str]:
    """段里所有 head(...) 调用中，括号内出现过 token 的那些（按括号配平切）。"""
    hits: list[str] = []
    for m in re.finditer(re.escape(head) + r"\s*\(", seg):
        i = m.end() - 1
        depth = 0
        j = i
        while j < len(seg):
            if seg[j] == "(":
                depth += 1
            elif seg[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        call = seg[i:j + 1]
        if re.search(token, call):
            hits.append(call)
    return hits


def read_sites() -> list[tuple[str, str, bool]]:
    """**算出**「从 expenses 取数」的函数清单：(相对路径, 函数名, 有没有过滤已撤销)。

    口径：函数体（剥注释与文档串）里出现 select(...) 且那个 select 的括号内提到 Expense。
    这是"从这张表读"的机器判据，不依赖任何人手写的清单。
    """
    rows: list[tuple[str, str, bool]] = []
    files = sorted(list((ROOT / "backend" / "app").rglob("*.py"))
                   + list((ROOT / "backend" / "scripts").rglob("*.py")))
    for f in files:
        src = f.read_text(encoding="utf-8", errors="replace")
        if "Expense" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        rel = f.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = py_code(ast.get_source_segment(src, node) or "")
            if calls_with(seg, "select", r"\bExpense\b"):
                rows.append((rel, node.name, "is_deleted" in seg))
    return rows


def kt_live(src: str) -> str:
    """去掉 Kotlin 的 `//` 行注释 —— **注释掉一个注解不算「这个入口还在」**。

    反验⑫实测出来的假阳面：把 `@DELETE("expenses/{expenseId}")` 整行注释掉之后，
    纯文本包含判定照样绿（那串字还在文件里），于是「客户端悄悄把撤销入口收起来」
    这件事判据抓不住。Kotlin 侧这几条断言一律走这里。
    """
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))

def block(src: str, marker: str, span: int = 4000) -> str:
    """从 marker 起切一段（到下一个顶层 class / @router 为止）—— 断言不要漫游整个文件。"""
    i = src.find(marker)
    if i < 0:
        return ""
    seg = src[i:i + span]
    cuts = [x for x in (seg.find("\nclass ", 1), seg.find("\n@router", 1), seg.find("\ndef ", 1)) if x > 0]
    return seg[:min(cuts)] if cuts else seg


def fn_sources(path: Path) -> dict[str, str]:
    src = read(path)
    out: dict[str, str] = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = py_code(ast.get_source_segment(src, node) or "")
    return out


def main() -> int:
    c = Checker()

    # ── 0. 反空转 ──────────────────────────────────────────────────────────
    c.section("0. 反空转（扫描规则坏掉时必须先喊）")
    need = [("api/v1/expenses.py", API), ("models/expense.py", MODEL),
            ("core/schema_bootstrap.py", BOOT), ("models/enums.py", ENUMS),
            ("schemas/accounting_v2.py", SCHEMA), ("tests/test_expense_soft_delete.py", TEST),
            ("scripts/backfill_expense_cash_flows.py", BACKFILL),
            ("ui/dispatcher/ExpensesScreen.kt", SCREEN), ("data/remote/dto/Dtos.kt", DTO),
            ("data/remote/api/Apis.kt", APIS), ("data/repo/AppRepository.kt", REPO)]
    gone = [n for n, p in need if not p.exists()]
    c.ok(f"{len(need)} 份关键文件都在", not gone, "不在的：" + "、".join(gone))
    n_py = len(list((ROOT / "backend" / "app").rglob("*.py"))) + len(list((ROOT / "backend" / "scripts").rglob("*.py")))
    c.ok(f"backend/app + backend/scripts 下扫到 {n_py} 个 .py（下限 {MIN_FILES}）",
         n_py >= MIN_FILES, "路径是不是被搬走了？扫描一空，第 3 组会**空过**")
    sites = read_sites()
    c.ok(f"算出 {len(sites)} 个「从 expenses 取数」的函数（下限 {MIN_SITES}）", len(sites) >= MIN_SITES,
         "判据自己的口径：select(...) 的括号里出现 Expense —— 中括号/join 写法变了就得改这里")

    # ── 1. 软删列与幂等 DDL ────────────────────────────────────────────────
    c.section("1. expenses 挂软删（列 + 幂等自愈 DDL）")
    model = read(MODEL)
    c.ok("Expense 继承了 SoftDeleteMixin",
         bool(re.search(r"class\s+Expense\s*\([^)]*SoftDeleteMixin", model)),
         "没有它就没有 is_deleted/deleted_at 两列，DBAPI 会直接报 no such column")
    boot_all = read(BOOT)
    boot = block(boot_all, 'if "expenses" in tables:')
    c.ok("bootstrap 里有 expenses 的幂等自愈段", bool(boot),
         "加列的**唯一**落点是 backend/app/core/schema_bootstrap.py（核心区）")
    for col, ddl in (("is_deleted", "BOOLEAN NOT NULL DEFAULT 0"), ("deleted_at", "DATETIME")):
        c.ok(f"补列 {col} {ddl}",
             f'("{col}", "{ddl}")' in boot,
             "照 shipper_receipts / cash_flows 那两段的写法")
    c.ok("建了 ix_expenses_is_deleted 索引", "CREATE INDEX ix_expenses_is_deleted" in boot,
         "默认查询每次都带 is_deleted = 0，没索引就是全表扫")
    c.ok("回填写成 SET is_deleted = 0（不是留 NULL）",
         "UPDATE expenses SET is_deleted = 0 WHERE is_deleted IS NULL" in boot,
         "⛔ is_deleted IS NULL 在 WHERE is_deleted = 0 下**不成立**，历史开销会整体从账上消失")
    c.ok("重复执行不报错（duplicate / already exists 被忽略）",
         'if "duplicate" in msg or "already exists" in msg:' in boot and "except DBAPIError" in boot,
         "自愈段每次启动都跑一遍，第二次必须安静地跳过")
    c.ok("DDL 在 with engine.begin() 作用域内",
         boot.find("with engine.begin() as conn:") > 0
         and boot.find("with engine.begin() as conn:") < boot.find("conn.execute("),
         "2026-09-04 的教训：在作用域外用 conn 会 ResourceClosedError，启动直接崩")

    # ── 2. 两个端点：软删、能恢复、逐字段原样 ──────────────────────────────
    c.section("2. DELETE /expenses/{id} 与 POST /expenses/{id}/restore")
    api = read(API)
    api_code = py_code(api)
    c.ok('有 @router.delete("/{expense_id}", status_code=204)',
         '@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)' in api_code,
         "台账实测 DELETE /api/v1/expenses/54 → 404，就是缺这一条")
    c.ok("有 @router.post(\"/{expense_id}/restore\", response_model=ExpenseOut)",
         '@router.post("/{expense_id}/restore", response_model=ExpenseOut)' in api_code,
         "恢复要回一张完整的开销单，客户端拿它刷新那一行")
    c.ok("两个端点都只要派单员（DispatcherUser）",
         api_code.count("current: DispatcherUser") >= 3,
         "开销是派单员在记；货主/司机没有这两条路（单测里各断言一次 401/403）")
    c.ok("这个文件里没有 db.delete( （撤销不是物理删）",
         "db.delete(" not in api_code,
         "物理删会把历史从账上抹掉；软删是用户 2026-09-20 定的硬规矩")
    c.ok("撤销/恢复都先按主键锁行（with_for_update）",
         api_code.count(".with_for_update()") == 2,
         "同一个请求进来两次（用户连点）时，第二遍要看到第一遍的结果")
    c.ok("撤销把开销单打标记（is_deleted=True + deleted_at=now）",
         "e.is_deleted = True" in api_code and "e.deleted_at = now" in api_code, "")
    c.ok("撤销把**它写下的那条流水**一起打标记",
         "select(CashFlow)" in api_code
         and 'CashFlow.party_type == "expense"' in api_code
         and "CashFlow.party_id == expense_id" in api_code
         and "f.is_deleted = True" in api_code,
         "收支页的流出、资金流水明细都是按 cash_flows 出的数；只标记开销单不改流水，"
         "钱就从两个口径里各说各话")
    c.ok("认流水用的是 party_type + party_id（不是按金额+日期猜）",
         'party_type == "expense"' in api_code and "party_id == expense_id" in api_code,
         "同一天同金额的两笔油费会被配错 —— 那比不撤更糟")
    c.ok("重复撤销 → 400 且点名（已经撤销过）", "已经撤销过了" in api_code, "")
    c.ok("没撤过就恢复 → 400 且点名（没有被撤销）", "没有被撤销" in api_code, "")
    c.ok("恢复把两处标记都摘掉（开销单 + 流水）",
         "e.is_deleted = False" in api_code and "e.deleted_at = None" in api_code
         and "f.is_deleted = False" in api_code and "f.deleted_at = None" in api_code, "")
    fns = fn_sources(API)
    for name, allowed in (("cancel_expense", FLAG_FIELDS), ("restore_expense", FLAG_FIELDS)):
        body = fns.get(name, "")
        touched = set(re.findall(r"\be\.(\w+)\s*=", body))
        extra = sorted(touched - allowed)
        c.ok(f"{name} 除了两个标记列之外不给任何字段赋值（逐字段原样）", not extra,
             "被赋值的其它字段：" + "、".join(extra) + " —— 恢复必须靠摘标记，"
             "不许按出参重建一条（重建一次就可能漂一个字段）")
    c.ok("撤销/恢复两条路都不调用金额算法（accounting_service 不出现）",
         "accounting_service" not in fns.get("cancel_expense", "")
         and "accounting_service" not in fns.get("restore_expense", ""),
         "核心区 services/accounting_service.py 一个字节都没动，判据 #2 的等式是天生的")
    c.ok("这个文件只有四条路由（没有被写两遍的端点）",
         len(re.findall(r"@router\.(get|post|delete)\(", api_code)) == 4,
         "orders.py 的同路径双定义（生效的是上面那条、openapi 显示的是下面那条）是本仓库的旧坑")

    # ── 3. 取数处都过滤（清单算出来的）────────────────────────────────────
    c.section("3. 凡是从 expenses 取数的地方都排除已撤销")
    bad = [(rel, fn) for rel, fn, ok in sites if not ok]
    c.ok(f"算出来的 {len(sites)} 个取数函数都带 is_deleted 过滤", not bad,
         "\n".join(f"         {rel}:{fn} 没有过滤 —— 这笔钱撤销了、这个口径里还在算" for rel, fn in bad))
    c.ok("列表本体是「二选一档」（deleted_only 直接进 where，不是「含已撤销」）",
         "stmt.where(Expense.is_deleted.is_(deleted_only))" in api_code,
         "两档混在一起，顶上那颗合计就说不清算的是花了多少还是撤销了多少")
    for label, path in READ_PLACES:
        code = py_code(read(path))
        c.ok(f"{label} 过滤了已撤销（Expense.is_deleted.is_(False)）",
             "Expense.is_deleted.is_(False)" in code,
             "这一处漏了的后果：那个合计里还在算这笔钱，而且两边都不报错")
    c.ok("利润表里那句「expenses 表没有软删列」的旧注释已经不在",
         "没有软删列" not in read(PROFIT),
         "前提不成立了：那句话留着，下一个人会照着它把过滤删掉")
    c.ok("回填脚本不给已撤销的开销补流水",
         "not e.is_deleted" in py_code(read(BACKFILL)),
         "否则收支页会凭空多出一笔已撤销的支出（回填脚本是运维会真跑的那种）")
    c.ok("收支页那一侧的口径本来就过滤已撤销流水（_scoped_stmt）",
         "CashFlow.is_deleted.is_(False)" in py_code(read(CASHAPI)),
         "撤销要把钱从「收支」里拿掉，靠的就是这一条 + 流水上的标记")

    # ── 4. 出参与审计 ──────────────────────────────────────────────────────
    c.section("4. 出参、审计码与 App 侧中文名")
    out_block = block(read(SCHEMA), "class ExpenseOut")
    c.ok("ExpenseOut 带 is_deleted（默认 False）", "is_deleted: bool = False" in out_block,
         "默认 False：老后端出参没有这个键时，正常开销不许被画成「已撤销」")
    c.ok("ExpenseOut 带 deleted_at（默认 None）", "deleted_at: datetime | None = None" in out_block, "")
    enums = read(ENUMS)
    for code_name in ("EXPENSE_DELETE", "EXPENSE_RESTORE"):
        c.ok(f"OperationAction 里有 {code_name}",
             f'{code_name} = "{code_name}"' in enums, "审计码是新增的，不加就是记了一笔无名账")
    c.ok("撤销写了审计（EXPENSE_DELETE + 金额 + 编号）",
         "action=OperationAction.EXPENSE_DELETE" in api_code
         and '"flow_ids": [f.id for f in flows]' in api_code, "")
    c.ok("恢复写了审计（EXPENSE_RESTORE）",
         "action=OperationAction.EXPENSE_RESTORE" in api_code, "")
    rc = read(REPORT_CENTER)
    for code_name in ("EXPENSE_DELETE", "EXPENSE_RESTORE"):
        m = re.search(r'"' + code_name + r'"\s*->\s*"([^"]+)"', rc)
        c.ok(f"ReportCenter.kt::actionLabel 有 {code_name} 的中文名",
             bool(m) and re.search(r"[\u4e00-\u9fff]", m.group(1) if m else "") is not None,
             "没有中文名 _tools/ai/_check_action_labels.py 红，审计页只会显示原始码")

    # ── 5. 安卓侧的手边入口 ────────────────────────────────────────────────
    c.section("5. 安卓：列表行上就能撤销、回收站档里能恢复")
    dto = block(read(DTO), "data class ExpenseDto")
    c.ok('ExpenseDto 解析 is_deleted（默认 false）', '@SerialName("is_deleted")' in dto, "")
    c.ok("ExpenseDto 解析 deleted_at", '@SerialName("deleted_at")' in dto, "")
    apis = read(APIS)
    live_apis = kt_live(apis)  # 注释掉的行不算入口（反验⑫就是这么弄坏的）
    c.ok('Apis.kt 有 @DELETE("expenses/{expenseId}")',
         '@DELETE("expenses/{expenseId}")' in live_apis, "")
    c.ok('Apis.kt 有 @POST("expenses/{expenseId}/restore")',
         '@POST("expenses/{expenseId}/restore")' in live_apis, "")
    c.ok('listExpenses 带 deleted_only 查询参数',
         '@Query("deleted_only")' in live_apis, "")
    repo = read(REPO)
    c.ok("AppRepository 有 deleteExpense / restoreExpense",
         "fun deleteExpense(" in repo and "fun restoreExpense(" in repo, "")
    c.ok("AppRepository.expenses 带 deletedOnly 参数",
         "deletedOnly" in block(repo, "suspend fun expenses(", 600), "")
    scr = read(SCREEN)
    c.ok("开销页有「显示已撤销」那一档", "显示已撤销" in scr and "只看未撤销" in scr,
         "已撤销的行默认看不见，这一档是它们的落点，也是「恢复」的入口")
    c.ok("那一档真的把 deleted_only 传下去", "deletedOnly = showDeleted" in scr, "")
    c.ok("行上有「撤销」（红字）与「恢复」两个手边按钮",
         'Text("撤销"' in scr and 'Text("恢复")' in scr, "")
    c.ok("撤销走既有的危险确认控件（二次确认）",
         "DangerConfirmDialog(" in scr and "vm.pendingCancel?.let" in scr,
         "用户 2026-09-20：所有删除一律软删 —— 界面上要给的是「撤销」+「恢复」，不是裸删")
    c.ok("确认框的失败原因画在弹层自己里面",
         "error = vm.actionError" in scr and "enabled = !vm.acting" in scr,
         "页面级错误在弹层下面，用户看到的是「点了没反应」（客户收款页真机实测过两次）")
    c.ok("撤销/恢复真的打到两个新端点上",
         "repo.deleteExpense(" in scr and "repo.restoreExpense(" in scr, "")
    c.ok("恢复之后列表与名册都刷新（那一笔回到合计里）",
         "loadCategories()" in block(scr, "fun restore(", 900), "")

    # ── 6. 单测、覆盖率理由、文书接线 ──────────────────────────────────────
    c.section("6. 单测、覆盖率与文书")
    tsrc = read(TEST)
    n_case = len(re.findall(r"def test_", tsrc))
    c.ok(f"单测用例数 {n_case}（下限 6）", n_case >= 6, "三态 + 每个口径各一支")
    for name in TEST_NAMES:
        c.ok(f"单测里有 {name}", f"def {name}(" in tsrc, "行为契约的名字改了就等于删了那条契约")
    c.ok("单测钉着「删前 − 这一笔 = 删后」的等式",
         "b - after[name] == amount" in tsrc and "back[name] == b" in tsrc,
         "恢复之后必须正好回到删前那个数 —— 少了后半句，"
         "「撤销没生效」与「撤销生效了但恢复坏了」就分不清")
    c.ok("等式覆盖三处口径（利润表 / 车辆成本表 / 收支页）",
         "operating_expense_total" in tsrc and "expense_window_total" in tsrc
         and "利润表期间费用" in tsrc, "")
    c.ok("单测用的是探针分类 + 远期窗口（不污染真账）",
         'PROBE = "TB16-PROBE"' in tsrc and "2032" in tsrc, "")
    cov = read(COVERAGE)
    for key, why in (('("DELETE", "expenses/{}")', "撤销"), ('("POST", "expenses/{}/restore")', "恢复")):
        c.ok(f"_write_coverage.py 的 EXCLUDED 里有 {key} 的书面理由", key in cov,
             f"{why}本轮只做人手出口（界面上那一行），理由要照 BUG-0029 那种「排期」写法")
    c.ok("那两条理由写的是「排期」而不是「永久不做」",
         "排期" in cov and '("DELETE", "expenses/{}")' in cov, "")
    led = read(LEDGER)
    row = next((ln for ln in led.splitlines() if ln.startswith("| TA-16 ")), "")
    c.ok("台账 TA-16 那一行的状态不再是「已复现」", bool(row) and "已复现" not in row,
         "实际那一行：" + row[:160])
    i = led.find("### TA-16 ")
    seg = led[i:i + 5000] if i >= 0 else ""
    c.ok("TA-16 详情块追加了「补充（2026-10-10，已修复）」",
         "- 补充（2026-10-10，已修复" in seg, "台账是给下一轮的人看的，结论要落在条目里")
    ch = read(CHANGE) if CHANGE.exists() else ""
    c.ok("变更单 docs/changes/BUG-0034.md 存在", bool(ch),
         "修法：照 docs/changes/_TEMPLATE.md 的九节写")
    c.ok("变更单头部有 - **ID**：BUG-0034", "- **ID**：BUG-0034" in ch, "")
    c.ok("变更单六格齐全",
         all(w in ch for w in ("Changed", "Preserved", "Evidence", "Known Limitations",
                               "Rollback", "Historical Data Impact")), "")
    c.ok("docs/changes/README.md 里那一行带 ](BUG-0034.md) 链接",
         "](BUG-0034.md)" in read(CHANGE_IDX), "少这个链接 _tools/qa/_check_dev_spec.py 红")
    claim = read(CLAIM) if CLAIM.exists() else ""
    c.ok("AI_WORK_CLAIM.md 声明了核心改动（schema_bootstrap）",
         "核心改动：backend/app/core/schema_bootstrap.py" in claim,
         "加列必须动核心区的幂等自愈段，声明页里要有 核心改动：<路径> —— 为什么必须动核心：<一句话>")
    c.ok("AI_WORK_CLAIM.md 的进行中里有 BUG-0034", "BUG-0034" in claim, "")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：开销的撤销是软删、能原样恢复、"
          f"{len(sites)} 处取数都排除了已撤销的行（BUG-0034 / 台账 TA-16）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
