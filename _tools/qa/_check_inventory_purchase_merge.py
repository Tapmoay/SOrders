"""把「采购单」并进「库存管理」（CHG-0073 / 台账 L-41）。

## 用户要的（2026-10-07，ref m01700 逐字）
「你这个说白了，这个采购单……原理跟我那个库存管理非常的像，采购单基本上就是属于库存管理，
他要有入库嘛，入库的数量、供应商以及进货价，所以干脆把这 2 个也融合在一起，合并成一个……
也就是采购单相当于库存管理那个入库记录嘛」。
口径 m13365 四条裁法：① 数据层本来就一处写完（库存 + 成本价 + 供应商应付同一次保存）；
② 工作台留「库存管理」那格，采购单**从它进**；③ 只并**入口与视图**，两张表与那六个端点照旧；
④ 流水行要能点进「它属于哪张单」。

## 这一条为什么必须有机器的判据
全是「没报错但也没发生」的毛病：
- **并成两次写**：把采购单的写逻辑搬进库存页、另起一条入库流水 —— 库存被记两遍（成本价与
  供应商应付也会各记一次），而一切都编译得过、接口照样 200；
- **并成删功能**：工作台那一格删了、顺手把页面 / 路由 / 端点也一起删 —— 看着更「合并」，
  实则是把功能砍了（用户说的是「合并成一个」，不是「干掉一个」）；
- **入口只删不接**：格子删了、没人 navigate —— 采购单从此进不去，而这**一行代码都不报错**；
- **回链猜归属**：凭 note 字段里的文字（采购单 #N）或按「商品 + 时间」猜，会点错单
  （同一个商品一天进两次货就有两个候选）；归属的唯一真相是 purchase_order_items.movement_id；
- **顺手给流水加一列**：那会造出第二份归属真相（列 vs 明细绑定），一旦漂移就没人说得清回链
  可不可信；还要一次迁移 + 历史回填，而用户明确说老数据不回填；
- **把只读派生字段也放进写模型**：手工入库就能自称属于某张采购单，「手工调整不猜归属」被绕过；
- **忘了软删 / 作废**：点进去是一张进了回收站的单、或明细已作废 —— 回链指着一个不存在的归属。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
这一条的红线全是「同一份事实的第二处定义」与「入口的通路」：
「归属真相只有一处」在类型上表达不出来 —— 想加一列 purchase_order_id 一样编译得过、迁移也
跑得过；「工作台不再有那一格，但页面 / 路由 / 端点一个都没少」是**两处清单的一致性**
（模块清单 vs 路由表），漏了一处照样编译得过；「流水行那颗链接只在有归属时才画」是运行期
数据（null 与 0 的差别）；「反查只做一次、按本页 id 批量」是**查询条数**（逐行查一样返回正确
结果，只是 N+1）。所以判据只能钉在源码结构、唯一性、次序与几条过滤条件上，外加真机把
两个入口走一遍。反向破坏用例见 _reverse_verify_inventory_purchase_merge.py。

## 判据（每条都能被反向验证弄红）
1. 工作台那一格真的没了，而且**只搬入口**：模块清单与 ENTRY_CAPABILITY 里都不再有
   Routes.PURCHASE_ORDERS；而路由常量、两个页面、后端六个端点一个都没少；
2. 入口长在库存管理页顶栏：InventoryScreen 的两个回调（整条签名逐字）、那颗
   TextButton … Text("采购单")、NavGraph 里那条 navigate（列表与 ?orderId= 两档）；
3. 流水行的回链：DTO 只读字段 + MovementRow 里 if (poId != null) 才画的那颗「采购单 #N」；
4. 后端**只读派生**：MovementOut.purchase_order_id（不是列、不在写模型里、没有迁移）、
   _attach_purchase_orders 是唯一挂载点、按本页 id 一次反查、两条过滤都在、且挂在
   finish_page 之前；
5. 写侧与 AI 权限：本单一个字没改（当时采购单还没有 AI 写域）；⚠️ 2026-10-07 CHG-0074
   （台账 L-42）把那四条写端点开了 ⇒ 这一节跟着改成「写域已开」的正向断言（见 §5 的注释）；
   变更单九节 + 登记簿 + 工作声明 + 反验脚本 + 防静默空转。

用法：python _tools/qa/_check_inventory_purchase_merge.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from _airepo import refuse_if_injecting  # noqa: E402
from _check_product_card_single_source import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
BE = ROOT / "backend/app"

MODULES = AND / "ui/nav/Modules.kt"
ROUTES = AND / "ui/nav/Routes.kt"
NAVGRAPH = AND / "ui/nav/NavGraph.kt"
INV_SCREEN = AND / "ui/dispatcher/InventoryScreen.kt"
PO_LIST = AND / "ui/dispatcher/PurchaseOrdersScreen.kt"
PO_FORM = AND / "ui/dispatcher/PurchaseOrderFormScreen.kt"
DTOS = AND / "data/remote/dto/Dtos.kt"

SCH_INV = BE / "schemas/inventory.py"
API_INV = BE / "api/v1/inventory.py"
API_PO = BE / "api/v1/purchase_orders.py"
MODEL_INV = BE / "models/inventory.py"
MIGRATIONS = BE / "migrations"

COVERAGE = ROOT / "_tools/ai/_app_feature_coverage.py"
WRITE_COVERAGE = ROOT / "_tools/ai/_write_coverage.py"

CHG_ID = "CHG-0073"
CHG_DOC = ROOT / "docs/changes/CHG-0073.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = "_tools/qa/_reverse_verify_inventory_purchase_merge.py"

#: 九节标题（按前缀认：这几节的标题后面还带括号说明）
CHG_SECTIONS = (
    "## ① 六问",
    "## ② Must Change / Must Not Change",
    "## ③ Boundary",
    "## ④ Behavior Contract",
    "## ⑤ Data Contract",
    "## ⑥ CHG 专章",
    "## ⑦ 测试",
    "## ⑧ 证据",
    "## ⑨ 关闭",
)

#: 扫到的 .kt 数下限（防目录改名 / 搬走之后「一个文件都没扫到」也算过）
MIN_KT = 100

#: 迁移文件数下限（防 migrations 目录被搬走时空转）
MIN_MIGRATIONS = 10

#: 必须真的数到这几个文件（少一个就说明目录结构变了，判据要跟着改）
REQUIRED_FILES = (
    MODULES,
    ROUTES,
    NAVGRAPH,
    INV_SCREEN,
    PO_LIST,
    PO_FORM,
    DTOS,
    SCH_INV,
    API_INV,
    API_PO,
    MODEL_INV,
    COVERAGE,
    WRITE_COVERAGE,
    CHG_DOC,
    REGISTRY,
    CLAIM,
)


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def code(p: Path) -> str:
    return strip_comments(read(p))


def subs(text: str, needle: str) -> int:
    """子串出现次数（故意用纯字符串：锚点里全是 ( ) . ? 这类正则元字符）。"""
    return text.count(needle)


def first(text: str, needle: str) -> int:
    """needle 首次出现的位置（取不到返回一个很大的数 —— 让「谁在前」的比较判红）。"""
    i = text.find(needle)
    return i if i >= 0 else 10 ** 9


def fn_body(src: str, sig: str) -> str:
    """sig 那段代码块的花括号体（按大括号配对，不是按行猜）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    b = src.find("{", i)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[b : j + 1]
    return ""


