#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品管理页：沽清的商品**整张卡变灰**（CHG-0103）。

用户要的是什么（ref `m05399`，逐字）：

    「顺便参考他这个样式啊，我们现在的商品管理。如果估清了。他那个卡片只会有一个沽清的状态，
     但是并没有整体变灰的样式啊参考。他的样式啊，他当时就有一个整体变灰的变动啊啊，改一下吧。」

这条口径不是这一轮才有的 —— 下单页选品弹层早就定过（台账 L-35 / `BUG-0017`，ref `m01347`，逐字）：

    「灰掉了之后就不能点的哈……就是整卡变灰嘛……就是拦住不让下，
     不可能是提示后他仍然可以下呀。」

## 为什么这条必须有机器的判据

因为它坏起来**不报错、不崩溃、界面照样能点、单测照样绿**：

1. 有人把灰罩那一层删了（"卡片上已经有已沽清角标了，够了吧"）—— 屏幕回到这一轮之前的样子，
   编译、单测、其它 200 多条判据**全绿**。这正是用户这一轮提的那句话。
2. 有人把 `0.45f` 改成 `0.95f` / 把 `0.6f` 改成 `0.95f` —— 字面上"整卡变灰"还在、
   画出来几乎看不出，跟没做一样。
3. 有人只灰了一部分（灰罩挂到 `ProductLine` 上、没包住底下那排按钮）—— 屏幕上"半张卡灰"，
   而"哪几个动作还点得动"这个信号就没了。
4. 有人只改灰底、不给内容降不透明度 —— 白底按钮 + 红字压在灰底上反而更跳（参考图里
   「取消沽清」那颗是暗的），用户要的"整体变灰"只做到一半。
5. 有人把三个动作的 `enabled` 还原成 `!acting` —— 灰卡上"改价"又点得动，
   一件已经不能卖的商品可以改个价；**灰卡给用户的承诺是"看起来不能点"**。
6. 有人图省事，用 `!p.isActive` 之外的条件（比如"库存为 0 也灰"）—— 未沽清的卡被误灰，
   而"灰"在本系统里就等于"不能卖"，这是个会让人不敢下单的假信号。
7. 有人把 `ProductSoldOutBadge` 的文案参数化，好让灰卡上写「已下架」/「售罄」——
   这正是 `:421` 那段注释记着的既有病灶（同一个状态两个词两种颜色）。
8. 有人绕开确认弹层：灰卡上那颗「上架」直接调 `vm.toggleActive(…)` —— P29 那个病
   （一次误触静默下架）会从灰卡上重来一遍。
9. 有人把 `ProductPicker.kt` 里已经上线的那一份数值**只改一处**（比如把灰底调到 0.7 试效果），
   于是同一件事在两个页面上是两个灰度 —— 用户过两天会说"这两个地方怎么不一样"。
10. 有人把 `ProductSoldOutBadge` 换成自绘的印章水印（参考图里那个斜章）时顺手改了文案 ——
    灰卡与角标于是变成"两个状态两个词"。

## R4-BOUNDARY-JUSTIFICATION: 为什么这条不下沉到类型 / 契约层

因为**没有类型可以表达它**。`soldOut: Boolean` 是 `Boolean`，`Color` 是 `Color`，
`0.45f` 与 `0.95f` 在 Kotlin 的类型系统里是同一个类型 —— 编译器、detekt、Kotlin 的检查
都不可能说"这个布尔为真时，那个容器必须换色、而且整棵子树必须降到 0.6 不透明度、
而且三个按钮必须同时不可点"。这是**一棵 composable 树的形状**，只在源码文本上成立。

它也不该下沉到数据契约：后端没有、也不该有"这张卡灰不灰"这个字段 —— 灰不灰是
`products.is_active` 这个既有事实的**画法**，多一个字段就是同一件事两处真相。

所以它只能在两处守：`ProductSoldOutScrim.kt`（值本身）与**本脚本**（值被谁用、怎么用）。
`ProductSoldOutScrimTest.kt` 那类单测只能测到"函数返回了 0.45"，测不到"产品管理页有没有用它"。

