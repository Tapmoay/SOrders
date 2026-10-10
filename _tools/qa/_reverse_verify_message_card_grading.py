#!/usr/bin/env python3
"""消息卡片「分级 + 深链」（FEAT-0019）的反向验证：把实现**故意写坏**，看判据是否变红。

配合 _check_message_card_grading.py。每一条注入都对应一种"用户会当场看出来"的坏法
（已读也上色 / 风险色没了 / 类型映射抄第二份 / 6px 方角改掉 / 库存深链丢商品号 /
payload 缺键瞎跳 / 消息页又抄一份订单兜底 / 退货规则抄第二份）。
注入后判据**必须变红**，而且红的正是那条该红的判据；末尾逐字节还原，再跑一次要求全绿。

用法：python _tools/qa/_reverse_verify_message_card_grading.py
"""

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_message_card_grading.py"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = ANDROID / "ui/messages/MessagesScreen.kt"
GRADING = ANDROID / "ui/messages/MessageGrading.kt"
ROUTES = ANDROID / "ui/nav/Routes.kt"
NAVGRAPH = ANDROID / "ui/nav/NavGraph.kt"
INVENTORY = ANDROID / "ui/dispatcher/InventoryScreen.kt"

LF = chr(10)
CRLF = chr(13) + chr(10)

BAR_OLD = """            if (unread) {
                Spacer(
                    Modifier
                        .padding("""
BAR_NEW = """            if (true) {
                Spacer(
                    Modifier
                        .padding("""
EXTRA_COLOR_OLD = """private val MESSAGE_BAR_WIDTH = 6.dp"""
EXTRA_COLOR_NEW = """private val MESSAGE_BAR_WIDTH = 6.dp
private val MESSAGE_BAR_COLOR_SECOND_COPY = 0xFF008EABL"""
EXTRA_FAMILY_OLD = """private val MESSAGE_BAR_WIDTH = 6.dp"""
EXTRA_FAMILY_NEW = """private val MESSAGE_BAR_WIDTH = 6.dp
private fun familyOf(type: String): MessageFamily = MessageFamily.SYSTEM"""
ORDER_FALLBACK_OLD = """                    val route = noticeRoute(roleKey, m.type, m.payload)"""
ORDER_FALLBACK_NEW = """                    val route = m.payload?.get("order_id")?.toString()?.toLongOrNull()
                        ?.let { Routes.orderDetail(it) } ?: noticeRoute(roleKey, m.type, m.payload)"""
NAV_OLD = """                focusProductId = entry.arguments?.getLong("focusId") ?: 0L,"""
NAV_NEW = """                focusProductId = 0L,"""
STOCK_OLD = """                                focused = s.productId == focusProductId,"""
STOCK_NEW = """                                focused = false,"""

