"""反向验证：`_tools/qa/_check_billing_rule_form.py` 那些判据**真的抓得住**吗（2026-10-05 · CHG-0022）。

## 为什么必须有它
一条「永远绿的检查」等于没有检查（本仓库为此栽过好几次）。这一批被判的事**全都是「改坏了不会有任何报错」的类型**：
表单搬回弹窗、错误行从常驻底栏挪回滚动区末尾、金额格绕过 InputRules、closeForm() 被拆成两处裸赋值、
旧零件名字复活 —— 这些都能编译过、真机上「看着也能用」（弹窗里照样能填能存），只有翻页面才发现。

## 手法（与 `_reverse_verify_sheet_form_pages.py` 同一套，不另立一套）
对每个注入点：**先把文件按字节备份** → 注入 → 跑红线（期望非零退出**且**命中指定的判据标签）
→ **按字节还原** → 校验 sha256 与备份一致。
⛔ 全程不碰 `git checkout --`（那会把别的会话未提交的改动一起抹掉，实测发生过）。

## 两条特别挑出来的注入
- **⑦ 系统返回键交出去**：`BackHandler(enabled = false)` 一样能编译、返回箭头一样好使，
  只有按**系统返回键**时才发现「表单没关、列表被盖在底下」。这条钉住判据真的读了 BackHandler 的 enabled，
  而不是只看见 `BackHandler(` 就算过。
- **㊹㊺ 两条文档注入用正则锚**：变更登记表那一行与 AI_WORK_CLAIM 的声明块在同一批工作的**归档提交里会改内容**
  （进行中 → 已关闭、整块搬去「已完成」）。锚点写死整行/整块的话，归档完锚点就腐烂，
  元检查 `_check_reverse_verify_anchors.py` 会报红 —— 所以这两条按「这一行/这一块」匹配，归档后仍然认得出。

用法：
    python _tools/qa/_reverse_verify_billing_rule_form.py          # 全部跑
    python _tools/qa/_reverse_verify_billing_rule_form.py --list   # 只列注入点
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_billing_rule_form.py"

# 路径写成完整字面量（不是 `A + "…"`）：这样 `_check_reverse_verify_anchors.py` 才折得出目标文件，
# 每次全仓扫描都会顺手核对「这些锚点还在不在源码里」（锚点腐烂当场报红）。
P1 = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt"
P2 = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesViewModel.kt"
SPEC = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
STYLE = "_tools/qa/_check_form_panel_style.py"
INPUT = "_tools/qa/_check_input_rules.py"
README = "docs/changes/README.md"
CLAIM = "docs/AI_WORK_CLAIM.md"

# (说明, 相对路径, 锚点, 替换成, 期望哪条判据报红)
#
# ⚠️ 「期望」写的是**判据标签**，命中判据是输出里出现 `[!!]   <标签>` ——
#    只写标签本身不行：通过时那行也会打出来（`[OK]   <标签>`），等于永远算命中。
#    `~` 开头 = 任意一条 [!!] 行里包含这段子串即可（标签前面拼了行号时用）。
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    ("① 表单体不再铺满整屏（缩成半宽，像嵌在别处的一段）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "            .fillMaxSize()\n            .padding(pad)",
     "            .fillMaxWidth()\n            .padding(pad)",
     "表单体铺满整屏"),
    ("② 表单体丢掉纵向滚动（字段一多，底下的直接够不着）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "            .padding(pad)\n            .verticalScroll(rememberScrollState())",
     "            .padding(pad)",
     "表单体是能滚的一整列"),
    ("③ 错误行又落回滚动区里（且不止一处 FormErrorLine）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "        FormGroup(icon = Icons.Default.Notes, title = \"备注\", tint = MaterialTheme.colorScheme.outline) {",
     "        FormErrorLine(vm.formError)\n        FormGroup(icon = Icons.Default.Notes, title = \"备注\", tint = MaterialTheme.colorScheme.outline) {",
     "表单体里没有 FormErrorLine"),
    ("④ 常驻底栏里的错误行被拿掉（错误又只剩滚到底才看得见）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "            FormErrorLine(vm.formError)\n",
     "",
     "保存栏里有 FormErrorLine"),
    ("⑤ 早返回没了，列表又被画在表单底下（两层同屏叠着）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "            return@Scaffold\n",
     "",
     "表单打开时列表不再画在底下"),
    ("⑥ 保存栏不再挂在 Scaffold 的 bottomBar 上（换成别的位置）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "        bottomBar = {",
     "        bottomBarX = {",
     "底部那条保存栏挂在 Scaffold 的 bottomBar 上"),
    ("⑦ 系统返回键不再交给表单（按返回直接退出这一页，填的全丢）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "    BackHandler(enabled = vm.showForm) { vm.closeForm() }",
     "    BackHandler(enabled = false) { vm.closeForm() }",
     "系统返回键交给表单"),
    ("⑧ 顶栏不再跟着表单切换（新建时标题还是列表那个）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "                    title = if (vm.editing == null) \"新建计费规则\" else \"编辑计费规则\",",
     "                    title = if (vm.editing == null) \"新建规则\" else \"编辑计费规则\",",
     "顶栏跟着表单切换"),
    ("⑨ 备注那一组不再用 FormGroup（退回自己写的 Column）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "        FormGroup(icon = Icons.Default.Notes, title = \"备注\", tint = MaterialTheme.colorScheme.outline) {",
     "        Column(Modifier.fillMaxWidth()) {",
     "分组用 FormGroup，本页至少 5 组"),
    ("⑩ 规则名称那一格改名（判据按标签认它，改名就是换了一格）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "                label = \"规则名称\",",
     "                label = \"名称\",",
     "规则名称那一格还在且必填"),
    ("⑪ 固定工资那一格改名",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "                label = \"固定工资\",",
     "                label = \"月薪\",",
     "固定工资那一格还在"),
    ("⑫ 每单金额那一格改名",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "                    label = \"每单金额\",",
     "                    label = \"每单\",",
     "每单金额那一格还在"),
    ("⑬ 提成比例那一格改名",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "                label = \"提成比例\",",
     "                label = \"提成率\",",
     "提成比例那一格还在"),
    ("⑭ 价目那一格从 FormPickRow 退回普通行（看不出点了会展开）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "            FormPickRow(",
     "            FormActionRow(",
     "价目那一格是 FormPickRow"),
    ("⑮ 备注那一格从 FormTextAreaRow 换成单行 FormInputRow",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "            FormTextAreaRow(",
     "            FormInputRow(",
     "备注那一格是 FormTextAreaRow"),
    ("⑯ 这一页自己写回一个 SoTextField（共用行被绕开）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "        FormGroup(icon = Icons.Default.Notes, title = \"备注\", tint = MaterialTheme.colorScheme.outline) {",
     "        SoTextField(value = vm.draftRemark, onValueChange = { vm.draftRemark = it })\n        FormGroup(icon = Icons.Default.Notes, title = \"备注\", tint = MaterialTheme.colorScheme.outline) {",
     "这一页没有自己写的 SoTextField"),
    ("⑰ 这一页自己写回一个 OutlinedTextField（旧版式复辟）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "        FormGroup(icon = Icons.Default.Notes, title = \"备注\", tint = MaterialTheme.colorScheme.outline) {",
     "        OutlinedTextField(value = vm.draftRemark, onValueChange = { vm.draftRemark = it })\n        FormGroup(icon = Icons.Default.Notes, title = \"备注\", tint = MaterialTheme.colorScheme.outline) {",
     "这一页没有 OutlinedTextField"),
    ("⑱ 外面又冒出一个 FormGroup（分组跑出表单体了）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "        bottomBar = {",
     "        FormGroup(icon = Icons.Default.Badge, title = \"外面\", tint = Color(ShipperTeal)) { }\n        bottomBar = {",
     "所有 FormGroup 都在表单体里"),
    ("⑲ 固定工资那一格绕过 InputRules.moneyInput（金额过滤随手写）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "                onValueChange = { vm.draftSalary = InputRules.moneyInput(it) },",
     "                onValueChange = { vm.draftSalary = it },",
     "固定工资那一格过 InputRules.moneyInput"),
    ("⑳ 提成比例那一格放开到三位小数（百分比小数位不再统一）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "                    vm.draftCommissionRate = InputRules.moneyInput(it, maxDecimals = 2, maxWhole = 3)",
     "                    vm.draftCommissionRate = InputRules.moneyInput(it, maxDecimals = 3, maxWhole = 3)",
     "提成那两格限两位小数"),
    ("㉑ 逐类那一行的标题写死（不再带类名，五个类分不出哪行是哪行）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "                        label = c.name + \" · 每单金额\",",
     "                        label = \"每单金额\",",
     "逐类那两行的标题是拼出来的"),
    ("㉒ 分段选择器少掉一处（互斥选项改回一排按钮）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "                SegmentedPicker(\n                    labels = PIECE_MODE_OPTIONS.map { it.second },",
     "                SegmentedPickerX(\n                    labels = PIECE_MODE_OPTIONS.map { it.second },",
     "少数互斥选项仍用 SegmentedPicker（至少 5 处）"),
    ("㉓ PickerBlock 定义改名（分段选择器不再包在块里）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "private fun PickerBlock(",
     "private fun PickerBlockX(",
     "表单里的分段选择器都包在 PickerBlock 里"),
    ("㉔ 价目选择层被删掉（FreightPickSheet 那套整层没了）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "private fun FreightPickSheet(",
     "private fun FreightPickSheetX(",
     "价目选择层还在（FreightPickSheet / CategoryRail / 全选本分类）"),
    ("㉕ 价目层的开关换成表单自己那个标志位（两个开关串味）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "if (vm.showTemplatePicker) FreightPickSheet(vm)",
     "if (vm.showForm) FreightPickSheet(vm)",
     "价目层的开关还是 vm.showTemplatePicker"),
    ("㉖ 全页多出第二个 ModalBottomSheet（两层 modal 又叠起来）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "        bottomBar = {",
     "        ModalBottomSheet(onDismissRequest = {}) {}\n        bottomBar = {",
     "全页只有一个 ModalBottomSheet"),
    ("㉗ 全页多出第二个 AlertDialog（表单又回到弹窗那条路）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "        bottomBar = {",
     "        AlertDialog(onDismissRequest = {}) {}\n        bottomBar = {",
     "这一页只剩一个 AlertDialog"),
    ("㉘ 表单体里塞了一个弹窗（同屏两层 modal）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "        FormGroup(icon = Icons.Default.Notes, title = \"备注\", tint = MaterialTheme.colorScheme.outline) {",
     "        AlertDialog(onDismissRequest = {}) {}\n        FormGroup(icon = Icons.Default.Notes, title = \"备注\", tint = MaterialTheme.colorScheme.outline) {",
     "表单体里没有弹窗"),
    ("㉙ 剩下的那个 AlertDialog 不再是删除确认（被改成表单弹窗）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "            title = { Text(\"删除计费规则\") },",
     "            title = { Text(\"删掉规则\") },",
     "那个 AlertDialog 是删除确认，不是表单"),
    ("㉚ 旧零件名字回来（RuleDialog 又出现在这一页）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "private fun RuleFormBody(",
     "private fun RuleDialog(",
     "旧的 RuleDialog 弹窗零件彻底没了"),
    ("㉛ 保存栏丢掉 navigationBarsPadding（手势条压住按钮）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "                .navigationBarsPadding()",
     "                .padding(0.dp)",
     "保存栏是常驻的 Surface 且加了 navigationBarsPadding"),
    ("㉜ 保存按钮不再是满宽 52.dp 主按钮（变成又矮又不满宽）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt",
     "                modifier = Modifier.fillMaxWidth().height(52.dp),",
     "                modifier = Modifier.height(40.dp),",
     "保存按钮是满宽主按钮（52.dp）"),
    ("㉝ 表单状态改回旧名字 showDialog",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesViewModel.kt",
     "var showForm by mutableStateOf(false)",
     "var showDialog by mutableStateOf(false)",
     "状态叫 showForm"),
    ("㉞ 错误状态改回旧名字 dialogError",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesViewModel.kt",
     "var formError by mutableStateOf<String?>(null)",
     "var dialogError by mutableStateOf<String?>(null)",
     "错误叫 formError"),
    ("㉟ closeForm() 只关不清错误（上一次的红字跟着下一次表单走）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesViewModel.kt",
     "    fun closeForm() {\n        showForm = false\n        formError = null\n    }",
     "    fun closeForm() {\n        showForm = false\n    }",
     "closeForm() 一次清两样"),
    ("㊱ save() 成功路径不走 closeForm()（改成裸写标志位）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesViewModel.kt",
     "                closeForm()\n                load()",
     "                showForm = false\n                load()",
     "save() 成功路径走 closeForm()"),
    ("㊲ 保存失败也把表单关了（用户填的半页东西没了）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesViewModel.kt",
     "                formError = toApiException(e).message\n",
     "                formError = toApiException(e).message\n                closeForm()\n",
     "save() 失败时不关表单"),
    ("㊳ 保存失败不再把后端那句话写进 formError（错误被吞成一句套话）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesViewModel.kt",
     "formError = toApiException(e).message",
     "formError = \"保存失败\"",
     "save() 失败把后端那句话写进 formError"),
    ("㊴ openCreate() 不再把表单置为打开（点新建没反应）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesViewModel.kt",
     "        showForm = true",
     "        showForm = false",
     "openCreate 和 openEdit 都只置 showForm = true"),
    ("㊵ 旧名字没清干净（某处还留着 showDialog）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesViewModel.kt",
     "    var showForm by mutableStateOf(false)",
     "    var showForm by mutableStateOf(false)\n    private val showDialog = false",
     "旧名字清零"),
    ("㊶ 设计规范里那句根据被改掉（表单又允许塞进弹层）",
     "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md",
     "**表单带选择器时用单独一页**",
     "**表单改用弹层**",
     "设计规范里那句根据还在"),
    ("㊷ 这一页没登记进 _check_form_panel_style.py 的 CONVERTED（棘轮漏了它）",
     "_tools/qa/_check_form_panel_style.py",
     "\"ui/dispatcher/DriverBillingRulesScreen.kt\"",
     "\"ui/dispatcher/DriverBillingOther.kt\"",
     "这一页已登记进 _check_form_panel_style.py 的 CONVERTED"),
    ("㊸ 输入规则判据里这一页的豁免键被换走（化石规则回来了）",
     "_tools/qa/_check_input_rules.py",
     "DriverBillingRulesScreen.kt::规则名称",
     "DriverBillingOther.kt::规则名称",
     "输入规则判据里这一页的豁免键跟着改名了"),
    ("㊹ 变更登记表里那一行被换成别的号（判据说登记过，其实没登记）",
     "docs/changes/README.md",
     "re:\\| `CHG-0022` \\| CHG \\|[^\\n]*",
     "| `CHG-002X` | CHG | 注入占位（这一行被改号了） | 🚧 进行中 | [CHG-002X.md](CHG-002X.md) |",
     "变更登记表里有 CHG-0022 这一行"),
    ("㊺ AI_WORK_CLAIM.md 里那一块被改成别的号（判据说声明过，其实没声明）",
     "docs/AI_WORK_CLAIM.md",
     "re:### \\[2026-10-05 [^\\]]*\\][^\\n]*CHG-0022[\\s\\S]*?docs/changes/CHG-0022\\.md[^\\n]*",
     "### [2026-10-05 进行中] 会话：**CHG-002X 注入占位**",
     "AI_WORK_CLAIM.md 里有 CHG-0022 声明块"),
]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _old, _new, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    print("先确认干净状态下是绿的：", end=" ")
    rc, _ = run_check()
    if rc != 0:
        print("❌ 现在就是红的，先修好再跑反向验证")
        return 1
    print("✅ 绿")

    caught = 0
    problems: list[str] = []
    for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
        path = ROOT / rel
        if not path.exists():
            problems.append(f"{name}：找不到 {rel}")
            print(f"\n[{i}] {name}\n  ❌ 找不到 {rel}")
            continue
        orig = path.read_bytes()
        orig_sha = sha(orig)
        text = orig.decode("utf-8")
        # 锚点里写的是 `\n`。目标文件可能是 CRLF —— 那种情况下锚点会**静默不命中**，
        # 所以按文件自己的行尾归一，而不是直接跳过。
        eol = "\r\n" if "\r\n" in text else "\n"
        if eol != "\n":
            old = old.replace("\n", eol)
            new = new.replace("\n", eol)
        pat = old[3:] if old.startswith("re:") else re.escape(old)
        injected, n = re.subn(pat, new, text, count=1)
        if n != 1:
            problems.append(f"{name}：锚点没命中（{rel} 里的 {old[:40]!r}）")
            print(f"\n[{i}] {name}\n  ❌ 锚点没命中，跳过（注入点腐烂了）")
            continue
        inj_bytes = injected.encode("utf-8")
        path.write_bytes(inj_bytes)
        try:
            rc, out = run_check()
        finally:
            now = path.read_bytes()
            if now != inj_bytes:
                print(f"\n[{i}] {name}\n  🛑 有别的东西改了 {rel} —— **拒绝还原**，请人工处理！")
                return 2
            path.write_bytes(orig)
        if sha(path.read_bytes()) != orig_sha:
            print(f"\n[{i}] {name}\n  🛑 {rel} 还原后哈希对不上，停手")
            return 2

        if want.startswith("~"):
            hit = any(want[1:] in ln for ln in out.splitlines() if ln.lstrip().startswith("[!!]"))
        else:
            hit = f"[!!]   {want}" in out
        if rc != 0 and hit:
            caught += 1
            print(f"\n[{i}] {name}\n  ✅ 被抓到（红线非零退出，命中「{want}」）")
        else:
            why = "红线居然还是绿的" if rc == 0 else f"退出了，但输出里没有「[!!]   {want}」"
            problems.append(f"{name}：{why}")
            print(f"\n[{i}] {name}\n  ❌ {why}")

    print("\n" + "=" * 60)
    print(f"{caught}/{len(INJECTIONS)} 种破坏方式被抓住")
    if problems:
        print("❌ 有漏网的：")
        for p in problems:
            print("   -", p)
        return 1
    print("✅ 全部注入都被抓住，且每个文件都按字节还原")
    return 0


if __name__ == "__main__":
    sys.exit(main())