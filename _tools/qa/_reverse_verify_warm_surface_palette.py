# -*- coding: utf-8 -*-
r"""近白家族那条红线，一条条被真的破坏一次 —— 台账 L-19 / CHG-0063（2026-10-09 CHG-0091 换过值）。

一条红线要能被「真的破坏一次」证明它在检查：下面每一条注入都只改一处，然后要求
_tools/qa/_check_warm_surface_palette.py 报红，而且报的是**这一条**（关键词比对）。
跑完按字节还原，再逐字节核对 —— 一个字节都不许留在工作区。

这一组破坏方式的来路都是真实会发生的改法：把 token 改回旧灰蓝、把某一层抹成纯中性灰、
「顺手」把白色都刷成同一个值（分层塌）、把弹层刷成纯白（CHG-0051 的「方案 C」回潮）、
把抽屉那一层拽进暖白家族（用户 m09782 点名不许）、接线换档、暗色与描边被顺手改、
设计基线文档没跟上。

⛔ 锚点一律不写行首缩进以外的松散形状：这里用的是文件里的真实长相（含前导空格）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_warm_surface_palette.py"

COLOR = "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Color.kt"
THEME = "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Theme.kt"
DESIGN = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

NL = chr(10)

CASES: list[tuple[str, str, object, str]] = [
    (
        "近白家族被改回旧的灰蓝：页面底 #F7F6F3 → #F2F3F7",
        COLOR,
        lambda s: s.replace("val BackgroundLight = Color(0xFFF7F6F3)",
                            "val BackgroundLight = Color(0xFFF2F3F7)", 1),
        "Color.kt：BackgroundLight = #F7F6F3",
    ),
    (
        "不偏蓝被抹成纯中性灰：SurfaceVariantLight #F3F2EF → #F0F0F0",
        COLOR,
        lambda s: s.replace("val SurfaceVariantLight = Color(0xFFF1EFEA)",
                            "val SurfaceVariantLight = Color(0xFFF0F0F0)", 1),
        "SurfaceVariantLight 不偏蓝",
    ),
    (
        "分层塌了：SurfaceContainer 被抬到和页面底同色",
        COLOR,
        lambda s: s.replace("val SurfaceContainer = Color(0xFFEFECE6)",
                            "val SurfaceContainer = Color(0xFFF7F6F3)", 1),
        "四层互不相同",
    ),
    (
        "纯白一色到底：弹层那一层被刷成纯白（SurfaceContainerHigh → #FFFFFF，四层就不再互不相同）",
        COLOR,
        lambda s: s.replace("val SurfaceContainerHigh = Color(0xFFE4E0D9)",
                            "val SurfaceContainerHigh = Color(0xFFFFFFFF)", 1),
        "四层互不相同",
    ),
    (
        "白卡被拽到页面底同色：SurfaceLight #FFFFFF → #FBFBFA",
        COLOR,
        lambda s: s.replace("val SurfaceLight = Color(0xFFFFFFFF)",
                            "val SurfaceLight = Color(0xFFF7F6F3)", 1),
        "SurfaceLight 仍是纯白",
    ),
    (
        "抽屉那一层被卷进近白：SheetSurface #F0F0F0 → #FBFBFA（用户点名不许）",
        COLOR,
        lambda s: s.replace("val SheetSurface = Color(0xFFF0F0F0)",
                            "val SheetSurface = Color(0xFFF7F6F3)", 1),
        "SheetSurface 仍是",
    ),
    (
        "抽屉面接错档：Theme 的 surfaceContainerLow 不再接 SheetSurface",
        THEME,
        lambda s: s.replace("    surfaceContainerLow = SheetSurface,",
                            "    surfaceContainerLow = SurfaceContainerLow,", 1),
        "surfaceContainerLow 仍接给 SheetSurface",
    ),
    (
        "页面底接线被换：Theme 的 background 改接 SurfaceVariantLight",
        THEME,
        lambda s: s.replace("    background = BackgroundLight,",
                            "    background = SurfaceVariantLight,", 1),
        "background = BackgroundLight",
    ),
    (
        "弹层接线被换成暗色那一档（亮色下弹层跟着暗色走）",
        THEME,
        lambda s: s.replace("    surfaceContainerHigh = SurfaceContainerHigh,",
                            "    surfaceContainerHigh = SurfaceContainerHighDark,", 1),
        "surfaceContainerHigh = SurfaceContainerHigh",
    ),
    (
        "暗色被顺手改了：BackgroundDark #0E1014 → #0E1015",
        COLOR,
        lambda s: s.replace("val BackgroundDark = Color(0xFF0E1014)",
                            "val BackgroundDark = Color(0xFF0E1015)", 1),
        "Color.kt：BackgroundDark = #0E1014",
    ),
    (
        "设计基线文档没跟上：06_DESIGN_SYSTEM.md 里还写旧值",
        DESIGN,
        lambda s: s.replace("BackgroundLight=#F7F6F3", "BackgroundLight=#F2F3F7", 1),
        "设计基线里页面底写的是新值",
    ),
    # ⚠️ 原来这里有一条「描边被顺手改：OutlineLight #7A7F8C → #F0F0F0」的注入。
    #    CHG-0101 把 OutlineLight / OutlineVariantLight 从这张表的 `KEEP` 里删掉了
    #    （旧的 #7A7F8C / #CFD4E0 是冷灰，与暖砂白同屏发脏），改由
    #    `_tools/qa/_check_low_sat_palette.py` 的 `IDENTITY` 正面钉住新值 ——
    #    所以这条注入在本脚本里恒为绿（本 checker 已经不认这件事了）。
    #    ⛔ 不是"抓不住就删"：那条红线现在由
    #    `_tools/qa/_reverse_verify_low_sat_palette.py` 覆盖（它逐 token 注入、必须报红）。
]


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    fails: list[str] = []

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", NL)
        mutated = mutate(plain)
        if mutated == plain:
            print(f"  [SKIP] {label}：注入没生效（锚点变了，请更新本脚本）")
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            continue
        text = mutated.replace(NL, "\r\n") if crlf else mutated
        try:
            path.write_bytes(text.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        if code != 0 and (not expect or expect in out):
            print(f"  [OK]   {label} → 报红")
        else:
            print(f"  [MISS] {label}（退出码 {code}，期望关键词「{expect}」）")
            fails.append(f"{label}（退出码 {code}，期望关键词「{expect}」）")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    for rel in dirty:
        (ROOT / rel).write_bytes(originals[rel])
        print(f"  [!!]   {rel} 没还原干净，已强制写回")
        fails.append(f"{rel} 没还原干净")

    print("=" * 60)
    if fails:
        print(f"❌ 反向验证不通过：{len(fails)} 条")
        for f in fails:
            print(f"   - {f}")
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())