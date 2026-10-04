# -*- coding: utf-8 -*-
"""反向验证：把「经营利润表」（FEAT-0011）逐条打断，看
`_tools/qa/_check_profit_report.py` 是否每次都报红。

用法（从仓库根）：python _tools/qa/_reverse_verify_profit_report.py

纪律（与兄弟脚本一致）：

* 先确认**源码完好时判据是全绿的**（前提不成立就直接失败，不做任何注入）；
* 每条注入只改一处、改完立刻跑判据、`finally` 里**逐字节还原**；
* 结束时核对「被碰过的文件与运行前逐字节一致」；
* 注入没生效（锚点变了 → 替换结果与原文件相同）算 **SKIP = 失败**，
  因为那意味着这条注入已经**证明不了任何事**，而不是「通过」；
* 全程拿着 `lock_reverse_verify`：注入期间别的检查看这份工作区会得到不可信的结论。

这 24 条对应的正是这张表最容易被改坏的地方 —— 它们有个共同点：**改完都能编译、接口也照样 200**，
只有把这些数拿去和营业纵览对一遍才会发现：

1-6   后端查询：毛利换了收入侧、营业利润少减一项、税金编出一个税率、期间费用丢了上界、
      偷偷重算别的钱、口径说明里抹掉折旧那条；
7-11  接口与导出：不再 pop 内部键、不再把窗口交给查询、导出那一支改名、
      导出里丢掉成本覆盖率、丢掉口径说明；
12-14 AI 读能力：toolmap 读动作改名、生成器的中文说明改名、DTO 的 snake_case 键被改成驼峰；
15-19 Android：页签 6 的导出 kind 改回 audit、第 7 格走错路由、ViewModel 把上界改回 6、
      页面自己减一遍、口径说明只画第一条；
20-21 用例与文档：后端单测少一条、地图文档里把那四个字抹掉；
22    本脚本自己摘掉注入锁；
23-24 真机实测补上的两条（2026-10-04，模拟器截图上先看见的）：
      利润构成里删掉「算不出成本的收入」那一行（链条又变成 7020.2 − 186 = 60.4，看着像算错）、
      口径说明里塞回 markdown 星号（手机上原样显示 **偏高**）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools/ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

JUDGE = ROOT / "_tools/qa/_check_profit_report.py"

QUERY = "backend/app/services/reports/profit_query.py"
API = "backend/app/api/v1/reports.py"
TOOLMAP = "docs/ai/ai_toolmap.json"
CN_GEN = "_tools/ai/_gen_ai_read_catalog.py"
DTOS = "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"
FINANCE = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportFinance.kt"
NAV = "android/app/src/main/java/com/tapmoay/sorders/ui/nav/NavGraph.kt"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenterViewModel.kt"
CENTER = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"
TEST_PY = "backend/tests/test_profit_report.py"
DOC_TESTING = "docs/PROJECT_MAP/05_TESTING.md"
SELF = "_tools/qa/_reverse_verify_profit_report.py"

#: 反引号与引号**不写进源码字面量**：这样整份脚本里不会出现「某种引号被迫转义」的角落。
BT = chr(96)
Q = chr(34)

#: 折旧那一条口径说明（删掉它时用得到 —— 它跨四行，只删一行仍有「折旧」二字）。
#: ⚠️ 第二期 FEAT-0012 把这条整条重写了（折旧已经算进来了），所以这四行必须与
#: `backend/app/services/reports/profit_query.py` 的 `_NOTES` 第 2 条**逐字一致** ——
#: 不一致的话这条注入就变成"没改到任何东西"，而 SKIP 在反向验证里算失败。
NOTE_DEP_1 = '    "车辆折旧已经算进来了（第二期落地）：月折旧额 = 购置价 ×（1 − 残值率）÷（使用年限 × 12），"'
NOTE_DEP_2 = '    "从购置日期起、按每个自然月的天数摊到这个窗口里（提足之后就是 0，不是没算）。"'
NOTE_DEP_3 = '    "没录购置价 / 购置日期 / 使用年限的车算不出折旧，它们的折旧没进这一格（营业利润偏高），"'
NOTE_DEP_4 = '    "单列在「折旧未覆盖」那一行里 —— 把缺的那一格补上，这一格就会跟着变。",'
NOTE_DEP = "\n".join((NOTE_DEP_1, NOTE_DEP_2, NOTE_DEP_3, NOTE_DEP_4)) + "\n"

#: 反验脚本自己的注入锁（连 `unlock_reverse_verify` 一起换掉：它含子串，
#: 只删一半的话判据那一条照样是绿的 —— 这一条是 CHG-0033 那轮踩过的坑）。
LOCK = "lock_reverse_verify"


# --------------------------------------------------------------- 24 条注入


def _gross_profit_uses_revenue_total(s: str) -> str:
    """毛利的分母换成「全部营业额」（把算不出成本的那些钱也当成本能算的钱）。"""
    return s.replace('    gross_profit = revenue_covered - cost_total',
                     '    gross_profit = revenue_total - cost_total')


def _operating_profit_drops_tax(s: str) -> str:
    """营业利润少减一项（税金那一格从此没人扣）。"""
    return s.replace('    operating_profit = gross_profit - delivery_cost - expense_total - depreciation_total - tax_total',
                     '    operating_profit = gross_profit - delivery_cost - expense_total - depreciation_total')


def _tax_invents_a_rate(s: str) -> str:
    """税金那一格去编一个税率出来（比空着危险得多）。"""
    return s.replace('    tax_total = _ZERO', '    tax_total = revenue_total * Decimal(' + Q + '0.13' + Q + ')')


def _expense_window_loses_upper_bound(s: str) -> str:
    """期间费用只剩左边界（这个窗口之后的开销也会被算进来）。"""
    return s.replace('Expense.exp_date >= start, Expense.exp_date <= end', 'Expense.exp_date >= start')


def _query_recomputes_money_itself(s: str) -> str:
    """在报表里**再算一遍**别的钱（毛利上栽过的那次就是这么来的）。"""
    return s.replace('    revenue_total = turnover[' + Q + 'total_amount' + Q + ']',
                     '    revenue_total = turnover[' + Q + 'total_amount' + Q + ']\n    _again = money_map(db, [])')


def _notes_drop_depreciation(s: str) -> str:
    """口径说明里抹掉「折旧还没算进来」那一条（于是营业利润被读成净利）。"""
    return s.replace(NOTE_DEP, '')


def _route_keeps_internal_window(s: str) -> str:
    """返回前不再 pop 掉 _window（内部键跟着 schema 一起出去，多一个键谁也不会报错）。"""
    return s.replace('    data.pop(' + Q + '_window' + Q + ', None)\n    return ProfitReportOut(**data)',
                     '    return ProfitReportOut(**data)')


def _route_drops_span(s: str) -> str:
    """接口不再把算好的窗口交给查询（于是「同一屏两个时间段」又回来了）。"""
    return s.replace('    data = build_profit(db, mode, anchor, span=span)',
                     '    data = build_profit(db, mode, anchor, span=(anchor, anchor))')


def _export_branch_renamed(s: str) -> str:
    """导出那一支改名（kind 正则还收 profit，点导出直接落进 else）。"""
    return s.replace('    elif kind == ' + Q + 'profit' + Q + ':',
                     '    elif kind == ' + Q + 'profitx' + Q + ':')


def _export_drops_coverage(s: str) -> str:
    """导出里丢掉成本覆盖率（只有数字没有覆盖率，就是让人误读毛利）。"""
    return s.replace(Q + '成本覆盖率' + Q + ',', Q + '覆盖率' + Q + ',')


def _export_drops_notes(s: str) -> str:
    """导出里丢掉口径说明（表被转发出去之后，没人说得出税金为什么是 0）。"""
    return s.replace('        append_text_row(ws, [' + Q + '口径说明' + Q + '])',
                     '        append_text_row(ws, [' + Q + '说明' + Q + '])')


def _toolmap_action_renamed(s: str) -> str:
    """AI 目录里那条读动作改名（模型于是找不到「这月赚了多少」）。"""
    return s.replace(Q + 'action' + Q + ': ' + Q + 'profit_report' + Q,
                     Q + 'action' + Q + ': ' + Q + 'profit_summary' + Q)


def _cn_desc_renamed(s: str) -> str:
    """生成器里的中文说明改名（这一条改名之后生成器会直接报错退出）。"""
    return s.replace(Q + 'reports.profit_report' + Q + ': (',
                     Q + 'reports.profit_xx' + Q + ': (')


def _dto_key_turns_camel(s: str) -> str:
    """DTO 的 snake_case 键被改成驼峰（字段静默变成默认值 0）。"""
    return s.replace('@SerialName(' + Q + 'operating_profit' + Q + ') val operatingProfit',
                     '@SerialName(' + Q + 'operatingProfit' + Q + ') val operatingProfit')


def _export_kind_back_to_audit(s: str) -> str:
    """页签 6 的导出 kind 改回 audit（第 7 页导出的是异常与审计那张表）。"""
    return s.replace('6 -> ' + Q + 'profit' + Q, '6 -> ' + Q + 'audit' + Q)


def _nav_wrong_route(s: str) -> str:
    """入口第 7 格走错页（点「经营利润」进的是异常与审计）。"""
    return s.replace('6 -> navController.navigate(Routes.REPORT_PROFIT)',
                     '6 -> navController.navigate(Routes.REPORT_EXCEPTION)')


def _vm_caps_at_five(s: str) -> str:
    """ViewModel 把页签上界改回 5（第 7 格进来会被压成第 6 页）。"""
    return s.replace('initialTab.coerceIn(0, 7)', 'initialTab.coerceIn(0, 6)')


def _tab_does_own_math(s: str) -> str:
    """页面自己减一遍（正是毛利栽过的那次：界面与接口各说各话）。"""
    return s.replace('StatBig(' + Q + '营业利润' + Q + ', money(data.operatingProfit), opColor)',
                     'StatBig(' + Q + '营业利润' + Q + ', money(data.grossProfit - data.deliveryCost), opColor)')


def _tab_notes_collapsed(s: str) -> str:
    """口径说明只画第一条（其余四条「为什么是 0」从此没人看得见）。"""
    return s.replace('data.notes.forEach', 'data.notes.take(1).forEach')


def _notes_wrapped_in_hint(s: str) -> str:
    """口径说明整块被包进 Hint 开关（提示一关，这一页就只剩一个营业利润数字）。"""
    return s.replace('                    data.notes.forEach { n ->',
                     '                    Hint(\n'
                     '                        ' + Q + '口径说明（这几件事今天算不进这张表）' + Q + ',\n'
                     '                        style = MaterialTheme.typography.bodySmall,\n'
                     '                        color = MaterialTheme.colorScheme.onSurfaceVariant,\n'
                     '                    )\n'
                     '                    data.notes.forEach { n ->')


def _tests_drop_one(s: str) -> str:
    """后端单测少一条（空窗口那条被改名，收集不到）。"""
    return s.replace('def test_空窗口全0且不炸(', 'def test2_空窗口全0且不炸(')


def _doc_drops_the_word(s: str) -> str:
    """地图文档里把那四个字抹掉（文档说 7 页，但没人说得出第 7 页是什么）。"""
    return s.replace('**经营利润**', '营业利润')


def _chain_loses_uncovered_row(s: str) -> str:
    """利润构成里删掉「− 算不出成本的收入」那一行（链条又变成 7020.2 − 186 = 60.4，看着像算错了）。"""
    return s.replace('                    StatRow(' + Q + '− 算不出成本的收入' + Q
                     + ', money(data.revenueUncovered), Color(0xFF8A8A8E))\n', '')


def _notes_gain_markdown(s: str) -> str:
    """口径说明里塞回 markdown 星号（手机上把 ** 原样印出来）。"""
    return s.replace('（营业利润偏高）', '（营业利润**偏高**）')


def _self_drops_lock(s: str) -> str:
    """本脚本自己摘掉注入锁（于是注入期间的结论都不可信）。"""
    return s.replace(LOCK, 'locked_x')


CASES = [
    ("① 毛利的分母换成全部营业额", QUERY, _gross_profit_uses_revenue_total, "商品毛利 = 参与毛利的收入"),
    ("② 营业利润少减一项", QUERY, _operating_profit_drops_tax, "营业利润 = 毛利"),
    ("③ 税金编出一个税率", QUERY, _tax_invents_a_rate, "税金恒为 0"),
    ("④ 期间费用丢了上界", QUERY, _expense_window_loses_upper_bound, "期间费用按业务发生日落地"),
    ("⑤ 查询里偷偷重算别的钱", QUERY, _query_recomputes_money_itself, "没有自己重算别的钱"),
    ("⑥ 口径说明抹掉折旧那条", QUERY, _notes_drop_depreciation, "折旧是怎么算进来的"),
    ("⑦ 路由不再 pop 内部键", API, _route_keeps_internal_window, "pop 掉 _window"),
    ("⑧ 接口不再把窗口交给查询", API, _route_drops_span, "取数走 build_profit"),
    ("⑨ 导出那一支改名", API, _export_branch_renamed, "导出里有 profit 这一支"),
    ("⑩ 导出丢掉成本覆盖率", API, _export_drops_coverage, "导出里带成本覆盖率"),
    ("⑪ 导出丢掉口径说明", API, _export_drops_notes, "导出里带口径说明"),
    ("⑫ AI 目录里那条读动作改名", TOOLMAP, _toolmap_action_renamed, "toolmap 里多了 reports.profit_report"),
    ("⑬ 生成器的中文说明改名", CN_GEN, _cn_desc_renamed, "生成器里有它的中文说明"),
    ("⑭ DTO 的键被改成驼峰", DTOS, _dto_key_turns_camel, "21 个 snake_case 键一个不少"),
    ("⑮ 页签 6 的导出 kind 改回 audit", FINANCE, _export_kind_back_to_audit, "页签 6 导出 profit"),
    ("⑯ 入口第 7 格走错页", NAV, _nav_wrong_route, "NavGraph 里点第 7 格走到利润页"),
    ("⑰ ViewModel 上界改回 6", VM, _vm_caps_at_five, "ViewModel 收下页签 0..7"),
    ("⑱ 页面自己减一遍", CENTER, _tab_does_own_math, "页面自己不做减法"),
    ("⑲ 口径说明只画第一条", CENTER, _tab_notes_collapsed, "口径说明逐条原样常显"),
    ("⑳ 后端单测少一条", TEST_PY, _tests_drop_one, "后端单测至少 9 条"),
    ("㉑ 地图文档里抹掉那四个字", DOC_TESTING, _doc_drops_the_word, "三份地图文档都跟着改"),
    ("㉒ 本脚本自己摘掉注入锁", SELF, _self_drops_lock, "反向验证脚本拿着注入锁"),
    ("㉓ 利润构成里删掉「算不出成本的收入」那一行", CENTER, _chain_loses_uncovered_row, "利润构成是一条能自己算通的链"),
    ("㉔ 口径说明里塞回 markdown 星号", QUERY, _notes_gain_markdown, "口径说明里不许出现 markdown 星号"),
    ("㉕ 口径说明整块被包进 Hint 开关", CENTER, _notes_wrapped_in_hint, "口径说明没有被包进 Hint 开关"),
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
    print("✅ " + str(ok) + " 条注入都证明「经营利润表只减不重算、不知道的如实说」真的被钉住了。")
    return 0


def main() -> int:
    print("反向验证 · 经营利润表（FEAT-0011）")
    print("")
    lock_reverse_verify()
    try:
        return run_all()
    finally:
        unlock_reverse_verify()


if __name__ == "__main__":
    raise SystemExit(main())