MUTATIONS = [
    ("已读也画竖条（已读那张卡也带色条）", SCREEN, BAR_OLD, BAR_NEW, "竖条只有未读才画"),
    ("已读也上高亮（「已读所有消息一个样」破功）", SCREEN,
     "val words = if (unread) emphasisWords(m.payload) else emptyList()",
     "val words = emphasisWords(m.payload)", "已读一律灰调且去掉高亮"),
    ("已读也画「查看… ›」链接", SCREEN,
     "if (unread && action != null && route != null) {",
     "if (action != null && route != null) {", "链接只有未读且真能跳才画"),
    ("竖条从 6px 改成 4px", SCREEN,
     "private val MESSAGE_BAR_WIDTH = 6.dp", "private val MESSAGE_BAR_WIDTH = 4.dp", "竖条是 6px 方角"),
    ("消息页里又写了一份颜色字面量", SCREEN, EXTRA_COLOR_OLD, EXTRA_COLOR_NEW, "消息页里不许再写颜色字面量"),
    ("类型→色映射抄成第二处", SCREEN, EXTRA_FAMILY_OLD, EXTRA_FAMILY_NEW, "类型→色只有一处 familyOf"),
    ("warn 也涂成红（风险两档变一档）", GRADING,
     "const val MSG_TEXT_WARN = 0xFFE07B00L", "const val MSG_TEXT_WARN = 0xFFD93025L", "危险/警告两个文字色"),
    ("severity 的着色整个去掉", GRADING,
     "MessageRisk.WARN -> MSG_TEXT_WARN", "MessageRisk.WARN -> null", "风险→颜色只有一处 emphasisColor"),
    ("消息页又抄一份「有 order_id 就开订单」兜底", SCREEN,
     ORDER_FALLBACK_OLD, ORDER_FALLBACK_NEW, "消息页不再自己兜底跳订单"),
    ("退货那半条线抄第二份（不再走 noticeReturnRoute）", GRADING,
     "noticeReturnRoute(roleKey, type, payload)?.let { return it }", "", "退货那半条线仍只走 noticeReturnRoute"),
    ("payload 缺键时瞎跳（回落成 1L）", GRADING,
     "(payload?.get(key) as? JsonPrimitive)?.contentOrNull?.trim()?.toLongOrNull()?.takeIf { it > 0L }",
     "(payload?.get(key) as? JsonPrimitive)?.contentOrNull?.trim()?.toLongOrNull() ?: 1L",
     "缺键/非数/<=0 一律不跳"),
    ("库存路由把 ?focus=<商品号> 丢掉", ROUTES,
     "fun inventory(focusProductId: Long? = null): String = withFocus(INVENTORY, focusProductId)",
     "fun inventory(focusProductId: Long? = null): String = INVENTORY", "Routes 只有一处拼 focus"),
    ("库存路由不再把商品号交给库存页", NAVGRAPH, NAV_OLD, NAV_NEW, "库存路由收了 focus 参数"),
    ("库存页不再聚焦那个商品", INVENTORY, STOCK_OLD, STOCK_NEW, "库存页真的定位到那个商品"),
]


def read_raw(path):
    return path.read_bytes()


def native(text, raw):
    nl = CRLF if CRLF.encode("utf-8") in raw else LF
    return text.replace(LF, nl)


def run_check():
    res = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        cwd=str(ROOT),
    )
    out = res.stdout.decode("utf-8", errors="replace")
    err = res.stderr.decode("utf-8", errors="replace")
    return res.returncode, out, err


def main():
    print("反向验证：消息卡片分级与深链（注入 —— 判据必须变红 —— 逐字节还原）")
    print("")

    code, out, err = run_check()
    if code != 0:
        print("[FAIL] 基线不绿，先让 _check_message_card_grading.py 全绿再跑反向验证")
        print(out)
        print(err)
        return 1
    print("[ OK ] 基线全绿")

    passed = 0
    for (name, path, old, new, expect) in MUTATIONS:
        raw = read_raw(path)
        text = raw.decode("utf-8")
        old_native = native(old, raw)
        new_native = native(new, raw)
        hits = text.count(old_native)
        if hits != 1:
            print("[FAIL] " + name + "  --  锚点在 " + path.name + " 里出现 " + str(hits) + " 次（要求 1 次），这条注入没生效")
            continue
        try:
            path.write_bytes(text.replace(old_native, new_native, 1).encode("utf-8"))
            code, out, err = run_check()
            red_lines = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            hit = code != 0 and any(expect in ln for ln in red_lines)
            if hit:
                passed += 1
                print("[ OK ] " + name + "  --  判据变红：" + expect)
            else:
                print("[FAIL] " + name + "  --  判据没变红（期望关键词：" + expect + "，退出码 " + str(code) + "）")
                print("       " + (red_lines[0] if red_lines else "（没有 [FAIL] 行）"))
        finally:
            path.write_bytes(raw)
            if read_raw(path) != raw:
                print("[FAIL] " + name + "  --  还原后与原文不是逐字节相同：" + str(path))
                return 2

    print("")
    code, out, err = run_check()
    if code == 0:
        print("[ OK ] 末尾还原后判据全绿")
    else:
        print("[FAIL] 末尾还原后判据没回到全绿，工作区可能被写坏")
        print(out)
        return 2

    total = len(MUTATIONS)
    print("")
    if passed == total:
        print("反向验证通过：" + str(passed) + "/" + str(total) + " 条注入都让判据变红，且都逐字节还原。")
        return 0
    print("反向验证不通过：" + str(passed) + "/" + str(total) + " 条注入生效（其余没抓到）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
