"""地点库抽屉「一份实现两个入口」+ 三档分类面板的操作回执（CHG-0047 = 台账 L-09 + L-11）。

## 用户要的是什么（2026-10-06）
- L-09：「我那个在路线了、路线新增路线，他不是**可以从地点库选**吗？所以**地点库怎么还是只有
  自己的地点库**……我们现在已经改了方案了，已经是**左边侧边栏，然后来选地点**，但同时还有一个
  叫什么**共享地点**……**你可以去看一下像我们代理下单那个地点库是怎么改的**哦，**要是对应的
  包括终点也是一样的**」。台账的建议是：把下单页那份弹层参数化后**共用**，⛔ 不要再抄第二份。
- L-11：「在「管理分类」里新建一个分类，界面**不弹任何提示**（名字出现在列表里就算成功）；
  改名、删除同理」—— 三个 VM 早就写好了 actionResult，三个面板一次都没渲染过。

## 机制（改动后的形状）
| 事项 | 改法 | 不这么做会怎样 |
| --- | --- | --- |
| 起点 / 终点选点 | 复用 ui/shipper/OrderCreateScreen.kt 里的 fun AddressPickerSheet(（去掉 private）+ 新增必填 title: String，两个入口各自点名「选择收货地址」/「选择起点」/「选择终点」 | 抄第二份的话，共享地点的搜索 / 截断 / 管理这一整套要在两处各改一遍 |
| 「＋ 新增地点」 | 抽屉里新增一格，靠参数 onAddLocation: (() -> Unit)? = null 控制；null = **不画** —— 下单页没传，于是下单页那份**逐字未变** | 这一格画在共享地点段 = 给全库共用的一张表开了个行内新增口 |
| 宿主层级 | AddressScreen 的宿主写在页面顶层（4 空格缩进），画在表单抽屉**外面** | 落在表单那个 ModalBottomSheet 里就成了「弹层里再弹一层」，点空白处关哪个说不清 |
| 回执 | 每个面板 OneShotSnackbar(snackbar, vm.actionResult, ...) + SnackbarHost 沉底 | 建了 / 改了 / 删了分类界面上一点回声都没有，用户只能自己猜成没成 |

## ⛔ 这条判据证不了什么
- 它不验证抽屉**长相**（左栏三段、搜索框、行里那张图）—— 那是 _check_current_location_button.py
  与人工验收的事；
- 它不验证「新建完自动回填到刚才那个槽位」真的回填成功（要跑起来点一遍）；
- 它不验证后端 placesPage 的截断响应头（那是 _check_page_truncation_wiring.py 的下限）；
- 「一份实现」只证到**只有一处 fun 定义 + 两处调用**，证不到两处行为逐字一致。

R4-BOUNDARY-JUSTIFICATION: 边界挡不住这条 —— 「两个入口共用一份实现」与「回执画出来了没有」
都不是架构边界能表达的：把弹层复制第二份照样编译、照样跑，类型系统只会说两份都对；面板少了
SnackbarHost 也只是「没提示」，不报错、不红，Lint 与任何分层规则都反对不了它。能在编译前拦住
它们的只有一条静态判据 —— 本项目把边界解决不了的问题一律落到 _tools/qa 的 fail-closed 检查器里，
所以这条判据本身就是那道边界，不能靠架构消掉。
反向破坏用例见 _reverse_verify_place_picker_shared.py（改坏 + 还原后逐字节比对）。

## 判据
1. ui/shipper/OrderCreateScreen.kt 里那份弹层是**唯一实现**：不再是 private、标题走形参（抽屉体
   里不再写死「选择收货地址」）、onAddLocation 可空且 null 时不画；
2. 「＋ 新增地点」只在「我的地点」段、不在共享地点段，而且共享地点段里一个 onAddLocation 都没有；
3. 下单页**没传** onAddLocation（它的形状与改动前逐字一致）；线路表单传了，并且**先关弹层**
   再 openLocationCreate(start/end)；
4. 起点 / 终点两个入口共用**同一个**宿主（locPickerTarget 一个变量、这一页里只有一处
   AddressPickerSheet 调用），且宿主画在页面顶层（不在任何表单抽屉里）；
5. 旧的 startLocMenu / endLocMenu 两个下拉已退役；selectOriginLocation / selectDestLocation 的
   选中效果仍在（坐标 + 图片 + 收货人）；
6. AddressViewModel 有 places / placesTruncated / placesLimit / recentlyDeletedPlace /
   canManageSharedPlaces、loadPlaces(q)、reloadAddressLibrary()、四个管理动作 + shareLocation；
   applyPickedRoute 在「线路没写起点」时说清理由并**什么都不填**（绝不拿终点当地起点）；
   applyPickedPlace 记一次 usePlace 并在 autoAdded 时说一句；
7. 三档面板都接上了回执（OneShotSnackbar + SnackbarHost 沉底），且壳 / 体分开：公开的
   fun XCategoriesPanel(vm, onBack = null) 里只搭壳，原函数体搬进 private fun XCategoriesBody。

用法：python _tools/qa/_check_place_picker_shared.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
CREATE = AND / "ui/shipper/OrderCreateScreen.kt"
ADDR = AND / "ui/shipper/AddressScreen.kt"
VM = AND / "ui/shipper/AddressViewModel.kt"
COMPONENTS = AND / "ui/common/Components.kt"
DISP = AND / "ui/dispatcher"

#: (档位, 面板文件, 面板壳函数名, 面板体函数名)
PANELS = [
    ("联系人", DISP / "ContactCategoriesScreen.kt", "ContactCategoriesPanel", "ContactCategoriesBody"),
    ("线路", DISP / "RouteCategoriesScreen.kt", "RouteCategoriesPanel", "RouteCategoriesBody"),
    ("地点", DISP / "PlaceCategoriesScreen.kt", "PlaceCategoriesPanel", "PlaceCategoriesBody"),
]

ADD_CELL = 'Text("＋ 新增地点")'
L_BRANCH = 'sel == "l" || sel.startsWith("c|") -> {'
P_BRANCH = 'else -> if (places.isEmpty()) {'
OLD_TITLE = '"选择收货地址"'
SHEET_END = "private fun ConfirmActionDialog("


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


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数，好让行号还对得上）。

    这几个文件的注释里**故意**写着「原来只列自己的地点」「不要再抄一份」这些字眼 ——
    判据要抓的是**代码里**还有没有。
    """
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def region(text: str, start: str, stop: str) -> str:
    """截出 [start, stop) 那一段；找不到 start 就返回空串（由调用方的判据报红）。"""
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(stop, i + len(start))
    return text[i:j] if j >= 0 else text[i:]


