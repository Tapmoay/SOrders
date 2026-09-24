"""红线：**订单上的「数量 + 单位」与「商品明细」的两列**（2026-09-22 用户口述，三端一致）。

## 由来（用户原话，逐句对着做）

> 你改一下不管是派单员的那个，那个订单卡片还是货主的订单卡片还是司机的订单卡片……
> 不是详情页嘛，是**概要的那个订单卡片**，它那个商品后面的数字**没有单位**啊，这个不行啊，
> **这是要有单位的**。还有一个**商品明细**……由于派单员，他这个商品明细后面是**有价格的没有做对齐**啊，
> 就是**件与件数做对齐、价格与价格做个对齐**，他们都**放在右边的**……
> 包括我们**货主**看到的也是一样的，他也要做一个对齐，就是**规整一点、美观一点**。

## 这条判据守的事，坏起来一句报错都没有

| 写坏的方式 | 表现 |
|---|---|
| 卡片那一行退回 `"×" + quantity` | 屏幕上又只剩「×6」——正是用户点名的那句，而编译、运行、别的红线**全绿** |
| 有人把「空单位」兜底成「件」（照商品那一侧的 `unitOrDefault` 抄一份） | 老单**凭空长出**「×6 件」：系统编了一个没人填过的事实，而它看起来完全正常（用户会拿它去对货） |
| 「数量 + 单位」在卡片 / 详情页 / 账本小卡各拼一份 | 改一处漏两处（卡片写「6 桶」、明细还写「6」），两边都不报错 |
| 商品明细的件数/金额退回**各自自然宽度** | 数字位数一变两列就参差 —— 用户说的「没有做对齐」 |
| 货损那一格改成「这一行有货损才占位」 | **没货损的那几行**金额贴最右、有货损的往左缩一截 → 金额列自己错开一格 |
| 卡片底部合计不管单位 | 一单「6 桶」底下写着「共 6 **件**」 |
| 在 `map` 里调 `rememberTextWidth` | 组合期槽位与列表长度对不上（`Adaptive.kt` 明说只有 fold / forEach 能放进去，map 不是 inline） |

## 判据（清单**全部自己算**，不手写「要查哪些文件」）

1. 三个拼法（数量+单位 / 整单共同单位 / 货损）**各只有一处定义**，且都在 `ui/common/Units.kt`；
   调用点 ≥3（订单卡片 / 订单详情 / 账本小卡）—— 少了说明有人又自己拼了一份，或者判据失配在空转。
2. `qtyWithUnit` 里**不许**出现 `DEFAULT_UNIT` / `unitOrDefault`（那正是「替老单编一个件」）。
3. 订单卡片：商品行走 `qtyWithUnit(`，底部合计走 `sharedUnitOf(`；四张订单列表共用这一张卡
   （调用点从源码算，不手写文件名）。
4. 订单详情的「商品明细」：件数、金额两格都 `Modifier.width(<量出来的>)` + `textAlign = TextAlign.End`；
   货损格用**整单判据** `hasDamage` 占位（不是「这一行有没有」）。
5. 账本小卡 `OrderPeek.kt` 同形（派单员账本与货主账本共用它）。
6. 钱的规矩没被顺手删：`role != Role.DRIVER` 那道门还在（细则在 `_check_driver_money.py`）。
7. 反空转：文件在、被扫的块非空、解析出的「量宽」调用 ≥5。
8. 文档：`06_DESIGN_SYSTEM.md` 与 `08_CODE_LOCATOR.md` 都记着这条形状（文档过期比没有文档更糟）。

⚠️ 注入式反向验证（改坏 → 本脚本必须红）：`_tools/qa/_reverse_verify_order_row_columns.py`。

用法：python _tools/qa/_check_order_row_columns.py
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

UNITS = ANDROID / "ui/common/Units.kt"
CARD = ANDROID / "ui/common/OrderCard.kt"
DETAIL = ANDROID / "ui/order/OrderDetailScreen.kt"
PEEK = ANDROID / "ui/common/OrderPeek.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"

#: 三个拼法的名字 —— 定义处只许在 Units.kt
HELPERS = ("qtyWithUnit", "sharedUnitOf", "damageLabel")
#: 四张订单列表 → 必须都走同一张卡（调用点从源码算，不手写文件名）
MIN_CARD_CALLERS = 4
#: 三个页面（卡片 / 详情 / 小卡）都要用到「数量+单位」这份拼法
MIN_QTY_CALL_SITES = 3
#: 量宽调用（卡片 0 + 详情 3 + 小卡 2）至少这么多处
MIN_MEASURE_CALLS = 5


class Checker:
    def __init__(self) -> None:
        self.n_ok = 0
        self.fails: list[tuple[str, str]] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.n_ok += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append((label, detail))
            print(f"  [!!]   {label}")
            if detail:
                print(f"         {detail}")

    def section(self, title: str) -> None:
        print(f"\n== {title} ==")


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的判据要跟着改，不许静默跳过）")
    return strip_comments(io.open(p, encoding="utf-8", errors="replace", newline="").read())


def raw(p: Path) -> str:
    return io.open(p, encoding="utf-8", errors="replace", newline="").read()


def kt_sources() -> dict[Path, str]:
    return {p: strip_comments(io.open(p, encoding="utf-8", errors="replace", newline="").read())
            for p in sorted(ANDROID.rglob("*.kt"))}


def definers(srcs: dict[Path, str], name: str) -> list[Path]:
    """全树里**定义**了 `fun <name>(` 的文件（从源码算，不手写清单）。"""
    pat = re.compile(rf"\bfun {re.escape(name)}\(")
    return [p for p, s in srcs.items() if pat.search(s)]


def callers(srcs: dict[Path, str], name: str) -> list[Path]:
    """全树里**调用**了 `name(` 的文件（定义那一行不算调用）。"""
    pat = re.compile(rf"(?<!fun )\b{re.escape(name)}\(")
    return [p for p, s in srcs.items() if pat.search(s)]


def region(src: str, start: str, end: str) -> str:
    """截出 [start, end) 那段（判据要盯的是**某一块**，不是整份文件）。"""
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i + len(start))
    return src[i:] if j < 0 else src[i:j]


def func_body(src: str, name: str) -> str:
    """按**花括号配对**截出一个函数的函数体（按 `\\n}` 切只会命中最后一个括号，不能用）。"""
    m = re.search(rf"\bfun {re.escape(name)}\(", src)
    if not m:
        return ""
    i = src.find("{", m.end())
    if i < 0:
        return ""
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    return src[i:]


def main() -> int:
    if refuse_if_injecting("订单行「数量+单位」与商品明细两列红线"):
        return 1

    c = Checker()
    srcs = kt_sources()
    units = read(UNITS)
    card = read(CARD)
    detail = read(DETAIL)
    peek = read(PEEK)
    design = raw(DESIGN)
    locator = raw(LOCATOR)

    # ---- ① 拼法只有一份 ----
    c.section("「数量 + 单位」这一类的拼法：只有一份实现（在 ui/common/Units.kt）")
    for name in HELPERS:
        ds = definers(srcs, name)
        c.ok(
            f"`fun {name}(` 全树只有一处定义，且就在 ui/common/Units.kt"
            f"（实测 {len(ds)} 处：{[str(p.relative_to(ROOT)) for p in ds]}）",
            ds == [UNITS],
            "同一个拼法有两个实现 = 改一处漏一处，而两边都不报错",
        )

    # ⚠️ 2026-09-24：数量那一格的拼法从 `qtyWithUnit(` 换成了 `qtyWithUnitConverted(`
    #    （单位换算：设过「1 车 = 8 方」时写「×10 车 ≈ 80 方」）。**落点没变、数量也没变少** ——
    #    所以这里把调用点判据一起挪到新函数上，并**同时**要求退回那一支还在
    #    （`qtyWithUnitConverted` 内部必须仍然调 `qtyWithUnit`）。
    #    ⛔ 别把这条判据删掉：它是"四处渲染没有各自拼一份"的唯一证据。
    qty_callers = [p for p in callers(srcs, "qtyWithUnitConverted") if p != UNITS]
    c.ok(
        f"`qtyWithUnitConverted(` 的调用点 ≥{MIN_QTY_CALL_SITES} 个（订单卡片 / 订单详情 / 账本小卡 / 下单页），"
        f"实测 {len(qty_callers)}：{[p.name for p in qty_callers]}",
        len(qty_callers) >= MIN_QTY_CALL_SITES,
        f"低于 {MIN_QTY_CALL_SITES} 说明有人又自己拼了一份，或者判据失配在空转",
    )
    c.ok(
        "换算版仍然**逐字退回**原样（`qtyWithUnitConverted` 体内调 `qtyWithUnit`）",
        "qtyWithUnit(quantity, rawUnit)" in func_body(units, "qtyWithUnitConverted"),
        "退回那一支没了 —— 没设换算的单会少显示/编一个单位",
    )

    body = func_body(units, "qtyWithUnit")
    c.ok("qtyWithUnit 的函数体认出来了（认不出 = 判据要跟着改，不许静默通过）",
         "return" in body, f"截出来是 {body[:60]!r}")
    c.ok(
        "⛔ qtyWithUnit 里不许出现 DEFAULT_UNIT / unitOrDefault（那是替老单编一个「件」）",
        "DEFAULT_UNIT" not in body and "unitOrDefault" not in body,
        "订单行是下单那一刻的快照：老单没填过单位时只能给数字。编一个「件」出来的后果是"
        "「系统说了一个没人填过的事实」，而且看起来完全正常",
    )
    c.ok(
        "它与商品那一侧的兜底是两个函数（unitOrDefault 保留自己的语义，没被合并掉）",
        "fun unitOrDefault" in units and "fun qtyWithUnit" in units,
    )

    sum_body = func_body(units, "sharedUnitOf")
    c.ok(
        "整单共同单位：有一条没填就返回 null（不拿「多数派」替整单说话）",
        "any { it.isEmpty() }" in sum_body and "singleOrNull" in sum_body,
        "混装 / 缺填的单，那个合计数本来就没有共同单位",
    )

    # ---- ② 订单卡片（四张列表共用） ----
    c.section("订单卡片：商品行带单位、合计带共同单位")
    c.ok(
        "商品行的数量走共用拼法（不是裸拼 `\"×\" + op.quantity`）",
        re.search(r'"×" \+ qtyWithUnitConverted\(op\.quantity, op\.unit, conversions\)', card) is not None,
        "这正是用户点名的那句「商品后面的数字没有单位」",
    )
    c.ok(
        "⛔ 卡片里没有裸拼数量的老写法",
        re.search(r'"×" \+ op\.quantity\b', card) is None,
    )
    c.ok(
        "底部合计的单位走 sharedUnitOf（全单一致才敢写它）",
        re.search(r"sharedUnitOf\(order\.orderProducts\.map \{ it\.unit \}\)", card) is not None,
        "否则一单「6 桶」底下会写「共 6 件」",
    )
    c.ok(
        "合计那处的兜底是 DEFAULT_UNIT（口语的「件」），不是硬编码的字面量",
        "DEFAULT_UNIT" in region(card, "sharedUnitOf(order.orderProducts.map", "style = MaterialTheme"),
    )

    card_callers = [p for p in callers(srcs, "OrderCard") if p != CARD]
    c.ok(
        f"`OrderCard(` 的调用点 ≥{MIN_CARD_CALLERS} 个（待派单池 / 订单管理 / 我的订单 / 司机任务），"
        f"实测 {len(card_callers)}：{[p.name for p in card_callers]}",
        len(card_callers) >= MIN_CARD_CALLERS,
        "三端看到的是同一张卡；调用点变少说明有人另起了一张",
    )
    c.ok(
        "司机那一端也在这张卡上（`driverMode = true` 的调用点还在）",
        any("driverMode = true" in s for s in srcs.values()),
    )

    # ---- ③ 详情页「商品明细」的两列 ----
    c.section("订单详情「商品明细」：件数一列、金额一列，都是同一个宽度 + 右对齐")
    block = region(detail, '"商品明细"', '"合计"')
    c.ok("截到了商品明细那一块（截不到 = 判据失配，先修判据）", len(block) > 200,
         f"实际 {len(block)} 字符")
    c.ok(
        "件数那一格右对齐（textAlign = TextAlign.End + 同一个宽度）",
        re.search(r'"×" \+ qtyWithUnitConverted\(line\.quantity, line\.unit, conversions\),[\s\S]{0,200}?'
                  r"textAlign = TextAlign\.End,\s*modifier = Modifier\.width\(qtyW\)", block) is not None,
        "用户：「件与件数做对齐」",
    )
    c.ok(
        "金额那一格右对齐（textAlign = TextAlign.End + 同一个宽度）",
        re.search(r'"¥" \+ formatMoney\(line\.lineTotal\),[\s\S]{0,200}?'
                  r"textAlign = TextAlign\.End,\s*modifier = Modifier\.width\(moneyW\)", block) is not None,
        "用户：「价格与价格做个对齐」",
    )
    c.ok(
        "两列的宽度是量出来的（rememberTextWidth），不是按字数猜的",
        block.count("rememberTextWidth(") >= 3,
        f"实际 {block.count('rememberTextWidth(')} 处（件数 / 金额 / 货损各一处）",
    )
    # ⚠️ 这两条是反向验证逼出来的：原来只查了「有没有量」，没查「量的是不是画的那一串」——
    #    注入"量宽度时偷偷把单位去掉"之后判据照样绿，而真机上那一列会**按「×6」的宽度去装「×6 桶」**，
    #    数字被那个固定宽度裁掉，屏幕上只是"看着有点挤"，一句报错都没有。
    c.ok(
        "量宽度用的那串文字与画出来的那串是同一个拼法（都带单位、同一个 style、换算也同源）",
        re.search(r'rememberTextWidth\("×" \+ qtyWithUnitConverted\(l\.quantity, l\.unit, conversions\), qtyStyle\)',
                  block) is not None
        and re.search(r'"×" \+ qtyWithUnitConverted\(line\.quantity, line\.unit, conversions\),[\s\S]{0,120}?style = qtyStyle,',
                      block) is not None,
        "量的比画的窄 → 数字被固定宽度裁掉，而界面上没有任何提示",
    )
    c.ok(
        "金额列同理（量的是 ¥ + formatMoney，画的是同一串、同一个 moneyStyle）",
        re.search(r'rememberTextWidth\("¥" \+ formatMoney\(l\.lineTotal\), moneyStyle\)', block) is not None
        and re.search(r'"¥" \+ formatMoney\(line\.lineTotal\),[\s\S]{0,120}?style = moneyStyle,',
                      block) is not None,
    )
    c.ok(
        "货损格用整单判据 hasDamage 占位（不是「这一行有没有货损」）",
        re.search(r"val hasDamage = order\.orderProducts\.any \{ it\.damageQuantity > 0 \}", block) is not None
        and re.search(r"if \(hasDamage\) \{", block) is not None,
        "用「这一行有没有」当判据的话，没货损的那几行金额会贴到最右边、与有货损的错开一列",
    )
    c.ok(
        "货损那一格也给了固定宽度（Modifier.width(damageW)）",
        re.search(r"modifier = Modifier\.width\(damageW\)", block) is not None,
    )
    c.ok(
        "⛔ 没有人在 map 里调 rememberTextWidth（组合期槽位会与列表长度对不上）",
        re.search(r"\.map \{[^}]*rememberTextWidth", detail) is None
        and re.search(r"\.map \{[^}]*rememberTextWidth", peek) is None,
        "Adaptive.kt 明说：forEach / fold 是 inline 所以能调，map 不是",
    )
    c.ok(
        "钱的门还在：司机看不到货款那一格（role != Role.DRIVER）",
        re.search(r"if \(role != Role\.DRIVER\) \{", block) is not None,
        "细则在 _check_driver_money.py，这里只钉住「别被顺手删掉」",
    )

    # ---- ④ 账本小卡（派单员账本 + 货主账本共用） ----
    c.section("账本小卡（OrderPeek）：同一形状的行，同样补单位 + 分列右对齐")
    peek_block = region(peek, "order.orderProducts.forEach {", "if (order.remark.isNotBlank())")
    c.ok("截到了小卡的商品行那一块（截不到 = 判据失配）", len(peek_block) > 120,
         f"实际 {len(peek_block)} 字符")
    c.ok(
        # ⚠️ 必须钉**画出来那一行**（尾部 `style = qtyStyle,`）：小卡里这个串出现两次
        #    （量宽度 + 画），只写 `qtyWithUnit(lp.quantity, lp.unit)` 的话，
        #    把**画**的那一处改回裸拼、判据照样绿（反向验证第 ⑧ 条就是这么空转了一轮）。
        "小卡的数量也走共用拼法（画出来那一行，不是只有量宽度那处）",
        re.search(r'"×" \+ qtyWithUnitConverted\(lp\.quantity, lp\.unit, conversions\),[\s\S]{0,120}?style = qtyStyle,',
                  peek) is not None,
    )
    c.ok(
        "小卡的两格也右对齐 + 固定宽度",
        re.search(r"textAlign = TextAlign\.End,\s*modifier = Modifier\.width\(qtyW\)", peek) is not None
        and re.search(r"textAlign = TextAlign\.End,\s*modifier = Modifier\.width\(moneyW\)", peek) is not None,
    )
    c.ok(
        "小卡量宽度与画出来的也是同一个拼法（都带单位 + 同一个 style + **换算也同源**）",
        re.search(r'rememberTextWidth\("×" \+ qtyWithUnitConverted\(lp\.quantity, lp\.unit, conversions\), qtyStyle\)',
                  peek) is not None
        and re.search(r'"×" \+ qtyWithUnitConverted\(lp\.quantity, lp\.unit, conversions\),[\s\S]{0,120}?style = qtyStyle,',
                      peek) is not None,
        "小卡是账本页就地展开的那一块，行更窄、被裁掉更看不出来；"
        "量宽与渲染不同源时，长出来的「≈ 80 方」会把右对齐挤歪",
    )

    # ---- ⑤ 反空转 ----
    c.section("反空转：量宽的调用数、被扫的块都不能是空的")
    n_measure = sum(len(re.findall(r"rememberTextWidth\(", s)) for s in (card, detail, peek))
    c.ok(
        f"三个页面里 rememberTextWidth( 合计 ≥{MIN_MEASURE_CALLS} 处（实测 {n_measure}）",
        n_measure >= MIN_MEASURE_CALLS,
        "少于这个数说明那几列悄悄退回自然宽度了（就是用户说的「没有做对齐」）",
    )
    c.ok(
        "卡片里的商品行块认得出来（order.orderProducts.take(3) 还在）",
        "order.orderProducts.take(3)" in card,
    )

    # ---- ⑥ 文档 ----
    c.section("文档：这条形状写进规范与定位表（下一个人照文档做，而不是照猜）")
    c.ok(
        "06_DESIGN_SYSTEM.md 记着「数量带单位 + 分列右对齐」这一条（含 qtyWithUnit）",
        "qtyWithUnit" in design and "分列" in design,
        "文档过期比没有文档更糟：下一个人会照他自己觉得好看的样子再做一遍",
    )
    c.ok(
        "08_CODE_LOCATOR.md 的订单卡片那一行提到单位与两列",
        "qtyWithUnit" in locator,
    )

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for label, detail in c.fails:
            print("   - " + label + (f" —— {detail}" if detail else ""))
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：数量带单位（三端同一份拼法），商品明细两列右对齐。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
