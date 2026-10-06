"""反向验证：把 CHG-0071（台账 L-34 打折 / 商品「不参与打折」）的红线逐条弄坏，看它们**真的会红**。

为什么这块必须反向验证：这条红线几乎全是「没报错但也没发生」的毛病 ——
  · 折扣算法被抄成第二份（两处迟早算出两个数，用户在两个页面看到两种优惠）；
  · 退货改回按 unit_price 退（打过折的行**退得比收的多**，账上凭空多出钱）；
  · 明细改完忘了重摊（Σ 行金额 ≠ 折后总额，账本与详情页对不上）；
  · 出参只清 discount_amount 却留下 discount_lines（司机拿逐行 before/after 一减就还原货款）；
  · 客户端把 no_discount 当成「价格锁」，或自己拿金额乘一遍（用户口径 m01347 明确否掉前者）。
判据里还有一半是「扫全仓 / 扫常量」（算法只有一处、三处能打折的状态字面一致），
清单如果不验证，就可能因为「目录扫不到 / 集合是空的」而永远绿。所以每一条都要有对应的破坏用例。

用法：python _tools/qa/_reverse_verify_order_discount.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_order_discount.py"

BACK = ROOT / "backend/app"
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

MONEY = BACK / "services/order_money.py"
RETURN = BACK / "services/order_return.py"
CONTRACT = BACK / "services/money_contract.py"
RESPONSE = BACK / "services/order_response.py"
ORDER_MODEL = BACK / "models/order.py"
PRODUCT_MODEL = BACK / "models/product.py"
MIGRATION = BACK / "migrations/025_order_discount.py"
BOOTSTRAP = BACK / "core/schema_bootstrap.py"
ENDPOINT = BACK / "api/v1/orders_discount.py"
ROUTER = BACK / "api/v1/router.py"
LINES = BACK / "api/v1/order_products.py"
ENUMS = BACK / "models/enums.py"
COVERAGE = BACK / "core/capability_audit_coverage.py"
KT_LOGIC = AND / "ui/order/OrderDiscount.kt"
KT_VM = AND / "ui/order/OrderDetailViewModel.kt"
KT_DETAIL = AND / "ui/order/OrderDetailScreen.kt"
KT_DTOS = AND / "data/remote/dto/Dtos.kt"
KT_APIS = AND / "data/remote/api/Apis.kt"
KT_REPO = AND / "data/repo/AppRepository.kt"
KT_FORM = AND / "ui/dispatcher/ProductFormScreen.kt"
KT_FORM_VM = AND / "ui/dispatcher/ProductFormViewModel.kt"

SQ = chr(39)

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "money 层自己又算了一遍折扣（第二个实现点）",
        MONEY,
        "def line_unit_price(op: OrderProduct) -> Decimal:",
        "def _discount_amount_of(order) -> Decimal:\n    return Decimal(getattr(order, \"discount_amount\", 0) or 0)\n\n\ndef line_unit_price(op: OrderProduct) -> Decimal:",
        "谁都不能再算一遍",
    ),
    (
        "orders.discount_amount 变成 NOT NULL（历史订单一律为空）",
        ORDER_MODEL,
        "discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True, default=None)",
        "discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=False, default=None)",
        "可为空",
    ),
    (
        "商品档案上那个勾被删了（勾不到「不参与打折」）",
        PRODUCT_MODEL,
        "no_discount: Mapped[bool] = mapped_column(Boolean, default=False)",
        "no_discount_removed: Mapped[bool] = mapped_column(Boolean, default=False)",
        "商品上那个勾是布尔列",
    ),
    (
        "迁移版本号被改成 26（老库上永远跑不到这一版）",
        MIGRATION,
        "VERSION = 25",
        "VERSION = 26",
        "版本号 25",
    ),
    (
        "老库补列偷偷写回 schema_bootstrap（正式迁移被绕过）",
        BOOTSTRAP,
        "                    conn.execute(text(\"ALTER TABLE orders ADD COLUMN collect_cash BOOLEAN DEFAULT 0\"))",
        "                    conn.execute(text(\"ALTER TABLE orders ADD COLUMN collect_cash BOOLEAN DEFAULT 0\"))\n                    conn.execute(text(\"ALTER TABLE orders ADD COLUMN discount_kind VARCHAR(16)\"))",
        "核心区 schema_bootstrap",
    ),
    (
        "钱契约里少了「订单打折」这条钱数（折扣不再是一等公民）",
        CONTRACT,
        "    Figure(\n        key=\"order_discount\",\n        name=\"订单打折（百分比 / 抹零）省下的钱与折后行金额\",\n        meaning=(\n            \"折扣只由派单员在改单时打（Permission.ORDER_EDIT）；整单或只打勾选的行；\"\n            \"按分四舍五入 + 余数摊回各行 ⇒ Σ 折后行金额 = 折后总额（用户口径 ref m01280 / m01347）\"\n        ),\n        impls=(\n            \"services/order_discount.py::apply_discount\",\n            \"services/order_discount.py::clear_discount\",\n            \"services/order_discount.py::plan_discount\",\n            \"services/order_discount.py::reapply_after_line_change\",\n        ),\n        consumers=(\n            \"api/v1/orders_discount.py\",\n            \"api/v1/order_products.py\",\n        ),\n        # 这四个函数**不**转出（REEXPORTS 里没有）：折扣是订单域内部的一步计算，\n        # 转出会把「打折」变成跨域接口；详情页要的折后单价走 order_money.line_unit_price。\n        forbid=(),\n    ),",
        "",
        "order_discount 这条钱数",
    ),
    (
        "折后单价被转出成跨域接口",
        CONTRACT,
        "    \"money_of\": (\"app.services.order_money\", \"money_of\"),",
        "    \"line_unit_price\": (\"app.services.order_money\", \"line_unit_price\"),\n    \"money_of\": (\"app.services.order_money\", \"money_of\"),",
        "折后单价不进 REEXPORTS",
    ),
    (
        "折扣这条钱数改成要转出（把打折变成跨域接口）",
        CONTRACT,
        "forbid=(),",
        "forbid=((\"discount_x\", \"x\", \"x\"),),",
        "折扣这条不转出",
    ),
    (
        "退货又按 unit_price 退（退得比收的多）",
        MONEY,
        "    returned = line_unit_price(op) * Decimal(int(op.returned_quantity or 0))",
        "    returned = (op.unit_price or ZERO) * Decimal(int(op.returned_quantity or 0))",
        "退货的钱走折后单价",
    ),
    (
        "退货服务改回按 unit_price 算",
        RETURN,
        "    return (line_unit_price(op) * Decimal(qty)).quantize(Decimal(\"0.0001\"), rounding=ROUND_HALF_UP)",
        "    return ((op.unit_price or ZERO) * Decimal(qty)).quantize(Decimal(\"0.0001\"), rounding=ROUND_HALF_UP)",
        "退货金额按折后单价算",
    ),
    (
        "取消折扣改成 POST（两个同路径端点撞车）",
        ENDPOINT,
        "@router.delete(\"/{order_id}/discount\", response_model=OrderOut)",
        "@router.post(\"/{order_id}/discount\", response_model=OrderOut)",
        "取消折扣端点",
    ),
    (
        "没折扣也放行取消（审计里分不出真假）",
        ENDPOINT,
        "    if not has_discount(order):\n        raise HTTPException(status_code=400, detail=\"这一单本来就没有折扣。\")",
        "if False:\n        raise HTTPException(status_code=400, detail=\"这一单本来就没有折扣。\")",
        "没折扣就别取消",
    ),
    (
        "并发占位那条条件 UPDATE 被删掉",
        ENDPOINT,
        "    claimed = db.execute(\n        update(Order)\n        .where(\n            Order.id == order.id,\n            Order.status.in_(LINE_EDITABLE_STATUSES),\n            Order.deleted_at.is_(None),\n        )\n        .values(updated_at=utc_now_naive())\n    )",
        "    claimed = None",
        "条件 UPDATE 占位",
    ),
    (
        "取消折扣那把钥匙换成只读权限",
        ENDPOINT,
        "def clear_order_discount(\n    order_id: int,\n    db: Session = Depends(get_db),\n    current: User = Depends(require_permission(Permission.ORDER_EDIT)),",
        "def clear_order_discount(\n    order_id: int,\n    db: Session = Depends(get_db),\n    current: User = Depends(require_permission(Permission.ORDER_VIEW)),",
        "两个端点都要 ORDER_EDIT",
    ),
    (
        "router.py 不再挂这个模块",
        ROUTER,
        "api_router.include_router(orders_discount.router)",
        "# api_router.include_router(orders_discount.router)",
        "挂上了这个模块（include）",
    ),
    (
        "取消折扣的动作码被改名（审计认不出）",
        ENUMS,
        "ORDER_DISCOUNT_CLEAR = \"ORDER_DISCOUNT_CLEAR\"",
        "ORDER_DISCOUNT_CLEAR_X = \"ORDER_DISCOUNT_CLEAR\"",
        "动作码：取消折扣",
    ),
    (
        "审计覆盖表里删掉这两个码",
        COVERAGE,
        "'ORDER_DISCOUNT', 'ORDER_DISCOUNT_CLEAR',",
        "",
        "审计覆盖表里认得出打折与取消",
    ),
    (
        "价格规则表上长出折扣列",
        PRODUCT_MODEL,
        "class PriceRule(Base, TimestampMixin, SoftDeleteMixin):",
        "class PriceRule(Base, TimestampMixin, SoftDeleteMixin):\n    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)",
        "折扣也不长在价格规则模型上",
    ),
    (
        "改行之后忘了重摊（Σ 行金额 ≠ 折后总额）",
        LINES,
        "        reapply_after_line_change(db, order=order, edited_line=op)",
        "        pass",
        "改行之后重摊",
    ),
    (
        "删行之后忘了重摊（快照一直说一个不存在的优惠）",
        LINES,
        "            reapply_after_line_change(db, order=order, edited_line=None)",
        "            pass",
        "删行之后重摊",
    ),
    (
        "行金额不再由单价 × 数量定（客户端说多少就多少）",
        LINES,
        "            op.line_total = resolve_line_total(new_up, new_qty, body.line_total)",
        "            op.line_total = Decimal(body.line_total or 0)",
        "那一行逐字保留",
    ),
    (
        "折扣金额不再归到货款那一档（司机判据会自算）",
        RESPONSE,
        "    # 见 [DISCOUNT_FIELDS] 与 [apply_driver_view_gating]。\n    \"discount_amount\",\n)",
        "    # 见 [DISCOUNT_FIELDS] 与 [apply_driver_view_gating]。\n)",
        "折扣金额归到",
    ),
    (
        "司机视角只清折扣金额一个数（其余七格照发）",
        RESPONSE,
        "for _discount_field in DISCOUNT_FIELDS:",
        "for _discount_field in (\"discount_amount\",):",
        "整块清",
    ),
    (
        "装配时不再查是谁打的折",
        RESPONSE,
        "            data[\"discount_by_name\"] = discount_user.full_name or dialable_phone(discount_user)",
        "            discount_user.full_name or dialable_phone(discount_user)",
        "谁打的折在装配时查出来",
    ),
    (
        "客户端把可打折状态少写一档（ACCEPTED 打不了折）",
        KT_LOGIC,
        "val DISCOUNT_STATUSES: Set<String> = setOf(\"PENDING_DISPATCH\", \"DISPATCHED\", \"ACCEPTED\")",
        "val DISCOUNT_STATUSES: Set<String> = setOf(\"PENDING_DISPATCH\", \"DISPATCHED\")",
        "客户端能打折的状态与后端字面一致",
    ),
    (
        "客户端自己拿金额乘一遍（两个实现点）",
        KT_LOGIC,
        "    return \"已优惠 ¥\" + formatMoney(order.discountAmount)",
        "    return \"已优惠 ¥\" + formatMoney(order.discountAmount) + ((order.discountAmount?.toBigDecimalOrNull() ?: java.math.BigDecimal.ZERO) * java.math.BigDecimal.ONE).toPlainString()",
        "客户端不自己算折扣",
    ),
    (
        "详情页把「已优惠」那段挪到挂账那颗按钮之前（既有 900 字符窗口被挤）",
        KT_DETAIL,
        "                onDiscountClick = { vm.openDiscount() },",
        "                onDiscountClick = { vm.openDiscount() },\n                savedDiscountProbe = { val savedDiscount = discountHeadline(order) },",
        "折扣那一段插在",
    ),
    (
        "客户端 DTO 少了「谁打的折」",
        KT_DTOS,
        "    @SerialName(\"discount_by_name\") val discountByName: String? = null,",
        "    @SerialName(\"discount_by_name_x\") val discountByNameX: String? = null,",
        "DTO 认得 discount_by_name",
    ),
    (
        "Retrofit 层少了取消折扣端点",
        KT_APIS,
        "@DELETE(\"orders/{orderId}/discount\")",
        "@GET(\"orders/{orderId}/discount\")",
        "Retrofit 取消折扣端点",
    ),
    (
        "仓库层不再转发取消折扣",
        KT_REPO,
        "suspend fun clearOrderDiscount(orderId: Long) = api.orderApi.clearOrderDiscount(orderId)",
        "suspend fun clearOrderDiscountX(orderId: Long) = api.orderApi.clearOrderDiscount(orderId)",
        "仓库层转发取消",
    ),
    (
        "商品编辑页少了「不参与打折」开关",
        KT_FORM,
        "label = \"不参与打折\",",
        "label = \"参与打折\",",
        "商品编辑页有那个开关",
    ),
    (
        "商品表单每次整份回传（没改也发）",
        KT_FORM_VM,
        "    val noDiscountOut = if (d.noDiscount != baseline.noDiscount) { dirty = true; d.noDiscount } else null",
        "    val noDiscountOut = d.noDiscount",
        "只有改过才发",
    ),
    (
        "发出去之前先把值格式化（12.3456 被抹成 12.35）",
        KT_VM,
        "                        value = discountValueToSend(discountValue),\n                        lineIds = if (discountWholeOrder) null else discountPickedLines.sorted(),\n                        reason = discountReason.trim().ifBlank { null },\n                    ),\n                )\n                actionResult = \"已打折：\" + discountSummary(discountKind, discountValueToSend(discountValue))",
        "                        value = formatMoney(discountValue),\n                        lineIds = if (discountWholeOrder) null else discountPickedLines.sorted(),\n                        reason = discountReason.trim().ifBlank { null },\n                    ),\n                )\n                actionResult = \"已打折：\" + discountSummary(discountKind, formatMoney(discountValue))",
        "发出去的值不做格式化",
    ),
]


def read_src(p: Path):
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
    # 还原**当场核对**：写回后重新读回来逐字节比，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        raise SystemExit(2)


def run_check():
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str):
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    detail = "实际红 " + str(len(fails)) + " 条"
    if not hit:
        detail += "：" + str([f.strip()[:70] for f in fails[:2]])
    return hit, detail


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线没过\n" + out[-1200:])
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print("  [SKIP] " + label + " —— 原文出现 " + str(src.count(old)) + " 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            hit, detail = verdict(expect)
        finally:
            restore_src(path, src, crlf)
        tag = "OK" if hit else "MISS"
        print("  [" + tag + "] " + label + " → " + detail)
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    print()
    if bad:
        print("❌ " + str(bad) + "/" + str(total) + " 条不成立（红线对它们不敏感）")
        return 1
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
