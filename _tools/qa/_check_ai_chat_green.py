#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 聊天页的强调色＝一个像微信的绿，与全 App 主操作色解绑（台账 L-67 / CHG-0104）。

用户要的是什么（ref `m04856`，逐字）：

    「还有一点就是你别帮我那个 a i 对话框改的颜色改其他颜色了它的主颜色还是绿色，
     但是什么样的绿呃还是啊，要你的方案进行，它就像微信一样，为什么要绿色呢？
     因为我希望让使用，用人跟微信一样亲切啊，因为我们微信是大家经常用的」

⇒ 两件事：① AI 这一片的主色**是绿的**；② **绿值我们定**，方向是「像微信」。
   ⛔ 不是「把全 App 主色改回绿」—— 全 App 主操作色 `ThemeGreen` 是用户 2026-10-09
   亲手画的那一族（CHG-0105 起：老色相 ＋ H 档明度彩度，值是 `#006C43`）。

## 为什么这条必须有机器的判据

因为它坏起来**不报错、不崩溃、编译也过**：

1. 有人把 `AiAccent` 写回 `Color(ThemeGreen)` —— AI 页立刻跟着全 App 主操作色跑。
   **这正是本单的病根**：CHG-0091 把它收敛到 `ThemeGreen`，CHG-0101 换主色时
   AI 页毫无防备地跟着一起变了（那次的 `ThemeGreen` 是深红棕），用户才来说这一句。
2. 有人图省事把「实心底 + 白字」那几处也写 `AiChatGreen` —— 白字只有 **4.03:1**，
   不到 AA 的 4.5。屏幕上看不出差别，但老年用户读不清（本项目的核心约束）。
3. 有人把某个值微调成「更亮一点的绿」去讨好眼睛 —— 绿在 sRGB 里亮度权重是 0.7152，
   **稍微亮一点白字就掉到 4.5 以下**，而没有任何东西会报错。
4. 有人顺手把 `ThemeGreen` / `ThemeGreenDeep` 改了来「让 AI 页变绿」——
   那不是 AI 页专属的色：`ThemeGreen` 是全 App 的主操作色、`ThemeGreenDeep` 是
   订单卡「确认接单」读的深一档。⚠️ 它们现在**本来就偏绿**（CHG-0105 把色相还给了
   老色相），所以「改成绿」这个念头比 CHG-0104 那会儿更容易冒出来 —— 而绑定照旧是错的。
5. 有人把 AI 的品牌三段渐变（`aiBrandBrush` 的蓝→紫→粉）也一起「统一」成绿 ——
   用户从没让动过，那是 AI 的身份标识。
6. 有人删掉 AI 设置页 / 操作流水页那一处，于是 AI 这一片又变成「一半绿一半蓝」。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事

色值是 `Long`（裸 ARGB）或 `Color`，两者之间**没有类型差**：`#4B8C5E` 与 `#006C43`
在类型系统里是同一个东西。编译器、detekt、Kotlin 的类型检查都**不可能**表达
「这个值必须是一个色相 ≈150° 的绿」「白字压上去必须 ≥ 4.5:1」。
后一条更是**只在算完对比度之后才成立的性质**，连"值的集合"都不是 ——
只能在「把值读出来、算一遍」的地方守，也就是这里和 `AiChatGreenTest.kt`。

本脚本**只读工作区里的文件**，不编译、不跑 UI、不连设备（这是它能进 `_check_all.py` 的前提）。

## 判据

0. 反空转：扫描本身得是活的（`Color.kt` token 数够、三个 AI 页都在）
1. 两个 token 在 `Color.kt` 里，就是那两个值
2. **用 Python 独立算一遍**对比度与 Lab：白字过 AA / 强调色不过 AA（两档拆分是必需的，不是装饰）
3. 色相是个绿，且与微信品牌绿同一个色相家族
4. `AiChatScreen.kt`：强调色绑到新 token；旧的两个绿引用一处不留；四处实心全走深档
5. `AiSettingsScreen.kt` / `AiOperationsScreen.kt`：同一片表面一起收敛，蓝一处不留
6. 主操作色与 AI 品牌渐变**一个字都没动**（本单最容易误伤的两处）
7. 单测、反验脚本、变更单、登记簿、设计系统 §4.25j 都在