def main() -> int:
    c = Checker()
    create = read(CREATE)
    addr = read(ADDR)
    vm = read(VM)
    create_code = code_only(create)
    addr_code = code_only(addr)

    sheet = region(create, "fun AddressPickerSheet(", SHEET_END)
    ocs_call = region(create, OLD_TITLE, "onDismiss = { vm.showAddressSheet = false },")
    addr_call = region(addr, "AddressPickerSheet(", "onDismiss = { locPickerTarget = null },")
    apply_route = region(vm, "fun applyPickedRoute(", "fun applyPickedPlace(")

    print("== 1. 那份弹层是唯一实现，标题改由调用方点名 ==")
    c.present("弹层仍叫 AddressPickerSheet(（判据与文档都点名它）", create,
              r"(?m)^fun AddressPickerSheet\(")
    c.absent("弹层不再是 private（另一页要跨文件用它）", create,
             r"(?m)^\s*(private|internal) fun AddressPickerSheet\(")
    c.present("多了一个必填的 title 形参", sheet, r"title: String,")
    c.absent("title 没有默认值（有默认值 = 调用方能忘了点名，界面就悄悄退回旧标题）",
             sheet, r"title: String = ")
    c.present("新增的「＋ 新增地点」靠可空形参控制", sheet,
              r"onAddLocation: \(\(\) -> Unit\)\? = null,")
    c.present("抽屉体的标题画的是形参，不再写死", sheet, r"Text\(\s*\n\s*title,")
    c.absent("抽屉体里不再出现写死的旧标题", sheet, re.escape(OLD_TITLE))
    c.ok("全文件只剩调用点那一处「选择收货地址」", create.count(OLD_TITLE) == 1,
         f"实际 {create.count(OLD_TITLE)} 处")

    print("== 2. 「＋ 新增地点」那一格画在哪一段 ==")
    c.ok("这一格只画一次", create.count(ADD_CELL) == 1, f"实际 {create.count(ADD_CELL)} 处")
    i_add = create.find(ADD_CELL)
    i_l = create.find(L_BRANCH)
    i_p = create.find(P_BRANCH)
    c.ok("它在「我的地点」那一段里", i_l >= 0 and i_add > i_l,
         f"我的地点段 @{i_l} / 这一格 @{i_add}")
    c.ok("共享地点段在它后面（= 没画在共享段里）", i_p >= 0 and i_add < i_p,
         f"这一格 @{i_add} / 共享段 @{i_p}")
    c.ok("共享地点段里一个 onAddLocation 都没有（那张表全库共用，不给人行内新增）",
         i_p >= 0 and create.find("onAddLocation", i_p) < 0,
         f"共享段之后还有 onAddLocation @{create.find('onAddLocation', max(i_p, 0))}")
    c.present("null 时整格不画（不是画个灰按钮）", create, r"if \(onAddLocation != null\) \{")
    c.present("这一格点了走形参", create, r"onClick = onAddLocation,")
    cell = region(create, "if (onAddLocation != null) {", "if (shownLocations.isEmpty()) {")
    c.present("它是一个文字按钮", cell, r"TextButton\(")
    c.present("它底下带一条分隔线（与列表第一行分开）", cell,
              r"HorizontalDivider\(color = MaterialTheme\.colorScheme\.outlineVariant\)")

    print("== 3. 两个调用点各自点名标题（下单页那份逐字未变）==")
    c.present("下单页点名了自己的标题", ocs_call, re.escape(OLD_TITLE))
    c.absent("下单页**没传** onAddLocation（它没有行内新增这条路）", ocs_call, r"onAddLocation")
    c.present("下单页仍然把撤销那条传进去", ocs_call, r"onRestorePlace = \{ vm\.restorePlace\(it\) \},")
    c.present("线路表单按起点 / 终点给不同标题", addr_call,
              r'title = if \(asOrigin\) "选择起点" else "选择终点",')
    c.present("线路表单传了 onAddLocation", addr_call, r"onAddLocation = \{")
    c.present("它先去新建地点（start / end 交给 VM 记着回填哪个槽位）", addr_call,
              r'vm\.openLocationCreate\(if \(asOrigin\) "start" else "end"\)')
    add_block = region(addr_call, "onAddLocation = {", "vm.openLocationCreate(")
    c.ok("点这一格时**先关掉**地点库弹层（不然两层弹层叠在一起）",
         "locPickerTarget = null" in add_block, "onAddLocation 支里没有 locPickerTarget = null")
    c.present("关弹层是这一支的**第一句**（先关弹层，再开新建）", addr_call,
              r"onAddLocation = \{\s*\n\s*locPickerTarget = null\s*\n\s*vm\.openLocationCreate\(")

    print("== 4. 起点 / 终点共用同一个宿主，且画在表单抽屉外 ==")
    c.present("这一页只有一个 locPickerTarget 状态（起点终点共用一份宿主）",
              addr, r"var locPickerTarget by remember \{ mutableStateOf<String\?>\(null\) \}")
    c.present("起点入口：先拉一次共享地点再开抽屉", addr,
              r'onClick = \{ vm\.loadPlaces\(\); locPickerTarget = "origin" \},')
    c.present("起点入口的文案", addr, r'label = "从地点库选起点",')
    c.present("终点入口：同一条路，只是目标不同", addr,
              r'locPickerTarget = "dest"')
    c.present("终点入口的文案", addr, r'label = "从地点库选终点",')
    c.absent("旧的「从地点库选」下拉菜单已退役（startLocMenu）", addr_code, r"startLocMenu")
    c.absent("旧的「从地点库选」下拉菜单已退役（endLocMenu）", addr_code, r"endLocMenu")
    c.ok("这一页只有一处 AddressPickerSheet 调用", addr.count("AddressPickerSheet(") == 1,
         f"实际 {addr.count('AddressPickerSheet(')} 处")
    hosts = re.findall(r"(?m)^    locPickerTarget\?\.let \{ target ->$", addr)
    c.ok("宿主画在页面顶层（恰好 4 空格缩进 = 不在任何表单抽屉里）", len(hosts) == 1,
         f"实际 {len(hosts)} 处顶层宿主")
    i_host = addr.find("    locPickerTarget?.let { target ->")
    i_form = addr.find("if (vm.showContactDialog) {")
    c.ok("宿主在表单抽屉**之后**（不是嵌在里面）", i_host > i_form > 0,
         f"宿主 @{i_host} / 表单抽屉 @{i_form}")
    c.present("截断那两条照旧传下去（共享库迟早一页装不下）", addr_call,
              r"placesTruncated = vm\.placesTruncated,")
    c.present("截断上限照旧传下去", addr_call, r"placesLimit = vm\.placesLimit,")
    c.present("管理权照旧传下去（只有派单员看得到管理入口）", addr_call,
              r"canManagePlaces = vm\.canManageSharedPlaces,")
    c.present("刚删掉那条照旧传下去（顶上那行「已删除 · 撤销」）", addr_call,
              r"recentlyDeleted = vm\.recentlyDeletedPlace,")
    c.present("搜索走 VM 的 loadPlaces(q)", addr_call, r"onSearchPlaces = \{ vm\.loadPlaces\(it\) \},")
    c.present("改过分组后回来刷名册", addr_call,
              r"onCategoriesChanged = \{ vm\.reloadAddressLibrary\(\) \},")

    print("== 5. 选中效果没退化（坐标 + 图片 + 收货人）==")
    c.present("「我的地点」那条仍走 selectOriginLocation / selectDestLocation", addr_call,
              r"if \(asOrigin\) vm\.selectOriginLocation\(l\) else vm\.selectDestLocation\(l\)")
    c.present("线路那条走新的 applyPickedRoute", addr_call,
              r"vm\.applyPickedRoute\(a, asOrigin = asOrigin\)")
    c.present("共享地点那条走新的 applyPickedPlace", addr_call,
              r"vm\.applyPickedPlace\(p, asOrigin = asOrigin\)")

    print("== 6. AddressViewModel 侧的数据源与管理动作 ==")
    c.present("共享地点名册在（截断标记与上限一起）", vm,
              r"var places by mutableStateOf<List<com\.tapmoay\.sorders\.data\.remote\.dto\.PlaceDto>>\(emptyList\(\)\)")
    c.present("截断标记", vm, r"var placesTruncated by mutableStateOf\(false\)")
    c.present("本次上限", vm, r"var placesLimit by mutableStateOf<Int\?>\(null\)")
    c.present("刚删掉那一条", vm, r"var recentlyDeletedPlace by mutableStateOf<Pair<Long, String>\?>\(null\)")
    c.present("管理权状态", vm, r"var canManageSharedPlaces by mutableStateOf\(false\)")
    c.present("loadPlaces(q) 存在（默认 null = 不带关键词）", vm,
              r"fun loadPlaces\(q: String\? = null\) \{")
    load = region(vm, "fun loadPlaces(q: String? = null) {", "// ===== 共享库的管理")
    c.present("它打的是 placesPage", load, r"container\.repo\.placesPage\(q\)")
    c.present("整页写进 places", load, r"places = page\.rows")
    c.present("截断标记来自响应头", load, r"placesTruncated = page\.meta\.hasMore")
    c.present("本次上限来自响应头", load, r"placesLimit = page\.meta\.limit")
    c.present("reloadAddressLibrary() 存在", vm, r"fun reloadAddressLibrary\(\) \{")
    reload = region(vm, "fun reloadAddressLibrary() {", "fun loadPlaces(")
    c.present("它重拉地点分组名册", reload, r"placeCategories = container\.repo\.placeCategories\(\)")
    c.present("它重拉线路名册", reload, r"addresses = container\.repo\.addresses\(\)")
    c.present("它重拉我的地点名册", reload, r"locations = container\.repo\.locations\(\)")
    c.present("改共享地点", vm, r"fun updatePlace\(id: Long, name: String\?, address: String\?\)")
    c.present("它走 PlaceUpdateRequest", vm,
              r"com\.tapmoay\.sorders\.data\.remote\.dto\.PlaceUpdateRequest\(name = name, detailAddress = address\)")
    c.present("删共享地点（软删）", vm, r"fun deletePlace\(id: Long\) \{")
    c.present("删掉后记着那条（界面给一次撤销）", vm,
              r"recentlyDeletedPlace = id to \(places\.firstOrNull \{ it\.id == id \}\?\.name\.orEmpty\(\)\)")
    c.present("恢复", vm, r"fun restorePlace\(id: Long\) \{")
    c.present("撤销为我的地点", vm, r"fun demotePlace\(id: Long\) \{")
    c.present("设为共享地址", vm, r"fun shareLocation\(l: LocationDto\) \{")
    c.present("用过的共享地点要记一次账", vm, r"container\.repo\.usePlace\(p\.id\)")
    c.present("后端顺手收进「我的地点」时要说一句", vm, r"if \(r\.autoAdded\) \{")
    c.present("线路的起点读的是 originAddress", apply_route,
              r"val addr = a\.originAddress\.orEmpty\(\)\.trim\(\)")
    c.present("线路没写起点时说清理由", apply_route,
              r'formError = "这条线路没写起点（只送到终点），改选一个地点，或先编辑这条线路补上起点"')
    c.absent("绝不拿这条线路的终点当地起点", apply_route, r"draftOrigin = a\.detailAddress")
    c.present("管理权来自会话角色", vm,
              r'val isDispatcher = container\.tokenStore\.sessionFlow\.first\(\)\?\.role == "dispatcher"')
    c.present("canManageSharedPlaces 用的就是它", vm, r"canManageSharedPlaces = isDispatcher")

    print("== 7. 三档面板的操作回执（L-11）==")
    for tier, path, panel_fun, body_fun in PANELS:
        panel = read(path)
        shell = region(panel, f"fun {panel_fun}(", f"private fun {body_fun}(")
        c.present(f"{tier}：面板壳仍叫 {panel_fun}(", panel, rf"(?m)^fun {panel_fun}\(")
        c.present(f"{tier}：宿主不点名时仍可不传 onBack", panel,
                  r"onBack: \(\(\) -> Unit\)\? = null,")
        c.present(f"{tier}：提示条状态住在壳里", panel,
                  r"val snackbar = remember \{ SnackbarHostState\(\) \}")
        c.present(f"{tier}：把 VM 的回执接上（从前 vm.actionResult 零命中）", panel,
                  r"OneShotSnackbar\(snackbar, vm\.actionResult, onConsumed = \{ vm\.actionResult = null \}\)")
        c.present(f"{tier}：提示条沉在底部", panel,
                  r"SnackbarHost\(snackbar, Modifier\.align\(Alignment\.BottomCenter\)\)")
        c.present(f"{tier}：原函数体搬进 private fun {body_fun}(", panel,
                  rf"(?m)^private fun {body_fun}\(")
        c.present(f"{tier}：壳里那行调用点还在", panel, rf"{body_fun}\(vm, onBack\)")
        c.present(f"{tier}：体仍然带着自己的 OptIn（Material3 的 API 在体里用）", panel,
                  rf"@OptIn\(ExperimentalMaterial3Api::class\)\s*\n@Composable\s*\nprivate fun {body_fun}\(")
        c.ok(f"{tier}：壳里**没有**原来的布局（体确实搬走了，不是抄了一份）",
             "SectionCard(" not in shell and "CATEGORY_ROW_HEIGHT" not in shell,
             "壳里还留着 SectionCard( 或 CATEGORY_ROW_HEIGHT")

    print("== 8. 回执组件本身只有一份 ==")
    components = read(COMPONENTS)
    c.present("OneShotSnackbar 定义在公共组件里", components, r"(?m)^fun OneShotSnackbar\(")
    c.ok("全库只有这一处定义（各页不许自己再造一份）",
         components.count("fun OneShotSnackbar(") == 1,
         f"实际 {components.count('fun OneShotSnackbar(')} 处")

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
