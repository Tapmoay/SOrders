"""订单打折（CHG-0071 / 台账 L-34）：整单 / 选行的百分比或抹零折扣 + 商品「不参与打折」。

## 用户原话（2026-10-06，台账 L-34，ref m01280）
「我们要加个新功能就是**商品可以打折**，就是**订单它可以给订单进行打折**，然后我们
**对应的商品是可以固定价格的，就是不参与打折**。」
口径三条（ref m01347）：① 入口只有派单员改单（`Permission.ORDER_EDIT`），货主下单不能打折；
② 两种表达都要（百分比 / 抹零）；③ 商品级勾选叫「不参与打折」，语义只是"算折扣时跳过它"，
**价格照旧能改**（⛔ 不是"固定价"，⛔ 不长在批发商专属价 `PriceRule` 上）；
④ 粒度两档（整单 / 只勾几行）。退货口径（ref m13365）：**按折后实付退**。

## 机制（这一条为什么不是"加一个字段、乘一下"）
1. 钱落在**行**上：`goods_amount = Σ line_total`（`schemas/order.py` 的恒等式被
   `tests/test_order_return.py` 钉着）。整单减 5 元必须真的摊成"第一行少 1.37、第二行少 1.63"，
   否则账本 / 营业额 / 毛利与 `goods_amount` 当场对不上。
2. **不能反推**：行金额是"按分四舍五入 + 余数摊回"的结果，抹零还会被合计封顶 ——
   `discount_value` 反推不出 `discount_amount`，所以七列快照必须一起落。
3. 退货必须改口径：`order_money.line_receivable` 原来按 `unit_price` 乘退货数量算，
   打过折的行会**退得比收的多**（单价没变、实付变少了）。
4. 明细变了就得重摊：改数量 / 改单价 / 删行之后，`line_total` 会被"单价 × 数量"重算，
   快照里的折扣还是老的 —— 不重摊，详情页会一直说"减了 X 元"而钱已经变了。

## 为什么这条必须有机器的判据
这一条**全是"没报错但钱错了"的毛病**，模拟器上点一遍看起来完全正常：
- 谁都可以在第二个文件里再算一遍 `discount_amount`（编译器非常乐意，两边还会"差不多"）；
- 谁都可以把 `line_total = 单价 × 数量` 那一行留在改明细里（折扣被静默抹掉）；
- 谁都可以只把 `discount_amount` 给司机清掉，留下 `discount_lines` 里逐行的原价 / 折后价；
- 谁都可以让"取消折扣"按**现在的价**重算一遍（数字看着也对，就是与打折前差几毛）；
- 谁都可以把 `no_discount` 做成"价格不能改"（用户说的不是这个意思）。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
缺的那一层是**"钱只算一次"这个跨模块约定**与**行金额的重算顺序**：
折扣算法是一个普通纯函数，任何模块都能 import 它、也能自己写一份等价的；
"行金额由单价 × 数量定，然后折扣作用在它现在的金额上"是**调用顺序**，
类型系统看不见谁先谁后（两次赋值都能编译，结果差一个折扣）；
"司机看不到货款口径"是**出参装配**的约定，`OrderOut` 上多一个字段不会有任何提示；
"不参与打折"的商品勾选是**数据语义**，把它当成"价格锁"在类型上完全一样。
所以判据只能钉在源码结构与常量上：算法只许出现在一个文件、明细路径必须先重算再重摊、
出参八格整块清零、以及三处"能打折的状态"必须字面一致。
反向破坏用例见 _reverse_verify_order_discount.py
（换个文件再算一遍 / 去掉重摊 / 去掉门控 / 让取消折扣按现价重算 / 把 no_discount 当成价格锁 …
 + 还原后逐字节比对）。
静默空转保护：MIN_PY = 120、MIN_KT = 100，与"必须数到那几个关键文件"
（目录被搬走就红，不许"扫了 0 个也全绿"）。

## 判据（每条都能被反向验证弄红）
1. 折扣算法**全库只有一处**：`backend/app/services/order_discount.py`；提到 `discount_amount` /
   `discount_kind` 的后端文件只有那张白名单（多一个就红）；客户端一个乘法都不做；
2. 七列快照齐全且都是 nullable（kind / value / amount / lines / reason / by_id / at），
   老库由**正式迁移** `migrations/025_order_discount.py` 补列（⛔ 不写 schema_bootstrap）；
3. 钱契约新增第 6 条 Figure `order_discount`（4 个 impl + 2 个消费方），
   `order_money.line_unit_price` 挂在 order_money 那条的 impls 上且**不**转出；
4. 退货按折后实付退：`order_money.line_unit_price` 用 `line_total / quantity`，
   `line_receivable` 与 `order_return._line_amount` 都走它；
5. 端点：`POST` / `DELETE /orders/{order_id}/discount` + `Permission.ORDER_EDIT` +
   可编辑状态门 + `lock_order_row` + 条件 UPDATE 占位 + 两个动作码各一条审计；
6. 明细改动后重摊：`op.line_total = resolve_line_total(...)` **逐字保留**，紧跟一次
   `reapply_after_line_change`（改行带 `edited_line=op`，删行带 `edited_line=None`）；
7. 出参：`discount_amount` 归 `CUSTOMER_GOODS_FIELDS`（名字像钱），司机视角**整块**八格清零；
8. 客户端：值校验在本地判一次、服务端再判一次（文字不重写算法）；三处"能打折的状态"
   字面一致；商品表单有「不参与打折」开关，且草稿差异只带改过的键。

用法：python _tools/qa/_check_order_discount.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACK = ROOT / "backend/app"
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders"

SERVICE = BACK / "services/order_discount.py"
MONEY = BACK / "services/order_money.py"
RETURN = BACK / "services/order_return.py"
CONTRACT = BACK / "services/money_contract.py"
RESPONSE = BACK / "services/order_response.py"
ORDER_MODEL = BACK / "models/order.py"
PRODUCT_MODEL = BACK / "models/product.py"
ENUMS = BACK / "models/enums.py"
COVERAGE = BACK / "core/capability_audit_coverage.py"
BOOTSTRAP = BACK / "core/schema_bootstrap.py"
MIGRATION = BACK / "migrations/025_order_discount.py"
ENDPOINT = BACK / "api/v1/orders_discount.py"
ROUTER = BACK / "api/v1/router.py"
LINES = BACK / "api/v1/order_products.py"
ORDER_SCHEMA = BACK / "schemas/order.py"
PRODUCT_SCHEMA = BACK / "schemas/product.py"
PRICE_RULES = BACK / "api/v1/price_rules.py"
PY_TEST = ROOT / "backend/tests/test_order_discount.py"
GATING_TEST = ROOT / "backend/tests/test_order_out_driver_pay_gating.py"

KT_LOGIC = AND / "ui/order/OrderDiscount.kt"
KT_LOGIC_TEST = TEST / "ui/order/OrderDiscountTest.kt"
KT_DIALOG = AND / "ui/order/OrderDiscountDialog.kt"
KT_DETAIL = AND / "ui/order/OrderDetailScreen.kt"
KT_VM = AND / "ui/order/OrderDetailViewModel.kt"
KT_DTOS = AND / "data/remote/dto/Dtos.kt"
KT_APIS = AND / "data/remote/api/Apis.kt"
KT_REPO = AND / "data/repo/AppRepository.kt"
KT_STATUS = AND / "core/OrderStatusModel.kt"
KT_FORM = AND / "ui/dispatcher/ProductFormScreen.kt"
KT_FORM_VM = AND / "ui/dispatcher/ProductFormViewModel.kt"
KT_DIFF_TEST = TEST / "ui/dispatcher/ProductFormDiffTest.kt"

#: 全仓至少要有这么多 .py / .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_PY = 120
MIN_KT = 100

#: 必须真的数到这几个文件（少一个就说明目录结构变了，判据要跟着改）。
REQUIRED_FILES = [SERVICE, MONEY, RETURN, CONTRACT, RESPONSE, ORDER_MODEL, PRODUCT_MODEL,
                  MIGRATION, ENDPOINT, ROUTER, LINES, ORDER_SCHEMA, PY_TEST]
REQUIRED_KT = [KT_LOGIC, KT_LOGIC_TEST, KT_DIALOG, KT_DETAIL, KT_VM, KT_FORM, KT_FORM_VM]

#: 允许提到折扣列的后端文件（多一个 ⇒ 有人又在别处算了一遍/抄了一份快照）。
DISCOUNT_FIELD_ALLOWLIST = {
    "services/order_discount.py",
    "models/order.py",
    "migrations/025_order_discount.py",
    "schemas/order.py",
    "services/order_response.py",
}

#: 七列快照（列名 → 模型里的声明片段）。
SNAPSHOT_COLUMNS = {
    "discount_kind": "discount_kind: Mapped[str | None] = mapped_column(String(16)",
    "discount_value": "discount_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4)",
    "discount_amount": "discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 4)",
    "discount_lines": "discount_lines: Mapped[list[Any] | None] = mapped_column(JSON",
    "discount_reason": "discount_reason: Mapped[str | None] = mapped_column(String(255)",
    "discount_by_id": "discount_by_id: Mapped[int | None] = mapped_column(ForeignKey(\"users.id\")",
    "discount_at": "discount_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)",
}

#: 出参上给司机整块清零的八格。
DISCOUNT_FIELDS = ("discount_kind", "discount_value", "discount_amount", "discount_lines",
                   "discount_reason", "discount_by_id", "discount_by_name", "discount_at")


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def present(self, label: str, text: str, needle: str) -> None:
        self.ok(label, needle in text, f"没找到 {needle!r}")

    def absent(self, label: str, text: str, needle: str) -> None:
        self.ok(label, needle not in text, f"命中：{needle!r}")

    def absent_re(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")

    def count(self, label: str, text: str, needle: str, want: int) -> None:
        n = text.count(needle)
        self.ok(label, n == want, f"{needle!r} 出现 {n} 次（要 {want} 次）")


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数，好让行号还对得上）。"""
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def py_code_only(t: str) -> str:
    """去掉 Python 的注释与 docstring（保留换行数，好让行号还对得上）。

    注释里提到某个列名不算"又算了一遍" —— 判据只认代码。
    """
    t = re.sub(r'"""[\s\S]*?"""', lambda m: chr(10) * m.group(0).count(chr(10)), t)
    t = re.sub(r"'''[\s\S]*?'''", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"#[^\n]*", "", t)


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def line_of(t: str, needle: str) -> int:
    i = t.find(needle)
    return 0 if i < 0 else t[:i].count(chr(10)) + 1


