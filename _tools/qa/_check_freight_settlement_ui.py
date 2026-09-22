"""红线：**司机运费结算这一页的形状** —— 抽屉选人 + 顶栏右上角月份（2026-09-22 用户第二轮）。

## 由来（用户原话，逐句对着做）

> 那个**司机运费结算**，我们的形式也发生改变时间嘛，我们也可以按照**右上角一个时间**（栏），
> 但是**月份的选择形式跟我们平常的不一样**。然后我们那个司机他那个**不要按照这样子的商品的管理**啊。
> 这样子，**非常不好** —— 我们直接换那个**类似于货主的账本管理**的那种形式，是那个**左侧的抽屉栏**
> 在那里选择人物，**也可以在那里搜索**，然后呢，选择之后，我们就可以**直接看对应的那个司机那个结账**。

## 这条判据守的事，坏起来都不会报错

| 写坏的方式 | 表现 |
|---|---|
| 又把 `MasterRail` 那套"商品管理式左栏"装回来 | 页面看着没坏，但用户已经点名否过一次（他会再否第二次） |
| 选人的抽屉**又各写一份** | 账本页的抽屉改了（比如加"停用"标记），结算页那份没跟上 —— 两边都不报错 |
| 把"月份"退回我们常用的那列**档位清单**（`DatePresetDialog`） | 用户点名的"**选择形式不一样**"当场失效（那是**按天**的档位，不是**月份**） |
| 换窗口时"回落到第一位司机" | 用户明明在看张师傅，切个月份屏幕上是李四的账 —— 界面上一句话都没有 |
| 「自定义区间」在改版里被顺手丢掉 | 2026-09-20 用户明确要过「除了上个月上上个月，还可以选择时间」 |

## 判据（清单**全部自己算**，不手写"要查哪些文件"）

1. **选人的零件只有一份**：全树 `fun PersonDrawer(` / `fun PersonTriggerRow(` 只在
   `ui/common/PersonPicker.kt`；调用点 ≥2（账本页 + 结算页）—— 少于 2 说明判据失配或在空转。
2. **抽屉里的搜索走共用那一份**：`PersonPicker.kt` 里有 `SearchField(`，且**没有**自己写的
   `.contains(` 匹配（按人搜索的规则只有 `core/UserSearch.kt` 一处）。
3. **结算页的形状**：`ModalNavigationDrawer` + `ModalDrawerSheet` + `PersonDrawer(` +
   `PersonTriggerRow(`；**没有** `MasterRail(`。
4. **时间是顶栏右上角的药丸**：`AppTopBar(` 的 `actions` 里调 `DatePresetPill(`。
5. **点开是年月网格**：`MonthPickerSheet(` + `(1..12).chunked(3)` + 年份左右翻；
   **不许**出现 `DatePresetDialog(`（那是"我们平常的"档位清单）。
6. **自定义区间还在**：网格里那一行接着开 `DateRangeDialog(`。
7. **选中态语义**：「空串 = 全部」；换了窗口**不许**悄悄回落到第一位司机
   （页面里得有"他在这一段没有单"那一支）。
8. 反空转：文件不存在、关键块为空、认出的调用点 < 2 都要先报错，而不是安静通过。

⚠️ 注入式反向验证（改坏 → 本脚本必须红）：
   `_tools/qa/_reverse_verify_freight_settlement_ui.py`。

用法：python _tools/qa/_check_freight_settlement_ui.py
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

PICKER = ANDROID / "ui/common/PersonPicker.kt"
SCREEN = ANDROID / "ui/dispatcher/FreightSettlementScreen.kt"
VM = ANDROID / "ui/dispatcher/FreightSettlementViewModel.kt"
LEDGER_SCREEN = ANDROID / "ui/dispatcher/DispatcherLedgerScreen.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

MIN_CALL_SITES = 2

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


def kt_sources() -> dict[Path, str]:
    return {p: strip_comments(io.open(p, encoding="utf-8", errors="replace").read())
            for p in sorted(ANDROID.rglob("*.kt"))}


def definers(srcs: dict[Path, str], name: str) -> list[Path]:
    """全树里**定义**了 `fun <name>(` 的文件（从源码算，不手写清单）。"""
    pat = re.compile(rf"\bfun {re.escape(name)}\(")
    return [p for p, s in srcs.items() if pat.search(s)]


def callers(srcs: dict[Path, str], name: str) -> list[Path]:
    """全树里**调用**了 `name(` 的文件（定义那一行不算调用）。"""
    pat = re.compile(rf"(?<!fun )\b{re.escape(name)}\(")
    return [p for p, s in srcs.items() if pat.search(s)]


def main() -> int:
    srcs = kt_sources()
    picker = read(PICKER)
    screen = read(SCREEN)
    vm = read(VM)
    design = io.open(DESIGN, encoding="utf-8", errors="replace").read()

    # ---- ① 选人的零件只有一份 ----
    print("选人的零件（页面上那一行入口 + 侧边抽屉）：**只有一份实现**")
    ok("PersonPicker.kt 里有数据形状 PersonOption", "data class PersonOption(" in picker)
    for name in ("PersonTriggerRow", "PersonDrawer"):
        ds = definers(srcs, name)
        ok(
            f"`fun {name}(` 全树只有一处定义（实测 {len(ds)}：{[str(p.relative_to(ROOT)) for p in ds]}）",
            ds == [PICKER],
            "同一个形态两个页面各写一份 = 改一处漏一处，而两边都不报错",
        )
        cs = [p for p in callers(srcs, name) if p != PICKER]
        ok(
            f"`{name}(` 的调用点 ≥{MIN_CALL_SITES} 个（账本页 + 司机结算页），实测 {len(cs)}",
            len(cs) >= MIN_CALL_SITES,
            f"实际 {[str(p.relative_to(ROOT)) for p in cs]} —— 低于 {MIN_CALL_SITES} 说明判据失配或在空转",
        )
    ok(
        "抽屉里的搜索走共用那一份 SearchField（不是各页自己画一个框）",
        re.search(r"SearchField\(", picker) is not None,
    )
    ok(
        "零件里没有自己写的按人匹配（规则只在 core/UserSearch.kt）",
        ".contains(" not in picker,
        "自己写一份 contains，就会出现「这一页搜得到、那一页搜不到」",
    )
    ok(
        "抽屉里的名单能滚（LazyColumn）—— 人多的时候它得装得下",
        "LazyColumn(" in picker,
    )

    # ---- ② 结算页的形状 ----
    print("\n司机运费结算页：抽屉选人 + 顶栏月份")
    ok("页面里有侧边抽屉（ModalNavigationDrawer）", "ModalNavigationDrawer(" in screen)
    ok(
        "抽屉真的挂在 ModalDrawerSheet 上（不是画在正文里的一个方块）",
        re.search(r"ModalDrawerSheet \{[\s\S]{0,800}?PersonDrawer\(", screen) is not None,
    )
    ok(
        "页面上有「选人」那一行入口（PersonTriggerRow）",
        re.search(r"PersonTriggerRow\(", screen) is not None,
    )
    ok(
        "⛔ 不再有商品管理那套左栏（MasterRail 是被用户点名否掉的）",
        "MasterRail(" not in screen,
        "用户 2026-09-22：「不要按照这样子的商品的管理啊。这样子，非常不好」",
    )
    ok(
        "⛔ 页内那行月份药丸没了（时间挪到顶栏之后不该还留一行）",
        "MonthPills" not in screen and "DatePresetRow(" not in screen,
    )
    ok(
        "VM 里也不再留换月份药丸用的那个方法（留着它，下一个人就会再做一个页内时间控件）",
        "fun shiftMonth(" not in vm,
    )

    # ---- ③ 时间是顶栏右上角的药丸，点开是年月网格 ----
    print("\n时间：顶栏右上角一个药丸 → 年月网格（**不是**我们平常那列档位清单）")
    ok(
        "药丸在 AppTopBar 的 actions 里（右上角）",
        re.search(r"AppTopBar\([\s\S]{0,500}?actions = \{[\s\S]{0,400}?DatePresetPill\(", screen) is not None,
    )
    ok(
        "药丸写着当前那一档（口径词永远看得见）",
        re.search(r"DatePresetPill\(label = vm\.periodLabel", screen) is not None,
    )
    ok(
        "点开是月份网格（年份左右翻 + 12 格）",
        re.search(r"MonthPickerSheet\(", screen) is not None
        and "(1..12).chunked(3)" in screen
        and re.search(r"year -= 1", screen) is not None,
    )
    ok(
        "⛔ 点开的**不是**我们平常那列档位清单（用户点名的「选择形式不一样」）",
        "DatePresetDialog(" not in screen and "DateFilterDialogs(" not in screen,
        "那两份是**按天**的档位清单；这一页结的是**月**",
    )
    ok(
        "换月份只走 VM 那一个入口（页面不自己拼月份字符串）",
        re.search(r"vm\.pickMonth\(", screen) is not None,
    )
    ok(
        "自定义区间还在（网格里那一行接着开区间弹层）",
        re.search(r"onCustom = \{[\s\S]{0,200}?showRange = true", screen) is not None
        and re.search(r"DateRangeDialog\(", screen) is not None,
        "用户 2026-09-20 要过「除了上个月上上个月，还可以选择时间」—— 不许在改版里丢掉",
    )
    ok(
        "月份网格里标注了「今天所在的月」（用户对着日历找「这个月」靠它）",
        re.search(r"isCurrent = key == current", screen) is not None,
    )

    # ---- ④ 选中态：空串 = 全部；换了窗口不悄悄换人 ----
    print("\n选中态：空串 = 全部；换了窗口**不许**悄悄回落到第一位司机")
    ok(
        "VM 里选中态初值是空串（= 全部）",
        re.search(r'selectedKey by mutableStateOf\(""\)', vm) is not None,
    )
    ok(
        "页面把空串当「全部」（写清有几个人）",
        re.search(r'vm\.selectedKey\.isBlank\(\) -> "全部（"', screen) is not None,
    )
    ok(
        "选了人、但这一段他没有单时**如实说**（有那一支空态）",
        re.search(r"vm\.selectedKey\.isNotBlank\(\) && selected == null", screen) is not None,
        "回落到第一位司机的表现是：我明明在看张师傅，屏幕上却是李四的账，而且一句话都没有",
    )
    ok(
        "名字存在 VM 里（换到他没有单的月份时，界面还说得清「他是谁」）",
        re.search(r"var selectedName by mutableStateOf", vm) is not None
        and re.search(r"vm\.selectedName", screen) is not None,
    )
    ok(
        "⛔ 页面里没有「选不到就取第一个」那种回落写法",
        re.search(r"\?: *visible\.firstOrNull\(\)", screen) is None,
    )

    # ---- ⑤ 钱的两个口径不许混 ----
    print("\n明细行显示的是**司机应得**（不是货主运费）")
    ok(
        "明细行取 payTotal（与组头合计同源）并另标注运费",
        re.search(r'formatMoney\(o\.payTotal\)', screen) is not None
        and 'if (o.freightFee != null) "运费 ¥"' in screen,
        "这一页有三个容易混的钱：取错了会出现「明细加起来 ≠ 上面那个数」",
    )
    ok(
        "抽屉里的名单带「¥… · N 单」（挑人的时候就看得到谁多少钱）",
        re.search(r'"¥" \+ formatMoney\(g\.total\.toString\(\)\) \+ " · " \+ g\.count \+ " 单"', screen) is not None,
    )

    # ---- ⑥ 设计规范里记着这条形状 ----
    print("\n设计规范：这两条形状写在文档里（下一个人照文档做，而不是照猜）")
    ok(
        "06_DESIGN_SYSTEM.md 的 §4.15 第 8 条记着这次的形状（含「按月不是按天」这条理由）",
        "§4.15 第 8 条" in design
        and "PersonPicker.kt" in design
        and "MonthPickerSheet" in design,
        "文档过期比没有文档更糟：下一个人会照「我们平常那列档位清单」再做一遍",
    )

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {passes} 项通过：结算页 = 抽屉选人 + 顶栏月份，且选人零件只有一份。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
