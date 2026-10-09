"""反向验证：把 CHG-0073（台账 L-41 采购单并入库存管理）的红线逐条弄坏，看它们**真的会红**。

为什么这块必须反向验证：这条线的毛病全是「没报错但也没发生」——
  · 并成两次写（把采购单的写逻辑搬进库存页、另起一条入库流水）：编译得过、接口 200，库存记两遍；
  · 并成删功能（格子删了、顺手把页面 / 路由 / 端点也删）：看着更「合并」，实则是把功能砍了；
  · 入口只删不接（格子删了、没人 navigate）：采购单从此进不去，而**一行代码都不报错**；
  · 回链猜归属（凭 note 文字或「商品 + 时间」猜）：同一个商品一天进两次货就点错单；
  · 顺手给流水加一列（＝第二份归属真相）：还能一次迁移 + 历史回填，而用户明确说老数据不回填；
  · 只读派生字段被放进写模型 / 忘了 is_void 与 deleted_at 两道过滤（点进去是回收站里的单）。
判据里还有一半是「扫全仓 / 数出现次数 / 谁在谁之前」，清单如果不验证，就可能因为「目录扫不到 /
集合是空的 / 抽取函数失效」而永远绿（本轮 fn_body 抽 Python 时真的抽出了 2 个字符）。所以每一条
都要有对应的破坏用例，最后还要确认还原之后红线**逐字节**回到绿。

用法：python _tools/qa/_reverse_verify_inventory_purchase_merge.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_inventory_purchase_merge.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
BE = ROOT / "backend/app"

MODULES = AND / "ui/nav/Modules.kt"
ROUTES = AND / "ui/nav/Routes.kt"
NAVGRAPH = AND / "ui/nav/NavGraph.kt"
INV_SCREEN = AND / "ui/dispatcher/InventoryScreen.kt"
PO_LIST = AND / "ui/dispatcher/PurchaseOrdersScreen.kt"
DTOS = AND / "data/remote/dto/Dtos.kt"

SCH_INV = BE / "schemas/inventory.py"
API_INV = BE / "api/v1/inventory.py"
API_PO = BE / "api/v1/purchase_orders.py"
MODEL_INV = BE / "models/inventory.py"
MIG019 = BE / "migrations/019_purchase_orders.py"

COVERAGE = ROOT / "_tools/ai/_app_feature_coverage.py"
WRITE_COVERAGE = ROOT / "_tools/ai/_write_coverage.py"

CHG_DOC = ROOT / "docs/changes/CHG-0073.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "工作台那一格加回来（＝没并，只是多了一个入口）",
        MODULES,
        '        ModuleEntry("库存管理", Routes.INVENTORY, Icons.Default.Warehouse, color = 0xFF278A9DL),                        // 深青 · 库存仓储（CHG-0102 起按 H 档：L*53.0 C*28.0 h219.8）\n',
        '        ModuleEntry("库存管理", Routes.INVENTORY, Icons.Default.Warehouse, color = 0xFF278A9DL),                        // 深青 · 库存仓储（CHG-0102 起按 H 档：L*53.0 C*28.0 h219.8）\n        ModuleEntry("采购单", Routes.PURCHASE_ORDERS, Icons.Default.ShoppingCart, color = 0xFF4CAF50L),\n',
        "模块清单里没有「采购单」那一格",
    ),
    (
        "ENTRY_CAPABILITY 里加回一行（能力没跟着入口搬走）",
        MODULES,
        '        Routes.INVENTORY to "product:manage",',
        '        Routes.INVENTORY to "product:manage",\n        Routes.PURCHASE_ORDERS to "product:manage",',
        "ENTRY_CAPABILITY 里也没有它",
    ),
    (
        "路由常量被改名（＝并成删功能：那条路由再也到不了那两页）",
        ROUTES,
        'const val PURCHASE_ORDERS = "dispatcher/purchase-orders"',
        'const val PURCHASE_ORDERS = "dispatcher/purchase-orders-x"',
        "两条路由常量逐字都还在",
    ),
    (
        "采购单列表那一页被改名（页面没了，编译照样过）",
        PO_LIST,
        "fun PurchaseOrdersScreen(",
        "fun PurchaseOrdersScreenOld(",
        "那一页还在且只有一处",
    ),
    (
        "恢复端点被摘掉（撤单后拉不回来，其余五个端点照样绿）",
        API_PO,
        '@router.post("/{order_id}/restore", response_model=PurchaseOrderOut)\n',
        "",
        "恢复那一条仍在",
    ),
    (
        "库存页签名少一个回调（顶栏那颗按钮没有着落）",
        INV_SCREEN,
        "    onOpenPurchaseOrders: () -> Unit,",
        "    onOpenPurchaseOrdersX: () -> Unit,",
        "签名多出两个回调",
    ),
    (
        "顶栏那颗按钮改成空实现（点下去什么都不发生）",
        INV_SCREEN,
        'TextButton(onClick = onOpenPurchaseOrders) { Text("采购单") }',
        'TextButton(onClick = {}) { Text("采购单") }',
        "采购单那颗与「流水」都在顶栏里",
    ),
    (
        "NavGraph 没把顶栏那颗接上（入口只删不接）",
        NAVGRAPH,
        "onOpenPurchaseOrders = { navController.navigate(Routes.PURCHASE_ORDERS) },",
        "onOpenPurchaseOrders = { },",
        "顶栏那颗接到采购单列表",
    ),
    (
        "流水行那颗指向表单却不带 id（点开一张新单）",
        NAVGRAPH,
        'navController.navigate(Routes.PURCHASE_ORDER_FORM + "?orderId=" + id)',
        "navController.navigate(Routes.PURCHASE_ORDER_FORM)",
        "流水行那颗接到那一张单",
    ),
    (
        "DTO 那个字段变成非空（老接口没这个字段就解析炸）",
        DTOS,
        '@SerialName("purchase_order_id") val purchaseOrderId: Long? = null,',
        '@SerialName("purchase_order_id") val purchaseOrderId: Long = 0,',
        "可空、有缺省值",
    ),
    (
        "无条件画那颗链接（手工调整也自称属于某张单）",
        INV_SCREEN,
        "if (poId != null) {",
        "if (true) {",
        "只有非 null 才画那颗链接",
    ),
    (
        "那颗链接不可点（画得出来、点不动）",
        INV_SCREEN,
        "modifier = Modifier.clickable { onOpenPurchaseOrder(poId) },",
        "modifier = Modifier,",
        "那颗链接可点",
    ),
    (
        "文案丢了单号（用户看不出属于哪张单）",
        INV_SCREEN,
        '"采购单 #" + poId,',
        '"采购单",',
        "文案是「采购单 #N」",
    ),
    (
        "只读派生字段被挪进写模型（手工入库就能自称属于某张单）",
        SCH_INV,
        "class MovementCreate(MoneyInput):",
        "class MovementCreate(MoneyInput):\n    purchase_order_id: int | None = None",
        "写模型 MovementCreate 里没有它",
    ),
    (
        "models 里真加了一列（第二份归属真相，列与明细绑定会漂移）",
        MODEL_INV,
        "class InventoryMovement(Base, TimestampMixin):",
        "class InventoryMovement(Base, TimestampMixin):\n    purchase_order_id: Mapped[int | None] = mapped_column(nullable=True)",
        "models/inventory.py 里没有这一列",
    ),
    (
        "迁移里提它（＝历史回填，用户明确不要）",
        MIG019,
        'DESCRIPTION = "新增 purchase_orders + purchase_order_items：一次进货同时写库存、成本价与供应商应付"',
        'DESCRIPTION = "新增 purchase_orders + purchase_order_items：一次进货同时写库存、成本价与供应商应付"\nNOTE = "回填 movements.purchase_order_id"',
        "没有一条迁移碰它",
    ),
    (
        "反查不再按本页 id 批量（in_ 掉了，只认第一条 id）",
        API_INV,
        "                PurchaseOrderItem.movement_id.in_(ids),",
        "                PurchaseOrderItem.movement_id == (ids[0] if ids else 0),",
        "按本页 id 批量反查",
    ),
    (
        "明细作废那道过滤没了（作废的明细还牵着一条回链）",
        API_INV,
        "                PurchaseOrderItem.is_void.is_(False),\n",
        "",
        "明细已作废的不给回链",
    ),
    (
        "软删那道过滤没了（点进去是回收站里的单）",
        API_INV,
        "                PurchaseOrder.deleted_at.is_(None),\n",
        "",
        "单子已软删的不给回链",
    ),
    (
        "逐行再查一次（N+1，结果一样对、只是每行一次库查询）",
        API_INV,
        "    ids = [m.id for m in rows]",
        "    ids = [m.id for m in rows]\n    for _row in rows:\n        db.execute(select(PurchaseOrderItem.movement_id).where(PurchaseOrderItem.movement_id == _row.id))",
        "整段只有一次库查询",
    ),
    (
        "归属不再挂在行属性上（出参永远没有这个字段）",
        API_INV,
        "    for m in rows:\n        m.purchase_order_id = owner.get(m.id)  # type: ignore[attr-defined]",
        "    for m in rows:\n        continue",
        "挂的是行的属性",
    ),
    (
        "归属挂到 finish_page 之后（截断/加响应头先发生，行的身份被改）",
        API_INV,
        "    _attach_purchase_orders(db, rows)\n    return finish_page(rows, limit, response)",
        "    return finish_page(rows, limit, response)\n    _attach_purchase_orders(db, rows)",
        "归属在 finish_page 之前挂上",
    ),
    (
        "覆盖表又冒出一个独立的「采购单」模块条目（--check 报化石）",
        COVERAGE,
        '    "库存管理": (\n        ["库存管理", "采购单"],',
        '    "采购单": (["采购单"], "None", "老条目"),\n    "库存管理": (\n        ["库存管理", "采购单"],',
        "不再有独立的「采购单」模块条目",
    ),
    # ⚠️ 2026-10-07（CHG-0074，台账 L-42）：采购单的 AI 写域**后来真的开了**（四个写动作 +
    # 表格解析器 + 确认卡），所以原来那条「写侧被顺手开放」的注入已经没有意义 ——
    # 换成它在新世界里的反面：写侧认领被摘掉。
    (
        "写侧认领被摘掉（覆盖表那格又不认「采购单」的写能力了）",
        COVERAGE,
        '        ["库存", "采购单"],',
        '        ["库存"],',
        "覆盖表那格的写能力也认领了「采购单」",
    ),
    (
        "变更单少一节（⑨ 关闭 被改名）",
        CHG_DOC,
        "## ⑨ 关闭（六格）",
        "## ⑨ 收尾（六格）",
        "变更单有这一节：## ⑨ 关闭",
    ),
    (
        "登记簿那一行的链接被拆（对账找不到文件）",
        REGISTRY,
        "[CHG-0073.md](CHG-0073.md)",
        "[CHG-0073 合并](CHG-0073.md)",
        "登记簿里有 CHG-0073 那一行",
    ),
    (
        "工作声明那一行被改名（认领段对不上变更单）",
        CLAIM,
        "**CHG-0073 把「采购单」并进「库存管理」",
        "**CHG-0073：把「采购单」并进「库存管理」",
        "工作声明里有 CHG-0073 这一段",
    ),
    (
        "反验脚本的路径被挪走（判据里那条「反向验证脚本在」不能自己骗自己）",
        CHECK,
        'REVERSE = "_tools/qa/_reverse_verify_inventory_purchase_merge.py"',
        'REVERSE = "_tools/qa/_reverse_verify_nothing.py"',
        "反向验证脚本在",
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
    # 还原当场核对：写回后重新读回来逐字节比，对不上就非零退出。
    # 本句是原则：写了还原不是证明；重新读回来的字节 == 刚写出去的字节 才是。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print("还原后与快照不一致（注入污染了源码树）：" + str(p))
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
        print("前提不成立：源码完好时这条红线没过\n" + out[-1200:])
        return 1
    print("前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print("  [SKIP] " + label + " —— 原文出现 " + str(src.count(old)) + " 次，无法唯一替换")
            bad += 1
            continue
        write_src(p=path, text=src.replace(old, new), crlf=crlf)
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
