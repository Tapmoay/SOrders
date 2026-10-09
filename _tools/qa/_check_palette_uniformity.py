#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作台配色「低饱和但不发灰」—— 明度、彩度、色相三条底线（CHG-0102）。

用户要的是什么（ref `m04527`，逐字）：

    「呃我觉得饱和度还是太低了一点不也不说饱和度吧，应该说太灰了一点。整天都饱和度或者说
     是明度吧，应该叫做明度。他们并不是完全都是一致的只是在一个区间内。就像是色彩理论一
     样啊，我们现在一看好看的话，它所有的呃比如说我们一般评价一个画它比较偏低，饱和但是
     整体的色调又统一且看的舒适是这样子的这样，它又是怎么做到的呢？我们就以工作台的所有
     那些功能的图标为例子，你做一份简单的html样式做给我看并且最后呃发送给我网站地址」

然后他从三档里点了名（ref `m04677`，逐字）：

    「算了，算了，还是用这个吧推荐 / 相对彩度 0.62、明度带 58±5、彩度夹 28~44。」

## 为什么这条必须有机器的判据

因为它坏起来**不报错、不崩溃、界面照样能点**：

1. 有人把某一格换回「照参考图取色」的高彩度值 —— 那一格立刻比同屏其它格艳一倍，
   同屏「一套」的感觉没了（CHG-0101 就是这个病：最艳 58.4 / 最灰 8.1 ＝ **7.2 倍**）。
2. 有人为了「统一」把彩度整体压到底 —— 19 格全变成灰的，用户第二轮会再说一次「太灰」。
3. 有人只改一个 token 的**色相**去躲「两格太像」 —— 色相是身份，撞了就是两个功能看起来
   是同一个（`_check_low_sat_palette.py` 管值，这条管**它们之间的相对关系**）。
4. 有人把 `PaletteUniformity.kt` 里的 Lab 换算写错（sRGB 忘了先去 gamma）—— 算出来的
   明度极差会假性变小，三条判据全绿而屏幕上依旧是花的。
5. 有人把 `PaletteUniformityTest.kt` 的阈值放宽（12 → 30）来「让它过」—— 这条脚本按
   阈值本身的数值钉住它。
6. 有人把新加的一格塞进宫格却忘了给它一个和邻居分得开的色 —— 明度极差/彩度比会当场抖出来。
7. 有人把「明度带」当成「每一格都必须一样亮」 —— 那会回到 CHG-0091 之前那种「一排同色
   深浅」的死板；判据里的极差是**上界**，不是「必须相等」。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事

色值是 `Long`（裸 ARGB）或 `Color`，两者之间**没有类型差** —— `#DE7C81` 与 `#8B4A4A` 在
类型系统里是同一个东西。编译器、detekt、Kotlin 的类型检查都**不可能**表达「这 19 个值
必须落在同一条明度带里、最艳与最灰不许差过 2 倍」。这条性质只在**值的集合**上成立，
只能在「把 19 个值读出来、算一遍」的地方守 —— 也就是这里和 `PaletteUniformityTest.kt`。

本脚本**只读工作区里的文件**，不编译、不跑 UI、不连设备（这是它能进 `_check_all.py` 的前提）。

## 判据

0. 反空转：扫描本身得是活的（`.kt` 数 ≥ 100；四张表格数正确）
1. `PaletteUniformity.kt` 的纯函数都在（Lab 换算 ＋ 三条度量 ＋ 距离）
2. `PaletteUniformityTest.kt` 七档都在，且阈值与本文档一致
3. 派单端 19 格：逐个点名、顺序也要对（就是 H 档那 19 个值）
4. 派单端 19 格的三条硬指标（**用 Python 独立算一遍 Lab**，交叉验证 Kotlin 那份）
5. 货主端 8 格与账本页 7 格：同样三条指标
6. 设计系统 §4.25h 与用户口径留档
7. 配套：反验脚本在、`CHG-0102.md` 有 Blast Radius

