"""BUG-0016：账本里「欠款人＝货主自己」那一档，卡片与左栏都要红着说破。

用户原话（2026-10-07 m12371）：
  「还有这个我欠我自己的账，他这个卡片啊，也要有详细的提示啊，比如说，用红色或者说啊告诉他，
    这个是异常订单啊。不可能存在我欠我自己的账，你这个还是没搞好啊，也就卡片样式他也要告诉
    用户说，这卡片这个这个订单有问题啊。到时候账是算不清算不明白的」

这一块最容易悄悄坏掉的六件事（每条都有判据）：
  1. 判定只比名字、或只比电话 —— 分组键是「名字|电话」两半，漏一半就漏报（真库 orders.id=603
     是名字撞上、orders.id=595 是电话撞上，两种都得报）。
  2. 空串被当成命中：「未指定货主|」那一档不是人，名字空 + 电话空不该报。
  3. 自己的账号资料没取到（null）时报出来 —— 冤枉别人（宁可漏，不可误报）。
  4. 只在左栏标、或只在卡片上标 —— 用户说的「卡片样式」要的是卡片上有，左栏名册也要标。
  5. 提示顺手把数改了、或把核销拦了 —— 这是提示，不是闸门。
  6. 规矩只活在代码里：设计规范与定位表没指路，下一个人会把红条当装饰删掉。

规矩的出处：docs/PROJECT_MAP/06_DESIGN_SYSTEM.md §4.14 第 5 条、docs/PROJECT_MAP/08_CODE_LOCATOR.md
货主「账本」那一行；反向验证 _tools/qa/_reverse_verify_ledger_self_debt.py。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事

这一条**边界解决不了** —— 缺口不在"某个函数算错了"，而在「**同一档客户该不该被当成异常**」这个判断
与"货主自己的账号资料恰好等于分组键的一半"之间的**巧合**：后端那处兜底（下单人没填就写货主账号资料）
本身是合法行为，客户端的分组键（名字|电话）也是合法口径，两层各自都对；只有把它们放在一起看，
才会发现"这一档其实是我自己"。边界层没有任何单点可以表达"这两份合法数据撞在一起就是异常"，
所以只能靠静态判据钉住判定的两半、两处提示，以及"只提示、不改数字、不拦核销"这条纪律。

反向破坏用例（`_tools/qa/_reverse_verify_ledger_self_debt.py`，15 条注入真实源码、跑完按字节还原）：
判定只看名字 / 只看电话、空串也算命中、身份为 null 也报、左栏那处提示删掉、卡片那处提示删掉、
卡片底色换掉、名字来源换成别的字段、界面入口恒 false、取失败时写空串、设计规范那条被删、
定位表那条被删、单测里"null 不报"那条断言被删、卡片文案丢了「异常订单」、左栏红字换色 ——
每条都必须让本判据变红并点名对应那一条。

静默空转保护：断言总数 `total < 40` 时直接判"判据在空转，停"（`return 1`），
避免"文件改名 / 正则没命中"被读成"全过"。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
GROUPING = ANDROID / "ui/shipper/ShipperLedgerGrouping.kt"
VM = ANDROID / "ui/shipper/ShipperLedgerViewModel.kt"
SCREEN = ANDROID / "ui/shipper/ShipperLedgerScreen.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/shipper/ShipperLedgerGroupingTest.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"
CHANGE = ROOT / "docs/changes/BUG-0016.md"
README = ROOT / "docs/changes/README.md"


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数，好让行号还对得上）。

    这里的注释**故意**写着 isSelfDebtCustomer / errorContainer / 不拦核销 这些字眼（KDoc 就是
    要把口径讲清楚），判据要抓的是**代码里**还有没有 —— 不剥注释的话，散文能把红线喂饱。
    """
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def region(text: str, start: str, stop: str) -> str:
    """截出 [start, stop) 那一段；找不到 start 就返回空串（由调用方的判据报红）。"""
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(stop, i + len(start))
    return text[i:j] if j >= 0 else text[i:]


def around(text: str, anchor: str, before: int = 0, after: int = 400) -> str:
    """取 anchor 附近那一段（把断言圈在附近，免得被兄弟函数或另一个屏满足）。"""
    i = text.find(anchor)
    if i < 0:
        return ""
    return text[max(0, i - before):i + after]


