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
4. **订单的计费模式只许从订单读**（2026-09-21）：`orders.driver_billing_mode_snapshot` 为空/空串的是老单
   （这一列 v3.36 才加），钱那一侧对它的口径是"有运费就算 PIECE"，而四个展示/门控点各自按
   **司机档案**再算一遍 → 同一张老单"账单按单结、界面看不见运费"。
   判据：① `resolve_billing_mode(` 只许出现在"问**这个人**现在怎么算钱"的地方；
   ② 那一列只许出现在 driver_pay（唯一读处）/ 列定义 / 建列三处，SQL 侧要筛"有按单应付"就用
   `per_order_pay_filter`（两处各写一遍时曾对**空串**给出相反答案：账单生成了、结算页不列它）；
   ③ 三个入口必须在、消费点不许消失（否则判据会因为"没人再碰它"而恒绿）。

清单全部**从源码算出来**（白名单也写在这里，且每条要带理由），扫到的数量低于下限就报错（防空转）。

用法：python _tools/qa/_check_single_source.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

#: ⛔ 让 **stdout 与 stderr 都** 按 UTF-8 写（本机 Windows 的 stderr 默认是 GBK）。
#: 为什么放在这里：几乎每个工具都 import 本模块，而 `raise SystemExit("中文")` 与
#: `print(..., file=sys.stderr)` 走的是 stderr —— 只重配 stdout 的话，检查红了的**原因**
#: 在开发机上是乱码（2026-09-25 实测：反向验证因此匹配不上那句话）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass


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
    # ⛔ 2026-09-23 第 18 轮并行渗透补：上面五种形状漏掉了另外三类，而**同族缺陷全落在缺口里**
    #    （A2 抓到 4 条：绩效 SLA 的 UTC 日末、结算付款的 `flow_date`、内部备注的时间戳、
    #    以及客户端三处 `take(16)`）：
    #    ⑥ `datetime.combine(某业务日, time(...), tzinfo=utc)` —— 把**当地日**当成 UTC 日末
    #       （每天白送 8 小时宽限：本机准时率 82.3% 应为 30.9%）；
    #    ⑦ `某个时间戳.date()` —— 从**时间戳**推**日期列**（当地时间 00:00~08:00 会记到前一天）；
    #       `delivered_at` 已经在上面的白名单机制里，这里补的是**别的**时间戳列
    #       （`paid_at` / `settled_at` / `deleted_at` …：写 DATE 列时必须过 `business_date`）。
    r"datetime\.combine\(\s*[^,]+,\s*time\(",
    #    ⚠️ 中间的 `\)?` 不能省：实际写法常常是 `(s.paid_at).date()`（带括号），
    #    第一版没写它 —— 注入 `flow_date=(s.paid_at).date()` 时判据**照样绿**（反向验证当场抓到）。
    r"\.(?!delivered_at|cancelled_at|created_at)[a-z_]+_at\)?\.date\(\)",
]

