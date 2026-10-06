# -*- coding: utf-8 -*-
"""订单详情里看得见「已退几件」与**这一单的退货申请** —— 台账 L-21（2026-10-06）。

## 用户口径（原话）
- m00481：「我那个申请了退货，然后派单员也通过了退货，为什么再点击订单详情他那个商品的页面
  并没有发生改变……要有一个显示，已退货多少……总数从 5 个，退了 3 个，总数会变成 2 个，
  然后再下面会有一个红色的 −3，表示已退货；或者直接在下面显示一个「已退货商品 3 件」。」
- **m00542（更晚，以它为准）**：「只显示最后的数字，然后后面一个小字『已退 3』」；
  「在查看的时候也可以查到这个单子的退货单，退货单也可以查到这个单子」。

## 机制：这一条为什么必须有机器的判据
「商品明细里多一行『已退 N』」写出来只有两种可能：在、或者不在。删掉它**不会有编译错误、
不会有任何用例报红** —— 商品明细照旧四格、金额照旧对得上、`_check_order_row_columns.py` 照样绿。
更贵的是**退化**，而且每一条退化源码都完全合法：

| 写坏的方式 | 表现 |
|---|---|
| 净数算式改回 `line.quantity` | 没退过货的单子照样对，只有退过货的那几行悄悄多画几件 |
| 只改「画出来」那处、量宽度仍按原数量 | 列宽按「×12」量、数字画「×9」，右边被固定宽度裁掉 —— 只是"看着有点挤" |
| 「已退 N」改成无条件画 | 每一行都多一句「已退 0」，用户要的那个信号被淹掉 |
| 「已退 N」干脆不画 | 件数变小了没人解释，而用户报的就是这一条 |
| 那块退货申请改成**跳转**（`Routes.shipperReturnRequests(...)`） | 从订单点进去，那一条会被打上「消息里点进来的这一条」（判据钉死全仓只许一处）—— 一句假话；不带 focus 又只能落到整张列表上 |
| 取数失败写进 `error` | 整页被顶成 ErrorView；而这只是卡片下面多一块 |
| 状态中文名自己写一份映射表 | 后端换文案就有一处对不上（`label` 只许来自 `statusLabel`） |

## 这一刀动什么 / 不动什么
- **动**：`ui/order/OrderDetailViewModel.kt`（`returnRequests` ＋ `loadReturnRequests()`）；
  `ui/order/OrderDetailScreen.kt`（件数画净数 ＋ 小字「已退 N」＋「商品明细」卡尾那块只读的退货申请）。
- **不动**：`core/ReturnRules.kt`（只加显示、不加算法）、后端（`order_id` 过滤本来就已就绪）、
  退货申请两端页面与路由（`Routes` / `NavGraph` / `NoticeRouting` 一个字没动）、
  `ui/common/ReturnRequestChip.kt`（共用胶囊）。
- ⚠️ **后续（2026-10-07，台账 L-38 / CHG-0065）**：用户看着「火腿 ×2 已退 3 … ¥430.8」问
  「**为什么钱没有变**」—— 上面那句「行金额与合计逐字未动」**已被推翻**：两格从此都画**净额**
  （行金额 − 单价 × 已退数量，与后端 `order_money.py::line_receivable` 同源），合计那一行多一颗
  小字「已退 ¥X」。下面第 4 组的判据同步改成"必须画净额"。
  ⛔ 这一刀只改**订单详情页**：订单卡片（`ui/common/OrderCard.kt`）与两端退货申请列表页没动。

## 判据（8 组）
1. 取数：按登录缓存的角色**原文**分派到两个接口、拉「全部」档位、失败只留空列表、不写页面级 error；
2. 详情页把这一单的退货申请画出来（胶囊 ＋ 要退摘要 ＋ 时间 ＋ 驳回原因 / 谁办的）；
3. 那块是**只读**的：没有按钮、没有写操作、没有自己造的状态中文名；
4. **不做跳转**（详情页不许把用户扔进退货申请页）；
5. 件数画净数、后面跟一个小字「已退 N」，且只在这一行真的退过时才画；
6. 金额与合计**画的是退货后的净额**（`netLineMoneyText` / `netOrderMoneyText`），且合计那行只在
   真退过时多一颗「已退 ¥X」小字；
7. 共用件没被抄第二份（胶囊调用点清单、`loadReturnRequests` 定义恰一处）；
8. 文档（CHG / README / CLAIM）＋ 反验脚本 ＋ 防静默空转。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
这一条守的是一串**否定式**属性：「不许跳转」「不许有按钮」「不许自己造状态中文名」「不许在没退过
货时也画」。否定式属性在类型系统里没有位置：`returnRequests: List<ReturnRequestDto>` 这个参数
多传少传都不影响编译；把整块 `if (returnRequests.isNotEmpty()) { ... }` 删掉，只有一个取数函数
变成没人用，Kotlin 一声不吭；把 `netQty(line)` 换回 `line.quantity` 仍然返回 `Int`。
正向的边界（接口 / 分层 / 数据 Owner）在这里也使不上劲：这块**不写任何数据**，仓库层没有任何
一个点能拦住「多画了一条状态」或者「少画了小字」—— 能拦住的只有源码结构本身：谁被调用、
那块里有没有动作、算式是不是只有一份。

用法：python _tools/qa/_check_order_return_visible.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 剥 Kotlin 注释只有一份实现（抄一份必踩同一个坑）
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = AND / "ui/order/OrderDetailScreen.kt"
VM = AND / "ui/order/OrderDetailViewModel.kt"
APIS = AND / "data/remote/api/Apis.kt"
REPO = AND / "data/repo/AppRepository.kt"
CHIP = AND / "ui/common/ReturnRequestChip.kt"
RULES = AND / "core/ReturnRules.kt"
ROWCOL_CHECK = ROOT / "_tools/qa/_check_order_row_columns.py"
RETURN_CHECK = ROOT / "_tools/qa/_check_return_request.py"
CHG = ROOT / "docs/changes/CHG-0054.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_order_return_visible.py"

#: 全仓至少要有这么多 .kt（防「目录被搬走 → 一个都没扫到 → 全绿」）。
MIN_KT = 100
#: 半角双引号：源码里字符串字面量的定界符。
DQ = chr(34)
#: 那块只读块的闸门（切段用；结束位置按花括号配对算，不靠注释）。
GATE = "if (returnRequests.isNotEmpty()) {"
#: 净数算式（只许一处）。
NETQTY = "private fun netQty(l: OrderProductDto): Int = (l.quantity - l.returnedQuantity).coerceAtLeast(0)"
#: 两个角色各自的接口调用（逐字）。
SHIPPER_CALL = "myReturnRequests(orderId = orderId, status = RETURN_STATUS_ALL)"
DISPATCHER_CALL = "returnRequestTodo(status = RETURN_STATUS_ALL, orderId = orderId)"
#: 状态胶囊的调用（中文名只许来自后端的 statusLabel）。
CHIP_CALL = "ReturnRequestStatusChip(status = req.status, label = req.statusLabel)"
REQUIRED_FILES = [SCREEN, VM, APIS, REPO, CHIP, RULES, ROWCOL_CHECK, RETURN_CHECK, CHG, README, CLAIM, REVERSE]


def read(p: Path) -> str:
    """读文本并**统一成 LF**（判据里有跨行锚点，CRLF 会让它们一处也匹配不上）。"""
    if not p.exists():
        return ""
    return io.open(p, encoding="utf-8", errors="replace", newline="").read().replace(chr(13) + chr(10), chr(10))


def code(p: Path) -> str:
    return strip_comments(read(p))


def between(text: str, a: str, b: str) -> str:
    """`a` 之后、`b` 之前的那一段（用来问「这句在不在这一段里」）。"""
    i = text.find(a)
    if i < 0:
        return ""
    j = text.find(b, i + len(a))
    return text[i : j if j >= 0 else len(text)]


def near(text: str, needle: str, after: int = 400) -> str:
    """`needle` 那一点往后的一段（用来问「紧跟它的是不是那个 style」）。"""
    i = text.find(needle)
    if i < 0:
        return ""
    return text[i : i + after]


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

    def absent(self, label: str, text: str, needle: str) -> None:
        self.ok(label, needle not in text, "不该出现却出现了 " + repr(needle))

    def section(self, title: str) -> None:
        print(f"\n== {title} ==")


def brace_block(text: str, header: str) -> str:
    """从 `header` 起按花括号配对切出整块（含结尾的 `}`）。

    ⚠️ 为什么不用「闸门 → 下一句注释」那种切法：`code()` 已经把注释剥掉了，注释锚点在这里**必然找不到**，
    切出来会一路延到文件末尾 —— 于是「这块里没有按键」变成拿整个文件在问，测试会**静默地**变松。
    """
    i = text.find(header)
    if i < 0:
        return ""
    j = text.find("{", i)
    if j < 0:
        return ""
    depth = 0
    for k in range(j, len(text)):
        ch = text[k]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[i : k + 1]
    return ""

def hits(srcs: list[tuple[str, str]], needle: str) -> list[tuple[str, int]]:
    """全仓里含 `needle` 的文件与次数（用来钉「调用点清单**恰为**这些」）。"""
    out: list[tuple[str, int]] = []
    for rel, src in srcs:
        n = src.count(needle)
        if n:
            out.append((rel, n))
    return out


def main() -> int:
    c = Checker()
    screen = code(SCREEN)
    vm = code(VM)
    apis = code(APIS)
    repo = code(REPO)
    rules = code(RULES)
    kts = sorted(AND.rglob("*.kt"))
    ui = [(p.relative_to(AND).as_posix(), code(p)) for p in kts]
    #: 「商品明细」卡尾那一块（闸门起、按花括号配对切出来）。
    block = brace_block(screen, GATE)
    #: 取数那个函数体。
    loader = brace_block(vm, "private fun loadReturnRequests()")

    c.section("0. 前提：读到了东西（否则下面每一条都是空转）")
    c.ok("详情页 / VM / 那块 / 取数体都非空",
         len(screen) > 1000 and len(vm) > 1000 and len(block) > 200 and len(loader) > 100,
         "screen=" + str(len(screen)) + " vm=" + str(len(vm))
         + " block=" + str(len(block)) + " load=" + str(len(loader)))
    #: 切出来的块要是**不合理地大**，说明锚点漂了（切到文件尾），上面那些「这块里没有…」会静默变松。
    c.ok("两块的大小都合常理（切歪了这里先报红）",
         200 < len(block) < 8000 and 100 < len(loader) < 1200,
         "block=" + str(len(block)) + " load=" + str(len(loader)))

    c.section("1. 取数：按登录缓存的角色分派到两个接口、拉「全部」档位、失败只留空列表")
    c.ok("顶层有 RETURN_STATUS_ALL（Kotlin 的 const val 不许放进类里）",
         'private const val RETURN_STATUS_ALL = "all"' in vm)
    c.ok("两个接口都按 RETURN_STATUS_ALL 拉「全部」档位",
         SHIPPER_CALL in loader and DISPATCHER_CALL in loader)
    c.ok("角色用的是登录缓存里那一份（不是自己再猜一次）",
         "container.tokenStore.cachedRole()" in loader)
    c.ok("分派写的正是 Role.SHIPPER.key / Role.DISPATCHER.key",
         "Role.SHIPPER.key ->" in loader and "Role.DISPATCHER.key ->" in loader)
    c.ok("两个角色都只取 items（返回体不是列表）", loader.count(".items") == 2,
         "count=" + str(loader.count(".items")))
    c.ok("非关键取数失败 → 空列表（runCatching ＋ getOrDefault(emptyList())）",
         loader.count("runCatching {") == 2 and loader.count("getOrDefault(emptyList())") == 2)
    c.ok("这一块自己不许写页面级 error（那是订单主体取数失败才有的）",
         re.search(r"\berror\s*=", loader) is None and ".error" not in loader)
    c.ok("returnRequests 是 mutableStateOf ＋ 只读对外（private set）",
         "var returnRequests by mutableStateOf<List<ReturnRequestDto>>(emptyList())" in vm
         and re.search(r"var returnRequests by mutableStateOf<List<ReturnRequestDto>>\(emptyList\(\)\)\s*\n\s*private set", vm) is not None)
    c.ok("loadReturnRequests() 恰两处：定义一处 ＋ load() 里调一处",
         vm.count("loadReturnRequests(") == 2, "count=" + str(vm.count("loadReturnRequests(")))
    c.ok("它是挂在 load() 里跑的（打开详情就会拉）",
         "loadReturnRequests()" in between(vm, "fun load() {", "\n    /**"))

    c.section("2. 详情页把这一单的退货申请画出来（胶囊 ＋ 要退 ＋ 时间 ＋ 驳回/办理）")
    c.ok("闸门原文在：只在真的有申请时才出现", GATE in screen)
    c.ok("那一块切得出来（闸门那一整块）", len(block) > 200, "len=" + str(len(block)))
    c.ok("状态胶囊走共用件", CHIP_CALL in block)
    c.ok("中文名只许来自后端的 statusLabel（不自己映射一份）", "statusLabel" in block)
    c.ok("要退的东西原文照登（linesSummary）", '"要退 " + req.linesSummary' in block)
    c.ok("申请时间画出来（带年份那一档 formatDateTimeFull）", "formatDateTimeFull(req.createdAt)" in block)
    c.ok("被驳回的要把原因画出来（没填要有兜底文案）",
         re.search(r'if \(req\.status == "rejected"\) \{[\s\S]{0,400}?"驳回原因："', block) is not None
         and "req.rejectReason" in block and "（派单员没有填原因）" in block,
         "闸门与文案必须同在一段里：把 if 改成恒假，整条答复就没了")
    c.ok("已办结的要说清是谁办的（空名字有兜底）",
         re.search(r'if \(req\.status == "done"\) \{[\s\S]{0,400}?"已由 "', block) is not None
         and "handledByName" in block and '"派单员"' in block,
         "同上：办了不说谁办的，货主不知道该找谁")
    c.ok("这一块里没有任何按键（它是只读的）",
         re.search(r"\bButton\(|IconButton\(|TextButton\(|onClick\s*=", block) is None)

    c.section("3. 这一块不写任何数据（动作仍在退货申请页）")
    c.absent("没有改明细", block, ".saveEdit")
    c.absent("没有提交", block, ".submit")
    c.absent("没有直接调仓库", block, "container.repo")
    c.absent("没有反过来改 VM 的状态", block, "vm.")
    c.absent("没有跳高德", block, "androidamap")
    c.ok("整块里一次都没有出现 Routes（要做动作就得跳出去）", "Routes." not in block)

    c.section("4. 件数与金额都画净数（件数 − 已退数 / 行金额 − 单价 × 已退数量）＋ 各自一颗小字")
    c.ok("净数算式全仓只有这一份（唯一一处相减）",
         screen.count("(l.quantity - l.returnedQuantity)") == 1 and NETQTY in screen)
    c.ok("量宽度与画出来那串都走 netQty（否则右边被固定宽度裁掉）",
         'rememberTextWidth("×" + qtyWithUnitConverted(netQty(l)' in screen
         and '"×" + qtyWithUnitConverted(netQty(line)' in screen)
    c.ok("「已退 N」紧跟净数、且只在这一行真的退过时才画",
         re.search(r'Modifier\.width\(qtyW\),[\s\S]{0,400}?if \(line\.returnedQuantity > 0\) \{[\s\S]{0,200}?"已退 " \+ line\.returnedQuantity', screen) is not None)
    c.ok("「已退 N」是数据不是解释句（没挂到提示组件上）",
         re.search(r'H\w*\(\s*"已退 ', screen) is None)
    c.ok("净数不许为负（退到超过原件数也不能画出负数）", ".coerceAtLeast(0)" in screen)
    c.ok("算法本身没被动（core/ReturnRules.kt 一个字没改）",
         "fun maxReturnable(" in rules and "returnedQuantity" in rules)
    # ---- 台账 L-38 / CHG-0065（2026-10-07）：钱也要跟着退货回退 ----
    # ⛔ 上面那句"行金额与合计逐字未动"是 CHG-0054 当时的决定，**已被用户推翻**：他看到的是一行
    #    「火腿 ×2 已退 3 … ¥430.8」—— 件数是净数、钱是原价，同一行里两个数说的是两件事。
    c.ok("行金额画的是**退货后**的净额（行金额 − 单价 × 已退数量，与后端 line_receivable 同源）",
         "netLineMoneyText(line)" in screen
         and '"¥" + formatMoney(line.lineTotal)' not in screen
         and "centsToMoney(lineReceivableCents(l))" in screen,
         "退回原价 = 退过货的行仍按「当时卖了多少」显示，而合计已经退了 → 一张卡里上下对不上")
    c.ok("合计同样画净额，且只在真退过时多一颗「已退 ¥X」小字（没退过的单一个像素不动）",
         "val netTotal = netOrderMoneyText(order)" in screen
         and "val total = order.orderProducts.sumOf { moneyToDouble(it.lineTotal) }" not in screen
         and re.search(r'if \(returnedAmount > 0\.0\) \{[\s\S]{0,240}?"已退 ¥" \+ formatMoney\(order\.returnedAmount\)',
                       screen) is not None,
         "只退件数不退钱：用户 2026-10-07 报的就是这一条")

    c.section("5. 共用的件没被抄第二份")
    c.ok("状态胶囊调用点清单恰三处（定义 ＋ 两端页面）",
         hits(ui, "ReturnRequestStatusChip(") == [("ui/common/ReturnRequestChip.kt", 1),
                                                ("ui/common/ReturnRequestsUi.kt", 1),
                                                ("ui/order/OrderDetailScreen.kt", 1)],
         str(hits(ui, "ReturnRequestStatusChip(")))
    c.ok("胶囊定义只有一份",
         [rel for rel, _ in hits(ui, "fun ReturnRequestStatusChip(")] == ["ui/common/ReturnRequestChip.kt"],
         str(hits(ui, "fun ReturnRequestStatusChip(")))
    c.ok("「要退 …」的拼法只在详情页出现一次（不另造一份摘要）", screen.count('"要退 "') == 1)
    c.ok("接口的 order_id 过滤还在（后端按单过滤本来就已就绪）",
         '@Query("order_id") orderId: Long? = null' in apis and "orderId = orderId" in vm)
    c.ok("仓库层两个签名没被顺手改",
         'suspend fun myReturnRequests(orderId: Long? = null, status: String = "all")' in repo
         and 'suspend fun returnRequestTodo(status: String = "pending", orderId: Long? = null)' in repo)

    c.section("6. 不做跳转（详情页不许把用户扔进退货申请页）")
    c.ok("详情页里不出现退货申请的路由（跳过去会让「消息点进来的那一条」变成假话）",
         "shipperReturnRequests" not in screen and "dispatcherReturnRequests" not in screen)
    c.ok("那条既有红线还在（重复的那三小块只许一处）", "badge_dup" in read(RETURN_CHECK))
    c.ok("退货申请两端页面都还在（动作仍然在那边做）",
         (AND / "ui/shipper/ShipperReturnRequestsScreen.kt").exists()
         and (AND / "ui/dispatcher/DispatcherReturnRequestsScreen.kt").exists())

    c.section("7. 既有判据被同步、关键文件都在")
    c.ok("列宽判据已改成净数（否则它会盯着一句不存在的源码）",
         read(ROWCOL_CHECK).count("netQty") >= 3 and "已退 " in read(ROWCOL_CHECK),
         "netQty×" + str(read(ROWCOL_CHECK).count("netQty")))
    c.ok("列宽判据的反验也跟着加了净数的注入",
         "netQty" in read(ROOT / "_tools/qa/_reverse_verify_order_row_columns.py"))
    for f in REQUIRED_FILES:
        c.ok("关键文件在：" + f.relative_to(ROOT).as_posix(), f.exists())
    c.ok(".kt 文件数 ≥ " + str(MIN_KT) + "（防「目录被搬走 → 一条都没扫到 → 全绿」）",
         len(kts) >= MIN_KT, "len=" + str(len(kts)))

    c.section("8. 文档与反验（归档那一步才算数）")
    chg = read(CHG)
    reverse = read(REVERSE)
    c.ok("CHG-0054.md 在且写够了", len(chg) > 500, "len=" + str(len(chg)))
    for token in ["L-21", "m00542", "已退 3", "退货申请", "netQty", "不跳转"]:
        c.ok("CHG-0054.md 写了「" + token + "」", token in chg)
    c.ok("CHG-0054.md 的 Boundary 结论逐字", "- **结论**：**PRESENTATION（展示层）**" in chg)
    c.ok("CHG-0054.md 写明了「没退过货的行不画」", "没退过" in chg or "退过货" in chg)
    c.ok("README 里登记了 CHG-0054", "[CHG-0054.md](CHG-0054.md)" in read(README))
    c.ok("AI_WORK_CLAIM 里认领了 CHG-0054", "CHG-0054" in read(CLAIM))
    c.ok("反验脚本在、且注入够多（≥12 条）",
         REVERSE.exists() and reverse.count("\n    (\n") >= 12,
         "n=" + str(reverse.count("\n    (\n")))

    print("\n" + "=" * 60)
    if c.fails:
        print("❌ " + str(len(c.fails)) + " 项不通过：")
        for label, detail in c.fails:
            print("   - " + label + (" —— " + detail if detail else ""))
        return 1
    print("✅ 全部 " + str(c.n_ok) + " 项通过：件数画净数 ＋ 小字「已退 N」＋ 就地的只读退货申请。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
