"""反向验证：把「收支」页那条红线逐条弄坏，看它**真的会红**。

## 为什么这块必须反向验证
这一页坏掉的方式**全部不报错、不崩、界面上也看不出来**：
· 客户端自己按 `biz_type` 分类求和 → 页面上就是几个数，只是**少了**（实测 62% 那一类）；
· 方向的大写 `IN` 没归一 → 那笔钱从收入里消失、跑到支出里，两边都不报错；
· 中文名抄了第二份 → 认不出的类型显示成原始码，看起来只像"数据脏了"；
· 「开销管理」的入口/路由/NavGraph 少一样 → **用户点不进去**，而这一页完全正常；
· 明细页自己又挑一次时间 → 明细加起来与刚才那一路的合计对不上，用户以为账错了；
· 新读端点没进 AI 读目录 → 用户问"钱都花哪了"，模型只会回一句"我查不了"。

⚠️ 这一份**特别重要的一条**：本文件里的第 3 条注入（`dir_col` 不再归一）打的是
**「判据在空转」**——写检查时那条断言数的其实是 `/summary` 里已有的两处 `func.lower`,
改成 `scoped.c.direction` 它照样绿。注入跑出来 MISS 才发现，判据已经改成只看新 handler 的函数体。

用法：python _tools/qa/_reverse_verify_ledger_cash.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_ledger_cash.py"

ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
API = ROOT / "backend/app/api/v1/cash_flows.py"
TEST = ROOT / "backend/tests/test_cash_flow_breakdown.py"
SCREEN = ANDROID / "ui/dispatcher/LedgerCashScreen.kt"
DETAIL = ANDROID / "ui/dispatcher/LedgerCashDetailScreen.kt"
ROUTES = ANDROID / "ui/nav/Routes.kt"
MODULES = ANDROID / "ui/nav/Modules.kt"
CATALOG = ANDROID / "ai/AiReadCatalog.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "分项端点不再复用 _scoped_stmt（自己写一套筛选 = 与 /summary 走散）",
        API,
        "scoped = _scoped_stmt(current, None, None, None, None, date_from, date_to).subquery()",
        "scoped = select(CashFlow).subquery()",
        "筛选复用 _scoped_stmt",
    ),
    (
        "求和搬回 Python（不再在 SQL 侧算）",
        API,
        "func.coalesce(func.sum(scoped.c.amount), 0)",
        "scoped.c.amount",
        "求和是 SQL 侧",
    ),
    (
        "分组键不再归一小写（老数据里那个大写 IN 会自成一组、还会被判成支出）",
        API,
        "    dir_col = func.lower(scoped.c.direction)",
        "    dir_col = scoped.c.direction",
        "分组键把 direction 归一小写",
    ),
    (
        "把 in/out 之外的脏方向也算成收入（`OUT` 会被端到收入那一侧）",
        API,
        '(income if str(direction or "").lower() == "in" else expense).append(item)',
        '(income if str(direction or "").lower() in ("in", "out") else expense).append(item)',
        "只有 in 算收入",
    ),
    (
        # ⚠️ 2026-09-25 §9 第二域：原来是往**函数体**里注入 `if False:`。
        #    授权搬到签名上之后，体内那段文字已经不在了 —— 注入点必须跟着搬到签名，
        #    否则这条反向验证会变成恒 SKIP（锚点失效），而 SKIP 会被记成 MISS。
        "守门从**签名**上摘掉（换回 CurrentUser —— 体内那段文字早就搬走了，只剩签名能证明它守了门）",
        API,
        '@router.get("/breakdown")\ndef cash_flow_breakdown(\n    current: DispatcherUser,',
        '@router.get("/breakdown")\ndef cash_flow_breakdown(\n    current: CurrentUser,',
        "守门在**签名**上",
    ),
    (
        "没标注的流水被并进「其他」（账上出现没见过的东西被藏起来）",
        API,
        '"biz_type": str(biz_type or ""),',
        '"biz_type": str(biz_type or "EXPENSE_OTHER"),',
        "不并进「其他」",
    ),
    (
        "回归测试被削弱（分项之和 == 汇总 → 只要不是负数就行）",
        TEST,
        'Decimal(b["income_total"]) == Decimal(s["income"])',
        'float(b["income_total"]) >= 0',
        "分项之和 == 汇总",
    ),
    (
        "总览页自己按 biz_type 分类求和（少算，而且与汇总对不上）",
        SCREEN,
        "    fun load() {",
        "    fun load() {\n        val _total = data?.income?.sumOf { it.count } ?: 0",
        "不许对分项自己求和",
    ),
    (
        "总览页自己再写一份 biz_type → 中文 词表（会与 ReportFinance 走散）",
        SCREEN,
        "            rows.forEachIndexed { i, r ->",
        '            val _cn = mapOf("RECEIPT_CASH" to "收款")\n            rows.forEachIndexed { i, r ->',
        "没有自己再写一份",
    ),
    (
        "收入/支出各写一张卡（抄成两份，两边慢慢长得不一样）",
        SCREEN,
        "private fun CashGroupCard(",
        "private fun CashGroupCardX(",
        "共用一份实现",
    ),
    (
        "支出那张卡底部的「开销管理」入口不接回调（画着好看，点了没反应）",
        SCREEN,
        "                            footer = {",
        "                            footer = null.let { {",
        "真的接了回调",
    ),
    (
        "支出那一组改用硬编码颜色（主题里那份语义色成了摆设）",
        SCREEN,
        "                            accent = Color(CashOut),",
        "                            accent = Color(0xFF1565C0L),",
        "第二份硬编码",
    ),
    (
        "明细页自己又挑一次时间（明细与刚才那一路的合计对不上）",
        DETAIL,
        "    val isIncome = ReportFinance.isIncome(vm.direction)",
        '    val isIncome = ReportFinance.isIncome(vm.direction)\n'
        '    DatePresetPill(label = "今天", onClick = {})',
        "自己再挑一次时间",
    ),
    (
        "「开销管理」的路由常量被删（用户再也进不去那一页）",
        ROUTES,
        'const val DISPATCH_EXPENSES = "dispatcher/expenses"',
        'const val DISPATCH_EXPENSES_GONE = "dispatcher/expenses"',
        "路由常量还在",
    ),
    (
        "「开销管理」又被加回入口页当第 7 格（用户点名的「整合」被回退）",
        MODULES,
        'ModuleEntry("收支", Routes.DISPATCH_CASH, Icons.Default.SwapHoriz, color = 0xFF1565C0L),',
        'ModuleEntry("收支", Routes.DISPATCH_CASH, Icons.Default.SwapHoriz, color = 0xFF1565C0L),\n'
        '        ModuleEntry("开销管理", Routes.DISPATCH_EXPENSES, Icons.Default.Receipt, color = 0xFF1565C0L),',
        "没有第二个「开销管理」格",
    ),
    (
        "新读端点没进 AI 读目录（用户问「钱都花哪了」，模型只会说查不了）",
        CATALOG,
        'ReadAction("cash_flows.cash_flow_breakdown"',
        'ReadAction("cash_flows.cash_flow_breakdown_missing"',
        "读目录里有它",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str) -> tuple[bool, str]:
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    return hit, f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            hit, detail = verdict(expect)
        finally:
            write_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
