"""反向验证 `_tools/qa/_check_purchase_orders.py`（红线：一次进货 = 库存 + 成本价 + 供应商应付）。

## 为什么必须做

这条判据守的事**坏起来一条报错都不会有**：
单头又落一列合计、改单改成再记一笔冲销、撤行把成本价抹成 0、采购模块自己 insert 一张应付、
写请求失败把半成品留在会话里、成本覆盖表自己再算一遍收入 ——
这些改法都能 import、pytest 也可能照样绿（那时候账已经悄悄错了），只有用户对账时才发现。

所以逐条**注入真缺陷**：每条都必须让判据报红；跑完逐字节还原，并再跑一次确认还原后是绿的。

用法：python _tools/qa/_reverse_verify_purchase_orders.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_purchase_orders.py"

MODEL = ROOT / "backend/app/models/purchase.py"
SERVICE = ROOT / "backend/app/services/purchase_service.py"
API = ROOT / "backend/app/api/v1/purchase_orders.py"
COVERAGE = ROOT / "backend/app/services/reports/cost_coverage_query.py"
REPORTS = ROOT / "backend/app/api/v1/reports.py"
REPORTS_SCHEMA = ROOT / "backend/app/schemas/reports.py"
ROUTER = ROOT / "backend/app/api/v1/router.py"
ENUMS = ROOT / "backend/app/models/enums.py"
SUPPLIERS = ROOT / "backend/app/api/v1/suppliers.py"
TEST = ROOT / "backend/tests/test_purchase_orders.py"

NL = chr(10)
Q = chr(34)


def sub(old: str, new: str, n: int | None = 1):
    """注入：把 old 换成 new（n=None 表示全换）。"""

    def _apply(s: str) -> str:
        return s.replace(old, new) if n is None else s.replace(old, new, n)

    return _apply


CASES: list[tuple[str, Path, object]] = [
    # ================= ① 形状：三条不变量 =================
    (
        "单头又落一列合计（同一个数两处，早晚有一处忘了改）",
        MODEL,
        sub(
            "    items: Mapped[list[PurchaseOrderItem]] = relationship(" ,
            "    total: Mapped[int] = mapped_column(Integer, default=0)" + NL
            + "    items: Mapped[list[PurchaseOrderItem]] = relationship(" ,
        ),
    ),
    (
        "明细又落一列金额（一行行的钱与合计各存一份）",
        MODEL,
        sub(
            "    is_void: Mapped[bool] = mapped_column(Boolean, default=False)",
            "    amount: Mapped[int] = mapped_column(Integer, default=0)" + NL
            + "    is_void: Mapped[bool] = mapped_column(Boolean, default=False)",
        ),
    ),
    (
        "明细不再绑定它写下的那条流水（改单时只能猜是哪一笔）",
        MODEL,
        sub(
            "    movement_id: Mapped[int | None] = mapped_column(" + NL
            + "        ForeignKey(" + Q + "inventory_movements.id" + Q + "), nullable=True, default=None, index=True" + NL
            + "    )",
            "    movement_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None, index=True)",
        ),
    ),
    (
        "撤行改成真删这一行（撤掉的量与原价对不了证）",
        SERVICE,
        sub("    item.is_void = True", "    db.delete(item)"),
    ),
    # ================= ② 建单：三件事一个事务 =================
    (
        "建单不再自动生成那张应付单（欠款没人记）",
        SERVICE,
        sub(
            "    _sync_payable(" + NL
            + "        db, order," + NL
            + "        total=total_of(order.items)," + NL
            + "        supplier=supplier," + NL
            + "        operator_id=operator_id," + NL
            + "    )" + NL
            + "    write_log(",
            "    write_log(",
        ),
    ),
    (
        "加一行不再记成本价（进了货价没变）",
        SERVICE,
        sub(
            "    # 成本价的唯一写入口（它同时更新 products.cost_price 与成本价区间表）" + NL            + "    record_cost(" + NL            + "        db, product, unit_cost," + NL            + "        source=cost_history.SOURCE_PURCHASE," + NL            + "        operator_id=operator_id," + NL            + "        movement_id=mv.id," + NL            + "    )" + NL            + "    return item",
            "    return item",
        ),
    ),
    (
        "入库流水的来源换个名字（流水列表里认不出是采购）",
        SERVICE,
        sub("        source=SOURCE_PURCHASE,", "        source=SOURCE_OTHER,"),
    ),
    (
        "采购模块自己 insert 一张应付单（同一笔欠款两处可改）",
        SERVICE,
        sub(
            "    db.add(order)" + NL + "    db.flush()          # 先拿到 order.id（明细行与流水的备注都要它）",
            "    db.add(order)" + NL
            + "    db.add(SupplierPayable(supplier_id=supplier.id, category=PAYABLE_CATEGORY, amount=_ZERO, operator_id=operator_id))" + NL
            + "    db.flush()          # 先拿到 order.id（明细行与流水的备注都要它）",
        ),
    ),
    (
        "绕过 record_cost 直接给成本价赋值",
        SERVICE,
        sub(
            "    # 成本价的唯一写入口（它同时更新 products.cost_price 与成本价区间表）" + NL            + "    record_cost(" + NL            + "        db, product, unit_cost," + NL            + "        source=cost_history.SOURCE_PURCHASE," + NL            + "        operator_id=operator_id," + NL            + "        movement_id=mv.id," + NL            + "    )" + NL            + "    return item",
            "    product.cost_price = unit_cost" + NL + "    return item",
        ),
    ),
    (
        "金额算两遍（合计自己又写了一遍那个式子）",
        SERVICE,
        sub(
            "    return q2(sum((line_amount(it) for it in items), _ZERO))",
            "    total = _ZERO" + NL
            + "    for it in items:" + NL
            + "        total += q2(Decimal(int(it.quantity or 0)) * Decimal(str(item.unit_cost or 0)))" + NL
            + "    return q2(total)",
        ),
    ),
    # ================= ③ 改单：一行 = 一条流水，改单是改写 =================
    (
        "改单改成再记一笔冲销（同一次进货留下两条流水）",
        SERVICE,
        sub(
            "    mv.change = quantity" + NL + "    mv.unit_cost = unit_cost" + NL + "    mv.status = STATUS_COMMITTED",
            "    db.add(InventoryMovement(product_id=item.product_id, change=quantity, unit_cost=unit_cost, source=SOURCE_PURCHASE, status=STATUS_COMMITTED))" + NL
            + "    mv.change = quantity" + NL + "    mv.status = STATUS_COMMITTED",
        ),
    ),
    (
        "撤行时把成本价写成 0（不是 NULL，报表会读成「成本是 0」）",
        SERVICE,
        sub("    mv.unit_cost = None" + NL + "    mv.status = STATUS_VOID",
            "    mv.unit_cost = Decimal(0)" + NL + "    mv.status = STATUS_VOID"),
    ),
    (
        "恢复时不写回原价（撤了再恢复，价没了）",
        SERVICE,
        sub(
            "    mv.change = item.quantity" + NL + "    mv.unit_cost = item.unit_cost" + NL + "    mv.status = STATUS_COMMITTED",
            "    mv.change = item.quantity" + NL + "    mv.status = STATUS_COMMITTED",
        ),
    ),
    (
        "请求里没给的行不再撤（整单替换的语义丢了）",
        SERVICE,
        sub("        _void_line(db, item, operator_id=operator_id)", "        continue"),
    ),
    (
        "items=None 与空数组合并（只改单头变成把行全撤了）",
        SERVICE,
        sub("    if items is not None:", "    if items:"),
    ),
    # ================= ④ 成本价重算 =================
    (
        "去掉那句 db.flush()（2026-10-04 实测抓到的那个静默缺陷）",
        SERVICE,
        sub("    db.flush()" + NL + "    last = db.scalars(", "    last = db.scalars("),
    ),
    (
        "重算的查询不再排除已脱离的流水",
        SERVICE,
        sub("            InventoryMovement.status != STATUS_VOID," + NL, ""),
    ),
    (
        "守卫只看 last is None（又把 None 递给 record_cost，价被记成 0）",
        SERVICE,
        sub("    if last is None or last.unit_cost is None:", "    if last is None:"),
    ),
    (
        "重算出来的价不再记回去",
        SERVICE,
        sub(
            "    record_cost(" + NL
            + "        db, product, last.unit_cost," + NL
            + "        source=source," + NL
            + "        operator_id=operator_id," + NL
            + "        movement_id=last.id," + NL
            + "    )",
            "    _ = (product, source)",
        ),
    ),
    (
        "脱离那条路不再重算成本价（成本价停在最后一次进货）",
        SERVICE,
        sub("    _reprice_product(db, item.product_id, operator_id=operator_id)", "    _ = item.product_id"),
    ),
    # ================= ⑤ 写请求失败不留半成品 =================
    (
        "写端点报错时不再回滚（半成品留给下一个请求的 commit）",
        API,
        sub(
            "    try:" + NL + "        return fn(db, **kwargs)" + NL + "    except HTTPException:" + NL + "        db.rollback()" + NL + "        raise",
            "    try:" + NL + "        return fn(db, **kwargs)" + NL + "    except HTTPException:" + NL + "        raise",
        ),
    ),
    (
        "改单端点绕开守卫",
        API,
        sub("    order = _write(" + NL + "        psvc.update_order," + NL + "        db,",
            "    order = psvc.update_order(" + NL + "        db,"),
    ),
    # ================= ⑥ 谁能看、谁能改 =================
    (
        "看详情的权限降一档（读的人变少，谁都不报错）",
        API,
        sub(
            "    db: Session = Depends(get_db)," + NL + "    _: User = Reader," + NL + ") -> PurchaseOrderOut:",
            "    db: Session = Depends(get_db)," + NL + "    _: User = Writer," + NL + ") -> PurchaseOrderOut:",
        ),
    ),
    (
        "路由不再挂上去（端点写了但外面看不见）",
        ROUTER,
        sub("api_router.include_router(purchase_orders.router)", "api_router.include_router(suppliers.router)"),
    ),
    (
        "供应商页不再拦采购单生成的应付（这笔欠款又能从供应商页改）",
        SUPPLIERS,
        sub("    psvc.guard_supplier_payable(db, p)", "    _ = p"),
    ),
    # ================= ⑦ 留痕 =================
    (
        "改单留痕换成别的动作码",
        SERVICE,
        sub("        action=OperationAction.PURCHASE_ORDER_UPDATE,", "        action=OperationAction.PURCHASE_ORDER_CREATE,"),
    ),
    (
        "枚举里删掉「恢复」的动作码",
        ENUMS,
        sub("    PURCHASE_ORDER_RESTORE = " + Q + "PURCHASE_ORDER_RESTORE" + Q + NL, ""),
    ),
    (
        "留痕只剩 after（丢了 before，改前什么样查不到）",
        SERVICE,
        sub("{" + Q + "before" + Q + ": before, " + Q + "after" + Q + ": _snapshot(order)}", "_snapshot(order)", None),
    ),
    # ================= ⑧ 成本覆盖表 =================
    (
        "覆盖表又自己算一遍「算不出成本的收入」（同一个数两处）",
        COVERAGE,
        sub("        " + Q + "revenue_uncovered" + Q + ": revenue_total - revenue_covered,",
            "        " + Q + "revenue_uncovered" + Q + ": turnover[" + Q + "total_amount" + Q + "] - turnover[" + Q + "cost_covered_amount" + Q + "],"),
    ),
    (
        "覆盖表自己判「有没有成本价」（碰 cost_basis）",
        COVERAGE,
        sub("_ZERO = Decimal(" + Q + "0" + Q + ")",
            "from app.services.cost_basis import cost_basis  # 自己判成本" + NL + NL + "_ZERO = Decimal(0)"),
    ),
    (
        "收入那一侧不再复用上游的窗口（各算各的时段）",
        COVERAGE,
        sub("    turnover = build_turnover(db, mode, anchor, span=span)", "    turnover = build_turnover(db, mode, anchor)"),
    ),
    (
        "「没记过进货价」改看商品台账那一列（不看流水）",
        COVERAGE,
        sub("        InventoryMovement.unit_cost.isnot(None),", "        Product.cost_price.isnot(None),"),
    ),
    (
        "口径说明里出现 markdown 星号",
        COVERAGE,
        sub("    " + Q + "下面那份清单是", "    " + Q + "**下面那份清单**是"),
    ),
    (
        "说明里不再写清两份清单不是一回事",
        COVERAGE,
        sub("它不等于上面那笔收入的来源", "它就是上面那笔收入的来源"),
    ),
    (
        "商品清单的键不再对上出参模型",
        COVERAGE,
        sub("            " + Q + "is_active" + Q + ": bool(p.is_active),", "            " + Q + "active" + Q + ": bool(p.is_active),"),
    ),
    (
        "出参模型少一个字段（说了要给却给不出来）",
        REPORTS_SCHEMA,
        sub("    missing_purchase_price: list[CostCoverageProduct] = []" + NL, ""),
    ),
    (
        "端点不再丢掉内部键 _window（它不该出现在接口上）",
        REPORTS,
        sub("    data.pop(" + Q + "_window" + Q + ", None)" + NL + "    return CostCoverageReportOut(**data)",
            "    return CostCoverageReportOut(**data)"),
    ),
    # ================= ⑨ 单测钉住的那几条 =================
    (
        "「改单是改写那条流水」的单测被删掉",
        TEST,
        sub("def test_改数量与单价_改写那条流水而不是再记一笔(", "def test_改数量与单价_顺手改改("),
    ),
    (
        "恒等式 helper 被改名（Σ流水 == 库存 那条没人钉了）",
        TEST,
        sub("_assert_identity", "_check_stock_identity", None),
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
        print("前提不成立：源码完好时这条判据就没过（先让 _check_purchase_orders.py 变绿）")
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
