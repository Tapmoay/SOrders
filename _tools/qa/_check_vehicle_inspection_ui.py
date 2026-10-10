#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""FEAT-0022 · 车辆年检两个日期字段（录入 / 显示 / 消息族 / 库存偏低）App 端红线。

R4-BOUNDARY-JUSTIFICATION:
  本判据管的是**边界**而不是"有没有写"：一台车的"下次年检是哪天"这条事实一旦
  出现第二个算法，界面显示的日期就会与后端发出的提醒不是同一天（差一天、差一年
  都不会报错，只会在某天早上少响/多响一次）；"编辑时把没填的日期也原样发出去"
  则会**清空老车本来填过的日期**（用户什么都没做，界面上也看不出来）。这两类错误
  都无声无息，所以必须由判据钉住：
    ① 年检算法（解析 / 加一年 / 剩余天数 / 三档 / 文案 / PATCH 差量）在整个 App 里
       **只有一处实现**（ui/dispatcher/VehicleInspection.kt）；
    ② 后端出参带了 next_inspection_date 时**必须用后端的**，本地只作兜底；
    ③ 编辑保存走 PATCH 差量：没动过的那一格**一个键都不发**（原样发 = 清空）；
    ④ 分档只有一条线（30 天）：大于 30 天常规 / 30 天以内 warn 橙 / 已过期 danger 红，
       颜色只能取消息中心那张表（emphasisColor），界面里不许出现色值字面量；
    ⑤ 新消息类型 vehicle.inspection_overdue 必须归**已有的**车辆族（竖条色 #00AAAE），
       且只改那一个映射集合、不改渲染逻辑；
    ⑥ 「偏低」是 warn 橙的第三档角标，**不许盖掉**"低库存"（到报警线）那一档。

判据分九层：
  1. 年检算法只有一处（唯一实现 + 阈值 + 三档顺序）
  2. 后端优先、本地兜底同一条规则
  3. 两个可空日期字段（DTO 三处）与 PATCH 差量语义
  4. 表单用既有日期控件（FormPickRow + DatePickerDialog），不新造一套
  5. 车辆卡片那一行（日期 + 还有几天）与分档颜色
  6. 消息族：新类型归车辆族，渲染逻辑未动
  7. 库存「偏低」第三档（warn 橙，不盖低库存）
  8. 单测条数与断言（至少 8 例，钉住上面那几件事）
  9. 判据自身与反向验证脚本
