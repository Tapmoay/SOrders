"""反向验证 _tools/qa/_check_tax_invoices.py（红线：税账 —— 一张票 = 一笔进项或销项的税）。

## 为什么必须做

税这件事坏起来**一条报错都不会有**：
税额在第二个地方又算一遍（两边都看着有理，差一分钱）、
作废 / 回收站里的票照样进税汇（用户拿去申报就多缴）、
利润表的「税」既留在期间费用又搬进税那一格（同一笔钱扣两次）、
删单闸不在（挂着没作废进项票的采购单被删掉，那些票的进项税额凭空少掉）——
这些改法都能 import、接口都照样 200、pytest 也可能照样绿，只有用户对账时才发现。

所以逐条**注入真缺陷**：每条都必须让判据报红；跑完逐字节还原，并再跑一次确认还原后是绿的。

用法：python _tools/qa/_reverse_verify_tax_invoices.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_tax_invoices.py"

MODEL = ROOT / "backend/app/models/invoice.py"
MIGRATION = ROOT / "backend/app/migrations/020_invoices.py"
SERVICE = ROOT / "backend/app/services/tax_service.py"
API = ROOT / "backend/app/api/v1/invoices.py"
INV_SCHEMA = ROOT / "backend/app/schemas/invoice.py"
TAX_QUERY = ROOT / "backend/app/services/reports/tax_query.py"
PROFIT_QUERY = ROOT / "backend/app/services/reports/profit_query.py"
REPORTS_SCHEMA = ROOT / "backend/app/schemas/reports.py"
REPORTS = ROOT / "backend/app/api/v1/reports.py"
PURCHASE = ROOT / "backend/app/services/purchase_service.py"
ROUTER = ROOT / "backend/app/api/v1/router.py"
ENUMS = ROOT / "backend/app/models/enums.py"
CAPA = ROOT / "backend/app/core/capability_audit_coverage.py"
TEST = ROOT / "backend/tests/test_tax_invoices.py"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
DTOS_KT = ANDROID / "data/remote/dto/Dtos.kt"
# 2026-10-05 CHG-0034：11 格清单搬到 report/ReportV2Model.kt 的 REPORT_ENTRIES ⇒ 注入点跟着搬
HOME_KT = ANDROID / "ui/dispatcher/report/ReportV2Model.kt"
FINANCE_KT = ANDROID / "ui/dispatcher/ReportFinance.kt"
NAV_KT = ANDROID / "ui/nav/NavGraph.kt"
MODULES_KT = ANDROID / "ui/nav/Modules.kt"
INV_FORM_KT = ANDROID / "ui/dispatcher/InvoiceFormScreen.kt"

NL = chr(10)


def sub(old: str, new: str, n: int | None = 1):
    """注入：把 old 换成 new（n=None 表示全换）。"""

    def _apply(s: str) -> str:
        return s.replace(old, new) if n is None else s.replace(old, new, n)

    return _apply


CASES: list[tuple[str, Path, object]] = [
    # ================= ① 形状：三张表 + 票号唯一的编码方式 =================
    (
        "唯一索引少了一列（票号唯一不再按方向算）",
        MODEL,
        sub(
            'Index("uq_invoices_direction_no", "direction", "no_key", unique=True)',
            'Index("uq_invoices_direction_no", "direction", unique=True)',
        ),
    ),
    (
        "票头少一列供应商（进项票答不出是谁开的）",
        MODEL,
        sub(
            "    supplier_id: Mapped[int | None] = mapped_column(",
            "    supplier_x: Mapped[int | None] = mapped_column(",
        ),
    ),
    (
        "空票号变成必填（月结代开先登记、后补号这条路上没了）",
        MODEL,
        sub(
            "no_key: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)",
            'no_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")',
        ),
    ),
    (
        "改用 sqlite_where 那种部分唯一索引（MySQL 会静默忽略它）",
        MODEL,
        sub(
            "from sqlalchemy.orm import Mapped, mapped_column, relationship",
            "from sqlalchemy.orm import Mapped, mapped_column, relationship" + NL + NL
            + "sqlite_where = None",
        ),
    ),
    (
        "金额列换成字符串（钱一旦是字符串，迟早有人拿它做加法）",
        MODEL,
        sub(
            "    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))",
            '    amount: Mapped[str] = mapped_column(String(20), default="0.00")',
        ),
    ),
    (
        "税率列变必填（未税票与零税率票混成一回事）",
        MODEL,
        sub(
            "    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True, default=None)",
            '    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"))',
        ),
    ),
    (
        "销项票那条线不挂账本条目了（列名换了，界面上的连线看不懂）",
        MODEL,
        sub(
            '    ledger_id: Mapped[int] = mapped_column(ForeignKey("ledgers.id"), index=True)',
            '    ledger_x: Mapped[int] = mapped_column(ForeignKey("ledgers.id"), index=True)',
        ),
    ),
    (
        "迁移版本号忘了改（迁移头与库里的表对不上）",
        MIGRATION,
        sub("VERSION = 20", "VERSION = 19"),
    ),
    (
        "迁移只建两张表（销项 ↔ 账本那条线没建）",
        MIGRATION,
        sub("    InvoiceLedger.__table__.create(bind=engine, checkfirst=True)", "    # 忘了第三张"),
    ),

    # ================= ② 税额只有一个算法 =================
    (
        "税额算了两遍（第二份税额实现）",
        SERVICE,
        sub("def tax_of_amount(", "def tax_of_amount_again("),
    ),
    (
        "默认税率常量没了（默认值散在各处）",
        SERVICE,
        sub('DEFAULT_TAX_RATE = Decimal("3.00")', 'DEFAULT_TAX_RATE_X = Decimal("3.00")'),
    ),
    (
        "税率区间松掉（百分数填成 0~1 也放行）",
        SERVICE,
        sub("只能在 0 到 100 之间", "只能在 0 到 1000 之间"),
    ),
    (
        "税额不再与税率同生同灭（未税票也能带税额）",
        SERVICE,
        sub('detail="没填税率的票不该有税额', 'detail="税额随便填'),
    ),
    (
        "税额大于价税合计也放行（填反了不吭声）",
        SERVICE,
        sub("税额不能大于价税合计", "税额看着差不多就行"),
    ),
    (
        "「算不算进税汇」改成真值判断（0.00 的零税率票被踢出去）",
        SERVICE,
        sub("return invoice.tax_rate is not None", "return bool(invoice.tax_rate)"),
    ),
    # ================= ③ 关联校验 =================
    (
        "进项票可以不挂采购单（答不出这批货有没有票）",
        SERVICE,
        sub(
            '"进项票必须挂至少一张采购单 —— 不然答不出「这批货有没有票」。"',
            '"进项票挂不挂采购单都行。"',
        ),
    ),
    (
        "进项票也能填客户（两边串了）",
        SERVICE,
        sub('detail="进项票是供应商开给我们的，不该填客户。"', 'detail="进项票也可以填客户。"'),
    ),
    (
        "挂的单据不校验是不是同一家供应商",
        SERVICE,
        sub('"一张进项票只能抵同一家供应商的货。"', '"供应商对不对无所谓。"'),
    ),
    (
        "挂在回收站里的采购单被静默当不存在",
        SERVICE,
        sub(
            'ensure_alive(row, "采购单", f"先去采购单回收站把 #{row.id} 恢复出来，再挂到这张票上。")',
            "pass",
        ),
    ),
    # ================= ④ 状态机 + 两种不算数 =================
    (
        "开具之后照样能改（冻结规则没了）",
        SERVICE,
        sub('"只有「已登记」状态的票能改；要改就作废重开一张。"', '"随时都能改。"'),
    ),
    (
        "开具能推进两次（状态机不管重复）",
        SERVICE,
        sub('detail="这张票已经开具过了。"', 'detail="再开一次也行。"'),
    ),
    (
        "作废能推进两次",
        SERVICE,
        sub('detail="这张票已经作废过了。"', 'detail="再作废一次也行。"'),
    ),
    (
        "不在回收站里的票点恢复也当成功",
        SERVICE,
        sub('detail="这张票不在回收站里，不需要恢复。"', 'detail="恢复了。"'),
    ),
    (
        "查重又把回收站筛掉（删一张票再登记同号会撞唯一索引报 500）",
        SERVICE,
        sub(
            "    stmt = select(Invoice.id, Invoice.is_deleted).where(",
            "    stmt = select(Invoice.id, Invoice.is_deleted).where(" + NL
            + "        Invoice.is_deleted.is_(False),",
        ),
    ),
    (
        "命中回收站里的票时不告诉用户先恢复",
        SERVICE,
        sub(
            '"（那张票现在在回收站里 —— 先把它恢复出来，而不是把同一张票再登记一遍。）"',
            '"（那张票用过了。）"',
        ),
    ),
    # ================= ⑤ 税汇口径唯一 =================
    (
        "税汇窗口按 created_at 算（今天补录上个月的票落错月份）",
        SERVICE,
        sub("                Invoice.invoice_date >= start,", "                Invoice.created_at >= start,"),
    ),
    (
        "回收站里的票照样进税汇（查询上不再排掉）",
        SERVICE,
        sub("                Invoice.is_deleted.is_(False),", "                Invoice.id.isnot(None),"),
    ),
    (
        "作废的票照样算税（冲红白冲）",
        SERVICE,
        sub("            voided += 1", "            voided += 0"),
    ),
    (
        "没税率的票并进税额（税额凭空变大）",
        SERVICE,
        sub('            side["untaxed_count"] += 1', '            side["count"] += 1'),
    ),
    (
        "应交增值税改成两次相加",
        SERVICE,
        sub(
            '"vat_payable": sides[OUTPUT]["tax_amount"] - sides[INPUT]["tax_amount"]',
            '"vat_payable": sides[OUTPUT]["tax_amount"] + sides[INPUT]["tax_amount"]',
        ),
    ),
    (
        "分税率小格排序反了（进项混在销项前面）",
        SERVICE,
        sub("sorted(buckets, key=lambda k: (k[0] != OUTPUT, -k[1]))", "sorted(buckets, key=lambda k: k[1])"),
    ),
    (
        "两侧小格少一个键（未税金额看不见）",
        SERVICE,
        sub('        "untaxed_amount": Decimal("0.00"),' + NL, ""),
    ),
    # ================= ⑥ 采购单删单闸 =================
    (
        "删单闸被拿掉（挂着没作废进项票的采购单照样能删）",
        PURCHASE,
        sub("    _ensure_no_live_invoices(db, order)" + NL, ""),
    ),
    (
        "闸门把已开具的票也当成不算数（该拦的不拦）",
        PURCHASE,
        sub(
            "                Invoice.status != InvoiceStatus.VOIDED.value,",
            "                Invoice.status != InvoiceStatus.ISSUED.value,",
        ),
    ),
    (
        "拦截文案不说为什么（用户不知道删了会怎样）",
        PURCHASE,
        sub('"删单会让这些票的进项税额凭空少掉，税账就对不上了。"', '"这张单删不了。"'),
    ),
    # ================= ⑦ 利润表接线 =================
    (
        "税既留在期间费用又搬进税那一格（同一笔钱扣两次）",
        PROFIT_QUERY,
        sub("        expense_total = expense_total - tax_total", "        expense_total = expense_total"),
    ),
    (
        "营业利润那一行自己改了（搬家变成改总额）",
        PROFIT_QUERY,
        sub(
            "operating_profit = gross_profit - delivery_cost - expense_total - depreciation_total - tax_total",
            "operating_profit = gross_profit - delivery_cost - expense_total - depreciation_total",
        ),
    ),
    (
        "增值税不再来自税汇（自己另算一套）",
        PROFIT_QUERY,
        sub(
            "    vat = vat_of_span(db, start, end)",
            '    vat = {"vat_output": _ZERO, "vat_input": _ZERO, "vat_payable": _ZERO}',
        ),
    ),
    (
        "口径说明里混进 markdown 星号",
        PROFIT_QUERY,
        sub("_NOTES: tuple[str, ...] = (" + NL, "_NOTES: tuple[str, ...] = (" + NL + '    "** 税金及附加",' + NL),
    ),
    (
        "利润表出参少一列（界面上看不见增值税）",
        REPORTS_SCHEMA,
        sub('    vat_output: Decimal = Decimal("0")' + NL, ""),
    ),
    # ================= ⑧ 端点 / 权限 / 路由 / 导出 =================
    (
        "读端点不再要权限（谁都能看税账）",
        API,
        sub("Reader = Depends(require_permission(Permission.ORDER_DISPATCH))", "Reader = Depends()"),
    ),
    (
        "写端点不再 rollback（失败留半成品）",
        API,
        sub("        db.rollback()", "        pass"),
    ),
    (
        "少一个端点（把票删进回收站这条路没了）",
        API,
        sub('@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)' + NL, ""),
    ),
    (
        "路由忘了挂（端点写好了但没人能访问）",
        ROUTER,
        sub("api_router.include_router(invoices.router)", "pass  # 忘了挂"),
    ),
    (
        "导出 kind 白名单忘了加 tax-summary",
        REPORTS,
        # ⚠️ 2026-10-04 · FEAT-0015：白名单尾部长出了第 11 个值 `customer-balances`，
        # 锚点必须跟着长（⛔ 只改锚点，不动判据：注入语义仍是「把 tax-summary 这一个可选值删掉」）。
        sub("|tax-summary|customer-balances)$", "|cost-coverage|customer-balances)$"),
    ),
    (
        "导出明细不写「算不算数」（作废 / 回收站 / 未税三种不算数看不出来）",
        REPORTS,
        sub('"算不算数"', '"状态说明"'),
    ),
    # ================= ⑨ 出参对齐 =================
    (
        "税账出参少了分税率小格（界面上看不见按税率分组）",
        INV_SCHEMA,
        sub("    by_rate: list[TaxRateBucketOut] = Field(default_factory=list)" + NL, ""),
    ),
    (
        "逐票明细少一个键（这张票算不算数看不见）",
        INV_SCHEMA,
        sub("    counts_in_tax: bool = True" + NL, "", None),
    ),
    (
        "builder 多返回一个接口上没有的键（出参与实现悄悄分叉）",
        TAX_QUERY,
        sub('        "notes": list(_NOTES),', '        "notes": list(_NOTES),' + NL + '        "extra_key": 1,'),
    ),
    # ================= ⑩ 留痕 =================
    (
        "枚举里少一个动作码（删票留不下痕）",
        ENUMS,
        sub('    TAX_INVOICE_DELETE = "TAX_INVOICE_DELETE"' + NL, ""),
    ),
    (
        "能力审计里少登记一个码（权限 → 动作 → 留痕覆盖率断链）",
        CAPA,
        sub("'TAX_INVOICE_RESTORE'", "'TAX_INVOICE_RESTORE_X'"),
    ),
    (
        "服务层少用一个码（作废那次没留痕）",
        SERVICE,
        sub("OperationAction.TAX_INVOICE_VOID", "OperationAction.TAX_INVOICE_ISSUE"),
    ),
    # ================= ⑪ 单测 =================
    (
        "单测被删掉一条（作废退出税汇没人钉了）",
        TEST,
        sub("def test_作废的票退出税汇", "def test_票作废之后退出税汇("),
    ),
    # ================= ⑫ Android：入口 / 报表第 10 格 / 两页接线 =================
    (
        "入口页第 10 格删掉（税账这一页从入口进不去）",
        HOME_KT,
        sub('EntryCard("9", "税账", Icons.Default.Receipt, Color(0xFFA98F76)),' + NL, ""),
    ),
    (
        "导出 kind(9) 改回 audit（第 10 页导出的是异常与审计那张表）",
        FINANCE_KT,
        sub('9 -> "tax-summary"', '9 -> "audit"'),
    ),
    (
        "NavGraph 第 10 格走错页（点「税账」进的是异常与审计）",
        NAV_KT,
        sub("9 -> navController.navigate(Routes.REPORT_TAX)",
            "9 -> navController.navigate(Routes.REPORT_EXCEPTION)"),
    ),
    (
        "台账一格不挂写侧能力（谁都能登记票，票面金额直接进税汇）",
        MODULES_KT,
        sub('Routes.INVOICES to "ledger:edit",' + NL, ""),
    ),
    (
        "改票请求多出 direction（方向变成可以改，票面与税汇对不上）",
        DTOS_KT,
        sub("data class InvoiceUpdateRequest(" + NL,
            "data class InvoiceUpdateRequest(" + NL + "    val direction: String? = null," + NL),
    ),
    (
        "表单页把校验放宽（填了税额不填税率也放过去）",
        INV_FORM_KT,
        sub('formError = "填了税额就得填税率', 'formError = "请检查税率'),
    ),
    (
        "表单页自己算了一遍税额（界面与接口各说各话）",
        INV_FORM_KT,
        sub('formError = "填了税额就得填税率',
            'val taxAmount = vm.amount.toDouble() * vm.taxRate.toDouble()' + NL +
            '        formError = "填了税额就得填税率'),
    ),
]


def run(path: Path) -> int:
    proc = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return proc.returncode


def main() -> int:
    if run(CHECK) != 0:
        print("前提不成立：源码完好时这条判据就没过（先让 _check_tax_invoices.py 变绿）")
        return 1
    print("前提：源码完好时判据是绿的（" + str(len(CASES)) + " 种破坏方式将逐条注入）")

    fails: list[str] = []
    for label, path, mutate in CASES:
        original_bytes = path.read_bytes()
        original = original_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
        mutated = mutate(original)  # type: ignore[operator]
        if mutated == original:
            fails.append(label + "：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code = run(CHECK)
        finally:
            if path.read_bytes() != original_bytes:
                path.write_bytes(original_bytes)
        if code != 0:
            print("  抓到：" + label)
        else:
            fails.append(label + "：注入之后没有报红 —— 这条判据是空转的")

    if run(CHECK) != 0:
        fails.append("还原之后判据仍然红（有文件没被改回来）")

    print("")
    if fails:
        print("反向验证没通过：")
        for item in fails:
            print("   - " + item)
        return 1
    print(str(len(CASES)) + "/" + str(len(CASES)) + " 种破坏方式全部被抓到，且源码已还原。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
