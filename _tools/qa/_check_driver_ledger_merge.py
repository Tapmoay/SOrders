"""红线：**「司机账」与「司机运费结算」合并成一页**（2026-10-07 CHG-0075，台账 L-36）。

## 由来（用户原话，逐句对着做）

> 还有一个就是将司机账，就是账本管理的司机账，以及司机运费结算啊，这 2 个直接合并成一个。

同一段里他还补了半句口径（这是"什么不许在合并里丢掉"）：

> 本来就是司机的运费结算。当然，像一些功能，比如说有些订单没有定价啊，那些功能是要保留的。

（2026-10-07；变更单 docs/changes/CHG-0075.md）合并后的落地面 —— **下面这七条就是本文的红线**：

1. 入口**只有一处**：账本管理入口页那格「司机账 · 运费结算」（`Routes.FREIGHT_SETTLEMENT`）；
   工作台那格「司机运费结算」**整格删掉**。
2. 账本页只剩 **3 档**（0 订单账 / 1 货主账 / 2 批发商账）—— 「司机账」不再是它的第 4 个档位；
   越界的 deep link（老的 `dispatcherLedger(3)`）落回订单账，不许出现"标题写订单账、页面却走账户汇总"。
3. 时间 = **账本页那一套档位**（`DateFilterDialogs` + `DatePresets.rangeOf`，含「全部」按天）；
   不许再自己拼月份，也不许把 2026-09-22 那版年月网格装回来；「全部」那一档的宽边界
   （`DatePresets.WIDE_FROM/WIDE_TO`）**只有一份**，账本页与结算页都引用它。
4. 取数**不回流**：结算页走 `freightSettlementRange(from, to)`；不许退回按月的 `freightSettlement(month)`。
5. 明细**就地展开**（点一行 → 这一行下面长出一块 `OrderPeek`），不再点一下跳订单详情页。
6. 那条孤儿路由「司机结算（按月）」（`Routes.DISPATCH_SETTLEMENTS`）**救活**：出口挂在这一页上。
7. 司机那一层**没有核销**（给他的是"该拿多少"，不是"他欠我多少"）；核销只在账本页的人那一层。
   另外 ⛔ 两件事照旧：司机应得（`pay_total`）与货主运费合计（`freight_fee`）**分开写**；
   待定价那一行 +「去定价」→ `Routes.FREIGHT_UNPRICED`（用户点名要保留的那类功能）。

## 这条判据守的事，坏起来都不会报错

| 写坏的方式 | 表现 |
|---|---|
| 工作台那格又长回来，或入口页那格改回 `dispatcherLedger(1)` | 两个入口 = 两种时间口径，两边都看着对 |
| 账本页又把「司机账」接回档位（多一个 tab 分支） | 页面能开、数字也对，只是同一件事有了两个地方 |
| 结算页自己拼月份（回到 `freightSettlement(month)`） | 「账本页的本月」与「结算页的本月」差几天，而两边都看着对 |
| 宽边界抄成第二份 | 改一处漏一处（这正是 2026-09-22 那次分开写留下的坑） |
| 明细退回"点一下跳订单详情" | 用户要多退一层才回得来 |
| 孤儿页没人进得去 | 路由还在、注册还在，只是永远点不到 |
| 结算页长出核销 | 把"该给他多少"和"他欠我多少"混成一个口径，账面上看不出来 |

⚠️ 注入式反向验证（改坏 → 本脚本必须红）：`_tools/qa/_reverse_verify_driver_ledger_merge.py`。

用法：python _tools/qa/_check_driver_ledger_merge.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用兄弟红线里剥 Kotlin 注释的实现，不抄第二份。
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

MODULES = ANDROID / "ui/nav/Modules.kt"
ROUTES = ANDROID / "ui/nav/Routes.kt"
NAVGRAPH = ANDROID / "ui/nav/NavGraph.kt"
WORKBENCH = ANDROID / "ui/home/WorkbenchScreen.kt"
#: 合并后的那一页（账本管理入口页那格「司机账 · 运费结算」）。
SETTLEMENT_SCREEN = ANDROID / "ui/dispatcher/FreightSettlementScreen.kt"
SETTLEMENT_VM = ANDROID / "ui/dispatcher/FreightSettlementViewModel.kt"
#: 账本页（合并后只剩订单账 / 货主账 / 批发商账三档）。
SCREEN = ANDROID / "ui/dispatcher/DispatcherLedgerScreen.kt"
VM = ANDROID / "ui/dispatcher/DispatcherLedgerViewModel.kt"
PERSON_SCREEN = ANDROID / "ui/dispatcher/LedgerPersonScreen.kt"
PRESETS = ANDROID / "ui/common/DatePresets.kt"


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return strip_comments(p.read_text(encoding="utf-8"))


def read_all_kt() -> dict[str, str]:
    """全树源码（已剥注释）—— 用来算"某件事是不是只有一处"，不手写文件名单。"""
    out: dict[str, str] = {}
    for p in sorted(ANDROID.rglob("*.kt")):
        out[str(p.relative_to(ANDROID)).replace("\\", "/")] = strip_comments(p.read_text(encoding="utf-8"))
    if len(out) < 40:
        raise SystemExit(f"只读到 {len(out)} 个 .kt（目录结构变了？本脚本要跟着改）")
    return out


def block_between(text: str, start: str, end: str) -> str | None:
    """取一段（含头不含尾）。取不到返回 None —— 调用处**必须**报红，不许安静通过。"""
    i = text.find(start)
    if i < 0:
        return None
    j = text.find(end, i + len(start))
    return text[i:j] if j > i else None


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

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)[:60]!r}" if m else "")


def main() -> int:
    c = Checker()
    modules = read(MODULES)
    routes = read(ROUTES)
    navgraph = read(NAVGRAPH)
    workbench = read(WORKBENCH)
    settlement_screen = read(SETTLEMENT_SCREEN)
    settlement_vm = read(SETTLEMENT_VM)
    screen = read(SCREEN)
    vm = read(VM)
    person_screen = read(PERSON_SCREEN)
    presets = read(PRESETS)
    all_kt = read_all_kt()

    # ---- ① 入口只有一处 ----
    c.present("入口页那一格就是合并后的那一页（名字 + 路由落在结算页上）",
              modules, r'ModuleEntry\("司机账 · 运费结算", Routes\.FREIGHT_SETTLEMENT')
    c.absent("入口页里没有单独的「司机账」那一格（合并后叫「司机账 · 运费结算」）",
             modules, r'ModuleEntry\("司机账", ')
    n_entry = sum(len(re.findall(r'ModuleEntry\("司机账 · 运费结算", Routes\.FREIGHT_SETTLEMENT', t))
                  for t in all_kt.values())
    c.ok(f"全树挂「司机账 · 运费结算」的入口正好 1 处（实测 {n_entry}）", n_entry == 1,
         "多一处就是两个入口 = 两种时间口径，两边都看着对")
    m_title = re.search(r'AppTopBar\(\s*title = "([^"]+)"', settlement_screen)
    m_entry = re.search(r'ModuleEntry\("([^"]+)"[^\n]*?Routes\.FREIGHT_SETTLEMENT', modules)
    c.ok(
        "入口页那一格与结算页标题同名（实测 "
        + (m_entry.group(1) if m_entry else "?")
        + " / "
        + (m_title.group(1) if m_title else "?")
        + "）",
        m_title is not None and m_entry is not None and m_title.group(1) == m_entry.group(1),
        "同一件事在两处写的字符串不一样，用户会以为进了两个页面",
    )
    workbench_block = block_between(modules, "val dispatcherEntries", "val ledgerHomeEntries")
    c.ok("取到工作台网格那一段（取不到这条检查就是空转）",
         workbench_block is not None and len(workbench_block) > 200)
    if workbench_block:
        c.absent("工作台网格里没有「司机运费结算」那一格（用户 2026-10-07 要求合并）",
                 workbench_block, r"Routes\.FREIGHT_SETTLEMENT")
    c.absent("工作台页面上也没有那一格的痕迹", workbench, r'ModuleEntry\("司机运费结算"')

    # ---- ② 账本页只剩 3 档 ----
    ledger_block = block_between(modules, "val ledgerHomeEntries", "val shipperEntries")
    c.ok("取到入口页那一段（取不到这条检查就是空转）",
         ledger_block is not None and len(ledger_block) > 200)
    if ledger_block:
        labels = re.findall(r'ModuleEntry\("([^"]+)"', ledger_block)
        tabs = re.findall(r"Routes\.dispatcherLedger\((\d)\)", ledger_block)
        c.ok(f"入口页正好 7 格（实测 {len(labels)}）", len(labels) == 7, f"实际 {labels}")
        c.ok(f"3 类账各占一档，顺序 0/1/2（实测 {tabs}）", tabs == ["0", "1", "2"], f"实际 {tabs}")
    c.ok("全树不再有 dispatcherLedger(3) 这一档（司机账并走了）",
         not any(re.search(r"Routes\.dispatcherLedger\(3\)", t) for t in all_kt.values()),
         "老的第 4 档还在被生成")
    c.present("账本页的档位进来之后不再变，且越界的 tab 落回订单账",
              vm, r"var tab by mutableStateOf\(if \(initialTab in 0\.\.2\) initialTab else 0\)")
    c.absent("账本页的 VM 里没有司机那一档的数据源（driverAccounts/driverOrdersOf/driverPersonTotal）",
             vm, r"driverAccounts|driverOrdersOf|driverPersonTotal")
    c.absent("账本页与它的 VM 不许再挂「司机结算单」入口", screen + vm, r"onOpenSettlements|司机结算单")

    # ---- ③ 时间与账本页同一份 ----
    c.present("结算页点开的是账本页那一份档位弹层", settlement_screen, r"DateFilterDialogs\(")
    c.present("档位与区间都交给 VM（applyPreset / applyCustomRange）", settlement_screen,
              r"onPickPreset = \{ vm\.applyPreset\(it\) \},[\s\S]{0,120}?onApplyCustom = \{ f, t -> vm\.applyCustomRange\(f, t\) \},")
    c.present("时间在顶栏右上角的药丸里（口径词一直看得见）",
              settlement_screen, r"DatePresetPill\(label = vm\.periodLabel")
    c.present("默认档是「本月」那一档，且取自 DatePresets（不许自己拼月份串）", settlement_vm,
              r"var preset by mutableStateOf\(DatePresets\.THIS_MONTH\)")
    c.absent("全树都没有年月网格那套（2026-10-07 已并进账本那档位）",
             "\n".join(all_kt.values()), r"MonthPickerSheet\(|MonthCell\(|vm\.pickMonth\(")
    both_vm = settlement_vm + "\n" + vm
    n_rangeof = len(re.findall(r"DatePresets\.rangeOf\(", both_vm))
    c.ok(f"两页的档位 → 区间换算都读 DatePresets.rangeOf（实测 {n_rangeof} 处）", n_rangeof >= 2,
         "有一页自己拼月份/自己算区间了")
    c.present("宽边界定义在 ui/common/DatePresets.kt（唯一一份）", presets,
              r'const val WIDE_FROM = "2000-01-01"[\s\S]{0,240}?const val WIDE_TO = "2099-12-31"')
    n_wide = sum(len(re.findall(r"const val WIDE_FROM", s)) for s in all_kt.values())
    c.ok(f"宽边界常量全树只定义 1 处（实测 {n_wide} 处）", n_wide == 1, "又抄了一份（改一处漏一处）")
    c.present("结算页引用那一份宽边界", settlement_vm,
              r"DatePresets\.WIDE_FROM[\s\S]{0,160}?DatePresets\.WIDE_TO")
    c.absent("账本页没有自己抄一份宽边界", vm, r'"2000-01-01"|"2099-12-31"')
    c.absent("结算页没有自己抄一份宽边界", settlement_vm, r'"2000-01-01"|"2099-12-31"')

    # ---- ④ 取数不回流 ----
    c.present("结算页取数走 freightSettlementRange(from, to)", settlement_vm, r"repo\.freightSettlementRange\(")
    c.absent("结算页不再按月取数（freightSettlement(month) 那条老路不许回流）",
             settlement_vm, r"\.freightSettlement\(")

    # ---- ⑤ 明细就地展开 ----
    c.present("点一行是就地展开（toggleOrderDetail）", settlement_screen, r"vm\.toggleOrderDetail\(o\.orderId\)")
    c.present("展开块是共用的 OrderPeek（与账本页同一块）",
              settlement_screen, r"OrderPeek\(\s*loading = vm\.expandedOrderLoading")
    c.present("VM 里挂着展开态（expandedOrderId / expandedOrder / loading）", settlement_vm,
              r"expandedOrderId[\s\S]{0,400}?expandedOrderLoading")
    c.present("那一笔的取单接口与账本页同一个（container.repo.order）", settlement_vm, r"container\.repo\.order\(id\)")
    c.absent("明细行不再点一下直接跳订单详情页", settlement_screen, r"clickable \{ onOpenOrder\(o\.orderId\) \}")

    # ---- ⑥ 孤儿页救活 ----
    c.present("「司机结算（按月）」那一行有定义", settlement_screen, r"private fun SettlementSheetsRow\(")
    c.present("那一行真的挂在页面上（不是一段没人调的死代码）",
              settlement_screen, r"SettlementSheetsRow\(onOpenSettlements\)")
    c.present("NavGraph 把出口接到孤儿路由上", navgraph,
              r"onOpenSettlements = \{ navController\.navigate\(Routes\.DISPATCH_SETTLEMENTS\) \}")
    c.present("那条孤儿路由还注册着（救活的前提）", navgraph, r"composable\(Routes\.DISPATCH_SETTLEMENTS\)")
    c.present("路由常量还在", routes, r"const val DISPATCH_SETTLEMENTS =")

    # ---- ⑦ 司机那一层没有核销 ----
    n_settle = len(re.findall(r"openSettleAll\(|SettleAllDialog\(|submitSettleAll\(",
                              settlement_screen + settlement_vm))
    c.ok(f"合并页里数不到核销（实测 {n_settle} 处）", n_settle == 0,
         "司机那笔是「该给他多少」，不是应收 —— 给他挂一层核销就是把两个口径搞混")
    c.present("核销还在，只是活在账本页的人那一层（货主/批发商）", person_screen, r"fun SettleAllDialog\(")
    c.present("批量核销仍然必须先选中某个人", vm, r"if \(personKey == null \|\| tab == 0\) return")

    # ---- ⑧ 两个数分开 + 待定价照旧 ----
    c.present("司机应得取的是 payTotal（不是货主运费）", settlement_screen, r"formatMoney\(o\.payTotal\)")
    c.present("货主运费那一栏还在（运费 ¥ / 运费 待定价 两种写法）", settlement_screen,
              r'"运费 ¥"[\s\S]{0,160}?"运费 待定价"')
    c.present("待定价那一行还在（不分司机，也不在上面那张表里）", settlement_screen, r"unpricedNotice\(")
    c.present("「去定价」那一行的零件也在", settlement_screen, r"UnpricedNoticeRow\(")
    c.present("待定价的落点没变（Routes.FREIGHT_UNPRICED）", navgraph,
              r"onOpenUnpriced = \{ navController\.navigate\(Routes\.FREIGHT_UNPRICED\) \}")

    # ---- ⑨ 反空转 ----
    c.ok(f"全树读到 {len(all_kt)} 个 .kt（低于 40 说明目录结构变了）", len(all_kt) >= 40)
    c.ok("入口页那 7 格里真的解析出了格子（不是正则失配）",
         ledger_block is not None and len(re.findall(r'ModuleEntry\("', ledger_block)) == 7)

    print()
    if c.fails:
        print("❌ 没通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：入口只有一处 · 账本页 3 档 · 时间与账本同源 · 孤儿页救活 · 司机那层没有核销。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