"""
import getpass
import re
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_pagination_wiring import strip_comments  # noqa: E402  （Kotlin 剥注释，复用不抄第二份）

ROOT = Path(__file__).resolve().parents[2]
JUDGE_NAME = "_check_vehicle_inspection_ui.py"
REVERSE_NAME = "_reverse_verify_vehicle_inspection_ui.py"

MAIN = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders"
INSPECTION = MAIN / "ui/dispatcher/VehicleInspection.kt"
SCREEN = MAIN / "ui/dispatcher/VehicleManageScreen.kt"
GRADING = MAIN / "ui/messages/MessageGrading.kt"
CARDKIT = MAIN / "ui/common/ProductCardKit.kt"
INVENTORY = MAIN / "ui/dispatcher/InventoryScreen.kt"
DTOS = MAIN / "data/remote/dto/Dtos.kt"
T_INSPECTION = TEST / "ui/dispatcher/VehicleInspectionTest.kt"
T_GRADING = TEST / "ui/messages/MessageGradingTest.kt"
T_CARDKIT = TEST / "ui/common/ProductCardKitTest.kt"
REVERSE = ROOT / "_tools/qa" / REVERSE_NAME
SELF = Path(__file__).resolve()

FLOOR = {
    INSPECTION: 3500,
    SCREEN: 40000,
    GRADING: 9000,
    CARDKIT: 5000,
    T_INSPECTION: 4000,
    T_GRADING: 9000,
    T_CARDKIT: 2500,
}


def read(p):
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8", errors="replace")


def kt(p):
    return strip_comments(read(p))


def count(hay, needle):
    return hay.count(needle)


def block(src, start, end=None, limit=6000):
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i + len(start)) if end else -1
    return src[i: j if j > 0 else i + limit]


def main_kt_files():
    """清单自己算：整个 App 主源码树（不手写文件名清单）。"""
    return sorted(MAIN.rglob("*.kt"))


class Checker:
    def __init__(self):
        self.n = 0
        self.fails = []

    def ok(self, cond, label):
        self.n += 1
        if not cond:
            self.fails.append(label)
        return bool(cond)

    def present(self, hay, needle, label):
        return self.ok(needle in hay, f"{label}（找不到：{needle[:70]}）")

    def absent(self, hay, needle, label):
        return self.ok(needle not in hay, f"{label}（不该出现：{needle[:70]}）")

    def need(self, n, lo, label):
        return self.ok(n >= lo, f"{label}（实际 {n}，要求至少 {lo}）")

    def equals(self, got, want, label):
        return self.ok(got == want, f"{label}（实际 {got!r}，要求 {want!r}）")

    def report(self, title):
        if self.fails:
            print(f"❌ {title}：失败 {len(self.fails)} / {self.n} 项")
            for f in self.fails:
                print(f"[FAIL] {f}")
            return 1
        print(f"✅ {title}：通过 {self.n} 项，失败 0 项")
        return 0


def check_unique(c, sources):
    """1. 年检算法只有一处"""
    print("== 1. 年检算法只有一处（唯一实现 + 阈值 + 三档顺序） ==")
    for p, floor in FLOOR.items():
        if p.exists():
            c.need(len(read(p)), floor, p.name + " 不是空壳")
    ins = kt(INSPECTION)
    scr = kt(SCREEN)
    for sig in (
        "internal fun parseIsoDate(",
        "internal fun nextInspectionDue(",
        "internal fun inspectionDaysLeft(",
        "internal fun inspectionRisk(",
        "internal fun inspectionText(",
        "internal fun inspectionBadge(",
        "internal fun inspectionLine(",
        "internal fun inspectionBadgeOf(",
        "internal fun isoDateOfMillis(",
        "internal fun isoDateToMillis(",
        "internal fun newDateOrNull(",
        "internal fun changedDateOrNull(",
    ):
        total = sum(count(s, sig) for s in sources.values())
        c.equals(total, 1, sig + f" 整个 App 只有一处（实际 {total} 处）")
    c.present(ins, "internal const val INSPECTION_WARN_DAYS = 30L", "30 天这条线是常量")
    c.ok(
        re.search(
            r"daysLeft < 0 -> MessageRisk\.DANGER\s+"
            r"daysLeft <= INSPECTION_WARN_DAYS -> MessageRisk\.WARN\s+"
            r"else -> MessageRisk\.INFO",
            ins,
        ),
        "三档顺序：已过期 danger / 30 天以内 warn / 其余 info",
    )
    c.present(ins, "DateTimeParseException", "坏日期串当没填（解析失败不抛）")
    c.equals(count(ins, "plusYears(1)"), 1, "加一年用 plusYears（不是加 365 天）")
    c.present(ins, "data class InspectionBadge(", "徽章类型是 public（VM 的公开属性暴露它）")
    c.absent(ins, "internal data class InspectionBadge", "不许回退成 internal（会编译不过）")
    c.absent(scr, "java.time", "界面不碰 java.time（日期格式只有一处）")
    c.absent(scr, "LocalDate", "界面不许自己造日期类型")
    c.absent(scr, "ChronoUnit", "界面不许自己算天数")
    c.absent(scr, "plusYears", "界面不许自己算下次年检")
    c.absent(scr, "nextInspectionDue(", "界面只经 inspectionBadgeOf，不直接调算法")
    c.present(scr, "import com.tapmoay.sorders.ui.messages.emphasisColor", "风险色走消息中心那张表")
    c.absent(scr, "0xFFE07B00", "界面不写 warn 色字面量")
    c.absent(scr, "0xFFD93025", "界面不写 danger 色字面量")


def check_backend_first(c, sources):
    """2. 后端优先、本地兜底同一条规则"""
    print("== 2. 后端优先、本地兜底同一条规则 ==")
    ins = kt(INSPECTION)
    scr = kt(SCREEN)
    dtos = kt(DTOS)
    c.present(
        ins,
        "parseIsoDate(backendNextDue) ?: nextInspectionDue(registrationDate, lastInspectionDate)",
        "后端给了就用后端的，没给才按同一条规则兜底",
    )
    c.present(ins, "base.plusYears(1)", "兜底规则 = (上次年检 or 上牌) + 1 年")
    c.present(
        scr,
        "inspectionBadgeOf(v.nextInspectionDate, v.registrationDate, v.lastInspectionDate)",
        "卡片把后端那一格传进去（第一位 = 后端算的）",
    )
    c.equals(count(dtos, '@SerialName("next_inspection_date")'), 1, "后端出参那一格有对应字段")
    c.present(dtos, "val nextInspectionDate: String? = null", "后端那一格可空（后端还没落地时取不到）")


def check_dates(c, sources):
    """3. 两个可空日期字段与 PATCH 差量语义"""
    print("== 3. 两个可空日期字段与 PATCH 差量语义 ==")
    dtos = kt(DTOS)
    scr = kt(SCREEN)
    ins = kt(INSPECTION)
    c.equals(
        count(dtos, '@SerialName("registration_date") val registrationDate: String? = null,'), 3,
        "上牌日期在新增/编辑/出参三处都是可空 String",
    )
    c.equals(
        count(dtos, '@SerialName("last_inspection_date") val lastInspectionDate: String? = null,'), 3,
        "上次年检日期在新增/编辑/出参三处都是可空 String",
    )
    c.present(ins, "val now = draft.trim()", "差量先把草稿规范化")
    c.present(ins, "val before = original?.trim().orEmpty()", "原值也规范化后再比")
    c.present(ins, "return if (now == before) null else now", "没改过 = null = 这个键不发")
    c.present(ins, "draft.trim().ifEmpty { null }", "新建：没填 = 不发这个键")
    c.present(scr, 'draftRegistrationDate = ""', "新增车辆时上牌日期是空的")
    c.present(scr, 'draftLastInspectionDate = ""', "新增车辆时上次年检日期是空的")
    c.present(scr, "draftRegistrationDate = v.registrationDate.orEmpty()", "编辑时原样带出上牌日期")
    c.present(scr, "draftLastInspectionDate = v.lastInspectionDate.orEmpty()", "编辑时原样带出上次年检日期")
    c.present(scr, "registrationDate = newDateOrNull(draftRegistrationDate),", "新建走「填了才发」")
    c.present(scr, "lastInspectionDate = newDateOrNull(draftLastInspectionDate),", "新建走「填了才发」")
    c.present(
        scr,
        "registrationDate = changedDateOrNull(before?.registrationDate, draftRegistrationDate),",
        "编辑走上牌日期的差量",
    )
    c.present(
        scr,
        "lastInspectionDate = changedDateOrNull(before?.lastInspectionDate, draftLastInspectionDate),",
        "编辑走上次年检日期的差量",
    )
    c.absent(scr, "registrationDate = draftRegistrationDate.trim()", "不许原样发（= 清空老车的日期）")
    c.absent(scr, "lastInspectionDate = draftLastInspectionDate.trim()", "不许原样发（= 清空老车的日期）")


def check_form(c, sources):
    """4. 表单用既有日期控件（不新造一套）"""
    print("== 4. 表单用既有日期控件（不新造一套） ==")
    scr = kt(SCREEN)
    c.absent(scr, "OutlinedTextField", "这一页不用裸输入框（表单行的既有版式）")
    c.need(count(scr, "FormPickRow("), 2, "两个日期格用 FormPickRow")
    c.present(scr, 'label = "上牌日期"', "表单里有「上牌日期」这一格")
    c.present(scr, 'label = "上次年检日期"', "表单里有「上次年检日期」这一格")
    c.need(count(scr, 'placeholder = "没填就不提醒"'), 2, "两格都写明「没填就不提醒」")
    c.present(scr, "DatePickerDialog(", "复用仓库既有的日期选择器")
    c.present(
        scr,
        "rememberDatePickerState(initialSelectedDateMillis = isoDateToMillis(current))",
        "已经填过的那天先停在选择器里",
    )
    c.present(scr, "DatePicker(state = dpState)", "标准 DatePicker")
    c.present(scr, 'Text("就用这天")', "确认键与「进货日期」同一文案")
    c.present(scr, "pickingRegistration", "上牌日期那一格有自己的开合状态")
    c.present(scr, "pickingInspection", "上次年检那一格有自己的开合状态")
    c.present(scr, "vm.draftInspection?.let { badge ->", "改到一半也先看见算出来的结果")


def check_card(c, sources):
    """5. 车辆卡片那一行与分档颜色"""
    print("== 5. 车辆卡片那一行与分档颜色 ==")
    scr = kt(SCREEN)
    ins = kt(INSPECTION)
    g = kt(GRADING)
    c.present(scr, "val inspection = inspectionBadgeOf(", "卡片那一行按同一处算")
    c.present(scr, "if (inspection != null) {", "算不出来时整行不出现（不写占位）")
    c.present(scr, "inspectionLine(inspection).orEmpty()", "卡片上就是那一行字")
    c.present(scr, "color = inspectionInk(inspection),", "颜色由分档决定")
    c.present(scr, "internal fun inspectionInk(badge: InspectionBadge): Color =", "分档到颜色只有这一处")
    c.present(
        scr,
        "emphasisColor(badge.risk)?.let { Color(it) } ?: MaterialTheme.colorScheme.onSurfaceVariant",
        "颜色只能来自 emphasisColor，算不出色调才退回常规灰",
    )
    c.present(ins, '"下次年检：${it.due} · ${it.text}"', "那一行 = 日期 + 还有几天")
    c.present(ins, '"已过期 ${-daysLeft} 天"', "过期说「已过期 N 天」")
    c.present(ins, '"今天到期"', "当天说「今天到期」")
    c.present(ins, '"还有 $daysLeft 天"', "没过期说「还有 N 天」")
    c.present(g, "const val MSG_TEXT_WARN = 0xFFE07B00L", "warn 橙的唯一出处（消息中心）")
    c.present(g, "const val MSG_TEXT_DANGER = 0xFFD93025L", "danger 红的唯一出处（消息中心）")


def check_family(c, sources):
    """6. 消息族：新类型归车辆族，渲染逻辑未动"""
    print("== 6. 消息族：新类型归车辆族，渲染逻辑未动 ==")
    g = kt(GRADING)
    all_main = "\n".join(sources.values())
    c.present(
        g,
        'private val VEHICLE_TYPES = setOf("vehicle.inspection_due", "vehicle.inspection_overdue")',
        "两个年检类型都进已有的车辆族集合（唯一改动点）",
    )
    c.present(g, "t in VEHICLE_TYPES -> MessageFamily.VEHICLE", "族映射那一条没改")
    c.equals(count(g, "const val MSG_COLOR_VEHICLE = 0xFF00AAAEL"), 1, "车辆族竖条色仍是 #00AAAE")
    c.present(g, 'VEHICLE("车辆提醒", MSG_COLOR_VEHICLE)', "族名与色仍然绑在一起")
    for sig in (
        "fun familyOf(type: String): MessageFamily",
        "fun riskOf(severity: String?): MessageRisk",
        "fun emphasisColor(risk: MessageRisk): Long?",
    ):
        c.equals(sum(count(s, sig) for s in sources.values()), 1, sig + " 仍然只有一处")
    c.ok(re.search(r"enum class MessageRisk\s*\{\s*INFO,\s*WARN,\s*DANGER\s*\}", g), "三档风险枚举没动")
    c.equals(count(all_main, '"vehicle.inspection_overdue"'), 1, "新类型字面量只出现在族映射那一处")
    c.present(all_main, "vehicle.inspection_due", "到期那条仍在")
    c.absent(g, '"vehicle.inspection_overdue" ->', "不许另开一条 when 分支去换色")


def check_near_low(c, sources):
    """7. 库存「偏低」第三档（warn 橙，不盖低库存）"""
    print("== 7. 库存「偏低」第三档（warn 橙，不盖低库存） ==")
    kit = kt(CARDKIT)
    inv = kt(INVENTORY)
    c.present(
        kit,
        'lowStockAlert > 0 && stock * 5 <= lowStockAlert * 6 -> "偏低"',
        "偏低 = 报警线的 1.2 倍以内（整数比，不引入浮点）",
    )
    badge = block(kit, "fun productStockBadgeText(", "\n}")
    c.present(badge, 'stock <= 0 -> "缺货"', "缺货那档仍在最前")
    c.present(badge, 'lowStockAlert > 0 && stock <= lowStockAlert -> "低库存"', "到报警线仍是低库存")
    c.ok(
        badge.find('"低库存"') >= 0 and badge.find('"偏低"') > badge.find('"低库存"'),
        "偏低那一档必须在低库存之后（不许盖掉报警线）",
    )
    c.present(kit, "private val NearLowInk = Color(MSG_TEXT_WARN)", "偏低的字色 = warn 橙（唯一出处）")
    c.present(kit, "import com.tapmoay.sorders.ui.messages.MSG_TEXT_WARN", "引的是消息中心那个常量")
    c.present(kit, "else -> NearLowInk to Color(0xFFFFEAD1)", "偏低有自己更浅的底色")
    c.present(kit, "stock <= 0 -> StockOutRed to Color(0xFFFFE6E6)", "缺货角标没改")
    c.present(kit, "lowStockAlert > 0 && stock <= lowStockAlert -> LowStockInk to Color(0xFFFFF3C0)", "低库存角标没改")
    c.present(kit, "stock <= 0 -> StockOutRed", "数字色：缺货那档没改")
    c.present(kit, "lowStockAlert > 0 && stock <= lowStockAlert -> StockLowYellow", "数字色：到线那档没改")
    c.present(kit, "else -> StockOkCyan", "数字色：正常那档没改")
    c.equals(count(kit, "fun productStockBadgeText("), 1, "角标文案只有一处实现")
    c.equals(count(inv, "ProductStockBadge("), 1, "库存页仍然只调那一个角标")
    c.equals(count(inv, "productStockBadgeText("), 0, "库存页不许自己判偏低")
    c.equals(count(inv, '"偏低"'), 0, "库存页不许自己写「偏低」两个字")


def check_tests(c, sources):
    """8. 单测条数与断言"""
    print("== 8. 单测条数与断言 ==")
    ti = kt(T_INSPECTION)
    tg = kt(T_GRADING)
    tk = kt(T_CARDKIT)
    c.need(count(ti, "@Test"), 8, "年检单测至少 8 例")
    c.present(ti, "class VehicleInspectionTest", "类名带 Vehicle（gradle --tests *Vehicle* 收得到）")
    c.present(tk, "class ProductCardKitTest", "角标单测仍在")
    for name in (
        "两格都空就不给提醒",
        "坏日期串当没填",
        "跨闰年是加一年不是加三百六十五天",
        "剩余天数分档",
        "还有几天的说法",
        "卡片那一行是整串",
        "后端给了下次年检日期就用后端的",
        "没动过的日期一个键都不发",
        "原来有值而用户清空了",
    ):
        c.present(ti, name, f"单测里有「{name}」这条")
    for risk in ("MessageRisk.INFO", "MessageRisk.WARN", "MessageRisk.DANGER"):
        c.present(ti, risk, f"三档都断言了 {risk}")
    c.present(ti, "assertNull(changedDateOrNull(", "断言：没改过就不发")
    c.present(ti, 'assertEquals("", changedDateOrNull(', "断言：清空就要发空串")
    c.present(ti, "assertNotEquals(base.plusDays(365)", "断言：不是加 365 天")
    c.present(ti, "MSG_TEXT_WARN", "断言：warn 色取自消息中心那张表")
    c.present(tg, 'familyOf("vehicle.inspection_overdue")', "消息单测认新类型")
    c.present(tg, 'assertEquals(0xFF00AAAEL, familyOf("vehicle.inspection_overdue").color)', "断言新类型竖条色 = #00AAAE")
    c.present(tg, 'assertEquals(MessageRisk.DANGER, riskOf("danger"))', "断言过期那条上 danger 档")
    c.present(tk, 'assertEquals("偏低", productStockBadgeText(stock = 12, lowStockAlert = 10))', "断言偏低那一档")
    c.present(tk, 'assertEquals("低库存", productStockBadgeText(stock = 10, lowStockAlert = 10))', "断言到线仍是低库存")
    c.present(tk, 'assertEquals(null, productStockBadgeText(stock = 13, lowStockAlert = 10))', "断言出线就不是偏低了")


def check_self(c, sources):
    """9. 判据自身与反向验证脚本"""
    print("== 9. 判据自身与反向验证脚本 ==")
    me = read(SELF)
    c.present(me, "R4-BOUNDARY-JUSTIFICATION:", "本判据写了边界理由")
    c.present(me, 'sys.stdout.reconfigure(encoding="utf-8", errors="replace")', "输出按 UTF-8")
    c.present(me, 'if "--list" in sys.argv:', "有 --list")
    c.ok(REVERSE.exists(), f"反向验证脚本在位：{REVERSE_NAME}")
    if REVERSE.exists():
        rev = read(REVERSE)
        c.present(rev, "lock_reverse_verify", "反向验证先上锁")
        c.present(rev, "unlock_reverse_verify", "反向验证收尾解锁")
        cases = re.findall(r'(?m)^    \("', block(rev, "CASES = [", "]\n"))
        c.need(len(cases), 5, "注入条数至少 5")
        for theme in ("清空", "warn", "车辆族", "分档", "第二套"):
            c.present(rev, theme, f"注入覆盖「{theme}」那一条")
        c.present(rev, "JUDGE", "反向验证跑的是本判据")


def main():
    sources = {p: kt(p) for p in main_kt_files()}
    layers = []
    for fn in (
        check_unique,
        check_backend_first,
        check_dates,
        check_form,
        check_card,
        check_family,
        check_near_low,
        check_tests,
        check_self,
    ):
        c = Checker()
        fn(c, sources)
        layers.append(c.report(fn.__doc__ or fn.__name__))
    bad = sum(layers)
    print()
    if bad:
        print(f"❌ {JUDGE_NAME}：{bad} 层有失败项（共 9 层）")
        return 1
    print(f"✅ {JUDGE_NAME}：9 层全部通过")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        for p in sorted(FLOOR):
            print(f"· {p.relative_to(ROOT)}")
        print(f"· 反向验证：_tools/qa/{REVERSE_NAME}")
        raise SystemExit(0)
    raise SystemExit(main())