def py_block(src: str, sig: str) -> str:
    """Python 顶层函数 / 类的那一段（从 sig 起到下一个顶层 def / @ / class 之前）。

    ⛔ 不能用 fn_body 抽 Python：owner: dict[int, int] = {} 里的那对花括号会被当成函数体，
    于是「函数体」只有 2 个字符、后面所有断言全变成假绿（本轮踩过）。
    """
    i = src.find(sig)
    if i < 0:
        return ""
    m = re.search(r"\n(?=(def |@|class ))", src[i + len(sig) :])
    return src[i:] if not m else src[i : i + len(sig) + m.start()]


def paren_block(src: str, sig: str) -> str:
    """sig（以 ( 结尾）那段括号体（mapOf( … ) 这种 —— 里面没有花括号，不能按大括号配）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    depth = 0
    for j in range(i + len(sig) - 1, len(src)):
        ch = src[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return src[i : j + 1]
    return ""


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

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")


def main() -> int:
    if refuse_if_injecting("采购单并入库存管理判据"):
        return 0
    c = Checker()

    mod = code(MODULES)
    routes = code(ROUTES)
    nav = read(NAVGRAPH)
    inv = read(INV_SCREEN)
    dtos = read(DTOS)
    sch = read(SCH_INV)
    api = read(API_INV)
    model = read(MODEL_INV)
    cov = read(COVERAGE)

    print("== 1. 工作台那一格真的没了，而且只搬入口 ==")
    kts = sorted(AND.rglob("*.kt"))
    c.ok(f"扫到 {len(kts)} 个 .kt（>={MIN_KT}，防目录被搬走时空转）", len(kts) >= MIN_KT, f"实际 {len(kts)}")
    c.ok("模块清单里没有「采购单」那一格", 'ModuleEntry("采购单"' not in mod)
    c.ok(
        "ENTRY_CAPABILITY 里也没有它（能力跟着入口走）",
        "Routes.PURCHASE_ORDERS" not in mod,
        f"实际 {subs(mod, 'Routes.PURCHASE_ORDERS')} 处",
    )
    c.present("工作台仍有一格进「库存管理」", mod, r'ModuleEntry\("库存管理", Routes\.INVENTORY,')
    cap = paren_block(mod, "val ENTRY_CAPABILITY: Map<String, String> = mapOf(")
    c.ok(f"ENTRY_CAPABILITY 摘得出来（{len(cap)} 字，防抽取失效变成永远绿的检查）", len(cap) >= 200, f"实际 {len(cap)} 字")
    c.ok('库存管理那条能力还在（Routes.INVENTORY to "product:manage"）', 'Routes.INVENTORY to "product:manage"' in cap)
    c.ok(
        "搬的是入口不是功能：两条路由常量逐字都还在",
        subs(routes, 'const val PURCHASE_ORDERS = "dispatcher/purchase-orders"') == 1
        and subs(routes, 'const val PURCHASE_ORDER_FORM = "dispatcher/purchase-order-form"') == 1,
    )
    for page, sig in ((PO_LIST, "fun PurchaseOrdersScreen("), (PO_FORM, "fun PurchaseOrderFormScreen(")):
        owners = sorted(p.relative_to(AND).as_posix() for p in kts if sig in code(p))
        c.ok(f"那一页还在且只有一处：{sig.rstrip('(')}", owners == [page.relative_to(AND).as_posix()], "；".join(owners) or "一处都没扫到")
    po_api = read(API_PO)
    c.ok(f"后端采购单路由还在：{API_PO.relative_to(ROOT).as_posix()}", API_PO.exists())
    c.present("前缀照旧（/purchase-orders）", po_api, r'APIRouter\(prefix="/purchase-orders"')
    c.ok(
        f"六个端点一个都没少（实际 {subs(po_api, '@router.')} 个装饰器）",
        subs(po_api, "@router.") >= 6,
        f"实际 {subs(po_api, '@router.')} 个",
    )
    c.ok("恢复那一条仍在（撤单后能拉回来）", '@router.post("/{order_id}/restore"' in po_api)

    print("\n== 2. 入口长在库存管理页顶栏 ==")
    c.ok(
        "InventoryScreen 全仓只有一处（不许复制一页出去）",
        len([p for p in kts if "fun InventoryScreen(" in code(p)]) == 1,
    )
    c.present(
        "签名多出两个回调、顺序固定（container / onBack / onOpenPurchaseOrders / onOpenPurchaseOrder）",
        code(INV_SCREEN),
        r"fun InventoryScreen\(\s*container: AppContainer,\s*onBack: \(\) -> Unit,\s*onOpenPurchaseOrders: \(\) -> Unit,\s*onOpenPurchaseOrder: \(Long\) -> Unit,\s*\)",
    )
    c.ok("两个回调各自带一句说明（一个是「进列表」、一个是「进某一张」）",
         "/** 进采购单列表" in inv and "/** 进某一张采购单" in inv)
    po_btn = 'TextButton(onClick = onOpenPurchaseOrders) { Text("采购单") }'
    c.ok(
        "顶栏那颗按钮逐字在、只有一处",
        subs(inv, po_btn) == 1,
        f"实际 {subs(inv, po_btn)} 处",
    )
    actions = fn_body(inv, "actions = {")
    c.ok(f"顶栏 actions 摘得出来（{len(actions)} 字）", len(actions) >= 120, f"实际 {len(actions)} 字")
    c.ok(
        "采购单那颗与「流水」都在顶栏里（不是塞进某个弹层）",
        po_btn in actions and 'TextButton(onClick = { showMovements = true }) { Text("流水") }' in actions,
    )
    inv_block = fn_body(nav, "composable(Routes.INVENTORY) {")
    c.ok(f"NavGraph 里那一格摘得出来（{len(inv_block)} 字）", len(inv_block) >= 150, f"实际 {len(inv_block)} 字")
    c.ok(
        "顶栏那颗接到采购单列表（navigate(Routes.PURCHASE_ORDERS)）",
        "onOpenPurchaseOrders = { navController.navigate(Routes.PURCHASE_ORDERS) }," in inv_block,
    )
    c.ok(
        "流水行那颗接到那一张单（表单页的 ?orderId= 档）",
        'navController.navigate(Routes.PURCHASE_ORDER_FORM + "?orderId=" + id)' in inv_block,
    )
    c.ok("两个回调都真接上了（不是空实现）", "onOpenPurchaseOrder = { id ->" in inv_block)
    c.present("列表那一页的路由仍在 NavGraph 里", nav, r"composable\(Routes\.PURCHASE_ORDERS\) \{")
    c.present("表单页仍是「一条路由两个档位」（?orderId= 参数）", nav, r'route = Routes\.PURCHASE_ORDER_FORM \+ "\?orderId=\{orderId\}"')

    print("\n== 3. 流水行能点进它属于哪张单 ==")
    dto_sig = '@SerialName("purchase_order_id") val purchaseOrderId: Long? = null,'
    c.ok("DTO 只读字段逐字在、只有一处", subs(dtos, dto_sig) == 1, f"实际 {subs(dtos, dto_sig)} 处")
    seg = dtos[first(dtos, "data class InventoryMovementDto(") :][:2500]
    c.ok("它挂在 InventoryMovementDto 里（不是别的 DTO）", dto_sig in seg)
    c.ok("可空、有缺省值（老接口没这个字段也不炸）", re.search(r"val purchaseOrderId: Long\? = null,", dtos) is not None)
    c.ok("流水行读了它", "val poId = m.purchaseOrderId" in inv)
    c.ok("只有非 null 才画那颗链接（手工调整 / 订单自动一律不画）", "if (poId != null) {" in inv)
    c.ok(
        "那颗链接可点，点的是那一张单",
        "modifier = Modifier.clickable { onOpenPurchaseOrder(poId) }," in inv,
    )
    c.ok('文案是「采购单 #N」（带数字 ⇒ 提示规范里算数据、永不隐藏）', '"采购单 #" + poId,' in inv)
    c.ok(
        "MovementRow 的签名与调用点各一处（多一个入口就多一条要维护的路）",
        subs(inv, "private fun MovementRow(m: InventoryMovementDto, onOpenPurchaseOrder: (Long) -> Unit) {") == 1
        and subs(inv, "MovementRow(m, onOpenPurchaseOrder = onOpenPurchaseOrder)") == 1,
    )

    print("\n== 4. 后端：归属是只读派生，不是第二份真相 ==")
    field = "purchase_order_id: int | None = None"
    c.ok(f"出参字段逐字在、只有一处（{field}）", subs(sch, field) == 1, f"实际 {subs(sch, field)} 处")
    c.ok("它在 MovementOut 里（出参）", first(sch, "class MovementOut(") < first(sch, field))
    c.ok("排在那批老字段之后（unit_cost 之后才追加）", first(sch, "unit_cost: Decimal | None = None") < first(sch, field))
    create_seg = sch[first(sch, "class MovementCreate(") : first(sch, "class MovementOut(")]
    c.ok(f"写模型 MovementCreate 里没有它（{len(create_seg)} 字，手工入库不能自称属于某张单）", "purchase_order_id" not in create_seg)
    c.ok("models/inventory.py 里没有这一列（不是新列）", "purchase_order_id" not in model)
    c.ok("模型仍然养着 unit_cost（说明读的是那份模型）", "unit_cost" in model)
    migs = sorted(MIGRATIONS.rglob("*.py"))
    c.ok(f"扫到 {len(migs)} 个迁移文件（>={MIN_MIGRATIONS}，防目录搬走时空转）", len(migs) >= MIN_MIGRATIONS, f"实际 {len(migs)}")
    hit = sorted(p.name for p in migs if "purchase_order_id" in read(p))
    c.ok("没有一条迁移碰它（不新增列、不回填历史）", not hit, "；".join(hit))
    c.ok("019 那份采购单迁移仍在（历史照旧）", (MIGRATIONS / "019_purchase_orders.py").exists())
    c.present("列表端点的出参仍是 list[MovementOut]", api, r'@router\.get\("/movements", response_model=list\[MovementOut\]\)')
    c.ok(
        "_attach_purchase_orders 定义一处、调用一处",
        subs(api, "def _attach_purchase_orders(db: Session, rows: list[InventoryMovement]) -> None:") == 1
        and subs(api, "_attach_purchase_orders(db, rows)") == 1,
    )
    c.ok("定义在端点之前（不是事后补的旁路）", first(api, "def _attach_purchase_orders(") < first(api, '@router.get("/movements"'))
    body = py_block(api, "def _attach_purchase_orders(")
    c.ok(f"函数体摘得出来（{len(body)} 字，防抽取失效变成永远绿的检查）", len(body) >= 300, f"实际 {len(body)} 字")
    c.ok("先取本页 id 再反查（不是逐行查）", "ids = [m.id for m in rows]" in body)
    c.ok("按本页 id 批量反查（in_）", "PurchaseOrderItem.movement_id.in_(ids)" in body)
    c.ok("明细已作废的不给回链", "PurchaseOrderItem.is_void.is_(False)" in body)
    c.ok("单子已软删的不给回链（否则点进去是回收站里的单）", "PurchaseOrder.deleted_at.is_(None)" in body)
    c.ok(
        f"整段只有一次库查询（实际 {subs(body, 'db.execute(')} 处：逐行查会变成 N+1）",
        subs(body, "db.execute(") == 1,
        f"实际 {subs(body, 'db.execute(')} 处",
    )
    c.ok("挂的是行的属性（投影，不是列）", "m.purchase_order_id = owner.get(m.id)" in body)
    c.ok(
        "归属在 finish_page 之前挂上（截断 / 加响应头不改行的身份）",
        first(api, "_attach_purchase_orders(db, rows)") < first(api, "return finish_page(rows, limit, response)"),
    )
    c.ok("端点仍把整页交给 finish_page（没绕过分页）", "return finish_page(rows, limit, response)" in api)

    print("\n== 5. 写侧与 AI 权限 ==")
    # 2026-10-07 CHG-0074（台账 L-42）：采购单的 AI 写域**后来开了** —— 用户口径 m13365 ②
    # 「上传一张进货单照片 → AI 读出供应商与每行 → 确认卡 → 建采购单」。所以这一节从
    # 「仍然不开放」改成正向断言：那四条写端点确实从 EXCLUDED 里移走了、理由写在原处；
    # 写能力也跟着入口落在「库存管理」那一格（认领跟着入口走，与读能力同一个口径）。
    wcov = read(WRITE_COVERAGE)
    c.ok("采购单的写域已开、理由写在原处（CHG-0074）", "2026-10-07 CHG-0074（台账 L-42）起已开" in wcov)
    c.ok(
        "四条写端点不再列在 EXCLUDED 里",
        not any(
            k in wcov
            for k in (
                '("POST", "purchase-orders")',
                '("PATCH", "purchase-orders/{}")',
                '("DELETE", "purchase-orders/{}")',
                '("POST", "purchase-orders/{}/restore")',
            )
        ),
    )
    c.ok('覆盖表把「采购单」读能力并到「库存管理」那一格', '["库存管理", "采购单"],' in cov)
    c.ok('覆盖表那格的写能力也认领了「采购单」', '["库存", "采购单"],' in cov)
    c.ok('不再有独立的「采购单」模块条目（否则 --check 报化石）', '"采购单": (' not in cov)
    c.ok("覆盖表那格的说明写清了采购单从它进", "采购单从它进（列表 + 表单：建单/改单/撤单/恢复）" in cov)

    print("\n== 6. 文档 / 反验 / 防静默空转 ==")
    doc = read(CHG_DOC)
    c.ok(f"变更单在：docs/changes/{CHG_ID}.md", CHG_DOC.exists())
    for sec in CHG_SECTIONS:
        c.ok(f"变更单有这一节：{sec}", any(ln.startswith(sec) for ln in doc.splitlines()))
    c.ok("变更单引着口径 ref（m13365）与用户原话的关键句", "m13365" in doc and "合并成一个" in doc)
    c.present("这条判据自己写在变更单的判据段里", doc, r"_check_inventory_purchase_merge\.py")
    c.ok(f"登记簿里有 {CHG_ID} 那一行（整行，不是一个链接里的字样）", f"[{CHG_ID}.md]({CHG_ID}.md)" in read(REGISTRY))
    c.ok(f"工作声明里有 {CHG_ID} 这一段", f"**{CHG_ID} " in read(CLAIM))
    c.ok("工作声明里记着用户原话的 ref（m01700）", "m01700" in read(CLAIM))
    c.ok(f"反向验证脚本在：{REVERSE}", (ROOT / REVERSE).exists())
    missing = [p.relative_to(ROOT).as_posix() for p in REQUIRED_FILES if not p.exists()]
    c.ok(f"{len(REQUIRED_FILES)} 个关键文件都在", not missing, "；".join(missing))

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
