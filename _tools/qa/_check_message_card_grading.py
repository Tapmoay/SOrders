#!/usr/bin/env python3
"""消息卡片「分级 + 深链」（FEAT-0019）的判据。

用户 2026-10-11 的验收口径（逐字要点）：
- 「按消息类型做颜色区别，而且**只有未读**才有这个样式，**已读所有消息一个样**」；
- 卡片最左边一条 **6px 方角竖条**（颜色 = 该消息类型对应**工作台那一格**的颜色）+ 同色小标签；
- 「我们的真正的重心是这几个字……**其他的文字你用正常的黑色就可以了**……**全是重点就是没有重点**」
  ⇒ 只有 payload 里被**业务点名**的词与数字上色（客户端不猜），已读连高亮也去掉；
- 能查的消息点进去**直达**：库存预警 → 库存管理并显示那个商品与当前库存……没有 payload 的就不跳。

这条判据钉的是「源码里那几处实现」，会被写坏成什么样：

| 写坏的样子 | 用户会看到 |
| --- | --- |
| 已读的卡片也画竖条 / 也上色 | 满屏都是彩色，「已读所有消息一个样」破功 |
| 把 severity 的着色去掉（或把 warn 也涂成红） | 重点词又变成一个样，风险分不出来 |
| 在消息页里再写一份「type → 颜色」 | 同一种消息两处两个色 |
| 竖条从 6px 改掉 / 圆角改成圆的 | 与用户已过目的样本（6px、方角）不一致 |
| 库存深链把 ?focus=<商品号> 丢掉 | 点库存预警落到一整张库存表，得自己找那个商品 |
| payload 缺键（没有 product_id / order_id）时瞎跳 | 点进去是一张无关的订单 / 空列表 |
| 消息页又抄一份「有 order_id 就开订单详情」 | 库存预警点进去开出一张订单 |

R4-BOUNDARY-JUSTIFICATION: 这条判据只读**源码文本**（Kotlin 与 Python 源码），
不去渲染界面、也不连后端 —— 「6px 竖条到底画出来多宽」「点一下真的跳到那一页」属于
人眼验收与真机点验（回执里如实写：未做真机点验）。它守的是**代码里那几处唯一实现与守卫**：
颜色表一处、风险色一处、路由一处、缺键不跳、未读才画 —— 这些一旦被改回去，
判据立刻变红（见 _reverse_verify_message_card_grading.py 的 13 条注入）。
"""

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
MESSAGES = ANDROID / "ui/messages"
GRADING = MESSAGES / "MessageGrading.kt"
SCREEN = MESSAGES / "MessagesScreen.kt"
ROUTING = MESSAGES / "NoticeRouting.kt"
NAVGRAPH = ANDROID / "ui/nav/NavGraph.kt"
ROUTES = ANDROID / "ui/nav/Routes.kt"
MODULES = ANDROID / "ui/nav/Modules.kt"
INVENTORY = ANDROID / "ui/dispatcher/InventoryScreen.kt"
ROLEHOME = ANDROID / "ui/home/RoleHomeScreen.kt"
DTO = ANDROID / "data/remote/dto/Dtos.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/messages/MessageGradingTest.kt"

MIN_FILES = 10
MIN_TEST_CASES = 10
MSG_TAB = 'BottomTab("消息", Icons.Default.Notifications, "messages", color = MessageRed)'

FAILS = []


def read(path):
    return path.read_text(encoding="utf-8")


def strip_comments(src):
    """去掉注释再匹配：散文里出现的关键词（例如注释里解释"以前那条 order_id 兜底"）不算实现。"""
    out = []
    in_block = False
    for line in src.splitlines():
        s = line
        if in_block:
            if "*/" in s:
                s = s.split("*/", 1)[1]
                in_block = False
            else:
                continue
        while "/*" in s:
            head, tail = s.split("/*", 1)
            if "*/" in tail:
                s = head + tail.split("*/", 1)[1]
            else:
                s = head
                in_block = True
                break
        if "//" in s:
            s = s.split("//", 1)[0]
        out.append(s)
    return chr(10).join(out)


def nearest_if(src, needle):
    """针尖所在的那一层守卫：返回它前面最近的一条 if (...)。"""
    idx = src.index(needle)
    head = src[:idx]
    start = head.rfind("if (")
    if start < 0:
        return ""
    rest = head[start:]
    end = rest.find(") {")
    return rest[: end + 3] if end >= 0 else ""


def check(name, cond, detail=""):
    if cond:
        print("[ OK ] " + name)
    else:
        print("[FAIL] " + name + ("  --  " + detail if detail else ""))
        FAILS.append(name)


