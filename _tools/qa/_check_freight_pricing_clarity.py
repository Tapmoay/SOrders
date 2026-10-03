# -*- coding: utf-8 -*-
"""红线：两笔钱不许混着说、待定价的单不许看不见（CHG-0029，2026-10-03 E2E 走查 P19）。

## 这条是怎么来的
2026-10-03 的 E2E 走查里，用户看到的是同一个毛病的两头：

- 计费规则卡上**同一个事实自相矛盾**：卡上写「按单计件 · 小货车每单 22 元」，
  同一张卡下面又写「还没勾价目 —— 派给这个司机的单会进『待定价』」。
  两句话说的其实是**两笔钱**（给司机的工资 / 货主付的运费），但卡上没有一个字区分；
- 王强真实送达的那一单在「司机运费结算」页**查不到**：钱在 运费模板 → 待定价 里，
  而这两页之间原来既没有链接、也没有角标 —— 派单员核这位司机的运费时看到的是一片空。

## 为什么必须有机器的判据
这两处的形状都是「界面在**沉默**」：

- 规则卡少一行「给司机的钱」照样编译、照样排版，两句数字仍然并排躺在同一张卡上；
- 结算页不知道待定价的存在照样编译 —— 它只是**少查一次**（少一个 unpriced=true 的请求），
  页面上什么都不缺，用户看不出少了什么。

所以判据分三层：
1. 待定价的单在结算页看得见：状态从共用取数口来（repo.unpricedOrders()，截断读 X-Truncated 头）、
   load() 里真的调了它、它失败**不许**把主表拖红、那一行把三件事同句说清
   （还有多少单 / 不分司机 / 不在上面这张表里）、它不写金额、去向是待定价页；
2. 计费规则卡不再自相矛盾：口径标签「给司机的钱」在数字上方、没勾价目时挂「缺价目」角标（共用零件）、
   被冻的那句原话一字不动、空价目分支后面多一句把两笔钱的关系说明白；
3. 与反向验证脚本配对，文档 / 登记表 / 认领簿三处都记了这条（防「永远红 / 永远绿」）。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。少显示一行字、少查一次接口都不会让
任何断言变红，编译也照样过；「待定价的单在不在这一页上」是**口径问题**，
只有扫结构与扫文案才问得出来。反向破坏用例由
_tools/qa/_reverse_verify_freight_pricing_clarity.py 负责；「用户确实看到了」那一头由
2026-10-03 模拟器 5554 的截图负责（规则卡 / 结算页那一行 / 待定价页）。
本判据只读源码与文档（read()），不连库、不 import 后端、不跑迁移。

用法：python _tools/qa/_check_freight_pricing_clarity.py
     python _tools/qa/_check_freight_pricing_clarity.py --list   # 只列它到底在查什么
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
# 注释剥离**只有一份实现**（那个状态机是为 "image/*" 这种字符串写的，抄一份必踩同一个坑）
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
UI = AND / "ui"

VM = AND / "ui/dispatcher/FreightSettlementViewModel.kt"
SCREEN = AND / "ui/dispatcher/FreightSettlementScreen.kt"
RULES = AND / "ui/dispatcher/DriverBillingRulesScreen.kt"
PRICING = AND / "ui/dispatcher/FreightPricingScreens.kt"
TEMPLATES = AND / "ui/dispatcher/FreightTemplatesScreen.kt"
NAV = AND / "ui/nav/NavGraph.kt"
CHIP = AND / "ui/dispatcher/VehicleManageScreen.kt"
README = ROOT / "docs/changes/README.md"
DOC = ROOT / "docs/changes/CHG-0029.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = "_tools/qa/_reverse_verify_freight_pricing_clarity.py"

#: 扫到的界面文件数下限（防目录改名 / 搬走之后"一个文件都没扫到"也算过）
MIN_UI_FILES = 100

#: 那一行文案（一字不许改：三个事实缺一个，用户就会把这张表当成完整的账）
NOTICE = 'return "还有 $n 运费没定价 —— 不分司机，也不在上面这张表里"'
#: 被冻的规则卡原话（_tools/qa/_check_freight_pricing.py 也钉着这一整段前缀）
FROZEN = "还没勾价目 —— 派给这个司机的单会进「待定价」"
#: 口径标签（少了它，「每单 22 元」会被读成运费已经定了）
WAGE_LABEL = 'Text("给司机的钱", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)'
#: 角标（没勾价目 = 这条规则还没配好）
CHIP_TAG = 'MiniChip("缺价目", MaterialTheme.colorScheme.error)'
#: 结算页那一行的去向
NAV_LINE = "onOpenUnpriced = { navController.navigate(Routes.FREIGHT_UNPRICED) },"
#: 共用零件（角标只许有一份实现）
CHIP_DEF = "internal fun MiniChip(text: String, color: Color) {"
#: 反引号（Python 源码里不写反引号，判据要认登记表里的 Markdown 代码记号）
BT = chr(96)


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def kt(p: Path) -> str:
    """源码去掉注释之后的正文（词表判据必须去注释，否则自己写的注释会把它喂饱）。"""
    return strip_comments(read(p))


def body_of(src: str, sig: str) -> str:
    """按大括号配对取出一个函数体（sig 是函数签名那一行）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    b = src.find("{", i + len(sig) - 1)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i : j + 1]
    return ""