def py_names(t: str, enum: str) -> set[str]:
    return set(re.findall(rf"{enum}\.([A-Z_]+)", t))


def kt_set(t: str, decl: str) -> set[str]:
    m = re.search(rf"{decl}\s*(?::\s*Set<String>\s*)?=\s*setOf\(([^)]*)\)", t)
    return set(re.findall(r"\"([A-Z_]+)\"", m.group(1))) if m else set()


def main() -> int:
    c = Checker()
    print("== 1. 折扣算法全库只有一份（后端） ==")
    pys = sorted(BACK.rglob("*.py"))
    c.ok(f"扫到 {len(pys)} 个后端 .py（>={MIN_PY}）", len(pys) >= MIN_PY, f"实际 {len(pys)}")
    kts = sorted(AND.rglob("*.kt"))
    c.ok(f"扫到 {len(kts)} 个 .kt（>={MIN_KT}）", len(kts) >= MIN_KT, f"实际 {len(kts)}")

    svc = read(SERVICE)
    for label, sig in (
        ("两种折扣方式（percent / amount）", "KIND_PERCENT = \"percent\""),
        ("抹零方式常量", "KIND_AMOUNT = \"amount\""),
        ("拒绝都走同一个异常类型", "class OrderDiscountError(ValueError)"),
        ("纯函数：算一份折扣方案", "def plan_discount("),
        ("落库：把方案摊到行上", "def apply_discount("),
        ("取消折扣（精确还原）", "def clear_discount(db: Session, *, order: Order) -> list[int]"),
        ("明细变了就重摊", "def reapply_after_line_change("),
        ("这一单有没有折扣（以 kind 为准）", "def has_discount(order: Order) -> bool"),
        ("快照里的行 id", "def discount_line_ids(order: Order) -> list[int]"),
        ("摊分到分（余数给小数最大的行）", "def _spread("),
        ("查「不参与打折」的商品", "def _no_discount_names("),
        ("只认商品档案上那个勾", "Product.no_discount.is_(True)"),
        ("摊分向下取整到分", "ROUND_DOWN"),
        ("勾到不参与的行要拒绝（不静默过滤）", "勾了「不参与打折」"),
        ("整单折扣自动跳过不参与的行", "picked = [op for op in picked if op.product_id not in names]"),
        ("摊不出整数分就拒绝（不写对不上的数）", "摊到每一行时对不上整数分"),
        ("折扣是替换不是叠乘（先还原再算）", "restored = _restore(order, lines)"),
    ):
        c.present(label, svc, sig)

    # 取消折扣 / 重算失败时，七列一起回到"没打过折"
    for col in ("discount_kind", "discount_value", "discount_amount", "discount_lines",
                "discount_reason", "discount_by_id", "discount_at"):
        c.present(f"取消折扣会把 orders.{col} 置空", svc, f"order.{col} = None")
    c.ok("七列同生共死（kind / amount / lines 在两处被清）",
         all(svc.count(f"order.{x} = None") >= 2 for x in ("discount_kind", "discount_amount", "discount_lines")),
         f"kind 出现 {svc.count('order.discount_kind = None')} 次")

    print("")
    order_cols = {"discount_kind", "discount_value", "discount_amount", "discount_lines",
                  "discount_reason", "discount_by_id", "discount_at"}
    order_ok = {"services/order_discount.py", "models/order.py",
                "migrations/025_order_discount.py", "schemas/order.py",
                "services/order_response.py"}
    prod_ok = {"models/product.py", "schemas/product.py", "api/v1/products.py",
               "migrations/025_order_discount.py", "services/order_discount.py"}
    bad_order: list[str] = []
    bad_prod: list[str] = []
    for p in pys:
        t = py_code_only(p.read_text(encoding="utf-8"))
        rel = p.relative_to(BACK).as_posix()
        if any(col in t for col in order_cols) and rel not in order_ok:
            bad_order.append(rel)
        if "no_discount" in t and rel not in prod_ok:
            bad_prod.append(rel)
    c.ok("提到订单折扣列的只有那 5 个文件（谁都不能再算一遍）", not bad_order, "；".join(bad_order))
    c.ok("提到 no_discount 的只有商品相关的 4 个文件", not bad_prod, "；".join(bad_prod))

    kt_logic = read(KT_LOGIC)
    kt_code = code_only(kt_logic)
    for label, sig in (
        ("两种方式与后端同一个词（percent）", "const val DISCOUNT_KIND_PERCENT = \"percent\""),
        ("取消折扣时能识别的抹零常量", "const val DISCOUNT_KIND_AMOUNT = \"amount\""),
        ("能打折的状态是一份独立常量", "val DISCOUNT_STATUSES: Set<String> = setOf("),
        ("状态门是一个纯函数", "fun canDiscount(status: String): Boolean = status.uppercase() in DISCOUNT_STATUSES"),
        ("界面上那句「减百分比 / 抹零」", "fun discountKindLabel(kind: String): String ="),
        ("值校验（返回给用户看的那句话）", "fun discountValueError(kind: String, raw: String): String? {"),
        ("发出去的值不格式化", "fun discountValueToSend(raw: String): String = raw.trim()"),
        ("只念服务端算好的优惠额", "fun discountHeadline(order: OrderDto): String? {"),
        ("一行「谁 · 理由」的说明", "fun discountTrace(order: OrderDto): String? {"),
        ("认得出快照里的行 id", "fun discountLineIds(order: OrderDto): Set<Long> {"),
    ):
        c.present(label, kt_logic, sig)
    c.absent("客户端不自己算折扣（这一页一个乘法都不做）", kt_code, " * ")
    c.absent("客户端也不拿折扣去除钱", kt_code, " / ")
    c.present("详情页只认服务端给的实付优惠额", kt_logic, "return \"已优惠 ¥\" + formatMoney(order.discountAmount)")
    for label, msg in (
        ("空值", "先填一个数"),
        ("不是数", "只能填数字（比如 10 或 12.5）"),
        ("零或负数", "要大于 0"),
        ("百分比到 100", "百分比要小于 100%（那等于白送，请改用「抹零」）"),
        ("小数点太多", "最多四位小数"),
    ):
        c.present(f"值校验拦得住{label}", kt_logic, msg)

    print("\n== 2. 七列快照 + 商品「不参与打折」 + 正式迁移 ==")
    om = read(ORDER_MODEL)
    for col, sig in SNAPSHOT_COLUMNS.items():
        c.present(f"orders.{col} 按快照声明", om, sig)
        c.ok(f"orders.{col} 可为空（历史订单一律为空）",
             re.search(rf"{col}:.*nullable=True", om) is not None, "少了 nullable=True")
    c.present("快照列写明「七列同生共死」", om, "discount_lines")
    c.present("折扣列说明算法只有一处", om, "order_discount.py")

    pm = read(PRODUCT_MODEL)
    c.present("商品上那个勾是布尔列", pm, "no_discount: Mapped[bool] = mapped_column(Boolean, default=False)")
    c.present("商品列写明老库靠正式迁移补（不是 schema_bootstrap）", pm, "025_order_discount.py")

    mig = read(MIGRATION)
    c.ok("迁移文件名符合 FILE_RE（三位版本号 + 小写下划线）",
         re.fullmatch(r"\d{3}_[a-z0-9_]+\.py", MIGRATION.name) is not None, MIGRATION.name)
    for label, sig in (
        ("版本号 25", "VERSION = 25"),
        ("迁移名就是订单折扣", "NAME = \"order_discount\""),
        ("两张表的补列清单", "COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {"),
        ("商品列默认不参与", "(\"no_discount\", \"BOOLEAN DEFAULT 0\")"),
        ("先查现有列（可重跑）", "insp = inspect(engine)"),
        ("列已在就跳过", "if name in present:"),
        ("表不在就跳过（新库由 create_all 建）", "if present is None:"),
        ("补列走 ALTER TABLE", "ALTER TABLE {table} ADD COLUMN {name} {ddl}"),
    ):
        c.present(label, mig, sig)

    bs = read(BOOTSTRAP)
    for col in ("no_discount", "discount_kind", "discount_amount"):
        c.absent(f"⛔ 核心区 schema_bootstrap.py 里没有 {col}（走的是正式迁移）", bs, col)

    print("\n== 3. 钱契约：新增第 6 条 Figure，折后单价挂在不转出的那一档 ==")
    mc = read(CONTRACT)
    c.present("契约里多了 order_discount 这条钱数", mc, "key=\"order_discount\"")
    c.present("order_money 的 impls 上有折后单价", mc, "\"services/order_money.py::line_unit_price\"")
    for fn in ("apply_discount", "clear_discount", "plan_discount", "reapply_after_line_change"):
        c.present(f"折扣这条 Figure 声明了 {fn}", mc, f"\"services/order_discount.py::{fn}\"")
    c.present("消费方之一是打折端点", mc, "\"api/v1/orders_discount.py\"")
    c.present("消费方之一是改明细端点", mc, "\"api/v1/order_products.py\"")
    c.present("折扣这条不转出（订单域内部计算）", mc, "forbid=()")
    n_keys = len(re.findall(r"key=\"", mc))
    c.ok(f"钱数至少 6 条（>{5}）", n_keys >= 6, f"实际 {n_keys}")
    i_reex = mc.find("\nREEXPORTS: dict[str, tuple[str, str]] = {")
    reexports = mc[i_reex:] if i_reex > 0 else ""
    c.absent("折后单价不进 REEXPORTS（跨域没人要用它）", reexports, "line_unit_price")

    print("\n== 4. 退货按折后实付退（不能退得比收的多） ==")
    mm = read(MONEY)
    c.present("折后单价的唯一实现", mm, "def line_unit_price(op: OrderProduct) -> Decimal:")
    c.present("折后单价 = 行金额 / 数量", mm, "return (total / qty).quantize(Decimal(\"0.0001\"), rounding=ROUND_HALF_UP)")
    c.present("退货的钱走折后单价", mm, "returned = line_unit_price(op) * Decimal(int(op.returned_quantity or 0))")
    rt = read(RETURN)
    c.present("退货服务 import 了折后单价", rt, "from app.services.order_money import line_unit_price")
    c.present("退货金额按折后单价算", rt, "return (line_unit_price(op) * Decimal(qty)).quantize(Decimal(\"0.0001\"), rounding=ROUND_HALF_UP)")
    c.present("退货单价的 KDoc 写明口径", rt, "line_unit_price")
    pyt = read(PY_TEST)
    c.present("单测钉着「退货按折后实付退」", pyt, "按折后实付")
    print("\n== 5. 端点 / 门 / 审计（打折只有派单员能打） ==")
    ep = read(ENDPOINT)
    c.present("路由模块自己声明前缀（按文件解析的 AST 工具靠这行）",
              ep, "router = APIRouter(prefix=\"/orders\", tags=[\"orders\"])")
    c.present("打折端点", ep, "@router.post(\"/{order_id}/discount\", response_model=OrderOut)")
    c.present("取消折扣端点", ep, "@router.delete(\"/{order_id}/discount\", response_model=OrderOut)")
    c.count("两个端点都要 ORDER_EDIT 这把钥匙", ep, "require_permission(Permission.ORDER_EDIT)", 2)
    c.present("服务端再判一次业务规则（客户端那句只是提前拦）", ep, "OrderDiscountError")
    c.present("折扣算法是 import 进来的（契约第 5 条认这个）",
              ep, "from app.services.order_discount import (")
    c.present("拒绝走 400", ep, "raise HTTPException(status_code=400, detail=str(exc))")
    c.present("取消折扣也写审计", ep, "action=OperationAction.ORDER_DISCOUNT_CLEAR,")
    c.present("打折写审计", ep, "action=OperationAction.ORDER_DISCOUNT,")
    c.present("可编辑状态只有一处（这里 import 不复写）", ep, "LINE_EDITABLE_STATUSES")
    c.present("取锁 + 重读", ep, "lock_order_row(db, _get_order_scoped(order_id, current, db))")
    c.ok("条件 UPDATE 占位（并发下不许改一张已结束的单）",
         "update(Order)" in ep and "Order.status.in_(LINE_EDITABLE_STATUSES)" in ep,
         "多行链式调用要分两段找")
    c.present("没折扣就别取消（免得落一堆假审计）", ep, "if not has_discount(order):")
    c.count("钱变了要通知司机", ep, "_notify_driver_lines_changed(db, order)", 2)
    c.present("折完把最新的订单装配回去", ep, "return _respond(db, order, current)")

    # ⚠️ `py_code_only`：把 include 那行注释掉不能算「挂上了」—— `present` 只做子串匹配，
    #    注释里出现同样的字样会假绿（2026-10-07 反向验证实测：那条注入当时是漏的）。
    rt = py_code_only(read(ROUTER))
    c.present("router.py 里挂上了这个模块（import）", rt, "orders_discount,")
    c.present("router.py 里挂上了这个模块（include）", rt, "api_router.include_router(orders_discount.router)")
    en = read(ENUMS)
    c.present("动作码：打折", en, "ORDER_DISCOUNT = \"ORDER_DISCOUNT\"")
    c.present("动作码：取消折扣", en, "ORDER_DISCOUNT_CLEAR = \"ORDER_DISCOUNT_CLEAR\"")
    c.present("动作码不复用 ORDER_UPDATE（改地址与少收钱是两件事）", en, "ORDER_UPDATE = \"ORDER_UPDATE\"")
    cov = read(COVERAGE)
    c.present("审计覆盖表里认得出打折与取消", cov, "'ORDER_DISCOUNT', 'ORDER_DISCOUNT_CLEAR',")
    pr = read(PRICE_RULES)
    c.absent("⛔ 折扣不长在批发商专属价上", pr, "discount")
    c.absent_re("⛔ 折扣也不长在价格规则模型上", pm, r"discount_(kind|value|amount|lines|reason|by_id|at)")

    print("\n== 6. 明细变了就重摊（行金额先由单价 × 数量定，折扣作用在它现在的金额上） ==")
    ln = read(LINES)
    c.present("那一行逐字保留", ln, "op.line_total = resolve_line_total(new_up, new_qty, body.line_total)")
    c.present("改行之后重摊（带 edited_line）", ln, "reapply_after_line_change(db, order=order, edited_line=op)")
    c.present("删行之后重摊（edited_line=None）", ln, "reapply_after_line_change(db, order=order, edited_line=None)")
    i_line = line_of(ln, "op.line_total = resolve_line_total(new_up, new_qty, body.line_total)")
    i_re = line_of(ln, "reapply_after_line_change(db, order=order, edited_line=op)")
    c.ok("顺序不能反：先重算行金额，再重摊折扣", 0 < i_line < i_re, f"行金额@{i_line} / 重摊@{i_re}")
    c.absent("改明细这一层不自己碰折扣列（注释里提一句不算）", py_code_only(ln), "discount_amount")
    c.present("重摊失败要说清是哪一单", ln, "这一单还挂着折扣")

    print("\n== 7. 出参：折扣金额算货款、司机整块看不见 ==")
    rp = read(RESPONSE)
    i_cg = rp.find("CUSTOMER_GOODS_FIELDS: tuple[str, ...] = (")
    i_ds = rp.find("DISCOUNT_FIELDS: tuple[str, ...] = (")
    cg_block = rp[i_cg:rp.find(")", i_cg)] if i_cg > 0 else ""
    ds_block = rp[i_ds:rp.find(")", i_ds)] if i_ds > 0 else ""
    c.present("折扣金额归到「货款」那一档（名字像钱，判据会自算）", cg_block, "\"discount_amount\"")
    for f in DISCOUNT_FIELDS:
        c.present(f"司机视角要清的八格里有 {f}", ds_block, f'"{f}"')
    c.present("整块清（不是只清一个数）", rp, "for _discount_field in DISCOUNT_FIELDS:")
    c.present("逐格置空", rp, "data[_discount_field] = None")
    c.present("谁打的折在装配时查出来", rp, "data[\"discount_by_name\"] = discount_user.full_name or dialable_phone(discount_user)")
    c.ok("司机那条路真的会走到整块清零（在 apply_driver_view_gating 里）",
         line_of(rp, "for _discount_field in DISCOUNT_FIELDS:") > line_of(rp, "def apply_driver_view_gating(") > 0,
         "找不到那个循环或函数")

    sch = read(ORDER_SCHEMA)
    c.present("入参体继承 MoneyInput（挡「存不进数据库的数」）", sch, "class OrderDiscountBody(MoneyInput):")
    for f in ("kind", "value", "line_ids", "reason"):
        c.present(f"入参体有 {f}", sch, f"    {f}:")
    for f in DISCOUNT_FIELDS:
        c.present(f"出参有 {f}", sch, f"    {f}:")
    c.present("快照串能解析成 list（脏数据当空）", sch, '@field_validator("discount_lines", mode="before")')
    c.present("业务规则在服务层，不在 schema 里", sch, "services/order_discount.py")
    ps = read(PRODUCT_SCHEMA)
    n_nd = ps.count("no_discount")
    c.ok(f"商品三个 schema 都带上了 no_discount（实际 {n_nd} 处）", n_nd >= 3, f"实际 {n_nd}")
    c.present("出参默认 False（老数据是空）", ps, "no_discount: bool = False")
    c.ok("司机出参门控那条自算判据还在（名字像钱的字段必须归类）", GATING_TEST.exists(), str(GATING_TEST))
    print("\n== 8. 客户端：三处状态值同一个、钱不自己算、开关只带改过的键 ==")
    client_status = kt_set(kt_logic, "val DISCOUNT_STATUSES")
    m_lines = re.search(r"LINE_EDITABLE_STATUSES = \(([\s\S]*?)\)", read(LINES))
    backend_status = py_names(m_lines.group(1), "OrderStatus") if m_lines else set()
    model_status = kt_set(read(KT_STATUS), "val EDITABLE")
    want_status = {"PENDING_DISPATCH", "DISPATCHED", "ACCEPTED"}
    c.ok(f"后端可编辑状态就是那三档：{sorted(backend_status)}", backend_status == want_status, str(backend_status))
    c.ok(f"客户端能打折的状态与后端字面一致：{sorted(client_status)}", client_status == backend_status,
         f"客户端 {sorted(client_status)} vs 后端 {sorted(backend_status)}")
    c.ok(f"与改信息的 EDITABLE 也是同一组：{sorted(model_status)}", model_status == backend_status,
         f"OrderStatusModel {sorted(model_status)}")
    c.present("状态门复用同一个集合（不写第二份字面量）", kt_logic, "in DISCOUNT_STATUSES")

    vm = read(KT_VM)
    for label, sig in (
        ("打开折扣弹层前先看状态", "fun openDiscount() {"),
        ("把折扣发给服务端", "fun applyDiscount() {"),
        ("取消折扣", "fun clearDiscount() {"),
        ("只发给服务端算（不在本地试算）", "container.repo.applyOrderDiscount("),
        ("发出去的值不做格式化", "discountValueToSend(discountValue)"),
        ("服务端那句原样显示给用户", "discountError = toApiException(e).message"),
    ):
        c.present(label, vm, sig)
    c.absent("本地不做折扣试算（没有乘除）", code_only(vm), "discountAmount *")

    dlg = read(KT_DIALOG)
    for label, sig in (
        ("两种方式可选", "discountKindLabel(k)"),
        ("范围两档（整单 / 只打几件）", "onWholeOrderChange"),
        ("逐行勾选", "onToggleLine(line.id)"),
        ("理由选填", "理由"),
        ("已打折时能就地取消", "onClear"),
        ("解释「不参与打折」的语义", "不参与打折"),
        ("解释取消折扣是精确还原", "还原成打折前的金额"),
    ):
        c.present(label, dlg, sig)

    dt = read(KT_DETAIL)
    c.present("详情页有只读的「已优惠」行", dt, "val savedDiscount = discountHeadline(order)")
    c.present("折扣入口回调", dt, "onDiscountClick = { vm.openDiscount() },")
    c.present("取消折扣回调", dt, "onClearDiscountClick = { vm.clearDiscount() },")
    c.count("折扣弹层只挂一次", dt, "OrderDiscountDialog(", 1)
    c.count("弹层只在开关打开时挂", dt, "if (vm.showDiscountDialog)", 1)
    i_disc = line_of(dt, "val savedDiscount = discountHeadline(order)")
    i_arrears = line_of(dt, 'Text("挂账")')
    c.ok("折扣那一段插在「挂账」那颗按钮之后（既有判据的 900 字符窗口不许被挤）",
         i_disc > i_arrears > 0, f"折扣@{i_disc} / 挂账@{i_arrears}")

    dto = read(KT_DTOS)
    # 出参字段名就是 JSON 里的键（后端是 snake_case，客户端用 @SerialName 对齐）
    for name in DISCOUNT_FIELDS:
        if name == "discount_by_id":
            continue  # 客户端只认名字，不认操作人 id
        c.present(f"DTO 认得 {name}", dto, f'"{name}"')
    c.absent("客户端 DTO 不带操作人 id（只认 discount_by_name）", dto, '"discount_by_id"')
    c.present("DTO 里有打折入参体", dto, "data class OrderDiscountBody(")
    c.present("商品 DTO 带上了那个勾", dto, "val noDiscount: Boolean = false,")
    c.present("DTO 写明折扣别反推", dto, "反推")

    apis = read(KT_APIS)
    c.present("Retrofit 打折端点", apis, "@POST(\"orders/{orderId}/discount\")")
    c.present("Retrofit 取消折扣端点", apis, "@DELETE(\"orders/{orderId}/discount\")")
    c.count("商品的建 / 改请求都带 no_discount", apis, "@SerialName(\"no_discount\")", 2)
    repo = read(KT_REPO)
    c.present("仓库层转发打折", repo, "suspend fun applyOrderDiscount(")
    c.present("仓库层转发取消", repo, "suspend fun clearOrderDiscount(orderId: Long) = api.orderApi.clearOrderDiscount(orderId)")

    form = read(KT_FORM)
    c.present("商品编辑页有那个开关", form, "label = \"不参与打折\",")
    c.present("开关绑在视图模型上", form, "checked = vm.noDiscount,")
    c.present("开关能改", form, "onCheckedChange = { vm.noDiscount = it },")
    c.present("文案说清它不是价格锁", form, "价格照旧能改")
    fvm = read(KT_FORM_VM)
    for label, sig in (
        ("表单状态", "var noDiscount by mutableStateOf(false)"),
        ("载入时回填", "noDiscount = p.noDiscount"),
        ("草稿带上它", "noDiscount = noDiscount,"),
        ("草稿数据结构里有它", "val noDiscount: Boolean = false,"),
        ("只有改过才发（不是每次整份回传）", "val noDiscountOut = if (d.noDiscount != baseline.noDiscount) { dirty = true; d.noDiscount } else null"),
        ("新建请求带上它", "noDiscount = noDiscount,"),
    ):
        c.present(label, fvm, sig)
    c.present("修改请求带上它", fvm, "noDiscount = noDiscountOut,")

    lt = read(KT_LOGIC_TEST)
    n_kt = lt.count("@Test")
    c.ok(f"折扣纯逻辑单测至少 8 条（实际 {n_kt}）", n_kt >= 8, f"实际 {n_kt}")
    c.present("单测钉着「发出去不格式化」", lt, "discountValueToSend")
    c.present("单测钉着状态常量字面量", lt, "DISCOUNT_STATUSES")
    dft = read(KT_DIFF_TEST)
    c.present("表单差异单测追了「不参与打折」", dft, "不参与打折")
    c.present("表单差异单测查「只带这一个键」", dft, "assertEquals(true, req!!.noDiscount)")
    n_pyt = pyt.count("def test_")
    c.ok(f"后端折扣单测至少 10 条（实际 {n_pyt}）", n_pyt >= 10, f"实际 {n_pyt}")
    print("\n== 9. 防静默空转 ==")
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED_FILES if not p.exists()]
    c.ok(f"后端 {len(REQUIRED_FILES)} 个关键文件都在", not missing, "；".join(missing))
    missing_kt = [str(p.relative_to(ROOT)) for p in REQUIRED_KT if not p.exists()]
    c.ok(f"客户端 {len(REQUIRED_KT)} 个关键文件都在", not missing_kt, "；".join(missing_kt))
    c.ok("打折扣的算法文件非空（不是空壳骗判据）", len(svc.splitlines()) >= 200, f"{len(svc.splitlines())} 行")
    total = c.passes + len(c.fails)
    c.ok(f"这条判据自己至少有 55 项断言（实际 {total}）", total >= 55, f"实际 {total}")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())