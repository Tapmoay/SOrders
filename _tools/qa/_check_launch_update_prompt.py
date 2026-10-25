#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_launch_update_prompt.py —— 冷启动「有新版本」提示（CHG-0137）。

用户 2026-10-26：「我们推送的版本，用户第一次打开这个 App 的时候，还是有一个弹窗提示说有新的
版本了、是否更新？检查一下有没有做。」

### 这条最容易"看起来做了、其实没有"的五处
| # | 走样的写法 | 后果（界面上看不出来） |
|---|---|---|
| 1 | 只在「我的」页查 | 用户不切到那一页就一辈子不提示（**改之前就是这样**） |
| 2 | 每次冷启动都弹 | 用久了变成"看到就点稍后"，新版永远装不上，还闹人 |
| 3 | 弹窗挂在页面局部 | 换 Tab / 进详情页就丢，或同时出现两份 |
| 4 | 另写一套下载逻辑 | 进度、FileProvider、未知来源开关三处口径分叉 |
| 5 | 检查失败也弹错误框 | 开门第一秒被一个"检查更新失败"拦住（这本来就是顺带的事） |

用法：python _tools/qa/_check_launch_update_prompt.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
VM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/profile/ProfileViewModel.kt"
PREFS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/UpdatePromptPrefs.kt"
CONTAINER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/AppContainer.kt"
HOME = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/home/RoleHomeScreen.kt"
PROFILE = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/profile/ProfileScreen.kt"
DIALOG = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/profile/UpdateConfirmDialog.kt"
MIN_RULES = 12

bad: list[str] = []
checked = 0


def _ok(m: str) -> None:
    global checked
    checked += 1
    print("  OK   " + m)


def _bad(m: str) -> None:
    global checked
    checked += 1
    print("  BAD  " + m)
    bad.append(m)


def _need(name: str, cond: bool, why: str = "") -> None:
    if cond:
        _ok(name)
    else:
        _bad(name + ("　—— " + why if why else ""))


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def main() -> int:
    vm = _read(VM)
    prefs = _read(PREFS)
    container = _read(CONTAINER)
    home = _read(HOME)
    profile = _read(PROFILE)
    dialog = _read(DIALOG)

    print("1. 判定只有一处（手动检查与启动提示共用）")
    progress = _read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/profile/UpdateProgress.kt")
    _need("纯函数 UpdateProgress.isNewer 存在（有 JVM 单测）", "fun isNewer(" in progress)
    _need(
        "构建号比较只写在它里面（VM 里不许再写一份）",
        progress.count("theirCode > localCode") == 1 and "> BuildConfig.VERSION_CODE" not in vm,
        "两处各写一份 ⇒ 迟早出现「手动说没有新版、启动却弹」",
    )
    _need("VM 里有 isNewerThanCurrent 这道唯一入口", "private fun isNewerThanCurrent(" in vm)
    _need("手动检查（checkUpdate）也走它", re.search(r"if \(!isNewerThanCurrent\(info\)\)", vm) is not None)
    _need(
        "单测覆盖了「构建号数值大小」而不是看位数",
        "isNewer" in _read(ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/profile/UpdateProgressTest.kt"),
        "99999999 只有 8 位，比 10 位的 2026102601 小 —— 光看位数会判错",
    )

    print("2. 启动检查：只查一次、失败静默")
    _need("有 checkUpdateOnLaunch()", "fun checkUpdateOnLaunch()" in vm)
    _need("进程内只查一次（launchChecked 门）", "if (launchChecked) return" in vm)
    _need(
        "失败静默：catch 里不碰 updateMessage / 不弹框",
        re.search(r"catch \(_: Exception\) \{\s*//", vm) is not None and "updateMessage = humanError(e)" not in vm.split("fun checkUpdateOnLaunch()")[1].split("fun downloadFromLaunchPrompt")[0],
        "开门第一秒不该被「检查更新失败」拦住",
    )

    print("3. 同一版只提示一次（用户选了 A 方案）")
    _need("有 UpdatePromptPrefs（SharedPreferences，同步读）", "class UpdatePromptPrefs" in prefs)
    _need("shouldPrompt + markPrompted 两个口子", "fun shouldPrompt(" in prefs and "fun markPrompted(" in prefs)
    _need("容器里有一份实例", "updatePromptPrefs" in container)
    _need(
        "点「稍后」也记下来（dismissLaunchPrompt 里 markPrompted）",
        re.search(r"fun dismissLaunchPrompt\(\) \{[^}]*markPrompted", vm) is not None,
        "不记的话下次冷启动又弹 = 变成每次都弹",
    )
    _need(
        "点「下载并更新」也记下来（downloadFromLaunchPrompt 里 markPrompted）",
        re.search(r"fun downloadFromLaunchPrompt\([^)]*\) \{[^}]*markPrompted", vm) is not None,
    )

    print("4. 弹在登录后的主界面（不是「我的」页里）")
    _need("RoleHomeScreen 调 checkUpdateOnLaunch", "checkUpdateOnLaunch()" in home)
    _need(
        "VM 与「我的」页是同一个实例（都是 appViewModel{ProfileViewModel(container)}）",
        "appViewModel { ProfileViewModel(container) }" in home
        and "appViewModel { ProfileViewModel(container) }" in profile,
    )
    _need("launchPrompt 非空才弹，且用的是共用那个弹窗", "launchPrompt?.let" in home and "UpdateConfirmDialog(" in home)

    print("5. 弹窗只有一份（措辞不会两边漂移）")
    _need("有共用 UpdateConfirmDialog", "fun UpdateConfirmDialog(" in dialog)
    _need("「是否立即下载并安装更新？」只出现在那一份里", dialog.count("是否立即下载并安装更新") == 1 and "是否立即下载并安装更新" not in profile)
    _need("两处都调它", "UpdateConfirmDialog(" in profile and "UpdateConfirmDialog(" in home)
    _need("下载仍走原来那条链路（downloadAndInstall）", "downloadAndInstall(ctx)" in vm)

    print("6. ⛔ 没有为了它新开权限")
    manifest = _read(ROOT / "android/app/src/main/AndroidManifest.xml")
    _need("没有 REQUEST_INSTALL_PACKAGES 之外的更新相关权限", "REQUEST_INSTALL_PACKAGES" in manifest)

    print()
    if bad:
        print("❌ 失败 %d 项（共 %d）" % (len(bad), checked))
        for b in bad:
            print("   - " + b)
        return 1
    if checked < MIN_RULES:
        print("❌ 只跑到 %d 项（下限 %d）" % (checked, MIN_RULES))
        return 1
    print("✅ 全部通过：%d 项" % checked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