class Checker:
    def __init__(self) -> None:
        self.passes = 0
        self.fails: list[str] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
        else:
            self.fails.append(f"{label}｜{detail}" if detail else label)

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")


def main() -> int:
    c = Checker()
    grouping = read(GROUPING)
    vm = read(VM)
    screen = read(SCREEN)
    test = read(TEST)
    design = read(DESIGN)
    locator = read(LOCATOR)

    gcode = code_only(grouping)
    vmcode = code_only(vm)
    scode = code_only(screen)

    fn_body = region(gcode, "fun isSelfDebtCustomer(", chr(10) + chr(10))
    me_block = around(vmcode, "var meName by mutableStateOf", 0, 260)
    me_init = around(vmcode, "val me = container.repo.me()", 160, 520)
    _, _, catch_raw = me_init.partition("catch")
    catch_part = catch_raw[:220]
    drawer_call = around(scode, "warn = if (vm.isSelfDebt(c))", 120, 200)
    row_body = region(scode, "private fun DrawerCustomerRow(", chr(10) + "@Composable")
    card = around(scode, "if (vm.isSelfDebt(g)) {", 60, 700)

    print("== 1. 判定本身：分组键的两半，撞上任意一半就算 ==")
    c.ok("取到了 isSelfDebtCustomer 的函数体", len(fn_body) > 200, f"只有 {len(fn_body)} 字符")
    c.present("形参一：这一档客户的名字", fn_body, r"name: String,")
    c.present("形参二：这一档客户的电话", fn_body, r"phone: String,")
    c.present("形参三：货主自己的名字（可空）", fn_body, r"meName: String\?,")
    c.present("形参四：货主自己的电话（可空）", fn_body, r"mePhone: String\?,")
    c.present("返回布尔（界面拿它决定画不画红条）", fn_body, r"\): Boolean \{")
    c.present("客户名字先 trim", fn_body, r"val n = name\.trim\(\)")
    c.present("客户电话先 trim", fn_body, r"val p = phone\.trim\(\)")
    c.present("自己的名字取不到就是空串（? .trim().orEmpty()）", fn_body, r"val mn = meName\?\.trim\(\)\.orEmpty\(\)")
    c.present("自己的电话取不到就是空串", fn_body, r"val mp = mePhone\?\.trim\(\)\.orEmpty\(\)")
    c.present("电话那一半：两边都非空且相同才命中", fn_body,
              r"if \(p\.isNotEmpty\(\) && mp\.isNotEmpty\(\) && p == mp\) return true")
    c.present("名字那一半：两边都非空且相同才命中", fn_body,
              r"return n\.isNotEmpty\(\) && mn\.isNotEmpty\(\) && n == mn")
    c.absent("⛔ 没有把空串当命中（去掉 isNotEmpty，「未指定货主」那档就会混进来）", fn_body,
             r"if \(p == mp\) return true")
    c.absent("⛔ 没有 !! 硬解空（账号资料没回来时会崩）", fn_body, r"me(?:Name|Phone)!!")
    c.absent("⛔ 判定里不许把「未指定货主」当人（那一档另有提示）", fn_body, r"UNSET_CUSTOMER")
    c.present("KDoc 点名了用户这一次报障（m12371）", grouping, r"m12371")
    c.present("KDoc 引了用户原话", grouping, r"不可能存在我欠我自己的账")
    c.present("KDoc 写清根因是后端那条「账号资料兜底」", grouping, r"backend/app/commands/order\.py")
    c.present("KDoc 点名兜底写进去的是 target_shipper.full_name", grouping, r"target_shipper\.full_name")
    c.present("KDoc 留了真库第一单（orders.id=603：名字与电话都撞上）", grouping, r"orders\.id=603")
    c.present("KDoc 留了真库第二单（orders.id=595：只有电话撞上）", grouping, r"orders\.id=595")
    c.present("KDoc 留了 603 那个分组键", grouping, r"Shipper\|13800000002")
    c.present("KDoc 留了 595 那个分组键", grouping, r"苏春梅\|13619667470")
    c.present("KDoc 写清判据＝分组键的两半", grouping, r"分组键的两半")
    c.present("KDoc 钉了空串一律不算命中", grouping, r"空串一律")
    c.present("KDoc 钉了身份没拿到就不报（宁可漏，不可误报）", grouping, r"宁可漏，不可误报")
    c.present("KDoc 钉了只提示、不拦核销、不改数字", grouping, r"不拦核销、不改数字")

    print("== 2. 「我自己」是从哪儿来的：users/me 的名字与电话 ==")
    c.ok("取到了 meName / mePhone 那一段", len(me_block) > 100, f"只有 {len(me_block)} 字符")
    c.present("meName 是可空状态（没回来就是 null）", me_block,
              r"var meName by mutableStateOf<String\?>\(null\)")
    c.present("mePhone 是可空状态", me_block, r"var mePhone by mutableStateOf<String\?>\(null\)")
    c.ok("两个都对外只读（private set）", me_block.count("private set") == 2,
         f"数到 {me_block.count('private set')} 处")
    c.present("注释点名名字取的是 full_name", vm, r"后端给「下单人」兜底时写的正是这个字段")
    c.present("注释写清取不到就保持 null（null 一律不报）", vm, r"null 一律不报")
    c.present("在 init 里取自己的账号资料", me_init, r"val me = container\.repo\.me\(\)")
    c.present("名字用 fullName（后端兜底写的正是这个字段）", me_init, r"meName = me\.fullName")
    c.present("电话用 phone", me_init, r"mePhone = me\.phone")
    c.absent("⛔ 取失败时不写 meName（保持 null ⇒ 不报，不冤枉别人）", catch_part, r"meName")
    c.absent("⛔ 取失败时不写 mePhone", catch_part, r"mePhone")
    c.present("界面用的入口：isSelfDebt(分组) 直接委托纯函数", vmcode,
              r"fun isSelfDebt\(g: LedgerCustomer\): Boolean = isSelfDebtCustomer\(g\.name, g\.phone, meName, mePhone\)")
    c.ok("VM 里 isSelfDebt 只此一处（没有第二个判据分叉）", vmcode.count("isSelfDebt(") == 1,
         f"数到 {vmcode.count('isSelfDebt(')} 处")

    print("== 3. 两处提示：左栏名册里红字、主区卡片上红条 ==")
    c.present("左栏那一行把判定接上了", drawer_call, r"warn = if \(vm\.isSelfDebt\(c\)\)")
    c.present("左栏提示说清了「就是你自己」与下一步", drawer_call, r"就是你自己 · 请先改收货人")
    c.ok("取到了 DrawerCustomerRow 的函数体", len(row_body) > 200, f"只有 {len(row_body)} 字符")
    c.present("红字是一个可空形参（不命中就整块不画）", row_body, r"warn: String\? = null,")
    c.present("红字只有 warn != null 才画", row_body, r"if \(warn != null\) \{")
    c.present("红字用 error 色（不是普通副标题）", row_body, r"color = MaterialTheme\.colorScheme\.error\b")
    c.present("左栏那处的注释点名了 m12371", screen, r"m12371")
    c.ok("取到了主区卡片上那一段", len(card) > 300, f"只有 {len(card)} 字符")
    c.present("卡片那处也接上了同一个判定", card, r"if \(vm\.isSelfDebt\(g\)\) \{")
    c.present("卡片用 errorContainer 底（与订单详情那两条红条同一套）", card,
              r"color = MaterialTheme\.colorScheme\.errorContainer")
    c.present("卡片的字用 onErrorContainer", card, r"color = MaterialTheme\.colorScheme\.onErrorContainer")
    c.present("卡片上写着「异常订单」", card, r"异常订单：这一档的客户就是你自己")
    c.present("卡片上说破了「你欠你自己」", card, r"你欠你自己")
    c.present("卡片给了下一步（去订单里改收货人）", card, r"去订单里把收货人改成真正的客户")
    c.present("注释钉了「必须当场说破」这个决定", screen, r"当场说破")
    c.ok("界面里判定只有这两处（左栏 + 卡片）", scode.count("isSelfDebt(") == 2,
         f"数到 {scode.count('isSelfDebt(')} 处")

    print("== 4. 只提示：不改数字、不拦核销（用户要的是「知道」，不是闸门） ==")
    c.absent("⛔ 判定没有接进核销/收款那一路", scode + vmcode,
             r"isSelfDebt[^\n]*(?:settle|Settle|receipt|Receipt)")
    c.absent("⛔ 卡片那段没有 enabled = ... 之类的禁用", card, r"enabled\s*=")
    c.absent("⛔ 提示没有就地改数字（欠款额仍由分组算出来）", card + drawer_call, r"owedCents\s*=")
    c.present("顶上那张卡仍然取服务端的收支统计", vmcode, r"summary = container\.repo\.myLedgerSummary\(")
    c.present("summary 仍按选中的人取（提示不改筛选口径）", vmcode, r"customerName = summaryCustomerName\(\),")
    c.present("核销明细的算法一个字没动", vmcode,
              r"val settledByLine: Map<Long, Long> get\(\) = settledByLineCents\(settlements\)")
    c.ok("单测里钉了真库那两单（两种撞法都要报）", test.count("isSelfDebtCustomer(") >= 6,
         f"数到 {test.count('isSelfDebtCustomer(')} 处")
    c.present("真库 603：名字与电话都撞上", test,
              r'isSelfDebtCustomer\("Shipper", "13800000002", "Shipper", "13800000002"\)')
    c.present("真库 595：只有电话撞上也要报", test,
              r'isSelfDebtCustomer\("苏春梅", "13619667470", "陈记中学食堂", "13619667470"\)')
    c.present("只有名字撞上也要报", test,
              r'isSelfDebtCustomer\("Shipper", "13500000001", "Shipper", "13800000002"\)')
    c.present("不相干的不报", test, r'!isSelfDebtCustomer\("罗伟东"')
    c.present("「未指定货主」那一档不报", test,
              r'!isSelfDebtCustomer\(UNSET_CUSTOMER, "", "Shipper", "13800000002"\)')
    c.present("身份没拿到（null）不报", test, r'!isSelfDebtCustomer\("Shipper", "13800000002", null, null\)')
    c.present("名字与电话都空不报", test, r'!isSelfDebtCustomer\("", "", "Shipper", "13800000002"\)')

    print("== 5. 文档与变更台账（这条规矩得有出处） ==")
    c.ok("变更文档 docs/changes/BUG-0016.md 在", CHANGE.exists(), str(CHANGE))
    change = read(CHANGE) if CHANGE.exists() else ""
    c.present("变更文档引了用户原话", change, r"我欠我自己的账")
    c.present("变更文档点名了那个纯函数", change, r"isSelfDebtCustomer")
    c.present("变更文档写清只提示、不拦核销", change, r"不拦核销")
    c.present("变更文档关联了旧账 L-28 / L-31", change, r"L-28")
    c.present("设计规范写了这条规矩并点名判据", design, r"_check_ledger_self_debt\.py")
    c.present("设计规范引了用户原话", design, r"不可能存在我欠我自己的账")
    c.present("设计规范写清「只提示、不拦核销、不改数字」", design, r"不拦核销")
    c.present("设计规范钉了顶上那张卡仍取服务端 summary", design, r"GET /shipper-ledger/summary")
    c.present("设计规范写清拿不到账号资料时不报", design, r"宁可不报")
    c.present("代码定位表点名了判据", locator, r"_check_ledger_self_debt\.py")
    c.present("代码定位表点名了这个缺陷号", locator, r"BUG-0016")
    c.present("登记簿里有 BUG-0016 这一行", read(README), r"BUG-0016\.md")

    total = c.passes + len(c.fails)
    if total < 40:
        print(f"❌ 只跑了 {total} 项（<40）—— 判据在空转，停。")
        return 1
    if c.fails:
        print(f"[FAIL] {len(c.fails)} 项不成立：")
        for f in c.fails:
            print("  · " + f)
        return 1
    print(f"✅ 账本「欠款人＝货主自己」那一档：{c.passes} 项全部成立（含「只提示、不拦核销、不改数字」"
          "与「空串 / 身份 null 一律不报」两套反向判据）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
