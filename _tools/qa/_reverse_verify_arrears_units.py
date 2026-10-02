#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""反向验证：挂账单位页这条红线（_tools/qa/_check_arrears_units.py）真的会红吗？

判据全绿只能证明"现在没问题"，不能证明"出了问题它会喊"。这个脚本把每一种退化
各注入一次（一共 28 条），每次都单独跑一遍判据，要求它**必须报红**，而且报出来的
那句话必须命中我预先写下的关键词 —— 否则就是"这条红线其实没在查这件事"。

为什么这条红线必须反向验证：

- 它查的东西**全是画法与错误归属**（抽屉在不在最上面、图标有没有圈底、表单的错画在哪），
  这些都会"编译通过 + 功能正常"，只有机器盯着才不会悄悄退回去；
- 其中几条最要命的是**静默**退化：「formError 被改回 loadError」会让"一填错整页列表
  全没了"那个被用户骂过的坑复活，而单看代码是看不出问题的；
- 「撤回」最容易被做成安慰按钮（只把行塞回列表、不调后端 restore）——
  这种假撤回比没有更坏，必须由注入来证明判据真的盯着 repo.restoreArrearsUnit。

安全约定：改之前把每个被碰过的文件按**字节**存下来，每条注入跑完都无条件还原，
跑完再逐字节核对一遍。中途异常也不会留下被改过的源码。

用法：python _tools/qa/_reverse_verify_arrears_units.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_arrears_units.py"

NL = chr(10)

#: 被注入的文件（相对仓库根，正斜杠）
SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ArrearsUnitsScreen.kt"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ArrearsUnitsViewModel.kt"
COLOR = "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Color.kt"
FORMROWS = "android/app/src/main/java/com/tapmoay/sorders/ui/common/FormRows.kt"
BACKEND = "backend/app/api/v1/arrears.py"
DELUNDO = "_tools/qa/_check_delete_undo.py"
PANEL = "_tools/qa/_check_form_panel_style.py"
DOC = "docs/changes/CHG-0020.md"
REGISTRY = "docs/changes/README.md"
CLAIM = "docs/AI_WORK_CLAIM.md"


def rep(s: str, old: str, new: str) -> str:
    """把第一处 old 换成 new（找不到就原样返回，让主流程报 SKIP）。"""
    i = s.find(old)
    if i < 0:
        return s
    return s[:i] + new + s[i + len(old):]


def drop_line(s: str, needle: str) -> str:
    """删掉含有 needle 的整行（找不到就原样返回）。"""
    return NL.join(ln for ln in s.split(NL) if needle not in ln)


def cut_block(s: str, marker: str, tail: str):
    """抠出 [marker, tail] 这一块，返回 (剩下的, 切下来的)；找不到就 (s, None)。"""
    i = s.find(marker)
    if i < 0:
        return s, None
    j = s.find(tail, i + len(marker))
    if j < 0:
        return s, None
    j += len(tail)
    return s[:i] + s[j:], s[i:j]


def paste_after(s: str, anchor: str, block: str) -> str:
    """把 block 插在 anchor 之后（找不到 anchor 就原样返回）。"""
    i = s.find(anchor)
    if i < 0:
        return s
    return s[:i + len(anchor)] + block + s[i + len(anchor):]


def swap_card_actions(s: str) -> str:
    """把卡片上那两枚动作调个个儿：编辑跑到左边、删除跑到右边。"""
    d = 'Icons.Default.Delete, "删除", Color(MessageRed), onDelete,'
    e = 'Icons.Default.Edit, "编辑", Color(NavBlue), onEdit,'
    if d not in s or e not in s:
        return s
    return s.replace(d, "@@DEL@@").replace(e, "@@EDIT@@").replace("@@DEL@@", e).replace("@@EDIT@@", d)


def to_pick_row(s: str) -> str:
    """把备注那一行的共用输入行换成选择行（三行输入就只剩两行）。"""
    k = s.find('"备注",')
    if k < 0:
        return s
    i = s.rfind("FormInputRow(", 0, k)
    if i < 0:
        return s
    return s[:i] + "FormPickRow(" + s[i + len("FormInputRow("):]


