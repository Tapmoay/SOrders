#!/usr/bin/env python
"""亮色下「页面底那一层」必须是**不偏蓝的近白**，而且分层与抽屉那一层一个字没动 —— 台账 L-19 / CHG-0063。

⚠️ 2026-10-09 **CHG-0091（绿主题）改过一次口径**，改的是"偏哪一边"，**不是**把这条规矩废掉：
   用户给了「背景加一个由深绿往下到白色……大概到 1/3 的位置就全白了」（ref m01501），
   页面底于是从「暖白 #F8F7F4」改成「**中性近白**」—— 原来那种暖白压在纯白渐变尾巴上
   会露出一条肉眼可见的暖色带。**分层、不偏蓝、抽屉层与暗色一个字没动**这三条原样保留。
   改口径的同时必须改本文件 + 反验 + 设计基线文档，三处一起（否则这条判据会挡住绿主题）。

盯住八件事：

1. 四个 token 的精确值：`BackgroundLight` / `SurfaceVariantLight` / `SurfaceContainer` /
   `SurfaceContainerHigh` 是一套「近白家族」，不是原来那套灰蓝、也不是纯白一色到底。
2. 不偏蓝：每一层 R >= B（原来的 #F2F3F7 / #ECEFF5 / #E6E9F0 / #DDE1EA 全是 B > R，
   这正是用户说的「灰蓝」）。
3. 分层还在：白卡（`SurfaceLight` = #FFFFFF）仍是最亮的一层，往下 BackgroundLight →
   SurfaceVariantLight → SurfaceContainer → SurfaceContainerHigh 严格变暗、四个值互不相同。
   ⛔ 分层一塌（比如都刷成同一个白）不会有任何编译错误，只有这一组在盯。
4. 旧的灰蓝在亮色区一处不剩：那四个旧值在 `Color.kt` 的代码里 0 命中。
5. 底部抽屉与侧面抽屉不在此列：`SheetSurface` 仍是纯中性 #F0F0F0（R == G == B），
   `Theme.kt` 仍把 `surfaceContainerLow` 接给它 —— 那是全 App 底部抽屉与侧面抽屉共用的那一层。
   用户原话（m09782）：「底部抽屉啊，侧面抽屉啊，那些都不要搞啊别搞反了嘞」。
6. 暗色一块没动，描边也没动（`OutlineLight` / `OutlineVariantLight` 原值）。
7. 亮色四条接线都在 `Theme.kt`（background / surfaceVariant / surfaceContainer / surfaceContainerHigh）。
8. 设计基线文档同步：`docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` 里写的是新值、旧值 0 命中。

为什么这些必须由机器盯着：这几行就是四个十六进制数 —— 顺手改回去不会有任何编译错误、不会有
任何用例报红，屏幕上却是「整屏又灰蓝回去」或者「抽屉跟着变白」这种一眼就坏的结果；而分层塌了
（白卡与页面底同色）在真机上只剩「卡片看不出边界」这种说不清的观感。这条口径是用户在真机上
看一眼定下来的（ref m00481 / m09782），它不在任何后端契约或类型里。

R4-BOUNDARY-JUSTIFICATION: 这条判据不下沉到任何一层边界。被查的是亮色配色 token 与它的接线；
后端契约、领域类型、权限模型里都没有「页面底该偏暖还是偏蓝」的位置 —— 它是用户看到的观感口径，
`Color` 类型表达不出「暖」，所以只能钉在色值、相对关系与接线这几处（`_tools` 里原来一条都没有）。

配套：python `_tools/qa/_reverse_verify_warm_surface_palette.py`（11 种破坏方式全被抓）

用法：python _tools/qa/_check_warm_surface_palette.py  （--list 打一份人读清单）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
COLOR = AND / "ui" / "theme" / "Color.kt"
THEME = AND / "ui" / "theme" / "Theme.kt"
ENTRY_GRID = AND / "ui" / "common" / "EntryGrid.kt"
DESIGN = ROOT / "docs" / "PROJECT_MAP" / "06_DESIGN_SYSTEM.md"
CHG = ROOT / "docs" / "changes" / "CHG-0063.md"
README = ROOT / "docs" / "changes" / "README.md"
CLAIM = ROOT / "docs" / "AI_WORK_CLAIM.md"

#: 亮色这几层：页面底 → 周围那几层（越往下越深一档）。
#: 2026-10-06（台账 L-19）定的是暖白；2026-10-09（CHG-0091）随绿主题改成"中性近白"；
#: 2026-10-09 晚（CHG-0101）随用户第三套整体配色图改成**暖砂白**（#F7F6F3 系）。
NEAR_WHITE = {
    "BackgroundLight": 0xF7F6F3,
    "SurfaceVariantLight": 0xF1EFEA,
    "SurfaceContainer": 0xEFECE6,
    "SurfaceContainerHigh": 0xE4E0D9,
}

#: 那四个 token 的**旧值**：亮色区一处都不许剩。
#: ⚠️ CHG-0101 换色时踩过一次坑 —— 这里原先第一项写的是 `0xFFF7F6F3`（CHG-0063 那版暖白），
#:    而用户第三张图给的背景色**正好又是** `#F7F6F3` ⇒ 它从"旧值黑名单"变成了"当前值"，
#:    这条判据必须跟着改，否则会拿新值当旧值查（真跑出来 6 条红，全是这一处引起的）。
#: ⚠️ 也别把**新**的那四层（`F7F6F3` / `F1EFEA` / `EFECE6` / `E4E0D9`）写进来 —— 那是
#:    `NEAR_WHITE` 正面钉的值，写进黑名单就是自己跟自己打架。
OLD = [
    # CHG-0063 那版暖白之外的三层冷灰（B 比 R 高 = 用户说的「灰蓝」）
    "0xFFECEFF5", "0xFFE6E9F0", "0xFFDDE1EA",
    # CHG-0091 那一版的"中性近白"（偏冷），CHG-0101 起也不许再回来
    "0xFFFBFBFA", "0xFFF3F2EF", "0xFFEFEEEB", "0xFFE9E7E3",
]

#: 本事项明确不动的那几档：白卡 ＋ 暗色全档。
#: ⚠️ 两个字描边（OutlineLight / OutlineVariantLight）在 CHG-0101 里**跟着换了**
#:    （旧的 #7A7F8C / #CFD4E0 是冷灰，与暖砂白同屏发脏），所以它们不再进这张表 ——
#:    改由 CHG-0101 的判据正面钉住新值。
KEEP = {
    "SurfaceLight": 0xFFFFFF,
    "BackgroundDark": 0x0E1014,
    "SurfaceVariantDark": 0x44464F,
    "SurfaceContainerDark": 0x1E1F25,
    "SurfaceContainerHighDark": 0x292A31,
}

#: 亮色那四层在 Theme.kt 里各自接在哪一格（键 = Theme 里的属性名）。
WIRED = {
    "BackgroundLight": "background",
    "SurfaceVariantLight": "surfaceVariant",
    "SurfaceContainer": "surfaceContainer",
    "SurfaceContainerHigh": "surfaceContainerHigh",
}

#: 抽屉那一层的面（用户点名不许动）：纯中性，三通道相等。
SHEET = 0xF0F0F0

#: 反空转的下限：源码根下 .kt 的份数与 Color.kt 里认得出的亮色常量个数。
MIN_KT = 250
MIN_TOKENS = 20


def hexes(src: str, name: str) -> int | None:
    m = re.search(r"\bval " + name + r"\s*=\s*Color\(0xFF([0-9A-Fa-f]{6})\)", src)
    return int(m.group(1), 16) if m else None


def channels(v: int) -> tuple[int, int, int]:
    return (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF


def brightness(v: int) -> int:
    return sum(channels(v))


def show(v: int | None) -> str:
    return "#------" if v is None else "#%06X" % v


def present(self: Checker, label: str, text: str, pattern: str) -> None:
    m = re.search(pattern, text)
    self.ok(label, m is not None, f"没找到 {pattern!r}")


def absent(self: Checker, label: str, text: str, pattern: str) -> None:
    m = re.search(pattern, text)
    self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")


Checker.present = present  # type: ignore[attr-defined]
Checker.absent = absent  # type: ignore[attr-defined]


def main() -> int:
    c = Checker()

    c.section("0. 反空转：扫描本身得是活的")
    kts = sorted(AND.rglob("*.kt"))
    c.ok(f"扫到 {len(kts)} 个 .kt（下限 {MIN_KT}）", len(kts) >= MIN_KT, "源码根路径是不是变了？")
    color = strip_comments(read(COLOR))
    theme = strip_comments(read(THEME))
    found = re.findall(r"\bval [A-Za-z0-9_]+ = Color\(0xFF[0-9A-Fa-f]{6}\)", color)
    c.ok(f"Color.kt 里认出 {len(found)} 个亮色常量（下限 {MIN_TOKENS}）", len(found) >= MIN_TOKENS,
         "解析规则被改坏的话，下面每一组都会空过")

    c.section("1. 近白家族：四个精确值 ＋ 每一层 R >= B（不偏蓝）")
    vals = {name: hexes(color, name) for name in NEAR_WHITE}
    for name, want in NEAR_WHITE.items():
        got = vals[name]
        c.ok(f"Color.kt：{name} = {show(want)}", got == want, f"现在是 {show(got)}")
    for name, got in vals.items():
        if got is None:
            continue
        r, g, b = channels(got)
        c.ok(f"{name} 不偏蓝（R {r} >= B {b}）", r >= b,
             f"{show(got)} 的 B 通道高过 R —— 又回到用户说的「灰蓝」那一侧了")

    c.section("2. 分层没塌：白卡最亮，四层严格变暗")
    white = hexes(color, "SurfaceLight")
    c.ok("Color.kt：SurfaceLight 仍是纯白 #FFFFFF（卡片那一层没被顺手改）", white == 0xFFFFFF,
         f"现在是 {show(white)}")
    order = ["BackgroundLight", "SurfaceVariantLight", "SurfaceContainer", "SurfaceContainerHigh"]
    seq = [vals[n] for n in order]
    allp = all(v is not None for v in seq)
    distinct = allp and len({v for v in seq}) == len(order)
    c.ok("四层互不相同（分层还在）", distinct, f"现在有重复值：{seq}")
    if white is not None and allp and distinct:
        c.ok(f"白卡比页面底亮：{show(white)} > {show(seq[0])}", brightness(white) > brightness(seq[0]),
             "卡片和页面底同色 = 卡片看不出边界")
        deeper = all(brightness(seq[i]) > brightness(seq[i + 1]) for i in range(len(seq) - 1))
        c.ok("越往下越深一档：" + " > ".join(show(v) for v in seq), deeper, "顺序被调换或步长塌了")
    else:
        c.ok("白卡比页面底亮（上面的值先红了，这一条跟着红）", False, "先把上面四条的值修回来")
        c.ok("越往下越深一档（同上）", False, "先把上面四条的值修回来")

    c.section("3. 旧的灰蓝在亮色区一处不剩")
    for old in OLD:
        c.absent(f"Color.kt 的代码里不再有 {old}", color, re.escape(old))

    c.section("4. 底部抽屉 / 侧面抽屉那一层一个字没动（用户 m09782）")
    sheet = hexes(color, "SheetSurface")
    c.ok(f"Color.kt：SheetSurface 仍是 {show(SHEET)}（抽屉那一层的面）", sheet == SHEET,
         f"现在是 {show(sheet)}")
    if sheet is not None:
        r, g, b = channels(sheet)
        c.ok("SheetSurface 三通道相等（中性：没被卷进「暖」或「蓝」任何一侧）", r == g == b,
             f"{show(sheet)} 偏了：R {r} / G {g} / B {b}")
    c.present("Theme.kt：surfaceContainerLow 仍接给 SheetSurface（全 App 抽屉的面）", theme,
              r"(?m)^[ \t]*surfaceContainerLow = SheetSurface,")
    c.present("抽屉那一层自己的定义还在 Color.kt（没被删掉换成别的 token）", color,
              r"\bval SurfaceContainerLow = Color\(0xFF[0-9A-Fa-f]{6}\)")

    c.section("5. 暗色与描边没动 ＋ 亮色四条接线都在")
    for name, want in KEEP.items():
        got = hexes(color, name)
        c.ok(f"Color.kt：{name} = {show(want)}", got == want, f"现在是 {show(got)}")
    for name, key in WIRED.items():
        c.present(f"Theme.kt：{key} = {name}（接线还在，没换成别的档）", theme,
                  r"(?m)^[ \t]*" + key + r" = " + name + r",")

    c.section("6. 设计基线文档同步 ＋ 描边仍是原来那一份 ＋ 本事项的登记")
    design = read(DESIGN) if DESIGN.exists() else ""
    c.ok("docs/PROJECT_MAP/06_DESIGN_SYSTEM.md 在", DESIGN.exists(), "设计基线文档被搬走/改名了？")
    c.present("设计基线里页面底写的是新值", design, r"BackgroundLight=#F7F6F3")
    c.absent("设计基线里不再写旧值", design, r"BackgroundLight=#F2F3F7")
    c.present("设计基线点了「暖」这条口径（改色的人得看得到为什么）", design, r"暖")
    c.present("描边没动：EntryGrid 那一圈仍是 1dp 的 #ECEFF5", read(ENTRY_GRID),
              r"BorderStroke\(1\.dp, Color\(0xFFECEFF5\)\)")
    c.ok("docs/changes/CHG-0063.md 在（本事项的立项文档）", CHG.exists())
    c.present("README 有 CHG-0063 的登记行（链到文档）", read(README),
              r"\[CHG-0063\.md\]\(CHG-0063\.md\)")
    c.present("AI_WORK_CLAIM 里有本事项的条目", read(CLAIM), r"CHG-0063")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：亮色四层是近白家族、分层还在、抽屉与暗色一个字没动、设计基线已同步。")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("亮色近白家族：", ", ".join(f"{k}={show(v)}" for k, v in NEAR_WHITE.items()))
        print("旧的灰蓝（亮色区不许剩）：", " ".join(OLD))
        print("动不了的那几档：", ", ".join(f"{k}={show(v)}" for k, v in KEEP.items()))
        print("抽屉那一层的面：", show(SHEET))
        sys.exit(0)
    sys.exit(main())