def between(src: str, start: str, stop: str) -> str:
    """start 之后、stop 之前的那一段（用来把判据关在一条路由里）。"""
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(stop, i + len(start))
    return src[i : j if j > 0 else len(src)]


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def section(title: str) -> None:
    print()
    print(f"-- {title} --")


def main() -> int:
    if refuse_if_injecting("定价口径检查"):
        return 1

    c = Checker()
    print("两笔钱不许混着说、待定价的单不许看不见（CHG-0029：E2E 走查 P19）")

    app = {p: kt(p) for p in sorted(AND.rglob("*.kt"))}
    ui_files = [p for p in app if UI in p.parents]
    vm = app.get(VM, "")
    sc = app.get(SCREEN, "")
    rules = app.get(RULES, "")
    nav = app.get(NAV, "")
    chip_defs = sum(CHIP_DEF in app[p] for p in ui_files)

    # ---- 1. 待定价的单在结算页看得见 ----
    section("1. 待定价的单在结算页看得见（钱在哪一页，页面上要说）")
    c.ok(
        "结算页 ViewModel 记着待定价的单（unpricedRows）与它是否被截断（unpricedMore）",
        "var unpricedRows by mutableStateOf<List<OrderDto>>(emptyList())" in vm
        and "var unpricedMore by mutableStateOf(false)" in vm,
        "少了这两个状态 —— 结算页又只剩已计价的那一页，待定价的单一个字都不提",
    )
    c.ok(
        "待定价的单从共用取数口来（repo.unpricedOrders()），没人自己拼查询",
        "val page = container.repo.unpricedOrders()" in vm,
        "自己拼了一份 unpriced 查询 —— 过滤条件（已派单、没运费、未撤销）会与后端漂开",
    )
    c.ok(
        "截断只认响应头（page.meta.hasMore），不按条数等于上限猜",
        "unpricedMore = page.meta.hasMore" in vm,
        "又回到猜法了：刚好整页时会说假话",
    )
    c.ok(
        "load() 里真的去问了这一句（不只是定义了没人调）",
        "            loadUnpriced()" in vm and "private suspend fun loadUnpriced()" in vm,
        "loadUnpriced 定义了却没人调 —— 那一行永远是 0",
    )
    unpriced_body = body_of(vm, "private suspend fun loadUnpriced()")
    c.ok(
        "它失败时按没有处理，不把主表拖红",
        "catch (e: Exception)" in unpriced_body
        and "error =" not in unpriced_body
        and "data = null" not in unpriced_body,
        "待定价那一次请求失败会连带把已计价的账也画成错误 —— 它是多给一条路，不是主数据",
    )
    notice_body = body_of(sc, "internal fun unpricedNotice(")
    c.ok(
        "那一行的文案只有一份实现，且是 internal（单测够得着）",
        notice_body != "" and "if (count <= 0) return null" in notice_body,
        "没有 0 单就不显示这一条 —— 没有待定价的单时页面上会挂一句还有 0 单",
    )
    c.ok(
        "被服务端截断时只说「N 单以上」，不说确数",
        'val n = if (more) "$count 单以上" else "$count 单"' in notice_body,
        "截断了还说确数 —— 那是假话（后端一页最多 200 条）",
    )
    c.ok(
        "那一行把三件事同句说清（还有多少单 / 不分司机 / 不在上面这张表里）",
        NOTICE in notice_body,
        "三件事没同句说清 —— 少任何一条，用户就会拿着这张表当完整的账去对",
    )
    c.ok(
        "结算页真的显示那一行，并且点了去得了待定价页",
        "unpricedNotice(vm.unpricedRows.size, vm.unpricedMore)?.let { text ->" in sc
        and "UnpricedNoticeRow(text, onOpenUnpriced)" in sc,
        "文案函数写好了却没人调用（或者点了没去处）",
    )
    row_body = body_of(sc, "private fun UnpricedNoticeRow(")
    c.ok(
        "那一行**不写金额**（金额要等那些单自己被定完价才算得出来）",
        row_body != "" and "¥" not in row_body and "formatMoney" not in row_body,
        "这一行写了金额 —— 它只是在说别处还有单，钱数此刻还不存在",
    )
    c.ok(
        "那一行没有 maxLines = 1（自适应挤压基线只许降）",
        row_body != "" and "maxLines" not in row_body,
        "给它加了 maxLines = 1 —— _tools/qa/_adaptive_squeeze_baseline.txt 里这一页的处数只许降",
    )
    c.ok(
        "结算页的选人那一行仍只有一处（反向验证脚本按它做注入锚点）",
        sc.count("PersonTriggerRow(") == 1,
        f"实际 {sc.count('PersonTriggerRow(')} 处 —— 多一处会让 _reverse_verify_freight_settlement_ui.py 的注入落空",
    )
    settle_route = between(nav, "composable(Routes.FREIGHT_SETTLEMENT)", "composable(")
    c.ok(
        "结算页那一行绑到了待定价页（NavGraph 传 onOpenUnpriced → Routes.FREIGHT_UNPRICED）",
        NAV_LINE in settle_route,
        "没接路由 —— 用户点那一行什么都不会发生",
    )
    c.ok(
        "待定价那一页还在，且两条路都通（模板页底栏 + 结算页那一行）",
        "fun UnpricedOrdersScreen(" in app.get(PRICING, "")
        and nav.count(NAV_LINE) >= 2
        and '"待定价"' in app.get(TEMPLATES, ""),
        "待定价页被搬走 / 改名了 —— 那一行会把用户带到一个不存在的地方",
    )
    c.ok(
        "同一个词（待定价）三处一致：结算页明细行 / 规则卡 / 待定价页",
        '"运费 待定价"' in sc and "待定价" in rules and "待定价" in app.get(PRICING, ""),
    )

    # ---- 2. 计费规则卡不再自相矛盾 ----
    section("2. 计费规则卡：两笔钱分开说")
    card = body_of(rules, "private fun RuleCard(")
    c.ok("规则卡还在（找得到 RuleCard 的函数体）", card != "", "RuleCard 被改名 / 搬走了")
    c.ok(
        "口径标签「给司机的钱」在数字上方（少了它，每单 22 元会被读成运费已经定了）",
        WAGE_LABEL in card and card.find(WAGE_LABEL) < card.find("Text(rule.summary"),
        "标签不在 / 排到了 summary 后面 —— 用户先看到数字再看到解释，顺序反了",
    )
    c.ok(
        "卡上仍是被冻的那句原话（一字不动，另一条判据也钉着它）",
        FROZEN in rules,
        "改了那句被冻的话 —— _tools/qa/_check_freight_pricing.py 会红，AI 话术与帮助文案还引用着它",
    )
    c.ok(
        "空价目分支后面多了一句把两笔钱的关系说明白",
        FROZEN in card
        and "运费按价目算" in card
        and "点「编辑」勾上" in card
        and card.find(FROZEN) < card.find("运费按价目算"),
        "只有会进待定价这一句后果，没说清那笔 22 元是工资 —— 两句话看着还是自相矛盾",
    )
    c.ok(
        "没勾价目时挂「缺价目」角标（挂在名字那一行，卡片一多也看得出）",
        CHIP_TAG in card and card.find("rule.templateBriefs.isEmpty()") < card.find(CHIP_TAG),
        "没有角标 —— 卡片一多，哪条还没配好得逐张读完才知道",
    )
    c.ok(
        "角标用的是共用零件（MiniChip 全库只有一份实现）",
        len(ui_files) >= MIN_UI_FILES and chip_defs == 1 and CHIP_DEF in app.get(CHIP, ""),
        f"扫到 {len(ui_files)} 个界面文件、MiniChip 定义了 {chip_defs} 处（下限 {MIN_UI_FILES} 个文件）",
    )

    # ---- 3. 配对与文档 ----
    section("3. 配对与文档")
    c.ok("这条红线配了反向验证脚本", (ROOT / REVERSE).exists(), f"找不到 {REVERSE}")
    c.ok(
        "改动文档在（九节 + 走查原话）",
        DOC.exists() and "P19" in read(DOC),
        "docs/changes/CHG-0029.md 不在 / 少了走查项",
    )
    c.ok(
        "改动登记表里有 CHG-0029 行（进行中 / 已关闭两态）",
        ("| " + BT + "CHG-0029" + BT + " |") in read(README),
        "docs/changes/README.md 里没有 CHG-0029 那一行",
    )
    c.ok("认领簿里有 CHG-0029 的块", "CHG-0029" in read(CLAIM))

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 结算页 记着待定价的单（共用取数口 + 只认响应头）、load() 真去问了、失败不拖红主表")
        print("     · 那一行 三件事同句说清（还有多少单 / 不分司机 / 不在上面这张表里）、不写金额、没有 maxLines = 1")
        print("     · 路    NavGraph 把它绑到 Routes.FREIGHT_UNPRICED（模板页底栏那条路还在）")
        print("     · 规则卡 「给司机的钱」标签在数字上方、没勾价目挂「缺价目」角标、被冻那句一字不动、再补一句说清两笔钱")
        print("     · 配    反向验证脚本、改动文档、登记表、认领簿四件事都在")

    return c.report("两笔钱不许混着说、待定价的单不许看不见（CHG-0029）")


if __name__ == "__main__":
    sys.exit(main())
