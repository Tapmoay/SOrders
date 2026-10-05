# -*- coding: utf-8 -*-
"""红线：报表与账本上的数字都要自带口径（CHG-0026 / P20·P25·P26·P32，2026-10-03）。

## 这条是怎么来的
2026-10-03 的 E2E 走查（`_tmp/E2E测试报告.md`）在两个页面上抓到四件事，病根是同一个：
**数字算对了，口径没写在它旁边**，于是同一个数被读成另一件事。

- P20 报表中心 · 营业纵览：「待处理异常（近 30 天）」原来与「订单数 / 单均价 / 司机运费支出」
  挤在同一张「营业指标」卡里，那三行是**本期**（随顶栏时间药丸变），只有它带一句括号说明；
  四个数字并排、其中一个是 30 天窗口的，必然被读成「今天有 N 单异常」。
- P32 报表中心 · 客户经营：标签叫「客单价」，算的却是 订货总额 ÷ **客户数**（all.size）；
  客户数只有 1 家时它跟「订货笔数」那一行的金额一模一样，看着像同一个数算了两遍。
- P25 我的账本 · 卡片：「支出 · 我该付的」与「收入 · 我该收的」在批发商账号下**都是 ¥85.5**
  （同一批货的两头：他欠公司、下游货主又欠他）。标签里没有方向，唯一那句解释是 Hint，
  而提示开关默认是关的（core/HintPrefs.kt）—— 页面上一个字都没有。
  ⇒ 2026-10-06 台账 L-17（用户 m00354：「那个括号都不应该存在」）**推翻了 P25 的括号写法**：
    标签回到「支出 · 我该付的」/「收入 · 我该收的」，方向靠**方向词** ＋ 常显口径句体现。
    本判据第 ③ 组因此**反过来**钉：裸标签必须在、**括号不许再挂回去**。
- P26 我的账本 · 行：退货单的应收被**红冲成 0**（lineReceivableCents = 行金额 − 单价 × 已退数量），
  而那一格只看 remaining == 0 就写「已核销」，于是「已退货」的行被说成钱已收讫。

## 为什么必须有机器的判据
四条全是「文案 + 表达式」级别的改动，没有任何类型能拦住它们被改回去：
StatRow(客单价, money(totalAmount / all.size)) 与新标签类型完全一样；
else 已核销 与 RETURNED -> 已退货 · 账已冲平 也一样能编译、单测全绿。
所以判据只能盯**结构**：老标签必须消失（0 处也红）、两个「户均 / 每笔」的**分母必须不同**、
RETURNED 那一支必须排在 remaining > 0L 之前、方向标签必须带**方向词**且**不许带括号**
（括号写法 2026-10-06 被台账 L-17 推翻，见上面 P25 那条）、那句口径说明必须是常显 Text
（最近的那个调用不许是 Hint）、四句话**全库各只有一份**。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。P20 / P32 / P25 / P26 的病都不是「算错」，
而是「算对了但没写清楚口径」—— 后端返回的字段、Kotlin 的类型、单测的断言在这四处**全都一样**：
把 户均订货额 改回 客单价，把 when 三分支改回二选一，把常显 Text 改回 Hint，
编译器与 1136 条单测都不会有一句反对（上游 money 口径完全没变，变的只是这行字与那个分支顺序）。
所以只能扫源码结构：老标签 0 处、分母不同、分支顺序、最近调用是不是 Hint、四句话的唯一性。
运行时那一头交给 _tools/qa/_reverse_verify_report_metrics.py（按条注入破坏）与
2026-10-03 模拟器 5554（报表中心两张卡）＋ 5556（我的账本卡片与退货行）的实测截图。
本判据只读源码与文档（read()/code()），不连库、不 import 后端、不跑迁移。

用法：python _tools/qa/_check_report_metrics.py
     python _tools/qa/_check_report_metrics.py --list   # 只列它到底在查什么
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

REPORT = AND / "ui/dispatcher/ReportCenter.kt"
LEDGER = AND / "ui/shipper/ShipperLedgerScreen.kt"
HINTS = ROOT / "_tools/qa/_hint_inventory.py"
REVERSE = "_tools/qa/_reverse_verify_report_metrics.py"

#: 扫到的界面文件数下限（防目录改名 / 搬走之后「一个文件都没扫到」也算过）
MIN_UI_FILES = 100

#: 半角双引号：源码里的字符串字面量定界符（**不能写成反斜杠转义**，见 _reverse_verify 的同类注释）
DQ = chr(34)

#: P20：老的合并标签（口径与本期挤在一张卡）—— 全库必须 0 处
OLD_ANOMALY = "待处理异常（近 30 天）"
#: P20：新卡片的标题与标签（窗口必须写在标签里）
NEW_ANOMALY_TITLE = "待处理异常"
NEW_ANOMALY_LABEL = "近 30 天（与本页时间无关）"
#: 标题那一行的**调用点**：页面里「待处理异常」这四个字还出现在另一页的说明句里，
#: 所以窗口必须钉在 Text("待处理异常" 这个调用上（否则窗口会套到那句说明句上，判据空转）
ANOMALY_TITLE_CALL = "Text(" + DQ + NEW_ANOMALY_TITLE + DQ
#: 本期卡上的两行（P20 的窗口里不该再出现它们 —— 出现过就说明又挤回一张卡了）
PERIOD_ROWS = ["司机运费支出", "已撤销订单数"]

#: P32：老标签（分母是客户数，读作每单均价）—— 全库必须 0 处
OLD_AVG = "客单价"
PER_CUSTOMER = "户均订货额"
PER_ORDER = "每笔订货额"

#: P25：方向标签与那句**常显**口径说明
#: ⚠️ 2026-10-06 台账 L-17（用户 m00354）**推翻了 P25 的括号写法** —— 现在标签就是
#:    「支出 · 我该付的」/「收入 · 我该收的」（不带（欠公司）/（下游欠我））；
#:    方向靠**方向词**（支出/收入 ＋ 我该付的/我该收的）＋ 那句常显口径说明体现。
PAY_LABEL = "支出 · 我该付的"
PAY_LABEL_OLD = "支出 · 我该付的（欠公司）"
RECV_LABEL = "收入 · 我该收的"
RECV_LABEL_OLD = "收入 · 我该收的（下游欠我）"
SAME_GOODS = "同一批货的两头，两边各记各的账，不会重复收钱。"

#: P26：退货那一支的判词，与它替换掉的老表达式
RETURNED_WORD = "已退货 · 账已冲平"
OLD_SETTLE = ("if (remaining > 0) " + DQ + "未核销 ¥" + DQ
              + " + formatMoney(centsToMoney(remaining)) else " + DQ + "已核销" + DQ)


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def count(needle: str, text: str) -> int:
    return text.count(needle)


def hits(needle: str, sources: list[tuple[str, str]]) -> list[str]:
    """哪些文件里出现了这个字符串（用来问「全库是不是只有一份」）。"""
    return [name for name, src in sources if needle in src]


def window(src: str, needle: str, before: int, after: int) -> str:
    i = src.find(needle)
    if i < 0:
        return ""
    return src[max(0, i - before) : i + len(needle) + after]


def nearest_call(src: str, needle: str, span: int = 200) -> str:
    """这句文案最近的那个「被调用者」是谁（Text / Hint）—— 在它前面 span 字里找。

    为什么问「最近的调用」而不是「有没有出现过 Text(」：这一段上下都是 Text( 调用，
    「出现过」永远为真（判据会空转）。真正要问的是：**这句挂在谁身上**。
    """
    i = src.find(needle)
    if i < 0:
        return ""
    head = src[max(0, i - span) : i]
    best = ""
    best_at = -1
    for n in ("Text(", "Hint("):
        at = head.rfind(n)
        if at > best_at:
            best_at = at
            best = n
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

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def main() -> int:
    if refuse_if_injecting("报表 / 账本口径检查"):
        return 1

    c = Checker()
    print("报表与账本上的数字自带口径（CHG-0026 / P20·P25·P26·P32）：2026-10-03")

    ui_files = sorted(AND.rglob("*.kt"))
    sources = [(p.relative_to(AND).as_posix(), code(p)) for p in ui_files]
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(ui_files) >= MIN_UI_FILES,
        f"实际 {len(ui_files)}",
    )

    for p, why in ((REPORT, "报表中心（P20 待处理异常 / P32 户均与每笔）"),
                   (LEDGER, "我的账本（P25 方向标签 / P26 退货行的收款状态）")):
        c.ok(f"{p.relative_to(ROOT).as_posix()} 存在（{why}）", p.exists(), "文件被搬走 / 改名了")

    rep = code(REPORT)
    led = code(LEDGER)

    # ---- 1. P20：30 天窗口不许再与本期同一张卡 ----
    c.ok(
        f"老的合并标签 {DQ}{OLD_ANOMALY}{DQ} 全库 0 处（口径不许再与本期挤一张卡）",
        all(OLD_ANOMALY not in src for _n, src in sources),
        "还在：" + "、".join(hits(OLD_ANOMALY, sources)),
    )
    c.ok(
        f"新的独立标签 {DQ}{NEW_ANOMALY_LABEL}{DQ} 全库恰好 1 处（且在本页）",
        hits(NEW_ANOMALY_LABEL, sources) == ["ui/dispatcher/ReportCenter.kt"]
        and count(ANOMALY_TITLE_CALL, rep) == 1,
        "实际出现在：" + "、".join(hits(NEW_ANOMALY_LABEL, sources))
        + f"；标题调用 {count(ANOMALY_TITLE_CALL, rep)} 处",
    )
    w = window(rep, NEW_ANOMALY_LABEL, 200, 200)
    c.ok(
        "那个数仍然在（pendingExceptionCount 没被顺手删掉）",
        "pendingExceptionCount" in w,
        "标签前后 200 字里找不到 pendingExceptionCount",
    )
    c.ok(
        "它现在挂在**自己的小节卡**里（窗口里有 SectionCard，且没有本期那几行）",
        ("SectionCard" in window(rep, ANOMALY_TITLE_CALL, 160, 0))
        and all(x not in window(rep, ANOMALY_TITLE_CALL, 200, 400) for x in PERIOD_ROWS),
        "窗口里看不到 SectionCard，或仍与 " + " / ".join(PERIOD_ROWS) + " 同卡",
    )

    # ---- 2. P32：两个名字，两个分母 ----
    c.ok(
        f"老标签 {DQ}{OLD_AVG}{DQ} 全库 0 处（分母是客户数，不该叫客单价）",
        all(OLD_AVG not in src for _n, src in sources),
        "还在：" + "、".join(hits(OLD_AVG, sources)),
    )
    c.ok(
        f"{DQ}{PER_CUSTOMER}{DQ} 与 {DQ}{PER_ORDER}{DQ} 各 1 处（两种读法都写实）",
        count(PER_CUSTOMER, rep) == 1 and count(PER_ORDER, rep) == 1,
        f"实际 {count(PER_CUSTOMER, rep)} / {count(PER_ORDER, rep)}",
    )
    w1 = window(rep, PER_CUSTOMER, 0, 140)
    w2 = window(rep, PER_ORDER, 0, 140)
    c.ok(
        "两个分母**确实不同**（户均 ÷ 客户数 all.size；每笔 ÷ 订单数 totalCount）",
        ("all.size" in w1) and ("totalCount" not in w1) and ("totalCount" in w2) and ("all.size" not in w2),
        "两行用了同一个分母（又变成同一个数算两遍）",
    )

    # ---- 3. P25：方向标签 + 常显口径句（括号写法已被 2026-10-06 台账 L-17 推翻）----
    c.ok(
        f"支出标签带方向词 {DQ}{PAY_LABEL}{DQ}（L-17 起不带括号）",
        PAY_LABEL in led,
        "支出标签连方向词都没了（只看一个 ¥ 数，看不出这笔钱是付出的还是收进的）",
    )
    c.ok(
        f"收入标签带方向词 {DQ}{RECV_LABEL}{DQ}（L-17 起不带括号）",
        RECV_LABEL in led,
        "收入标签连方向词都没了",
    )
    c.ok(
        "括号不许再挂回两个标签上（2026-10-06 台账 L-17 / 用户 m00354「那个括号都不应该存在」）",
        all((DQ + PAY_LABEL_OLD + DQ) not in src and (DQ + RECV_LABEL_OLD + DQ) not in src for _n, src in sources),
        "仍在：" + "、".join(hits(DQ + PAY_LABEL_OLD + DQ, sources) + hits(DQ + RECV_LABEL_OLD + DQ, sources)),
    )
    c.ok(
        f"口径句全库恰好 1 处（两段卡片共用一句，不许各写各的）：{SAME_GOODS}",
        hits(SAME_GOODS, sources) == ["ui/shipper/ShipperLedgerScreen.kt"],
        "实际出现在：" + "、".join(hits(SAME_GOODS, sources)),
    )
    c.ok(
        "那句是**常显**的（最近的那个调用是 Text( 而不是 Hint(）",
        nearest_call(led, SAME_GOODS) == "Text(",
        "最近调用是 " + (nearest_call(led, SAME_GOODS) or "（找不到）") + " —— 提示开关默认关着，藏起来等于没有",
    )
    c.ok(
        "它在会员分支里（只有批发商同时有两段，才需要这句话）",
        led.find("vm.isMember") >= 0 and led.find("vm.isMember") < led.find(SAME_GOODS),
        "找不到 vm.isMember，或口径句跑到了会员分支之前",
    )
    hint_src = read(HINTS)
    c.ok(
        "分类器复核表认了这句（_hint_inventory.py 的 OVERRIDE，判 DATA）",
        "同一批货的两头" in hint_src,
        "_tools/qa/_hint_inventory.py 的 OVERRIDE 里没有这一条 —— 重生成提示目录时会把它算成可藏的解释句",
    )

    # ---- 4. P26：退货那一支必须排在前面，且说的是冲平不是收讫 ----
    i_ret = led.find(DQ + RETURNED_WORD + DQ)
    i_pos = led.find("remaining > 0L ->")
    i_else = led.find("else -> " + DQ + "已核销" + DQ)
    c.ok(
        "when 的三支都在（退货 / 还有未核销 / 真的收讫）",
        i_ret > 0 and i_pos > 0 and i_else > 0,
        f"下标 {i_ret} / {i_pos} / {i_else}",
    )
    c.ok(
        "退货那一支排在 remaining > 0L **之前**（顺序反了就永远不会命中退货单）",
        i_ret > 0 and i_pos > i_ret,
        f"退货支 {i_ret} 排在未核销支 {i_pos} 之后",
    )
    c.ok(
        f"判词 {DQ}{RETURNED_WORD}{DQ} 全库恰好 1 处，且挂在 Text( 上",
        hits(RETURNED_WORD, sources) == ["ui/shipper/ShipperLedgerScreen.kt"]
        and nearest_call(led, RETURNED_WORD) == "Text(",
        "出现在：" + "、".join(hits(RETURNED_WORD, sources))
        + "；最近调用 " + (nearest_call(led, RETURNED_WORD) or "（找不到）"),
    )
    c.ok(
        "老的两选一表达式全库 0 处（remaining == 0 就写已核销）",
        all(OLD_SETTLE not in src for _n, src in sources),
        "还在：" + "、".join(hits(OLD_SETTLE, sources)),
    )
    c.ok(
        f"诚实的那一支还在（{DQ}已核销{DQ} 与橙色未核销都没被删掉）",
        (DQ + "已核销" + DQ) in led and "Color(ReceivableOrange)" in led,
        "把「已核销」或橙色未核销一起删掉了 —— 那不是修口径，是把情况藏起来",
    )

    # ---- 5. 配对：反向验证 + 本文自己的边界理由 ----
    c.ok("这条红线配了反向验证脚本", (ROOT / REVERSE).exists(), f"找不到 {REVERSE}")
    c.ok(
        "本判据写了边界理由（_check_r3_constraints.py 的检查器预算闸要求 R4-BOUNDARY-JUSTIFICATION）",
        "R4-BOUNDARY-JUSTIFICATION:" in read(Path(__file__)),
        "模块 docstring 里没有 R4-BOUNDARY-JUSTIFICATION 段",
    )

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · P20：待处理异常（近 30 天）这个合并标签全库 0 处；新标签单独一张卡，窗口写在标签里")
        print("     · P32：客单价全库 0 处；户均订货额 ÷ 客户数、每笔订货额 ÷ 订单数，两个分母必须不同")
        print("     · P25：两个标签都带方向括号；那句口径说明全库只有一份，且是常显 Text（不是 Hint）")
        print("     · P26：退货单的收款状态 = 已退货 · 账已冲平，排在 remaining > 0L 之前；老的两选一表达式 0 处")
        print("     · 四句话的唯一性 + 反向验证脚本在 + 本文自己的边界理由在")

    return c.report("报表 / 账本口径（CHG-0026 / P20·P25·P26·P32）")


if __name__ == "__main__":
    sys.exit(main())
