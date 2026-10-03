"""红线：司机计费规则的表单是单独一整页，不是弹窗（2026-10-05 · CHG-0022）。

## 这条红线保的是什么
设计规范 docs/PROJECT_MAP/06_DESIGN_SYSTEM.md 的 §4.14 四条坑第 4 条：

> 「表单带选择器时用单独一页，不要塞进 AlertDialog：全屏选品层套在弹窗里就是两层 modal
> 窗口叠着，而且字段一多弹窗会顶到屏幕边」（同处明说这条不限于记账）

这一页原来正是那个反例：RuleDialog 把十段字段（含「按分类」模式下每类一行）塞进 AlertDialog，
弹窗里还能再开一个占 90% 屏高的价目选择层。CHG-0022 把它搬成「同屏整页表单」——
顶部 AppTopBar 的返回、底部常驻保存栏、中间滚动体。

## 为什么要有机器判据
改回弹窗不会编译失败、真机上也能用，只有人肉翻页面才发现 —— 这正是本仓库最贵的一类退化。
所以下面钉住的不只是「是不是弹窗」，还有几件同样「改坏了不报错」的事：形态（整页 / 顶栏 /
常驻底栏 / 系统返回键 / 列表早返回）、字段零件（一律共用行）、错误行的位置（必须在常驻底栏里，
放在滚动体末尾等于滚到底才看得见）、钱的校验（三个金额格走 InputRules.moneyInput）、
VM 契约（closeForm 一条路关表单、失败不关表单）。

## 不归它管
卡片长什么样、价目层怎么排版 —— 那是 _check_freight_pricing.py 的地盘；
共用行的总数棘轮在 _check_form_panel_style.py；输入过滤在 _check_input_rules.py。

## 会互相盯着的三处（第 8 节复查）
- 本页已登记进 _check_form_panel_style.py 的 CONVERTED（那里一个描边输入框都不许有）；
- _check_input_rules.py 的豁免表里这一页必须已经不在了（规则名称框的标题变成干干净净的
  「规则名称」，不再被判类；留着旧的豁免键会按化石规则判红）；
- 设计规范里那句根据必须还在（不然这条判据的出处就没了）。

R4-BOUNDARY-JUSTIFICATION: 本文件只读 Presentation 层的两个 .kt 与四份文档/工具配置的文本，
不碰 Core / Extension / Infrastructure 的任何契约，也不替别的判据写断言（分工见上）。

用法：python _tools/qa/_check_billing_rule_form.py
配套：python _tools/qa/_reverse_verify_billing_rule_form.py（**45** 种破坏方式全被抓）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
# 报告器与注释剥离都不另立一套（注释剥离是个状态机，为了 "image/*" 这种字符串写的，抄一份必踩坑）
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = AND / "ui/dispatcher/DriverBillingRulesScreen.kt"
VM = AND / "ui/dispatcher/DriverBillingRulesViewModel.kt"
STYLE_CHK = ROOT / "_tools/qa/_check_form_panel_style.py"
INPUT_CHK = ROOT / "_tools/qa/_check_input_rules.py"
SPEC = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
CHANGE = ROOT / "docs/changes/CHG-0022.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

REL = "ui/dispatcher/DriverBillingRulesScreen.kt"
REL_VM = "ui/dispatcher/DriverBillingRulesViewModel.kt"
#: 这一页的下限（现在 725 行）：被搬走或清空时必须先喊，不许安静全绿。
MIN_LINES = 600
#: 设计规范里那句话（本判据的出处）。
SPEC_QUOTE = "表单带选择器时用单独一页"
DOC_PARTS = "①②③④⑤⑥⑦⑧⑨"


def slice_fun(src: str, header: str) -> str:
    """抠一个函数的正文：从 header 起、到**与自己同缩进**的那个右花括号。

    不写死行号：这一页还会被改，写死行号的判据第二次跑就指到别处去了（GOV-0004 那类事）。
    ⚠️ 收尾括号必须按 header 自己的缩进找（不是「行首的 }」）：ViewModel 里这些是**类方法**，
    整体缩进 4 格，写死 `\n}` 会把整个类剩下的部分都算进正文 —— 那样「closeForm() 一次清两样」
    这类断言会被后面别的函数里的同名赋值喂饱，永远绿（反验 ㉟㊴ 两条当场抓出来的）。
    """
    i = src.find(header)
    if i < 0:
        return ""
    indent = i - (src.rfind("\n", 0, i) + 1)
    close = "\n" + " " * indent + "}"
    j = src.find(close, i)
    return src[i : j + len(close)] if j >= 0 else src[i:]


def main() -> int:
    c = Checker()
    raw = read(SCREEN)
    src = strip_comments(raw)
    vm = strip_comments(read(VM))
    page = slice_fun(src, "fun DriverBillingRulesScreen(")
    body = slice_fun(src, "private fun RuleFormBody(")
    bar = slice_fun(src, "private fun RuleFormBottomBar(")
    blk = slice_fun(src, "private fun PickerBlock(")
    save = slice_fun(vm, "fun save()")
    close = slice_fun(vm, "fun closeForm()")

    # ── 1. 反空转 ─────────────────────────────────────────────────────────
    c.section("1. 反空转：源码与四个零件都认得出来（不然下面全是空话）")
    c.ok(f"{REL} 还是完整的一页（至少 {MIN_LINES} 行）",
         SCREEN.exists() and len(raw.splitlines()) >= MIN_LINES,
         f"读到 {len(raw.splitlines())} 行 —— 文件被搬走或清空了？")
    for name, seg in (("页面 DriverBillingRulesScreen", page),
                      ("表单体 RuleFormBody", body),
                      ("保存栏 RuleFormBottomBar", bar),
                      ("选择器块 PickerBlock", blk)):
        c.ok(f"认得出来{name}的正文", len(seg) > 150, f"只抠到 {len(seg)} 字")
    c.ok("认得出来 ViewModel 的 save() 正文", len(save) > 200, f"只抠到 {len(save)} 字")

    # ── 2. 形态 ──────────────────────────────────────────────────────────
    c.section("2. 形态：表单是单独一整页，不是弹窗")
    c.ok("旧的 RuleDialog 弹窗零件彻底没了", "RuleDialog" not in src)
    n_alert = src.count("AlertDialog(")
    c.ok("这一页只剩一个 AlertDialog", n_alert == 1, f"实际 {n_alert} 个")
    i_alert = src.find("AlertDialog(")
    zone = src[i_alert : i_alert + 1600] if i_alert >= 0 else ""
    c.ok("那个 AlertDialog 是删除确认，不是表单",
         "删除计费规则" in zone and "vm.confirmDelete()" in zone)
    c.ok("表单体铺满整屏", "fillMaxSize()" in body)
    c.ok("表单体是能滚的一整列", "verticalScroll(" in body)
    c.ok("表单体里没有弹窗", "AlertDialog(" not in body)
    c.ok("表单打开时列表不再画在底下", "return@Scaffold" in page and "if (vm.showForm) {" in page)
    c.ok("底部那条保存栏挂在 Scaffold 的 bottomBar 上",
         "bottomBar = {" in page and "RuleFormBottomBar(vm)" in page)
    c.ok("顶栏跟着表单切换", "新建计费规则" in page and "编辑计费规则" in page)
    c.ok("系统返回键交给表单",
         "BackHandler(enabled = vm.showForm)" in page and "vm.closeForm()" in page)

    # ── 3. 位置 ──────────────────────────────────────────────────────────
    c.section("3. 位置：错误行在常驻底栏里，不在滚动区末尾")
    c.ok("保存栏里有 FormErrorLine", "FormErrorLine(" in bar)
    c.ok("表单体里没有 FormErrorLine", "FormErrorLine(" not in body)
    c.ok("保存栏是常驻的 Surface 且加了 navigationBarsPadding",
         "Surface(" in bar and "navigationBarsPadding()" in bar)
    c.ok("保存按钮是满宽主按钮（52.dp）", "fillMaxWidth().height(52.dp)" in bar)

    # ── 4. 零件 ──────────────────────────────────────────────────────────
    c.section("4. 每一格都走共用行（不再自写输入框）")
    n_group = src.count("FormGroup(")
    c.ok("分组用 FormGroup，本页至少 5 组", n_group >= 5, f"实际 {n_group} 组")
    c.ok("规则名称那一格还在且必填", 'label = "规则名称",' in body and "required = true," in body)
    c.ok("固定工资那一格还在", 'label = "固定工资",' in body)
    c.ok("每单金额那一格还在", 'label = "每单金额",' in body)
    c.ok("提成比例那一格还在", 'label = "提成比例",' in body)
    c.ok("价目那一格是 FormPickRow", "FormPickRow(" in body and 'label = "价目",' in body)
    c.ok("备注那一格是 FormTextAreaRow", "FormTextAreaRow(" in body)
    c.ok("这一页没有自己写的 SoTextField", "SoTextField(" not in src)
    c.ok("这一页没有 OutlinedTextField", "OutlinedTextField" not in src)
    c.ok("所有 FormGroup 都在表单体里", n_group == body.count("FormGroup("),
         f"全页 {n_group} 组、表单体里 {body.count('FormGroup(')} 组")

    # ── 5. 钱 ────────────────────────────────────────────────────────────
    c.section("5. 钱：金额格都走 InputRules.moneyInput")
    n_money = src.count("InputRules.moneyInput(")
    c.ok("三个金额格都走 InputRules.moneyInput（至少 5 处）", n_money >= 5, f"实际 {n_money} 处")
    c.ok("固定工资那一格过 InputRules.moneyInput",
         "vm.draftSalary = InputRules.moneyInput(it)" in body)
    c.ok("提成那两格限两位小数", src.count("maxDecimals = 2, maxWhole = 3") >= 2)
    c.ok("逐类那两行的标题是拼出来的", src.count("label = c.name + ") >= 2)

    # ── 6. 选择器 ────────────────────────────────────────────────────────
    c.section("6. 少量互斥选项仍用分段选择器（放在白卡的块里）")
    n_seg = src.count("SegmentedPicker(")
    c.ok("少数互斥选项仍用 SegmentedPicker（至少 5 处）", n_seg >= 5, f"实际 {n_seg} 处")
    n_blk = src.count("PickerBlock(")
    c.ok("表单里的分段选择器都包在 PickerBlock 里", n_blk >= 6, f"实际 {n_blk} 处（含 1 处定义）")
    c.ok("价目选择层还在（FreightPickSheet / CategoryRail / 全选本分类）",
         "private fun FreightPickSheet(" in src and "CategoryRail(" in src and "全选本分类" in src)
    c.ok("价目层的开关还是 vm.showTemplatePicker",
         "if (vm.showTemplatePicker) FreightPickSheet(vm)" in src)
    n_sheet = src.count("ModalBottomSheet(")
    c.ok("全页只有一个 ModalBottomSheet", n_sheet == 1, f"实际 {n_sheet} 个")

    # ── 7. VM 契约 ───────────────────────────────────────────────────────
    c.section("7. ViewModel 契约：一条路关表单，失败不关")
    c.ok("状态叫 showForm", "var showForm by mutableStateOf(false)" in vm)
    c.ok("错误叫 formError", "var formError by mutableStateOf<String?>(null)" in vm)
    c.ok("closeForm() 一次清两样", "showForm = false" in close and "formError = null" in close)
    c.ok("save() 成功路径走 closeForm()", "closeForm()" in save)
    tail = save.split("catch (", 1)[1] if "catch (" in save else save
    c.ok("save() 失败时不关表单", "closeForm()" not in tail)
    c.ok("save() 失败把后端那句话写进 formError", "formError = toApiException(e).message" in tail)
    c.ok("openCreate 和 openEdit 都只置 showForm = true",
         "showForm = true" in slice_fun(vm, "fun openCreate()")
         and "showForm = true" in slice_fun(vm, "fun openEdit("))
    c.ok("旧名字清零", "showDialog" not in vm and "dialogError" not in vm)

    # ── 8. 登记与跨判据 ──────────────────────────────────────────────────
    c.section("8. 登记与跨判据（防清单过期 → 判据空转）")
    c.ok("设计规范里那句根据还在", SPEC_QUOTE in read(SPEC))
    c.ok("这一页已登记进 _check_form_panel_style.py 的 CONVERTED", REL in read(STYLE_CHK))
    c.ok("输入规则判据里这一页的豁免键跟着改名了",
         "DriverBillingRulesScreen.kt::规则名称" in read(INPUT_CHK))
    doc = read(CHANGE) if CHANGE.exists() else ""
    c.ok("docs/changes/CHG-0022.md 存在且九节齐",
         CHANGE.exists() and all(f"## {k}" in doc for k in DOC_PARTS))
    c.ok("变更登记表里有 CHG-0022 这一行", "CHG-0022" in read(REGISTRY))
    c.ok("AI_WORK_CLAIM.md 里有 CHG-0022 声明块", "CHG-0022" in read(CLAIM))

    # ── 汇总 ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：司机计费规则的表单是单独一整页"
          f"（顶栏 + 常驻保存栏 + 滚动体）、每一格都走共用行、"
          f"错误落在常驻底栏里、三个金额格都过 InputRules。")
    return 0


if __name__ == "__main__":
    sys.exit(main())