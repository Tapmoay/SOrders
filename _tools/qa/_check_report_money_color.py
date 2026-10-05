# -*- coding: utf-8 -*-
"""红线：**报表中心金额配色**（CHG-0037，2026-10-05）—— 带负号的金额一律红。

## 用户原话（2026-10-05）
> 「哦我说的是如果是负的钱的话，就是欠钱，只要是带负号的都是用红色的，其他的用其他颜色
>  或者黑色都没关系。」「也就是那些金钱显示啊」

上一版（CHG-0036）把红收成了「欠钱」专用、亏损画橙。这一条把它改回来并推到所有金额显示：
**只要这个数带负号就是红**（v2 用 Palette.bad = #FF4D4F，老报表页沿用本页既有的 #E53935）。
正数随便 —— 用户原话「其他的用其他颜色或者黑色都没关系」。

## 为什么必须有一条机器判据
配色是全项目**唯一一处「谁都不觉得自己改过」的地方**：amountTone 里一个词就能把全站负数从红改回橙，
既没有编译错误、也没有接口变化，更没有第二处实现能互相对照；而它决定的正是
「老板一眼扫过去，哪几个数是坏的」。所以这里钉六层：

0. **反空转**：六个文件都在 + 两处金额渲染点数量下限（清单截空即红）；
1. **唯一判负函数**：amountTone 的负数分支必须是 Tone.BAD，且整个 v2 包里只有这一处判负；
2. **可变符号点必须显式判负**：税账留抵 / 「还能欠多少」/ 逐单欠款 / 司机待结
   —— 接口给什么符号就画什么色，不许拿另一个标志位替它决定颜色；
3. **结构减号行不许被连坐**：利润表里的「− 商品成本 / − 司机运费 / − 期间费用 / − 车辆折旧」
   值本身是**正数**，减号只是公式的运算符，必须保持中性色（红只给带负号的数，不给减号本身）；
4. **老页面三处「商品毛利」**：为负时不许再画绿（这正是用户看得见的那个数），同时老页面既有的
   「营业利润 / 净流入」正负上色一个字都不许被换掉；
5. **老页面「该交的增值税」**：留抵（进项比销项多）后端给的是**负数**，老页面原来把它当好事画绿
   （`ReportCenter.kt:1324` 经营利润卡 / `:1672` 税账页大数）—— 带负号 ⇒ 必须红；正数仍是本页的橙 #FF6B2C。

⛔ 已知盲区：这里只判「源码怎么写的」，判不了「用户在屏幕上看到的确实是红」—— 那一步靠模拟器
截图（CHG-0037.md ⑧ 的三张）；颜色够不够红（对比度）也不在这里判。

R4-BOUNDARY-JUSTIFICATION: 这一条**没法用边界消除** —— 「这个数该画什么颜色」不是类型属性：
正数 53.48 与负数 -127.49 走的是同一路 `Double` / `String`，同一个 `Tone` 枚举同时装得下红与橙，
把 `amountTone` 的负数分支写回 `Tone.WARN` 既不会编译失败、也不会让任何单测或接口契约翻红；
而且它**有两份实现**（v2 的 `amountTone` 与老报表页那几处 `if (x >= 0) 绿 else 红`），
用户看得见的正是这两份画出来的结果。所以只能扫「判负那一句到底写成什么色」
（`Tone.BAD` / `#E53935` 还是 `Tone.WARN` / `#00B578`），并把「结构减号行不许被连坐」
按清单挡住。反向破坏用例见 `_tools/qa/_reverse_verify_report_money_color.py`（14 条注入）。

用法：python _tools/qa/_check_report_money_color.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用兄弟红线里剥注释的实现（Kotlin 侧）—— 「代码里不许有 X」不能被自己的说明弄红。
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/report"
MODEL = PKG / "ReportV2Model.kt"
NODES = PKG / "ReportV2Nodes.kt"
HOME = PKG / "ReportV2Home.kt"
CENTER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"
REVERSE = ROOT / "_tools/qa/_reverse_verify_report_money_color.py"
DOC = ROOT / "docs/changes/CHG-0037.md"
REGISTRY = ROOT / "docs/changes/README.md"

#: 金额渲染点下限（改色只需要动几行，但这几行必须长在**真的在画钱**的文件里）
V2_FLOOR = 70
CENTER_FLOOR = 70
#: 利润表节点里保持中性色的行数下限（结构减号行 + 其它不需要上色的行）
UNSPECIFIED_FLOOR = 6

#: 结构减号行：标签 -> 那一段里必须仍是 Color.Unspecified
MINUS_ROWS = ("− 商品成本", "− 司机运费", "− 期间费用", "− 车辆折旧")

#: 老页面三处「商品毛利」的判负写法（两处 StatRow 文本完全相同，数它们出现 2 次）
GP_TONE = "if (profit >= 0) Color(0xFF00B578) else Color(0xFFE53935)"
GP_GREEN_ONLY = 'StatRow("商品毛利", "¥" + formatMoney(profit.toString()), Color(0xFF00B578))'


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit("找不到文件：" + str(p) + "（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


class Checks:
    def __init__(self) -> None:
        self.n = 0
        self.bad: list[str] = []

    def _tick(self, label: str, ok: bool, detail: str) -> None:
        self.n += 1
        if ok:
            print("  ✅ " + label)
        else:
            print("  ❌ " + label + " —— " + detail)
            self.bad.append(label)

    def present(self, label: str, hay: str, needle: str) -> None:
        self._tick(label, needle in hay, "找不到：" + repr(needle))

    def absent(self, label: str, hay: str, needle: str) -> None:
        self._tick(label, needle not in hay, "仍在（不该有的）：" + repr(needle))

    def present_re(self, label: str, hay: str, pattern: str) -> None:
        self._tick(label, re.search(pattern, hay) is not None, "匹配不上：" + repr(pattern))

    def absent_re(self, label: str, hay: str, pattern: str) -> None:
        self._tick(label, re.search(pattern, hay) is None, "还能匹配上：" + repr(pattern))

    def count(self, label: str, hay: str, needle: str, want: int) -> None:
        got = hay.count(needle)
        self._tick(label, got == want, "出现 " + str(got) + " 次，要 " + str(want) + " 次：" + repr(needle))

    def floor(self, label: str, got: int, least: int, what: str) -> None:
        self._tick(label, got >= least, what + " 只有 " + str(got) + " 个（下限 " + str(least) + "）—— 清单截空了？")


def main() -> int:
    print("报表中心金额配色（CHG-0037）：带负号的金额一律红")

    c = Checks()
    print("[0] 反空转：文件与渲染点")
    missing = [str(p) for p in (MODEL, NODES, HOME, CENTER, REVERSE, DOC, REGISTRY) if not p.exists()]
    c._tick("文件都在", not missing, "缺：" + "、".join(missing))
    model_raw = read(MODEL)
    nodes_raw = read(NODES)
    home_raw = read(HOME)
    center_raw = read(CENTER)
    doc_raw = read(DOC)
    registry_raw = read(REGISTRY)
    read(REVERSE)
    model = strip_comments(model_raw)
    nodes = strip_comments(nodes_raw)
    home = strip_comments(home_raw)
    center = strip_comments(center_raw)
    c.floor("渲染点", model.count("money(") + nodes.count("money(") + home.count("money("),
            V2_FLOOR, "报表中心 v2 三份文件里的 money( 调用")
    c.floor("渲染点", center.count("money("), CENTER_FLOOR, "老报表页 ReportCenter.kt 里的 money( 调用")

    print("[1] 唯一判负函数：amountTone")
    c.present("amountTone", model,
              "internal fun amountTone(v: Double): Tone = if (v < 0) Tone.BAD else Tone.GOOD")
    c.absent("amountTone", model, "if (v < 0) Tone.WARN")
    c.count("amountTone", model + nodes + home, "if (v < 0)", 1)
    c.present("Palette", model_raw, "val bad = Color(0xFFFF4D4F)")
    c.present("Palette", model_raw, "带负号的金额")
    c.present("Palette", model_raw, "如果是负的钱的话")
    c.absent("只给「欠钱」", model_raw, "只给「欠钱」")

    print("[2] 可变符号点必须显式判负")
    c.present("vatPayable", nodes, "if (num(t.vatPayable) < 0) Tone.BAD else Tone.INFO")
    c.present("还能欠多少", nodes, "val canStillOwe = num(row.creditAvailable)")
    c.present("还能欠多少", nodes, "if (canStillOwe < 0) Tone.BAD else Tone.GOOD")
    c.absent("还能欠多少", nodes, "if (row.overLimit) Tone.BAD else Tone.GOOD")
    c.present("逐单欠款", nodes, "toneColor(if (num(o.arrears) != 0.0) Tone.BAD else Tone.PLAIN)")
    c.present("司机待结", nodes, "toneColor(if (num(r.freightOwed) != 0.0) Tone.BAD else Tone.PLAIN)")
    c.absent("逐单欠款", nodes, "num(o.arrears) > 0")
    c.absent("司机待结", nodes, "num(r.freightOwed) > 0")

    print("[3] 结构减号行仍是中性色")
    for label in MINUS_ROWS:
        c.present_re("结构减号行", nodes,
                     re.escape('"' + label + '"') + r"[\s\S]{0,220}?Color\.Unspecified")
    c.absent_re("结构减号行", nodes, r'"− 商品成本"[\s\S]{0,220}?(Tone\.BAD|Palette\.bad)')
    c.floor("结构减号行", nodes.count("Color.Unspecified"), UNSPECIFIED_FLOOR, "利润表节点里的中性色行")
    c.present("结构减号行", center, 'StatRow("− 商品成本", money(data.costTotal))')

    print("[4] 老页面：商品毛利为负时不许画绿")
    c.count("商品毛利", center, GP_TONE, 2)
    c.present("商品毛利", center, "else if (profit < 0) Color(0xFFE53935) else Color(0xFF00B578),")
    c.present("商品毛利", center, "val gpColor = if (gp >= 0) Color(0xFF00B578) else Color(0xFFE53935)")
    c.absent("商品毛利", center, GP_GREEN_ONLY)

    print("[5] 老页面：留抵（该交的增值税为负）不许画绿")
    # 留抵 = 进项比销项多，后端给的数**带负号**（演示库实测 -127.49）。老页面原来把「留抵」当好事画绿，
    # 被 2026-10-05 的口径推翻：带负号 ⇒ 红；正数（真该交的税）仍是本页原有的橙 #FF6B2C。
    c.present("留抵", center,
              "if ((data.vatPayable.toDoubleOrNull() ?: 0.0) < 0.0) 0xFFE53935 else 0xFFFF6B2C")
    c.present("留抵", center, "if (payable < 0.0) Color(0xFFE53935) else Color(0xFFFF6B2C)")
    c.absent("留抵", center, "0xFF00B578 else 0xFFFF6B2C")

    print("[6] 老页面既有的正负上色一个字都没被换掉")
    c.present("opColor", center, "val opColor = if (op >= 0) Color(0xFF00B578) else Color(0xFFE53935)")
    c.present("净流入", center,
              "if (income - expense >= 0) Color(0xFF00B578) else Color(0xFFE53935)")

    print("[7] 文档与登记表")
    c.present("CHG-0037", doc_raw, "带负号的金额")
    c.present("CHG-0037", doc_raw, "如果是负的钱的话")
    c.present("登记表", registry_raw, "| `CHG-0037` | CHG |")

    print()
    if c.bad:
        print("❌ 报表中心金额配色（CHG-0037）：通过 " + str(c.n - len(c.bad)) + " 项，失败 "
              + str(len(c.bad)) + " 项 —— " + "、".join(sorted(set(c.bad))))
        return 1
    print("✅ 报表中心金额配色（CHG-0037）：通过 " + str(c.n) + " 项，失败 0 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