本脚本**只读工作区里的文件**，不编译、不跑 UI、不连设备（这是它能进 `_check_all.py` 的前提）。

## 判据

0. 反空转：扫描本身得是活的（`.kt` 数 ≥ 100；切出来的那几个片段都不为空）
1. 共用件 `ui/common/ProductSoldOutScrim.kt`：两个常量与两个函数都在，且**只有一份定义**
2. `ProductsScreen.kt`：灰罩**包住了整张卡**（`SectionCard` 是它的直接子级），且只有一处
3. 灰罩的开关**就是** `p.isActive`（不是库存、不是别的），且**只有这一处**
4. 三个动作：只有「改价」多一个 `p.isActive`，沽清/编辑仍只认 `acting`
5. 已沽清角标仍然是共用件 `ProductSoldOutBadge`（唯一一处），没有第二个词
6. 三颗按钮的文案仍是「改价」「沽清 / 上架」「编辑」，且沽清方向仍走确认弹层
7. ⛔ 判据反向：**没有**第二套透明度字面量（`ProductsScreen.kt` 里出现 0.45f / 0.6f 即红）
8. 交叉对账：`ProductPicker.kt` 里已上线的那一份数值与共用件**同值**（两个文件各一份值）
9. 未沽清的卡不许被顺手改掉（在售那一支里不许出现 alpha / 灰底色）
10. 设计系统 §4.25i 与 CHG-0103 变更单：这条口径留了档、逐字引了用户原话
11. 配套：反验脚本在、登记簿与进行中声明都有 CHG-0103

用法：
    python _tools/qa/_check_sold_out_card_grey.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = AND / "ui/dispatcher/ProductsScreen.kt"
SCRIM = AND / "ui/common/ProductSoldOutScrim.kt"
PICKER = AND / "ui/common/ProductPicker.kt"
KIT = AND / "ui/common/ProductCardKit.kt"
COLOR = AND / "ui/theme/Color.kt"
DOC = ROOT / "docs/changes/CHG-0103.md"
REG = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_sold_out_card_grey.py"

#: 静默空转保护：源码被搬走/清空时，判据不许「无一可查所以全绿」
MIN_KT = 100

SURFACE_ALPHA = "0.45f"
CONTENT_ALPHA = "0.6f"

#: 用户原话里那几个字（逐字，⛔ 不许改写；判据按它们找口径留档）
USER_WORDS = "并没有整体变灰的样式"
USER_WORDS_01347 = "就是整卡变灰嘛"


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
        # ⚠️ 一律带 `re.M`：下面几条是按**行首**找的（`^| `CHG-0103` |`、`^- \*\*Blast Radius\*\*`），
        #    不带 M 的话 `^` 只认整份文本的开头 —— 会假红。
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


