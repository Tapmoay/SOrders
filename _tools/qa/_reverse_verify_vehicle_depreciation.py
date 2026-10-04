# -*- coding: utf-8 -*-
"""反向验证：把「车辆台账与折旧」（FEAT-0012 第二期）逐条打断，看
`_tools/qa/_check_vehicle_depreciation.py` 是否每次都报红。

用法（从仓库根）：python _tools/qa/_reverse_verify_vehicle_depreciation.py

纪律（与兄弟脚本一致）：

* 先确认**源码完好时判据是全绿的**（前提不成立就直接失败，不做任何注入）；
* 每条注入只改一处、改完立刻跑判据、`finally` 里**逐字节还原**；
* 结束时核对「被碰过的文件与运行前逐字节一致」；
* 注入没生效（锚点变了 → 替换结果与原文件相同）算 **SKIP = 失败**，
  因为那意味着这条注入已经**证明不了任何事**，而不是「通过」；
* 全程拿着 `lock_reverse_verify`：注入期间别的检查看这份工作区会得到不可信的结论。

这 21 条对应的正是这一期最容易被改坏的地方 —— 它们有个共同点：**改完都能编译、接口也照样 200**，
只有把数拿去手工算一遍、或者拿两个窗口对一遍才会发现：

1-6    折旧口径：月额公式去掉残值率、缺格按 0 算、按整月摊、开始碰库、留空不当 0%、
       未覆盖原因换了说法；
7-8    列定义：迁移少一列、自愈副本少一列（老库与新库从此长得不一样）；
9-10   利润表：折旧折进期间费用、口径说明塞回「还没算」；
11-14  车辆成本表与导出：逐车恒等式少一笔、把收入也拆进来、导出 kind 白名单漏掉它、端点改名；
15-18  Android：ViewModel 上界改回 6、入口第 8 格去掉、利润链条那一行删掉、四格少一格话术；
19-20  用例与界面文字：后端单测少一条、界面文案里塞回 markdown 星号；
21     本脚本自己摘掉注入锁（注入期间的结论从此不可信）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools/ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

JUDGE = ROOT / "_tools/qa/_check_vehicle_depreciation.py"

DEP = "backend/app/services/vehicle_depreciation.py"
MIG = "backend/app/migrations/018_vehicle_depreciation.py"
BOOT = "backend/app/core/schema_bootstrap.py"
QUERY = "backend/app/services/reports/profit_query.py"
COST = "backend/app/services/reports/vehicle_cost_query.py"
API_R = "backend/app/api/v1/reports.py"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenterViewModel.kt"
HOME = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportHome.kt"
CENTER = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"
VSCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleManageScreen.kt"
TEST_PY = "backend/tests/test_vehicle_depreciation.py"
SELF = "_tools/qa/_reverse_verify_vehicle_depreciation.py"

#: 反引号与引号**不写进源码字面量**：这样整份脚本里不会出现「某种引号被迫转义」的角落。
BT = chr(96)
Q = chr(34)
NL = chr(10)

#: 反验脚本自己的注入锁（连 `unlock_reverse_verify` 一起换掉：它含子串，
#: 只删一半的话判据那一条照样是绿的）。
LOCK = "lock_reverse_verify"


# --------------------------------------------------------------- 20 条注入


def _monthly_forgets_residual_rate(s: str) -> str:
    """月额公式去掉残值率（每台车每月都多提一点点，一年后是一笔钱）。"""
    return s.replace("price * (Decimal(1) - residual_rate_of(residual_rate)) / (years * 12)",
                     "price / (years * 12)")


def _missing_cells_become_zero(s: str) -> str:
    """缺购置信息的车按 0 算（那台车的折旧从此在报表里消失）。"""
    return s.replace("    if price is None or years is None or price <= PRICE_MIN or years <= 0:" + NL +
                     "        return None",
                     "    if price is None or years is None or price <= PRICE_MIN or years <= 0:" + NL +
                     "        return Decimal(" + Q + "0.00" + Q + ")")


def _window_uses_whole_month(s: str) -> str:
    """窗口内按整月一刀切（月中买的车多提半个月，跨窗口对不上）。"""
    return s.replace("total += monthly * Decimal(span) / Decimal(days)",
                     "total += monthly")


def _service_starts_touching_db(s: str) -> str:
    """折旧服务开始碰库（从此它不再是纯函数，改口径要回填历史行）。"""
    return s.replace("def _money(value: Decimal) -> Decimal:",
                     "def _money(value: Decimal, session: Session | None = None) -> Decimal:")


def _blank_rate_is_not_zero(s: str) -> str:
    """残值率留空不再当 0%（凭空按 10% 计提）。"""
    return s.replace("    if rate is None:" + NL + "        return RATE_MIN",
                     "    if rate is None:" + NL + "        return Decimal(" + Q + "0.1" + Q + ")")


def _uncovered_reason_renamed(s: str) -> str:
    """未覆盖原因换了说法（界面上从此说不清缺哪一格）。"""
    return s.replace("MISSING_PRICE = " + Q + "没录购置价" + Q,
                     "MISSING_PRICE = " + Q + "缺购置价" + Q)


def _migration_loses_a_column(s: str) -> str:
    """迁移少一列（老库升上来没有 residual_rate，模型却按它有）。"""
    return s.replace("    " + Q + "residual_rate" + Q + ": " + Q + "residual_rate DECIMAL(5,4) NULL" + Q + "," + NL, "")


def _bootstrap_loses_a_column(s: str) -> str:
    """运行时自愈少一列（没跑过迁移的库从此长得和跑过的不一样）。"""
    return s.replace("            (" + Q + "residual_rate" + Q + ", " + Q +
                     "ALTER TABLE vehicles ADD COLUMN residual_rate DECIMAL(5,4) NULL" + Q + ")," + NL, "")


def _depreciation_folded_into_expenses(s: str) -> str:
    """折旧折进期间费用（恒等式还成立，但「− 车辆折旧」这一行没了）。"""
    return s.replace("operating_profit = gross_profit - delivery_cost - expense_total - depreciation_total - tax_total",
                     "operating_profit = gross_profit - delivery_cost - (expense_total + depreciation_total) - tax_total")


def _notes_say_not_counted_yet(s: str) -> str:
    """口径说明塞回「折旧还没算」（老板会把营业利润读成净利）。"""
    return s.replace(Q + "车辆折旧已经算进来了（第二期落地）",
                     Q + "折旧没有算进去：车辆台账里没有购置价与折旧字段，")


def _per_vehicle_total_drops_depreciation(s: str) -> str:
    """逐车成本少加折旧那一笔（合计与明细从此刻不上）。"""
    return s.replace(Q + "total_cost" + Q + ": depreciation + expense_total + delivery_cost,",
                     Q + "total_cost" + Q + ": expense_total + delivery_cost,")


def _cost_table_splits_revenue(s: str) -> str:
    """车辆成本表里开始拆收入（订单上没有「哪台车拉的」这个事实，硬摊就是编比例）。"""
    return s.replace("_ZERO = Decimal(" + Q + "0.00" + Q + ")",
                     "_ZERO = Decimal(" + Q + "0.00" + Q + ")" + NL + "_REVENUE_KEY = " + Q + "revenue" + Q)


def _export_kind_regex_drops_it(s: str) -> str:
    """导出 kind 白名单漏掉 vehicle-cost（点导出直接落进 else）。"""
    return s.replace("|vehicle-cost", "")


def _route_renamed(s: str) -> str:
    """端点改名（Android 那边 404，而判据只看「有没有这一支」）。"""
    return s.replace("@router.get(" + Q + "/vehicle-cost" + Q + ", response_model=VehicleCostReportOut)",
                     "@router.get(" + Q + "/vehicle-costs" + Q + ", response_model=VehicleCostReportOut)")


def _vm_caps_at_six(s: str) -> str:
    """ViewModel 把页签上界改回 6（第 8 格进来会被压成第 7 页）。"""
    return s.replace("initialTab.coerceIn(0, 9)", "initialTab.coerceIn(0, 6)")


def _home_drops_the_card(s: str) -> str:
    """入口第 8 格去掉（报表中心那一页从此进不去）。"""
    return s.replace("        EntryCard(" + Q + "7" + Q + ", " + Q + "车辆成本" + Q +
                     ", Icons.Default.DirectionsCar, Color(0xFF546E7A))," + NL, "")


def _chain_loses_depreciation_row(s: str) -> str:
    """利润构成里删掉「− 车辆折旧」那一行（上一步减完不等于下一步）。"""
    return s.replace("                    StatRow(" + Q + "− 车辆折旧" + Q +
                     ", money(data.depreciationTotal), Color(0xFF8A8A8E))" + NL, "")


def _screen_renames_rate_field(s: str) -> str:
    """车辆管理少一格话术（残值率那一行变成「残值」）。"""
    return s.replace("label = " + Q + "残值率" + Q + ",", "label = " + Q + "残值" + Q + ",")


def _tests_drop_one(s: str) -> str:
    """后端单测少一条（月额公式那条被改名，收集不到）。"""
    return s.replace("def test_monthly_depreciation_formula(", "def t2_monthly_depreciation_formula(")


def _screen_gains_markdown(s: str) -> str:
    """界面文案里塞回 markdown 星号（手机上原样印出来）。"""
    return s.replace(Q + "每月折旧 ¥" + Q, Q + "每月折旧 **¥**" + Q)


CASES = [
    ("① 月额公式去掉残值率", DEP, _monthly_forgets_residual_rate, "月折旧额 = 购置价"),
    ("② 缺格按 0 算", DEP, _missing_cells_become_zero, "缺格返回 None"),
    ("③ 窗口内按整月摊", DEP, _window_uses_whole_month, "窗口内折旧按自然月的天数摊"),
    ("④ 折旧服务开始碰库", DEP, _service_starts_touching_db, "折旧服务是纯函数"),
    ("⑤ 留空不再当 0%", DEP, _blank_rate_is_not_zero, "残值率留空 = 0%"),
    ("⑥ 未覆盖原因换说法", DEP, _uncovered_reason_renamed, "未覆盖原因三条常量"),
    ("⑦ 迁移少一列", MIG, _migration_loses_a_column, "迁移 018 声明四列"),
    ("⑧ 自愈副本少一列", BOOT, _bootstrap_loses_a_column, "自愈副本"),
    ("⑨ 折旧折进期间费用", QUERY, _depreciation_folded_into_expenses, "营业利润是五级相减"),
    ("⑩ 口径说明塞回「还没算」", QUERY, _notes_say_not_counted_yet, "口径说明里不再说"),
    ("⑪ 逐车成本少加折旧", COST, _per_vehicle_total_drops_depreciation, "逐车成本 = 折旧"),
    ("⑫ 成本表开始拆收入", COST, _cost_table_splits_revenue, "这张表只算成本"),
    ("⑬ 导出 kind 白名单漏掉它", API_R, _export_kind_regex_drops_it, "导出 kind 正则收下了 vehicle-cost"),
    ("⑭ 端点改名", API_R, _route_renamed, "端点 /reports/vehicle-cost 在"),
    ("⑮ ViewModel 上界改回 6", VM, _vm_caps_at_six, "ViewModel 收下页签 0..8"),
    ("⑯ 入口第 8 格去掉", HOME, _home_drops_the_card, "入口页第 8 格是车辆成本"),
    ("⑰ 利润链条删掉折旧那一行", CENTER, _chain_loses_depreciation_row, "利润构成链条里有"),
    ("⑱ 车辆管理少一格话术", VSCREEN, _screen_renames_rate_field, "车辆管理页四格"),
    ("⑲ 后端单测少一条", TEST_PY, _tests_drop_one, "后端折旧单测至少 28 条"),
    ("⑳ 界面文案塞回 markdown 星号", VSCREEN, _screen_gains_markdown, "界面文字里不许出现 markdown 星号"),
    ("㉑ 本脚本自己摘掉注入锁", SELF, lambda s: s.replace(LOCK, "locked_x"), "配套反向验证拿着注入锁"),
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
    print("✅ " + str(ok) + " 条注入都证明「折旧口径唯一、缺格单列、三处列定义一致」真的被钉住了。")
    return 0


def main() -> int:
    print("反向验证 · 车辆台账与折旧（FEAT-0012 第二期）")
    print("")
    lock_reverse_verify()
    try:
        return run_all()
    finally:
        unlock_reverse_verify()


if __name__ == "__main__":
    raise SystemExit(main())

