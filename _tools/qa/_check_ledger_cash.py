"""红线：账本管理的「收支」页（2026-09-22 用户要求）——**收入按来源、支出按去路**。

## 用户原话
> 「在**账本管理新建一个区域，这个区域就是支出和收入**……我记得好像有个**开销管理**吧，
> 干脆把我们两个**整合在一起**。**收入**也要**跟现在的系统做一个合并**，但**具体的收入来源
> 要明细一下**……**所有能力功能全部开放给 AI，并且给 AI 做一个后路**。」

## 这一页最容易悄悄坏掉的六件事（每条都有判据）
1. **金额跑到客户端算**：这一页的收入/支出分项必须来自 `GET /cash-flows/breakdown`
   （后端 SQL 侧 `SUM`、与 `/summary` 共用 `_scoped_stmt`）。客户端按 `biz_type` 自己分类求和
   会同时踩"列表被截断"（实测少算 62%，2026-09-19 审计定案）与"分类口径走散"两个坑。
2. **中文名抄第二份**：只有 `ReportFinance.bizLabel()` 一份（后端只给 `RECEIPT_CASH` 这种枚举名）。
3. **方向大小写不归一**：老数据里存过大写 `IN` —— 归一漏一处，那笔钱会从收入里消失、跑到支出里。
4. **「开销管理」被顺手弄丢**：它不再并列占一格，但**必须还进得去**（支出卡底部那个入口 +
   路由 + NavGraph 注册三样都要在）。这一条是用户那句"整合"的全部风险所在。
5. **明细页自己挑时间**：窗口必须由总览页带过来，否则"这一路合计"与"明细加起来"对不上。
6. **AI 读不到**：新增的读端点必须进 toolmap → 读目录（`AiReadCatalog`）→ 中文说明，
   否则用户问"这段时间钱都花哪了"，模型只会如实回一句"我查不了"。

用法：python _tools/qa/_check_ledger_cash.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_pagination_wiring import strip_comments  # noqa: E402

ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
BACKEND = ROOT / "backend/app/api/v1/cash_flows.py"
TEST = ROOT / "backend/tests/test_cash_flow_breakdown.py"
SCREEN = ANDROID / "ui/dispatcher/LedgerCashScreen.kt"
DETAIL = ANDROID / "ui/dispatcher/LedgerCashDetailScreen.kt"
ROUTES = ANDROID / "ui/nav/Routes.kt"
NAV = ANDROID / "ui/nav/NavGraph.kt"
MODULES = ANDROID / "ui/nav/Modules.kt"
COLOR = ANDROID / "ui/theme/Color.kt"
APIS = ANDROID / "data/remote/api/Apis.kt"
REPO = ANDROID / "data/repo/AppRepository.kt"
DTO = ANDROID / "data/remote/dto/Dtos.kt"
CATALOG = ANDROID / "ai/AiReadCatalog.kt"
GENCAT = ROOT / "_tools/ai/_gen_ai_read_catalog.py"
TOOLMAP = ROOT / "docs/ai/ai_toolmap.json"
ENDPOINTS = ROOT / "docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class Checker:
    def __init__(self) -> None:
        self.passes = 0
        self.fails: list[str] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text) is not None, f"没找到 /{pattern}/")

    def absent(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text) is None, f"不该出现 /{pattern}/ 却出现了")


def main() -> int:
    c = Checker()
    for p in (BACKEND, TEST, SCREEN, DETAIL, ROUTES, NAV, MODULES, COLOR, APIS, REPO, DTO,
              CATALOG, GENCAT, TOOLMAP, ENDPOINTS, DESIGN, LOCATOR):
        if not p.exists():
            print(f"❌ 文件不存在：{p}")
            return 1

    api = strip_comments(read(BACKEND))
    screen = strip_comments(read(SCREEN))
    detail = strip_comments(read(DETAIL))
    routes = strip_comments(read(ROUTES))
    nav = strip_comments(read(NAV))
    modules = strip_comments(read(MODULES))
    color = strip_comments(read(COLOR))
    test = read(TEST)

    # ---- ① 后端：分组求和只在 SQL 侧，且与汇总共用同一套筛选 ----
    #
    # ⚠️ 这一段**必须只看新 handler 的函数体**：这个文件里 `/summary` 早就有两处
    #    `func.lower(scoped.c.direction)` 与一处 `仅派单员可查看` —— 在全文件上数它们，
    #    判据会一直绿（写这条检查时我自己就踩了一次：改成 `scoped.c.direction`
    #    它也照样通过）。反向验证里专门有一条注入打这个。
    rest = api[api.index("def cash_flow_breakdown("):]
    cut = re.search(r"\n(?=[A-Za-z@])", rest)
    handler = rest[: cut.start()] if cut else rest
    c.ok("取到新 handler 的函数体（取不到这条检查就是空转）", len(handler) > 400)
    c.present("路径就是 /breakdown（不与 summary 抢同一个路由）",
              api, r'@router\.get\("/breakdown"\)\s*\ndef cash_flow_breakdown\(')
    c.present("筛选复用 _scoped_stmt（⛔ 不抄第二份判据）",
              handler, r"scoped = _scoped_stmt\(current, None, None, None, None, date_from, date_to\)\.subquery\(\)")
    c.present("求和是 SQL 侧 coalesce(sum(...))",
              handler, r"func\.coalesce\(func\.sum\(scoped\.c\.amount\), 0\)")
    c.ok("分组键把 direction 归一小写（select 里那一处 + 分组用它）",
         len(re.findall(r"func\.lower\(scoped\.c\.direction\)", handler)) == 1
         and ".group_by(dir_col" in handler,
         "少了归一，老数据里那个大写 IN 会自成一组、还会被判成支出")
    c.present("只有 in 算收入，其余归支出一侧", handler, r'== "in" else expense')
    c.present("守门条件就是 dispatcher（⛔ 不是一句空话）",
              handler,
              r'if user_role_key\(current\) != UserRole\.DISPATCHER\.value:\s*\n\s*'
              r'raise HTTPException\(status_code=403, detail="仅派单员可查看"\)')
    c.ok("三个端点都守了门（只有派单员能看：全公司成本不从这一页漏出去）",
         len(re.findall(r"仅派单员可查看", api)) == 3,
         f"实际出现 {len(re.findall(r'仅派单员可查看', api))} 次")
    c.present("空/NULL 的 biz_type 不并进「其他」（账上出现没见过的东西要看得见）",
              handler, r'"biz_type": str\(biz_type or ""\)')

    # ---- ② 后端测试：分项之和 == 汇总（两条独立路径必须同一个数）----
    c.present("有回归测试文件，且钉住「分项之和 == 汇总」",
              test, r'Decimal\(b\["income_total"\]\) == Decimal\(s\["income"\]\)')
    c.present("笔数也要对得上（漏一路就红）", test, r'b\["count"\] == s\["count"\]')
    c.present("钉住「方向存成大写也算收入不算支出」", test, r'_mk_flow\(db_session, "IN"')
    c.present("钉住「货主看不了」", test, r'test_货主看不了[\s\S]{0,200}?status_code == 403')

    # ---- ③ 安卓数据层：唯一一条取数路 ----
    c.present("Apis 里有 breakdown 端点", read(APIS), r'@GET\("cash-flows/breakdown"\)')
    c.present("Repository 透出 cashFlowBreakdown", read(REPO), r"suspend fun cashFlowBreakdown\(")
    c.present("DTO 有 CashFlowBreakdownDto", read(DTO), r"data class CashFlowBreakdownDto\(")
    c.present("总览页走 repo.cashFlowBreakdown", screen, r"container\.repo\.cashFlowBreakdown\(")

    # ---- ④ 金额一律服务端算：客户端不许自己分类求和 ----
    c.absent("总览页不许对分项自己求和（sumOf/sumBy）", screen, r"\.sumOf\s*\{|\.sumBy\s*\{")
    c.absent("总览页不许把金额转 Double 自己算", screen, r"toDoubleOrNull\(\)|moneyToDouble\(")
    c.present("净额/收入合计/支出合计三个数都取服务端那三个字段",
              screen, r'formatMoney\(d\.net\)[\s\S]{0,900}?formatMoney\(d\.incomeTotal\)[\s\S]{0,900}?formatMoney\(d\.expenseTotal\)')

    # ---- ⑤ 中文名只有一份 ----
    c.present("总览页用 ReportFinance.bizLabel 翻中文", screen, r"ReportFinance\.bizLabel\(")
    c.present("明细页也用同一份", detail, r"ReportFinance\.bizLabel\(")
    c.absent("总览页没有自己再写一份 biz_type → 中文 的词表",
             screen, r'"RECEIPT_CASH"|"EXPENSE_FUEL"|"PAYMENT_DRIVER"')
    c.absent("明细页也没有第二份词表", detail, r'"RECEIPT_CASH"|"EXPENSE_FUEL"|"PAYMENT_DRIVER"')

    # ---- ⑥ 两组合用一份实现（收入/支出不许各写一张卡）----
    n_group = len(re.findall(r"CashGroupCard\(", screen))
    c.ok(f"收入/支出两组共用一份实现（定义 1 + 调用 2，实测 {n_group}）", n_group == 3,
         f"实际 {n_group}（抄成两份的话，两边会慢慢长得不一样）")
    c.present("「收入」那一组接的是收入侧数据", screen, r'title = "收入"')
    c.present("「支出」那一组接的是支出侧数据", screen, r'title = "支出"')
    c.ok("两组各自点得进明细（in / out 两条路都在）",
         re.search(r'onOpenDetail\("in", it\.bizType', screen) is not None
         and re.search(r'onOpenDetail\("out", it\.bizType', screen) is not None,
         "少了任何一条，那一边就只能看合计")

    # ---- ⑦ 「开销管理」没有被弄丢（用户那句"整合"的全部风险）----
    c.present("支出那张卡底部有「开销管理」入口", screen, r'Text\("开销管理"')
    c.present("那个入口真的接了回调（不是画着好看）", screen, r"footer = \{[\s\S]{0,400}?onClick = onOpenExpenses")
    c.present("路由常量还在", routes, r'const val DISPATCH_EXPENSES = "dispatcher/expenses"')
    c.present("NavGraph 里还注册着开销管理页", nav, r"composable\(Routes\.DISPATCH_EXPENSES\)")
    c.present("收支页把「去开销管理」接到了那条路由上",
              nav, r"onOpenExpenses = \{ navController\.navigate\(Routes\.DISPATCH_EXPENSES\) \}")
    c.present("入口页那一格不再叫「开销管理」（并进「收支」了）",
              modules, r'ModuleEntry\("收支", Routes\.DISPATCH_CASH')
    c.absent("入口页 6 格里没有第二个「开销管理」格", modules, r'ModuleEntry\("开销管理"')

    # ---- ⑧ 路由 / 明细页 ----
    c.present("收支页路由常量存在", routes, r'const val DISPATCH_CASH = "dispatcher/cash"')
    c.present("明细页路由常量存在", routes, r'const val DISPATCH_CASH_DETAIL = "dispatcher/cash/detail"')
    c.present("收支页在 NavGraph 注册了", nav, r"composable\(Routes\.DISPATCH_CASH\)")
    c.present("明细页在 NavGraph 注册了（带四个查询参数）",
              nav, r'Routes\.DISPATCH_CASH_DETAIL \+ "\?direction=\{direction\}&biz=\{biz\}&from=\{from\}&to=\{to\}"')
    c.present("明细页从参数里取窗口（窗口由总览页带过来）",
              nav, r'dateFrom = entry\.arguments\?\.getString\("from"\)')
    c.absent("明细页**不许**自己再挑一次时间（挑了就会与刚才那一路的合计对不上）",
             detail, r"DatePresetPill\(|DatePresets\.pickWindow\(|DatePresets\.rangeOf\(")
    c.present("明细页把条数上限说出来（截断了不许装没截断）", detail, r"TruncationNote\(")
    c.present("明细页按 order_id 点得进订单详情", detail, r"f\.orderId\?\.let\(onOpenOrder\)")

    # ---- ⑨ 收支两组的语义色：一份定义，两个页面共用 ----
    c.present("收支语义色定义在主题里（唯一一份）", color, r"val CashIn = MgrGreen")
    c.present("支出那一档接着原「开销管理」的蓝", color, r"val CashOut = 0xFF1565C0L")
    c.present("总览页用 CashIn/CashOut", screen, r"Color\(CashIn\)[\s\S]{0,4000}?Color\(CashOut\)")
    c.absent("总览页里没有第二份硬编码的收支色", screen, r"0xFF1565C0L|0xFF00B578L")

    # ---- ⑩ 时间控件与"先盘点再取数"（与账本/开销两页同一条规矩）----
    c.present("时间是顶栏一个紧凑药丸", screen, r"DatePresetPill\(")
    c.absent("不铺那一行日期胶囊", screen, r"DatePresetRow\(")
    c.present("药丸点开走共用的 DateFilterDialogs", screen, r"DateFilterDialogs\(")
    c.present("窗口没定下来时整页 loading（不许闪两下）", screen, r"!vm\.windowSettled -> LoadingBox\(\)")
    c.present("自动退档走共用的阶梯", screen, r"DatePresets\.pickWindow\(DatePresets\.AUTO_LADDER\)")
    c.present("用户自己挑过档位后不再自动改", screen, r"userPickedPreset = true")
    vm_before_init = re.search(r"var windowSettled[\s\S]*?\n    init \{", screen)
    c.ok("VM 里 windowSettled 声明在 init 之前（写在后面＝打开这一页必崩）",
         vm_before_init is not None, "见 _check_vm_state_before_init.py")

    # ---- ⑪ AI 后路：新读端点必须被模型看得到 ----
    c.present("toolmap 里有这个读动作", read(TOOLMAP), r'"action": "cash_flow_breakdown"')
    c.present("中文说明写进生成器（模型选工具靠它）",
              read(GENCAT), r'"cash_flows\.cash_flow_breakdown": "收支分项')
    c.present("读目录里有它（App 侧的工具清单）",
              read(CATALOG), r'ReadAction\("cash_flows\.cash_flow_breakdown"')
    c.present("读目录里的角色是派单员（与后端 403 一致）",
              read(CATALOG), r'ReadAction\("cash_flows\.cash_flow_breakdown"[\s\S]{0,200}?setOf\("dispatcher"\)')
    c.present("端点索引里有它（文档不许过期）",
              read(ENDPOINTS), r"GET /api/v1/cash-flows/breakdown")

    # ---- ⑫ 文档指针 ----
    c.ok("设计规范里写了收支那一条规矩",
         re.search(r"收支", read(DESIGN)) is not None
         and "_check_ledger_cash.py" in read(DESIGN),
         "缺一条：账本管理「收支」的规矩 + 指路到本判据")
    loc = read(LOCATOR)
    c.ok("定位表里指到了收支（并点名本判据）",
         "收支" in loc and "_check_ledger_cash.py" in loc,
         "改这一页的人应当能从定位表找到本文件")

    total = c.passes + len(c.fails)
    if total < 40:
        print(f"❌ 只跑了 {total} 项（<40）—— 判据在空转，停。")
        return 1
    if c.fails:
        print(f"❌ 收支页红线不通过（{c.passes}/{total}）：")
        for f in c.fails:
            # ⚠️ `[FAIL]` 这个标记是**反向验证脚本认的**（它按它筛"哪一条红了"）——
            #    改成本仓库别的写法会让 `_reverse_verify_ledger_cash.py` 全部报 MISS。
            print("   [FAIL] " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：收支=一路一行、金额只在服务端算、开销管理还进得去、AI 读得到。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
