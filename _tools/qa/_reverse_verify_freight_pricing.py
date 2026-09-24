"""反向验证：把「运费怎么算」这条红线逐条弄坏，看它**真的会红**（价目归规则的新口径）。

用法：python _tools/qa/_reverse_verify_freight_pricing.py
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = Path(__file__).resolve().parent / "_check_freight_pricing.py"
APP = ROOT / "backend/app"
KT = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

PRICING = APP / "services/freight_pricing.py"
PAY = APP / "services/driver_pay.py"
RULES_API = APP / "api/v1/driver_billing_rules.py"
RULE_SCHEMA = APP / "schemas/driver_billing_rule.py"
CAT_API = APP / "api/v1/freight_categories.py"
TPL_API = APP / "api/v1/freight_templates.py"
ORDERS = APP / "api/v1/orders.py"
#: orders 的**查询组**（2026-09-24 整改阶段 4 纯搬迁：列表/待派计数/详情搬去了 orders_query.py）
ORDERS_Q = APP / "api/v1/orders_query.py"
USERS_KT = KT / "ui/dispatcher/UsersManageScreen.kt"
TPL_KT = KT / "ui/dispatcher/FreightTemplatesScreen.kt"
RULE_KT = KT / "ui/dispatcher/DriverBillingRulesScreen.kt"
UNPRICED_KT = KT / "ui/dispatcher/FreightPricingScreens.kt"
REPORT_KT = KT / "ui/dispatcher/ReportCenter.kt"

MUTATIONS = [
    (
        "候选不按规则过滤了（规则白勾：司机拿别人的价目）",
        PRICING,
        "        stmt = stmt.where(FreightTemplate.id.in_(picked_template_ids))",
        "        stmt = stmt",
        "候选先按「规则勾的价目」过滤",
    ),
    (
        "没挂规则也照常给价（用户以为配好了）",
        PRICING,
        '                reason="这个司机还没挂计费规则 —— 运费是从「他的规则勾了哪几条价目」来的，"',
        '                reason="ok"',
        "没挂规则 → 说清原因",
    ),
    (
        "匹配里又去看司机绑定（价目归规则这条链断了）",
        PRICING,
        "def _category_map(db: Session, templates: list[FreightTemplate]) -> dict[int, list[int]]:",
        "def _driver_map(db, templates):\n    from app.models import FreightTemplateDriver\n    return {}\n\n\ndef _category_map(db: Session, templates: list[FreightTemplate]) -> dict[int, list[int]]:",
        "匹配里**不许**看司机绑定",
    ),
    (
        "多条同样优先时随便取一条（运费看运气）",
        PRICING,
        "    if len(same) > 1:",
        "    if False:",
        "多条同样优先 → **不猜**",
    ),
    (
        "路线不认地点库了（改成永不命中）",
        PRICING,
        "        db.scalars(select(ShipperAddress.id).where(ShipperAddress.detail_address == addr)).all()",
        "        db.scalars(select(ShipperAddress.id).where(ShipperAddress.id < 0)).all()",
        "路线判据来自**地点库的线路**",
    ),
    (
        "挂一个不存在的分类也收下（那条价目永远匹配不到）",
        TPL_API,
        '        missing = [i for i in wanted if i not in found]\n        if missing:\n            raise HTTPException(status_code=400, detail=f"这些运费分类不存在：{missing}")',
        "        missing = []",
        "挂一个不存在的分类会被拒",
    ),
    (
        "删除分类时不管还有没有人在用",
        CAT_API,
        "    if used_t or used_r:",
        "    if False:",
        "删除还有人在用时**拒绝**",
    ),
    (
        "改分类名顺手级联改价目（按编号挂的，级联会改错）",
        CAT_API,
        "    changes: list[dict] = []",
        "    FreightTemplate.__table__.update().values(name=body.name)\n    changes: list[dict] = []",
        "改分类名**不级联**",
    ),
    (
        "勾了不存在的价目也收下（那条规则永远匹配不到运价）",
        RULES_API,
        '    missing = [i for i in uniq if i not in found and i not in stale]\n    if missing:',
        "    missing = []\n    if missing:",
        "勾了不存在的价目会被拒",
    ),
    (
        "按分类定价时又允许填统一的每单金额（填了不生效）",
        RULE_SCHEMA,
        '        if Decimal(str(p.get("piece_amount") or 0)) > 0 or Decimal(str(p.get("commission_rate") or 0)) > 0:',
        "        if False:",
        "按分类时**不许**再填统一的每单金额",
    ),
    (
        "按分类的规则不算「有按单应付」→ 账单都不生成",
        PAY,
        "        if self.by_category_pay:\n            return True\n",
        "",
        "按分类的规则**必须算「有按单应付」**",
    ),
    (
        "逐单覆盖的比例被规则默认值盖掉",
        PAY,
        "    rate = money(rate_override) if rate_override is not None else base_rate",
        "    rate = rule.commission_rate",
        "逐单覆盖仍然优先",
    ),
    (
        "沉淀出来的价目不勾进司机的规则（「下次自动带价」是假的）",
        ORDERS,
        "                db.add(DriverBillingRuleTemplate(rule_id=int(rule_id), template_id=tmpl.id))",
        "                pass",
        "沉淀出来的价目**自动勾进这位司机的规则**",
    ),
    (
        "手动定价顺手改异常标记（异常页再也看不清）",
        ORDERS,
        "    order.freight_fee = body.freight_fee\n    order.freight_category_id = body.category_id",
        "    order.is_exception = True\n    order.freight_fee = body.freight_fee\n    order.freight_category_id = body.category_id",
        "手动定价那一段里没有 `is_exception = True`",
    ),
    (
        "待定价不再看运费是否为空（列表变成全部单）",
        ORDERS_Q,
        "                Order.freight_fee.is_(None),",
        "                Order.freight_fee.isnot(None),",
        "两条查询路径上都写全了",
    ),
    (
        "unpriced 过滤只留在一条查询路径上（待定价页会静默返回全部单）",
        ORDERS_Q,
        "    if unpriced:\n        q = q.where(",
        "    if False:\n        q = q.where(",
        "两条",
    ),
    (
        "司机编辑页又长出「固定工资」（同一个数两处写）",
        USERS_KT,
        "                        // ---- 计费规则：**他怎么算钱只有这一个入口**（2026-09-21）----",
        '                        SoTextField("", {}, placeholder = "固定工资（元/月）")\n'
        "                        // ---- 计费规则：**他怎么算钱只有这一个入口**（2026-09-21）----",
        "编辑弹窗里**没有**「固定工资」输入框",
    ),
    (
        "运费模板表单又长出车型/司机（价目不匹配它们）",
        TPL_KT,
        # ⚠️ 锚点跟着实现走（2026-09-23 静态审计抓到它已腐烂）：那句文案从 `Text(\n …)` 改成
        #    了 `Hint("…")` 的一个实参（提示语统一走 Hint），缩进也从 20 变 12。
        #    注入要表达的是"表单里冒出「适用车型」那一段"，所以锚 `Hint(` 那一行、
        #    把 `Text("适用车型")` 插在它前面（判据找的就是 `Text\("适用车型"\)`）。
        '        Hint(\n            "这条价目归「计费规则」勾选使用 —— 车型与司机在计费规则里匹配，不在这里。",\n',
        '        Text("适用车型")\n'
        '        Hint(\n            "这条价目归「计费规则」勾选使用 —— 车型与司机在计费规则里匹配，不在这里。",\n',
        "运费模板表单里**没有**车型与司机两段",
    ),
    (
        "价目选择器退回手输编号（不再是选品页那种勾选）",
        RULE_KT,
        '                TextButton(onClick = { vm.toggleWholeTab() }) { Text("全选本分类") }',
        "",
        "App 有选品页那种价目选择器",
    ),
    (
        "卡片按钮又单独占一行、不再跟信息同排（卡片白白高一行，用户点名要贴最右）",
        RULE_KT,
        "        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {",
        "        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {",
        "计费规则卡片：同上",
    ),
    (
        "定价时不问司机规则了（直接让派单员从零手填）",
        UNPRICED_KT,
        "quoteFreight(o.id, driverId = o.driverId",
        "quoteFreight(o.id, driverId = null",
        "先按这位司机的规则",
    ),
    (
        "新审计码没有中文名（审计卡片上显示原始码）",
        REPORT_KT,
        '    "ORDER_FREIGHT_PRICE" -> "手动定价运费"',
        '    "ORDER_FREIGHT_PRICE_X" -> "手动定价运费"',
        "新的审计码有中文名",
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


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时这一节红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            code, out = run_check()
            fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            hit = code != 0 and any(expect in ln for ln in fails)
            detail = f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")
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
