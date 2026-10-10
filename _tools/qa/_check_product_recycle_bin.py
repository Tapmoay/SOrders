"""商品的**回收站**：弹窗承诺的那个入口，从后端参数一路钉到界面上那一排（BUG-0035 / 台账 TA-11、TA-03）。

## 这条判据在防什么

商品删除的确认弹窗一直承诺「列表顶端的『回收站』里可以把它恢复回来」，而那个入口
**从来没有做出来**（第 4 轮实测：`ProductsScreen.kt` 里「回收站」零命中、`Apis.kt` 的
`listProducts` 连 `deleted_only` 参数都没有）。这一轮补齐之后，最怕的不是"没做"，
而是**做了一半**：

· 后端加了参数但缺省查询把这些行漏进普通列表（选品页会冒出已删商品）；
· 回收站分支顺手套了 `is_active` 过滤（删除会强制下架 ⇒ **回收站恒空**，比没有更糟）；
· App 画了入口但没真的调 `restoreProduct`（点「恢复」什么也不发生）；
· 入口画在了搜索框下面 —— 而弹窗承诺的是"列表**顶端**"（文案与实现不是同一件事）。

所以下面每一节都对应其中一条：**参数语义 → 只列已删 → 恢复真的被调到 → 入口在顶端且文案同源**。

## 清单自己算

"界面里有几处还在承诺旧位置""哪些文件引用了 `undoDelete`"这一类**不写死文件名单**：
UI 文件从 `android/app/src/main/java/com/tapmoay/sorders/ui` 现 glob，再逐条正则扫。
数不到下限（`MIN_UI_FILES`）先报红 —— 目录被搬走时不许"全绿"。

用法：python -X utf8 _tools/qa/_check_product_recycle_bin.py [仓库根]
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
UI = AND / "ui"
PRODUCTS_API = ROOT / "backend/app/api/v1/products.py"
TEST = ROOT / "backend/tests/test_product_recycle_bin.py"
APIS = AND / "data/remote/api/Apis.kt"
REPO = AND / "data/repo/AppRepository.kt"
SCREEN = UI / "dispatcher/ProductsScreen.kt"
KIT = UI / "common/ProductCardKit.kt"
VM = UI / "dispatcher/ProductsViewModel.kt"
FORM = UI / "dispatcher/ProductFormScreen.kt"
BATCH = UI / "dispatcher/ProductBatchScreen.kt"
FORM_VM = UI / "dispatcher/ProductFormViewModel.kt"
SPEC = ROOT / "docs/changes/BUG-0035.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
LEDGER = ROOT / "docs/TEST_BUG_LEDGER.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_product_recycle_bin.py"

#: 扫到的界面文件数下限（目录被搬走时先报错，而不是安静地什么都查不到）
MIN_UI_FILES = 100

#: 三处承诺文案必须共用的那一句话（入口在哪 —— 它就是"文案与实现同源"的那根钉子）
WHERE = "最上面那一排的「回收站」"


def strip_comments(src: str) -> str:
    """去掉 `//` 行注释与 `/* */` 块注释 —— 判据只看**代码**，不看散文。

    ⚠️ 不能正则一把梭：Kotlin 里 `"…/*…"` 这种字符串会把后面整段吃掉
    （`_check_product_card_single_source.py` 的同一处注释记着这个坑）。这里用一个小状态机，
    同时跟踪"块注释里"与"字符串里"两种状态。
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
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def py_code(src: str) -> str:
    """后端/脚本源码是 **Python**：注释符是 `#` 而不是 `//`（`strip_comments` 只认 Kotlin）。

    ⚠️ 少这一步的后果实测过一次：回收站那段里的中文注释写着"不许再套 is_active"，
    而判据正是在找 `is_active` —— 于是一条**正确**的实现被判红。
    这里只丢整行注释（本文件里的注释都是整行写的）。
    """
    return "\n".join(ln for ln in src.split("\n") if not ln.strip().startswith("#"))


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + label)
        else:
            self.fails.append(label + (" —— " + detail if detail else ""))
            print("  [FAIL] " + label + (" —— " + detail if detail else ""))

    def section(self, name: str) -> None:
        print()
        print("== " + name + " ==")

    def report(self, title: str) -> int:
        print()
        print("===== " + title + " =====")
        print("  通过 " + str(self.passes) + " 项，失败 " + str(len(self.fails)) + " 项")
        for f in self.fails:
            print("    - " + f)
        return 1 if self.fails else 0


