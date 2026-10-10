# -*- coding: utf-8 -*-
"""反向验证：把「车辆年检两个日期字段」（FEAT-0022 App 端）逐条打断，看
_tools/qa/_check_vehicle_inspection_ui.py 是否每次都报红。

用法（从仓库根）：python _tools/qa/_reverse_verify_vehicle_inspection_ui.py

纪律（与兄弟脚本一致）：

* 先确认**源码完好时判据是全绿的**（前提不成立就直接失败，不做任何注入）；
* 每条注入只改一处、改完立刻跑判据、finally 里**逐字节还原**；
* 结束时核对「被碰过的文件与运行前逐字节一致」；
* 注入没生效（锚点变了 → 替换结果与原文件相同）算 SKIP = 失败；
* 全程拿着 lock_reverse_verify：注入期间别的检查看这份工作区会得到不可信的结论。

这 14 条对应的正是这一单最容易被改坏的地方 —— 它们有个共同点：**改完都能编译、
App 也照样跑**，只有把日期拿去手工算一遍、或者拿两个窗口对一遍才会发现：

1-2    PATCH 语义：编辑时把没填的日期也原样发出去（清空老车本来填过的日期）、
       新建时没填也发一格空日期；
3-4    分档：过期那条画成 warn（红变橙）、30 天以内那档干脆不存在（没有分档）；
5      消息族：新增的 vehicle.inspection_overdue 漏出车辆族（竖条从 #00AAAE 掉回系统灰）；
6-7    唯一算法：卡片里长出第二套算法、后端给的下次年检日期被丢掉不用；
8      DTO：上牌日期那一格消失（老库的日期读不回来）；
9      表单：日期选择器被换成别的控件；
10-12  库存：偏低盖掉低库存、库存页自己判偏低、偏低不再用 warn 橙；
13     本脚本自己摘掉注入锁（注入期间的结论从此不可信）。
14     表单：未来日期在选择层就能选中（后端不做范围校验，填了只是永远不提醒）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools/ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

JUDGE = ROOT / "_tools/qa/_check_vehicle_inspection_ui.py"

INSPECTION = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleInspection.kt"
SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleManageScreen.kt"
GRADING = "android/app/src/main/java/com/tapmoay/sorders/ui/messages/MessageGrading.kt"
CARDKIT = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductCardKit.kt"
INVENTORY = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/InventoryScreen.kt"
DTOS = "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"
SELF = "_tools/qa/_reverse_verify_vehicle_inspection_ui.py"

#: 反引号与引号**不写进源码字面量**：这样整份脚本里不会出现「某种引号被迫转义」的角落。
BT = chr(96)
Q = chr(34)
NL = chr(10)

#: 本脚本自己的注入锁（连 unlock_reverse_verify 一起换掉：它含这个子串，
#: 只删一半的话判据那一条照样是绿的）。
LOCK = "lock_reverse_verify"


# --------------------------------------------------------------- 13 条注入


def _edit_sends_untouched_date(s: str) -> str:
    """编辑时把没填的日期也原样发出去（老车本来填过的日期被清空，用户什么都没做）。"""
    return s.replace("registrationDate = changedDateOrNull(before?.registrationDate, draftRegistrationDate),",
                     "registrationDate = draftRegistrationDate.trim(),")


def _create_sends_blank_date(s: str) -> str:
    """新建时没填也发一格空日期（老库上就是一次「把它清空」的指令）。"""
    return s.replace("registrationDate = newDateOrNull(draftRegistrationDate),",
                     "registrationDate = draftRegistrationDate,")


def _overdue_painted_warn(s: str) -> str:
    """过期那条也画成 warn（红变橙，司机把过期车当成还有 30 天）。"""
    return s.replace("daysLeft < 0 -> MessageRisk.DANGER",
                     "daysLeft < 0 -> MessageRisk.WARN")


def _warn_band_disappears(s: str) -> str:
    """30 天以内那档不存在了（剩余天数没有分档，到期前也不变色）。"""
    return s.replace("daysLeft <= INSPECTION_WARN_DAYS -> MessageRisk.WARN",
                     "daysLeft <= INSPECTION_WARN_DAYS -> MessageRisk.INFO")


def _overdue_type_falls_out_of_family(s: str) -> str:
    """新类型漏出车辆族（竖条从 #00AAAE 掉回系统灰，与其它提醒混在一堆）。"""
    return s.replace("setOf(" + Q + "vehicle.inspection_due" + Q + ", " + Q + "vehicle.inspection_overdue" + Q + ")",
                     "setOf(" + Q + "vehicle.inspection_due" + Q + ")")


def _card_grows_second_algorithm(s: str) -> str:
    """卡片那一行长出第二套算法（同一台车，界面说的日子与后端提醒的不是同一天）。"""
    return s.replace("inspectionBadgeOf(v.nextInspectionDate, v.registrationDate, v.lastInspectionDate)",
                     "inspectionBadge(parseIsoDate(v.lastInspectionDate)?.plusYears(1), java.time.LocalDate.now())")


def _backend_date_ignored(s: str) -> str:
    """后端给的下次年检日期被丢掉不用（后端改了规则，界面还是老日子）。"""
    return s.replace("parseIsoDate(backendNextDue) ?: nextInspectionDue(registrationDate, lastInspectionDate)",
                     "nextInspectionDue(registrationDate, lastInspectionDate)")


