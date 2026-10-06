# -*- coding: utf-8 -*-
"""红线：同一个事实只许有一种说法（CHG-0028，2026-10-03 E2E 走查 P3 / P5 / P11 / P13 +「已沽清」残余）。

## 这条是怎么来的
2026-10-03 的 E2E 走查里，用户看到的四处「同一个事实两处说法」，外加一处历史遗留：

- P3 新增商品页：「库存」那一行画着必填红星 *，同一行的占位语却写「初始库存（选填）」；
- P5 分类下 0 个商品时，商品分类管理页写「暂无商品」，商品分组选择器里写「0 个商品」；
- P11 新增车辆的车型默认「挂车」（＝下拉第一项），而真实名册里最多的是小货车
  （vehicles 表 small 11 / large 3 / trailer 1），不注意就会建错车型；
- P13 订单卡上的异常图标只有一个 ⚠＋「异常」，是哪一类（钱货风险 / 履约卡住 / 一般）只在
  「报表中心 → 异常与审计」看得到，两页之间没有链接；
- 遗留：同一个状态（products.is_active = false）商品卡上写「已沽清」，
  账户管理的商品勾选列表写「已下架」。

## 为什么必须有机器的判据
这五处的共同形状是「同一个事实有两份实现」，而两份实现在**类型上完全一样**：

- 红星是 required = true 画的，与占位语那句「（选填）」是两个字段，编译器不会发现它们打架；
- CategoryChoice(it.name, it.productCount.toString() + " 个商品") 与走共用函数**类型一样**；
- VEHICLE_TYPES 的顺序与 draftType 的初值是两处独立的字面量，改一处永远绿；
- 卡片上写 label = "钱货风险" 与写 label = orderExceptionRisk(order).label 一样能编译，
  但前者会在报表页改词的那天悄悄说另一个名字；
- 多抄一个「已下架」同样不会红。

所以判据分六层：
1. 库存那一行不画红星，而且**全库**没有「选填 + required = true」的行（类级，不只这一行）；
   同时钉住后端 ProductCreate.stock 仍是可选 —— 那一行的「选填」不是我们自己编的；
2. 分类商品数只有一份实现（0 处也红）、三个调用点都走它、别处 0 处自己拼；
3. 车型默认值与下拉第一项**同源**（DEFAULT_VEHICLE_TYPE = VEHICLE_TYPES.first().first），
   那个 "trailer" 字面量只出现在取值表与中文名映射里（不在任何赋值 / 默认值位置）；
4. 订单卡说的类别词来自共用判据，卡片自己不写词；报表页那条入口与卡片那条入口都交给
   同一份本体（exceptionRiskOf 全库一处定义）；
5. UI 代码里同一个状态只有一个词（已下架 0 处），共用角标仍是那个词；
   领域动作词「下架」只留在后端描述与 AI 话术里（界面词是「沽清」）；
6. 与反向验证脚本配对，文档 / 登记表 / 认领簿三处都记了这条（防「永远红 / 永远绿」）。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。上面那五对「两份实现」在类型系统里
完全等价 —— 画红星的字段与占位语是两个独立字段；自己拼的副标题与共用函数的返回值同为
String；默认车型是另一个字面量；卡片自己写的类别词同样是 String。任何一处改了都不影响
编译、也不影响别的单测，只有**扫结构**才问得出「这个事实是不是只有一个说法」。
反向破坏用例由 _tools/qa/_reverse_verify_wording_consistency.py（13 条注入）负责；
「用户确实看到了」那一头由 2026-10-03 模拟器 5554 / 5556 / 5558 的截图负责。
本判据只读源码与文档（read()），不连库、不 import 后端、不跑迁移。

用法：python _tools/qa/_check_wording_consistency.py
     python _tools/qa/_check_wording_consistency.py --list   # 只列它到底在查什么
"""
from __future__ import annotations

import re
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
UI = AND / "ui"

