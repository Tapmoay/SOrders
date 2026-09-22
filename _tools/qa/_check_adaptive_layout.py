"""红线：**一行放不下时**，全 App 只许走一条规则 —— **换行 或 滑动**。

⛔ 不按屏宽等比缩放字号、⛔ 不缩小字号、⛔ 不截断文字（尤其状态/档位这种"少一个字就是另一个意思"的词）。

## 由来（用户 2026-09-22，原话）
> 「所有卡片样式要根据手机的不同的大小来做一个适配……比如说就是正常的一种缩放吧，svg 啊的一种形式」→
> 看到我造的坏屏后当场改口：「**我们的小屏整体的样式是不能有改变的**……甚至那个小屏啊，我发现，
> 我们这些**字体都已经看不清了**……我们要去**权衡一下大屏小屏**……你要看**其他人的方案**是怎么做的，
> 尤其是**大厂**……**他不可能每度做一遍**吧」。

## 为什么"等比缩放"这条路被否掉（官方出处，写在 `ui/common/Adaptive.kt` 里）
1. 官方断点：**宽度 < 600dp 的手机竖屏全部算同一档（紧凑）**，只有 600/840/1200/1600 才换版式
   → **手机之间本来就不该做两套适配**；
2. 官方：**sp 的职责就是跟随用户的字体设置**；**Android 14 起必须能扛住系统字号 200%**
   （非线性放大曲线的唯一目的就是"别让大字被截断"）→ 缩字号与这条正好相反。

## 这一页在防什么（每条都对应一种"真机上才看得见、而且不报错"的塌陷）
1. **档位条被截断成歧义**：`maxLines = 1` 不写 `overflow` = 默认**剪掉**。中文一字一格，
   320dp + 系统字号 1.3 时「已接单→**已接**、已送达→**已送**」—— 用户分不出这两档，
   而且切错档看到的是另一批订单（**信息错误**，不是"不好看"）；
2. **缩字号**：有人为了"塞得下"把 sp 改小 —— 那是把老人特意调大的字又压回去；
3. **按屏宽缩放**（`Density` 覆盖 / `fontScale` 参与换算 / 设计稿宽缩放）：一旦进来，
   全 App 的字号就与用户的字体设置脱钩，而且**没人会再收到报错**；
4. **长串被折行**：单号是 21 位，和状态徽章挤不进一行时会被折成「…31271」+「78」；
   徽章宽度 = 文字实测 + 38dp，**改徽章内边距却忘了改这个常数**，判定就会算错；
5. **可伸缩的文本没给 `weight`**：它自己会去挤**后面的兄弟**（真机踩到：长单号把日期挤成一条缝，
   `2026-09-19` 被折成 `202`/`6-0`/`9-1`/`9` 四行 —— 而且 **411dp 下就能看见**）。
   存量的处数记在 `_adaptive_squeeze_baseline.txt` 里：**只许往下减，不许涨**。

清单**自己算**（扫 `ui/**/*.kt`，不手写文件名单）；每节都带数量下限，扫描规则腐烂时先红再说。

用法：
    python _tools/qa/_check_adaptive_layout.py            # 查
    python _tools/qa/_check_adaptive_layout.py --update    # 重写存量基线（改完存量处数才用）
配套：python _tools/qa/_reverse_verify_adaptive_layout.py（8 种破坏方式全被抓）
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker, read, strip_comments  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
UI_DIR = SRC / "ui"
COMMON = UI_DIR / "common"
ADAPTIVE = COMMON / "Adaptive.kt"
TABS = COMMON / "SegmentedStatusTabs.kt"
CARD = COMMON / "OrderCard.kt"
COMPONENTS = COMMON / "Components.kt"
ENTRY_GRID = COMMON / "EntryGrid.kt"
EXPENSES = UI_DIR / "dispatcher/ExpensesScreen.kt"
BASELINE = Path(__file__).resolve().parent / "_adaptive_squeeze_baseline.txt"

ELLIPSIS = "overflow = TextOverflow.Ellipsis"

#: 允许出现 `screenWidthDp` 的文件（**它就是"按屏宽改版式"的唯一合法用途：数格子**）。
#: 值 = 允许出现的次数。多一处就必须有人来解释 —— 防的是"悄悄按屏宽改字号"从这里溜进来。
SCREEN_WIDTH_ALLOWED: dict[str, int] = {"ui/common/EntryGrid.kt": 1}


# ── 解析小工具（错了就跳过，**宁可漏报也不许误报**：误报会让这条红线变成"永远红"）──────


def paren_block(src: str, open_idx: int) -> int | None:
    """从 `(` 配对到 `)`，返回闭合下标。"""
    depth = 0
    i = open_idx
    while i < len(src):
        c = src[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def brace_block(src: str, open_idx: int) -> int | None:
    """从 `{` 配对到 `}`（跳过字符串里的花括号）。"""
    depth = 0
    i = open_idx
    in_str = False
    while i < len(src):
        c = src[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def call_blocks(src: str, name: str) -> list[tuple[int, int, str]]:
    """所有 `name(...)` 调用：`[(起点, 终点, 整段源码)]`。

    ⚠️ 前置字符不能是字母/点（否则 `BasicText(` / `foo.Text(` 会被误当成 `Text(`）。
    """
    out: list[tuple[int, int, str]] = []
    for m in re.finditer(rf"(?<![\w.]){name}\(", src):
        end = paren_block(src, m.end() - 1)
        if end is None:
            continue
        out.append((m.start(), end + 1, src[m.start(): end + 1]))
    return out


def fun_body(src: str, name: str) -> str | None:
    """`fun name(...) { ... }` 的函数体（找不到就 None）。"""
    m = re.search(rf"\bfun\s+{name}\s*\(", src)
    if not m:
        return None
    close = paren_block(src, m.end() - 1)
    if close is None:
        return None
    brace = src.find("{", close)
    if brace < 0:
        return None
    end = brace_block(src, brace)
    if end is None:
        return None
    return src[brace: end + 1]


# ── 存量扫描：`Text(maxLines = 1, overflow = Ellipsis)` 却没给 weight ─────────────


def squeeze_lines(src: str) -> list[int]:
    """这种文本**自己会被挤瘪**（更准确地说：它会去吃宽度，把后面的兄弟挤成一条缝）。"""
    hits: list[int] = []
    for s, _e, block in call_blocks(src, "Text"):
        if ELLIPSIS not in block or not re.search(r"maxLines\s*=\s*1\b", block):
            continue
        # 已经定死宽度的（weight / width / fillMaxWidth）不算 —— 它不会去抢别人的宽度
        if re.search(r"weight\(|\.width\(|fillMaxWidth", block):
            continue
        hits.append(src.count("\n", 0, s) + 1)
    return hits


def kt_files() -> list[Path]:
    return sorted(p for p in UI_DIR.rglob("*.kt") if p.is_file())


def squeeze_by_file() -> dict[str, int]:
    out: dict[str, int] = {}
    for p in kt_files():
        n = len(squeeze_lines(strip_comments(read(p))))
        if n:
            out[p.relative_to(SRC).as_posix()] = n
    return out


def read_baseline() -> dict[str, int]:
    if not BASELINE.exists():
        return {}
    out: dict[str, int] = {}
    for line in read(BASELINE).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.rsplit(None, 1)
        if len(parts) == 2 and parts[1].isdigit():
            out[parts[0]] = int(parts[1])
    return out


def write_baseline(rows: dict[str, int]) -> None:
    lines = [
        "# 基线：`Text(maxLines = 1, overflow = TextOverflow.Ellipsis)` 却没给 `weight` 的**存量**处数。",
        "# 由 `python _tools/qa/_check_adaptive_layout.py --update` 生成；只比**处数**、不比行号",
        "# （行号会腐烂，处数不会）。⛔ 只许往下减：涨一处就红 —— 这类文本会去挤它后面的兄弟，",
        "# 真机上表现为「日期被折成四行」「电话被挤成一条缝」，而两边都不报错。",
        "#",
        "# 格式：  <相对 android/app/src/main/java/com/tapmoay/sorders 的路径>  <处数>",
        "",
    ]
    for path in sorted(rows):
        lines.append(f"{path} {rows[path]}")
    BASELINE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="重写存量基线")
    a = ap.parse_args()

    if refuse_if_injecting("自适应布局红线"):
        return 1

    if a.update:
        rows = squeeze_by_file()
        write_baseline(rows)
        total = sum(rows.values())
        print(f"✅ 基线已重写：{len(rows)} 个文件 / 共 {total} 处 → {BASELINE.name}")
        return 0

    c = Checker()
    files = kt_files()

    # ── 0. 反空转 ─────────────────────────────────────────────────────────
    c.section("0. 反空转（扫描规则被改坏时必须先喊）")
    c.ok(f"扫到 ui/**/*.kt ≥ 60 个（实际 {len(files)}）", len(files) >= 60)
    all_src = {p: strip_comments(read(p)) for p in files}
    n_ellipsis = sum(s.count(ELLIPSIS) for s in all_src.values())
    c.ok(f"全库 `overflow = Ellipsis` 站点 ≥ 40（实际 {n_ellipsis}）", n_ellipsis >= 40)
    for p in (ADAPTIVE, TABS, CARD, COMPONENTS, ENTRY_GRID, EXPENSES):
        c.ok(f"在（{p.name}）", p.exists())
    if c.fails:
        print("\n❌ 扫描本身不成立，后面的结论不可信")
        return 1

    adaptive = strip_comments(read(ADAPTIVE))
    adaptive_raw = read(ADAPTIVE)
    tabs = strip_comments(read(TABS))
    card = strip_comments(read(CARD))
    comps = strip_comments(read(COMPONENTS))
    grid = strip_comments(read(ENTRY_GRID))
    exp = strip_comments(read(EXPENSES))

    # ── 1. 规则只有一份 ────────────────────────────────────────────────────
    c.section("1. 「放不下怎么办」只有 Adaptive.kt 一份，且写明了官方出处")
    c.ok("Adaptive.kt 导出 `rememberTextWidth`（实测，不是按字数猜）",
         "fun rememberTextWidth(" in adaptive)
    c.ok("Adaptive.kt 有 `ROW_ITEM_GAP`（判定与排版同一个间隔）", "val ROW_ITEM_GAP" in adaptive)
    c.ok("Adaptive.kt 引了官方「窗口大小类别」那一页（断点出处）",
         "layouts/adaptive/use-window-size-classes" in adaptive_raw)
    c.ok("Adaptive.kt 写明 600dp 才是断点（手机竖屏是同一档）", "600" in adaptive_raw)
    c.ok("Adaptive.kt 引了官方「字体 200%」那一页（不缩字号的依据）",
         "versions/14/features" in adaptive_raw)

    # ── 2. 档位条：放不下就滑动，标签永不截断 ───────────────────────────────
    c.section("2. 档位条（SegmentedStatusTabs）：放得下照旧、放不下整条滑动")
    c.ok("有 `BoxWithConstraints`（先知道自己有多宽）", "BoxWithConstraints(" in tabs)
    c.ok("有 `horizontalScroll`（放不下时的退路）", "horizontalScroll(" in tabs)
    c.ok("用 `rememberTextWidth` 实测每格宽度", "rememberTextWidth(" in tabs)
    c.ok("有 `needEqual` 判定（等宽铺满时最宽那格也得放得下）", "needEqual" in tabs)
    c.ok("`weight` 只挂在「放得下」那一支（滑动支上挂 weight 会与无限宽约束打架）",
         "if (fits) Modifier.weight(1f) else Modifier," in tabs)
    c.ok("标签 `softWrap = false`（不许折成两行）", "softWrap = false" in tabs)
    c.ok("等宽那一支的文字**不加内边距**（加了会把内容盒子挤窄 → 判定说放得下、画出来却被切）",
         "pad = if (fits) 0.dp else TAB_H_PADDING" in tabs)
    c.ok("量的是**纯文字宽**（没把内边距算进 needEqual —— 算进去就会量宽了还自以为放得下）",
         "widths += rememberTextWidth(it, labelStyle) }" in tabs)
    c.ok("⛔ 标签里没有 `TextOverflow.Ellipsis`（截断＝改成另一个意思）", ELLIPSIS not in tabs)
    c.ok("⛔ 标签里没有 `TextOverflow.Clip` 这种显式剪裁", "TextOverflow.Clip" not in tabs)

    # ── 3. 单号行：两种形态 ────────────────────────────────────────────────
    c.section("3. 订单卡片的单号行：放得下=原样，放不下=单号独占一行")
    c.ok("用 `rememberTextWidth(orderNumber, numberStyle)` 实测单号",
         "rememberTextWidth(orderNumber, numberStyle)" in card)
    c.ok("用 `orderStatusChipWidth(order.status)` 实测徽章",
         "orderStatusChipWidth(order.status)" in card)
    c.ok("`numberStyle` 同时喂给 Text 与测量（两边不许各写一个 style）",
         "style = numberStyle" in card and "rememberTextWidth(orderNumber, numberStyle)" in card)
    c.ok("有 `onOneLine` 的两支（放得下 / 放不下）",
         "if (onOneLine)" in card and "else {" in card)
    number_calls = [b for _s, _e, b in call_blocks(card, "Text") if "orderNumber" in b]
    c.ok(f"单号那一处 Text 找得到（{len(number_calls)} 处）", len(number_calls) >= 1)
    c.ok("⛔ 单号没有 `Ellipsis`（21 位单号截断就看不出是哪一单）",
         all(ELLIPSIS not in b for b in number_calls))
    c.ok("⛔ 单号没有 `TextOverflow.Clip`", all("TextOverflow.Clip" not in b for b in number_calls))

    # ── 4. 徽章常数与源码对账 ──────────────────────────────────────────────
    c.section("4. 徽章宽度的常数 = 徽章源码里那几个数之和（防「改了内边距忘改常数」）")
    chip_body = fun_body(comps, "OrderStatusChip")
    c.ok("拿到 `OrderStatusChip` 的函数体", chip_body is not None)
    if chip_body:
        pad = re.search(r"padding\(horizontal\s*=\s*([\d.]+)\.dp", chip_body)
        icon = re.search(r"size\(([\d.]+)\.dp\)", chip_body)
        gap = re.search(r"Spacer\(Modifier\.width\(([\d.]+)\.dp\)\)", chip_body)
        const = re.search(r"val\s+ORDER_CHIP_CHROME_DP\s*=\s*([\d.]+)\.dp", comps)
        c.ok("徽章的内边距/图标/间隔三个数都解析到了",
             all(x is not None for x in (pad, icon, gap)))
        c.ok("解析到 `ORDER_CHIP_CHROME_DP`", const is not None)
        if all(x is not None for x in (pad, icon, gap, const)):
            want = 2 * float(pad.group(1)) + float(icon.group(1)) + float(gap.group(1))
            got = float(const.group(1))
            c.ok(f"ORDER_CHIP_CHROME_DP = {got} == 2×{pad.group(1)} + {icon.group(1)} + {gap.group(1)} = {want}",
                 abs(want - got) < 0.01,
                 f"徽章源码里那三个数加起来是 {want}dp，而常数写的是 {got}dp —— 宽度判定会算错")
    c.ok("徽章文字样式只有一份 `chipLabelStyle()`（测量与渲染共用）",
         "fun chipLabelStyle()" in comps and comps.count("chipLabelStyle()") >= 3)

    # ── 5. 存量：可伸缩文本必须给 weight ───────────────────────────────────
    c.section("5. 可伸缩文本必须显式给 weight（否则它去挤后面的兄弟）")
    now = squeeze_by_file()
    base = read_baseline()
    c.ok("基线文件在（`--update` 生成）", BASELINE.exists(), f"缺 {BASELINE.name}")
    grew: list[str] = []
    for path, n in sorted(now.items()):
        allowed = base.get(path, 0)
        if n > allowed:
            grew.append(f"{path}：{allowed} → {n}")
    c.ok(f"没有新增（存量 {sum(base.values())} 处，现在 {sum(now.values())} 处）",
         not grew, "涨了：" + "；".join(grew))
    gone = [p for p in base if now.get(p, 0) < base[p]]
    if gone:
        print(f"  [ℹ️]  比基线少了（可以 `--update` 收紧）：{', '.join(sorted(gone))}")
    c.ok("开销卡那一处已修（`ExpensesScreen` 的主关联文本带 weight）",
         _has_weighted_text(exp, "primary.label"))

    # ── 6. 不许按屏宽缩放 ─────────────────────────────────────────────────
    c.section("6. ⛔ 不许「按屏宽等比缩放字号」（官方否掉的那条路）")
    bad_scale: list[str] = []
    for p, s in all_src.items():
        rel = p.relative_to(SRC).as_posix()
        if "fontScale" in s:
            bad_scale.append(f"{rel}：出现 fontScale")
        if re.search(r"\bDensity\(", s):
            bad_scale.append(f"{rel}：自己构造 Density（覆盖系统密度/字号）")
        if re.search(r"CompositionLocalProvider\s*\(\s*LocalDensity", s):
            bad_scale.append(f"{rel}：覆盖 LocalDensity")
    c.ok("没有「缩放字号」的野路子（fontScale / Density 覆盖）", not bad_scale,
         "；".join(bad_scale))
    bad_width: list[str] = []
    for p, s in all_src.items():
        rel = p.relative_to(SRC).as_posix()
        n = s.count("screenWidthDp")
        if n and SCREEN_WIDTH_ALLOWED.get(rel) != n:
            bad_width.append(f"{rel}：{n} 处（允许 {SCREEN_WIDTH_ALLOWED.get(rel, 0)}）")
    c.ok("`screenWidthDp` 只用在数格子上（改版式可以，改字号不行）", not bad_width,
         "；".join(bad_width))

    # ── 7. 入口网格：手机恒 2 列 ───────────────────────────────────────────
    c.section("7. 入口网格：手机恒 2 列（不许掉到 1 列）")
    c.ok("用 `maxOf(2, …)` 兜住下限", "maxOf(2," in grid)
    c.ok("⛔ 没用 `GridCells.Adaptive`（窄屏会掉到 1 列 = 小屏样式变了）",
         "GridCells.Adaptive" not in grid)
    c.ok("列数来自 `LocalConfiguration.current.screenWidthDp`",
         "LocalConfiguration.current.screenWidthDp" in grid)

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {c.n_ok} 项通过，{len(c.fails)} 项失败：")
        for label, detail in c.fails:
            print(f"   - {label}" + (f"\n     {detail}" if detail else ""))
        return 1
    print(f"✅ 自适应布局 {c.n_ok} 项全绿")
    return 0


def _has_weighted_text(src: str, needle: str) -> bool:
    for _s, _e, block in call_blocks(src, "Text"):
        if needle in block:
            return bool(re.search(r"weight\(", block))
    return False


if __name__ == "__main__":
    sys.exit(main())
