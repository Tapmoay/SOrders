#!/usr/bin/env python
"""客户欠款 / 应收账龄与信用额度（FEAT-0015 第五期）的机器判据。

盯住八件事（每一条都是「不报错但会错」的形状）：

1. **一行 = 一个债务人，不是一份客户档案**：订单上根本没有 customer_id，唯一的路是
   customers.arrears_unit_id 这条**可空、非唯一**的映射 —— 按它分组必然出现「同一个客户两个答案」。
   凭证次序必须是 挂账单位 → 单位名快照 → 货主账号 → 临时货主名 → 未填货主，
   而且这份报表里⛔ 不许再出现「未分配挂账单位」（那个桶把没挂单位的单全端成一锅，打电话都找不到人）。
2. **正欠款进账龄桶、负数（预收）单列**：桶回答的是「欠久了多少」，负数没有「欠」。
   顺序反了（先写预收再写桶）会把预收算成欠款，而**报错不会出现** —— 只有对着数字才看得出来。
3. **账龄锚点是「最早一笔记账日」，红冲只冲金额不冲起点**：⛔ 不许顺手 sum(Ledger.total)
   另写一个钱的实现（钱那一侧的唯一口径是 order_money，判据 _check_money_contract.py 在管）。
4. **报表是时点账**：as_of = min(窗口末, 今天)；窗口起点不参与余额。把它做成「期间账」也编译得过、
   接口也通 —— 但那一天之后的单会被算成欠款。
5. **出参金额一律到分**（_q2 / ROUND_HALF_UP）：不然同一个表里 "0" 与 "6726.40" 混排，
   导出到 Excel 是文本、客户端按字符串直显时又对不齐。
6. **信用额度长在挂账单位上**（不是客户档案）：NULL = 不限额、0 = 一分都不许再赊，两件事；
   列可空、⛔ 不回填、⛔ 不当 0；超限只是提示，⛔ 不挡下单、不挡发货。
7. **额度留痕三处都要在**：领域词汇表的动作码 + 权限归属表（ledger:edit）+ Android 审计页的中文名
   （少一处 _check_action_labels.py / _check_capability_* 就红，但红的原因常常被当成"别人的事"）。
8. **口径不许被悄悄删掉**：桶边界、跨口径对拍（turnover 的 arrears_total == totals.balance）、
   预收单列、时点语义 —— 单测里少一条，这份报表就可能在不报错的情况下变成另一个意思。

R4-BOUNDARY-JUSTIFICATION: 这条判据不下沉到任何一层边界，因为它盯的是**跨层的口径一致性**：
  行的身份（订单 ↔ 挂账单位 ↔ 客户档案三种凭证）、金额的符号归类、时点账的 as_of 语义、
  额度的可空语义、审计留痕的三处登记 —— 每一件单独看都合规矩（报表只读、金额只走 order_money、
  额度只是一列），但**组合起来**才决定「这笔钱该向谁要、欠了多久、还能不能再赊」。
  后端契约层看不见「预收没进桶」，领域类型层看不见「没挂单位的单落到了真人」，
  权限模型层看不见「额度写进审计日志时用的是哪个动作码」。谁都不会写错的边界，
  这里才需要机器盯着；而拼错的那一天，界面上每一个数字都还是"正常"的。

用法：python _tools/qa/_check_customer_balances.py  （--list 打一份人读清单）
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_hints import Checker, read, strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BE = ROOT / "backend/app"
BQ = BE / "services/reports/balance_query.py"
API = BE / "api/v1/reports.py"
SERVICE = BE / "services/reports_service.py"
SCHEMAS = BE / "schemas/reports.py"
ARR_SCHEMAS = BE / "schemas/arrears.py"
ARREARS_API = BE / "api/v1/arrears.py"
AMODEL = BE / "models/arrears.py"
CUSTOMER_MODEL = BE / "models/customer.py"
ENUMS = BE / "models/enums.py"
COVERAGE = BE / "core/capability_audit_coverage.py"
BOOT = BE / "core/schema_bootstrap.py"
MIG = BE / "migrations/021_arrears_unit_credit_limit.py"
TEST = ROOT / "backend/tests/test_customer_balances.py"
REVERSE = ROOT / "_tools/qa/_reverse_verify_customer_balances.py"
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
CENTER = AND / "ui/dispatcher/ReportCenter.kt"
# 2026-10-05 CHG-0034：11 格清单搬到 report/ReportV2Model.kt 的 REPORT_ENTRIES ⇒ 锚点跟着搬
HOME = AND / "ui/dispatcher/report/ReportV2Model.kt"
DOC = ROOT / "docs/changes/FEAT-0015.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
EP_INDEX = ROOT / "docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md"

NL = chr(10)
CR = chr(13)
BT = chr(96)

#: 反空转下限（文件被搬走 / 目录改名 / 扫描写坏时不许安静全绿）
MIN_BQ_CHARS = 7000
MIN_TEST_CHARS = 6000
MIN_REVERSE_CHARS = 3000
MIN_REPORT_MODULES = 10


def norm(path: Path) -> str:
    """读一份文件并把 CRLF 归一成 LF（仓库里两种行尾都有，锚点不该被行尾绊倒）。"""
    return read(path).replace(CR + NL, NL)


def seg(src: str, start: str, end: str) -> str:
    """抠出 [start, end) 之间的一块（找不到 start 就返回空串，让判据报红）。"""
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i + len(start))
    return src[i:] if j < 0 else src[i:j]


def model_columns(path: Path) -> set[str]:
    """模型类里的列名（AST：类体里的注解赋值与赋值）。

    ⚠️ 故意不用「字符串里找 credit_limit」：那样一段**被注释掉的拷贝**也会报红，
    而注释不是真相 —— 这条判据问的是「额度这一列长在哪张表上」。
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(read(path))):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                names.add(stmt.target.id)
            elif isinstance(stmt, ast.Assign):
                names.update(t.id for t in stmt.targets if isinstance(t, ast.Name))
    return names