FORM = AND / "ui/dispatcher/ProductFormScreen.kt"
BATCH = AND / "ui/dispatcher/ProductBatchScreen.kt"
CATS = AND / "ui/dispatcher/ProductCategoriesScreen.kt"
PICKER = AND / "ui/common/CategoryPickerSheet.kt"
VEHICLE = AND / "ui/dispatcher/VehicleManageScreen.kt"
ORDERS = AND / "ui/dispatcher/DispatcherOrdersScreen.kt"
PRIORITY = AND / "ui/dispatcher/ReportPriority.kt"
REPORT = AND / "ui/dispatcher/ReportCenter.kt"
USERS = AND / "ui/dispatcher/UsersManageScreen.kt"
BADGE = AND / "ui/common/ProductCardKit.kt"
# CHG-0062：账户管理页「商品可见范围」第二层的那一列商品行整块搬进了这个共用零件，
# 所以第 5 节「同一个状态只有一个词」要连着这个文件一起看（搬家不是放宽）。
PART = AND / "ui/common/ProductCheckList.kt"
SCHEMA = ROOT / "backend/app/schemas/product.py"
PRODUCTS_API = ROOT / "backend/app/api/v1/products.py"
README = ROOT / "docs/changes/README.md"
DOC = ROOT / "docs/changes/CHG-0028.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = "_tools/qa/_reverse_verify_wording_consistency.py"

#: 扫到的界面文件数下限（防目录改名 / 搬走之后"一个文件都没扫到"也算过）
MIN_UI_FILES = 100
#: 扫到的输入行数下限（同上：抽取失效比判据腐烂更危险）
MIN_FORM_ROWS = 40

#: 共用那一份（改词要改这里，别处只许调用它）
CAT_LABEL = 'internal fun categoryCountLabel(n: Int): String = if (n > 0) "$n 个商品" else "暂无商品"'
#: 默认值与下拉第一项同源的那一行
SAME_SOURCE = "internal val DEFAULT_VEHICLE_TYPE = VEHICLE_TYPES.first().first"
#: 订单卡上那句类别词
CARD_LABEL = "label = if (order.isException) orderExceptionRisk(order).label else null,"
#: 车型取值集（顺序由本判据按 P11 单独钉；一个字都不许扩）
VEHICLE_SET = {("small", "小货车"), ("large", "大货车"), ("trailer", "挂车")}
#: 「自己拼一份商品数」的旧写法（出现即红）
HAND_ROLLED = 'productCount.toString() + " 个商品"'
#: 反引号（Python 源码里不写反引号，判据要认登记表里的 Markdown 代码记号）
BT = chr(96)


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def kt(p: Path) -> str:
    """源码去掉注释之后的正文（词表判据必须去注释，否则自己写的注释会把它喂饱）。"""
    return strip_comments(read(p))


def calls(src: str, sig: str) -> list[str]:
    """按括号配对取出一段调用（FormInputRow( / CategoryChoice( 都是多行的）。"""
    out: list[str] = []
    i = 0
    while True:
        i = src.find(sig, i)
        if i < 0:
            return out
        b = src.find("(", i + len(sig) - 1)
        if b < 0:
            return out
        depth = 0
        for j in range(b, len(src)):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    out.append(src[i : j + 1])
                    i = j + 1
                    break
        else:
            return out


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


def section(title: str) -> None:
    print()
    print(f"-- {title} --")