配套：python `_tools/qa/_reverse_verify_ai_chat_green.py`（32 种破坏方式全被抓）
      —— 上面每一条都有人"把源码改坏"证明过它真的会红，不是摆着好看的。

用法：
    python _tools/qa/_check_ai_chat_green.py
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
CHAT = AND / "ui/ai/AiChatScreen.kt"
SETTINGS = AND / "ui/ai/AiSettingsScreen.kt"
OPS = AND / "ui/ai/AiOperationsScreen.kt"
#: AI 品牌渐变的三个色 —— 本单的「不许动」名单
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/theme/AiChatGreenTest.kt"
DOC = ROOT / "docs/changes/CHG-0104.md"
REG = ROOT / "docs/changes/README.md"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_ai_chat_green.py"

#: 静默空转保护：源码被搬走/清空时，判据不许「无一可查所以全绿」
MIN_COLOR_TOKENS = 80
MIN_CHAT_LINES = 1500

#: 定稿的两个值（`_tmp/chg0104_pick.py` 选出来的，理由写在 Color.kt 的注释里）
WANT_ACCENT = "4B8C5E"      # 强调色：图标 / 浅底 / 选中 / 描边
WANT_DEEP = "3D734D"        # 实心底：按钮 + 白字

#: 微信品牌绿（用户点名的那一家）—— 只用来比色相，⛔ 不用来比值
WECHAT_GREEN = "00C939"

#: AA 阈值。白字压色块要 4.5；「图形」那一档 WCAG 只要 3.0。
AA_TEXT = 4.5
AA_GRAPHIC = 3.0

#: 色相允许落在哪一带（绿）。50° 很宽了 —— 目的是挡住「换成蓝/黄/红」这类事故。
HUE_LO, HUE_HI = 100.0, 180.0
#: 与微信绿的色相最大偏差（deg）。超过就不是「像微信」那个绿了。
HUE_WECHAT_MAX = 12.0


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
        # ⚠️ 一律带 `re.M`：下面几条是按**行首**找的（`^val AiChatGreen = `），
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


def code_only(text: str) -> str:
    """把注释整行去掉（`//`、`/*`、`/**`、以及 KDoc 正文那种行首 `*` 的行）。

    ⚠️ 必须有这一步：本单在 `AiChatScreen.kt` 里**故意**留了
    「⛔ 别再写回 `Color(ThemeGreen)`」这种注释（一句在 KDoc 正文、一句在 `//` 行）。
    不去注释的话，那条「代码里不许再出现 ThemeGreen」的判据会被自己的说明文字弄红（踩过）。
    ⛔ 只去**整行**都是注释的行（允许缩进）；不处理「代码后面跟一句行尾注释」——
    那一种在本仓库里没用来写色值。
    """
    out = []
    for ln in text.split("\n"):
        s = ln.lstrip()
        if s.startswith("//") or s.startswith("/*") or s.startswith("*"):
            continue
        out.append(ln)
    return "\n".join(out)


# ---------------------------------------------------------------- 颜色换算
def _lin(c: int) -> float:
    v = c / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def luminance(rgb: str) -> float:
    """WCAG 相对亮度。⛔ 与 `Color.kt` 注释里那个数字同一套公式。"""
    r = int(rgb[0:2], 16)
    g = int(rgb[2:4], 16)
    b = int(rgb[4:6], 16)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def lab(rgb: str) -> tuple[float, float, float]:
    """sRGB -> CIE L*a*b*（D65）。⛔ 与 `_check_palette_uniformity.py` 同一套公式。"""
    r, g, b = _lin(int(rgb[0:2], 16)), _lin(int(rgb[2:4], 16)), _lin(int(rgb[4:6], 16))
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) / 1.00000
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def lch(rgb: str) -> tuple[float, float, float]:
    L, a, b = lab(rgb)
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360.0


def hue_delta(h1: float, h2: float) -> float:
    d = abs(h1 - h2) % 360.0
    return min(d, 360.0 - d)


def hex_in(text: str, name: str) -> str:
    """从源码里读出某个 `val <name> = 0xFF……[L]` 的十六进制（大写、无 0x）。

    ⚠️ 本仓库**两种写法并存**（`08_CODE_LOCATOR.md` 专门警告过这条）：
    `val MoneyOrange = 0xFFFF8700L`（裸 Long）与 `val BackgroundLight = Color(0xFFF7F6F3)`
    （包了 `Color()`、没有 `L`）。只认一种就会读出空串 —— 本脚本第一版就栽在这，
    表现是「页面底读到了（#）」这种空值假红。
    """
    m = re.search(r"^val %s = (?:Color\()?0xFF([0-9A-Fa-f]{6})L?\)?" % re.escape(name), text, re.M)
    return m.group(1).upper() if m else ""