用法：
    python _tools/qa/_check_palette_uniformity.py
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
COLOR = AND / "ui/theme/Color.kt"
MODULES = AND / "ui/nav/Modules.kt"
UNIFORMITY = AND / "ui/theme/PaletteUniformity.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/theme/PaletteUniformityTest.kt"
DOC = ROOT / "docs/changes/CHG-0102.md"
REG = ROOT / "docs/changes/README.md"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_palette_uniformity.py"

#: 静默空转保护：源码被搬走/清空时，判据不许「无一可查所以全绿」
MIN_KT = 100

MODULE_TABLES = {
    "dispatcherEntries": 19,
    "ledgerHomeEntries": 7,
    "shipperEntries": 8,
    "driverEntries": 2,
}

#: H 档（用户点名的那一档）：`relative chroma 0.62 / L* 58±5 / chroma clamp 28~44`
#:
#: ⚠️ CHG-0105（2026-10-10）**只还色相**：每个颜色的 L\* / C\* 仍取 H 档那一套，
#:    色相回到 CHG-0101 之前的老色相（用户：「……来调整它们的明度或者说是饱和度，
#:    但是**不要调整它们的色相**啊」）。下面这三张表是**按现值重锚过的**。
DISPATCHER_LABELS = [
    "代理下单", "预订单", "地址与联系人", "订单管理", "退货申请",
    "账户管理", "司机管理", "货主管理", "批发商管理", "商品管理",
    "发票台账", "库存管理", "账本管理", "车辆管理", "运费模板",
    "计费规则", "挂账单位", "报表中心", "消息中心",
]
DISPATCHER_HEX = [
    "49A67A", "7A98D8", "4CA0BC", "908643", "D97C65",
    "A2763D", "7E8338", "3F8F81", "BA8F4A", "A587D4",
    "CF8855", "278A9D", "AF7C4D", "4AA5A7", "5387B1",
    "939F4E", "BA6947", "8075C0", "DE7C81",
]
SHIPPER_HEX = ["8D7A3C", "49A67A", "4CA0BC", "C29750", "DE7C81", "BC5A58", "A76BAF", "4285F4"]
LEDGER_HEX = ["C78A4F", "4A8A4E", "5BA592", "8A7339", "9C8AD7", "537BC6", "CB6587"]

#: 三条硬指标（数字全部是实测值留一点余量，⛔ 不是「大概齐」）
DISP_SPREAD_MAX = 12.0      # 实测 10.1（CHG-0091 是 51.8、CHG-0101 是 25.6）
SHIP_SPREAD_MAX = 16.0      # 实测 14.8
LEDGER_SPREAD_MAX = 15.0    # 实测 13.2
CHROMA_FLOOR = 27.0         # 实测最灰 27.8
CHROMA_RATIO_MAX = 2.0      # 实测 1.6（CHG-0101 是 7.2 倍）

#: 品牌色不参与「彩度落差」那条（AI 助手是 Google 那颗蓝，用户点名保留）
BRAND_EXEMPT_BY_ROUTE = {"ai/chat"}


