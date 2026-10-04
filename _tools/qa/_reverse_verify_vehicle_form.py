# -*- coding: utf-8 -*-
r"""反向验证「车辆管理页抽屉表单按规范重做」这条红线**真的会红**（CHG-0017，2026-10-03）。

## 为什么这条要反向验证
本批判据查的四件事，每一件都有自己典型的失效方式，而且**都不影响编译**：

1. 分组一律白卡（规范 §5.0）：白卡只是 SectionCard 的用法，谁都能在任意一页再手写一遍
   描边输入框 —— 编译照样过、界面照样能用，只有用户看屏幕时才发现两页不是一个东西。
2. 选取器用下拉还是点选 chips（规范 §5 :1377）：这是**形态**，审代码时最容易被「顺手改一下」破坏。
3. 属性项的量纲写在标签上还是靠占位符：4 与 400 在界面上都像是对的，只有回头看账才发现差 100 倍。
4. 保存键的字色（黄绿底白字只有约 1.4:1）：两种写法在代码里都合法，只有真机看得出来 ——
   本批修的正是 CHG-0016 留下的那一处。

⚠️ 快照 / 还原按**字节**做，跑完逐字节核对（本项目栽过「注入把 bug 留在源码里」）。

用法：python _tools/qa/_reverse_verify_vehicle_form.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_vehicle_form.py"

AND = "android/app/src/main/java/com/tapmoay/sorders"
VEHICLE = AND + "/ui/dispatcher/VehicleManageScreen.kt"
FORM_PANEL = "_tools/qa/_check_form_panel_style.py"
SHEET_PAGES = "_tools/qa/_check_sheet_form_pages.py"
DOC = "docs/changes/CHG-0017.md"
REGISTRY = "docs/changes/README.md"

NL = chr(10)
BT = chr(96)  # 反引号（本文件里直接写反引号会把外面的模板串截断，一律用这个拼）
Q = chr(34)


def drop_line(s: str, needle: str) -> str:
    """整行删掉（表格行、单行声明）。"""
    return NL.join(ln for ln in s.split(NL) if needle not in ln)


def recolor_save(s: str) -> str:
    """只改**保存键**的字色 —— 黄绿在别处（新增车 FAB :333-334）也有一处 contentColor，不能误伤。

    ⛔ 用 rfind：新增车 FAB :333-334 与保存键 :771-772 长得一模一样，find 会先撞上 FAB，
    那样这条注入就变成「验 FAB」而放过保存键（第一次跑就是这么 MISS 的）。
    """
    i = s.rfind("containerColor = VehicleAccent,")
    if i < 0:
        return s
    j = s.find("Color(OnDriverLime)", i)
    if j < 0:
        return s
    return s[:j] + "Color.White" + s[j + len("Color(OnDriverLime)"):]


CASES: list[tuple[str, str, object, str]] = [
    (
        "① 车牌那一行退回描边输入框（白卡分组又被顶回一堆矩形框）",
        VEHICLE,
        lambda s: s.replace("FormInputRow(", "OutlinedTextField(", 1),
        "OutlinedTextField",
    ),
    (
        "② 少一个白卡分组（司机那一组退回 SectionCard 手拼）",
        VEHICLE,
        lambda s: s.replace(
            "FormGroup(icon = Icons.Default.Person", "SectionCard(icon = Icons.Default.Person", 1
        ),
        "白卡分组恰好五个",
    ),
    (
        "③ 组标题被改（两页叫法不一致，用户要找的东西换名字了）",
        VEHICLE,
        lambda s: s.replace("title = " + Q + "车辆" + Q + ", tint", "title = " + Q + "车辆信息" + Q + ", tint", 1),
        "分组「车辆」在",
    ),
    (
        "④ 司机那一组借了黄绿（同一屏两个语义共用一个色）",
        VEHICLE,
        lambda s: s.replace("title = " + Q + "司机与状态" + Q + ", tint = Color(NavBlue)",
                            "title = " + Q + "司机与状态" + Q + ", tint = Color(DriverLime)", 1),
        "分组「司机与状态」在",
    ),
    (
        "⑤ 点选 chips 又回到这一页（规范 §5 点名不许用它替代下拉）",
        VEHICLE,
        lambda s: s.replace(
            "ExposedDropdownMenuBox(expanded = typeMenu",
            "PickChip(text = " + Q + "小货车" + Q + ", selected = true, onClick = {})" + NL
            + "                ExposedDropdownMenuBox(expanded = typeMenu",
            1,
        ),
        "PickChip",
    ),
    (
        "⑥ 下拉不再锚在共用行上（menuAnchor 被摘掉）",
        VEHICLE,
        lambda s: s.replace("modifier = Modifier.menuAnchor(),", "", 1),
        "menuAnchor",
    ),
    (
        "⑦ 车型候选就地写死（第二套口径，改一处漏一处）",
        VEHICLE,
        lambda s: s.replace(
            "VEHICLE_TYPES.forEach",
            "listOf(" + Q + "small" + Q + " to " + Q + "小货车" + Q + ").forEach",
            1,
        ),
        "候选来自共用取值表",
    ),
    (
        "⑧ 车身型式下拉直接给草稿赋值（新型式没有的项留在草稿里，保存时才炸）",
        VEHICLE,
        lambda s: s.replace("vm.setBody(k)", "vm.draftBody = k", 1),
        "setBody",
    ),
    (
        "⑨ 属性不再按型式过滤（平板车也让你填容积）",
        VEHICLE,
        lambda s: s.replace("attrsFor(vm.draftBody).forEach", "VEHICLE_ATTR_FIELDS.forEach", 1),
        "按型式过滤",
    ),
    (
        "⑩ 标签丢了量纲（4 与 400 在界面上都像是对的）",
        VEHICLE,
        lambda s: s.replace("attrTitle(f, vm.draftBody)", "f.label", 1),
        "量纲",
    ),
    (
        "⑪ 属性退回两列一行（半栏宽把「净重(吨)」挤成两行）",
        VEHICLE,
        lambda s: s.replace(
            "attrsFor(vm.draftBody).forEach { f ->",
            "attrsFor(vm.draftBody).chunked(2).forEach { pair ->",
            1,
        ),
        "chunked",
    ),
    (
        "⑫ 车牌必填写进标签文字（不再画红星）",
        VEHICLE,
        lambda s: drop_line(
            s.replace("label = " + Q + "车牌号" + Q + ",", "label = " + Q + "车牌号（必填）" + Q + ",", 1),
            "required = true,",
        ),
        "required",
    ),
    (
        "⑬ 保存键退回 PrimaryActionButton（它把字色写死成白）",
        VEHICLE,
        lambda s: s.replace("Button(", "PrimaryActionButton("),
        "PrimaryActionButton",
    ),
    (
        "⑭ 保存键的字色改回白（黄绿底白字只有约 1.4:1）",
        VEHICLE,
        recolor_save,
        "OnDriverLime",
    ),
    (
        "⑮ 表单的错改成裸 Text（不再走 FormErrorLine）",
        VEHICLE,
        lambda s: s.replace(
            "FormErrorLine(vm.sheetError)",
            "Text(vm.sheetError ?: " + Q + Q + ", style = MaterialTheme.typography.bodySmall)",
            1,
        ),
        "FormErrorLine",
    ),
    (
        "⑯ 抽屉不再撑满（大屏上只剩半截）",
        VEHICLE,
        lambda s: drop_line(s, ".fillMaxHeight()"),
        "fillMaxHeight",
    ),
    (
        "⑰ 三个搜索框退回 SoTextField（同一件事两种画法）",
        VEHICLE,
        lambda s: s.replace("SearchField(", "SoTextField("),
        "SearchField",
    ),
    (
        "⑱ 车型取值表被改（那是计费口径：挂车按件、其余按月）",
        VEHICLE,
        lambda s: s.replace(Q + "large" + Q + " to " + Q + "大货车" + Q,
                            Q + "large" + Q + " to " + Q + "中货车" + Q, 1),
        "车型取值表",
    ),
    (
        "⑲ 属性行不再按字段类型分键盘（整吨数与米数共用一个键盘）",
        VEHICLE,
        lambda s: s.replace(
            "keyboardType = if (f.integer) KeyboardType.Number else KeyboardType.Decimal",
            "keyboardType = KeyboardType.Number",
            1,
        ),
        "数字键盘按字段类型分",
    ),
    (
        "⑳ 共用行被换成手写的开关（白卡里出现第二种行）",
        VEHICLE,
        lambda s: s.replace("FormSwitchRow(", "Switch(", 1),
        "共用行 FormSwitchRow",
    ),
    (
        "㉑ 卡片不再用 capacityText（自己拼载重 / 容积文字）",
        VEHICLE,
        lambda s: drop_line(s, "val capacity = capacityText(v.attrs)"),
        "capacityText",
    ),
    (
        "㉒ 又出现删除（车牌会留在记账 / 油耗的历史里）",
        VEHICLE,
        lambda s: s + NL + "private fun injected(x: Any) { repo.delete(x) }" + NL,
        "只停用",
    ),
    (
        "㉓ 抽屉不再被键盘顶起（imePadding 被摘掉）",
        VEHICLE,
        lambda s: drop_line(s, ".imePadding()"),
        "imePadding",
    ),
    (
        "㉔ 组间距被改（每页一个样）",
        VEHICLE,
        lambda s: drop_line(s, "verticalArrangement = Arrangement.spacedBy(14.dp),"),
        "14dp",
    ),
    (
        "㉕ 空值提示被换成没有信息量的「请输入」",
        VEHICLE,
        lambda s: s.replace("placeholder = " + Q + "没量过就留空" + Q + ",",
                            "placeholder = " + Q + "请输入" + Q + ",", 1),
        "没量过",
    ),
    (
        "㉖ 这一页从 CONVERTED 撤出（描边输入框的闸门不再管它）",
        FORM_PANEL,
        lambda s: s.replace(
            Q + "ui/dispatcher/VehicleManageScreen.kt" + Q + ": (",
            Q + "ui/dispatcher/VehicleManageScreen.kt.bak" + Q + ": (",
            1,
        ),
        "CONVERTED",
    ),
    (
        "㉗ 这一页又挂回欠账表（那条豁免永远空转）",
        SHEET_PAGES,
        lambda s: s + NL + "# 故意写一次 VehicleManageScreen.kt" + NL,
        "欠账表",
    ),
    (
        "㉘ 登记簿里 CHG-0017 那一行被撤",
        REGISTRY,
        lambda s: drop_line(s, "| " + BT + "CHG-0017" + BT + " |"),
        "没登记",
    ),
    (
        "㉙ 文档少一节（九节是 _check_dev_spec 与本判据共同的底线）",
        DOC,
        lambda s: s.replace("## ⑨", "", 1),
        "文档缺节",
    ),
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