def main() -> int:
    c = Checker()
    color = read(COLOR)
    chat = read(CHAT)
    settings = read(SETTINGS)
    ops = read(OPS)

    print("== 0. 反空转：扫描本身得是活的 ==")
    toks = re.findall(r"^val [A-Za-z][A-Za-z0-9_]* = ", color, re.M)
    c.ok("Color.kt 扫到 %d 个 token（下限 %d）" % (len(toks), MIN_COLOR_TOKENS),
         len(toks) >= MIN_COLOR_TOKENS, "正则失配、或者 token 被搬去别的文件了")
    for p, least in ((CHAT, MIN_CHAT_LINES), (SETTINGS, 500), (OPS, 120)):
        n = len(read(p).split("\n"))
        c.ok("%s 有 %d 行（下限 %d）" % (p.name, n, least), n >= least,
             "文件被截断/搬走了？这条判据要跟着改")

    print("\n== 1. 两个 token 在 Color.kt 里，就是那两个值 ==")
    c.present("强调色 token 在（`val AiChatGreen = 0xFF%sL`）" % WANT_ACCENT,
              color, r"^val AiChatGreen = 0xFF%sL" % WANT_ACCENT)
    c.present("实心档 token 在（`val AiChatGreenDeep = 0xFF%sL`）" % WANT_DEEP,
              color, r"^val AiChatGreenDeep = 0xFF%sL" % WANT_DEEP)
    accent = hex_in(color, "AiChatGreen")
    deep = hex_in(color, "AiChatGreenDeep")
    c.ok("读出来就是 #%s / #%s" % (WANT_ACCENT, WANT_DEEP),
         accent == WANT_ACCENT and deep == WANT_DEEP,
         "读出来是 #%s / #%s" % (accent or "?", deep or "?"))

    print("\n== 2. 对比度与 Lab：Python 独立算一遍 ==")
    #: 页面底（CHG-0102 的暖白）与白卡 —— 强调色当图形时压在这两层上
    page = hex_in(color, "BackgroundLight")
    c.ok("页面底 BackgroundLight 读到了（#%s）" % page, bool(page), "改名前先改这条判据")
    w_on_accent = contrast("FFFFFF", accent)
    w_on_deep = contrast("FFFFFF", deep)
    accent_on_page = contrast(accent, page) if page else 0.0
    # ① 实心档必须过 AA —— 这是它存在的全部理由
    c.ok("白字压实心档 #%s = %.2f:1 ≥ %.1f（过 AA）" % (deep, w_on_deep, AA_TEXT),
         w_on_deep >= AA_TEXT, "又亮回去了？绿一亮点白字就掉")
    # ② 强调档**必须**过不了 AA —— 两档拆分才不是装饰。这条红了说明该合并成一个 token。
    c.ok("白字压强调档 #%s = %.2f:1 < %.1f（所以它不能被拿去压字）" % (accent, w_on_accent, AA_TEXT),
         w_on_accent < AA_TEXT,
         "它居然过了 AA —— 那两档可以合并，Color.kt 里那段「为什么是两个」要重写")
    # ③ 强调档当「图形」用要过 3:1
    c.ok("强调档压页面底 #%s = %.2f:1 ≥ %.1f（当图标用够了）" % (page, accent_on_page, AA_GRAPHIC),
         accent_on_page >= AA_GRAPHIC, "图标也看不清了")
    # ④ 两档要真的分得开（有人把 Deep 调成和 Accent 一样，UI 上主次就没了）
    dl = lab(deep)[0] - lab(accent)[0]
    c.ok("两档明度差 |ΔL*| = %.1f（要在 5~16 之间：分得开、又不是两个色）" % abs(dl),
         5.0 <= abs(dl) <= 16.0, "太近看不出主次 / 太远像两个不相关的色")
    c.ok("实心档比强调档暗（Deep 是「深一档」）", luminance(deep) < luminance(accent),
         "写反了")

    print("\n== 3. 色相：是个绿，而且与微信品牌绿同一家族 ==")
    La, Ca, Ha = lch(accent)
    _, _, Hw = lch(WECHAT_GREEN)
    c.ok("强调档 L*=%.1f C*=%.1f h=%.1f°" % (La, Ca, Ha), True)
    c.ok("色相落在绿带 %.0f~%.0f°（实际 %.1f°）" % (HUE_LO, HUE_HI, Ha),
         HUE_LO <= Ha <= HUE_HI, "换成蓝/黄/红了？")
    c.ok("与微信品牌绿 #%s（h=%.1f°）差 %.1f° ≤ %.0f°" % (WECHAT_GREEN, Hw, hue_delta(Ha, Hw), HUE_WECHAT_MAX),
         hue_delta(Ha, Hw) <= HUE_WECHAT_MAX, "色相偏了就不是「像微信」那个绿")
    # 微信绿自己没过 AA —— 用户要的是**观感像**，不是照抄那个值
    c.ok("微信品牌绿自己白字只有 %.2f:1（<%.1f）⇒ 本单不能照抄它的值"
         % (contrast("FFFFFF", WECHAT_GREEN), AA_TEXT),
         contrast("FFFFFF", WECHAT_GREEN) < AA_TEXT,
         "微信绿居然过 AA 了，那 Color.kt 里那段论证要重写")

    print("\n== 4. AiChatScreen.kt：强调色绑到新 token，旧引用一处不留 ==")
    chat_code = code_only(chat)
    c.present("`private val AiAccent = Color(AiChatGreen)`",
              chat, r"^private val AiAccent = Color\(AiChatGreen\)$")
    c.absent("代码里没有 `Color(ThemeGreen)` 了", chat_code, r"Color\(ThemeGreen\)")
    c.absent("代码里没有 `ThemeGreenDeep` 了", chat_code, r"ThemeGreenDeep")
    c.absent("import 里也没有旧的两个绿", chat,
             r"^import com\.tapmoay\.sorders\.ui\.theme\.ThemeGreen(Deep)?$")
    #: 四处「实心底 + 白字」必须全走深档。逐处点名（计数型判据单独用会漏逐处退化）。
    solids = [
        ("新对话按钮", r"containerColor = Color\(AiChatGreenDeep\), contentColor = Color\.White\)"),
        ("去设置按钮", r"containerColor = Color\(AiChatGreenDeep\),\n\s+contentColor = Color\.White,"),
        ("发送键", r"else -> SolidColor\(Color\(AiChatGreenDeep\)\)"),
        ("思考强度分段控件", r"accent = Color\(AiChatGreenDeep\),"),
    ]
    for label, pat in solids:
        c.present("实心处「%s」读的是深档" % label, chat, pat)
    c.present("发送键的失效态还是强调档的 45%（可发/不可发要看得出来）",
              chat, r"!canSend -> SolidColor\(AiAccent\.copy\(alpha = 0\.45f\)\)")
    c.ok("强调档在这一页确实被用着（不是定义了没人用）",
         len(re.findall(r"AiAccent", chat_code)) >= 20,
         "只数到 %d 处" % len(re.findall(r"AiAccent", chat_code)))
    #: 用户自己发出去的那一句气泡。CHG-0104 之前它读 `MaterialTheme.colorScheme.primary`
    #  —— 那是**全 App 的主操作色**，于是 CHG-0101 换主色时它隔着主题变成红棕：
    #  整页强调点都绿了，就它一个红棕（用户说的「改了其他颜色」）。微信里自己那条是绿的。
    c.present("用户气泡读 AI 页自己的深档（底色深、白字才 5.59:1）",
              chat, r"isUser -> Color\(AiChatGreenDeep\)")
    c.absent("这一页不再隔着主题借全 App 主操作色（代码里没有 `colorScheme.primary`）",
             chat_code, r"colorScheme\.primary")

    print("\n== 5. AI 设置页 / 操作流水页：同一片表面一起收敛 ==")
    set_code = code_only(settings)
    ops_code = code_only(ops)
    c.present("设置页强调色 `val accent = Color(AiChatGreen)`",
              settings, r"^\s+val accent = Color\(AiChatGreen\)$")
    c.absent("设置页代码里没有 `Color(ThemeGreen)` 了", set_code, r"Color\(ThemeGreen\)")
    c.absent("设置页 import 里也没有 ThemeGreen", settings,
             r"^import com\.tapmoay\.sorders\.ui\.theme\.ThemeGreen$")
    c.present("设置页「保存」按钮走深档（实心底 + 白字）",
              settings, r"containerColor = Color\(AiChatGreenDeep\),")
    c.present("设置页分段控件走深档（选中态是文字）",
              settings, r"accent = Color\(AiChatGreenDeep\),")
    # 操作流水页：原来只有它还是 Google 蓝
    c.absent("操作流水页代码里没有 `AiBlue` 了", ops_code, r"AiBlue")
    c.absent("操作流水页 import 里也没有 AiBlue", ops,
             r"^import com\.tapmoay\.sorders\.ui\.theme\.AiBlue$")
    c.present("操作流水页刷新图标改成强调档",
              ops, r"tint = Color\(AiChatGreen\)\)")
    c.present("操作流水页分段控件走深档", ops, r"accent = Color\(AiChatGreenDeep\),")

    print("\n== 6. 不许误伤：主操作色与 AI 品牌渐变一个字都不许动 ==")
    # ⚠️ `ThemeGreen` 那一行是**6 位裸 ARGB**（`0xFF006C43`，而 CHG-0104 当时是 8 位的
    #    `0xFFFF8B4A4A`），`ThemeGreenDeep` 则是**8 位 ＋ `L` 后缀**（`0xFF00532EL`）——
    #    两者写法不同，别把两句正则写成一样。
    # ⚠️ CHG-0105 起这两个值都换了：老色相 ＋ H 档明度彩度（`#8B4A4A` → `#006C43`、
    #    `#6E3636` → `#00532E`）。这里钉的是**现值**，不再是用户画的那两个 hex。
    c.present("主操作色还在用户画的那一族里（老色相 ＋ H 档，`#006C43`）",
              color, r"^val ThemeGreen = 0xFF006C43\b")
    c.present("深一档还是 `#00532E`（订单卡的确认接单读它）",
              color, r"^val ThemeGreenDeep = 0xFF00532EL")
    for name, want in (("AiBlue", "4285F4"), ("AiPurple", "9B72CB"), ("AiPink", "D96570")):
        c.present("AI 品牌渐变 %s 还是 #%s（用户没让动过）" % (name, want),
                  color, r"^val %s = 0xFF%sL" % (name, want))
    c.present("品牌渐变笔刷 aiBrandBrush 还在", chat, r"aiBrandBrush")
    # 本单**只该**新增两个 token，不该删别人的
    c.absent("没有拿 AiChatGreen 去覆盖一个已有 token", color,
             r"^val (ThemeGreen|Primary|NavBlue|InfoBlue|MgrGreen|SuccessGreen) = 0xFF4B8C5EL")

    print("\n== 7. 单测、反验脚本、变更单、登记簿 ==")
    c.ok("单测在（%s）" % TEST.name, TEST.exists(), "没有机器判据，下次换色没人拦")
    t = read(TEST)
    c.ok("单测钉住了强调档的值", ("0xFF%sL" % WANT_ACCENT) in t, "值没钉")
    c.ok("单测钉住了实心档的值", ("0xFF%sL" % WANT_DEEP) in t, "值没钉")
    c.ok("单测自己算了一遍白字对比度（不是只比值）",
         ("4.5" in t) and ("contrast" in t or "ratio" in t or "lum" in t), "没人算对比度")
    c.ok("反验脚本在（%s）" % REVERSE.name, REVERSE.exists(), "反向验证都没写，红线没人证")
    rev = read(REVERSE)
    c.present("反验脚本里有注入表 `CASES`", rev, r"\nCASES: list\[tuple\[str, str, object, str\]\] = \[")
    doc = read(DOC)
    c.present("变更单写了 Blast Radius", doc, r"^- \*\*Blast Radius\*\*：L0")
    c.present("变更单里留了用户那句「它就像微信一样」", doc, r"它就像微信一样")
    c.present("变更单在登记簿里（表会骗人）", read(REG), r"^\|\s*[\x60]?CHG-0104[\x60]?\s*\|")
    c.present("设计系统里新增了这一节（§4.25j）", read(DESIGN), r"### 4\.25j ")

    return c.report("AI 聊天页的绿：一个像微信、又压得住白字的强调色（CHG-0104）")


if __name__ == "__main__":
    raise SystemExit(main())
