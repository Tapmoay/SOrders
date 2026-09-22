"""从截图里**量像素**（真机验收用）。

## 为什么需要它
2026-09-22 这一轮判的就是"这个颜色对不对"：「底部抽屉弹出来那个颜色都是**灰蓝灰蓝**的，
不要啊，改成底部灰（色）没关系，卡片一定要是**白色**的」。这类结论**肉眼不能下**：
- 屏幕上"看着像灰"的一块，可能是 #EDEFF4（B 比 R 高 7，偏蓝），也可能是 #F0F0F0（纯中性）；
- 两张截图并排看会受**显示器与压缩**影响，而差 3~4 个色阶就已经是"偏蓝"了。

所以：**量**。坐标从 `_emu_ui.py dump` 拿（按文字定位，别写死），
量完把数字写进验收记录（比"我看着差不多"可复核）。

## 用法
    python _tools/qa/_px_probe.py <png> 540,1880 900,1474        # 量若干点
    python _tools/qa/_px_probe.py <png> --col 540 1200 2300      # 沿一列扫，只打颜色变化处
    python _tools/qa/_px_probe.py <png> --row 1880 0 1080        # 沿一行扫
`--col/--row` 用来**找边界**（抽屉从哪一行开始、卡片到哪一行结束），
拿到边界再回头量点，比盲猜坐标稳。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    print("需要 Pillow：pip install pillow")
    raise SystemExit(2)


def hexs(px: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*px[:3])


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"找不到 {path}")
        return 2
    im = Image.open(path).convert("RGB")
    print(f"{path.name}  {im.width}x{im.height}")

    a = sys.argv[2:]
    if a[0] in ("--col", "--row"):
        fixed = int(a[1])
        lo, hi = int(a[2]), int(a[3])
        prev = None
        runs: list[tuple[int, str]] = []
        for v in range(lo, hi):
            px = im.getpixel((fixed, v)) if a[0] == "--col" else im.getpixel((v, fixed))
            h = hexs(px)
            if h != prev:
                runs.append((v, h))
                prev = h
        # 只打**持续 ≥6 像素**的段（抗压缩噪点/抗锯齿）
        keep = [(v, h) for i, (v, h) in enumerate(runs)
                if (runs[i + 1][0] if i + 1 < len(runs) else hi) - v >= 6]
        for v, h in keep:
            print(f"  {a[0][2:]}={fixed}  从 {v:>5} 起  {h}")
        return 0

    for pt in a:
        x, y = (int(v) for v in pt.split(","))
        px = im.getpixel((x, y))
        r, g, b = px[:3]
        note = "中性" if b == r else ("偏蓝" if b > r else "偏暖")
        print(f"  ({x:>5},{y:>5})  {hexs(px)}   R={r} G={g} B={b}  {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