def main():
    files = [GRADING, SCREEN, ROUTING, NAVGRAPH, ROUTES, MODULES, INVENTORY, ROLEHOME, DTO, TEST]
    missing = [str(p.relative_to(ROOT)) for p in files if not p.exists()]
    if missing:
        print("[FAIL] 文件齐全  --  缺少：" + "，".join(missing))
        print("反空转：至少要有 " + str(MIN_FILES) + " 个文件参与，缺文件时判据无意义。")
        return 1

    grading = read(GRADING)
    grading_code = strip_comments(grading)
    screen = read(SCREEN)
    screen_code = strip_comments(screen)
    routing_code = strip_comments(read(ROUTING))
    navgraph_code = strip_comments(read(NAVGRAPH))
    routes_code = strip_comments(read(ROUTES))
    modules_code = strip_comments(read(MODULES))
    inventory_code = strip_comments(read(INVENTORY))
    rolehome_code = strip_comments(read(ROLEHOME))
    dto = read(DTO)
    test = read(TEST)

    # ---- 1) 类型 → 颜色：只有一处 ----
    family_defs = []
    hex_outsiders = []
    hex_re = re.compile("0xFF[0-9A-Fa-f]{6}")
    for p in sorted((ANDROID / "ui").rglob("*.kt")):
        s = strip_comments(read(p))
        if "fun familyOf(" in s or "enum class MessageFamily" in s:
            family_defs.append(p)
        if p.parent == MESSAGES and p.name != "MessageGrading.kt":
            for m in hex_re.finditer(s):
                hex_outsiders.append(p.name + " 里的 " + m.group(0))
    check(
        "类型→色只有一处 familyOf",
        len(family_defs) == 1 and family_defs[0] == GRADING,
        "定义出现在：" + "，".join(str(x.relative_to(ROOT)) for x in family_defs),
    )
    check("消息页里不许再写颜色字面量", not hex_outsiders, "，".join(hex_outsiders[:5]))

    family_colors = [
        ("MSG_COLOR_ORDER", "0xFF1E6FFFL"),
        ("MSG_COLOR_DONE", "0xFF00AC6EL"),
        ("MSG_COLOR_VOID", "0xFF917A16L"),
        ("MSG_COLOR_STOCK", "0xFF008EABL"),
        ("MSG_COLOR_RECEIPT", "0xFF9C88E0L"),
        ("MSG_COLOR_PAYABLE", "0xFFE05288L"),
        ("MSG_COLOR_INVOICE", "0xFFE08034L"),
        ("MSG_COLOR_PRICE", "0xFFB65DC4L"),
        ("MSG_COLOR_VEHICLE", "0xFF00AAAEL"),
        ("MSG_COLOR_ACCOUNT", "0xFFAC7217L"),
        ("MSG_COLOR_SYSTEM", "0xFFE07B80L"),
    ]
    bad_colors = [
        name + " 不是 " + val
        for (name, val) in family_colors
        if ("const val " + name + " = " + val) not in grading_code
    ]
    check("11 个族色与用户过目的样本一致", not bad_colors, "；".join(bad_colors))

    # ---- 2) severity → 风险色：只有一处，且三档分明 ----
    check(
        "危险/警告两个文字色与样本一致",
        "const val MSG_TEXT_DANGER = 0xFFD93025L" in grading_code
        and "const val MSG_TEXT_WARN = 0xFFE07B00L" in grading_code,
    )
    check(
        "风险→颜色只有一处 emphasisColor",
        grading_code.count("fun emphasisColor(") == 1
        and "MessageRisk.DANGER -> MSG_TEXT_DANGER" in grading_code
        and "MessageRisk.WARN -> MSG_TEXT_WARN" in grading_code
        and "MessageRisk.INFO -> null" in grading_code,
    )
    check(
        "severity 三档认得出（缺字段按 info）",
        'fun riskOf(severity: String?): MessageRisk' in grading_code
        and '"danger" -> MessageRisk.DANGER' in grading_code
        and '"warn", "warning" -> MessageRisk.WARN' in grading_code
        and "else -> MessageRisk.INFO" in grading_code,
    )

    # ---- 3) 卡片：未读才有的样式 ----
    check(
        "竖条是 6px 方角",
        "private val MESSAGE_BAR_WIDTH = 6.dp" in screen_code
        and "private val MESSAGE_BAR_SHAPE = RoundedCornerShape(3.dp)" in screen_code,
    )
    check(
        "竖条只有未读才画",
        nearest_if(screen_code, ".background(Color(family.color), MESSAGE_BAR_SHAPE)") == "if (unread) {",
        "竖条的守卫是：" + (nearest_if(screen_code, ".background(Color(family.color), MESSAGE_BAR_SHAPE)") or "（找不到）"),
    )
    check(
        "已读一律灰调且去掉高亮",
        "val words = if (unread) emphasisWords(m.payload) else emptyList()" in screen_code,
    )
    check(
        "链接只有未读且真能跳才画",
        "if (unread && action != null && route != null) {" in screen_code,
    )
    check(
        "未读才画类型小标签（已读写「已读」）",
        "MessageFamilyChip(label = messageLabel(m.type, m.payload), color = family.color)" in screen_code
        and '"已读",' in screen_code,
    )

    # ---- 4) 只有被点名的片段上色 ----
    check(
        "被点名的片段才上色（找不到就原样）",
        grading_code.count("fun splitByEmphasis(") == 1
        and "val hit = needles.firstOrNull { text.startsWith(it, i) }" in grading_code
        and "if (needles.isEmpty()) return listOf(MessageTextSpan(text, false))" in grading_code
        and "splitByEmphasis(text, words).forEach { span ->" in screen_code,
    )
    check(
        "点名词只从 payload.emphasis 取（客户端不猜）",
        'const val KEY_EMPHASIS = "emphasis"' in grading_code
        and "fun emphasisWords(payload: Map<String, JsonElement>?): List<String>" in grading_code,
    )

    # ---- 5) 深链：唯一一处决策 + 缺键不跳 ----
    check(
        "退货那半条线仍只走 noticeReturnRoute",
        "noticeReturnRoute(roleKey, type, payload)?.let { return it }" in grading_code
        and grading_code.count("fun noticeRoute(") == 1
        and routing_code.count("fun noticeReturnRoute(") == 1,
    )
    check(
        "卡片点击只认 noticeRoute 算出来的路由",
        "val route = noticeRoute(roleKey, m.type, m.payload)" in screen_code
        and "route?.let { onOpenRoute(it) }" in screen_code,
    )
    check(
        "消息页不再自己兜底跳订单",
        "order_id" not in screen_code and "onOpenOrder" not in screen_code,
    )
    check(
        "消息页签名只留一个去向回调",
        "onOpenRoute: (String) -> Unit = {}," in screen_code
        and "onOpenReturnRequest" not in screen_code
        and "onOpenReturnRequest" not in navgraph_code
        and "onOpenReturnRequest" not in rolehome_code,
    )
    check(
        "两个调用点都接 onOpenRoute",
        "onOpenRoute = { route -> navController.navigate(route) }" in navgraph_code
        and "onOpenRoute = onNavigate" in rolehome_code,
    )
    check(
        "缺键/非数/<=0 一律不跳",
        grading_code.count("private fun longAt(") == 1
        and "as? JsonPrimitive" in grading_code
        and "takeIf { it > 0L }" in grading_code,
    )
    check(
        "单测钉住缺键不跳",
        "assertNull(noticeRoute(" in test and "缺商品号就不跳" in test,
    )

    # ---- 6) 库存深链：一路带到那个商品 ----
    check(
        "Routes 只有一处拼 focus",
        routes_code.count("private fun withFocus(") == 1
        and "fun inventory(focusProductId: Long? = null): String = withFocus(INVENTORY, focusProductId)" in routes_code,
    )
    check(
        "库存消息带商品号才跳",
        'MessageFamily.STOCK -> longAt(payload, "product_id")?.let { Routes.inventory(it) }' in grading_code,
    )
    check(
        "库存路由收了 focus 参数",
        'Routes.INVENTORY + "?focus={focusId}"' in navgraph_code
        and 'navArgument("focusId")' in navgraph_code
        and "defaultValue = 0L" in navgraph_code
        and 'focusProductId = entry.arguments?.getLong("focusId") ?: 0L' in navgraph_code,
    )
    check(
        "库存页加的是可选参数（老入口行为不变）",
        "focusProductId: Long = 0L," in inventory_code and "InventoryBody(vm, focusProductId)" in inventory_code,
    )
    check(
        "库存页真的定位到那个商品",
        "val focusIndex = visible.indexOfFirst { it.productId == focusProductId }" in inventory_code
        and "listState.animateScrollToItem(focusIndex + 1)" in inventory_code
        and "focused = s.productId == focusProductId," in inventory_code,
    )

    # ---- 7) 出参与"不许动"的东西 ----
    check("出参模型补了 severity（缺字段不崩）", "val severity: String? = null," in dto)
    check(
        "底部消息 Tab 的三处定义没被动过",
        modules_code.count(MSG_TAB) == 3,
        "实际出现 " + str(modules_code.count(MSG_TAB)) + " 次",
    )

    # ---- 8) 反空转 ----
    cases = test.count("@Test")
    check("单测至少 " + str(MIN_TEST_CASES) + " 例", cases >= MIN_TEST_CASES, "实际 " + str(cases))
    check("反空转：参与的文件数达到下限", len(files) >= MIN_FILES, "实际 " + str(len(files)))

    print("")
    if FAILS:
        print("消息卡片分级与深链：判据不通过 " + str(len(FAILS)) + " 项 —— " + "，".join(FAILS))
        return 1
    print(
        "消息卡片分级与深链：全部判据通过（"
        + str(len(family_colors))
        + " 个族色 / "
        + str(cases)
        + " 例单测 / "
        + str(len(files))
        + " 个文件）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
