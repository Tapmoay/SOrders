# -*- coding: utf-8 -*-
"""红线：固定工资司机也有「我的账本」＝工资那一半，以及派单员的核销（CHG-0127）。

## 由来（用户 2026-10-15 口述，m43131）
「我们的大车司机也就是固定工资的司机不是没有我的账本吗，我们加一个我的账本啊，这个我的账本
就是**统计他的工资**的……如果在任职期间他的固定工资发生了改变，我们也同样也是有记录的，也会有
个统计；当然，如果……已经核销了……表示已核销，就是**重新计算那个没有核销的工资**……同时，我们
那个派单员可以在司机账本这里啊，对他的工资进行核销」。

## 为什么必须有一条红线盯着它
这一项把**两本账**放进了同一个页面（运费 / 工资），而这两本账的钱来自两个不同的后端口径。
最容易悄悄退回原样的五处，**没有一处会报错**：

* **按单的钱混进工资合计**：工资合计多出一笔运费，界面上只是一个偏大的数，对账时才会发现；
* **已核销的被重算**（最贵的一种）：被草稿结算单锁住的单状态**还是 open**（只写了
  `settled_doc_id`），只看状态就会把它当「未核销」重算，而那张草稿单的金额是按旧数定死的 ——
  结出来的账两边都对不上；
* **入口又按老裁决关掉**：2026-09-20 用户说过「固定工资的司机不需要我的账本」，2026-10-15 他
  自己改了这条 —— 只按 `pays_per_order` 判入口的话，固定工资司机的账在 App 里彻底看不见
  （而 `GET /freight-settlement` 其实一条不少）；
* **金额渲染漏进纯逻辑文件**：`ui/driver/` 下只有 `DriverFreightScreen.kt` 一个文件能画钱
  （`_tools/qa/_check_driver_money.py` 第 8 节按目录自己算），在 `DriverSalary.kt` 里写一句
  `formatMoney` 就把那条判据打红了 —— 而它守的是「司机端金额不外泄」；
* **刷新不重算 / 重算不留痕**：改了一张**已经存在**的单的金额，却只在界面上说一句「已重算」，
  巡检就再也查不出这笔钱是什么时候、被谁改的。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。被查的全是「哪个数算进哪本账 / 谁还能改这张单」：
刷新条件里少写 `settled_doc_id is None`、`refresh_unsettled` 缺省改成 True、金额没变也写一遍、
把两条分支的返回合成一个、工资合计从 `salaryBillsOf(bills)` 退成 `bills`、入口表达式少一个字段、
在纯逻辑文件里写金额 —— 这七处没有一处会编译失败，也没有一处会让别的判据变红（后端那半只有一份
真跑钱的集成测试兜着，App 这半只有这里）。边界那一半已经先做了（判据收进
`driver_bills._is_open_unlocked` 一个函数、分账收进 `DriverSalary.kt` 六个纯函数、后端口径收在
`driver_pay.monthly_salary_of` 一处），但「有没有调它」「谁先谁后」只存在于**调用点**，
所以判据只能扫结构 + 扫顺序。运行时那一头交给
_tools/qa/_reverse_verify_driver_salary_ledger.py（逐条注入破坏）。

## 判据（清单全部自己算；路径写错会先在「关键文件都在」那条报红）
1. 刷新的判据只有一处（`_is_open_unlocked`），两个条件都在。
2. 缺省 False；金额没变一个字不写；**先记旧数再改**（审计要拿得到「改之前是多少」）。
3. 两条分支的返回各归各的：SALARY 回「新建的 + 刷新的」，PIECE 只回新建的。
4. 刷新留痕（refreshed_count / refreshed_total / refresh_unsettled）＋回给调用方的是真动过的那张。
5. App 侧六个纯函数各一处；这个文件一个字金额都不画；`ui/driver` 下画钱的文件只有运费那一页。
6. 司机端两半页并存：运费那半页取数与文案一字没动（别人判据钉着的两行还在）。
7. 派单端：生成带 refresh_unsettled；核销＝建单 + confirm；作废 / 付款走现成动作。
8. 入口闸门三个字段**并列**在同一个表达式里（不许抽成辅助函数）。
9. 路由 / NavGraph / 运费结算页那个出口都在，且出口行不写金额。
10. 单测、变更单、反向验证脚本都在，且条数对得上。
11. 结算单那一行数的是**被它锁住的工资单**张数（工资结算单没有订单，数 order_ids 必然是 0）。

⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：
   python _tools/qa/_reverse_verify_driver_salary_ledger.py（12 种破坏方式全被抓）

用法：python _tools/qa/_check_driver_salary_ledger.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 失败行 / 章节标题的形状只此一份（房规）：失败行是 "  [!!]   <标题>" ——
#: _reverse_verify_*.py 正是拿这个前缀去认「这一条被判据抓住了」。
#: 剥 Kotlin 注释的实现也只此一份（**保留字符串字面量**）。
from _check_hints import Checker, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
DRIVER = ANDROID / "ui/driver"
DISPATCH = ANDROID / "ui/dispatcher"
NAV = ANDROID / "ui/nav"

SALARY = DRIVER / "DriverSalary.kt"
FREIGHT_SCREEN = DRIVER / "DriverFreightScreen.kt"
FREIGHT_VM = DRIVER / "DriverFreightViewModel.kt"
SALARY_SCREEN = DISPATCH / "DriverSalaryScreen.kt"
FREIGHT_SETTLE = DISPATCH / "FreightSettlementScreen.kt"
PROFILE = ANDROID / "ui/profile/ProfileScreen.kt"
ROUTES = NAV / "Routes.kt"
NAVGRAPH = NAV / "NavGraph.kt"
DTOS = ANDROID / "data/remote/dto/Dtos.kt"

BE_BILLS = ROOT / "backend/app/api/v1/driver_bills.py"
BE_SCHEMA = ROOT / "backend/app/schemas/accounting_v2.py"
BE_USER_SCHEMA = ROOT / "backend/app/schemas/user.py"
BE_USERS = ROOT / "backend/app/api/v1/users.py"
BE_TEST = ROOT / "backend/tests/test_driver_billing_api.py"

KTEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/driver/DriverSalaryTest.kt"
CHG = ROOT / "docs/changes/CHG-0127.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_driver_salary_ledger.py"

REQUIRED = [SALARY, FREIGHT_SCREEN, FREIGHT_VM, SALARY_SCREEN, FREIGHT_SETTLE, PROFILE, ROUTES,
            NAVGRAPH, DTOS, BE_BILLS, BE_SCHEMA, BE_USER_SCHEMA, BE_USERS, BE_TEST, KTEST, CHG]

#: 反空转下限：.kt 扫不到东西时下面每一条都会「找不到就空过」。
MIN_KT = 340

#: 后端那两行就是「未核销」的判据（少一个都会把已经对过的账改掉）。
UNLOCK_HALF_A = 'if str(getattr(status, "value", status) or "") != DriverBillStatus.OPEN.value:'
UNLOCK_HALF_B = '    return getattr(bill, "settled_doc_id", None) is None'
REFRESH_GATE = 'if body.refresh_unsettled and _is_open_unlocked(exists) and exists.amount != sal:'
OLD_AMOUNT_FIRST = 'refreshed.append((exists, exists.amount))'
REFRESH_TOTAL = '"refreshed_total": str(sum((b.amount for b, _ in refreshed), Decimal("0"))),'

#: App 侧：入口那三个字段（判据按字面找子串，⛔ 不许抽成辅助函数）。
GATE_FIELDS = ('vm.user?.paysPerOrder == true',
               'vm.user?.hasPerOrderEarnings == true',
               'vm.user?.hasSalary == true')
#: 入口那三条件必须**并列在同一个表达式里**（⛔ 不许抽成 driverHasLedger(vm.user) 之类的
#: 辅助函数）。缩进不写死（源码里那段是两层括号的续行），但三个字段的顺序与连接词钉死。
GATE_RE = re.compile(
    r"\(vm\.user\?\.paysPerOrder == true \|\| vm\.user\?\.hasPerOrderEarnings == true \|\|"
    r"\s+vm\.user\?\.hasSalary == true\)"
)

#: 运费那半页的取数口径（别人判据 _check_driver_money.py 逐字钉着这两行）。
FREIGHT_PINS = ('"\u00a5" + formatMoney(vm.total().toString())',
                '"\u00a5" + formatMoney(e.payTotal)')

#: 出口行不许写金额（它指的另一本账）。
ROW_DEF = 'private fun SalarySheetsRow(onOpen: () -> Unit)'

C = Checker()


def ok(label: str, cond: bool, detail: str = "") -> None:
    C.ok(label, cond, detail)


def section(title: str) -> None:
    C.section(title)


def raw(path: Path) -> str:
    """整份源码（**带注释**：KDoc 里还写着旧理由也算没改干净）。"""
    if not path.is_file():
        return ""
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        return fh.read().replace("\r\n", "\n")


def kt(path: Path) -> str:
    """Kotlin 文件：注释已剥（注释里写「三个字段都在」是不算数的）。"""
    return strip_comments(raw(path)) if path.is_file() else ""


def finish() -> int:
    print("\n" + "=" * 60)
    total = C.n_ok + len(C.fails)
    if C.fails:
        print("❌ %d 项不通过（通过 %d 项）：" % (len(C.fails), C.n_ok))
        for label, _ in C.fails:
            print("   - " + label)
        print("_check_driver_salary_ledger: %d/%d 通过" % (C.n_ok, total))
        return 1
    print("✅ 全部 %d 项通过：固定工资司机的工资账只算工资、未核销的跟着新工资走、已核销的一分不动。" % C.n_ok)
    print("_check_driver_salary_ledger: %d/%d 通过" % (C.n_ok, total))
    return 0


def before(text: str, a: str, b: str) -> bool:
    """a 在 b 前面 —— 两段都得只出现一次才算数（找不到 / 出现两次都当没守住）。"""
    return text.count(a) == 1 and text.count(b) == 1 and text.index(a) < text.index(b)


def main() -> int:
    # ── §0 反空转：文件在不在、是不是空壳 ─────────────────────────────
    section("§0 反空转（关键文件都在 + 不是空壳）")
    missing = [p for p in REQUIRED if not p.is_file()]
    ok("16 份关键文件都在", not missing, "缺：" + "、".join(str(p.relative_to(ROOT)) for p in missing))
    if missing:
        return finish()
    sizes = {p.name: len(raw(p)) for p in (SALARY, FREIGHT_SCREEN, SALARY_SCREEN, BE_BILLS, BE_TEST)}
    ok("DriverSalary.kt 不是空壳（> 3000 字符）", sizes["DriverSalary.kt"] > 3000, "%d 字符" % sizes["DriverSalary.kt"])
    ok("DriverFreightScreen.kt 够大（> 15000 字符）", sizes["DriverFreightScreen.kt"] > 15000, "%d" % sizes["DriverFreightScreen.kt"])
    ok("DriverSalaryScreen.kt 够大（> 15000 字符）", sizes["DriverSalaryScreen.kt"] > 15000, "%d" % sizes["DriverSalaryScreen.kt"])
    ok("driver_bills.py 够大（> 12000 字符）", sizes["driver_bills.py"] > 12000, "%d" % sizes["driver_bills.py"])
    ok("后端那份测试够大（> 30000 字符）", sizes["test_driver_billing_api.py"] > 30000, "%d" % sizes["test_driver_billing_api.py"])
    n_kt = len(list(ANDROID.rglob("*.kt")))
    ok(".kt 扫得到（>= %d 个）" % MIN_KT, n_kt >= MIN_KT, "扫到 %d 个" % n_kt)
    ok("反向验证脚本在（改坏 → 本脚本必须红）", REVERSE.is_file())

    # ── §① 后端：只动未核销的，且留痕 ───────────────────────────────
    section("§① 后端（driver_bills / schemas / users）")
    be = raw(BE_BILLS)
    ok("「未核销」的判据收在一个函数里", "def _is_open_unlocked(bill: DriverBill) -> bool:" in be)
    ok("判据 A：状态必须还是 open（比的是枚举的 .value）", UNLOCK_HALF_A in be)
    ok("判据 B：还得没被任何结算单锁住（settled_doc_id is None）", UNLOCK_HALF_B in be)
    ok("刷新门三个条件合在一行（开关 + 未核销 + 金额真的变了）", REFRESH_GATE in be)
    ok("先记旧数再改（审计要拿得到「改之前是多少」）", before(be, OLD_AMOUNT_FIRST, "exists.amount = sal"))
    four = ["exists.amount = sal", "exists.note = note",
            "exists.rule_id = dr.id if dr is not None else None",
            'exists.rule_name = (dr.name or "") if dr is not None else ""']
    ok("四个字段一起改（金额 / 说明 / 规则 id / 规则名）", all(f in be for f in four), "、".join(f for f in four if f not in be))
    ok("refreshed 与 created 各记各的", "refreshed = []" in be and "created = []" in be)
    ok("账本留痕：created or refreshed 时才写日志", "if created or refreshed:" in be)
    ok("留痕三个字段齐全（refreshed_count / refreshed_total / refresh_unsettled）",
       all(f in be for f in ('"refreshed_count"', REFRESH_TOTAL, '"refresh_unsettled"')))
    ok("SALARY 分支把「新建的 + 刷新的」都回给调用方", "return created + [b for b, _ in refreshed]" in be)
    ok("PIECE 分支不受影响（return created 仍恰好 2 处）", be.count("return created") == 2, "%d 处" % be.count("return created"))
    ok("刷新只开了一个口子（body.refresh_unsettled 只出现一次）", be.count("body.refresh_unsettled") == 1, "%d 处" % be.count("body.refresh_unsettled"))
    ok("开关缺省 False（不传就是老行为，一个字节都不改）", "refresh_unsettled: bool = False" in raw(BE_SCHEMA))
    ok("司机有没有月薪由后端算（has_salary，与按单那两个字段并列）", "has_salary: bool | None = None" in raw(BE_USER_SCHEMA))
    ok("口径走 monthly_salary_of 一处（没挂规则的固定工资司机也认）", "out.has_salary = monthly_salary_of(current) > 0" in raw(BE_USERS))

    # ── §② App 分账：工资那一半是纯函数算的，且这个文件不画钱 ──────────
    section("§② App 分账（ui/driver/DriverSalary.kt）")
    sal = raw(SALARY)
    sal_kt = kt(SALARY)
    for fn in ("isSalaryBill", "isSettledBill", "salaryBillsOf", "salaryTotalsOf", "salaryChangesOf", "salaryMonthWord"):
        n_fn = sal_kt.count("fun %s(" % fn)
        ok("纯函数 %s 只定义一次" % fn, n_fn == 1, "%d 处" % n_fn)
    ok("核销判两个条件取或（状态 settled 或被结算单锁住）",
       'b.status.equals("settled", ignoreCase = true) || b.settledDocId != null' in sal_kt)
    ok("只留月薪单，按月份倒序", "bills.filter { isSalaryBill(it) }.sortedByDescending { it.month }" in sal_kt)
    ok("合计分两笔给，不混成一个数",
       "val all: Double get() = settled + open" in sal_kt and "settledCount" in sal_kt and "openCount" in sal_kt)
    ok("变更：相邻两张不一样才算一次",
       "if (prev != cur) out += SalaryChange(rows[i].month, prev, cur, rows[i].ruleName)" in sal_kt)
    ok("变更线新的在前", "return out.asReversed()" in sal_kt)
    ok("月份脏数据原样回（宁可丑，不可无）", "if (m.length < 7) return m" in sal_kt and "else m" in sal_kt)
    ok("大小写都认（后端枚举是小写）", sal_kt.count("ignoreCase = true") == 2, "%d 处" % sal_kt.count("ignoreCase = true"))
    ok("⛔ 这个纯逻辑文件一个字金额都不画", "formatMoney" not in sal_kt and "\u00a5" not in sal and "\uffe5" not in sal)
    money_files = sorted(p.name for p in DRIVER.glob("*.kt") if "formatMoney(" in kt(p))
    ok("ui/driver 下画钱的文件只有运费那一页", money_files == ["DriverFreightScreen.kt"], "、".join(money_files))
    ok("KDoc 写明后端同口径那一半（_is_open_unlocked）", "_is_open_unlocked" in sal)
    ok("KDoc 写明月薪口径来源（services/driver_pay.py）", "services/driver_pay.py" in sal)

    # ── §③ 司机端「我的账本」两半页 ───────────────────────────────────
    section("§③ 司机端界面（DriverFreightScreen / ViewModel）")
    fs = raw(FREIGHT_SCREEN)
    fs_kt = kt(FREIGHT_SCREEN)
    ok("运费那半页的显示条件（有运费 / 没工资 / 有按单钱）",
       "val showFreight = vm.rows.isNotEmpty() || !vm.hasSalary || vm.hasPiece" in fs_kt)
    ok("工资那半页的显示条件", "val showSalary = vm.hasSalary || vm.salaryRows.isNotEmpty()" in fs_kt)
    ok("两半页各画各的",
       "if (showFreight) freightItems(vm, onOpenOrder)" in fs_kt and "if (showSalary) salaryItems(vm)" in fs_kt)
    ok("运费那半页取数一字没动（别人判据钉着的两行还在）", all(p in fs_kt for p in FREIGHT_PINS))
    ok("工资那半页是独立的一段（LazyListScope.salaryItems）", "private fun LazyListScope.salaryItems(" in fs_kt)
    ok("三张卡：汇总 / 工资单 / 变更",
       all(s in fs_kt for s in ("SalarySummaryCard(vm)", "SalaryBillCard(b)", "SalaryChangeCard(vm.salaryChanges)")))
    ok("文案分「已核销 / 未核销」两种说法", "已核销" in fs and "未核销" in fs)
    ok("未核销的跟着新工资走（写在脚注里）", "重算" in fs)
    ok("工资取数失败单独说（不连累运费那半页）", "salaryError" in fs_kt and "MaterialTheme.colorScheme.error" in fs_kt)
    ok("金额都来自 VM（界面不自己按规则猜）", "vm.salaryTotals" in fs_kt)
    n_squeeze = len(re.findall(r"maxLines = 1,\s*overflow = TextOverflow\.Ellipsis", fs_kt))
    ok("自适应红线：没加新的「省略号但没 weight」的行（<= 1）", n_squeeze <= 1, "%d 处" % n_squeeze)
    fvm = kt(FREIGHT_VM)
    ok("VM 里工资那半页的状态齐了",
       all(s in fvm for s in ("salaryRows", "salaryError", "hasSalary", "hasPiece", "salaryTotals", "salaryChanges")))
    ok("工资与运费分两次取（工资挂了不影响运费）",
       "salaryBillsOf(container.repo.driverBills())" in fvm and "freightSettlementRange(" in fvm)
    ok("司机自读的口径没变（me + driver-bills）", "container.repo.me()" in fvm and "driverBills()" in fvm)

    # ── §④ 派单端：生成 / 重算 + 一键核销 ─────────────────────────────
    section("§④ 派单端（DriverSalaryScreen + 运费结算页的出口 + 导航）")
    ds = raw(SALARY_SCREEN)
    ds_kt = kt(SALARY_SCREEN)
    ok("VM 与 Screen 都在这一页里", "class DriverSalaryViewModel(" in ds_kt and "fun DriverSalaryScreen(" in ds_kt)
    ok("生成 / 重算：带上 refresh_unsettled", "fun generate()" in ds_kt and "refreshUnsettled = true," in ds_kt)
    ok("核销：建一张工资结算单（settleType = salary）",
       'SettlementCreateRequest(driverId = id, settleType = "salary", month = month),' in ds_kt)
    ok("核销：建完立刻确认（一步走完）", 'container.repo.settlementAction(docId, "confirm")' in ds_kt)
    ok("付款 / 作废走现成动作",
       'settlementAction(s.id, "pay")' in ds_kt and 'settlementAction(s.id, "cancel")' in ds_kt)
    ok("两个按钮的字面都在", "生成 / 重算" in ds and "核销这个月的工资" in ds)
    ok("选司机用现成抽屉（PersonDrawer）", "PersonDrawer(" in ds_kt)
    ok("抽屉那份名册真的会筛（走唯一实现 UserSearch，不是画个框）",
       "UserSearch.filter(drivers, query, { driverText(it) }, { it.phone })" in ds_kt
       and "options = vm.visibleDrivers.map {" in ds_kt)
    ok("结算单那一行数的是「被它锁住的工资单」张数（工资结算单没有订单，数 order_ids 必然是 0）",
       "settledBillCountOf(vm.bills, s.id)" in ds_kt and "orderIds" not in ds_kt
       and "bills.count { it.settledDocId == docId }" in kt(SALARY))
    ok("空态说清下一步", "点上面「生成 / 重算」" in ds)
    fts = kt(FREIGHT_SETTLE)
    ok("运费结算页多了一个出口参数", "onOpenSalaries: () -> Unit = {}," in fts)
    ok("出口排在结算单那行之后（不抢位置）",
       before(fts, "SettlementSheetsRow(onOpenSettlements)", "SalarySheetsRow(onOpenSalaries)"))
    ok("这一页的司机选择行只有一处（别人反验脚本的锚点）", fts.count("PersonTriggerRow(") == 1, "%d 处" % fts.count("PersonTriggerRow("))
    ok("出口行是文件最后一个函数", fts.rindex("@Composable") < fts.index(ROW_DEF))
    tail = fts[fts.index(ROW_DEF):]
    ok("出口行只说「去哪儿」不写金额", "司机工资（按月）" in tail and "formatMoney" not in tail and "\u00a5" not in tail)
    ok("路由常量在", 'const val DISPATCH_DRIVER_SALARIES = "dispatcher/driver-salaries"' in kt(ROUTES))
    nav = kt(NAVGRAPH)
    ok("NavGraph 注册了这一页", "composable(Routes.DISPATCH_DRIVER_SALARIES)" in nav and "DriverSalaryScreen(" in nav)
    ok("运费结算页那个出口接到了这一页",
       "onOpenSalaries = { navController.navigate(Routes.DISPATCH_DRIVER_SALARIES) }" in nav)

    # ── §⑤ 入口闸门 + 接口字段 ────────────────────────────────────────
    section("§⑤ 入口闸门 + 接口字段（ProfileScreen / Dtos）")
    prof = raw(PROFILE)
    prof_kt = kt(PROFILE)
    ok("三个字段并列在同一个表达式里（按单两个 + 新的按月薪）", GATE_RE.search(prof_kt) is not None)
    ok("三个字段一个不少", all(f in prof_kt for f in GATE_FIELDS), "、".join(f for f in GATE_FIELDS if f not in prof_kt))
    ok("老那半边一字没动（别人判据逐字钉着）",
       "vm.user?.paysPerOrder == true || vm.user?.hasPerOrderEarnings == true" in prof_kt)
    ok("⛔ 没抽成辅助函数", "driverHasLedger(" not in prof)
    ok("尾注照着「他进去能看到什么」念（三档）",
       all(s in prof for s in ("运费 / 工资明细", "工资明细", "按单计费明细")))
    ok("KDoc 写明推翻了 2026-09-20 那条旧裁决（带 m43131）", "2026-09-20" in prof and "m43131" in prof)
    dt = raw(DTOS)
    dt_kt = kt(DTOS)
    ok("DriverBillDto / DriverBillGenerateRequest 都在",
       "data class DriverBillDto(" in dt_kt and "data class DriverBillGenerateRequest(" in dt_kt)
    ok("请求带上了刷新开关", '@SerialName("refresh_unsettled") val refreshUnsettled: Boolean = false,' in dt_kt)
    ok("UserDto 带上了 has_salary", '@SerialName("has_salary") val hasSalary: Boolean? = null,' in dt_kt)
    blk = dt_kt[dt_kt.index("data class DriverBillDto("):][:1500]
    ok("工资单多了「哪份规则算的」和「说明」（后端本来就在返回）",
       '@SerialName("rule_name") val ruleName: String = "",' in blk and 'val note: String = ""' in blk)

    # ── §⑥ 单测 + 文书 + 反向验证 ────────────────────────────────────
    section("§⑥ 单测 + 文书 + 反向验证")
    ktest = raw(KTEST)
    n_test = len(re.findall(r"@Test", ktest))
    ok("App 单测 >= 10 条", n_test >= 10, "%d 条" % n_test)
    bt = raw(BE_TEST)
    ok("旧用例还在（别人判据逐字钉着函数名，⛔ 不许改名）", "def test_一直拿固定工资没按单跑过的司机_没有我的账单入口" in bt)
    ok("旧用例跟着新口径断言了 has_salary", 'assert me["has_salary"] is True' in bt)
    ok("新增：未核销的跟着重算、已核销的一分不动",
       "def test_固定工资改过_未核销的月薪单跟着重算_已核销的一分不动" in bt)
    ok("新用例把「被草稿结算单锁住」这一档也钉住了",
       "settled_doc_id" in bt and "refresh=True" in bt)
    chg = raw(CHG)
    ok("变更单够长（> 3000 字符）", len(chg) > 3000, "%d 字符" % len(chg))
    miss = [p for p in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨") if ("## " + p) not in chg]
    ok("九个必填小节都在", not miss, "缺：" + "、".join(miss))
    ok("README 里登记了这一单", "](CHG-0127.md)" in raw(README))
    ok("AI_WORK_CLAIM 里认领了这一单", "CHG-0127" in raw(CLAIM))
    rev = raw(REVERSE)
    n_inj = len(re.findall(r"(?m)^    \(\s*$", rev))
    ok("反向验证脚本：注入点 >= 3 条（房规下限）", n_inj >= 3, "%d 条" % n_inj)
    ok("反向验证脚本：逐字节还原 + sha256 都真有",
       all(s in rev for s in ("read_bytes", "write_bytes", "sha256", "anchor_preflight")))
    m_claim = re.search(r"（(\d+) 种破坏方式全被抓）", __doc__ or "")
    declared = int(m_claim.group(1)) if m_claim else 0
    ok("判据自己写的声明条数 == 反验脚本实际条数", declared == n_inj, "声明 %d / 实际 %d" % (declared, n_inj))
    return finish()


if __name__ == "__main__":
    sys.exit(main())


