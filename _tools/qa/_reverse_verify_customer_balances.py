"""反向验证：**客户欠款（应收账龄与信用额度，FEAT-0015）**——三十七种破坏方式全被抓。

## 为什么要反验

`_tools/qa/_check_customer_balances.py` 是本期的红线：行的身份必须是**债务人**（不是客户档案）、
正欠款才进桶、账龄锚点是**最早一笔记账日**、余额是**时点账**、额度只长在挂账单位上。
这些口径全都**不报错但会算错钱**：

- 把挂账单位那一档抹掉 → 同一笔钱换个名字出现，催收时找不到人；
- 桶边界写成 15 天 → 账龄分档全乱，坏账准备按错的档计提；
- 锚点换成 `max(entry_date)` → 老账越放越"新"；
- 端点多了个分组参数 → 同一张表两个答案，谁都能挑一个对自己有利的看。

所以每一条都要**把源码改坏一次**，确认红线真的报红 —— 判据里写错字、锚点漂移、
断言写成了恒真，都只有在这一步才暴露。

## 安全约定（照 `_reverse_verify_arrears_units.py`）

改之前按**字节**存下来；每条注入跑完**无条件**还原（`finally`）；跑完逐字节核对
被碰过的文件与运行前一致。⛔ 绝不把注入的 bug 留在源码里。

用法：
  python _tools/qa/_reverse_verify_customer_balances.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_customer_balances.py"
NL = chr(10)

# ---- 会被注入的文件（正斜杠相对路径）
BQ = "backend/app/services/reports/balance_query.py"
API = "backend/app/api/v1/reports.py"
SCHEMAS = "backend/app/schemas/reports.py"
CUSTOMER_MODEL = "backend/app/models/customer.py"
AMODEL = "backend/app/models/arrears.py"
MIG = "backend/app/migrations/021_arrears_unit_credit_limit.py"
COVERAGE = "backend/app/core/capability_audit_coverage.py"
ARREARS_API = "backend/app/api/v1/arrears.py"
TEST = "backend/tests/test_customer_balances.py"
SELF = "_tools/qa/_check_customer_balances.py"
DOC = "docs/changes/FEAT-0015.md"
REGISTRY = "docs/changes/README.md"
CLAIM = "docs/AI_WORK_CLAIM.md"
EP_INDEX = "docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md"
CENTER = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"
# 2026-10-05 CHG-0034：11 格清单搬到 report/ReportV2Model.kt 的 REPORT_ENTRIES ⇒ 注入点跟着搬
HOME = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/report/ReportV2Model.kt"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenterViewModel.kt"


def _cut_export_branch(s: str) -> str:
    """把导出里这一份报表的整段切掉（只留 kind 白名单）—— 那一支是「导出真的写了」的锚点。"""
    marker = 'elif kind == "customer-balances":'
    i = s.find(marker)
    if i < 0:
        return s
    j = s.find("    elif kind ==", i + len(marker))
    if j < 0:
        return s
    return s[:i] + s[j + 4:]


CASES: list[tuple[str, str, object, str]] = [
    # ---------------------------------------------------- balance_query.py：行的身份
    ("行按债务人分（挂账单位那一档认不出来）", BQ,
     lambda s: s.replace("if o.arrears_unit_id is not None:", "if False:", 1),
     "四种凭证按优先次序认"),
    ("只有名字快照的老单被塞进「认不出来」", BQ,
     lambda s: s.replace('return "unit_name", name', 'return "unknown", ""', 1),
     "四种凭证按优先次序认"),
    ("认不出来的行又叫回「未分配挂账单位」", BQ,
     lambda s: s.replace('UNKNOWN_NAME = "未填货主"', 'UNKNOWN_NAME = "未分配挂账单位"', 1),
     "未分配挂账单位"),
    ("单位行不再带客户名册（催收不知道是谁）", BQ,
     lambda s: s.replace('"customer_names"', '"customer_name_list"'),
     "单位行带得出客户名册"),
    ("货主名不再按 order_response 的口径（名字 → 手机号 → 空）", BQ,
     lambda s: s.replace('(u.full_name or "").strip() or ', '(u.full_name or "") + ', 1),
     "货主名与 order_response 同一口径"),
    # ---------------------------------------------------- balance_query.py：桶与锚点
    ("预收/零额的负数也进账龄桶", BQ,
     lambda s: s.replace("if amount > ZERO:", "if amount >= ZERO:", 1),
     "进桶的只有正数"),
    ("账龄边界被改成 15 天", BQ,
     lambda s: s.replace("if days <= 30:", "if days <= 15:", 1),
     "账龄边界真的是 30 / 60 / 90"),
    ("锚点换成最后一笔记账日", BQ,
     lambda s: s.replace("func.min(Ledger.entry_date)", "func.max(Ledger.entry_date)", 1),
     "最早一笔记账日"),
    ("钱在别处又算了一遍（sum(Ledger.total)）", BQ,
     lambda s: s.replace("EARLIEST = date(1970, 1, 1)",
                         "EARLIEST = date(1970, 1, 1)" + NL
                         + "_LEAK = func.sum(Ledger.total)  # 注入：钱在别处又算了一遍", 1),
     "0 处 Ledger.total"),
    ("余额不再归一到分", BQ,
     lambda s: s.replace("_q2(", "q2r("),
     "_q2 至少打在 8 处"),
    ("行序不再确定（同额时按名字）", BQ,
     lambda s: s.replace('out_rows.sort(key=lambda r: (-r["balance"], r["name"]))',
                         'out_rows.sort(key=lambda r: r["name"])', 1),
     "行序确定"),
    ("窗口起点也参与余额（不再是时点账）", BQ,
     lambda s: s.replace("if ds is None or ds > as_of:", "if ds is None:", 1),
     "窗口起点不参与余额"),
    # ---------------------------------------------------- api/v1/reports.py：端点
    ("报表日越过今天", API,
     lambda s: s.replace("as_of = min(span[1], business_today())", "as_of = span[1]", 1),
     "不越过今天"),
    ("逐单明细默认打开（白送字节）", API,
     lambda s: s.replace("include_orders: bool = Query(False", "include_orders: bool = Query(True", 1),
     "逐单明细开关默认关"),
    ("端点长出第二个分组视图", API,
     lambda s: s.replace("def customer_balances_report(",
                         'def customer_balances_report(group_by: str = Query("customer"), ', 1),
     "端点不做第二个分组视图"),
    ("导出的 kind 白名单少了这一份", API,
     lambda s: s.replace("|customer-balances)$", ")$", 1),
     "导出的 kind 白名单收了这一份"),
    ("导出里这一份的整段分支被切掉", API,
     lambda s: _cut_export_branch(s),
     "导出分支真的写了"),
    ("端点丢了 response_model", API,
     lambda s: s.replace("response_model=CustomerBalancesOut)", ")", 1),
     "端点在（response_model=CustomerBalancesOut）"),
    # ---------------------------------------------------- 出参模型
    ("出参金额变成 float", SCHEMAS,
     lambda s: s.replace('credit_used: Decimal = Decimal("0")', "credit_used: float = 0.0", 1),
     "0 处 float"),
    ("恒等式写错（漏掉预收那一项）", SCHEMAS,
     lambda s: s.replace("balance == Σ buckets − prepaid", "balance == Σ buckets"),
     "三条恒等式"),
    ("行模型被改名", SCHEMAS,
     lambda s: s.replace("class CustomerBalanceRow(BaseModel):", "class BalanceRow(BaseModel):", 1),
     "出参模型"),
    # ---------------------------------------------------- 额度：列长在谁身上
    ("额度列长到 customers 上", CUSTOMER_MODEL,
     lambda s: s.replace('__tablename__ = "customers"',
                         '__tablename__ = "customers"' + NL
                         + "    credit_limit: Mapped[Decimal | None] = mapped_column("
                         + "Numeric(14, 2), nullable=True)  # 注入：额度长错了人", 1),
     "列加在 arrears_units"),
    ("列变成 NOT NULL（老库补不出来）", AMODEL,
     lambda s: s.replace("Numeric(14, 2), nullable=True)", "Numeric(14, 2), nullable=False)", 1),
     "列可空"),
    ("迁移顺手回填成 0（把「不限额」变成「额度为零」）", MIG,
     lambda s: s.replace('DDL = "credit_limit DECIMAL(14,2) NULL"',
                         'DDL = "credit_limit DECIMAL(14,2) NOT NULL DEFAULT 0"', 1),
     "不回填"),
    # ---------------------------------------------------- 留痕：额度改过要查得到
    ("权限归属表里少登记这个动作码", COVERAGE,
     lambda s: s.replace("'ARREARS_UNIT_CREDIT_LIMIT'," + NL, "", 1),
     "权限归属表里登记在 ledger:edit"),
    ("Android 审计页少了中文名", CENTER,
     lambda s: s.replace("ARREARS_UNIT_CREDIT_LIMIT", "ARREARS_UNIT_CREDIT_CAP", 1),
     "Android 审计页有它的中文名"),
    ("挂账单位端点多开了一条路径", ARREARS_API,
     lambda s: s.replace('@router.patch("/{unit_id}", response_model=ArrearsUnitOut)',
                         '@router.put("/{unit_id}/credit-limit")' + NL
                         + '    @router.patch("/{unit_id}", response_model=ArrearsUnitOut)', 1),
     "挂账单位端点仍是 5 条"),
    ("同一个数重发也写日志（留痕变成噪声）", ARREARS_API,
     lambda s: s.replace("if limit_touched and u.credit_limit != limit_before:",
                         "if limit_touched:", 1),
     "只在真的改了数时才写第二条日志"),
    # ---------------------------------------------------- 单测 / 判据自身
    ("单测丢了跨口径对拍", TEST,
     lambda s: s.replace("arrears_total", "arrears_sum_total"),
     "跨口径对拍"),
    ("判据自身丢了边界声明段", SELF,
     lambda s: s.replace("R4-BOUNDARY-JUSTIFICATION:", "R4-NONE:", 1),
     "本判据自己带边界声明段"),
    # ---------------------------------------------------- 文档与生成物
    ("文档里又冒出第二个分组视图", DOC,
     lambda s: s.replace("## ③", "## ③" + NL + "分组视图：" + "group_" + "by=customer", 1),
     "文档里不再有第二个分组视图"),
    ("变更文档少了第 ⑨ 节", DOC,
     lambda s: s.replace("## ⑨ 关闭（六格）", "## 收尾（六格）", 1),
     "变更文档九节齐全"),
    ("登记簿里少了 FEAT-0015 这一行", REGISTRY,
     lambda s: s.replace("| `FEAT-0015` |", "| `FEAT-0016` |", 1),
     "登记簿里有 FEAT-0015 这一行"),
    ("工作声明页上的 FEAT-0015 块不在了", CLAIM,
     lambda s: s.replace("会话：**FEAT-0015 ", "会话：**FEAT-0015X ", 1),
     "工作声明页上有 FEAT-0015 的声明块"),
    ("端点索引生成物没重跑", EP_INDEX,
     lambda s: s.replace("customer-balances", "customer-balance-x"),
     "端点索引生成物已重跑"),
    ("报表中心第 11 格不在", HOME,
     lambda s: s.replace('EntryCard("10"', 'EntryCard("12"', 1),
     "报表中心第 11 格在"),
    ("报表中心页数上限没放到 10", VM,
     lambda s: s.replace("coerceIn(0, 10)", "coerceIn(0, 9)", 1),
     "报表中心页数上限已放到 10"),
]


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    print("反向验证：客户欠款（FEAT-0015）—— 注入 " + str(len(CASES)) + " 种破坏方式")
    if not CHECK.exists():
        print("❌ 判据脚本都不在：" + str(CHECK))
        return 1

    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过 —— 先把它跑绿再来做反向验证")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _label, rel, _mutate, _expect in CASES})
    missing = [rel for rel in touched if not (ROOT / rel).exists()]
    if missing:
        print("❌ 前提不成立：这几个要被注入的文件不存在 —— " + ", ".join(missing))
        return 1
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    fails: list[str] = []
    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            print("  [SKIP] " + label)
            continue
        try:
            text = mutated.replace("\n", "\r\n") if crlf else mutated
            path.write_bytes(text.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print("  [OK] " + label + " → 报红")
        else:
            fails.append(label + "：注入之后没有按预期报红（退出码 " + str(code)
                         + "，期望关键词「" + expect + "」）")
            print("  [MISS] " + label + " → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        fails.append("还原检查没过（已强制还原）：" + ", ".join(dirty))
        print("❌ 还原检查：" + str(len(dirty)) + " 个文件跑完与运行前不一致（已强制还原）")
    else:
        print("✅ 还原检查：" + str(len(touched)) + " 个被碰过的文件与运行前逐字节一致")

    print(NL + "=" * 60)
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print("✅ " + str(len(CASES)) + " 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
