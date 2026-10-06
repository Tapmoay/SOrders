# -*- coding: utf-8 -*-
"""红线：选供应商的弹层里能**就地新建**一家（台账 L-40 / CHG-0068）。

## 这条是怎么来的
2026-10-07 用户台账 L-40：建采购单 / 进项票时点「供应商」那一行选人，名册里没有那一家时**没有别的出路** ——
只能退出这一页、去「供应商 / 厂商」页建、再回来重选。用户原话：「**没有建供应商的话他可以在这里
直接选择新建供应商**，省得又跑到那边去」。四问拍板：只填**名称 ＋ 电话**（最小可建）、进项票那处
弹层**一起改**、建完要**一句提示**、采购单保存时那句「还没选供应商」**改成引导**。

## 为什么必须有机器的判据
"加一颗按钮 + 打开一张表单"本身很容易做对，难的是它**四处都不被悄悄改回去**：

1. 入口有三个动作要一起成立：弹层底部那颗按钮（`onCreate`）、空态那句（说的是"现在就建一家"而不是支使人
   去别处）、以及"建完**直接选中**"（`pickSupplier(s)` 必须排在 `onCreated(s)` 之前）。少任何一头界面上都
   "长得很像"：按钮在、表单能开，只是建完什么都没选中 —— 用户会以为白建了。
2. 最小表单与全字段表单**只有一份实现**（`ui/common/SupplierEditorDialog.kt` 的 `minimal`）：再抄一份最小表单出来，
   编译、界面全绿，而"只问名称 ＋ 电话"这条口径会开始漂。
3. 采购单保存那句从**报错**变成了**入口**（`NEED_SUPPLIER` ＋ 提示条上那颗按钮）：它是两处代码的约定
   （那句话与那个 `actionLabel = if (vm.actionResult == NEED_SUPPLIER)`），改一处不改另一处，界面上看不出来。
4. 进项票那处最容易踩：`loadSuppliers()` 头一句带 `if (suppliers.isNotEmpty()) return` 早退守卫，就地新建之后**必须**
   直接重拉名册（`suppliers = container.repo.suppliers()`）—— 走错路的话新供应商不在名册里，而弹层已经关掉了，
   用户只看到"选完了、但栏里什么都没有"。
5. 还有一条**代价**要盯住：给 `OneShotSnackbar` 加可选参数时，全库唯一用尾随 lambda 的调用点
   （`OneShotSnackbar(snackbar, resetMessage) { … }`）会**静默改绑**到新参数上（Kotlin 的尾随 lambda 绑最后一个参数）——
   那正是本轮编译红过一次的原因。

所以判据分六层（空转闸 / 共用件 / 采购单 / 进项票 / 提示条 / 边界与文档），并且**自带空转闸**：
扫到的界面文件数、抽出来的函数体长度、以及**判据自己的总项数**都要达标 —— 少了任何一头，
这条红线会安静地全绿，比没有判据更危险。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。病是「名册里没有那一家时，用户只能退出去再回来」，
而"有入口"与"没有入口"在类型上完全一样：`onCreate: (() -> Unit)? = null` 传与不传、
`pickSupplier(s)` 排在 `onCreated(s)` 的前面还是后面、空态句是"现在就建一家"还是"先去别处建一个"，
全都照样编译、照样跑单测、界面上一眼看不出区别（除非有人在模拟器里真的点一遍）。
所以只能扫**结构**：那颗按钮在不在、挂在哪个分支下、最小表单是不是唯一一份、
"建完选中"那三行的**顺序**对不对、以及那句话与提示条上那颗按钮有没有一起改。
配套：python _tools/qa/_reverse_verify_supplier_inline_create.py（12 种破坏方式全被抓）；
「屏幕上真的能用」那一头由模拟器实测的截图负责（`shots/chg0068_*_5554.png`）。
本判据只读源码与文档（`read()`），不连库、不 import 后端、不跑迁移。

用法：python _tools/qa/_check_supplier_inline_create.py
     python _tools/qa/_check_supplier_inline_create.py --list   # 只列它到底在查什么
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
# 注释剥离**只有一份实现**（抄一份必踩同一个坑）
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

DIALOG = AND / "ui/common/SupplierEditorDialog.kt"
COMPONENTS = AND / "ui/common/Components.kt"
SUPPLIERS = AND / "ui/dispatcher/SuppliersScreen.kt"
PO_FORM = AND / "ui/dispatcher/PurchaseOrderFormScreen.kt"
INVOICE = AND / "ui/dispatcher/InvoiceFormScreen.kt"
BASIC = AND / "ui/profile/BasicSettingsScreen.kt"
DTOS = AND / "data/remote/dto/Dtos.kt"
APIS = AND / "data/remote/api/Apis.kt"
SUPPLIERS_API = ROOT / "backend/app/api/v1/suppliers.py"
CATALOG = ROOT / "docs/PROJECT_MAP/09A_HINT_CATALOG.md"
SPEC = ROOT / "docs/changes/CHG-0068.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = "_tools/qa/_reverse_verify_supplier_inline_create.py"

#: 扫到的界面文件数下限（防目录改名 / 搬走之后"一个文件都没扫到"也算过）
MIN_UI_FILES = 100
#: 抽出来的函数体字符数下限（**抽取失效比判据腐烂更危险** —— 那会变成一条永远绿的检查）
BODY_FLOOR = 200
SMALL_BODY_FLOOR = 120
#: 提示条调用点下限（给 `OneShotSnackbar` 加参数时，别的页面一个都不许被顺手改掉）
MIN_SNACKBAR_CALLS = 60
#: ⛔ 空转即停：判据自己的总项数下限（少了就是判据被删空 —— 比如整段被注释掉）
MIN_ITEMS = 40

NEW_EMPTY = "还没有供应商 —— 现在就建一家"
OLD_EMPTY_PO = "还没有供应商档案，先去「供应商 / 厂商」建一个"
OLD_EMPTY_INV = "还没有供应商 —— 先去「供应商」里建一家。"
GUIDE = "还没选供应商 —— 现在就建一家"
HINT_LINE = "地址、备注以后可以在「供应商 / 厂商」页补"
CREATE_BTN = 'TextButton(onClick = onCreate) { Text("新建供应商") }'


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def count(needle: str, text: str) -> int:
    return text.count(needle)


def fn_body(src: str, sig: str) -> str:
    """sig（如 `fun createSupplierInline(`）那个函数的**函数体**（按大括号配对，不是按行猜）。"""
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


def sig_of(src: str, sig: str, span: int = 400) -> str:
    """签名那一段（从 `fun X(` 起 span 个字符）—— 参数表在这里，函数体里没有。"""
    i = src.find(sig)
    return "" if i < 0 else src[i : i + span]


def between(src: str, a: str, b: str) -> str:
    i = src.find(a)
    j = src.find(b, i + 1) if i >= 0 else -1
    return "" if i < 0 or j < 0 else src[i:j]


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

    @property
    def total(self) -> int:
        return self.passes + len(self.fails)

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项，共 {self.total} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def main() -> int:
    if refuse_if_injecting("就地新建供应商检查"):
        return 1

    c = Checker()
    print("选供应商的弹层里能就地新建一家（台账 L-40 / CHG-0068）：2026-10-07")

    all_kt = list(AND.rglob("*.kt"))
    all_ui = "".join(code(p) for p in all_kt)
    dlg = code(DIALOG)
    comp = code(COMPONENTS)
    sup = code(SUPPLIERS)
    po = code(PO_FORM)
    inv = code(INVOICE)

    # ---- 0. 空转闸：先证明"确实扫到了东西" ----
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(all_kt) >= MIN_UI_FILES,
        f"实际 {len(all_kt)}",
    )
    for p, why in (
        (DIALOG, "共用弹窗（最小形态与全字段形态同一份）"),
        (COMPONENTS, "共用提示条（那颗按钮的落点）"),
        (PO_FORM, "采购单表单（弹层 ＋ 就地新建 ＋ 保存那句引导）"),
        (INVOICE, "进项票表单（第二个就地新建入口）"),
    ):
        c.ok(f"空转闸：{why}读得到（{p.name}）", len(code(p)) > 2000, f"{len(code(p))} 字符")
    dlg_body = fn_body(dlg, "fun SupplierEditorDialog(")
    po_vm = fn_body(po, "fun createSupplierInline(")
    inv_vm = fn_body(inv, "fun createSupplierInline(")
    po_sheet = fn_body(po, "private fun SupplierPickSheet(")
    inv_sheet = fn_body(inv, "private fun PickSheet(")
    snack_body = fn_body(comp, "fun OneShotSnackbar(")
    for label, body, floor in (
        ("共用弹窗 SupplierEditorDialog", dlg_body, BODY_FLOOR),
        ("采购单 createSupplierInline", po_vm, SMALL_BODY_FLOOR),
        ("进项票 createSupplierInline", inv_vm, SMALL_BODY_FLOOR),
        ("采购单 SupplierPickSheet", po_sheet, BODY_FLOOR),
        ("进项票 PickSheet", inv_sheet, BODY_FLOOR),
        ("共用提示条 OneShotSnackbar", snack_body, SMALL_BODY_FLOOR),
    ):
        c.ok(
            f"空转闸：{label} 的函数体抽得出来（≥ {floor} 字符）",
            len(body) >= floor,
            f"只抽到 {len(body)} 字符 —— 抽取失效会让下面每一条都安静地过",
        )

    # ---- 1. 共用件：最小表单与全字段表单**只有一份实现** ----
    c.ok(
        "共用弹窗只有一份定义（全库 fun SupplierEditorDialog( 恰好 1 处）",
        count("fun SupplierEditorDialog(", all_ui) == 1,
        f"数到 {count('fun SupplierEditorDialog(', all_ui)} 处 —— 有人又抄了一份",
    )
    c.ok("共用弹窗住在 ui/common/（不是某个页面私有）", DIALOG.exists(), "文件不在")
    c.ok(
        "签名带 `minimal: Boolean = false`（可选，档案页那两处不传）",
        "minimal: Boolean = false" in dlg,
        "参数被改成必填 / 改名了",
    )
    c.ok(
        "最小形态的标题是「新建供应商」",
        'minimal -> "新建供应商"' in dlg and '"新增供应商 / 厂商"' in dlg and '"改资料"' in dlg,
        "标题分支被改掉了（档案页那两种标题必须还在）",
    )
    i_m1 = dlg.find("if (!minimal) {")
    i_m2 = dlg.find("if (!minimal) {", i_m1 + 1) if i_m1 >= 0 else -1
    i_phone = dlg.find('label = "电话"')
    c.ok(
        "最小形态只问名称 ＋ 电话（电话那一行夹在两个 if (!minimal) 之间 ⇒ 两种形态都有它）",
        i_m1 >= 0 and i_m2 > i_m1 and i_m1 < i_phone < i_m2,
        f"位置：m1={i_m1} phone={i_phone} m2={i_m2}",
    )
    c.ok(
        "字段分支恰好两处 if (!minimal)（联系人一处、地址＋备注一处）",
        count("if (!minimal) {", dlg) == 2,
        f"数到 {count('if (!minimal) {', dlg)} 处",
    )
    i_else = dlg.find("} else {")
    i_hint = dlg.find(HINT_LINE)
    c.ok(
        "口径 ③ 的那句提示在最小形态里（} else { 之后，两处共用同一份）",
        i_else >= 0 and i_hint > i_else and "Spacer(Modifier.height(4.dp))" in dlg[i_else:i_hint],
        "提示句没挂在最小形态上（或者被挪去了别处）",
    )
    c.ok(
        "那句提示全库只有一处（不各写一遍）",
        count(HINT_LINE, all_ui) == 1,
        f"数到 {count(HINT_LINE, all_ui)} 处",
    )
    c.ok(
        "确认按钮在最小形态下说「建好并选中」、全字段下说「保存」",
        'if (minimal) "建好并选中" else "保存"' in dlg,
        "按钮文案被改掉了 —— 用户看不出这一次会顺手选中",
    )
    c.ok(
        "名称必填：按钮 enabled = name.isNotBlank()",
        "enabled = name.isNotBlank()" in dlg,
        "空名字也能提交了",
    )
    c.ok(
        "电话仍走唯一一份输入规则（InputRules.phoneInput）",
        "InputRules.phoneInput(it)" in dlg,
        "电话那一行绕过了输入规则",
    )
    c.ok(
        "新文件只画共用行、没有第二份描边输入框（OutlinedTextField 不许出现）",
        "OutlinedTextField" not in dlg,
        "又手写了一个描边输入框（_check_form_panel_style.py 会红，这条先红）",
    )
    c.ok(
        "供应商页那份私有的已删除（private fun SupplierEditorDialog 全库 0 处）",
        count("private fun SupplierEditorDialog(", all_ui) == 0,
        "页面私有那一份还在 —— 同一个弹窗有两份实现了",
    )
    c.ok(
        "供应商页仍有两处调用（改资料 ＋ 新建），且都走**全字段**形态",
        count("SupplierEditorDialog(", sup) == 2 and "minimal" not in sup,
        f"调用 {count('SupplierEditorDialog(', sup)} 处；minimal 出现 {count('minimal', sup)} 次",
    )
    c.ok(
        "就地新建的两处调用都传 minimal = true（全库恰好 2 处）",
        count("minimal = true", all_ui) == 2,
        f"数到 {count('minimal = true', all_ui)} 处",
    )

    # ---- 2. 采购单：弹层那颗按钮 ＋ 建完直接选中 ＋ 保存那句是入口 ----
    c.ok(
        "采购单弹层加了可选参数 onCreate",
        "onCreate: (() -> Unit)? = null" in sig_of(po, "private fun SupplierPickSheet("),
        "参数表里没有 onCreate",
    )
    c.ok(
        "弹层底部那颗按钮真的画出来了（if (onCreate != null) + 「新建供应商」）",
        "if (onCreate != null) {" in po_sheet and CREATE_BTN in po_sheet,
        "按钮没画 / 文案被改",
    )
    c.ok(
        "那颗按钮在列表之后（空态也在它前面）—— 名册空的时候照样点得到",
        po_sheet.find(NEW_EMPTY) < po_sheet.find("if (onCreate != null) {"),
        "按钮被放到了列表前面 / 空态分支里",
    )
    c.ok(
        "空态句改成了入口（不再是支使人去别的页面）",
        NEW_EMPTY in po and OLD_EMPTY_PO not in po,
        "旧句还在 / 新句没写",
    )
    c.ok(
        "调用点把 onCreate 接上（creatingSupplier = true）",
        "onCreate = { creatingSupplier = true }" in po,
        "弹层收不到 onCreate（按钮点了没反应）",
    )
    c.ok(
        "就地新建那张弹窗挂在采购单页上（minimal = true）",
        "SupplierEditorDialog(" in po and "minimal = true," in po,
        "弹窗没挂上",
    )
    po_block = between(po, "if (creatingSupplier) {", "if (showProductPicker)")
    po_save = po_block[po_block.find("onSave = {"):]
    c.ok(
        "建完把两个弹层都关掉（在 onSave 回调里：先关这张弹窗、再关选供应商弹层）",
        "vm.createSupplierInline(name, phone) {" in po_save
        and 0 <= po_save.find("vm.createSupplierInline(name, phone) {") < po_save.find("creatingSupplier = false")
        and 0 <= po_save.find("creatingSupplier = false") < po_save.find("showSupplierPicker = false"),
        "少关了一个 —— 用户会停在空弹层上",
    )
    c.ok(
        "采购单 VM 的 createSupplierInline：先建、再刷新、再**选中**、最后回调",
        "container.repo.createSupplier(SupplierCreateRequest(name = name, phone = phone))" in po_vm
        and po_vm.find("loadSuppliers()") >= 0
        and 0 <= po_vm.find("pickSupplier(s)") < po_vm.find("onCreated(s)"),
        "「建完直接选中」这条链断了（顺序或调用缺一）",
    )
    c.ok(
        "建成功有一句回执（已建档案：<名字>）",
        'actionResult = "已建档案：' in po_vm,
        "建完没有任何回执",
    )
    c.ok(
        "建失败如实报后端那句话（重名由后端 _check_name_free 拦）",
        "actionResult = toApiException(e).message" in po_vm,
        "把后端的拒绝吞掉了",
    )
    c.ok(
        "保存那句引导是常量、且只定义一次",
        'private const val NEED_SUPPLIER = "' in po and count(GUIDE, po) == 1,
        f"常量没了 / 这句话在采购单页出现 {count(GUIDE, po)} 次",
    )
    c.ok(
        "保存时没选供应商仍然**拦住**（改了常量没改闸门）",
        "actionResult = NEED_SUPPLIER" in po and "if (sid == null) {" in po,
        "闸门被顺手放开了",
    )
    c.ok(
        "旧的那句裸文案不在了（还没选供应商）",
        'actionResult = "还没选供应商"' not in po,
        "两句话并存 —— 提示条认不出该不该长按钮",
    )
    c.ok(
        "提示条上那颗按钮只在那一句时出现，点它去开选供应商弹层",
        'actionLabel = if (vm.actionResult == NEED_SUPPLIER) "现在就建一家" else null' in po
        and "onAction = { showSupplierPicker = true }" in po,
        "按钮与那句话的约定断了",
    )
    c.ok(
        "三个 showXxxPicker 状态在提示条**之前**声明（否则 lambda 前向引用编译不过）",
        0 <= po.find("var showSupplierPicker by remember") < po.find("OneShotSnackbar("),
        "状态被挪到了提示条之后 —— 编译会红（本轮已经红过一次）",
    )
    c.ok(
        "回归：保存成功仍然回上一页",
        "LaunchedEffect(vm.saved) { if (vm.saved) onBack() }" in po,
        "保存成功之后的收尾被动了",
    )

    # ---- 3. 进项票：同一件事的第二处（早退守卫那条最坑）----
    c.ok(
        "进项票弹层加了两个可选参数 createLabel / onCreate",
        "createLabel: String? = null" in sig_of(inv, "private fun PickSheet(")
        and "onCreate: (() -> Unit)? = null" in sig_of(inv, "private fun PickSheet("),
        "参数表里少了一个",
    )
    c.ok(
        "弹层底部那颗按钮画出来了（两个都给了才画）",
        "if (createLabel != null && onCreate != null) {" in inv_sheet and "Text(createLabel)" in inv_sheet,
        "按钮没画 / 条件被放宽",
    )
    c.ok(
        "空态句改成了入口（进项票那处）",
        NEW_EMPTY in inv and OLD_EMPTY_INV not in inv,
        "旧句还在 / 新句没写",
    )
    inv_call = between(inv, "empty = " + '"' + NEW_EMPTY + '"', "onDismiss")
    c.ok(
        "供应商那处调用点把三样都接上了（空态句 ＋ createLabel ＋ onCreate）",
        'createLabel = "新建供应商"' in inv and "onCreate = { creatingSupplier = true }" in inv,
        "调用点没接上",
    )
    c.ok(
        "只有供应商那一处带那颗按钮（选客户弹层不动）",
        count("createLabel = ", inv) == 1,
        f"数到 {count('createLabel = ', inv)} 处 —— 选客户那处也被改了",
    )
    inv_block = between(inv, "if (creatingSupplier) {", "if (showCustomerSheet)")
    inv_save = inv_block[inv_block.find("onSave = {"):]
    c.ok(
        "就地新建那张弹窗挂在进项票页上（minimal = true）＋ 建完关掉两个弹层",
        "SupplierEditorDialog(" in inv_block and "minimal = true," in inv_block
        and "vm.createSupplierInline(name, phone) {" in inv_save
        and 0 <= inv_save.find("vm.createSupplierInline(name, phone) {") < inv_save.find("creatingSupplier = false")
        and 0 <= inv_save.find("creatingSupplier = false") < inv_save.find("showSupplierSheet = false"),
        "弹窗没挂上 / 没关干净",
    )
    c.ok(
        "进项票 VM 刷新名册**绕开** loadSuppliers() 的早退守卫（直接重拉）",
        "suppliers = container.repo.suppliers()" in inv_vm and "loadSuppliers()" not in inv_vm,
        "走了带 if (suppliers.isNotEmpty()) return 的那条路 —— 新供应商不在名册里",
    )
    c.ok(
        "进项票 VM 也是先建、再选中、最后回调",
        0 <= inv_vm.find("pickSupplier(s)") < inv_vm.find("onCreated(s)"),
        "「建完直接选中」这条链断了",
    )
    c.ok(
        "进项票建失败走这一页已有的错误行（formError）",
        "formError = toApiException(e).message" in inv_vm,
        "失败被吞掉 / 换了通道（这一页没有提示条）",
    )
    c.ok(
        "回归：loadSuppliers 的早退守卫仍在（那是「进页面才拉一次」的意思，别顺手删）",
        "if (suppliers.isNotEmpty()) return" in inv,
        "守卫被删了 —— 得重新想这条路的语义",
    )
    c.ok(
        "回归：进项票那句既有措辞没动",
        "进了谁的货就选谁" in inv and "进项票至少要挂一张采购单" in inv,
        "顺手改了别的错误文案",
    )

    # ---- 4. 共用提示条：那颗按钮是**可选**的，60 多处旧调用点一个都不许受影响 ----
    snack_sig = sig_of(comp, "fun OneShotSnackbar(")
    c.ok(
        "提示条新增的两个参数都是可选的（有默认值）",
        "actionLabel: String? = null" in snack_sig and "onAction: (() -> Unit)? = null" in snack_sig,
        "参数被改成必填（全库 60 多处会一起编译红）",
    )
    c.ok(
        "提示条把按钮交给原生 Snackbar（showSnackbar 的 actionLabel）",
        "hostState.showSnackbar(" in snack_body
        and "actionLabel = actionLabel" in snack_body
        and "withDismissAction = false" in snack_body,
        "自己另画了一个提示条 / 没把按钮传下去",
    )
    c.ok(
        "只有人**真的按了**才算（SnackbarResult.ActionPerformed 才回调）",
        "if (result == SnackbarResult.ActionPerformed) onAction?.invoke()" in snack_body,
        "把「显示过」当成了「按过」—— 会自己打开弹层",
    )
    c.ok(
        "回归：消息仍然**先消费再显示**（切页回来不重放）",
        0 <= snack_body.find("onConsumed()") < snack_body.find("hostState.showSnackbar("),
        "顺序反了（用户 2026-09-18 要的行为）",
    )
    c.ok(
        "全库提示条调用点没被顺手改掉（≥ 60 处）",
        count("OneShotSnackbar(", all_ui) >= MIN_SNACKBAR_CALLS,
        f"只剩 {count('OneShotSnackbar(', all_ui)} 处",
    )
    c.ok(
        "唯一用尾随 lambda 的那处已改成显式 onConsumed（本轮编译红的根因）",
        "OneShotSnackbar(snackbar, resetMessage, onConsumed = { resetMessage = null })" in code(BASIC)
        and "OneShotSnackbar(snackbar, resetMessage) {" not in all_ui,
        "尾随 lambda 会把新参数当成回调 —— 编译红，而且报错在别的文件里",
    )
    c.ok(
        "提示条定义只有一份（fun OneShotSnackbar( 恰好 1 处）",
        count("fun OneShotSnackbar(", all_ui) == 1,
        f"数到 {count('fun OneShotSnackbar(', all_ui)} 处",
    )

    # ---- 5. 边界：后端与接口一个字没动 ----
    sup_api = read(SUPPLIERS_API)
    c.ok(
        "后端没有新端点（POST /suppliers 仍然只有一处）",
        count('@router.post("/suppliers"', sup_api) == 1,
        "有人顺手加了一个创建供应商的端点",
    )
    c.ok(
        "建供应商仍然走既有的重名校验与审计",
        "_check_name_free(db, name)" in sup_api and "OperationAction.SUPPLIER_UPSERT" in sup_api,
        "重名 / 审计被绕过了",
    )
    c.ok(
        "接口层没有新增（Apis.kt 里 createSupplier 仍然只有一处定义）",
        count("suspend fun createSupplier(", code(APIS)) == 1,
        "多了一个创建供应商的接口",
    )
    dto = code(DTOS)
    dto_body = sig_of(dto, "data class SupplierCreateRequest(", 500)
    c.ok(
        "DTO 字段一个没变（name / contact_name / phone / address / remark）",
        '@SerialName("contact_name")' in dto_body and "address: String" in dto_body and "remark: String" in dto_body,
        "最小表单是靠改 DTO 实现的",
    )
    c.ok(
        "构造 SupplierCreateRequest 的地方仍然只有那几处（DTO 定义 ＋ 档案页全字段 ＋ 两处最小 ＋ AI 写工具 = 5）",
        count("SupplierCreateRequest(", all_ui) == 5,
        f"数到 {count('SupplierCreateRequest(', all_ui)} 处 —— 有人又造了一个「最小可建」",
    )

    # ---- 6. 文档与配对（判据自己也要有人盯）----
    c.ok(
        "新句子进了提示清单（跑过 python _tools/qa/_hint_inventory.py --md）",
        HINT_LINE in read(CATALOG),
        "09A_HINT_CATALOG.md 里没有这句 —— 提示总开关管不到它",
    )
    c.ok("变更单 docs/changes/CHG-0068.md 存在", SPEC.exists(), "变更单没了")
    spec = read(SPEC)
    c.ok(
        "变更单写清了两份脚本的名字（判据 + 反向验证）",
        "_check_supplier_inline_create.py" in spec and "_reverse_verify_supplier_inline_create.py" in spec,
        "⑥/⑦ 里没有这份脚本的名字",
    )
    c.ok(
        "变更单的边界结论写的是 PRESENTATION（这次只动界面入口）",
        "PRESENTATION" in spec,
        "边界结论没写 / 写成了核心",
    )
    c.ok(
        "变更单写清了「只填名称 ＋ 电话」与「建完直接选中」这两条口径",
        "名称 ＋ 电话" in spec and "选中" in spec,
        "口径没写进变更单",
    )
    c.ok(
        "登记簿里有这一行（docs/changes/README.md）",
        "CHG-0068" in read(README),
        "README 里没有它 —— 下一个人会以为这条没人在做",
    )
    c.ok(
        "认领里有这一条（docs/AI_WORK_CLAIM.md）",
        "CHG-0068" in read(CLAIM),
        "AI_WORK_CLAIM.md 里没有它",
    )
    c.ok("这条红线配了反向验证脚本", (ROOT / REVERSE).exists(), f"找不到 {REVERSE}")

    # ---- 7. ⛔ 空转即停：判据自己的总项数 ----
    c.ok(
        f"判据总项数 ≥ {MIN_ITEMS}（少了就是判据被删空 —— 空转的检查比没有检查更危险）",
        c.total + 1 >= MIN_ITEMS,
        f"只有 {c.total + 1} 项",
    )

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 空转闸：扫到的 .kt ≥ 100、六段函数体抽得出来、判据自己的项数 ≥ 40")
        print("     · 共用件：SupplierEditorDialog 只有一份、minimal 只砍掉联系人与地址备注、那句提示在最小形态里")
        print("     · 采购单：弹层底部那颗按钮（列表之后）、空态句是入口、建完直接选中、提示条上那颗按钮只认 NEED_SUPPLIER")
        print("     · 进项票：同一套 ＋ 刷新名册必须绕开 loadSuppliers 的早退守卫")
        print("     · 提示条：两个新参数可选、按钮交给原生 Snackbar、只有真按了才回调、先消费再显示、旧调用点一个没少")
        print("     · 边界：后端没有新端点、DTO 一个字段没变、选客户弹层与既有错误文案没动")
        print("     · 文档：提示清单收进新句、变更单 / 登记簿 / 认领 / 反向验证脚本在")

    return c.report("选供应商的弹层里能就地新建一家（L-40 / CHG-0068）")


if __name__ == "__main__":
    sys.exit(main())