def _dto_loses_registration_date(s: str) -> str:
    """上牌日期那一格消失（老库上填过的上牌日期从此读不回来）。"""
    return s.replace("    @SerialName(" + Q + "registration_date" + Q + ") val registrationDate: String? = null," + NL, "")


def _picker_replaced(s: str) -> str:
    """日期选择器被换成别的控件（手打日期，格式错一个字符就静默当没填）。"""
    return s.replace("DatePickerDialog(", "AlertDialog(")


def _near_low_overwrites_low_stock(s: str) -> str:
    """偏低盖掉低库存（已经到报警线了却只说「偏低」，红档消失）。"""
    return s.replace('lowStockAlert > 0 && stock <= lowStockAlert -> "低库存"',
                     'lowStockAlert > 0 && stock <= lowStockAlert -> "偏低"')


def _inventory_judges_itself(s: str) -> str:
    """库存页自己判偏低（判据变成两份，改一处另一处不动）。"""
    return s.replace("ProductStockBadge(s.stock, s.lowStockAlert)",
                     Q + "偏低" + Q + " to ProductStockBadge(s.stock, s.lowStockAlert)")


def _near_low_not_warn_color(s: str) -> str:
    """偏低不再用 warn 橙（与低库存的红、正常的青又混在一起）。"""
    return s.replace("private val NearLowInk = Color(MSG_TEXT_WARN)",
                     "private val NearLowInk = Color(0xFF008EAB)")


def _picker_allows_future(s: str) -> str:
    """未来日期又能选了（后端不做范围校验：填了不报错，只是这台车永远不提醒）。"""
    return s.replace("Boolean = inspectionDateSelectable(utcTimeMillis)", "Boolean = true")


def _self_drops_injection_lock(s: str) -> str:
    """本脚本自己摘掉注入锁（注入期间的结论从此不可信）。"""
    return s.replace(LOCK, "locked_x")


CASES = [
    ("① 编辑把没填的日期也发出去（清空老数据）", SCREEN, _edit_sends_untouched_date, "不许原样发"),
    ("② 新建没填也发一格空日期（清空）", SCREEN, _create_sends_blank_date, "新建走「填了才发」"),
    ("③ 过期那档也画成 warn（分档）", INSPECTION, _overdue_painted_warn, "三档顺序"),
    ("④ 30 天以内那档不存在（没有分档）", INSPECTION, _warn_band_disappears, "三档顺序"),
    ("⑤ 新类型漏出车辆族", GRADING, _overdue_type_falls_out_of_family, "车辆族集合"),
    ("⑥ 卡片里长出第二套算法", SCREEN, _card_grows_second_algorithm, "界面不许自己算下次年检"),
    ("⑦ 后端给的下次年检日期被丢掉", INSPECTION, _backend_date_ignored, "后端给了就用后端的"),
    ("⑧ 上牌日期那一格从 DTO 里消失", DTOS, _dto_loses_registration_date, "上牌日期在新增"),
    ("⑨ 日期选择器被换掉", SCREEN, _picker_replaced, "复用仓库既有的日期选择器"),
    ("⑩ 偏低盖掉低库存", CARDKIT, _near_low_overwrites_low_stock, "偏低那一档必须在低库存之后"),
    ("⑪ 库存页自己判偏低", INVENTORY, _inventory_judges_itself, "库存页不许自己写"),
    ("⑫ 偏低不再用 warn 橙", CARDKIT, _near_low_not_warn_color, "偏低的字色"),
    ("⑭ 未来日期又能选了（选择器没封顶今天）", SCREEN, _picker_allows_future, "选择层那条规则来自唯一实现"),
    ("⑬ 本脚本自己摘掉注入锁", SELF, _self_drops_injection_lock, "反向验证先上锁"),
]

# --------------------------------------------------------------- 脚手架


def read_src(rel):
    """读成 LF 规范化文本，并记住原本是不是 CRLF（写回时要还原）。"""
    path = rel if isinstance(rel, Path) else (ROOT / rel)
    data = path.read_bytes()
    crlf = b"\r\n" in data
    return path, data.decode("utf-8").replace("\r\n", "\n"), crlf


def write_src(path: Path, text: str, crlf: bool) -> None:
    out = text.replace("\n", "\r\n") if crlf else text
    path.write_bytes(out.encode("utf-8"))


def run_judge():
    r = subprocess.run(
        [sys.executable, str(JUDGE)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def hit(out: str, want: str) -> bool:
    """判据报红的那一行里必须出现关键词（只认 [FAIL] 行，防「别处碰巧提到」）。"""
    for ln in out.splitlines():
        if "[FAIL]" in ln and want in ln:
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
    print("✅ " + str(ok) + " 条注入都证明「年检算法只有一处、PATCH 没填不发、分档与族色都钉住」真的成立。")
    return 0


def main() -> int:
    print("反向验证 · 车辆年检两个日期字段（FEAT-0022 App 端）")
    print("")
    lock_reverse_verify()
    try:
        return run_all()
    finally:
        unlock_reverse_verify()


if __name__ == "__main__":
    raise SystemExit(main())
