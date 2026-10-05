"""三档分类管理面板（联系人 / 线路 / 地点）的行布局、拖动排序与返回分层（CHG-0046 = 台账 L-06 + L-07 + L-08）。

## 用户报的三件事（2026-10-06，台账 L-06 / L-07 / L-08）
- L-06：「我在联系人新建那个（分类）……**新建分类的卡片的名称并没有正常显示**」；三档都有。
- L-07：「它的排序**最好不要用那个按钮排序**，我们直接像**拖动卡片式**的排序」。
- L-08：「点那个（顶上的）返回啊，他是**直接退出了**啊不要啊，**我们是任何返回都是返回上 1 级**」；
  面板里那三颗「返回联系人 / 返回线路 / 返回地址」与顶栏那颗**互相容易误解**。

## 机制
- **名字被挤扁**：一行里的固定件是「位次框 58dp + 间距 10dp + **四颗 48dp 的 IconButton**」= 260dp；
  360dp 屏上 SectionCard 内可用 288dp ⇒ 名字列只剩 **28dp ≈ 2 个中文字**（而名字上限是 8 字，
  见 ui/shipper/AddressScreen.kt 的新建弹窗 take(8)）。三处名字 Text 还只有 maxLines = 1、
  **没有 overflow = Ellipsis**（地点那份连 fillMaxWidth() 都没有）⇒ 不是"省略"，是硬切半个字。
- **排序**：旧形态是"填第几位 + ↑↓ 按钮"。用户点名要长按拖动（样板 = 商品分类管理页，
  2026-09-19 已认可：⠿ 拖动柄 + ⋮ 菜单 + 固定行高换算）。
- **返回**：顶栏那颗无条件 onClick = onBack（没判面板开着），而面板里又画了一颗语义重复的返回。

## 为什么这条必须有机器的判据
这三样**一条都不报错**：名字被挤扁只是难看；四颗图标退回一排只是"又挤了"；
顶栏返回恢复成 onClick = onBack 甚至**看上去更简单**；拖动那套一旦少了 key(c.id)，
表现是"拖了半天只挪一格就自己松手" —— 不崩、不红，也没有类型能拦住。
缺的那一层是**布局与手势的空间/时间语义**：宽度的算术、位移到格数的换算、
以及"这一层现在是谁在接管返回"，语言、类型系统与 Lint 都说不出来。
反向破坏用例见 _reverse_verify_category_row_layout.py（17 条改坏 + 还原后逐字节比对）。

R4-BOUNDARY-JUSTIFICATION: 边界挡不住这条 —— 上面那层「布局与手势的空间/时间语义」没有任何单点
架构边界能表达它：行高 84dp 与「名字还剩多少宽度」是**渲染期算出来的**事实，类型系统只看得见 dp 值的
声明；detectDragGesturesAfterLongPress 少了 change.consume() 只是"偶尔被父滚动吃掉"，不报错；
onBack 改成可空、宿主不点名，更没有哪条分层边界反对（它看上去还更简单）。能在编译前拦住它们的
只有**一条静态判据** —— 本项目把边界解决不了的问题一律落到 _tools/qa 的 fail-closed 检查器里，
所以这条判据本身就是那道边界，不能靠架构消掉。

## 判据（每条都能被反向验证弄红）
1. 三档面板都还在、那两个符号名没改（面板 fun 仍 public、行零件名如旧）；
2. 行里**不再有** ↑↓ 两颗 IconButton，整行只剩**一颗** IconButton（⋮）；
3. 名字 Text 三件套：maxLines = 1 + overflow = TextOverflow.Ellipsis + modifier = Modifier.fillMaxWidth()
   （最后一条是 _check_adaptive_layout.py 存量基线的要求：不给宽度的省略号文本会去吃兄弟的宽度）；
4. 拖动柄 ⠿ + ⋮ 菜单两项（改名 / 删除），删除色走命名 token Color(MessageRed)；
5. 位次框用 SoTextField，这三个文件里不许再出现 OutlinedTextField（全库描边输入框只减不增）；
6. 拖动三件套：detectDragGesturesAfterLongPress + change.consume() + dragSteps(...) + vm.moveBy(...)；
7. 列表是 Column + verticalScroll（**不是** LazyColumn：拖动要靠固定行高把位移换算成格数）、
   key(c.id) 在、行高常量 CATEGORY_ROW_HEIGHT 既量了行也换算了像素；
8. Hint 里写着「长按一行可以拖动排序」；
9. onBack 是可空的、且只有宿主点名了才画那颗返回（地址页不点名 ⇒ 顶栏那一颗是唯一入口）；
10. 三个 VM：有 moveBy、有提交编号 submitSeq（旧响应不覆盖新顺序）、提交前先本地换位（rows = next）、
    旧的 fun move(index, delta) 已消失；submittableIds( 与 repo.reorderXCategories( 仍在；
11. 返回分层（AddressScreen）：BackHandler(enabled = managingCategory && !drawer.isOpen)、
    backOneLevel 三层（抽屉 → 面板 → 退页）、顶栏走 backOneLevel、
    地址页的面板调用点**不点** onBack；下单页的地点抽屉**仍要点名** onBack（那里没有顶栏，不点名就卡住）。

用法：python _tools/qa/_check_category_row_layout.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
DISP = AND / "ui/dispatcher"
ADDR = AND / "ui/shipper/AddressScreen.kt"
CREATE = AND / "ui/shipper/OrderCreateScreen.kt"

#: (档位, 面板文件, 面板函数名, 行零件名, 条数文案, VM 文件, 后端重排函数名)
PANELS = [
    (
        "联系人",
        DISP / "ContactCategoriesScreen.kt",
        "ContactCategoriesPanel",
        "ContactCategoryRow",
        "位联系人",
        DISP / "ContactCategoriesViewModel.kt",
        "reorderContactCategories",
    ),
    (
        "线路",
        DISP / "RouteCategoriesScreen.kt",
        "RouteCategoriesPanel",
        "RouteCategoryRow",
        "条线路",
        DISP / "RouteCategoriesViewModel.kt",
        "reorderRouteCategories",
    ),
    (
        "地点",
        DISP / "PlaceCategoriesScreen.kt",
        "PlaceCategoriesPanel",
        "CategoryRow",
        "个地点",
        DISP / "PlaceCategoriesViewModel.kt",
        "reorderPlaceCategories",
    ),
]


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

    为什么要这样：这三个文件的注释里**故意**点着「不是 LazyColumn」「而不是 OutlinedTextField」
    「上下箭头退役」这些字眼 —— 它们写的正是"为什么这么改"。判据要抓的是**代码里**还有没有。
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
    addr = read(ADDR)
    create = read(CREATE)

    for tier, panel_path, panel_fun, row_fun, count_label, vm_path, reorder in PANELS:
        panel = read(panel_path)
        vm = read(vm_path)
        code = code_only(panel)
        row = region(panel, f"private fun {row_fun}(", "\n@Composable")

        print(f"== 1. {tier}：行零件还在、名字不再被四颗图标挤扁 ==")
        c.present(f"{tier}：面板 fun {panel_fun}( 仍是 public（判据与文档都点名它）",
                  panel, rf"(?m)^fun {panel_fun}\(")
        c.absent(f"{tier}：面板 fun 没被收成 private", panel, rf"private fun {panel_fun}\(")
        c.present(f"{tier}：行零件 {row_fun}( 在", panel, rf"private fun {row_fun}\(")
        c.present(f"{tier}：行高常量还是量过的那个数（84dp = SoTextField 52 + SectionCard 16×2）",
                  panel, r"private val CATEGORY_ROW_HEIGHT = 84\.dp")
        name_block = region(row, "c.name,", "Text(")
        c.present(f"{tier}：名字只画一行", name_block, r"maxLines = 1,")
        c.present(f"{tier}：名字**带省略号**（从前只有 maxLines=1 → 硬切半个字）",
                  name_block, r"overflow = TextOverflow\.Ellipsis,")
        c.present(f"{tier}：名字显式占满这一列（不给宽度的省略号文本会去吃兄弟的宽度）",
                  name_block, r"modifier = Modifier\.fillMaxWidth\(\),")
        c.absent(f"{tier}：行里不再有 ↑↓ 按钮（用户点名的『不要用那个按钮排序』）",
                 code, r"Icons\.Default\.KeyboardArrow(Up|Down)")
        c.ok(f"{tier}：整行只剩一颗 IconButton（⋮），不再是四颗排排坐",
             code.count("IconButton(") == 1, f"实际 {code.count('IconButton(')} 颗")
        c.present(f"{tier}：留着 ⠿ 拖动柄并写明用途",
                  panel, r"Icons\.Default\.DragHandle,\s*\n\s*contentDescription = \"长按拖动排序\"")
        c.present(f"{tier}：⋮ 菜单里有『改名』", panel, r"Text\(\"改名\"\)")
        c.present(f"{tier}：⋮ 菜单里有『删除』且走命名 token MessageRed",
                  panel, r"Text\(\"删除\", color = Color\(MessageRed\)\)")

        print(f"== 2. {tier}：位次框与旧形态的收尾 ==")
        c.present(f"{tier}：位次框走 SoTextField", row, r"SoTextField\(")
        c.absent(f"{tier}：这三个文件里不再有 OutlinedTextField（全库描边输入框只减不增）",
                 code, r"OutlinedTextField")

        print(f"== 3. {tier}：长按拖动排序 ==")
        c.present(f"{tier}：手势是『长按后拖动』", panel, r"detectDragGesturesAfterLongPress\(")
        c.present(f"{tier}：拖动时 consume（不 consume 会连父级滚动一起拖）",
                  panel, r"change\.consume\(\)")
        c.present(f"{tier}：位移靠 dragSteps 换算成格数（与商品分类页共用同一个函数）",
                  panel, r"dragSteps\(dragOffset, rowHeightPx\)")
        c.present(f"{tier}：拖动结果交给 vm.moveBy", panel, r"vm\.moveBy\(c\.id, steps\)")
        c.present(f"{tier}：行高常量既量了行也换算了像素",
                  panel, r"CATEGORY_ROW_HEIGHT\.toPx\(\)")
        c.present(f"{tier}：列表是 Column + verticalScroll（拖动要靠固定行高换算）",
                  panel, r"\.verticalScroll\(rememberScrollState\(\)\)")
        c.absent(f"{tier}：列表**不是** LazyColumn（item 复用会让『位移→格数』变成靠测量）",
                 code, r"LazyColumn")
        c.present(f"{tier}：每行有稳定 key(c.id)（少了它拖动会被手势取消）",
                  panel, r"key\(c\.id\) \{")
        c.present(f"{tier}：Hint 里写着怎么排序",
                  panel, r"长按一行可以拖动排序")
        c.present(f"{tier}：条数文案还在（{count_label}）", panel, re.escape(count_label))

        print(f"== 4. {tier}：面板自己不画返回（由宿主点名） ==")
        c.present(f"{tier}：onBack 是可空的", panel, r"onBack: \(\(\) -> Unit\)\? = null,")
        c.present(f"{tier}：只有宿主点名了才画那颗返回",
                  panel, r"if \(onBack != null\) \{")

        print(f"== 5. {tier}：VM 的提交口径 ==")
        c.present(f"{tier}：VM 有 moveBy(id, steps)",
                  vm, r"fun moveBy\(id: Long, steps: Int\)")
        c.present(f"{tier}：VM 有提交编号 submitSeq", vm, r"private var submitSeq = 0")
        c.present(f"{tier}：提交编号逐次递增", vm, r"val seq = \+\+submitSeq")
        c.present(f"{tier}：拖动先本地换位（不然手指走了卡片还在原地）",
                  vm, r"rows = next")
        c.present(f"{tier}：旧响应不许覆盖新顺序（成功那支）",
                  vm, r"if \(seq == submitSeq\) rows = fresh")
        c.present(f"{tier}：旧响应不许覆盖新顺序（失败那支）",
                  vm, r"if \(seq == submitSeq\) load\(\)")
        c.absent(f"{tier}：旧的『按格挪』接口已退役（只被 ↑↓ 用过）",
                 code_only(vm), r"fun move\(index: Int,")
        c.present(f"{tier}：提交口径仍是共用件 submittableIds(", vm, r"submittableIds\(")
        c.present(f"{tier}：仍然走 repo.{reorder}(", vm, rf"repo\.{reorder}\(")
        i_next = vm.find("rows = next")
        i_submit = vm.find("submit(next)")
        c.ok(f"{tier}：本地换位发生在提交**之前**",
             i_next >= 0 and i_submit >= 0 and i_next < i_submit,
             f"rows = next @{i_next} / submit(next) @{i_submit}")

    print("== 6. 返回分层（ui/shipper/AddressScreen.kt，L-08）==")
    c.present("系统返回键只在『面板开着且抽屉关着』时接管（抽屉那一种归 ModalNavigationDrawer）",
              addr, r"BackHandler\(enabled = managingCategory && !drawer\.isOpen\)")
    bl = region(addr, "val backOneLevel: () -> Unit = {", "// 系统返回键")
    c.present("backOneLevel：抽屉开着 → 先关抽屉", bl, r"if \(drawer\.isOpen\) \{")
    c.present("backOneLevel：关抽屉走 scope.launch { drawer.close() }",
              bl, r"scope\.launch \{ drawer\.close\(\) \}")
    c.present("backOneLevel：面板开着 → 退回上一层", bl, r"\} else if \(managingCategory\) \{")
    c.present("backOneLevel：退面板走 leaveCategoryPanel()", bl, r"leaveCategoryPanel\(\)")
    c.present("backOneLevel：都不是才退这一页", bl, r"\} else \{\s*\n\s*onBack\(\)")
    c.present("顶栏那颗返回走 backOneLevel（不再直连退页）",
              addr, r"IconButton\(onClick = \{ backOneLevel\(\) \}\)")
    c.absent("AddressScreen 里没有一处顶栏返回直连 onClick = onBack",
             code_only(addr), r"IconButton\(onClick = onBack\)")
    c.ok("地址页的面板调用点不点 onBack（顶栏那一颗是唯一入口）",
         "ContactCategoriesPanel(vm = catVm)" in addr
         and "PlaceCategoriesPanel(vm = catVm)" in addr
         and "RouteCategoriesPanel(vm = catVm)" in addr,
         "三个调用点没同时出现『只传 vm』的形状")
    c.ok("地址页仍按页签回读名册（改名/删除后抽屉里那一格要跟着变）",
         addr.count("LaunchedEffect(Unit) { catVm.load() }") >= 3,
         f"实际 {addr.count('LaunchedEffect(Unit) { catVm.load() }')} 处")
    c.present("下单页的地点抽屉**仍然点名** onBack（那里没有顶栏，不点名就卡在面板里）",
              create, r"PlaceCategoriesPanel\(\s*\n\s*vm = catVm,\s*\n\s*onBack = \{")

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
