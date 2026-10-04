# -*- coding: utf-8 -*-
"""红线：**经营利润表**（FEAT-0011，2026-10-04）—— 「这一段赚了多少」全项目只有一处减法，
每一格都要能被追问「这是怎么算的」。

## 用户原话（2026-10-04，先有分析、再要求把财务系统补完整）
> 「我们先自己目标，我们将整个项目的财务系统进行一个完善。同时，你也可以加对应的前端和后端的能力。
>  然后对应的设计风格和写代码的规范和要求，要按照我们的要求进行。与此同时，别忘了，我们的 a i
>  也要具备啊，全部的查看能力，他能通过这些所有数据进行分析。」

财务分析当场算出来的那个数是 **−32,830.30**（2026-06 至 10-04：商品毛利 16,707.70 − 司机应得 13,537.00
− 开销 36,001.00）—— 也就是说「赚了多少」这个问题，此前**全系统没有任何一处能回答**：
营业额在 `/reports/turnover`、毛利在同一处的另外两格、司机应得在 `driver_bills`、开销在
`expenses`，四块钱从来没有在同一张表上相减过。

## 这条为什么必须有机器的判据
这张表**只减不加**，所以它的危险全在「悄悄地算第二遍」和「把不知道的当成 0」这两件事上：

* 把 `expenses` 改成按 `cash_flows.flow_date` 取数 → 同一笔钱落在别的月份，**两个人都不会报错**
  （钱什么时候付 ≠ 这笔费用算哪一期）；
* 把 `delivery_cost` 写成 Σ `orders.freight_fee` → 数字看着很像，但它与营业纵览的「司机运费支出」
  是两个口径（审计 R12-M2 实测过：47,870.00 vs 24,770.00，虚高 93%）；
* 拿 `order_money` / `cost_basis` / `driver_pay` 在报表里**再算一遍** → 毛利上栽过的那次就是两边各算一遍
  （界面 72,177.75 vs 正确 10,789.00，差 6.7 倍），而这次的代价是「利润」这一格；
* 给算不出成本的收入按 0 成本或平均成本**替它猜** → 毛利凭空变好，且没人会来报「你算多了」；
* 税金那一格去编一个税率 → 一个**编出来的数字**进了老板的眼睛，比空着危险得多；
* 期间费用里再单独扣一次 `damage_amount` → 货损被扣两遍（货损本来就是一张开销单）；
* 客户端（Android）为了"顺手"自己减一遍 → 界面与接口各说各话，且这一页永远不会因为后端改口径而变。

判据分八层：

0. **反空转**：查询 / schema / 路由 / 导出 / Android 那一页都在（截空即红）；
1. **只相减、不重算**：前四格全部取营业纵览的同一批聚合数，本文件一个原始金额都不自己算；
2. **窗口只有一处**：期间费用按业务发生日（`exp_date`）落窗口、不加软删过滤（这张表没有软删列）；
3. **不知道就说不知道**：税金恒 0 且原因进 notes、未覆盖收入单列、口径说明五条齐全；
4. **接口与导出**：`GET /reports/profit` 四件套（窗口下推到 `_span`、只读权限、pop `_window`、schema），
   导出第 7 个 kind 里**带着覆盖率与口径说明**一起写进表；
5. **AI 看得见**（用户这次的要求之一）：toolmap 读动作 + 中文说明 + 生成的 App 侧白名单，
   三处缺一处，模型就问不出「这月赚了多少」；
6. **Android 九处**：DTO / Api / Repository / 页签常量 / 入口第 7 格 / 路由 / NavGraph / ViewModel / 页面，
   以及**页面自己不做减法**（`money(...)` 里不许出现算术）、口径说明**常显**；
7. **用例与文档**：后端单测钉恒等式与税、Android 单测钉页签映射、三份地图文档跟着改。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界消除不了**。四块钱各自都有唯一实现、也各自都有判据，
但「把它们相减」这件事**没有任何类型能保证**：`build_profit` 返回的是一个普通 `dict`，
`ProfitReportOut` 的每个字段都有默认值 `0`，Android 侧每个金额都是 `String = "0"`。
所以「用了另一个口径」「自己算了一遍」「把算不出来的当成 0」这三种写法**全部编译通过、接口也照样 200**，
只有懂行的人把这些数拿去和营业纵览对一遍才会发现。类型系统管不了「这个数是从哪来的」，
只能靠一条判据把查询、schema、路由、导出、AI 目录与 Android 那一页对起来，
并在反向验证里把这几种写法各跑一遍（看判据是否每次都报红）。

用法：python _tools/qa/_check_profit_report.py
     python _tools/qa/_check_profit_report.py --list
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用兄弟红线里剥注释的实现，不抄第二份（Kotlin 侧用）。
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

QUERY = ROOT / "backend/app/services/reports/profit_query.py"
SCHEMA = ROOT / "backend/app/schemas/reports.py"
API = ROOT / "backend/app/api/v1/reports.py"
REPORTS_SERVICE = ROOT / "backend/app/services/reports_service.py"
TOOLMAP = ROOT / "docs/ai/ai_toolmap.json"
CN_GEN = ROOT / "_tools/ai/_gen_ai_read_catalog.py"
CATALOG = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiReadCatalog.kt"

DTOS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"
APIS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt"
REPO = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/repo/AppRepository.kt"
FINANCE = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportFinance.kt"
HOME = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportHome.kt"
ROUTES = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/nav/Routes.kt"
NAV = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/nav/NavGraph.kt"
VM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenterViewModel.kt"
CENTER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"

TEST_PY = ROOT / "backend/tests/test_profit_report.py"
TEST_KT = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/dispatcher/ReportFinanceTest.kt"

REVERSE = ROOT / "_tools/qa/_reverse_verify_profit_report.py"
DOC_TESTING = ROOT / "docs/PROJECT_MAP/05_TESTING.md"
DOC_FLOW = ROOT / "docs/PROJECT_MAP/07_END_TO_END_FLOW.md"
DOC_LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"

JUDGE_NAME = "_tools/qa/_check_profit_report.py"
REVERSE_NAME = "_tools/qa/_reverse_verify_profit_report.py"

#: 导出第 7 个 kind 与那张 sheet 的名字（改名字必须同步这里）
KIND = "profit"
SHEET = "经营利润"

#: 后端返回的键 = DTO 的 snake_case 名 = 这一页能用到的每一个数（少一个都说明有人改了对外口径）
KEYS = (
    "period_label", "revenue_total", "revenue_covered", "revenue_uncovered",
    "cost_total", "gross_profit", "total_lines", "covered_lines",
    "cost_avg_lines", "cost_snapshot_lines", "delivery_cost",
    "operating_expense_total", "operating_expenses", "tax_total", "operating_profit",
    "collected", "arrears_total", "cancelled_orders", "damage_qty", "damage_amount",
    "notes",
)

#: 函数体下限（抽取失效比判据腐烂更危险）
QUERY_FLOOR = 900
SCHEMA_FLOOR = 800
TAB_FLOOR = 1500


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit("找不到文件：" + str(p) + "（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


def py_code(src: str) -> str:
    """Python 侧剥掉模块 docstring 与整行注释 —— 「代码里不许有 X」不能被自己的说明弄红。"""
    src = re.sub(r'(?s)^\s*"""\s*.*?"""', "", src, count=1)
    return re.sub(r"(?m)^\s*#.*$", "", src)


def kt_code(p: Path) -> str:
    return strip_comments(read(p))


def body(src: str, sig: str, limit: int = 6000) -> str:
    """从 [sig] 处取到**紧跟其后的下一个顶层定义**为止（取不到就按 [limit] 截）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    end = i + limit
    for marker in ("\ndef ", "\nclass ", "\nasync def ", "\n@router.", "\n@Composable",
                   "\nprivate fun ", "\nfun ", "\ninternal fun "):
        j = src.find(marker, i + len(sig))
        if i < j < end:
            end = j
    return src[i:end]


