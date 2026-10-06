#!/usr/bin/env python
"""账号管理页（新增 / 编辑账号：从 AlertDialog 搬进抽屉）按设计规范重做的机器判据 —— CHG-0018。

盯住五件事：

1. 表单不再塞进弹窗（规范 :762-763「表单带选择器时用单独一页，不要塞进 AlertDialog」）：
   这一页有车型、计费规则两个选择器 + 一个商品可见范围入口（点进去是第二层整屏清单），弹窗装不下（旧代码自己写着
   「字段叠起来在小屏上会把「保存」顶出屏幕」）。现在必须是 ModalBottomSheet + 三件套
   （fillMaxHeight + verticalScroll + imePadding），开关叫 showSheet、关它走 closeSheet()。
2. 分组一律白卡（规范 §5.0）：四个 FormGroup（账号 / 车辆与计费 / 商品可见范围 / 分类），
   行一律走 ui/common/FormRows.kt 那一套 —— 这一页的 OutlinedTextField 必须是 0。
3. 选取器一律下拉（规范 :1377）：车型与计费规则必须 ExposedDropdownMenuBox + FormPickRow(menuAnchor)。
   ⛔ 计费规则的标签「计费规则（他怎么算钱就看这一项）」是另一条判据的锚点
   （_check_freight_pricing.py:285「只剩这一个入口」），必须原样留着。
4. 表单里的错画在表单里（规范 §4.8 :475）：save() 的校验失败 / 保存失败必须写 vm.formError
   → FormErrorLine 画在「保存」正上方；save() 里**不许**再出现页面级 error = 赋值
   （那种写法会画到抽屉背后：用户看到的是"点保存没反应"，关掉抽屉整页还被 ErrorView 顶掉 —— 这就是本批修的 bug）。
5. 既有口径没被动：搜索仍打服务端（SearchField + vm.query）、司机卡片的车型 chip 还在、
   driverKindLabel 四档不变、商品可见范围那套（两选一 / 入口 + 第二层 / 汇总「实际可见 N 个」/ 配完一个都看不到就拦住）没缩水。

「商品清单」那一套（搜索 / 左分类栏 / 三态「全选这一类」/ 勾选行 / 自己滚 / 不把行藏掉）已经搬进 ui/common/ProductCheckList.kt，
两个页面共用 —— 零件自己的判据在 _tools/qa/_check_product_check_list.py；本脚本第 6 节只钉页面侧的形状（入口 / 第二层 / 汇总 / 拦住）。

为什么这些必须由机器盯着：

- 「弹窗还是抽屉」是形态性质：AlertDialog + 一个自带 scroll 的 Column 能编译、能跑、截图里甚至"看着像表单"，
  只有在小屏上点保存时才知道它坏了；
- 「错画在哪儿」是本批真正的 bug：写 error 还是 formError 都是合法 Kotlin，**没有编译器会拦**，
  而症状（点保存无反应 / 整页被顶掉）只在真机上出现；
- 四个分组的标题 / 图标 / 底色、两个下拉的候选表都是"顺手改一下"就散的形态，审代码时看不出来。

R4-BOUNDARY-JUSTIFICATION: 这条判据不下沉到任何一层边界。被查的五件事全是画法：
用的是弹窗还是抽屉、分组是不是白卡、选取器是下拉还是 chips、错画在表单里还是页面级、
页脚两个键怎么排 —— 后端契约、领域类型、权限模型里都没有它们的位置（后端不知道抽屉长什么样，
也不该知道）。反向说：把 FormGroup / FormErrorLine 抽进 ui/common/ 也不能让任何一条边界去承担
「这一页必须用抽屉」，因为那只是"抽屉没搬"或"错写错了变量"，边界根本看不见它。

用法：python _tools/qa/_check_users_form.py  （--list 打一份人读清单）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = AND / "ui/dispatcher/UsersManageScreen.kt"
VM = AND / "ui/dispatcher/UsersManageViewModel.kt"
FORMS = AND / "ui/common/FormRows.kt"
COMPONENTS = AND / "ui/common/Components.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_users_form.py"
PART_CHECK = ROOT / "_tools/qa/_check_product_check_list.py"
PART_REVERSE = ROOT / "_tools/qa/_reverse_verify_product_check_list.py"
FORM_PANEL = ROOT / "_tools/qa/_check_form_panel_style.py"
SHEET_PAGES = ROOT / "_tools/qa/_check_sheet_form_pages.py"
BASELINE = ROOT / "_tools/qa/_form_panel_baseline.txt"
DOC = ROOT / "docs/changes/CHG-0018.md"
REGISTRY = ROOT / "docs/changes/README.md"

#: 源码下限（路径变了 / 文件被截断时不许安静全绿）
MIN_SCREEN_CHARS = 29000
MIN_VM_CHARS = 13000
#: OutlinedTextField 的全库基线（本批 56 → 51，只许再降）
MAX_BASELINE = 51
#: 四个白卡分组（标题 → 必须出现在这一组体里的东西）—— 第 4 组「分类」是 FEAT-0010 加的
#: （账号名册那一格走共用件 CategoryPickRow，是下拉）。
GROUPS = {
    "账号": "FormInputRow(",
    "车辆与计费": "FormPickRow(",
    "商品可见范围": "FormPickRow(",
    "分类": "CategoryPickRow(",
}
Q = chr(34)


def _spans(src: str, name: str) -> list[tuple[str, str]]:
    """所有 name(...) 的 (实参文本, 后面那个尾随 lambda 的体)；跳过 fun 定义、不吃 xxxName( 后缀。"""
    base = name[:-1] if name.endswith("(") else name
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"(?<![A-Za-z0-9_])" + re.escape(base) + r"[(]", src):
        i = src.find("(", m.start())
        depth, end = 0, -1
        for j in range(i, len(src)):
            ch = src[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end < 0:
            continue
        k = end + 1
        while k < len(src) and src[k] in " \t\r\n":
            k += 1
        body = ""
        if k < len(src) and src[k] == "{":
            d = 0
            for j in range(k, len(src)):
                ch = src[j]
                if ch == "{":
                    d += 1
                elif ch == "}":
                    d -= 1
                    if d == 0:
                        body = src[k + 1:j]
                        break
        out.append((src[i + 1:end], body))
    return out


def calls(src: str, name: str) -> list[str]:
    """所有 name(...) 的实参文本。"""
    return [a for a, _b in _spans(src, name)]


def bodies(src: str, name: str) -> list[str]:
    """所有 name(...) 后面那个尾随 lambda 的体（白卡分组里的行就在这里面）。"""
    return [b for _a, b in _spans(src, name)]


def fn_body(src: str, head: str) -> str:
    """抓一个 Kotlin 函数的体：从 head（含）开始做花括号配平。抓不到返回空串。"""
    i = src.find(head)
    if i < 0:
        return ""
    j = src.find("{", i)
    if j < 0:
        return ""
    d = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            d += 1
        elif src[k] == "}":
            d -= 1
            if d == 0:
                return src[j + 1:k]
    return ""


def group_arg(g: str, key: str) -> str:
    """从调用实参里取 key = "值" 的那个值（取不到返回空串）。"""
    m = re.search(re.escape(key) + r"\s*=\s*" + Q + r"([^" + Q + r"]*)" + Q, g)
    return m.group(1) if m else ""


def arg_expr(g: str, key: str) -> str:
    """从调用实参里取 key = <表达式>（到这一层的逗号 / 右括号为止）—— 给 tint / icon 这种非字符串用。"""
    m = re.search(re.escape(key) + r"\s*=\s*", g)
    if not m:
        return ""
    i, depth = m.end(), 0
    out = []
    while i < len(g):
        ch = g[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            break
        out.append(ch)
        i += 1
    return "".join(out).strip()


def baseline_value() -> int:
    """基线文件第一行是数字，后面是注释（只许减不许增）。"""
    m = re.search(r"^(\d+)\s*$", read(BASELINE), re.M)
    return int(m.group(1)) if m else -1


def main() -> int:
    c = Checker()
    screen = strip_comments(read(SCREEN))
    vm = strip_comments(read(VM))

    # ── 0. 反空转 ────────────────────────────────────────────────────────
    c.section("0. 反空转（扫描规则被改坏时必须先喊）")
    c.ok(f"账号管理页去掉注释后 {len(screen)} 字符（下限 {MIN_SCREEN_CHARS}）",
         len(screen) >= MIN_SCREEN_CHARS,
         f"文件被截断 / 路径变了？实测 {len(screen)} 字符")
    c.ok(f"它的 ViewModel 去掉注释后 {len(vm)} 字符（下限 {MIN_VM_CHARS}）",
         len(vm) >= MIN_VM_CHARS, f"实测 {len(vm)} 字符")
    c.ok("共用行还在唯一定义处（ui/common/FormRows.kt）",
         all(f"fun {k}(" in read(FORMS) for k in ("FormGroup", "FormInputRow", "FormPickRow")),
         "定义没了的话下面全在空转")
    c.ok("表单的错还画在共用组件里（Components.kt::FormErrorLine）",
         "fun FormErrorLine(" in read(COMPONENTS), "共用组件没了的话第 5 节在空转")

    # ── 1. 弹窗 → 抽屉（规范 :762-763）────────────────────────────────────
    c.section("1. 不再是弹窗：AlertDialog 归零、抽屉三件套齐")
    c.ok("本页不再有 AlertDialog（表单带选择器时不许塞进弹窗）", "AlertDialog(" not in screen,
         "规范 :762「表单带选择器时用单独一页，不要塞进 AlertDialog」")
    c.ok(f"抽屉恰好一个（实际 {screen.count('ModalBottomSheet(')} 个）",
         screen.count("ModalBottomSheet(") == 1)
    c.ok("抽屉是全展开的（skipPartiallyExpanded = true）",
         "rememberModalBottomSheetState(skipPartiallyExpanded = true)" in screen,
         "用户：「底部抽屉是拉到最上面」")
    c.ok("抽屉体 fillMaxWidth().fillMaxHeight()（大屏上不许半截）",
         re.search(r"\.fillMaxWidth\(\)\s*\.fillMaxHeight\(\)", screen) is not None)
    c.ok("撑满之后接 .padding(horizontal = 16.dp).imePadding()（键盘弹起不盖住正在填的那一行）",
         re.search(r"\.fillMaxHeight\(\)\s*\.padding\(horizontal = 16\.dp\)\s*\.imePadding\(\)",
                   screen) is not None)
    c.ok("能滚（.imePadding() 之后紧接 .verticalScroll(rememberScrollState())）",
         re.search(r"\.imePadding\(\)\s*\.verticalScroll\(rememberScrollState\(\)\)",
                   screen) is not None,
         "字段比一屏高时要够得着保存")
    c.ok("组间统一 14dp", "verticalArrangement = Arrangement.spacedBy(14.dp)" in screen)
    c.ok("底部留 24dp（最后一行不贴手势条）", "Spacer(Modifier.height(24.dp))" in screen)
    c.ok("开关叫 showSheet、不再是 showDialog（旧名多半意味着又变回弹窗了）",
         "showDialog" not in screen and "showDialog" not in vm)
    c.ok("VM 里 showSheet 存在", "var showSheet by mutableStateOf(false)" in vm)
    close = fn_body(vm, "fun closeSheet()")
    c.ok("关抽屉统一走 closeSheet()（右上角 × 与底部「取消」都调它）",
         screen.count("vm.closeSheet()") >= 2
         and "SheetCloseButton(onClick = { vm.closeSheet() })" in screen)
    c.ok("保存途中不许关（closeSheet 里闸门是 acting）",
         "if (!acting) showSheet = false" in close,
         "保存请求在飞的时候被关掉，用户不知道到底存没存上")

    # ── 2. 分组一律白卡（规范 §5.0）──────────────────────────────────────
    c.section("2. 分组一律白卡（规范 §5.0）：四个 FormGroup + 卡外的组标题")
    groups = calls(screen, "FormGroup(")
    gbodies = bodies(screen, "FormGroup(")
    c.ok(f"白卡分组恰好四个（实际 {len(groups)} 个）", len(groups) == 4,
         "账号 / 车辆与计费 / 商品可见范围 / 分类")
    titles = [group_arg(g, "title") for g in groups]
    c.ok(f"四个分组的标题就是这四样（实际 {titles}）", titles == list(GROUPS),
         f"要 {list(GROUPS)}")
    for (title, row), g, b in zip(GROUPS.items(), groups, gbodies):
        c.ok(f"分组「{title}」里用的是 {row}", row in b,
             "白卡分组里的行必须走 ui/common/FormRows.kt 那一套")
    tints = [arg_expr(g, "tint") for g in groups]
    c.ok("账号 / 商品可见范围 / 分类用本池的语义色（poolAccent(pool)）",
         tints[0] == "poolAccent(pool)" and tints[2] == "poolAccent(pool)"
         and tints[3] == "poolAccent(pool)",
         f"实际 {tints}")
    c.ok("「车辆与计费」用黄绿 DriverLime（和车辆管理页同一族的语义色）",
         tints[1] == "Color(DriverLime)", f"实际 {tints[1]}")
    icons = [arg_expr(g, "icon") for g in groups]
    c.ok(f"四个分组的图标（实际 {icons}）",
         icons == ["Icons.Default.Person", "Icons.Default.LocalShipping",
                   "Icons.Default.Visibility", "Icons.Default.Folder"])
    c.ok("商品可见范围那一组自己不再画标题（标题只在卡外画一次；第二层顶栏那个是另一屏）",
         'Text("商品可见范围"' not in gbodies[2]
         and screen.count('title = "商品可见范围"') == 1
         and 'Text("商品可见范围", style = MaterialTheme.typography.titleLarge' in screen,
         "同一个标题两处画 —— 搬进白卡时最容易漏掉的一句；gbodies[2] 就是第三个白卡（可见范围那一组）")

    # ── 3. 选取器一律下拉（规范 :1377）────────────────────────────────────
    c.section("3. 选取器一律下拉（规范 :1377）：两个下拉都锚在共用行上")
    c.ok("本页 OutlinedTextField 是 0（描边框不许回来）", "OutlinedTextField" not in screen)
    c.ok(f"下拉容器恰好两个（实际 {screen.count('ExposedDropdownMenuBox(')} 个）",
         screen.count("ExposedDropdownMenuBox(") == 2)
    c.ok(f"两个下拉都锚在共用行上（menuAnchor 实际 {screen.count('Modifier.menuAnchor()')} 处）",
         screen.count("Modifier.menuAnchor()") == 2,
         "FormPickRow 少了 menuAnchor 就点不开")
    c.ok(f"选取行恰好三处（车型 / 计费规则 / 可见范围入口，实际 {len(calls(screen, 'FormPickRow('))} 处）",
         len(calls(screen, "FormPickRow(")) == 3,
         "多出来的一处 = 有人在抽屉里又手拼了一个入口")
    c.ok("车型候选就是那两档（大车 / 挂车 —— 计费口径的取值表不许扩）",
         'listOf("large" to "大车司机", "trailer" to "挂车司机")' in screen,
         "vehicles.vehicle_type 是计费用的词，取值集合不能加")
    c.ok("车型下拉写回 vm.draftVehicleType", "vm.draftVehicleType = k" in screen)
    c.ok("计费规则第一项是「不挂规则」→ vm.draftRuleId = null",
         'Text("不挂规则")' in screen and "vm.draftRuleId = null" in screen)
    c.ok("规则候选来自 vm.rules 且带后端给的一句话说明",
         "vm.rules.forEach { r ->" in screen and "Text(r.name)" in screen
         and "r.summary," in screen,
         "说明由后端给（和服务端算钱的口径同源），界面不自己拼")
    c.ok("选中规则写回 vm.draftRuleId = r.id", "vm.draftRuleId = r.id" in screen)
    c.ok("⛔ 计费规则的标签原样保留（另一条判据锚着这串字）",
         'label = "计费规则（他怎么算钱就看这一项）"' in screen,
         "_check_freight_pricing.py:285「只剩『计费规则』这一个入口」锚着它")

    # ── 4. 输入行 / 必填 / 键位（规范 §4.8、§4.3）────────────────────────
    c.section("4. 输入行走共用行：三行、必填画红星、手机号按规矩走 InputRules")
    rows = calls(screen, "FormInputRow(")
    c.ok(f"输入行恰好三处（手机号 / 姓名 / 密码，实际 {len(rows)} 处）", len(rows) == 3)
    phone = next((r for r in rows if "手机号" in group_arg(r, "label")), "")
    c.ok("手机号那一行在、走 required（红星）", bool(phone) and "required = true" in phone)
    c.ok("手机号标签仍是「手机号（登录账号）」（它是登录账号，功能上必须说清）",
         group_arg(phone, "label") == "手机号（登录账号）",
         "另一份反向验证脚本的期望关键词就是这一串")
    c.ok("手机号走 InputRules.mobileInput（规则唯一实现在 core/InputRules.kt）",
         "vm.draftPhone = InputRules.mobileInput(it)" in phone,
         "这一处原来什么过滤都没有，同一个 App 里另一页却有 —— 两页两个口径")
    c.ok("手机号键位是 Phone", "keyboardType = KeyboardType.Phone" in phone)
    c.ok("手机号空值提示说清是 11 位", group_arg(phone, "placeholder") == "11 位手机号")
    nm = next((r for r in rows if group_arg(r, "label") == "姓名"), "")
    c.ok("姓名那一行在、且不走手机号过滤（姓名要能写中文）",
         bool(nm) and "InputRules" not in nm,
         "给姓名加数字过滤会把汉字在输入层就丢掉")
    c.ok("姓名如实标「选填」（后端 full_name 默认空串，确实不必填）",
         group_arg(nm, "placeholder") == "选填")
    pwd = next((r for r in rows if "密码" in r), "")
    c.ok("密码那一行在、新建时才是必填（required = vm.editing == null）",
         bool(pwd) and "required = vm.editing == null" in pwd)
    c.ok("密码标签分新建 / 编辑两种说法",
         'label = if (vm.editing == null) "初始密码" else "重置密码"' in pwd)
    c.ok("密码空值提示也分两种（至少 6 位 / 留空就不改）",
         '"至少 6 位" else "留空就不改"' in pwd)
    c.ok("必填只在 save() 里卡 6 位、界面文案里没有「必填」二字",
         "必填" not in screen and 'formError = "初始密码至少 6 位"' in vm,
         "红星就够，别把「必填」写进标签")

    # ── 5. 错画在表单里 + 页脚（本批修的那处 bug）─────────────────────────
    c.section("5. 表单的错画在表单里（规范 §4.8）+ 页脚两键")
    c.ok("VM 里有 formError（表单级），注释里写清了病因",
         "var formError by mutableStateOf<String?>(null)" in vm
         and "FormErrorLine" in read(VM),  # 病因写在 KDoc 里（剥注释后就看不见了）
         "旧写法把它写进页面级 error ⇒ 那句话画在抽屉背后")
    c.ok("表单的错画在「保存」正上方（FormErrorLine(vm.formError)）",
         "FormErrorLine(vm.formError)" in screen)
    c.ok(f"vm.formError 全页只画一处（实际 {screen.count('vm.formError')} 处）",
         screen.count("vm.formError") == 1, "画两处就是同一个错两遍")
    sv = fn_body(vm, "fun save()")
    c.ok("save() 抓到了（抓不到的话下面几条全是空转）", bool(sv))
    c.ok("手机号格式错的提示走 formError",
         re.search(r"InputRules\.mobileError\(draftPhone\.trim\(\)\)\?\.let \{\s*formError = it",
                   sv) is not None)
    c.ok("密码长度错的提示走 formError", 'formError = "初始密码至少 6 位"' in sv)
    c.ok("保存失败的提示走 formError（catch 里）",
         re.search(r"catch \(e: Exception\) \{\s*formError = toApiException\(e\)\.message", sv)
         is not None,
         "写进页面级 error 就会被画到抽屉背后 —— 用户看到的是「点保存没反应」")
    c.ok("⛔ save() 里不再出现页面级 error = 赋值",
         re.search(r"(?<![A-Za-z_])error\s*=", sv) is None,
         "这条是本批的核心：两类错必须分开画（表单里 / 页面级）")
    c.ok("进抽屉时清掉上一次的错（openCreate / openEdit 都清）",
         "formError = null" in fn_body(vm, "fun openCreate()")
         and "formError = null" in fn_body(vm, "fun openEdit("),
         "不清的话上次那条错会跟着新表单出现")
    c.ok("保存前再清一次（只清表单里那条）",
         re.search(r"acting = true\s*(?://[^\n]*\n\s*)*formError = null", sv) is not None)
    c.ok(f"取消键是描边键（OutlinedButton 实际 {screen.count('OutlinedButton(')} 个）",
         screen.count("OutlinedButton(") == 1 and 'Text("取消")' in screen)
    c.ok("取消键也走 closeSheet()", "onClick = { vm.closeSheet() }" in screen)
    c.ok("保存键是本池的深色底 + 白字（这三个深色对比度 ≥ 7:1）",
         "containerColor = poolAccent(pool)" in screen and "contentColor = Color.White" in screen)
    c.ok("poolAccent 仍是那三个深色（司机深橄榄 / 货主深蓝 / 批发商深金）",
         all(v in screen for v in ("0xFF5A6B00", "0xFF0A3168", "0xFF7A5900")),
         "浅色底压白字只有 1.x:1 —— 这三个是「圆底用它 16%、字用它本身」的深色")
    c.ok(f"两键同宽同高（weight(1f).height(48.dp) 实际 {screen.count('Modifier.weight(1f).height(48.dp)')} 处）",
         screen.count("Modifier.weight(1f).height(48.dp)") == 2)
    c.ok("保存中显示「保存中…」（用户知道请求在飞）",
         'Text(if (vm.acting) "保存中…" else "保存")' in screen)
    c.ok("不再用 PrimaryActionButton（它把字色写死成白，本页要跟池色走）",
         "PrimaryActionButton(" not in screen)

    # ── 6. 商品可见范围没缩水 ─────────────────────────────────────────────
    c.section("6. 商品可见范围（货主/批发商）：入口一格 + 第二层整屏清单，没缩水")
    c.ok(f"第二层在（定义 + 一处调用，实际 {screen.count('ProductVisibilityLayer(')} 处）",
         screen.count("ProductVisibilityLayer(") == 2,
         "定义没了 / 调用没了 —— 两种都是这一块消失")
    c.ok("清单没有摊回抽屉里（那一组只剩「可见范围」一格，点它开第二层）",
         'label = "可见范围"' in screen
         and "onClick = { showVisibilityLayer = true }" in screen
         and "heightIn(max = 220.dp)" not in screen,
         "摊回抽屉 = LazyColumn 被塞进 verticalScroll（量成无限高，直接崩）")
    c.ok("两选一还在（全部商品 / 只给勾选的）",
         'ScopeChip("全部商品"' in screen and 'ScopeChip("只给勾选的"' in screen)
    c.ok("上一层那一格就说人话（实际可见 N 个，不是让人自己数勾了几个）",
         "private fun visibilitySummary(" in screen
         and "实际可见 ${vm.visibleProductIds().size} 个" in screen)
    c.ok("第二层顶上同样先给「实际可见 N 个」（与上一层同一套口径）",
         "val seen = vm.visibleProductIds()" in screen and "实际可见 ${seen.size} 个" in screen)
    c.ok("一个商品都看不见时数字当场变红（不用等保存才知道配错了）",
         "if (seen.isEmpty()) MaterialTheme.colorScheme.error" in screen)
    c.ok("判据是「他到底看得见几个」、不是「勾了几个」（只按分类授权是合法的一种）",
         "fun visibleProductIds()" in vm
         and "products.filter { categoryOf(it) in draftAllowCategories || it.id in draftVisible }" in vm,
         "看勾了几个会把「只授权了分类」误判成配错了")
    c.ok("保存前就拦住：这么配他一个商品都看不到（本地先拦一道，与后端同一套判据）",
         "if (seen.isEmpty() && products.isNotEmpty()) {" in vm
         and "他一个商品都看不到" in vm and "选品页会是空的" in vm,
         "交上去只能说明他还没勾，不是他的本意")
    c.ok("关掉一行 / 关掉一类在界面上分开说（不许长一样）",
         '"已单独关掉"' in screen and "这一类已整类关掉" in screen,
         "排除优先于授权 —— 混成一句话，用户不知道该去关谁")
    c.ok("被整类关掉的行勾不动、当场写清原因（不把行藏掉）",
         "rowLocked = { p -> categoryOf(p) in hiddenCats }" in screen
         and "要单独放开，先把这一类打开" in screen,
         "藏起来的商品 = 用户以为它不存在")
    c.ok("清单走共用零件 ui/common/ProductCheckList.kt（它自己那套由别的判据盯着）",
         "ProductCheckList(" in screen and "checkedIds = seen," in screen,
         "两个调用方必须是同一份零件，否则「能复用就复用」又散成两份")
    c.ok("只在「编辑一个货主」时出现（vm.editing != null && vm.visibilityApplies）",
         "if (vm.editing != null && vm.visibilityApplies)" in screen)
    c.ok("可见范围仍然只对货主/批发商生效（visibilityApplies 判 role == shipper）",
         'editing?.role == "shipper"' in vm, "批发商就是高级货主，同一套")

    # ── 7. 既有口径没被动 ────────────────────────────────────────────────
    c.section("7. 既有口径没被动：搜索、司机卡片、车型口径")
    c.ok(f"搜索仍走 SearchField 且打服务端（实际 {len(re.findall(r'(?<!fun )SearchField[(]', screen))} 个）",
         len(re.findall(r"(?<!fun )SearchField[(]", screen)) == 1
         and "value = vm.query" in screen)
    c.ok("司机卡片上的车型 chip 还在",
         "MiniChip(driverKindLabel(u.vehicleType), Color(NavBlue))" in screen)
    c.ok("driverKindLabel 四档没变（三档车型 + 未设置）",
         all(s in screen for s in ('"trailer" -> "挂车司机"', '"small" -> "小车司机"',
                                   '"large" -> "大车司机"', '"未设置车型"')))
    c.ok("本页不出现 repo.delete（账号只停用、不删除）", "repo.delete" not in screen)
    c.ok("池色只有一份定义（poolAccent）", "private fun poolAccent(" in screen)
    c.ok("商品维度批量调价那个抽屉还在（showBatch）",
         "if (vm.showBatch) {" in screen and "BatchPriceSheet(" in screen)

    # ── 8. 接线：反验脚本、两个闸门、文档九节、登记簿 ─────────────────────
    c.section("8. 接线：反验脚本、两个闸门、文档九节、登记簿")
    c.ok("反向验证脚本在（_tools/qa/_reverse_verify_users_form.py）", REVERSE.exists(),
         "没有它的话上面每一条都可能是空转")
    c.ok("清单零件（ui/common/ProductCheckList.kt）自己的判据 ＋ 反验也在",
         PART_CHECK.exists() and PART_REVERSE.exists(),
         "共用零件没人盯 = 两个调用方各自的保证都成了空转")
    c.ok("本页已登记进 _check_form_panel_style.py 的 CONVERTED",
         '"ui/dispatcher/UsersManageScreen.kt": (' in read(FORM_PANEL),
         "改好的页面必须进 CONVERTED，否则它只是这一次碰巧干净")
    base = baseline_value()
    c.ok(f"OutlinedTextField 全库基线 {base}（本批 56 → 51，只许再降）",
         0 <= base <= MAX_BASELINE, f"基线数字没读出来或者是 {base}")
    pending = read(SHEET_PAGES).split("PENDING_FORMS")[1].split("}")[0]
    c.ok("本页不再挂在 _check_sheet_form_pages.py 的欠账表里",
         "UsersManageScreen.kt" not in pending,
         "搬好了就要把 PENDING_FORMS 里那一行删掉，别让它空转")
    c.ok("规范里两处依据都还在（表单带选择器用单独一页 / 下拉一律）",
         "表单带选择器时用单独一页" in read(DESIGN) and "下拉一律" in read(DESIGN),
         "判据的依据被删了")
    doc = read(DOC) if DOC.exists() else ""
    c.ok("文档九节齐全（docs/changes/CHG-0018.md）",
         all(("## " + s) in doc for s in "①②③④⑤⑥⑦⑧⑨"),
         "少了哪一节？① 六问 ② Must Change ③ Boundary ④ Behavior ⑤ Data ⑥ CHG 专章 ⑦ 测试 ⑧ 证据 ⑨ 关闭")
    c.ok("登记簿里有 CHG-0018 这一行（整行，不是一个链接里的字样）",
         re.search(r"^\|\s*`CHG-0018`\s*\|", read(REGISTRY), re.M) is not None,
         "没登记（别人不知道这个 ID 用掉了）")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：表单搬进抽屉（不再是弹窗）、四个白卡分组、两个选取器都是下拉、"
          f"表单的错画在表单里、商品可见范围（入口 + 第二层）没缩水、既有口径没被动。")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("== 它到底在查什么（账号管理页抽屉表单 CHG-0018）==")
        print("1. 不再是弹窗：AlertDialog 归零、ModalBottomSheet ×1、三件套齐、开关叫 showSheet")
        print("2. 分组一律白卡：四个 FormGroup（账号 / 车辆与计费 / 商品可见范围 / 分类）+ 组内只用共用行")
        print("3. 选取器一律下拉：车型与计费规则都 ExposedDropdownMenuBox + menuAnchor；")
        print("   计费规则标签「计费规则（他怎么算钱就看这一项）」是别处判据的锚点，必须原样留着")
        print("4. 输入行：手机号走 InputRules + required 红星、姓名不许加数字过滤、密码新建才必填")
        print("5. 表单的错画在表单里：save() 三类错都走 formError，且不再出现页面级 error =")
        print("6. 页脚：取消走 closeSheet、保存是本池深色底 + 白字、两键同宽同高")
        print("7. 商品可见范围没缩水（入口一格 + 第二层整屏清单：两选一 / 汇总「实际可见 N 个」/")
        print("   关一行≠关一类 / 配完一个都看不到就拦在保存前）；清单零件另有判据 _check_product_check_list.py")
        print("8. 接线：反验脚本在、CONVERTED 登记、基线降到 51、欠账表已清、文档九节、登记簿有 CHG-0018")
    else:
        sys.exit(main())
