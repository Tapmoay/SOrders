"""反向验证：`_tools/qa/_check_profile_page.py` 那些判据**真的抓得住**吗（2026-09-21）。

## 为什么必须有它
一条"永远绿的检查"等于没有检查（本仓库为此栽过好几次）。所以每条新红线都要证明：
**把规矩做坏 → 它当场红**。

## 手法（与 `_reverse_verify_hints.py` 同一套，不另立一套）
对每个注入点：**先把文件按字节备份** → 注入 → 跑红线（期望非零退出**且**命中指定的判据标签）
→ **按字节还原** → 校验 sha256 与备份一致。
⛔ 全程不碰 `git checkout --`（那会把别的会话未提交的改动一起抹掉，实测发生过）。

## 安全措施
1. 注入前先比对"我刚写进去的那份"还在不在：**别人插了一脚就拒绝还原并报错**。
2. 还原后哈希对不上 → 立刻停手并打出文件路径。
3. 注入清单里的锚点都是**普通字符串**（脚本内部 `re.escape`），只有 `re:` 开头才当正则 ——
   与 `_reverse_verify_hints.py` 同一口径。

用法：
    python _tools/qa/_reverse_verify_profile_page.py          # 全部跑
    python _tools/qa/_reverse_verify_profile_page.py --list   # 只列注入点
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
CHECK = ROOT / "_tools" / "qa" / "_check_profile_page.py"
A = "android/app/src/main/java/com/tapmoay/sorders/"

# (说明, 相对路径, 锚点, 替换成, 期望哪条判据报红)
#
# ⚠️ 「期望」写的是**判据标签的开头**，命中判据是输出里出现 `[!!]   <标签>`——
#    只写标签本身不行：通过时那行也会打出来（`[OK]   <标签>`），等于永远算命中。
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    ("① 深色头部不再管状态栏图标（浅色模式下时间/电量/信号全看不见）",
     A + "ui/profile/ProfileScreen.kt",
     "    LightStatusBarIcons()", "    // 注入：不管状态栏了",
     "ProfileScreen.kt 里调了 LightStatusBarIcons()"),
    ("② 离开这一页不还原（子页的白图标压在浅色 AppBar 上）",
     A + "ui/common/StatusBarIcons.kt",
     "controller?.isAppearanceLightStatusBars = !ThemeMode.isDark",
     "controller?.isAppearanceLightStatusBars = false",
     "StatusBarIcons.kt 离开这一页时"),
    ("③ 把「基础设置」那一行换成「消息中心」（重复入口回来了）",
     A + "ui/profile/ProfileScreen.kt",
     'title = "基础设置"', 'title = "消息中心"',
     "「我的」里没有「消息中心」这一行"),
    ("④ 第一层多一行（用户说的「按钮太多」又回来了）",
     A + "ui/profile/ProfileScreen.kt",
     "                    // ---- 基础设置（第二层）：剩下的纯显示偏好 ----",
     '                    RowMotion(9, scroll) { ProfileRow(icon = Icons.Default.Settings, '
     'tint = Color.White, title = "临时加的一行") }',
     "第一层恰好 6 行"),
    ("⑤ 司机那一行（我的账本）被删掉",
     A + "ui/profile/ProfileScreen.kt",
     r're:\n\s*if \(vm\.user\?\.role == "driver" &&[\s\S]*?onClick = onOpenFreight,\n\s*\)\n\s*\}\n',
     "",
     "第一层恰好 6 行"),
    ("⑥ 这个 Tab 又去吃 Scaffold 的顶部 inset（头部上面留一条浅灰带）",
     A + "ui/home/RoleHomeScreen.kt",
     'if (tabs[tabIdx].content == "profile")', "if (false)",
     "RoleHomeScreen.kt：profile 这一 Tab 不吃"),
    ("⑦ 列表不可滚（「退出登录」在小屏上够不着）",
     A + "ui/profile/ProfileScreen.kt",
     ".verticalScroll(listScroll)", "// 注入：不可滚",
     "列表能滚"),
    ("⑧ 「提示」那一格被塞回「基础设置」里（用户明确说不能放在里面）",
     A + "ui/profile/BasicSettingsScreen.kt",
     'title = if (ThemeMode.isDark) "夜间模式" else "白天模式",', 'title = "提示",',
     "「提示」**不在**基础设置里"),
    ("⑨ 基础设置的路由注册被摘（点了没反应）",
     A + "ui/nav/NavGraph.kt",
     "composable(Routes.BASIC_SETTINGS) {", 'composable("settings/basic-old") {',
     "路由三处齐全"),
    ("⑩ 退出登录不再是红的（危险动作和普通设置长一样）",
     A + "ui/profile/ProfileScreen.kt",
     r're:("退出登录",[\s\S]{0,300}?titleColor = )MaterialTheme\.colorScheme\.error',
     r"\1MaterialTheme.colorScheme.onSurface",
     "「退出登录」用 error 色"),
    ("⑪ 退出登录点一下就真退（误碰一次就退出去了）",
     A + "ui/profile/ProfileScreen.kt",
     "onClick = { confirmLogout = true },", "onClick = { vm.logout { } },",
     "那一行**只弹确认框**"),
    ("⑫ 确认框不再复用危险操作弹层（自己拼一个，两边迟早不一样）",
     A + "ui/profile/ProfileScreen.kt",
     "        DangerConfirmDialog(", "        AlertDialog(",
     "确认框复用全 App 那一个危险操作弹层"),
    ("⑬ 果冻改挂回滚动位置（列表滚不动时一点反应都没有 —— 第一版就是这个错）",
     A + "ui/profile/RowMotion.kt",
     "override fun onPostScroll(consumed: Offset, available: Offset, source: NestedScrollSource): Offset {",
     "override fun onPreScroll(consumed: Offset, available: Offset, source: NestedScrollSource): Offset {",
     "果冻挂在**手势**上"),
    ("⑭ 「提示」的状态文字又变成另起一行（用户说不要两排）",
     A + "ui/profile/ProfileScreen.kt",
     '                            title = "提示",',
     '                            title = "提示",\n                            subtitle = { Text("不显示说明") },',
     "「提示」的状态文字在**右边同一行**"),
    ("⑮ 详细说明也被搬到右边（长句挤在标题旁边）",
     A + "ui/profile/ProfileScreen.kt",
     "                            subtitle = {\n                                Hint(",
     "                            trailing = {\n                                Hint(",
     "**详细说明**仍然另起一行"),
    ("⑯ 果冻的嵌套滚动挂进滚动容器**里面**（一个事件都收不到，整列纹丝不动）",
     A + "ui/profile/ProfileScreen.kt",
     "                        .nestedScroll(jelly.connection)\n"
     "                        .verticalScroll(listScroll)\n",
     "                        .verticalScroll(listScroll)\n"
     "                        .nestedScroll(jelly.connection)\n",
     "嵌套滚动写在**滚动容器外面**"),
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
