# -*- coding: utf-8 -*-
"""红线：**地址与联系人页三张卡上的动作** —— 圈底图标 + 左＝删除、右＝编辑（CHG-0012，2026-10-03）。

## 用户原话（2026-09-22，对着订单卡片说的）
> 「假如像我们**派单员编辑**的话，一定是在**右边**的，而且他就是一个…**笔**啊，**这个不行**啊，
>  他**要一个图标**啊，**稍微圈一下**；然后呢**异常**的话，就放置在**左边**而且**是最左边**。」
> 「包括以后的那个，只要涉及到**编辑**和其他的比如说**删除**等等，**编辑一定在右边**
>  （因为我们的**惯用手是右手**，我们好编辑），但是比如说**相反的操作，就在左边**」

规范落在 docs/PROJECT_MAP/06_DESIGN_SYSTEM.md 的 4.2c（位置 + 形态两条）。

## 这条为什么必须有机器的判据
「卡片上的图标动作」在本仓库是一条**两句话的视觉纪律**（右＝编辑 / 左＝反向·警示；且必须**圈底**），
它**没有任何东西在兜底**：Compose 里两个动作都是 @Composable () -> Unit，谁在左谁在右照样编译、照样渲染；
自己再写一个裸 IconButton 也照样编译、照样能点。破法全部是**静默**的：

* 换个页面又写裸 IconButton → 在信息很满的卡片上那个 18dp 图标几乎看不见、手指也不好找
  （用户那句「这个不行」指的就是它），但**没有任何报错**；
* 两个动作**对调** → 最危险的那个（删除）正好落在右手最容易点到的地方，**界面完全正常**；
* 2026-10-04 用户又改了一次（CHG-0032）：「把地点线路联系人，他那里的**删除键卡片删除键移到
  编辑界面当中**，并且**做二次确认**的，不要点一下就直接删掉了，防止误触」—— 于是**卡上只剩编辑那一颗**。
  这一步同样是**静默**的：把红色垃圾桶画回卡片上、或者让抽屉里那颗删除直接落库（跳过二次确认），
  编译、渲染、点上去全都正常，只有用户会又一次「点一下就没了」。

所以判据分六层：
1. **卡片清点自己算**：扫 AddressScreen.kt 里所有 private fun *Card( 的函数体，逐张断言
   「IconButton( == 0」—— 清单不许手写行号，**多扫出一张卡就红**（新卡片的动作纪律要先登记进 CARDS）；
2. **卡上只剩编辑**（2026-10-04 起）：每张卡恰好一颗 CardActionIcon = 编辑、主色；全页
   contentDescription = "删除" / onDelete / Icons.Default.Delete 一律 0（搬走了就是搬走了）；
3. **删除入口在抽屉里、只在编辑态、只举手不落库**：三个抽屉各一行 FormRow → vm.askDelete("…")，
   包在对应的 if (vm.editingXxx != null) 里；页面**一次都不许**直接调 vm.delete*；页尾那份
   vm.pendingDelete?.let + DangerConfirmDialog 是**唯一**的确认入口（确认才走 vm.confirmDelete()）；
4. **形态**：共用件 CardActionIcon 本身（全库只有一处定义、内部就是 TintedIcon 圆底、默认 36/18）；
5. **本批没顺手改别的**：三张卡的回调签名（现在只剩 onEdit）、取数 / 抽屉 / 左栏锚点、来历注释、规范 4.2c；
6. **接线**：反向验证在、CONVERTED 表里还在、文档九节、登记簿有 CHG-0012。

R4-BOUNDARY-JUSTIFICATION: 这一条**没法用边界消除** —— 这套纪律只存在于**调用点**（哪一张卡的哪几个动作、
删除那颗是画在卡上还是抽屉里、点下去有没有中间那一层），而类型系统看见的全是一模一样的
@Composable () -> Unit：把共用件换回裸 IconButton、把垃圾桶画回卡片、把 vm.askDelete 换成 vm.delete，
都能通过编译、通过渲染，也通过任何结构判据。共用件 CardActionIcon / DangerConfirmDialog 已经把**形态**
收成了一处实现，但没有任何机制能强制某一页**用它**、更没法强制"点删除必须先举手"。破法又是**静默**的：
页面照常工作，只是用户又一次在没有任何提示的情况下丢了一条常用线路。所以只能靠一条判据把两侧
（三张卡 ＋ 三个抽屉 ↔ 共用件的形状）对起来，并在反向验证里把"垃圾桶画回卡上""抽屉里直接删"
"页尾那份确认弹层删掉"这几条真跑一遍。

用法：python _tools/qa/_check_address_cards.py
     python _tools/qa/_check_address_cards.py --list
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
ADDR_SCREEN = AND / "ui/shipper/AddressScreen.kt"
ADDR_VM = AND / "ui/shipper/AddressViewModel.kt"
ADDR_CONFIRM_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/shipper/AddressDeleteConfirmTest.kt"
COMPONENTS = AND / "ui/common/Components.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
FORM_STYLE_CHECK = ROOT / "_tools/qa/_check_form_panel_style.py"
REVERSE = "_tools/qa/_reverse_verify_address_cards.py"
DOC = ROOT / "docs/changes/CHG-0012.md"
REGISTRY = ROOT / "docs/changes/README.md"

#: 这一批点名要改的三张卡（位置纪律只对横排的那两张有「左／右」；线路卡是竖排）
CARDS = ("AddressCard", "ContactCard", "LocationCard")
#: 函数体字符数下限：**抽取失效比判据腐烂更危险**（截空之后「有没有 IconButton」在空串上恒真）
BODY_FLOOR = 120
#: 竖排那块 Column 的字符数下限（同上：截空即红）
COLUMN_FLOOR = 60
#: 全库 Kotlin 文件数下限（防目录改名后「一个文件都没扫到」也算过）
MIN_KT_FILES = 200
#: 卡片动作的两条语义色（危险 ＝ error，编辑 ＝ primary）
DELETE_TINT = "tint = MaterialTheme.colorScheme.error,"
EDIT_TINT = "tint = MaterialTheme.colorScheme.primary,"
#: 卡片函数签名（这一页的卡片都是顶格声明）
CARD_SIG = re.compile(r"^private fun (\w*Card)\(.*\) \{", re.M)
ICON_BTN = re.compile(r"IconButton\(")
CARD_ACTION = re.compile(r"CardActionIcon\(")
PRIV_ACTION = re.compile(r"private fun \w*Action\(")
CALLBACK_PAIR = re.compile(r"onEdit: \(\) -> Unit, onDelete: \(\) -> Unit")  #: 2026-10-04 起应为 0 处
#: 只剩一个回调的三张卡（CHG-0032 之后这就是唯一合法的签名形状）
CARD_SIG_SOLO = re.compile(r"^private fun (?:AddressCard|ContactCard|LocationCard)\(.*onEdit: \(\) -> Unit\) \{", re.M)
#: 抽屉里那一行删除入口：FormRow(label = "删除…", onClick = { vm.askDelete("line") })
DELETE_ROW = re.compile(r'FormRow\(label = "删除[^"]*", onClick = \{ vm\.askDelete\("(\w+)"\) \}\)')
#: 一行删除入口与它上面那道「只在编辑态」的门（kind → 门那一行的源码）
ASK_GUARDS = {
    "line": "if (vm.editing != null) {",
    "place": "if (vm.editingLocation != null) {",
    "contact": "if (vm.editingContact != null) {",
}
DEL_CD = 'contentDescription = "删除"'
EDIT_CD = 'contentDescription = "编辑"'
VERTICAL_COLUMN = "Column(horizontalAlignment = Alignment.CenterHorizontally) {"
#: §4.2c 那一节的标题（位置纪律的规范原文落在这里：删掉一节 ＝ 删掉规范）
DESIGN_42C = "### 4.2c"
#: 那一节的字符数下限（截空即红：规范被删掉 / 搬到别处）
SECTION_FLOOR = 300


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def fn_body(src: str, sig: str) -> str:
    """sig 那个函数的**函数体**（大括号配对，不按行猜）。"""
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


def decl_body(src: str, sig: str) -> str:
    """sig 那个函数的**声明 + 函数体**。

    ⚠️ 必须连声明一起要：默认值（如 `container: Dp = 36.dp`）写在**参数表**里，
    只取大括号函数体就看不到它们 —— 那样"默认尺寸没被改"会变成一条永远绿的检查。
    """
    i = src.find(sig)
    if i < 0:
        return ""
    b = fn_body(src, sig)
    if not b:
        return ""
    j = src.find(b, i)
    return src[i : j + len(b)]


def section(text: str, heading: str) -> str:
    """文档里某一节（从 heading 那一行到下一个同级 ### 之前）。"""
    i = text.find(heading)
    if i < 0:
        return ""
    j = text.find("\n### ", i + len(heading))
    return text[i:] if j < 0 else text[i:j]


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
    if refuse_if_injecting("地址与联系人页卡片动作检查"):
        return 1

    c = Checker()
    print("地址与联系人页：三张卡的圈底动作 + 左删右编（CHG-0012，2026-10-03）")

    kt_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的 Kotlin 文件数 ≥ {MIN_KT_FILES}（防目录搬走 → 判据空转）",
        len(kt_files) >= MIN_KT_FILES,
        f"实际 {len(kt_files)}",
    )
    c.ok("AddressScreen.kt 存在", ADDR_SCREEN.exists(), str(ADDR_SCREEN))

    raw = read(ADDR_SCREEN)
    src = code(ADDR_SCREEN)

    # ---- 1. 卡片清单自己算 ----
    sigs = [m.group(0) for m in CARD_SIG.finditer(src)]
    names = [m.group(1) for m in CARD_SIG.finditer(src)]
    c.ok(
        "这一页的卡片函数就是这三张（清点自己算：多一张就得先把它登记进 CARDS，再谈动作纪律）",
        sorted(set(names)) == sorted(CARDS),
        f"清点出来的是 {sorted(set(names))}，CARDS 里是 {sorted(CARDS)}",
    )
    bodies = {n: fn_body(src, s) for n, s in zip(names, sigs)}
    for n in CARDS:
        got = len(bodies.get(n, ""))
        c.ok(f"{n} 抽出的函数体 ≥ {BODY_FLOOR} 字符（抽取失效即红）", got >= BODY_FLOOR, f"只有 {got} 字符")

    # ---- 2. 卡上只剩编辑（2026-10-04：删除搬进了编辑抽屉）----
    for name in [n for n in names if n in CARDS]:
        body = bodies[name]
        n_icon = len(ICON_BTN.findall(body))
        n_del = body.count(DEL_CD)
        n_edit = body.count(EDIT_CD)
        n_act = len(CARD_ACTION.findall(body))
        c.ok(
            f"{name} 里没有裸 IconButton（用户：这个不行，他要一个图标，稍微圈一下）",
            n_icon == 0,
            f"还有 {n_icon} 处裸图标按钮",
        )
        c.ok(
            f"{name} 卡上已经没有删除那一颗了（用户 2026-10-04：删除键卡片删除键移到编辑界面当中）",
            n_del == 0,
            f"卡上又画回 {n_del} 处删除图标 —— 那正是他要搬走的东西",
        )
        c.ok(f"{name} 卡上只剩编辑那一颗（不多不少）", n_edit == 1, f"编辑 {n_edit} 处")
        c.ok(f"{name} 的编辑走共用件 CardActionIcon", n_act == 1, f"有 {n_act} 个圈底动作")
        c.ok(f"{name} 的编辑仍是主题主色", EDIT_TINT in body, "编辑不是 primary")
    c.ok("全页没有 onDelete 形参了（三张卡都不再接删除回调）", "onDelete" not in src, f"还有 {src.count('onDelete')} 处")
    c.ok("全页没有 Icons.Default.Delete（垃圾桶整个搬走了）", "Icons.Default.Delete" not in src, "垃圾桶还在卡上")
    c.ok("全页没有 contentDescription = 删除（删除不再是一颗卡上图标）", DEL_CD not in src, f"还有 {src.count(DEL_CD)} 处")

    # ---- 3. 三张卡：那颗编辑仍在，且都不再竖排（只剩一颗动作时没有上下之分）----
    for name in CARDS:
        body = bodies.get(name, "")
        c.ok(f"{name} 的那颗编辑还在（这一批只搬删除，不动编辑）", body.find(EDIT_CD) >= 0, "编辑那颗不见了")
        c.ok(
            f"{name} 右半边不再竖排（用户 2026-09-22 那条「一上一下」说的是删除 + 编辑两颗，现在只剩一颗）",
            VERTICAL_COLUMN not in body,
            "这张卡又被改成竖排了",
        )
    n_solo = len(CARD_SIG_SOLO.findall(src))
    c.ok(f"三张卡的签名都只剩 onEdit（清点自己算，实测 {n_solo} 处）", n_solo == 3, f"实际 {n_solo} 处")
    c.ok(
        "线路卡的 KDoc 里记着这次改动的来历（CHG-0032：删除从卡上搬走）",
        "CHG-0032" in raw and "搬" in raw,
        "来历被删了 —— 下一个人会把红色垃圾桶画回卡上",
    )

    # ---- 3b. 删除入口：在抽屉里、只在编辑态、只举手不落库 ----
    kinds = DELETE_ROW.findall(src)
    c.ok(
        "三个抽屉各有且只有一行删除入口（FormRow → vm.askDelete）",
        sorted(kinds) == ["contact", "line", "place"],
        f"抽到的是 {sorted(kinds)}",
    )
    for kind, guard in ASK_GUARDS.items():
        i = src.find('vm.askDelete("' + kind + '")')
        j = src.rfind(guard, 0, i) if i >= 0 else -1
        c.ok(
            f"「{kind}」那一行删除只在编辑态画（新增时没有这一条可删）",
            i >= 0 and 0 <= j and (i - j) < 400,
            f"入口在 {i}、那道门在 {j} —— 门没了就是新增时也能点删除",
        )
    spans = (
        ('vm.askDelete("line")', "vm.save()", "vm.saveLocation()"),
        ('vm.askDelete("place")', "vm.saveLocation()", "vm.saveContact()"),
        ('vm.askDelete("contact")', "vm.saveContact()", "vm.pendingDelete?.let"),
    )
    for needle, save_btn, next_marker in spans:
        i, s, n = src.find(needle), src.find(save_btn), src.find(next_marker)
        c.ok(
            f"「{needle}」落在自己那张抽屉里（取消/保存那一行之后、下一张抽屉之前）",
            0 <= s < i < n,
            f"位置 {i}：保存行 {s}、下一块 {n}",
        )
    bad = [x for x in ("vm.delete(", "vm.deleteContact(", "vm.deleteLocation(") if x in src]
    c.ok("页面一次都不许直接调 vm.delete*（要删必须过 askDelete → 确认）", not bad, "直接落库的调用还在：" + "、".join(bad))
    c.ok("页尾那份二次确认画在页面最外层（在最后一张抽屉之后）", src.find("vm.pendingDelete?.let") > src.find("vm.saveContact()"), "它跑到抽屉里去了")
    for needle, why in (
        ("DangerConfirmDialog(", "二次确认用的是共用件（别自己拼一个 AlertDialog）"),
        (chr(34) + "删除" + chr(34) + ",", "确认钮上的字是「删除」"),
        ("onConfirm = { vm.confirmDelete() },", "确认才走 confirmDelete（落库的唯一入口）"),
        ("onDismiss = { vm.cancelDelete() },", "点空白/取消要有地方可退（cancelDelete）"),
    ):
        c.ok(f"页尾确认弹层里：{why}", needle in src, f"找不到 {needle}")
    comp_src = code(COMPONENTS)
    c.ok(
        "共用件 DangerConfirmDialog 每次都弹（没有 ConfirmMemory 那种记一次就不问的开关）",
        "ConfirmMemory" not in decl_body(comp_src, "fun DangerConfirmDialog("),
        "二次确认被做成只问一次了 —— 用户要的是防误触，不是防第一次",
    )

    # ---- 4. 形态：共用件本身（一处实现 + 圈底 + 默认尺寸）----
    defs = [p for p in kt_files if "fun CardActionIcon(" in read(p)]
    c.ok(
        "圈底动作全库只有一处实现（不许各页自己再写一份）",
        [p.name for p in defs] == ["Components.kt"],
        "又出现第二份 CardActionIcon 定义：" + "、".join(p.name for p in defs),
    )
    comp = decl_body(code(COMPONENTS), "fun CardActionIcon(")
    c.ok("圈底件内部就是 TintedIcon 的圆底（一半描边一半实心会像两个人拼的）", "TintedIcon(" in comp, "CardActionIcon 里没有 TintedIcon")
    c.ok(
        "圈底件的默认尺寸没被改（36dp 圆底 + 18dp 图标）",
        "container: Dp = 36.dp" in comp and "size: Dp = 18.dp" in comp,
        "默认尺寸被改了",
    )
    c.ok("圈底件仍是可点的按钮语义（Role.Button）", "Role.Button" in comp, "没有 clickable(role = Role.Button)")
    c.ok("圈底件的 KDoc 里留着用户那句「稍微圈一下」", "稍微圈一下" in read(COMPONENTS), "来历被删了")
    n_priv = len(PRIV_ACTION.findall(src))
    c.ok("这一页没有自己再写一个私有动作控件（private fun *Action）", n_priv == 0, f"这一页又自己写了一份动作控件（{n_priv} 个）")

    # ---- 5. 本批没顺手改别的：回调签名 + 本页锚点 + 规范 ----
    n_cb = len(CALLBACK_PAIR.findall(src))
    c.ok("三张卡上没有成对回调了（onEdit + onDelete 应为 0 处）", n_cb == 0, f"实际 {n_cb} 处（删除回调又回来了？）")
    for needle, why in (
        ("RouteRail(", "线路卡的 A→B 轨道（共用件）"),
        ("ContactPickerSheet(", "联系人选择抽屉"),
        ("ContactCategoryPane(", "联系人的分类选择（FEAT-0009 起：标题行胶囊 + 左侧抽屉）"),
        ("vm.contacts.filter {", "联系人搜索的用户搜索过滤"),
    ):
        c.ok(f"本批没顺手改别的：{why} 还在", needle in src, f"找不到 {needle}")
    sec = section(read(DESIGN), DESIGN_42C)
    c.ok(
        f"设计规范 4.2c 那一节还在（≥ {SECTION_FLOOR} 字符）",
        len(sec) >= SECTION_FLOOR,
        f"那一节只剩 {len(sec)} 字符（规范被删掉或搬走了）",
    )
    c.ok(
        "4.2c 里那两条纪律都还在：位置（编辑一定在右边）+ 形态（圈底 CardActionIcon）",
        "编辑一定在右边" in sec and "CardActionIcon" in sec,
        "规范那一段被删了",
    )

    # ---- 6. 接线：反向验证 / CONVERTED 表 / 文档 / 登记 ----
    c.ok("本判据自己的反向验证在", (ROOT / REVERSE).exists(), REVERSE)
    c.ok(
        "本页还在 _check_form_panel_style 的 CONVERTED 表里（那一批的形态约束不能松）",
        "AddressScreen.kt" in read(FORM_STYLE_CHECK),
        "CONVERTED 表里找不到它",
    )
    doc = read(DOC)
    c.ok(
        "文档九节齐全（docs/changes/CHG-0012.md）",
        all(s in doc for s in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")),
        "文档缺节（_check_dev_spec.py 也会红）",
    )
    c.ok(
        "登记簿里有 CHG-0012 这一行（整行，不是一个链接里的字样）",
        bool(re.search(r"^\|\s*[\x60]?CHG-0012[\x60]?\s*\|", read(REGISTRY), re.M)),
        "没登记（别人不知道这个 ID 用掉了）",
    )

    return c.report("地址与联系人页卡片动作（CHG-0012）")


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("== 它到底在查什么（地址与联系人页卡片动作 CHG-0012）==")
        print("1. 卡片清点自己算：扫 private fun *Card(，逐张断言没有裸 IconButton（多一张卡就红）")
        print("2. 每张卡：只剩编辑那一颗（走 CardActionIcon、主色）；删除图标 / onDelete / 垃圾桶一律 0")
        print("3. 三张卡都不竖排、签名只剩 onEdit；线路卡 KDoc 里留着「删除搬进抽屉」的来历")
        print("3b. 删除入口在三个抽屉里、只在编辑态、只走 askDelete；页面不直接调 delete；页尾有二次确认")
        print("4. 形态：CardActionIcon 全库只有一处定义、内部是 TintedIcon 圆底、默认 36/18、Role.Button")
        print("5. 本批没顺手改别的：回调签名（只剩 onEdit）、路线轨道、联系人抽屉、左分类右列表、搜索过滤、规范 4.2c")
        print("6. 接线：反向验证在、CONVERTED 表里还在、文档九节、登记簿有 CHG-0012")
        sys.exit(0)
    sys.exit(main())