class Checker:
    def __init__(self) -> None:
        self.fails: list = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + label)
        else:
            self.fails.append(label + (" —— " + detail if detail else ""))
            print("  [FAIL] " + label + (" —— " + detail if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, "没找到 " + repr(pattern))

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, ("命中：" + repr(m.group(0)[:60])) if m else "")

    def report(self, what: str) -> int:
        if self.fails:
            print("")
            print("❌ " + what + "：通过 " + str(self.passes) + " 项，失败 " + str(len(self.fails)) + " 项")
            for f in self.fails:
                print("   - " + f)
            return 1
        print("")
        print("✅ " + what + "：通过 " + str(self.passes) + " 项，失败 0 项")
        return 0


def main() -> int:
    c = Checker()
    q = py_code(read(QUERY))
    q_raw = read(QUERY)
    sch = read(SCHEMA)
    api = py_code(read(API))
    svc = read(REPORTS_SERVICE)
    toolmap = read(TOOLMAP)
    cn_gen = read(CN_GEN)
    catalog = read(CATALOG)
    dtos = kt_code(DTOS)
    apis = kt_code(APIS)
    repo = kt_code(REPO)
    finance = kt_code(FINANCE)
    home = kt_code(HOME)
    routes = kt_code(ROUTES)
    nav = kt_code(NAV)
    vm = kt_code(VM)
    center = kt_code(CENTER)

    print("== 0. 反空转：查询 / schema / 路由 / 导出 / Android 那一页都在 ==")
    fn = body(q, "def build_profit(")
    c.ok("查询 build_profit 在且函数体 ≥ " + str(QUERY_FLOOR) + " 字符", len(fn) >= QUERY_FLOOR, "只有 " + str(len(fn)) + " 字符")
    c.present("函数签名收 span（窗口由接口层算好传进来，本文件不解析日期）",
              fn, r"span: tuple\[date, date\] \| None = None")
    model = body(sch, "class ProfitReportOut(")
    c.ok("schema ProfitReportOut 在且 ≥ " + str(SCHEMA_FLOOR) + " 字符", len(model) >= SCHEMA_FLOOR, "只有 " + str(len(model)) + " 字符")
    route = body(api, "def profit_report(")
    c.ok("路由 /profit 在且 ≥ 400 字符", len(route) >= 400, "只有 " + str(len(route)) + " 字符")
    c.present("导出里有 profit 这一支", api, r'elif kind == "' + KIND + r'":')
    tab = body(center, "private fun ProfitTab(")
    c.ok("Android ProfitTab 在且 ≥ " + str(TAB_FLOOR) + " 字符", len(tab) >= TAB_FLOOR, "只有 " + str(len(tab)) + " 字符")
    c.ok("reports_service 转出了 build_profit（接口层从它 import）",
         "build_profit" in svc and "profit_query" in svc)

    print("")
    print("== 1. 只相减、不重算：四块钱全部取既有唯一实现 ==")
    c.present("查询 import 的是营业纵览的 build_turnover（不是自己再查一遍订单）",
              q, r"from app\.services\.reports\.turnover_query import build_turnover")
    c.ok("build_turnover 只调一次（多调一次就是在同一页里取两遍数）",
         len(re.findall(r"build_turnover\(", fn)) == 1,
         "实际 " + str(len(re.findall(r"build_turnover\(", fn))) + " 次")
    c.present("窗口取自 turnover 的 _window（与营业纵览同一段，⛔ 不自己解析 date_from）",
              fn, r'turnover\["_window"\]')
    c.present("营业收入取 total_amount", fn, r'revenue_total = turnover\["total_amount"\]')
    c.present("参与毛利的收入取 cost_covered_amount", fn, r'revenue_covered = turnover\["cost_covered_amount"\]')
    c.present("商品成本取 cost_total", fn, r'cost_total = turnover\["cost_total"\]')
    c.present("配送成本取 total_freight（= 司机应得，⛔ 不是 orders.freight_fee）",
              fn, r'delivery_cost = turnover\["total_freight"\]')
    c.present("商品毛利 = 参与毛利的收入 − 商品成本（两侧同一批行）",
              fn, r"gross_profit = revenue_covered - cost_total")
    c.present("营业利润 = 毛利 − 配送 − 期间费用 − 税金（四级相减，一处也不许挪到客户端）",
              fn, r"operating_profit = gross_profit - delivery_cost - expense_total - tax_total")
    c.present("未覆盖收入 = 营业额 − 参与毛利的收入（单列，不替它猜成本）",
              fn, r'"revenue_uncovered": revenue_total - revenue_covered')
    c.absent("没有自己去读订单/账本/资金表（那都是别的钱的实现）",
             q, r"OrderProduct|from app\.models\.order|CashFlow|from app\.models\.ledger|Ledger\b")
    c.absent("没有自己重算别的钱：money_map( / pay_for_order( / line_receivable( / has_per_order_pay( 一个都不许出现",
             q, r"money_map\(|pay_for_order\(|line_receivable\(|has_per_order_pay\(")
    c.absent("查询里没有任何写库动词（只读边界另外还有 _check_report_boundary.py 在 AST 上盯着）",
             q, r"db\.add\(|db\.delete\(|db\.commit\(|db\.flush\(|\.insert\(|\.update\(|\.delete\(")

    print("")
    print("== 2. 期间费用的窗口与口径 ==")
    c.present("期间费用按业务发生日落地（exp_date），不是按钱什么时候付（flow_date）",
              fn, r"Expense\.exp_date >= start, Expense\.exp_date <= end")
    c.absent("没有用 flow_date 取费用（资金口径与经营口径是两件事）", q, r"flow_date")
    c.absent("没有加 is_deleted 过滤（expenses 表没有软删列，加了会直接报错）",
             q, r"Expense\.is_deleted|is_deleted\.is_\(False\)")
    c.present("空分类兜到「未分类」", fn, r'or "未分类"')
    c.present("服务端定序（金额降序、同额按分类名 —— 界面与导出不再各自排一遍）",
              fn, r'expenses\.sort\(key=lambda r: \(-r\["amount"\], r\["category"\]\)\)')
    c.present("期间费用合计 = 明细之和", fn, r'expense_total = sum\(')

    print("")
    print("== 3. 不知道就说不知道：税金 / 未覆盖收入 / 口径说明 ==")
    c.present("税金恒为 0（⛔ 不许编一个税率出来）", fn, r"tax_total = _ZERO")
    c.present("返回值里真的有 tax_total 这一格", fn, r'"tax_total": tax_total')
    notes = re.search(r"_NOTES: tuple\[str, \.\.\.\] = \(([\s\S]*?)\n\)", q_raw)
    body_notes = notes.group(1) if notes else ""
    c.ok("口径说明是模块常量、至少 5 条", body_notes.count('"') >= 10, "实际 " + str(body_notes.count('"')) + " 个引号")
    for word, why in (("税", "税金为什么是 0"), ("折旧", "折旧还没算进来"), ("工资", "固定工资不在这里"),
                      ("revenue_uncovered", "未覆盖收入单列"), ("货损", "货损不重复扣")):
        c.ok("口径说明里写了「" + why + "」", word in body_notes)
    c.absent("口径说明里不许出现 markdown 星号（这些字会原样进手机与导出的表）", body_notes, r"\*\*")
    c.present("notes 原样交给上层（界面与导出都靠它解释每一格）", fn, r'"notes": list\(_NOTES\)')
    c.present("docstring 写明两条恒等式是构造上成立的、不是碰巧相等",
              q_raw, r"是\*\*构造上成立\*\*的")

    print("")
    print("== 4. 接口与导出 ==")
    c.present("路由声明与 schema 对上", api, r'@router\.get\("/profit", response_model=ProfitReportOut\)')
    c.present("只读权限（报表是全店口径，与其它报表同一个权限）",
              route, r"require_permission\(Permission\.ORDER_DISPATCH\)")
    c.present("窗口走唯一入口 _span（半截窗口与反了的窗口由它拒绝）",
              route, r"_span\(mode, anchor, date_from, date_to\)")
    c.present("取数走 build_profit", route, r"data = build_profit\(db, mode, anchor, span=span\)")
    c.present("返回前 pop 掉 _window（内部键不许出接口）", route, r'data\.pop\("_window", None\)')
    c.present("返回 ProfitReportOut(**data)", route, r"return ProfitReportOut\(\*\*data\)")
    c.present("导出的 kind 正则收下了第 7 个值",
              api, r'\^\(turnover\|products\|drivers\|customers\|finance\|audit\|' + KIND + r'\)\$')
    c.present("导出里那张表叫「" + SHEET + "」", api, r'next_sheet\("' + SHEET + r'"\)')
    c.present("导出里带成本覆盖率（只有数字没有覆盖率，就是让人误读毛利）", api, r'"成本覆盖率"')
    c.present("导出里带口径说明（逐条 notes 写进表）", api, r'"口径说明"')
    c.present("导出里带期间费用明细与合计", api, r'"期间费用明细"')

    print("")
    print("== 5. AI 看得见（用户这次的要求之一：AI 要具备全部的查看能力）==")
    c.present("toolmap 里多了 reports.profit_report 这条读动作",
              toolmap, r'"action": "profit_report"')
    c.present("它的路径就是新端点", toolmap, r'"path": "/api/v1/reports/profit"')
    c.present("生成器里有它的中文说明（缺了生成器会直接报错退出，模型也选不出这个工具）",
              cn_gen, r'"reports\.profit_report": \(')
    c.present("App 侧白名单里有它（role = dispatcher，非会员专属）",
              catalog, r'ReadAction\("reports\.profit_report"')
    c.present("白名单里的路径与后端一致",
              catalog, r'"reports\.profit_report"[\s\S]{0,400}?"/api/v1/reports/profit"')
    c.present("白名单把它交给派单员", catalog, r'"reports\.profit_report"[\s\S]{0,600}?setOf\("dispatcher"\)')

    print("")
    print("== 6. Android：九处接线 ==")
    missing = [k for k in KEYS if ('@SerialName("' + k + '")') not in dtos]
    c.ok("ProfitReportDto 的 21 个 snake_case 键一个不少（少一个就是有人改了对外口径）",
         not missing, "缺：" + "、".join(missing))
    dto_body = body(dtos, "data class ProfitReportDto(")
    c.ok("金额字段都走 FlexibleStringSerializer（后端给的是字符串化的 Decimal）",
         dto_body.count("FlexibleStringSerializer") >= 13,
         "实际 " + str(dto_body.count("FlexibleStringSerializer")) + " 处")
    c.present("期间费用明细的类型在", dtos, r"data class ProfitReportExpenseItemDto\(")
    c.present("interface ReportApi 里声明了 GET reports/profit", apis, r'@GET\("reports/profit"\)')
    c.present("它返回 ProfitReportDto", apis, r"suspend fun profit\([\s\S]{0,300}?\): ProfitReportDto")
    c.present("Repository 包了一层 profitReport(...)",
              repo, r"suspend fun profitReport\([\s\S]{0,300}?\) = api\.reportApi\.profit\(mode, date, dateFrom, dateTo\)")
    c.present("页签 6 导出 profit（第 7 个 kind）", finance, r'6 -> "profit"')
    c.present("页签 5 显式写 audit（原来靠 else —— 加了第 7 格之后 else 会把它吃掉）",
              finance, r'5 -> "audit"')
    cards = re.findall(r"EntryCard\(", home)
    c.ok("入口页现在是 7 格", len(cards) == 7, "实际 " + str(len(cards)) + " 格")
    c.present("第 7 格是「经营利润」且 key 是 6（key 直接当页签号用）",
              home, r'EntryCard\("6", "经营利润"')
    c.present("路由常量 REPORT_PROFIT 在", routes, r'const val REPORT_PROFIT = "report/profit"')
    c.present("NavGraph 里点第 7 格走到利润页", nav, r"6 -> navController\.navigate\(Routes\.REPORT_PROFIT\)")
    c.present("NavGraph 里第 6 格显式走到异常与审计（⛔ 不许再靠 else 兜）",
              nav, r"5 -> navController\.navigate\(Routes\.REPORT_EXCEPTION\)")
    c.present("利润页那条 composable 把页签号传进去",
              nav, r"composable\(Routes\.REPORT_PROFIT\) \{ ReportCenterScreen\([\s\S]{0,200}?initialTab = 6\)")
    c.present("ViewModel 收下页签 6", vm, r"initialTab\.coerceIn\(0, 6\)")
    c.present("ViewModel 给这一页留了数据槽", vm, r"var profit by mutableStateOf<ProfitReportDto\?>\(null\)")
    c.present("load() 里第 7 支取数（窗口与其它页共用同一个 dateRange）",
              vm, r"6 -> \{[\s\S]{0,200}?val \(f, t\) = dateRange[\s\S]{0,200}?profit = container\.repo\.profitReport\(")
    c.present("标题栏认第 7 个页签", center, r'6 -> "经营利润"')
    c.present("主体分发认第 7 个页签", center, r"6 -> ProfitTab\(vm\)")
    c.present("这一页吃的是 vm.profit", tab, r"val data = vm\.profit")
    c.absent("页面自己不做减法（money(...) 里不许出现算术 —— 那正是毛利栽过的那次）",
             tab, r"money\([^()]*[-+][^()]*\)")
    c.present("营业利润最大那格按正负上色（赚绿亏红）", tab, r"StatBig\(\"营业利润\", money\(data\.operatingProfit\), opColor\)")
    c.present("税金那一行在（今天恒 0，但必须看得见）", tab, r'"− 税金及附加"')
    c.present("配送成本用橙（与营业纵览同一个颜色，⛔ 不许换色）", tab, r'"− 配送成本\(司机应得\)", money\(data\.deliveryCost\), Color\(0xFFFF9500\)')
    c.present("未覆盖收入单列一张卡", tab, r'"算不出成本的收入"')
    c.present("利润构成是一条能自己算通的链（营业额 − 算不出成本 = 参与毛利 − 商品成本 = 商品毛利）",
              tab, r'"营业收入\(应收\)"[\s\S]{0,900}?"− 算不出成本的收入"[\s\S]{0,900}?"= 参与毛利的收入"[\s\S]{0,900}?"− 商品成本"[\s\S]{0,900}?"= 商品毛利"')
    lits = re.findall(r'"([^"\\\n]*)"', tab)
    bad_lits = [s for s in lits if "**" in s]
    c.ok("界面上的文字里不许出现 markdown 星号（手机上会原样显示）", not bad_lits, "命中：" + repr(bad_lits[:3]))
    c.present("口径说明走 CoverNote（成本覆盖率四处一致）",
              tab, r"CoverNote\(data\.coveredLines, data\.totalLines, data\.costAvgLines, data\.costSnapshotLines\)")
    c.present("口径说明逐条原样常显", tab, r"data\.notes\.forEach")
    c.absent("口径说明没有被包进 Hint 开关（藏起来就等于让人把营业利润读成净利润）",
             tab, r"Hint\(|ExpandableCard\(|var .*by remember \{ mutableStateOf\(false\) \}")
    c.present("资金状态那一块在（赚了不等于收到了）", tab, r"赚了不等于收到了")

    print("")
    print("== 7. 用例与文档 ==")
    test_py = read(TEST_PY)
    names = re.findall(r"def (test_\w+)\(", test_py)
    c.ok("后端单测至少 8 条", len(names) >= 8, "实际 " + str(len(names)) + " 条")
    c.ok("其中有一条逐分对账营业纵览（恒等式两侧同源）",
         any("营业纵览" in n or "逐分" in n for n in names), "现有：" + "、".join(names))
    c.ok("其中有一条钉「税恒为 0 且说了为什么」", any("税" in n for n in names), "现有：" + "、".join(names))
    c.ok("其中有一条钉窗口边界被拒（半截 / 反了的窗口）",
         any("窗口" in n for n in names), "现有：" + "、".join(names))
    test_kt = kt_code(TEST_KT)
    c.present("Android 单测钉了第 7 个页签的导出 kind", test_kt, r'exportKind\(6\)')
    c.present("Android 单测改成 7 个页签两两不同", test_kt, r"\(0\.\.6\)")
    rev = read(REVERSE)
    c.present("反向验证脚本拿着注入锁（lock_reverse_verify）", rev, r"lock_reverse_verify")
    c.present("反向验证脚本自己列了注入表（CASES）", rev, r"CASES = \[")
    c.present("反向验证脚本在 finally 里逐字节还原", rev, r"write_src\(path, plain, crlf\)")
    c.ok("三份地图文档都跟着改",
         ("经营利润" in read(DOC_TESTING)) and ("经营利润" in read(DOC_FLOW)) and ("经营利润" in read(DOC_LOCATOR)),
         "缺：" + "、".join([n for n, p in (("05_TESTING", DOC_TESTING), ("07_END_TO_END_FLOW", DOC_FLOW), ("08_CODE_LOCATOR", DOC_LOCATOR)) if "经营利润" not in read(p)]))
    c.ok("定位表里指路了本判据与它的反向验证",
         (JUDGE_NAME.split("/")[-1] in read(DOC_LOCATOR)) and (REVERSE_NAME.split("/")[-1] in read(DOC_LOCATOR)))

    return c.report("经营利润表：四块钱一处相减、不知道的如实说（FEAT-0011）")


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("经营利润表（FEAT-0011）红线：查询只相减不重算 / 期间费用按 exp_date / 税金如实记 0 且说明 /")
        print("接口与导出（含覆盖率与口径说明）/ AI 读动作三处齐全 / Android 九处接线与页面不做减法 / 用例与文档")
        raise SystemExit(0)
    raise SystemExit(main())