def main() -> int:
    if refuse_if_injecting("措辞一致性检查"):
        return 1

    c = Checker()
    print("同一个事实只许有一种说法（CHG-0028：E2E 走查 P3 / P5 / P11 / P13 +「已沽清」残余）")

    app = {p: kt(p) for p in sorted(AND.rglob("*.kt"))}
    ui_files = [p for p in app if UI in p.parents]

    # ---- 1. P3：库存那一行不画红星，而且全库没有第二处「选填 + 红星」 ----
    section("1. P3：红星与占位语不许自相矛盾")
    form_src = app.get(FORM, "")
    stock = [call for call in calls(form_src, "FormInputRow(") if 'label = "库存"' in call]
    c.ok('库存那一行还在（找得到 label = "库存" 的输入行）', len(stock) == 1, f"找到 {len(stock)} 处")
    row = stock[0] if stock else ""
    c.ok(
        "库存那一行不画红星（required = false）",
        "required = false" in row and "required = true" not in row,
        "这一行又写回了红星（required = true）—— 同一行的占位语还写着「（选填）」",
    )
    c.ok("库存那一行的占位语仍是「初始库存（选填）」", 'placeholder = "初始库存（选填）"' in row)
    c.ok("库存仍只收 7 位整数（InputRules.intInput(it, 7)）", "InputRules.intInput(it, 7)" in row)

    rows = 0
    contradictions: list[str] = []
    for p, src in app.items():
        for call in calls(src, "FormInputRow(") + calls(src, "FormChoiceRow("):
            rows += 1
            if "选填" in call and "required = true" in call:
                contradictions.append(f"{p.relative_to(AND)} :: {' '.join(call.split())[:90]}")
    c.ok(
        f"全库没有「选填 + 红星」自相矛盾的行（扫了 {rows} 行输入行）",
        rows >= MIN_FORM_ROWS and not contradictions,
        f"这些行同时写着选填与 required = true：{contradictions}"
        if contradictions
        else f"只扫到 {rows} 行（下限 {MIN_FORM_ROWS}）—— 抽取可能失效",
    )

    schema = read(SCHEMA)
    c.ok(
        "后端 ProductCreate.stock 仍是可选（这一行的「选填」不是我们自己编的）",
        "stock: int | None = Field(default=None" in schema and "初始库存（选填" in schema,
        "backend/app/schemas/product.py 里 stock 的语义变了 → 这一行该不该画红星要重新判",
    )

    # ---- 2. P5：分类商品数只有一份实现 ----
    section("2. P5：0 个商品的说法只有一份")
    defs = [p for p, src in app.items() if "internal fun categoryCountLabel(" in src]
    c.ok(
        "分类商品数的说法只有一份实现（categoryCountLabel）",
        len(defs) == 1 and defs[0] == PICKER and CAT_LABEL in app.get(PICKER, ""),
        f"实际 {len(defs)} 处定义：{[str(p.relative_to(AND)) for p in defs]}"
        "（0 处也算红：改名 / 搬走之后这条判据会空转）",
    )
    handmade: list[str] = []
    for p, src in app.items():
        for call in calls(src, "CategoryChoice("):
            if "productCount" in call and "categoryCountLabel(" not in call:
                handmade.append(f"{p.relative_to(AND)} :: {' '.join(call.split())[:80]}")
    c.ok(
        "每一处显示分类商品数的地方都走共用那一份（没有谁自己拼「N 个商品」）",
        not handmade and not any(HAND_ROLLED in src for src in app.values()),
        f"自己拼的地方：{handmade or [HAND_ROLLED]}",
    )
    for p, tag in ((BATCH, "批量操作页"), (FORM, "新增 / 编辑商品页"), (CATS, "商品分类管理页")):
        c.ok(f"{tag}走共用那一份分类商品数", "categoryCountLabel(" in app.get(p, ""))

    # ---- 3. P11：默认车型与下拉第一项同源 ----
    section("3. P11：默认车型不许是另一个字面量")
    veh = app.get(VEHICLE, "")
    m = re.search(r'internal val VEHICLE_TYPES = listOf\(([^)]*)\)', veh)
    pairs = re.findall(r'"([a-z]+)" to "([^"]+)"', m.group(1)) if m else []
    c.ok(
        "小货车排第一（名册里最多的是它：vehicles 表 small 11 / large 3 / trailer 1）",
        pairs[:1] == [("small", "小货车")],
        f"实际第一项 {pairs[:1] or '（没解析出取值表）'}",
    )
    c.ok("车型取值集还是那三档（顺序之外一个字都没扩）", set(pairs) == VEHICLE_SET, f"实际 {pairs}")
    c.ok(
        "默认值与下拉第一项同源（DEFAULT_VEHICLE_TYPE = VEHICLE_TYPES.first().first）",
        SAME_SOURCE in veh,
        "默认值又变成了独立字面量 —— 顺序一改它就会悄悄变成一个不在第一项上的值",
    )
    trailer_lines = [ln.strip() for ln in veh.splitlines() if '"trailer"' in ln]
    assign_form = [
        ln
        for ln in trailer_lines
        if re.search(r'=\s*"trailer"', ln) or re.search(r'ifBlank\s*\{\s*"trailer"', ln)
    ]
    c.ok(
        '车型字面量 "trailer" 只出现在取值表与中文名映射里（没有第二处默认值）',
        len(trailer_lines) == 2
        and any("VEHICLE_TYPES = listOf(" in ln for ln in trailer_lines)
        and any(ln.startswith('"trailer" ->') for ln in trailer_lines)
        and not assign_form,
        f"它出现在这些行：{trailer_lines}（其中赋值形式：{assign_form}）",
    )
    c.ok(
        "新建 / 编辑 / 初值三处都用 DEFAULT_VEHICLE_TYPE",
        "var draftType by mutableStateOf(DEFAULT_VEHICLE_TYPE)" in veh
        and "draftType = DEFAULT_VEHICLE_TYPE" in veh
        and "draftType = v.vehicleType.ifBlank { DEFAULT_VEHICLE_TYPE }" in veh
        and veh.count("DEFAULT_VEHICLE_TYPE") >= 4,
        "还有哪一处硬写了车型 —— 新建时用户不动这一格就会建错车型",
    )
    c.ok("下拉仍列出全部三档（VEHICLE_TYPES.forEach）", "VEHICLE_TYPES.forEach" in veh)

    # ---- 4. P13：订单卡说的类别词来自共用判据 ----
    section("4. P13：订单卡上的「异常」要说清是哪一类")
    od = app.get(ORDERS, "")
    pr = app.get(PRIORITY, "")
    c.ok(
        "订单卡的异常图标说了是哪一类（label = orderExceptionRisk(order).label）",
        CARD_LABEL in od,
        "卡片又只剩一个「异常」了 —— 类别只在报表页里看得到（P13 原样复发）",
    )
    c.ok(
        "卡片仍只对真异常写词（非异常那颗 ⚠ 是待派超时提醒）",
        CARD_LABEL.startswith("label = if (order.isException)") and 'contentDescription = "异常"' in od,
    )
    c.ok(
        "卡片不自己写类别词（词只可能来自 RiskLevel.label）",
        "钱货风险" not in od and "履约卡住" not in od,
        "卡片上自己抄了一份类别词 —— 报表页改词的那天它就会说另一个名字",
    )
    c.ok(
        "异常类别判据只有一份本体（exceptionRiskOf 全库一处定义）",
        sum("fun exceptionRiskOf(" in src for src in app.values()) == 1
        and "fun exceptionRiskOf(reason: String, resolved: Boolean, overdue: Boolean): RiskLevel {" in pr,
        "本体被抄了第二份 —— 两页迟早说两个词",
    )
    c.ok(
        "报表页那条入口只是薄封装（三个事实取全再交给本体）",
        "exceptionRiskOf(e.exceptionReason, resolved = e.exceptionResolvedAt != null, overdue = isOverdue(e))" in pr,
        "exceptionRisk 不再取全事实（是否已解决 / 是否逾期）—— 两页会得出不同的类别",
    )
    c.ok(
        "卡片那条入口也交给同一份本体（resolved 恒 false）",
        "fun orderExceptionRisk(order: OrderDto): RiskLevel =" in pr
        and "exceptionRiskOf(order.exceptionReason, resolved = false, overdue = isOrderOverdue(order))" in pr,
    )
    c.ok(
        "报表中心仍用同一份判据（exceptionRisk( 在 ui/dispatcher/ReportCenter.kt 里）",
        "exceptionRisk(" in app.get(REPORT, ""),
    )
    c.ok(
        "词表仍是那五个词（钱货风险 / 履约卡住 / 一般 / 已过去 / 已解决）",
        all(w in pr for w in ('MONEY("钱货风险")', 'STUCK("履约卡住")', 'OTHER("一般")', 'PAST("已过去")', 'DONE("已解决")')),
    )

    # ---- 5. 同一个状态只有一个词 ----
    section("5. 同一个状态只有一个词（已沽清 vs 已下架）")
    users_src = app.get(USERS, "")
    # CHG-0062：这一列商品行整块搬进了共用零件 ui/common/ProductCheckList.kt，
    # 所以「账户管理那一行写的是哪个词」要连着零件一起看 —— 搬家不是放宽：
    # 零件里必须走共用角标 ProductSoldOutBadge，且两个文件里都不许出现「已下架」。
    part_src = app.get(PART, "")
    c.ok(
        "账户管理的商品行（现住在共用零件里）写「已沽清」",
        "ProductSoldOutBadge(" in part_src and "已下架" not in users_src and "已下架" not in part_src,
        "这一行又写回了「已下架」—— 同一个状态在 App 里就有两个词了",
    )
    stale = [str(p.relative_to(AND)) for p in ui_files if "已下架" in app[p]]
    c.ok(
        "UI 代码里同一个状态只有一个词（已下架 0 处）",
        len(ui_files) >= MIN_UI_FILES and not stale,
        f"这些界面文件还在写「已下架」：{stale}"
        if stale
        else f"只扫到 {len(ui_files)} 个界面文件（下限 {MIN_UI_FILES}）—— 目录可能被搬走",
    )
    c.ok(
        "共用角标仍是那个词（ui/common/ProductCardKit.kt 的 ProductSoldOutBadge）",
        "ProductSoldOutBadge" in app.get(BADGE, "") and '"已沽清"' in app.get(BADGE, ""),
    )
    c.ok(
        "领域动作词「下架」只留在后端描述里（那句被 API 快照钉着，不许顺手改）",
        "含已下架商品" in read(PRODUCTS_API),
        "backend/app/api/v1/products.py 里 include_inactive 的描述变了 → API 快照与判据要一起看",
    )

    # ---- 6. 配对与文档 ----
    section("6. 配对与文档")
    c.ok("这条红线配了反向验证脚本", (ROOT / REVERSE).exists(), f"找不到 {REVERSE}")
    c.ok(
        "改动文档在（九节 + 走查原话）",
        DOC.exists() and "P13" in read(DOC) and "P11" in read(DOC),
        "docs/changes/CHG-0028.md 不在 / 少了走查项",
    )
    c.ok(
        "改动登记表里有 CHG-0028 行（进行中 / 已关闭两态）",
        ("| " + BT + "CHG-0028" + BT + " |") in read(README),
        "docs/changes/README.md 里没有 CHG-0028 那一行（进行中与已关闭两种形状都认）",
    )
    c.ok("认领簿里有 CHG-0028 的块", "CHG-0028" in read(CLAIM))

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · P3  库存那一行不画红星；全库没有「选填 + required = true」的行；后端 stock 仍是可选")
        print("     · P5  分类商品数只有一份实现（0 处也红），三个调用点都走它，别处 0 处自己拼")
        print("     · P11 小货车排第一、默认值与下拉第一项同源、文件里没有第二处车型字面量")
        print("     · P13 订单卡说清是哪一类、卡片自己不写词、两页共用同一份本体与词表")
        print("     · 词   UI 代码里「已下架」0 处（界面词是「沽清」，领域词「下架」留在后端描述里）")
        print("     · 配   反向验证脚本、改动文档、登记表、认领簿四件事都在")

    return c.report("同一个事实只许有一种说法（CHG-0028）")


if __name__ == "__main__":
    sys.exit(main())
