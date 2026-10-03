#!/usr/bin/env python
"""车辆管理页（新增 / 编辑抽屉的表单）按设计规范重做的机器判据 —— CHG-0017 第 2 批。

盯住四件事：

1. 分组一律白卡（规范 §5.0）：四个 FormGroup（车辆 / 车身与属性 / 司机与状态 / 分类），
   行一律走 ui/common/FormRows.kt 那一套 —— 这一页的 OutlinedTextField 必须是 0。
2. 下拉不许用点选 chips 替代（规范 §5 :1377）：车型与车身型式都是「从固定取值里选一个」，
   必须 ExposedDropdownMenuBox + FormPickRow(menuAnchor)；本页 PickChip 归零。
3. 属性项的量纲必须留在标签上：attrTitle(f, vm.draftBody)；一项一行（chunked(2) 不许回来）；
   换型式必须走 vm.setBody(k)（它会把新型式没有的项从草稿里剔掉并说出来）。
4. 钱与错处的画法：保存键的字色必须是深橄榄 OnDriverLime（黄绿底白字只有约 1.4:1）、
   表单错走 FormErrorLine 且全页只画一处（规范 §4.8 表单的错画在表单里）、
   车牌必填画红星而不是写进标签。

为什么这些必须由机器盯着：

- 「分组一律白卡」是跨文件性质：白卡只是 SectionCard 的用法，谁都能在任意一页再手写一遍
  描边输入框 —— 编译不报错、界面照样能用，只有用户看屏幕时才发现两页不是一个东西；
- 「下拉 vs chips」这类是形态性质，审代码时最容易被「顺手改一下」破坏；
- 保存键字色是对比度：白字与深橄榄在代码里都合法，只有真机上才看得出来
  （本批修的正是 CHG-0016 留下的那一处 1.4:1）。

R4-BOUNDARY-JUSTIFICATION: 这条判据不下沉到任何一层边界，因为被查的四件事都是画法：
分组是不是白卡、选取器用下拉还是 chips、量纲写在标签还是占位符、按钮的字用什么色 ——
后端契约、领域类型、权限模型里都没有它们的位置（后端不知道抽屉长什么样，也不该知道）。
反向说：把 FormGroup 抽进 ui/common/ 也不能让任何一条边界去承担「这一页必须用白卡」，
因为手写一个描边输入框不会调用任何一层，边界根本看不见它。

用法：python _tools/qa/_check_vehicle_form.py  （--list 打一份人读清单）
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
VEHICLE = AND / "ui/dispatcher/VehicleManageScreen.kt"
FORMS = AND / "ui/common/FormRows.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_vehicle_form.py"
FORM_PANEL = ROOT / "_tools/qa/_check_form_panel_style.py"
SHEET_PAGES = ROOT / "_tools/qa/_check_sheet_form_pages.py"
BASELINE = ROOT / "_tools/qa/_form_panel_baseline.txt"
DOC = ROOT / "docs/changes/CHG-0017.md"
REGISTRY = ROOT / "docs/changes/README.md"

#: 源码下限（路径变了 / 文件被截断时不许安静全绿）
MIN_VEHICLE_CHARS = 30000
#: OutlinedTextField 的全库基线（本批 58 → 56，只许再降）
MAX_BASELINE = 56
#: 这一页要用的共用行（定义只有一份：ui/common/FormRows.kt）
ROW_KINDS = ["FormInputRow", "FormPickRow", "FormSwitchRow", "FormRow"]
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


def baseline_value() -> int:
    """基线文件第一行是数字，后面是注释（只许减不许增）。"""
    m = re.search(r"^(\d+)\s*$", read(BASELINE), re.M)
    return int(m.group(1)) if m else -1


def main() -> int:
    c = Checker()
    vehicle = strip_comments(read(VEHICLE))
    forms = read(FORMS)

    # ── 0. 反空转 ────────────────────────────────────────────────────────
    c.section("0. 反空转（扫描规则被改坏时必须先喊）")
    c.ok(f"车辆管理页去掉注释后 {len(vehicle)} 字符（下限 {MIN_VEHICLE_CHARS}）",
         len(vehicle) >= MIN_VEHICLE_CHARS, "路径变了或文件被截断了？")
    c.ok("共用行还在唯一定义处（ui/common/FormRows.kt）",
         all(f"fun {k}(" in forms for k in ROW_KINDS),
         "没有 FormRows 的话这一页几组断言会空过")

    # ── 1. 四个白卡分组 ──────────────────────────────────────────────────
    c.section("1. 分组一律白卡（规范 §5.0）：四个 FormGroup + 卡外的组标题")
    groups = calls(vehicle, "FormGroup(")
    c.ok(f"白卡分组恰好四个（实际 {len(groups)} 个）", len(groups) == 4,
         "多了少了都说明分组结构被改过（第 4 组「分类」是 FEAT-0010 加的）")
    want = [("车辆", "LocalShipping", "Color(DriverLime)"),
            ("车身与属性", "Straighten", "Color(DriverLime)"),
            ("司机与状态", "Person", "Color(NavBlue)"),
            # 分类那一组（FEAT-0010）：底色与「车辆」「车身与属性」同一族（都是车辆域）。
            ("分类", "Folder", "Color(DriverLime)")]
    for title, icon, tint in want:
        hit = [g for g in groups if f"title = {Q}{title}{Q}" in g and f"tint = {tint}" in g]
        c.ok(f"分组「{title}」在、底色 {tint}、图标 {icon}",
             len(hit) == 1 and f"icon = Icons.Default.{icon}" in hit[0],
             "组标题、底色、图标是规范那张表定死的三样")
    gbodies = bodies(vehicle, "FormGroup(")
    for k in ROW_KINDS:
        c.ok(f"分组里用的是共用行 {k}", any(f"{k}(" in b for b in gbodies),
             "白卡里手写行 = 又出现第二种画法")

    # ── 2. 选取器一律下拉 ────────────────────────────────────────────────
    c.section("2. 选取器一律下拉（规范 §5 :1377）：两个下拉都锚在共用行上")
    c.ok("本页不再有点选 chips（PickChip( 归零）", "PickChip(" not in vehicle,
         "规范点名：不要用点选 chips 替代下拉")
    c.ok(f"下拉容器恰好两个（实际 {vehicle.count('ExposedDropdownMenuBox(')} 个）",
         vehicle.count("ExposedDropdownMenuBox(") == 2)
    c.ok(f"两个下拉都锚在共用行上（menuAnchor 实际 {vehicle.count('Modifier.menuAnchor()')} 处）",
         vehicle.count("Modifier.menuAnchor()") == 2,
         "没有 menuAnchor 就没有「点整行弹候选」这个形态")
    c.ok("候选来自共用取值表（VEHICLE_TYPES / BODY_CHOICES）",
         "VEHICLE_TYPES.forEach" in vehicle and "BODY_CHOICES.forEach" in vehicle,
         "自己再写一份候选 = 第二套口径")
    c.ok("车型下拉写回 vm.draftType", "vm.draftType = k" in vehicle)
    c.ok("车身型式下拉走 vm.setBody(k)（换型式要剔掉新型式没有的项）",
         "vm.setBody(k)" in vehicle and "vm.draftBody = k" not in vehicle,
         "直接给草稿赋值 = 新型式没有的项留在草稿里，保存时才炸")

    # ── 3. 属性行 ───────────────────────────────────────────────────────
    c.section("3. 属性行：一项一行、量纲在标签上、按型式过滤")
    c.ok("属性行按型式过滤（attrsFor(vm.draftBody)）", "attrsFor(vm.draftBody)" in vehicle)
    c.ok("标签带量纲（attrTitle(f, vm.draftBody)）",
         "attrTitle(f, vm.draftBody)" in vehicle,
         "不带单位的 4 与 400 在界面上都像是对的")
    c.ok("数字键盘按字段类型分（Number / Decimal）",
         "keyboardType = if (f.integer) KeyboardType.Number else KeyboardType.Decimal" in vehicle)
    c.ok("不再两列一行（chunked(2) 不许回来）", "chunked(2)" not in vehicle,
         "半栏宽塞不下「净重(吨)」+ 右边一个数，真机上会把标签挤成两行")
    c.ok(f"输入行恰好两处（车牌 + 属性行模板，实际 {len(calls(vehicle, 'FormInputRow('))} 处）",
         len(calls(vehicle, "FormInputRow(")) == 2)
    c.ok("空值说清楚是「没量过就留空」", "没量过就留空" in vehicle)

    # ── 4. 必填与错误 ───────────────────────────────────────────────────
    c.section("4. 必填画红星、错画在表单里（规范 §4.8）")
    plate = [a for a in calls(vehicle, "FormInputRow(") if f"label = {Q}车牌号{Q}" in a]
    c.ok("车牌那一行在、走 required（红星）",
         len(plate) == 1 and "required = true" in plate[0],
         "车牌是这一屏唯一必填（VM 的 save() 第一件事就是拦空车牌）")
    c.ok("界面文案里没有「必填」二字", "必填" not in vehicle, "必填画红星，不写进标签文字")
    c.ok("表单的错画在表单里（FormErrorLine(vm.sheetError)）",
         "FormErrorLine(vm.sheetError)" in vehicle)
    c.ok(f"vm.sheetError 全页只画一处（实际 {vehicle.count('vm.sheetError')} 处）",
         vehicle.count("vm.sheetError") == 1,
         "页面级错误会把整份列表抹掉，而这一页的列表就在抽屉底下")

    # ── 5. 页脚的字色 ───────────────────────────────────────────────────
    c.section("5. 页脚：黄绿底的字必须是深橄榄（8:1 对 1.4:1）")
    save = [a for a in calls(vehicle, "Button(") if "containerColor = VehicleAccent" in a]
    c.ok("保存键是显式 Button 且 containerColor = VehicleAccent", len(save) == 1)
    c.ok("保存键的字色是 Color(OnDriverLime)（黄绿底白字只有约 1.4:1）",
         len(save) == 1 and "contentColor = Color(OnDriverLime)" in save[0])
    c.ok("不再走 PrimaryActionButton（它把字色写死成白）",
         "PrimaryActionButton(" not in vehicle)
    c.ok("取消键在（OutlinedButton + Text(取消)）",
         len(calls(vehicle, "OutlinedButton(")) == 1 and f"Text({Q}取消{Q})" in vehicle)
    c.ok(f"两键同宽同高（weight(1f).height(48.dp) 实际 {vehicle.count('Modifier.weight(1f).height(48.dp)')} 处）",
         vehicle.count("Modifier.weight(1f).height(48.dp)") == 2)

    # ── 6. 抽屉三件套 ───────────────────────────────────────────────────
    c.section("6. 抽屉：撑满 + 可滚 + 键盘顶起 + 组间同距")
    c.ok("抽屉体 fillMaxWidth().fillMaxHeight()（大屏上不许半截）",
         ".fillMaxWidth()" in vehicle and ".fillMaxHeight()" in vehicle)
    c.ok("可滚动 + 键盘顶起（verticalScroll + imePadding）",
         "verticalScroll(rememberScrollState())" in vehicle and "imePadding()" in vehicle)
    c.ok("组间统一 14dp", "verticalArrangement = Arrangement.spacedBy(14.dp)" in vehicle)
    c.ok("底部留 24dp（最后一行不贴手势条）", "Spacer(Modifier.height(24.dp))" in vehicle)

    # ── 7. 既有约束没被踩坏 ─────────────────────────────────────────────
    c.section("7. 既有约束：白卡不许被描边框顶回去、搜索框 / 计费口径 / 只停用不删除")
    c.ok("本页 OutlinedTextField 是 0（规范 §5.0）", "OutlinedTextField" not in vehicle)
    c.ok(f"三个搜索框仍走 SearchField（实际 {len(re.findall(r'(?<!fun )SearchField[(]', vehicle))} 个）",
         len(re.findall(r"(?<!fun )SearchField[(]", vehicle)) == 3)
    c.ok("车型取值表仍是计费口径那三档",
         f"internal val VEHICLE_TYPES = listOf({Q}trailer{Q} to {Q}挂车{Q}, "
         f"{Q}large{Q} to {Q}大货车{Q}, {Q}small{Q} to {Q}小货车{Q})" in vehicle)
    c.ok("载重 / 容积仍由 capacityText 画", "capacityText(v.attrs)" in vehicle)
    c.ok("仍然只停用、不删除（不出现 repo.delete）", "repo.delete" not in vehicle)

    # ── 8. 接线 ─────────────────────────────────────────────────────────
    c.section("8. 接线：反验脚本、两个闸门、文档九节、登记簿")
    c.ok("反向验证脚本在（_tools/qa/_reverse_verify_vehicle_form.py）", REVERSE.exists(),
         "没有反向验证的判据＝没人证明它真的会红")
    c.ok("本页已登记进 _check_form_panel_style.py 的 CONVERTED",
         f"ui/dispatcher/VehicleManageScreen.kt{Q}: (" in read(FORM_PANEL),
         "登记进 CONVERTED 才会被「OutlinedTextField 必须 0」钉住")
    base = baseline_value()
    c.ok(f"OutlinedTextField 全库基线 {base}（本批 58 → 56，只许再降）",
         base >= 0 and base <= MAX_BASELINE)
    c.ok("本页不再挂在 _check_sheet_form_pages.py 的欠账表里",
         "VehicleManageScreen.kt" not in read(SHEET_PAGES),
         "欠账表里留着它 = 那条豁免永远空转")
    c.ok("规范里那条「下拉一律」还在", "下拉一律" in read(DESIGN), "判据的依据被删了")
    doc = read(DOC) if DOC.exists() else ""
    # ⛔ 认的是**标题**（"## ⑨"），不是那个字符：光有「⑨」两个字出现在正文里不算这一节在。
    c.ok("文档九节齐全（docs/changes/CHG-0017.md）",
         all(("## " + s) in doc for s in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")), "文档缺节")
    c.ok("登记簿里有 CHG-0017 这一行（整行，不是一个链接里的字样）",
         bool(re.search(r"^\|\s*[\x60]?CHG-0017[\x60]?\s*\|", read(REGISTRY), re.M)),
         "没登记（别人不知道这个 ID 用掉了）")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：四个白卡分组用共用行、两个选取器都是下拉、"
          f"属性一项一行且量纲在标签上、保存键的字是深橄榄、错画在表单里、既有口径没被动。")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("== 它到底在查什么（车辆管理页抽屉表单 CHG-0017）==")
        print("1. 分组一律白卡：四个 FormGroup（车辆 / 车身与属性 / 司机与状态 / 分类）+ 组内只用共用行")
        print("2. 选取器一律下拉：两个 ExposedDropdownMenuBox + menuAnchor，PickChip 归零，")
        print("   车身型式走 vm.setBody(k)（换型式必须剔掉新型式没有的项）")
        print("3. 属性行：attrsFor(vm.draftBody) 过滤 + attrTitle 带量纲 + 一项一行（chunked(2) 归零）")
        print("4. 必填画红星（required）、界面文案里没有「必填」二字、错走 FormErrorLine 且只画一处")
        print("5. 页脚：保存键字色 Color(OnDriverLime)、不再走 PrimaryActionButton、两键同宽同高")
        print("6. 抽屉三件套：fillMaxHeight + verticalScroll + imePadding + 组间 14dp + 底部 24dp")
        print("7. 既有约束：OutlinedTextField 归零、三个 SearchField、车型取值表、capacityText、只停用不删除")
        print("8. 接线：反验脚本在、CONVERTED 登记、基线降到 56、欠账表已清、文档九节、登记簿有 CHG-0017")
        sys.exit(0)
    sys.exit(main())
