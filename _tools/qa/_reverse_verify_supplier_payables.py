"""反向验证：把「供应商 / 应付款」那条红线逐条弄坏，看它**真的会红**。

## 为什么这块必须反向验证
供应商这一块坏掉的方式**全部不报错、不崩**：
· 漏一处 `is_deleted` 过滤 → "欠款说没付、收支说付了"（同一笔钱两个答案，两边都不报错）；
· 端点里自己减一遍欠款 → 第二个口径，改口径时只改一处，另一处静默留旧；
· 付款超付 → 欠款变负数（界面上没人读得对）；
· 撤销付款写成"再记一笔反向的钱" → 账上留一对谁也不敢删的行；
· 有付款的应付单能删 → 那笔钱"付出去了、账上没有任何对应的应付款"；
· 删供应商不释放名字 → "删掉再建同名"直接撞唯一约束 500；
· 界面/卡片不写"还差多少" → 用户核对一笔付款时只能凭记忆（而钱付出去撤不回来）；
· 那一格/那两条路由/读能力认领没了 → 用户从界面上根本找不到这个功能。

用法：python _tools/qa/_reverse_verify_supplier_payables.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_supplier_payables.py"

BACKEND = ROOT / "backend/app"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
API = BACKEND / "api/v1/suppliers.py"
SERVICE = BACKEND / "services/supplier_service.py"
FLOW_MODEL = BACKEND / "models/cash_flow.py"
BOOTSTRAP = BACKEND / "core/schema_bootstrap.py"
ENUMS = BACKEND / "models/enums.py"
MODEL = BACKEND / "models/supplier.py"
CASH_API = BACKEND / "api/v1/cash_flows.py"
ORDER_MONEY = BACKEND / "services/order_money.py"
REPORT_CENTER = ANDROID / "ui/dispatcher/ReportCenter.kt"
LIST_SCREEN = ANDROID / "ui/dispatcher/SuppliersScreen.kt"
DETAIL_SCREEN = ANDROID / "ui/dispatcher/SupplierDetailScreen.kt"
MODULES = ANDROID / "ui/nav/Modules.kt"
NAV = ANDROID / "ui/nav/NavGraph.kt"
ROUTES = ANDROID / "ui/nav/Routes.kt"
AI_DECL = ANDROID / "ai/AiWriteSuppliers.kt"
AI_HANDLER = ANDROID / "ai/AiWriteSupplierHandlers.kt"
AI_RES = ANDROID / "ai/AiResources.kt"
AI_CRUD = ANDROID / "ai/AiWriteCrudHandlers.kt"
GUARDRAILS = ROOT / "_tools/ai/_check_ai_guardrails.py"
COVERAGE = ROOT / "_tools/ai/_app_feature_coverage.py"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "① 收支列表/汇总/分组那一处漏掉软删过滤（撤销过的付款照样算支出）",
        CASH_API,
        "    stmt = stmt.where(CashFlow.is_deleted.is_(False))",
        "    stmt = stmt",
        "cash_flows.py 取 cash_flows 时带了 is_deleted 过滤",
    ),
    (
        "② 订单的钱那一处漏掉软删过滤（本项目最贵的「少改一处」形状）",
        ORDER_MONEY,
        "            .where(CashFlow.order_id.in_(ids), CashFlow.is_deleted.is_(False))",
        "            .where(CashFlow.order_id.in_(ids))",
        "order_money.py 的**每一处**取数都带过滤",
    ),
    (
        "③ cash_flows 模型丢掉软删（撤销付款立刻变成物理删除语义）",
        FLOW_MODEL,
        "class CashFlow(Base, TimestampMixin, SoftDeleteMixin):",
        "class CashFlow(Base, TimestampMixin):",
        "cash_flows 模型带软删",
    ),
    (
        "④ 迁移不再回填 0（留 NULL → 历史流水整体从账上消失）",
        BOOTSTRAP,
        'conn.execute(text("UPDATE cash_flows SET is_deleted = 0 WHERE is_deleted IS NULL"))',
        "pass",
        "回填 0",
    ),
    (
        "⑤ 端点里自己减出欠款（第二个口径的起点）",
        API,
        "        unpaid_total=_money(svc.balance_of(due, paid)),",
        "        unpaid_total=_money(due - paid),",
        "端点里不许自己减出欠款",
    ),
    (
        "⑥ 付款不再拦超付（欠款会变成负数，界面上没人读得对）",
        SERVICE,
        "    if amt > left:",
        "    if False:",
        "付款不许超过还差",
    ),
    (
        "⑦ 删供应商时不再释放名字（删掉再建同名 → 撞唯一约束 500）",
        SERVICE,
        "    supplier.name = del_suffix(supplier.name, supplier.id, SUPPLIER_NAME_WIDTH)",
        "    pass",
        "删供应商**释放名字**",
    ),
    (
        "⑧ 有活着的付款也能删应付单（那笔钱对不上任何单据了）",
        SERVICE,
        "    n = payable_payment_count(db, payable.id)\n    if n:",
        "    n = 0\n    if n:",
        "拦的判据是「数出来的笔数 > 0」",
    ),
    (
        "⑨ 撤销付款改走「再记一笔反向的钱」（账上留一对谁也不敢删的行）",
        AI_RES,
        "            paired(\n                AiWrites.SUPPLIER_PAYMENT_CANCEL,",
        "            update(\n                AiWrites.SUPPLIER_PAYMENT_CANCEL,",
        "付款的「撤销 ↔ 恢复」在资源表里**成对**声明",
    ),
    (
        "⑩ 付款卡片上不再写「现在还差」（用户核对一笔付款时只能凭记忆）",
        AI_HANDLER,
        '                    "现在还差：',
        '                    "你自己算还差多少：',
        "卡片上写了「现在还差多少」",
    ),
    (
        "⑪ 超付改成只在后端拒绝（用户点了确认才吃一个错）",
        AI_HANDLER,
        "        if (amountValue > unpaid) {",
        "        if (false) {",
        "超付在**发卡之前**就拒绝（判据就是「这次付的 > 还差」）",
    ),
    # ---- ⑬⑭ 付款的并发闸门（2026-09-23 并发实测：一张 1000 元的单付出去 3000）----
    (
        "⑬ 付款又退回「读一遍余额再判断」（并发下同一张应付单能被付超）",
        SERVICE,
        "            SupplierPayable.amount - paid_sub >= amt,\n",
        "",
        "真闸门是条件 UPDATE（余额判据在 WHERE 里，由数据库串行化）",
    ),
    (
        "⑭ 抢不到行（余额被另一笔用掉）也往下走 —— 等于没占位",
        SERVICE,
        "    if claimed.rowcount != 1:",
        "    if False:",
        "抢不到行 → 回滚 + 说清「刚刚被另一笔付款用掉了/付清了」",
    ),
    (
        "⑫ 读名册方法从白名单里拿掉（prepare 里读一下就被当成「在 prepare 里写库」）",
        GUARDRAILS,
        '    "suppliers", "supplierPayables", "supplierPayments",',
        "",
        "读方法进了 guardrails 的读白名单",
    ),
    (
        "⑬ 界面上自己减出欠款（口径从一处变成两处）",
        LIST_SCREEN,
        "    val owes = s.unpaidTotal.toDoubleOrNull() ?: 0.0",
        "    val owes = (s.payableTotal.toDoubleOrNull() ?: 0.0) - (s.paidTotal.toDoubleOrNull() ?: 0.0)",
        "界面上不许自己减出欠款（`paidTotal` 附近不许出现减号）",
    ),
    (
        "⑭ 删供应商不再给「撤回」（用户定的硬规矩：手边要有撤销入口）",
        LIST_SCREEN,
        '            actionLabel = "撤回",',
        '            actionLabel = "知道了",',
        "删供应商也有「撤回」",
    ),
    (
        "⑮ 账本管理入口页那一格被删（用户从界面上再也找不到它）",
        MODULES,
        'ModuleEntry("供应商/应付", Routes.DISPATCH_SUPPLIERS, Icons.Default.Factory, color = 0xFFAD1457L),',
        "",
        "那一格的颜色与邻居分得开",
    ),
    (
        "⑯ 详情页路由没注册（格子点下去是空白页）",
        NAV,
        "            SuppliersScreen(",
        "            OrderTemplatesScreen(",
        "NavGraph 注册了档案页",
    ),
    (
        "⑰ 付款动作从 HIGH 降成 MEDIUM（钱的动作与改电话同档）",
        AI_DECL,
        "            id = AiWrites.SUPPLIER_PAYMENT_PAY,\n            title = \"给供应商付款\",\n            risk = AiWriteRisk.HIGH,",
        "            id = AiWrites.SUPPLIER_PAYMENT_PAY,\n            title = \"给供应商付款\",\n            risk = AiWriteRisk.MEDIUM,",
        "付款动作是 HIGH",
    ),
    (
        "⑱ 审计动作码从领域词汇表里删掉（审计页只能显示原始码）",
        ENUMS,
        '    SUPPLIER_PAYMENT_CREATE = "SUPPLIER_PAYMENT_CREATE"',
        '    SUPPLIER_PAYMENT_CREATE_X = "SUPPLIER_PAYMENT_CREATE"',
        "动作码 SUPPLIER_PAYMENT_CREATE 进了领域词汇表",
    ),
    (
        "⑲ 审计页那条中文名被删（付款在审计里显示成 SUPPLIER_PAYMENT_CREATE）",
        REPORT_CENTER,
        '    "SUPPLIER_PAYMENT_CREATE" -> "付供应商款"',
        "",
        "审计页有 SUPPLIER_PAYMENT_CREATE 的中文名",
    ),
    (
        "⑳ 名字唯一约束被拿掉（重复档案把同一个供应商的欠款拆成两半）",
        MODEL,
        '    __table_args__ = (Index("uq_suppliers_name", "name", unique=True),)',
        "    __table_args__ = ()",
        "名字唯一",
    ),
    (
        "㉑ 读能力没人认领（能力做出来了、用户在界面上看不到它）",
        COVERAGE,
        '    "供应商/应付": (',
        '    "供应商/应付X": (',
        "读能力被 App 模块认领",
    ),
    (
        "㉒ 设计规范里那条规矩被删（下一个人不知道「付款不是第三张表」这条界线）",
        DESIGN,
        "`_tools/qa/_check_supplier_payables.py`（含反向验证；后端那一半在",
        "（判据脚本名待补）",
        "设计规范里写了这一条规矩",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    p.write_bytes(out)
    return out



def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**（R3-07b）：写回后**重新读回来逐字节比**，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是（L2 要的就是这一句）。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print('⛔ 还原后与快照不一致（注入污染了源码树）：' + str(p))
        raise SystemExit(2)

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
            restore_src(path, src, crlf)
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
