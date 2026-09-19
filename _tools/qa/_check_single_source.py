"""红线：**"同一个数只有一处算法"**（时间口径 + 金额单元格 + 指标实现）。

## 为什么要有这一条（2026-09-19 第十三轮审计的教训）
这一轮抓到的三条缺陷**同一个形状**：同一个指标在另一处被**重新实现了一遍**，
于是两处慢慢走散，而且**两边都不报错**：

| 指标 | 走散后的样子 |
|---|---|
| 商品毛利 | Android 用 `total_amount − cost_total`，后端用 `cost_covered_amount − cost_total` → 界面 72,177.75 vs 正确 10,789.00（差 6.7 倍） |
| 司机绩效（导出 vs 页面） | 导出自己算准时率/平均送达分钟/待结运费 → 平均分钟恒空、准时率导出空而页面 54.5%、工资制司机印 0 |
| 挂账未收 | 两处一个按 `paid=False`、一个多一条 `payment_method == 'arrears'` → 63,006.00 vs 62,920.50 |
| 时间口径 | `delivered_at` 存 UTC，一处按当地日分桶、另一处直接 `.date()`/`.hour` → 当地凌晨的单算进前一天、凌晨标成下午 |

"逐条去修"治不了这个形状——**要有一条机器判据盯着"这类算法只许有一处"**。所以：

1. **后端不许自己算日期**：凡是让 `Order`/`CashFlow`/`Notification` 的时间参与"哪一天/哪一月/几点"的判断，
   必须走 `app/core/business_time.py`。判据：`backend/app/**` 里不许出现
   `.delivered_at.date()`、`.delivered_at.hour`、`.cancelled_at.date()`、`func.date(`（有理由的写进白名单）。
2. **导出的金额单元格必须过 `_money()`**（写数字、两位小数）：
   判据：`reports.py` 里每个 `ws.append(...)` 中，带金额字样的键必须包在 `_money(` 里。
3. **指标实现只许一处**：`driver_performance`（准时率/平均送达/待结）只能出现在 `stats_service.py`；
   `reports.py` 只许调它。判据：`reports.py` 里不许出现 `ot_valid`、`freight_owed`、`pay_for_order(...).total`
   这类"自己再算一遍"的痕迹。

清单全部**从源码算出来**（白名单也写在这里，且每条要带理由），扫到的数量低于下限就报错（防空转）。

用法：python _tools/qa/_check_single_source.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/app"

#: 允许"自己算日期"的地方 —— 键是 `相对路径:行号锚点` 不行（会漂），所以按**文件名 + 理由**放行，
#: 且理由必须写清"为什么这里不能用 business_time"。
DATE_ALLOW = {
    "core/business_time.py": "它就是那一处实现",
    "services/data_retention.py": "保留策略比的是『多少天以前』，用库内时间差，不涉及『当地哪一天』",
    "services/image_archive.py": "同上：按文件 mtime 算天数",
    "api/v1/auth.py": "登录失败记录的时间戳，只用于限流窗口（相对时间）",
    "services/login_guard.py": "同上",
    "services/ledger_export.py": "导出行的 entry_date 直接来自账本列（已经是业务日）",
}

#: 金额列名（导出单元格里出现这些键时必须过 `_money()`）
MONEY_HINT = re.compile(
    r"(amount|total|fee|freight|profit|owed|income|expense|collected|arrears|damage_amount|cost)",
    re.I,
)
DATE_PATTERNS = [
    r"\.delivered_at\.date\(\)",
    r"\.delivered_at\.hour",
    r"\.cancelled_at\.date\(\)",
    r"\.created_at\.date\(\)",
    r"func\.date\(",
]

#: 「现在」的裸写法 —— 一律不许（R14-9，2026-09-19 审计）。
#:
#: ⛔ `datetime.now()`（不带时区参数）是**进程本地时间**，`date.today()` / `datetime.utcnow()`
#:    同理各有各的坑；而库里的时间列按本项目的口径存的是 **UTC**。两者相减是固定的时区偏差，
#:    而且完全静默。第十四轮就是这样：`GET /notifications?days=1` 少给 8 小时 / 1508 条；
#:    六张表的 `deleted_at` 写的是本地时间，30 天隔离期因此早 8 小时到期。
#:    正确写法只有两个入口：
#:      · 要比库里的时间列（naive UTC）→ `business_time.utc_now_naive()`
#:      · 要"业务当地的今天"           → `business_time.business_today()` / `business_date()`
#: 带时区参数的 `datetime.now(timezone.utc)`（明确说了是 UTC）不在禁止之列。
NOW_PATTERNS = [
    r"datetime\.now\(\s*\)",
    r"datetime\.utcnow\(",
    r"date\.today\(\s*\)",
]

#: 允许裸写"现在"的地方 → 理由（同样按文件名 + 理由，且上限收紧）
NOW_ALLOW: dict[str, str] = {}


def rel(p: Path) -> str:
    return str(p.relative_to(BACKEND)).replace("\\", "/")


def code_only(src: str) -> str:
    """把注释与字符串/文档字符串换成等长空格（保留行号与列位置）。

    为什么必须做：`business_time.py` 的模块文档里就写着 `.delivered_at.date()` 这个**反例**
    （"原来就是这么写的、所以会错"）——不剥掉的话，判据会被自己的文档骗红，
    而"改文档来迎合判据"比红更糟。
    """
    out = list(src)
    n = len(src)
    i = 0
    while i < n:
        ch = src[i]
        if ch == "#":
            j = src.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if src.startswith('"""', i) or src.startswith("'''", i):
            quote = src[i : i + 3]
            j = src.find(quote, i + 3)
            j = n if j < 0 else j + 3
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def main() -> int:
    fails: list[str] = []
    py = sorted(BACKEND.rglob("*.py"))
    if len(py) < 50:
        print(f"❌ 只扫到 {len(py)} 个后端文件——判据在空转，停。")
        return 1

    # ---- ① 日期不许自己算 ----
    hits: list[str] = []
    for f in py:
        name = rel(f)
        src = code_only(f.read_text(encoding="utf-8"))
        for pat in DATE_PATTERNS:
            for m in re.finditer(pat, src):
                line_no = src[: m.start()].count("\n") + 1
                hits.append(f"{name}:{line_no} {m.group(0)}")
    bad = [h for h in hits if h.split(":")[0] not in DATE_ALLOW]
    for h in hits:
        print(f"     · {h}{'（白名单）' if h.split(':')[0] in DATE_ALLOW else ''}")
    # 反空转：`business_time` 必须真的被用在一批地方——否则"没人自己算日期"是因为**没人算日期**，
    # 而不是因为都走了那一处（把 5 个消费点全删掉也会让上面那条变绿）。
    funnel = sum(
        len(re.findall(rf"\b{fn}\(", code_only(f.read_text(encoding="utf-8"))))
        for f in py
        for fn in ("business_date", "business_local", "business_today", "business_range_utc", "to_utc_naive")
    )
    print(f"   business_time 的调用点共 {funnel} 处")
    if funnel < 6:
        fails.append(f"business_time 只有 {funnel} 个调用点（<6）——它没被真正接线，判据在空转")
    print(f"① 「当地哪一天」的取值点共 {len(hits)} 处，其中 {len(bad)} 处没走 business_time")
    if bad:
        fails.append("这些地方自己算了日期/小时（必须走 app/core/business_time.py）：" + "；".join(bad[:6]))

    # ---- ①b 不许裸写「现在」（R14-9：`datetime.now()` 是进程本地时间，库里的时间列是 UTC）----
    now_hits: list[str] = []
    for f in py:
        name = rel(f)
        src = code_only(f.read_text(encoding="utf-8"))
        for pat in NOW_PATTERNS:
            for m in re.finditer(pat, src):
                line_no = src[: m.start()].count("\n") + 1
                now_hits.append(f"{name}:{line_no} {m.group(0)}")
    now_bad = [h for h in now_hits if h.split(":")[0] not in NOW_ALLOW]
    for h in now_bad[:8]:
        print(f"     · {h}")
    print(f"①b 裸写「现在」的地方共 {len(now_hits)} 处，其中 {len(now_bad)} 处该走 business_time")
    if now_bad:
        fails.append(
            "这些地方裸写了「现在」（本地时间 vs 库里的 UTC，相减就是静默的 8 小时偏差）："
            "改用 business_time.utc_now_naive() / business_today()：" + "；".join(now_bad[:6])
        )
    # 反空转：两个新入口必须真的被用（否则"没人裸写"只是因为没人取时间）
    for fn in (r"utc_now_naive\(", r"business_today\("):
        n = sum(len(re.findall(rf"\b{fn}", code_only(f.read_text(encoding="utf-8")))) for f in py)
        print(f"   `{fn}` 调用点 {n} 处")
        if n < 3:
            fails.append(f"`{fn}` 只有 {n} 个调用点（<3）——刚立的同源入口没被接线，判据在空转")

    # ---- ② 导出金额必须过 _money ----
    # ⚠️ 第一版判据是"看整行里有没有 `_money(`"，被两条排除规则放到太宽：注入
    #    `str(data["arrears_total"])` 之后**仍然全绿**（那一行同时含 `cancelled_orders`，
    #    被"计数行"的排除规则放行了）。现在改成**逐个金额表达式**查：`str(<金额表达式>)` 一律报红。
    reports = (BACKEND / "api/v1/reports.py").read_text(encoding="utf-8")
    money_expr = (
        r"(?:data\[[\"'][a-z_]*[\"']\]|it\.\w+|s\.\w+|u\.\w+|b\[[\"']total[\"']\]|"
        r"g\[[\"']amount[\"']\]|f\.amount|income|expense|amt)"
    )
    moneyish = re.compile(rf"str\(\s*{money_expr}")
    offenders = [f"{n}: {ln.strip()[:80]}" for n, ln in enumerate(reports.splitlines(), 1) if moneyish.search(ln)]
    cells = [ln.strip() for ln in reports.splitlines() if "ws.append(" in ln]
    wrapped = len(re.findall(r"_money\(", reports))
    print(f"② 导出写入行 {len(cells)} 行；`_money(` {wrapped} 处；仍用 `str(...)` 包金额 {len(offenders)} 处")
    if wrapped < 8:
        fails.append(f"reports.py 里的 `_money(` 只有 {wrapped} 处（<8）——判据可能已空转")
    if offenders:
        fails.append("这些导出金额没走 _money()（写出来是文本，Excel 求和加不到）：" + "；".join(offenders[:4]))

    # ---- ③ 指标实现只许一处 ----
    traces = []
    if re.search(r"ot_valid\s*=", reports) or re.search(r"freight_owed\s*=", reports):
        traces.append("reports.py 里自己算了准时率/待结运费")
    # ⚠️ 光查名字不够：注入把 **import** 删掉之后，调用处的 `driver_performance(` 还在文本里，
    #    判据照样绿（反向验证当场抓到）。所以 import 与调用**都要**在。
    if "from app.services.stats_service import driver_performance" not in reports:
        traces.append("reports.py 没有 import stats_service.driver_performance")
    if "for row in driver_performance(db, s, e)" not in reports:
        traces.append("reports.py 没有调用 stats_service.driver_performance（司机绩效导出又在自己算）")
    stats = (BACKEND / "services/stats_service.py").read_text(encoding="utf-8")
    if "def driver_performance(" not in stats:
        traces.append("stats_service.driver_performance 不见了（唯一的实现没了）")
    print(f"③ 指标同源检查：{'OK' if not traces else traces}")
    if traces:
        fails.append("；".join(traces))

    # ---- ④ 钱的算法只许一处（pay_for_order 是唯一实现）----
    # ⚠️ 查的是**调用**（带实参），不是 import 行：注入把调用换掉而 import 还在时，
    #    只查 `pay_for_order(` 会漏（第一版的注入就证明了这一点）。
    call_re = re.compile(r"pay_for_order\((?:o|ode|x|order)\)")
    for name in ("services/stats_service.py", "api/v1/freight_settlement.py", "api/v1/reports.py"):
        src = (BACKEND / name).read_text(encoding="utf-8")
        if not call_re.search(src):
            fails.append(f"{name} 没有真的调用 pay_for_order（司机应得又有一份自己的算法）")

    # ---- ⑤ 白名单不许悄悄变长 ----
    # 白名单是"允许自己算日期"的唯一口子；它一旦变长，就说明有地方在绕开 business_time。
    # 数量判据不是万能药，但它能让"顺手加一行"变成一个**需要解释**的动作。
    if len(DATE_ALLOW) > 6:
        fails.append(
            f"「自己算日期」的白名单有 {len(DATE_ALLOW)} 条（上限 6）——"
            "变长说明有地方在绕开 app/core/business_time.py，请先问清楚为什么"
        )

    if fails:
        print("\n❌ 「一个数只有一处算法」被破坏：")
        for f in fails:
            print("   - " + f)
        return 1
    print("\n✅ 时间、导出金额、司机绩效、司机应得 —— 四类算法都只有一处实现。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
