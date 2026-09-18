"""量真机截图里的导航栏「凹口」：证明它真的画出来了（而不是"看着像"）。

为什么要量：第一版凹口的圆心算错了（放在栏外），切出来的坑又浅又藏在圆钮背后，
**肉眼在截图上根本看不出来**，但拉一条逐像素的剖面就一目了然。
这个脚本就是那把尺子——以后调凹口深浅，用它对比改动前后。

用法：python _tools/notify/_measure_notch.py <截图路径> [中心x]
"""
import sys
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def first_white(px, x, y0, y1):
    """从 y0 往下找第一块纯白 = 导航条上沿（缺口内会晚很多才出现）"""
    for y in range(y0, y1):
        r, g, b = px[x, y]
        if r >= 253 and g >= 253 and b >= 253:
            return y
    return None


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "_agent/nav-dispatcher2.png"
    im = Image.open(path).convert("RGB")
    px = im.load()
    w, _ = im.size
    cx = int(sys.argv[2]) if len(sys.argv) > 2 else w // 2
    density = w / 360  # 1080px 宽的模拟器 = 3x

    base = first_white(px, cx - 300, 2050, 2400)
    print(f"图 {path}  宽 {w}  密度≈{density:.1f}")
    print(f"预期：半宽 31.4dp = {31.4 * density:.0f}px，最深 47dp = {47 * density:.0f}px（相对基准）")
    print(f"基准上沿 y={base}\n")
    print("列偏移   上沿y   下沉")
    prof = {}
    for dx in range(-160, 161, 20):
        y = first_white(px, cx + dx, 2050, 2400)
        drop = None if (y is None or base is None) else y - base
        prof[dx] = drop
        bar = "" if not drop else "#" * max(0, drop // 8)
        print(f"{dx:+5d}   {y}   {drop}  {bar}")

    deepest = max((d for d in prof.values() if d is not None), default=0)
    half = max((abs(dx) for dx, d in prof.items() if d and d > 20), default=0)
    print(f"\n实测：最深 {deepest}px（{deepest / density:.0f}dp），缺口半宽 ≥{half}px")
    # 判据：坑要够深（>25dp）才看得见；第一版只有 18dp 且被圆钮挡住
    ok = deepest / density > 25
    print(("✅ 凹口看得见" if ok else "❌ 凹口太浅/没画出来（第一版就是这个毛病）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