def before(src: str, a: str, b: str) -> bool:
    """a 必须出现在 b 之前（两段都得在）。"""
    ia, ib = src.find(a), src.find(b)
    return 0 <= ia < ib


def main() -> int:
    if refuse_if_injecting("客户欠款判据"):
        return 1
    c = Checker()

    # ── 0. 反空转 ────────────────────────────────────────────────────────
    c.section("0. 反空转（文件搬走 / 目录改名 / 扫描写坏时先喊）")
    files = (
        BQ, API, SERVICE, SCHEMAS, ARR_SCHEMAS, ARREARS_API, AMODEL, CUSTOMER_MODEL, ENUMS,
        COVERAGE, BOOT, MIG, TEST, REVERSE, CENTER, HOME, DOC, REGISTRY, CLAIM, EP_INDEX,
    )
    missing = [p.name for p in files if not p.exists()]
    c.ok("二十个文件都在（查询模块 / 端点 / 旧路径壳 / 两份出参 / 挂账单位端点与模型 / "
         "枚举 / 归属表 / 自愈 / 迁移 / 单测 / 反验 / 两个 Android 页 / 四份台账）",
         not missing, "缺：" + str(missing))
    if missing:
        print(NL + "❌ 文件都不在，后面的判据没有意义")
        return 1

    bq = norm(BQ)
    api = norm(API)
    service = norm(SERVICE)
    sch = norm(SCHEMAS)
    arr_sch = norm(ARR_SCHEMAS)
    ar = norm(ARREARS_API)
    amod = norm(AMODEL)
    cust_mod = norm(CUSTOMER_MODEL)
    enums = norm(ENUMS)
    coverage = norm(COVERAGE)
    boot = norm(BOOT)
    mig = norm(MIG)
    test = norm(TEST)
    center = strip_comments(norm(CENTER))
    home = strip_comments(norm(HOME))
    doc = norm(DOC)
    registry = norm(REGISTRY)
    claim = norm(CLAIM)
    ep_index = norm(EP_INDEX)

    pkg = sorted((ROOT / "backend/app/services/reports").glob("*.py"))
    c.ok("报表包扫到 " + str(len(pkg)) + " 个模块（下限 " + str(MIN_REPORT_MODULES) + "）",
         len(pkg) >= MIN_REPORT_MODULES,
         "目录改名了？那样「一处都没有」和「一处都没扫到」是同一个输出")
    c.ok("balance_query.py 读到了内容（下限 " + str(MIN_BQ_CHARS) + " 字符）",
         len(bq) >= MIN_BQ_CHARS, "实际 " + str(len(bq)))
    c.ok("单测读到了内容（下限 " + str(MIN_TEST_CHARS) + " 字符）",
         len(test) >= MIN_TEST_CHARS, "实际 " + str(len(test)))
    c.ok("报表中心第 11 格在（客户欠款）", "客户欠款" in home and 'EntryCard("10"' in home)

    # ── 1. 行的身份 ──────────────────────────────────────────────────────
    c.section("1. 一行 = 一个债务人（不是 customers 档案）")
    c.ok("有 _debtor_of（这笔欠款记在谁头上）", "def _debtor_of(o: Order)" in bq)
    for kind in ("unit", "unit_name", "shipper", "temp", "unknown"):
        c.ok('凭证 kind "' + kind + '" 在', '"' + kind + '"' in bq)
    c.ok("四种凭证按优先次序认：挂账单位 → 单位名快照 → 货主账号 → 临时货主名 → 未填货主",
         before(bq, 'if o.arrears_unit_id is not None:', 'return "unit_name"')
         and before(bq, 'return "unit_name"', "if o.shipper_id is not None:")
         and before(bq, "if o.shipper_id is not None:", 'return "temp"')
         and before(bq, 'return "temp"', 'return "unknown", ""'))
    c.ok("认不出来时那一行叫「未填货主」", 'UNKNOWN_NAME = "未填货主"' in bq)
    c.ok("这份模块里 0 处「未分配挂账单位」（口径换了：没挂单位的单落到真人）",
         "未分配挂账单位" not in bq)
    c.ok("为什么不是客户档案的理由写在代码里（可空非唯一的映射）",
         "可空、非唯一" in bq and "划分" in bq)
    c.ok("单位行带得出客户名册（催收时「这个单位是哪个客户」）",
         "customer_names" in bq and "Customer.arrears_unit_id.in_(unit_ids)" in bq)
    c.ok("货主名与 order_response 同一口径（名字 → 手机号 → 空）",
         "def _user_label(u: User | None)" in bq and 'or (u.phone or "").strip()' in bq)

    # ── 2. 钱的形状 ──────────────────────────────────────────────────────
    c.section("2. 钱的形状：正欠款进桶、负数单列预收、出参到分")
    c.ok("四个桶名与顺序在（0_30 / 31_60 / 61_90 / over_90）",
         'BUCKET_KEYS = ("0_30", "31_60", "61_90", "over_90")' in bq)
    c.ok("账龄边界真的是 30 / 60 / 90（30 与 31、90 与 91 分属两桶）",
         "if days <= 30:" in bq and "if days <= 60:" in bq and "if days <= 90:" in bq)
    loop = seg(bq, "for o, mm, ds in use:", "out_rows = [")
    c.ok("进桶的只有正数、预收单列（同一段里按符号分岔）",
         "if amount > ZERO:" in loop
         and 'g["buckets"][bucket_of(days)] += amount' in loop
         and 'g["prepaid"] += -amount' in loop)
    c.ok("进桶那一句在预收那句之前（顺序反了就把预收算成欠款）",
         before(loop, 'g["buckets"][bucket_of(days)] += amount', 'g["prepaid"] += -amount'))
    c.ok("预收那句的注释写明「不进账龄桶」", "不进账龄桶" in loop)
    c.ok("余额与预收都进合计（total_balance == Σ行）",
         '"balance": _q2(sum((r["balance"] for r in out_rows), ZERO))' in bq
         and '"prepaid": _q2(sum((r["prepaid"] for r in out_rows), ZERO))' in bq)
    c.ok("窗口起点不参与余额（只有上界 as_of 在切：时点账）",
         "if ds is None or ds > as_of:" in bq)
    c.ok("账龄锚点是「最早一笔记账日」（min(entry_date)，且只认订单行与手工行）",
         "func.min(Ledger.entry_date)" in bq
         and "Ledger.source.in_((LedgerSource.ORDER, LedgerSource.MANUAL))" in bq)
    c.ok("本文件 0 处 Ledger.total / 0 处 func.sum（钱不在别处再算一遍）",
         "Ledger.total" not in bq and "func.sum(" not in bq)
    c.ok("出参金额一律到分（ROUND_HALF_UP + Decimal('0.01')）",
         'Decimal("0.01")' in bq and "rounding=ROUND_HALF_UP" in bq)
    n_q2 = bq.count("_q2(")
    c.ok("_q2 至少打在 8 处（余额 / 预收 / 四桶 / 已用 / 可用 / 合计）", n_q2 >= 8, "实际 " + str(n_q2))
    c.ok("行序确定（欠得多的在前、同额按名字）",
         'out_rows.sort(key=lambda r: (-r["balance"], r["name"]))' in bq)
    c.ok("口径说明里写明这是时点账、与窗口起点无关", "这是**时点账**" in bq)
    c.ok("口径说明里写明「往前调报表日」的读法与它的边界",
         "收款流水没有历史快照" in bq)
    c.ok("口径说明六条都在（含「行是按债务人分的」与「往前调报表日」那两条）",
         "行是按**债务人**分的" in bq and "把报表日往前调" in bq)

    # ── 3. 端点 ──────────────────────────────────────────────────────────
    c.section("3. 端点：时点账 as_of + 逐单明细可选 + 导出能带走")
    ep = seg(api, '@router.get("/customer-balances"', '@router.get("/export"')
    c.ok("端点在（response_model=CustomerBalancesOut）",
         '@router.get("/customer-balances", response_model=CustomerBalancesOut)' in api)
    c.ok("权限与既有报表同档（ORDER_DISPATCH）", "Permission.ORDER_DISPATCH" in ep)
    c.ok("报表日 = min(窗口末, 今天)，⛔ 不越过今天", "as_of = min(span[1], business_today())" in ep)
    c.ok("逐单明细开关默认关（省字节）", "include_orders: bool = Query(False" in ep)
    c.ok("出参丢掉内部 _window", 'data.pop("_window", None)' in ep)
    c.ok("端点不做第二个分组视图（没有 group_by 参数）", "group_by" not in ep)
    c.ok("视图函数名写死（接线与判据都锚它）", "def customer_balances_report(" in ep)
    c.ok("窗口仍走既有 _span（mode/anchor/date_from/date_to 一套实现）", "_span(mode, anchor" in ep)
    c.ok("导出的 kind 白名单收了这一份", "|customer-balances)" in api)
    exp = seg(api, 'elif kind == "customer-balances":', "elif kind ==")
    c.ok("导出分支真的写了（不是只放了个 kind 白名单）",
         "客户欠款" in exp and "不限额" in exp)
    c.ok("导出同样按「不越过今天」取报表日", "as_of = min(e, business_today())" in api)
    c.ok("旧路径壳里 re-export 了 build_customer_balances（既有引用不断）",
         "build_customer_balances" in service)

    # ── 4. 出参模型 ──────────────────────────────────────────────────────
    c.section("4. 出参模型（钱的字段是 Decimal，不是 float）")
    for name in ("CustomerBalanceOrderItem", "CustomerBalanceRow",
                 "CustomerBalanceTotals", "CustomerBalancesOut"):
        c.ok("出参模型 " + name + " 在 schemas/reports.py 里", "class " + name in sch)
    c.ok("三条恒等式写在出参模型的 docstring 上",
         "balance == Σ buckets − prepaid" in sch and "credit_available == limit − credit_used" in sch)
    c.ok("构造上保证恒等式的实现点写明了（balance_query.build_customer_balances）",
         "balance_query.py::build_customer_balances" in sch)
    sch_seg = seg(sch, "class CustomerBalanceOrderItem", "class CustomerBalancesOut")
    c.ok("这几个模型里 0 处 float（金额一律 Decimal → 字符串）", "float" not in sch_seg)
    c.ok("超限是布尔提示字段（over_limit），不是异常", "over_limit: bool" in sch)

    # ── 5. 信用额度 ──────────────────────────────────────────────────────
    c.section("5. 信用额度：长在挂账单位上、NULL = 不限额、0 是真的零")
    c.ok("列加在 arrears_units（赊账主体）而不是 customers",
         "credit_limit" in model_columns(AMODEL)
         and "credit_limit" not in model_columns(CUSTOMER_MODEL))
    c.ok("列可空（NULL = 不限额：⛔ 不回填、⛔ 不当 0）",
         "credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)" in amod)
    c.ok("模型注释写明「超限只是提示，不挡下单、不挡发货」", "超限只是**提示**" in amod)
    c.ok("迁移 021 在（版本 21 / 列名 credit_limit / DECIMAL(14,2) NULL）",
         "VERSION = 21" in mig and 'COLUMN = "credit_limit"' in mig
         and 'DDL = "credit_limit DECIMAL(14,2) NULL"' in mig)
    c.ok("迁移可重跑（列已在就 return）", "inspect(engine)" in mig and "get_columns(TABLE)" in mig)
    c.ok("迁移⛔ 不回填、⛔ 不设默认值（0 与 NULL 是两件事）",
         "UPDATE" not in mig and "server_default" not in mig and "NOT NULL" not in mig)
    c.ok("启动自愈副本同步补列（两道保险）",
         'if "credit_limit" not in acols' in boot and "arrears_units.credit_limit 已补列" in boot)
    c.ok("挂账单位的出参/入参三处都带 credit_limit（Create / Update / Out）",
         arr_sch.count("credit_limit") >= 4
         and all(("class " + n) in arr_sch for n in ("ArrearsUnitCreate", "ArrearsUnitUpdate", "ArrearsUnitOut")))
    c.ok("字段名命中不了 money.py 的金额名正则，所以自己写范围约束（ge=0 + MONEY_MAX）",
         "ge=0" in arr_sch and "MONEY_MAX" in arr_sch)
    c.ok("null 是合法值 = 清额度（端点看 model_fields_set 不看 None）",
         'limit_touched = "credit_limit" in body.model_fields_set' in ar)
    c.ok("额度三件套由行上的余额派生（已用 / 还能赊 / 超没超）",
         "credit_used" in bq and "credit_available" in bq and "over_limit" in bq)
    c.ok("已用额度不从负数起算（预收不许放大可用额度）",
         'used = g["balance"] if g["balance"] > ZERO else ZERO' in bq)

    # ── 6. 额度留痕 ──────────────────────────────────────────────────────
    c.section("6. 额度留痕：动作码三处登记 + 额度走既有 PATCH（不开新路径）")
    c.ok("动作码在领域词汇表里定义",
         'ARREARS_UNIT_CREDIT_LIMIT = "ARREARS_UNIT_CREDIT_LIMIT"' in enums)
    c.ok("权限归属表里登记在 ledger:edit（与欠款/开销同一档）",
         "ARREARS_UNIT_CREDIT_LIMIT" in coverage)
    c.ok("Android 审计页有它的中文名（否则 _check_action_labels.py 红）",
         "ARREARS_UNIT_CREDIT_LIMIT" in center and "额度" in center)
    n_routes = ar.count("@router.")
    c.ok("挂账单位端点仍是 5 条（额度复用既有的 POST/PATCH，⛔ 不开新路径）",
         n_routes == 5, "实际 " + str(n_routes))
    c.ok("额度变更只在真的改了数时才写第二条日志（同一个数重发不留痕）",
         "if limit_touched and u.credit_limit != limit_before:" in ar)
    c.ok("审计 payload 里的额度是文本（_limit_text，注释写明「不是显示口径」）",
         "def _limit_text(" in ar and "_limit_text(u.credit_limit)" in ar
         and "不是显示口径" in ar)
    c.ok("新建单位时若直接带了额度也留痕（scope=create）", '"scope": "create"' in ar)
    c.ok("超限只在报表里当提示（写侧一个字都不提 over_limit）", "over_limit" not in ar)

    # ── 7. 测试与反验 ────────────────────────────────────────────────────
    c.section("7. 测试与反验：边界、跨口径对拍、时点语义都钉住了")
    c.ok("单测守住了桶边界（30 / 31 / 60 / 61 / 90 / 91 六个数字都在）",
         all(str(n) in test for n in (30, 31, 60, 61, 90, 91)))
    c.ok("单测里有跨口径对拍（turnover 的 arrears_total == totals.balance）",
         "arrears_total" in test and "turnover" in test)
    c.ok("单测覆盖预收单列（prepaid 且不进桶）", "prepaid" in test)
    c.ok("单测覆盖「报表日往前调」的时点语义", "昨天" in test)
    c.ok("单测覆盖额度三态（不限额 / 零 / 超限只是提示）",
         "credit_limit" in test and "over_limit" in test)
    c.ok("单测里有逐行恒等式的断言助手（balance == Σ桶 − 预收）",
         "buckets" in test and "prepaid" in test)
    c.ok("反向验证脚本在（注入写法必须报红）",
         len(norm(REVERSE)) >= MIN_REVERSE_CHARS, "实际 " + str(len(norm(REVERSE))))
    c.ok("本判据自己带边界声明段（_check_r3_constraints 的新检查器闸）",
         "R4-BOUNDARY-JUSTIFICATION:" in (__doc__ or ""))

    # ── 8. 文档与登记 ────────────────────────────────────────────────────
    c.section("8. 文档与登记：四处裁决已落到文档 + 新端点进了生成物")
    c.ok("变更文档九节齐全（认小节标题，不是字符）",
         all(("## " + s) in doc for s in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")),
         "文档缺节")
    c.ok("文档里不再有第二个分组视图（group_by 已砍）", "group_by" not in doc)
    c.ok("文档写明额度列加在 arrears_units、迁移叫 021_arrears_unit_credit_limit.py",
         "021_arrears_unit_credit_limit.py" in doc and "arrears_units" in doc)
    c.ok("文档写明出参模型并入 schemas/reports.py（不新建 schemas/balance.py）",
         "schemas/reports.py" in doc and "schemas/balance.py" not in doc)
    c.ok("文档写明行的身份是债务人（四种凭证）", "债务人" in doc)
    c.ok("登记簿里有 FEAT-0015 这一行（整行，不是一个链接里的字样）",
         any(ln.startswith("| " + BT + "FEAT-0015" + BT + " |") for ln in registry.split(NL)),
         "没登记（别人不知道这个 ID 用掉了）")
    c.ok("工作声明页上有 FEAT-0015 的声明块",
         "会话：**FEAT-0015 " in claim, "没声明就开工了（或者声明块被删了）")
    c.ok("声明块里写了核心改动行（enums.py 与 schema_bootstrap.py 是核心区）",
         "核心改动" in claim)
    c.ok("端点索引生成物已重跑（含 reports/customer-balances）",
         "customer-balances" in ep_index, "跑：cd backend && python -m scripts.gen_endpoint_index")
    c.ok("报表中心页数上限已放到 10（第 11 格进得去）",
         "coerceIn(0, 10)" in strip_comments(
             norm(AND / "ui/dispatcher/ReportCenterViewModel.kt")))

    print(NL + "=" * 60)
    if c.fails:
        print("❌ " + str(len(c.fails)) + " 项未通过（通过 " + str(c.n_ok) + " 项）：")
        for label, _detail in c.fails:
            print("   - " + label)
        return 1
    print("✅ 全部 " + str(c.n_ok) + " 项通过：客户欠款 —— 一行一个债务人（挂账单位 → 单位名快照 → "
          "货主 → 临时货主 → 未填货主）、正欠款进四桶预收单列、账龄从最早一笔记账日起算、"
          "报表日是时点、额度长在挂账单位上（NULL = 不限额）且超限只是提示、每一步都留痕。")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("客户欠款 / 应收账龄（FEAT-0015）判据覆盖：")
        print("1. 行的身份：四种凭证次序 + 未填货主 + 0 处「未分配挂账单位」+ 单位行带客户名册")
        print("2. 钱的形状：正数进桶 / 负数进预收（顺序）+ 最早记账日为锚 + 只到分 + 行序确定")
        print("3. 端点：response_model + ORDER_DISPATCH + as_of = min(窗口末, 今天) + 明细开关 + 导出分支")
        print("4. 出参模型：四个模型 + 三条恒等式 + 0 处 float")
        print("5. 额度：列在 arrears_units（可空 NULL）+ 迁移 021 可重跑不回填 + 自愈副本 + 三处出参")
        print("6. 留痕：动作码（词汇表 / 归属表 / Android 中文名）+ 仍 5 条路由 + 只在改了数时写日志")
        print("7. 测试与反验：桶边界六个数 + 跨口径对拍 + 预收 + 时点语义 + 反验脚本 + 本判据自带声明段")
        print("8. 文档与登记：九节 + 四处裁决 + 登记簿 + 声明块 + 端点索引生成物 + 页数上限 10")
        sys.exit(0)
    sys.exit(main())
