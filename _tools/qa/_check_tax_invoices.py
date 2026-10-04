"""红线：**税账**（FEAT-0014，2026-10-04 五期计划第四期）—— 一张票 = 一笔进项的抵 / 一笔销项的缴。

## 由来（需求方要的四件事）

```text
1. 系统里要能登记发票（票号、开票日期、价税合计、税率、税额）
2. 要能开出去，也要能作废 · 冲红
3. 要能问「这个月要交多少增值税」—— 销项税额 − 进项税额
4. 利润表那一格「− 税金及附加」不能再恒为 0
```

在这之前，全库**一个税的数据源都没有**：利润表 `tax_total` 恒为 0、口径说明里如实写着
「税没有数据源」；`shipper_receipts.invoiced` 是一个勾了也没有落点的布尔；进项这一侧连
「这批货有没有票」都答不出来。于是「这个月要交多少税」只能翻纸质票手工加总。

## 三件坏起来**一条报错都不会有**的事

| 写坏的方式 | 表现 |
|---|---|
| 税额在第二个地方又算一遍 | 票面税额与税汇里的数差一分钱，两边都看着有理 |
| 税汇把作废 / 回收站里的票也算进去 | 已经冲红的票还在交税，用户拿去申报就多缴 ⚠️ 两种「不算数」都保留行 |
| 利润表的「税」既留在期间费用里又搬进税那一格 | 同一笔钱扣两次，营业利润凭空少一截 |

## 判据（清单**全部自己算**，不手写「查哪些文件」）

1. **形状**：三张表（票头 + 进项↔采购单 + 销项↔账本）；票号唯一靠 `no_key` 编码，⛔ 不用
   `sqlite_where` 那种部分唯一索引（MySQL 会静默忽略，本机 SQLite 一切正常）。
2. **税额只有一个算法**：`tax_of_amount` 一处定义；税率区间与「税额不能大于合计」都在
   `_tax_pair`；端点层不碰税。
3. **关联校验**：进项要供应商 + 至少一张采购单、销项要客户；两边不许串；供应商 / 客户要一致。
4. **状态机**：登记 → 开具 → 作废；非「已登记」改不动；开具 / 作废不许重复推进；
   **软删的票仍然占着号**（唯一索引是两列，软删不清号）。
5. **税汇口径唯一**：`counts_in_tax` 一处判据；`sum_taxes` 三态（作废只计数、未税进
   `untaxed_*`、其余进分方向与分税率的小格）；`vat_payable` 一处减法。
6. **采购单删单闸**：挂着还没作废的进项票就不许删（删了那些票的进项税额会凭空少掉）。
7. **利润表接线**：税那一格取分类名带「税」的开销 + 从期间费用搬出（总额不变）；
   `vat_*` 三格只读、不进营业利润；口径说明不含 markdown 星号。
8. **端点与权限**：写 `LEDGER_EDIT`、读 `ORDER_DISPATCH`；六个写端点全走 `_write(` 守卫；
   路由挂载 + 报表端点 + 导出 kind 白名单。
9. **出参对齐**：`TaxSummaryOut` 的字段与 builder 的返回键一一对应（多一个少一个都是「界面上
   看不见的那个数」）。
10. **留痕**：六个动作码在枚举里、服务层各用一次、能力审计里登记过。
11. **单测**：上面每一条口径都有人钉（`backend/tests/test_tax_invoices.py`）。
12. **Android**：发票台账 / 登记一张票两页 + 报表第 10 格「税账」的接线（DTO 键逐字、八个端点、
    仓库转出、路由三件套 + NavGraph、入口第 10 格、工作台一格挂写侧能力、页面⛔ 不算税额）。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界消除不了**。「一张票 = 一笔税」把三类事实绑在一起：
**票面金额与税率算出的税额**、**它抵的那几张业务单据**、**它算不算进这一期税汇**。
三件事都建在既有表上、都编译通过、接口都照样 200：

* 「税额在第二个地方又算一遍」与「只算一次」在类型上完全一样（都是 `Decimal`），差的是四舍五入
  取整的位置（`ROUND_HALF_UP` 到分）—— 差一分钱的两套数在界面上都看着有理；
* 「作废的票照样进税汇」是合法 SQL、合法 HTTP —— 而作废 · 冲红恰恰**是为了让它不进税汇**，
  用户会拿这个数去申报；
* 「税既留在期间费用又搬进税那一格」两处都是合法的求和：营业利润凭空少一截，而利润表七格
  彼此自洽（恒等式照样成立）；
* 「软删的票不占号」也是合法写法 —— 直到有人删一张票再登记同一个号，撞数据库的唯一索引报 500。

类型系统、权限点与 DB 约束只能保证「不炸」，保证不了「几个数对得上」—— 税对不对只有把票面
税额、税汇、利润表三处拿去复算才知道。所以守门人是这一条判据 + 注入式反验：每种破坏方式都要
让本脚本报红，且被碰过的文件逐字节还原。

⚠️ 注入式反向验证（改坏 → 本脚本必须红）：`_tools/qa/_reverse_verify_tax_invoices.py`（60 种破坏方式全被抓）。

用法：python _tools/qa/_check_tax_invoices.py
"""
from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
#: ⛔ 复用兄弟判据里「取一个模块级 Python 函数体」与「剥掉注释/文档字符串」的实现，不抄第二份。
from _check_report_window import py_def_body  # noqa: E402
from _check_single_source import code_only  # noqa: E402
ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "backend/app/models/invoice.py"
MIGRATION = ROOT / "backend/app/migrations/020_invoices.py"
SERVICE = ROOT / "backend/app/services/tax_service.py"
API = ROOT / "backend/app/api/v1/invoices.py"
INV_SCHEMA = ROOT / "backend/app/schemas/invoice.py"
TAX_QUERY = ROOT / "backend/app/services/reports/tax_query.py"
PROFIT_QUERY = ROOT / "backend/app/services/reports/profit_query.py"
REPORTS_SCHEMA = ROOT / "backend/app/schemas/reports.py"
REPORTS = ROOT / "backend/app/api/v1/reports.py"
PURCHASE = ROOT / "backend/app/services/purchase_service.py"
ROUTER = ROOT / "backend/app/api/v1/router.py"
ENUMS = ROOT / "backend/app/models/enums.py"
CAPA = ROOT / "backend/app/core/capability_audit_coverage.py"
TEST = ROOT / "backend/tests/test_tax_invoices.py"

ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
DTOS_KT = ANDROID / "data/remote/dto/Dtos.kt"
APIS_KT = ANDROID / "data/remote/api/Apis.kt"
REPO_KT = ANDROID / "data/repo/AppRepository.kt"
# 2026-10-05 CHG-0034：11 格清单搬到 report/ReportV2Model.kt 的 REPORT_ENTRIES ⇒ 锚点跟着搬
HOME_KT = ANDROID / "ui/dispatcher/report/ReportV2Model.kt"
FINANCE_KT = ANDROID / "ui/dispatcher/ReportFinance.kt"
CENTER_KT = ANDROID / "ui/dispatcher/ReportCenter.kt"
VM_KT = ANDROID / "ui/dispatcher/ReportCenterViewModel.kt"
ROUTES_KT = ANDROID / "ui/nav/Routes.kt"
NAV_KT = ANDROID / "ui/nav/NavGraph.kt"
MODULES_KT = ANDROID / "ui/nav/Modules.kt"
INV_LIST_KT = ANDROID / "ui/dispatcher/InvoicesScreen.kt"
INV_FORM_KT = ANDROID / "ui/dispatcher/InvoiceFormScreen.kt"