def slice_kt_block(text: str, decl: str) -> str:
    """从 `decl` 那一行起，按大括号配平切出**整个函数体**（含 KDoc 之后的声明行）。

    ⚠️ 为什么要配平而不是找下一个 `@Composable`：本次要钉的正是"灰罩**包住了**哪几行"，
    用"下一个函数的开头"切会把 `ProductCard` 收口的 `}` 一起吞进来，
    于是"灰罩没包住按钮"这种坏法照样能过。
    """
    i = text.find(decl)
    if i < 0:
        return ""
    j = text.find("{", i + len(decl) - 1)
    if j < 0:
        return ""
    depth = 0
    for k in range(j, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return text[i:k + 1]
    return ""


#: 三个动作在卡上的**顺序**（用户 m 里点名的三个：改价、沽清/上架、编辑）
ACTIONS = [
    ("改价", r'^\s+label = "改价",$'),
    ("沽清/上架", r'^\s+label = if \(p\.isActive\) "沽清" else "上架",$'),
    ("编辑", r'^\s+label = "编辑",$'),
]


def main() -> int:
    c = Checker()

    print("== 0. 反空转：扫描本身是活的 ==")
    kts = [p for p in AND.rglob("*.kt") if p.is_file()]
    c.ok("扫到 %d 个 .kt（下限 %d）" % (len(kts), MIN_KT), len(kts) >= MIN_KT,
         "源码被清空/搬走了 —— ⛔ 不许把下限调低来过")

    screen = read(SCREEN)
    card = slice_kt_block(screen, "private fun ProductCard(")
    c.ok("切出了 ProductCard 的函数体（%d 字）" % len(card), len(card) > 500,
         "函数被改名 / 被删了？⛔ 别改判据去迁就它")
    scrim = read(SCRIM)
    picker = read(PICKER)

    print("\n== 1. 共用件：两个常量与两个函数，而且**只有一份** ==")
    for label, pattern in (
        ("灰底常量 `PRODUCT_SOLD_OUT_SURFACE_ALPHA = 0.45f`",
         r"^const val PRODUCT_SOLD_OUT_SURFACE_ALPHA: Float = 0\.45f$"),
        ("内容常量 `PRODUCT_SOLD_OUT_CONTENT_ALPHA = 0.6f`",
         r"^const val PRODUCT_SOLD_OUT_CONTENT_ALPHA: Float = 0\.6f$"),
        ("灰底色函数 `fun productSoldOutCardColor(): Color`",
         r"^fun productSoldOutCardColor\(\): Color =$"),
        # ⛔ 必须把**整份参数表**钉死：只查 `fun ProductSoldOutCard(` + 第一行参数的话，
        # 后面插进来一个 `label: String = \"已沽清\"`（下一页就会传「售罄」「下架」）照样能过。
        ("卡壳 `fun ProductSoldOutCard(soldOut, modifier, content)`（四个参数一个不多）",
         r"^fun ProductSoldOutCard\(\n    soldOut: Boolean,\n    modifier: Modifier = Modifier,\n"
         r"    content: @Composable ColumnScope\.\(\) -> Unit,\n\) \{$"),
    ):
        c.present("共用件里有「%s」" % label, scrim, pattern)
    c.present("灰底色用的是 `surfaceVariant`（不是写死一个灰 —— 深浅两主题各用各的）",
              scrim, r"MaterialTheme\.colorScheme\.surfaceVariant\.copy\(alpha = PRODUCT_SOLD_OUT_SURFACE_ALPHA\)")
    c.present("内容变暗挂在**容器**上（整棵子树一起降，不是逐个子件各挂一次）",
              scrim, r"^        Box\(Modifier\.alpha\(PRODUCT_SOLD_OUT_CONTENT_ALPHA\)\) \{$")
    c.present("在售那一支**原样透传**（`if (!soldOut)` → 直接 Column，一个字都不加）",
              scrim, r"^    if \(!soldOut\) \{\n        Column\(modifier = modifier, content = content\)\n        return$")
    c.present("⛔ 共用件不依赖 android（只 import androidx.*，否则单测引不了）",
              scrim, r"^import androidx\.compose\.material3\.Surface$")
    c.absent("共用件里没有 `android.` 的 import", scrim, r"^import android\.")
    n_def_const = len(re.findall(r"^const val PRODUCT_SOLD_OUT_SURFACE_ALPHA", scrim, re.M))
    c.ok("灰底常量在全库只有这一处定义（本文件 %d 处）" % n_def_const, n_def_const == 1,
         "又冒出来一份定义 → 两处会各自漂")
    n_def_fun = len(re.findall(r"^fun ProductSoldOutCard\(", scrim, re.M))
    c.ok("`ProductSoldOutCard` 只有一个实现（本文件 %d 处）" % n_def_fun, n_def_fun == 1)

    print("\n== 2. 商品管理页：灰罩**包住了整张卡** ==")
    c.present("卡上真的用了共用件（`ProductSoldOutCard(soldOut = !p.isActive) {`）",
              card, r"^    ProductSoldOutCard\(soldOut = !p\.isActive\) \{$")
    c.present("⛔ `SectionCard` 是它的**直接子级**（整张卡都在灰罩里，三行必须挨着）",
              card, r"^    ProductSoldOutCard\(soldOut = !p\.isActive\) \{\n        SectionCard \{$")
    n_grey = len(re.findall(r"^    ProductSoldOutCard\(", card, re.M))
    c.ok("整卡只包了一次（%d 次）" % n_grey, n_grey == 1,
         "包两次会叠出两层灰底（0.45 × 0.45）")
    # 灰罩里必须看得见那三样东西 —— 只灰了图/名不算「整卡」
    for name, pattern in (
        ("图 + 名称 + 两条事实", r"^            ProductLine\($"),
        ("三个动作那一排", r"^            Row\(Modifier\.fillMaxWidth\(\), horizontalArrangement"),
        ("「已沽清」角标仍然在卡上", r"badge = soldOut,$"),
    ):
        c.present("灰罩里还有「%s」" % name, card, pattern)

    print("\n== 3. 灰罩的开关**就是** `p.isActive`，而且只有这一处 ==")
    n_switch = len(re.findall(r"ProductSoldOutCard\(soldOut = !p\.isActive\)", screen))
    c.ok("全页只有这一个灰罩开关（%d 处）" % n_switch, n_switch == 1,
         "多出来一处 = 有别的条件也在灰卡")
    c.absent("⛔ 灰罩不是按库存/别的字段触发的", screen,
             r"ProductSoldOutCard\(soldOut = (?!!p\.isActive)")

    print("\n== 4. 三个动作的 enabled：只有「改价」多认 `p.isActive` ==")
    n_active = len(re.findall(r"^ +enabled = !acting && p\.isActive,$", card, re.M))
    c.ok("灰卡上多一道 `&& p.isActive` 的按钮正好 1 个（%d 个）" % n_active, n_active == 1,
         "0 个 = 只灰不拦（改价还点得动）；3 个 = 连「上架」「编辑」一起禁掉，"
         "那沽清的商品永远回不到在售")
    n_plain = len(re.findall(r"^ +enabled = !acting,$", card, re.M))
    c.ok("仍只认 `!acting` 的按钮正好 2 个（%d 个）" % n_plain, n_plain == 2,
         "沽清/上架与编辑必须留着 —— 参考图里「取消沽清」与「编辑」也是暗的但仍能点")
    # 那一个必须落在**改价**那一颗上（不是沽清、不是编辑）
    qi = card.find('label = "改价",')
    ti = card.find('label = if (p.isActive) "沽清" else "上架",')
    ei = card.find('label = "编辑",')
    gi = card.find("enabled = !acting && p.isActive,")
    c.ok("那一颗是「改价」（第 %d 处 enabled 落在改价与沽清之间）" % gi,
         qi >= 0 and ti > qi and gi > qi and gi < ti,
         "落错按钮了：灰卡上还能改价的商品、或者沽清了就再也上不了架")
    for label, pattern in ACTIONS:
        c.present("卡上还有「%s」这颗按钮" % label, card, pattern)
    # ⚠️ 查的是 `screen`（整份文件）而不是 `card`：调用点 `ProductCard(...)` 在 `:218`，
    #    在 `ProductCard` 这个函数**之外** —— 只查函数体的话这条会假红（判据自己在骗人）。
    #    两行仍然必须挨着，且都从行首锚定（`re.M`），不给"别处也有一行就够了"的口子。
    c.present("⛔ 沽清 / 上架仍然**只打开确认弹层**（`onToggle = { toggleFor = p }`，"
              "两行必须挨着）", screen,
              r"^                                        onToggle = \{ toggleFor = p \},$")
    c.present("弹层那一份仍在页面上（`toggleFor?.let { p ->` → `toActive = !p.isActive`）",
              screen,
              r"^    toggleFor\?\.let \{ p ->\n        ProductActiveConfirmDialog\(\n"
              r"            toActive = !p\.isActive,$")
    c.absent("⛔ 这颗按钮没有绕开弹层直接改状态", card,
             r"onClick = \{ vm\.(toggleActive|setActive)\(")

    print("\n== 5. 「已沽清」角标仍然是共用件，而且只有这一个词 ==")
    c.present("角标来自共用件 `ProductSoldOutBadge()`", card,
              r"val soldOut: \(@Composable \(\) -> Unit\)\? = if \(p\.isActive\) null else "
              r"\(\{ ProductSoldOutBadge\(\) \}\)")
    for label, text in (("商品管理页", card), ("选品弹层", picker)):
        # ⚠️ 只认"给共用角标传了参数"或"另写了一个别名的角标" —— 空的 `ProductSoldOutBadge()`
        #    正是我们要的那一个，不能把它算成第二个词。
        c.absent("⛔ %s 上没有第二个词（「售罄」「已下架」「缺货」）" % label, text,
                 r"ProductSoldOutBadge\([^)]|Text\(\s*\"(售罄|已下架|缺货|已停售)\"")
    c.present("共用角标本身仍然是**无参**的（文案只有「已沽清」）", read(KIT),
              r"^fun ProductSoldOutBadge\(\) \{")

    print("\n== 6. ⛔ 判据反向：商品管理页里**没有**第二套透明度字面量 ==")
    # 这一页只说"算不算沽清"，数值一律走共用件 —— 这里再写一个 0.45f / 0.6f 就是两份真相
    for lit in (SURFACE_ALPHA, CONTENT_ALPHA):
        c.absent("⛔ `ProductsScreen.kt` 里没有 `%s` 这个字面量" % lit, screen,
                 r"(?<![\d.])" + re.escape(lit))
    c.absent("⛔ `ProductsScreen.kt` 里没有 `Modifier.alpha(`（变暗挂在共用件的 Box 上）",
             screen, r"Modifier\.alpha\(")
    c.absent("⛔ `ProductsScreen.kt` 里没有 `surfaceVariant`（灰底只有共用件那一处）",
             screen, r"surfaceVariant")

    print("\n== 7. 交叉对账：ProductPicker 里已上线那一份与共用件同值 ==")
    s_alpha = re.search(r"surfaceVariant\.copy\(alpha = ([0-9.]+f)\)", picker)
    c.ok("选品弹层的灰底透明度 = %s（与共用件同值）" % SURFACE_ALPHA,
         s_alpha is not None and s_alpha.group(1) == SURFACE_ALPHA,
         "读出来是 %s —— 两个页面会灰得不一样" % (s_alpha.group(1) if s_alpha else "没找到"))
    c_alpha = re.search(r"\.alpha\(if \(soldOut\) ([0-9.]+f) else 1f\)", picker)
    c.ok("选品弹层的内容透明度 = %s（与共用件同值）" % CONTENT_ALPHA,
         c_alpha is not None and c_alpha.group(1) == CONTENT_ALPHA,
         "读出来是 %s" % (c_alpha.group(1) if c_alpha else "没找到"))
    c.present("⚠️ 那份字面量还在 `ProductPicker.kt` 里（CHG-0102 落地后应合并进共用件 —— "
              "文件头写了「后续可以合并到哪」）", scrim, r"后续可以合并到哪")

    print("\n== 8. 未沽清的卡不许被顺手改掉 ==")
    c.present("在售那一支直接 `Column` 透传（连 alpha 都不挂）", scrim,
              r"^    if \(!soldOut\) \{\n        Column\(modifier = modifier, content = content\)\n        return$")
    c.absent("⛔ 在售那一支里没有灰底色 / 没有 alpha", scrim,
             r"if \(!soldOut\) \{[\s\S]{0,200}?alpha")
    c.present("三个动作的默认值仍是 `enabled: Boolean = true`（别把默认改成 false 蒙过判据）",
              screen, r"^    enabled: Boolean = true,$")

    print("\n== 9. 设计系统 §4.25i：这条口径留了档 ==")
    design = read(DESIGN)
    c.present("新增的那一节在（§4.25i）", design, r"^### 4\.25i ")
    sec = slice_section(design, "### 4.25i ")
    c.ok("切出了 §4.25i 这一节（%d 字，下限 800）" % len(sec), len(sec) >= 800,
         "节标题被改名 / 这一节被删了？⛔ 别改判据去迁就它")
    c.ok("那一节逐字引了这一轮的用户原话（「%s」）" % USER_WORDS, USER_WORDS in sec,
         "用户为什么提这一轮，没人记得了")
    c.ok("那一节也写了这条路最早的出处（选品弹层 / L-35）", "L-35" in sec,
         "不看 L-35 就不知道「整卡变灰」不是这一轮发明的")
    c.ok("那一节写了「%s」这句原话（说明「灰」= 不能卖）" % USER_WORDS_01347,
         USER_WORDS_01347 in sec, "少了它，后来人会以为灰只是好看")
    for lit, why in ((SURFACE_ALPHA, "灰底"), (CONTENT_ALPHA, "内容")):
        c.ok("那一节写了%s那档透明度（%s）" % (why, lit), lit in sec,
             "没写数值，下一个人只能猜")
    c.ok("那一节点了共用件（`ProductSoldOutScrim.kt`）", "ProductSoldOutScrim.kt" in sec,
         "口径没落到文件上，等于没写")
    # ⛔ 钉整句、不钉「同一件事」这四个字：那一节里另有一句「与角标是同一件事」，
    # 于是把这一句改成「两件不同的事」时，松判据照样绿 —— 这条红线就白设了。
    c.ok("那一节说清了灰卡与角标是同一件事的两种说法",
         "灰卡与「已沽清」角标是同一件事的两种说法" in sec,
         "不说清就会被下一个人做成「两个状态两个词」（`:421` 那个既有病灶）")
    c.absent("⛔ 那一节没有把「上架」这颗按钮也禁掉", sec, r"三个动作一起不可点")
    c.present("§4.2b 的布局表那一行也指过来了", design,
              # 表格行末是「空格 + |」（这张表的写法），所以空格必须显式写进正则：
              # 少了它这条在最自然的写法上会假红，而假红会被下一个人当成"判据太严"删掉。
              r"^\| 右上 \| 商品名（最多两行）\+ 「已沽清」角标（沽清时整卡变灰，见 §4\.25i） \|$")

    print("\n== 10. 变更单 / 登记簿 / 进行中声明 ==")
    doc = read(DOC)
    c.present("变更单在（%s）" % DOC.name, doc, r"^# CHG-0103 ")
    c.present("变更单写了 Blast Radius", doc, r"^- \*\*Blast Radius\*\*：L0")
    # ⛔ 必须钉在 ① 六问 里：那句话在整份变更单里会出现两遍（另一遍是 Must Not Change
    # 第 7 行格子里顺口提的），只查"全文里有没有"的话，把六问里那段原话删掉判据照样绿。
    six = slice_section(doc, "## ① 六问")
    c.ok("① 六问 里逐字引了这一轮的用户原话（「%s」）" % USER_WORDS, USER_WORDS in six,
         "逐字引用了才拦得住「按理解重写需求」")
    c.ok("① 六问 引的是整句、不是半句（前半句与结尾都在）",
         "如果估清了。他那个卡片只会有一个沽清的状态" in six and "改一下吧。」" in six,
         "只留半句，读的人会把「沽清状态」当成用户要的东西")
    c.present("变更单在登记簿里（表会骗人）", read(REG),
              r"^\|\s*`CHG-0103`\s*\|")
    c.present("`AI_WORK_CLAIM.md` 的进行中里有这一条", read(CLAIM),
              r"^### \[2026-10-10 [0-9:]+ → ⏳ CST 进行中\] 会话：\*\*CHG-0103 ")
    c.present("定位表那一行也跟着动了（提到整卡变灰）", read(LOCATOR),
              r"整卡变灰")

    print("\n== 11. 配套：反验脚本与它自己的注入表 ==")
    c.ok("反验脚本在（%s）" % REVERSE.name, REVERSE.exists(), "反向验证都没写，红线没人证")
    rev = read(REVERSE)
    c.present("反验脚本里有注入表 `CASES`（不是空壳）", rev,
              r"\nCASES: list\[tuple\[str, str, object, str\]\] = \[")
    n_cases = len(re.findall(r"^\s{4}\(\"", rev, re.M))
    c.ok("注入条数 %d ≥ 8（父任务要求的下限）" % n_cases, n_cases >= 8,
         "注入太少证明不了这条红线是活的")

    return c.report("商品管理页：沽清整卡变灰（CHG-0103）")


if __name__ == "__main__":
    raise SystemExit(main())
