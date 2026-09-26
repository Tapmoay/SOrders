"""反向验证 `_tools/qa/_check_report_window.py`（红线：报表中心的时间控件与默认窗口）。

## 为什么必须做

这条判据守的事**坏起来一条报错都不会有**：
把那个"点一下就弹日历"的控件装回去、页面里再铺一条时间胶囊行、六个页签各取各的窗口、
自动挡自己抄一份阶梯、先取一次数再退档、「全部」悄悄换成更窄的窗口 ——
这些改法**都能编译、都能跑、界面都"看着正常"**，只有用户点下去才知道不对。

所以逐条**注入真缺陷**，每条都必须让判据报红；跑完逐字节还原并再验一次绿。

用法：python _tools/qa/_reverse_verify_report_window.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_report_window.py"

ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
FINANCE = ANDROID / "ui/dispatcher/ReportFinance.kt"
VM = ANDROID / "ui/dispatcher/ReportCenterViewModel.kt"
SCREEN = ANDROID / "ui/dispatcher/ReportCenter.kt"
#: ⚠️ 2026-09-25 第 21 轮：报表聚合**下沉到 service 层**之后，这一族里的注入目标分成了两处 ——
#: 聚合函数（`build_turnover`/`build_products`/`load_delivered`/`delivered_span_sql`/`_window`…）
#: 现在住在 `services/reports_service.py`，而**导出**（`export_report` 里的 `s, e = _span(...)`）仍在 API 层。
#: 所以下面分成两个常量：**注入要打在"那段原文真正住着的文件"上**，否则反向验证会静默 SKIP（锚点腐烂）。
REPORTS_SVC = ROOT / "backend/app/services/reports_service.py"
REPORTS_PY = ROOT / "backend/app/api/v1/reports.py"
ORDER_MODEL = ROOT / "backend/app/models/order.py"
BOOTSTRAP = ROOT / "backend/app/core/schema_bootstrap.py"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/dispatcher/ReportFinanceTest.kt"

CASES: list[tuple[str, Path, object]] = [
    # ---- ① 会弹日历的那类控件 ----
    (
        "又把「点一下就开系统日期选择器」的导航装回报表页",
        SCREEN,
        lambda s: s.replace(
            "                when (vm.tab) {",
            "                ReportTimeNav(mode = \"day\", anchor = \"2026-09-22\", periodText = \"\", onModeChange = {}, onAnchorChange = {})\n"
            "                when (vm.tab) {",
            1,
        ),
    ),
    (
        "页面里直接开 M3 的日期选择器（日期绕过了我们自己的弹层）",
        SCREEN,
        lambda s: s.replace(
            "    vm.resolveTarget?.let { t ->",
            "    if (showPresets) DatePickerDialog(onDismissRequest = {}) {}\n\n    vm.resolveTarget?.let { t ->",
            1,
        ),
    ),
    (
        "页面里又铺一条时间胶囊行（一个页面只能有一颗药丸）",
        SCREEN,
        lambda s: s.replace(
            "                when (vm.tab) {",
            "                DatePresetRow(selected = vm.preset, customFrom = null, customTo = null, onPick = {})\n"
            "                when (vm.tab) {",
            1,
        ),
    ),
    # ---- ② 顶栏药丸 + 共用弹层 ----
    (
        "药丸从顶栏拿掉（时间控件不在右上角了）",
        SCREEN,
        lambda s: s.replace(
            "DatePresetPill(label = vm.periodLabel, onClick = { showPresets = true })",
            'Text(vm.periodLabel)',
            1,
        ),
    ),
    (
        "档位弹层不再挂上（药丸点了没反应）",
        SCREEN,
        lambda s: s.replace("    DateFilterDialogs(\n", "    // DateFilterDialogs(\n", 1),
    ),
    (
        "挑档位绕过 VM 直接改状态",
        SCREEN,
        lambda s: s.replace("onPickPreset = { vm.applyPreset(it) },", "onPickPreset = { vm.preset = it },", 1),
    ),
    # ---- ③ 一个窗口口径 ----
    (
        "ReportFinance 里自己再算一遍区间（月份/周首那种算法）",
        FINANCE,
        lambda s: s.replace(
            "    fun windowOf(preset: String, customFrom: String?, customTo: String?, today: LocalDate): Pair<String, String> {",
            "    fun windowOf(preset: String, customFrom: String?, customTo: String?, today: LocalDate): Pair<String, String> {\n"
            "        val end = today.withDayOfMonth(today.lengthOfMonth())  // 自己算一遍",
            1,
        ),
    ),
    (
        "「全部」悄悄换成「近一年」那种更窄的窗口",
        FINANCE,
        lambda s: s.replace(
            "?: (ALL_FROM to today.toString())",
            "?: (today.minusDays(364).toString() to today.toString())",
            1,
        ),
    ),
    (
        "六个页签不再共用同一个 entry（dateRange 自己拼）",
        VM,
        lambda s: s.replace(
            "get() = ReportFinance.windowOf(preset, customFrom, customTo, LocalDate.now())",
            "get() = (customFrom ?: preset) to LocalDate.now().toString()",
            1,
        ),
    ),
    (
        "页面又自己拿 mode/anchor 那种第二套窗口状态",
        SCREEN,
        lambda s: s.replace(
            "                    TextButton(onClick = { vm.load() }) {",
            "                    vm.mode = \"month\"\n                    TextButton(onClick = { vm.load() }) {",
            1,
        ),
    ),
    (
        "营业纵览/商品经营又只按 mode 取数（区间没传下去）",
        VM,
        lambda s: s.replace("turnoverReport(ReportFinance.LEGACY_MODE, f, f, t)", "turnoverReport(ReportFinance.LEGACY_MODE, f)", 1),
    ),
    # ---- ④ 自动挡 ----
    (
        "先取一次数、再异步退档（用户点名的「闪两下」）",
        VM,
        lambda s: s.replace(
            "            windowSettled = true\n            load()",
            "            load()\n            windowSettled = true",
            1,
        ),
    ),
    (
        "探测换成另一个便宜接口（探到了进去还是空）",
        VM,
        lambda s: s.replace("repo.turnoverReport(", "repo.productReport(", 1),
    ),
    (
        "探测里的 CancellationException 被当成业务失败吞掉",
        VM,
        lambda s: s.replace("catch (e: CancellationException) {", "catch (e: Exception) {", 1),
    ),
    (
        "「异常与审计」也被拖进定窗口那一步（它没有时间控件）",
        VM,
        lambda s: s.replace("if (tab == 5) {", "if (false) {", 1),
    ),
    (
        "那道门被去掉（窗口没定下来就先画一版）",
        SCREEN,
        lambda s: s.replace("!vm.windowSettled", "false", 1),
    ),
    # ---- ⑤ 后端 ----
    (
        "半截窗口不再报错（猜另一头）",
        REPORTS_SVC,
        lambda s: s.replace("date_from 与 date_to 必须同时给", "date_from 随便给", 1),
    ),
    (
        "两个 build_* 不再共用同一段聚合（各写各的窗口）",
        REPORTS_SVC,
        lambda s: s.replace("    start, end = span if span else _window(mode, anchor)", "    start, end = _window(mode, anchor)", 1),
    ),
    (
        "曲线的粒度又只看 mode（整月区间会画成每小时一个点）",
        REPORTS_SVC,
        # ⚠️ 锚点必须带上下一行：文件里 `if start == end:` 还出现在 `_span_label` 里，
        #    只换第一处就会打在那一处上 —— 判据照样绿（第一次跑就是这么被抓出来的）。
        lambda s: s.replace(
            "    if start == end:\n        series = [\n",
            '    if mode == "day":\n        series = [\n',
            1,
        ),
    ),
    (
        "导出不走 `_span(`（文件名与内容又变成两段）",
        REPORTS_PY,
        lambda s: s.replace("s, e = _span(mode, d, date_from, date_to)", "s, e = _window(mode, d)", 1),
    ),
    # ---- ⑤b 窗口下推到 SQL（2026-09-23 容量实测补）----
    (
        "营业纵览又把全库已送达单读进内存（span 被摘掉 → 报表随历史线性变慢）",
        REPORTS_SVC,
        lambda s: s.replace("orders = load_delivered(db, span=(start, end))", "orders = load_delivered(db)", 1),
    ),
    (
        "商品经营那一路的 span 被摘掉（只留一处也会让那一页慢）",
        REPORTS_SVC,
        lambda s: s.replace("for o in load_delivered(db, span=(start, end)):", "for o in load_delivered(db):", 1),
    ),
    (
        "挂账汇总那条自己写的查询丢了窗口条件",
        REPORTS_SVC,
        lambda s: s.replace("                *delivered_span_sql(start, end),\n", "", 1),
    ),
    (
        "窗口翻译函数被改名/删掉（调用点就成了未定义名）",
        REPORTS_SVC,
        lambda s: s.replace("def delivered_span_sql(", "def _delivered_span_sql_x(", 1),
    ),
    # ---- ⑤c 窗口列必须有索引可用（2026-09-23 生产 EXPLAIN ANALYZE 实测补）----
    (
        "报表窗口索引被删掉（模型里不声明 → 新库也没这个索引，报表回到全表扫）",
        ORDER_MODEL,
        lambda s: s.replace(
            '        Index("ix_orders_status_delivered", "status", "delivered_at"),\n',
            "",
            1,
        ),
    ),
    (
        "索引列顺序写反（(delivered_at, status)：范围条件在前，status 那一段就用不上了）",
        ORDER_MODEL,
        lambda s: s.replace(
            'Index("ix_orders_status_delivered", "status", "delivered_at")',
            'Index("ix_orders_status_delivered", "delivered_at", "status")',
            1,
        ),
    ),
    (
        "老库（生产 MySQL）不再补建索引（新库有、线上没有 → 两套环境计划不同）",
        BOOTSTRAP,
        lambda s: s.replace(
            "                        conn.execute(text(\n"
            "                            \"ALTER TABLE orders ADD INDEX ix_orders_status_delivered (status, delivered_at)\"\n"
            "                        ))\n",
            "",
            1,
        ),
    ),
    (
        "窗口条件套上函数（`func.date(delivered_at)` 写法：索引当场失效，没人会报错）",
        REPORTS_SVC,
        lambda s: s.replace(
            "    return Order.delivered_at >= lo, Order.delivered_at < hi",
            "    return func.date(Order.delivered_at) >= lo, func.date(Order.delivered_at) < hi",
            1,
        ),
    ),
    # ---- ⑥ 单测不是摆设 ----
    (
        "「半截自定义落到最宽窗口」那条单测被删掉",
        TEST,
        lambda s: s.replace("fun `自定义区间用它自己那一段；半截自定义落到最宽的窗口（宁可多算不许少算）`()", "fun `x`()", 1),
    ),
]


def run(path: Path) -> int:
    p = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return p.returncode


def main() -> int:
    before = {str(p): p.read_text(encoding="utf-8") for _, p, _ in CASES}
    if run(CHECK) != 0:
        print("❌ 前提不成立：源码完好时这条判据就没过（先让 _check_report_window.py 变绿）")
        return 1
    print("✅ 前提：源码完好时判据是绿的")

    fails: list[str] = []
    for label, path, mutate in CASES:
        original_bytes = path.read_bytes()
        original = original_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
        # 第二轮 R2-05：报表源码搬进了 `services/reports/` —— 目标路径可能已经过期。
        # 判据读的是**并集**，注入器也照着并集找：哪一份真的被 mutate 改了，就打在哪一份上。
        # ⛔ 不逐条改 CASES 里的路径常量：那几条锚点跨多个新文件，改常量改不干净。
        if mutate(original) == original:
            import sys as _sys
            from pathlib import Path as _P
            _sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "ai"))
            from _airepo import reports_files as _rf
            for _c in _rf():
                _t = _c.read_text(encoding="utf-8")
                if mutate(_t) != _t:
                    # ⛔ 2026-09-26 修正（R3-07b 顺带抓到的真事故）：搬家时**字节快照必须一起搬**。
                    #    只换 path/original、不换 original_bytes 的后果：还原把**老文件**的字节写进了新文件
                    #    （实测把 `services/reports_service.py` 那份 1176B 的壳盖到 `reports/turnover_query.py` 上），
                    #    而「还原后核对」拿的还是同一份错字节 ⇒ 恒等、**静默通过**。
                    path = _c
                    original_bytes = _c.read_bytes()
                    original = original_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
                    break
        # ⛔ 注入前的**不变量**：快照必须确实属于要改的那个文件（否则还原会写错东西）
        if path.read_bytes() != original_bytes:
            fails.append(f"{label}：快照与目标不是同一个文件（搬家时漏换 original_bytes）")
            continue
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code = run(CHECK)
        finally:
            path.write_bytes(original_bytes)
        if code != 0:
            print(f"✅ 注入「{label}」→ 报红")
        else:
            fails.append(f"{label}：注入之后没有报红 —— 这条判据是空转的")

    for k, v in before.items():
        if Path(k).read_text(encoding="utf-8") != v:
            fails.append(f"收尾没还原：{k}")
    if run(CHECK) != 0:
        fails.append("还原之后判据仍然红（有文件没被改回来）")

    if fails:
        print("\n❌ 反向验证没通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ {len(CASES)}/{len(CASES)} 种破坏方式全部被抓到，且源码已还原。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