CODES = (
    "TAX_INVOICE_CREATE",
    "TAX_INVOICE_UPDATE",
    "TAX_INVOICE_ISSUE",
    "TAX_INVOICE_VOID",
    "TAX_INVOICE_DELETE",
    "TAX_INVOICE_RESTORE",
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


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的判据要跟着改，不许静默跳过）")
    return io.open(p, encoding="utf-8", errors="replace").read()


def ast_names(src: str, cls: str) -> set[str]:
    """一个 class 里显式声明的字段名（注解赋值）—— 模型与 pydantic schema 通用。"""
    for node in ast.parse(src).body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return {t.target.id for t in node.body
                    if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)}
    return set()


def ast_return_keys(src: str, func: str) -> set[str]:
    """一个函数里 return 那个 dict 的字符串键（出参与 builder 对齐用）。"""
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                    return {k.value for k in sub.value.keys if isinstance(k, ast.Constant)}
    return set()


def ast_str_tuple(src: str, name: str) -> list[str]:
    """模块级的一个字符串元组常量（`_NOTES` 那种）。"""
    value = None
    for node in ast.parse(src).body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == name:
            value = node.value
        elif isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            value = node.value
        else:
            continue
        if isinstance(value, ast.Tuple):
            return [e.value for e in value.elts if isinstance(e, ast.Constant)]
    return []