#: 允许"从时间戳推日期"的地方 → 理由（按文件名）。
#: ⚠️ 与 `DATE_ALLOW` 同一套机制：白名单要写理由，**不许为了变绿而掏空清单**。
DATE_STAMP_ALLOW: dict[str, str] = {
    "core/business_time.py": "`business_date` 自己的实现（唯一那一处换算）",
}

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
    bad = [
        h for h in hits
        if h.split(":")[0] not in DATE_ALLOW and h.split(":")[0] not in DATE_STAMP_ALLOW
    ]
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
    reports = ((BACKEND / "api/v1/reports.py").read_text(encoding="utf-8")
               + ((BACKEND / "services/reports_service.py").read_text(encoding="utf-8")
                  if (BACKEND / "services/reports_service.py").is_file() else ""))   # 聚合可能已下沉到 service 层（阶段 4）
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
    for name in ("services/stats_service.py", "api/v1/freight_settlement.py"):
        src = (BACKEND / name).read_text(encoding="utf-8")
        if not call_re.search(src):
            fails.append(f"{name} 没有真的调用 pay_for_order（司机应得又有一份自己的算法）")

    # ---- 报表那一份：路由在 api/v1/reports.py、聚合可能在 services/reports_service.py（阶段 4 下沉）----
    rep_files = [BACKEND / "api/v1/reports.py", BACKEND / "services/reports_service.py"]
    rep_src = "".join(f.read_text(encoding="utf-8") for f in rep_files if f.is_file())
    if not call_re.search(rep_src):
        fails.append("报表（api/v1/reports.py + services/reports_service.py）没有真的调用 pay_for_order"
                     "（司机应得又有一份自己的算法）")

    # ---- ④b 订单的计费模式只许从订单读（2026-09-21）----
    # `orders.driver_billing_mode_snapshot` 为空/空串的是**老单**（这一列 v3.36 才加）。钱那一侧
    # 对它的口径早就定过：有运费就算 PIECE。而四个展示/门控点（运费可见性、出参
    # driver_billing_mode、运费变更提醒、送达拍照义务）各自抄了兜底
    # `快照 or resolve_billing_mode(车型, 计费)` —— 那算的是司机**现在**的档案，于是同一张老单
    # "账单按单给他结、界面上却看不见运费"，两边都不报错。
    # 三条判据（每条都要能红，反向验证见 `_reverse_verify_single_source.py`）：
    #   ① `resolve_billing_mode(` 只许出现在"问**这个人**现在怎么算钱"的地方；
    #   ② 那一列只许出现在三处：唯一读处（driver_pay）/ 列定义 / 建列 —— SQL 侧也一样，
    #      要筛"有按单应付"就用 `per_order_pay_filter`（两处各写一遍时曾对**空串**给出相反答案）；
    #   ③ 反空转：三个入口函数必须在，消费点也不许消失（判据不能因为"没人再碰它"而恒绿）。
    mode_allow = {
        "services/driver_pay.py": "它就是那一处实现（人怎么算钱也从这儿问）",
        "api/v1/users.py": "问的是「这个司机现在怎么算钱」（司机管理页那一列 / 建档默认值），不是某一张订单",
    }
    column_allow = {
        "services/driver_pay.py": "唯一的读处（`order_mode` 判一张单、`per_order_pay_filter` 给 SQL 用）",
        "models/order.py": "列定义",
        "core/schema_bootstrap.py": "建列/改列（迁移里的表名与列名字符串）",
    }
    # ⚠️ 判据是"**调用**"，不是"出现过这个名字"：`models/user.py` 里那个 `def resolve_billing_mode(`
    #    是定义本身（第一版把它当成了违规，红线当场误报）。
    resolve_call = re.compile(r"(?<!def )resolve_billing_mode\(")
    # 同理：只算**读**（`快照.is_(None)` / `快照 or …`）。`order.driver_billing_mode_snapshot = …`
    # 是派单时的**写入**（唯一一处，`order_flow.assign_driver`）——写进去不是判据。
    column_read = re.compile(r"driver_billing_mode_snapshot(?!\s*=(?!=))")
    mode_offenders: list[str] = []
    column_offenders: list[str] = []
    mode_callers: list[str] = []
    for f in py:
        name = rel(f)
        src = code_only(f.read_text(encoding="utf-8"))
        if resolve_call.search(src) and name not in mode_allow:
            mode_offenders.append(name)
        if column_read.search(src) and name not in column_allow:
            column_offenders.append(name)
        if name != "services/driver_pay.py" and ("has_per_order_pay(" in src or "order_mode(" in src):
            mode_callers.append(name)
    print(
        f"④b 订单模式的消费点 {len(mode_callers)} 个文件；绕过同源问司机档案 {len(mode_offenders)} 处；"
        f"直接读那一列 {len(column_offenders)} 处"
    )
    if mode_offenders:
        fails.append(
            "这些地方又按**司机档案**算了一遍订单的计费模式（订单请走 "
            "driver_pay.has_per_order_pay / order_mode）：" + "；".join(sorted(set(mode_offenders))[:5])
        )
    if column_offenders:
        fails.append(
            "这些地方直接读了 `driver_billing_mode_snapshot`（读一张单的模式走 `driver_pay.order_mode`，"
            "SQL 筛选走 `per_order_pay_filter`）：" + "；".join(sorted(set(column_offenders))[:5])
        )
    # 反空转：三个入口必须都在（删掉一个，上面两条会因为"没人绕开它"而恒绿）
    pay_src = code_only((BACKEND / "services/driver_pay.py").read_text(encoding="utf-8"))
    for fn in ("def order_mode(", "def has_per_order_pay(", "def per_order_pay_filter("):
        if fn not in pay_src:
            fails.append(f"driver_pay 里少了 `{fn}` —— 订单模式的唯一入口不见了")
    if len(mode_callers) < 5:
        fails.append(f"只有 {len(mode_callers)} 个文件在调订单模式的同源函数（<5）——判据在空转")
    for label, table, cap in (("问司机档案", mode_allow, 3), ("直接读列", column_allow, 3)):
        if len(table) > cap:
            fails.append(
                f"「{label}」的白名单有 {len(table)} 条（上限 {cap}）——"
                "变长说明有地方在绕开同源判据，请先问清楚为什么"
            )

    # ---- ④c Android 侧：订单商品行合计只许一处（2026-09-21）----
    # 这个数（Σ 订单行 line_total，定点）原来在 Android 里写了**三遍**：AI 找单的两条路
    # （`AiWriteService` 的 findOrders / findDeletedOrders）+ 收款页（`AccountToolsScreens.orderTotal`）。
    # 而收款页拿它当**判据**：用户照抄填进去的金额必须与后端 `Decimal` 算出的数完全相等，
    # 差一分就 400，表现是**多行/多单时永久收不了款**（2026-09-19 报告 P0-4：原来判据用
    # `Double` 顺序累加，20 万次随机试验失配率 2 行 22.72% / 5 行 37.68%）。
    # 判据：折点求和的**写法**全 Android 只许出现 1 次，且必须在 `util/Money.kt` 里
    # （它就是那一处实现）；消费点（调 `goodsTotal` / `goodsTotalText`）不许消失。
    ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
    kt = sorted(ANDROID.rglob("*.kt"))
    if len(kt) < 100:
        print(f"❌ 只扫到 {len(kt)} 个 Kotlin 文件——判据在空转，停。")
        return 1
    fold_sites: list[str] = []
    sum_callers: list[str] = []
    for f in kt:
        rel_kt = f.relative_to(ANDROID).as_posix()
        src_kt = f.read_text(encoding="utf-8")
        code_kt = code_only(src_kt)
        # 只数**代码**里的折点求和（`p.lineTotal?.toBigDecimalOrNull()`）：注释里提到它不算
        for m in re.finditer(r"[\w.]*lineTotal\?\.toBigDecimalOrNull\(\)", code_kt):
            fold_sites.append(f"{rel_kt}:{code_kt[:m.start()].count(chr(10)) + 1}")
        # 消费点 = **调**这两个函数的地方（定义它自己的那个文件不算）
        if ("goodsTotal(" in code_kt or "goodsTotalText(" in code_kt) and "fun OrderDto.goodsTotal(" not in code_kt:
            sum_callers.append(rel_kt)
    print(f"④c Android 侧折点求和的写法 {len(fold_sites)} 处；调用同源函数 {len(sum_callers)} 个文件")
    bad_fold = [s for s in fold_sites if not s.startswith("util/Money.kt:")]
    if bad_fold:
        fails.append(
            "Android 里又自己折点求和了（订单商品行合计请走 util/Money.kt 的 goodsTotal）："
            + "；".join(bad_fold[:5])
        )
    if len(fold_sites) != 1:
        fails.append(f"折点求和的写法有 {len(fold_sites)} 处（应为 1 处：util/Money.kt）")
    if len(sum_callers) < 2:
        fails.append(f"只有 {len(sum_callers)} 个文件在调 goodsTotal（<2）——判据可能已空转")

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
    print("\n✅ 时间、导出金额、司机绩效、司机应得、订单计费模式、Android 商品行合计 —— 六类算法都只有一处实现。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
