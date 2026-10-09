# -*- coding: utf-8 -*-
r"""账号管理页抽屉表单（CHG-0018）的反向验证：一条红线要能被"真的破坏一次"证明它在检查。

每条注入只改一处，跑一遍 _check_users_form.py，要求它报红、而且报红的就是这条红线；
跑完按**字节**把被碰过的文件还原，再逐字节核对一遍。
锚点一律不写行首缩进：注入结果不需要能编译，只要判据变红。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:  # PowerShell 重定向时 stdout 会退回 GBK，中文与 ✅ 都编不出去
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_users_form.py"

SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/UsersManageScreen.kt"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/UsersManageViewModel.kt"
FORM_PANEL = "_tools/qa/_check_form_panel_style.py"
SHEET_PAGES = "_tools/qa/_check_sheet_form_pages.py"
BASELINE = "_tools/qa/_form_panel_baseline.txt"
DOC = "docs/changes/CHG-0018.md"
REGISTRY = "docs/changes/README.md"
DESIGN = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

NL = chr(10)
Q = chr(34)


def kill(s: str, old: str, n: int = 1) -> str:
    """删掉 old（最多 n 处）。"""
    return s.replace(old, "", n)


def gsub(s: str, pat: str, rep: str) -> str:
    r"""按正则换一处（锚点里用 \s* 兜住缩进，不数空格）。"""
    return re.sub(pat, rep, s, count=1)


CASES: list[tuple[str, str, object, str]] = [
    # ── 1. 不再是弹窗 / 抽屉三件套 ────────────────────────────────────────
    ("抽屉又变回 AlertDialog",
     SCREEN,
     lambda s: s.replace("ModalBottomSheet(onDismissRequest = { vm.closeSheet() }, sheetState = sheetState) {",
                         "AlertDialog(onDismissRequest = { vm.closeSheet() }) {"),
     "本页不再有 AlertDialog"),
    ("抽屉不再撑满高度（大屏上只占半截）",
     SCREEN, lambda s: gsub(s, r"\.fillMaxHeight\(\)\s*\n\s*", ""),
     "fillMaxWidth().fillMaxHeight()"),
    ("抽屉不再避让键盘（imePadding 没了）",
     SCREEN, lambda s: gsub(s, r"\.imePadding\(\)\s*(?=\n)", ""),
     "撑满之后接 .padding"),
    ("抽屉不能滚了（够不着保存）",
     SCREEN, lambda s: gsub(s, r"\.imePadding\(\)(\s*)\.verticalScroll\(rememberScrollState\(\)\)", ".imePadding()"),
     "能滚（.imePadding()"),
    ("分组之间贴在一起（14dp 没了）",
     SCREEN, lambda s: kill(s, "verticalArrangement = Arrangement.spacedBy(14.dp)," + NL),
     "组间统一 14dp"),
    ("最底一行贴着手势条（24dp Spacer 没了）",
     SCREEN, lambda s: kill(s, "Spacer(Modifier.height(24.dp))"),
     "底部留 24dp"),
    ("右上角的 × 自己动手关（不走 closeSheet）",
     SCREEN, lambda s: s.replace("SheetCloseButton(onClick = { vm.closeSheet() })",
                                 "SheetCloseButton(onClick = { vm.showSheet = false })"),
     "关抽屉统一走 closeSheet()"),
    ("VM 里开关改回旧名 showDialog",
     VM, lambda s: s.replace("var showSheet by mutableStateOf(false)", "var showDialog by mutableStateOf(false)"),
     "开关叫 showSheet"),
    ("保存途中也能关抽屉（闸门没了）",
     VM, lambda s: s.replace("if (!acting) showSheet = false", "showSheet = false"),
     "保存途中不许关"),

    # ── 2. 分组一律白卡 ──────────────────────────────────────────────────
    ("第三个分组不再是白卡（FormGroup → SectionCard）",
     SCREEN, lambda s: gsub(s, r"FormGroup\((\s*icon = Icons\.Default\.Visibility)", r"SectionCard(\1"),
     "白卡分组恰好四个"),
    ("分组标题改了（账号 → 基本信息）",
     SCREEN, lambda s: s.replace('title = "账号"', 'title = "基本信息"'),
     "四个分组的标题就是这四样"),
    ("账号组里的三行退回系统描边框",
     SCREEN, lambda s: s.replace("FormInputRow(", "PlainRow(", 3),
     "分组「账号」里用的是 FormInputRow("),
    ("「车辆与计费」借了深蓝色（本族黄绿没了）",
     SCREEN, lambda s: gsub(s, r"(title = .车辆与计费.,\s*tint = )Color\(DriverLime\)", r"\1Color(NavBlue)"),
     "「车辆与计费」用黄绿 DriverLime"),
    ("商品可见范围那个分组换了图标",
     SCREEN, lambda s: gsub(s, r"(icon = )Icons\.Default\.Visibility", r"\1Icons.Default.Person"),
     "四个分组的图标"),
    ("商品可见范围那一组又自己画了一遍标题",
     SCREEN, lambda s: s.replace('                            label = "可见范围",',
                                 "Text(" + Q + "商品可见范围" + Q + ", style = MaterialTheme.typography.titleSmall)" + NL + '                            label = "可见范围",', 1),
     "自己不再画标题"),

    # ── 3. 选取器一律下拉 ────────────────────────────────────────────────
    ("抽屉里又出现描边框（OutlinedTextField）",
     SCREEN, lambda s: s.replace("FormErrorLine(vm.formError)",
                                 "OutlinedTextField(value = " + Q + Q + ", onValueChange = {})" + NL + "                FormErrorLine(vm.formError)", 1),
     "OutlinedTextField 是 0"),
    ("下拉行丢了 menuAnchor（点不开）",
     SCREEN, lambda s: kill(s, "modifier = Modifier.menuAnchor()," + NL),
     "menuAnchor"),
    ("选取行退回手拼（三处只剩两处）",
     SCREEN, lambda s: s.replace("FormPickRow(", "PickRow(", 1),
     "选取行恰好三处"),
    ("车型候选就地写死（只剩大车）",
     SCREEN, lambda s: s.replace('listOf("large" to "大车司机", "trailer" to "挂车司机")',
                                 'listOf("large" to "大车司机")'),
     "车型候选就是那两档"),
    ("车型下拉选完不写回 vm.draftVehicleType",
     SCREEN, lambda s: kill(s, "vm.draftVehicleType = k" + NL),
     "车型下拉写回"),
    ("「不挂规则」写回一个假 id",
     SCREEN, lambda s: s.replace("vm.draftRuleId = null; ruleExpanded = false",
                                 "vm.draftRuleId = 0L; ruleExpanded = false"),
     "不挂规则"),
    ("规则候选不再带后端给的一句话说明",
     SCREEN, lambda s: kill(s, "r.summary," + NL),
     "规则候选来自 vm.rules"),
    ("选中规则不再写回 draftRuleId",
     SCREEN, lambda s: s.replace("vm.draftRuleId = r.id; ruleExpanded = false", "ruleExpanded = false"),
     "选中规则写回"),
    ("计费规则标签改短（别处判据的锚点被毁）",
     SCREEN, lambda s: s.replace('label = "计费规则（他怎么算钱就看这一项）"', 'label = "计费规则"'),
     "计费规则的标签原样保留"),

    # ── 4. 输入行 ────────────────────────────────────────────────────────
    ("手机号不再必填（红星没了）",
     SCREEN, lambda s: gsub(s, r'(label = "手机号（登录账号）",[\s\S]{0,400}?required = )true', r"\1false"),
     "手机号那一行在、走 required"),
    ("手机号标签改短（说不清它是登录账号）",
     SCREEN, lambda s: s.replace('label = "手机号（登录账号）"', 'label = "手机号"'),
     "手机号标签仍是"),
    ("手机号丢了 InputRules 过滤",
     SCREEN, lambda s: s.replace("InputRules.mobileInput(it)", "it", 1),
     "手机号走 InputRules"),
    ("手机号键位改成文本",
     SCREEN, lambda s: s.replace("keyboardType = KeyboardType.Phone", "keyboardType = KeyboardType.Text"),
     "手机号键位是 Phone"),
    ("手机号空值提示不说 11 位",
     SCREEN, lambda s: s.replace('placeholder = "11 位手机号"', 'placeholder = "请输入"'),
     "手机号空值提示说清是 11 位"),
    ("姓名也套上手机号过滤（中文写不进去）",
     SCREEN, lambda s: s.replace("onValueChange = { vm.draftName = it },",
                                 "onValueChange = { vm.draftName = InputRules.mobileInput(it) },"),
     "姓名那一行在"),
    ("姓名不再标选填",
     SCREEN, lambda s: s.replace('placeholder = "选填"', 'placeholder = "请输入"'),
     "姓名如实标"),
    ("密码编辑时也变成必填",
     SCREEN, lambda s: s.replace("required = vm.editing == null,", "required = true,", 1),
     "新建时才是必填"),
    ("密码标签只有一种说法",
     SCREEN, lambda s: s.replace('label = if (vm.editing == null) "初始密码" else "重置密码",', 'label = "密码",'),
     "密码标签分新建"),
    ("密码空值提示只有一种说法",
     SCREEN, lambda s: s.replace('placeholder = if (vm.editing == null) "至少 6 位" else "留空就不改",',
                                 'placeholder = "请输入",'),
     "密码空值提示也分两种"),
    ("界面文案里出现「必填」二字",
     SCREEN, lambda s: s.replace('placeholder = "11 位手机号"', 'placeholder = "11 位手机号（必填）"'),
     "界面文案里没有「必填」"),

    # ── 5. 表单的错画在表单里 ────────────────────────────────────────────
    ("VM 里 formError 没了（退回页面级 error）",
     VM, lambda s: s.replace("var formError by mutableStateOf<String?>(null)", "var error2 by mutableStateOf<String?>(null)"),
     "VM 里有 formError"),
    ("表单的错改画成裸 Text（不在共用组件里）",
     SCREEN, lambda s: s.replace("FormErrorLine(vm.formError)",
                                 'Text(vm.formError ?: "", color = MaterialTheme.colorScheme.error)'),
     "画在「保存」正上方"),
    ("手机号格式错的提示改走页面级 error",
     VM, lambda s: s.replace("formError = it" + NL, "error = it" + NL, 1),
     "手机号格式错的提示走 formError"),
    ("保存失败的提示改走页面级 error",
     VM, lambda s: s.replace("formError = toApiException(e).message", "error = toApiException(e).message"),
     "保存失败的提示走 formError"),
    ("进抽屉时不清上一次的错",
     VM, lambda s: gsub(s, r"formError = null\s*\n\s*showSheet = true", "showSheet = true"),
     "进抽屉时清掉上一次的错"),

    # ── 6. 页脚 ──────────────────────────────────────────────────────────
    ("保存键换成浅黄绿底（白字压不住）",
     SCREEN, lambda s: s.replace("containerColor = poolAccent(pool),", "containerColor = Color(0xFF9AA35F),"),
     "保存键是本池的深色底"),
    ("两个键不再同宽同高",
     SCREEN, lambda s: kill(s, "modifier = Modifier.weight(1f).height(48.dp)," + NL, 2),
     "两键同宽同高"),
    ("保存键改回 PrimaryActionButton（字色写死白）",
     SCREEN, lambda s: gsub(s, r"(?<!Outlined)(?<!Text)Button\((\s*\n\s*)onClick = \{ vm\.save\(\) \}",
                            r"PrimaryActionButton(\1onClick = { vm.save() }"),
     "不再用 PrimaryActionButton"),

    # ── 7. 商品可见范围没缩水 ────────────────────────────────────────────
    ("清单又摊回了抽屉里（220dp 的老滚动区回来了）",
     SCREEN, lambda s: s.replace("ProductCheckList(",
                                 "Box(Modifier.heightIn(max = 220.dp)) {" + NL + "                        ProductCheckList(", 1),
     "清单没有摊回抽屉里"),
    ("可见范围那层不再走共用零件（自己拼了一套）",
     SCREEN, lambda s: s.replace("ProductCheckList(", "VisibilityPickList(", 1),
     "清单走共用零件"),
    ("关掉一行与关掉一类说成同一句话",
     SCREEN, lambda s: s.replace(Q + "已单独关掉" + Q, Q + "已关掉" + Q),
     "关掉一行 / 关掉一类在界面上分开说"),
    ("第二层整块没了（定义与调用不再是两处）",
     SCREEN, lambda s: s.replace("ProductVisibilityLayer(", "ProductVisibilityLayerOld(", 1),
     "第二层在"),
    ("两选一退成一档",
     SCREEN, lambda s: s.replace('ScopeChip("只给勾选的"', 'ScopeChip("按分类的"'),
     "两选一还在"),
    ("上一层那一格不再说「实际可见 N 个」",
     SCREEN, lambda s: s.replace("实际可见 ${vm.visibleProductIds().size} 个", "已配置"),
     "上一层那一格就说人话"),
    ("第二层顶上不再给「实际可见 N 个」",
     SCREEN, lambda s: s.replace("实际可见 ${seen.size} 个", "已选"),
     "第二层顶上同样先给"),
    ("看不见商品时数字不再变红",
     SCREEN, lambda s: s.replace("if (seen.isEmpty()) MaterialTheme.colorScheme.error",
                                 "if (false) MaterialTheme.colorScheme.error", 1),
     "一个商品都看不见时数字当场变红"),
    ("锁被拆了（被整类关掉的行也能勾）",
     SCREEN, lambda s: s.replace("rowLocked = { p -> categoryOf(p) in hiddenCats }",
                                 "rowLocked = { p -> false }", 1),
     "被整类关掉的行勾不动"),
    ("判据改成「勾了几个」（只授权分类会被误判成配错）",
     VM, lambda s: s.replace("products.filter { categoryOf(it) in draftAllowCategories || it.id in draftVisible }",
                             "products.filter { it.id in draftVisible }", 1),
     "判据是「他到底看得见几个」"),
    ("保存前不再拦「一个都看不到」",
     VM, lambda s: s.replace("if (seen.isEmpty() && products.isNotEmpty()) {", "if (false) {", 1),
     "保存前就拦住"),
    ("可见范围对谁都生效（不看角色）",
     VM, lambda s: s.replace('editing?.role == "shipper"', 'editing?.role == "driver"', 1),
     "可见范围仍然只对货主/批发商生效"),
    ("可见范围不再只在编辑货主时出现",
     SCREEN, lambda s: s.replace("if (vm.editing != null && vm.visibilityApplies) {", "if (vm.visibilityApplies) {"),
     "只在「编辑一个货主」时出现"),

    # ── 8. 既有口径没被动 ────────────────────────────────────────────────
    ("搜索框退回手拼描边框",
     SCREEN, lambda s: s.replace("SearchField(value = vm.query,", "SoTextField(value = vm.query,"),
     "搜索仍走 SearchField"),
    ("司机卡片的车型 chip 删掉",
     SCREEN, lambda s: kill(s, "MiniChip(driverKindLabel(u.vehicleType), Color(NavBlue))"),
     "车型 chip 还在"),
    ("driverKindLabel 少了一档",
     SCREEN, lambda s: s.replace('"small" -> "小车司机"', '"small" -> "大车司机"'),
     "driverKindLabel 四档没变"),

    # ── 9. 接线：两个闸门、文档、登记簿 ──────────────────────────────────
    ("CONVERTED 里去掉了本页",
     FORM_PANEL, lambda s: s.replace('"ui/dispatcher/UsersManageScreen.kt": (',
                                     '"ui/dispatcher/UsersManageScreen.kt.bak": ('),
     "已登记进 _check_form_panel_style.py 的 CONVERTED"),
    ("描边输入框基线又涨回去",
     BASELINE, lambda s: s.replace("51", "60", 1),
     "全库基线"),
    ("欠账表里又挂回本页",
     SHEET_PAGES, lambda s: s.replace("PENDING_FORMS = {",
                                      "PENDING_FORMS = {" + NL + '    "ui/dispatcher/UsersManageScreen.kt": ("手机号（登录账号）", "还没搬三件套"),', 1),
     "不再挂在 _check_sheet_form_pages.py 的欠账表里"),
    ("规范里删掉「下拉一律」那句",
     DESIGN, lambda s: gsub(s, r"下拉一律", "下拉"),
     "规范里两处依据都还在"),
    ("文档少一节",
     DOC, lambda s: kill(s, "## ⑨"),
     "文档九节齐全"),
    ("登记簿里删掉 CHG-0018 行",
     REGISTRY, lambda s: re.sub(r"^\|\s*.CHG-0018.\s*\|.*\n", "", s, count=1, flags=re.M),
     "登记簿里有 CHG-0018"),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", NL)
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            print("  [SKIP] " + label)
            continue
        try:
            out_txt = mutated.replace("\r\n", NL)
            if crlf:
                out_txt = out_txt.replace(NL, "\r\n")
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print("  [OK] " + label + " → 报红")
        else:
            fails.append(label + f"：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print("  [MISS] " + label + " → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