def kt_class(src: str, name: str) -> str:
    """一个 Kotlin data class 的声明体（`data class X(` 到第一列的 `)`）——

    ⚠️ 判据要看的是**这一个类**里的键：整份 Dtos.kt 里找 `@SerialName("status")` 会命中别的类，
    那种查法在别处重复出现时是空转的（反验里踩过）。
    """
    head = "data class " + name + "("
    i = src.find(head)
    if i < 0:
        return ""
    j = src.find(chr(10) + ")", i)
    return src[i:j if j > 0 else len(src)]


def kt_has_key(body: str, key: str) -> bool:
    """这个 Kotlin 类里有没有这个 JSON 键（`@SerialName` 改过名，或属性名本身就是键）。"""
    return f'@SerialName("{key}")' in body or ("val " + key + ":") in body or ("val " + key + " :") in body


def main() -> int:
    inv = read(MODEL)
    mig = read(MIGRATION)
    svc = read(SERVICE)
    api = read(API)
    schema_inv = read(INV_SCHEMA)
    tq = read(TAX_QUERY)
    pq = read(PROFIT_QUERY)
    schema_rep = read(REPORTS_SCHEMA)
    reports = read(REPORTS)
    purchase = read(PURCHASE)
    router = read(ROUTER)
    enums = read(ENUMS)
    capa = read(CAPA)
    test = read(TEST)
    dto_kt = read(DTOS_KT)
    apis_kt = read(APIS_KT)
    repo_kt = read(REPO_KT)
    home_kt = read(HOME_KT)
    finance_kt = read(FINANCE_KT)
    center_kt = read(CENTER_KT)
    vm_kt = read(VM_KT)
    routes_kt = read(ROUTES_KT)
    nav_kt = read(NAV_KT)
    modules_kt = read(MODULES_KT)
    list_kt = read(INV_LIST_KT)
    form_kt = read(INV_FORM_KT)
    api_code = code_only(api)
    # ---- ① 形状：三张表，口径写进列里 ----
    print("① 形状：三张表（票头 + 进项↔采购单 + 销项↔账本），口径写进列里")
    head_cols = ast_names(inv, "Invoice")
    ok("票头字段齐（方向/票号/唯一键/开票日期/价税合计/税率/税额/供应商/客户/状态/备注/经手人）",
       {"direction", "invoice_no", "no_key", "invoice_date", "amount", "tax_rate", "tax_amount",
        "supplier_id", "customer_id", "status", "note", "operator_id"} <= head_cols,
       f"实际 {sorted(head_cols)}")
    po_cols = ast_names(inv, "InvoicePurchaseOrder")
    lg_cols = ast_names(inv, "InvoiceLedger")
    ok("进项票 ↔ 采购单（多对多：一张票可抵好几车货，月结合并开票）",
       {"invoice_id", "purchase_order_id"} <= po_cols, f"实际 {sorted(po_cols)}")
    ok("销项票 ↔ 账本条目（公司的应收记在 ledgers 上，⛔ 不是批发商自己那本）",
       {"invoice_id", "ledger_id"} <= lg_cols, f"实际 {sorted(lg_cols)}")
    ok("同方向 + 同票号唯一（两列都在那一个索引里）",
       'Index("uq_invoices_direction_no", "direction", "no_key", unique=True)' in inv)
    ok("空票号不参与唯一（no_key 可空 = 月结代开先登记、后补号，空号可以登记多张）",
       "no_key: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)" in inv)
    ok("⛔ 不用 sqlite_where 那种部分唯一索引（MySQL 静默忽略它，本机 SQLite 一切正常）",
       "sqlite_where" not in code_only(inv))
    ok("金额 / 税额是 Numeric 不是字符串（钱一旦是字符串，迟早有人拿它做加法）",
       "amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))" in inv
       and "tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True" in inv)
    ok("未税票与零税率票是两回事（tax_rate 可空 = 未税；0.00 = 零税率，照样进税汇）",
       "tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True" in inv)
    ok("迁移 020 只建这三张表（一事一迁移、不回填历史）",
       all(f"{cls}.__table__.create(bind=engine, checkfirst=True)" in mig
           for cls in ("Invoice", "InvoicePurchaseOrder", "InvoiceLedger"))
       and "VERSION = 20" in mig)

    # ---- ② 税额只有一个算法 ----
    print(chr(10) + "② 税额只有一个算法：票面合计与税率是输入，税额是算出来的")
    ok("tax_of_amount 在服务层定义恰好一次（税额的唯一写入点）",
       svc.count("def tax_of_amount(") == 1)
    ok("端点层不碰税（不自己乘税率、也不调 tax_of_amount）",
       "tax_of_amount" not in api_code)
    pair = py_def_body(svc, "_tax_pair")
    ok("税率与税额同生同灭 + 越界拦下（0 ~ 100 的百分数）",
       "只能在 0 到 100 之间" in pair and "没填税率的票不该有税额" in pair)
    ok("税额不许大于价税合计（填反了要指出来）", "税额不能大于价税合计" in pair)
    ok("登记与改票都走 _tax_pair（没有第二条算税的路）",
       "_tax_pair(" in py_def_body(svc, "create_invoice")
       and "_tax_pair(" in py_def_body(svc, "update_invoice"))
    ok("「算不算进税汇」用的是 tax_rate is not None（⛔ 不是真值判断 —— 0.00 的票要算数）",
       "return invoice.tax_rate is not None" in svc)
    ok("默认税率是一个后端常量（改默认值要改代码，这一点写进口径说明里）",
       svc.count("DEFAULT_TAX_RATE = ") == 1)
    # ---- ③ 关联校验：一张票只能抵 / 开给同一家 ----
    print(chr(10) + "③ 关联校验：进项要供应商 + 采购单，销项要客户，两边不许串")
    ok("进项票要写清供应商", "进项票要写清是哪个供应商开的" in svc)
    ok("进项票必须挂至少一张采购单（不然答不出「这批货有没有票」）",
       "进项票必须挂至少一张采购单" in svc)
    ok("销项票要写清客户", "销项票要写清开给哪个客户" in svc)
    ok("两边不许串（进项不填客户 / 账本，销项不填供应商 / 采购单）",
       "进项票是供应商开给我们的，不该填客户。" in svc
       and "进项票挂的是采购单，不该挂账本条目。" in svc
       and "销项票是我们开给客户的，不该填供应商。" in svc
       and "销项票挂的是客户应收（账本条目），不该挂采购单。" in svc)
    ok("挂的单据要与票面同一家（供应商一致 / 客户一致两条都在）",
       "一张进项票只能抵同一家供应商的货" in svc and "一张销项票只能开给同一个客户" in svc)
    ok("方向只有销项 / 进项两个取值", "发票方向只能是销项（OUTPUT）或进项（INPUT）。" in svc)
    ok("挂在回收站里的采购单要如实拦下（⛔ 不是静默当它不存在）",
       "先去采购单回收站把" in svc and "再挂到这张票上" in svc)

    # ---- ④ 状态机 + 两种「不算数」 ----
    print(chr(10) + "④ 状态机：登记 → 开具 → 作废，两种不算数都保留原样可查")
    ok("三个状态常量取自枚举（⛔ 不是散落的字符串字面量）",
       "REGISTERED = InvoiceStatus.REGISTERED.value" in svc
       and "ISSUED = InvoiceStatus.ISSUED.value" in svc
       and "VOIDED = InvoiceStatus.VOIDED.value" in svc)
    ok("只有「已登记」的票能改（开具 / 作废之后冻结）", "只有「已登记」状态的票能改" in svc)
    ok("开具不许重复推进（已开具 / 已作废两种都给不同的话）",
       "这张票已经开具过了。" in svc and "作废的票不能再开具" in svc)
    ok("作废不许重复推进", "这张票已经作废过了。" in svc)
    dup = py_def_body(svc, "_check_no_duplicate")
    ok("查重不筛回收站（软删不清号 —— 筛了就会撞数据库唯一索引报 500）",
       "Invoice.is_deleted" in dup and ".is_(False)" not in dup)
    ok("命中回收站里那张票时，把「先恢复出来」说出来", "那张票现在在回收站里" in dup)
    ok("恢复：不在回收站里的票要拦下（⛔ 不是静默成功）", "这张票不在回收站里，不需要恢复。" in svc)

    # ---- ⑤ 税汇：口径唯一 ----
    print(chr(10) + "⑤ 税汇：counts_in_tax 一处判据，sum_taxes 一处聚合")
    ok("窗口按开票日期（⛔ 不按 created_at —— 今天补录上个月的票要落在上个月）",
       "Invoice.invoice_date >= start" in svc and "Invoice.invoice_date <= end" in svc)
    st = py_def_body(svc, "sum_taxes")
    ok("回收站里的票不进税汇（查询条件上就排掉 —— 查的是 sum_taxes 里那一句）",
       "Invoice.is_deleted.is_(False)" in st)
    ok("作废的票只计数、不进税额（voided_count 如实给出来）",
       "voided += 1" in st and '"voided_count": voided' in st)
    ok("没税率的票进 untaxed_*、不进税额（一眼看得出还有票没税率）",
       'side["untaxed_count"] += 1' in st and "if invoice.tax_rate is None:" in st)
    ok("应交增值税只有一处减法：销项税额 − 进项税额",
       '"vat_payable": sides[OUTPUT]["tax_amount"] - sides[INPUT]["tax_amount"]' in st)
    ok("按税率分组的小格：销项在前、税率从高到低",
       "sorted(buckets, key=lambda k: (k[0] != OUTPUT, -k[1]))" in st)
    side = py_def_body(svc, "_empty_side")
    ok("两侧小格的形状齐全（笔数 / 价税合计 / 不含税 / 税额 + 未税的两个计数）",
       all(k in side for k in ("count", "amount", "net_amount", "tax_amount",
                               "untaxed_count", "untaxed_amount")))
    # ---- ⑥ 采购单删单闸 ----
    print(chr(10) + "⑥ 采购单删单闸：挂着还没作废的进项票就不许删")
    ok("闸门函数在（找出还算数的进项票 + 拦住删单）",
       "def _live_invoices_on(" in purchase and "def _ensure_no_live_invoices(" in purchase)
    sdo = py_def_body(purchase, "soft_delete_order")
    ok("删单时先 ensure_alive 再查票（两道闸都在、顺序固定）",
       -1 < sdo.find("ensure_alive(") < sdo.find("_ensure_no_live_invoices("))
    live = py_def_body(purchase, "_live_invoices_on")
    ok("还算数的进项票 = 没软删 + 没作废（与税汇口径一致）",
       "Invoice.is_deleted.is_(False)" in live and "InvoiceStatus.VOIDED.value" in live)
    ok("拦截文案说清了为什么（删了这些票的进项税额会凭空少掉）",
       "进项税额凭空少掉" in purchase and "先把那些票作废或删掉" in purchase)

    # ---- ⑦ 利润表接线 ----
    print(chr(10) + "⑦ 利润表接线：税那一格接上数据源，搬家不双扣，增值税不进营业利润")
    ok("「税金及附加」的判据只有一个：分类名里带「税」",
       'TAX_CATEGORY_KEYWORD = "税"' in tq
       and 'return TAX_CATEGORY_KEYWORD in str(name or "")' in tq)
    ok("带「税」的开销从期间费用里挖出来单列（⛔ 不重复扣）",
       'tax_expenses = [r for r in expenses if is_tax_category(r["category"])]' in pq
       and 'expenses = [r for r in expenses if not is_tax_category(r["category"])]' in pq
       and "expense_total = expense_total - tax_total" in pq)
    ok("营业利润那一行一字未改（搬家不改总额，逐分与旧实现相同）",
       "operating_profit = gross_profit - delivery_cost - expense_total - depreciation_total - tax_total" in pq)
    ok("增值税三格来自税汇的唯一实现（vat_of_span → sum_taxes）",
       "from app.services.reports.tax_query import is_tax_category, vat_of_span" in pq
       and "vat = vat_of_span(db, start, end)" in pq)
    ok("增值税三个键都在返回体里，且不进营业利润那一行",
       all(f'"{k}": vat["{k}"]' in pq for k in ("vat_output", "vat_input", "vat_payable")))
    notes = ast_str_tuple(pq, "_NOTES")
    ok("口径说明写清了税与增值税（至少 5 条、提到税与增值税、不含 markdown 星号）",
       len(notes) >= 5 and any("税" in n for n in notes) and any("增值税" in n for n in notes)
       and not any("**" in n for n in notes), f"实际 {len(notes)} 条")
    prof = ast_names(schema_rep, "ProfitReportOut")
    ok("出参模型跟上（vat_output / vat_input / vat_payable / tax_expenses 四列都在）",
       {"vat_output", "vat_input", "vat_payable", "tax_expenses"} <= prof)
    ok("利润表出参是 Decimal 入 Decimal 出（两位小数只在端点层格式化）",
       'vat_output: Decimal = Decimal("0")' in schema_rep)
    # ---- ⑧ 端点 / 权限 / 路由 / 导出 ----
    print(chr(10) + "⑧ 端点与权限：写 LEDGER_EDIT、读 ORDER_DISPATCH，六个写端点全走 _write 守卫")
    ok("写端点要 LEDGER_EDIT、读端点要 ORDER_DISPATCH（⛔ 不新建权限点）",
       "Writer = Depends(require_permission(Permission.LEDGER_EDIT))" in api
       and "Reader = Depends(require_permission(Permission.ORDER_DISPATCH))" in api)
    ok("八个端点齐（列表 / 详情 / 登记 / 改 / 开具 / 作废 / 删除 / 恢复）",
       api.count("@router.") == 8)
    ok("六个写端点都走 _write( 守卫（失败要 rollback，不留半成品）",
       api.count("_write(") == 7 and "db.rollback()" in py_def_body(api, "_write"))
    ok("路由挂在 app 上", "api_router.include_router(invoices.router)" in router)
    ok("税账报表端点在（只读，走 ensure_date_order 那一族）",
       '@router.get("/tax-summary"' in reports and "build_tax_summary(" in reports
       and "TaxSummaryOut(**data)" in reports)
    # ⚠️ 2026-10-04 · FEAT-0015：白名单第 11 个值 `customer-balances` 接在 tax-summary **后面**，
    # 所以这一条⛔ 不能再钉字符串尾部 `|tax-summary)$`（那会被后继者顶掉）——
    # 改成钉「白名单里真的有这个可选值」，中间与结尾两种位置都算。
    ok("导出 kind 白名单里加了 tax-summary",
       "|tax-summary|" in reports or "|tax-summary)" in reports)
    ok("导出分支把「算不算数」逐票写出来（作废 / 回收站 / 未税三种不算数都看得见）",
       'elif kind == "tax-summary":' in reports and 'next_sheet("税账")' in reports
       and "算不算数" in reports)

    # ---- ⑨ 出参对齐 + 口径说明 ----
    print(chr(10) + "⑨ 出参对齐：TaxSummaryOut 的字段与 builder 的返回键一一对应")
    out_keys = ast_return_keys(tq, "build_tax_summary") - {"_window"}
    fields = ast_names(schema_inv, "TaxSummaryOut")
    ok("builder 返回的每个键在出参里都有（少一个键 = 界面上看不见那个数）",
       out_keys <= fields, f"缺 {sorted(out_keys - fields)}")
    row_keys = {"direction", "invoice_no", "invoice_date", "amount", "tax_rate", "tax_amount",
                "net_amount", "status", "party_name", "counts_in_tax"}
    ok("逐票明细的键都在 TaxInvoiceRowOut 里",
       row_keys <= ast_names(schema_inv, "TaxInvoiceRowOut"),
       f"缺 {sorted(row_keys - ast_names(schema_inv, chr(84) + chr(97) + chr(120) + chr(73) + chr(110) + chr(118) + chr(111) + chr(105) + chr(99) + chr(101) + chr(82) + chr(111) + chr(119) + chr(79) + chr(117) + chr(116)))}")
    ok("两侧小格的键都在 TaxSideOut 里",
       {"count", "amount", "net_amount", "tax_amount", "untaxed_count", "untaxed_amount"}
       <= ast_names(schema_inv, "TaxSideOut"))
    ok("分税率的小格也有出参模型（direction / tax_rate / count / 三个金额）",
       {"direction", "tax_rate", "count", "amount", "net_amount", "tax_amount"}
       <= ast_names(schema_inv, "TaxRateBucketOut"))
    tq_notes = ast_str_tuple(tq, "_NOTES")
    ok("税账自己的口径说明也写清了（至少 4 条、提到作废与未税、不含 markdown 星号）",
       len(tq_notes) >= 4 and any("作废" in n for n in tq_notes)
       and not any("**" in n for n in tq_notes), f"实际 {len(tq_notes)} 条")

    # ---- ⑩ 留痕 ----
    print(chr(10) + "⑩ 留痕：六个动作码在枚举里、服务层各用一次、能力审计里登记过")
    ok("六个动作码都在枚举里（⛔ 一个动作一个码，出问题查得出是谁干的）",
       all(f'{c} = "{c}"' in enums for c in CODES),
       f"缺 {[c for c in CODES if c not in enums]}")
    ok("服务层每个码都用了一次（登记 / 改 / 开具 / 作废 / 删除 / 恢复各一处）",
       all(f"OperationAction.{c}" in svc for c in CODES))
    ok("能力审计里六个码都登记过（权限 → 动作 → 留痕覆盖率）",
       all(f"'{c}'" in capa for c in CODES))

    # ---- ⑪ 单测 ----
    print(chr(10) + "⑪ 单测：上面每一条口径都有人钉（backend/tests/test_tax_invoices.py）")
    for needle, label in (
        ("test_登记一张进项票", "税额由后端按税率算出来"),
        ("test_进项票不挂采购单", "进项必须挂采购单、供应商要一致"),
        ("test_进项票不许填客户", "进项不许填客户 / 账本"),
        ("test_销项票要写客户", "销项要客户、不许填供应商"),
        ("test_同方向同票号只能登记一次", "票号唯一（空号可以多张）"),
        ("test_回收站里的票仍然占着号", "软删占号、恢复不撞号"),
        ("test_开具之后改不动", "开具后冻结"),
        ("test_开具两次", "状态机不许重复推进"),
        ("test_作废的票退出税汇", "作废退出税汇但明细还在"),
        ("test_没填税率的票单独计数", "未税票不进税汇"),
        ("test_删掉挂着没作废进项票的采购单要拦下", "采购单删单闸"),
        ("test_按税率分组", "分税率小格（销项在前、税率降序）"),
        ("test_利润表的税那一格取分类名带税的开销", "税那一格搬家不双扣"),
        ("test_利润表多出应交增值税", "增值税不进营业利润"),
        ("test_每一步都留痕", "六个动作码留痕"),
        ("test_货主和司机一个口子都进不来", "货主 / 司机进不来"),
    ):
        ok(f"单测里有「{label}」那一条", needle in test)

    # ---- ⑫ Android：发票台账 / 登记一张票 / 报表第 10 格「税账」----
    print(chr(10) + "⑫ Android：发票台账 + 登记一张票 + 报表第 10 格「税账」")
    inv_dto = kt_class(dto_kt, "InvoiceDto")
    create_dto = kt_class(dto_kt, "InvoiceCreateRequest")
    update_dto = kt_class(dto_kt, "InvoiceUpdateRequest")
    tax_dto = kt_class(dto_kt, "TaxSummaryReportDto")
    side_dto = kt_class(dto_kt, "TaxSideDto")
    bucket_dto = kt_class(dto_kt, "TaxRateBucketDto")
    row_dto = kt_class(dto_kt, "TaxInvoiceRowDto")
    miss = [k for k in ("direction", "invoice_no", "invoice_date", "amount", "tax_rate", "tax_amount",
                        "status", "supplier_id", "supplier_name", "customer_id", "customer_name", "note",
                        "counts_in_tax", "purchase_order_ids", "ledger_ids", "is_deleted")
            if not kt_has_key(inv_dto, k)]
    ok("发票出参 DTO 的键与后端逐字对上（方向 / 票号 / 日期 / 价税合计 / 税率 / 税额 / 状态 / 双方 / 备注 / 算不算数 / 挂着谁 / 回收站）",
       not miss, "缺 " + str(miss))
    ok("建票请求：方向必填、价税合计必填、开票日期必填、税率与税额可空（都空 = 未税票）、可挂采购单",
       "val direction: String," in create_dto and "val amount: String," in create_dto
       and all(kt_has_key(create_dto, k) for k in ("invoice_date", "tax_rate", "tax_amount",
                                                   "purchase_order_ids", "ledger_ids")))
    ok("⛔ 改票请求里没有 direction（方向只在建票时定，换方向＝作废重开一张）",
       "direction" not in update_dto and kt_has_key(update_dto, "amount") and kt_has_key(update_dto, "note"))
    miss = [k for k in ("mode", "anchor", "date_from", "date_to", "label", "output", "input", "vat_payable",
                        "by_rate", "notes", "invoices", "voided_count", "default_tax_rate")
            if not kt_has_key(tax_dto, k)]
    ok("税汇 DTO 的键与后端 top keys 对上（销项 / 进项 / 该交的 / 分税率 / 口径 / 明细 / 作废张数 / 默认税率）",
       not miss, "缺 " + str(miss))
    ok("两侧小格六格都在（张数 / 价税合计 / 不含税 / 税额 / 未税张数 / 未税金额 —— 未税票单列，不混进合计）",
       all(kt_has_key(side_dto, k) for k in ("count", "amount", "net_amount", "tax_amount",
                                             "untaxed_count", "untaxed_amount")))
    ok("分税率小格与逐票明细的键都在（明细里带「算不算数」这一格）",
       all(kt_has_key(bucket_dto, k) for k in ("direction", "tax_rate", "count", "amount", "net_amount", "tax_amount"))
       and all(kt_has_key(row_dto, k) for k in ("party_name", "counts_in_tax", "net_amount")))
    ok("八个发票端点都在（列表 / 详情 / 建 / 改 / 开具 / 作废 / 撤票 / 恢复）",
       all(x in apis_kt for x in ('@GET("invoices")', '@GET("invoices/{invoiceId}")', '@POST("invoices")',
                                  '@PATCH("invoices/{invoiceId}")', '@POST("invoices/{invoiceId}/issue")',
                                  '@POST("invoices/{invoiceId}/void")', '@DELETE("invoices/{invoiceId}")',
                                  '@POST("invoices/{invoiceId}/restore")')))
    ok("报表接口收下了税汇这一支（reports/tax-summary）", '@GET("reports/tax-summary")' in apis_kt)
    ok("仓库把八个写读方法都转出来了（与后端一个口子：读 ORDER_DISPATCH、写 LEDGER_EDIT）",
       all(x in repo_kt for x in ("api.invoiceApi.listInvoices(", "api.invoiceApi.getInvoice(",
                                  "api.invoiceApi.createInvoice(", "api.invoiceApi.updateInvoice(",
                                  "api.invoiceApi.issueInvoice(", "api.invoiceApi.voidInvoice(",
                                  "api.invoiceApi.deleteInvoice(", "api.invoiceApi.restoreInvoice("))
       and "taxSummaryReport(" in repo_kt)
    ok("入口页第 10 格是「税账」（新页签只许追加在末尾）", 'EntryCard("9", "税账"' in home_kt)
    ok("导出 kind(9) = tax-summary（第 10 页导出的是税账那张表）", '9 -> "tax-summary"' in finance_kt)
    ok("报表页认第 10 格（标题 + 分发到税账页，页面本体在同一个文件里）",
       '9 -> "税账"' in center_kt and "9 -> TaxTab(vm)" in center_kt and "private fun TaxTab(" in center_kt)
    ok("ViewModel 收下页签 0..10 且拉了税汇（窗口与其它页签同一段）",
       "initialTab.coerceIn(0, 10)" in vm_kt and "taxSummary = container.repo.taxSummaryReport(" in vm_kt)
    ok("税账页只显示接口给的数（页面里没有第二种税额算法）",
       "vatPayable" in center_kt and "tax_of_amount" not in center_kt and "sum_taxes" not in center_kt)
    ok("三条路由常量都在（报表第 10 格 / 发票台账 / 登记一张票）",
       'const val REPORT_TAX = "report/tax"' in routes_kt
       and 'const val INVOICES = "dispatcher/invoices"' in routes_kt
       and 'const val INVOICE_FORM = "dispatcher/invoice-form"' in routes_kt)
    ok("NavGraph 认第 10 格（点「税账」进的是税账页）",
       "9 -> navController.navigate(Routes.REPORT_TAX)" in nav_kt and "initialTab = 9" in nav_kt)
    ok("两条发票路由都挂上了，表单页一条路由两个用法（带 invoiceId 就是改单）",
       "InvoicesScreen(" in nav_kt and "InvoiceFormScreen(" in nav_kt
       and 'Routes.INVOICE_FORM + "?invoiceId={invoiceId}"' in nav_kt and 'navArgument("invoiceId")' in nav_kt)
    ok("工作台多了「发票台账」一格、且挂在写侧能力上（票面金额直接进税汇）",
       'ModuleEntry("发票台账", Routes.INVOICES' in modules_kt and 'Routes.INVOICES to "ledger:edit"' in modules_kt)
    ok("台账页四件事都在（回收站开关 / 方向筛选 / 开具 / 作废 / 撤票 / 恢复），并写清「作废不等于删除」",
       all(x in list_kt for x in ("DIRECTION_TABS", "发票台账 · 回收站", "container.repo.issueInvoice(",
                                  "container.repo.voidInvoice(", "container.repo.deleteInvoice(",
                                  "container.repo.restoreInvoice(", "作废不等于删除")))
    ok("登记 / 改票页的三条本地校验都在（金额必填、填了税额就得填税率、进项要供应商 + 采购单）",
       "价税合计得填个数" in form_kt and "填了税额就得填税率" in form_kt
       and "进项票至少要挂一张采购单" in form_kt)
    ok("只读条件只有一处（非「已登记」或进了回收站 ⇒ 不显示保存按钮并说明原因）",
       "val editable" in form_kt and "Icons.Default.Lock" in form_kt)
    ok("⛔ 表单页不算税额（不出现 `amount × 税率` 那套 —— 界面与接口各算一遍就会各说各话）",
       all(x not in form_kt for x in ("* vm.taxRate", "toDouble() *", "* 0.13")))
    ok("未税票的含义写在界面上（「不是 0% 税率的票」），且讲清了「只填税率、后端倒推」",
       "未税票" in form_kt and "倒推" in form_kt and "未税" in list_kt)

    print(chr(10) + "=" * 64)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for item in fails:
            print("   - " + item)
        return 1
    print(f"✅ 全部 {passes} 项通过：一张票 = 一笔进项的抵 / 一笔销项的缴；税额只有一个算法、"
          "税汇口径唯一、作废与回收站都不算数；利润表的税那一格搬家不双扣，增值税不进营业利润。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())