def move_undo_below_list(s: str) -> str:
    """把撤回行整块搬到列表**下面**（"手边要有撤回"就没了）。"""
    rest, block = cut_block(s, "vm.recentlyDeleted?.let { rd ->", NL + "                    }" + NL)
    if block is None:
        return s
    return paste_after(rest, "item { Spacer(Modifier.height(72.dp)) }", block)


CASES: list[tuple[str, str, object, str]] = [
    # ── 1. 抽屉三件套（规范 :1266-1269）──────────────────────────────
    ("① 抽屉退回居中弹窗",
     SCREEN, lambda s: rep(s, "ModalBottomSheet(onDismissRequest", "AlertDialog(onDismissRequest"),
     "居中弹窗"),
    ("② 抽屉不再拉满（删掉 fillMaxHeight）",
     SCREEN, lambda s: drop_line(s, ".fillMaxHeight()"),
     "抽屉内容拉满"),
    ("③ 抽屉内容不能滚（删掉 verticalScroll）",
     SCREEN, lambda s: drop_line(s, ".verticalScroll(rememberScrollState()),"),
     "抽屉内容能滚"),
    ("④ 抽屉不是拉到最上面（skipPartiallyExpanded 改成 false）",
     SCREEN, lambda s: rep(s, "skipPartiallyExpanded = true", "skipPartiallyExpanded = false"),
     "拉到最上面"),
    ("⑤ 键盘弹起时输入框够不着（删掉 imePadding）",
     SCREEN, lambda s: drop_line(s, ".imePadding()"),
     "键盘弹起时输入框够得着"),
    # ── 2. 白卡分组 + 共用行 ────────────────────────────────────────
    ("⑥ 白卡里冒出描边输入框",
     SCREEN, lambda s: paste_after(s, 'FormGroup(Icons.Default.Business, "挂账单位", Color(ArrearsTangerine)) {',
                                   NL + "                    OutlinedTextField("),
     "描边输入框一处都没有"),
    ("⑦ 三行输入里混进一个选择行",
     SCREEN, to_pick_row,
     "恰好三行共用输入行"),
    ("⑧ 电话行不再过滤非数字",
     SCREEN, lambda s: rep(s, "{ vm.draftPhone = InputRules.phoneInput(it) },", "{ vm.draftPhone = it },"),
     "数字键盘"),
    # ── 3. 表单的错画在抽屉里 ───────────────────────────────────────
    ("⑨ 抽屉里那条 FormErrorLine 被删掉",
     SCREEN, lambda s: drop_line(s, "FormErrorLine(vm.formError)"),
     "表单错的唯一去处"),
    ("⑩ 保存键换成别的颜色",
     SCREEN, lambda s: rep(s, "containerColor = Color(ArrearsTangerine),", "containerColor = Color(NavBlue),"),
     "保存键用的是本页的模块色"),
    # ── 4. 卡片动作（§4.2c）─────────────────────────────────────────
    ("⑪ 编辑与删除换个位置（编辑跑到左边）",
     SCREEN, swap_card_actions,
     "编辑在最右"),
    ("⑫ 两枚圈底动作退回裸 IconButton",
     SCREEN, lambda s: s.replace("CardActionIcon(", "IconButton("),
     "卡片里不再有裸 IconButton"),
    ("⑬ 编辑那枚不再带字",
     SCREEN, lambda s: drop_line(s, 'label = "编辑",'),
     "两枚都带字"),
    ("⑭ 删除不用提示色 MessageRed",
     SCREEN, lambda s: rep(s, 'Icons.Default.Delete, "删除", Color(MessageRed), onDelete,',
                          'Icons.Default.Delete, "删除", MaterialTheme.colorScheme.error, onDelete,'),
     "删除用提示色 MessageRed"),
    # ── 5. 撤回是真能救回来的 ───────────────────────────────────────
    ("⑮ 撤销变成安慰按钮（只把行塞回列表、不调后端）",
     VM, lambda s: rep(s, "container.repo.restoreArrearsUnit(rd.id)", "recentlyDeleted = null"),
     "撤销是真的调后端"),
    ("⑯ 撤回行被搬到列表下面",
     SCREEN, move_undo_below_list,
     "撤回行画在列表头顶"),
    ("⑰ 删空的时候撤回行跟着消失（空状态少一个条件）",
     SCREEN, lambda s: rep(s, "vm.units.isEmpty() && vm.recentlyDeleted == null ->", "vm.units.isEmpty() ->"),
     "删空的时候撤回行还在"),
    ("⑱ 删除失败写成了页面级错误",
     VM, lambda s: rep(s, "actionResult = toApiException(e).message", "loadError = toApiException(e).message"),
     "删除失败如实报后端那句话"),
    # ── 6. 三种错分开（规范 :458-478）───────────────────────────────
    ("⑲ 表单校验的错写进了页面级 loadError",
     VM, lambda s: rep(s, "formError = it", "loadError = it"),
     "loadError 只在 load() 里写"),
    # ── 7. 名字与 token ─────────────────────────────────────────────
    ("⑳ 橙红底上那个字色不再来自 Color.kt",
     COLOR, lambda s: rep(s, "val OnArrearsTangerine = 0xFF2B1200L", "val OnArrearsTangerineX = 0xFF2B1200L"),
     "Color.kt 里的 token"),
    ("㉑ showSheet / showDialog 的名字混回来",
     VM, lambda s: rep(s, "var showSheet by mutableStateOf(false)", "var showDialog by mutableStateOf(false)"),
     "showDialog 这个名字在页面与 VM 里都不剩"),
    # ── 8. 接线：后端、共用件、工具表、三份文档 ─────────────────────
    ("㉒ 后端 restore 端点不见了（撤销无处可调）",
     BACKEND, lambda s: rep(s, '@router.post("/{unit_id}/restore"', '@router.post("/{unit_id}/undelete"'),
     "后端有 restore 端点"),
    ("㉓ 共用件 FormInputRow 的定义没了",
     FORMROWS, lambda s: rep(s, "fun FormInputRow(", "fun FormInputRowX("),
     "共用件还在定义处"),
    ("㉔ 欠账表的上限没有跟着收紧（13 条变回 12 条）",
     DELUNDO, lambda s: rep(s, "EXEMPT_MAX = 11", "EXEMPT_MAX = 12"),
     "上限也跟着收紧到 11"),
    ("㉕ 本页没有登记进表单行单一来源表",
     PANEL, lambda s: drop_line(s, '"ui/dispatcher/ArrearsUnitsScreen.kt"'),
     "本页登记进了"),
    ("㉖ 变更文档缺了第九节",
     DOC, lambda s: rep(s, "## ⑨", "## ⑩"),
     "文档九节齐全"),
    ("㉗ 登记簿里没有 CHG-0020 这一行",
     REGISTRY, lambda s: drop_line(s, "CHG-0020"),
     "登记簿里有 CHG-0020 这一行"),
    ("㉘ 工作声明页上没有这个事项",
      CLAIM, lambda s: rep(s, "**CHG-0020 挂账单位页按设计规范重做**", "**CHG-XXXX 挂账单位页按设计规范重做**"),
     "工作声明页上有"),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    print("== 反向验证：挂账单位页判据（_check_arrears_units.py）==")
    if not CHECK.exists():
        print("❌ 判据脚本都不在：" + str(CHECK))
        return 1

    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过 —— 先把它跑绿再来做反向验证")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _label, rel, _mutate, _expect in CASES})
    missing = [rel for rel in touched if not (ROOT / rel).exists()]
    if missing:
        print("❌ 前提不成立：这几个要被注入的文件不存在 —— " + ", ".join(missing))
        return 1
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    fails: list[str] = []
    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            print("  [SKIP] " + label)
            continue
        try:
            text = mutated.replace("\n", "\r\n") if crlf else mutated
            path.write_bytes(text.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print("  [OK] " + label + " → 报红")
        else:
            fails.append(label + "：注入之后没有按预期报红（退出码 " + str(code)
                         + "，期望关键词「" + expect + "」）")
            print("  [MISS] " + label + " → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        fails.append("还原检查没过（已强制还原）：" + ", ".join(dirty))
        print("❌ 还原检查：" + str(len(dirty)) + " 个文件跑完与运行前不一致（已强制还原）")
    else:
        print("✅ 还原检查：" + str(len(touched)) + " 个被碰过的文件与运行前逐字节一致")

    print(NL + "=" * 60)
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print("✅ " + str(len(CASES)) + " 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
