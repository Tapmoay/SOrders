# -*- coding: utf-8 -*-
"""我的账本顶上那张卡：支出段只在「全部」时画 ＋ 两个标签不再带括号（台账 L-17，2026-10-06）。

## 用户口径（原话，m00354）
「如果我在那个**货主选择**里选了**一个固定的人**，他那个**我欠公司的**是**不会显示**的，
只有**别人欠我的** …… 那个**括号都不应该存在**、括号都要**省略掉**，不要搞括号的内容，
就是「我该付的」和「我该收的」；当**选到固定货主**的时候，他**只会显示我该收的**，
就没有了，他下面就是那个**订单信息**。这是个 bug。」
2026-10-06 复述定稿（m00573）把这条钉成一句话：选「**全部**」时支出段要显示；选中**某个人**
时它**直接不显示**，下面接他的订单信息 —— 判据就是「**有没有选人**」，后端 `ledger_summary`
的过滤与 `is_member` 一个字都不用改。（台账里另外三种读法 —— "支出段真的没画出来" /
"只是要删括号" / "每人卡只显示欠我" —— 都**已作废**。）

## 机制：为什么这条会「看着像有、实际没有」
那张卡是**一段一段无脑往下画**的：支出块原来（`ui/shipper/ShipperLedgerScreen.kt` 的
:429-449）无条件渲染，只有收入块由 `if (s?.isMember == true)` 守着。于是选中某个货主之后，
卡片标题写着「这一段 · 江玉兰」、下面的列表也只剩他的单，**支出那一段却照旧画着**（数还是
"这一段"的）—— 用户看到的是"我欠公司的怎么不见了 / 怎么还在"两种读法都说得通的那种状态。
所以这一刀把闸门补齐：**选了人，支出段就不画**（闸门与标题**同一判据**）。

## 这一刀动什么 / 不动什么
- **动**：`TotalsCard` 的支出块加 `if (vm.isAllCustomers) { … }`；两段之间那条分隔线
  跟着同一闸门走（只剩一段时顶上横一条线像卡片缺了一块）；两个标签去掉括号。
- **不动**：后端（`_customer_filter` 同时喂支出与收入两侧，是既有设计）；
  两个方向的**钱口径**（`unpaid` / `unreceived` / 核销不互相写）；
  `if (s?.isMember == true)` 那道收入闸门；副行里 `"（" + s.settlements + " 笔核销）"`
  （那是**计数**，不是标签括号）；P25 与 CHG-0031 那两句**常显**口径句（提示开关默认关着，
  落回 `Hint` 等于页面上一个字都没有）；非会员那句「这里只有你欠公司的这一边」。

## 判据
1. 支出段的闸门 = `vm.isAllCustomers`（VM 里 `val isAllCustomers get() = selectedCustomer == null`，
   与标题 `vm.selectedCustomer?.let { "这一段 · " + it.name }` **同一判据**）；
2. 支出块那三行（标签 / `s?.unpaid` / 货款·已付副行）都在闸门**以内**；
3. 分隔线也在同一闸门以内；
4. 两个标签**不带括号**，带括号的老写法全仓**代码** 0 处（= 推翻 CHG-0026 的 P25 括号修法）；
5. 收入段仍由 `if (s?.isMember == true)` 守着，`isMember` 没被借来管支出段；
6. 没被顺手改掉的东西：计数括号 / 两句常显口径句（`Text(` 起步）/ 非会员那句 /
   `selectCustomer` 仍 `load()` / 后端零改动；
7. 既有红线随动对得上（`_check_report_metrics.py` 第 ③ 组已反转、
   `_reverse_verify_report_metrics.py` 第 ⑤ 条改成"括号挂回去"）；
8. 文档：`docs/changes/CHG-0052.md` 在、README 有行、`CHG-0026.md` 作为**历史快照原样保留**
   （推翻由新 CHG 声明，不回去改旧文档）；防静默空转（扫到的 .kt >= MIN_KT）。

## 为什么这条必须有机器的判据
「选中某人时别画那一段」是**一层 if**：删掉它不会有任何编译错误、不会有任何用例报红 ——
而 `_check_shipper_ledger_stats.py` 那类"数字对不对"的判据**全都照样通过**
（数字没变，变的是它**在什么时候被画出来**）。括号同理：`"支出 · 我该付的"` 与
`"支出 · 我该付的（欠公司）"` 都是合法字符串字面量，编译器一个字的意见都没有。
反向破坏用例见 `_reverse_verify_ledger_pay_block_gate.py`（17 条注入 ＋ 1 个新建文件）。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
闸门那条 `if` 的两边（画 / 不画）类型完全一样：`Text("支出 · 我该付的")` 在
"全部"与"某个人"两种状态下编译结果一模一样，后端返回的 `unpaid` 也一模一样
（它是**这一段**的应收应付，选谁都是同一个字段）——「选中人之后这段不该出现」是**这一页的展示
口径**，没有任何类型 / 接口 / 断言能表达它；标签括号同理，编译器只看见一个字符串。
所以判据只能钉源码结构（闸门锚点、三行与闸门的相对位置、全仓括号计数、随动文件里的口径行）。

用法：python _tools/qa/_check_ledger_pay_block_gate.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
# 注释剥离**只有一份实现**（那个状态机是为 "image/*" 这种字符串写的，抄一份必踩同一个坑）
from _check_product_card_single_source import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = AND / "ui/shipper/ShipperLedgerScreen.kt"
VM = AND / "ui/shipper/ShipperLedgerViewModel.kt"
BACKEND = ROOT / "backend/app/api/v1/shipper_ledger.py"
SHIP_STATS = ROOT / "_tools/qa/_check_shipper_ledger_stats.py"
REPORT_CHECK = ROOT / "_tools/qa/_check_report_metrics.py"
REPORT_REV = ROOT / "_tools/qa/_reverse_verify_report_metrics.py"
CHG = ROOT / "docs/changes/CHG-0052.md"
CHG26 = ROOT / "docs/changes/CHG-0026.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_ledger_pay_block_gate.py"

#: 全仓至少要有这么多 .kt（防「目录被搬走 → 一个都没扫到 → 全绿」）。
MIN_KT = 100
#: 半角双引号：源码里字符串字面量的定界符（**不能写成反斜杠转义**，见 _reverse_verify 的同类注释）。
DQ = chr(34)
#: 两个标签的**新**写法（L-17 起不带括号）与**老**写法（CHG-0026 的 P25；全仓代码必须 0 处）。
PAY_LABEL = "支出 · 我该付的"
PAY_LABEL_OLD = "支出 · 我该付的（欠公司）"
RECV_LABEL = "收入 · 我该收的"
RECV_LABEL_OLD = "收入 · 我该收的（下游欠我）"
#: P25 / CHG-0031 那两句**常显**口径句（判据 _check_report_metrics.py 也钉第一句）。
SAME_GOODS = "同一批货的两头，两边各记各的账，不会重复收钱。"
SAME_GOODS_2 = "两段互不影响：下面那本账怎么核销"
#: 支出块闸门的头两行（**缩进是判据的一部分**：这一段在 SectionCard 里，闸门在 8 空格那一层）。
PAY_OPEN = ("        if (vm.isAllCustomers) {" + chr(10)
            + "            Spacer(Modifier.height(6.dp))" + chr(10))
#: 收入段的闸门（本次一个字没动）。
MEMBER_GATE = "        if (s?.isMember == true) {" + chr(10)
#: 卡片那个函数的结束边界（用来算「这一段里 isMember 出现几次」）。
CARD_END = "/** 批发商：一个货主一张卡"
#: 换人必须重取统计（2026-09-22 真机实测抓到过的那条）。
SELECT_LOADS = r"fun selectCustomer\(key: String\?\) \{[^{}]*?\bload\(\)[^{}]*?\}"
REQUIRED_FILES = [SCREEN, VM, BACKEND, SHIP_STATS, REPORT_CHECK, REPORT_REV, CHG, README, CLAIM, REVERSE]


def read(p: Path) -> str:
    """读文本并**统一成 LF**（判据里有跨行锚点，CRLF 会让它们一处也匹配不上）。"""
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").replace(chr(13) + chr(10), chr(10))


def code(p: Path) -> str:
    return strip_comments(read(p))


def between(text: str, a: str, b: str) -> str:
    """`a` 之后、`b` 之前的那一段（用来问「这行在不在闸门里面」）。"""
    i = text.find(a)
    if i < 0:
        return ""
    j = text.find(b, i + len(a))
    return text[i : j if j >= 0 else len(text)]


def nearest_call(src: str, needle: str, span: int = 200) -> str:
    """这句文案最近的那个「被调用者」是谁（Text / Hint）—— 在它前面 span 字里找。

    为什么问「最近的调用」而不是「有没有出现过 Text(」：这一段上下全是 `Text(`，
    「出现过」永远为真（判据会空转）。真正要问的是：**这句挂在谁身上**。
    """
    i = src.find(needle)
    if i < 0:
        return ""
    head = src[max(0, i - span) : i]
    best, best_at = "", -1
    for n in ("Text(", "Hint("):
        at = head.rfind(n)
        if at > best_at:
            best_at, best = at, n
    return best


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
        self.ok(label, re.search(pattern, text) is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text) is None, f"不该出现却出现了 {pattern!r}")


def main() -> int:
    c = Checker()
    ship_raw = read(SCREEN)
    ship = code(SCREEN)
    vm_raw = read(VM)
    vm = code(VM)
    backend = read(BACKEND)
    kts = sorted(AND.rglob("*.kt"))
    ui = [(p.relative_to(ROOT).as_posix(), code(p)) for p in kts]

    print("== 1. 支出段的闸门：选中某个货主就不画（L-17 第一半） ==")
    c.ok("先确认读到了东西（否则下面每一条都是空转）", len(ship) > 1000 and len(vm) > 1000,
         f"ship={len(ship)} vm={len(vm)}")
    c.ok("支出块的头两行逐字：`if (vm.isAllCustomers) {` ＋ 12 空格缩进的 Spacer",
         PAY_OPEN in ship, "闸门不在支出块头上 —— 选中某人时这一段会又画出来")
    pay_body = between(ship, PAY_OPEN, MEMBER_GATE)
    c.ok("闸门以内的三行都在（标签 / 未付那个数 / 货款·已付副行）",
         ("                " + DQ + PAY_LABEL + DQ + ",") in pay_body
         and (DQ + "¥" + DQ + " + formatMoney(s?.unpaid ?: " + DQ + "0" + DQ + "),") in pay_body
         and (DQ + "货款 ¥" + DQ + " + formatMoney(s?.payable ?: " + DQ + "0" + DQ + ") + " + DQ
              + " · 已付 ¥" + DQ) in pay_body,
         "支出段有一行跑到闸门外面了（选中某人时会单独冒出来一行）")
    c.ok("闸门在收入段之前就收掉了（支出是独立一段，不是把两段一起包进去）",
         pay_body.rstrip().endswith("}"), "闸门没有收在 收入段 之前")
    c.ok("未付那个数还是 `s?.unpaid` ＋ `Color(PayableRed)`（钱口径没被顺手换）",
         ("s?.unpaid" in pay_body) and ("color = Color(PayableRed)," in pay_body))
    c.ok("分隔线也走同一闸门（只剩一段时不留一条悬空的线）",
         "            if (vm.isAllCustomers) HorizontalDivider(Modifier.padding(vertical = 10.dp))" in ship,
         "分隔线还无条件画着 —— 选中某人时卡片顶上会横一条线")
    c.ok("VM 里那个具名判据在：`val isAllCustomers get() = selectedCustomer == null`",
         ("    val isAllCustomers: Boolean" + chr(10)
          + "        get() = selectedCustomer == null") in vm,
         "闸门读的不是「有没有选人」那件事")
    c.ok("闸门与标题**同一判据**（标题也读 selectedCustomer）",
         "vm.selectedCustomer?.let { " + DQ + "这一段 · " + DQ + " + it.name } ?: " + DQ + "这一段" + DQ in ship,
         "标题换了判据 —— 会出现「写着某个人的名字、却画着全部的支出」")

    print("== 2. 收入那一段照旧：闸门不是「顺手把整张卡改了」 ==")
    c.ok("收入段仍由 `if (s?.isMember == true)` 守着", MEMBER_GATE in ship)
    c.ok("收入标签在（新写法）", ("                " + DQ + RECV_LABEL + DQ + ",") in ship)
    c.ok("收入那两个数没被换（`s.unreceived` ＋ `Color(ReceivableOrange)`）",
         (DQ + "¥" + DQ + " + formatMoney(s.unreceived),") in ship
         and "color = Color(ReceivableOrange)," in ship)
    totals = between(ship, "private fun TotalsCard(", CARD_END)
    c.ok("TotalsCard 里 `s?.isMember` 只出现一次（收入那道闸门，没被借来管支出）",
         totals.count("s?.isMember") == 1, f"实际 {totals.count('s?.isMember')} 次")
    c.ok("TotalsCard 里两处都读同一个判据（支出段 ＋ 分隔线）",
         totals.count("vm.isAllCustomers") >= 2, f"实际 {totals.count('vm.isAllCustomers')} 次")

    print("== 3. 括号不算数了（L-17 第二半：推翻 CHG-0026 的 P25 括号修法） ==")
    c.ok(f"支出标签逐字 {DQ}{PAY_LABEL}{DQ}（全仓代码恰好 1 处）",
         sum(1 for _n, s in ui if (DQ + PAY_LABEL + DQ) in s) == 1,
         "出现位置：" + "、".join(n for n, s in ui if (DQ + PAY_LABEL + DQ) in s))
    c.ok(f"收入标签逐字 {DQ}{RECV_LABEL}{DQ}（全仓代码恰好 1 处）",
         sum(1 for _n, s in ui if (DQ + RECV_LABEL + DQ) in s) == 1,
         "出现位置：" + "、".join(n for n, s in ui if (DQ + RECV_LABEL + DQ) in s))
    c.ok("带括号的老写法全仓代码 0 处（（欠公司）/（下游欠我））",
         all((DQ + PAY_LABEL_OLD + DQ) not in s and (DQ + RECV_LABEL_OLD + DQ) not in s for _n, s in ui),
         "仍在：" + "、".join(n for n, s in ui
                            if (DQ + PAY_LABEL_OLD + DQ) in s or (DQ + RECV_LABEL_OLD + DQ) in s))
    c.ok("方向词都还在（标签不是只剩一个 ¥ 数）",
         ("支出 · 我该付的" in ship) and ("收入 · 我该收的" in ship))
    c.ok(f"副行那个**计数**括号还在：{DQ}（{DQ} + s.settlements + {DQ} 笔核销）{DQ}",
         (DQ + "（" + DQ + " + s.settlements + " + DQ + " 笔核销）" + DQ) in ship,
         "把计数括号也一起删了 —— 那一句是数据，不是标签")
    c.ok("留痕：注释里点了台账 L-17 与用户那句「那个括号都不应该存在」",
         ("台账 L-17" in ship_raw) and ("那个括号都不应该存在" in ship_raw))

    print("== 4. 没被顺手改掉的东西（这一刀只碰卡片上那一段） ==")
    c.ok("P25 那句常显口径句仍在，且最近调用是 `Text(` 不是 `Hint(`",
         nearest_call(ship, SAME_GOODS) == "Text(",
         "最近调用是 " + (nearest_call(ship, SAME_GOODS) or "（找不到）") + " —— 提示开关默认关着")
    c.ok("CHG-0031 那句「两段互不影响」仍在，也是 `Text(` 起步",
         nearest_call(ship, SAME_GOODS_2) == "Text(",
         "最近调用是 " + (nearest_call(ship, SAME_GOODS_2) or "（找不到）"))
    c.ok("非会员那句解释还在（`_check_hint_key_explain.py` 钉它）",
         "这里只有你欠公司的这一边" in ship)
    c.ok("换人仍会重取统计（`selectCustomer` 里 `load()` 还在）",
         re.search(SELECT_LOADS, vm) is not None,
         "换人不重取 —— 标题换了、数字还是全部那一段的（2026-09-22 真机抓到过）")
    c.ok("`UNSET_CUSTOMER`「未指定货主」不过滤那一支还在", "UNSET_CUSTOMER" in vm)
    c.ok("后端这次一个字没改（展示口径没漏进服务端）",
         "isAllCustomers" not in backend, "服务端出现了客户端展示口径")
    c.ok("后端 `ledger_summary` 的过滤仍是两侧同一处 `_customer_filter`",
         "_customer_filter(stmt, customer_name, customer_phone)" in backend)
    c.ok("后端 `is_member` 仍在出参里（收入那条路没被动）", "is_member" in backend)

    print("== 5. 随动与文档对得上 ==")
    rc = read(REPORT_CHECK)
    c.ok("既有红线 `_check_report_metrics.py` 已把括号写法收成「老写法」常量",
         ("PAY_LABEL_OLD = " + DQ + PAY_LABEL_OLD + DQ) in rc,
         "老写法没有常量名 —— 下一个人会以为裸标签才是老写法")
    c.ok("它那条判据反过来钉了「括号不许再挂回」", "括号不许再挂回" in rc)
    c.ok("它的 docstring 记了这次推翻（台账 L-17）", "台账 L-17" in rc)
    rv = read(REPORT_REV)
    c.ok("反验 `_reverse_verify_report_metrics.py` 第 ⑤ 条改成「把括号挂回去」",
         (DQ + PAY_LABEL + DQ) in rv and (DQ + PAY_LABEL_OLD + DQ) in rv,
         "第 ⑤ 条还钉着老锚点（源码里已经找不到那段原文，注入会 SKIP）")
    stats = read(SHIP_STATS)
    c.ok("既有红线 `_check_shipper_ledger_stats.py` 那两个标签 present 仍在",
         ("支出 · 我该付的" in stats) and ("收入 · 我该收的" in stats))
    chg = read(CHG)
    c.ok("CHG-0052.md 在", len(chg) > 500, f"{len(chg)} 字符")
    c.ok("它点了台账 L-17 与用户那句「选到固定货主」",
         ("L-17" in chg) and ("选到固定货主" in chg))
    c.ok("它的 Boundary 结论逐字宣布 PRESENTATION（本事项没碰 Core）",
         "- **结论**：**PRESENTATION（展示层）**" in chg)
    c.ok("它记了「推翻 CHG-0026 的括号修法」这件事（不回去改旧 CHG）",
         ("CHG-0026" in chg) and ("（历史快照）**不改** —— 推翻由本文件声明。" in chg))
    c.ok("README 登记簿有 CHG-0052 行", "[CHG-0052.md](CHG-0052.md)" in read(README))
    c.ok("AI_WORK_CLAIM 有本事项条目", "会话：**CHG-0052" in read(CLAIM))
    c.ok("历史快照 `CHG-0026.md` 原样保留（推翻由新 CHG 声明，不回去改旧文档）",
         "（欠公司）" in read(CHG26), "旧 CHG 被改了 —— 历史快照改了就看不出裁定是怎么演进的")

    print("== 6. 防静默空转 ==")
    c.ok(f"扫到的 .kt 有 {len(kts)} 份（>= {MIN_KT}）", len(kts) >= MIN_KT)
    for p in REQUIRED_FILES:
        c.ok("关键文件在：" + p.relative_to(ROOT).as_posix(), p.exists())
    rvsrc = read(REVERSE)
    n_inj = rvsrc.count(chr(10) + "    (" + chr(10))
    c.ok("反验脚本在，且注入表至少 12 条", n_inj >= 12, f"实际 {n_inj} 条")

    print()
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print(f"  - {f}")
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
