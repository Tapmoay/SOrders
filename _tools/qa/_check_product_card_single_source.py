"""商品「长什么样」与「表单怎么填」的**单一来源**（2026-09-21 商品管理改版第 1 期）。

## 这一轮抄了什么、为什么必须有机器的判据
用户给了一批 POS「商品管理」的截图，原话是：
> 「他其实**复用了很多的组件**……我们参考他的样式和排版，**不要完全照抄他的所有的功能**。」

我们这边恰好相反：**同一件商品在外观上有 3 份实现**（管理列表的卡、选品页的行、库存页的卡），
"商品名用什么色""库存什么颜色算该处理""售价怎么拼"这些小判据还各自散着 ——
`"#1565C0"` 这个兜底值全库一度有 **5 份**，而其中 **4 份没有 `try/catch`**
（库里一个脏颜色值就让整页崩）。

这一轮把它们收成：
· `ui/common/ProductCardKit.kt` —— 缩略图 / 事实行 / 两条判据 / 售价与库存的格式化
· `ui/common/FormRows.kt` —— 表单那一行（标签在左、值在右、能进二级的带 `>`）
· `ui/common/Units.kt` + `UnitPickerSheet.kt` —— 单位词表与选择页
· `ui/common/CategoryPickerSheet.kt` —— 从名册里单选一个
· `ui/dispatcher/ProductFormScreen.kt` + `ProductFormViewModel.kt` —— 新增/编辑商品那一页

## ⛔ 为什么不能只靠"注释里写着别抄第二份"
抄第二份的代价在这个仓库里**已经发生过**：四个分类名册页各写一遍，
结果运费那一页的「撤销排序」是**丢行**的那一版（保存之后新建的分类会从列表里消失），
是靠人肉比对另外两页才发现的 —— 同一个按钮、三页两种行为，**谁都没报错**。
所以每一条都要有一条能红的判据，且每条都能被反向验证弄红（见
`_tools/ai/_reverse_verify_product_card.py`）。

用法：python _tools/qa/_check_product_card_single_source.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders"
DOC = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
ROUTES = AND / "ui/nav/Routes.kt"
NAV = AND / "ui/nav/NavGraph.kt"

KIT = AND / "ui/common/ProductCardKit.kt"
FORM_ROWS = AND / "ui/common/FormRows.kt"
UNITS = AND / "ui/common/Units.kt"
UNIT_SHEET = AND / "ui/common/UnitPickerSheet.kt"
CAT_SHEET = AND / "ui/common/CategoryPickerSheet.kt"
FORM_SCREEN = AND / "ui/dispatcher/ProductFormScreen.kt"
FORM_VM = AND / "ui/dispatcher/ProductFormViewModel.kt"
FORM_TEST = TEST / "ui/dispatcher/ProductFormDiffTest.kt"

LIST = AND / "ui/dispatcher/ProductsScreen.kt"
PICKER = AND / "ui/common/ProductPicker.kt"
INVENTORY = AND / "ui/dispatcher/InventoryScreen.kt"
BATCH = AND / "ui/dispatcher/ProductBatchScreen.kt"
SORT = AND / "ui/dispatcher/ProductSortScreen.kt"
BATCH_PRICE = AND / "ui/dispatcher/BatchPriceSheets.kt"
PRICE_MATRIX = AND / "ui/dispatcher/PriceMatrixScreen.kt"

#: 这一轮新增/搬动的文件 —— 少一个就红（防"文件被搬走 → 判据全都空转 → 满屏绿灯"）。
REQUIRED_FILES = [
    KIT, FORM_ROWS, UNITS, UNIT_SHEET, CAT_SHEET, FORM_SCREEN, FORM_VM, FORM_TEST, BATCH, SORT,
]

#: 三条商品外观都必须走零件（它们自己不许再画缩略图）。
THREE_VIEWS = [LIST, PICKER, INVENTORY]

#: **渲染商品**的页面（第二轮起全部走 `ProductLine` + `productFacts`）。
#: 少一个就会漏掉一处"改了一个地方、别处不跟着变"（用户 2026-09-21 的原话）。
PRODUCT_LINE_VIEWS = [LIST, BATCH, SORT, PICKER]

#: 这些页面里**不许**再出现 `"¥" + …` 这种手拼价格 / `parseColor` 这种手解颜色。
NO_HAND_ROLLED_MONEY = [LIST, BATCH, SORT, PICKER, BATCH_PRICE]
NO_HAND_ROLLED_COLOR = [LIST, BATCH, SORT, PICKER, INVENTORY, PRICE_MATRIX]

#: 扫到的界面文件数下限（防目录改名/搬走之后"一个文件都没扫到"也算过）。
MIN_UI_FILES = 100


def strip_comments(src: str) -> str:
    """去掉 `//` 行注释与 `/* */` 块注释 —— 判据只看**代码**，不看散文。

    ⚠️ **不能用正则一把梭**（第一版就是那么写的，当场被自己坑了）：
    `ProductFormScreen.kt` 里有一句 `pickImage.launch("image/*")` ——
    那个**字符串里的 `/*`** 会被 `re.sub(r"/\\*.*?\\*/")` 当成块注释的开头，
    于是从那一行一直吃到下一个 `*/`，把**整个表单主体**删掉，
    判据开始报"表单没走共用行"这种假红。所以这里用一个小状态机，
    同时跟踪"块注释里"与"字符串里"两种状态（改这里之前先想清楚这一点）。
    """
    out: list[str] = []
    in_block = False
    for line in src.split("\n"):
        res: list[str] = []
        i = 0
        in_str = False
        while i < len(line):
            ch = line[i]
            nxt = line[i + 1] if i + 1 < len(line) else ""
            if in_block:
                if ch == "*" and nxt == "/":
                    in_block = False
                    i += 2
                else:
                    i += 1
                continue
            if in_str:
                res.append(ch)
                if ch == "\\" and nxt:
                    res.append(nxt)
                    i += 2
                    continue
                if ch == '"':
                    in_str = False
                i += 1
                continue
            if ch == '"':
                in_str = True
                res.append(ch)
                i += 1
                continue
            if ch == "/" and nxt == "*":
                in_block = True
                i += 2
                continue
            if ch == "/" and nxt == "/":
                break
            res.append(ch)
            i += 1
        out.append("".join(res))
    return "\n".join(out)


def read(p: Path) -> str:
    # ⚠️ 文件被搬走时**不要抛栈**：那条判据自己会红（`REQUIRED_FILES`），
    #    这里再抛异常的话整条检查会以"崩溃"收场 —— `[FAIL]` 一行都打不出来，
    #    而反向验证（`_reverse_verify_product_card.py` 的 MOVES）正是靠那几行判对错的。
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


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

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def main() -> int:
    c = Checker()
    print("商品外观与表单的单一来源（商品管理改版第 1 期）")

    # ---- 0. 防化石：这些文件必须在 ----
    missing = [p.name for p in REQUIRED_FILES if not p.exists()]
    c.ok("这一轮新增的零件/页面文件都在", not missing, f"缺：{missing}")

    ui_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(ui_files) >= MIN_UI_FILES,
        f"实际 {len(ui_files)}",
    )

    # ---- 1. 商品名颜色：兜底值只有一份、且是"不抛异常"的那一份 ----
    holders = [p.name for p in ui_files if '"#1565C0"' in code(p)]
    c.ok(
        '"#1565C0"（商品名兜底色）只在 ProductCardKit.kt 里出现',
        holders == ["ProductCardKit.kt"],
        f"实际出现在：{holders}",
    )
    c.ok(
        "productNameColor 的兜底在 try/catch 里（脏颜色值不许让整页崩）",
        # ⚠️ 判据要**连 `try` 一起认**：只找 "catch" 的话，"把 try 换成 run" 这种坏法照样能过
        #    （反向验证抓出来的：注入之后 `catch` 还在，判据却不该绿）
        re.search(r"fun productNameColor\(.*?\):\s*Color\s*=\s*try\s*\{", code(KIT), re.S) is not None
        and "catch" in code(KIT),
        "ProductCardKit.kt 里 productNameColor 不是 `= try { … } catch`",
    )
    others = [p.name for p in ui_files if count(r"fun productNameColor", code(p)) and p != KIT]
    c.ok("productNameColor 只有一处定义", not others, f"另有定义：{others}")

    # ---- 2. 商品缩略图：三页都不许自己画 ----
    for p in THREE_VIEWS:
        n = count(r"AsyncImage\s*\(", code(p))
        c.ok(f"{p.name} 不再自己画商品图（AsyncImage 0 处）", n == 0, f"实际 {n} 处")
    c.ok(
        "ProductThumb 只有一处定义",
        count(r"fun ProductThumb", code(KIT)) == 1
        and not [p.name for p in ui_files if p != KIT and count(r"fun ProductThumb", code(p))],
        "ProductThumb 在别处也被定义了",
    )

    # ---- 3. 管理与库存两页的"事实行"判据都搬走了 ----
    c.ok(
        "ProductsScreen.kt 不再自己判库存颜色（stock <= 0 / lowStockAlert > 都在零件里）",
        count(r"stock\s*<=\s*0", code(LIST)) == 0 and count(r"lowStockAlert\s*>", code(LIST)) == 0,
        "商品管理页里还留着库存配色判据",
    )
    c.ok("ProductsScreen.kt 不再自己拼售价文案", count(r"productFacts\s*\(", code(LIST)) >= 1)
    c.ok("ProductsScreen.kt 用的是零件画的商品卡", count(r"ProductThumb\s*\(", code(LIST)) >= 1)

    # ---- 4. 售价/库存两行的格式化只有一处 ----
    c.ok(
        "productPriceFact / productStockFact / ProductFacts 只有一处定义",
        count(r"fun productPriceFact", code(KIT)) == 1
        and count(r"fun productStockFact", code(KIT)) == 1
        and count(r"fun ProductFacts", code(KIT)) == 1,
        "ProductCardKit.kt 里的定义数不对",
    )
    dup = [
        p.name
        for p in ui_files
        if p != KIT and count(r"fun (productPriceFact|productStockFact|ProductFacts|productStockColor)", code(p))
    ]
    c.ok("这三条判据没有第二份实现", not dup, f"另有实现：{dup}")

    # ---- 4b. 五个渲染商品的页面共用同一个"行主体"与同一个"事实构造器" ----
    # 用户 2026-09-21（第二轮）：「像我们这样子的形式——比如说右边是分类、它是个条的，
    # 那个商品啊，它其实是有点区别的…你也**全部做深**吧…**其他地方你也得改**，
    # 最好是采用（通）用的继承，**上次你改一个地方，它就其他跟着改了**。」
    c.ok(
        "ProductLine（行主体）只有一处定义",
        count(r"fun ProductLine\(", code(KIT)) == 1
        and not [p.name for p in ui_files if p != KIT and count(r"fun ProductLine\(", code(p))],
        "ProductLine 在别处也被定义了",
    )
    for p in PRODUCT_LINE_VIEWS:
        c.ok(f"{p.name} 的商品行/卡走共用的 ProductLine", count(r"ProductLine\(", code(p)) >= 1)

    c.ok(
        "productFacts（事实构造器）只有一处定义",
        count(r"fun productFacts\(", code(KIT)) == 1
        and not [p.name for p in ui_files if p != KIT and count(r"fun productFacts\(", code(p))],
        "productFacts 在别处也被定义了",
    )
    m = re.search(r"fun productFacts\([^)]*\)[^=]*=\s*(.*?)\n\n", code(KIT), re.S)
    body = m.group(1) if m else ""
    c.ok(
        "productFacts 里**售价排在库存前面**（用户要的「库存在售价下面」就定在这一处）",
        body.count("productPriceFact") == 1
        and body.count("productStockFact") == 1
        and 0 <= body.find("productPriceFact") < body.find("productStockFact"),
        "取不到 productFacts 的函数体，或两行的先后被换了",
    )

    # 手拼价格 / 手解颜色：这一轮各消灭了一份，不许再长回来
    #
    # ⚠️ 判据**只盯"把商品售价拼成一行"这个惯用法**（`"¥" + formatMoney(…) … unitOrDefault(…)`），
    #    不是"这个文件里不许出现 ¥"：这两个文件里还有**别的钱**——
    #    `ProductPicker` 的数量小窗里是**订单小计**（价 × 数量）、
    #    `ProductsScreen` 的成本价历史里是 `trimMoneyZeros` 拼的**成本**。
    #    一条"凡 ¥ 必红"的判据会把它们一起打红，然后下一个人只会把判据关掉。
    money = [
        p.name
        for p in NO_HAND_ROLLED_MONEY
        for ln in code(p).split("\n")
        if '"¥"' in ln and "formatMoney" in ln and "unitOrDefault" in ln
    ]
    c.ok(
        "这几个页面不再把「售价」拼成一行（格式化只有 productPriceFact 一处）",
        not money,
        f"还在手拼售价行：{money}",
    )
    for p in PRODUCT_LINE_VIEWS:
        c.ok(
            f"{p.name} 的售价走共用事实构造器",
            count(r"productFacts\(", code(p)) >= 1 or count(r"productPriceFact\(", code(p)) >= 1,
        )
    color = [p.name for p in NO_HAND_ROLLED_COLOR if "parseColor" in code(p)]
    c.ok(
        "这几个页面不再自己解析颜色（productNameColor 一处，脏值不许崩）",
        not color,
        f"还在自己解析：{color}",
    )

    # 库存页的颜色判据也必须搬走（搬之前它自己那套和商品卡**不一样**：低库存红/缺货灰）
    c.ok(
        "库存页不再自己判库存颜色（判据只有 productStockColor / productStockBadgeText 一处）",
        count(r"stock\s*<=\s*0", code(INVENTORY)) == 0 and count(r"lowStockAlert\s*>", code(INVENTORY)) == 0,
        "库存页里还留着库存配色判据",
    )
    c.ok(
        "库存页用的是共用的事实行与共用角标",
        count(r"productStockFact\(", code(INVENTORY)) >= 1
        and count(r"ProductStockBadge\(", code(INVENTORY)) >= 1,
        "库存页没用 ProductCardKit 的事实行/角标",
    )

    for fn in ("ProductSoldOutBadge", "ProductStockBadge", "productStockBadgeText", "productReservedFact"):
        c.ok(
            f"{fn} 只有一处定义",
            count(rf"fun {fn}\(", code(KIT)) == 1
            and not [p.name for p in ui_files if p != KIT and count(rf"fun {fn}\(", code(p))],
            f"{fn} 在别处也被定义了",
        )
    sold = [p.name for p in (LIST, BATCH, PICKER) if count(r"ProductSoldOutBadge\(", code(p)) >= 1]
    c.ok(
        "「已沽清」角标在三个会显示它的页面上都是同一份实现",
        len(sold) == 3,
        f"只有这些页面用了它：{sold}",
    )

    # 排序行高度：这一轮行里多了一行事实，高度写小了会**静默裁掉**那一行
    mh = re.search(r"SORT_ROW_HEIGHT\s*=\s*(\d+)\.dp", code(SORT))
    c.ok(
        "排序行的高度够放下「名称 + 售价 + 库存」（写小了会把事实行裁掉，且不报错）",
        mh is not None and int(mh.group(1)) >= 90,
        f"实际 {mh.group(1) + 'dp' if mh else '取不到'}",
    )

    # ---- 5. 单位：词表与选择页各只有一处 ----
    unit_holders = [
        p.name for p in ui_files if re.search(r'"件"\s*,\s*"个"\s*,\s*"块"', code(p))
    ]
    c.ok(
        "单位词表只有一处（`\"件\",\"个\",\"块\"…` 这种连排清单只许在 Units.kt 里）",
        unit_holders == ["Units.kt"],
        f"实际出现在：{unit_holders}",
    )
    c.ok(
        "unitChoices / filterUnits / UNIT_PRESETS 只有一处定义",
        all(count(pat, code(UNITS)) == 1 for pat in (r"fun unitChoices", r"fun filterUnits"))
        and count(r"val UNIT_PRESETS", code(UNITS)) == 1,
        "Units.kt 里的定义数不对",
    )
    c.ok(
        "UnitPickerSheet 只有一处定义，且是 chips 网格（FlowRow）",
        count(r"fun UnitPickerSheet", code(UNIT_SHEET)) == 1 and "FlowRow" in code(UNIT_SHEET),
        "选择页没了或没走 FlowRow",
    )
    c.ok(
        "⚠️ 单位选择页是 §5 的例外，规范里必须写着它（否则下一个人会照 §5 改回下拉）",
        DOC.exists() and "单位选择页" in read(DOC) and "chips" in read(DOC),
        "06_DESIGN_SYSTEM.md §5 里没记这条例外",
    )

    # ---- 6. 表单行：一套定义 + 表单页不许再有带框输入框 ----
    for fn in ("FormInputRow", "FormPickRow", "FormSwitchRow"):
        c.ok(
            f"{fn} 只有一处定义",
            count(rf"fun {fn}\(", code(FORM_ROWS)) == 1
            and not [p.name for p in ui_files if p != FORM_ROWS and count(rf"fun {fn}\(", code(p))],
            f"{fn} 在别处也被定义了",
        )
    c.ok(
        "商品表单里一个带框输入框都没有（那一屏「乱」的根因就是三个 OutlinedTextField）",
        count(r"OutlinedTextField", code(FORM_SCREEN)) == 0,
        f"实际 {count(r'OutlinedTextField', code(FORM_SCREEN))} 处",
    )
    c.ok(
        "商品表单用的是共用行（输入 / 选择 / 开关各至少一处）",
        all(count(rf"{fn}\(", code(FORM_SCREEN)) >= 1 for fn in ("FormInputRow", "FormPickRow", "FormSwitchRow")),
        "有行没走 FormRows.kt",
    )
    c.ok(
        "商品表单的二级选择走共用选择页（单位 + 分组）",
        count(r"UnitPickerSheet\(", code(FORM_SCREEN)) >= 1
        and count(r"CategoryPickerSheet\(", code(FORM_SCREEN)) >= 1,
        "表单自己写了选择弹层",
    )

    # ---- 7. 新增/编辑不再是抽屉 ----
    c.ok("ProductsScreen.kt 里没有 ModalBottomSheet 了（编辑改成单独一页）", count(r"ModalBottomSheet", code(LIST)) == 0)
    c.ok(
        "Routes 里有 PRODUCT_FORM 与它的构造函数",
        # ⚠️ 用 `const val PRODUCT_FORM =`（不是子串 "PRODUCT_FORM"）：
        #    改名成 `PRODUCT_FORM_X` 时子串仍然命中 —— 反向验证抓出来的
        re.search(r"const val PRODUCT_FORM\s*=", code(ROUTES)) is not None
        and count(r"fun productForm\(", code(ROUTES)) == 1,
        "路由没加或加了两个",
    )
    # ⚠️ 判据要**只看这一条路由那一段**：NavGraph 里 `navArgument("productId")` 还有别处
    #    （价格矩阵的"按商品"页），全局找它的话"参数名写岔了"照样能过（反向验证抓出来的）。
    nav = code(NAV)
    try:
        seg = nav[nav.index("Routes.PRODUCT_FORM") :][:700]
    except ValueError:
        seg = ""
    c.ok(
        "NavGraph 注册了它，且那一段里 productId 参数名与 Routes 侧一致",
        'navArgument("productId")' in seg and 'getLong("productId")' in seg and "ProductFormScreen(" in seg,
        "注册缺失或参数名对不上（对不上会静默落成「新增」）",
    )
    c.ok(
        "列表页的入口是 onOpenForm（不是旧的 vm.openEdit）",
        "onOpenForm" in code(LIST) and "vm.openEdit" not in code(LIST),
        "还挂着旧的抽屉入口",
    )

    # ---- 8. 「只发改动的键」：纯函数在、且被真的调用、且单测在 ----
    c.ok(
        "productEdits 只有一处定义且被 ViewModel 调用",
        count(r"fun productEdits\(", code(FORM_VM)) == 1 and count(r"productEdits\(", code(FORM_VM)) >= 2,
        "纯函数没了或没被调用（那就退回「整份回传」）",
    )
    c.ok(
        "productEdits 的单测文件在（它是「静默写回旧值」的唯一防线）",
        FORM_TEST.exists() and "productEdits" in read(FORM_TEST),
        "单测文件缺失",
    )
    c.ok(
        "新增/编辑商品是一次请求 + 一次可选上传，没有「读出来整套再写回去」",
        count(r"updateProduct\(", code(FORM_VM)) == 1,
        f"updateProduct 调用了 {count(r'updateProduct\(', code(FORM_VM))} 次",
    )

    # ---- 9. 底栏与旧入口不许回潮 ----
    c.ok(
        "商品管理页不再有「打开抽屉」的入口（showDialog / draftName 这些草稿字段已搬走）",
        "showDialog" not in code(LIST) and "draftName" not in code(LIST),
        "列表页还留着表单草稿",
    )

    return c.report("商品外观 / 表单 单一来源")


if __name__ == "__main__":
    sys.exit(main())
