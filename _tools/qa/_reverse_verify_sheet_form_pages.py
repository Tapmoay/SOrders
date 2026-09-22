"""反向验证：`_tools/qa/_check_sheet_form_pages.py` 那些判据**真的抓得住**吗（2026-09-22）。

## 为什么必须有它
一条"永远绿的检查"等于没有检查（本仓库为此栽过好几次）。这一轮尤其需要：
被判的那两件事**都是"改坏了不会有任何报错"的类型** ——
抽屉底色从 token 上脱钩、表单里又写回一个描边输入框，两样都能编译过、
真机上"看着也能用"，只有翻页面才发现。

## 手法（与 `_reverse_verify_profile_page.py` 同一套，不另立一套）
对每个注入点：**先把文件按字节备份** → 注入 → 跑红线（期望非零退出**且**命中指定的判据标签）
→ **按字节还原** → 校验 sha256 与备份一致。
⛔ 全程不碰 `git checkout --`（那会把别的会话未提交的改动一起抹掉，实测发生过）。

## 两条特别挑出来的注入
- **⑨ 把 `containerColor` 传在参数表的最后**：判据如果写成 `ModalBottomSheet\\([^)]*containerColor`，
  碰到实参里第一个 `)`（`rememberModalBottomSheetState(...)`）就停了 —— 这种写法正好逃掉。
  这条注入就是钉住"判据是按**括号配平**取实参的"。
- **⑩⑪ 动作的左右位**：判据写的是"**第一个**动作是删除、**最后一个**动作是编辑"，
  而不是"删除的下标小于编辑"（后者只要左栏还留着一个删除就永远成立，等于没判）。

用法：
    python _tools/qa/_reverse_verify_sheet_form_pages.py          # 全部跑
    python _tools/qa/_reverse_verify_sheet_form_pages.py --list   # 只列注入点
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
CHECK = ROOT / "_tools" / "qa" / "_check_sheet_form_pages.py"
A = "android/app/src/main/java/com/tapmoay/sorders/"

# (说明, 相对路径, 锚点, 替换成, 期望哪条判据报红)
#
# ⚠️ 「期望」写的是**判据标签的开头**，命中判据是输出里出现 `[!!]   <标签>`——
#    只写标签本身不行：通过时那行也会打出来（`[OK]   <标签>`），等于永远算命中。
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    ("① 抽屉底色改回旧的灰蓝 #EDEFF4（用户点名的那件事回来了）",
     A + "ui/theme/Color.kt",
     "val SheetSurface = Color(0xFFF0F0F0)", "val SheetSurface = Color(0xFFEDEFF4)",
     "SheetSurface 是中性灰"),
    ("② 抽屉刷成纯白（里面的白卡糊在白的面上，「对比」没了）",
     A + "ui/theme/Color.kt",
     "val SheetSurface = Color(0xFFF0F0F0)", "val SheetSurface = Color(0xFFFFFFFF)",
     "SheetSurface 不是纯白"),
    ("③ 为了「对比更强」一路刷到深灰 #D8D8D8（卡看着像贴纸）",
     A + "ui/theme/Color.kt",
     "val SheetSurface = Color(0xFFF0F0F0)", "val SheetSurface = Color(0xFFD8D8D8)",
     "SheetSurface 落在浅灰这一档"),
    ("④ 抹掉「这个颜色管的是哪件事」的证据（M3 那条默认链）—— 下一个人以为可以随手改",
     A + "ui/theme/Color.kt",
     "`BottomSheetDefaults.ContainerColor` → `SheetBottomTokens.DockedContainerColor`",
     "M3 自己的一个默认值",
     "Color.kt 里写着它管的是哪件事"),
    ("⑤ 亮色方案脱钩（指回旧 token，抽屉又变灰蓝，且没有任何报错）",
     A + "ui/theme/Theme.kt",
     "    surfaceContainerLow = SheetSurface,", "    surfaceContainerLow = SurfaceContainerLow,",
     "Theme.kt 亮色方案把 surfaceContainerLow"),
    ("⑥ 暗色也照搬亮色那个值（暗色分层方向是反的，卡片会糊在黑底上）",
     A + "ui/theme/Theme.kt",
     "    surfaceContainerLow = SurfaceContainerLowDark,", "    surfaceContainerLow = SheetSurface,",
     "Theme.kt 暗色方案"),
    ("⑦ 表单里又写回一个描边输入框（线框回来了）",
     A + "ui/dispatcher/AccountManageScreen.kt",
     '            AccountSecretRow(\n                label = "密码",',
     '            OutlinedTextField(value = vm.draftPassword, onValueChange = {})\n'
     '            AccountSecretRow(\n                label = "密码",',
     "AccountManageScreen.kt 里一个描边输入框都没有"),
    ("⑧ 角色改回 chips（未选中带描边＝线框，且打断「标签在左、值在右」的节奏）",
     A + "ui/dispatcher/AccountManageScreen.kt",
     "        SectionCard {\n            ExposedDropdownMenuBox(",
     "        SectionCard {\n"
     '            FilterChip(selected = true, onClick = {}, label = { Text("货主") })\n'
     "            ExposedDropdownMenuBox(",
     "没有 FilterChip"),
    ("⑨ 这一页自己给抽屉定颜色，而且**传在参数表最后**（钉住判据是按括号配平取的实参）",
     A + "ui/dispatcher/AccountManageScreen.kt",
     "            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),",
     "            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),\n"
     "            containerColor = Color(0xFFEDEFF4),",
     "ModalBottomSheet 没有自己传 containerColor"),
    ("⑩ 「编辑」被摆到最左边（用户说的「惯用手在右」反了）",
     A + "ui/dispatcher/AccountManageScreen.kt",
     '            // 左栏：先删除（最不可逆的那个）再停用/启用\n'
     '            AccountAction("删除", Icons.Default.DeleteOutline, Color(MessageRed), onDelete)',
     '            AccountAction("编辑", Icons.Default.Edit, Color(NavBlue), onEdit)\n'
     '            AccountAction("删除", Icons.Default.DeleteOutline, Color(MessageRed), onDelete)',
     "动作行里第一个动作是「删除」"),
    ("⑪ 「编辑」被换掉（右栏那个位置变成删除，两个删除、没有编辑）",
     A + "ui/dispatcher/AccountManageScreen.kt",
     '            AccountAction("编辑", Icons.Default.Edit, Color(NavBlue), onEdit)',
     '            AccountAction("删除", Icons.Default.DeleteOutline, Color(MessageRed), onDelete)',
     "「编辑」是动作行里最后一个动作"),
    ("⑫ 左右两栏之间不再撑开（一排四个动作挤在一起，左右分区看不出来）",
     A + "ui/dispatcher/AccountManageScreen.kt",
     '            Spacer(Modifier.weight(1f))\n'
     '            // 右栏：编辑（惯用手那一侧）\n'
     '            AccountAction("编辑", Icons.Default.Edit, Color(NavBlue), onEdit)',
     '            AccountAction("编辑", Icons.Default.Edit, Color(NavBlue), onEdit)',
     "左右两栏之间有 Spacer(weight 1f)"),
    ("⑬ 手机号长按复制被去掉（换成普通 clickable）",
     A + "ui/dispatcher/AccountManageScreen.kt",
     "                modifier = Modifier.combinedClickable(",
     "                modifier = Modifier.clickable(",
     "手机号长按可复制"),
    ("⑭ 抽屉里不画红字了（校验拦住时用户看不到任何反应）",
     A + "ui/dispatcher/AccountManageScreen.kt",
     "        FormErrorLine(vm.formError)", "        // FormErrorLine(vm.formError)",
     "抽屉里画了 FormErrorLine"),
    ("⑮ 保存失败改回页面级 error（「保存被拦下」变成「整页账号全没了」）",
     A + "ui/dispatcher/AccountManageViewModel.kt",
     "                saveError = toApiException(e).message",
     "                error = toApiException(e).message",
     "保存失败写的是 saveError"),
    ("⑯ 角色那张卡不再是白卡（分组又变成裸 Column）",
     A + "ui/dispatcher/AccountManageScreen.kt",
     "        SectionCard {\n            ExposedDropdownMenuBox(",
     "        Column {\n            ExposedDropdownMenuBox(",
     "抽屉的分组是白卡"),
    # ---- 第二页：运费模板的「新建」（2026-09-22 从弹窗搬进抽屉）----
    ("⑰ 运费模板的「新建」又变回居中弹窗（用户点名在意的就是形态）",
     A + "ui/dispatcher/FreightTemplatesScreen.kt",
     "        ModalBottomSheet(", "        AlertDialog(",
     "新建/编辑走的是 ModalBottomSheet"),
    ("⑱ 抽屉不再拉满（「拉到最上面」那一行被删，抽屉退回半截）",
     A + "ui/dispatcher/FreightTemplatesScreen.kt",
     "            .fillMaxHeight()\n", "",
     "抽屉内容是 fillMaxHeight()"),
    ("⑲ 抽屉退回 M3 默认档（一打开先弹半截，字段多得滚着填）",
     A + "ui/dispatcher/FreightTemplatesScreen.kt",
     "rememberModalBottomSheetState(skipPartiallyExpanded = true)",
     "rememberModalBottomSheetState()",
     "抽屉一打开就展开到底"),
    ("⑳ 运费模板里又写回一个描边输入框（线框回来了）",
     A + "ui/dispatcher/FreightTemplatesScreen.kt",
     '            FormInputRow(\n                label = "价目名",',
     '            OutlinedTextField(value = vm.draftPriceName, onValueChange = {})\n'
     '            FormInputRow(\n                label = "价目名",',
     "FreightTemplatesScreen.kt 里一个描边输入框都没有"),
    ("㉑ 抽屉里的红字又不画了（校验拦住时用户看不到任何反应）",
     A + "ui/dispatcher/FreightTemplatesScreen.kt",
     "        FormErrorLine(vm.formError)", "        // FormErrorLine(vm.formError)",
     "运费模板抽屉里画了 FormErrorLine"),
    ("㉒ 运费模板保存失败改回页面级 error（那句话落到抽屉背后，＝点保存没反应）",
     A + "ui/dispatcher/FreightTemplatesViewModel.kt",
     "                formError = toApiException(e).message",
     "                error = toApiException(e).message",
     "VM 的校验/保存失败写的是 formError"),
    ("㉓ 运费模板的分组不再是白卡（备注那张又变成裸 Column）",
     A + "ui/dispatcher/FreightTemplatesScreen.kt",
     '        FormGroup(icon = Icons.Default.Notes, title = "备注", '
     'tint = MaterialTheme.colorScheme.outline) {',
     "        Column {",
     "分组是白卡"),
    ("㉔ 账户卡的动作只剩一个图标（把「文字」丢了 —— 用户要的是「圈一下 + 有字」）",
     A + "ui/dispatcher/AccountManageScreen.kt",
     "    label = label,\n", "",
     "卡片上的动作是「圈底图标 + 文字」"),
    ("㉕ 运费模板的三个动作不再挂在底栏（`FreightBottomBar` 那一行被摘掉）",
     A + "ui/dispatcher/FreightTemplatesScreen.kt",
     "            FreightBottomBar(\n", "            // FreightBottomBar(\n",
     "三个动作在底栏三格里"),
    ("㉖ 底栏中间的主操作不再是语义色圆钮（换成描边按钮）",
     A + "ui/dispatcher/FreightTemplatesScreen.kt",
     "                FilledIconButton(\n", "                OutlinedButton(\n",
     "中间是**语义色圆钮**"),
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
