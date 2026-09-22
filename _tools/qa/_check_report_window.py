"""红线：**报表中心的时间控件与默认窗口** —— 一打开就有数、页面里没有会弹日历的暗雷（2026-09-22）。

## 由来（用户两轮原话）

第一轮（数据）：
> 修一下**报告中心没有任何数据**的bug。

第二轮（控件 + 那个日历）：
> 那你就将他的**界面**进行一下处理。尤其是……那个**时间选择**按照我们**现在的要求**进行处理；
> 而且点击**商品经营**的时候有时候会弹出**一个日历**吧，但是不知道是什么原因啊？这个也是个**小bug**，你解决一下。

## 两个 bug 的根因（都实测过）

1. **一打开全是 0**：报表页写死「按日 + 今天」，今天没有已送达的单时整页 ¥0.00；
   同一时刻「按月」是 ¥21,345.60 · 100 单 ⇒ 数据一直在，是**默认窗口**的事。
2. **点商品经营会弹日历**：页内那条 `ReportTimeNav` 顶上"完整时段"是个**可点的 Surface**，
   真机 dump 出来的节点是 `[42,296][803,422]`（**761×126 px**，正压在顶栏下面）——
   点它就弹 M3 的 `DatePickerDialog`。那一整块区域看起来只是"一行字"。

## 这条判据守的事，坏起来一条报错都不会有

| 写坏的方式 | 表现 |
|---|---|
| 又给报表页塞一个"点一下就开系统日期选择器"的控件 | 用户随手一点就弹日历（这一轮修掉的那个 bug） |
| 页面里又铺一条时间胶囊行 / 自造第三个时间控件 | 违反"一个页面一个时间控件、且是顶栏那颗药丸" |
| 六个页签各取各的窗口 | 同一屏两个时间段，而两边都"看着有理" |
| 自动挡自己再写一份阶梯 | 与订单/账本页的默认行为分叉 |
| 先取一次数、再异步退档 | 用户点名的「闪两下」 |
| 「全部」悄悄换成"近一年"那种更窄的窗口 | 口径词与窗口不一致（药丸写全部、数只有一年） |

## 判据（清单**全部自己算**，不手写"查哪些文件"）

1. **没有会自己弹日历的控件**：全树不许再有 `ReportTimeNav`（文件也不许回来），
   报表页里不许出现 `DatePicker(` / `DatePickerDialog(`。
2. **时间是顶栏右上角那颗药丸**：`AppTopBar` 的 `actions` 里 `DatePresetPill(`，
   点开是**共用的** `DateFilterDialogs`（五个页面同一份实现）。
3. **一个窗口**：`ReportFinance.windowOf` 是唯一的"档位 → (from, to)"实现，
   六个页签都从 `dateRange` 取；页面里不许出现 `vm.mode` / `vm.anchor` 这种第二套口径。
4. **先探测、再取数**：`windowSettled` 门；探测打的就是本页第一屏那个接口 + 同一段区间；
   `CancellationException` 原样抛出；没有时间控件的页签（异常与审计）不参与。
5. **后端认区间**：`/reports/turnover`、`/reports/products`、`/reports/export` 都收
   `date_from`/`date_to`，且窗口只有一个入口 `_span(...)`（半截窗口 400）。
6. 反空转：文件/函数/关键字块找不到时先报错，而不是安静通过。

⚠️ 注入式反向验证（改坏 → 本脚本必须红）：
   `_tools/qa/_reverse_verify_report_window.py`。

用法：python _tools/qa/_check_report_window.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用兄弟红线里剥 Kotlin 注释的实现（保留行号），不抄第二份。
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

FINANCE = ANDROID / "ui/dispatcher/ReportFinance.kt"
VM = ANDROID / "ui/dispatcher/ReportCenterViewModel.kt"
SCREEN = ANDROID / "ui/dispatcher/ReportCenter.kt"
PRESETS = ANDROID / "ui/common/DatePresets.kt"
TIME_NAV = ANDROID / "ui/common/ReportTimeNav.kt"
REPORTS_PY = ROOT / "backend/app/api/v1/reports.py"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/dispatcher/ReportFinanceTest.kt"

fails: list[str] = []
passes = 0


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的判据要跟着改，不许静默跳过）")
    return strip_comments(io.open(p, encoding="utf-8", errors="replace").read())


def slice_fun(src: str, header: str) -> str:
    """取出一个函数体：从 header 那行到**与它配平的那个 `}`**（找不到就返回空串）。

    ⚠️ 不能按"下一个 `\\n}`"截：Kotlin 里类成员是缩进的，`\\n}` 只匹配**最外层**那个收尾花括号
    ——于是"取一个函数"实际会一路吃到文件末尾，别的函数里出现过同一个词就会让判据假绿
    （本文件第一次跑反向验证时实测踩到：探测换成别的接口了，判据还是绿的，因为 `load()` 里也有一处）。

    ⚠️ 也不能只取"第一对花括号"：`= try { … } catch (…) { … }` 这种写法里，
    第一对括号是 **try 块**，`catch` 那几段会被切掉。后面跟 `catch` / `else` 就继续吃。
    """
    i = src.find(header)
    if i < 0:
        return ""
    k = src.find("{", i)
    if k < 0:
        return src[i:i + 400]
    end = None
    while True:
        depth = 0
        for m in range(k, len(src)):
            if src[m] == "{":
                depth += 1
            elif src[m] == "}":
                depth -= 1
                if depth == 0:
                    end = m
                    break
        if end is None:
            return src[i:]
        tail = src[end + 1:end + 60].lstrip()
        if tail.startswith("catch") or tail.startswith("else"):
            nk = src.find("{", end)
            if nk < 0:
                break
            k = nk
            continue
        break
    return src[i:end + 1]


def main() -> int:
    fin = read(FINANCE)
    vm = read(VM)
    screen = read(SCREEN)
    presets = read(PRESETS)
    reports_py = io.open(REPORTS_PY, encoding="utf-8", errors="replace").read()
    test = read(TEST)

    # ---- ① 「点一下就弹日历」那个控件不许回来 ----
    print("① 没有会自己弹日历的控件（这就是用户报的那个小 bug）")
    ok(
        "`ui/common/ReportTimeNav.kt` 已经删掉了（零引用）",
        not TIME_NAV.exists(),
        "留着下一个人还会把它装回报表页 —— 而它顶上那块 761×126 px 的可点区域就是弹日历的源头",
    )
    all_kt = {p: strip_comments(io.open(p, encoding="utf-8", errors="replace").read())
              for p in ANDROID.rglob("*.kt")}
    nav_users = [str(p.relative_to(ROOT)) for p, s in all_kt.items() if re.search(r"\bReportTimeNav\(", s)]
    ok(f"全树没有人再调用它（实测 {nav_users}）", nav_users == [])
    ok(
        "报表页里没有直接开系统日期选择器的地方（日期只从我们自己的弹层来）",
        re.search(r"DatePicker\(|DatePickerDialog\(|rememberDatePickerState\(", screen) is None,
    )

    # ---- ② 时间是顶栏右上角那颗药丸 ----
    print("\n② 时间 = 顶栏右上角一颗药丸 + 共用的档位清单")
    ok(
        "药丸在 AppTopBar 的 actions 里",
        re.search(r"AppTopBar\([\s\S]{0,700}?actions = \{[\s\S]{0,900}?DatePresetPill\(", screen) is not None,
    )
    ok("药丸写着当前档位（`vm.periodLabel`）", "DatePresetPill(label = vm.periodLabel" in screen)
    ok(
        "点开是**共用**那两个弹层（DateFilterDialogs，五个页面同一份实现）",
        re.search(r"DateFilterDialogs\(", screen) is not None,
    )
    ok(
        "两个回调都回到 VM（vm.applyPreset / vm.applyCustomRange）",
        re.search(r"onPickPreset = \{ vm\.applyPreset\(it\) \}", screen) is not None
        and re.search(r"onApplyCustom = \{ f, t -> vm\.applyCustomRange\(f, t\) \}", screen) is not None,
    )
    ok(
        "⛔ 页面里没有第二条时间控件（胶囊行 / 报表自带的时间导航）",
        "DatePresetRow(" not in screen and "ReportTimeNav" not in screen,
    )

    # ---- ③ 一个窗口：档位 → (from, to) 只有一份 ----
    print("\n③ 六个页签**共用一段**窗口（口径只有一处）")
    ok(
        "有 ReportFinance.windowOf（纯函数）与它引用的 DatePresets.rangeOf",
        "fun windowOf(" in fin and re.search(r"DatePresets\.rangeOf\(", fin) is not None,
    )
    win = slice_fun(fin, "fun windowOf(")
    ok("自定义用自己那一段", "DatePresets.CUSTOM" in win and "customFrom to customTo" in win)
    ok("「全部」落成一段覆盖所有数据的区间（ALL_FROM ~ 今天）",
       "ALL_FROM" in win and re.search(r"\?: \(ALL_FROM to today\.toString\(\)\)", win) is not None,
       "报表端点必须给一段窗口；换成「近一年」那种更窄的 = 口径词与窗口不一致")
    ok("ReportFinance 里没有自己再算一遍区间（月份/周首那种算法）",
       "dayOfWeek" not in fin and "lengthOfMonth" not in fin)
    ok("VM 的 dateRange 只调那一个入口",
       re.search(r"val dateRange: Pair<String, String>[\s\S]{0,200}?ReportFinance\.windowOf\(", vm) is not None)
    ok("⛔ 报表页不再有第二套窗口状态（mode/anchor）",
       not re.search(r"\bvm\.(mode|anchor)\b", screen) and "var mode by" not in vm and "var anchor by" not in vm)
    ok("档位是 DatePresets 那一套（`var preset`）", "var preset by mutableStateOf(" in vm)
    ok("VM 引用的档位常量都在 DatePresets 里真的存在（防化石）",
       all(k in presets for k in ("ORDER_PRESET_LADDER", "pickWindow", "rangeOf", "CUSTOM")))
    ok("受控的页签共用同一个 dateRange（0/1 走 turnover/products 时也传区间）",
       re.search(r"turnoverReport\(\s*ReportFinance\.LEGACY_MODE, f, f, t\s*\)", vm) is not None
       and re.search(r"productReport\(\s*ReportFinance\.LEGACY_MODE, f, f, t\s*\)", vm) is not None)

    # ---- ④ 自动挡：先探测、再取数 ----
    print("\n④ 自动挡（一打开就有数）：先探测、再取数")
    ok("用共享的 DatePresets.pickWindow", re.search(r"DatePresets\.pickWindow\(", vm) is not None)
    ok("阶梯是共享的 DatePresets.ORDER_PRESET_LADDER",
       re.search(r"pickWindow\(DatePresets\.ORDER_PRESET_LADDER\)", vm) is not None)
    settle = slice_fun(vm, "private fun settleWindowThenLoad(")
    i_settled = settle.find("windowSettled = true")
    i_load = settle.find("load()")
    ok("**先探测、再取数**：windowSettled 必须在 load() 之前",
       i_settled >= 0 and i_load >= 0 and i_settled < i_load,
       "顺序反了就是用户点名的「闪两下」")
    ok("探测用的就是那一档的区间（同一段，不另算）",
       re.search(r"DatePresets\.rangeOf\(label, today\)", settle) is not None)
    probe = slice_fun(vm, "private suspend fun windowHasData(")
    ok("探测打的是本页自己要打的那个接口（probe 函数体里就是 turnoverReport + 区间）",
       re.search(r"repo\.turnoverReport\(", probe) is not None and re.search(r"from, from, to", probe) is not None,
       "换个便宜的近似接口 = 探到了进去还是空，正是这个 bug 的翻版")
    ok("探测里的 CancellationException 原样抛出", "catch (e: CancellationException)" in probe and "throw e" in probe)
    ok("探测失败按「这一档没数」继续往后退",
       re.search(r"catch \(e: Exception\) \{\s*false\s*\}", probe) is not None)
    ok("「异常与审计」（tab 5，没有时间控件）不参与定窗口",
       re.search(r"if \(tab == 5\) \{\s*windowSettled = true\s*load\(\)", vm) is not None)
    ok("有那道门（!vm.windowSettled → LoadingBox），且药丸也在门后面",
       re.search(r"!vm\.windowSettled\) \{\s*LoadingBox\(", screen) is not None
       and re.search(r"if \(vm\.tab != 5 && vm\.windowSettled\)", screen) is not None)
    ok("窗口状态声明在 init 之前", vm.find("var windowSettled") < vm.find("init {"))
    ok("有数的判据同时认单数与金额", "totalOrders > 0" in fin and "toDoubleOrNull()" in fin)

    # ---- ⑤ 后端认区间，且窗口只有一个入口 ----
    print("\n⑤ 后端：区间优先、半截窗口 400、窗口只有一个入口")
    ok("有 `_span(` 这个唯一入口", re.search(r"def _span\(", reports_py) is not None)
    span = reports_py[reports_py.find("def _span("):]
    span = span[:span.find("\ndef ", 10)] if "\ndef " in span[10:] else span
    ok("只给一头 → 400（不许猜另一头）", re.search(r"必须同时给|只有一头|成对", span) is not None
       or "date_from 与 date_to 必须同时给" in reports_py)
    ok("结束早于开始 → 400", "结束日期不能早于开始日期" in reports_py)
    ok("turnover / products 两个端点都收 date_from/date_to",
       reports_py.count("date_from: date | None = Query(None") >= 3,
       "营业纵览 / 商品经营 / 导出 —— 少一个就会出现「页面按区间、那个端点按 mode」")
    ok("两个 build_* 都收 `span` 并且**共用同一段聚合**",
       reports_py.count("span: tuple[date, date] | None = None") == 2
       and reports_py.count("span if span else _window(mode, anchor)") == 2)
    ok("导出也走同一个 `_span(`（文件名与内容同一段）",
       re.search(r"s, e = _span\(mode, d, date_from, date_to\)", reports_py) is not None)
    ok("曲线的粒度由**窗口**决定（不再只看 mode）",
       re.search(r"if start == end:\s*\n\s*series = \[", reports_py) is not None,
       "只看 mode 的话：整月区间 + mode=day 会画成每小时一个点")

    # ---- ⑥ 单测把新规矩钉住 ----
    print("\n⑥ 单测：新口径各有人钉")
    for needle, label in (
        ("时间窗口：档位 → (from, to)", "档位 → 区间"),
        ("半截自定义落到最宽的窗口", "半截自定义"),
        ("「全部」落成一段覆盖所有数据的区间", "全部"),
        ("每一档都能落成区间", "自动挡那一串档位每一档都能落成区间"),
        ("有数的判据", "单数或金额任一非零"),
    ):
        ok(f"单测里有「{label}」那一条", needle in test)

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {passes} 项通过：报表时间 = 顶栏药丸 + 共用弹层，六个页签一段窗口，且没有会弹日历的暗雷。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
