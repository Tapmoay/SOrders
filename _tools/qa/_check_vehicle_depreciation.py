# -*- coding: utf-8 -*-
"""红线：**车辆台账与折旧**（FEAT-0012 第二期，2026-10-04）—— 「这台车每个月自己在花钱」
第一次是一个**能被算出来、能被复算的派生量**，而不是一个账本里躺着的数。

## 需求方 2026-10-04 拍板的三条口径（本项目全部落点都从这三条推出来）
> 折旧怎么算 → 「录「购置价 ＋ 购置日期 ＋ 使用年限 ＋ 残值率」，系统**按月直线法**自动计提」
> 折旧放哪里 → 「**并入「期间费用」那一层**（与开销同一层，多一行「− 车辆折旧」）」
> 历史车怎么办 → 「**不回溯**：缺购置价的车不算折旧，利润表里单列「未覆盖折旧」并说明」

## 这条为什么必须有机器的判据

折旧这一格里**每一个数都是派生量**：月额 = 购置价 ×（1 − 残值率）÷（使用年限 × 12），
窗口内 = Σ 各自然月（月额 × 交集天数 ÷ 当月天数）。危险全在下面这几件事上，
而它们**每一件都能编译通过、接口也照样 200**：

* 按**整月**摊而不是按天摊 → 月中买的车多提半个月，跨窗口对不上（而数字看着很正常）；
* 忘掉残值率（或当成 0）→ 每台车每月多提一点点，一年后是一笔钱；
* 缺购置信息的车**按 0 算** → 报表里那台车的折旧消失，用户以为"系统算过了"；
* 把折旧**折进期间费用** → 恒等式还成立，但「− 车辆折旧」这一行没了，利润表从此看不懂；
* 折旧**落库**（写一列 accumulated_depreciation）→ 改口径就要回填历史行，而且再也不会自己变；
* 车辆成本表里**硬摊收入** → 订单上没有「哪台车拉的」这个事实，摊出来的比例会被拿去决定"这车留不留"；
* 客户端自己减一遍 → 界面与接口各说各话（毛利上栽过的那一次就是这个形状）。

判据分八层：

0. **反空转**：折旧服务 / 车辆成本查询 / 迁移 / 利润查询 / Android 两个页面 / 配套反验都在（截空即红）；
1. **口径唯一**：月额公式、留空 = 0%、按天摊、只四舍五入一次、提足之后是 0 —— 全在
   `services/vehicle_depreciation.py` 一个纯函数文件里，⛔ 不许碰库；
2. **校验话术也是唯一一份**：越界 → 400 ＋ 一句能照着改的中文（与接口层共用同一个函数）；
3. **模型 / 迁移 / 运行时自愈三处逐列一致**（少了任何一处，老库与新库就会长得不一样）；
4. **利润表**：折旧独立减一项（五级相减）、未覆盖的车单列、口径说明第 2 条改成"已经算进来了"；
5. **车辆成本表**：三笔成本全部取既有唯一实现、合计 == 逐车相加、⛔ 这张表没有收入；
6. **Android**：第 8 格入口 / 路由 / ViewModel / 利润链条那一行 / 车辆成本页 / 车辆管理四格；
7. **用例与文档**：后端两类单测的下限、Android 单测钉"¥0 与未覆盖是两件事"、定位表指路。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界消除不了**。四格都存在 `vehicles` 表上（可空），
折旧额本身**不进任何一张表** —— 它是一个普通 Python 函数的返回值，再进 `dict` 与 pydantic 模型，
每一层都有默认值 0。所以「按整月摊」「忘掉残值率」「缺格当 0」「折进期间费用」「落库」
这五种写法**全部编译通过、接口也照样 200**，只有把数拿去和手工算的对一遍才会发现。
类型系统管不了「这个数是怎么摊出来的」，只能靠一条判据把口径、三处列定义、报表、
成本表与 Android 那一页对起来，并在反向验证里把这几种写法各跑一遍（看判据是否每次都报红）。

配套：`python _tools/qa/_reverse_verify_vehicle_depreciation.py`（23 种破坏方式全被抓）。

用法：python _tools/qa/_check_vehicle_depreciation.py
     python _tools/qa/_check_vehicle_depreciation.py --list
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

DEP = ROOT / "backend/app/services/vehicle_depreciation.py"
COST = ROOT / "backend/app/services/reports/vehicle_cost_query.py"
QUERY = ROOT / "backend/app/services/reports/profit_query.py"
MIGRATION = ROOT / "backend/app/migrations/018_vehicle_depreciation.py"
BOOT = ROOT / "backend/app/core/schema_bootstrap.py"
MODEL = ROOT / "backend/app/models/vehicle.py"
SCHEMA_R = ROOT / "backend/app/schemas/reports.py"
SCHEMA_A = ROOT / "backend/app/schemas/accounting_v2.py"
API_V = ROOT / "backend/app/api/v1/vehicles.py"
API_R = ROOT / "backend/app/api/v1/reports.py"
SVC = ROOT / "backend/app/services/reports_service.py"
PKG = ROOT / "backend/app/services/reports/__init__.py"

DTOS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"
APIS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt"
REPO = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/repo/AppRepository.kt"
CENTER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"
VM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenterViewModel.kt"
FINANCE = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportFinance.kt"
HOME = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/report/ReportV2Model.kt"
# 2026-10-05 CHG-0034：11 格老入口清单从 `ReportHome.kt` 搬进了 `report/ReportV2Model.kt` 的
# `REPORT_ENTRIES`（ReportHome.kt 只引用它，避免两处手抄）⇒ 锚点跟着实现搬家，判据一条没放宽：
# 仍然数「一共 11 格」「第 N 格的 key 与名字」，只是改在唯一那一份清单上数。
ROUTES = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/nav/Routes.kt"
NAV = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/nav/NavGraph.kt"
VSCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleManageScreen.kt"

TEST_PY = ROOT / "backend/tests/test_vehicle_depreciation.py"
TEST_PY2 = ROOT / "backend/tests/test_vehicle_cost_report.py"
TEST_KT = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/dispatcher/VehicleManageScreenTest.kt"

REVERSE = ROOT / "_tools/qa/_reverse_verify_vehicle_depreciation.py"
PROFIT_JUDGE = ROOT / "_tools/qa/_check_profit_report.py"
PROFIT_REVERSE = ROOT / "_tools/qa/_reverse_verify_profit_report.py"
DOC_LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"
FEAT_DOC = ROOT / "docs/changes/FEAT-0012.md"

JUDGE_NAME = "_tools/qa/_check_vehicle_depreciation.py"
REVERSE_NAME = "_tools/qa/_reverse_verify_vehicle_depreciation.py"

#: Android DTO 上四格与折旧三格必须是这些 snake_case 键（少一个就是"页面上永远显示 0"）。
DTO_KEYS = (
    "purchase_price", "purchase_date", "useful_life_years", "residual_rate",
    "depreciation_covered", "depreciation_missing", "depreciation_monthly",
    "monthly_depreciation", "depreciation", "residual_rate_effective",
    "depreciation_total", "depreciation_uncovered_count", "delivery_cost_total", "total_cost",
)

#: 函数体下限（抽取失效比判据腐烂更危险）
DEP_FLOOR = 6000
COST_FLOOR = 3000
MIG_FLOOR = 600
QUERY_FLOOR = 900
COST_TAB_FLOOR = 1200
SCREEN_FLOOR = 4000
REVERSE_FLOOR = 3000


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit("找不到文件：" + str(p) + "（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


def py_code(src: str) -> str:
    """Python 侧剥掉模块 docstring 与整行注释 —— 「代码里不许有 X」不能被自己的说明弄红。"""
    q3 = chr(34) * 3
    src = re.sub("(?s)^" + re.escape(q3) + ".*?" + re.escape(q3), "", src, count=1)
    return re.sub("(?m)^[ 	]*#.*$", "", src)


def kt_code(p: Path) -> str:
    return strip_comments(read(p))


def esc(text: str) -> str:
    """把一段**原文**变成正则 —— 判据里凡"找这句话"都用它，别手写转义。"""
    return re.escape(text)


def literals(src: str) -> list[str]:
    """Kotlin 源码里双引号字面量的内容（只取同一行的；界面文案都在这类字面量里）。"""
    parts = src.split(chr(34))
    return parts[1::2]


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

    def need(self, label: str, text: str, needles: tuple) -> None:
        """一组「这句话还在不在」—— 与 present 同口径（都按正则），别一半正则一半子串。"""
        miss = [n for n in needles if not re.search(n, text)]
        self.ok(label, not miss, "缺：" + "、".join(miss))

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

def notes_block(src: str) -> str:
    """把 `_NOTES: tuple[str, ...] = (…)` 那一段原文抠出来（口径说明的正文）。"""
    i = src.find("_NOTES: tuple[str, ...] = (")
    if i < 0:
        return ""
    j = src.find(chr(10) + ")", i)
    return src[i:j if j > 0 else i + 4000]


def main() -> int:
    c = Checker()
    dep = read(DEP)
    dep_code = py_code(dep)
    cost_raw = read(COST)
    cost = py_code(cost_raw)
    mig = read(MIGRATION)
    boot = read(BOOT)
    model = read(MODEL)
    q = py_code(read(QUERY))
    q_raw = read(QUERY)
    sch = read(SCHEMA_R)
    api_v = py_code(read(API_V))
    api_r = py_code(read(API_R))
    api_r_raw = read(API_R)
    svc = read(SVC)
    pkg = read(PKG)
    dtos = kt_code(DTOS)
    apis = kt_code(APIS)
    repo = kt_code(REPO)
    center = kt_code(CENTER)
    vm = kt_code(VM)
    finance = kt_code(FINANCE)
    home = kt_code(HOME)
    routes = kt_code(ROUTES)
    nav = kt_code(NAV)
    vscreen = kt_code(VSCREEN)
    test_py = read(TEST_PY)
    test_py2 = read(TEST_PY2)
    test_kt = kt_code(TEST_KT)
    locator = read(DOC_LOCATOR)
    feat = read(FEAT_DOC)

    print("== 0. 反空转：口径文件 / 两张报表 / 两个页面 / 配套反验都在 ==")
    c.ok("折旧服务在且 ≥ " + str(DEP_FLOOR) + " 字符", len(dep) >= DEP_FLOOR, "只有 " + str(len(dep)) + " 字符")
    c.ok("车辆成本查询在且 ≥ " + str(COST_FLOOR) + " 字符", len(cost_raw) >= COST_FLOOR, "只有 " + str(len(cost_raw)) + " 字符")
    c.ok("迁移 018 在且 ≥ " + str(MIG_FLOOR) + " 字符", len(mig) >= MIG_FLOOR, "只有 " + str(len(mig)) + " 字符")
    fn = body(q, "def build_profit(")
    c.ok("利润查询 build_profit 在且 ≥ " + str(QUERY_FLOOR) + " 字符", len(fn) >= QUERY_FLOOR, "只有 " + str(len(fn)) + " 字符")
    tab = body(center, "private fun ProfitTab(", limit=12000)
    tab2 = body(center, "private fun VehicleCostTab(")
    c.ok("Android 车辆成本页在且 ≥ " + str(COST_TAB_FLOOR) + " 字符", len(tab2) >= COST_TAB_FLOOR, "只有 " + str(len(tab2)) + " 字符")
    c.ok("Android 车辆管理页在且 ≥ " + str(SCREEN_FLOOR) + " 字符", len(vscreen) >= SCREEN_FLOOR, "只有 " + str(len(vscreen)) + " 字符")
    rev = read(REVERSE)
    c.ok("配套反向验证在且 ≥ " + str(REVERSE_FLOOR) + " 字符", len(rev) >= REVERSE_FLOOR, "只有 " + str(len(rev)) + " 字符")
    c.present("配套反向验证拿着注入锁（lock_reverse_verify）", rev, esc("lock_reverse_verify"))

    print("")
    print("== 1. 折旧口径：月额 / 留空 = 0% / 按天摊 / 只四舍五入一次 / 提足之后是 0 ==")
    c.present("月折旧额 = 购置价 ×（1 − 残值率）÷（使用年限 × 12）",
              dep, esc("price * (Decimal(1) - residual_rate_of(residual_rate)) / (years * 12)"))
    c.present("缺格返回 None（⛔ 不拿 0 顶替）",
              body(dep, "def monthly_depreciation("), esc("return None"))
    c.present("残值率留空 = 0%（越界夹到 0–50%）",
              dep, "(?s)" + esc("if rate is None:") + ".{0,40}?" + esc("return RATE_MIN"))
    c.present("提足时点 = 购置日期 + 使用年限（整月走日历加法）",
              dep, esc("def depreciation_end(purchase_date: date, useful_life_years: Decimal) -> date:"))
    c.present("窗口内折旧按自然月的天数摊（不是整月一刀切）",
              dep, esc("total += monthly * Decimal(span) / Decimal(days)"))
    c.present("只在这一处四舍五入到分",
              body(dep, "def window_depreciation("), esc("return _money(total)"))
    c.present("参与计提的日子 = 窗口 ∩ [购置日期, 提足时点)",
              dep, esc("start = max(window_start, purchase_date)"))
    c.need("未覆盖原因三条常量（没录购置价 / 没录购置日期 / 没录使用年限）", dep, (
        esc(chr(34) + "没录购置价" + chr(34)), esc(chr(34) + "没录购置日期" + chr(34)),
        esc(chr(34) + "没录使用年限" + chr(34))))
    c.absent("折旧服务是纯函数：不 import sqlalchemy、也不碰 Session / commit()",
             dep_code, "(?i)sqlalchemy|session|" + esc("commit("))
    c.absent("折旧额不进库（源码里没有 depreciation_amount 之类的列）",
             model + mig + boot, esc("depreciation_amount") + "|" + esc("accumulated_depreciation") + "|" + esc("monthly_depreciation_amount"))
    c.present("summarize 逐车与合计出自同一次计算",
              dep, "(?s)" + esc("total = _money(sum(") + ".{0,600}?" + esc(chr(34) + "per_vehicle" + chr(34)))
    c.present("window_depreciation 收窗口两端（由调用方给，本文件不解析日期）",
              dep, "(?s)" + esc("def window_depreciation(") + ".{0,200}?" + esc("window_end: date,"))

    print("")
    print("== 2. 校验话术（唯一一份中文）：越界 400 ＋ 一句能照着改的话 ==")
    c.need("四格校验话术都在（购置价 / 日期 / 年限 / 残值率）", dep, (
        "购置价要大于 0 元", "购置日期不能晚于今天", "使用年限要在 0.5 到 30 年之间", "残值率要在 0% 到 50% 之间"))
    c.present("clean_fields 收 today（好测：日期上限与今天有关）",
              dep, "(?s)" + esc("def clean_fields(") + ".{0,300}?today")
    c.present("FIELD_KEYS 是四格的唯一清单",
              dep, esc(chr(34) + "purchase_price" + chr(34) + ", " + chr(34) + "purchase_date" + chr(34) + ", " + chr(34) + "useful_life_years" + chr(34) + ", " + chr(34) + "residual_rate" + chr(34)))
    c.present("审计只记真的变了的（清空也记）",
              dep, "(?s)" + esc("def field_lines(") + ".{0,900}?" + esc("（清空）"))
    c.present("接口层把越界翻译成 400 ＋ 那句中文（不是 500 / 不是英文）",
              api_v, "(?s)" + esc("except ValueError as exc:") + ".{0,80}?" + esc("HTTPException"))

    print("")
    print("== 3. 模型 / 迁移 018 / 运行时自愈三处逐列一致 ==")
    c.need("模型四列：Numeric(12,2) / Date / Numeric(4,1) / Numeric(5,4)，全可空", model, (
        esc("purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)"),
        esc("purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)"),
        esc("useful_life_years: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)"),
        esc("residual_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)")))
    c.need("迁移 018 声明四列（TABLE = vehicles / VERSION = 18）", mig, (
        esc("VERSION = 18"), esc(chr(34) + "vehicles" + chr(34)),
        esc(chr(34) + "purchase_price" + chr(34) + ": " + chr(34) + "purchase_price DECIMAL(12,2) NULL" + chr(34)),
        esc(chr(34) + "purchase_date" + chr(34) + ": " + chr(34) + "purchase_date DATE NULL" + chr(34)),
        esc(chr(34) + "useful_life_years" + chr(34) + ": " + chr(34) + "useful_life_years DECIMAL(4,1) NULL" + chr(34)),
        esc(chr(34) + "residual_rate" + chr(34) + ": " + chr(34) + "residual_rate DECIMAL(5,4) NULL" + chr(34))))
    c.need("迁移可重跑（逐列判存在性）", mig, (esc("for name, ddl in COLUMNS.items():"), esc("if name in have:")))
    c.need("schema_bootstrap 里是同一句 DDL 的自愈副本（四列）", boot, (
        esc("ALTER TABLE vehicles ADD COLUMN purchase_price DECIMAL(12,2) NULL"),
        esc("ALTER TABLE vehicles ADD COLUMN purchase_date DATE NULL"),
        esc("ALTER TABLE vehicles ADD COLUMN useful_life_years DECIMAL(4,1) NULL"),
        esc("ALTER TABLE vehicles ADD COLUMN residual_rate DECIMAL(5,4) NULL")))
    c.present("迁移文件头写明分工（正式变更走迁移、运行时自愈走 schema_bootstrap）",
              mig, esc("运行时自愈"))

    print("")
    print("== 4. 利润表：折旧独立减一项、未覆盖单列、口径说明改成「已经算进来了」 ==")
    c.need("折旧真的从营业利润里减掉（summarize 一次、只取 total）", q, (
        esc("dep = vdep.summarize(db.scalars(select(Vehicle)).all(), start, end)"),
        esc(chr(34) + "depreciation_total" + chr(34) + ": depreciation_total")))
    c.present("营业利润是五级相减（折旧独立一项，⛔ 不折进期间费用）",
              fn, esc("operating_profit = gross_profit - delivery_cost - expense_total - depreciation_total - tax_total"))
    c.need("返回值里有折旧五格", q, (
        esc(chr(34) + "depreciation_total" + chr(34)), esc(chr(34) + "depreciation_monthly_total" + chr(34)),
        esc(chr(34) + "depreciation_vehicle_count" + chr(34)), esc(chr(34) + "depreciation_uncovered_count" + chr(34)),
        esc(chr(34) + "depreciation_uncovered" + chr(34))))
    notes = notes_block(q_raw)
    c.present("口径说明第 2 条已改成「折旧已经算进来了」", notes, esc("车辆折旧已经算进来了"))
    c.absent("口径说明里不再说「折旧没有算进去」", q_raw, esc("折旧没有算进去"))
    c.present("导出里有「车辆折旧」这一行", api_r, esc(chr(34) + "车辆折旧" + chr(34)))
    c.present("导出里未覆盖的车单独列出来", api_r, esc(chr(34) + "折旧未覆盖的车" + chr(34)))
    c.need("schema 有 ProfitDepreciationUncovered 与折旧五格", sch, (
        esc("class ProfitDepreciationUncovered(BaseModel)"), esc("depreciation_uncovered_count: int = 0"),
        esc("depreciation_total: Decimal = Decimal(" + chr(34) + "0" + chr(34) + ")")))
    c.ok("利润表口径说明里不许出现 markdown 星号", chr(42) * 2 not in notes, "命中星号")

    print("")
    print("== 5. 车辆成本表：三笔成本、合计 = 逐车相加、⛔ 没有收入 ==")
    c.present("逐车成本 = 折旧 + 这台车的开销 + 配送成本",
              cost, esc(chr(34) + "total_cost" + chr(34) + ": depreciation + expense_total + delivery_cost"))
    c.present("合计 == 逐车相加",
              cost, esc(chr(34) + "total_cost" + chr(34) + ": depreciation_total + expense_total_all + delivery_total"))
    c.absent("这张表只算成本，⛔ 不拆收入（订单上没有「哪台车拉的」这个事实）",
             cost, "(?i)revenue|income")
    cost_notes = notes_block(cost_raw)
    c.ok("车辆成本表口径说明至少 5 条", cost_notes.count(chr(34)) >= 10, "实际 " + str(cost_notes.count(chr(34))) + " 个引号")
    c.ok("车辆成本表口径说明里不许出现 markdown 星号", chr(42) * 2 not in cost_notes, "命中星号")
    #: ⚠️ 2026-10-09 财务方向测试的 TB-03（CHG-0100）：口径说明第 3 条早就写了「只算挂靠司机」，
    #:    可「成本合计」那两行没带这个限定 —— 拿它跟利润表的「司机运费」对会差一大截。
    c.need("车辆成本表口径说明说清了「没挂车的司机去哪了」（TB-03）", cost_notes, (
        esc("没挂车的司机"), esc("司机运费")))
    c.present("端点 /reports/vehicle-cost 在（response_model 对上）",
              api_r, esc(chr(64) + "router.get(" + chr(34) + "/vehicle-cost" + chr(34) + ", response_model=VehicleCostReportOut)"))
    c.present("只读权限（与其它报表同一个权限）", api_r, esc("require_permission(Permission.ORDER_DISPATCH)"))
    c.present("取数走 build_vehicle_cost", api_r, esc("data = build_vehicle_cost(db, mode, anchor, span=span)"))
    c.present("导出 kind 正则收下了 vehicle-cost", api_r, esc("|vehicle-cost"))
    c.present("导出里那张表叫「车辆成本」", api_r, esc("next_sheet(" + chr(34) + "车辆成本" + chr(34) + ")"))
    c.ok("reports_service 转出了 build_vehicle_cost", "build_vehicle_cost" in svc and "vehicle_cost_query" in svc)
    c.ok("__init__ 的文件清单里有 vehicle_cost_query.py", "vehicle_cost_query.py" in pkg)

    print("")
    print("== 6. Android：第 8 格入口 / 利润链条那一行 / 车辆成本页 / 车辆管理四格 ==")
    c.need("DTO 有四格与折旧三格（snake_case 键）", dtos,
           tuple(esc(chr(64) + "SerialName(" + chr(34) + k + chr(34) + ")") for k in DTO_KEYS))
    c.present("接口有 reports/vehicle-cost", apis, esc(chr(64) + "GET(" + chr(34) + "reports/vehicle-cost" + chr(34) + ")"))
    c.present("仓库有 vehicleCostReport", repo, esc("vehicleCostReport("))
    c.present("入口页第 8 格是车辆成本", home, esc("EntryCard(" + chr(34) + "7" + chr(34) + ", " + chr(34) + "车辆成本" + chr(34)))
    c.present("exportKind(7) = vehicle-cost", finance, esc("7 -> " + chr(34) + "vehicle-cost" + chr(34)))
    c.need("路由常量与 NavGraph 都认第 8 格", routes + nav, (
        esc("const val REPORT_VEHICLE_COST = " + chr(34) + "report/vehicle-cost" + chr(34)),
        esc("7 -> navController.navigate(Routes.REPORT_VEHICLE_COST)"), esc("initialTab = 7")))
    # ⚠️ 上界 2026-10-04 从 7 抬到 8（FEAT-0013 加了第 9 格），2026-10-05 又抬到 9（FEAT-0014 加了第 10
    #    格「税账」）、再抬到 10（FEAT-0015 加了第 11 格「客户欠款」）—— 这里钉的仍是「第 8 格进得来」，
    #    所以只改数字，不改判据的意思。
    c.need("ViewModel 收下页签 0..10 且拉了 vehicleCost", vm, (
        esc("initialTab.coerceIn(0, 10)"), esc("vehicleCost = container.repo.vehicleCostReport(")))
    c.present("利润构成链条里有「− 车辆折旧」这一行（在期间费用与税金之间）",
              tab, "(?s)" + esc(chr(34) + "− 期间费用" + chr(34)) + ".{0,600}?" + esc(chr(34) + "− 车辆折旧" + chr(34))
              + ".{0,600}?" + esc(chr(34) + "− 税金及附加" + chr(34)))
    c.present("利润页有「折旧未覆盖的车」卡", tab, esc(chr(34) + "折旧未覆盖的车" + chr(34)))
    c.present("车辆成本页三笔成本全取自接口（客户端不做减法）",
              tab2, "(?s)" + esc(chr(34) + "车辆折旧" + chr(34)) + ".{0,3000}?" + esc(chr(34) + "这台车的开销" + chr(34))
              + ".{0,3000}?" + esc(chr(34) + "配送成本（司机应得）" + chr(34)))
    c.absent("车辆成本页自己不做减法（money(...) 里不许出现算术）",
             tab2, esc("money(") + "[^()]*[-+][^()]*" + esc(")"))
    #: ⚠️ TB-03：这两条只钉「说清楚了」，不钉任何金额 —— 改的是标签那几行字，数一个都没动。
    c.present("车辆成本页把「配送成本只算挂靠司机」写在成本合计旁边（TB-03）",
              tab2, esc("配送成本只算挂在这台车上的司机"))
    c.ok("两处「= 成本合计」都带上了限定（只含挂靠司机）（TB-03）",
         tab2.count("（只含挂靠司机）") == 2, "实际 " + str(tab2.count("（只含挂靠司机）")) + " 处")
    c.need("车辆管理页四格：四个输入行都在", vscreen, (
        esc("label = " + chr(34) + "购置价(元)" + chr(34) + ","), esc("label = " + chr(34) + "购置日期" + chr(34) + ","),
        esc("label = " + chr(34) + "使用年限(年)" + chr(34) + ","), esc("label = " + chr(34) + "残值率" + chr(34) + ",")))
    c.need("车辆管理页显示折旧（算不出来就说缺哪一格，⛔ 不写 ¥0）", vscreen, (
        esc("internal fun depreciationLine("), esc(chr(34) + "折旧未覆盖：" + chr(34)), esc("internal fun rateText("),
        esc("每月折旧 ¥")))
    c.absent("车辆管理页的 OutlinedTextField 必须是 0（全局规范：分组白卡 + 不描边的行）",
             vscreen, "OutlinedTextField")
    bad_lits = [s for s in literals(vscreen) + literals(tab2) if chr(42) * 2 in s]
    c.ok("界面文字里不许出现 markdown 星号（手机会原样显示）", not bad_lits, "命中：" + repr(bad_lits[:3]))

    print("")
    print("== 7. 用例与文档 ==")
    names = re.findall("def (test_[A-Za-z0-9_]+)" + esc("("), test_py)
    c.ok("后端折旧单测至少 28 条（纯函数 20 + 接口 8）", len(names) >= 28, "实际 " + str(len(names)) + " 条")
    c.ok("其中有一条把模型 / 迁移 / 自愈三处逐列对了一遍",
         "test_columns_match_model_migration_and_bootstrap" in names, "现有：" + "、".join(names[:6]) + " …")
    c.ok("其中有一条钉「折旧永不落库」", "test_depreciation_is_never_stored" in names, "现有：" + "、".join(names[:6]) + " …")
    c.ok("其中有一条钉纯函数（源码里不许有 sqlalchemy / Session）",
         "test_module_is_pure_no_db" in names, "现有：" + "、".join(names[:6]) + " …")
    names2 = re.findall("def (test_[^(]+)" + esc("("), test_py2)
    c.ok("后端车辆成本单测至少 7 条", len(names2) >= 7, "实际 " + str(len(names2)) + " 条")
    c.ok("其中有一条钉「配送成本与运费结算同源」",
         any("运费结算同源" in n for n in names2), "现有：" + "、".join(names2))
    c.need("Android 单测钉了折旧显示口径（¥0 与未覆盖是两件事）", test_kt, (
        esc("折旧未覆盖："), esc("rateText("), esc(chr(34) + "5%" + chr(34))))
    c.ok("定位表里指路了本判据与它的反向验证",
         JUDGE_NAME.split("/")[-1] in locator and REVERSE_NAME.split("/")[-1] in locator,
         "缺：" + "、".join([n for n in (JUDGE_NAME, REVERSE_NAME) if n.split("/")[-1] not in locator]))
    c.ok("FEAT-0012.md 在且写了折旧（这一期的口径落点）", "折旧" in feat and "车辆成本" in feat)
    pj = read(PROFIT_JUDGE)
    pr = read(PROFIT_REVERSE)
    c.ok("经营利润那条红线同步了折旧项（五级恒等式）", "depreciation_total - tax_total" in pj)
    c.ok("它的反验也同步了 notes 文本锚点", "车辆折旧已经算进来了" in pr)

    return c.report("车辆台账与折旧：录购置信息、按月直线法现算、缺格单列（FEAT-0012）")


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("车辆台账与折旧（FEAT-0012）红线：月额公式 / 留空 = 0% / 按自然月天数摊 / 提足之后是 0 /")
        print("校验话术唯一一份中文 / 模型与迁移与自愈三处逐列一致 / 利润表五级相减与未覆盖单列 /")
        print("车辆成本表三笔成本与恒等式（⛔ 没有收入）/ Android 第 8 格与四格 / 用例与文档")
        raise SystemExit(0)
    raise SystemExit(main())