def bin_block(src: str) -> str:
    """`list_products` 里 `if deleted_only:` 那一段（到它自己的 return 为止）。"""
    m = re.search(r"\n    if deleted_only:\n(.*?\n)    q = select\(Product\)", src, re.S)
    return m.group(1) if m else ""


def card_body(src: str) -> str:
    m = re.search(r"private fun RecycleBinCard\(.*?\n\}", src, re.S)
    return m.group(0) if m else ""


def main() -> int:
    c = Checker()
    print("商品的回收站：删掉的商品能从界面上找回来（BUG-0035）")

    ui_files = list(UI.rglob("*.kt"))
    api = read(PRODUCTS_API)
    api_code = py_code(read(PRODUCTS_API))
    screen = read(SCREEN)
    screen_code = code(SCREEN)
    vm = read(VM)
    vm_code = code(VM)
    apis = read(APIS)
    repo = read(REPO)
    form = read(FORM)
    batch = read(BATCH)
    test = read(TEST)

    # ---- 0. 防化石 + 清单下限 ----
    c.section("0. 防化石（文件都在、清单不是空的）")
    need = (PRODUCTS_API, TEST, APIS, REPO, SCREEN, VM, FORM, BATCH, FORM_VM, SPEC, REVERSE)
    missing = [p.name for p in need if not p.exists()]
    c.ok("这一轮碰过的文件都在", not missing, "缺：" + str(missing))
    c.ok(
        "扫到的界面文件数 >= " + str(MIN_UI_FILES) + "（防目录搬走导致判据空转）",
        len(ui_files) >= MIN_UI_FILES,
        "实际 " + str(len(ui_files)),
    )
    c.ok("后端 list_products 还在（一处 @router.get 空路径）",
         count(r"@router\.get\(\"\"", api_code) == 1,
         "实际 " + str(count(r"@router\.get\(\"\"", api_code)) + " 处")

    # ---- 1. 后端参数语义 ----
    c.section("1. 后端：两个查询参数（不是新端点）")
    c.ok("deleted_only 是 list_products 的查询参数",
         count(r"deleted_only: bool = Query\(", api_code) == 1)
    c.ok("include_deleted 是 list_products 的查询参数",
         count(r"include_deleted: bool = Query\(", api_code) == 1)
    c.ok("两个参数都默认 False（缺省行为与加它们之前逐字一致）",
         count(r"deleted_only: bool = Query\(\s*False,", api_code) == 1
         and count(r"include_deleted: bool = Query\(\s*False,", api_code) == 1)
    c.ok("两个参数都没被写进路由（查询参数 != 新端点）",
         count(r"@router\.(get|post|patch|delete)\([^)]*deleted", api_code) == 0)
    c.ok("回收站只有能恢复它的人能看（门 = 既有的 product:manage，403 而不是静默降级）",
         bool(re.search(r"if \(deleted_only or include_deleted\) and not role_has_permission\(rk, Permission\.PRODUCT_MANAGE\):", api_code))
         and "status.HTTP_403_FORBIDDEN" in api_code
         and 'detail="无权查看回收站"' in api_code)
    c.ok("include_inactive 的语义与那句描述一个字没动",
         "含已下架商品" in api
         and "if include_inactive and rk not in (UserRole.DISPATCHER.value, UserRole.SHIPPER.value):" in api_code)

    # ---- 2. 只列已删 / 缺省不含已删 ----
    c.section("2. 后端：只列已删，缺省一个已删商品都不回")
    blk = bin_block(api_code)
    c.ok("回收站分支存在（有它自己的取数与 return）",
         bool(blk) and "return [product_out(" in blk, "取不到那一段（源码结构变了就更新本判据）")
    c.ok("回收站只取 is_deleted=True 的行", "Product.is_deleted.is_(True)" in blk)
    c.ok("回收站按删除时间倒序（刚删的在最上面）",
         "Product.deleted_at.desc()" in blk and "Product.id.desc()" in blk)
    c.ok("回收站分支没有再套 is_active 过滤（套上去回收站恒空 —— 删除会强制下架）",
         "is_active" not in blk, "回收站那一段里出现了 is_active")
    c.ok("缺省查询仍然排除已删商品（if not include_deleted + is_deleted false）",
         bool(re.search(r"if not include_deleted:\s*\n\s*q = q\.where\(Product\.is_deleted\.is_\(False\)\)", api_code)))
    c.ok("include_deleted 时已删的排在最后（is_deleted 的 CASE 写在 is_active 之前）",
         "case((Product.is_deleted.is_(False), 0), else_=1)" in api_code
         and api_code.index("case((Product.is_deleted.is_(False), 0), else_=1)")
         < api_code.index("case((Product.is_active.is_(True), 0), else_=1)"))
    c.ok("include_deleted 且只看在售时，放行已删的（or_ 那一行）",
         "or_(Product.is_active.is_(True), Product.is_deleted.is_(True))" in api_code)

    # ---- 3. 后端单测（删 -> 缺省查不到 -> 回收站查得到 -> 恢复 -> 缺省查得到） ----
    c.section("3. 后端单测：那一整条往返")
    c.ok("单测存在且覆盖四个动作",
         "assert pid not in _ids(_list(client, token_dispatcher))" in test
         and 'deleted_only="true"' in test
         and "/restore" in test
         and "assert pid in _ids(_list(client, token_dispatcher))" in test)
    c.ok("恢复后与删之前逐项对比（不是只看 id）", "after == before" in test)
    c.ok("非管理员拿不到回收站（403，不是空列表）", "assert r.status_code == 403" in test)
    c.ok("缺省查询与回收站两批 id 不许有交集（那条不变量也在单测里）",
         "bin_ids & alive_ids" in test or "not (bin_ids & alive_ids)" in test)

    # ---- 4. App 取数链路：参数真的传下去、恢复真的被调到 ----
    c.section("4. App：取数带 deleted_only、恢复真的调 restoreProduct")
    c.ok("Apis.kt 的 listProducts 带 deleted_only 查询参数",
         '@Query("deleted_only") deletedOnly: Boolean = false' in apis)
    c.ok("既有的 includeInactive: Boolean = true 子串没被改掉",
         "includeInactive: Boolean = true" in apis)
    c.ok("AppRepository 另起了一条取数路径（没动 products() 的签名）",
         "suspend fun deletedProducts() = api.productApi.listProducts(deletedOnly = true)" in repo
         and "suspend fun products(includeInactive: Boolean = true)" in repo)
    c.ok("ProductsViewModel 调的是 repo.deletedProducts()",
         "container.repo.deletedProducts()" in vm_code)
    c.ok("ProductsViewModel 的恢复调的是 repo.restoreProduct(（既有端点）",
         "container.repo.restoreProduct(" in vm_code)
    # ⚠️ 这里必须逐条点名**三处写入各自被挡住**，不能只数 `if (bin == recycleBin)` 出现几次：
    #    切档那一句 `if (bin == recycleBin) return` 也算一次，数数会让"去掉一处守卫"照样绿
    #    （反验的 App② 就是这样抓出来的）。
    guards = [
        "if (bin == recycleBin) binItems = list",
        "if (bin == recycleBin) binError = toApiException(e).message",
        "if (bin == recycleBin) binLoading = false",
    ]
    c.ok("取数回来按页签核对（列表 / 错误 / 加载态三处写入各自被挡住）",
         all(x in vm_code for x in guards),
         "缺：" + str([x for x in guards if x not in vm_code]))
    c.ok("成功提示写清恢复到哪儿、什么状态",
         "已恢复到商品列表（" in vm and 'if (back.isActive) "上架" else "沽清"' in vm)

    # ---- 5. 界面入口：在列表顶端，文案与实现同源 ----
    c.section("5. 界面：在用 / 回收站 那一排在列表顶端")
    c.ok("回收站入口存在（SegmentedPicker + switchRecycleBin）",
         'labels = listOf("在用", "回收站")' in screen_code and "vm.switchRecycleBin(" in screen_code)
    picker_at = screen_code.find('labels = listOf("在用", "回收站")')
    search_at = screen_code.find("OutlinedTextField(")
    c.ok("入口画在搜索框之上（弹窗承诺的是列表顶端）",
         0 <= picker_at < search_at, "入口 @" + str(picker_at) + "、搜索框 @" + str(search_at))
    anchor = screen_code.find("Box(Modifier.weight(1f)) {")
    c.ok("入口画在列表容器之前（_check_delete_undo.py 的 LIST_ANCHOR 那条规矩）",
         0 <= picker_at < anchor, "入口 @" + str(picker_at) + "、列表容器 @" + str(anchor))
    c.ok("回收站那一档换的是整块内容（when 的第一条臂）",
         bool(re.search(r"when \{\s*\n(?:\s*//[^\n]*\n)*\s*vm\.recycleBin ->", screen_code)))
    c.ok("空回收站说回收站是空的（不是暂无商品）",
         '"回收站是空的"' in screen and '"暂无商品，点下方「商品新增」"' in screen)
    c.ok("取数失败留在页面上（binError + 重试），不被提示条吃掉",
         "vm.binError.orEmpty()" in screen_code and "onRetry = { vm.loadBin() }" in screen_code)
    c.ok("每一行都有恢复，且调的是 vm.restoreFromBin(",
         count(r"vm\.restoreFromBin\(", screen_code) == 1
         and "onRestore = { vm.restoreFromBin(p) }" in screen_code)
    body = card_body(screen_code)
    c.ok("回收站那一行不出现改价/沽清/上架/编辑（那些动作的对象是在用商品）",
         bool(body) and not any(k in body for k in ("改价", "沽清", "上架", "编辑")),
         "取不到 RecycleBinCard 的函数体" if not body else "行里出现了在用商品的动作")
    c.ok("行内容复用商品零件（ProductLine + productFacts + ProductThumb）",
         all(k in body for k in ("ProductLine(", "productFacts(", "ProductThumb(")))
    c.ok("回收站的角标是已删除，不是已沽清（两件事两个词）",
         "RecycleBinBadge(" in body and "ProductSoldOutBadge(" not in body,
         "在用商品那张卡上仍然该用共用的 ProductSoldOutBadge —— 这里只管回收站那一行")
    kit = read(KIT)
    c.ok("那枚角标住在共用件里（ProductCardKit.kt 的 RecycleBinBadge，全库唯一一处）",
         count(r"fun RecycleBinBadge\(", "".join(read(p) for p in ui_files)) == 1
         and '"已删除"' in kit)
    c.ok("⛔ 商品管理页自己没有画第二层灰底（surfaceVariant 只许在共用件里）",
         "surfaceVariant" not in code(SCREEN), "ProductsScreen.kt 里出现了 surfaceVariant")
    c.ok("顶栏/底栏的动作没被这一轮搬走（单位换算与排序仍在顶栏、底栏三格仍在）",
         'Text("单位换算")' in screen_code and 'Text("排序")' in screen_code
         and "ProductsBottomBar(" in screen_code)

    # ---- 6. 三处承诺文案与实现同源 ----
    c.section("6. 三处承诺文案与实现同源（不许说 A 做 B）")
    for name, src in (("ProductFormScreen.kt", form), ("ProductBatchScreen.kt", batch)):
        c.ok(name + " 里写清了入口在哪（含「" + WHERE + "」）", WHERE in src)
    c.ok("旧位置不再作为界面文案出现（全库字符串字面量 0 处）",
         not [p for p in ui_files if '"列表顶端的「回收站」' in read(p)],
         "还有文件在写旧位置")
    # 撤销这件事在别处是真的有（欠款单位 / 名册 / 地址各一份 `fun undoDelete()`）——
    # 要钉的是「**没有定义却在引用**」：提到 undoDelete 的文件必须自己定义或调用它。
    callers = [p.name for p in ui_files if "undoDelete" in read(p)
                and ("fun undoDelete(" not in read(p) and "vm.undoDelete(" not in read(p))]
    c.ok("没有文件凭空引用不存在的撤销函数（提到 undoDelete 就得自己定义或调用）",
         not callers, "还在凭空引用：" + str(callers))
    c.ok("表单页那段 KDoc 现在指向真的入口（SegmentedPicker / restoreFromBin）",
         "SegmentedPicker(在用 / 回收站)" in read(FORM_VM) and "restoreFromBin" in read(FORM_VM))

    # ---- 7. 文书与配对 ----
    c.section("7. 文书与配对")
    spec = read(SPEC)
    c.ok("变更单 docs/changes/BUG-0035.md 在，且写了这一轮两处脚本名",
         bool(spec) and "_check_product_recycle_bin.py" in spec
         and "_reverse_verify_product_recycle_bin.py" in spec)
    c.ok("登记簿里有带链接的那一行",
         "| `BUG-0035` |" in read(README) and "](BUG-0035.md)" in read(README))
    c.ok("认领页有 BUG-0035 块与核心改动：无",
         "BUG-0035" in read(CLAIM) and "核心改动：**无**" in read(CLAIM))
    ledger = read(LEDGER)
    c.ok("台账 TA-11 与 TA-03 两行都改成了已修复（带短哈希）",
         count(r"\| TA-11 \|.*已修复 [0-9a-f]{7}", ledger) >= 1
         and count(r"\| TA-03 \|.*已修复 [0-9a-f]{7}", ledger) >= 1,
         "两行里至少有一行还是已复现")
    c.ok("两处详情块都补了「补充（……已修复）」那一条",
         count(r"补充（2026-10-10，已修复）：\*\*提交", ledger) >= 2)

    return c.report("商品的回收站（BUG-0035）")


if __name__ == "__main__":
    sys.exit(main())
