# -*- coding: utf-8 -*-
"""反向验证：把「下单时选送达日期」（FEAT-0028）逐条打断，看
_tools/qa/_check_order_delivery_date.py 是否每次都报红。

用法（从仓库根）：python _tools/qa/_reverse_verify_order_delivery_date.py

纪律（与兄弟脚本一致）：先确认源码完好时判据全绿 → 每条只改一处 → 立刻跑判据 →
finally 里逐字节还原 → 结束时核对被碰过的文件与运行前逐字节一致 → 注入没生效算失败。

这 12 条对应的正是这一单最容易改坏的地方，共同点是**改完都能编译、App 也照样跑**：

1-2   后端那条闸与那次赋值（不写进去 / 不拒昨天）；
3     迁移的版本号对不上（生产库永远没有这一列，而本地新库看不出来）；
4     红条画到日期行**下面**（用户点名要"在日期选择前面"）；
5     红条不红了（改成主题第二色，看起来仍像一条提示）；
6     红条的字被改成软话（"尽量提前" —— 那就不是规矩了）；
7     日历里过去的日子又能选（选出一个注定被拒的日子）；
8     毫秒换算改回设备时区（东八区打开就停在昨天，界面看不出来）；
9     下单页自己算日期（规则从此有两份）；
10    默认值写死成某个日期（业务口径被抄进状态）；
11    请求体里不发送达日（后端收到的永远是 NULL）；
12    拆分单不继承送达日（同一趟货，日子凭空丢了）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools/ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

JUDGE = ROOT / "_tools/qa/_check_order_delivery_date.py"

COMMAND = "backend/app/commands/order.py"
FLOW = "backend/app/services/order_flow.py"
MIGRATION = "backend/app/migrations/036_order_delivery_date.py"
SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt"
RULES = "android/app/src/main/java/com/tapmoay/sorders/ui/common/DeliveryDate.kt"
CARD = "android/app/src/main/java/com/tapmoay/sorders/ui/common/OrderCard.kt"
DETAIL = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt"
INSPECTION = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleInspection.kt"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateViewModel.kt"

NL = chr(10)
Q = chr(34)

#: 红条那次调用（含行首缩进）：挪位注入要按**整行**搬，少一个空格就对不上。
NOTICE_LINE = "                    DeliveryLeadNotice()" + NL
#: 日期那一行的收尾（括号那一行）：红条要搬到它**后面**去。
ROW_END = "                        iconTint = Color(ShipperTeal)," + NL + "                    )" + NL

#: 红条那句逐字文案（注入 ⑥ 把它改成软话）。
NOTICE_TEXT = "当天下的单，不一定能准时送达。"


# --------------------------------------------------------------- 12 条注入


def _command_forgets_to_store(s: str) -> str:
    """命令里那次赋值被删掉（接口照收、库里永远是 NULL）。"""
    return s.replace("        delivery_date=body.delivery_date,", "", 1)


def _command_accepts_past(s: str) -> str:
    """「早于今天」那道闸没了（昨天的日期照收，那单注定晚点）。"""
    return s.replace(
        "if body.delivery_date is not None and body.delivery_date < business_today():",
        "if False:",
        1,
    )


def _migration_version_drifts(s: str) -> str:
    """迁移的 VERSION 与文件名对不上（运行器按文件名的版本记账，这条会被当成另一条）。"""
    return s.replace("VERSION = 36", "VERSION = 37", 1)


def _notice_below_row(s: str) -> str:
    """红条画到日期那一行**下面**（用户点名要"在日期选择前面"）。"""
    if NOTICE_LINE not in s or ROW_END not in s:
        return s
    return s.replace(NOTICE_LINE, "", 1).replace(ROW_END, ROW_END + NOTICE_LINE, 1)


def _notice_not_red(s: str) -> str:
    """红条不红了（换成主题第二色的容器 —— 看起来仍像一条提示）。"""
    return s.replace(
        "color = MaterialTheme.colorScheme.errorContainer",
        "color = MaterialTheme.colorScheme.secondaryContainer",
        1,
    )


def _notice_softened(s: str) -> str:
    """红条的字被改成软话（"尽量提前" —— 那就不是规矩了）。"""
    return s.replace(NOTICE_TEXT, "尽量提前一天下单。", 1)


def _picker_allows_past(s: str) -> str:
    """日历里过去的日子又能选（选出一个注定被后端拒的日子）。"""
    return s.replace(
        "Boolean = deliveryDateSelectable(utcTimeMillis)",
        "Boolean = true",
        1,
    )


def _millis_use_device_zone(s: str) -> str:
    """毫秒换算改回**设备时区**（东八区打开就停在昨天，而且界面上看不出来）。"""
    return s.replace(
        "Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC)",
        "Instant.ofEpochMilli(millis).atZone(java.time.ZoneId.systemDefault())",
        1,
    )


def _rules_copy_their_own_millis(s: str) -> str:
    """规则文件自己又抄一份毫秒换算（两对同名函数 = 两份口径）。"""
    return s.replace(
        "fun deliveryDateChoices(",
        "internal fun isoDateOfMillis(x: Long): String = " + Q + Q + NL + NL + "fun deliveryDateChoices(",
        1,
    )


def _screen_computes_today(s: str) -> str:
    """下单页自己算"今天"（规则从此有两份）。"""
    return s.replace(
        "    var showDeliverySheet by remember { mutableStateOf(false) }",
        "    val _today = java.time.LocalDate.now()" + NL
        + "    var showDeliverySheet by remember { mutableStateOf(false) }",
        1,
    )


def _default_prefilled(s: str) -> str:
    """又替用户预填了明天（用户 2026-10-22 逐字否过：「默认是空的是不填的，不是默认就填明天」）。"""
    return s.replace(
        'var deliveryDate by mutableStateOf("")',
        "var deliveryDate by mutableStateOf(defaultDeliveryDate())",
        1,
    )


def _request_omits_date(s: str) -> str:
    """请求体里不发送达日（后端收到的永远是 NULL）。"""
    return s.replace("                            deliveryDate = deliveryDate," + NL, "", 1)


def _pill_removed(s: str) -> str:
    """「提前一天」的深红胶囊被拆回普通文字（重点又看不见了）。"""
    return s.replace("shape = CircleShape,", "shape = RoundedCornerShape(0.dp),", 1)


def _missing_date_hidden(s: str) -> str:
    """没选过送达日时又变成"整行不画"（用户明确否过：要写一条"他没有选择"）。"""
    return s.replace('deliveryDateText(raw, status, today) ?: "未选择送达日期"',
                     'deliveryDateText(raw, status, today) ?: ""', 1)


def _card_hides_date(s: str) -> str:
    """订单卡片不画送达日期（司机与派单员都看不到"还剩几天"）。"""
    return s.replace(
        "deliveryDateDisplay(order.deliveryDate, order.status),",
        '"",',
        1,
    )


def _detail_hides_date(s: str) -> str:
    """订单详情不画送达日期。"""
    return s.replace(
        'InfoRow("送达日期", deliveryDateDisplay(order.deliveryDate, order.status))',
        'InfoRow("下单日期", deliveryDateDisplay(order.deliveryDate, order.status))',
        1,
    )


def _finished_still_counts_down(s: str) -> str:
    """已送达/已撤销的单还在倒计时（读起来像"还没到"）。"""
    return s.replace(
        "if (status.uppercase() in FINISHED_STATUS) return md",
        "if (false) return md",
        1,
    )


def _warn_note_plain(s: str) -> str:
    """「不保证准时」退回普通小字（用户点名要红色深胶囊框起来）。"""
    return s.replace("deliveryLeadDays(iso) == 0L -> Color(DangerRed)", "deliveryLeadDays(iso) == 0L -> null", 1)


def _hint_loses_amber(s: str) -> str:
    """抽屉里那句提示的黄橙底色没了（与下面那片红糊成一片）。"""
    return s.replace("background(Color(0xFFFFF7DE), RoundedCornerShape(10.dp))", "background(Color.Transparent, RoundedCornerShape(10.dp))", 1)


def _recommend_not_green(s: str) -> str:
    """「推荐」没有深绿底了（用户点名要给绿色推荐一个深绿底）。"""
    return s.replace("iso == recommended -> Color(ThemeGreenDeep)", "iso == recommended -> null", 1)


def _split_drops_date(s: str) -> str:
    """拆分单不继承送达日（同一趟货，日子凭空丢了）。"""
    return s.replace(
        "            delivery_date=order.delivery_date," + NL,
        "",
        1,
    )


CASES = [
    ("① 命令里那次赋值被删掉（库里永远 NULL）", COMMAND, _command_forgets_to_store,
     "create_order 把它写进 Order"),
    ("② 「早于今天」那道闸没了", COMMAND, _command_accepts_past, "拒「早于今天」"),
    ("③ 迁移的 VERSION 与文件名对不上", MIGRATION, _migration_version_drifts,
     "迁移 036 存在且 VERSION = 36"),
    ("④ 红条画到日期行下面", SCREEN, _notice_below_row, "红条画在日期那一行之前"),
    ("⑤ 红条不红了", SCREEN, _notice_not_red, "警告是**红**的"),
    ("⑥ 红条的字被改成软话", SCREEN, _notice_softened, "逐字写着「提前一天」"),
    ("⑦ 日历里过去的日子又能选", SCREEN, _picker_allows_past, "日历里过去的日子点不动"),
    ("⑧ 毫秒换算改回设备时区", INSPECTION, _millis_use_device_zone, "共用的毫秒换算是 **UTC 零点**"),
    ("⑧b 规则文件自己又抄一份毫秒换算", RULES, _rules_copy_their_own_millis,
     "⛔ 规则文件不自己再抄一份毫秒换算"),
    ("⑨ 下单页自己算「今天」", SCREEN, _screen_computes_today, "下单页自己不碰 java.time"),
    ("⑩ 又替用户预填明天", VM, _default_prefilled, "VM 的初值是**空串**"),
    ("⑪ 请求体里不发送达日", VM, _request_omits_date, "VM 把值放进请求体"),
    ("⑫ 拆分单不继承送达日", FLOW, _split_drops_date, "拆分单继承送达日"),
    ("⑬ 「提前一天」的深红胶囊被拆掉", SCREEN, _pill_removed, "深红胶囊"),
    ("⑭ 订单卡片不画送达日期", CARD, _card_hides_date, "卡片上有一行送达日期"),
    ("⑮ 订单详情不画送达日期", DETAIL, _detail_hides_date, "详情有一行「送达日期」"),
    ("⑯ 已送达/已撤销的单还在倒计时", RULES, _finished_still_counts_down, "终态订单不再显示倒计时"),
    ("⑰ 没选过送达日又变成整行/空字符串", RULES, _missing_date_hidden, "不许整行消失"),
    ("⑱ 「不保证准时」不再用深红胶囊", SCREEN, _warn_note_plain, "深红胶囊"),
    ("⑲ 「推荐」没有深绿胶囊了", SCREEN, _recommend_not_green, "深绿胶囊"),
    ("⑳ 提示的黄橙底色没了", SCREEN, _hint_loses_amber, "黄橙底色"),
]

# --------------------------------------------------------------- 脚手架


def read_src(rel):
    path = rel if isinstance(rel, Path) else (ROOT / rel)
    data = path.read_bytes()
    crlf = b"\r\n" in data
    return path, data.decode("utf-8").replace("\r\n", "\n"), crlf


def write_src(path: Path, text: str, crlf: bool) -> None:
    out = text.replace("\n", "\r\n") if crlf else text
    path.write_bytes(out.encode("utf-8"))


def run_judge():
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(JUDGE)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def hit(out: str, want: str) -> bool:
    """判据报红的那一行里必须出现关键词（防别处碰巧提到）。"""
    for ln in out.splitlines():
        if ("BAD" in ln or "[FAIL]" in ln) and want in ln:
            return True
    return False


def run_all() -> int:
    rc, out = run_judge()
    if rc != 0:
        print("❌ 前提不成立：源码完好时判据必须是绿的，实际 rc=" + str(rc))
        print(out[-4000:])
        return 1
    print("前提成立：源码完好时判据全绿。")
    print("")
    touched = {}
    ok = 0
    skipped = []
    missed = []
    try:
        for label, rel, mutate, want in CASES:
            path, plain, crlf = read_src(rel)
            if path not in touched:
                touched[path] = (plain, crlf)
            mutated = mutate(plain)
            if mutated == plain:
                print("  [SKIP] " + label + " —— 注入没生效（锚点过期，请更新本脚本的常量）")
                skipped.append(label)
                continue
            write_src(path, mutated, crlf)
            try:
                rc2, out2 = run_judge()
            finally:
                write_src(path, plain, crlf)
            if rc2 != 0 and hit(out2, want):
                print("  [OK]   " + label + " → 判据报红：" + want)
                ok += 1
            else:
                print("  [!!]   " + label + " → 期望判据报红「" + want + "」，实际 rc=" + str(rc2))
                missed.append(label)
    finally:
        for path, (plain, crlf) in touched.items():
            write_src(path, plain, crlf)
    dirty = []
    for path, (plain, crlf) in touched.items():
        if read_src(path)[1] != plain:
            dirty.append(str(path.relative_to(ROOT)))
    print("")
    if dirty:
        print("❌ 还原检查：这些文件没还原干净：" + "、".join(dirty))
        return 1
    print("✅ 还原检查：" + str(len(touched)) + " 个被碰过的文件与运行前逐字节一致")
    if skipped:
        print("❌ " + str(len(skipped)) + " 条注入没生效（锚点过期）：" + "、".join(skipped))
    if missed:
        print("❌ " + str(len(missed)) + " 条注入没能让判据报红：" + "、".join(missed))
    if skipped or missed:
        return 1
    print("✅ " + str(ok) + " 条注入都证明「送达日独立成列、提前一天有闸、红条在日期行上面、日期规则只有一处」真的成立。")
    return 0


def main() -> int:
    print("反向验证 · 下单时选送达日期（FEAT-0028）")
    print("")
    lock_reverse_verify()
    try:
        return run_all()
    finally:
        unlock_reverse_verify()


if __name__ == "__main__":
    raise SystemExit(main())
