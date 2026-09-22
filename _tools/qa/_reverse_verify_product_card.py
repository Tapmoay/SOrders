"""反向验证：把「商品外观与表单的单一来源」那条红线逐条弄坏，看它**真的会红**。

## 为什么这块必须反向验证
这一轮收的是**抄第二份**这类毛病，而抄第二份**从来不报错**：
卡片上多一个色值、选品页又自己画一次缩略图、表单又写一个带边框的输入框 ——
编译过、测试过、真机上看着也"差不多"。本仓库已经为这类分叉付过一次代价：
四个分类名册页各写一遍，运费那一页的「撤销排序」成了**丢行**的那一版，靠人肉比对才发现。

所以每条判据都要被证明"改坏了会红"。注入点刻意选在**别的检查不看的地方**。

用法：python _tools/qa/_reverse_verify_product_card.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_product_card_single_source.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
TESTD = ROOT / "android/app/src/test/java/com/tapmoay/sorders"
DOC = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

KIT = AND / "ui/common/ProductCardKit.kt"
FORM_ROWS = AND / "ui/common/FormRows.kt"
UNITS = AND / "ui/common/Units.kt"
UNIT_SHEET = AND / "ui/common/UnitPickerSheet.kt"
FORM_SCREEN = AND / "ui/dispatcher/ProductFormScreen.kt"
FORM_VM = AND / "ui/dispatcher/ProductFormViewModel.kt"
FORM_TEST = TESTD / "ui/dispatcher/ProductFormDiffTest.kt"
LIST = AND / "ui/dispatcher/ProductsScreen.kt"
PICKER = AND / "ui/common/ProductPicker.kt"
INVENTORY = AND / "ui/dispatcher/InventoryScreen.kt"
BATCH = AND / "ui/dispatcher/ProductBatchScreen.kt"
SORT = AND / "ui/dispatcher/ProductSortScreen.kt"
ROUTES = AND / "ui/nav/Routes.kt"
NAV = AND / "ui/nav/NavGraph.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "商品管理页又抄一份名称兜底色（5 份之一就是这么来的）",
        LIST,
        "    var quickPriceFor by remember { mutableStateOf<ProductDto?>(null) }",
        '    var quickPriceFor by remember { mutableStateOf<ProductDto?>(null) }\n'
        '    val LeakedNameColorFallback = "#1565C0"',
        "兜底色",
    ),
    (
        "把 productNameColor 的 try/catch 拆掉（库里一个脏颜色值就让整页崩）",
        KIT,
        "fun productNameColor(raw: String?): Color = try {",
        "fun productNameColor(raw: String?): Color = run {",
        "try/catch",
    ),
    (
        "选品页又自己画一次商品图（缩略图两份）",
        PICKER,
        "                ProductThumb(\n                    imageUrl = product.imageUrl,",
        "                coil.compose.AsyncImage(model = null, contentDescription = null)\n"
        "                ProductThumb(\n                    imageUrl = product.imageUrl,",
        "不再自己画商品图",
    ),
    (
        "商品管理页又自己判一次库存颜色（配色判据两份）",
        LIST,
        "@Composable\nprivate fun ProductsBottomBar(",
        "private fun leakedStockColor(stock: Int, lowStockAlert: Int) = when {\n"
        "    stock <= 0 -> Color(0xFFE53935)\n"
        "    else -> Color(0xFF00BCD4)\n"
        "}\n\n"
        "@Composable\nprivate fun ProductsBottomBar(",
        "不再自己判库存颜色",
    ),
    (
        "把单位词表抄进选择页（第二份 16 个单位）",
        UNIT_SHEET,
        "    val units = remember(current, inUse) { unitChoices(current, inUse) }",
        '    val units = remember(current, inUse) {\n'
        '        val leaked = listOf("件", "个", "块", "包", "箱")\n'
        "        leaked + unitChoices(current, inUse)\n"
        "    }",
        "单位词表只有一处",
    ),
    (
        "把 UnitPickerSheet 改成不用 FlowRow（不再是 chips 网格）",
        UNIT_SHEET,
        "                FlowRow(",
        "                Column(",
        "chips 网格",
    ),
    (
        "把 §5 里那条『单位选择页是例外』删掉（下一个人会照 §5 改回下拉）",
        DOC,
        "  - ⚠️ **登记在案的例外：单位选择页**",
        "  - ⚠️ 历史上有人试过：",
        "§5 的例外",
    ),
    (
        "表单又写一个带边框的输入框（那一屏『乱』的根因回来了）",
        FORM_SCREEN,
        '                    FormInputRow(\n                        label = "商品名称",',
        '                    androidx.compose.material3.OutlinedTextField(value = vm.name, onValueChange = {})\n'
        '                    FormInputRow(\n                        label = "商品名称",',
        "带框输入框都没有",
    ),
    (
        "把表单行的定义搬进页面（FormRows.kt 之外的第二份）",
        FORM_SCREEN,
        "private fun ProductImageBlock(",
        "private fun FormSwitchRow(label: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit, modifier: Modifier = Modifier) {}\n\n"
        "private fun ProductImageBlock(",
        "FormSwitchRow 只有一处定义",
    ),
    (
        "表单改调自己写的单位弹层（不再用共用的那一个）",
        FORM_SCREEN,
        "        UnitPickerSheet(\n            current = vm.unit,",
        "        LeakedOwnUnitPicker(\n            current = vm.unit,",
        "二级选择走共用选择页",
    ),
    (
        "商品管理页把编辑抽屉加回来（用户要的是整页）",
        LIST,
        "    // 快捷改价（只改默认售价）",
        "    androidx.compose.material3.ModalBottomSheet(onDismissRequest = {}) { }\n\n"
        "    // 快捷改价（只改默认售价）",
        "没有 ModalBottomSheet",
    ),
    (
        "把 PRODUCT_FORM 路由常量改个名（NavGraph 那边就悬空了）",
        ROUTES,
        'const val PRODUCT_FORM = "dispatcher/products/form"',
        'const val PRODUCT_FORM_X = "dispatcher/products/form"',
        "PRODUCT_FORM",
    ),
    (
        "NavGraph 的参数名与 Routes 侧写岔（点了编辑会静默落成『新增』）",
        NAV,
        'navArgument("productId") { type = NavType.LongType; defaultValue = 0L }',
        'navArgument("pid") { type = NavType.LongType; defaultValue = 0L }',
        "NavGraph 注册了它",
    ),
    (
        "列表页把旧的抽屉入口加回来（onEdit 又去调 vm.openEdit）",
        LIST,
        "                                        onEdit = { onOpenForm(p.id) },",
        "                                        onEdit = { onOpenForm(p.id); vm.openEdit(p) },",
        "入口是 onOpenForm",
    ),
    (
        "编辑退回『整份回传』（不再算差异 → 静默写回旧值）",
        FORM_VM,
        "        return productEdits(b, draft())",
        "        return ProductUpdateRequest(name = name, defaultUnitPrice = price, costPrice = cost)",
        "只有一处定义且被 ViewModel 调用",
    ),
    # ---------- 第二轮（2026-09-21）：五个页面共用行主体 / 事实构造器 ----------
    (
        "批量页又抄一份 ProductLine（行主体两份，改一处不再处处跟着变）",
        BATCH,
        "private fun ActionChip(",
        "private fun ProductLine(name: String) {}\n\nprivate fun ActionChip(",
        "ProductLine（行主体）只有一处定义",
    ),
    (
        "排序页不再走共用的行主体（自己拼一行回去）",
        SORT,
        "            ProductLine(\n                name = p.name,",
        "            Column(\n                name = p.name,",
        "走共用的 ProductLine",
    ),
    (
        "把 productFacts 里售价与库存的先后调过来（用户要的『库存放售价下面』就没了）",
        KIT,
        "    listOf(\n        productPriceFact(price, unit),\n        productStockFact(stock, lowStockAlert, unit),\n    )",
        "    listOf(\n        productStockFact(stock, lowStockAlert, unit),\n        productPriceFact(price, unit),\n    )",
        "售价排在库存前面",
    ),
    (
        "批量页把售价行手拼回来（`\"¥\" + formatMoney(…) + \"/\" + unitOrDefault(…)`）",
        BATCH,
        "                                        badge = if (p.isActive) null else ({ ProductSoldOutBadge() }),",
        "                                        badge = null,\n"
        "                                        // 手拼一行回去\n"
        '                                        name2 = "¥" + formatMoney(p.defaultUnitPrice) + "/" + unitOrDefault(p.unit),',
        "不再把「售价」拼成一行",
    ),
    (
        "商品管理页又抄一份「已沽清」角标",
        LIST,
        "@Composable\nprivate fun BottomCell(",
        "private fun ProductSoldOutBadge() {}\n\n@Composable\nprivate fun BottomCell(",
        "ProductSoldOutBadge 只有一处定义",
    ),
    (
        "库存页又自己判一次库存颜色（与商品卡那套分叉：缺货灰 vs 断货红）",
        INVENTORY,
        "            Surface(\n                shape = RoundedCornerShape(12.dp),\n                color = productStockColor(s.stock, s.lowStockAlert),\n            ) {",
        "            val leakedLow = s.lowStockAlert > 0 && s.stock <= s.lowStockAlert\n"
        "            Surface(\n                shape = RoundedCornerShape(12.dp),\n"
        "                color = productStockColor(s.stock, s.lowStockAlert),\n            ) {",
        "库存页不再自己判库存颜色",
    ),
    (
        "选品页又自己解析一次颜色（parseColor 第二份）",
        PICKER,
        "private fun pickedFact(",
        'private fun leakedParse() = android.graphics.Color.parseColor("#123456")\n\nprivate fun pickedFact(',
        "不再自己解析颜色",
    ),
    (
        "把排序行高度写回 64dp（会把新加的那行事实静默裁掉）",
        SORT,
        "private val SORT_ROW_HEIGHT = 96.dp",
        "private val SORT_ROW_HEIGHT = 64.dp",
        "排序行的高度够放下",
    ),
]

#: 「文件被搬走」这类注入：把必需文件改名，跑完再改回来（判据里有"文件都在"那一条兜底）
MOVES = [
    (
        "把单位选择页整个搬走（判据清单要能发现少了文件）",
        UNIT_SHEET,
        "文件都在",
    ),
    (
        "把 productEdits 的单测搬走（「静默写回旧值」的防线没了）",
        FORM_TEST,
        "单测文件在",
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


def verdict(expect: str) -> tuple[bool, str]:
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    return hit, f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"[X] 前提不成立：源码完好时这条红线没过\n{out[-1200:]}")
        return 1
    print("[ok] 前提：源码完好时这条红线是绿的")

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
            write_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    for label, path, expect in MOVES:
        src, crlf = read_src(path)
        moved = path.with_suffix(path.suffix + ".rv-moved")
        path.rename(moved)
        try:
            hit, detail = verdict(expect)
        finally:
            moved.rename(path)
            write_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + len(MOVES) + 1
    print()
    if bad:
        print(f"[X] {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"[ok] {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