class Checker:
    def __init__(self) -> None:
        self.passes = 0
        self.fails: list[str] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + label)
        else:
            self.fails.append(label)
            print("  [FAIL] " + label + ("  —— " + detail if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        # ⚠️ 一律带 `re.M`：变更单 / 登记簿那几条判据是按**行首**（`^- **Blast Radius**`、
        #    `^\| \`CHG-0102\` |`）找的，不带 M 的话 `^` 只认整份文本的开头 —— 会假红。
        self.ok(label, re.search(pattern, text, re.M) is not None, "没找到：%s" % pattern)

    def absent(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text, re.M) is None, "还留着：%s" % pattern)

    def report(self, title: str) -> int:
        print("\n" + "=" * 60)
        if self.fails:
            print("❌ %d 项未通过（通过 %d 项）：" % (len(self.fails), self.passes))
            for f in self.fails:
                print("   - " + f)
            return 1
        print("✅ 全部 %d 项通过 —— %s" % (self.passes, title))
        return 0


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit("找不到文件：%s（被改名/搬走了？这条判据要跟着改）" % p)
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def slice_section(text: str, heading: str) -> str:
    """切出某一个 `### …` 小节（到下一个 `### ` / `## ` 之前）。

    ⛔ 切不出来就返回空串 —— 让上面那条「切出了这一节」的判据**当场红**，
    而不是悄悄退化成"整份文件里搜一下"（那样这一节被删空了判据照样绿）。
    """
    i = text.find(heading)
    if i < 0:
        return ""
    ends = [j for j in (text.find("\n### ", i + len(heading)),
                        text.find("\n## ", i + len(heading))) if j > 0]
    j = min(ends) if ends else len(text)
    return text[i:j]


# ---------------------------------------------------------------- Lab 换算
def _lin(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lab(argb: int) -> tuple[float, float, float]:
    """sRGB(ARGB) -> CIE L*a*b*（D65）。⛔ 与 `PaletteUniformity.kt` 同一套公式。"""
    r = _lin((argb >> 16) & 0xFF)
    g = _lin((argb >> 8) & 0xFF)
    b = _lin(argb & 0xFF)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 216.0 / 24389.0 else (841.0 / 108.0) * t + 4.0 / 29.0

    fx, fy, fz = f(x), f(y), f(z)
    return 116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


def lightness(argb: int) -> float:
    return lab(argb)[0]


def chroma(argb: int) -> float:
    _, a, b = lab(argb)
    return math.hypot(a, b)


def spread(colors: list[int]) -> float:
    ls = [lightness(c) for c in colors]
    return max(ls) - min(ls)


def chroma_ratio(colors: list[int]) -> float:
    cs = [chroma(c) for c in colors]
    return max(cs) / min(cs) if min(cs) > 0 else 999.0


# ---------------------------------------------------- Modules.kt 表格解析
def parse_module_tables(text: str) -> dict[str, list[tuple[str, str]]]:
    """`Modules.kt` -> `{表名: [(格子名, 颜色原文), …]}`。

    ⚠️ 这里**故意不用正则**，全部用字符串操作（`find` / `split` / `partition`）。
    表头长这样 —— `    val dispatcherEntries: List<ModuleEntry> = listOf(`，表体是"一行一格"。
    ⛔ 别把表头写成 `"val dispatcherEntries = listOf("` —— 那行里 `val` 与 `=` 之间还有
    `: List<ModuleEntry>` 这个类型标注，那个 marker 根本不可能命中。
    ⛔ 表尾＝下一个**四空格缩进的 `val `**（`driverEntries` 之后还有
    `    val ENTRY_CAPABILITY: … = mapOf(` 之类的声明，中间夹着别的 `ModuleEntry(`，
    只找"下一个模块表"会把司机端 2 格数成 5 格）。
    """
    heads: list[tuple[str, int]] = []
    for name in MODULE_TABLES:
        marker = "val " + name
        pos = text.find(marker)
        while pos >= 0:
            nxt = text[pos + len(marker):pos + len(marker) + 1]
            after = text[pos + len(marker):pos + len(marker) + 3]
            if nxt == ":" or after == " = ":
                heads.append((name, pos))
                break
            pos = text.find(marker, pos + 1)
    heads.sort(key=lambda h: h[1])

    out: dict[str, list[tuple[str, str]]] = {}
    for name, start in heads:
        end = len(text)
        base = start + 1
        for off in range(len(text) - base):
            if text[base + off] != "\n":
                continue
            if text.startswith("    val ", base + off + 1):
                end = base + off
                break
        rows: list[tuple[str, str]] = []
        label = ""
        # ⚠️ 格子有两种写法，都得认：
        #   ① 一行一个：`ModuleEntry("挂账单位", Routes.…, color = ArrearsTangerine),`
        #   ② 多行具名参数（`报表中心` / `AI 助手` / `司机账 · 运费结算`）
        for line in text[start:end].split("\n"):
            s = line.strip()
            if s.startswith("ModuleEntry("):
                label = ""
                q1 = s.find('"')
                if q1 >= 0:
                    q2 = s.find('"', q1 + 1)
                    if q2 > q1:
                        label = s[q1 + 1:q2]
            elif s.startswith(")"):
                label = ""
                continue
            if label == "" and 'label = "' in s:
                q1 = s.find('label = "')
                q2 = s.find('"', q1 + 9)
                if q2 > q1:
                    label = s[q1 + 9:q2]
            if "color = " in s:
                _, _, tail = s.partition("color = ")
                cut = len(tail)
                for ch in (")", ",", "/"):
                    j = tail.find(ch)
                    if j >= 0:
                        cut = min(cut, j)
                rows.append((label, tail[:cut].strip()))
                label = ""
        out[name] = rows
    return out


def color_tokens(text: str) -> dict[str, int]:
    """`Color.kt` -> `{token 名: ARGB}`。

    ⚠️ token 的写法三种并存（裸 ARGB / 带 `L` 后缀 / `Color(0x…)`），所以这里**只认
    `0x` 后面那 8 位**，别去钉 `L`。
    """
    out: dict[str, int] = {}
    for line in text.split("\n"):
        s = line.strip()
        if not s.startswith("val ") or "=" not in s:
            continue
        name, _, tail = s[4:].partition("=")
        name = name.strip()
        i = tail.find("0x")
        if i < 0:
            continue
        hx = tail[i + 2:i + 10]
        if len(hx) == 8 and all(c in "0123456789abcdefABCDEF" for c in hx):
            out[name] = int(hx, 16)
    return out


def resolve(raw: str, tokens: dict[str, int]) -> int | None:
    if raw.startswith("0x") or raw.startswith("0X"):
        return int(raw[2:10], 16)
    return tokens.get(raw)


def main() -> int:
    c = Checker()

    kt = list(AND.rglob("*.kt"))
    print("== 0. 反空转：扫描本身得是活的 ==")
    c.ok("扫到 %d 个 .kt（下限 %d）" % (len(kt), MIN_KT), len(kt) >= MIN_KT, "源码树被搬走了？")

    color = read(COLOR)
    modules = read(MODULES)
    grids = parse_module_tables(modules)
    tokens = color_tokens(color)
    for name, least in MODULE_TABLES.items():
        got = len(grids.get(name, []))
        c.ok("%s 解析出 %d 格（下限 %d）" % (name, got, least), got >= least,
             "解析器坏了 / 表格被拆了（⛔ 别改判据去迁就它）")

    print("\n== 1. 纯函数：Lab 换算与三条度量，都在 PaletteUniformity.kt 里 ==")
    uni = read(UNIFORMITY)
    for sig in (
        "internal fun labLightness(argb: Long): Double",
        "internal fun labChroma(argb: Long): Double",
        "internal fun lightnessSpread(colors: List<Long>): Double",
        "internal fun weakestChroma(colors: List<Long>): Double",
        "internal fun argbGap(a: Long, b: Long): Double",
        "internal fun closestPair(",
        "internal fun relativeChroma(argb: Long, maxChroma: Double): Double",
        "internal fun hueDistance(argbA: Long, argbB: Long): Double",
    ):
        c.ok("PaletteUniformity.kt 里有 `%s`" % sig, sig in uni, "被改名/删了？")

    print("\n== 2. 单测：七档都在，阈值与文档一致 ==")
    test = read(TEST)
    # ⚠️ 钉的是**整条 `fun \`…\`` 声明**，不是名字里的一小段 —— 名字里那一小段在注释里
    #    也可能出现，那样「把阈值改成 30」这种注入就抓不住了（踩过：注入只改到注释）。
    for name in (
        "fun `派单端那 19 格的明度极差不超过 12（用户说的「在一个区间内」）`",
        "fun `货主端 8 格的明度极差不超过 16`",
        "fun `账本管理入口页 7 格的明度极差不超过 15`",
        "fun `派单端那 19 格，最没颜色的那一格彩度也不低于 27`",
        "fun `货主端与账本页的彩度地板同样成立`",
        "fun `同屏里最艳与最不艳的两格，彩度差不超过 2 倍`",
        "fun `派单端 19 格两两距离都不低于 20（够不上 60 的约束，但也不许几乎同色）`",
    ):
        c.ok("单测里有「%s」" % name, name in test, "这一档被删/改名/放宽了")

    print("\n== 3. 派单端 19 格：逐个点名（就是 H 档那 19 个值） ==")
    disp = grids.get("dispatcherEntries", [])
    for label, want in zip(DISPATCHER_LABELS, DISPATCHER_HEX):
        got = [hx for lb, raw in disp
               if lb == label and (hx := resolve(raw, tokens)) is not None
               and "%06X" % (hx & 0xFFFFFF) == want]
        c.ok("派单端「%s」= #%s" % (label, want), len(got) == 1,
             "对不上（真值：%s）" % [(lb, raw) for lb, raw in disp if lb == label])
    c.ok("派单端格数就是 19（多一格少一格都得说出来）", len(disp) == 19, "现在 %d 格" % len(disp))

    print("\n== 4. 派单端 19 格的三条硬指标（Python 独立算一遍 Lab） ==")
    disp_colors = [v for _, raw in disp if (v := resolve(raw, tokens)) is not None]
    c.ok("19 格都能解析成 ARGB（没有认不出的 token）", len(disp_colors) == 19,
         "解析出 %d 个" % len(disp_colors))
    if len(disp_colors) == 19:
        s = spread(disp_colors)
        c.ok("明度极差 %.1f ≤ %.0f（统一的是明度）" % (s, DISP_SPREAD_MAX), s <= DISP_SPREAD_MAX,
             "回到了「有的很亮有的很沉」")
        wc = min(chroma(cc) for cc in disp_colors)
        c.ok("最灰的一格彩度 %.1f ≥ %.0f（低饱和 ≠ 发灰）" % (wc, CHROMA_FLOOR), wc >= CHROMA_FLOOR,
             "有格子掉进灰色了")
        r = chroma_ratio(disp_colors)
        c.ok("最艳/最灰 %.2f 倍 ≤ %.1f 倍（CHG-0101 是 7.2 倍）" % (r, CHROMA_RATIO_MAX),
             r <= CHROMA_RATIO_MAX, "同屏彩度落差又拉开了")
        c.ok("19 格两两互异（没有两格一模一样）", len(set(disp_colors)) == 19, "有重复")

    print("\n== 5. 货主端 8 格与账本页 7 格：同样三条指标 ==")
    ship = grids.get("shipperEntries", [])
    ship_colors = [v for _, raw in ship if (v := resolve(raw, tokens)) is not None]
    c.ok("货主端 8 格都能解析", len(ship_colors) == 8, "解析出 %d 个" % len(ship_colors))
    if len(ship_colors) == 8:
        s = spread(ship_colors)
        c.ok("货主端明度极差 %.1f ≤ %.0f" % (s, SHIP_SPREAD_MAX), s <= SHIP_SPREAD_MAX)
        c.ok("货主端 8 格互异", len(set(ship_colors)) == 8, "有重复")
        nonbrand = [v for (lb, raw), v in zip(ship, ship_colors)
                    if lb != "AI 助手"]
        c.ok("货主端去 AI 后 7 格彩度比 %.2f ≤ %.1f" % (chroma_ratio(nonbrand), CHROMA_RATIO_MAX),
             chroma_ratio(nonbrand) <= CHROMA_RATIO_MAX,
             "AI 那颗品牌蓝不参与这条（用户点名保留）")
    ledger = grids.get("ledgerHomeEntries", [])
    ledger_colors = [v for _, raw in ledger if (v := resolve(raw, tokens)) is not None]
    c.ok("账本页 7 格都能解析", len(ledger_colors) == 7, "解析出 %d 个" % len(ledger_colors))
    if len(ledger_colors) == 7:
        s = spread(ledger_colors)
        c.ok("账本页明度极差 %.1f ≤ %.0f" % (s, LEDGER_SPREAD_MAX), s <= LEDGER_SPREAD_MAX)
        wc = min(chroma(cc) for cc in ledger_colors)
        c.ok("账本页最灰一格彩度 %.1f ≥ %.0f" % (wc, CHROMA_FLOOR), wc >= CHROMA_FLOOR)
        c.ok("账本页 7 格互异", len(set(ledger_colors)) == 7, "有重复")

    print("\n== 6. 设计系统 §4.25h 与用户口径留档 ==")
    design = read(DESIGN)
    c.present("设计系统新增的那一节在（§4.25h）", design, r"### 4\.25h ")
    # ⚠️ 下面全部**只看 §4.25h 那一节**，不是整份规范 —— 用户原话与那三个数字在别的小节里
    #    也出现过（变更沿革那一带），整份文件里 `in` 一下的话，那一节被人删空了判据照样绿（踩过）。
    sec = slice_section(design, "### 4.25h ")
    c.ok("切出了 §4.25h 这一节（%d 字，下限 1500）" % len(sec), len(sec) >= 1500,
         "节标题被改名 / 这一节被删了？⛔ 别改判据去迁就它")
    c.ok("那一节带收尾锚句（**这一节就是 §4.25h**）", "**这一节就是 §4.25h**" in sec,
         "收尾锚句是别的脚本按它找这一节的")
    c.ok("那一节写了用户那句「太灰了一点」", "太灰了一点" in sec, "用户为什么提这一轮，没人记得了")
    c.ok("那一节写了用户点名的那一档（相对彩度 0.62、明度带 58±5、彩度夹 28~44）",
         "相对彩度 0.62、明度带 58±5、彩度夹 28~44" in sec, "口径没留档，后来人只能猜")
    c.ok("那一节写了 CHG-0101 的病根数字（7.2 倍）", "7.2 倍" in sec,
         "没有对照数字就看不出为什么要改")
    # ⚠️ 文档里写的是 `0.62 × C\*max`（有空格，星号还被 markdown 转义了）——
    #    所以这里按「按相对彩度给色 + 天花板夹取」这两件事分别找，⛔ 别去钉一连串空格。
    c.ok("那一节写了生成口径：按相对彩度给色（`min(max(0.62 × …`）",
         "min(max(0.62" in sec, "没写生成口径，后来人只能猜")
    c.ok("那一节写了天花板夹取（`C*max × 0.94`）",
         "max × 0.94" in sec, "少了天花板，青蓝会被推艳")
    c.absent("那一节没有把「按固定彩度给」写成推荐做法", sec,
             r"推荐[^\n]{0,20}固定彩度")

    print("\n== 7. 配套：反验脚本与变更单 ==")
    c.ok("反验脚本在（%s）" % REVERSE.name, REVERSE.exists(), "反向验证都没写，红线没人证")
    rev = read(REVERSE)
    c.present("反验脚本里有注入表 `CASES`", rev, r"\nCASES: list\[tuple\[str, str, object, str\]\] = \[")
    doc = read(DOC)
    c.present("变更单写了 Blast Radius", doc, r"^- \*\*Blast Radius\*\*：L0")
    c.present("变更单在登记簿里（表会骗人）", read(REG), r"^\|\s*[\x60]?CHG-0102[\x60]?\s*\|")

    return c.report("工作台配色：低饱和但不发灰（CHG-0102）")


if __name__ == "__main__":
    raise SystemExit(main())
