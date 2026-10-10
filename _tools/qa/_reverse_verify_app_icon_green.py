#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反向验证：`_tools/qa/_check_app_icon_green.py` 里那些红线**真的在检查**吗？

机器判据最怕的不是写错，是**写得太松**：把现值在判据里又抄一遍（于是换色时判据和资源
一起过期，等于没判据）、只判"文件里有这几个字"、只判一处而放过另一处 —— 三种都
**不报错、照样全绿**，而桌面上那枚图标还是旧的蓝色。

这个脚本用「把资源改坏 → 判据必须变红」逐条证明：

  1. **判据得跟着 Color.kt 走**：把 `Color.kt` 的 `PrimaryContainer` 改掉，判据必须红
     （如果它把 `#DBE8E1` 抄死在自己里面，这一条就抓不出来）；
  2. **四处字面量互相钉住**：背景层 / colors.xml 两项 / 前景层，任意一处单独改回旧值都必须红；
  3. **启动画面那一层是活的**：删掉 `windowSplashScreenBackground`、把 v31 的父样式
     改成不继承 `.Base`、覆盖基础项 → 都必须红；
  4. **形状与清单**：改 monochrome 的 pathData、把清单的 icon 换成状态栏图标 → 必须红。

本脚本**只读写工作区里的文件**，不编译、不跑 UI、不连设备；每条注入跑完立刻按字节还原。

用法：
    python _tools/qa/_reverse_verify_app_icon_green.py
"""
from __future__ import annotations

import hashlib
import io
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_app_icon_green.py"

COLOR = "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Color.kt"
BG = "android/app/src/main/res/drawable/ic_launcher_background.xml"
FG = "android/app/src/main/res/drawable/ic_launcher_foreground.xml"
MONO = "android/app/src/main/res/drawable/ic_launcher_monochrome.xml"
STAT = "android/app/src/main/res/drawable/ic_stat_order.xml"
COLORS = "android/app/src/main/res/values/colors.xml"
THEMES = "android/app/src/main/res/values/themes.xml"
V31 = "android/app/src/main/res/values-v31/themes.xml"
MANIFEST = "android/app/src/main/AndroidManifest.xml"

CASES: list[tuple[str, str, str, int, str]] = [
    # (文件, old, new, 第几处, 说明)
    (COLOR, "val PrimaryContainer = Color(0xFFDBE8E1)",
     "val PrimaryContainer = Color(0xFFD9E8FF)", 0, "① Color.kt 的底色一改，判据得跟着红（证明它读的是 token 不是抄死的值）"),
    (BG, 'android:fillColor="#DBE8E1"', 'android:fillColor="#D9E8FF"', 0, "② 图标背景层改回旧蓝"),
    (FG, 'android:fillColor="#0E3021"', 'android:fillColor="#0A3168"', 0, "③ 货车改回旧藏蓝"),
    (COLORS, '<color name="ic_launcher_background">#DBE8E1</color>',
     '<color name="ic_launcher_background">#FFB020</color>', 0, "④ 兜底色改回橙金"),
    (COLORS, '<color name="splash_background">#DBE8E1</color>',
     '<color name="splash_background">#123456</color>', 0, "⑤ 启动画面底色与图标底不一致"),
    (V31, '<item name="android:windowSplashScreenBackground">@color/splash_background</item>',
     "", 0, "⑥ 启动画面底色整条删掉"),
    (V31, '<style name="Theme.SOrders" parent="Theme.SOrders.Base">',
     '<style name="Theme.SOrders" parent="android:Theme.Material.Light.NoActionBar">', 0,
     "⑦ v31 不再继承基础样式（基础项就被抄成两份了）"),
    (V31, '<item name="android:windowSplashScreenAnimatedIcon">@mipmap/ic_launcher</item>',
     '<item name="android:windowSplashScreenAnimatedIcon">@drawable/ic_stat_order</item>', 0,
     "⑧ 启动画面图标被换成通知栏那枚单色剪影"),
    (THEMES, '<style name="Theme.SOrders.Base" parent="android:Theme.Material.Light.NoActionBar">',
     '<style name="Theme.SOrders.BaseX" parent="android:Theme.Material.Light.NoActionBar">', 0,
     "⑨ 基础样式被改名（两层继承链断掉）"),
    (MONO, "M20,8 h-3 V4 H3 c-1.1,0", "M20,8 h-3 V5 H3 c-1.1,0", 0,
     "⑩ 主题图标的形状与前景层不再逐字相同"),
    (MANIFEST, 'android:icon="@mipmap/ic_launcher"', 'android:icon="@drawable/ic_stat_order"', 0,
     "⑪ 清单的 icon 被换成状态栏图标"),
    (STAT, 'android:width="24dp"', 'android:width="24dp" tools:ignore="@mipmap/ic_launcher"', 0,
     "⑫ 通知栏图标里混进 @mipmap 引用"),
]


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sub(old: str, new: str, idx: int = 0):
    """把第 `idx` 处（0 起）`old` 换成 `new`；命中数必须恰好 1 次。

    ⚠️ 为什么要 `idx`：`str.replace(old, new, 1)` 认的是第一处**子串**，
    而 `old` 经常被更长的行包含 —— 于是"改第 3 处"其实改了第 1 处，判据照样绿，
    注入就成了自欺（本项目踩过）。
    """
    def run(text: str) -> str:
        n = text.count(old)
        if n == 0:
            raise AssertionError("注入点不在了：" + repr(old[:80]))
        pos = -1
        for _ in range(idx + 1):
            pos = text.find(old, pos + 1)
        return text[:pos] + new + text[pos + len(old):]
    return run


def main() -> int:
    if not CHECK.exists():
        print("⛔ 缺判据脚本：%s" % CHECK.relative_to(ROOT))
        return 2

    # 先确认判据本身是绿的，否则"注入后变红"什么也证明不了
    base = subprocess.run([sys.executable, "-X", "utf8", str(CHECK)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if base.returncode != 0:
        print("⛔ 判据现在本来就是红的，先修它再跑反向验证：")
        print((base.stdout or "")[-1500:])
        return 2
    print("✅ 判据当前全绿（基线）\n")

    bad: list[str] = []
    for path_s, old, new, idx, what in CASES:
        p = ROOT / path_s
        before = p.read_bytes()
        h0 = hashlib.sha256(before).hexdigest()
        text = io.open(p, encoding="utf-8").read()
        p.write_text(sub(old, new, idx)(text), encoding="utf-8", newline="")
        try:
            r = subprocess.run([sys.executable, "-X", "utf8", str(CHECK)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            red = r.returncode != 0
        finally:
            p.write_bytes(before)
        h1 = digest(p)
        restored = h1 == h0
        mark = "✅" if (red and restored) else "❌"
        print(f"  {mark} {what}")
        if not red:
            bad.append(f"{what} —— 注入后判据仍然全绿（这条判据是死的）")
        if not restored:
            bad.append(f"{what} —— 还原后 sha256 不一致（{path_s}）")

    print(f"\n  {'✅' if not bad else '❌'} {len(CASES) - len(bad)}/{len(CASES)} 条注入都让判据变红，且文件逐字节还原")
    if bad:
        print("\n  未通过：")
        for b in bad:
            print("    - " + b)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
